"""Preparation must retain completed stages without letting failures create a baseline."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.storage import write_json
from dazedtl.translation import preparation


class PreparationTests(unittest.TestCase):
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
            self.assertIn("Add gameupdate/patch-config.txt", state["configuration"])
            self.assertFalse(state["configurationReady"])
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
            self.assertIn("Set repo=", result["configuration"])
            self.assertFalse(result["configurationReady"])
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
