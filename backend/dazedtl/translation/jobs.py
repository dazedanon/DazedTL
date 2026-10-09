"""Durable project-owned runs and bounded worker lifecycle."""

import hashlib
import hmac
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.diagnostics import FOLDER
from dazedtl.storage import WorkspaceError, WorkspaceLock, write_bytes, write_json

from .files import digest, read_json
from .results import Results


def now():
    return datetime.now(UTC).isoformat()


def declined_units(job):
    return sum(
        count
        for identity, count in job["unit_counts"].items()
        if job["states"][identity]["state"] == "declined"
    )


def declined_message(job):
    lines = declined_units(job)
    return f"{lines} declined {'line needs' if lines == 1 else 'lines need'} another translator."


class RunStore:
    def __init__(self, workspace, owner_alive=lambda: True):
        self.workspace = Path(workspace)
        self.root = self.workspace / "translation/runs"
        self.owner_alive = owner_alive
        self.warnings = []

    def folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("Choose a saved run.")
        path = self.root / identity
        if path.is_symlink() or not path.is_dir():
            raise ValueError("The saved run is unavailable.")
        return path

    def record(self, identity, project_id=None):
        folder = self.folder(identity)
        job = read_json(folder / "job.json")
        if not isinstance(job, dict) or job.get("version") != 1:
            raise ValueError("Unsupported saved run record.")
        if (
            job.get("id") != identity
            or project_id is not None
            and job.get("project_id") != project_id
        ):
            raise ValueError("This run belongs to another project.")
        if (
            not isinstance(job.get("states"), dict)
            or not isinstance(job.get("unit_counts"), dict)
            or not isinstance(job.get("fingerprints"), dict)
        ):
            raise ValueError("The saved run index is incomplete.")
        if set(job["states"]) != set(job["unit_counts"]) or set(job["states"]) != set(
            job["fingerprints"]
        ):
            raise ValueError(
                "The saved run index no longer matches its request states."
            )
        if job["kind"] == "operation" and "action" not in job:
            plan = read_json(folder / "plan.json")
            if (
                not isinstance(plan, dict)
                or plan.get("version") != 1
                or digest(plan) != job["plan_sha256"]
            ):
                raise ValueError("The saved operation plan changed.")
            job["action"] = plan.get("action")
            # Enrich older indexes once, retaining their original timestamps and plan.
            write_json(folder / "job.json", job)
        return job

    def load(self, identity, project_id=None):
        folder = self.folder(identity)
        job = self.record(identity, project_id)
        plan = read_json(folder / "plan.json")
        if (
            not isinstance(plan, dict)
            or plan.get("version") != 1
            or digest(plan) != job["plan_sha256"]
        ):
            raise ValueError("The saved request plan changed. It cannot be executed.")
        return job, plan

    def save(self, job):
        job["updated"] = now()
        write_json(self.folder(job["id"]) / "job.json", job)

    def create(self, project_id, plan, quote=None):
        identity = uuid.uuid4().hex
        folder = self.root / identity
        folder.mkdir(parents=True)
        write_json(folder / "plan.json", plan)
        states = {}
        if plan["kind"] == "translation":
            results = Results(plan["source"])
            for request in plan["requests"]:
                states[request["id"]] = {
                    "state": "accepted" if results.get(request) else "pending",
                    "message": "",
                }
        job = {
            "version": 1,
            "id": identity,
            "project_id": project_id,
            "source": plan["source"],
            "kind": plan["kind"],
            "label": plan.get("label", "Translation"),
            "created": now(),
            "updated": now(),
            "status": "ready",
            "message": "Ready",
            "plan_sha256": digest(plan),
            "configuration_sha256": digest(plan["configuration"])
            if "configuration" in plan
            else None,
            "states": states,
            "mode": plan.get("configuration", {}).get("mode"),
            "action": plan.get("action") if plan["kind"] == "operation" else None,
            "finishes": plan.get("finishes"),
            "unit_counts": {
                row["id"]: len(row["sources"]) for row in plan.get("requests", [])
            },
            "fingerprints": {
                row["id"]: row["fingerprint"] for row in plan.get("requests", [])
            },
            "qa_requests": [
                {
                    "id": row["id"],
                    "index": index,
                    "notes": len(row["context"].get("qa_notes", {})),
                }
                for index, row in enumerate(plan.get("requests", []))
                if row["context"].get("qa_notes")
            ],
            "quote": quote,
            "approval_token": uuid.uuid4().hex if quote is not None else "",
            "approved": False,
            "batches": [],
            "result": None,
            "usage": {},
        }
        if states and all(item["state"] == "accepted" for item in states.values()):
            job.update(
                status="complete",
                message="All requested translations are already saved.",
            )
        self.save(job)
        return job

    def authorize(self, job, *, in_app=False):
        if job["quote"] is None:
            raise ValueError("API authorization requires a concrete quote.")
        key = self.root.parent / "approval.key"
        if key.is_symlink():
            raise ValueError("The approval key must be a regular workspace file.")
        if not key.exists():
            write_bytes(key, secrets.token_bytes(32))
        receipt = {
            "run_id": job["id"],
            "project_id": job["project_id"],
            "plan_sha256": job["plan_sha256"],
            "quote_sha256": digest(job["quote"]),
            "approved_at": now(),
        }
        receipt["signature"] = hmac.new(
            key.read_bytes(), digest(receipt).encode("ascii"), hashlib.sha256
        ).hexdigest()
        write_json(self.folder(job["id"]) / "authorization.json", receipt)
        # The assistant learns of an approval given in the app only when it
        # next reaches the project, so Progress reminds the user until then.
        if in_app:
            job["app_approved_at"] = receipt["approved_at"]
        job["approved"] = True
        self.save(job)

    def authorized(self, job):
        path = self.folder(job["id"]) / "authorization.json"
        key = self.root.parent / "approval.key"
        if not path.is_file() or not key.is_file() or key.is_symlink():
            return False
        receipt = read_json(path, limit=4096)
        signature = receipt.pop("signature", "")
        expected = {
            "run_id": job["id"],
            "project_id": job["project_id"],
            "plan_sha256": job["plan_sha256"],
            "quote_sha256": digest(job["quote"]),
            "approved_at": receipt.get("approved_at"),
        }
        return (
            receipt == expected
            and isinstance(signature, str)
            and hmac.compare_digest(
                signature,
                hmac.new(
                    key.read_bytes(), digest(receipt).encode("ascii"), hashlib.sha256
                ).hexdigest(),
            )
        )

    def list(self, project_id):
        result = []
        self.warnings = []
        for path in self.root.glob("*/job.json"):
            if path.is_symlink() or path.parent.is_symlink():
                continue
            try:
                value = self.record(path.parent.name)
            except ValueError, OSError, KeyError, TypeError:
                self.warnings.append(
                    "Saved run "
                    + path.parent.name
                    + " could not be read; its files were retained."
                )
                continue
            if project_id is None or value.get("project_id") == project_id:
                result.append(value)
        return sorted(result, key=lambda value: value["created"], reverse=True)

    def stopped(self, identity):
        return not self.owner_alive() or (self.folder(identity) / "stop.json").exists()

    def cancel_requested(self, identity):
        return (self.folder(identity) / "cancel.json").exists()

    def stop(self, identity, project_id):
        self.load(identity, project_id)
        write_json(self.folder(identity) / "stop.json", {"requested": now()})

    def settled(self, job):
        """The run with any declined request another run has since translated
        read as accepted. It checks only that the saved result exists, so
        state polls stay cheap; the result itself is validated when read."""
        done = [
            identity
            for identity, row in job["states"].items()
            if row["state"] == "declined"
            and (
                Path(job["source"])
                / Results(job["source"]).relative(
                    {"fingerprint": job["fingerprints"][identity]}
                )
            ).is_file()
        ]
        if not done:
            return job
        value = {
            **job,
            "states": {
                **job["states"],
                **{identity: {"state": "accepted", "message": ""} for identity in done},
            },
        }
        if all(row["state"] == "accepted" for row in value["states"].values()):
            value.update(
                status="complete",
                message="Translations saved. Injection and runtime QA remain separate.",
            )
        else:
            value["message"] = declined_message(value)
        return value

    def view(self, job):
        job = self.settled(job)
        counts = {
            state: sum(row["state"] == state for row in job["states"].values())
            for state in (
                "pending",
                "sending",
                "queued",
                "accepted",
                "declined",
                "failed",
                "uncertain",
            )
        }
        return {
            key: job[key]
            for key in (
                "id",
                "project_id",
                "kind",
                "label",
                "status",
                "message",
                "created",
                "updated",
                "quote",
                "approval_token",
                "approved",
                "result",
                "usage",
            )
        } | {
            # Retired terminal labels do not alter stored receipts or retry guards.
            "status": job["status"]
            if job["status"]
            in {
                "ready",
                "running",
                "waiting",
                "complete",
                "failed",
                "uncertain",
                "stopped",
                "interrupted",
                "canceled",
            }
            else "failed",
            "mode": job["mode"],
            "action": job.get("action"),
            "counts": counts,
            "approved": self.authorized(job),
            "app_approved_at": job.get("app_approved_at"),
            "units": sum(job["unit_counts"].values()),
            "accepted_units": sum(
                count
                for identity, count in job["unit_counts"].items()
                if job["states"][identity]["state"] == "accepted"
            ),
            "declined_units": declined_units(job),
            "finishes": job.get("finishes"),
            "requests": len(job["states"]),
            "batches": [
                {
                    key: chunk.get(key)
                    for key in ("id", "state", "api_status", "counts", "cancel_error")
                }
                for chunk in job["batches"]
            ],
            "qa_requests": job.get("qa_requests", []),
            "stop_requested": self.stopped(job["id"]),
            "can_cancel_provider": (job.get("quote") or {}).get("provider")
            != "openrouter",
            "cancel_requested": self.cancel_requested(job["id"]),
            "issues": [
                {"id": key, **value}
                for key, value in job["states"].items()
                if value["state"] in {"failed", "uncertain"}
            ],
        }

    def overlapping(self, project_id, fingerprints, exclude=None):
        for job in self.list(project_id):
            if job["id"] == exclude or job["kind"] != "translation":
                continue
            for identity, fingerprint in job["fingerprints"].items():
                if fingerprint in fingerprints and job["states"][identity]["state"] in {
                    "sending",
                    "queued",
                    "uncertain",
                }:
                    raise ValueError(
                        "Matching work is still in flight or uncertain in run "
                        + job["id"]
                        + ". Reconcile that run first."
                    )
        if self.warnings:
            raise ValueError(
                "An unreadable saved run must be recovered before submitting more work."
            )


class Jobs:
    def __init__(self, workspace, allow_providers):
        self.store = RunStore(workspace)
        self.allow_providers = allow_providers
        self.processes = {}
        self.owner_token = uuid.uuid4().hex
        self.owner_path = Path(workspace) / "translation/owner.json"
        write_json(self.owner_path, {"pid": os.getpid(), "token": self.owner_token})
        # The app owns workers. A previous process must not be restarted implicitly.
        for value in self.store.list(None):
            if value["status"] in {"running", "waiting"}:
                value.update(
                    status="interrupted",
                    message="The app closed. Resume to reconcile saved work.",
                )
                self.store.save(value)

    def running(self, project_id=None, kind=None):
        """Whether a run or operation, or only one of the given kind, holds
        the project."""
        self.reconcile()
        for identity in self.processes:
            record = self.store.record(identity)
            if (project_id is None or record["project_id"] == project_id) and (
                kind is None or record["kind"] == kind
            ):
                return True
        for job in self.store.list(project_id):
            if job["status"] not in {"running", "waiting", "interrupted"}:
                continue
            if kind is not None and job["kind"] != kind:
                continue
            try:
                lock = WorkspaceLock(self.store.folder(job["id"]))
            except WorkspaceError:
                return True
            else:
                lock.close()
        return False

    def reconcile(self):
        for identity, process in list(self.processes.items()):
            if process.poll() is None:
                continue
            self.processes.pop(identity)
            job, _plan = self.store.load(identity)
            if job["status"] in {"running", "waiting"}:
                job.update(
                    status="interrupted",
                    message="The worker exited before completion. Resume to reconcile receipts before sending more work.",
                )
                self.store.save(job)

    def start(self, identity, project_id):
        self.reconcile()
        job, plan = self.store.load(identity, project_id)
        if identity in self.processes or job["status"] == "complete":
            return self.store.view(job)
        if self.running(project_id):
            raise ValueError(
                "Wait for this project's current operation to reach a checkpoint."
            )
        try:
            lock = WorkspaceLock(self.store.folder(identity))
        except WorkspaceError as exc:
            raise ValueError(
                "A previous worker is still finishing this run. Wait for its saved checkpoint."
            ) from exc
        else:
            lock.close()
        if plan["kind"] == "translation":
            if plan["configuration"]["mode"] == "agent":
                raise ValueError(
                    "Use the starting prompt and import the agent's saved results."
                )
            if not self.allow_providers:
                raise ValueError("Provider execution is disabled in this app session.")
            if not self.store.authorized(job):
                raise ValueError(
                    "Review and approve this run's exact estimate before execution."
                )
            self.store.overlapping(
                project_id,
                {row["fingerprint"] for row in plan["requests"]},
                exclude=identity,
            )
        if job["status"] == "uncertain":
            raise ValueError(
                "Reconcile the uncertain provider submission before resuming."
            )
        stop = self.store.folder(identity) / "stop.json"
        stop.unlink(missing_ok=True)
        job.update(
            status="running",
            message="Starting…"
            if job["status"] == "ready"
            else "Resuming from saved checkpoints.",
        )
        self.store.save(job)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH",
                "LOCALAPPDATA",
                "HOME",
                "USERPROFILE",
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_ATTR_NOSYSTEM",
                FOLDER,
            }
        }
        environment.update(
            PYTHON_DOTENV_DISABLED="1",
            PYTHONNOUSERSITE="1",
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        arguments = [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            "-B",
            str(Path(__file__).with_name("worker.py")),
            "--workspace",
            str(self.store.workspace),
            "--run",
            identity,
            "--owner-pid",
            str(os.getpid()),
            "--owner-token",
            self.owner_token,
        ]
        try:
            # Only structured job records cross into the UI; raw provider output is never logged.
            self.processes[identity] = subprocess.Popen(
                arguments,
                cwd=self.store.folder(identity),
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
        except OSError:
            job.update(
                status="failed",
                message="The worker could not start; no requests were submitted.",
            )
            self.store.save(job)
            raise
        return self.store.view(job)

    def close(self):
        self.owner_path.unlink(missing_ok=True)
        for identity in self.processes:
            job, _plan = self.store.load(identity)
            self.store.stop(identity, job["project_id"])
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and any(
            process.poll() is None for process in self.processes.values()
        ):
            time.sleep(0.05)
        for process in self.processes.values():
            if process.poll() is None:
                # The whole tree, or a Git command the worker waits on outlives it.
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGTERM)
        self.reconcile()
