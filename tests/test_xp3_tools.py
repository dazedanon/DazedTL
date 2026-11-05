"""Len's KiriKiri XP3 tools, run as an assistant runs them, on small archives."""

import importlib.util
import struct
import sys
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_census import xp3

TOOLS = (
    Path(__file__).resolve().parents[1]
    / "backend/dazedtl/engine/data/skills/game-translation/tools/Game Archives/KiriKiri XP3"
)


def tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(name, *args):
    """The tool's exit code and what it printed to stderr."""
    module = tool(name)
    errors = StringIO()
    with (
        patch.object(sys, "argv", [name, *map(str, args)]),
        redirect_stdout(StringIO()),
        redirect_stderr(errors),
    ):
        try:
            module.main()
            code = 0
        except SystemExit as exit:
            code = exit.code
        except module.XP3Error as exc:
            # The tool's own entry point prints it and exits with 1.
            print(exc, file=errors)
            code = 1
    return code, errors.getvalue()


class Xp3ToolTests(unittest.TestCase):
    def test_a_patch_archive_unpacks_to_the_files_packed(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "decoded/image").mkdir(parents=True)
            (root / "decoded/image/title.bmp").write_bytes(b"BM" + bytes(300))
            (root / "decoded/image/menu.tlg").write_bytes(b"TLG5.0")
            code, _ = run(
                "pack_xp3",
                root / "patch.xp3",
                "--root",
                root / "decoded",
                "--flat",
                "image/title.bmp",
                "image/menu.tlg",
            )
            self.assertEqual(code, 0)
            self.assertEqual(run("unpack_xp3", root / "patch.xp3", root / "out")[0], 0)
            # Flat: KiriKiri finds a patch archive's files by bare name.
            self.assertEqual(
                sorted(path.name for path in (root / "out").iterdir()),
                ["menu.tlg", "title.bmp"],
            )
            self.assertEqual((root / "out/title.bmp").read_bytes(), b"BM" + bytes(300))
            # Packed twice into the folder it packs, it held its old self.
            for _ in range(2):
                self.assertEqual(
                    run(
                        "pack_xp3",
                        root / "decoded/patch.xp3",
                        "--root",
                        root / "decoded",
                        "--flat",
                        "--overwrite",
                    )[0],
                    0,
                )
            self.assertEqual(
                run("unpack_xp3", root / "decoded/patch.xp3", root / "again")[0], 0
            )
            self.assertEqual(
                sorted(path.name for path in (root / "again").iterdir()),
                ["menu.tlg", "title.bmp"],
            )

    def test_unreadable_files_and_indexes_are_named_and_fail(self):
        # An archive whose index the tool can't read reported "records: 0"
        # and exited 0, so an assistant read an encrypted archive as empty.
        with TemporaryDirectory() as folder:
            root = Path(folder)
            index = b"hnfn" + struct.pack("<Q", 4) + b"abcd"
            packed = zlib.compress(index)
            (root / "hashed.xp3").write_bytes(
                tool("unpack_xp3").XP3_MAGIC
                + struct.pack("<Q", 19)
                + struct.pack("<BQQ", 1, len(packed), len(index))
                + packed
            )
            code, errors = run("unpack_xp3", root / "hashed.xp3", root / "out")
            self.assertEqual(code, 1)
            self.assertIn("lists no files", errors)
            # A member the game's cipher scrambles is named and left out.
            (root / "data.xp3").write_bytes(xp3({"image/secret.png": b"x" * 40}, True))
            code, errors = run("unpack_xp3", root / "data.xp3", root / "data")
            self.assertEqual(code, 2)
            self.assertIn("image/secret.png", errors)
            self.assertFalse((root / "data/image/secret.png").exists())


if __name__ == "__main__":
    unittest.main()
