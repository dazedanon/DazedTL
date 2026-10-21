"""Run one guided action with independent imports, cwd and cancellation."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROTOCOL = sys.stdout


def main():
    from util import system

    plan = json.loads(system.read_bytes(sys.argv[1]))
    canceled = threading.Event()
    def commands():
        for _line in sys.stdin:
            canceled.set()
        canceled.set()
    threading.Thread(target=commands, daemon=True).start()
    def emit(event, **values):
        PROTOCOL.write(json.dumps({"event": event, **values}, ensure_ascii=False) + "\n")
        PROTOCOL.flush()
    def log(message, activity=None):
        """Reports a status line, and optionally where the action stands as
        structured `activity` of its own shape, which the next line replaces."""
        if canceled.is_set():
            raise InterruptedError("Stopped at a safe boundary. Completed writes were retained; review the destination before retrying.")
        emit("log", message=str(message), activity=activity)
    log.stopped = canceled.is_set
    sys.stdout = sys.stderr
    try:
        from desktop.backend.workflow_actions import run_action, json_value
        if plan.get("kind") == "len":
            from desktop.backend.len_method import run_action
        elif plan.get("kind") == "version":
            from desktop.backend.version_update import run_action
        elif plan.get("kind") == "assets":
            from desktop.backend.assets import run_action
        elif plan.get("kind") == "batch":
            from desktop.backend.batches import run_action
        elif plan.get("kind") == "evaluation":
            from desktop.backend.evaluations import run_action
        result = run_action(plan, log)
        emit("finished", status="failed" if isinstance(result, dict) and result.get("ok") is False else "complete",
             message=result.get("message") or "Completed: " + plan["label"] if isinstance(result, dict) else "Completed: " + plan["label"], result=json_value(result))
    except Exception as exc:
        from desktop.backend.worker_failures import reported
        reported(exc)
        emit("finished", status="stopped" if isinstance(exc, InterruptedError) else "failed", message=str(exc))
    finally:
        sys.stdout = PROTOCOL


if __name__ == "__main__":
    main()
