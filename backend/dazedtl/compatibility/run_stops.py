"""The run-stop rule of a Guided run frozen with settings/preferences
RUN_STOPS: a provider error every later request would get too stops the run
with one message, instead of failing one call, page or file at a time."""

import json
import re
from functools import partial
from pathlib import Path

from dazedtl import storage, system
from dazedtl.settings.preferences import RUN_STOPS

from .provider_responses import error_evidence, provider_error

# Statuses a provider answers the same request with again: bad request,
# unauthorized, forbidden, not found and unprocessable. Timeouts, conflicts,
# rate limits and server errors may pass on another try.
DETERMINISTIC = frozenset({400, 401, 403, 404, 422})
# The same deterministic error on this many requests in a row stops the run.
REPEATS = 3
LAYER = "run-stops"
# A prompt a provider's safety system flagged gets the same error as every
# other flagged prompt, but the run's other text need not be flagged: it
# fails its call without counting toward a stop.
FLAGGED = re.compile(
    r"flagged|content[ _-]?(?:filter|policy|management)|usage polic", re.IGNORECASE
)


def stop_message(detail):
    """The one message a run stops with after *detail*'s error repeated."""
    return (
        f"The provider rejected {REPEATS} requests in a row with the same error, "
        f"so the run stopped without sending the rest: {provider_error(detail)} "
        "Check the model and the connection in Settings, then start the run "
        "again. Rejected requests are not billed."
    )


def rejection_message(detail):
    """The message a request the provider rejected fails with."""
    return f"The provider rejected the request: {provider_error(detail)}"


class ProviderFailure(Exception):
    """A Live request the engine gave up on, read as the provider's own error
    (failed) instead of the engine's wrapped text."""


def failed(translation, native, *args, **kwargs):
    """A Live call in every Guided run, frozen with the rule or before it:
    once the engine's tries end, an error the provider answered fails it with
    the provider's own status and message, a rejection as one, and an
    unreachable provider says so; the requests and their retries stay as the
    run sends them, and a run's stop or rejection passes as it is. A Batch
    phase sends nothing Live and passes as it is."""
    if translation.get_batch_phase():
        return native(*args, **kwargs)
    try:
        return native(*args, **kwargs)
    except translation.RunStoppingError, translation.RequestRejectedError:
        raise
    except Exception as error:
        secret = getattr(getattr(translation, "openai", None), "api_key", "") or ""
        detail = error_evidence(error, secret)
        if detail["status"] in DETERMINISTIC:
            raise ProviderFailure(rejection_message(detail)) from error
        if detail["status"] is not None:
            raise ProviderFailure(
                f"The provider failed the request: {provider_error(detail)}"
            ) from error
        unreachable = _unreachable(error)
        if unreachable is None:
            raise
        raise ProviderFailure(
            f"The provider could not be reached: {unreachable}"
        ) from error


def _unreachable(error):
    """The SDK's own words for a provider it could not reach, such as
    "Connection error." or "Request timed out.", from *error*'s chain."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if any(kind.__name__ == "APIConnectionError" for kind in type(error).__mro__):
            return str(error).strip() or "Connection error."
        error = error.__cause__ or error.__context__
    return None


class Record:
    """The run's streak of one deterministic error and the stop it ended in,
    shared by the run's workers in its folder. The run's coordinator starts
    each attempt with none."""

    def __init__(self, root):
        self.path = Path(root) / "log" / "run_stop.json"
        self.lock = self.path.with_name("run_stop.lock")

    def read(self):
        if not self.path.is_file():
            return {}
        try:
            record = json.loads(system.read_text(self.path))
        except FileNotFoundError, ValueError:
            # Gone meanwhile, or damaged: no streak and no stop to honour.
            return {}
        return record if isinstance(record, dict) else {}

    def stopped(self):
        """The message the run stopped with, or None."""
        return self.read().get("stopped")

    def reject(self, detail):
        """Counts a request *detail*'s deterministic error rejected; returns
        the stop message once the same error rejected REPEATS in a row."""
        code = detail.get("code")
        error = [
            detail["status"],
            None if code is None else str(code),
            detail["message"],
        ]
        with storage.exclusive(self.lock):
            record = self.read()
            if record.get("stopped"):
                return record["stopped"]
            count = record["count"] + 1 if record.get("error") == error else 1
            stopped = stop_message(detail) if count >= REPEATS else None
            system.write_json(
                self.path, {"error": error, "count": count, "stopped": stopped}
            )
            return stopped

    def stop(self, message):
        """Records that the run stopped with *message*, unless it already had."""
        with storage.exclusive(self.lock):
            if not self.read().get("stopped"):
                system.write_json(self.path, {"stopped": message})

    def clear(self):
        """A request succeeded, which ends a streak but never a stop."""
        if not self.path.is_file():
            return
        with storage.exclusive(self.lock):
            if not self.read().get("stopped"):
                system.unlink(self.path, missing_ok=True)

    def reset(self):
        system.unlink(self.path, missing_ok=True)


def guarded(translation, record, native, *args, **kwargs):
    """A Live request under the rule: none is sent once the run stopped, and a
    deterministic error fails the call without a retry or stops the run."""
    stopped = record.stopped()
    if stopped is not None:
        raise translation.RunStoppingError(stopped)
    try:
        response = native(*args, **kwargs)
    except translation.RunStoppingError as error:
        record.stop(str(error))
        raise
    except Exception as error:
        secret = getattr(getattr(translation, "openai", None), "api_key", "") or ""
        detail = error_evidence(error, secret)
        if detail["status"] not in DETERMINISTIC:
            raise
        rejected = translation.RequestRejectedError(rejection_message(detail))
        if FLAGGED.search(f"{detail.get('code') or ''} {detail['message']}"):
            raise rejected from error
        stop = record.reject(detail)
        if stop is not None:
            raise translation.RunStoppingError(stop) from error
        raise rejected from error
    record.clear()
    return response


def configure(translation, policy, root, *, coordinator=False):
    """Follows the rule in a run frozen with it; the coordinator, which
    starts each attempt before its workers, clears the last attempt's
    record. Every run's failed calls read as their provider's error (failed)."""
    translation.RUN_STOPS = bool(policy and policy.get("runStops") == RUN_STOPS)
    translation.translateAI.layer(LAYER, partial(failed, translation))
    translation.translateText.remove(LAYER)
    if not translation.RUN_STOPS:
        return
    record = Record(root)
    if coordinator:
        record.reset()
    # Outermost, so it also sees the effort refusal (request_parameters).
    translation.translateText.layer(LAYER, partial(guarded, translation, record))
