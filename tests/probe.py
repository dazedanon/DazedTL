"""Background fixture processes that overlap the rest of the suite."""

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp

# Runs a fixture script as its own program after the setup every test
# module has, which includes the write check (tests/game_writes.py).
LAUNCH = """
import runpy, sys
del sys.argv[0]
sys.path.insert(0, sys.argv[1])
import tests
runpy.run_path(sys.argv[0], run_name="__main__")
"""


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
                # Windows' home folder, which Path.home() reads.
                "USERPROFILE",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH",
                "DAZEDTL_TEST_BUDGET",
            }
        }
        environment.update(
            PYTHON_DOTENV_DISABLED="1",
            API_KEY_OPTIONAL="true",
            DAZEDTL_TEST_OFFLINE="1",
            DAZEDTL_LEGACY_ROOT=str(Path(temporary) / "missing-engine"),
            DAZEDTL_ENGINE_SOURCE=str(Path(temporary) / "missing-engine"),
        )
        # Within the suite's budget (scripts/test.mjs), leaving room to report.
        budget = float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10)
        self.deadline = time.monotonic() + budget * 0.8
        # A file rather than pipes: a probe that printed much would wait on a
        # full pipe until its test read it, and reading a finished probe's
        # pipes after the deadline timed out on Windows, which failed a slow
        # CI run whose probes had long finished. The child keeps its own handle.
        descriptor, self.log = mkstemp(prefix="dazedtl-probe-")
        with open(descriptor, "wb") as output:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-X",
                    "utf8",
                    "-B",
                    "-c",
                    LAUNCH,
                    str(root / "tests/fixtures" / script),
                    str(root),
                    temporary,
                ],
                cwd=temporary,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        atexit.register(self.close)

    def result(self):
        try:
            self.process.wait(timeout=max(0, self.deadline - time.monotonic()))
            output = Path(self.log).read_bytes().decode("utf-8", "replace")
        finally:
            self.close()
        return self.process.returncode, output

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        Path(self.log).unlink(missing_ok=True)
        self.temporary.cleanup()
