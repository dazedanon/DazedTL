"""Which HTTP tries of a paid Live request could have been billed.

SDK clients retry inside one recorded request, so its final error alone cannot
show that nothing was billed: a lost response can precede a refused
connection. Each try is observed at the transport instead.
"""

import importlib
import threading
from urllib.parse import urlsplit

from dazedtl.settings.providers import own_server

# Statuses where the provider refused the request itself, so nothing was
# processed and no Batch was created. Timeouts, conflicts and server errors can
# follow processing.
REFUSED = frozenset({400, 401, 402, 403, 404, 405, 413, 415, 422, 429})
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
    """How each try of the current request ended, oldest first."""
    return list(getattr(_local, "tries", None) or [])


def unbilled(tries):
    """Only observed tries that never connected, were refused or failed by
    the model server itself prove that sending the request again cannot be
    charged twice."""
    return bool(tries) and all(outcome != "maybe" for outcome in tries)


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
        code = getattr(error, "status_code", None)
        if status is None and type(code) is int:
            status = code
        url = url or _request_url(error)
        error = error.__cause__
    return status, "maybe" if status is None else answer(status, url)


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
        tries = getattr(_local, "tries", None)
        try:
            response = native(self, request)
        except unreached:
            if tries is not None:
                tries.append("unreached")
            raise
        except BaseException:
            if tries is not None:
                tries.append("maybe")
            raise
        if tries is not None:
            tries.append(answer(response.status_code, str(request.url)))
        return response

    return handle_request
