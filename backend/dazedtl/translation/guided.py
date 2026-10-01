"""User-driven RPG Maker workflow over preserved engines and shared project services."""

from copy import deepcopy
from pathlib import Path
import uuid

from dazedtl.storage import write_json
from .files import read_json, project_path, evidence, verify_evidence
from .operations import lifecycle, require_source_backup, verify_guided_review
from .guided_inputs import GuidedInputs
from .files import digest
from . import backups

STEPS = {"prepare", "context", "translate", "apply", "layout", "review"}
PHASES = {"database", "dialogue", "variables", "advanced", "speakers"}
NATIVE_ACTIONS = {
    "import", "format_data", "format_plugins", "gameupdate", "export_selected",
    "ace_decrypt", "ace_extract", "ace_pack", "rewrap_preview", "rewrap_apply",
    "qa_prepare", "qa_status", "playtest_install", "playtest_status",
}
SHARED_ACTIONS = {
    "backup_source": "Preserve original game", "git_setup": "Set up Git versioning",
    "checkpoint": "Save reviewed patch in Git", "guided_review": "Record playtest review",
    "guided_package": "Build local patch ZIP",
    "refresh_sources": "Review source refresh",
}
MANIFEST = ".dazedtl/guided/runtime-manifest.json"


class Guided:
    def __init__(self, backend, projects, settings, translation):
        self.backend, self.projects, self.settings = backend, projects, settings
        self.translation = translation
        self.confirmations = {}
        self.observed_files = {}

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

    def idle(self):
        if self.backend.running() or self.translation.jobs.running():
            raise ValueError("Finish or stop the current run before starting another action.")

    def record(self, project_id):
        project = self.projects.get(project_id)
        native = self.backend.workflows.projects.get(project.get("backend_id"))
        if not native or native["source"] != project["source"]:
            raise ValueError("Open Translation to initialize this game's workspace.")
        if native["engine"] not in {"MVMZ", "ACE"}:
            raise ValueError("Guided translation supports RPG Maker MV/MZ and VX Ace. WOLF support comes later.")
        return project, native

    def open(self, project_id):
        project = self.projects.get(project_id)
        if project.get("backend_id"):
            _, native = self.record(project_id)
            current = self.backend.describe(project["source"])
            if current["source"] != project["source"] or current["engine"] != native["engine"]:
                raise ValueError("The game location or engine changed. Open the correct game folder before continuing.")
            if any(native.get(key) != value for key, value in current.items()):
                updated = {**native, **current}
                self.backend.workflows.save(updated)
                self.backend.workflows.projects[native["id"]] = updated
            return
        self.idle()
        layout = self.backend.describe(project["source"])
        if layout["engine"] not in {"MVMZ", "ACE"}:
            raise ValueError("Guided translation supports RPG Maker MV/MZ and VX Ace. Use Len's method for other engines.")
        self.settings.prepare_engine()
        pending = self.translation.drafts(project_id)["documents"]
        native = self.backend.workflows.open(project["source"])["project"]
        if pending:
            self.backend.workflows.draft(native["id"], {"documents": pending})
        # Persist registry ownership before publishing it in memory.
        data = deepcopy(self.projects.data)
        self.projects._get(data, project_id)["backend_id"] = native["id"]
        self.projects._commit(data)

    def path(self, project_id, name):
        self.projects.get(project_id)
        return self.translation.workspace / "translation/projects" / project_id / ("guided-" + name + ".json")

    def position(self, project_id, step):
        self.record(project_id)
        if step not in STEPS:
            raise ValueError("Choose a guided step.")
        write_json(self.path(project_id, "position"), {"step": step})
        return {"saved": True}

    def form(self, project_id, value):
        self.record(project_id)
        if (not isinstance(value, dict) or set(value) != {"version", "original", "untranslated", "only_overflow"}
                or any(not isinstance(value[key], str) or len(value[key]) > 10000 or "\0" in value[key] for key in ("version", "original"))
                or any(type(value[key]) is not bool for key in ("untranslated", "only_overflow"))):
            raise ValueError("Invalid guided form values.")
        write_json(self.path(project_id, "form"), value)
        return {"saved": True}

    def preferences(self, native):
        mode = native["mode"] if native["mode"] in {"batch", "translate"} else "batch"
        return {"revision": native["revision"], "values": {
            "selected": [name for name in native["selected"] if name in self.supported_files(native)],
            "mode": mode, "engine_options": native["engine_options"],
            "widths": native["widths"], "phase1_comments": native["phase1_comments"],
        }}

    def supported_files(self, native):
        return set(self.backend.phase_files(native, "database")) | set(self.backend.phase_files(native, "dialogue"))

    def inputs(self, native):
        return GuidedInputs(self.backend.workflows.folder(native["id"]), native["source"], native["data"],
                            self.translation.engine.source_bindings, self.translation.engine.original_bytes,
                            native_exports=native["engine"] == "ACE")

    def owned_runs(self, native):
        return list(dict.fromkeys([native.get("manual_job"), *reversed(native.get("collected", [])),
                                   *self.inputs(native).record().get("retired_runs", [])]))

    def run_view(self, identity, *, compact=False):
        job = dict(self.backend.manual.jobs[identity])
        try:
            folder = self.backend.manual.folder(identity) / "translated"
            job["outputsAvailable"] = bool(job.get("outputs")) and all(project_path(folder, name).is_file() for name in job["outputs"])
        except (OSError, ValueError):
            job["outputsAvailable"] = False
        if compact:
            job["log"] = []
        return job

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
        outputs = [row["name"] for row in native["files"] if self.inputs(native).path("translated", row["name"]).is_file()]
        applied = []
        edited = []
        receipt = folder / "applied-outputs.json"
        applied_outputs = read_json(receipt).get("files", {}) if receipt.exists() else {}
        for name in outputs:
            source = project_path(native["source"], (Path(native["data"]) / name).relative_to(native["source"]).as_posix())
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
            source_status = source_status or self.inputs(native).status([row["name"] for row in native["files"]], self.observed_digest)
            scope_matches = (review.get("source_inputs_sha256") == digest(sources) if review and review.get("source_inputs_sha256") else not sources.get("last_refresh"))
            current = bool(review and scope_matches and not source_status["changed"] and review["evidence"] and all(self.observed_digest(project_path(native["source"], name)) == sha for name, sha in review["evidence"].items()))
        except (OSError, ValueError, KeyError):
            pass
        scan = next((job for job in value["jobs"] if job["action"] == "rewrap_preview" and job["status"] == "complete"), None)
        if scan:
            try:
                plan = read_json(self.backend.operations.root / scan["id"] / "plan.json")
            except (OSError, ValueError):
                plan = {}
            configured = plan.get("options", {})
            form_path = self.path(project_id, "form")
            only_overflow = read_json(form_path).get("only_overflow", True) if form_path.exists() else True
            selected_layout = [row["name"] for row in native["files"] if row["name"] in native["selected"]]
            if (configured.get("files") != selected_layout or configured.get("widths") != native["widths"]
                    or configured.get("over_limit") != only_overflow
                    or any(self.observed_digest(Path(native["data"]) / name) != plan.get("guard", {}).get("data", {}).get(name) for name in selected_layout)):
                scan = None
        return {"outputs": outputs, "applied": applied, "runtime_edited": edited, "review_current": current,
                "layout_scan": scan["id"] if scan else None,
                "delivery_available": bool(state.get("delivery") and Path(state["delivery"]["path"]).is_file())}

    def patch_manifest(self, project_id, paths, action):
        project, native = self.record(project_id)
        entries = {name: {} for name in paths}
        if action != "git_setup":
            originals = self.translation.engine.source_bindings(project["source"], paths)
            state = lifecycle(self.translation.workspace, project_id)
            saved = state.get("prepared_source") or state.get("source_backup")
            source_files = {}
            if saved:
                location = backups.lookup(project["source"], Path(saved["path"]).parent, saved["id"])
                source_files = backups.manifest(location, source=project["source"])["files"]
            for name in paths:
                if name not in originals and name not in source_files:
                    entries[name] = {"original_sha256": None}
        inputs = []
        if native["engine"] == "ACE":
            inputs = [path.relative_to(Path(project["source"])).as_posix() for path in Path(native["data"]).glob("*.json")]
        return {"files": entries, "inputs": sorted(inputs)}

    def options_draft(self, project_id, value):
        self.record(project_id)
        if value is not None and (not isinstance(value, dict) or set(value) != {"revision", "values"}
                                 or type(value["revision"]) is not int):
            raise ValueError("Invalid guided options draft.")
        if value is not None:
            self.validate_options(value["values"])
        write_json(self.path(project_id, "draft"), value)
        return {"saved": True}

    @staticmethod
    def validate_options(values):
        import json
        if not isinstance(values, dict) or set(values) != {"selected", "mode", "engine_options", "widths", "phase1_comments"}:
            raise ValueError("Unknown guided setting.")
        if values["mode"] not in {"batch", "translate"}:
            raise ValueError("Guided translation supports Batch or Live API only.")
        if not isinstance(values["selected"], list) or any(not isinstance(name, str) for name in values["selected"]):
            raise ValueError("Choose supported game files.")
        if len(set(values["selected"])) != len(values["selected"]):
            raise ValueError("Choose each game file once.")
        if (not isinstance(values["engine_options"], dict) or not isinstance(values["widths"], dict)
                or type(values["phase1_comments"]) is not bool or len(json.dumps(values)) > 200_000):
            raise ValueError("Invalid guided options.")

    def save_options(self, project_id, revision, values):
        self.idle()
        _, native = self.record(project_id)
        self.validate_options(values)
        if set(values["selected"]) - self.supported_files(native):
            raise ValueError("Select files supported by this game's translation phases.")
        result = self.backend.workflows.update(native["id"], revision, values)
        self.options_draft(project_id, None)
        return self.preferences(result["project"])

    def state(self, project_id):
        project, native = self.record(project_id)
        value = self.backend.workflows.state(native["id"])
        native = value["project"]
        supported = self.supported_files(native)
        native["files"] = [row for row in native["files"] if row["name"] in supported]
        native["selected"] = [name for name in native["selected"] if name in supported]
        database = set(self.backend.phase_files(native, "database"))
        for row in native["files"]:
            row["group"] = "database" if row["name"] in database else "dialogue"
        inputs = self.inputs(native)
        source_status = inputs.status([row["name"] for row in native["files"]], self.observed_digest)
        source_status["retired"] = inputs.record().get("retired_runs", [])
        prepared = list(dict.fromkeys([*native["imported"], *source_status["ready"]]))
        if prepared != native["imported"]:
            native["imported"] = prepared
            self.backend.workflows.projects[native["id"]].update(imported=prepared)
            self.backend.workflows.save(self.backend.workflows.projects[native["id"]])
        position = self.path(project_id, "position")
        draft = self.path(project_id, "draft")
        form = self.path(project_id, "form")
        return {
            **value, "step": read_json(position)["step"] if position.exists() else "prepare",
            "preferences": self.preferences(native), "options_draft": read_json(draft) if draft.exists() else None,
            "form": read_json(form) if form.exists() else {"version": "", "original": "", "untranslated": False, "only_overflow": True},
            "ace_available": self.backend.ace_available(),
            "documents": self.backend.workflows.documents(native["id"]), "phase": project["phase"],
            "phase_files": [name for name in self.backend.phase_files(native, project["phase"]) if name in native["selected"]],
            "source_status": source_status, "readiness": self.readiness(project_id, native, value, source_status),
            "runs": [self.run_view(identity, compact=True) for identity in self.owned_runs(native)[:30]
                     if identity in self.backend.manual.jobs],
            "provider": {**self.settings.translation_defaults(), "credential_ready": self.settings.ready()},
        }

    def phase_select(self, project_id, phase):
        self.idle()
        project, native = self.record(project_id)
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
        path = self.path(project_id, "draft")
        if path.exists() and read_json(path) is not None:
            raise ValueError("Save or discard guided options before running an action.")

    @staticmethod
    def pending_run(value):
        job = value.get("manual_job")
        if job and job.get("mode") in {"batch", "translate", "speakers"} and job["status"] not in {"complete", "canceled"}:
            raise ValueError("Resume the unfinished API run before starting another phase or estimate. Its saved provider work must stay attached to this project.")

    def preview(self, project_id, action, files=None, options=None):
        self.idle()
        project, native = self.record(project_id)
        self.clean(project_id)
        options = {} if options is None else deepcopy(options)
        if not isinstance(options, dict):
            raise ValueError("Action options must be an object.")
        if action not in NATIVE_ACTIONS | SHARED_ACTIONS.keys() | {"start"}:
            raise ValueError("Choose a supported guided action.")
        self.settings.prepare_engine()
        value = self.backend.workflows.state(native["id"])
        if action != "backup_source":
            self.source_preserved(project_id)
        if action in {"start", "export_selected", "rewrap_apply", "ace_pack", "qa_prepare", "playtest_install", "checkpoint", "guided_review", "guided_package"}:
            self.translation.ready(project_id)
        if action.startswith("ace_") and (native["engine"] != "ACE" or not self.backend.ace_available()):
            raise ValueError("Ace preparation requires Windows or Wine and the bundled Ace tools.")
        if action == "format_plugins" and native["engine"] == "ACE":
            raise ValueError("Ace does not use plugins.js.")
        paths = []
        expected = None
        manifest = None
        if action == "start":
            self.pending_run(value)
            if set(options) != {"mode"} or options["mode"] not in {"batch", "translate", "estimate", "speakers"}:
                raise ValueError("Choose Batch, Live API, a cost estimate, or speaker collection.")
            mode = options["mode"]
            phase = "speakers" if mode == "speakers" else project["phase"]
            if phase == "speakers" and mode != "speakers":
                raise ValueError("Choose a translation phase first.")
            paths = [name for name in self.backend.phase_files(native, phase) if name in native["selected"]]
            if not paths:
                raise ValueError("Select game files belonging to this phase first.")
            if self.inputs(native).status(sorted(self.supported_files(native)))["changed"]:
                raise ValueError("The original source changed. Review source changes and refresh the working copies before preparing a new run.")
            if value["project"].get("collection_error"):
                raise ValueError(value["project"]["collection_error"])
            options["phase"] = phase
            label = {"batch": "Prepare Batch translation", "translate": "Start Live API translation", "estimate": "Estimate selected phase", "speakers": "Collect speaker names"}[mode]
        elif action in SHARED_ACTIONS:
            label = SHARED_ACTIONS[action]
            allowed = {"version", "original", "untranslated"} if action == "git_setup" else {"reviewed", "playtested"} if action == "guided_review" else set()
            if set(options) - allowed:
                raise ValueError("Unknown guided action option.")
            if action == "backup_source":
                saved = lifecycle(self.translation.workspace, project_id).get("source_backup")
                if saved and backups.record_status(project["source"], saved, kind="source")["available"]:
                    raise ValueError("The original is already preserved. Use workspace backups for later milestones.")
            if action == "refresh_sources":
                self.pending_run(value)
                if (not isinstance(files, list) or not files or any(not isinstance(name, str) for name in files)
                        or len(set(files)) != len(files) or set(files) - self.supported_files(native)):
                    raise ValueError("Select supported files to refresh.")
                paths = files
                options = {"sources": self.inputs(native).sources(paths, self.inputs(native).record()["inputs"])}
            if action in {"git_setup", "checkpoint", "guided_review"}:
                paths = self.backend.guided_runtime_files(project["source"])
                expected = evidence(project["source"], paths)
                manifest = self.patch_manifest(project_id, paths, action)
            if action == "guided_review" and (options.get("reviewed") is not True or options.get("playtested") is not True):
                raise ValueError("Review the translated scope and playtest it before recording release readiness.")
            if action == "guided_review":
                options["source_inputs_sha256"] = digest(self.inputs(native).record())
            if action == "guided_package":
                self.verify_review(project_id, native)
        else:
            if action == "import":
                if not isinstance(files, list) or any(not isinstance(name, str) or name not in self.supported_files(native) for name in files):
                    raise ValueError("Select supported RPG Maker files from this project's list.")
                options = {"files": files or []}
            elif action == "export_selected":
                if value["project"].get("collection_error"):
                    raise ValueError(value["project"]["collection_error"])
                folder = self.backend.workflows.folder(native["id"])
                paths = [name for name in native["selected"] if (folder / "translated" / name).is_file()]
                if not paths:
                    raise ValueError("Complete and review a translation before applying its files.")
                if self.inputs(native).status(paths)["changed"]:
                    raise ValueError("Review changed sources and refresh their working copies before applying older outputs.")
                self.inputs(native).prepare(paths)
                options = {"files": paths}
            result = (self.backend.guided_export_preview(native["id"], paths) if action == "export_selected"
                      else self.backend.workflows.preview(native["id"], action, options))
            token = result["token"]
            if action == "rewrap_apply":
                result["rewrap"] = self.backend.guided_rewrap_review(native["id"], token)
            self.confirmations = {token: {"project_id": project_id, "action": action, "native": True,
                "revision": native["revision"], "phase": project["phase"], "settings_revision": self.settings.describe()["revision"]}}
            # Routine preparation uses the same one-use plan and execution checks,
            # without asking the user to confirm the button they just clicked.
            return {**result, "action": action, "paths": paths or result["options"].get("files", []),
                    "confirmation": result["confirmation"] and action not in {"format_data", "format_plugins", "gameupdate"}}
        token = uuid.uuid4().hex
        self.confirmations = {token: {"project_id": project_id, "action": action, "options": options,
            "paths": paths, "evidence": expected, "manifest": manifest,
            "guard": self.backend.guided_guard(native, self.backend.workflows.folder(native["id"])),
            "revision": native["revision"], "phase": project["phase"], "settings_revision": self.settings.describe()["revision"]}}
        destination = str(backups.store_path(project["source"])) if action == "backup_source" else project["source"]
        return {"token": token, "action": action, "label": label, "destination": destination,
                "files": len(paths), "paths": paths, "options": options,
                "confirmation": (bool(lifecycle(self.translation.workspace, project_id).get("source_backup")) if action == "backup_source"
                                 else not (action == "start" and options["mode"] == "estimate")),
                "additions": [name for name, row in manifest["files"].items() if row.get("original_sha256", "") is None] if manifest else []}

    def execute(self, project_id, token):
        self.idle()
        confirmed = self.confirmations.get(token)
        if not confirmed or confirmed["project_id"] != project_id:
            raise ValueError("The action changed. Review a new preview.")
        self.clean(project_id)
        project, native = self.record(project_id)
        self.confirmations.pop(token)
        action = confirmed["action"]
        if action != "backup_source":
            self.source_preserved(project_id)
        if action in {"start", "export_selected", "rewrap_apply", "ace_pack", "qa_prepare", "playtest_install", "checkpoint", "guided_review", "guided_package"}:
            self.translation.ready(project_id)
        if confirmed.get("native"):
            if (confirmed["revision"] != native["revision"] or confirmed["phase"] != project["phase"]
                    or confirmed["settings_revision"] != self.settings.describe()["revision"]):
                raise ValueError("The selection or settings changed. Review the action again.")
            return self.backend.workflows.execute(token)
        if (confirmed["guard"] != self.backend.guided_guard(native, self.backend.workflows.folder(native["id"]))
                or confirmed["revision"] != native["revision"] or confirmed["phase"] != project["phase"]
                or confirmed["settings_revision"] != self.settings.describe()["revision"]):
            raise ValueError("The game, selection, or settings changed. Review the action again.")
        if confirmed["evidence"]:
            verify_evidence(project["source"], confirmed["evidence"])
            if self.backend.guided_runtime_files(project["source"]) != confirmed["paths"]:
                raise ValueError("The runtime file list changed. Review the complete patch again.")
        options = confirmed["options"]
        if action == "start":
            return self._start(project_id, options["mode"], options["phase"], confirmed["paths"])
        if action == "refresh_sources":
            self.pending_run(self.backend.workflows.state(native["id"]))
            return self.backend.guided_refresh(native, confirmed["paths"], options["sources"])
        if action in {"git_setup", "checkpoint", "guided_review"}:
            if confirmed["manifest"] != self.patch_manifest(project_id, confirmed["paths"], action):
                raise ValueError("The original or runtime scope changed. Review the patch again.")
            write_json(project_path(project["source"], MANIFEST, exists=False), confirmed["manifest"])
            options = {**options, "manifest": MANIFEST}
        if action == "guided_review":
            inputs = self.inputs(native)
            current = inputs.record()
            if digest(current) != options["source_inputs_sha256"]:
                raise ValueError("Working sources changed. Review this pass again.")
            if not inputs.index.exists():
                write_json(inputs.index, current)
            options = {"manifest": MANIFEST, "source_inputs": inputs.index.relative_to(self.translation.workspace).as_posix(), "source_inputs_sha256": digest(current)}
        if action == "guided_package":
            self.verify_review(project_id, native)
        operation = self.translation.guided_operation if action in {"guided_review", "guided_package"} else self.translation.operation
        return operation(project_id, action, options)

    def verify_review(self, project_id, native):
        state = lifecycle(self.translation.workspace, project_id)
        review = verify_guided_review(native["source"], state, self.translation.workspace, self.translation.engine)
        inputs = self.inputs(native)
        if (not review.get("source_inputs_sha256") and inputs.record().get("last_refresh")
                or inputs.status(sorted(self.supported_files(native)))["changed"]):
            raise ValueError("Source work changed after review. Playtest and record the current pass again.")

    def _start(self, project_id, mode, phase, files):
        _, native = self.record(project_id)
        self.pending_run(self.backend.workflows.state(native["id"]))
        self.inputs(native).prepare(files)
        native["imported"] = list(dict.fromkeys([*native["imported"], *files]))
        self.backend.workflows.save(native)
        self.settings.prepare_engine(mode=mode)
        previous_mode = self.preferences(native)["values"]["mode"]
        if mode != "speakers":
            self.backend.workflows.update(native["id"], native["revision"], {"mode": mode})
        try:
            return self.backend.guided_phase(native["id"], phase, files)
        finally:
            if mode == "estimate":
                current = self.backend.workflows.projects[native["id"]]
                self.backend.workflows.update(native["id"], current["revision"], {"mode": previous_mode})

    def skill(self, project_id, name):
        self.clean(project_id)
        project, native = self.record(project_id)
        if name not in {"setup", "advanced", "wrap", "plugins", "walkthrough"}:
            raise ValueError("Choose a task-specific helper.")
        text = self.backend.workflows.skill(native["id"], name)
        return {"text": f"Selected game: {project['source']}\n\nThis is one user-requested Guided Workflow task: {name}. Complete only this task, report what changed and what needs review, then stop. The user controls translation submission, export, versioning and packaging in DazedTL.\n\n" + text}

    def job(self, project_id):
        _, native = self.record(project_id)
        identity = native.get("manual_job")
        if not identity or identity not in self.backend.manual.jobs:
            raise ValueError("There is no translation run for this project.")
        return self.backend.manual.jobs[identity]

    def answer(self, project_id, token, approved):
        return self.backend.manual.answer(self.job(project_id)["id"], token, approved)

    def stop(self, project_id):
        _, native = self.record(project_id)
        operation = self.backend.operations.jobs.get(self.backend.operations.active)
        if operation and operation["project_id"] == native["id"]:
            return self.backend.operations.stop(operation["id"])
        return self.backend.manual.stop(self.job(project_id)["id"])

    def resume(self, project_id):
        self.idle()
        identity = self.job(project_id)["id"]
        self.settings.prepare_engine(resume=self.backend.saved_run_configuration(identity))
        return self.backend.manual.resume(identity)

    def export(self, project_id, run_id=None):
        self.idle()
        _, native = self.record(project_id)
        identity = run_id if run_id is not None else self.job(project_id)["id"]
        if not isinstance(identity, str) or identity not in self.owned_runs(native):
            raise ValueError("Choose a saved run belonging to this project.")
        if (self.backend.saved_run_configuration(identity).get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved output belongs to another project.")
        return self.backend.manual.export(identity)

    def draft(self, project_id, documents):
        _, native = self.record(project_id)
        current = self.backend.workflows.state(native["id"]).get("draft", {})
        return self.backend.workflows.draft(native["id"], {**current, "documents": documents})

    def save_document(self, project_id, name, revision, text):
        self.idle()
        _, native = self.record(project_id)
        result = self.backend.workflows.document_save(native["id"], name, revision, text)
        draft = self.backend.workflows.state(native["id"]).get("draft", {})
        draft.get("documents", {}).pop(name, None)
        self.backend.workflows.draft(native["id"], draft)
        return result
