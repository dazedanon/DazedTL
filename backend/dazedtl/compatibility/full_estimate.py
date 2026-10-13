"""Estimate every Guided translation task's API cost in one local operation.

Each task's requests are built by the same isolated engine worker a Translate
estimate starts, from every file of the task rather than its selection. The
worker runs without a credential or network; a Claude estimate is then priced
again with Claude's own free token count, as a Batch review prices it.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest, project_path

from .estimate_pricing import count

LABELS = {
    "database": "Database files",
    "dialogue": "Maps & events",
    "advanced": "Other event text",
}
WORKER = Path(__file__).with_name("manual_worker.py")
ENGINE = "RPG Maker MV/MZ"


def run(plan, log):
    from desktop.backend.workflow_actions import validate_plan

    validate_plan(plan)
    folder = Path(plan["folder"])
    options = plan["options"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="full-estimate-", dir=folder) as temporary:
        root = Path(temporary)
        log("Copying the game's current text")
        inventory = stage(root / "source", folder, plan["project"], options["files"])
        for task in options["tasks"]:
            if not task["files"]:
                rows.append(row(task, {}))
                continue
            estimate = estimate_task(
                root / task["phase"], folder, plan, inventory, task, log
            )
            rows.append(row(task, estimate))
    return {
        "fingerprint": options["fingerprint"],
        "model": options["model"],
        "batchSupported": options["batchSupported"],
        "tasks": rows,
    }


def stage(target, folder, project, files):
    """Each file as a Translate run would start from it: its saved
    translation, else its working copy, else the game's own file."""
    rows = []
    for name, relative in sorted(files.items()):
        raw = None
        for group in ("translated", "files"):
            path = folder / group / name
            if path.is_file() and not path.is_symlink():
                raw = path.read_bytes()
                break
        if raw is None:
            raw = project_path(project["source"], relative).read_bytes()
        write_bytes(target / name, raw)
        rows.append({"name": name, "bytes": len(raw), "sha256": digest(raw)})
    return {
        "source": str(target),
        "engine": ENGINE,
        "files": rows,
        "revision": digest(rows),
    }


def estimate_task(directory, folder, plan, inventory, task, log):
    from desktop.backend.manual import (
        prepare_inputs,
        run_plan,
        seed_variables,
        snapshot_context,
        worker_environment,
    )

    workspace = folder.parent.parent
    label = LABELS[task["phase"]]
    log(f"{label} · preparing")
    directory.mkdir()
    native = run_plan(
        workspace,
        inventory,
        task["files"],
        "estimate",
        plan["project"]["source"],
        workflow=task["workflow"],
    )
    snapshot_context(directory, native, workspace)
    seed_variables(directory, native, folder)
    policy = plan["options"]["policy"]
    if policy is not None:
        if policy["model"] != native["settings"]["model"]:
            raise ValueError("The selected model changed. Estimate again.")
        native["dazedtl_request_policy"] = policy
    write_json(directory / "plan.json", native)
    # The staged copy is this operation's own, so every task shares its files.
    prepare_inputs(directory, native, log.stopped, link=True)
    write_json(
        directory / "attempt.json",
        {"files": task["files"], "resume": False, "batch_resume_state": None},
    )
    estimate = launch(directory, worker_environment(workspace, native), label, log)
    if (
        plan["options"]["claudeCount"]
        and estimate.get("provider") == "anthropic"
        and estimate.get("approximate_input")
    ):
        log(f"{label} · counting Claude tokens")
        estimate = count(directory, workspace, native, estimate, log.stopped)
    return estimate


def launch(directory, env, label, log):
    """Runs the engine's estimate worker and returns its estimate."""
    with (directory / "log/startup.txt").open("a", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [sys.executable, "-u", str(WORKER), str(directory)],
            cwd=directory,
            env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=os.name != "nt",
        )
        estimate = failure = None
        shown = 0.0
        try:
            assert process.stdout is not None  # Opened above.
            for line in process.stdout:
                if log.stopped():
                    raise InterruptedError("Stopped. No cost was estimated.")
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind, args = event.get("event"), event.get("args") or []
                if kind == "progress" and len(args) >= 2:
                    # A progress line per file would rewrite the operation
                    # record hundreds of times a minute.
                    if time.monotonic() - shown >= 0.5 or args[0] == args[1]:
                        log(f"{label} · {args[0]:,} of {args[1]:,} files")
                        shown = time.monotonic()
                elif kind == "estimate_ready" and args:
                    estimate = args[0]
                elif kind == "file_error" and len(args) >= 2 and failure is None:
                    failure = f"{args[0]}: {args[1]}"
                elif kind == "finished" and args and args[0] is not True:
                    raise ValueError(f"{label}: {failure or args[1]}")
            process.wait()
        finally:
            end(process)
    if not isinstance(estimate, dict):
        raise ValueError(f"{label} could not be estimated. Try again.")
    return estimate


def end(process):
    if process.poll() is not None:
        return
    try:
        assert process.stdin is not None  # Opened by launch.
        process.stdin.write(json.dumps({"command": "stop"}) + "\n")
        process.stdin.flush()
    except OSError:
        pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def row(task, estimate):
    """One task's line in the saved result."""

    def number(key):
        value = estimate.get(key)
        return float(value) if isinstance(value, (int, float)) else 0.0

    cached = bool(estimate.get("uses_prompt_cache"))
    return {
        "phase": task["phase"],
        "files": len(task["files"]),
        "noSources": bool(task.get("noSources")),
        "requests": int(number("requests")),
        "inputTokens": int(number("input_tokens")),
        "outputTokens": int(number("output_tokens")),
        "liveCost": number("live_cost"),
        "batchCost": number("batch_cached_cost" if cached else "batch_nocache_cost"),
        "batchNocacheCost": number("batch_nocache_cost"),
        "promptCache": cached,
        "approximateInput": bool(estimate.get("approximate_input")),
        "unestimatedThinking": bool(estimate.get("unestimated_thinking_tokens")),
    }
