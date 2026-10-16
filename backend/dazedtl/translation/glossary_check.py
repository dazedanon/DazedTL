"""The Glossary check task: lines whose English lacks a glossary term their
Japanese holds, the user's choice for each, and the fixes it applies.

A tool operation scans the game and saves its lines in the workflow folder;
observations summarize that file and the choices beside it, and the task
reads the lines themselves only while it shows them. Each choice saves at
once in the game's `.dazedtl/guided/glossary-check.json`, bound to the
English it was made for, so a line that changes is checked afresh. Fixes go
into the game as one text batch through the Guided publication flow, so
History can restore them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from .files import digest, project_path, read_json

if TYPE_CHECKING:
    from .guided import Guided

ACTION = "glossary_check"
RECORD = ".dazedtl/guided/glossary-check.json"
CHOICES = ("keep", "use", "edit", "clear")
# A record's own version, raised when its shape changes.
VERSION = 1


def _state(line: dict[str, Any], saved: dict[str, Any] | None) -> dict[str, Any]:
    """Where one flagged line stands given its saved choice: open, a fix
    waiting to apply, or kept. A choice holds only for the English it was
    made for; a fix the game already holds that still lacks a term is the
    text the user chose, so it reads as kept, until another term goes
    missing from it."""
    terms = {term["source"] for term in line["terms"]}
    if saved and terms <= set(saved["terms"]):
        if saved["live"] == line["live"]:
            if saved["choice"] == "keep":
                return {"state": "kept", "choice": "keep"}
            return {"state": "fix", "choice": saved["choice"], "text": saved["text"]}
        if saved.get("text") == line["live"]:
            return {"state": "kept", "choice": saved["choice"]}
    return {"state": "open"}


class GlossaryCheck:
    def __init__(self, guided: Guided):
        self.guided = guided
        # Each scan's data and glossary digests, read once from its plan.
        self.guards: dict[str, tuple[dict[str, str], str | None]] = {}
        # The last summary, by the scan file's and the record's digests.
        self.summaries: dict[tuple[str, str, str | None], dict[str, Any]] = {}

    def folder(self, native) -> Path:
        return Path(self.guided.backend.workflows.folder(native["id"]))

    def scans(self, native):
        """The project's glossary scans, newest first."""
        return sorted(
            (
                job
                for job in self.guided.backend.operations.jobs.values()
                if job["project_id"] == native["id"] and job["action"] == ACTION
            ),
            key=lambda job: job["created"],
            reverse=True,
        )

    def saved(self, native, digest_of=None):
        """The newest finished scan whose lines file is still the one it
        saved, or None."""
        from dazedtl.compatibility.glossary_check import ARTIFACT

        digest_of = digest_of or (lambda path: digest(path.read_bytes()))
        try:
            artifact = digest_of(self.folder(native) / ARTIFACT)
        except OSError, ValueError:
            return None
        return next(
            (
                job
                for job in self.scans(native)
                if job["status"] == "complete"
                and (job.get("result") or {}).get("artifact_sha256") == artifact
            ),
            None,
        )

    def guard(self, job):
        if job["id"] not in self.guards:
            plan = read_json(
                self.guided.backend.operations.root / job["id"] / "plan.json"
            )
            self.guards[job["id"]] = (
                plan["guard"]["data"] or {},
                plan["guard"]["glossary"],
            )
        return self.guards[job["id"]]

    def current(self, native, job) -> bool:
        """Whether the game's data and glossary are as the scan read them."""
        data, glossary = self.guard(job)
        try:
            found = self.guided.observed_digests(native["data"], sorted(data))
            path = project_path(native["source"], ".dazedtl/glossary.txt", exists=False)
            observed = self.guided.observed_digest(path) if path.is_file() else None
        except OSError, ValueError:
            return False
        return observed == glossary and found == data

    def record(self, native) -> dict[str, Any]:
        path = project_path(native["source"], RECORD, exists=False)
        if not path.is_file():
            return {"version": VERSION, "lines": {}}
        saved = read_json(path)
        if saved.get("version") != VERSION or not isinstance(saved.get("lines"), dict):
            raise ValueError(f"DazedTL can't read {RECORD}; remove it to choose again.")
        return saved

    def lines(self, native, job) -> dict[str, Any]:
        from dazedtl.compatibility.glossary_check import saved_scan

        return saved_scan(self.folder(native), job["result"]["artifact_sha256"])

    def state(self, native) -> dict[str, Any]:
        """The snapshot's summary: the scan, whether it is current, and how
        many lines are open, fixed and kept."""
        empty = {
            "scan": None,
            "current": False,
            "lines": 0,
            "flagged": 0,
            "open": 0,
            "fixes": 0,
            "kept": 0,
            "revision": "",
        }
        job = self.saved(native, self.guided.observed_digest)
        if job is None:
            return empty
        try:
            path = project_path(native["source"], RECORD, exists=False)
            record = self.guided.observed_digest(path) if path.is_file() else None
            key = (job["id"], job["result"]["artifact_sha256"], record)
            if key not in self.summaries:
                try:
                    saved = self.record(native)["lines"]
                except ValueError:
                    # The list says why the choices can't be read; until
                    # then every line counts as open.
                    saved = {}
                rows = self.rows(native, job, saved)
                self.summaries = {
                    key: {
                        "scan": job["id"],
                        "lines": job["result"]["lines"],
                        "flagged": job["result"]["flagged"],
                        **{
                            name: sum(1 for row in rows if row["state"] == state)
                            for name, state in (
                                ("open", "open"),
                                ("fixes", "fix"),
                                ("kept", "kept"),
                            )
                        },
                        "revision": digest([list(key)]),
                    }
                }
            return {**self.summaries[key], "current": self.current(native, job)}
        except OSError, ValueError:
            return empty

    def rows(self, native, job, saved=None) -> list[dict[str, Any]]:
        """Each flagged line with where the user's choices leave it."""
        if saved is None:
            saved = self.record(native)["lines"]
        rows = []
        for line in self.lines(native, job)["found"]:
            row = {
                **{
                    key: line[key]
                    for key in ("key", "file", "pointer", "source", "live")
                },
                "terms": [
                    {key: term[key] for key in ("source", "english", "start", "end")}
                    for term in line["terms"]
                ],
            }
            if line.get("proposal"):
                row["proposal"] = line["proposal"]
            rows.append({**row, **_state(line, saved.get(line["identity"]))})
        return rows

    def report(self, project_id) -> dict[str, Any]:
        """Every flagged line with where it stands, for the task's list."""
        _, native = self.guided.record(project_id)
        job = self.saved(native)
        summary = self.state(native)
        if job is None:
            return {**summary, "found": []}
        return {**summary, "found": self.rows(native, job)}

    def run(self, project_id, step, keys=None, choice="", text=""):
        if step == "choose":
            self.choose(project_id, keys, choice, text)
            return self.report(project_id)
        if step == "apply":
            operation = self.apply(project_id)
            return {**self.report(project_id), "operation": operation}
        raise ValueError("Choose a glossary check step: choose or apply.")

    def choose(self, project_id, keys, choice, text):
        """Saves the user's choice for some lines: keep the text, use the
        proposal, write their own fix, or clear an earlier choice."""
        from dazedtl.compatibility.glossary_check import fitted

        _, native = self.guided.record(project_id)
        job = self.saved(native)
        if job is None:
            raise ValueError("Check the glossary terms first.")
        if (
            choice not in CHOICES
            or not isinstance(keys, list)
            or not keys
            or any(not isinstance(key, str) for key in keys)
        ):
            raise ValueError("Choose lines and what to do with them.")
        if choice == "edit" and (len(keys) != 1 or not isinstance(text, str)):
            raise ValueError("Write a fix for one line at a time.")
        scan = self.lines(native, job)
        by_key = {line["key"]: line for line in scan["found"]}
        if any(key not in by_key for key in keys):
            raise ValueError("That line is no longer in the check; check again.")
        record = self.record(native)
        saved = dict(record["lines"])
        for key in keys:
            line = by_key[key]
            if choice == "clear":
                saved.pop(line["identity"], None)
                continue
            entry = {
                "live": line["live"],
                "terms": sorted(term["source"] for term in line["terms"]),
                "choice": choice,
            }
            if choice == "use":
                if not line.get("proposal"):
                    raise ValueError("That line has no proposal; write a fix instead.")
                entry["text"] = line["proposal"]
            elif choice == "edit":
                written, problems = fitted(scan["layout"], line["record"], text)
                if problems:
                    raise ValueError("This fix " + "; ".join(problems) + ".")
                entry["text"] = written
            saved[line["identity"]] = entry
        path = project_path(native["source"], RECORD, exists=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"version": VERSION, "lines": saved})

    def apply(self, project_id):
        """Puts every chosen fix into the game as one text batch."""
        _, native = self.guided.record(project_id)
        job = self.saved(native)
        if job is None or not self.current(native, job):
            raise ValueError("Check the glossary terms again before applying fixes.")
        fixes = {
            row["key"]: row["text"]
            for row in self.rows(native, job)
            if row["state"] == "fix"
        }
        if not fixes:
            raise ValueError("Choose the fixes to apply first.")
        preview = self.guided.preview(
            project_id,
            "glossary_apply",
            None,
            {"scan": job["result"]["artifact_sha256"], "fixes": fixes},
        )
        started = self.guided.execute(project_id, preview["token"])
        return {"id": started["id"]}
