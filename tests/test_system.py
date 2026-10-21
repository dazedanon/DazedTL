"""The platform layer keeps the Windows rules on every platform."""

import importlib
import json
import os
import stat
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl import storage, system
from dazedtl.translation.files import read_json

from tests.engine import engine_package

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
            encoding="utf-8",
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


class WriteTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Windows has no mode bits")
    def test_new_saved_files_stay_private_and_rewrites_keep_their_mode(self):
        # The workspace's approval key and settings are written this way.
        with TemporaryDirectory() as folder:
            key = Path(folder, "approval.key")
            system.write_bytes(key, b"secret")
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            key.chmod(0o644)
            system.write_bytes(key, b"other")
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o644)
            self.assertEqual(os.listdir(folder), ["approval.key"])


class HeldFileTests(unittest.TestCase):
    def test_each_writer_waits_for_a_reader_that_holds_its_file(self):
        # Windows refuses to replace or delete a file another process reads,
        # such as the app's poll reading a run record while its worker saves.
        from desktop.backend.project import atomic_json

        rv2json = importlib.import_module(
            engine_package("util/ace").__name__ + ".rv2json"
        )
        writers = {
            "saved state": lambda path: storage.write_json(path, "new"),
            "run records": lambda path: atomic_json(path, "new"),
            "Ace data": lambda path: rv2json._replace(path, b'"new"\n'),
            "deletes": system.unlink,
            "renames": lambda path: system.rename(path, path.with_name("moved")),
            "folders": lambda path: system.remove_tree(path.parent),
            "folder renames": lambda path: system.rename(
                path.parent, path.parent.with_name("moved")
            ),
        }
        with TemporaryDirectory() as root:
            for name, write in writers.items():
                with self.subTest(name):
                    folder = Path(root, name)
                    folder.mkdir()
                    path = folder / "file.json"
                    path.write_bytes(b'"old"\n')
                    with system.held_open(path, attempts=3) as reader:
                        write(path)
                    self.assertEqual(reader.attempts, 0)
                    if name == "folders":
                        self.assertFalse(folder.exists())
                    elif name == "folder renames":
                        self.assertTrue(folder.with_name("moved").is_dir())
                    elif name == "deletes":
                        self.assertEqual(os.listdir(folder), [])
                    elif name == "renames":
                        self.assertEqual(os.listdir(folder), ["moved"])
                    else:
                        self.assertEqual(json.loads(path.read_bytes()), "new")
                        self.assertEqual(os.listdir(folder), ["file.json"])

    def test_each_reader_waits_for_a_writer_replacing_its_file(self):
        # Windows refuses to open a file while it is being replaced, which
        # failed a Batch estimate reading job.json as its worker saved it.
        from desktop.backend.manual import ManualJobs

        record = {"id": "run", "version": 2, "status": "done"}
        readers = {
            "bytes": system.read_bytes,
            "text": system.read_text,
            "checked JSON": read_json,
            "manual runs": lambda path: ManualJobs(
                path.parents[3], threading.Lock()
            ).load_saved(),
        }
        with TemporaryDirectory() as root:
            for name, read in readers.items():
                with self.subTest(name):
                    path = Path(root, name, "manual/jobs/run/job.json")
                    path.parent.mkdir(parents=True)
                    path.write_text(json.dumps(record), encoding="utf-8")
                    with system.held_open(path, attempts=3) as reader:
                        read(path)
                    self.assertEqual(reader.attempts, 0)
