"""Run the native job protocol using the application's frozen model policy."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ["DAZEDTL_ENGINE_SOURCE"])

if __name__ == "__main__":
    from dazedtl.compatibility.worker_policy import install
    from desktop.backend import manual_worker

    install()
    # Native main resolves its per-file runner beside __file__. ROOT remains the
    # original engine root; redirect only that child entrypoint to our wrapper.
    manual_worker.__file__ = __file__
    raise SystemExit(manual_worker.main())
