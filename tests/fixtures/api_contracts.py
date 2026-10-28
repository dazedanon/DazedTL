"""Exercise the real application API offline and check both sides of every call."""

import inspect
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))

from dazedtl.api import views
from dazedtl.api.contracts.methods import METHODS
from dazedtl.api.server import Application, dispatcher, routes
from dazedtl.compatibility import original_files, original_record

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
    assert call("project_languages_lock", {"project_id": project_id}) == {"reason": ""}
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
    call("guided_position", {"project_id": project_id, "step": "setup"})
    call("workspace_recheck", {"project_id": project_id})
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
    # Opening the game started recording its original files in the
    # background; a task's write into the game waits for that record, which
    # takes longer on a busy machine.
    for _attempt in range(200):
        if original_files.recorded(game):
            break
        time.sleep(0.05)
    assert original_files.recorded(game), "Opening the game recorded nothing."
    call("guided_skill", {"project_id": project_id, "name": "setup"})
    call("assistant_task_dismiss", {"project_id": project_id, "kind": "names"})
    call("guided_draft", {"project_id": project_id, "documents": {}})
    name, document = next(iter(guided["documents"].items()))
    call(
        "guided_save_documents",
        {
            "project_id": project_id,
            "documents": {
                name: {
                    "revision": document["revision"],
                    "text": document["text"] + "\n",
                }
            },
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
        {"project_id": project_id, "action": "prepare_game", "options": {}},
    )
    for method in (
        "translation_state",
        "translation_documents",
        "translation_backups",
        "translation_word_spacing",
        "project_checkpoints",
        "images_state",
        "images_list",
        "images_editor_state",
        "images_editor_translation_state",
        "plugins_state",
    ):
        call(method, {"project_id": project_id})
    call("workspace_snapshot", {})
    # While it runs, every reply carries its progress for the writes that
    # wait for it, whose refusals the page tells apart by their code.
    running = {
        "running": True,
        "message": "Recorded 2 of 3 original files in Git.",
        "error": "",
        "stopped": False,
    }
    with patch.object(original_record, "view", lambda _root: running):
        shown = call("workspace_snapshot", {})["application"]["project"]
        assert shown["originals"] == running, shown
    assert views.error(original_record.RecordPending("Wait."))["code"] == "recording"
    try:
        call("originals_stop", {"project_id": project_id})
    except ValueError as error:
        assert "no longer being recorded" in str(error), error
    else:
        raise AssertionError("A finished record stopped.")
    # A game moved into a folder inside its old one, as the user tidied a
    # download, opens as the same project with its work and stages; until
    # then the project offers Find game folder.
    before = call("workspace_snapshot", {})
    game.rename(temporary / "moving")
    game.mkdir()
    moved = (temporary / "moving").rename(game / "Game")
    gone = call("workspace_snapshot", {})["application"]["project"]
    assert not gone["available"] and gone["next_label"] == "Find game folder", gone
    assert call("open_project", {"source": str(moved)})["project"]["id"] == project_id
    after = call("workspace_snapshot", {})
    assert after["guided"] == json.loads(
        json.dumps(before["guided"]).replace(
            json.dumps(str(game))[1:-1], json.dumps(str(moved))[1:-1]
        )
    ), "The moved project's Guided workspace changed."
    assert [p["id"] for p in after["application"]["recent"]] == [project_id]
    # Renamed while the project points at it, Find game folder opens it where
    # it is now, though the project's own folder is gone.
    found = moved.rename(game / "Renamed")
    located = call("locate_project", {"project_id": project_id, "source": str(found)})
    assert located["project"]["source"] == str(found), located["project"]
    # Runs saved by earlier versions keep estimate fields the contract dropped.
    from dazedtl.api import views
    from dazedtl.api.contracts.validation import check_response

    saved = {"id": "saved", "status": "complete", "message": "", "log": []}
    saved["estimate"] = {"input_tokens": 1, "cold_cache": False, "speakers": []}
    check_response("guided_inspect", views.job(saved))
    # The run view keeps every field its contract declares: a dropped optional
    # field passes every response check and reaches the app as missing.
    from dazedtl.api.contracts.runs import Job

    assert set(views.job(dict.fromkeys(Job.__annotations__))) == set(
        Job.__annotations__
    )
    # Copied Guided tasks tell the assistant to run these helper commands; the
    # loopback helper used to refuse every Guided request.
    from importlib.util import module_from_spec, spec_from_file_location

    from dazedtl.api.local import LocalAPI
    from dazedtl.api.server import PROTOCOL, assistant_dispatch

    spec = spec_from_file_location("project_helper", root / "scripts/project.py")
    helper = module_from_spec(spec)
    spec.loader.exec_module(helper)
    # Progress shows an Assistant-led run started once the assistant uses the
    # helper, before its first report; the app's own reads never count.
    state = {"project_id": project_id}
    assert call("translation_state", state)["assistantSeenAt"] is None
    failures = []

    def dispatch(name, params):
        if params.get("explode"):
            raise RuntimeError("A fault the assistant can't act on.")
        return call(name, params)

    local = LocalAPI(
        app.workspace,
        PROTOCOL["version"],
        assistant_dispatch(app, dispatch),
        lambda _error, operation: failures.append(operation),
    )
    try:
        for method in (
            "guided_context_status",
            "guided_event_text_request",
            "translation_state",
        ):
            helper.call(app.workspace, method, {"project_id": project_id})
        # Guided tasks use the helper too (Text QA, Plugin files); only an
        # Assistant-led project counts it as its assistant.
        assert call("translation_state", state)["assistantSeenAt"] is None
        app.projects.choose_method(project_id, "len")
        helper.call(app.workspace, "translation_state", {"project_id": project_id})
        # Only the user starts a project over; the helper must refuse it.
        try:
            helper.call(
                app.workspace,
                "project_start_over",
                {"project_id": project_id, "keep_context": True},
            )
        except ValueError as refused:
            assert "only exposes" in str(refused), refused
        else:
            raise AssertionError("The project helper reached Start over.")
        # An unexpected fault reads as generic to the assistant, so Copy
        # diagnostics must keep its cause.
        try:
            helper.call(
                app.workspace,
                "translation_state",
                {"project_id": project_id, "explode": 1},
            )
        except ValueError as refused:
            assert "could not finish" in str(refused), refused
        assert failures == ["helper translation_state"], failures
    finally:
        local.close()
    assert call("translation_state", state)["assistantSeenAt"]
finally:
    app.closing = True
    app.guided.batch_monitor.close()
    app.translation.jobs.close()
    original_record.close()
    app.images.close()
    try:
        app.backend.close()
    finally:
        app.workspace_lock.close()
