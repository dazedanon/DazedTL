"""A Claude estimate run, counted against a local token-count stand-in.

The engine probe runs the real offline estimate worker and its file worker.
Here the engine queues and prices the request in this process instead, so
the run's only child is the count process it starts before completing.
"""

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))
# The suite never counts; this probe counts only against its own stand-in.
os.environ.pop("DAZEDTL_TEST_OFFLINE")
calls = []


def offline(*_args, **_kwargs):
    raise RuntimeError("Network access is disabled in the Claude estimate probe.")


# The count process connects to the stand-in; nothing here connects anywhere.
socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline


class CountStandIn(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        calls.append((self.path, self.headers.get("x-api-key"), len(body)))
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

model = "claude-sonnet-5-5"
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
    {"language": "English", "model": model},
    {
        model: {
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
    from util import translation

    environment = engine_manual.worker_environment
    listing = manual.inspect(str(game), "RPG Maker MV/MZ")


def estimate_worker(_launch, _arguments, cwd, **_options):
    """What the offline worker leaves and reports: the queued request and its
    approximate Claude estimate, sent as the worker's protocol events."""
    queue = Path(cwd) / "log/estimate_requests.json"
    payload = json.dumps({"Line1": "薬"}, ensure_ascii=False)
    params = translation.buildClaudeRequest(
        "Translate.", f"```json\n{payload}\n```", [], "json", model, 1
    )
    translation.queue_batch_request(payload, "English", params, provider="anthropic")
    translation.flush_batch_queue(force=True, queue_file=queue)
    with (
        patch.dict(os.environ, {"DAZEDTL_TEST_OFFLINE": "1"}),
        patch.object(translation, "BATCH_ESTIMATE_QUEUE_FILE", queue),
    ):
        estimate = translation.estimateTranslationCosts()
    assert estimate and estimate["approximate_input"], estimate
    events = (
        ("estimate_ready", {**estimate, "files": 1}),
        ("finished", True, "Estimation completed."),
    )
    return SimpleNamespace(
        stdout=[
            json.dumps({"event": event, "args": args}) + "\n" for event, *args in events
        ],
        wait=lambda: 0,
        poll=lambda: 0,
    )


# Runs start their worker through the compatibility layer's own copy of the
# engine module.
sys.modules["desktop.backend._dazedtl_manual"].launch_worker.layer(
    "probe-estimate-worker", estimate_worker
)
# Only the count process reads this module's environment, which leads it to
# the stand-in.
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
    # Half the suite's budget (scripts/test.mjs) for the run to complete.
    manual.controller(job["id"]).worker.join(
        float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10) / 2
    )
result = manual.jobs[job["id"]]
assert result["status"] == "complete", (result["status"], result.get("message"))
estimate = result["estimate"]
assert estimate["provider"] == "anthropic", estimate
assert estimate["approximate_input"] is False, estimate
assert f"[Input: {estimate['input_tokens']}]" in result["message"], result["message"]
assert calls and all(
    call[:2] == ("/v1/messages/count_tokens", "sk-ant-probe") for call in calls
), calls
# One request, counted whole: its count is the estimate's input.
assert estimate["input_tokens"] == max(call[2] for call in calls), (estimate, calls)
print("A Claude estimate completed with Claude's own count.")
