"""Collect saved Batches and their frozen, bounded clarification allowance."""

import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime

from dazedtl.compatibility import batch_control
from dazedtl.compatibility.batch_continuation import BatchContinuationError
from dazedtl.compatibility.openrouter_batch import ResultsUnavailable
from dazedtl.compatibility.preparations import temporary
from dazedtl.compatibility.process_view import saved


class BatchMonitor:
    def __init__(self, guided):
        self.guided = guided
        self.backend = guided.backend
        self.stopping = threading.Event()
        self.worker = None
        self.busy = set()
        self.consumed = set()
        self.settled = set()
        self.views = {}

    def start(self):
        if self.backend.allow_providers and self.worker is None:
            self.worker = threading.Thread(
                target=self._run, name="saved-batch-monitor", daemon=True
            )
            self.worker.start()

    def close(self):
        # An in-flight read may finish later, but cannot commit or launch work.
        with self.backend.lock:
            self.stopping.set()
        if self.worker:
            self.worker.join(timeout=1)

    def _run(self):
        while not self.stopping.is_set():
            self.tick()
            self.stopping.wait(30)

    def tick(self):
        with self.backend.lock:
            identities = list(self.backend.manual.jobs)
        for identity in identities:
            if self.stopping.is_set():
                return
            try:
                self.check(identity)
            except BatchContinuationError as error:
                with self.backend.lock:
                    self.views[identity] = {"state": "blocked", "message": str(error)}
            except ResultsUnavailable as error:
                with self.backend.lock:
                    self.views[identity] = {"state": "blocked", "message": str(error)}
                    job = self.backend.manual.jobs.get(identity)
                    if job and not self.backend.manual.controller(identity).running():
                        job["dazedtl_batch_results_error"] = str(error)
                        self.backend.manual.save(job)
            except Exception:
                # Provider errors can contain credentials; keep background
                # feedback fixed and retain the last successful observation.
                with self.backend.lock:
                    self.views[identity] = {
                        **self.views.get(identity, {}),
                        "state": "error",
                        "message": "Could not check or collect this Batch. Check its saved connection in Settings; the app will retry automatically.",
                    }
            finally:
                with self.backend.lock:
                    self.busy.discard(identity)

    def _owned(self, identity):
        plan = self.backend.saved_run_configuration(identity)
        native_id = (plan.get("workflow") or {}).get("id")
        native = self.backend.workflows.projects.get(native_id)
        owner = next(
            (
                project
                for project in self.guided.projects.data["projects"]
                if project.get("backend_id") == native_id
            ),
            None,
        )
        if (
            not native
            or not owner
            or owner["source"] != native["source"]
            or plan.get("batch_link")
        ):
            raise ValueError("The original Batch owner is unavailable.")
        return plan

    def _superseded(self, identity, plan):
        job = self.backend.manual.jobs[identity]
        for other_id, other in self.backend.manual.jobs.items():
            if (
                other_id == identity
                or other.get("created", "") <= job.get("created", "")
                or not other.get("dazedtl_approved")
                or other.get("mode") not in {"batch", "translate"}
                or not set(other.get("files", [])) & set(job.get("files", []))
            ):
                continue
            other_plan = self.backend.saved_run_configuration(other_id)
            if (other_plan.get("workflow") or {}).get("id") == (
                plan.get("workflow") or {}
            ).get("id"):
                return True
        return False

    @contextmanager
    def _commit(self, identity, expected):
        with self.backend.context():
            job = self.backend.manual.jobs[identity]
            if (
                self.stopping.is_set()
                or job["status"] not in {"stopped", "interrupted", "failed", "canceled"}
                or self.backend.manual.controller(identity).running()
                or self._owned(identity) != expected
            ):
                raise ValueError("The Batch owner or worker changed during collection.")
            yield

    def check(self, identity):
        with self.backend.context():
            job = self.backend.manual.jobs[identity]
            if (
                not self.backend.allow_providers
                or self.stopping.is_set()
                or job.get("mode") != "batch"
                or temporary(job)
                or job["status"] not in {"stopped", "interrupted", "failed", "canceled"}
                or self.backend.manual.controller(identity).running()
            ):
                self.views.pop(identity, None)
                return
            root = self.backend.manual.folder(identity)
            history = saved(root, "batch_history.json").get("batches", [])
            if not history and not job.get("dazedtl_batch_approval"):
                return
            if identity in self.settled:
                self.views.pop(identity, None)
                return
            plan = self._owned(identity)
            if job.get("dazedtl_batch_results_error"):
                self.views[identity] = {
                    "state": "blocked",
                    "message": job["dazedtl_batch_results_error"],
                }
                return
            # The approval covers the entire frozen queue. A local app close
            # does not revoke it or turn the first provider chunk into the run.
            remaining = batch_control.unsent_requests(root)
            restartable = job["status"] in {"stopped", "interrupted"} or job.get(
                "dazedtl_consume_only"
            )
            if (
                remaining
                and restartable
                and job.get("dazedtl_approved")
                and not job.get("dazedtl_batch_stopped")
                and not job.get("dazedtl_batch_cancellations")
                and job["status"] != "canceled"
                and not self._superseded(identity, plan)
            ):
                self.guided.settings.prepare_engine(resume=plan)
                self.backend.manual.continue_batch(identity)
                self.consumed.discard(identity)
                self.views.pop(identity, None)
                return
            if not history:
                return
            if batch_control.no_successful_results(root):
                self._finish_empty(identity)
                return
            if identity in self.consumed and not batch_control.unsent_requests(root):
                self.views[identity] = {
                    "state": "save_error",
                    "message": "Saving the collected responses did not finish. Review the run error, then retry saving results.",
                }
                return
            state = saved(root, "batch_state.json").get("status")
            if state not in {"submitted", "partially_submitted", "fetched"}:
                self.views[identity] = {
                    "state": "blocked",
                    "message": "The saved Batch state is incomplete. View requests to inspect its retained submission receipts.",
                }
                return
            batches = [
                deepcopy(batch_control.receipt(root, batch["id"])) for batch in history
            ]
            connections = {
                batch["id"]: self.guided.settings.batch_connection(batch, plan)
                for batch in batches
            }
            self.busy.add(identity)
            # Rechecking a recovery record is not provider or local work.
            # Keep its last outcome visible until there is new evidence.
        resolve = lambda batch: connections[batch["id"]]
        if state != "fetched":
            observed = []
            for batch in batches:
                with batch_control.connection(
                    batch, resolve, receipt_root=root
                ) as provider:
                    current = provider.status(batch["id"])
                observed.append(
                    {
                        "id": batch["id"],
                        "status": current["api_status"],
                        "counts": current.get("counts") or {},
                    }
                )
            pending = any(
                row["status"] not in batch_control.TERMINAL for row in observed
            )
            with self._commit(identity, plan):
                self.views[identity] = {
                    "state": "monitoring" if pending else "collecting",
                    "message": "",
                    "batches": observed,
                    "checkedAt": datetime.now(UTC).isoformat(),
                }
            if pending:
                return
            batch_control.collect(
                root, resolve, commit=lambda: self._commit(identity, plan)
            )
        if (plan.get("dazedtl_request_policy") or {}).get("refusalRetry"):
            from dazedtl.compatibility.batch_refusals import advance_guided

            outcome = advance_guided(
                root,
                plan,
                resolve,
                commit=lambda: self._commit(identity, plan),
                allow_submit=job.get("status") != "canceled"
                and not job.get("dazedtl_batch_cancellations")
                and not job.get("dazedtl_batch_stopped"),
            )
            if not outcome["ready"]:
                with self._commit(identity, plan):
                    self.views[identity] = {
                        "state": "blocked"
                        if outcome.get("uncertain")
                        else "monitoring",
                        "phase": "poll_capacity"
                        if outcome.get("waiting_capacity")
                        else "poll_status",
                        "message": "Reconcile the clarification Batch submission."
                        if outcome.get("uncertain")
                        else "Waiting for available Batch token capacity."
                        if outcome.get("waiting_capacity")
                        else "Waiting for the Batch clarification of refused requests.",
                        "batches": [
                            {
                                "id": batch["id"],
                                "status": batch.get("api_status", "validating"),
                                "counts": batch.get("counts", {}),
                            }
                            for batch in outcome["batches"]
                            if batch["id"]
                        ],
                    }
                return
        with self._commit(identity, plan):
            if batch_control.no_successful_results(root):
                self._finish_empty(identity)
                return
            remaining = len(batch_control.unsent_requests(root))
            if remaining:
                self.views[identity] = {
                    "state": "blocked",
                    "message": f"{remaining:,} requests were not submitted. Collected responses are retained; "
                    "this stopped or superseded run will not submit more work automatically.",
                }
                return
            self.guided.settings.prepare_engine(resume=plan)
            # Only fetched responses can reach the local consume worker.
            # In particular a partially submitted queue is never resumed.
            self.backend.manual.consume_batch(identity)
            self.consumed.add(identity)
            self.views.pop(identity, None)

    def _finish_empty(self, identity):
        job = self.backend.manual.jobs[identity]
        job.update(
            status="failed",
            phase="failed",
            approval=None,
            message="No successful Batch responses. Use Translate for a fresh estimate of remaining work.",
        )
        self.backend.manual.save(job)
        self.settled.add(identity)
        self.views.pop(identity, None)
