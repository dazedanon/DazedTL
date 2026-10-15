"""Tasks handed to a coding assistant, listed the same way across stages.

Each feature's copy reply says what it handed out: its kind, request id and
the result files it expects back. One record per kind keeps when it was
copied, so the app can say what is still waiting without asking each
feature, and whether anything came back since. A task that keeps working
after its first results also names the file it saves last, so it does not
read finished early, and one whose assistant validates its results after
saving them names the validator's report, so it reads finished only once a
passing report follows them. The features keep their own requests, reports
and validation.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_json

from .files import read_json

KINDS = (
    "names",
    "line_widths",
    "event_text",
    "plugins",
    "image_discovery",
    "image_editing",
    "qa",
    "walkthrough",
)


def _time(seconds=None):
    moment = (
        datetime.now(UTC) if seconds is None else datetime.fromtimestamp(seconds, UTC)
    )
    return moment.isoformat(timespec="milliseconds")


class AssistantTasks:
    def __init__(self, workspace):
        self.root = Path(workspace) / "assistant-tasks"
        self.lock = threading.Lock()
        # Validation reports by path, read again only when they change.
        self.reports = {}

    def _path(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", project_id
        ):
            raise ValueError("Choose an open project.")
        return self.root / (project_id + ".json")

    def _load(self, project_id):
        path = self._path(project_id)
        if not path.exists():
            return {}
        value = read_json(path, limit=1_000_000)
        tasks = value.get("tasks") if isinstance(value, dict) else None
        if not isinstance(tasks, dict):
            raise ValueError("Saved assistant tasks are invalid.")
        return {
            kind: tasks[kind] for kind in KINDS if isinstance(tasks.get(kind), dict)
        }

    def _save(self, project_id, tasks):
        write_json(self._path(project_id), {"version": 1, "tasks": tasks})

    def copied(self, project_id, handoff):
        """Records a copied task, replacing an earlier one of its kind."""
        kind = handoff.get("kind")
        if kind not in KINDS:
            raise ValueError("Unknown assistant task.")
        with self.lock:
            tasks = self._load(project_id)
            tasks[kind] = {
                "requestId": str(handoff.get("requestId") or ""),
                "copiedAt": _time(),
                "expects": [str(path) for path in handoff.get("expects", [])],
                **({"finish": str(handoff["finish"])} if handoff.get("finish") else {}),
                **(
                    {"validation": str(handoff["validation"])}
                    if handoff.get("validation")
                    else {}
                ),
            }
            self._save(project_id, tasks)

    def dismiss(self, project_id, kind):
        """Marks a task abandoned; its saved results stay with its feature."""
        if kind not in KINDS:
            raise ValueError("Unknown assistant task.")
        with self.lock:
            tasks = self._load(project_id)
            # A task copied before records existed has none yet.
            tasks[kind] = {
                **tasks.get(kind, {"requestId": "", "copiedAt": "", "expects": []}),
                "dismissed": True,
            }
            self._save(project_id, tasks)
        return {"kind": kind}

    def view(self, project_id):
        """Every record, with the newest time a result it expects was saved.

        Only file times are read, so the observer can afford it; a
        validation report is read again only when its time or size changes.
        """
        rows = []
        for kind, record in self._load(project_id).items():
            saved = [
                time
                for path in record.get("expects", [])
                if (time := _saved(path)) is not None
            ]
            row = {
                "kind": kind,
                "requestId": record.get("requestId", ""),
                "copiedAt": record.get("copiedAt", ""),
                "resultAt": _time(max(saved)) if saved else None,
                "dismissed": bool(record.get("dismissed")),
            }
            if record.get("finish"):
                finished = _saved(record["finish"])
                row["finishedAt"] = None if finished is None else _time(finished)
            if record.get("validation"):
                row["validation"] = self._report(record["validation"])
            rows.append(row)
        return sorted(rows, key=lambda row: row["copiedAt"])

    def _report(self, path):
        """A validation report's outcome; None while none is readable, such as
        one still being written."""
        try:
            info = Path(path).stat()
        except OSError:
            return None
        key = (info.st_mtime_ns, info.st_size)
        cached = self.reports.get(path)
        if cached and cached[0] == key:
            return cached[1]
        outcome = None
        try:
            report = read_json(path)
        except OSError, ValueError:
            report = None
        if isinstance(report, dict) and report.get("status") in {"passed", "failed"}:
            summary = report.get("summary")
            errors = summary.get("errors") if isinstance(summary, dict) else None
            outcome = {
                "savedAt": _time(info.st_mtime),
                "passed": report["status"] == "passed",
                "errors": errors if type(errors) is int and errors > 0 else 0,
            }
        self.reports[path] = (key, outcome)
        return outcome


def _saved(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None
