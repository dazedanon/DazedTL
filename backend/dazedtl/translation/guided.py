"""User-driven RPG Maker workflow over preserved engines and shared project services."""

import re
from copy import deepcopy
from pathlib import Path

from dazedtl.storage import write_json

from . import context_setup, preparation, reference_folders, speaker_setup
from .event_text import EventText
from .files import digest, project_path, read_json
from .guided_actions import ADVANCED_CODES, GuidedActions
from .guided_context import GuidedContext
from .guided_inputs import GuidedInputs
from .guided_inspection import RunInspection
from .guided_release import GuidedRelease
from .guided_runs import GuidedRuns
from .operations import lifecycle, require_source_backup

STEPS = {"setup", "context", "translate", "check", "release"}
PHASES = {"database", "dialogue", "variables", "advanced", "speakers"}
# Stages that earlier versions saved, and the stage that holds their work now.
LEGACY_STEPS = {
    "prepare": "setup",
    "advanced": "translate",
    "plugins": "translate",
    "images": "translate",
    "apply": "check",
    "layout": "check",
    "review": "release",
}
# Tasks that earlier versions saved inside a stage that no longer has them.
LEGACY_TASKS = {
    "backup": "setup",
    "extract": "setup",
    "format": "setup",
    "baseline": "setup",
    "image-text": "images",
    "image-manager": "images",
    "playtest": "apply",
    "tools": "apply",
}


def retained_position(value):
    """Opens positions saved by earlier stage layouts on the task that holds
    their work now, without rewriting the saved file."""
    value = dict(value)
    if "task" in value:
        value["task"] = LEGACY_TASKS.get(value["task"], value["task"])
    if "step" in value:
        value["step"] = LEGACY_STEPS.get(value["step"], value["step"])
    if value.get("task") in {"plugins", "images"}:
        value["step"] = "translate"
    elif value.get("task") in {"apply", "fitting", "qa"}:
        value["step"] = "check"
    saved = value.get("positions")
    positions = {}
    for old, task in saved.items() if isinstance(saved, dict) else ():
        current = LEGACY_STEPS.get(old, old)
        task = LEGACY_TASKS.get(task, task)
        # A stage's own saved task wins over one moved in from a retired stage.
        if current in STEPS and (old == current or current not in positions):
            positions[current] = task
    value["positions"] = positions
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
        # Collaborators own their operations; Guided keeps them reachable by name
        # for API routes, the project helper and each other.
        self.actions = GuidedActions(self)
        self.pending_run = self.actions.pending_run
        self.submission_overlap = self.actions.submission_overlap
        self.saved_output = self.actions.saved_output
        self.preview = self.actions.preview
        self.execute = self.actions.execute
        self.verify_review = self.actions.verify_review
        self.inspection = RunInspection(self)
        self.run_view = self.inspection.run_view
        self.discard_preparation = self.inspection.discard_preparation
        self.settle_empty_estimate = self.inspection.settle_empty_estimate
        self.payload = self.inspection.payload
        self.file_preview = self.inspection.file_preview
        self.name_results = self.inspection.name_results
        self.provider_details = self.inspection.provider_details
        self.batch_cancel_preview = self.inspection.batch_cancel_preview
        self.batch_cancel = self.inspection.batch_cancel
        self.batch_collect = self.inspection.batch_collect
        self.inspect = self.inspection.inspect
        self.release = GuidedRelease(self)
        self.form = self.release.form
        self.form_value = self.release.form_value
        self.release_defaults = self.release.release_defaults
        self.release_destination = self.release.release_destination
        self.validate_release_form = self.release.validate_release_form
        self.saved_form = self.release.saved_form
        self.release_artifacts = self.release.release_artifacts
        self.release_paths = self.release.release_paths
        self.release_ready = self.release.release_ready
        self.patch_manifest = self.release.patch_manifest
        self.ace_packing = self.release.ace_packing
        self.context = GuidedContext(self)
        self.skill = self.context.skill
        self.event_text_request = self.context.event_text_request
        self.event_text_apply = self.context.event_text_apply
        self.event_text_view = self.context.event_text_view
        self.event_text_picker = self.context.event_text_picker
        self.comparisons_review = self.context.comparisons_review
        self.assistant_context = self.context.assistant_context
        self.reference_add = self.context.reference_add
        self.reference_remove = self.context.reference_remove
        self.context_status = self.context.context_status
        self.context_review = self.context.context_review
        self.speaker_findings = self.context.speaker_findings
        self.apply_speakers = self.context.apply_speakers
        self.speaker_configuration = self.context.speaker_configuration
        self.speakers = self.context.speakers

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
                "Guided translation supports RPG Maker MV/MZ and VX Ace. Use Assistant-led for other engines."
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

    def preferences(self, native):
        mode = native["mode"]
        if mode not in {"batch", "translate"}:
            # Offline launches record "estimate"; start new work in a method the
            # active connection can run, so a fresh game shows no Batch error.
            mode = (
                "batch"
                if self.settings.translation_defaults().get("batch_supported")
                else "translate"
            )
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
            except OSError, ValueError, KeyError:
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

    def resyncing(self, native):
        return any(
            job.get("project_id") == native["id"]
            and job.get("action") == "refresh_sources"
            and job.get("status") in {"ready", "running", "waiting"}
            for job in self.backend.operations.jobs.values()
        )

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
        except OSError, ValueError, KeyError:
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
            except OSError, ValueError:
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
            "step": saved_position.get("step", "setup"),
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
            "artifacts": self.release_artifacts(
                project_id, value["jobs"], native["source"]
            ),
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
            raise ValueError("Prepare the game files before saving its version.")

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

    def clean(self, project_id):
        self.translation.clean_drafts(project_id)
        self.clean_options(project_id)

    def clean_options(self, project_id):
        path = self.path(project_id, "draft")
        if path.exists() and read_json(path) is not None:
            raise ValueError("Save or discard guided options before running an action.")

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
