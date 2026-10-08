"""Preserved workflow runner with app-owned tool installation paths."""

import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dazedtl.stdio import private_stdin

# The stop command arrives on standard input while this action runs Git and
# other tools; they must not inherit that pipe.
sys.stdin = private_stdin()
from dazedtl.compatibility.runtime import activate

source = activate()
from desktop.backend import workflow_actions

from dazedtl.compatibility.guided import apply_selected, run_ace, run_release
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.translation.guided_inputs import GuidedInputs

original = workflow_actions.run_action


def run_action(plan, log):
    if plan.get("publication"):
        from dazedtl.compatibility.text import run_publication

        return run_publication(plan, log)
    if plan["action"] in {"qa_prepare", "qa_status"}:
        from dazedtl.compatibility.text import run_qa

        return run_qa(plan, log)
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
    if plan["action"] == "release":
        return run_release(plan, log)
    if plan["action"] == "export_selected":
        return apply_selected(plan, log)
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


workflow_actions.run_action = run_action
runpy.run_path(str(source / "desktop/backend/workflow_worker.py"), run_name="__main__")
