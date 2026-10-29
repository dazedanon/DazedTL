"""Which HTTP tries of a paid Live request could have been billed.

SDK clients retry inside one recorded request, so its final error alone cannot
show that nothing was billed: a lost response can precede a refused
connection. Each try is observed at the transport instead.
"""

import importlib
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

from dazedtl.settings.providers import own_server

# Statuses where the provider refused the request itself, so nothing was
# processed and no Batch was created. Timeouts, conflicts and server errors can
# follow processing.
REFUSED = frozenset({400, 401, 402, 403, 404, 405, 413, 415, 422, 429})
# The one refusal another try may pass: the provider's rate limit.
RATE_LIMITED = 429
# A model server's own server errors and overload answers, which end a Live
# request unanswered and unbilled. Anthropic: "Failed requests aren't charged"
# (https://support.claude.com/en/articles/8977456), 500 api_error and 529
# overloaded_error (https://platform.claude.com/docs/en/api/errors). Gemini:
# "If your request fails with a 400 or 500 error, you won't be charged"
# (https://ai.google.dev/gemini-api/docs/billing). OpenRouter: "An attempt
# that errors is not charged for its model tokens"
# (https://openrouter.ai/pricing). OpenAI, DeepSeek, Kimi and Mistral document
# no charge for an error either way, and take the same rule. A gateway's
# answer is never one: a 502, 504 or 524 timeout, or a client's own, can cut
# off a request the model finished and billed
# (https://platform.kimi.ai/docs/guide/troubleshooting), and any status from
# another host, such as a Custom server behind a proxy, may be a gateway's.
# A Batch create is not a Live request: its server error may follow a created
# Batch, so a create reads as never made only when "refused".
FAILED = frozenset({500, 503, 529})
# Anthropic streams an overload after its HTTP 200 as an `overloaded_error`
# event, "which would normally correspond to an HTTP 529 in a non-streaming
# context" (https://platform.claude.com/docs/en/build-with-claude/streaming),
# and its SDK raises it with the stream's 200. It reads as that 529, a failed
# request Anthropic does not charge for (the support article above).
STREAMED = {"overloaded_error": 529}

_local = threading.local()
_installed = False


def answer(status, url):
    """How an HTTP answer with *status* from *url* ends a paid Live try:
    "refused" outright, "failed" by the model server's own error, both
    unbilled, or "maybe" processed and billed."""
    if status in REFUSED:
        return "refused"
    if status in FAILED and own_server(url):
        return "failed"
    return "maybe"


def begin():
    """Observe the current thread's tries for a newly recorded request."""
    _local.tries = []


def end():
    _local.tries = None


def observed():
    """Each try of the current request, oldest first, as (how it ended, its
    HTTP status or None) pairs."""
    return list(getattr(_local, "tries", None) or [])


def unbilled(tries):
    """Only observed tries that never connected, were refused or failed by
    the model server itself prove that sending the request again cannot be
    charged twice."""
    return bool(tries) and all(outcome != "maybe" for outcome, _status in tries)


@contextmanager
def watching():
    """Every try the current thread sends while the block runs, oldest first,
    as (how it ended, its HTTP status or None) pairs, whichever request
    records it: a call can send several, such as a JSON-mode request after a
    refused one or a clarification after a refusal."""
    watched = []
    _local.watchers = (*getattr(_local, "watchers", ()), watched)
    try:
        yield watched
    finally:
        _local.watchers = tuple(
            other for other in _local.watchers if other is not watched
        )


def settled(tries, error):
    """A failed request's observed *tries*, with its last one read from its
    final *error* when that try answered HTTP 200 and the provider then
    streamed its own failure (STREAMED); the transport sees only the 200."""
    tries = list(tries)
    seen = set()
    # Only the error raised with that 200 speaks for it, not one an earlier
    # try raised under it.
    while tries and tries[-1][1] == 200 and error is not None:
        if id(error) in seen:
            break
        seen.add(id(error))
        status = _status(error)
        if getattr(error, "status_code", None) == 200 and status != 200:
            tries[-1] = (answer(status, _request_url(error)), status)
            break
        error = error.__cause__
    return tries


def ended(tries, error):
    """How a Live request that failed with *error* ended, as (its HTTP status
    or None, how it ended), the one reading of every route that records it:
    from its observed *tries* (watching, observed) when there are any, since
    a final error alone cannot show that an earlier try was unbilled, nor
    that a connection was never made; any try that may have been billed
    leaves the request "maybe", and otherwise the last says how it ended.
    Without tries, from *error* alone (answered)."""
    tries = settled(tries, error)
    if not tries:
        return answered(error)
    outcome, status = tries[-1]
    return status, outcome if unbilled(tries) else "maybe"


def resendable(tries, error):
    """Whether a Live request that failed with *error* after *tries*
    (watching) may be sent again: no try may have been processed and billed
    (unbilled), and the last could pass on another, since it never
    connected, met a rate limit or failed by the model server itself. Any
    other refusal comes back alike. A connection lost after the request was
    sent may follow processing: only a connection never made proves nothing
    reached the provider."""
    tries = settled(tries, error)
    if not unbilled(tries):
        return False
    outcome, status = tries[-1]
    return outcome in {"unreached", "failed"} or status == RATE_LIMITED


def answered(error):
    """A request's final *error* read by the same rule, for routes whose
    tries are not observed and for Batch creates: its HTTP status, or None,
    and how it ended (`answer`), from its status and the request's address
    where the error carries its HTTP response, through wrapping errors raised
    from it. An error without a status, such as a timeout or a lost
    connection, may follow processing."""
    status, url, seen = None, None, set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        code = _status(error)
        if status is None and code is not None:
            status = code
        url = url or _request_url(error)
        error = error.__cause__
    return status, "maybe" if status is None else answer(status, url)


def _status(error):
    """*error*'s own HTTP status, or None; an error event streamed after a
    200 reads as the status it stands for (STREAMED)."""
    code = getattr(error, "status_code", None)
    if type(code) is not int:
        return None
    body = getattr(error, "body", None)
    if code == 200 and isinstance(body, dict) and body.get("type") == "error":
        kind = body.get("error")
        return STREAMED.get(
            str(kind.get("type")) if isinstance(kind, dict) else "", code
        )
    return code


def _request_url(error):
    # OpenAI's and Anthropic's errors keep the response; Mistral's raw_response.
    for name in ("response", "raw_response"):
        response = getattr(error, name, None)
        if response is None:
            continue
        try:
            # An httpx response built without its request raises RuntimeError.
            url = str(response.request.url)
            if urlsplit(url).hostname:
                return url
        except AttributeError, RuntimeError, ValueError:
            continue
    return None


def install():
    """Wrap the sync transport of each HTTP library the SDK clients use, once.

    Current OpenAI and Anthropic SDKs send through httpx2; others use httpx.
    """
    global _installed
    if _installed:
        return
    _installed = True
    for name in ("httpx", "httpx2"):
        try:
            library = importlib.import_module(name)
        except ImportError:
            continue
        library.HTTPTransport.handle_request = _observing(library)


def _observing(library):
    native = library.HTTPTransport.handle_request
    unreached = (library.ConnectError, library.ConnectTimeout)

    def handle_request(self, request):
        try:
            response = native(self, request)
        except unreached:
            _observe("unreached", None)
            raise
        except BaseException:
            _observe("maybe", None)
            raise
        _observe(answer(response.status_code, str(request.url)), response.status_code)
        return response

    return handle_request


def _observe(outcome, status):
    tries = getattr(_local, "tries", None)
    if tries is not None:
        tries.append((outcome, status))
    for watched in getattr(_local, "watchers", ()):
        watched.append((outcome, status))
