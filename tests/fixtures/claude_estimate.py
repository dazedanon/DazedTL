"""A real Claude estimate run, counted against a local token-count stand-in."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))
# The suite never counts; this probe counts only against its own stand-in.
os.environ.pop("DAZEDTL_TEST_OFFLINE")
calls = []


class CountStandIn(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        calls.append((self.path, self.headers.get("x-api-key")))
        reply = json.dumps({"input_tokens": len(body)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), CountStandIn)
threading.Thread(target=server.serve_forever, daemon=True).start()

from dazedtl.api.server import Application

game = temporary / "game"
game.mkdir()
(game / "Items.json").write_text(
    json.dumps(
        [None, {"id": 1, "name": "薬", "description": "体力を回復する。", "note": ""}],
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
app = Application(temporary / "profile", True)
settings = app.settings_get()
settings = app.connection_save(
    revision=settings["revision"],
    provider="anthropic",
    protocol="anthropic",
    name="Claude",
    secret="sk-ant-probe",
    endpoint="",
    organization="",
    keyless=False,
    reuse_secret=False,
)
connection = next(item["id"] for item in settings["connections"])
settings = app.connection_select(settings["revision"], connection)
app.settings_save(
    settings["revision"],
    connection,
    {"language": "English", "model": "claude-sonnet-5-5"},
    {
        "claude-sonnet-5-5": {
            "entriesPerRequest": 30,
            "pricing": "custom",
            "inputRate": 3,
            "outputRate": 15,
        }
    },
)
app.settings.prepare_engine(mode="estimate")
manual = app.backend.manual
with app.backend.context():
    import desktop.backend.manual as engine_manual

    environment = engine_manual.worker_environment
    listing = manual.inspect(str(game), "RPG Maker MV/MZ")
# Only the count process may reach the stand-in; the estimate worker keeps
# its own environment, with no credential and no network.
with patch.object(
    engine_manual,
    "worker_environment",
    lambda workspace, plan: {
        **environment(workspace, plan),
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
    },
):
    with app.backend.context():
        job = manual.start(
            str(game), "RPG Maker MV/MZ", ["Items.json"], listing["revision"]
        )
    # Half the suite's budget (scripts/test.mjs) for the worker to exit.
    manual.controller(job["id"]).worker.join(
        float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10) / 2
    )
result = manual.jobs[job["id"]]
assert result["status"] == "complete", (result["status"], result.get("message"))
estimate = result["estimate"]
assert estimate["provider"] == "anthropic", estimate
assert estimate["approximate_input"] is False, estimate
assert estimate["files"] == 1, estimate
assert f"[Input: {estimate['input_tokens']}]" in result["message"], result["message"]
assert calls and all(
    call == ("/v1/messages/count_tokens", "sk-ant-probe") for call in calls
), calls
server.shutdown()
print("A Claude estimate completed with Claude's own count.")
