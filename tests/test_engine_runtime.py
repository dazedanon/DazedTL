"""The installed runtime must work without either historical engine checkout."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class EngineRuntimeTests(unittest.TestCase):
    def test_offline_startup_and_parser_ignore_external_engine_paths(self):
        # Existing unit fixtures replace engine APIs. This one small real parser
        # journey catches missing imports/assets and child-launch regressions.
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            environment = {key: value for key, value in os.environ.items() if key in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
                "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}}
            environment.update(PYTHON_DOTENV_DISABLED="1", API_KEY_OPTIONAL="true", DAZEDTL_TEST_OFFLINE="1",
                               DAZEDTL_LEGACY_ROOT=str(Path(temporary) / "missing-engine"),
                               DAZEDTL_ENGINE_SOURCE=str(Path(temporary) / "missing-engine"))
            result = subprocess.run([sys.executable, "-I", "-B", str(root / "tests/fixtures/engine_runtime.py"),
                                     str(root), temporary], cwd=temporary, env=environment,
                                    capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
