"""A translated game's window title (engine/util/window_title): the
translator's name in Settings, and the title an MZ and a VX Ace game show,
which leaves what saves depend on and every game without a name alone."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.compatibility import original_files
from dazedtl.compatibility.checkpoint_commits import for_action, running
from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.game_write import write_game
from dazedtl.settings.store import Settings, saved_translator
from dazedtl.storage import write_json
from desktop.backend.settings import validate_values
from util import window_title
from util.ace import game_ini
from util.ace.actions import write_window_title
from util.len_git import setup_git
from util.len_patch_scope import setup_files
from util.len_translation import LenProject
from util.paths import runtime_data_profile
from util.rpgmaker_plugin_registry import plugin_entries
from util.translation_update_check.installer import is_game_plugin

ROOT = Path(__file__).resolve().parents[1]


def git(game, *arguments, input=None):
    return subprocess.run(
        ["git", "-C", str(game), *arguments],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        input=input,
    ).stdout


def named(name):
    """The environment of a command run outside the app with `name` set."""
    values = {
        key: value
        for key, value in os.environ.items()
        if key != "DAZEDTL_DESKTOP_WORKSPACE"
    }
    return patch.dict(os.environ, {**values, window_title.SETTING: name}, clear=True)


class WindowTitleTests(unittest.TestCase):
    def test_title_leaves_out_what_is_missing(self):
        form = window_title.form
        self.assertEqual(
            form("Asylum", "1.0.9", "DazedAnon"), "Asylum v1.0.9 | TL: DazedAnon"
        )
        self.assertEqual(
            form(" Asylum ", "v1.0.9", " Dazed  Anon "),
            "Asylum v1.0.9 | TL: Dazed Anon",
        )
        self.assertEqual(form("Asylum", None, "DazedAnon"), "Asylum | TL: DazedAnon")
        self.assertEqual(form("Asylum", "1.0", ""), "")
        self.assertEqual(form("", "1.0", "DazedAnon"), "")
        self.assertEqual(
            window_title.preview(None, "DazedAnon"), "<English title> | TL: DazedAnon"
        )

    def test_settings_keep_the_translator_name(self):
        metadata = {"values": validate_values({})}
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            check_game_update=ExistingBackend.check_game_update,
        )
        defaults = {
            "forge": "gitlab",
            "host": "gitgud.io",
            "username": "",
            "branch": "main",
        }
        with TemporaryDirectory() as temporary:
            write_json(
                Path(temporary) / "settings/settings.json",
                {
                    "version": 2,
                    "revision": 0,
                    "values": {"language": "English", "model": "fixture-model"},
                    "legacy": {
                        "values": metadata["values"],
                        "engines": {},
                        "draft": None,
                    },
                    "model_options": {},
                    "active": "",
                    "draft": None,
                    "connections": [],
                },
            )
            settings = Settings(temporary, adapter)
            self.assertEqual(settings.translator(), "")
            with patch.object(Settings, "describe", lambda self: self._read()):
                state = settings.save_publishing(
                    0, {**defaults, "translator": "  Dazed\tAnon "}
                )
                with self.assertRaisesRegex(ValueError, "up to 80"):
                    settings.save_publishing(
                        state["revision"], {**defaults, "translator": "x" * 81}
                    )
            # A restart reads it, and so do the engine's writes in an operation.
            self.assertEqual(Settings(temporary, adapter).translator(), "Dazed Anon")
            self.assertEqual(saved_translator(temporary), "Dazed Anon")
            with runtime_data_profile(Path(temporary) / "engine"):
                self.assertEqual(window_title.translator(), "Dazed Anon")
            with patch.object(Settings, "describe", lambda self: self._read()):
                settings.save_publishing(
                    state["revision"], {**defaults, "translator": ""}
                )
            self.assertEqual(saved_translator(temporary), "")
        self.assertEqual(saved_translator(Path(temporary) / "missing"), "")

    def test_an_mz_game_shows_the_title_from_launch_and_keeps_its_save_values(self):
        with TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            shutil.copytree(ROOT / "tests/fixtures/mz-game", game)
            # Windows line endings stay through DazedTL's edits.
            plugins = game / "js/plugins.js"
            plugins.write_bytes(
                plugins.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            )
            # The app records the game's original files as it opens it.
            original_files.ensure_found(game)
            setup_git(LenProject(game), version="1.0.9", current_is_untranslated=True)
            # A Guided game's `original` branch holds only its patch's files.
            tree = git(game, "ls-tree", "original")
            kept = "".join(
                line + "\n"
                for line in tree.splitlines()
                if not line.endswith(("\tpackage.json", "\tindex.html"))
            )
            stripped = git(
                game,
                "commit-tree",
                git(game, "mktree", input=kept).strip(),
                "-p",
                "original",
                "-m",
                "Original\n\nDazedTL-Version: 1.0.9",
            ).strip()
            git(game, "update-ref", "refs/heads/original", stripped)
            system = json.loads((game / "data/System.json").read_text(encoding="utf-8"))
            system["gameTitle"] = "Magical Girl Adventure"
            translated = json.dumps(system, ensure_ascii=False).encode("utf-8")

            def write(raw):
                with (
                    running(for_action("export_selected")),
                    write_game(game, paths=["data/System.json"]) as written,
                ):
                    written.put("data/System.json", raw)

            with named(""):
                write(translated)
            # Without a translator name the game keeps its own title.
            self.assertIn(
                "魔法少女の冒険", (game / "package.json").read_text(encoding="utf-8")
            )
            self.assertFalse((game / "js/plugins/DazedTLWindowTitle.js").exists())

            with named("Tester"):
                # Setting the name leaves the title waiting for the next write.
                self.assertEqual(
                    sorted(window_title.pending(game)),
                    [
                        "index.html",
                        "js/plugins.js",
                        "js/plugins/DazedTLWindowTitle.js",
                        "package.json",
                    ],
                )
                write(translated.replace(b"Adventure", b"Adventures"))
            self.assertNotIn(b"\n", plugins.read_bytes().replace(b"\r\n", b""))
            title = "Magical Girl Adventures v1.0.9 | TL: Tester"
            package = json.loads((game / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(
                package,
                {"name": "rmmz-game", "main": "index.html", "window": {"title": title}},
            )
            self.assertIn(
                f"<title>{title}</title>",
                (game / "index.html").read_text(encoding="utf-8"),
            )
            entries = plugin_entries(
                (game / "js/plugins.js").read_text(encoding="utf-8")
            )
            self.assertIn(
                {
                    "name": window_title.PLUGIN_NAME,
                    "status": True,
                    "description": "Translation window title",
                    "parameters": {"title": title},
                },
                entries,
            )
            # The drawn title stays the translated one.
            self.assertEqual(
                json.loads((game / "data/System.json").read_text(encoding="utf-8"))[
                    "gameTitle"
                ],
                "Magical Girl Adventures",
            )
            # The title joins the write's own checkpoint, and every patch.
            committed = subprocess.run(
                ["git", "-C", str(game), "show", "--name-only", "--format=", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            ).stdout.split()
            self.assertEqual(
                sorted(committed),
                [
                    "data/System.json",
                    "index.html",
                    "js/plugins.js",
                    "js/plugins/DazedTLWindowTitle.js",
                    "package.json",
                ],
            )
            self.assertIn("js/plugins/DazedTLWindowTitle.js", setup_files(game))
            self.assertFalse(is_game_plugin(window_title.PLUGIN_NAME))
            # A write that changes nothing of it leaves the title's files alone.
            with named("Tester"):
                self.assertEqual(
                    window_title.sync(game, lambda *_: self.fail("wrote")), []
                )
            # Clearing the name gives the game its own title back at the next write.
            with named(""):
                write(translated)
            self.assertEqual(
                (game / "package.json").read_bytes(),
                (ROOT / "tests/fixtures/mz-game/package.json").read_bytes(),
            )
            self.assertIn(
                "<title>魔法少女の冒険</title>",
                (game / "index.html").read_text(encoding="utf-8"),
            )
            self.assertFalse((game / "js/plugins/DazedTLWindowTitle.js").exists())
            self.assertNotIn(
                window_title.PLUGIN_NAME,
                (game / "js/plugins.js").read_text(encoding="utf-8"),
            )

    def test_vx_ace_game_ini_takes_the_title_in_ascii(self):
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            ini = game / "Game.ini"
            ini.write_bytes(b"[Game]\r\nRTP=RPGVXAce\r\nTitle=\x83Q\x81[\x83\x80\r\n")
            (game / "Data").mkdir()
            (game / "Data/System.rvdata2").write_bytes(b"")
            (game / "ace_json").mkdir()
            (game / "ace_json/System.json").write_text(
                '{"gameTitle": "Cafe Quest"}', encoding="utf-8"
            )
            with named("Tester"):
                # A game whose Git is not set up, such as a staged update, keeps the title.
                self.assertEqual(
                    window_title.ini_title(game, "Cafe Quest"), "Cafe Quest"
                )
                for arguments in (
                    ["init", "-q", "-b", "original"],
                    [
                        "-c",
                        "user.name=t",
                        "-c",
                        "user.email=t@t",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "Original\n\nDazedTL-Version: 2.0",
                    ],
                    ["checkout", "-q", "-b", "main"],
                ):
                    subprocess.run(
                        ["git", "-C", str(game), *arguments],
                        check=True,
                        capture_output=True,
                    )
                with named("翻訳者"):
                    # Game.ini holds ASCII, so a name with none gives no credit.
                    self.assertEqual(
                        window_title.ini_title(game, "Cafe Quest"), "Cafe Quest"
                    )
                    self.assertEqual(
                        window_title.ini_title(game, "Cafe Quest", "Japanese"),
                        "Cafe Quest v2.0 | TL: 翻訳者",
                    )
                # Packing System is what brings Game.ini's title up to date.
                self.assertEqual(window_title.pending(game), ["Game.ini"])
                title = window_title.ini_title(game, "Café ♥ Quest")
                self.assertEqual(title, "Café ♥ Quest v2.0 | TL: Tester")
                self.assertTrue(game_ini.write_title(ini, title, lambda _line: None))
                self.assertEqual(window_title.pending(game), [])
            self.assertIn(
                b"\r\nTitle=Cafe Quest v2.0 | TL: Tester\r\n", ini.read_bytes()
            )
            # Clearing the name gives Game.ini the game title back, which a
            # pack writes even with nothing else to pack.
            with named(""):
                self.assertEqual(window_title.pending(game), ["Game.ini"])
                self.assertEqual(
                    write_window_title(game, lambda _line: None, system=False), [ini]
                )
                self.assertEqual(window_title.pending(game), [])
            self.assertIn(b"\r\nTitle=Cafe Quest\r\n", ini.read_bytes())
            with named(""):
                self.assertEqual(
                    window_title.ini_title(game, "Cafe Quest"), "Cafe Quest"
                )


if __name__ == "__main__":
    unittest.main()
