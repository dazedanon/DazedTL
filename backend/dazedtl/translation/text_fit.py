"""Fit a game's applied text again once its Line widths change.

Translation and Apply fit text to the Line widths as they write it. New
widths, set by hand or measured in the game, leave text written earlier
fitted to the old ones, so the areas whose width changed are fitted again,
in the files DazedTL applied, in one backed-up publication, which History
can restore.
"""

from copy import deepcopy

from dazedtl import system
from dazedtl.actions import label, named
from dazedtl.storage import write_json
from dazedtl.translation.files import read_json
from dazedtl.translation.operations import checkout_issue

ACTION = "fit_text"
LABEL = label(ACTION)
# The actions whose writes replace the game's text, after which a fit's list
# of what it could not fit no longer holds.
WRITES = named(writes_text=True)
# The Line widths entries that move where text wraps. Message rows only
# change where a long message goes on to its next page, so new rows rewrap
# nothing but check again what a window of fixed height cuts off.
AREAS = ("width", "faceWidth", "listWidth", "noteWidth")
ROWS = "messageRows"


class TextFit:
    def __init__(self, guided):
        self.guided = guided

    def _path(self, project_id):
        return self.guided.path(project_id, "text-fit")

    def request(self, project_id, native, before, after):
        """Queue the areas a change of widths moved, when the game holds
        applied text to fit. Saving the same widths again retries a fit that
        failed."""
        changed = {key for key in AREAS if before.get(key) != after.get(key)}
        failed = self.latest(native)
        if failed and failed.get("status") in {"failed", "interrupted", "stopped"}:
            changed |= set(self._areas(failed))
        checked = changed or before.get(ROWS) != after.get(ROWS)
        if not checked or native["engine"] not in {"MVMZ", "ACE"}:
            return
        path = self._path(project_id)
        queued = set(read_json(path).get("areas", [])) if path.exists() else set()
        write_json(path, {"version": 1, "areas": sorted(queued | changed)})

    def pending(self, project_id):
        path = self._path(project_id)
        return path.exists()

    def waiting(self, project_id):
        """Why a queued fit waits on the game's Git checkout, or "". Like any
        write to the game, it waits for an unfinished Git operation, such as
        a game update's merge whose conflicts the game's files still hold,
        and for the translation branch."""
        if not self.pending(project_id):
            return ""

        def read():
            translation = self.guided.translation
            try:
                _, project = translation.project(project_id)
                status = translation.engine.git_status(
                    project.root, project.read()["options"]
                )
            except Exception:  # noqa: BLE001
                # Unread, Git holds nothing back; History can restore a fit.
                return ""
            return checkout_issue(status) if status.get("configured") else ""

        return self.guided.observations.once(("checkout", project_id), read)

    def advance(self, project_id, native, applied):
        """Start a queued fit of the files DazedTL *applied* once nothing
        else runs and Git can take it. Text applied later is fitted as it is
        written, so with nothing applied the request ends."""
        path = self._path(project_id)
        if not path.exists():
            return None
        # The request outlasts an unfinished merge, while the game's files
        # are not as DazedTL applied them.
        if self.waiting(project_id):
            return None
        if not applied:
            system.unlink(path, missing_ok=True)
            return None
        backend = self.guided.backend
        if backend.running() or self.guided.translation.jobs.running():
            return None
        areas = read_json(path).get("areas", [])
        folder = backend.workflows.folder(native["id"])
        try:
            job = backend.operations.start(
                {
                    "project_id": native["id"],
                    "project": deepcopy(native),
                    "folder": str(folder),
                    "action": ACTION,
                    "label": LABEL,
                    "guard": backend.guided_guard(native, folder),
                    "options": {"areas": areas, "files": sorted(applied)},
                }
            )
        except OSError, ValueError:
            # Another operation won the race; the next look starts it.
            return None
        system.unlink(path, missing_ok=True)
        return job

    def _areas(self, job):
        """The areas a fit job was asked to fit, from its saved plan."""
        try:
            plan = read_json(
                self.guided.backend.operations.root / job["id"] / "plan.json"
            )
        except OSError, ValueError, KeyError, AttributeError:
            return []
        return [
            area for area in plan.get("options", {}).get("areas", []) if area in AREAS
        ]

    def latest(self, native):
        """The newest fit of this game's text, if any."""
        jobs = [
            job
            for job in self.guided.backend.operations.jobs.values()
            if job.get("project_id") == native["id"] and job.get("action") == ACTION
        ]
        return max(jobs, key=lambda job: job.get("created", 0), default=None)

    def misfits(self, native):
        """The text the newest fit could not fit, first ones, and how much,
        while the game holds the text it fitted: until new widths or another
        write of the game's text."""
        latest = self.latest(native)
        result = latest.get("result") or {} if latest else {}
        current = (
            latest
            and latest.get("status") == "complete"
            and result.get("widths") == native["widths"]
            and not any(
                job.get("project_id") == native["id"]
                and job.get("action") in WRITES
                and job.get("created", 0) > latest.get("created", 0)
                for job in self.guided.backend.operations.jobs.values()
            )
        )
        if not current:
            return {"misfits": [], "misfit_count": 0}
        return {
            "misfits": result.get("misfits", []),
            "misfit_count": result.get("misfit_count", 0),
        }
