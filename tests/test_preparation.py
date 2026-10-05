"""Preparation must retain completed stages without letting failures create a baseline."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dazedtl.compatibility.formatting import format_json_files, format_plugins_js
from dazedtl.storage import write_json
from dazedtl.translation import preparation


class PreparationTests(unittest.TestCase):
    def test_formatting_normalizes_existing_crlf_without_changing_game_text(self):
        # Already-pretty CRLF files used to bypass formatting, then produce a
        # whole-file diff against the translation writer's LF output.
        document = {"name": "薬", "text": "one\r\ntwo\nthree", "control": r"\C[2]"}
        expected_json = json.dumps(document, ensure_ascii=False, indent=4).encode(
            "utf-8"
        )
        expected_plugins = (
            'var $plugins = [{\n  "name": "薬",\n  "status": true\n}];\n'.encode()
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            nested = data / "nested"
            nested.mkdir()
            source, plugins = nested / "Items.JSON", root / "plugins.js"
            for newline in (b"\r\n", b"\r", b"\n"):
                with self.subTest(newline=newline):
                    source.write_bytes(expected_json.replace(b"\n", newline))
                    plugins.write_bytes(expected_plugins.replace(b"\n", newline))
                    self.assertEqual(format_json_files(data), (1, []))
                    self.assertEqual(
                        format_plugins_js(plugins),
                        len(expected_plugins.decode("utf-8")),
                    )
                    self.assertEqual(source.read_bytes(), expected_json)
                    self.assertEqual(json.loads(source.read_bytes()), document)
                    self.assertEqual(plugins.read_bytes(), expected_plugins)
            # BOM/minified inputs follow the same formatting, while a second
            # pass leaves canonical files untouched.
            source.write_bytes(
                b"\xef\xbb\xbf"
                + json.dumps(document, ensure_ascii=False).encode("utf-8")
            )
            plugins.write_bytes(
                b'\xef\xbb\xbfvar $plugins=[{"name":"'
                + "薬".encode()
                + b'","status":true}];'
            )
            self.assertEqual(format_json_files(data), (1, []))
            format_plugins_js(plugins)
            self.assertEqual(source.read_bytes(), expected_json)
            self.assertEqual(plugins.read_bytes(), expected_plugins)
            with patch.object(
                Path,
                "write_bytes",
                side_effect=AssertionError("Already LF; no rewrite needed"),
            ):
                self.assertEqual(format_json_files(data), (1, []))
                format_plugins_js(plugins)
            invalid = data / "broken.json"
            invalid.write_bytes(b"{invalid\r\n")
            count, errors = format_json_files(data)
            self.assertEqual((count, len(errors)), (1, 1))
            self.assertEqual(invalid.read_bytes(), b"{invalid\r\n")

    def test_stop_failure_resume_and_changed_files_retain_only_current_work(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            game, folder = root / "game", root / "profile"
            write_json(game / "data/Items.json", [None])
            (game / "js").mkdir()
            (game / "js/plugins.js").write_text("[]")
            folder.mkdir()
            native = {
                "id": "one",
                "source": str(game),
                "data": str(game / "data"),
                "plugins": str(game / "js/plugins.js"),
            }
            plan = {"action": "prepare_game", "project": native, "folder": str(folder)}
            called = []
            fail = True
            stop = False

            def execute(current, log):
                called.append(current["action"])
                if current["action"] == "format_plugins" and fail:
                    raise ValueError("Invalid plugin configuration")
                return {"files": 1}

            def log(message):
                if stop:
                    raise InterruptedError("Stopped")

            with self.assertRaises(ValueError):
                preparation.run(plan, log, execute, lambda *_: {})
            state = preparation.state(native, folder)
            self.assertFalse(state["complete"])
            self.assertEqual(
                [s["status"] for s in state["stages"]],
                ["complete", "failed", "pending"],
            )
            fail, stop = False, True
            with self.assertRaises(InterruptedError):
                preparation.run(plan, log, execute, lambda *_: {})
            self.assertEqual(called, ["format_data", "format_plugins"])
            self.assertEqual(
                preparation.state(native, folder)["stages"][1]["status"], "stopped"
            )
            stop = False
            preparation.run(plan, log, execute, lambda *_: {})
            self.assertEqual(
                called,
                ["format_data", "format_plugins", "format_plugins", "gameupdate"],
            )
            state = preparation.state(native, folder)
            self.assertTrue(state["complete"])
            self.assertIn("configuration is missing", state["configuration"])
            write_json(game / "data/Items.json", ["changed"])
            self.assertFalse(preparation.state(native, folder)["complete"])
            other = {**native, "id": "other"}
            self.assertFalse(preparation.state(other, folder)["complete"])
            preparation.run(
                {**plan, "action": "format_data"}, log, execute, lambda *_: {}
            )
            self.assertEqual(
                [s["status"] for s in preparation.state(native, folder)["stages"]],
                ["complete", "pending", "pending"],
            )

    def test_games_without_plugins_skip_the_plugin_stage_and_report_config_truthfully(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "game/data/Items.json", [None])
            (root / "profile").mkdir()
            native = {
                "id": "one",
                "source": str(root / "game"),
                "data": str(root / "game/data"),
                "plugins": "",
            }
            called = []

            def execute(plan, log):
                called.append(plan["action"])
                if plan["action"] == "gameupdate":
                    path = root / "game/gameupdate/patch-config.txt"
                    path.parent.mkdir()
                    path.write_text("repo=YOUR_PATCH_REPO")
                return {"config_written": False}

            result = preparation.run(
                {
                    "action": "prepare_game",
                    "project": native,
                    "folder": str(root / "profile"),
                },
                lambda _: None,
                execute,
                lambda *_: {},
            )
            self.assertEqual(called, ["format_data", "gameupdate"])
            self.assertTrue(result["complete"])
            self.assertIn("choose the patch repository", result["configuration"])
            # A completed receipt cannot authorize preparation after its Ace export disappears.
            native["engine"] = "ACE"
            data = root / "game/data/Items.json"
            original = data.read_bytes()
            data.unlink()
            self.assertFalse(preparation.state(native, root / "profile")["complete"])
            before = list(called)
            for action in ("prepare_game", "format_data"):
                with self.assertRaisesRegex(ValueError, "Convert the native Ace data"):
                    preparation.run(
                        {
                            "action": action,
                            "project": native,
                            "folder": str(root / "profile"),
                        },
                        lambda _: None,
                        execute,
                        lambda *_: {},
                    )
            self.assertEqual(called, before)
            data.write_bytes(original)
            self.assertTrue(preparation.state(native, root / "profile")["complete"])
            (root / "game/gameupdate/patch-config.txt").unlink()
            self.assertFalse(preparation.state(native, root / "profile")["complete"])
