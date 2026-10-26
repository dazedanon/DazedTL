"""Authenticated loopback access for the user's external coding assistant."""

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dazedtl import system
from dazedtl.api import views
from dazedtl.storage import write_json

# The selected project's operations an external assistant may call: every
# translation operation, and the image, plugin and Guided requests that its
# copied tasks name.
AGENT_METHODS = frozenset(
    {
        "images_state",
        "images_list",
        "images_preview",
        "plugins_state",
        "plugins_continue",
        "plugins_capture",
        "plugins_task",
        "plugins_apply",
        "guided_context_status",
        "guided_event_text_request",
    }
)


class LocalAPI:
    def __init__(
        self,
        workspace,
        version,
        dispatch,
        failure=lambda *_args: None,
        explain=lambda exc, _params: views.error(exc),
    ):
        self.path = Path(workspace) / "agent-connection.json"
        if self.path.is_symlink():
            raise ValueError("The agent connection must be a regular workspace file.")
        token = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                pass

            def do_POST(self):
                if self.path != "/rpc" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + token
                ):
                    self.send_error(403)
                    return
                method = None
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2_000_000:
                        raise ValueError("The agent request is too large.")
                    self.connection.settimeout(15)
                    value = json.loads(self.rfile.read(length))
                    if (
                        not isinstance(value, dict)
                        or value.get("version") != version
                        or not isinstance(value.get("params", {}), dict)
                    ):
                        raise ValueError(
                            "The agent helper and app versions must match."
                        )
                    method = value.get("method")
                    if not isinstance(method, str) or not (
                        method.startswith("translation_") or method in AGENT_METHODS
                    ):
                        raise ValueError(
                            "This helper only exposes the selected translation project's operations."
                        )
                    result = {
                        "ok": True,
                        "version": version,
                        "value": dispatch(method, value.get("params", {})),
                    }
                except Exception as exc:  # noqa: BLE001
                    params = value.get("params") if isinstance(value, dict) else None
                    shown = explain(exc, params if isinstance(params, dict) else {})
                    # Only failures shown as a generic message need a diagnostic trail.
                    if shown["code"] in {"internal", "storage"}:
                        failure(
                            exc,
                            f"helper {method}" if isinstance(method, str) else "helper",
                        )
                    result = {
                        "ok": False,
                        "version": version,
                        "error": shown["message"],
                    }
                raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="project-agent-api", daemon=True
        )
        write_json(
            self.path,
            {"version": version, "port": self.server.server_port, "token": token},
        )
        os.chmod(self.path, 0o600)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        system.unlink(self.path, missing_ok=True)
