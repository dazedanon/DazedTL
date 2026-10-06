"""Background fixture processes that overlap the rest of the suite."""

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


class Probe:
    """Runs a fixture script in a fresh offline interpreter, then cleans up."""

    def __init__(self, script):
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
                str(root / "tests/fixtures" / script),
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
