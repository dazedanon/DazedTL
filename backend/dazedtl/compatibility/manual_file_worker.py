"""Restore the same frozen policy in each native per-file worker."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ["DAZEDTL_ENGINE_SOURCE"])

if __name__ == "__main__":
    from dazedtl.compatibility.worker_policy import install

    install()
    from desktop.backend.manual_environment import prepare
    from util.subprocess_runner import run_handler

    root, engine, filename, estimate = sys.argv[1:]
    if filename == "--files-from-stdin":
        filename = json.load(sys.stdin)
    prepare(root)
    run_handler(root, engine, filename, estimate.lower() == "true")
