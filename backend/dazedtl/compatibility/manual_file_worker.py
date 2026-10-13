"""Restore the same frozen policy in each native per-file worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    from dazedtl.compatibility.runtime import activate

    activate()
    from dazedtl.compatibility.worker_policy import install

    install()
    from desktop.backend.manual_environment import prepare
    from util.subprocess_runner import file_arguments, run_handler

    root, engine, filename, estimate = sys.argv[1:]
    filename = file_arguments(filename)
    prepare(root)
    run_handler(root, engine, filename, estimate.lower() == "true")
