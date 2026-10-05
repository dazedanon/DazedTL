"""User-driven RPG Maker workflow over preserved engines and shared project services."""

import re
import shlex
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from dazedtl.storage import write_json

from . import backups, context_setup, preparation, reference_folders, speaker_setup
from .event_text import EventText
from .files import digest, evidence, project_path, read_json, verify_evidence
from .guided_inputs import GuidedInputs
from .guided_runs import GuidedRuns
from .operations import lifecycle, require_source_backup, verify_guided_review

STEPS = {
    "prepare",
    "context",
    "translate",
    "plugins",
    "images",
    "advanced",
    "apply",
    "layout",
    "review",
}
PHASES = {"database", "dialogue", "variables", "advanced", "speakers"}
ADVANCED_CODES = {
    "CODE122",
    "CODE357",
    "CODE355655",
    "CODE657",
    "CODE356",
    "CODE320",
    "CODE324",
    "CODE325",
    "CODE108",
}
NATIVE_ACTIONS = {
    "prepare_game",
    "import",
    "format_data",
    "format_plugins",
    "gameupdate",
    "export_selected",
    "ace_decrypt",
    "ace_extract",
    "ace_pack",
    "rewrap_preview",
    "rewrap_apply",
    "qa_prepare",
    "qa_status",
    "qa_apply",
    "runtime_restore",
    "playtest_install",
    "playtest_status",
    "playtest_apply",
    "inspector_install",
    "inspector_remove",
    "forge_install",
    "forge_remove",
    "editors",
    "release",
    "reference_add",
    "reference_pair",
    "reference_remove",
    "reference_build",
    "images_status",
}
TOOL_ACTIONS = {
    "playtest_install",
    "playtest_apply",
    "inspector_install",
    "inspector_remove",
    "forge_install",
    "forge_remove",
}
SHARED_ACTIONS = {
    "backup_source": "Preserve original game",
    "git_setup": "Review version baseline",
    "checkpoint": "Save reviewed patch in Git",
    "guided_review": "Record playtest review",
    "guided_package": "Build local patch ZIP",
    "release_patch": "Build local patch ZIP",
    "refresh_sources": "Resync selected files from game",
}
MANIFEST = ".dazedtl/guided/runtime-manifest.json"


def retained_position(value):
    """Keep older plugin/image locations when their formerly combined phase splits."""
    value = dict(value)
    if value.get("task") == "plugins":
        value["step"] = "plugins"
    elif value.get("task") in {"images", "image-text", "image-manager"}:
        value.update(step="images", task="images")
    elif value.get("task") in {"fitting", "playtest", "qa"}:
        value.update(step="apply", task="apply")
    return value


class Guided:
    def __init__(self, backend, projects, settings, translation):
        self.backend, self.projects, self.settings = backend, projects, settings
        self.translation = translation
        self.confirmations = {}
        self.batch_confirmations = {}
        self.observed_files = {}
        self.layout_failures = {}
        from dazedtl.compatibility.observations import RunObservations

        self.observations = RunObservations()
        self.runs = GuidedRuns(self)
        self.event_text = EventText(self)
        from .batch_monitor import BatchMonitor

        self.batch_monitor = BatchMonitor(self)

    def observed_digest(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError("Observed artifacts cannot be symbolic links.")
        stat = path.stat()
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        cached = self.observed_files.get(path)
        if cached and cached[0] == signature:
            return cached[1]
        value = digest(path.read_bytes())
        if len(self.observed_files) > 20_000:
            self.observed_files.clear()
        self.observed_files[path] = (signature, value)
        return value

    def idle(self, *, isolated_workers=False):
        # Apply and reload can coexist with frozen translation workers. Tool
        # operations still serialize writes to the game and working copies.
        busy = (
            self.backend.operations.running()
            if isolated_workers
            else self.backend.running()
        )
        if busy or self.translation.jobs.running():
            raise ValueError(
                "Finish or stop the current run before starting another action."
            )

    def record(self, project_id):
        project = self.projects.get(project_id)
        native = self.backend.workflows.projects.get(project.get("backend_id"))
        if not native or native["source"] != project["source"]:
            raise ValueError("Open Translation to initialize this game's workspace.")
        if native["engine"] not in {"MVMZ", "ACE"}:
            raise ValueError(
                "Guided translation supports RPG Maker MV/MZ and VX Ace. WOLF support comes later."
            )
        return project, native

    def open(self, project_id):
        project = self.projects.get(project_id)
        if project.get("backend_id"):
            _, native = self.record(project_id)
            current = self.backend.describe(project["source"])
            if (
                current["source"] != project["source"]
                or current["engine"] != native["engine"]
            ):
                raise ValueError(
                    "The game location or engine changed. Open the correct game folder before continuing."
                )
            if any(native.get(key) != value for key, value in current.items()):
                updated = {**native, **current}
                self.backend.workflows.save(updated)
                self.backend.workflows.projects[native["id"]] = updated
            return
        self.idle()
        layout = self.backend.describe(project["source"])
        if layout["engine"] not in {"MVMZ", "ACE"}:
            raise ValueError(
                "Guided translation supports RPG Maker MV/MZ and VX Ace. Use Len's method for other engines."
            )
        self.settings.prepare_engine()
        pending = self.translation.drafts(project_id)["documents"]
        existing = set(self.backend.workflows.projects)
        native = self.backend.workflows.open(project["source"])["project"]
        if native["id"] not in existing:
            # Another game's optional text targets are not an audit of this game.
            # Retain existing project choices and all frozen runs when reopening.
            options = {
                **native["engine_options"],
                **dict.fromkeys(ADVANCED_CODES, False),
                "CODE122_VAR_RANGES": "",
                "ENABLED_PLUGINS_357": [],
                "ENABLED_PATTERNS_355655": [],
            }
            options.update(
                {
                    key: False
                    for key in speaker_setup.KEYS
                    if type(options.get(key)) is bool
                }
            )
            native = self.backend.workflows.update(
                native["id"],
                native["revision"],
                {
                    "engine_options": options,
                    "selected": sorted(self.supported_files(native)),
                },
            )["project"]
        if pending:
            self.backend.workflows.draft(native["id"], {"documents": pending})
        # Persist registry ownership before publishing it in memory.
        data = deepcopy(self.projects.data)
        self.projects._get(data, project_id)["backend_id"] = native["id"]
        self.projects._commit(data)

    def path(self, project_id, name):
        self.projects.get(project_id)
        return (
            self.translation.workspace
            / "translation/projects"
            / project_id
            / ("guided-" + name + ".json")
        )

    def position(self, project_id, step, task=None, document=None):
        _, native = self.record(project_id)
        if step not in STEPS:
            raise ValueError("Choose a guided step.")
        if task is not None and (
            not isinstance(task, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,59}", task)
        ):
            raise ValueError("Choose a guided task.")
        documents = context_setup.retained_documents(
            native["source"],
            self.backend.workflows.documents(native["id"]),
            self.backend.workflows.state(native["id"])
            .get("draft", {})
            .get("documents", {}),
        )
        if document is not None and (
            not isinstance(document, str) or document not in documents
        ):
            raise ValueError("Choose an existing guidance document.")
        position_path = self.path(project_id, "position")
        previous = (
            retained_position(read_json(position_path))
            if position_path.exists()
            else {}
        )
        document_path = self.path(project_id, "context-document")
        if document is not None or not document_path.exists():
            choice = document or context_setup.selected_document(
                document_path, previous, documents
            )
            write_json(document_path, {"name": choice})
        positions = {**previous.get("positions", {}), step: task}
        write_json(
            position_path,
            {**previous, "step": step, "task": task, "positions": positions},
        )
        return {"saved": True}

    def form(self, project_id, value):
        self.record(project_id)
        value = self.form_value(project_id, value)
        write_json(self.path(project_id, "form"), value)
        return {"saved": True}

    def form_value(self, project_id, value):
        if (
            not isinstance(value, dict)
            or set(value)
            - {
                "version",
                "original",
                "untranslated",
                "only_overflow",
                "release",
                "text",
            }
            or {"version", "original", "untranslated", "only_overflow"} - set(value)
            or any(
                not isinstance(value[key], str)
                or len(value[key]) > 10000
                or "\0" in value[key]
                for key in ("version", "original")
            )
            or value.get("untranslated") is not None
            and type(value["untranslated"]) is not bool
            or type(value.get("only_overflow")) is not bool
        ):
            raise ValueError("Invalid guided form values.")
        text = value.get(
            "text",
            {
                "view": "apply",
                "categories": ["dialogue", "face_dialogue", "list", "notes"],
                "codes": "401,405",
                "max_rows": 4,
                "protect_rows": True,
                "focus": "release",
                "findings": [],
            },
        )
        if isinstance(text, dict):
            text = {"findings_task": "", **text}
        if (
            not isinstance(text, dict)
            or set(text)
            != {
                "view",
                "categories",
                "codes",
                "max_rows",
                "protect_rows",
                "focus",
                "findings_task",
                "findings",
            }
            or text["view"] not in {"apply", "fitting", "qa", "tools"}
            or not isinstance(text["categories"], list)
            or any(
                item not in {"dialogue", "face_dialogue", "list", "notes"}
                for item in text["categories"]
            )
            or not isinstance(text["codes"], str)
            or len(text["codes"]) > 100
            or type(text["max_rows"]) is not int
            or not 1 <= text["max_rows"] <= 100
            or type(text["protect_rows"]) is not bool
            or text["focus"] not in {"release", "database", "dialogue", "risky-codes"}
            or not isinstance(text["findings_task"], str)
            or len(text["findings_task"]) > 10000
            or not isinstance(text["findings"], list)
            or any(
                not isinstance(item, str) or len(item) > 200
                for item in text["findings"]
            )
        ):
            raise ValueError("Invalid fitting or optional QA choices.")
        return {
            **value,
            "text": deepcopy(text),
            "release": self.validate_release_form(
                value.get("release", self.release_defaults(project_id))
            ),
        }

    def release_defaults(self, project_id):
        source = Path(self.projects.get(project_id)["source"])
        return {
            "kind": "game",
            "name": source.name + "-game.zip",
            "names": {
                "game": source.name + "-game.zip",
                "patch": source.name + "-patch.zip",
            },
            "assets": [],
            "directory": str(source.parent),
            "tools": {
                "hotkey": "F9",
                "forgeHotkey": "F10",
                "uiScale": "auto",
                "editorCmd": "auto",
            },
        }

    @staticmethod
    def validate_release_form(value):
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            value = deepcopy(value)
            stem = (
                Path(value.get("name", "game.zip"))
                .stem.removesuffix("-public")
                .removesuffix("-game")
                .removesuffix("-patch")
            )
            value.setdefault(
                "names", {"game": stem + "-game.zip", "patch": stem + "-patch.zip"}
            )
            value.setdefault("assets", [])
        if (
            not isinstance(value, dict)
            or set(value) != {"kind", "name", "names", "assets", "directory", "tools"}
            or not isinstance(value["kind"], str)
            or value["kind"] not in {"game", "patch"}
            or any(
                not isinstance(value[key], str)
                or len(value[key]) > 10000
                or "\0" in value[key]
                for key in ("name", "directory")
            )
        ):
            raise ValueError("Invalid release options.")
        if (
            not isinstance(value["names"], dict)
            or set(value["names"]) != {"game", "patch"}
            or any(
                not isinstance(name, str) or len(name) > 10000 or "\0" in name
                for name in value["names"].values()
            )
            or not isinstance(value["assets"], list)
            or len(value["assets"]) > 2000
            or any(
                not isinstance(name, str) or len(name) > 2000
                for name in value["assets"]
            )
            or len(set(value["assets"])) != len(value["assets"])
        ):
            raise ValueError("Invalid retained archive names or runtime assets.")
        value["names"][value["kind"]] = value["name"]
        tools = value["tools"]
        if (
            not isinstance(tools, dict)
            or set(tools) != {"hotkey", "forgeHotkey", "uiScale", "editorCmd"}
            or any(
                not isinstance(item, str)
                or len(item) > 4096
                or any(char in item for char in ("\0", "\r", "\n"))
                for item in tools.values()
            )
            or tools["uiScale"]
            not in {"auto", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5"}
        ):
            raise ValueError("Choose valid playtest tool settings.")
        return deepcopy(value)

    def saved_form(self, project_id):
        path = self.path(project_id, "form")
        saved = read_json(path) if path.exists() else {}
        if not isinstance(saved, dict):
            raise ValueError(
                "The saved Guided form is invalid. Its original file was retained."
            )
        return self.form_value(
            project_id,
            {
                "version": "",
                "original": "",
                "untranslated": None,
                "only_overflow": True,
                **saved,
            },
        )

    def release_artifacts(self, project_id, jobs):
        from .release import available

        values = [
            (job["id"], job.get("result") or {})
            for job in jobs
            if job["action"] == "release" and job["status"] == "complete"
        ]
        state = lifecycle(self.translation.workspace, project_id)
        if state.get("guided_release"):
            values.insert(0, ("patch", state["guided_release"]))
        if state.get("delivery") and not any(
            value.get("path") == state["delivery"].get("path") for _, value in values
        ):
            legacy = {**state["delivery"], "kind": "patch"}
            values.append(("previous-patch", legacy))
        return [
            {
                "id": identity,
                "kind": value.get("kind", "game"),
                "path": value["path"],
                "folder": str(Path(value["path"]).parent),
                "size": value.get("size"),
                "saved": value.get("saved"),
                "available": available(value),
            }
            for identity, value in values
            if isinstance(value.get("path"), str)
        ][:10]

    def preferences(self, native):
        mode = native["mode"] if native["mode"] in {"batch", "translate"} else "batch"
        return {
            "revision": native["revision"],
            "values": {
                "selected": [
                    name
                    for name in native["selected"]
                    if name in self.supported_files(native)
                ],
                "mode": mode,
                "engine_options": native["engine_options"],
                "widths": native["widths"],
                "phase1_comments": native["phase1_comments"],
            },
        }

    def supported_files(self, native):
        return set(self.backend.phase_files(native, "database")) | set(
            self.backend.phase_files(native, "dialogue")
        )

    def inputs(self, native):
        return GuidedInputs(
            self.backend.workflows.folder(native["id"]),
            native["source"],
            native["data"],
            self.translation.engine.source_bindings,
            self.translation.engine.original_bytes,
            native_exports=native["engine"] == "ACE",
        )

    def owned_runs(self, native):
        return self.observations.once(
            ("owned", native["id"]), lambda: self._owned_runs(native)
        )

    def run_configuration(self, identity):
        return self.observations.configuration(self.backend, identity)

    def _owned_runs(self, native):
        owner = next(
            (
                item
                for item in self.projects.data["projects"]
                if item.get("backend_id") == native["id"]
            ),
            None,
        )
        recorded = list(self.runs.records(owner["id"])) if owner else []
        # Older runs may precede the registry. Their frozen workflow ownership is
        # authoritative, even after an estimate replaces the native pointer.
        historical = []
        for identity in getattr(getattr(self.backend, "manual", None), "jobs", {}):
            try:
                if (self.run_configuration(identity).get("workflow") or {}).get(
                    "id"
                ) == native["id"]:
                    historical.append(identity)
            except (OSError, ValueError, KeyError):
                pass
        identities = list(
            dict.fromkeys(
                [
                    *reversed(recorded),
                    *reversed(historical),
                    native.get("manual_job"),
                    *reversed(native.get("collected", [])),
                    *reversed(native.get("kept_failed_runs", {})),
                    *self.inputs(native).record().get("retired_runs", []),
                ]
            )
        )
        # A resumed old job can own the native pointer or have a newer update
        # time. Neither makes it the latest attempt for this task.
        jobs = getattr(getattr(self.backend, "manual", None), "jobs", {})
        return sorted(
            (
                identity
                for identity in identities
                if not jobs.get(identity, {}).get("dazedtl_discard_preparation")
            ),
            key=lambda identity: jobs.get(identity, {}).get("created", ""),
            reverse=True,
        )

    def run_view(self, identity, *, compact=False):
        job = dict(self.backend.manual.jobs[identity])
        # Background monitoring is public run activity, not a resumed worker.
        # Preserve the actual worker state for per-file ownership and progress.
        job["workerStatus"] = job["status"]
        plan = {}
        if job.get("mode") in {"translate", "offline"} and job.get("item_progress"):
            job["itemProgress"] = dict(job["item_progress"])
        from dazedtl.compatibility.preparations import temporary

        job["temporary"] = temporary(job)
        try:
            root = self.backend.manual.folder(identity)
            folder = root / "translated"
            plan = self.run_configuration(identity)
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
                and self.observed_digest(project_path(folder, name)) == expected
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
                    for item in self.projects.data["projects"]
                    if item.get("backend_id") == workflow.get("id")
                ),
                None,
            )
            if project:
                record = self.runs.records(project["id"]).get(identity, {})
                job["eventTextReview"] = record.get("review")
                job["repeatSubmission"] = bool(
                    (record.get("estimate") or {}).get("repeatSubmission")
                )
                if not job.get("estimate") and record.get("estimate"):
                    job["estimate"] = record["estimate"].get("value")
                if job.get("mode") == "estimate":
                    job["preparationMode"] = self.runs.preparation_mode(
                        project["id"], identity
                    )
            native = self.backend.workflows.projects.get(workflow.get("id"))
            if native:
                versions = self.inputs(native).record().get("file_versions", {})
                job["retiredFiles"] = [
                    name
                    for name in job.get("files", [])
                    if versions.get(name, "")
                    != plan.get("dazedtl_source_versions", {}).get(name, "")
                ]
                job["appliedOutputs"] = [
                    name
                    for name, expected in job.get("outputs", {}).items()
                    if self.observed_digest(project_path(native["data"], name))
                    == expected
                ]
        except (OSError, ValueError, KeyError):
            job["outputsAvailable"] = False
            job["availableOutputs"] = []
        if compact:
            job["log"] = []
        from dazedtl.compatibility.speaker_results import summary as name_summary

        job["nameTranslation"] = name_summary(
            self.backend.manual.folder(identity), self.backend.manual.jobs[identity]
        )
        try:
            job["process"] = self.observations.process(
                self.backend.manual.folder(identity), job, plan
            )
            rejected_files = {
                row["file"] for row in job["process"].get("validationIssues", [])
            }
            job["partialOutputs"] = sorted(
                set(job.get("partialOutputs", []))
                | (rejected_files & set(job.get("outputs", {})))
            )
        except (OSError, ValueError, KeyError):
            job["process"] = {
                "retryBlocked": job.get("mode") != "estimate",
                "errors": [
                    "Saved process evidence is unavailable. The run was retained for recovery."
                ],
            }
        # A worker may resume or finish while an earlier monitor read is in
        # flight. Its activity and completion take precedence over that view.
        monitoring = (
            self.batch_monitor.views.get(identity)
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
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose temporary preparation belonging to this project.")
        self.backend.manual.discard_preparation(run_id)
        records = self.runs.records(project_id)
        records.pop(run_id, None)
        write_json(self.path(project_id, "runs"), {"version": 1, "runs": records})
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

        _, native = self.record(project_id)
        if self.resyncing(native):
            raise ValueError(
                "Wait for the working files to finish resyncing before closing this estimate."
            )
        record = self.runs.records(project_id).get(run_id)
        job = self.backend.manual.jobs.get(run_id)
        if (
            not record
            or not job
            or job.get("mode") != "estimate"
            or run_id not in self.owned_runs(native)
        ):
            raise ValueError("Choose an estimate belonging to this project.")
        quote, _ = self.runs.quote(
            project_id,
            native,
            record["phase"],
            self.preferences(native)["values"]["mode"],
        )
        if (quote["job"] or {}).get("id") != run_id or not quote["current"]:
            raise ValueError(
                "The selection or guidance changed. Prepare a fresh estimate."
            )
        root = self.backend.manual.folder(run_id)
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
        self.inputs(native).settle(
            record["phase"],
            {name: record["file_versions"][name] for name in settled},
            job["created"],
        )
        self.discard_preparation(project_id, run_id)
        return {"files": settled}

    def resyncing(self, native):
        return any(
            job.get("project_id") == native["id"]
            and job.get("action") == "refresh_sources"
            and job.get("status") in {"ready", "running", "waiting"}
            for job in self.backend.operations.jobs.values()
        )

    def payload(self, project_id, run_id, index):
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        from dazedtl.compatibility.process_view import payload

        return payload(self.backend.manual.folder(run_id), index)

    def file_preview(self, project_id, name, offset=0, query=""):
        _, native = self.record(project_id)
        if name not in self.supported_files(native):
            raise ValueError("Choose a supported file from this project.")
        inputs = self.inputs(native)
        # Check the runtime path even when a working copy exists. No caller can
        # turn this reader into arbitrary project/profile filesystem access.
        relative = (
            (Path(native["data"]) / name).relative_to(Path(native["source"])).as_posix()
        )
        runtime = project_path(native["source"], relative, exists=False)
        from .file_preview import preview

        return preview(inputs, name, runtime, offset, query)

    def name_results(self, project_id, run_id, offset=0):
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        plan = self.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("Choose a translation run owned by this project.")
        from dazedtl.compatibility.speaker_results import page

        return page(
            self.backend.manual.folder(run_id), self.backend.manual.jobs[run_id], offset
        )

    def provider_details(self, project_id, run_id):
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a translation run owned by this project.")
        if not self.backend.allow_providers:
            raise ValueError("Provider reads are disabled in offline mode.")
        from dazedtl.compatibility.process_view import provider_details

        plan = self.backend.saved_run_configuration(run_id)
        return provider_details(
            self.backend.manual.folder(run_id),
            lambda batch: self.settings.batch_connection(batch, plan),
        )

    def batch_cancel_preview(self, project_id, run_id, batch_id):
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a Batch belonging to this project.")
        from dazedtl.compatibility.batch_control import binding, can_cancel, receipt

        batch = receipt(self.backend.manual.folder(run_id), batch_id)
        if not can_cancel(batch["provider"]):
            raise ValueError(
                "OpenRouter does not expose Batch cancellation. Submitted work continues at the provider."
            )
        job = self.backend.manual.jobs[run_id]
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
        self.batch_confirmations[token] = {
            "project": project_id,
            "value": value,
            "binding": binding(batch),
        }
        if len(self.batch_confirmations) > 32:
            self.batch_confirmations.pop(next(iter(self.batch_confirmations)))
        return value

    def batch_cancel(self, project_id, token):
        _, native = self.record(project_id)
        review = self.batch_confirmations.get(token)
        if not review or review["project"] != project_id:
            raise ValueError("Review cancellation for this project before continuing.")
        value = review["value"]
        if (
            value["runId"] not in self.owned_runs(native)
            or value["runId"] not in self.backend.manual.jobs
        ):
            raise ValueError("The Batch no longer belongs to this project.")
        if not self.backend.allow_providers:
            raise ValueError("Provider actions are disabled in offline mode.")
        self.batch_confirmations.pop(token)
        from dazedtl.compatibility.batch_control import cancel

        plan = self.backend.saved_run_configuration(value["runId"])
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved Batch belongs to another project.")
        result = cancel(
            self.backend.manual.folder(value["runId"]),
            value["batchId"],
            review["binding"],
            lambda batch: self.settings.batch_connection(batch, plan),
        )
        job = self.backend.manual.jobs[value["runId"]]
        job.setdefault("dazedtl_batch_cancellations", {})[value["batchId"]] = {
            "status": result["status"],
            "counts": result.get("counts"),
        }
        self.backend.manual.save(job)
        return result

    def batch_collect(self, project_id, run_id):
        _, native = self.record(project_id)
        if (
            run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a Batch belonging to this project.")
        job = self.backend.manual.jobs[run_id]
        if run_id in self.batch_monitor.busy:
            raise ValueError(
                "This Batch is already being checked or collected automatically."
            )
        if (
            job.get("mode") != "batch"
            or job.get("status") not in {"failed", "stopped", "interrupted", "canceled"}
            or self.backend.manual.controller(run_id).running()
        ):
            raise ValueError(
                "Wait for this run’s local worker to finish before collecting its results."
            )
        if not self.backend.allow_providers:
            raise ValueError("Provider reads are disabled in offline mode.")
        plan = self.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved Batch belongs to another project.")
        if plan.get("batch_link"):
            raise ValueError(
                "Collect results from the original run that owns this linked Batch."
            )
        from dazedtl.compatibility.batch_control import collect, no_successful_results
        from dazedtl.compatibility.process_view import saved

        root = self.backend.manual.folder(run_id)
        if saved(root, "batch_state.json").get("status") != "fetched":
            collect(root, lambda batch: self.settings.batch_connection(batch, plan))
        if job.pop("dazedtl_batch_results_error", None):
            self.backend.manual.save(job)
            self.batch_monitor.settled.discard(run_id)
        if no_successful_results(root):
            raise ValueError(
                "This Batch has no successful responses to save. Use Translate for a fresh estimate."
            )
        self.settings.prepare_engine(resume=plan)
        # The fetched marker restricts the native runner to local consumption.
        return self.backend.manual.consume_batch(run_id)

    def inspect(self, project_id, run_id):
        if not isinstance(run_id, str):
            raise ValueError("Choose a saved activity record.")
        _, native = self.record(project_id)
        operation = self.backend.operations.jobs.get(run_id)
        if operation and operation["project_id"] == native["id"]:
            return operation
        if run_id in self.owned_runs(native) and run_id in self.backend.manual.jobs:
            return self.run_view(run_id)
        return self.translation.run(project_id, run_id)

    def readiness(self, project_id, native, value, source_status=None):
        folder = self.backend.workflows.folder(native["id"])
        outputs = [
            row["name"]
            for row in native["files"]
            if self.inputs(native).path("translated", row["name"]).is_file()
        ]
        applied = []
        edited = []
        receipt = folder / "applied-outputs.json"
        applied_outputs = (
            read_json(receipt).get("files", {}) if receipt.exists() else {}
        )
        for name in outputs:
            source = project_path(
                native["source"],
                (Path(native["data"]) / name).relative_to(native["source"]).as_posix(),
            )
            output_hash = self.observed_digest(folder / "translated" / name)
            matches = self.observed_digest(source) == output_hash
            if matches or applied_outputs.get(name) == output_hash:
                applied.append(name)
                if not matches:
                    edited.append(name)
        state = lifecycle(self.translation.workspace, project_id)
        current = False
        try:
            review = state.get("guided_review")
            sources = self.inputs(native).record()
            source_status = source_status or self.inputs(native).status(
                [row["name"] for row in native["files"]], self.observed_digest
            )
            scope_matches = (
                review.get("source_inputs_sha256") == digest(sources)
                if review and review.get("source_inputs_sha256")
                else not sources.get("last_refresh")
            )
            current = bool(
                review
                and scope_matches
                and not source_status["changed"]
                and review["evidence"]
                and all(
                    self.observed_digest(project_path(native["source"], name)) == sha
                    for name, sha in review["evidence"].items()
                )
            )
        except (OSError, ValueError, KeyError):
            pass
        scan = next(
            (
                job
                for job in value["jobs"]
                if job["action"] == "rewrap_preview" and job["status"] == "complete"
            ),
            None,
        )
        if scan:
            try:
                plan = read_json(
                    self.backend.operations.root / scan["id"] / "plan.json"
                )
            except (OSError, ValueError):
                plan = {}
            configured = plan.get("options", {})
            form = self.saved_form(project_id)
            only_overflow = form["only_overflow"]
            selected_layout = [
                row["name"]
                for row in native["files"]
                if row["name"] in native["selected"]
            ]
            if (
                configured.get("files") != selected_layout
                or configured.get("widths") != native["widths"]
                or configured.get("over_limit") != only_overflow
                or any(
                    configured.get(key) != form["text"][key]
                    for key in ("categories", "codes", "max_rows", "protect_rows")
                )
                or any(
                    self.observed_digest(Path(native["data"]) / name)
                    != plan.get("guard", {}).get("data", {}).get(name)
                    for name in selected_layout
                )
            ):
                scan = None
        return {
            **self.backend.guided_text_state(
                native, self.saved_form(project_id)["text"]["focus"]
            ),
            "outputs": outputs,
            "applied": applied,
            "unapplied": sorted(
                set(outputs).intersection(native["selected"]) - set(applied)
            ),
            "runtime_edited": edited,
            "review_current": current,
            "layout_scan": scan["id"] if scan else None,
            "delivery_available": bool(
                state.get("delivery") and Path(state["delivery"]["path"]).is_file()
            ),
        }

    def patch_manifest(self, project_id, paths, action):
        project, native = self.record(project_id)
        entries = {name: {} for name in paths}
        if action != "git_setup":
            originals = self.translation.engine.source_bindings(
                project["source"], paths
            )
            state = lifecycle(self.translation.workspace, project_id)
            saved = state.get("prepared_source") or state.get("source_backup")
            source_files = {}
            if saved:
                location = backups.lookup(
                    project["source"], Path(saved["path"]).parent, saved["id"]
                )
                source_files = backups.manifest(location, source=project["source"])[
                    "files"
                ]
            for name in paths:
                if name not in originals and name not in source_files:
                    entries[name] = {"original_sha256": None}
        inputs = []
        if native["engine"] == "ACE":
            inputs = [
                path.relative_to(Path(project["source"])).as_posix()
                for path in Path(native["data"]).glob("*.json")
            ]
        return {"files": entries, "inputs": sorted(inputs)}

    def options_draft(self, project_id, value):
        _, native = self.record(project_id)
        if value is not None and (
            not isinstance(value, dict)
            or set(value) != {"revision", "values"}
            or type(value["revision"]) is not int
        ):
            raise ValueError("Invalid guided options draft.")
        if value is not None:
            self.validate_options(value["values"])
            value = context_setup.rebase_layout_draft(native, value)
        write_json(self.path(project_id, "draft"), value)
        return {"saved": True}

    @staticmethod
    def validate_options(values):
        import json

        if not isinstance(values, dict) or set(values) != {
            "selected",
            "mode",
            "engine_options",
            "widths",
            "phase1_comments",
        }:
            raise ValueError("Unknown guided setting.")
        if values["mode"] not in {"batch", "translate"}:
            raise ValueError("Guided translation supports Batch or Live API only.")
        if not isinstance(values["selected"], list) or any(
            not isinstance(name, str) for name in values["selected"]
        ):
            raise ValueError("Choose supported game files.")
        if len(set(values["selected"])) != len(values["selected"]):
            raise ValueError("Choose each game file once.")
        if (
            not isinstance(values["engine_options"], dict)
            or not isinstance(values["widths"], dict)
            or type(values["phase1_comments"]) is not bool
            or len(json.dumps(values)) > 200_000
        ):
            raise ValueError("Invalid guided options.")

    def save_options(self, project_id, revision, values):
        _, native = self.record(project_id)
        self.validate_options(values)
        if set(values["selected"]) - self.supported_files(native):
            raise ValueError(
                "Select files supported by this game's translation phases."
            )
        result = self.backend.workflows.update(native["id"], revision, values)
        self.options_draft(project_id, None)
        return self.preferences(result["project"])

    def state(self, project_id):
        with self.observations.read():
            return self._state(project_id)

    def _state(self, project_id):
        context = self.context_status(project_id)
        project, native = self.record(project_id)
        value = self.backend.workflows.state(native["id"])
        run_views = {}

        def run_view(identity, *, compact=False):
            key = (identity, compact)
            if key not in run_views:
                run_views[key] = self.run_view(identity, compact=compact)
            # Phase scope annotations must not leak into History or other phases.
            return dict(run_views[key])

        native = value["project"]
        supported = self.supported_files(native)
        native["files"] = [row for row in native["files"] if row["name"] in supported]
        native["selected"] = [name for name in native["selected"] if name in supported]
        database = set(self.backend.phase_files(native, "database"))
        for row in native["files"]:
            row["group"] = "database" if row["name"] in database else "dialogue"
        titles = self.backend.guided_titles(native)
        for row in native["files"]:
            if titles.get(row["name"]):
                row["title"] = titles[row["name"]]
        inputs = self.inputs(native)
        source_status = inputs.status(
            [row["name"] for row in native["files"]], self.observed_digest
        )
        source_status["retired"] = inputs.record().get("retired_runs", [])
        source_status["noRequests"] = inputs.no_requests()
        prepared = list(dict.fromkeys([*native["imported"], *source_status["ready"]]))
        if prepared != native["imported"]:
            native["imported"] = prepared
            self.backend.workflows.projects[native["id"]].update(imported=prepared)
            self.backend.workflows.save(self.backend.workflows.projects[native["id"]])
        position = self.path(project_id, "position")
        draft = self.path(project_id, "draft")
        saved_position = (
            retained_position(read_json(position)) if position.exists() else {}
        )
        documents = context_setup.retained_documents(
            native["source"],
            self.backend.workflows.documents(native["id"]),
            value.get("draft", {}).get("documents", {}),
        )
        paid = [
            self.backend.manual.jobs[identity]
            for identity in self.owned_runs(native)
            if identity in self.backend.manual.jobs
            and self.backend.manual.jobs[identity].get("mode") != "estimate"
        ]
        current_run = next(
            (
                job
                for job in paid
                if job["status"] in {"ready", "running", "waiting"}
                or self.batch_monitor.views.get(job["id"], {}).get("state")
                in {"monitoring", "collecting"}
            ),
            None,
        )
        recovered = read_json(draft) if draft.exists() else None
        rebased = context_setup.rebase_layout_draft(native, recovered)
        if recovered != rebased:
            write_json(draft, rebased)
        return {
            **value,
            **self.runs.snapshot(project_id, native, source_status, run_view=run_view),
            "manual_job": run_view(current_run["id"]) if current_run else None,
            "step": saved_position.get("step", "prepare"),
            "task": saved_position.get("task"),
            "positions": saved_position.get("positions", {})
            if isinstance(saved_position.get("positions", {}), dict)
            else {},
            "context_document": context_setup.selected_document(
                self.path(project_id, "context-document"), saved_position, documents
            ),
            "preferences": self.preferences(native),
            "options_draft": rebased,
            "form": self.saved_form(project_id),
            "preparation": self.preparation(native),
            "speaker_setup": self.speaker_findings(project_id, native),
            "speaker_scan": self.speakers(project_id),
            "context_setup": context,
            "reference_folders": reference_folders.describe(
                self.path(project_id, "reference-folders")
            ),
            "event_text": self.event_text.status(project_id, native),
            "tools": self.backend.guided_tools(native),
            "artifacts": self.release_artifacts(project_id, value["jobs"]),
            "ace_available": self.backend.ace_available(),
            "ace_packing": self.ace_packing(native),
            "documents": documents,
            "phase": project["phase"],
            "phase_files": [
                name
                for name in self.backend.phase_files(native, project["phase"])
                if name in native["selected"]
            ],
            "source_status": source_status,
            "readiness": self.readiness(project_id, native, value, source_status),
            "runs": [
                run_view(identity, compact=True)
                for identity in dict.fromkeys(
                    [*self.owned_runs(native), *native.get("kept_failed_runs", {})]
                )
                if identity in self.backend.manual.jobs
            ],
            "provider": {
                **self.settings.translation_defaults(),
                "credential_ready": self.settings.ready(),
                "connection": (self.settings.connection_summary() or {}).get(
                    "name", "No connection selected"
                ),
            },
        }

    def preparation(self, native):
        active = any(
            job.get("project_id") == native["id"]
            and job.get("action") in {"prepare_game", *preparation.LABELS}
            and job.get("status") in {"ready", "running", "waiting"}
            for job in self.backend.operations.jobs.values()
        )
        return preparation.state(
            native,
            self.backend.workflows.folder(native["id"]),
            active=active,
            observed=self.observed_digest,
        )

    def require_preparation(self, project_id, native):
        _, project = self.translation.project(project_id)
        options = project.read()["options"]
        if (
            not self.translation.engine.git_status(project.root, options)["configured"]
            and not self.preparation(native)["complete"]
        ):
            raise ValueError(
                "Complete game preparation first. Return to preparation before saving a new baseline."
            )

    def phase_select(self, project_id, phase):
        _project, _native = self.record(project_id)
        if phase not in PHASES:
            raise ValueError("Choose a supported RPG Maker phase.")
        data = deepcopy(self.projects.data)
        self.projects._get(data, project_id)["phase"] = phase
        self.projects._commit(data)
        return self.state(project_id)

    def source_preserved(self, project_id):
        project, _ = self.record(project_id)
        state = lifecycle(self.translation.workspace, project_id)
        require_source_backup(project["source"], state)
        return state

    def ace_packing(self, native):
        from .release import packing_state

        return packing_state(native, self.backend.workflows.folder(native["id"]))

    def release_paths(self, project_id, source, action):
        from .release import runtime_asset

        paths = set(self.backend.guided_runtime_files(source))
        paths.update(
            runtime_asset(source, name)
            for name in self.saved_form(project_id)["release"]["assets"]
        )
        if action == "release_patch":
            paths.discard("gameupdate/patch-config.txt")
        return sorted(paths)

    def release_ready(self, project_id, native, value):
        status = self.translation.ready(project_id)
        self.pending_run(value)
        source_status = self.inputs(native).status(sorted(self.supported_files(native)))
        if source_status["changed"]:
            raise ValueError("Review changed sources before packaging this pass.")
        readiness = self.readiness(project_id, native, value, source_status)
        if readiness["unapplied"]:
            raise ValueError(
                "Apply the selected saved outputs to the game before packaging them."
            )
        if not self.ace_packing(native)["current"]:
            raise ValueError(self.ace_packing(native)["message"])
        return status

    def clean(self, project_id):
        self.translation.clean_drafts(project_id)
        self.clean_options(project_id)

    def clean_options(self, project_id):
        path = self.path(project_id, "draft")
        if path.exists() and read_json(path) is not None:
            raise ValueError("Save or discard guided options before running an action.")

    @staticmethod
    def pending_run(value):
        job = value.get("manual_job")
        if job and job.get("status") in {"running", "waiting"}:
            raise ValueError(
                "Wait for the active worker before changing runtime files."
            )

    def submission_overlap(self, native, quote):
        """Advisory for a new cost review, never authority to deny a new run."""
        from dazedtl.compatibility.request_scope import overlap

        current = quote["jobId"]
        job = self.run_view(current, compact=True)
        previous = [
            (
                self.backend.manual.folder(identity),
                self.run_view(identity, compact=True),
            )
            for identity in self.owned_runs(native)
            if identity and identity != current and identity in self.backend.manual.jobs
        ]
        return overlap(self.backend.manual.folder(current), job, previous)

    def batch_output(self, native, run_id, files):
        if (
            not isinstance(run_id, str)
            or run_id not in self.owned_runs(native)
            or run_id not in self.backend.manual.jobs
        ):
            raise ValueError("Choose a saved Batch belonging to this project.")
        plan = self.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved Batch belongs to another project.")
        job = self.run_view(run_id)
        if (
            job.get("mode") != "batch"
            or job.get("status") != "complete"
            or job.get("temporary")
        ):
            raise ValueError(
                "Wait for this Batch to finish saving its results before reapplying it."
            )
        outputs = job.get("outputs", {})
        requested = sorted(outputs) if files is None else files
        if (
            not isinstance(requested, list)
            or not requested
            or any(not isinstance(name, str) for name in requested)
            or len(set(requested)) != len(requested)
            or set(requested)
            - (set(outputs) & set(job.get("files", [])) & self.supported_files(native))
        ):
            raise ValueError("Choose retained output files from this Batch.")
        if set(requested) - set(job.get("availableOutputs", [])):
            raise ValueError(
                "Saved Batch output is missing or changed. Its files cannot be reapplied."
            )
        return {
            "run_id": run_id,
            "folder": str(self.backend.manual.folder(run_id)),
            "outputs": {name: outputs[name] for name in requested},
        }, list(requested)

    def preview(
        self, project_id, action, files=None, options: dict[str, Any] | None = None
    ):
        if action != "start":
            self.idle(isolated_workers=action in {"export_selected", "refresh_sources"})
        project, native = self.record(project_id)
        self.clean(project_id)
        options = {} if options is None else deepcopy(options)
        if not isinstance(options, dict):
            raise ValueError("Action options must be an object.")
        run_output = None
        if action == "export_selected" and options:
            if set(options) != {"run_id"}:
                raise ValueError("Choose a saved Batch to reapply.")
            run_output, files = self.batch_output(native, options["run_id"], files)
        if action not in NATIVE_ACTIONS | SHARED_ACTIONS.keys() | {"start"}:
            raise ValueError("Choose a supported guided action.")
        self.settings.prepare_engine()
        value = self.backend.workflows.state(native["id"])
        if action != "backup_source":
            self.source_preserved(project_id)
        if (
            action
            in {
                "start",
                "export_selected",
                "rewrap_apply",
                "qa_apply",
                "runtime_restore",
                "ace_pack",
                "qa_prepare",
                "playtest_install",
                "checkpoint",
                "guided_review",
                "guided_package",
            }
            | TOOL_ACTIONS
        ):
            self.translation.ready(project_id)
        if (
            action in {"rewrap_apply", "qa_apply", "runtime_restore"}
            and self.inputs(native).status(sorted(self.supported_files(native)))[
                "changed"
            ]
        ):
            raise ValueError(
                "Original sources changed. Review source changes before replacing runtime text."
            )
        if action.startswith("ace_") and (
            native["engine"] != "ACE" or not self.backend.ace_available()
        ):
            raise ValueError(
                "Ace preparation requires a supported Windows environment and the bundled Ace tools."
            )
        if action in {"prepare_game", "format_data"}:
            preparation.require_data(native)
        if action == "format_plugins" and native["engine"] == "ACE":
            raise ValueError("Ace does not use plugins.js.")
        if action in TOOL_ACTIONS | {"playtest_status"} and native["engine"] != "MVMZ":
            raise ValueError("TL Inspector and Forge support RPG Maker MV/MZ games.")
        if action in {"release", "release_patch"}:
            release_status = self.release_ready(project_id, native, value)
        if action == "git_setup":
            self.require_preparation(project_id, native)
            if type(options.get("untranslated")) is not bool:
                raise ValueError(
                    "Choose whether this game is untranslated or already contains translations."
                )
        paths = []
        expected = None
        manifest = None
        if action == "start":
            if (
                set(options) - {"mode", "preparation_mode"}
                or options.get("mode")
                not in {"batch", "translate", "estimate", "speakers"}
                or "preparation_mode" in options
                and (
                    options["mode"] != "estimate"
                    or options["preparation_mode"] not in {"batch", "translate"}
                )
            ):
                raise ValueError(
                    "Choose Batch, Live API, a cost estimate, or speaker collection."
                )
            mode = options["mode"]
            if (
                options.get("preparation_mode")
                and options["preparation_mode"]
                != self.preferences(native)["values"]["mode"]
            ):
                raise ValueError(
                    "Save the intended translation mode before preparing its estimate."
                )
            phase = "speakers" if mode == "speakers" else project["phase"]
            if phase == "speakers" and mode != "speakers":
                raise ValueError("Choose a translation phase first.")
            if phase == "advanced":
                settings = native["engine_options"]
                if not any(settings.get(key) is True for key in ADVANCED_CODES):
                    raise ValueError(
                        "Audit advanced text and enable only confirmed player-visible sources, or skip this phase."
                    )
                if (
                    settings.get("CODE122") is True
                    and not settings.get("CODE122_VAR_RANGES", "").strip()
                ):
                    raise ValueError(
                        "Enter the variable IDs confirmed by the audit before translating variables (122)."
                    )
            paths = [
                name
                for name in self.backend.phase_files(native, phase)
                if name in native["selected"]
            ]
            if not paths:
                raise ValueError("Select game files belonging to this phase first.")
            if self.inputs(native).status(sorted(self.supported_files(native)))[
                "changed"
            ]:
                raise ValueError(
                    "The original source changed. Review source changes and refresh the working copies before preparing a new run."
                )
            if value["project"].get("collection_error"):
                raise ValueError(value["project"]["collection_error"])
            options["phase"] = phase
            if phase == "variables":
                comparisons = self.runs.comparisons(native)
                if not comparisons["matches"]:
                    raise ValueError(
                        "Translate the relevant audited assignments first. No saved mappings match the selected comparisons. "
                        + comparisons["message"]
                    )
                if comparisons["status"] != "ready":
                    raise ValueError(
                        "Review every matched literal and its variable uses before updating comparisons."
                    )
            if phase == "advanced":
                self.event_text.require(project_id, native)
            run_inputs = None
            quote = None
            if mode != "speakers":
                target_mode = (
                    self.preferences(native)["values"]["mode"]
                    if mode == "estimate"
                    else mode
                )
                matched, run_inputs = self.runs.quote(
                    project_id, native, phase, target_mode
                )
                if mode != "estimate":
                    if not matched["current"]:
                        raise ValueError(
                            "Calculate a current estimate for this phase, selection, and settings before reviewing translation."
                        )
                    quote = {
                        "jobId": matched["job"]["id"],
                        "fingerprint": run_inputs["fingerprint"],
                        "value": matched["job"]["estimate"],
                        "model": matched["job"].get("model", ""),
                        "connection": (self.settings.connection_summary() or {}).get(
                            "name", ""
                        ),
                    }
                    try:
                        quote["repeatSubmission"] = bool(
                            self.submission_overlap(native, quote)
                        )
                    except (OSError, ValueError, KeyError):
                        # Unreadable historical evidence cannot veto a separately
                        # approved run either; keep the repeat-charge notice.
                        quote["repeatSubmission"] = True
            label = {
                "batch": "Prepare Batch translation",
                "translate": "Start Live API translation",
                "estimate": "Estimate selected phase",
                "speakers": "Collect speaker names",
            }[mode]
        elif action in SHARED_ACTIONS:
            label = SHARED_ACTIONS[action]
            allowed = (
                {"version", "original", "untranslated"}
                if action == "git_setup"
                else {"reviewed", "playtested"}
                if action == "guided_review"
                else {"output"}
                if action == "release_patch"
                else set()
            )
            if set(options) - allowed:
                raise ValueError("Unknown guided action option.")
            if action == "backup_source":
                saved = lifecycle(self.translation.workspace, project_id).get(
                    "source_backup"
                )
                if (
                    saved
                    and backups.record_status(project["source"], saved, kind="source")[
                        "available"
                    ]
                ):
                    raise ValueError(
                        "The original is already preserved. Use workspace backups for later milestones."
                    )
            if action == "refresh_sources":
                if (
                    not isinstance(files, list)
                    or not files
                    or any(not isinstance(name, str) for name in files)
                    or len(set(files)) != len(files)
                    or set(files) - self.supported_files(native)
                ):
                    raise ValueError("Select supported files to refresh.")
                paths = files
                options = {
                    "sources": self.inputs(native).sources(
                        paths, self.inputs(native).record()["inputs"], fresh=True
                    )
                }
            if action in {"git_setup", "checkpoint", "guided_review", "release_patch"}:
                paths = self.release_paths(project_id, project["source"], action)
                manifest = self.patch_manifest(project_id, paths, action)
                expected = evidence(project["source"], [*paths, *manifest["inputs"]])
            if action == "release_patch":
                from .release import destination, git_identity, output_hash

                output = destination(
                    project["source"],
                    self.translation.workspace,
                    self.backend.source,
                    options.get("output"),
                )
                options = {
                    "output": str(output),
                    "output_hash": output_hash(output),
                    "source_inputs_sha256": digest(self.inputs(native).record()),
                    "git": git_identity(release_status),
                }
            if action == "guided_review" and (
                options.get("reviewed") is not True
                or options.get("playtested") is not True
            ):
                raise ValueError(
                    "Review the translated scope and playtest it before recording release readiness."
                )
            if action == "guided_review":
                options["source_inputs_sha256"] = digest(self.inputs(native).record())
            if action == "guided_package":
                self.verify_review(project_id, native)
        else:
            if action == "import":
                if not isinstance(files, list) or any(
                    not isinstance(name, str)
                    or name not in self.supported_files(native)
                    for name in files
                ):
                    raise ValueError(
                        "Select supported RPG Maker files from this project's list."
                    )
                options = {"files": files or []}
            elif action == "export_selected" and run_output:
                paths = files
                options = {"files": paths, "run_id": run_output["run_id"]}
            elif action == "export_selected":
                if value["project"].get("collection_error"):
                    raise ValueError(value["project"]["collection_error"])
                requested = native["selected"] if files is None else files
                if (
                    not isinstance(requested, list)
                    or any(not isinstance(name, str) for name in requested)
                    or len(set(requested)) != len(requested)
                    or set(requested) - set(native["selected"])
                ):
                    raise ValueError("Choose saved outputs within the selected scope.")
                paths = [
                    name
                    for name in requested
                    if self.inputs(native).path("translated", name).is_file()
                ]
                if files is not None and paths != files:
                    raise ValueError(
                        "The selected run outputs are no longer available. Review current outputs."
                    )
                if not paths:
                    raise ValueError(
                        "No saved translation output is available for these files yet."
                    )
                options = {"files": paths}
            if action == "release":
                from .release import destination

                if set(options) != {"output"}:
                    raise ValueError("Choose the release destination.")
                options["output"] = str(
                    destination(
                        project["source"],
                        self.translation.workspace,
                        self.backend.source,
                        options["output"],
                    )
                )
            result = (
                self.backend.guided_text_preview(native["id"], action, options)
                if action in {"runtime_restore", "qa_apply"}
                else self.backend.guided_export_preview(
                    native["id"], paths, run_output=run_output
                )
                if run_output
                else self.backend.guided_export_preview(native["id"], paths)
                if action == "export_selected"
                else self.backend.guided_preparation_preview(
                    native["id"], action, options
                )
                if action == "prepare_game"
                else self.backend.workflows.preview(native["id"], action, options)
            )
            token = result["token"]
            if action in TOOL_ACTIONS:
                configured = self.saved_form(project_id)["release"]["tools"]
                if (
                    not configured["hotkey"].strip()
                    or not configured["forgeHotkey"].strip()
                ):
                    raise ValueError("Choose hotkeys for the playtest tools.")
                self.backend.guided_configure_tools(token, configured)
            if action == "release":
                result.update(self.backend.guided_release_preview(token))
            if action == "rewrap_apply":
                result["rewrap"] = self.backend.guided_rewrap_review(
                    native["id"], token
                )
            if action in {"export_selected", "rewrap_apply"}:
                result.update(self.backend.guided_text_publication(token))
            reviewed_paths = (
                paths or result.get("paths") or result["options"].get("files", [])
            )
            self.confirmations = {
                token: {
                    "project_id": project_id,
                    "action": action,
                    "native": True,
                    "paths": list(reviewed_paths),
                    "revision": native["revision"],
                    "phase": project["phase"],
                    "settings_revision": self.settings.describe()["revision"],
                }
            }
            # Routine preparation uses the same one-use plan and execution checks,
            # without asking the user to confirm the button they just clicked.
            return {
                **result,
                "action": action,
                "paths": reviewed_paths,
                "confirmation": (
                    bool(result.get("overwrite"))
                    if action == "release"
                    else result["confirmation"]
                    and action
                    not in {
                        "prepare_game",
                        "format_data",
                        "format_plugins",
                        "gameupdate",
                        "qa_prepare",
                        "playtest_install",
                        "playtest_apply",
                        "inspector_install",
                        "forge_install",
                        "reference_build",
                        "reference_remove",
                    }
                ),
            }
        token = uuid.uuid4().hex
        self.confirmations = {
            token: {
                "project_id": project_id,
                "action": action,
                "options": options,
                "paths": paths,
                "evidence": expected,
                "manifest": manifest,
                "guard": self.backend.guided_guard(
                    native, self.backend.workflows.folder(native["id"])
                ),
                "revision": native["revision"],
                "phase": project["phase"],
                "settings_revision": self.settings.describe()["revision"],
                "run_inputs": run_inputs if action == "start" else None,
                "estimate": quote if action == "start" else None,
            }
        }
        destination = (
            str(backups.store_path(project["source"]))
            if action == "backup_source"
            else options["output"]
            if action == "release_patch"
            else project["source"]
        )
        return {
            "token": token,
            "action": action,
            "label": label,
            "destination": destination,
            "files": len(paths),
            "paths": paths,
            "options": options,
            "estimate": quote if action == "start" else None,
            "run": {
                "model": quote["model"],
                "connection": quote["connection"],
                "mode": options["mode"],
            }
            if action == "start" and quote
            else None,
            "confirmation": (
                bool(
                    lifecycle(self.translation.workspace, project_id).get(
                        "source_backup"
                    )
                )
                if action == "backup_source"
                else not (action == "start" and options["mode"] == "estimate")
            ),
            "package": {
                "included": len(paths),
                "excluded": int(
                    (Path(project["source"]) / "gameupdate/patch-config.txt").is_file()
                ),
                "exclusions": [
                    {
                        "path": "gameupdate/patch-config.txt",
                        "reason": "GameUpdate disabled in this local patch; publication is separate",
                    }
                ]
                if (Path(project["source"]) / "gameupdate/patch-config.txt").is_file()
                else [],
                "updater": "GameUpdate configuration is omitted from local patches. Publishing is separate.",
                "generated": [".gitignore", ".gitattributes", "README.md"],
            }
            if action == "release_patch"
            else None,
            "overwrite": bool(options.get("output_hash"))
            if action == "release_patch"
            else False,
            "game_version": release_status.get("original_version")
            if action == "release_patch"
            else None,
            "additions": [
                name
                for name, row in manifest["files"].items()
                if row.get("original_sha256", "") is None
            ]
            if manifest
            else [],
        }

    def execute(self, project_id, token):
        confirmed = self.confirmations.get(token)
        if not confirmed or confirmed["project_id"] != project_id:
            raise ValueError("The action changed. Review a new preview.")
        self.clean(project_id)
        project, native = self.record(project_id)
        self.confirmations.pop(token)
        action = confirmed["action"]
        if action != "start":
            self.idle(isolated_workers=action in {"export_selected", "refresh_sources"})
        if action != "backup_source":
            self.source_preserved(project_id)
        if (
            action
            in {
                "start",
                "export_selected",
                "rewrap_apply",
                "qa_apply",
                "runtime_restore",
                "ace_pack",
                "qa_prepare",
                "playtest_install",
                "checkpoint",
                "guided_review",
                "guided_package",
            }
            | TOOL_ACTIONS
        ):
            self.translation.ready(project_id)
        if (
            action in {"rewrap_apply", "qa_apply", "runtime_restore"}
            and self.inputs(native).status(sorted(self.supported_files(native)))[
                "changed"
            ]
        ):
            raise ValueError(
                "Original sources changed after review. Review current sources first."
            )
        if action in {"release", "release_patch"}:
            release_status = self.release_ready(
                project_id, native, self.backend.workflows.state(native["id"])
            )
        if confirmed.get("native"):
            if (
                confirmed["revision"] != native["revision"]
                or confirmed["phase"] != project["phase"]
                or confirmed["settings_revision"]
                != self.settings.describe()["revision"]
            ):
                raise ValueError(
                    "The selection or settings changed. Review the action again."
                )
            if action == "release":
                self.backend.guided_release_validate(token)
            return self.backend.workflows.execute(token)
        if (
            confirmed["guard"]
            != self.backend.guided_guard(
                native, self.backend.workflows.folder(native["id"])
            )
            or confirmed["revision"] != native["revision"]
            or confirmed["phase"] != project["phase"]
            or confirmed["settings_revision"] != self.settings.describe()["revision"]
        ):
            raise ValueError(
                "The game, selection, or settings changed. Review the action again."
            )
        if confirmed["evidence"]:
            verify_evidence(project["source"], confirmed["evidence"])
            if (
                self.release_paths(project_id, project["source"], action)
                != confirmed["paths"]
            ):
                raise ValueError(
                    "The runtime file list changed. Review the complete patch again."
                )
        options = confirmed["options"]
        if action == "release_patch":
            from .release import git_identity

            if git_identity(release_status) != options["git"]:
                raise ValueError(
                    "Version tracking changed. Review the current patch scope again."
                )
        if action == "start":
            if confirmed["run_inputs"]:
                current = self.runs.inputs(
                    project_id,
                    native,
                    options["phase"],
                    confirmed["run_inputs"]["mode"],
                )
                if current["fingerprint"] != confirmed["run_inputs"]["fingerprint"]:
                    raise ValueError(
                        "The estimate inputs changed. Refresh the estimate and review this run again."
                    )
                if options["mode"] != "estimate":
                    matched, _ = self.runs.quote(
                        project_id, native, options["phase"], options["mode"]
                    )
                    if (
                        not matched["current"]
                        or matched["job"]["id"] != confirmed["estimate"]["jobId"]
                    ):
                        raise ValueError(
                            "The matching estimate changed. Review a new preview."
                        )
            return self._start(
                project_id,
                options["mode"],
                options["phase"],
                confirmed["paths"],
                confirmed["run_inputs"],
                confirmed["estimate"],
                options.get("preparation_mode"),
            )
        if action == "refresh_sources":
            return self.backend.guided_refresh(
                native, confirmed["paths"], options["sources"]
            )
        if action == "git_setup":
            self.require_preparation(project_id, native)
        if action in {"git_setup", "checkpoint", "guided_review", "release_patch"}:
            if confirmed["manifest"] != self.patch_manifest(
                project_id, confirmed["paths"], action
            ):
                raise ValueError(
                    "The original or runtime scope changed. Review the patch again."
                )
            write_json(
                project_path(project["source"], MANIFEST, exists=False),
                confirmed["manifest"],
            )
            options = {**options, "manifest": MANIFEST}
        if action == "release_patch":
            from .release import output_hash

            inputs = self.inputs(native)
            current = inputs.record()
            if (
                digest(current) != options["source_inputs_sha256"]
                or output_hash(options["output"]) != options["output_hash"]
            ):
                raise ValueError(
                    "The source pass or release destination changed. Review a new package preview."
                )
            if not inputs.index.exists():
                write_json(inputs.index, current)
            payload = {
                "version": 1,
                "project_id": project_id,
                "source": project["source"],
                "manifest": MANIFEST,
                "evidence": evidence(
                    project["source"],
                    [
                        MANIFEST,
                        *confirmed["paths"],
                        *confirmed["manifest"].get("inputs", []),
                    ],
                ),
                "source_inputs": inputs.index.relative_to(
                    self.translation.workspace
                ).as_posix(),
                "source_inputs_sha256": digest(current),
                "git": options["git"],
                "output": options["output"],
                "output_hash": options["output_hash"],
            }
            path = self.path(project_id, "release-" + uuid.uuid4().hex)
            write_json(path, payload)
            return self.translation.guided_operation(
                project_id,
                "release_patch",
                {
                    "plan": path.relative_to(self.translation.workspace).as_posix(),
                    "sha256": digest(payload),
                },
            )
        if action == "guided_review":
            inputs = self.inputs(native)
            current = inputs.record()
            if digest(current) != options["source_inputs_sha256"]:
                raise ValueError("Working sources changed. Review this pass again.")
            if not inputs.index.exists():
                write_json(inputs.index, current)
            options = {
                "manifest": MANIFEST,
                "source_inputs": inputs.index.relative_to(
                    self.translation.workspace
                ).as_posix(),
                "source_inputs_sha256": digest(current),
            }
        if action == "guided_package":
            self.verify_review(project_id, native)
        operation = (
            self.translation.guided_operation
            if action in {"guided_review", "guided_package"}
            else self.translation.operation
        )
        return operation(project_id, action, options)

    def verify_review(self, project_id, native):
        state = lifecycle(self.translation.workspace, project_id)
        review = verify_guided_review(
            native["source"], state, self.translation.workspace, self.translation.engine
        )
        inputs = self.inputs(native)
        if (
            not review.get("source_inputs_sha256")
            and inputs.record().get("last_refresh")
            or inputs.status(sorted(self.supported_files(native)))["changed"]
        ):
            raise ValueError(
                "Source work changed after review. Playtest and record the current pass again."
            )

    def _start(
        self,
        project_id,
        mode,
        phase,
        files,
        run_inputs=None,
        estimate=None,
        preparation_mode=None,
    ):
        _, native = self.record(project_id)
        if self.resyncing(native):
            raise ValueError(
                "Wait for the working files to finish resyncing before preparing translation."
            )
        if mode == "estimate":
            from dazedtl.compatibility.preparations import temporary

            records = self.runs.records(project_id)
            for identity in self.owned_runs(native):
                job = self.backend.manual.jobs.get(identity)
                record = records.get(identity, {})
                if job and temporary(job) and record.get("phase") == phase:
                    self.discard_preparation(project_id, identity)
                elif job and job.get("approval") and record.get("phase") == phase:
                    self.answer(project_id, job["approval"]["token"], False)
        if preparation_mode:
            assert run_inputs is not None  # Preparation follows a confirmed estimate.
            for identity, record in reversed(
                list(self.runs.records(project_id).items())
            ):
                job = self.backend.manual.jobs.get(identity)
                if (
                    job
                    and job.get("mode") == "estimate"
                    and job.get("status") in {"ready", "running", "waiting"}
                    and record.get("preparation_mode") == preparation_mode
                    and record.get("fingerprint") == run_inputs["fingerprint"]
                ):
                    return self.run_view(identity)
        self.inputs(native).prepare(files)
        native["imported"] = list(dict.fromkeys([*native["imported"], *files]))
        self.backend.workflows.save(native)
        self.settings.prepare_engine(mode=mode)
        self.backend.manual.source_versions = (
            run_inputs.get("file_versions", {}) if run_inputs else {}
        )
        self.backend.manual.reused_names = (
            run_inputs.get("reused_names", []) if run_inputs else []
        )
        self.backend.manual.continuation = (
            self.runs.continuation(project_id, native, run_inputs) if run_inputs else {}
        )
        from dazedtl.compatibility.request_scope import requests

        self.backend.manual.reserved_sources = (
            list(
                requests(
                    self.backend.manual.folder(estimate["jobId"]),
                    self.run_view(estimate["jobId"]),
                )
            )
            if estimate
            else []
        )
        previous_mode = self.preferences(native)["values"]["mode"]
        if mode != "speakers":
            self.backend.workflows.update(
                native["id"], native["revision"], {"mode": mode}
            )
        try:
            self.backend.manual.temporary_preparation = mode in {"estimate", "batch"}
            job = self.backend.guided_phase(native["id"], phase, files)
            if run_inputs:
                self.runs.remember(
                    project_id, job, run_inputs, estimate, preparation_mode
                )
            if estimate and self.backend.manual.jobs.get(estimate["jobId"], {}).get(
                "dazedtl_preapproval"
            ):
                self.discard_preparation(project_id, estimate["jobId"])
            return {**job, "logicalPhase": phase, "preparationMode": preparation_mode}
        finally:
            self.backend.manual.temporary_preparation = False
            self.backend.manual.continuation = None
            self.backend.manual.source_versions = None
            self.backend.manual.reused_names = None
            self.backend.manual.reserved_sources = None
            if mode == "estimate":
                current = self.backend.workflows.projects[native["id"]]
                self.backend.workflows.update(
                    native["id"], current["revision"], {"mode": previous_mode}
                )

    def skill(self, project_id, name):
        self.clean(project_id)
        project, native = self.record(project_id)
        if name not in {
            "setup",
            "advanced",
            "wrap",
            "plugins",
            "walkthrough",
            "investigation",
        }:
            raise ValueError("Choose a task-specific helper.")
        if name == "advanced":
            request = self.event_text.request(project_id, native)
            command = shlex.join(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parents[3] / "scripts/project.py"),
                    "--workspace",
                    str(self.translation.workspace),
                    "--project",
                    project_id,
                    "event-text",
                ]
            )
            return {"text": self.event_text.instructions(request, command)}
        text = self.backend.workflows.skill(native["id"], name)
        if name == "setup":
            schema = self.backend.workflows.state(native["id"])["engine_schema"]
            request = speaker_setup.request(
                self.path(project_id, "speaker-request"), project_id, native, schema
            )
            command = shlex.join(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parents[3] / "scripts/project.py"),
                    "--workspace",
                    str(self.translation.workspace),
                    "--project",
                    project_id,
                    "speakers",
                ]
            )
            context_request = context_setup.request(
                self.path(project_id, "context-request"),
                project_id,
                request,
                native["widths"],
            )
            context_command = command.removesuffix("speakers") + "context"
            text += context_setup.instructions(context_request, context_command)
            text = (
                speaker_setup.instructions(request, command)
                + reference_folders.instructions(
                    reference_folders.records(
                        self.path(project_id, "reference-folders")
                    )
                )
                + "\n## Glossary and context investigation (after the local speaker scan)\n"
                + text
            )
        if name == "wrap":
            path = self.path(project_id, "context-request")
            previous = context_setup.optional_record(path)
            request = context_setup.request(
                path,
                project_id,
                {"request_id": previous.get("speaker_request_id", "layout")},
                native["widths"],
            )
            command = shlex.join(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve().parents[3] / "scripts/project.py"),
                    "--workspace",
                    str(self.translation.workspace),
                    "--project",
                    project_id,
                    "context",
                ]
            )
            text += context_setup.layout_instructions(request, command)
        return {
            "text": f"Selected game: {project['source']}\n\nThis is one user-requested Guided Workflow task: {name}. Complete only this task, report what changed and what needs review, then stop. The user controls translation submission, export, versioning and packaging in DazedTL.\n\n"
            + text
        }

    def event_text_request(self, project_id):
        _, native = self.record(project_id)
        path = self.path(project_id, "event-text-request")
        return {
            "request": read_json(path) if path.exists() else None,
            "findings": self.event_text.status(project_id, native),
        }

    def event_text_review(
        self,
        project_id,
        revision,
        binding,
        report_id=None,
        manual_reason="",
        risk_accepted=False,
    ):
        return self.event_text.review(
            project_id, revision, binding, report_id, manual_reason, risk_accepted
        )

    def event_text_view(self, project_id, view):
        return self.event_text.view(project_id, view)

    def event_text_picker(self, project_id, value):
        return self.event_text.picker(project_id, value)

    def comparisons_review(self, project_id, fingerprint, accepted):
        self.idle()
        _, native = self.record(project_id)
        current = self.runs.comparisons(native)
        if (
            accepted is not True
            or not current["matches"]
            or current["fingerprint"] != fingerprint
        ):
            raise ValueError(
                "The saved mappings or selected comparison uses changed. Review them again."
            )
        write_json(
            self.path(project_id, "comparisons-review"),
            {"fingerprint": fingerprint, "accepted": True},
        )
        return {"saved": True}

    def reference_add(self, project_id, folder):
        self.record(project_id)
        return reference_folders.add(self.path(project_id, "reference-folders"), folder)

    def reference_remove(self, project_id, reference_id):
        self.record(project_id)
        return reference_folders.remove(
            self.path(project_id, "reference-folders"), reference_id
        )

    def context_status(self, project_id, retry_layout=False):
        _, native = self.record(project_id)
        if type(retry_layout) is not bool:
            raise ValueError("Choose whether to retry saving the measured layout.")
        if retry_layout:
            self.layout_failures.pop(project_id, None)
        request_path = self.path(project_id, "context-request")

        def inspect():
            return context_setup.inspect(
                request_path,
                self.path(project_id, "context-review"),
                native,
                project_id,
                self.backend.workflows.documents(native["id"]),
                self.speaker_findings(project_id, native),
                self.speakers(project_id),
                self.observed_digest,
                self.backend.workflows.state(native["id"]).get("references", []),
            )

        setup = inspect()
        update = context_setup.layout_update(
            native, setup, context_setup.optional_record(request_path)
        )
        failure = self.layout_failures.get(project_id)
        if update and failure and failure["reportId"] == update["reportId"]:
            return {**setup, "layoutMessage": failure["message"]}
        draft_path = self.path(project_id, "draft")
        draft = read_json(draft_path) if draft_path.exists() else None
        if (
            update
            and not draft
            and not self.backend.running()
            and not self.translation.jobs.running()
        ):
            try:
                native = self.backend.workflows.apply_layout_settings(
                    native["id"], native["revision"], update
                )
                self.layout_failures.pop(project_id, None)
                setup = inspect()
            except (OSError, ValueError) as exc:
                setup["layoutMessage"] = "Measured layout could not be saved: " + str(
                    exc
                )
                self.layout_failures[project_id] = {
                    "reportId": update["reportId"],
                    "message": setup["layoutMessage"],
                }
        return setup

    def context_review(self, project_id, name, revision, choice):
        self.idle()
        _, native = self.record(project_id)
        documents = self.backend.workflows.documents(native["id"])
        return context_setup.review(
            self.path(project_id, "context-review"),
            documents,
            native,
            name,
            revision,
            choice,
        )

    def speaker_findings(self, project_id, native=None):
        if native is None:
            _, native = self.record(project_id)
        return speaker_setup.inspect(
            self.path(project_id, "speaker-request"),
            native,
            project_id,
            self.observed_digest,
        )

    def apply_speakers(self, project_id, revision, report_id, reset=False):
        self.idle()
        self.clean_options(project_id)
        _, native = self.record(project_id)
        if (
            type(revision) is not int
            or type(reset) is not bool
            or native["revision"] != revision
        ):
            raise ValueError(
                "The guided project changed. Reload before applying speaker findings."
            )
        findings = self.speaker_findings(project_id, native)
        if (
            not report_id
            or findings["reportId"] != report_id
            or findings["status"] not in {"ready", "applied"}
        ):
            raise ValueError(findings["message"])
        if findings["status"] == "applied" and not reset:
            return self.preferences(native)
        options, receipt = speaker_setup.configured(
            self.path(project_id, "speaker-request"), native, findings, reset=reset
        )
        updated = self.backend.workflows.apply_speaker_settings(
            native["id"], revision, options, receipt
        )
        return self.preferences(updated)

    @staticmethod
    def speaker_configuration(native):
        return digest(
            {
                "engine_options": native["engine_options"],
                "phase1_comments": native["phase1_comments"],
            }
        )

    def speakers(self, project_id, scan=False):
        if type(scan) is not bool:
            raise ValueError("Choose whether to run the local speaker scan.")
        _, native = self.record(project_id)
        if scan:
            self.clean_options(project_id)
            findings = self.speaker_findings(project_id, native)
            existing = self.speakers(project_id)
            if findings["status"] == "applied" and (
                existing["current"]
                or existing["job"]
                and existing["job"]["status"] == "running"
            ):
                return existing
            self.idle()
            self.open(project_id)
            _, native = self.record(project_id)
            if findings["status"] not in {"ready", "applied"}:
                raise ValueError(
                    "Identify speaker formats and save their evidence before running the speaker scan."
                )
            self.apply_speakers(project_id, native["revision"], findings["reportId"])
            _, native = self.record(project_id)
            files = self.backend.phase_files(native, "speakers")
            if not files:
                raise ValueError(
                    "Prepare the game’s event JSON before scanning speakers."
                )
            self.backend.operations.start(
                {
                    "project_id": native["id"],
                    "project": deepcopy(native),
                    "folder": str(self.backend.workflows.folder(native["id"])),
                    "action": "speaker_scan",
                    "label": "Scan speaker names",
                    "guard": self.backend.guided_guard(
                        native, self.backend.workflows.folder(native["id"])
                    ),
                    "options": {
                        "files": files,
                        "configuration": self.speaker_configuration(native),
                        "reportId": findings["reportId"],
                    },
                }
            )
        jobs = sorted(
            (
                job
                for job in self.backend.operations.jobs.values()
                if job["project_id"] == native["id"] and job["action"] == "speaker_scan"
            ),
            key=lambda job: job["created"],
            reverse=True,
        )
        job = jobs[0] if jobs else None
        artifact = None
        try:
            artifact = project_path(native["source"], ".dazedtl/guided/speakers.json")
            artifact_hash = self.observed_digest(artifact)
        except (OSError, ValueError):
            artifact_hash = None
        saved = next(
            (
                item
                for item in jobs
                if item["status"] == "complete"
                and artifact_hash
                and (item.get("result") or {}).get("artifact_sha256") == artifact_hash
            ),
            None,
        )
        result = saved.get("result") or {} if saved else {}
        available = saved is not None
        current = bool(
            saved
            and job is not None
            and job["id"] == saved["id"]
            and result.get("configuration") == self.speaker_configuration(native)
            and result.get("reportId")
            == native.get("guided_speakers", {}).get("reportId")
            and result.get("reportId")
            == self.speaker_findings(project_id, native)["reportId"]
        )
        if current:
            try:
                root = Path(native["source"])
                data = Path(native["data"])
                data_relative = data.relative_to(root)
                inventory = {
                    path.relative_to(root).as_posix()
                    for path in data.iterdir()
                    if path.is_file() and path.suffix.lower() == ".json"
                }
                scanned = {
                    name
                    for name in result.get("source_inputs", {})
                    if Path(name).parent == data_relative
                    and Path(name).suffix.lower() == ".json"
                }
                current = (
                    inventory == scanned
                    and bool(scanned)
                    and all(
                        self.observed_digest(project_path(native["source"], name))
                        == sha
                        for name, sha in result["source_inputs"].items()
                    )
                )
            except (OSError, ValueError):
                current = False
        return {
            "job": job,
            "available": available,
            "current": current,
            "names": result.get("names", []),
            "actorNames": result.get("actor_names", {}),
            "variableActorIds": result.get("variable_actor_ids", {}),
            "files": result.get("files", 0),
            "savedAt": (saved.get("updated") or saved.get("created"))
            if saved
            else None,
            "path": str(artifact) if available else None,
            "issue": "The saved scan file is missing or no longer matches its saved result."
            if not available and any(item["status"] == "complete" for item in jobs)
            else "",
        }

    def job(self, project_id):
        _, native = self.record(project_id)
        active = next(
            (
                identity
                for identity in self.owned_runs(native)
                if identity in self.backend.manual.jobs
                and self.backend.manual.jobs[identity].get("mode") != "estimate"
                and self.backend.manual.jobs[identity].get("status")
                in {"running", "waiting"}
            ),
            None,
        )
        identity = active or native.get("manual_job")
        if not identity or identity not in self.backend.manual.jobs:
            raise ValueError("There is no translation run for this project.")
        return self.backend.manual.jobs[identity]

    def answer(self, project_id, token, approved):
        _, native = self.record(project_id)
        if type(approved) is not bool:
            raise ValueError("Choose whether to approve this submission.")
        job = next(
            (
                self.backend.manual.jobs[identity]
                for identity in self.owned_runs(native)
                if identity in self.backend.manual.jobs
                and (self.backend.manual.jobs[identity].get("approval") or {}).get(
                    "token"
                )
                == token
            ),
            None,
        )
        if not job:
            raise ValueError("This approval is no longer pending. Refresh the run.")
        if approved:
            if job.get("dazedtl_preapproval") and not job.get("dazedtl_approved"):
                record = self.runs.records(project_id).get(job["id"])
                if (
                    not record
                    or self.runs.inputs(
                        project_id, native, record["phase"], record["mode"]
                    )["fingerprint"]
                    != record["fingerprint"]
                ):
                    raise ValueError(
                        "The files or settings changed after preparation. Click Translate for a fresh estimate."
                    )
            if job.get("mode") == "batch":
                # Persist intent before signaling the native worker, closing the
                # gap between approval and its first provider manifest write.
                job["dazedtl_submission_intent"] = True
                self.backend.manual.save(job)
        return self.backend.manual.answer(job["id"], token, approved)

    def stop(self, project_id, run_id=None):
        _, native = self.record(project_id)
        if run_id is not None:
            if run_id not in self.owned_runs(native):
                raise ValueError("Choose a run owned by this project.")
            result = self.backend.manual.stop(run_id)
            if result.get("mode") == "estimate":
                records = self.runs.records(project_id)
                if run_id in records:
                    records[run_id]["preparation_mode"] = None
                    write_json(
                        self.path(project_id, "runs"), {"version": 1, "runs": records}
                    )
            return result
        operation = self.backend.operations.jobs.get(self.backend.operations.active)
        if operation and operation["project_id"] == native["id"]:
            return self.backend.operations.stop(operation["id"])
        return self.backend.manual.stop(self.job(project_id)["id"])

    def resume(self, project_id, run_id=None):
        self.idle()
        _, native = self.record(project_id)
        identity = run_id if run_id is not None else self.job(project_id)["id"]
        if not isinstance(identity, str) or identity not in self.owned_runs(native):
            raise ValueError("Choose a saved run belonging to this project.")
        from dazedtl.compatibility.preparations import temporary

        if temporary(self.backend.manual.jobs.get(identity, {})):
            raise ValueError(
                "Unapproved preparation cannot be resumed. Click Translate for a fresh estimate."
            )
        if self.backend.manual.jobs.get(identity, {}).get("mode") == "batch":
            plan = self.backend.saved_run_configuration(identity)
            if (plan.get("workflow") or {}).get("id") != native[
                "id"
            ] or self.batch_monitor._superseded(identity, plan):
                raise ValueError(
                    "A newer approved run owns these files. Continue that run instead."
                )
            from dazedtl.compatibility.batch_continuation import (
                approved_binding,
                validate_submission_records,
            )

            root = self.backend.manual.folder(identity)
            approved_binding(root, self.backend.manual.jobs[identity], plan)
            validate_submission_records(root)
            self.settings.prepare_engine(resume=plan)
            return self.backend.manual.continue_batch(identity, explicit=True)
        plan = self.backend.saved_run_configuration(identity)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved run belongs to another project.")
        self.settings.prepare_engine(resume=plan)
        return self.backend.manual.resume(identity)

    def output_folder(self, project_id):
        _, native = self.record(project_id)
        self.backend.workflows.state(native["id"])
        folder = project_path(
            self.backend.workflows.folder(native["id"]), "translated", exists=False
        )
        if not folder.is_dir():
            raise ValueError("No translated folder is available for this project.")
        return {"path": str(folder)}

    def export(self, project_id, run_id=None):
        """Retained for the legacy-run recovery helper, not the Guided UI."""
        self.idle()
        _, native = self.record(project_id)
        identity = run_id if run_id is not None else self.job(project_id)["id"]
        if not isinstance(identity, str) or identity not in self.owned_runs(native):
            raise ValueError("Choose a saved run belonging to this project.")
        if (self.backend.saved_run_configuration(identity).get("workflow") or {}).get(
            "id"
        ) != native["id"]:
            raise ValueError("This saved output belongs to another project.")
        return self.backend.manual.export(identity)

    def draft(self, project_id, documents):
        _, native = self.record(project_id)
        current = self.backend.workflows.state(native["id"]).get("draft", {})
        return self.backend.workflows.draft(
            native["id"], {**current, "documents": documents}
        )

    def save_document(self, project_id, name, revision, text):
        _, native = self.record(project_id)
        if not isinstance(name, str):
            raise ValueError("Choose a guidance document.")
        # Explicit Save replaces the current guidance. The editor's older
        # revision is recovery metadata, not a conflict-review prerequisite.
        current = self.backend.workflows.documents(native["id"]).get(name, {})
        result = self.backend.workflows.document_save(
            native["id"], name, current.get("revision", ""), text
        )
        draft = self.backend.workflows.state(native["id"]).get("draft", {})
        draft.get("documents", {}).pop(name, None)
        self.backend.workflows.draft(native["id"], draft)
        return result
