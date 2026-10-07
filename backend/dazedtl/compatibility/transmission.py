"""Which HTTP tries of a paid Live request could have reached the provider.

SDK clients retry inside one recorded request, so its final error alone cannot
show that nothing was processed: a lost response can precede a refused
connection. Each try is observed at the transport instead.
"""

import importlib
import threading

# Statuses where the provider refused the request itself, so nothing was
# processed. Timeouts, conflicts and server errors can follow processing.
REFUSED = frozenset({400, 401, 402, 403, 404, 405, 413, 415, 422, 429})

_local = threading.local()
_installed = False


def begin():
    """Observe the current thread's tries for a newly recorded request."""
    _local.tries = []


def end():
    _local.tries = None


def observed():
    """How each try of the current request ended, oldest first."""
    return list(getattr(_local, "tries", None) or [])


def never_sent(tries):
    """Only observed tries that never connected or were refused prove nothing
    reached the provider."""
    return bool(tries) and all(outcome != "maybe" for outcome in tries)


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
            tries.append("refused" if response.status_code in REFUSED else "maybe")
        return response

    return handle_request
