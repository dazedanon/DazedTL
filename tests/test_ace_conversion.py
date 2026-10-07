"""The built-in Ace preparation writes what the Windows tools it replaced wrote.

fixtures/ace holds made-up, editor-shaped data that Ruby 3.4 dumped, with
RV2JSON 1.2.1's own JSON and packed output; its regenerate.py rebuilds it.
"""

import importlib
import shutil
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.engine import engine_package

ace = engine_package("util/ace")
actions = importlib.import_module(ace.__name__ + ".actions")
rgssad = importlib.import_module(ace.__name__ + ".rgssad")
ruby_marshal = importlib.import_module(ace.__name__ + ".ruby_marshal")
rv2json = importlib.import_module(ace.__name__ + ".rv2json")

FIXTURE = Path(__file__).resolve().parent / "fixtures/ace"
MASK = 0xFFFFFFFF


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


def stream(key, data):
    """RGSSAD file encryption, a byte at a time as RPGMakerDecrypter does."""
    out = bytearray()
    for index, byte in enumerate(data):
        if index and index % 4 == 0:
            key = (key * 7 + 3) & MASK
        out.append(byte ^ key.to_bytes(4, "little")[index % 4])
    return bytes(out)


def archive_v3(entries, seed):
    key = (seed * 9 + 3) & MASK
    key_bytes = key.to_bytes(4, "little")
    # A zero offset ends the table, as in shipped archives.
    offset = 12 + sum(16 + len(name.encode()) for name, _ in entries) + 4
    table, body = bytearray(), bytearray()
    for index, (name, data) in enumerate(entries):
        raw, file_key = name.encode(), 0x9E3779B9 + index
        values = (offset, len(data), file_key, len(raw))
        table += struct.pack("<4I", *(value ^ key for value in values))
        table += bytes(byte ^ key_bytes[i % 4] for i, byte in enumerate(raw))
        body += stream(file_key, data)
        offset += len(data)
    table += struct.pack("<I", key)
    return b"RGSSAD\0\x03" + struct.pack("<I", seed) + table + body


def contents(archive):
    data = archive.read_bytes()
    return [
        (name, rgssad.decrypt(data[offset : offset + size], key))
        for name, offset, size, key in rgssad.entries(data)
    ]


def archive_v1(entries):
    key, out = 0xDEADCAFE, bytearray(b"RGSSAD\0\x01")

    def step(value):
        return (value * 7 + 3) & MASK

    for name, data in entries:
        raw = name.encode()
        out += struct.pack("<I", len(raw) ^ key)
        key = step(key)
        for byte in raw:
            out.append(byte ^ (key & 0xFF))
            key = step(key)
        out += struct.pack("<I", len(data) ^ key)
        key = step(key)
        out += stream(key, data)
    return bytes(out)


class AceConversionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
