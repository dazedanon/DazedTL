"""Tests import only this checkout's backend, never a user's engine workspace."""

import sys
import tempfile
import unittest
from pathlib import Path

from tests.probe import Probe

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
# Windows may name the temporary folder by its 8.3 short name, such as
# RUNNER~1, while the app resolves the game folders it opens to long names.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())


def load_tests(loader, tests, pattern):
    # Probes start in the background when their modules are imported. Running
    # their tests last lets the rest of the suite overlap that work.
    modules = loader.discover(str(Path(__file__).parent), pattern or "test*.py")
    return unittest.TestSuite(sorted(modules, key=_waits_for_probe))


def _waits_for_probe(suite):
    return any(
        isinstance(getattr(sys.modules[type(test).__module__], "probe", None), Probe)
        for test in _tests(suite)
    )


def _tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _tests(test)
        else:
            yield test
