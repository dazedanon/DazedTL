"""Small line-delimited API for the clean Electron application."""

import argparse
import json
import os
import platform
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.runtime import ENGINE_ROOT
from dazedtl.projects.store import Projects
from dazedtl.storage import WorkspaceLock
from dazedtl.diagnostics import Diagnostics
from dazedtl.settings.store import Settings
from dazedtl.translation.guided import Guided
from dazedtl.translation.service import Translation
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.api.local import LocalAPI
from dazedtl.images import ImageService
from dazedtl.images.editor import ImageEditor
from dazedtl.images.native_translation import ImageNativeTranslation
from dazedtl.plugins import PluginService

RPC_OUTPUT = sys.stdout
from dazedtl.api import views

PROTOCOL = json.loads(
    Path(__file__).with_name("protocol.json").read_text(encoding="utf-8")
)


class Application:
    def __init__(self, workspace, allow_providers):
        self.closing = False
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_lock = WorkspaceLock(self.workspace)
        self.projects = Projects(self.workspace)
        self.projects.data["screen"] = "overview"
        self.backend = ExistingBackend(self.workspace / "engine", allow_providers)
        with self.backend.context():
            self.settings = Settings(self.workspace, self.backend)
        self.translation = Translation(self.workspace, self.projects, self.settings,
                                       TranslationEngine(self.workspace / "engine"))
        self.guided = Guided(self.backend, self.projects, self.settings, self.translation)
        self.images = ImageService(self.projects, self.translation, self.settings, self.backend)
        self.plugins = PluginService(self.projects, self.translation, self.backend)
        self.image_editor = ImageEditor(self.images)
        self.image_native = ImageNativeTranslation(self.images, self.image_editor)
        self.translation.legacy_actions = {
            "resume": lambda identity: views.job(self.guided.resume(identity)),
            "stop": lambda identity: views.job(self.guided.stop(identity)),
            "answer": lambda identity, token, approved: views.job(self.guided.answer(identity, token, approved)),
            "export": self.guided.export,
        }
        self.guided.batch_monitor.start()

    def state(self):
        value = self.projects.state()
        project = value["project"]
        value.update(running=self.backend.running() or self.translation.jobs.running(), provider_ready=self.settings.ready(),
                     observing=bool(project))
        if project:
            project = dict(project)
            project.update(
                available=Path(project["source"]).is_dir(),
                status="Project open",
                detail="Choose the next task for this project.",
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
                try:
                    native = self.backend.workflows.state(project["backend_id"])
                except (ValueError, OSError, KeyError):
                    project.update(status="Saved phased work unavailable", detail="The saved job reference was retained for recovery.")
                    value["project"] = project
                    return value
                job = native["manual_job"]
                latest = native["jobs"][0] if native["jobs"] else None
                if native["project"].get("imported"):
                    project.update(
                        status="Translation workspace ready", detail="Review the selected scope and saved guidance before starting a run.", next_label="Continue translation"
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
                    elif job["status"] == "canceled":
                        project.update(status="Translation workspace ready", detail="Review scope and guidance before starting a run.", next_label="Continue translation")
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
        project = state["project"]
        current = legacy = None
        error = ""
        if project and project["available"]:
            try:
                current = self.translation.state(project["id"])
                project["next_label"] = "Open translation"
                project["engine_label"] = current["engine"]
                project["engine"] = self.translation.engine.detect(project["source"])
                if current["jobs"]:
                    job = current["jobs"][0]
                    project.update(status=job["label"] + " · " + job["status"].replace("_", " "), detail=job["message"],
                                   operation=views.pick(job, ("label", "status", "message")))
                elif current["progress"] and current["progress"].get("phase"):
                    project.update(status="Last reported: " + current["progress"]["phase"], detail=current["progress"].get("next_action", ""))
                else:
                    project.update(status="Ready for project setup", detail="Choose a translation mode and prepare the starting prompt.")
                project["attention"].extend(current["warnings"])
                if project.get("backend_id"):
                    legacy = views.guided(self.guided.state(project["id"]), project["id"])
                    run = legacy["run"]
                    active_tool = next((job for job in legacy["operations"] if job["status"] == "running"), None)
                    if active_tool:
                        project.update(status=active_tool["label"], detail=active_tool["message"],
                                       operation=views.pick(active_tool, ("label", "status", "message")))
                    elif run and run["status"] in {"running", "waiting"}:
                        project.update(status="Guided run · " + run["status"], detail=run["message"],
                                       operation={"label": "Guided run", **views.pick(run, ("status", "message"))})
                    elif not current["jobs"] and not current["progress"]:
                        project.update(status="Guided workflow ready", detail="Continue from " + legacy["step"] + ".")
                elif project["engine"] in {"MVMZ", "ACE"} and not current["jobs"] and not current["progress"]:
                    project.update(status="Ready for guided setup", detail="Preserve the original, prepare game files, and choose a translation scope.")
            except (ValueError, OSError) as exc:
                error = str(exc)
                project.pop("operation", None)
                project.update(status="Project needs attention", detail=error, next_label="Open translation")
        images, image_error = None, ""
        if project and project["available"]:
            try:
                images = self.images.state(project["id"])
            except (ValueError, OSError) as exc:
                image_error = str(exc)
        plugins, plugin_error = None, ""
        if project and project["available"]:
            try:
                plugins = self.plugins.state(project["id"])
            except (ValueError, OSError) as exc:
                plugin_error = str(exc)
        return {"application": views.application(state), "translation": current, "translationError": error, "guided": legacy,
                "images": images, "imagesError": image_error, "plugins": plugins, "pluginsError": plugin_error}

    def open_project(self, source):
        root = Path(source).expanduser().resolve(strict=True)
        if not root.is_dir() or root == root.parent:
            raise ValueError("Choose a game folder.")
        for protected in (self.backend.source, self.workspace, Path(__file__).resolve().parents[3]):
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise ValueError("Choose a game folder separate from application and workspace storage.")
        detected = {"source": str(root), "engine": self.translation.engine.detect(root)}
        self.projects.open(detected)
        return self.state()

    def select_project(self, project_id):
        self.projects.select(project_id)
        return self.state()

    def navigate(self, screen):
        if screen in {"guided", "manual"}:
            if not self.projects.current:
                raise ValueError("Open a game project first.")
            self.guided.open(self.projects.current["id"])
            if screen == "manual":
                self.guided.position(self.projects.current["id"], "translate")
        self.projects.navigate(screen)
        return self.state()

    def settings_get(self):
        return self.settings.describe()

    def settings_save(self, revision, connection_id, values, model_options):
        self.guided.idle()
        return self.settings.save(revision, connection_id, values, model_options)

    def settings_draft(self, revision, connection_id, values, model_options):
        return self.settings.draft(revision, connection_id, values, model_options)

    def settings_model_defaults(self, connection_id, model):
        return self.settings.model_defaults(connection_id, model)

    def prepare_model_pricing(self, name, params):
        """Only explicit price/estimate actions may perform public price reads."""
        explicit = name == 'settings_model_defaults'
        prepares = (name == 'guided_preview' and params.get('action') == 'start'
                    or name == 'translation_compile' or name == 'images_editor_translation_preview')
        if not explicit and not prepares:
            return
        with self.backend.lock:
            if self.closing:
                raise ValueError('The app is closing. Reopen it before preparing requests.')
            if name == 'translation_compile':
                _record, project = self.translation.project(params.get('project_id'))
                if project.read()['options']['mode'] == 'agent':
                    return
            lookup = self.settings.pricing_lookup(connection_id=params.get('connection_id') if explicit else None,
                                                  model=params.get('model') if explicit else None, explicit=explicit)
        if lookup is None:
            return
        from dazedtl.settings.openrouter import live_prices
        try:
            prices = live_prices(lookup['model'], lookup['host'])
        except ValueError:
            with self.backend.lock:
                active = self.settings.pricing_selection(lookup)
                cached = self.settings.model_defaults(active['id'], lookup['model'])
                if cached['inputRate'] is not None and cached['outputRate'] is not None:
                    return  # Retain the labeled stale quote when its route still matches.
            raise
        with self.backend.lock:
            if self.closing:
                raise ValueError('The app closed while reading prices. Try again after reopening it.')
            self.settings.retain_prices(lookup, prices)

    def openrouter_hosts(self, model=""):
        return self.settings.openrouter_hosts(model)

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
    app = Application(args.workspace, not args.offline)
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
        "settings_model_defaults": (app.settings_model_defaults, lambda value, _params: value),
        "openrouter_hosts": (app.openrouter_hosts, lambda value, _params: views.openrouter_hosts(value)),
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
            for name in ("execute", "answer", "stop", "resume", "inspect", "retain_run")
        },
        "guided_export": (app.guided.export, lambda value, _params: value),
        "guided_output_folder": (app.guided.output_folder, lambda value, _params: value),
        "guided_payload": (app.guided.payload, lambda value, _params: value),
        "guided_name_results": (app.guided.name_results, lambda value, _params: value),
        "guided_file_preview": (app.guided.file_preview, lambda value, _params: value),
        "guided_discard_preparation": (app.guided.discard_preparation, lambda value, _params: value),
        "guided_provider_details": (app.guided.provider_details, lambda value, _params: value),
        "guided_batch_cancel_preview": (app.guided.batch_cancel_preview, lambda value, _params: value),
        "guided_batch_cancel": (app.guided.batch_cancel, lambda value, _params: value),
        "guided_batch_collect": (app.guided.batch_collect, lambda value, _params: views.job(value)),
        "translation_speakers": (app.guided.speakers, lambda value, _params: views.speaker_scan(value)),
        **{"guided_" + name: (getattr(app.guided, name), lambda value, _params: value)
           for name in ("position", "options_draft", "save_options", "apply_speakers", "skill", "form", "context_status", "context_review", "reference_add", "reference_remove", "event_text_request", "event_text_review", "event_text_view", "event_text_picker", "comparisons_review")},
        "guided_draft": (app.guided.draft, lambda value, _params: value),
        "guided_save_document": (
            app.guided.save_document,
            lambda value, _params: views.documents(value),
        ),
    }
    for name in ("state", "save", "draft", "documents", "save_document", "prepare", "backups", "compile", "run", "request",
                 "start", "stop", "accept", "review", "progress", "operation", "attach_batch", "resolve_uncertain", "identify", "legacy"):
        methods["translation_" + name] = (getattr(app.translation, name), lambda value, _params: value)
    for name in ("state", "list", "update", "action", "preview"):
        methods["images_" + name] = (getattr(app.images, name), lambda value, _params: value)
    for name in ("state", "list", "detail", "update", "action"):
        methods["plugins_" + name] = (getattr(app.plugins, name), lambda value, _params: value)
    methods["plugins_continue"] = (app.plugins.continue_task, lambda value, _params: value)
    for name in ("state", "save", "action"):
        methods["images_editor_" + name] = (getattr(app.image_editor, name), lambda value, _params: value)
    for name in ("state", "preview", "start", "action"):
        methods["images_editor_translation_" + name] = (getattr(app.image_native, name), lambda value, _params: value)

    def dispatch(name, params):
        if name not in methods:
            raise ValueError("Unknown project operation.")
        handler, present = methods[name]
        app.prepare_model_pricing(name, params)
        if name in {"connection_check", "openrouter_hosts"}:
            return present(handler(**params), params)
        with app.backend.context(), app.translation.engine.context():
            if app.closing:
                raise ValueError("The app is closing. Reopen it to resume saved project work.")
            return present(handler(**params), params)

    if set(methods) != set(PROTOCOL["methods"]):
        raise RuntimeError("The application API does not match its protocol manifest.")
    local = LocalAPI(app.workspace, PROTOCOL["version"], dispatch)
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
                    print(json.dumps(response), file=RPC_OUTPUT, flush=True)
                    continue
                method = methods.get(request.get("method"))
                if not method:
                    raise ValueError("Unknown application operation.")
                params = request.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError("Application parameters must be an object.")
                result = dispatch(request["method"], params)
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
            print(json.dumps(response, ensure_ascii=False), file=RPC_OUTPUT, flush=True)
    finally:
        app.closing = True
        app.guided.batch_monitor.close()
        local.close()
        app.translation.jobs.close()
        app.images.close()
        try:
            app.backend.close()
        finally:
            app.workspace_lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--diagnostics-directory", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    diagnostics = Diagnostics(
        args.diagnostics_directory or args.workspace / "diagnostics",
        root,
        ENGINE_ROOT,
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
