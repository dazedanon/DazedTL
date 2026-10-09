"""Small line-delimited API for the clean Electron application."""

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dazedtl.api.contracts.methods import METHODS
from dazedtl.api.local import LocalAPI
from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.runtime import ENGINE_ROOT
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.diagnostics import Diagnostics
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.images import ImageService
from dazedtl.images.editor import ImageEditor
from dazedtl.images.native_translation import ImageNativeTranslation
from dazedtl.plugins import PluginService
from dazedtl.projects.store import Projects
from dazedtl.settings.store import Settings
from dazedtl.stdio import private_stdin
from dazedtl.storage import WorkspaceLock
from dazedtl.translation.assistant_tasks import AssistantTasks
from dazedtl.translation.guided import Guided
from dazedtl.translation.service import Translation, assistant_request

RPC_OUTPUT = sys.stdout
from dazedtl.api import views

# Read-only image previews run on a few workers beside the request loop.
CONCURRENT = frozenset({"images_preview"})
PREVIEW_WORKERS = 4

PROTOCOL = json.loads(
    Path(__file__).with_name("protocol.json").read_text(encoding="utf-8")
)


class Application:
    def __init__(self, workspace, allow_providers, failure=None):
        self.closing = False
        # Records errors the app handles itself, such as one unreadable project.
        self.failure = failure or (lambda *_args, **_kwargs: None)
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_lock = WorkspaceLock(self.workspace)
        self.projects = Projects(self.workspace)
        self.projects.data["screen"] = "project"
        self.backend = ExistingBackend(self.workspace / "engine", allow_providers)
        with self.backend.context():
            self.settings = Settings(self.workspace, self.backend)
        self.translation = Translation(
            self.workspace,
            self.projects,
            self.settings,
            TranslationEngine(self.workspace / "engine"),
        )
        self.guided = Guided(
            self.backend, self.projects, self.settings, self.translation
        )
        self.images = ImageService(
            self.projects, self.translation, self.settings, self.backend
        )
        self.plugins = PluginService(
            self.projects,
            self.translation,
            self.backend,
            context=self.guided.assistant_context,
        )
        self.assistant_tasks = AssistantTasks(self.workspace)
        self.image_editor = ImageEditor(self.images)
        self.image_native = ImageNativeTranslation(self.images, self.image_editor)
        self.translation.image_units = self.images.progress_units
        self.translation.legacy_actions = {
            "resume": lambda identity: views.job(self.guided.resume(identity)),
            "stop": lambda identity: views.job(self.guided.stop(identity)),
            "answer": lambda identity, token, approved: views.job(
                self.guided.answer(identity, token, approved)
            ),
            "export": self.guided.export,
        }
        self.guided.batch_monitor.start()

    def state(self):
        value = self.projects.state()
        project = value["project"]
        value.update(
            running=self.backend.running() or self.translation.jobs.running(),
            provider_ready=self.settings.ready(),
            observing=bool(project),
        )
        if project:
            project = dict(project)
            project.update(
                available=Path(project["source"]).is_dir(),
                status="Project open",
                detail="Choose the next task for this project.",
                next_label="Continue setup",
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
                except ValueError, OSError, KeyError:
                    project.update(
                        status="Saved phased work unavailable",
                        detail="The saved job reference was retained for recovery.",
                    )
                    value["project"] = project
                    return value
                job = native["manual_job"]
                latest = native["jobs"][0] if native["jobs"] else None
                if native["project"].get("imported"):
                    project.update(
                        status="Translation workspace ready",
                        detail="Review the selected scope and saved guidance before starting a run.",
                        next_label="Continue translation",
                    )
                if latest and latest["status"] == "running":
                    project.update(
                        status="Preparing files",
                        detail=latest["label"],
                        next_label="View progress",
                    )
                elif job:
                    if job["status"] == "waiting":
                        project.update(
                            status="Approval needed",
                            detail="Review the pending request to continue.",
                            next_label="Review request",
                        )
                    elif job["status"] == "running":
                        project.update(
                            status="Batch awaiting results"
                            if job["mode"] == "batch"
                            and job["phase"].startswith("poll")
                            else "Translation running",
                            detail="",
                            next_label="View progress",
                        )
                    elif job["status"] == "complete":
                        project.update(
                            status="Estimate ready"
                            if job["mode"] == "estimate"
                            else "Translation ready",
                            detail="",
                            next_label="Review results",
                        )
                    elif job["status"] == "canceled":
                        project.update(
                            status="Translation workspace ready",
                            detail="Review scope and guidance before starting a run.",
                            next_label="Continue translation",
                        )
                    else:
                        project.update(
                            status="Run ended", detail="", next_label="Review run"
                        )
                elif latest and latest["status"] in {"failed", "interrupted"}:
                    project.update(
                        status="Preparation " + latest["status"],
                        next_label="Review progress",
                    )
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
                # A game opened before the method choice keeps the method it
                # already has work in; the choice itself is never inferred later.
                if project["method"] not in {"guided", "len"}:
                    project["method"] = (
                        "guided"
                        if project.get("backend_id")
                        else "len"
                        if current["jobs"]
                        or (current["progress"] or {}).get("updated_at")
                        else "translation"
                    )
                project["next_label"] = "Open translation"
                project["engine_label"] = current["engine"]
                project["engine"] = self.translation.engine.detect(project["source"])
                if current["jobs"]:
                    job = current["jobs"][0]
                    if (
                        job["quote"]
                        and job["status"] == "ready"
                        and not job["approved"]
                    ):
                        # A prepared run is not working; it waits for the user.
                        project.update(
                            status="Estimate needs your approval",
                            detail="Approve it on Progress, or answer your assistant.",
                        )
                    else:
                        project.update(
                            status=job["label"]
                            + " · "
                            + job["status"].replace("_", " "),
                            detail=job["message"],
                            operation=views.pick(job, ("label", "status", "message")),
                        )
                elif current["progress"] and current["progress"].get("phase"):
                    project.update(
                        status="Last reported: " + current["progress"]["phase"],
                        detail=current["progress"].get("next_action", ""),
                    )
                else:
                    project.update(
                        status="Ready for project setup",
                        detail="Choose a translation mode and prepare the starting prompt.",
                    )
                if project.get("backend_id"):
                    legacy = views.guided(
                        self.guided.state(project["id"]), project["id"]
                    )
                    run = legacy["run"]
                    active_tool = next(
                        (
                            job
                            for job in legacy["operations"]
                            if job["status"] == "running"
                        ),
                        None,
                    )
                    if active_tool:
                        project.update(
                            status=active_tool["label"],
                            detail=active_tool["message"],
                            operation=views.pick(
                                active_tool, ("label", "status", "message")
                            ),
                        )
                    elif run and run["status"] in {"running", "waiting"}:
                        project.update(
                            status="Guided run · " + run["status"],
                            detail=run["message"],
                            operation={
                                "label": "Guided run",
                                **views.pick(run, ("status", "message")),
                            },
                        )
                    else:
                        # The latest finished activity, whichever part of the
                        # app ran it: setup jobs, Guided operations or runs.
                        latest = max(
                            [
                                *current["jobs"][:1],
                                *legacy["operations"],
                                *(
                                    {**item, "label": "Translation run"}
                                    for item in legacy["runs"]
                                ),
                            ],
                            key=lambda item: item.get("updated") or "",
                            default=None,
                        )
                        if latest:
                            project.update(
                                status=latest["label"]
                                + " · "
                                + latest["status"].replace("_", " "),
                                detail=latest.get("message") or "",
                                operation=views.pick(
                                    latest, ("label", "status", "message")
                                ),
                            )
                        elif not current["progress"]:
                            project.update(
                                status="Guided workflow ready",
                                detail="Continue from " + legacy["step"] + ".",
                            )
                elif (
                    project["engine"] in {"MVMZ", "ACE"}
                    and not current["jobs"]
                    and not current["progress"]
                ):
                    project.update(
                        status="Ready for guided setup",
                        detail="Preserve the original, prepare game files, and choose a translation scope.",
                    )
            # A project that cannot be read, such as one whose Git cannot run
            # (engine errors are RuntimeErrors), must not close the workspace:
            # Settings and its updates stay reachable.
            except (
                ValueError,
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                error = self.unreadable(exc)
                project.pop("operation", None)
                project.update(
                    status="Project unavailable",
                    detail=error,
                    next_label="Open translation",
                )
        images, image_error, foreign = None, "", {}
        if project and project["available"]:
            try:
                images = self.images.state(project["id"])
            except ForeignWorkError as exc:
                foreign["imagesForeign"] = exc.summary
            except (
                ValueError,
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                image_error = self.unreadable(exc)
        plugins, plugin_error = None, ""
        if project and project["available"]:
            try:
                plugins = self.plugins.state(project["id"])
            except ForeignWorkError as exc:
                foreign["pluginsForeign"] = exc.summary
            except (
                ValueError,
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                plugin_error = self.unreadable(exc)
        assistant_tasks = []
        if project and project["available"]:
            try:
                assistant_tasks = self.assistant_tasks.view(project["id"])
            except ValueError, OSError, RuntimeError, subprocess.SubprocessError:
                assistant_tasks = []
        return {
            "application": views.application(state),
            "assistantTasks": assistant_tasks,
            "translation": current,
            "translationError": error,
            "guided": legacy,
            "images": images,
            "imagesError": image_error,
            "plugins": plugins,
            "pluginsError": plugin_error,
            **foreign,
        }

    def unreadable(self, error):
        """A project's read failure in words. A tool's own message is a Python
        command list, so it goes to diagnostics instead."""
        if isinstance(error, subprocess.SubprocessError):
            self.failure(error, "workspace_snapshot")
            return "A tool this project needs could not finish. Copy diagnostics for the details."
        return str(error)

    def recheck(self, project_id):
        """Rechecks files the user may have edited outside the app."""
        project = self.state()["project"]
        if not project or project["id"] != project_id or not project["available"]:
            return {"checked": 0}
        return {"checked": self.images.recheck(project_id)}

    def _handed_off(self, project_id, result):
        """Records the task a copy handed to the assistant; the reply keeps
        only what the renderer reads."""
        handoff = result.pop("handoff", None)
        if handoff:
            self.assistant_tasks.copied(project_id, handoff)
        return result

    def guided_skill(self, project_id, name):
        return self._handed_off(project_id, self.guided.skill(project_id, name))

    def images_action(self, project_id, action, options=None):
        return self._handed_off(
            project_id, self.images.action(project_id, action, options)
        )

    def translation_images(self, project_id, step):
        """One Images step for an Assistant-led project's own assistant. A
        Guided project's Images task stays the user's to apply."""
        record, project = self.translation.project(project_id)
        if record.get("method") != "len":
            raise ValueError(
                "The helper's image steps are for Assistant-led projects; Guided translates images in its Images task."
            )
        if not project.read()["options"]["include_images"]:
            raise ValueError(
                "Image text is outside this project's scope; report any remaining baked text instead."
            )
        result = self.images.assistant(project_id, step)
        try:
            self.translation.sync_images(project_id)
        except ValueError as exc:
            result["problems"].append("Progress was not updated: " + str(exc))
        return result

    def plugins_action(self, project_id, action, options=None):
        return self._handed_off(
            project_id, self.plugins.action(project_id, action, options)
        )

    def assistant_task_dismiss(self, project_id, kind):
        self.projects.get(project_id)
        return self.assistant_tasks.dismiss(project_id, kind)

    def open_project(self, source):
        root = Path(source).expanduser().resolve(strict=True)
        if not root.is_dir() or root == root.parent:
            raise ValueError("Choose a game folder.")
        for protected in (
            self.backend.source,
            self.workspace,
            Path(__file__).resolve().parents[3],
        ):
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise ValueError(
                    "Choose a game folder separate from application and workspace storage."
                )
        detected = {"source": str(root), "engine": self.translation.engine.detect(root)}
        self.projects.open(detected)
        return self.state()

    def select_project(self, project_id):
        self.projects.select(project_id)
        return self.state()

    def project_method(self, project_id, method):
        """Choose a game's method; Guided steps link the game's Guided workspace."""
        if method == "guided":
            self.guided.open(project_id)
        self.projects.choose_method(project_id, method)
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
        return self.resolve_batch_support(connection_id=connection_id, model=model)

    def resolve_batch_support(self, *, connection_id=None, model=None, persist=False):
        """Model selection checks endpoints without holding the engine/app lock."""
        with self.backend.lock:
            if self.closing:
                if persist:
                    return None
                raise ValueError(
                    "The app is closing. Reopen it before checking model defaults."
                )
            lookup = self.settings.batch_lookup(
                connection_id=connection_id, model=model
            )
        endpoints = None
        if lookup is not None:
            from dazedtl.settings.openrouter import check_endpoints

            connection = {**lookup["connection"], "model": lookup["model"]}
            endpoints = check_endpoints(connection, connection["catalog"])
        with self.backend.context(), self.translation.engine.context():
            if self.closing:
                if persist:
                    return None
                raise ValueError(
                    "The app closed while checking model defaults. Try again after reopening it."
                )
            if lookup is not None:
                endpoints = self.settings.retain_batch_endpoints(
                    lookup, endpoints, persist=persist
                )
            if not persist:
                return self.settings.model_defaults(
                    connection_id, model, batch_endpoints=endpoints
                )

    def prepare_model_pricing(self, name, params):
        """Only explicit price/estimate actions may perform public price reads."""
        explicit = name == "settings_model_defaults"
        prepares = (
            name == "guided_preview"
            and params.get("action") == "start"
            or name == "translation_compile"
            or name == "images_editor_translation_preview"
        )
        if not explicit and not prepares:
            return
        with self.backend.lock:
            if self.closing:
                raise ValueError(
                    "The app is closing. Reopen it before preparing requests."
                )
            if name == "translation_compile":
                _record, project = self.translation.project(params.get("project_id"))
                if project.read()["options"]["mode"] == "agent":
                    return
            lookup = self.settings.pricing_lookup(
                connection_id=params.get("connection_id") if explicit else None,
                model=params.get("model") if explicit else None,
                explicit=explicit,
            )
        if lookup is None:
            return
        from dazedtl.settings.openrouter import live_prices

        try:
            prices = live_prices(lookup["model"], lookup["host"])
        except ValueError:
            with self.backend.lock:
                active = self.settings.pricing_selection(lookup)
                cached = self.settings.model_defaults(active["id"], lookup["model"])
                if cached["inputRate"] is not None and cached["outputRate"] is not None:
                    return  # Retain the labeled stale quote when its route still matches.
            raise
        with self.backend.lock:
            if self.closing:
                raise ValueError(
                    "The app closed while reading prices. Try again after reopening it."
                )
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

    def connection_usage(self, connection_id):
        return self.settings.connection_usage(connection_id)

    def connection_remove(self, revision, connection_id, unfinished):
        self.guided.idle()
        return self.settings.remove_connection(revision, connection_id, unfinished)


def routes(app):
    """Each method's handler and the view that shapes its result."""
    methods = {
        "workspace_snapshot": (app.snapshot, lambda value, _params: value),
        "workspace_recheck": (app.recheck, lambda value, _params: value),
        **{
            name: (getattr(app, name), lambda value, _params: views.application(value))
            for name in ("open_project", "select_project", "navigate", "project_method")
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
                "connection_remove",
            )
        },
        "connection_usage": (app.connection_usage, lambda value, _params: value),
        "settings_draft": (app.settings_draft, lambda value, _params: value),
        "settings_model_defaults": (
            app.settings_model_defaults,
            lambda value, _params: value,
        ),
        "openrouter_hosts": (
            app.openrouter_hosts,
            lambda value, _params: views.openrouter_hosts(value),
        ),
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
            for name in ("execute", "answer", "stop", "resume", "inspect")
        },
        "guided_output_folder": (
            app.guided.output_folder,
            lambda value, _params: value,
        ),
        "guided_release_destination": (
            app.guided.release_destination,
            lambda value, _params: value,
        ),
        "guided_payload": (app.guided.payload, lambda value, _params: value),
        "guided_name_results": (app.guided.name_results, lambda value, _params: value),
        "guided_file_preview": (app.guided.file_preview, lambda value, _params: value),
        "guided_discard_preparation": (
            app.guided.discard_preparation,
            lambda value, _params: value,
        ),
        "guided_settle_empty_estimate": (
            app.guided.settle_empty_estimate,
            lambda value, _params: value,
        ),
        "guided_provider_details": (
            app.guided.provider_details,
            lambda value, _params: value,
        ),
        "guided_batch_cancel_preview": (
            app.guided.batch_cancel_preview,
            lambda value, _params: value,
        ),
        "guided_batch_cancel": (app.guided.batch_cancel, lambda value, _params: value),
        "guided_batch_collect": (
            app.guided.batch_collect,
            lambda value, _params: views.job(value),
        ),
        "translation_speakers": (
            app.guided.speakers,
            lambda value, _params: views.speaker_scan(value),
        ),
        **{
            "guided_" + name: (getattr(app.guided, name), lambda value, _params: value)
            for name in (
                "position",
                "options_draft",
                "save_options",
                "apply_speakers",
                "form",
                "context_status",
                "context_review",
                "reference_add",
                "reference_remove",
                "event_text_request",
                "event_text_apply",
                "event_text_view",
                "event_text_picker",
                "comparisons_review",
            )
        },
        "guided_skill": (app.guided_skill, lambda value, _params: value),
        "assistant_task_dismiss": (
            app.assistant_task_dismiss,
            lambda value, _params: value,
        ),
        "guided_draft": (app.guided.draft, lambda value, _params: value),
        "guided_save_document": (
            app.guided.save_document,
            lambda value, _params: views.documents(value),
        ),
    }
    for name in (
        "state",
        "save",
        "draft",
        "documents",
        "save_document",
        "prepare",
        "backups",
        "compile",
        "run",
        "request",
        "start",
        "stop",
        "accept",
        "review",
        "progress",
        "operation",
        "attach_batch",
        "resolve_uncertain",
        "identify",
        "legacy",
    ):
        methods["translation_" + name] = (
            getattr(app.translation, name),
            lambda value, _params: value,
        )
    for name in ("state", "list", "update", "preview"):
        methods["images_" + name] = (
            getattr(app.images, name),
            lambda value, _params: value,
        )
    # Absent from the helper's methods: only the user starts a project over.
    methods["project_start_over"] = (
        app.translation.start_over,
        lambda value, _params: value,
    )
    methods["translation_images"] = (
        app.translation_images,
        lambda value, _params: value,
    )
    methods["images_action"] = (
        app.images_action,
        lambda value, _params: views.image_action(value),
    )
    for name in ("adopt", "start_over"):
        methods["images_" + name] = (
            getattr(app.images, name),
            lambda value, _params: value,
        )
        methods["plugins_" + name] = (
            getattr(app.plugins, name),
            lambda value, _params: value,
        )
    methods["plugins_action"] = (app.plugins_action, lambda value, _params: value)
    methods["plugins_state"] = (app.plugins.state, lambda value, _params: value)
    methods["plugins_continue"] = (
        app.plugins.continue_task,
        lambda value, _params: value,
    )
    for name in ("state", "save", "action"):
        methods["images_editor_" + name] = (
            getattr(app.image_editor, name),
            lambda value, _params: value,
        )
    for name in ("state", "preview", "start", "action"):
        methods["images_editor_translation_" + name] = (
            getattr(app.image_native, name),
            lambda value, _params: value,
        )
    return methods


def dispatcher(app, check=False):
    """Run methods by name; check validates both sides against the contracts."""
    methods = routes(app)
    if set(methods) != set(METHODS):
        raise RuntimeError("The application API does not match its contracts.")
    checks = None
    if check:
        # Validation needs pydantic, which normal runs never load.
        from dazedtl.api.contracts import validation as checks

    def run(name, params):
        handler, present = methods[name]
        app.prepare_model_pricing(name, params)
        if name in {"connection_check", "openrouter_hosts", "settings_model_defaults"}:
            return present(handler(**params), params)
        # Previews only read image files and run on the preview workers, which
        # must not enter the engine context: it redirects stdout process-wide.
        if name in CONCURRENT:
            return present(handler(**params), params)
        with app.backend.context(), app.translation.engine.context():
            if app.closing:
                raise ValueError(
                    "The app is closing. Reopen it to resume saved project work."
                )
            value = present(handler(**params), params)
        if name in {"settings_save", "connection_save", "connection_select"}:
            app.resolve_batch_support(persist=True)
        return value

    def dispatch(name, params):
        if name not in methods:
            raise ValueError("Unknown project operation.")
        if checks:
            checks.check_request(name, params)
        value = run(name, params)
        if checks:
            checks.check_response(name, value)
        return value

    return dispatch


def assistant_dispatch(app, dispatch):
    """The project helper's requests; each Assistant-led one also notes that
    the user's assistant reached its project, whether or not it succeeds."""

    def run(name, params):
        request = assistant_request.set(True)
        try:
            return dispatch(name, params)
        finally:
            assistant_request.reset(request)
            if name.startswith("translation_") and not app.closing:
                app.translation.contacted(params.get("project_id"))

    return run


def serve(args, diagnostics):
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    app = Application(args.workspace, not args.offline, diagnostics.failure)
    dispatch = dispatcher(app, os.environ.get("DAZEDTL_CHECK_CONTRACTS") == "1")
    local = LocalAPI(
        app.workspace, PROTOCOL["version"], assistant_dispatch(app, dispatch)
    )
    # Electron matches replies by id, so previews may answer out of order
    # while the loop keeps reading; every other request still runs in turn.
    previews = ThreadPoolExecutor(PREVIEW_WORKERS, thread_name_prefix="preview")
    output = threading.Lock()

    def respond(response):
        line = json.dumps(response, ensure_ascii=False)
        with output:
            print(line, file=RPC_OUTPUT, flush=True)

    def answer(request):
        try:
            if not isinstance(request, dict):
                request = {}
                raise ValueError("Application requests must be objects.")
            if request.get("version") != PROTOCOL["version"]:
                return {
                    "id": request.get("id"),
                    "version": PROTOCOL["version"],
                    "error": {
                        "code": "protocol",
                        "message": "The application and backend versions do not match. Restart after updating.",
                    },
                }
            name = request.get("method")
            if not isinstance(name, str) or name not in METHODS:
                raise ValueError("Unknown application operation.")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("Application parameters must be an object.")
            return {
                "id": request.get("id"),
                "version": PROTOCOL["version"],
                "result": dispatch(name, params),
            }
        except Exception as exc:  # noqa: BLE001
            error = views.error(exc)
            # Validation and missing-file messages reach the user as written;
            # only failures shown as a generic message need a diagnostic trail.
            if error["code"] in {"internal", "storage"}:
                name = request.get("method")
                operation = (
                    name if isinstance(name, str) and name in METHODS else "native"
                )
                diagnostics.failure(exc, operation, request.get("id"))
            return {
                "id": request.get("id"),
                "version": PROTOCOL["version"],
                "error": error,
            }

    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except ValueError as exc:
                diagnostics.failure(exc, "native", None)
                respond(
                    {
                        "id": None,
                        "version": PROTOCOL["version"],
                        "error": views.error(exc),
                    }
                )
                continue
            if (
                isinstance(request, dict)
                and request.get("method") in CONCURRENT
                and request.get("version") == PROTOCOL["version"]
            ):
                previews.submit(lambda request=request: respond(answer(request)))
            else:
                respond(answer(request))
    finally:
        app.closing = True
        previews.shutdown(cancel_futures=True)
        app.guided.batch_monitor.close()
        local.close()
        app.translation.jobs.close()
        app.images.close()
        try:
            app.backend.close()
        finally:
            app.workspace_lock.close()


def main():
    # Requests arrive on standard input; children must not inherit that pipe.
    sys.stdin = private_stdin()
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
        if platform.python_version() != (root / ".python-version").read_text().strip():
            print("DAZEDTL_ERROR runtime_version", file=sys.stderr, flush=True)
            return 1
        serve(args, diagnostics)
        return 0
    except Exception as exc:  # noqa: BLE001
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
