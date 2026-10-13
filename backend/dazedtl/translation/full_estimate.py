"""The whole game's API cost before translation starts, from Context's Cost estimate.

It estimates every Translate task that sends game text through the API key,
over all of each task's files rather than its selection, in one local
operation that never creates a run. A saved estimate stays until a newer one
replaces it; it reads current while the inputs every task's own estimate
binds to are unchanged.
"""

import json
from copy import deepcopy
from datetime import datetime
from functools import cache
from pathlib import Path

from .files import digest

ACTION = "full_estimate"
# The Translate tasks that send game text through the API key, in their order.
PHASES = ("database", "dialogue", "advanced")
# An estimate prices both Batch and Live from the same requests, so switching
# between them keeps it current; the least demanding mode's configuration
# stands for both.
MODE = "translate"


@cache
def app_version():
    """The running DazedTL release. A newer one may estimate differently, so
    an estimate made by another release is never current."""
    try:
        package = Path(__file__).resolve().parents[3] / "app/package.json"
        return json.loads(package.read_bytes())["version"]
    except OSError, ValueError, KeyError, TypeError:
        return None


def took(job):
    """Seconds an operation ran, from its start to its last record."""
    try:
        return max(
            0.0,
            (
                datetime.fromisoformat(job["updated"])
                - datetime.fromisoformat(job["created"])
            ).total_seconds(),
        )
    except KeyError, TypeError, ValueError:
        return None


class FullEstimate:
    def __init__(self, guided):
        self.guided = guided

    def files(self, native, phase):
        """A task's whole share of the game, whatever its file selection."""
        supported = self.guided.supported_files(native)
        return sorted(
            name
            for name in self.guided.backend.phase_files(native, phase)
            if name in supported
        )

    def scope(self, project_id, native, event_text, *, guard=None, cached_only=False):
        """Each task's files and the inputs its estimate depends on. Other
        event text has nothing to translate until a source is chosen."""
        tasks = []
        for phase in PHASES:
            if phase == "advanced" and not event_text["enabled"]:
                tasks.append({"phase": phase, "files": [], "fingerprint": None})
                continue
            names = self.files(native, phase)
            inputs = self.guided.runs.inputs(
                project_id,
                native,
                phase,
                MODE,
                guard=guard,
                cached_only=cached_only,
                names=names,
            )
            tasks.append(
                {"phase": phase, "files": names, "fingerprint": inputs["fingerprint"]}
            )
        return tasks

    @staticmethod
    def fingerprint(tasks):
        return digest(
            {
                "app": app_version(),
                "tasks": [[task["phase"], task["fingerprint"]] for task in tasks],
            }
        )

    def start(self, project_id):
        self.guided.idle(isolated_workers=True)
        self.guided.clean_options(project_id)
        _, native = self.guided.record(project_id)
        self.guided.require_preparation(project_id, native)
        if native.get("collection_error"):
            raise ValueError(native["collection_error"])
        names = [*self.files(native, "database"), *self.files(native, "dialogue")]
        if not names:
            raise ValueError("Set up this game before estimating its cost.")
        inputs = self.guided.inputs(native)
        if inputs.status(sorted(self.guided.supported_files(native)))["changed"]:
            raise ValueError(
                "The original game files changed. Reload them from the game in "
                "Translate, then estimate again."
            )
        event_text = self.guided.event_text.status(project_id, native)
        if event_text["enabled"] and event_text["errors"]:
            raise ValueError(
                "Fix the event text source choices first: "
                + " ".join(event_text["errors"])
            )
        # The same frozen model options a Translate estimate starts with.
        self.guided.settings.prepare_engine(mode="estimate")
        policy = deepcopy(self.guided.backend.manual.request_policy)
        tasks = self.scope(project_id, native, event_text)
        saved = self.saved(native)
        if (
            saved
            and saved["result"].get("fingerprint") == self.fingerprint(tasks)
            # A count that failed may succeed now.
            and not any(
                task.get("approximateInput") for task in saved["result"]["tasks"]
            )
        ):
            raise ValueError(
                "Nothing changed since the last estimate, so it is still current."
            )
        folder = self.guided.backend.workflows.folder(native["id"])
        sources = inputs.sources(names, inputs.record()["inputs"])
        defaults = self.guided.settings.translation_defaults()
        return self.guided.backend.operations.start(
            {
                "project_id": native["id"],
                "project": deepcopy(native),
                "folder": str(folder),
                "action": ACTION,
                "label": "Estimate the translation cost",
                "guard": self.guided.backend.guided_guard(native, folder),
                "options": {
                    "fingerprint": self.fingerprint(tasks),
                    "model": defaults["model"],
                    "batchSupported": defaults["batch_supported"],
                    "policy": policy,
                    # A launch with providers disabled keeps Claude's
                    # approximate count rather than reach Anthropic.
                    "claudeCount": self.guided.backend.manual.allow_providers,
                    "files": {name: sources[name]["relative"] for name in names},
                    "tasks": [
                        {
                            "phase": task["phase"],
                            "files": task["files"],
                            "noSources": task["phase"] == "advanced"
                            and not task["files"],
                            "workflow": self.guided.backend.workflows.phase_workflow(
                                native["id"], task["phase"]
                            ),
                        }
                        for task in tasks
                    ],
                },
            }
        )

    def jobs(self, native):
        """The project's estimates, newest first."""
        return sorted(
            (
                job
                for job in self.guided.backend.operations.jobs.values()
                if job["project_id"] == native["id"] and job["action"] == ACTION
            ),
            key=lambda job: job["created"],
            reverse=True,
        )

    def saved(self, native):
        """The newest finished estimate, which the panel shows."""
        return next(
            (
                job
                for job in self.jobs(native)
                if job["status"] == "complete" and isinstance(job.get("result"), dict)
            ),
            None,
        )

    def status(self, project_id, native, event_text):
        jobs = self.jobs(native)
        saved = self.saved(native)
        result = saved["result"] if saved else None
        current = False
        if result:
            try:
                tasks = self.scope(
                    project_id,
                    native,
                    event_text,
                    guard=self.guided.runs.poll_guard(native),
                    cached_only=True,
                )
                current = self.fingerprint(tasks) == result.get("fingerprint")
            except OSError, ValueError, KeyError:
                current = False
        return {
            "job": jobs[0] if jobs else None,
            "result": result,
            "finished": saved["updated"] if saved else None,
            "took": took(saved) if saved else None,
            "current": current,
        }
