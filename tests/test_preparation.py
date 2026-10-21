"""Preparation must retain completed stages without letting failures create a baseline."""

import shutil
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
            (game / "js/plugins.js").write_text("[]", encoding="utf-8")
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

    def test_games_without_plugins_skip_the_plugin_stage_and_keep_it_through_config_changes(
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
                    path.write_text("repo=YOUR_PATCH_REPO", encoding="utf-8")
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
            # The config follows Settings and the game's repository afterwards,
            # so writing it again keeps the preparation receipt.
            (root / "game/gameupdate/patch-config.txt").write_text(
                "repo=filled-in", encoding="utf-8"
            )
            self.assertTrue(preparation.state(native, root / "profile")["complete"])
            (root / "game/gameupdate/other.txt").write_text(
                "changed helper file", encoding="utf-8"
            )
            self.assertFalse(preparation.state(native, root / "profile")["complete"])

    def test_formatting_a_vx_ace_games_exports_packs_them_into_its_data(self):
        # The game reads only Data, and Release waits for a pack once the
        # exports change; formatting them once left both to the user.
        from dazedtl.compatibility.game_write import write_game
        from dazedtl.translation.release import packing_state
        from util.dazedformat import format_json_files

        with TemporaryDirectory() as directory:
            root = Path(directory)
            game, folder = root / "game", root / "profile"
            fixture = Path(__file__).resolve().parent / "fixtures/ace"
            for name in ("Data", "ace_json"):
                shutil.copytree(fixture / name, game / name)
            folder.mkdir()
            native = {
                "id": "one",
                "source": str(game),
                "data": str(game / "ace_json"),
                "plugins": "",
                "engine": "ACE",
            }
            with write_game(game, folder) as written:
                written.repack()
            self.assertTrue(packing_state(native, folder)["current"])

            def execute(_plan, _log):
                return {"formatted": format_json_files(game / "ace_json")[0]}

            def stop(message):
                if message.startswith("Packing"):
                    raise InterruptedError("Stopped")

            plan = {"action": "format_data", "project": native, "folder": str(folder)}
            # A stop while packing reads as a stop, not as a failed pack.
            with self.assertRaises(InterruptedError):
                preparation.run(plan, stop, execute, lambda *_: {})
            self.assertEqual(
                preparation.state(native, folder)["stages"][0]["status"], "stopped"
            )
            preparation.run(plan, lambda _: None, execute, lambda *_: {})
            self.assertTrue(packing_state(native, folder)["current"])
