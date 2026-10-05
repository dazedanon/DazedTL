"""One isolated project operation or translation run; no UI or credential output."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazedtl.compatibility.translation import TranslationEngine, TranslationProvider
from dazedtl.settings.execution import worker_secret
from dazedtl.storage import WorkspaceError, WorkspaceLock, write_json
from dazedtl.translation.compilation import verify_compilation
from dazedtl.translation.files import project_path, read_json, verify_evidence
from dazedtl.translation.jobs import RunStore
from dazedtl.translation.operations import execute, lifecycle, require_baseline
from dazedtl.translation.ownership import alive
from dazedtl.translation.project import WORK, ProjectWorkspace, scope
from dazedtl.translation.results import Results
from dazedtl.translation.runner import Runner


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
    job, plan = store.load(identity)
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

                def update(message):
                    nonlocal last_update
                    if store.stopped(identity):
                        raise InterruptedError(
                            "Stopped at an operation checkpoint; completed writes and backups were retained."
                        )
                    if time.monotonic() - last_update >= 0.5:
                        job["message"] = str(message)[:1000]
                        store.save(job)
                        last_update = time.monotonic()

                result = execute(
                    engine,
                    workspace,
                    job,
                    plan,
                    lambda: store.stopped(identity),
                    update,
                )
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

            checked_compiler = None

            def current():
                nonlocal checked_compiler
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
                if checked_compiler != engine.compiler_fingerprint():
                    checked_compiler = verify_compilation(engine, plan)

            last_report = 0.0

            def progress(force=False):
                nonlocal last_report
                if not force and time.monotonic() - last_report < 10:
                    return
                verify_evidence(plan["source"], plan["evidence"])
                engine.verify_bindings(plan["source"], plan["original_bindings"])
                report_path = project_path(
                    plan["source"], WORK + "/progress-report.json", exists=False
                )
                report: dict[str, Any] = (
                    read_json(report_path) if report_path.exists() else {"phases": {}}
                )
                relative, changed = Results(plan["source"]).export(plan)
                report.update(text=relative, inputs=list(plan["evidence"]))
                if changed:
                    report.update(
                        phase="translation",
                        blocker="",
                        next_action="Continue saved work, then fit, inject and perform QA.",
                    )
                    report.setdefault("phases", {}).update(
                        translation="active",
                        injection="pending",
                        qa="pending",
                        patch="pending",
                    )
                engine.progress(plan["source"], plan["options"], report)
                write_json(report_path, report)
                last_report = time.monotonic()

            provider = TranslationProvider(
                plan["configuration"],
                worker_secret(workspace, plan["configuration"]),
                receipt_root=store.folder(identity),
            )
            while True:
                runner = Runner(store, identity, provider, current, progress)
                runner.step()
                progress(True)
                if runner.job["status"] != "waiting":
                    return
                for _ in range(25):
                    if store.stopped(identity):
                        break
                    time.sleep(0.2)
    except InterruptedError as exc:
        job, _plan = store.load(identity)
        job.update(status="stopped", message=str(exc))
        store.save(job)
    except Exception as exc:  # noqa: BLE001
        job, _plan = store.load(identity)
        # Provider exceptions can contain request bodies or auth details; retain only their class.
        message = engine.error_message(exc)
        job.update(status="failed", message=message)
        store.save(job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--run", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    parser.add_argument("--owner-token", required=True)
    args = parser.parse_args()
    run(args.workspace.resolve(), args.run, args.owner_pid, args.owner_token)
