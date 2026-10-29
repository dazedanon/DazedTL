"""Keep the legacy job controller, with a local worker-launch boundary."""

import hashlib
import importlib.util
import json
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from dazedtl import system

from .preparations import discard, discardable, temporary

SPEAKER_CANCELLATION = "Speaker translation canceled"
# The engine's failure summary names no cause; its file errors do.
ENGINE_FAILURE = "Translation failed"
DECLINED_SPEAKERS = (
    "No unresolved speakers were sent, and the translation run did not start."
)


def stage_originals(directory, plan, policy):
    """Stages in a run's folder the game's recorded originals of its files
    (translation/originals `stage`), for an RPG Maker MV/MZ run whose
    frozen request policy reads them (engine util/original_values); a run
    of a game whose originals are not recorded reads without them."""
    from util.original_values import FOLDER

    from dazedtl.settings.preferences import SOURCE_TEXT_LEVELS
    from dazedtl.translation import originals

    level = SOURCE_TEXT_LEVELS.get(str((policy or {}).get("sourceText")), 0)
    if plan.get("engine") != "RPG Maker MV/MZ" or level < 4:
        return
    if not plan.get("context_source"):
        return
    originals.stage(
        plan["context_source"],
        [item["name"] for item in plan["files"]],
        plan["source"],
        Path(directory) / FOLDER,
    )


def canceled_before_submission(job, directory, *, finishing=False):
    """Recognize an explicit declined preflight, never a generic worker failure."""
    logs = job.get("log")
    if (
        job.get("status") not in ({"running", "waiting"} if finishing else {"failed"})
        or job.get("mode") not in {"batch", "translate"}
        or job.get("phase") != "preparing"
        or job.get("message") != SPEAKER_CANCELLATION
        or not isinstance(logs, list)
        or not all(isinstance(line, str) for line in logs)
        or not any(DECLINED_SPEAKERS in line for line in logs)
        or any(
            job.get(key)
            for key in (
                "completed",
                "outputs",
                "errors",
                "mismatches",
                "batch_root",
                "batch_recovery",
                "batch_detail",
                "approval",
            )
        )
    ):
        return False
    try:
        if directory.is_symlink() or any(
            (directory / name).is_symlink() for name in ("translated", "log")
        ):
            return False
        plan_path, attempt_path = directory / "plan.json", directory / "attempt.json"
        if plan_path.is_symlink() or attempt_path.is_symlink():
            return False
        raw = system.read_bytes(plan_path)
        plan, attempt = json.loads(raw), json.loads(system.read_bytes(attempt_path))
        if (
            hashlib.sha256(raw).hexdigest() != job.get("plan_hash")
            or plan.get("mode") != job["mode"]
            or plan.get("batch_link")
            or attempt.get("resume") is not False
            or attempt.get("batch_resume_state") is not None
        ):
            return False
        # Even an unexpected queued request or output keeps its recovery guard.
        if any(
            path.is_file() or path.is_symlink()
            for path in (directory / "translated").rglob("*")
        ):
            return False
        if any((directory / "log").glob("batch*")):
            return False
    except OSError, ValueError, TypeError:
        return False
    return True


# What a Batch preparation's plan adds to, or changes from, its estimate's.
PREPARATION_KEYS = (
    "mode",
    "scan_speakers",
    "scanned_speakers",
    "dazedtl_claude_count",
    "dazedtl_reserved_sources",
)


def seed_requests(directory, plan, estimate):
    """Gives a Batch preparation its estimate's plan and requests. Its worker
    submits them instead of collecting the same requests again when its own
    final plan matches the estimate's (see the engine's adoptable_requests)."""
    from .process_view import queue

    try:
        raw_plan = system.read_bytes(estimate / "plan.json")
        requests = queue(estimate)
    except OSError, ValueError:
        return
    if not requests:
        return
    raw_queue = json.dumps(requests, ensure_ascii=False).encode()
    seed = Path(directory) / "seed"
    seed.mkdir(exist_ok=True)
    for name, raw in (
        ("estimate_plan.json", raw_plan),
        ("batch_requests.json", raw_queue),
    ):
        (seed / name).write_bytes(raw)
        plan["context_hashes"]["seed/" + name] = hashlib.sha256(raw).hexdigest()
    plan["adopt_requests"] = {
        "plan": "seed/estimate_plan.json",
        "queue": "seed/batch_requests.json",
        "ignore": list(PREPARATION_KEYS),
    }


def manual_jobs(source, workspace, lock, allow_providers):
    # Load an isolated module namespace so its launcher layer never changes the
    # preserved application's controller.
    name = "desktop.backend._dazedtl_manual"
    spec = importlib.util.spec_from_file_location(
        name, source / "desktop/backend/manual.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("The bundled engine module " + name + " is missing.")
    native = importlib.util.module_from_spec(spec)
    sys.modules[name] = native
    spec.loader.exec_module(native)
    expected = source / "desktop/backend/manual_worker.py"

    def launch(native_launch, arguments, **kwargs):
        if len(arguments) != 4 or Path(arguments[2]) != expected:
            raise RuntimeError(
                "The preserved worker entrypoint changed. Update the compatibility adapter."
            )
        directory = Path(arguments[3])
        job = json.loads(system.read_bytes(directory / "job.json"))
        if job.get("dazedtl_continue_batch"):
            from .batch_continuation import (
                approved_binding,
                validate_submission_records,
            )

            approved_binding(
                directory, job, json.loads(system.read_bytes(directory / "plan.json"))
            )
            validate_submission_records(directory)
        if job.get("dazedtl_consume_only"):
            attempt = json.loads(system.read_bytes(directory / "attempt.json"))
            if (
                job.get("mode") != "batch"
                or attempt.get("resume") is not True
                or attempt.get("batch_resume_state") != "fetched"
            ):
                raise ValueError(
                    "Automatic Batch recovery can only save already collected responses."
                )
            from .batch_control import require_complete_submission

            require_complete_submission(directory)
        arguments = [
            *arguments[:2],
            str(Path(__file__).with_name("manual_worker.py")),
            arguments[3],
        ]
        kwargs["env"] = {
            **kwargs["env"],
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return native_launch(arguments, **kwargs)

    native.launch_worker.layer("dazedtl-worker", launch)

    # Claude count processes started beside their estimates, by run folder.
    warm_counts = {}
    warm_lock = threading.Lock()

    def finish_estimate(native_finish, directory, plan, estimate, stopped):
        from .estimate_pricing import count, stop

        estimate = native_finish(directory, plan, estimate, stopped)
        with warm_lock:
            process = warm_counts.pop(str(directory), None)
        if not allow_providers or plan.get("dazedtl_claude_count") is False:
            stop(process)
            return estimate
        return count(directory, workspace, plan, estimate, stopped, process=process)

    native.finish_estimate.layer("dazedtl-claude-count", finish_estimate)

    class ManualJobs(native.ManualJobs):
        request_policy = None
        continuation = None
        reserved_sources = None
        source_versions = None
        reused_names = None
        workflow_selection = None
        temporary_preparation = False
        # False when a Batch preparation follows the estimate and counts the
        # requests it submits itself.
        claude_count = True
        # An estimate that a Batch preparation follows scans speakers for it,
        # and that preparation reuses the scan.
        speaker_scan = False
        scanned_speakers = None
        # That estimate's run folder, whose requests the preparation may reuse.
        adopt_from = None
        # Readies the selected working copies after a phase syncs saved
        # outputs into them and before it lists them for the run.
        prepare_inputs = None
        # Called under the lock with what a failed API run froze and the
        # message it ended with (settings/store refused_in_run); set before
        # any run starts.
        run_failed: Callable[[dict[str, Any]], None] | None = None
        controllers: dict[str, Any] | None = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.controllers = {}

        def running(self):
            return (
                any(item.running() for item in self.controllers.values())
                if self.controllers is not None
                else super().running()
            )

        def controller(self, identity):
            assert self.controllers is not None  # Only the owner hands out controllers.
            if identity not in self.controllers:
                item = object.__new__(ManualJobs)
                item.workspace, item.root, item.lock, item.allow_providers = (
                    self.workspace,
                    self.root,
                    self.lock,
                    self.allow_providers,
                )
                item.jobs, item.worker, item.process = self.jobs, None, None
                item.run_failed = self.run_failed
                item.stopping, item.active = threading.Event(), ""
                self.controllers[identity] = item
            return self.controllers[identity]

        def answer(self, identity, token, approved):
            if self.controllers is not None:
                return self.controller(identity).answer(identity, token, approved)
            with self.lock:
                job = self.jobs[identity]
                prompt = job.get("approval")
                if (
                    not prompt
                    or prompt["token"] != token
                    or identity != self.active
                    or type(approved) is not bool
                    or self.stopping.is_set()
                ):
                    raise ValueError(
                        "This approval is no longer pending. Prepare a new estimate."
                    )
                if approved and (
                    job.get("dazedtl_preapproval") or prompt.get("kind") == "batch"
                ):
                    # Persist before the worker can send, including separately
                    # approved speaker requests inside a Batch preparation.
                    previous = deepcopy(job)
                    job["dazedtl_approved"] = True
                    job["estimate"] = prompt["detail"]
                    try:
                        if job.get("mode") == "batch" and prompt.get("kind") == "batch":
                            from .batch_continuation import APPROVAL, binding

                            root = self.folder(identity)
                            plan = json.loads(system.read_bytes(root / "plan.json"))
                            job[APPROVAL] = binding(
                                root, job, plan, quote=prompt["detail"]
                            )
                        self.save(job)
                    except Exception:
                        job.clear()
                        job.update(previous)
                        raise
                result = super().answer(identity, token, approved)
                if not approved and temporary(job):
                    self.discard_preparation(identity)
                return result

        def discard_preparation(self, identity):
            if self.controllers is not None:
                return self.controller(identity).discard_preparation(identity)
            with self.lock:
                job = self.jobs[identity]
                if not discardable(job, self.folder(identity)):
                    raise ValueError(
                        "This run may contain approved work. Keep it for recovery."
                    )
                job["dazedtl_discard_preparation"] = True
                self.save(job)
                if self.running():
                    self.stop(identity)
                else:
                    discard(job, self.folder(identity))
                    self.jobs.pop(identity)

        def save(self, job):
            if self.temporary_preparation and "dazedtl_preapproval" not in job:
                job["dazedtl_preapproval"] = True
            return super().save(job)

        def stop(self, identity):
            if (
                not getattr(self, "_closing", False)
                and self.jobs[identity].get("mode") == "batch"
            ):
                self.jobs[identity]["dazedtl_batch_stopped"] = True
                self.save(self.jobs[identity])
            return (
                self.controller(identity).stop(identity)
                if self.controllers is not None
                else super().stop(identity)
            )

        def resume(self, identity):
            if temporary(self.jobs[identity]):
                raise ValueError(
                    "Unapproved preparation cannot be resumed. Prepare a fresh estimate."
                )
            return (
                self.controller(identity).resume(identity)
                if self.controllers is not None
                else super().resume(identity)
            )

        def resume_batch(self, identity, recovery):
            return (
                self.controller(identity).resume_batch(identity, recovery)
                if self.controllers is not None
                else super().resume_batch(identity, recovery)
            )

        def consume_batch(self, identity):
            from .process_view import saved

            with self.lock:
                job = self.jobs[identity]
                if (
                    job.get("mode") != "batch"
                    or saved(self.folder(identity), "batch_state.json").get("status")
                    != "fetched"
                ):
                    raise ValueError(
                        "Collect this Batch’s responses before saving results."
                    )
                from .batch_control import require_complete_submission

                require_complete_submission(self.folder(identity))
                job.pop("dazedtl_continue_batch", None)
                job["dazedtl_consume_only"] = True
                self.save(job)
                return self.resume(identity)

        def continue_batch(self, identity, *, explicit=False):
            from .batch_continuation import prepare_continuation

            with self.lock:
                job = self.jobs[identity]
                running = (
                    self.controller(identity).running()
                    if self.controllers is not None
                    else super().running()
                )
                if running or job.get("status") not in {
                    "stopped",
                    "interrupted",
                    "failed",
                }:
                    raise ValueError("This Batch already has a running worker.")
                root = self.folder(identity)
                prepare_continuation(
                    root,
                    job,
                    json.loads(system.read_bytes(root / "plan.json")),
                    explicit=explicit,
                )
                self.save(job)
                return self.resume(identity)

        def close(self):
            if self.controllers is None:
                self._closing = True
                try:
                    return super().close()
                finally:
                    self._closing = False
            for identity, item in list(self.controllers.items()):
                job = self.jobs.get(identity)
                if job and temporary(job) and discardable(job, self.folder(identity)):
                    item.discard_preparation(identity)
                item.close()

        def load_saved(self):
            super().load_saved()
            for identity, job in list(self.jobs.items()):
                if temporary(job) and discardable(job, self.folder(identity)):
                    discard(job, self.folder(identity))
                    self.jobs.pop(identity)
                    continue
                if canceled_before_submission(job, self.folder(job["id"])):
                    # Interpret the historical defect without rewriting saved user records.
                    job.update(status="canceled", phase="canceled", approval=None)

        def _event(self, job, event):
            with self.lock:
                args = event.get("args", [])
                if (
                    event.get("event") == "receipt"
                    and len(args) >= 2
                    and job.get("mode") in {"translate", "batch"}
                ):
                    from .process_view import record_receipt

                    record_receipt(job, args[0], args[1])
                failed = (
                    event.get("event") == "finished"
                    and len(args) >= 2
                    and args[0] is False
                )
                if (
                    failed
                    and args[1] == SPEAKER_CANCELLATION
                    and not self.stopping.is_set()
                ):
                    current = {**job, "message": SPEAKER_CANCELLATION}
                    if canceled_before_submission(
                        current, self.folder(job["id"]), finishing=True
                    ):
                        job["phase"] = "canceled"
                from .process_view import batch_refusal

                refused = (
                    failed
                    and job.get("mode") == "batch"
                    and job.get("phase") != "canceled"
                    and not self.stopping.is_set()
                    and batch_refusal(self.folder(job["id"]))
                )
                if refused:
                    # The provider refused the run's thinking effort, which
                    # every request carries: the run says so once, as Live.
                    event = {**event, "args": [False, refused, *args[2:]]}
                elif failed and args[1] == ENGINE_FAILURE and job.get("errors"):
                    name, error = next(iter(job["errors"].items()))
                    files = len(job["errors"])
                    event = {
                        **event,
                        "args": [
                            False,
                            (f"{files} files failed. " if files > 1 else "")
                            + f"{name}: {error}",
                            *args[2:],
                        ],
                    }
                return super()._event(job, event)

        def receipts(self, job):
            from .process_view import file_receipts

            return file_receipts(job)

        def _launch(self, job, resume):
            if job.get("phase") == "canceled":
                job["phase"] = "preparing"
            return super()._launch(job, resume)

        def _run(self, identity, resume):
            from .estimate_pricing import start, stop

            folder = str(self.folder(identity))
            job = self.jobs.get(identity) or {}
            if job.get("mode") == "estimate" and allow_providers:
                # Its startup, seconds on Windows, overlaps the estimate.
                try:
                    plan = json.loads(system.read_bytes(Path(folder) / "plan.json"))
                    if plan.get("dazedtl_claude_count") is not False:
                        process = start(folder, workspace, plan)
                        if process is not None:
                            with warm_lock:
                                warm_counts[folder] = process
                except OSError, ValueError:
                    pass
            try:
                result = super()._run(identity, resume)
                self.failed_run(identity)
                return result
            finally:
                with warm_lock:
                    stop(warm_counts.pop(folder, None))
                with self.lock:
                    job = self.jobs.get(identity)
                    if (
                        job
                        and temporary(job)
                        and job.get("dazedtl_discard_preparation")
                        and discardable(job, self.folder(identity))
                    ):
                        discard(job, self.folder(identity))
                        self.jobs.pop(identity)

        def failed_run(self, identity):
            """Hands a failed API run's frozen connection, model and thinking
            effort, with the message it ended with and when, to
            ``run_failed``."""
            with self.lock:
                job = self.jobs.get(identity)
                if (
                    not self.run_failed
                    or not job
                    or job.get("status") != "failed"
                    or job.get("mode") not in {"translate", "batch"}
                ):
                    return
                try:
                    plan = json.loads(
                        system.read_bytes(self.folder(identity) / "plan.json")
                    )
                except OSError, ValueError:
                    return  # The run's own outcome stands.
                frozen = plan["settings"]
                self.run_failed(
                    {
                        "key_name": plan["key_name"],
                        "protocol": frozen["API_PROVIDER"],
                        "endpoint": frozen["api"],
                        "organization": frozen.get("organization", ""),
                        "model": frozen["model"],
                        "thinkingEffort": (
                            plan.get("dazedtl_request_policy") or {}
                        ).get("thinkingEffort"),
                        "message": job.get("message"),
                        "ended": job.get("updated"),
                    }
                )

        @contextmanager
        def selected_workflow(self, identity, files):
            previous = self.workflow_selection
            self.workflow_selection = (identity, tuple(files))
            try:
                yield
            finally:
                self.workflow_selection = previous

        def start(self, source, engine, files, *args, **kwargs):
            if self.controllers is not None:
                with self.lock:
                    item = self.controller("preparing")
                    if item.running():
                        raise ValueError(
                            "A run is being prepared. Wait for its saved workspace."
                        )
                    item.request_policy, item.workflow_selection, item.continuation = (
                        self.request_policy,
                        self.workflow_selection,
                        self.continuation,
                    )
                    item.reserved_sources = self.reserved_sources
                    item.source_versions = self.source_versions
                    item.reused_names = self.reused_names
                    item.temporary_preparation = self.temporary_preparation
                    item.claude_count = self.claude_count
                    item.speaker_scan = self.speaker_scan
                    item.scanned_speakers = self.scanned_speakers
                    item.adopt_from = self.adopt_from
                    result = item.start(source, engine, files, *args, **kwargs)
                    self.controllers[result["id"]] = self.controllers.pop("preparing")
                    self.active = result["id"]
                    return result
            if self.workflow_selection is not None:
                identity, selected = self.workflow_selection
                if (kwargs.get("workflow") or {}).get("id") != identity or set(
                    selected
                ) - set(files):
                    raise ValueError(
                        "The selected files no longer match this project's phase."
                    )
                files = list(selected)
            return super().start(source, engine, files, *args, **kwargs)

        def _snapshot_context(self, directory, plan, workspace=None):
            super()._snapshot_context(directory, plan, workspace)
            if self.reused_names:
                from .speaker_results import seed

                seed(directory, plan, self.reused_names)
            if self.source_versions is not None:
                plan["dazedtl_source_versions"] = deepcopy(self.source_versions)
            if self.continuation:
                plan["dazedtl_continuation"] = deepcopy(self.continuation)
            if self.reserved_sources:
                plan["dazedtl_reserved_sources"] = deepcopy(self.reserved_sources)
            if not self.claude_count:
                plan["dazedtl_claude_count"] = False
            if self.speaker_scan:
                plan["scan_speakers"] = True
            if self.scanned_speakers is not None:
                plan["scanned_speakers"] = deepcopy(self.scanned_speakers)
            if self.adopt_from is not None:
                seed_requests(directory, plan, Path(self.adopt_from))
            if self.request_policy is not None:
                if self.request_policy["model"] != plan["settings"]["model"]:
                    raise ValueError(
                        "The selected model changed before creating the run."
                    )
                # Included before the native plan hash is computed and launch starts.
                plan["dazedtl_request_policy"] = deepcopy(self.request_policy)
            stage_originals(directory, plan, self.request_policy)

    return ManualJobs(workspace, lock, allow_providers=allow_providers)
