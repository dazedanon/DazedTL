"""Exercise the real application API offline and check both sides of every call."""

import inspect
import json
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))

from dazedtl.api.contracts.methods import METHODS
from dazedtl.api.server import Application, dispatcher, routes

game = temporary / "game"
(game / "data").mkdir(parents=True)
(game / "js").mkdir()
(game / "data/System.json").write_text('{"gameTitle": "テスト", "locale": "ja_JP"}')
(game / "data/Items.json").write_text(
    json.dumps([None, {"id": 1, "name": "薬", "note": ""}], ensure_ascii=False)
)
(game / "js/plugins.js").write_text("var $plugins = [];\n")
references = temporary / "references"
references.mkdir()
(references / "notes.md").write_text("Notes")
app = Application(temporary / "profile", False)
try:
    # Requests: the renderer may send every declared field, must send each
    # parameter without a default, and may omit only defaulted parameters.
    handlers = {name: handler for name, (handler, _view) in routes(app).items()}
    handlers["connection_save"] = app.settings.save_connection
    for name, method in METHODS.items():
        parameters = inspect.signature(handlers[name]).parameters
        defaulted = {
            key for key, value in parameters.items() if value.default is not value.empty
        }
        required, optional = (
            method.request.__required_keys__,
            method.request.__optional_keys__,
        )
        assert required | optional <= parameters.keys(), (name, parameters)
        assert parameters.keys() - defaulted <= required, (name, parameters)
        assert optional <= defaulted, (name, optional - defaulted)

    # Responses: a short real journey through the methods that finish without
    # background work. Each reply must match its contract exactly.
    call = dispatcher(app, check=True)
    call("workspace_snapshot", {})
    project = call("open_project", {"source": str(game)})["project"]
    assert project, "The fixture game did not open."
    project_id = project["id"]
    call("select_project", {"project_id": project_id})
    call("navigate", {"screen": "guided"})
    guided = call("workspace_snapshot", {})["guided"]
    settings = call("settings_get", {})
    preferences = {
        "revision": settings["revision"],
        "connection_id": settings["activeConnectionId"],
        "values": settings["values"],
        "model_options": settings["modelOptions"],
    }
    call("settings_draft", preferences)
    settings = call(
        "connection_save",
        {
            "revision": settings["revision"],
            "provider": "custom",
            "protocol": "openai",
            "name": "Local",
            "secret": "",
            "endpoint": "http://127.0.0.1:9/v1",
            "organization": "",
            "keyless": True,
            "reuse_secret": False,
        },
    )
    connection = settings["connections"][-1]["id"]
    settings = call(
        "connection_select",
        {"revision": settings["revision"], "connection_id": connection},
    )
    call(
        "settings_revert",
        {"revision": settings["revision"], "connection_id": connection},
    )
    call("guided_phase_select", {"project_id": project_id, "phase": "database"})
    call("guided_position", {"project_id": project_id, "step": "prepare"})
    call("guided_form", {"project_id": project_id, "value": guided["form"]})
    call(
        "guided_options_draft",
        {"project_id": project_id, "value": guided["preferences"]},
    )
    call(
        "guided_save_options",
        {
            "project_id": project_id,
            "revision": guided["preferences"]["revision"],
            "values": guided["preferences"]["values"],
        },
    )
    call("guided_context_status", {"project_id": project_id})
    call("guided_skill", {"project_id": project_id, "name": "setup"})
    call("guided_draft", {"project_id": project_id, "documents": {}})
    name, document = next(iter(guided["documents"].items()))
    call(
        "guided_save_document",
        {
            "project_id": project_id,
            "name": name,
            "revision": document["revision"],
            "text": document["text"] + "\n",
        },
    )
    folders = call(
        "guided_reference_add", {"project_id": project_id, "folder": str(references)}
    )
    call(
        "guided_reference_remove",
        {"project_id": project_id, "reference_id": folders[0]["id"]},
    )
    call("guided_event_text_request", {"project_id": project_id})
    call("guided_event_text_view", {"project_id": project_id, "view": "audit"})
    call("guided_output_folder", {"project_id": project_id})
    call("translation_speakers", {"project_id": project_id, "scan": False})
    call("guided_file_preview", {"project_id": project_id, "name": "Items.json"})
    call(
        "guided_preview",
        {"project_id": project_id, "action": "backup_source", "options": {}},
    )
    for method in (
        "translation_state",
        "translation_documents",
        "translation_backups",
        "images_state",
        "images_list",
        "images_editor_state",
        "images_editor_translation_state",
        "plugins_state",
        "plugins_list",
    ):
        call(method, {"project_id": project_id})
    call("workspace_snapshot", {})
finally:
    app.closing = True
    app.guided.batch_monitor.close()
    app.translation.jobs.close()
    app.images.close()
    try:
        app.backend.close()
    finally:
        app.workspace_lock.close()
