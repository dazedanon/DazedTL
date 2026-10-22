"""Background processes that overlap the rest of the suite."""

import atexit
import os
import subprocess
import sys
import time
from contextlib import ExitStack
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


def bytecode():
    """Interpreter options that share the suite's compiled modules
    (scripts/test.mjs), or write none."""
    if sys.pycache_prefix:
        return ["-X", "pycache_prefix=" + sys.pycache_prefix]
    return ["-B"]


class Background:
    """A process started while its test module is imported, so it runs beside
    the rest of the suite; tests/run.py keeps that module whole, so the process
    starts once."""

    def __init__(self):
        self.temporary = TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.process = None
        self.logs = []
        atexit.register(self.close)

    def start(self, command, *, merge=True, **options):
        """Starts `command`; its standard error joins its output unless
        `merge` is false. `options` go to subprocess.Popen."""
        # Within the suite's budget (scripts/test.mjs), leaving room to report.
        budget = float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10)
        self.deadline = time.monotonic() + budget * 0.8
        # Files rather than pipes: a process that printed much would wait on a
        # full pipe until its test read it, and reading a finished process's
        # pipes after the deadline timed out on Windows, which failed a slow
        # CI run whose probes had long finished. The child keeps its own handles.
        for _ in range(1 if merge else 2):
            descriptor, log = mkstemp(prefix="dazedtl-probe-")
            os.close(descriptor)
            self.logs.append(log)
        with ExitStack() as stack:
            output, *errors = [
                stack.enter_context(open(log, "wb")) for log in self.logs
            ]
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors[0] if errors else subprocess.STDOUT,
                **options,
            )
        return self

    def wait(self):
        """The process's exit code, once it ends within the suite's budget."""
        return self.process.wait(timeout=max(0, self.deadline - time.monotonic()))

    def result(self):
        """The process's exit code, output and, unless merged, its errors."""
        try:
            self.wait()
            output, errors = [
                Path(log).read_bytes().decode("utf-8", "replace") for log in self.logs
            ] + [""] * (2 - len(self.logs))
        finally:
            self.close()
        return self.process.returncode, output, errors

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        for log in self.logs:
            Path(log).unlink(missing_ok=True)
        self.temporary.cleanup()


class Probe(Background):
    """Runs a fixture script in a fresh offline interpreter, then cleans up."""

    def __init__(self, script):
        super().__init__()
        root = Path(__file__).resolve().parents[1]
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
        self.start(
            [
                sys.executable,
                "-I",
                "-X",
                "utf8",
                *bytecode(),
                "-c",
                LAUNCH,
                str(root / "tests/fixtures" / script),
                str(root),
                temporary,
            ],
            cwd=temporary,
            env=environment,
        )

    def result(self):
        returncode, output, _errors = super().result()
        return returncode, output
