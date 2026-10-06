"""Read-only views of saved runs and their provider batches, plus their cleanup."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from dazedtl.storage import write_json

from .files import digest, project_path

if TYPE_CHECKING:
    from .guided import Guided


class RunInspection:
    def __init__(self, guided: Guided):
        self.guided = guided

    def run_view(self, identity, *, compact=False):
        job = dict(self.guided.backend.manual.jobs[identity])
        # Background monitoring is public run activity, not a resumed worker.
        # Preserve the actual worker state for per-file ownership and progress.
        job["workerStatus"] = job["status"]
        plan = {}
        if job.get("mode") in {"translate", "offline"} and job.get("item_progress"):
            job["itemProgress"] = dict(job["item_progress"])
        from dazedtl.compatibility.preparations import temporary

        job["temporary"] = temporary(job)
        try:
            root = self.guided.backend.manual.folder(identity)
            folder = root / "translated"
            plan = self.guided.run_configuration(identity)
            if (root / "plan.json").is_file() and job.get("plan_hash") == digest(
                (root / "plan.json").read_bytes()
            ):
                from dazedtl.compatibility.checkpoints import (
                    can_collect_outputs,
                )
                from dazedtl.compatibility.checkpoints import (
                    outputs as checkpoint_outputs,
                )

                job["outputs"] = {
                    **job.get("outputs", {}),
                    **(
                        checkpoint_outputs(root, plan)
                        if can_collect_outputs(job)
                        else {}
                    ),
                }
                job["partialOutputs"] = [
                    name
                    for name in job["outputs"]
                    if name in job.get("errors", {})
                    or name in job.get("mismatches", {})
                    or (
                        name not in job.get("completed", [])
                        and job.get("status") != "complete"
                    )
                ]
            input_hashes = {
                row["name"]: row["sha256"]
                for row in plan.get("files", [])
                if isinstance(row, dict)
                and isinstance(row.get("name"), str)
                and isinstance(row.get("sha256"), str)
            }
            if set(job.get("files", [])).issubset(input_hashes):
                job["changedOutputs"] = [
                    name
                    for name, expected in job.get("outputs", {}).items()
                    if name in input_hashes and expected != input_hashes[name]
                ]
            job["availableOutputs"] = [
                name
                for name, expected in job.get("outputs", {}).items()
                if project_path(folder, name).is_file()
                and self.guided.observed_digest(project_path(folder, name)) == expected
            ]
            job["outputsAvailable"] = bool(job.get("outputs")) and len(
                job["availableOutputs"]
            ) == len(job["outputs"])
            workflow = plan.get("workflow") or {}
            job["logicalPhase"] = workflow.get("phase")
            if job.get("mode") == "estimate":
                from dazedtl.compatibility.process_view import nothing_to_translate

                job["nothingToTranslate"] = nothing_to_translate(root, job)
            project = next(
                (
                    item
                    for item in self.guided.projects.data["projects"]
                    if item.get("backend_id") == workflow.get("id")
                ),
                None,
            )
            if project:
                record = self.guided.runs.records(project["id"]).get(identity, {})
                job["eventTextReview"] = record.get("review")
                job["repeatSubmission"] = bool(
                    (record.get("estimate") or {}).get("repeatSubmission")
                )
                if not job.get("estimate") and record.get("estimate"):
                    job["estimate"] = record["estimate"].get("value")
                if job.get("mode") == "estimate":
                    job["preparationMode"] = self.guided.runs.preparation_mode(
                        project["id"], identity
                    )
            native = self.guided.backend.workflows.projects.get(workflow.get("id"))
            if native:
                versions = self.guided.inputs(native).record().get("file_versions", {})
                job["retiredFiles"] = [
                    name
                    for name in job.get("files", [])
                    if versions.get(name, "")
                    != plan.get("dazedtl_source_versions", {}).get(name, "")
                ]
                job["appliedOutputs"] = [
                    name
                    for name, expected in job.get("outputs", {}).items()
                    if self.guided.observed_digest(project_path(native["data"], name))
                    == expected
                ]
        except OSError, ValueError, KeyError:
            job["outputsAvailable"] = False
            job["availableOutputs"] = []
        if compact:
            job["log"] = []
        from dazedtl.compatibility.speaker_results import summary as name_summary

        job["nameTranslation"] = name_summary(
            self.guided.backend.manual.folder(identity),
            self.guided.backend.manual.jobs[identity],
        )
        try:
            job["process"] = self.guided.observations.process(
                self.guided.backend.manual.folder(identity), job, plan
            )
            rejected_files = {
                row["file"] for row in job["process"].get("validationIssues", [])
            }
            job["partialOutputs"] = sorted(
                set(job.get("partialOutputs", []))
                | (rejected_files & set(job.get("outputs", {})))
            )
        except OSError, ValueError, KeyError:
            job["process"] = {
                "retryBlocked": job.get("mode") != "estimate",
                "errors": [
                    "Saved process evidence is unavailable. The run was retained for recovery."
                ],
            }
        # A worker may resume or finish while an earlier monitor read is in
        # flight. Its activity and completion take precedence over that view.
        monitoring = (
            self.guided.batch_monitor.views.get(identity)
            if job["workerStatus"] in {"stopped", "interrupted", "failed", "canceled"}
            else None
        )
        if monitoring:
            updates = {batch["id"]: batch for batch in monitoring.get("batches", [])}
            refreshed = []
            from dazedtl.compatibility.batch_control import TERMINAL

            for batch in job["process"].get("batches", []):
                update = (
                    updates.get(batch["id"], {})
                    if batch["status"] not in TERMINAL
                    else {}
                )
                merged = {**batch, **update}
                if (
                    batch["status"] in {"cancelling", "canceling"}
                    and update.get("status") not in TERMINAL
                ):
                    merged["status"] = batch["status"]
                refreshed.append(merged)
            job["process"]["batches"] = refreshed
            # Terminal receipts can arrive after a provider poll. Do not turn
            # their stale monitoring label into a new active run on refresh.
            if (
                monitoring["state"] == "monitoring"
                and monitoring.get("phase") != "poll_capacity"
                and refreshed
                and all(batch["status"] in TERMINAL for batch in refreshed)
            ):
                monitoring = None
            if monitoring:
                job["process"]["monitoring"] = {
                    key: value for key, value in monitoring.items() if key != "batches"
                }
        from dazedtl.compatibility.process_view import phase_feedback

        job.update(phase_feedback(job))
        if monitoring and monitoring["state"] in {"monitoring", "collecting"}:
            # Public activity follows the app-owned monitor, without rewriting
            # the stopped native worker or granting it submission authority.
            job.update(
                status="running",
                phase=monitoring.get("phase", "poll_status"),
                approval=None,
                message=monitoring.get("message")
                or (
                    "Downloading Batch results."
                    if monitoring["state"] == "collecting"
                    else "Waiting for provider results. Monitoring continues automatically."
                ),
            )
        if job["temporary"]:
            # Collection can write local scratch JSON before any paid request.
            # It is never saved translation output available to the user.
            job.update(
                outputs={},
                availableOutputs=[],
                partialOutputs=[],
                outputsAvailable=False,
                appliedOutputs=[],
            )
        return job

    def discard_preparation(self, project_id, run_id):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose temporary preparation belonging to this project.")
        self.guided.backend.manual.discard_preparation(run_id)
        records = self.guided.runs.records(project_id)
        records.pop(run_id, None)
        write_json(
            self.guided.path(project_id, "runs"), {"version": 1, "runs": records}
        )
        return {"discarded": True}

    def settle_empty_estimate(self, project_id, run_id):
        """Keep a current estimate without work as file status, then discard it.

        Batch estimates count requests; Live estimates instead show no work by
        finding no source text. Files whose text was only reused from earlier
        responses still need a run to write it, so they keep their status.
        """
        from dazedtl.compatibility.process_view import (
            nothing_to_translate,
            translatable_files,
        )

        _, native = self.guided.record(project_id)
        if self.guided.resyncing(native):
            raise ValueError(
                "Wait for the working files to finish resyncing before closing this estimate."
            )
        record = self.guided.runs.records(project_id).get(run_id)
        job = self.guided.backend.manual.jobs.get(run_id)
        if (
            not record
            or not job
            or job.get("mode") != "estimate"
            or run_id not in self.guided.owned_runs(native)
        ):
            raise ValueError("Choose an estimate belonging to this project.")
        quote, _ = self.guided.runs.quote(
            project_id,
            native,
            record["phase"],
            self.guided.preferences(native)["values"]["mode"],
        )
        if (quote["job"] or {}).get("id") != run_id or not quote["current"]:
            raise ValueError(
                "The selection or guidance changed. Prepare a fresh estimate."
            )
        root = self.guided.backend.manual.folder(run_id)
        estimate = job.get("estimate") or {}
        requests = estimate.get("requests", estimate.get("request_count"))
        if not (
            (type(requests) is int and not requests) or nothing_to_translate(root, job)
        ):
            raise ValueError("This estimate has text to translate. Review its cost.")
        found = translatable_files(root)
        settled = (
            []
            if found is None
            else [
                name
                for name in record["files"]
                if name not in found
                and name not in job.get("errors", {})
                and name not in job.get("mismatches", {})
            ]
        )
        self.guided.inputs(native).settle(
            record["phase"],
            {name: record["file_versions"][name] for name in settled},
            job["created"],
        )
        self.discard_preparation(project_id, run_id)
        return {"files": settled}

    def payload(self, project_id, run_id, index):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        from dazedtl.compatibility.process_view import payload

        return payload(self.guided.backend.manual.folder(run_id), index)

    def file_preview(self, project_id, name, offset=0, query=""):
        _, native = self.guided.record(project_id)
        if name not in self.guided.supported_files(native):
            raise ValueError("Choose a supported file from this project.")
        inputs = self.guided.inputs(native)
        # Check the runtime path even when a working copy exists. No caller can
        # turn this reader into arbitrary project/profile filesystem access.
        relative = (
            (Path(native["data"]) / name).relative_to(Path(native["source"])).as_posix()
        )
        runtime = project_path(native["source"], relative, exists=False)
        from .file_preview import preview

        return preview(inputs, name, runtime, offset, query)

    def name_results(self, project_id, run_id, offset=0):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        plan = self.guided.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("Choose a translation run owned by this project.")
        from dazedtl.compatibility.speaker_results import page

        return page(
            self.guided.backend.manual.folder(run_id),
            self.guided.backend.manual.jobs[run_id],
            offset,
        )

    def provider_details(self, project_id, run_id):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        if not self.guided.backend.allow_providers:
            raise ValueError("Provider reads are disabled in offline mode.")
        from dazedtl.compatibility.process_view import provider_details

        plan = self.guided.backend.saved_run_configuration(run_id)
        return provider_details(
            self.guided.backend.manual.folder(run_id),
            lambda batch: self.guided.settings.batch_connection(batch, plan),
        )

    def batch_cancel_preview(self, project_id, run_id, batch_id):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a Batch belonging to this project.")
        from dazedtl.compatibility.batch_control import binding, can_cancel, receipt

        batch = receipt(self.guided.backend.manual.folder(run_id), batch_id)
        if not can_cancel(batch["provider"]):
            raise ValueError(
                "OpenRouter does not expose Batch cancellation. Submitted work continues at the provider."
            )
        job = self.guided.backend.manual.jobs[run_id]
        token = uuid.uuid4().hex
        value = {
            "token": token,
            "runId": run_id,
            "batchId": batch_id,
            "provider": batch["provider"],
            "files": job.get("files", []),
            "model": job.get("model", ""),
            "requests": len(batch["custom_ids"]),
        }
        self.guided.batch_confirmations[token] = {
            "project": project_id,
            "value": value,
            "binding": binding(batch),
        }
        if len(self.guided.batch_confirmations) > 32:
            self.guided.batch_confirmations.pop(
                next(iter(self.guided.batch_confirmations))
            )
        return value

    def batch_cancel(self, project_id, token):
        _, native = self.guided.record(project_id)
        review = self.guided.batch_confirmations.get(token)
        if not review or review["project"] != project_id:
            raise ValueError("Review cancellation for this project before continuing.")
        value = review["value"]
        if (
            value["runId"] not in self.guided.owned_runs(native)
            or value["runId"] not in self.guided.backend.manual.jobs
        ):
            raise ValueError("The Batch no longer belongs to this project.")
        if not self.guided.backend.allow_providers:
            raise ValueError("Provider actions are disabled in offline mode.")
        self.guided.batch_confirmations.pop(token)
        from dazedtl.compatibility.batch_control import cancel

        plan = self.guided.backend.saved_run_configuration(value["runId"])
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved Batch belongs to another project.")
        result = cancel(
            self.guided.backend.manual.folder(value["runId"]),
            value["batchId"],
            review["binding"],
            lambda batch: self.guided.settings.batch_connection(batch, plan),
        )
        job = self.guided.backend.manual.jobs[value["runId"]]
        job.setdefault("dazedtl_batch_cancellations", {})[value["batchId"]] = {
            "status": result["status"],
            "counts": result.get("counts"),
        }
        self.guided.backend.manual.save(job)
        return result

    def batch_collect(self, project_id, run_id):
        _, native = self.guided.record(project_id)
        if (
            run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a Batch belonging to this project.")
        job = self.guided.backend.manual.jobs[run_id]
        if run_id in self.guided.batch_monitor.busy:
            raise ValueError(
                "This Batch is already being checked or collected automatically."
            )
        if (
            job.get("mode") != "batch"
            or job.get("status") not in {"failed", "stopped", "interrupted", "canceled"}
            or self.guided.backend.manual.controller(run_id).running()
        ):
            raise ValueError(
                "Wait for this run’s local worker to finish before collecting its results."
            )
        if not self.guided.backend.allow_providers:
            raise ValueError("Provider reads are disabled in offline mode.")
        plan = self.guided.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved Batch belongs to another project.")
        if plan.get("batch_link"):
            raise ValueError(
                "Collect results from the original run that owns this linked Batch."
            )
        from dazedtl.compatibility.batch_control import collect, no_successful_results
        from dazedtl.compatibility.process_view import saved

        root = self.guided.backend.manual.folder(run_id)
        if saved(root, "batch_state.json").get("status") != "fetched":
            collect(
                root, lambda batch: self.guided.settings.batch_connection(batch, plan)
            )
        if job.pop("dazedtl_batch_results_error", None):
            self.guided.backend.manual.save(job)
            self.guided.batch_monitor.settled.discard(run_id)
        if no_successful_results(root):
            raise ValueError(
                "This Batch has no successful responses to save. Use Translate for a fresh estimate."
            )
        self.guided.settings.prepare_engine(resume=plan)
        # The fetched marker restricts the native runner to local consumption.
        return self.guided.backend.manual.consume_batch(run_id)

    def inspect(self, project_id, run_id):
        if not isinstance(run_id, str):
            raise ValueError("Choose a saved activity record.")
        _, native = self.guided.record(project_id)
        operation = self.guided.backend.operations.jobs.get(run_id)
        if operation and operation["project_id"] == native["id"]:
            return operation
        if (
            run_id in self.guided.owned_runs(native)
            and run_id in self.guided.backend.manual.jobs
        ):
            return self.run_view(run_id)
        return self.guided.translation.run(project_id, run_id)
