"""One isolated project operation or translation run; no UI or credential output."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazedtl.diagnostics import record_crashes, watch_action, worker_failure

if __name__ == "__main__":
    # Standard error is discarded, so a crash leaves only this record.
    record_crashes("run")
from dazedtl.actions import stopped_note
from dazedtl.compatibility.translation import (
    TranslationEngine,
    TranslationProvider,
    explained,
)
from dazedtl.settings.execution import worker_secret
from dazedtl.storage import WorkspaceError, WorkspaceLock
from dazedtl.translation import progress_report
from dazedtl.translation.compilation import verify_compilation
from dazedtl.translation.files import verify_evidence
from dazedtl.translation.jobs import RunStore
from dazedtl.translation.operations import execute, lifecycle, require_baseline
from dazedtl.translation.ownership import alive
from dazedtl.translation.project import ProjectWorkspace, scope
from dazedtl.translation.runner import Runner


def every(seconds, check):
    """``check`` at most once per ``seconds``; once true it stays true.

    Backups ask whether to stop for every file and block they read, and on
    Windows each answer lists every running process to find the app.
    """
    last, answer = -seconds, False

    def checked():
        nonlocal last, answer
        now = time.monotonic()
        if not answer and now - last >= seconds:
            # Set first, so the backup's other threads skip this round.
            last = now
            answer = bool(check())
        return answer

    return checked


def run(workspace, identity, owner_pid, owner_token):
    store = RunStore(
        workspace, owner_alive=lambda: alive(workspace, owner_pid, owner_token)
    )
    try:
        lock = WorkspaceLock(store.folder(identity))
    except WorkspaceError:
        return
    try:
        if not alive(workspace, owner_pid, owner_token):
            return
        run_locked(workspace, identity, store)
    finally:
        lock.close()


def run_locked(workspace, identity, store):
    job, plan = store.load(identity, reuse=True)
    engine = TranslationEngine(workspace / "engine")
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1", DAZEDTL_DESKTOP_WORKSPACE=str(engine.profile)
    )
    try:
        with engine.context():
            if plan["kind"] == "operation":
                if plan.get("evidence"):
                    verify_evidence(plan["source"], plan["evidence"])
                last_update = 0.0
                progressed = watch_action(plan["action"])
                stopped = every(0.2, lambda: store.stopped(identity))

                def update(message):
                    nonlocal last_update
                    progressed()
                    if stopped():
                        raise InterruptedError(stopped_note(plan["action"]))
                    if time.monotonic() - last_update >= 0.5:
                        job["message"] = str(message)[:1000]
                        store.save(job)
                        last_update = time.monotonic()

                try:
                    result = execute(
                        engine,
                        workspace,
                        job,
                        plan,
                        stopped,
                        update,
                    )
                finally:
                    # Ending also closes a stall it recorded.
                    progressed()
                # Native dataclasses can contain Paths; public records contain only JSON.
                result = json.loads(
                    json.dumps(
                        result,
                        default=lambda value: (
                            str(value)
                            if isinstance(value, Path)
                            else (_ for _ in ()).throw(TypeError())
                        ),
                    )
                )
                job.update(
                    status="complete",
                    message=plan["label"] + " completed.",
                    result=result,
                )
                store.save(job)
                return
            if not store.authorized(job) or plan["configuration"]["mode"] not in {
                "live",
                "batch",
            }:
                raise ValueError("This worker requires an approved API run.")

            compiled = False

            def current():
                nonlocal compiled
                project = ProjectWorkspace(plan["source"])
                if scope(project.read()["options"]) != plan["scope_sha256"]:
                    raise ValueError(
                        "Project scope changed. Preserve these results and prepare a new remaining-work quote."
                    )
                verify_evidence(project.root, plan["evidence"])
                engine.verify_bindings(project.root, plan["original_bindings"])
                require_baseline(
                    engine,
                    project.root,
                    plan["options"],
                    lifecycle(workspace, job["project_id"]),
                )
                if not compiled:
                    verify_compilation(engine, plan)
                    compiled = True

            last_report = 0.0

            def progress(force=False, started=False):
                nonlocal last_report
                if not force and time.monotonic() - last_report < 10:
                    return
                progress_report.refresh(
                    workspace, job["project_id"], engine, plan, started=started
                )
                last_report = time.monotonic()

            provider = TranslationProvider(
                plan["configuration"],
                worker_secret(workspace, plan["configuration"]),
                receipt_root=store.folder(identity),
            )
            # A worker restarted only to cancel the provider batch does not
            # answer anything the assistant is waiting on.
            if not store.cancel_requested(identity):
                progress(True, started=True)
            states = None
            recovered = False
            while True:
                runner = Runner(store, identity, provider, current, progress)
                # A Batch can wait for hours, and recovery rereads every saved
                # response and result, so only the first poll recovers.
                runner.step(recover=not recovered)
                recovered = True
                if runner.job["states"] != states:
                    progress(True)
                    states = runner.job["states"]
                else:
                    # Republishing the report reads every saved result, and a
                    # Batch can wait for hours, so a poll that changed no
                    # request only checks that the sources still match.
                    verify_evidence(plan["source"], plan["evidence"])
                    engine.verify_bindings(plan["source"], plan["original_bindings"])
                if runner.job["status"] != "waiting":
                    return
                for _ in range(25):
                    if store.stopped(identity):
                        break
                    time.sleep(0.2)
    except InterruptedError as exc:
        job = store.record(identity)
        job.update(status="stopped", message=str(exc))
        store.save(job)
    except Exception as exc:  # noqa: BLE001
        if not explained(exc):
            worker_failure(exc, plan.get("action") or plan["kind"])
        job = store.record(identity)
        # Provider exceptions can contain request bodies or auth details; retain only their class.
        message = engine.error_message(exc)
        job.update(status="failed", message=message)
        store.save(job)
    finally:
        if plan["kind"] == "translation":
            ended(engine, workspace, job["project_id"], plan)


def ended(engine, workspace, project_id, plan):
    """Saves the assistant's work waiting in the game as a checkpoint once
    its translation run finishes, stops or fails."""
    try:
        with engine.context():
            progress_report.checkpoint(engine, workspace, project_id, plan["source"])
    except Exception as exc:  # noqa: BLE001
        # The run's own outcome stands; the next report or write saves the
        # work instead.
        worker_failure(exc, "checkpoint")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    parser.add_argument("--owner-token", required=True)
    args = parser.parse_args()
    run(args.workspace.resolve(), args.run, args.owner_pid, args.owner_token)
