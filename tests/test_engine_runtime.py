"""The installed runtime must work without either historical engine checkout."""

import atexit
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest


class Probe:
    """Runs the engine probe in a fresh interpreter, then cleans up after it."""

    def __init__(self):
        root = Path(__file__).resolve().parents[1]
        self.temporary = TemporaryDirectory()
        temporary = self.temporary.name
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH",
            }
        }
        environment.update(
            PYTHON_DOTENV_DISABLED="1",
            API_KEY_OPTIONAL="true",
            DAZEDTL_TEST_OFFLINE="1",
            DAZEDTL_LEGACY_ROOT=str(Path(temporary) / "missing-engine"),
            DAZEDTL_ENGINE_SOURCE=str(Path(temporary) / "missing-engine"),
        )
        self.deadline = time.monotonic() + 8
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(root / "tests/fixtures/engine_runtime.py"),
                str(root),
                temporary,
            ],
            cwd=temporary,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        atexit.register(self.close)

    def result(self):
        try:
            output, errors = self.process.communicate(
                timeout=max(0, self.deadline - time.monotonic())
            )
        finally:
            self.close()
        return self.process.returncode, output + errors

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.communicate()
        self.temporary.cleanup()


# The probe spends most of its time starting three interpreters, so it starts
# when discovery imports this module and runs alongside the other tests.
probe = Probe()


class EngineRuntimeTests(unittest.TestCase):
    def test_offline_startup_and_parser_ignore_external_engine_paths(self):
        # Existing unit fixtures replace engine APIs. This one small real parser
        # journey catches missing imports/assets and child-launch regressions.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
