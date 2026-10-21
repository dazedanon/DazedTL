"""Preserved workflow runner with app-owned tool installation paths."""

import json
import runpy
import sys
from contextlib import suppress
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dazedtl import system
from dazedtl.diagnostics import record_crashes, watch_action, worker_failure

try:
    action = json.loads(system.read_bytes(sys.argv[1]))["action"]
except OSError, ValueError, KeyError, TypeError, IndexError:
    action = "unknown"  # The engine's worker reports the unreadable plan.
action = str(action)
record_crashes(action)
from dazedtl.system import private_stdin

# The stop command arrives on standard input while this action runs Git and
# other tools; they must not inherit that pipe.
sys.stdin = private_stdin()
from dazedtl.compatibility.runtime import activate

source = activate()
from desktop.backend import worker_failures, workflow_actions

from dazedtl import actions
from dazedtl.compatibility.translation import explained


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
    # only the errors that say what to fix. Recording must not stop the
    # worker from reporting it.
    with suppress(Exception):
        if not explained(error):
            worker_failure(error, action)
    native(error)


workflow_actions.run_action.layer("dazedtl-actions", actions.run)
worker_failures.reported.layer("dazedtl-diagnostics", reported)
# The worker keeps standard output as its event stream before redirecting it.
sys.stdout = Progress(sys.stdout, watch_action(action))
runpy.run_path(str(source / "desktop/backend/workflow_worker.py"), run_name="__main__")
