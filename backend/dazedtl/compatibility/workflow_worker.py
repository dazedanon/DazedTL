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
from dazedtl.compatibility.guided import run_ace

original = workflow_actions.run_action
workflow_actions.run_action = lambda plan, log: run_ace(plan, log) if plan["action"].startswith("ace_") else original(plan, log)
runpy.run_path(str(source / "desktop/backend/workflow_worker.py"), run_name="__main__")
