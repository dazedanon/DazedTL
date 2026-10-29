"""Estimate every Guided translation task's API cost in one local operation.

Each task's requests are built by the same isolated engine worker a Translate
estimate starts, from every file of the task rather than its selection. The
worker runs without a credential or network; a Claude estimate is then priced
again with Claude's own free token count, as a Batch review prices it.
"""

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from pathlib import Path

from dazedtl import system
from dazedtl.actions import stopped_note
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest, project_path

from .estimate_pricing import count, start, stop
from .manual import stage_originals

LABELS = {
    "database": "Database files",
    "dialogue": "Maps & events",
    "advanced": "Other event text",
}
WORKER = Path(__file__).with_name("manual_worker.py")
ENGINE = "RPG Maker MV/MZ"


class Activity:
    """Where each task stands, reported as the operation's activity with
    every status line: tasks with files, each waiting, starting its worker,
    estimating its files, priced by Claude's count, or done with the seconds
    it took. Tasks may report from their own threads."""

    def __init__(self, log, tasks):
        self.log = log
        self.stopped = log.stopped
        self.lock = threading.Lock()
        self.copying = True
        self.began = {}
        self.tasks = {
            task["phase"]: {
                "phase": task["phase"],
                "state": "waiting",
                "current": 0,
                "total": len(task["files"]),
                "took": None,
            }
            for task in tasks
            if task["files"]
        }

    def __call__(self, message, phase=None, **changes):
        with self.lock:
            if phase:
                task = self.tasks[phase]
                if changes.get("state") == "starting":
                    self.began[phase] = time.monotonic()
                elif changes.get("state") == "done":
                    changes["took"] = round(time.monotonic() - self.began[phase], 1)
                task.update(changes)
            self.log(
                message,
                {
                    "copying": self.copying,
                    "tasks": [dict(task) for task in self.tasks.values()],
                },
            )

    def copied(self):
        with self.lock:
            self.copying = False


def run(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util.provider_costs import PRICE_RULES_VERSION

    validate_plan(plan)
    folder = Path(plan["folder"])
    options = plan["options"]
    report = Activity(log, options["tasks"])
    with system.staging_folder(folder, "full-estimate-") as root:
        report("Copying the game's current text")
        inventory = stage(root / "source", folder, plan["project"], options["files"])
        report.copied()
        # Each task has its own worker processes, so they run side by side;
        # the first that fails stops the others.
        failed = threading.Event()
        report.stopped = lambda: log.stopped() or failed.is_set()

        def estimate(task):
            if not task["files"]:
                return row(task, {}), None
            try:
                value = estimate_task(
                    root / task["phase"], folder, plan, inventory, task, report
                )
            except BaseException:
                failed.set()
                raise
            report(f"{LABELS[task['phase']]} · estimated", task["phase"], state="done")
            return row(task, value), measured(value)

        with ThreadPoolExecutor(max_workers=len(options["tasks"]) or 1) as pool:
            futures = [pool.submit(estimate, task) for task in options["tasks"]]
            wait(futures, return_when=FIRST_EXCEPTION)
            if failed.is_set():
                wait(futures)
                for future in futures:
                    error = future.exception()
                    if error is not None and not isinstance(error, InterruptedError):
                        raise error
            rows = [future.result() for future in futures]
    return {
        "fingerprint": options["fingerprint"],
        "shape": options["shape"],
        "configuration": options["configuration"],
        "model": options["model"],
        "batchSupported": options["batchSupported"],
        # The rules its prices follow (translation/repricing).
        "price_rules": PRICE_RULES_VERSION,
        "tasks": [line for line, _counts in rows],
        # What pricing the tasks again needs (FullEstimate.priced).
        "measured": {
            line["phase"]: counts for line, counts in rows if counts is not None
        },
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
    phase = task["phase"]
    log(f"{label} · preparing", phase, state="starting")
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
    stage_originals(directory, native, policy)
    write_json(directory / "plan.json", native)
    # The staged copy is this operation's own, so every task shares its files.
    prepare_inputs(directory, native, log.stopped, link=True)
    write_json(
        directory / "attempt.json",
        {"files": task["files"], "resume": False, "batch_resume_state": None},
    )
    # Claude's count starts with the estimate, so its startup overlaps it.
    counting = (
        start(directory, workspace, native) if plan["options"]["claudeCount"] else None
    )
    try:
        estimate = launch(
            directory, worker_environment(workspace, native), label, phase, log
        )
        if (
            counting is not None
            and estimate.get("provider") == "anthropic"
            and estimate.get("approximate_input")
        ):
            log(f"{label} · counting Claude tokens", phase, state="counting")
            estimate = count(
                directory, workspace, native, estimate, log.stopped, process=counting
            )
    finally:
        stop(counting)
    return estimate


def launch(directory, env, label, phase, log):
    """Runs the engine's estimate worker and returns its estimate."""
    with (directory / "log/startup.txt").open("a", encoding="utf-8") as errors:
        process = system.popen(
            [sys.executable, "-u", str(WORKER), str(directory)],
            cwd=directory,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            bufsize=1,
            group=True,
        )
        estimate = failure = None
        shown = 0.0
        try:
            assert process.stdout is not None  # Opened above.
            for line in process.stdout:
                if log.stopped():
                    raise InterruptedError(stopped_note("full_estimate"))
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind, args = event.get("event"), event.get("args") or []
                if kind == "progress" and len(args) >= 2:
                    # A progress line per file would rewrite the operation
                    # record hundreds of times a minute.
                    if time.monotonic() - shown >= 0.5 or args[0] == args[1]:
                        log(
                            f"{label} · {args[0]:,} of {args[1]:,} files",
                            phase,
                            state="estimating",
                            current=args[0],
                            total=args[1],
                        )
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


def number(estimate, key):
    value = estimate.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def row(task, estimate):
    """One task's line in the saved result."""
    return {
        "phase": task["phase"],
        "files": len(task["files"]),
        "noSources": bool(task.get("noSources")),
        "requests": int(number(estimate, "requests")),
        "inputTokens": int(number(estimate, "input_tokens")),
        "outputTokens": int(number(estimate, "output_tokens")),
        "approximateInput": bool(estimate.get("approximate_input")),
        **prices(estimate),
    }


def prices(estimate):
    """A task line's prices, from its estimate."""
    from util.provider_costs import shown_batch_price

    batch = number(estimate, shown_batch_price(estimate))
    return {
        "promptCache": bool(estimate.get("uses_prompt_cache")),
        "liveCost": number(estimate, "live_cost"),
        "batchCost": batch,
        "batchMaxCost": max(batch, number(estimate, "batch_max_cost")),
        "unestimatedThinking": bool(estimate.get("unestimated_thinking_tokens")),
    }


# The counts an estimate keeps beside a task's line, which its prices come from.
MEASURED = (
    "provider",
    "requests",
    "input_tokens",
    "output_tokens",
    "uses_prompt_cache",
    "cache_read_tokens",
    "cacheable_tokens",
    "dynamic_tokens",
)


def measured(estimate):
    return {key: estimate[key] for key in MEASURED if key in estimate}
