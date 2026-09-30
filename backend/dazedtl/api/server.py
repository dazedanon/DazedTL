"""Small line-delimited API for the clean Electron application."""

import argparse
import json
import os
import platform
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.projects.store import Projects
from dazedtl.storage import WorkspaceLock
from dazedtl.diagnostics import Diagnostics
from dazedtl.settings.store import Settings
from dazedtl.translation.guided import Guided
from dazedtl.api import views

PROTOCOL = json.loads(
    Path(__file__).with_name("protocol.json").read_text(encoding="utf-8")
)


class Application:
    def __init__(self, workspace, legacy, allow_providers):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_lock = WorkspaceLock(self.workspace)
        self.projects = Projects(self.workspace)
        self.projects.data["screen"] = "overview"
        self.backend = ExistingBackend(legacy, self.workspace / "engine", allow_providers)
        with self.backend.context():
            self.settings = Settings(self.workspace, self.backend)
        self.guided = Guided(self.backend, self.projects, self.settings)

    def state(self):
        value = self.projects.state()
        project = value["project"]
        value.update(running=self.backend.running(), provider_ready=self.settings.ready())
        if project:
            project = dict(project)
            project.update(
                available=Path(project["source"]).is_dir(),
                status="Ready for setup",
                detail="Select the game files and review its context.",
                next_label="Continue setup",
                attention=[],
            )
            if not project["available"]:
                project.update(
                    status="Game folder unavailable",
                    detail="Reconnect the drive or open the game in its new location.",
                    next_label="Open another game",
                )
            elif project.get("backend_id"):
                native = self.backend.workflows.state(project["backend_id"])
                job = native["manual_job"]
                latest = native["jobs"][0] if native["jobs"] else None
                if native["project"].get("imported"):
                    project.update(
                        status="Ready to translate", detail="Your selected files and game context are ready.", next_label="Continue translation"
                    )
                if native["project"].get("collection_error"):
                    project["attention"].append(native["project"]["collection_error"])
                if latest and latest["status"] == "running":
                    project.update(status="Preparing files", detail=latest["label"], next_label="View progress")
                elif job:
                    if job["status"] == "waiting":
                        project.update(status="Approval needed", detail="Review the pending request to continue.", next_label="Review request")
                    elif job["status"] == "running":
                        project.update(
                            status="Batch awaiting results" if job["mode"] == "batch" and job["phase"].startswith("poll") else "Translation running",
                            detail="",
                            next_label="View progress",
                        )
                    elif job["status"] == "complete":
                        project.update(
                            status="Estimate ready" if job["mode"] == "estimate" else "Translation ready", detail="", next_label="Review results"
                        )
                    else:
                        project.update(status="Run needs attention", detail="", next_label="Review run")
                        project["attention"].append(job["message"])
                elif latest and latest["status"] in {"failed", "interrupted"}:
                    project.update(status="Preparation needs attention", next_label="Review progress")
                    project["attention"].append(latest["message"])
            value["project"] = project
        return value

    def snapshot(self):
        state = self.state()
        project = state['project']
        current = None
        if state['screen'] == 'guided' and project and project['available']:
            current = views.guided(self.guided.state(project['id']), project['id'])
        return {'application': views.application(state), 'guided': current}

    def open_project(self, source, method="guided"):
        self.guided.idle()
        detected = self.backend.describe(source)
        if method != "guided" or detected["engine"] != "MVMZ":
            raise ValueError(
                "This first migration includes Guided Workflow for RPG Maker MV/MZ. Continue using the current app for the other workflows."
            )
        self.settings.prepare_engine()
        native = self.backend.workflows.open(detected["source"])["project"]
        project = self.projects.open(detected, method)
        project["backend_id"] = native["id"]
        self.projects.save()
        return self.state()

    def select_project(self, project_id):
        self.guided.idle()
        self.projects.select(project_id)
        return self.state()

    def navigate(self, screen):
        self.projects.navigate(screen)
        return self.state()

    def settings_get(self):
        return self.settings.describe()

    def settings_save(self, revision, connection_id, values, engines):
        self.guided.idle()
        return self.settings.save(revision, connection_id, values, engines)

    def settings_draft(self, revision, connection_id, values, engines):
        return self.settings.draft(revision, connection_id, values, engines)

    def settings_revert(self, revision, connection_id):
        return self.settings.revert(revision, connection_id)

    def connection_save(self, **params):
        self.guided.idle()
        return self.settings.save_connection(**params)

    def connection_select(self, revision, connection_id):
        self.guided.idle()
        return self.settings.select(revision, connection_id)

    def connection_check(self, revision, connection_id):
        self.guided.idle()
        return self.settings.check_connection(revision, connection_id)


def serve(args, diagnostics):
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    app = Application(args.workspace, args.legacy_root, not args.offline)
    diagnostics.workspace_ready(app.projects.data["version"])
    methods = {
        "workspace_snapshot": (app.snapshot, lambda value, _params: value),
        **{
            name: (getattr(app, name), lambda value, _params: views.application(value))
            for name in ("open_project", "select_project", "navigate")
        },
        **{
            name: (getattr(app, name), lambda value, _params: views.settings(value))
            for name in (
                "settings_get",
                "settings_save",
                "settings_revert",
                "connection_save",
                "connection_select",
                "connection_check",
            )
        },
        "settings_draft": (app.settings_draft, lambda value, _params: value),
        "guided_phase_select": (
            app.guided.phase_select,
            lambda value, params: views.guided(value, params["project_id"]),
        ),
        "guided_preview": (
            app.guided.preview,
            lambda value, _params: views.preview(value),
        ),
        **{
            "guided_" + name: (
                getattr(app.guided, name),
                lambda value, _params: views.job(value),
            )
            for name in ("execute", "start", "answer", "stop", "resume")
        },
        "guided_export": (app.guided.export, lambda value, _params: value),
        "guided_draft": (app.guided.draft, lambda value, _params: value),
        "guided_save_document": (
            app.guided.save_document,
            lambda value, _params: views.documents(value),
        ),
    }
    if set(methods) != set(PROTOCOL["methods"]):
        raise RuntimeError("The application API does not match its protocol manifest.")
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    request = {}
                    raise ValueError("Application requests must be objects.")
                if request.get("version") != PROTOCOL["version"]:
                    response = {
                        "id": request.get("id"),
                        "version": PROTOCOL["version"],
                        "error": {
                            "code": "protocol",
                            "message": "The application and backend versions do not match. Restart after updating.",
                        },
                    }
                    print(json.dumps(response), flush=True)
                    continue
                method = methods.get(request.get("method"))
                if not method:
                    raise ValueError("Unknown application operation.")
                params = request.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError("Application parameters must be an object.")
                handler, present = method
                if request.get("method") == "connection_check":
                    result = present(handler(**params), params)
                else:
                    with app.backend.context():
                        result = present(handler(**params), params)
                response = {
                    "id": request.get("id"),
                    "version": PROTOCOL["version"],
                    "result": result,
                }
            except Exception as exc:
                name = request.get("method")
                operation = (
                    name if isinstance(name, str) and name in methods else "native"
                )
                diagnostics.failure(exc, operation, request.get("id"))
                response = {
                    "id": request.get("id"),
                    "version": PROTOCOL["version"],
                    "error": views.error(exc),
                }
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        try:
            app.backend.close()
        finally:
            app.workspace_lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--diagnostics-directory", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    diagnostics = Diagnostics(
        args.diagnostics_directory or args.workspace / "diagnostics",
        root,
        args.legacy_root.resolve(),
    )
    try:
        diagnostics.started()
        if platform.python_version() != (root / ".python-version").read_text().strip():
            print("DAZEDTL_ERROR runtime_version", file=sys.stderr, flush=True)
            return 1
        serve(args, diagnostics)
        return 0
    except Exception as exc:
        diagnostics.failure(exc)
        code = getattr(exc, "code", "internal")
        if code not in {
            "workspace_newer",
            "workspace_locked",
            "workspace_invalid",
            "workspace_upgrade",
            "workspace_backup",
        }:
            code = "internal"
        print("DAZEDTL_ERROR " + code, file=sys.stderr, flush=True)
        return 1
    finally:
        diagnostics.close()


if __name__ == "__main__":
    sys.exit(main())
