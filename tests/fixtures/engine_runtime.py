"""An offline startup and parser probe using only a generated miniature game."""

import json
import os
from pathlib import Path
import socket
import sys


root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))


def offline(*_args, **_kwargs):
    raise RuntimeError("Network access is disabled in the bundled engine probe.")


def no_external_engine(event, arguments):
    if event == "open" and isinstance(arguments[0], (str, bytes)):
        path = Path(os.fsdecode(arguments[0])).absolute()
        if any(path.is_relative_to(root.parent / name) for name in ("DazedMTLTool", "DazedMTLTool-engine")):
            raise RuntimeError("The bundled engine attempted to read a sibling checkout.")


socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline
sys.addaudithook(no_external_engine)

from dazedtl.api.server import Application
from dazedtl.compatibility.runtime import ENGINE_ROOT

game = temporary / "game"
game.mkdir()
original = json.dumps([None, {"id": 1, "name": "薬", "description": "体力を回復する。", "note": ""}], ensure_ascii=False).encode()
(game / "Items.json").write_bytes(original)
app = Application(temporary / "profile", False)
try:
    assert app.state()["project"] is None
    assert app.backend.source == ENGINE_ROOT
    with app.backend.context():
        from util.paths import PROMPT_PATH, runtime_data_file
        from util.skills import load_system_prompt, load_project_setup
        from desktop.backend.manual import signature
        # A real saved run's pre-relocation signature must still pass the native
        # resume guard. Updating engine behavior needs its own recovery decision.
        assert signature("RPG Maker MV/MZ") == "b0aa0546c511a7b996fad0dad1d62619258d5eb7ec1f23e9e0ebf113bd9284aa"
        assert runtime_data_file(PROMPT_PATH).is_relative_to(root / "backend/dazedtl/data")
        assert load_system_prompt() and load_project_setup("rpgmaker")
        manual = app.backend.manual
        listing = manual.inspect(str(game), "RPG Maker MV/MZ")
        job = manual.start(str(game), "RPG Maker MV/MZ", ["Items.json"], listing["revision"])
    controller = manual.controller(job["id"])
    controller.worker.join(5)
    result = manual.jobs[job["id"]]
    assert result["status"] == "complete", (result["status"], result.get("message"), result.get("log"))
    assert result["estimate"]["input_tokens"] > 0
    assert (game / "Items.json").read_bytes() == original
    frozen = manual.folder(job["id"]) / "context/system.md"
    assert frozen.read_bytes() == (root / "backend/dazedtl/data/skills/system.md").read_bytes()
    for name, module in list(sys.modules.items()):
        if name.startswith(("util.", "modules.", "desktop.backend.")) and getattr(module, "__file__", None):
            assert Path(module.__file__).is_relative_to(ENGINE_ROOT), name
    print("Bundled startup, frozen guidance, saved-run signature and isolated parser estimation passed.")
finally:
    app.guided.batch_monitor.close()
    app.translation.jobs.close()
    app.images.close()
    app.backend.close()
    app.workspace_lock.close()
