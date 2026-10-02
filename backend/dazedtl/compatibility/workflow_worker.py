"""Preserved workflow runner with app-owned tool installation paths."""

import os
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
source = Path(os.environ["DAZEDTL_ENGINE_SOURCE"])
sys.path.insert(0, str(source))
from desktop.backend import workflow_actions
from dazedtl.compatibility.guided import run_ace, apply_selected, run_release
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.translation.guided_inputs import GuidedInputs

original = workflow_actions.run_action
def run_action(plan, log):
    if plan["action"] == "speaker_scan":
        from dazedtl.compatibility.speaker_scan import run_scan
        return run_scan(plan, log)
    if plan["action"] == "release":
        return run_release(plan, log)
    if plan["action"] == "export_selected":
        return apply_selected(plan, log)
    if plan["action"] == "refresh_sources":
        workflow_actions.validate_plan(plan)
        engine = TranslationEngine(source, Path(plan["folder"]).parent.parent)
        project = plan["project"]
        inputs = GuidedInputs(plan["folder"], project["source"], project["data"], engine.source_bindings, engine.original_bytes,
                              native_exports=project["engine"] == "ACE")
        return inputs.prepare(plan["options"]["files"], refresh=True,
                              expected=plan["options"]["sources"], retired=plan["options"]["retired"], progress=log)
    return run_ace(plan, log) if plan["action"].startswith("ace_") else original(plan, log)
workflow_actions.run_action = run_action
runpy.run_path(str(source / "desktop/backend/workflow_worker.py"), run_name="__main__")
