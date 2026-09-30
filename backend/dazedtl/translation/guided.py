"""Guided actions compose the preserved engine runner without changing tabs."""


class Guided:
    def __init__(self, backend, projects, settings):
        self.backend = backend
        self.settings = settings
        self.projects = projects
        self.confirmations = {}

    def idle(self):
        if self.backend.running():
            raise ValueError("Finish or stop the current run before starting another action.")

    def record(self, project_id):
        project = self.projects.get(project_id)
        if project["method"] != "guided" or project["engine"] != "MVMZ":
            raise ValueError("This migration currently includes the guided RPG Maker MV/MZ path.")
        if not project.get("backend_id"):
            self.idle()
            self.settings.prepare_engine()
            native = self.backend.workflows.open(project["source"])["project"]
            project["backend_id"] = native["id"]
            self.projects.save()
        return project, self.backend.workflows.projects[project["backend_id"]]

    def state(self, project_id):
        project, native = self.record(project_id)
        value = self.backend.workflows.state(native["id"])
        return {
            **value,
            "documents": self.backend.workflows.documents(native["id"]),
            "phase": project["phase"],
            "phase_files": [name for name in self.backend.phase_files(native, project["phase"]) if name in value["project"]["imported"]],
            "provider": {
                **self.settings.translation_defaults(),
                "credential_ready": self.settings.ready(),
            },
        }

    def phase_select(self, project_id, phase):
        self.idle()
        project, native = self.record(project_id)
        self.backend.phase_files(native, phase)  # Use the existing engine's phase definitions.
        project["phase"] = phase
        self.projects.save()
        return self.state(project_id)

    def preview(self, project_id, action, files=None):
        self.idle()
        _, native = self.record(project_id)
        if action == "import":
            selected = files or []
        elif action == "export_selected":
            current = self.backend.workflows.state(native["id"])
            job = current["manual_job"]
            if current["project"].get("collection_error"):
                raise ValueError(current["project"]["collection_error"])
            if not job or job["status"] != "complete" or not job["outputs"]:
                raise ValueError("Complete and review a translation before applying its files.")
            selected = sorted(job["outputs"])
        else:
            raise ValueError("That guided action has not been migrated.")
        preview = self.backend.workflows.preview(native["id"], action, {"files": selected})
        self.confirmations = {preview["token"]: project_id}
        return preview

    def execute(self, project_id, token):
        self.idle()
        if self.confirmations.pop(token, None) != project_id:
            raise ValueError("The action changed. Review a new preview.")
        return self.backend.workflows.execute(token)

    def start(self, project_id, mode):
        self.idle()
        project, native = self.record(project_id)
        if mode not in {"estimate", "translate", "batch"}:
            raise ValueError("Choose an estimate, live translation, or batch translation.")
        state = self.backend.workflows.state(native["id"])
        if state.get("draft", {}).get("documents"):
            raise ValueError("Save or discard the context drafts before translating.")
        self.settings.prepare_engine(mode=mode)
        self.backend.workflows.update(native["id"], native["revision"], {"mode": mode})
        # Workflows.phase preserves the original phase profiles, speaker and
        # glossary context, input snapshots, variable cache and result collection.
        return self.backend.workflows.phase(native["id"], project["phase"], True)

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

    def export(self, project_id):
        self.idle()
        return self.backend.manual.export(self.job(project_id)["id"])

    def documents(self, project_id):
        _, native = self.record(project_id)
        return self.backend.workflows.documents(native["id"])

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
