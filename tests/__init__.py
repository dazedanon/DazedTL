"""Tests import only this checkout's backend, never a user's engine workspace."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def load_tests(loader, tests, pattern):
    # The engine probe starts in the background when its module is imported.
    # Running its test last lets the rest of the suite overlap that work.
    modules = loader.discover(str(Path(__file__).parent), pattern or "test*.py")
    return unittest.TestSuite(
        sorted(
            modules,
            key=lambda module: any(
                test.id().startswith("tests.test_engine_runtime.")
                for test in _tests(module)
            ),
        )
    )


def _tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _tests(test)
        else:
            yield test
