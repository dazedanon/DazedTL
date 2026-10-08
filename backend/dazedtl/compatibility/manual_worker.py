"""Run the native job protocol using the application's frozen model policy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    from dazedtl.stdio import private_stdin

    # Stop and approval commands arrive on standard input while the per-file
    # workers start; they must not inherit that pipe.
    sys.stdin = private_stdin()
    from dazedtl.compatibility.runtime import activate

    activate()
    from desktop.backend import manual_worker

    from dazedtl.compatibility.worker_policy import install

    install(coordinator=True)
    # Native main resolves its per-file runner beside __file__. ROOT remains the
    # original engine root; redirect only that child entrypoint to our wrapper.
    manual_worker.__file__ = __file__
    raise SystemExit(manual_worker.main())
