"""Bounded local failure records containing metadata and code locations, never payloads."""

import json
import logging
import sys
import sysconfig
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Diagnostics:
    def __init__(self, directory, root, legacy):
        self.roots = (
            ("python", Path(sys.prefix)),
            # A virtual environment's prefix holds packages but not the stdlib.
            ("python", Path(sysconfig.get_path("stdlib"))),
            ("app", Path(root)),
            ("engine", Path(legacy)),
        )
        # An unregistered logger keeps each instance's handlers separate.
        self.logger = logging.Logger("dazedtl.diagnostics", logging.INFO)  # noqa: LOG001
        self.logger.propagate = False
        try:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
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
            self.logger.info(
                json.dumps(
                    {
                        "time": datetime.now(UTC).isoformat(),
                        "event": event,
                        **fields,
                    }
                )
            )
        except OSError, ValueError:
            pass  # Logging must not prevent returning the original error.

    def location(self, filename):
        try:
            path = Path(filename).resolve()
        except OSError, ValueError:
            return "external"
        for label, root in self.roots:
            if path.is_relative_to(root):
                return (label + "/" + path.relative_to(root).as_posix())[:180]
        return "external"

    def failure(self, error, operation="startup", request_id=None):
        causes = []
        seen = set()
        current = error
        while current is not None and id(current) not in seen and len(causes) < 3:
            seen.add(id(current))
            frames = [
                {
                    "file": self.location(frame.f_code.co_filename),
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

    def close(self):
        for handler in self.logger.handlers:
            handler.close()
