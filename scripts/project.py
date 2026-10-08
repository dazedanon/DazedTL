#!/usr/bin/env python3
"""Operate one DazedTL project through the running app; no credentials are exported."""

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dazedtl.translation.service import OPERATIONS


def call(workspace, method, params):
    path = Path(workspace).expanduser().resolve() / "agent-connection.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError(
            "Open DazedTL with this workspace before continuing the project."
        )
    connection = json.loads(path.read_text(encoding="utf-8"))
    protocol = json.loads(
        (
            Path(__file__).resolve().parents[1] / "backend/dazedtl/api/protocol.json"
        ).read_text(encoding="utf-8")
    )
    if (
        connection["version"] != protocol["version"]
        or type(connection.get("port")) is not int
        or not 1 <= connection["port"] <= 65535
    ):
        raise ValueError("Restart DazedTL and use its current project helper.")
    request = urllib.request.Request(
        "http://127.0.0.1:" + str(connection["port"]) + "/rpc",
        data=json.dumps(
            {"version": protocol["version"], "method": method, "params": params}
        ).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + connection["token"],
            "Content-Type": "application/json",
        },
        method="POST",
    )

    # Credentials for the local control endpoint must never pass through a proxy.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with client.open(request, timeout=120) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(
            "The local DazedTL request failed. The app may still be running: a network sandbox can block "
            "loopback (127.0.0.1). Use the assistant's normal permission flow for this helper, then retry "
            "the read-only state command. Reopen DazedTL with this workspace only if it remains unreachable "
            "with permitted access. Inspect saved state and runs before retrying any state-changing command; "
            "the previous action may have reached the app."
        ) from exc
    if not value.get("ok"):
        raise ValueError(value.get("error", "Project operation failed."))
    return value["value"]


def main():
    # Assistants read this through a pipe, which Windows encodes in the ANSI
    # code page; game names and text need UTF-8 however the helper is started.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--project", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("state")
    commands.add_parser(
        "images",
        help="Read the selected project's indexed images, scoped handoffs and saved reports",
    )
    plugins = commands.add_parser(
        "plugins",
        help="Read plugin work or continue the copied agent task after saving its report",
    )
    plugins.add_argument(
        "--continue-request",
        help="Exact active request ID; checks the report and returns the next stage without publishing game files",
    )
    commands.add_parser("prepare")
    commands.add_parser(
        "backups", help="List local restore points and older profile backups"
    )
    speakers = commands.add_parser(
        "speakers",
        help="Read speaker discovery results; --scan applies evidenced rules and runs the local parser without API calls",
    )
    speakers.add_argument("--scan", action="store_true")
    event_text = commands.add_parser(
        "event-text",
        help="Read the current Other event text investigation request and validated findings; --apply saves their recommendations as source choices",
    )
    event_text.add_argument("--apply", action="store_true")
    commands.add_parser(
        "context",
        help="Read verified context investigation results and current document revisions",
    )
    commands.add_parser("plan-format")
    identify = commands.add_parser("identify")
    identify.add_argument("--engine", required=True)
    identify.add_argument("--evidence", required=True)
    legacy = commands.add_parser(
        "legacy", help="Recover the selected game's saved phased run"
    )
    legacy.add_argument(
        "--action", choices=("resume", "stop", "answer", "export"), required=True
    )
    legacy.add_argument("--token", default="")
    legacy.add_argument("--approved", action="store_true")
    operation = commands.add_parser(
        "operation",
        help="Start a saved engine/setup/delivery operation; inspect its ID with run",
    )
    operation.add_argument("action", choices=sorted(OPERATIONS))
    operation.epilog = "Arguments by operation: " + "; ".join(
        name + " (" + ", ".join(sorted(fields)) + ")"
        for name, (_label, fields) in OPERATIONS.items()
    )
    operation.add_argument(
        "--arguments",
        default="{}",
        help="JSON object; use --arguments-file for complex paths",
    )
    operation.add_argument("--arguments-file", type=Path)
    compile_plan = commands.add_parser("compile")
    compile_plan.add_argument("--input", required=True)
    for name in (
        "run",
        "stop",
        "start",
        "request",
        "accept",
        "review",
        "attach-batch",
        "resolve-uncertain",
    ):
        child = commands.add_parser(name)
        child.add_argument("--run", required=True)
        if name == "stop":
            child.add_argument(
                "--cancel-provider",
                action="store_true",
                help="Request provider cancellation and retain completed results",
            )
        if name == "start":
            child.add_argument(
                "--approve",
                default="",
                help="Exact quote token, only after the user's spending authorization",
            )
        if name == "request":
            child.add_argument("--index", type=int, required=True)
            child.add_argument("--output", type=Path)
        if name in {"accept", "review", "resolve-uncertain"}:
            child.add_argument("--batch", required=True)
        if name == "accept":
            child.add_argument("--input", required=True)
        if name in {"review", "resolve-uncertain"}:
            child.add_argument("--request-sha256", required=True)
        if name == "resolve-uncertain":
            child.add_argument(
                "--retry-reviewed",
                action="store_true",
                help="Only after checking whether the previous Live request was billed",
            )
        if name == "attach-batch":
            child.add_argument("--index", type=int, required=True)
            child.add_argument("--provider-job", required=True)
    progress = commands.add_parser("progress")
    progress.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan-format":
            result = {
                "version": 2,
                "complete": False,
                "inputs": [".dazedtl/len-method/work/source-units.json"],
                "batches": [
                    {
                        "id": "scene-01",
                        "sources": {"scene-01/line-1": "はい。"},
                        "speakers": {"scene-01/line-1": None},
                        "kinds": {"scene-01/line-1": "dialogue"},
                        "qa_notes": {},
                        "source_context": "",
                        "scene_context": "",
                        "constraints": {"scene-01/line-1": {"tokens": []}},
                    }
                ],
            }
        else:
            params = {"project_id": args.project}
            method = "translation_" + args.command.replace("-", "_")
            if args.command == "images":
                method = "images_state"
            if args.command == "plugins":
                method = (
                    "plugins_continue" if args.continue_request else "plugins_state"
                )
                if args.continue_request:
                    params["request_id"] = args.continue_request
            if hasattr(args, "run"):
                params["run_id"] = args.run
            if args.command in {"compile", "progress", "accept"}:
                params["input_path"] = args.input
            if args.command in {"accept", "review", "resolve-uncertain"}:
                params["batch_id"] = args.batch
            if args.command in {"review", "resolve-uncertain"}:
                params["request_sha256"] = args.request_sha256
            if args.command == "resolve-uncertain":
                params["retry_reviewed"] = args.retry_reviewed
            if args.command == "request":
                params["index"] = args.index
            if args.command == "stop":
                params["cancel_provider"] = args.cancel_provider
            if args.command == "start":
                params["approval_token"] = args.approve
            if args.command == "attach-batch":
                params.update(index=args.index, provider_job_id=args.provider_job)
            if args.command == "identify":
                params.update(engine=args.engine, evidence_file=args.evidence)
            if args.command == "event-text":
                method = "guided_event_text_request"
                params["apply"] = args.apply
            if args.command == "context":
                method = "guided_context_status"
            if args.command == "speakers":
                params["scan"] = args.scan
            if args.command == "legacy":
                params.update(
                    action=args.action, token=args.token, approved=args.approved
                )
            if args.command == "operation":
                params.update(
                    action=args.action,
                    arguments=json.loads(
                        args.arguments_file.read_text(encoding="utf-8")
                        if args.arguments_file
                        else args.arguments
                    ),
                )
            result = call(args.workspace, method, params)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if getattr(args, "output", None):
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
