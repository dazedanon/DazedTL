"""Visit MV/MZ menu choices once while preserving the native two-pass writer."""

from functools import wraps
import threading


def configure(module, enabled):
    if module is None:
        return
    previous = getattr(module, "_dazedtl_choice_pass", None)
    if not enabled:
        if previous:
            module.searchCodes, module._choice_current = previous
            del module._dazedtl_choice_pass
        return
    if previous:
        return
    native_search, native_current = module.searchCodes, module._choice_current
    local = threading.local()

    @wraps(native_search)
    def search(page, pbar, jobList, filename):
        previous = getattr(local, "second_pass", False)
        local.second_pass = bool(jobList)
        try:
            return native_search(page, pbar, jobList, filename)
        finally:
            local.second_pass = previous

    @wraps(native_current)
    def current(command, index):
        # Choices are translated directly on pass one. In collect/estimate
        # they still contain Japanese on pass two; returning no eligible value
        # avoids a second request without writing placeholder translations.
        # The same skip prevents an extra consume/retry after a rejected chunk.
        return (
            ""
            if getattr(local, "second_pass", False)
            else native_current(command, index)
        )

    module._dazedtl_choice_pass = (native_search, native_current)
    module.searchCodes, module._choice_current = search, current
