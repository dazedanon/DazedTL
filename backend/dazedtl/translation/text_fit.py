"""Fit a game's applied text again once its Line widths change.

Translation and Apply fit text to the Line widths as they write it. New
widths, set by hand or measured in the game, leave text written earlier
fitted to the old ones, so the areas whose width changed are fitted again in
one backed-up publication, which History can restore.
"""

from copy import deepcopy

from dazedtl.storage import write_json
from dazedtl.translation.files import read_json

ACTION = "fit_text"
LABEL = "Fit text to the new Line widths"
# The Line widths entries that move where text wraps. Message rows only
# change where a long message goes on to its next page.
AREAS = ("width", "faceWidth", "listWidth", "noteWidth")


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
        if not changed or native["engine"] not in {"MVMZ", "ACE"}:
            return
        path = self._path(project_id)
        queued = set(read_json(path).get("areas", [])) if path.exists() else set()
        write_json(path, {"version": 1, "areas": sorted(queued | changed)})

    def pending(self, project_id):
        path = self._path(project_id)
        return path.exists()

    def advance(self, project_id, native, applied):
        """Start a queued fit once nothing else runs. Text applied later is
        fitted as it is written, so with nothing applied the request ends."""
        path = self._path(project_id)
        if not path.exists():
            return None
        if not applied:
            path.unlink(missing_ok=True)
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
                    "options": {"areas": areas},
                }
            )
        except OSError, ValueError:
            # Another operation won the race; the next look starts it.
            return None
        path.unlink(missing_ok=True)
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
