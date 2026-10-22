"""Tests import only this checkout's backend, never a user's engine workspace."""

import faulthandler
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
# The app activates its bundled engine at startup; code that reads engine
# helpers, such as glossary rows, needs it in every test module too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/dazedtl/engine"))
# Windows may name the temporary folder by its 8.3 short name, such as
# RUNNER~1, while the app resolves the game folders it opens to long names.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
# App code writes a game's own files only through the game-write gateway.
from tests import game_writes

game_writes.install()
# The suite does not check what survives a power loss, and Windows takes
# about 2 ms per fsync: the app's durable saves made seconds of its runtime.
os.fsync = lambda _descriptor: None


def stop_at_deadline(file=sys.stderr):
    """A process of a suite stopped at its runtime budget (scripts/test.mjs)
    writes the test and line every thread waits on to `file` a second before,
    then exits rather than outlive the run."""
    if deadline := os.environ.get("DAZEDTL_TEST_DEADLINE"):
        faulthandler.dump_traceback_later(
            max(0.1, int(deadline) / 1000 - time.time() - 1), exit=True, file=file
        )


stop_at_deadline()
