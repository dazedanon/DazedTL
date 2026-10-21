"""Run the native job protocol using the application's frozen model policy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run_action(arguments):
    """The action a run's workers record their failures under, read from the
    run folder named first in their arguments."""
    import json

    try:
        mode = json.loads((Path(arguments[1]) / "plan.json").read_bytes())["mode"]
    except OSError, ValueError, KeyError, TypeError, IndexError:
        mode = "unknown"  # The engine's worker reports the unreadable plan.
    return "manual_" + str(mode)


if __name__ == "__main__":
    from dazedtl.diagnostics import record_crashes, worker_failure

    action = run_action(sys.argv)
    record_crashes(action)
    from dazedtl.system import private_stdin

    # Stop and approval commands arrive on standard input while the per-file
    # workers start; they must not inherit that pipe.
    sys.stdin = private_stdin()
    from dazedtl.compatibility.runtime import activate

    activate()
    from desktop.backend import manual_worker, worker_failures

    from dazedtl.compatibility.worker_policy import install

    def reported(native, error):
        # The run shows every failure as a generic message.
        worker_failure(error, action)
        native(error)

    worker_failures.reported.layer("dazedtl-diagnostics", reported)

    install(coordinator=True)
    # Native main resolves its per-file runner beside __file__. ROOT remains the
    # original engine root; redirect only that child entrypoint to our wrapper.
    manual_worker.__file__ = __file__
    raise SystemExit(manual_worker.main())
