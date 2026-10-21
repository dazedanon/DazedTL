"""The platform layer keeps the Windows rules on every platform."""

import subprocess
import sys
import unittest
from pathlib import Path

from dazedtl import system

BACKEND = Path(__file__).resolve().parents[1] / "backend"


class PrivateStdinTests(unittest.TestCase):
    def test_children_get_the_null_device_while_the_parent_keeps_its_pipe(self):
        # On Windows a child that inherits a pipe its parent is reading blocks
        # during startup, which froze every per-file translation worker.
        script = f"""
import subprocess, sys
sys.path.insert(0, {str(BACKEND)!r})
from dazedtl.system import private_stdin
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


class SpawnTests(unittest.TestCase):
    def test_python_children_read_utf8_and_inherit_no_input(self):
        # Without -X utf8 an isolated child decoded its pipes as cp1252 on
        # Windows; an inherited input pipe froze its startup.
        result = system.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys; print(sys.flags.utf8_mode, repr(sys.stdin.read()), 'ゲーム')",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.stdout.strip(), "1 '' ゲーム")
