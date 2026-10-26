"""The built-in Ace preparation writes what the Windows tools it replaced wrote.

fixtures/ace holds made-up, editor-shaped data that Ruby 3.4 dumped, with
RV2JSON 1.2.1's own JSON and packed output; its regenerate.py rebuilds it.
"""

import importlib
import json
import os
import shutil
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.engine import engine_package
from tests.rgssad_archives import archive_v1, archive_v3

ace = engine_package("util/ace")
actions = importlib.import_module(ace.__name__ + ".actions")
game_ini = importlib.import_module(ace.__name__ + ".game_ini")
rgssad = importlib.import_module(ace.__name__ + ".rgssad")
ruby_marshal = importlib.import_module(ace.__name__ + ".ruby_marshal")
rv2json = importlib.import_module(ace.__name__ + ".rv2json")

FIXTURE = Path(__file__).resolve().parent / "fixtures/ace"


def files(folder):
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def scripts(data):
    # Ruby's zlib and Python's compress differently; the code must match.
    return [
        (item[0], item[1].data, zlib.decompress(item[2].data))
        for item in ruby_marshal.load(data)
    ]


def contents(archive):
    data = archive.read_bytes()
    return [
        (name, rgssad.decrypt(data[offset : offset + size], key))
        for name, offset, size, key in rgssad.entries(data)
    ]


class AceConversionTests(unittest.TestCase):
    def test_updating_a_relative_game_root_writes_into_that_game(self):
        # With the root given relative to the working folder, the data folder
        # was joined to the root a second time and written as a nested copy.
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            shutil.copytree(FIXTURE / "Data", game / "Data")
            rv2json.create(game, log=lambda _line: None)
            shutil.copytree(
                FIXTURE / "translated", game / "ace_json", dirs_exist_ok=True
            )
            before = os.getcwd()
            os.chdir(game.parent)
            try:
                rv2json.update(Path(game.name), log=lambda _line: None)
            finally:
                os.chdir(before)
            self.assertEqual(
                [path for path in game.rglob("*") if path.name == game.name], []
            )
            self.assertTrue((game / "Data/backups").is_dir())

    def test_json_and_packed_data_match_rv2json_and_pack_files_named_in_any_case(self):
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            shutil.copytree(FIXTURE / "Data", game / "Data")
            # Shipped games name files in other cases; Windows tools found them.
            (game / "Data/CommonEvents.rvdata2").rename(
                game / "Data/Commonevents.rvdata2"
            )
            rv2json.create(game, log=lambda _line: None)
            self.assertEqual(files(game / "ace_json"), files(FIXTURE / "ace_json"))

            shutil.copytree(
                FIXTURE / "translated", game / "ace_json", dirs_exist_ok=True
            )
            rv2json.update(game, log=lambda _line: None)
            original = files(FIXTURE / "Data")
            packed = files(FIXTURE / "packed")
            original["Commonevents.rvdata2"] = original.pop("CommonEvents.rvdata2")
            packed["Commonevents.rvdata2"] = packed.pop("CommonEvents.rvdata2")
            # Packing a second time keeps the first backups of the originals.
            rv2json.update(game, log=lambda _line: None)
            result = files(game / "Data")
            self.assertEqual(
                {
                    name: data
                    for name, data in result.items()
                    if name.startswith("backups/")
                },
                {"backups/" + name: data for name, data in original.items()},
            )
            data = {name: data for name, data in result.items() if "/" not in name}
            self.assertEqual(sorted(data), sorted(packed))
            self.assertEqual(
                scripts(data.pop("Scripts.rvdata2")),
                scripts(packed.pop("Scripts.rvdata2")),
            )
            self.assertEqual(data, packed)

    def test_packing_scripts_keeps_a_name_with_characters_a_file_name_cannot_hold(self):
        # The file name was made by editing the script's own name in place,
        # so every pack renamed "Vocab: <用語>?" to "Vocab 用語" in the editor
        # and a later update saw Scripts.rvdata2 as changed.
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            shutil.copytree(FIXTURE / "Data", game / "Data")
            names = [
                item[1]
                for item in scripts((game / "Data/Scripts.rvdata2").read_bytes())
            ]
            self.assertIn("Vocab: <用語>?".encode(), names)
            rv2json.create(game, log=lambda _line: None)
            self.assertEqual(
                rv2json.script_names(game),
                [
                    "1500000000_Vocab 用語.rb",
                    "12345678_Main.rb",
                    "23456_.rb",
                ],
            )
            shutil.copytree(
                FIXTURE / "translated", game / "ace_json", dirs_exist_ok=True
            )
            rv2json.update(game, log=lambda _line: None)
            packed = scripts((game / "Data/Scripts.rvdata2").read_bytes())
            self.assertEqual([item[1] for item in packed], names)
            self.assertIn(b"Terms", packed[0][2])

    def test_packing_writes_the_game_title_into_game_ini_as_every_player_reads_it(
        self,
    ):
        # Game.exe decodes an ini without a byte order mark with the player's
        # code page, so the Japanese editor's Shift-JIS caption was mojibake
        # on English Windows even after translation.
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            shutil.copytree(FIXTURE / "Data", game / "Data")
            rv2json.create(game, log=lambda _line: None)
            ini = game / "Game.ini"
            original = "[Game]\r\nLibrary=System\\RGSS301.dll\r\nTitle=テストゲーム\r\nRTP=RPGVXAce\r\n"
            ini.write_bytes(original.encode("cp932"))
            # An untranslated title leaves the file as the editor wrote it.
            actions.run(game, "ace_pack", log=lambda _line: None)
            self.assertEqual(ini.read_bytes(), original.encode("cp932"))

            shutil.copytree(
                FIXTURE / "translated", game / "ace_json", dirs_exist_ok=True
            )
            # The receipt binds Game.ini with the data.
            self.assertIn(ini, actions.run(game, "ace_pack", log=lambda _line: None))
            self.assertEqual(
                ini.read_bytes(),
                original.replace("テストゲーム", "Test Game").encode("cp932"),
            )

            system = game / "ace_json/System.json"
            system.write_text(
                system.read_text(encoding="utf-8").replace(
                    '"Test Game"', '"Orc ♥ Revenge"'
                ),
                encoding="utf-8",
            )
            actions.run(game, "ace_pack", log=lambda _line: None)
            # Any other title turned the file into UTF-16, where mkxp-z
            # (Linux, Steam Deck, JoiPlay) found no Scripts= and could not
            # start the game; the title is written in ASCII instead.
            self.assertEqual(
                ini.read_bytes(),
                original.replace("テストゲーム", "Orc Revenge").encode("cp932"),
            )
            # Æ, Œ and ß were left out with the ♥, and a mostly Japanese
            # title shrank to its version; it keeps the title it had.
            for title, shown in [
                ("Ætherial Œuvre ß ～エーテル～", "AEtherial OEuvre ss"),
                ("ドキドキ★学園 Ver.1.05", "AEtherial OEuvre ss"),
            ]:
                game_ini.write_title(ini, title, log=lambda _line: None)
                self.assertEqual(
                    ini.read_bytes(),
                    original.replace("テストゲーム", shown).encode("cp932"),
                )
            # A game translated into Japanese is played where Windows reads
            # Shift-JIS, so its title is written whole, as the editor writes it.
            game_ini.write_title(
                ini, "オークの逆襲♪", log=lambda _line: None, language="Japanese"
            )
            self.assertEqual(
                ini.read_bytes(),
                original.replace("テストゲーム", "オークの逆襲♪").encode("cp932"),
            )

    def test_packing_writes_text_variables_translated_for_mv_mz_as_ruby_strings(
        self,
    ):
        # Earlier versions translated a VX Ace text variable as MV/MZ's
        # template literal, which Ruby runs as a shell command, so the packed
        # game froze at the event.
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            shutil.copytree(FIXTURE / "Data", game / "Data")
            rv2json.create(game, log=lambda _line: None)
            path = game / "ace_json/CommonEvents.json"
            events = json.loads(path.read_text(encoding="utf-8"))
            commands = events[1]["list"][16:19]
            for command, operand, original in zip(
                commands,
                (
                    "`\\\\C[2]Villager\\\\C[0] says #{hi}\\nto \\`you\\``;",
                    # Interpolates, so it holds no text Ruby can.
                    "`${name}'s room`",
                    # The game's own.
                    "`echo`",
                ),
                ("\\\\C[2]村人\\\\C[0]の挨拶", "${name}の部屋", None),
            ):
                self.assertEqual(command["code"], 122)
                command["parameters"][3:] = [4, operand]
                if original:
                    command["_original"] = original
            saved = json.dumps(events, ensure_ascii=False, indent=4)
            path.write_text(saved, encoding="utf-8")
            lines = []
            actions.run(game, "ace_pack", log=lines.append)
            packed = ruby_marshal.load(
                (game / "Data/CommonEvents.rvdata2").read_bytes()
            )
            self.assertEqual(
                [
                    rv2json.text(command.ivars["@parameters"][4])
                    for command in packed[1].ivars["@list"][16:19]
                ],
                [
                    # The text the template literal held: a message code's
                    # backslash, a line break, "#{" and backticks as text.
                    '"\\\\C[2]Villager\\\\C[0] says \\#{hi}\\nto `you`";',
                    "`${name}'s room`",
                    "`echo`",
                ],
            )
            self.assertIn(
                "CommonEvents.json: packed 1 text variable(s) as Ruby strings", lines
            )
            self.assertTrue(
                any("1 text variable(s) run JavaScript" in line for line in lines)
            )
            # The translation's JSON stays as it was written.
            self.assertEqual(path.read_text(encoding="utf-8"), saved)

    def test_archives_extract_their_files_inside_the_game_and_keep_existing_ones(self):
        long = bytes(range(256)) * 5 + b"tail"
        entries = [
            ("Data\\Map001.rvdata2", b"\x04\x08short"),
            ("Graphics\\Pictures\\a:b?.png", long),
            ("..\\..\\outside.txt", b"stays inside"),
            ("Data\\Kept.rvdata2", b"archived copy"),
        ]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            (game / "Data").mkdir(parents=True)
            (game / "Data/Kept.rvdata2").write_bytes(b"translated copy")
            archive = game / "game.rgss3a"
            archive.write_bytes(archive_v3(entries, seed=0xC0FFEE))
            self.assertEqual(rgssad.archives(game), [archive])
            written = rgssad.extract(archive, log=lambda _line: None)
            self.assertEqual(
                files(game),
                {
                    "Data/Kept.rvdata2": b"translated copy",
                    "Data/Map001.rvdata2": b"\x04\x08short",
                    "Graphics/Pictures/ab.png": long,
                    "game.rgss3a": archive.read_bytes(),
                    "outside.txt": b"stays inside",
                },
            )
            self.assertEqual(len(written), 3)

            # A rebuilt archive holds each file's current copy under its
            # archived name, then the added files it lacked.
            (game / "Data/New.rvdata2").write_bytes(b"added")
            rebuilt = root / "rebuilt.rgss3a"
            rgssad.rebuild(
                archive,
                rebuilt,
                game,
                extra=["Data\\New.rvdata2", "Graphics\\Pictures\\ab.png"],
            )
            self.assertEqual(
                contents(rebuilt),
                [
                    ("Data\\Map001.rvdata2", b"\x04\x08short"),
                    ("Graphics\\Pictures\\a:b?.png", long),
                    ("..\\..\\outside.txt", b"stays inside"),
                    ("Data\\Kept.rvdata2", b"translated copy"),
                    ("Data\\New.rvdata2", b"added"),
                ],
            )
            # Unchanged files rebuild the original archive byte for byte.
            (game / "Data/Kept.rvdata2").write_bytes(b"archived copy")
            rgssad.rebuild(archive, rebuilt, game)
            self.assertEqual(rebuilt.read_bytes(), archive.read_bytes())

            older = root / "Game.rgssad"
            older.write_bytes(archive_v1(entries[:2]))
            rgssad.extract(older, root / "xp", log=lambda _line: None)
            self.assertEqual(
                files(root / "xp"),
                {
                    "Data/Map001.rvdata2": b"\x04\x08short",
                    "Graphics/Pictures/ab.png": long,
                },
            )
            with self.assertRaises(rgssad.ArchiveError):
                rgssad.entries(b"RGSSAD\0\x03" + bytes(4))

    def test_setup_sets_an_encrypted_games_archive_aside_and_patches_rebuild_it(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            original = files(FIXTURE / "Data")
            entries = [("Data\\" + name, data) for name, data in original.items()]
            (game / "Game.rgss3a").write_bytes(archive_v3(entries, seed=7))
            actions.run(game, "ace_extract", log=lambda _line: None)
            # The game reads its extracted, translated files only while no
            # archive sits beside Game.exe.
            self.assertEqual(rgssad.archives(game), [])
            kept = game / ".dazedtl/ace/Game.rgss3a"
            self.assertEqual(actions.original_archive(game), kept)
            self.assertEqual(files(game / "Data"), original)
            self.assertTrue((game / "ace_json/System.json").is_file())

            shutil.copy(FIXTURE / "packed/Actors.rvdata2", game / "Data/Actors.rvdata2")
            (game / "Data/Extra.rvdata2").write_bytes(b"tracked addition")
            tracked = ["Data/Actors.rvdata2", "Data/Extra.rvdata2", "Game.ini"]
            self.assertEqual(
                actions.patch_archive(game, root / "patch.rgss3a", tracked),
                "Game.rgss3a",
            )
            patched = dict(contents(root / "patch.rgss3a"))
            self.assertEqual(
                patched,
                {
                    **{"Data\\" + name: data for name, data in original.items()},
                    "Data\\Actors.rvdata2": files(FIXTURE / "packed")["Actors.rvdata2"],
                    "Data\\Extra.rvdata2": b"tracked addition",
                },
            )
            self.assertIsNone(actions.patch_archive(root, root / "none", tracked))

            # A game that arrives converted, its archive still beside Game.exe
            # (as DazedMTLTool left it), shows none of the translation.
            arrived = root / "arrived"
            shutil.copytree(FIXTURE / "ace_json", arrived / "ace_json")
            shutil.copy(
                FIXTURE / "translated/Actors.json", arrived / "ace_json/Actors.json"
            )
            (arrived / "ace_json/Items.json").unlink()
            (arrived / "Game.rgss3a").write_bytes(archive_v3(entries, seed=7))
            with self.assertRaisesRegex(ValueError, "Convert Ace data"):
                actions.run(arrived, "ace_pack", log=lambda _line: None)
            # Converting keeps its translation and adds only what it lacks.
            actions.run(arrived, "ace_extract", log=lambda _line: None)
            self.assertEqual(rgssad.archives(arrived), [])
            self.assertEqual(
                files(arrived / "ace_json"),
                {
                    **files(FIXTURE / "ace_json"),
                    "Actors.json": files(FIXTURE / "translated")["Actors.json"],
                },
            )
            # Packing only the changed exports leaves the other data alone.
            written = actions.run(
                arrived, "ace_pack", log=lambda _line: None, only={"actors"}
            )
            self.assertEqual(written, [arrived / "Data/Actors.rvdata2"])
            self.assertEqual(
                files(arrived / "Data"),
                {
                    **original,
                    "Actors.rvdata2": files(FIXTURE / "packed")["Actors.rvdata2"],
                },
            )
            # Set up's first packing receipt names what packing writes.
            self.assertEqual(
                sorted(actions.packed_files(arrived)),
                sorted(actions.run(arrived, "ace_pack", log=lambda _line: None)),
            )


if __name__ == "__main__":
    unittest.main()
