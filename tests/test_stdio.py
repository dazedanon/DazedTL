"""A process's input pipe stays private to it."""

import subprocess
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


class PrivateStdinTests(unittest.TestCase):
    def test_children_get_the_null_device_while_the_parent_keeps_its_pipe(self):
        # On Windows a child that inherits a pipe its parent is reading blocks
        # during startup, which froze every per-file translation worker.
        script = f"""
import subprocess, sys
sys.path.insert(0, {str(BACKEND)!r})
from dazedtl.stdio import private_stdin
channel = private_stdin()
child = subprocess.run(
    [sys.executable, "-I", "-c", "import sys; print(repr(sys.stdin.read()))"],
    stdout=subprocess.PIPE, text=True, timeout=20, check=False,
)
print(child.stdout.strip(), repr(channel.readline()))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            input="request\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.strip(), "'' 'request\\n'")
