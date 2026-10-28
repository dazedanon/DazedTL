#!/usr/bin/env python3
"""Operate one DazedTL project through the running app; no credentials are exported."""

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dazedtl.translation.organize import EXAMPLE as UNITS_EXAMPLE
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


def wait(workspace, params, run, minutes):
    """Checks a run until its state changes or the time is up, so an assistant
    waits in one command instead of polling turn by turn, including while an
    estimate waits for the user's approval in DazedTL. An Assistant only run
    waits while another model translates the lines it declined."""
    deadline = time.monotonic() + minutes * 60

    def state(run):
        return run["status"], run.get("declined_units", 0)

    started = state(run)
    # Most operations finish in seconds; long runs settle to one check
    # every 15 seconds.
    pause = 1
    while state(run) == started and (
        run["status"] in {"ready", "running", "waiting"} or run.get("declined_units", 0)
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(pause, remaining))
        pause = min(pause * 2, 15)
        run = call(workspace, "translation_run", params)
    return run


def prepared(workspace, project_id, operation):
    """Waits while DazedTL compiles the run organize or compile started, then
    replies with the run, and organize's counts, as soon as it is saved; a
    refusal fails the command."""
    params = {"project_id": project_id, "run_id": operation["id"]}
    # A check costs the app next to nothing, so the reply follows the run.
    pause = 0.25
    while operation["status"] in {"ready", "running", "waiting"}:
        time.sleep(pause)
        pause = min(pause * 2, 1)
        operation = call(workspace, "translation_run", params)
    if operation["status"] != "complete":
        raise ValueError(operation["message"])
    result = operation["result"]
    run = call(workspace, "translation_run", {**params, "run_id": result["run"]})
    return {"run": run, "summary": result["summary"]} if "summary" in result else run


def awaiting_answers(workspace, params, minutes):
    """Waits while open QA questions wait for the user's answers in the app."""
    deadline = time.monotonic() + minutes * 60
    pause = 2
    status = {"project_id": params["project_id"], "step": "status"}
    while call(workspace, "translation_qa", status)["questions"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(pause, remaining))
        pause = min(pause * 2, 15)


def settle_qa(workspace, params, result):
    """Waits for the QA step the app started; an apply, undo or apply again
    is its own checkpoint."""

    def finish(result):
        while (result.get("operation") or {}).get("status") == "running":
            time.sleep(2)
            result = call(workspace, "translation_qa", {**params, "step": "status"})
        return result

    if params["step"] not in {"prepare", "apply", "undo", "reapply"}:
        return result
    result = finish(result)
    if (result.get("operation") or {}).get("status") != "complete":
        raise ValueError(
            "The QA step did not finish: "
            + json.dumps(result.get("operation"), ensure_ascii=False)
        )
    return result


def wait_playtest(workspace, params, result, minutes):
    """Waits while the playtest plays, then returns its status with the
    report file."""
    deadline = time.monotonic() + minutes * 60
    status = {"project_id": params["project_id"], "step": "report"}

    def settle(result):
        while "running" in {
            (result.get("operation") or {}).get("status"),
            ((result.get("layout") or {}).get("operation") or {}).get("status"),
        }:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result, False
            time.sleep(min(10, remaining))
            result = call(workspace, "translation_playtest", status)
        return result, True

    result, settled = settle(result)
    return call(workspace, "translation_playtest", status) if settled else result


def wait_capture(workspace, params, result, minutes):
    """Waits while the game shows the shortened labels, then returns how each
    one shows on its screen."""
    deadline = time.monotonic() + minutes * 60
    status = {"project_id": params["project_id"]}
    while (result.get("operation") or {}).get("status") == "running":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(5, remaining))
        result = call(workspace, "plugins_capture", status)
    return result


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
    images = commands.add_parser(
        "images",
        help="Read the selected project's indexed images, scoped handoffs and saved reports; "
        "an Assistant-led project's assistant runs its Images steps with one flag",
    )
    image_step = images.add_mutually_exclusive_group()
    for step, text in (
        ("status", "Where the Images steps stand and which comes next"),
        ("scan", "Index the game's images and wait for the scan to finish"),
        (
            "investigate",
            "Save the task that finds images with text, as a file to follow",
        ),
        (
            "translate",
            "Make editable copies of the listed images and save the task that translates them",
        ),
        ("apply", "Put the translated, reviewed images into the game"),
    ):
        image_step.add_argument(
            "--" + step,
            dest="image_step",
            action="store_const",
            const=step,
            help=text,
        )
    images.add_argument(
        "--root",
        metavar="FOLDER",
        help="With --scan: the game-relative folder you decoded the game's image archives into, "
        "which the Images steps then read and write",
    )
    qa = commands.add_parser(
        "qa",
        help="Text QA for RPG Maker games: where it stands, preparing its task, and "
        "applying finished findings through DazedTL, each its own checkpoint; for "
        "other engines, --check runs its text-only rules over your translations",
    )
    qa_step = qa.add_mutually_exclusive_group()
    for step, text in (
        ("status", "Where QA stands and which step comes next"),
        ("report", "Where QA stands, with the saved findings file"),
        ("prepare", "Prepare or resume the QA task and wait for it"),
        (
            "apply",
            (
                "Apply every finished finding and each proposal the user chose as "
                "one reviewed text batch"
            ),
        ),
        (
            "checkpoint",
            (
                "Kept for older runs: each apply, undo or apply again is "
                "already its own checkpoint"
            ),
        ),
    ):
        qa_step.add_argument(
            "--" + step, dest="qa_step", action="store_const", const=step, help=text
        )
    qa_step.add_argument(
        "--check",
        action="store_true",
        help="For engines other than RPG Maker MV/MZ and VX Ace: check the exported "
        "translations with Text QA's text-only rules, list each hit in the work "
        "folder and print the counts",
    )
    qa_step.add_argument(
        "--undo",
        nargs="+",
        metavar="FINDING",
        help="Put back the lines of these applied corrections",
    )
    qa_step.add_argument(
        "--apply-again",
        nargs="+",
        metavar="FINDING",
        help="Apply these undone corrections again",
    )
    qa_step.add_argument(
        "--choose",
        nargs=2,
        metavar=("QUESTION", "CHOICE"),
        help="Record the user's answer to an open question: keep or use",
    )
    qa.add_argument(
        "--wait",
        type=float,
        default=0,
        metavar="MINUTES",
        help="With --apply: wait up to MINUTES for the user's answers to open questions",
    )
    qa.add_argument(
        "--answers",
        type=Path,
        metavar="FILE",
        help="With --check: a JSON object of hit ID to a one-line reason the line is right",
    )
    qa.add_argument(
        "--since",
        metavar="VERSION",
        help=(
            "With --prepare: the text was checked before as of this version's update "
            "(or Git revision), so QA reviews only text changed since; it stays in "
            "effect for later QA of this game"
        ),
    )
    qa.add_argument(
        "--everything",
        action="store_true",
        help="With --prepare: review every line again, ignoring earlier reviews",
    )
    playtest = commands.add_parser(
        "playtest",
        help="The release playtest for RPG Maker MV/MZ: DazedTL checks the game's files and "
        "plays it in a hidden window, then reports crashes, Japanese on screen, text "
        "that doesn't fit and lost names or codes; only --fix writes into the game",
    )
    playtest_step = playtest.add_mutually_exclusive_group()
    playtest_step.add_argument(
        "--run", action="store_true", help="Play the game and write a new report"
    )
    playtest_step.add_argument(
        "--report", action="store_true", help="Where it stands, with the report file"
    )
    playtest_step.add_argument(
        "--fix",
        action="store_true",
        help="Play the game with the fixes file the status names in place of the game's "
        "fixes plugin, and write it into the game once nothing new breaks and something "
        "the last playtest found is gone, as a checkpoint of its own; History restores "
        "it in Guided",
    )
    playtest_step.add_argument(
        "--checkpoint",
        action="store_true",
        help="Kept for older runs: the fixes are already a checkpoint of their own",
    )
    playtest_step.add_argument(
        "--layout",
        type=Path,
        metavar="WIDTHS",
        help="Show English at the widths in a JSON file, such as "
        '{"width": 55, "faceWidth": 50, "listWidth": 70, "messageRows": 4}, in the '
        "game's message and help windows, and capture each; it keeps its own report",
    )
    playtest.add_argument(
        "--stops",
        type=Path,
        help="With --run: a JSON file of places to visit after the standard tour, each "
        '{"title": ..., "do": "map"|"event"|"common-event"|"battle"|"scene"|"script", ...}; '
        "they replace the saved stops, which every later run visits, and [] clears them",
    )
    playtest.add_argument(
        "--wait",
        type=float,
        default=0,
        metavar="MINUTES",
        help="Wait up to MINUTES for a running playtest to finish",
    )
    plugins = commands.add_parser(
        "plugins",
        help="Read plugin work or continue the copied agent task after saving its report",
    )
    plugins_step = plugins.add_mutually_exclusive_group()
    plugins_step.add_argument(
        "--continue-request",
        help="Exact active request ID; checks the report and returns the next stage without publishing game files",
    )
    plugins_step.add_argument(
        "--task",
        action="store_true",
        help="Start or resume what is left of the Plugin files task and print its "
        "instructions, or say nothing is; the final check uses it for plugin text the "
        "playtest saw",
    )
    plugins_step.add_argument(
        "--apply",
        action="store_true",
        help="Apply the checked plugin files to the game, as the app's Apply to game does",
    )
    plugins_step.add_argument(
        "--capture",
        action="store_true",
        help="Play the game with the shortening request's working copies served in place "
        "of its files and capture each label's screen again; it writes nothing into the game",
    )
    plugins.add_argument(
        "--wait",
        type=float,
        default=0,
        metavar="MINUTES",
        help="With --capture: wait up to MINUTES for the capture to finish",
    )
    commands.add_parser("prepare")
    commands.add_parser(
        "backups", help="List local restore points and older profile backups"
    )
    commands.add_parser(
        "word-spacing",
        help="Print how to join a translation's words in RPG Maker plugin commands and note tags, and whether this game's font draws U+00A0",
    )
    speakers = commands.add_parser(
        "speakers",
        help="Read speaker discovery results; --scan applies evidenced rules and runs the local parser without API calls",
    )
    speakers.add_argument("--scan", action="store_true")
    speakers.add_argument(
        "--fix-headers",
        action="store_true",
        help="Apply your review of the scan's likely header slips from .dazedtl/guided/header-review.json",
    )
    event_text = commands.add_parser(
        "event-text",
        help="Read the current Other event text investigation request and validated findings; --apply saves their recommendations as source choices",
    )
    event_text.add_argument("--apply", action="store_true")
    commands.add_parser(
        "context",
        help="Read verified context investigation results and current document revisions",
    )
    census_command = commands.add_parser(
        "census",
        help="Count the game's Japanese text from its original files, as the coverage organize --complete checks; inspect the returned run with run --wait",
    )
    census_command.add_argument(
        "--decoded",
        help="Game-relative folder your decoder wrote, for containers the census can't open",
    )
    commands.add_parser(
        "units-format",
        help="Print an example of the source units file organize reads",
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
    # Answering declines a pending approval; only the user approves, in DazedTL.
    legacy.add_argument("--token", default="")
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
    organize = commands.add_parser(
        "organize",
        help="Group the extracted source units into requests and compile the run, which can take a few minutes on a big game; replies with counts only",
    )
    organize.add_argument("--input", required=True)
    organize.add_argument(
        "--complete",
        action="store_true",
        help="Only after auditing that the units cover every line in scope",
    )
    for name in (
        "run",
        "stop",
        "start",
        "request",
        "results",
        "accept",
        "decline",
        "review",
        "attach-batch",
        "resolve-uncertain",
    ):
        child = commands.add_parser(
            name,
            help={
                "start": "Resume a run the user approved in DazedTL",
                "results": "Write the run's accepted translations by line ID to a file for injection; replies with counts only",
                "decline": "Assistant only: set aside a request you won't translate so another model can finish it",
            }.get(name),
        )
        child.add_argument("--run", required=True)
        if name == "run":
            child.add_argument(
                "--wait",
                type=float,
                default=0,
                metavar="MINUTES",
                help="Wait up to MINUTES while the run keeps its state; returns as soon as it finishes or changes state",
            )
        if name == "stop":
            child.add_argument(
                "--cancel-provider",
                action="store_true",
                help="Request provider cancellation and retain completed results",
            )
        if name == "request":
            chosen = child.add_mutually_exclusive_group(required=True)
            chosen.add_argument("--index", type=int)
            chosen.add_argument(
                "--request-sha256",
                help="A request of this run, or an earlier one whose lines organize kept for it, as its progress export row names it",
            )
            child.add_argument("--output", type=Path)
        if name in {"accept", "decline", "review", "resolve-uncertain"}:
            child.add_argument("--batch", required=True)
        if name == "decline":
            child.add_argument(
                "--reason",
                required=True,
                help="One line, at most 300 characters, without game text",
            )
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
        if args.command == "units-format":
            result = UNITS_EXAMPLE
        elif args.command == "plan-format":
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
                if args.root and args.image_step != "scan":
                    parser.error("--root goes with --scan")
                if args.image_step:
                    method = "translation_images"
                    params["step"] = args.image_step
                if args.root:
                    params["root"] = args.root
            if args.command == "qa" and args.answers and not args.check:
                parser.error("--answers goes with --check")
            if args.command == "qa" and args.check:
                method = "translation_qa_check"
                if args.since or args.everything or args.wait:
                    parser.error(
                        "--since, --everything and --wait don't go with --check"
                    )
                if args.answers:
                    params["answers"] = json.loads(
                        args.answers.read_text(encoding="utf-8-sig")
                    )
            elif args.command == "qa":
                params["step"] = (
                    "undo"
                    if args.undo
                    else "reapply"
                    if args.apply_again
                    else "choose"
                    if args.choose
                    else args.qa_step or "status"
                )
                if args.undo or args.apply_again:
                    params["findings"] = args.undo or args.apply_again
                if args.choose:
                    params.update(question=args.choose[0], choice=args.choose[1])
                if (args.since or args.everything) and params["step"] != "prepare":
                    parser.error("--since and --everything go with --prepare")
                if args.since:
                    params["since"] = args.since
                if args.everything:
                    params["everything"] = True
                if params["step"] == "apply" and args.wait > 0:
                    awaiting_answers(args.workspace, params, args.wait)
            if args.command == "playtest":
                params["step"] = (
                    "run"
                    if args.run
                    else "fix"
                    if args.fix
                    else "checkpoint"
                    if args.checkpoint
                    else "report"
                    if args.report
                    else "layout"
                    if args.layout
                    else "status"
                )
                if args.layout:
                    params["widths"] = json.loads(
                        args.layout.read_text(encoding="utf-8-sig")
                    )
                if args.stops:
                    params["stops"] = json.loads(
                        args.stops.read_text(encoding="utf-8-sig")
                    )
            if args.command == "plugins":
                method = (
                    "plugins_continue"
                    if args.continue_request
                    else "plugins_capture"
                    if args.capture
                    else "plugins_task"
                    if args.task
                    else "plugins_apply"
                    if args.apply
                    else "plugins_state"
                )
                if args.continue_request:
                    params["request_id"] = args.continue_request
                if args.capture:
                    params["start"] = True
            # A run's ID; the playtest's --run is a flag instead.
            if isinstance(getattr(args, "run", None), str):
                params["run_id"] = args.run
            if args.command in {"compile", "organize", "progress", "accept"}:
                params["input_path"] = args.input
            if args.command == "organize":
                params["complete"] = args.complete
            if args.command in {"accept", "decline", "review", "resolve-uncertain"}:
                params["batch_id"] = args.batch
            if args.command == "decline":
                params["reason"] = args.reason
            if args.command in {"review", "resolve-uncertain"}:
                params["request_sha256"] = args.request_sha256
            if args.command == "resolve-uncertain":
                params["retry_reviewed"] = args.retry_reviewed
            if args.command == "request":
                if args.index is None:
                    params["request_sha256"] = args.request_sha256
                else:
                    params["index"] = args.index
            if args.command == "stop":
                params["cancel_provider"] = args.cancel_provider
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
                if args.fix_headers:
                    params["fix_headers"] = True
            if args.command == "legacy":
                params.update(action=args.action, token=args.token, approved=False)
            if args.command == "census":
                method = "translation_operation"
                params.update(
                    action="census",
                    arguments={"decoded": args.decoded} if args.decoded else {},
                )
            if args.command == "operation":
                params.update(
                    action=args.action,
                    arguments=json.loads(
                        args.arguments_file.read_text(encoding="utf-8-sig")
                        if args.arguments_file
                        else args.arguments
                    ),
                )
            result = call(args.workspace, method, params)
            if args.command in {"compile", "organize"}:
                result = prepared(args.workspace, args.project, result)
            if args.command == "run" and args.wait > 0:
                result = wait(args.workspace, params, result, args.wait)
            if args.command == "qa" and not args.check:
                result = settle_qa(args.workspace, params, result)
            if args.command == "playtest" and args.wait > 0:
                result = wait_playtest(args.workspace, params, result, args.wait)
            if args.command == "plugins" and args.capture and args.wait > 0:
                result = wait_capture(args.workspace, params, result, args.wait)
            if getattr(args, "image_step", None) == "scan":
                while result["scan"] == "running":
                    time.sleep(2)
                    result = call(
                        args.workspace,
                        method,
                        {"project_id": args.project, "step": "status"},
                    )
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
