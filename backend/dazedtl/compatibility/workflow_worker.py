"""Preserved workflow runner with app-owned tool installation paths."""

import json
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dazedtl.diagnostics import record_crashes, watch_action, worker_failure

try:
    action = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["action"]
except OSError, ValueError, KeyError, TypeError, IndexError:
    action = "unknown"  # The engine's worker reports the unreadable plan.
action = str(action)
record_crashes(action)
from dazedtl.stdio import private_stdin

# The stop command arrives on standard input while this action runs Git and
# other tools; they must not inherit that pipe.
sys.stdin = private_stdin()
from dazedtl.compatibility.runtime import activate

source = activate()
from desktop.backend import worker_failures, workflow_actions

from dazedtl.compatibility.guided import (
    apply_selected,
    publish_ace,
    run_ace,
    run_release,
)
from dazedtl.compatibility.translation import TranslationEngine, explained
from dazedtl.translation.guided_inputs import GuidedInputs

original = workflow_actions.run_action


def run_action(plan, log):
    # Every write to the game's text also packs an Ace game's native data.
    if plan["action"] == "fit_text":
        from dazedtl.compatibility.text import run_fit

        return publish_ace(plan, log, run_fit)
    if plan.get("publication"):
        from dazedtl.compatibility.text import run_publication

        return publish_ace(plan, log, run_publication)
    if plan["action"] in {"qa_prepare", "qa_status"}:
        from dazedtl.compatibility.text import run_qa

        return run_qa(plan, log)
    if plan["action"] == "release_playtest":
        from dazedtl.compatibility.playtest import run_playtest

        return run_playtest(plan, log)
    if plan["action"] == "playtest_fix":
        from dazedtl.compatibility.playtest import run_fixes

        return run_fixes(plan, log)
    if plan["action"] == "layout_capture":
        from dazedtl.compatibility.playtest import run_layout

        return run_layout(plan, log)
    if plan["action"] == "label_capture":
        from dazedtl.compatibility.playtest import run_labels

        return run_labels(plan, log)
    if plan["action"] in {
        "prepare_game",
        "format_data",
        "format_plugins",
        "gameupdate",
    }:
        from dazedtl.translation.preparation import run

        workflow_actions.validate_plan(plan)
        return run(plan, log, original, workflow_actions.action_guard)
    if plan["action"] == "speaker_scan":
        from dazedtl.compatibility.speaker_scan import run_scan

        return run_scan(plan, log)
    if plan["action"] == "full_estimate":
        from dazedtl.compatibility.full_estimate import run

        return run(plan, log)
    if plan["action"] == "release":
        return run_release(plan, log)
    if plan["action"] == "export_selected":
        return publish_ace(plan, log, apply_selected)
    if plan["action"] == "refresh_sources":
        workflow_actions.validate_plan(plan)
        engine = TranslationEngine(Path(plan["folder"]).parent.parent)
        project = plan["project"]
        inputs = GuidedInputs(
            plan["folder"],
            project["source"],
            project["data"],
            engine.source_bindings,
            engine.original_bytes,
            native_exports=project["engine"] == "ACE",
        )
        return inputs.prepare(
            plan["options"]["files"],
            refresh=True,
            expected=plan["options"]["sources"],
            retired=plan["options"]["retired"],
            progress=log,
        )
    return (
        run_ace(plan, log) if plan["action"].startswith("ace_") else original(plan, log)
    )


class Progress:
    """The worker's event stream; every event the action sends is progress."""

    def __init__(self, stream, progressed):
        self.stream = stream
        self.progressed = progressed

    def write(self, text):
        self.progressed()
        return self.stream.write(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def reported(native, error):
    # The action's finished event shows the error's message, which explains
    # only the errors that say what to fix.
    if not explained(error):
        worker_failure(error, action)
    native(error)


workflow_actions.run_action = run_action
worker_failures.reported.layer("dazedtl-diagnostics", reported)
# The worker keeps standard output as its event stream before redirecting it.
sys.stdout = Progress(sys.stdout, watch_action(action))
runpy.run_path(str(source / "desktop/backend/workflow_worker.py"), run_name="__main__")
