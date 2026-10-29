"""The whole game's API cost before translation starts, from Context's Cost estimate.

It estimates every Translate task that sends game text through the API key,
over all of each task's files rather than its selection, in one local
operation that never creates a run. A saved estimate stays until a newer one
replaces it; it reads current while the inputs every task's own estimate
binds to are unchanged.
"""

from copy import deepcopy
from datetime import datetime

from dazedtl.actions import label
from dazedtl.freshness import Basis, compare

from . import repricing
from .files import digest

ACTION = "full_estimate"
# The Translate tasks that send game text through the API key, in their order.
PHASES = ("database", "dialogue", "advanced")
# An estimate prices both Batch and Live from the same requests, so switching
# between them keeps it current; the least demanding mode's configuration
# stands for both.
MODE = "translate"


# Raise when the same tasks would estimate differently. It is part of the
# fingerprint, so raising it outdates every saved whole-game estimate.
ESTIMATE_VERSION = 2
# Releases that bound a whole-game estimate to their own version instead, so
# every upgrade outdated it. Their estimates read current while the tasks match.
RELEASES = (
    *("2.13.2", "2.14.0", "2.14.1", "2.14.2", "2.15.0", "2.15.1", "2.16.0"),
    *("2.17.0", "2.18.0", "2.19.0", "2.20.0", "2.20.1", "2.21.0", "2.22.0"),
    *("2.23.0", "2.23.1", "2.24.0"),
)


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
                {
                    "phase": phase,
                    "files": names,
                    "fingerprint": inputs["fingerprint"],
                    "shape": inputs["shape"],
                    "legacy": inputs["legacy"],
                    "configuration": inputs["configuration"],
                }
            )
        return tasks

    @staticmethod
    def fingerprint(tasks, key="fingerprint", release=None):
        """What every task's estimate binds to; with ``shape``, what a switch
        that only prices their requests leaves alone. ``release`` gives the
        digest that release saved."""
        rows = [[task["phase"], task.get(key)] for task in tasks]
        if release:
            return digest({"app": release, "tasks": rows})
        return digest({"version": ESTIMATE_VERSION, "tasks": rows})

    def basis(self, tasks, result=None, routes=()):
        """The basis of ``tasks``, with the price rules an estimate priced on
        ``routes`` needs (repricing.route_rules), or, with ``result``, of the
        saved estimate, with the price rules it was priced under. One a
        listed release saved for these tasks reads as made under version 1.
        Versions up to 2.34.3 bound each task to the game folder
        (GuidedRuns.saved); one they saved for these tasks reads as theirs."""
        current = {
            key: self.fingerprint(tasks, key) for key in ("fingerprint", "shape")
        }
        if result is None:
            return Basis(
                ESTIMATE_VERSION,
                {},
                current["fingerprint"],
                current["shape"],
                repricing.route_rules(*routes),
            )
        located = [{**task, **(task.get("legacy") or {})} for task in tasks]
        saved, version = {}, ESTIMATE_VERSION
        for key, value in current.items():
            saved[key] = result.get(key)
            if saved[key] == value:
                continue
            if saved[key] == self.fingerprint(located, key):
                saved[key] = value
            elif saved[key] in {
                self.fingerprint(located, key, old) for old in RELEASES
            }:
                saved[key], version = value, 1
        return Basis(
            version,
            {},
            saved["fingerprint"],
            saved["shape"],
            repricing.rules(result),
        )

    def changed(self, result, tasks, route, *, reprice=True):
        """What changed since ``result`` was estimated, or None while it is
        current; one with a task priced on another route than ``route``, the
        Batch provider of the tasks' settings, changed its prices
        (repricing.rerouted). With ``reprice``, settings that differ only in
        prices not known yet count as the same."""
        routes = self.routes(result, route)
        saved = self.basis(tasks, result)
        current = self.basis(tasks, routes=routes)
        change = compare(
            saved,
            current,
            prices_unknown=reprice
            and saved.settings != current.settings
            and repricing.unknown_prices(
                result["configuration"], self.configuration(tasks)
            ),
        )
        return repricing.rerouted(change, routes, route)

    @staticmethod
    def routes(result, route):
        """The routes a saved estimate's tasks were priced on: the Batch
        provider each task's counts record (repricing.estimate_route), or
        ``route`` for counts that record none."""
        measured = result.get("measured") or {}
        return [repricing.estimate_route(counts, route) for counts in measured.values()]

    @staticmethod
    def configuration(tasks):
        """The settings the tasks are priced with, the same for every task."""
        return next(task["configuration"] for task in tasks if task["fingerprint"])

    def reading(self, result, tasks, *, reprice=True):
        """How a saved estimate reads for ``tasks`` (repricing.read): as
        saved, priced again from each task's counts on the route their
        settings take now, or outdated."""
        configuration = self.configuration(tasks)
        route = self.guided.runs.route(configuration)
        return repricing.read(
            self.changed(result, tasks, route, reprice=reprice),
            result.get("configuration"),
            configuration,
            lambda settings: self.priced(result, settings, route),
        )

    def priced(self, result, configuration, route):
        """A saved estimate priced again from each task's counts at the
        prices of ``configuration`` on ``route``, else None."""
        from dazedtl.compatibility.estimate_prices import reprice
        from dazedtl.compatibility.full_estimate import prices

        rows = []
        for task in result["tasks"]:
            counts = result["measured"].get(task["phase"])
            if counts is None:
                rows.append(task)
                continue
            estimate = reprice(counts, configuration, route)
            if estimate is None:
                return None
            rows.append({**task, **prices(estimate)})
        defaults = self.guided.settings.translation_defaults()
        return {
            **result,
            "model": configuration["model"],
            "batchSupported": defaults["batch_supported"],
            "price_rules": repricing.current_rules(),
            "tasks": rows,
        }

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
        self.guided.settings.prepare_engine(
            mode="estimate", pair=self.guided.runs.pair(native)
        )
        policy = deepcopy(self.guided.backend.manual.request_policy)
        tasks = self.scope(project_id, native, event_text)
        saved = self.saved(native)
        # A count that failed may succeed now.
        if saved and not any(
            task.get("approximateInput") for task in saved["result"]["tasks"]
        ):
            reading = self.reading(saved["result"], tasks, reprice=False)
            if reading.current and reading.figure is None:
                raise ValueError(
                    "Nothing changed since the last estimate, so it is still current."
                )
            # Pricing its counts again, as the panel shows it, is all it needs.
            if reading.current:
                return saved
        folder = self.guided.backend.workflows.folder(native["id"])
        sources = inputs.sources(names, inputs.record()["inputs"])
        defaults = self.guided.settings.translation_defaults()
        return self.guided.backend.operations.start(
            {
                "project_id": native["id"],
                "project": deepcopy(native),
                "folder": str(folder),
                "action": ACTION,
                "label": label(ACTION),
                "guard": self.guided.backend.guided_guard(native, folder),
                "options": {
                    "fingerprint": self.fingerprint(tasks),
                    "shape": self.fingerprint(tasks, "shape"),
                    "configuration": self.configuration(tasks),
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
        if result and self.guided.event_text.pending(event_text):
            # Other event text's inputs wait for readers: unknown, not stale.
            current = None
        elif result:
            try:
                tasks = self.scope(
                    project_id,
                    native,
                    event_text,
                    guard=self.guided.runs.poll_guard(native),
                    cached_only=True,
                )
                # A model switch that keeps every task's requests, or a
                # pricing fix, prices them again.
                reading = self.reading(result, tasks)
                current = reading.current
                if reading.figure is not None:
                    result = reading.figure
            except OSError, ValueError, KeyError:
                current = False
        return {
            "job": jobs[0] if jobs else None,
            "result": result,
            "finished": saved["updated"] if saved else None,
            "took": took(saved) if saved else None,
            "current": current,
        }
