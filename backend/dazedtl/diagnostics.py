"""Bounded local failure records containing metadata and code locations, never payloads."""

import json
import logging
import os
import sys
import sysconfig
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dazedtl.watchdog import Watchdog

HANGS = frozenset(
    {"backend.stalled", "backend.resumed", "operation.stalled", "operation.resumed"}
)
# The backend names its diagnostics folder here for the workers it starts.
FOLDER = "DAZEDTL_DIAGNOSTICS"
# An action this long without progress records where it waits.
PROGRESS_STALL_SECONDS = 60


class CodeLocations:
    """Code paths relative to the runtime, app and engine; anything else is external."""

    def __init__(self, root, legacy):
        self.roots = (
            ("python", Path(sys.prefix)),
            # A virtual environment's prefix holds packages but not the stdlib.
            ("python", Path(sysconfig.get_path("stdlib"))),
            ("app", Path(root)),
            ("engine", Path(legacy)),
        )

    def location(self, filename):
        try:
            path = Path(filename).resolve()
        except OSError, ValueError:
            return "external"
        for label, root in self.roots:
            if path.is_relative_to(root):
                return (label + "/" + path.relative_to(root).as_posix())[:180]
        return "external"

    def stack(self, frame, limit=8):
        """Where a thread is, innermost last.

        Each run of runtime frames keeps only the call the code made into it
        and where it waits, so the app's own callers fit within the limit.
        """
        if frame is None:
            return []
        frames = [
            {
                "file": self.location(current.f_code.co_filename),
                "line": line,
                "function": current.f_code.co_name[:80],
            }
            for current, line in traceback.walk_stack(frame)
        ][::-1]
        runtime = [item["file"].startswith("python/") for item in frames]
        return [
            item
            for index, item in enumerate(frames)
            if not (
                runtime[index]
                and 0 < index < len(frames) - 1
                and runtime[index - 1]
                and runtime[index + 1]
            )
        ][-limit:]


class Diagnostics:
    def __init__(self, directory, root, legacy, *, rotate=True):
        """A worker passes ``rotate=False``: it appends to the backend's log
        and leaves rotating it to the backend, which keeps the file open."""
        self.code = CodeLocations(root, legacy)
        self.path = None
        # An unregistered logger keeps each instance's handlers separate.
        self.logger = logging.Logger("dazedtl.diagnostics", logging.INFO)  # noqa: LOG001
        self.logger.propagate = False
        try:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not rotate:
                self.path = directory / "backend-failures.jsonl"
                return
            handler = RotatingFileHandler(
                directory / "backend-failures.jsonl",
                maxBytes=65536,
                backupCount=2,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
        except OSError:
            self.logger.addHandler(logging.NullHandler())

    def _record(self, event, **fields):
        # Callers pass fixed event names and metadata, never exception messages,
        # request/response bodies, environment variables, or worker log text.
        try:
            line = json.dumps(
                {"time": datetime.now(UTC).isoformat(), "event": event, **fields}
            )
            if self.path:
                # Opened only for each record, so the backend can still rotate.
                with self.path.open("a", encoding="utf-8", newline="\n") as log:
                    log.write(line + "\n")
            else:
                self.logger.info(line)
        except OSError, ValueError:
            pass  # Logging must not prevent returning the original error.

    def failure(self, error, operation="startup", request_id=None):
        causes = []
        seen = set()
        current = error
        while current is not None and id(current) not in seen and len(causes) < 3:
            seen.add(id(current))
            frames = [
                {
                    "file": self.code.location(frame.f_code.co_filename),
                    "line": line,
                    "function": frame.f_code.co_name[:80],
                }
                for frame, line in traceback.walk_tb(current.__traceback__)
            ][-8:]
            causes.append({"type": type(current).__name__[:80], "frames": frames})
            current = current.__cause__ or current.__context__
        fields = {"operation": operation, "causes": causes}
        if type(request_id) is int and 0 <= request_id <= 2**53 - 1:
            fields["requestId"] = request_id
        if isinstance(error, OSError) and isinstance(error.errno, int):
            fields["errno"] = error.errno
        self._record("backend.error", **fields)

    def stack(self, frame):
        return self.code.stack(frame)

    def hang(
        self, event, seconds, stack=(), *, operation=None, request_id=None, action=None
    ):
        """Work that went without progress ("stalled", with where it was
        waiting) or that moved on again ("resumed", after how long)."""
        if event not in HANGS:
            raise ValueError("Unknown hang record.")
        fields = {}
        if isinstance(operation, str):
            fields["operation"] = operation[:80]
        if type(request_id) is int and 0 <= request_id <= 2**53 - 1:
            fields["requestId"] = request_id
        if isinstance(action, str):
            fields["action"] = action[:80]
        if isinstance(seconds, int | float) and seconds >= 0:
            fields["seconds"] = round(seconds)
        # A worker's stack arrives as data; keep only the location fields.
        frames = [
            {
                "file": frame["file"][:180],
                "line": frame["line"],
                "function": frame["function"][:80],
            }
            for frame in stack
            if isinstance(frame, dict)
            and isinstance(frame.get("file"), str)
            and type(frame.get("line")) is int
            and isinstance(frame.get("function"), str)
        ][-8:]
        if frames:
            fields["causes"] = [{"type": "Stack", "frames": frames}]
        self._record(event, **fields)

    def close(self):
        for handler in self.logger.handlers:
            handler.close()


def watch_action(action):
    """Watches a worker's action from the calling thread, recording in the
    app's diagnostics when it goes quiet and when it moves on again.

    Returns the action's progress callback; outside the app it does nothing.
    """
    directory = os.environ.get(FOLDER)
    if not directory:
        return lambda: None
    from dazedtl.compatibility.runtime import ENGINE_ROOT

    diagnostics = Diagnostics(
        directory, Path(__file__).resolve().parents[2], ENGINE_ROOT, rotate=False
    )
    watchdog = Watchdog(
        PROGRESS_STALL_SECONDS,
        lambda state, label, seconds, frame: diagnostics.hang(
            "operation." + state, seconds, diagnostics.stack(frame), action=label
        ),
    )
    watchdog.busy(action)
    return watchdog.beat
