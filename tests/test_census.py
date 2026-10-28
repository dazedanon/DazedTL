"""The tool's own count of a game's Japanese text, which decides whether the
assistant's extraction is complete."""

import importlib
import json
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.translation import census

from tests.engine import engine_package

ruby_marshal = importlib.import_module(
    engine_package("util/ace").__name__ + ".ruby_marshal"
)
ACE = Path(__file__).resolve().parent / "fixtures/ace"


class Decoders:
    marshal = staticmethod(ruby_marshal.load)

    @staticmethod
    def rgssad(_data):
        raise ValueError("No archive in this fixture.")

    @staticmethod
    def wolf(_names):
        raise ValueError("No Wolf data in this fixture.")


def command(code, *parameters):
    return {"code": code, "indent": 0, "parameters": list(parameters)}


def asar(files):
    header = {"files": {}}
    body, offset = b"", 0
    for name, data in files.items():
        node = header
        *folders, leaf = name.split("/")
        for folder in folders:
            node = node["files"].setdefault(folder, {"files": {}})
        node["files"][leaf] = {"offset": str(offset), "size": len(data)}
        body += data
        offset += len(data)
    raw = json.dumps(header).encode()
    pickle = struct.pack("<II", len(raw) + 4, len(raw)) + raw
    return struct.pack("<II", 4, len(pickle)) + pickle + body


def xp3(files, scramble=False):
    """A KiriKiri XP3 archive with zlib-compressed members; scramble mimics
    an encrypted archive, whose stored bytes don't match their checksum."""
    body, index = b"", b""
    offset = len(census.XP3_MAGIC) + 8
    for name, data in files.items():
        stored = zlib.compress(data)
        if scramble:
            stored = zlib.compress(bytes(byte ^ 0x5A for byte in data))
        encoded = name.encode("utf-16le")
        info = struct.pack("<IQQH", 0, len(data), len(stored), len(name)) + encoded
        segment = struct.pack("<IQQQ", 1, offset + len(body), len(data), len(stored))
        adler = struct.pack("<I", zlib.adler32(data))
        chunks = b"".join(
            tag + struct.pack("<Q", len(chunk)) + chunk
            for tag, chunk in ((b"info", info), (b"segm", segment), (b"adlr", adler))
        )
        index += b"File" + struct.pack("<Q", len(chunks)) + chunks
        body += stored
    packed = zlib.compress(index)
    header = struct.pack("<BQQ", 1, len(packed), len(index))
    return (
        census.XP3_MAGIC
        + struct.pack("<Q", offset + len(body))
        + body
        + header
        + packed
    )


GAME = {
    "www/data/Map001.json": {
        "displayName": "森",
        "events": [
            None,
            {
                "name": "村長イベント",
                "pages": [
                    {
                        "list": [
                            command(101, "村長顔", 0, 0, 2, "村長"),
                            command(401, "よく来たな。"),
                            command(401, "森へ行け。"),
                            command(108, "メモ：あとで直す"),
                            command(
                                357, "TextPicture", "set", "", {"text": "看板の文字"}
                            ),
                            command(401, "誰にも言うな。"),
                        ]
                    }
                ],
            },
        ],
    },
    "www/data/System.json": {"gameTitle": "森の村", "switches": ["", "フラグ"]},
    "www/data/Animations.json": [None, {"name": "爆発"}],
}


def ypf(names, version=500):
    """A YU-RIS YPF archive's index for these member names, without data."""
    lengths = census._YPF_LENGTHS_500 if version == 500 else census._YPF_LENGTHS
    key = 0xFF ^ (0x36 if version == 500 else 0)
    entries = b"".join(
        struct.pack("<IB", 0, lengths.index(len(name)) ^ 0xFF)
        + bytes(byte ^ key for byte in name.encode("cp932"))
        + bytes(22)
        for name in names
    )
    return (
        struct.pack("<4sIII", b"YPF\0", version, len(names), 32 + len(entries))
        + bytes(16)
        + entries
    )


def scan(files, decoded=None):
    data = {
        name: value
        if isinstance(value, bytes)
        else json.dumps(value, ensure_ascii=False).encode()
        for name, value in files.items()
    }
    return census.scan(sorted(data), data.__getitem__, Decoders(), decoded)


class CensusTests(unittest.TestCase):
    def test_fields_name_structure_never_a_map_event_or_scene(self):
        result = scan(GAME)
        fields = {(entry["kind"], entry["field"]) for entry in result["entries"]}
        event = "events/*/pages/*/list/"
        for expected in (
            ("rpgmaker:map", event + "*[code=401]/parameters/0"),
            # MZ's speaker name and the face file share a command but not a meaning.
            ("rpgmaker:map", event + "*[code=101]/parameters/4"),
            ("rpgmaker:map", event + "*[code=101]/parameters/0"),
            ("rpgmaker:map", event + "*[code=357:TextPicture]/parameters/3/text"),
            ("rpgmaker:system", "gameTitle"),
        ):
            self.assertIn(expected, fields)
        self.assertTrue(
            census.protected("rpgmaker:map", event + "*[code=101]/parameters/4")
        )
        self.assertFalse(
            census.protected("rpgmaker:map", event + "*[code=101]/parameters/0")
        )
        # Keys that are data, such as Japanese names, are wildcarded too.
        keyed = census.read_json("data/Extra.json", '{"村長": {"text": "はい"}}')
        self.assertEqual(keyed[0][2], "*/text")

    def test_code_and_scenario_readers_keep_comments_apart_from_text(self):
        code = census.read_code(
            "js", 'a = "看板"; // 注釈\n/* ヘルプ */ b = /正規/g; c = d / 2;'
        )
        self.assertEqual(
            [(field, text) for _kind, _at, field, text in code],
            [
                ("string", "看板"),
                ("comment", "// 注釈"),
                ("comment", "/* ヘルプ */"),
                ("regex", "正規"),
            ],
        )
        broken = census.read_code("js", 'a = "閉じない')
        self.assertEqual(broken[0][2], "unparsed")
        self.assertTrue(census.protected("js", "unparsed"))
        kag = census.read_kag(
            '#あかね\nこんにちは[p]\n;コメント\n*start|はじまり\n[chara_new name="akane" jname="あかね" storage="あかね.png"]'
        )
        self.assertEqual(
            {(field, text) for _kind, _at, field, text in kag if census.runs(text)},
            {
                ("speaker", "あかね"),
                ("body", "こんにちは"),
                ("comment", ";コメント"),
                ("label_title", "はじまり"),
                ("tag:chara_new.jname", "あかね"),
                ("tag:chara_new.storage", "あかね.png"),
            },
        )
        renpy = census.read_renpy('# メモ\ne "やあ"\ndefine e = Character("エリ")\n')
        self.assertEqual(
            [(field, text) for _kind, _at, field, text in renpy],
            [("comment", "# メモ"), ("say", "やあ"), ("stmt:define", "エリ")],
        )

    def test_units_that_split_messages_line_by_line_are_counted(self):
        # A unit per 401 line nearly doubled a game's API requests; a
        # nameplate line kept as the speaker must not look like a split.
        message = ["リリ", "よく来たな。", "森へ行け。", "気をつけて。"]
        result = scan(
            {
                "www/data/CommonEvents.json": [
                    None,
                    {
                        "list": [
                            command(101, "", 0, 0, 2),
                            *(command(401, line) for line in message),
                            command(101, "", 0, 0, 2),
                            command(401, "ああ。"),
                            command(401, "そうだ。"),
                        ]
                    },
                ]
            }
        )
        # (split, judged): only messages of three or more lines are judged,
        # once their lines after the first are extracted.
        for sources, expected in (
            (message + ["ああ。", "そうだ。"], (1, 1)),
            (["リリ\nよく来たな。\n森へ行け。\n気をつけて。"], (0, 1)),
            (["よく来たな。\n森へ行け。\n気をつけて。", "リリ"], (0, 1)),
            (["よく来たな。"], (0, 0)),
        ):
            with self.subTest(sources=sources):
                self.assertEqual(census.split_messages(result, sources), expected)

    def test_coverage_counts_extracted_set_aside_and_uncovered_runs(self):
        result = scan(GAME)
        # An extractor may join a message's lines; runs still match.
        sources = ["よく来たな。\n森へ行け。", "看板の文字"]
        report, uncovered = census.coverage(result, sources, ["村長"], [])
        self.assertEqual(
            {(row["kind"], row["field"]) for row in census.summary(uncovered)},
            {
                ("rpgmaker:map", "events/*/pages/*/list/*[code=401]/parameters/0"),
                ("rpgmaker:map", "displayName"),
                ("rpgmaker:system", "gameTitle"),
            },
        )
        self.assertNotIn(
            "誰にも", json.dumps(census.summary(uncovered), ensure_ascii=False)
        )
        self.assertEqual(
            {(rule["field"], rule["reason"]) for rule in report["rules"]},
            {
                ("**/*[code=108]/**", "comment"),
                ("**/*[code=101]/parameters/0", "asset_name"),
                ("events/*/name", "identifier"),
                ("switches/*", "identifier"),
                # Editor labels, though other database names are player text.
                ("*/name", "identifier"),
            },
        )
        fields = {**census.fields(result), "json": {"*/text"}}
        for rule, refused in (
            (
                {"kind": "rpgmaker:map", "field": "**", "reason": "comment"},
                "player reads",
            ),
            (
                {"kind": "rpgmaker:map", "field": "events/3/**", "reason": "comment"},
                "matches a census field",
            ),
            (
                {
                    "kind": "rpgmaker:map",
                    "field": "displayName",
                    "reason": "identifier",
                    "file": "www/data/Map002.json",
                },
                "file pattern",
            ),
            (
                {
                    "kind": "rpgmaker:system",
                    "field": "switches/*",
                    "reason": "identifier",
                    "values": ["フラグ 2"],
                },
                "one Japanese run",
            ),
            (
                {"kind": "rpgmaker:system", "field": "gameTitle", "reason": "content"},
                "reason",
            ),
        ):
            with self.subTest(rule=rule), self.assertRaisesRegex(ValueError, refused):
                census.rules_input(
                    {"version": 1, "rules": [rule]}, fields, census.files(result)
                )
        rules = census.rules_input(
            {
                "version": 1,
                "rules": [
                    {
                        "kind": "rpgmaker:map",
                        "field": "**/*[code=357:*]/**",
                        "reason": "not_displayed",
                    }
                ],
            },
            fields,
        )
        report, _uncovered = census.coverage(result, sources[:1], ["村長"], rules)
        self.assertIn(
            {
                "by": "assistant",
                "kind": "rpgmaker:map",
                "field": "**/*[code=357:*]/**",
                "reason": "not_displayed",
                "runs": 1,
            },
            report["rules"],
        )

    def test_punctuation_only_text_is_listed_apart_from_coverage(self):
        # Lines with Japanese punctuation but no letters, which Guided writes
        # without a request, shipped in Japanese form when no unit held them.
        event = {
            "name": "",
            "pages": [
                {
                    "list": [
                        command(401, "「……」"),
                        command(401, "！？"),
                        command(401, "よく来たな。　"),
                        command(108, "！！"),
                        command(357, "Popup", "show", "", {"text": "？"}),
                        command(401, "　"),
                        command(401, "１００"),
                    ]
                }
            ],
        }
        result = scan({"www/data/Map001.json": {"events": [None, event]}})
        self.assertEqual(result["version"], census.VERSION)
        self.assertEqual(
            [entry["runs"] for entry in result["entries"]], [["よく来たな。　"]]
        )
        rules = census.rules_input(
            {
                "version": 1,
                "rules": [
                    {
                        "kind": "rpgmaker:map",
                        "field": "**/*[code=357:*]/**",
                        "reason": "not_displayed",
                    }
                ],
            },
            census.fields(result),
        )
        # The comment and the rule's plugin command are set aside; a unit
        # joining a message's lines still covers its punctuation-only one.
        for sources, extracted in (
            ([], 0),
            (["「……」\n！？"], 3),
            (["！？"], 1),
            (["よく来たな。\n！？"], 1),
        ):
            with self.subTest(sources=sources):
                report, missing = census.unsent(result, sources, rules)
                self.assertEqual(report, {"runs": 3, "extracted": extracted})
                self.assertEqual(
                    sum(len(entry["runs"]) for entry in missing), 3 - extracted
                )
        coverage, _uncovered = census.coverage(result, ["「……」\n！？"], [], rules)
        self.assertEqual(
            (coverage["runs"], coverage["extracted"], coverage["untraced"]), (1, 0, 0)
        )

    def test_comments_a_plugin_shows_players_count_as_their_text(self):
        # MPP_ChoiceEX shows the lines under a choice help marker; a census
        # that set every comment aside read full coverage with them Japanese.
        plugins = [
            {
                "name": "MPP_ChoiceEX",
                "status": True,
                "parameters": {"Choice Help Commands": '["<Help>"]'},
            }
        ]
        page = [
            # A malformed command stopped the whole census; the commands
            # after it are counted as before.
            {"code": [408], "parameters": []},
            command(102, ["森", "村"], -1, 0, 2, 0),
            command(402, 0, "森"),
            command(108, "選択肢ヘルプ"),
            command(408, "森へ向かいます。"),
            command(408, "(1/2)"),
            command(402, 1, "村"),
            command(108, "<Help>"),
            command(408, "村に残ります。"),
            command(404),
            command(108, "メモ"),
            command(408, "あとで直す。"),
        ]
        game = {
            "www/js/plugins.js": f"var $plugins =\n{json.dumps(plugins)};\n".encode(),
            "www/data/Map001.json": {
                "events": [None, {"name": "", "pages": [{"list": page}]}]
            },
        }
        result = scan(game)
        help_field = "events/*/pages/*/list/*[code=408:help]/parameters/0"
        self.assertTrue(census.protected("rpgmaker:map", help_field))
        sources = ["森", "村"]
        _report, uncovered = census.coverage(result, sources, [], [])
        self.assertEqual(
            census.summary(uncovered),
            [{"kind": "rpgmaker:map", "field": help_field, "runs": 2}],
        )
        with self.assertRaisesRegex(ValueError, "player reads"):
            census.rules_input(
                {
                    "version": 1,
                    "rules": [
                        {
                            "kind": "rpgmaker:map",
                            "field": "**/*[code=408:help]/**",
                            "reason": "comment",
                        }
                    ],
                },
                census.fields(result),
            )
        # The markers and other comments stay aside; the help lines, joined
        # as one unit, cover it.
        sources.append("森へ向かいます。\n(1/2)")
        sources.append("村に残ります。")
        report, uncovered = census.coverage(result, sources, [], [])
        self.assertEqual((uncovered, report["set_aside"]), ([], 5))
        # A decoded dump may hold the data before the plugin list it shows.
        dumped = census.scan(
            [],
            {}.get,
            Decoders(),
            [
                (name, json.dumps(game[name], ensure_ascii=True).encode())
                if name.endswith(".json")
                else (name, game[name])
                for name in sorted(game)
            ],
        )
        self.assertEqual(
            census.coverage(dumped, sources[:3], [], [])[0]["uncovered"], 1
        )
        # A marker the game's plugins don't list is no help.
        del game["www/js/plugins.js"]
        _report, uncovered = census.coverage(scan(game), sources[:3], [], [])
        self.assertEqual(uncovered, [])

    def test_plugins_count_as_the_game_loads_them(self):
        # The assistant translated plugins the game never runs: a disabled
        # entry, a plugin's later entry, DazedTL's own update check, and the
        # choice help markers MPP_ChoiceEX finds its comments by.
        plugins = [
            {"name": "Old", "status": False, "parameters": {"text": "古い文章"}},
            {"name": "Hud", "status": True, "parameters": {"label": "所持金"}},
            {"name": "Hud", "status": True, "parameters": {"label": "使わない"}},
            {"name": "Dazed_Update", "status": True, "parameters": {"t": "更新"}},
            {
                "name": "MPP_ChoiceEX",
                "status": True,
                "parameters": {"Choice Help Commands": '["選択肢ヘルプ"]'},
            },
        ]
        game = {
            "www/js/plugins.js": f"var $plugins =\n{json.dumps(plugins)};\n".encode(),
            "www/js/plugins/Old.js": 'var a = "古い";'.encode(),
            "www/js/plugins/Hud.js": 'var b = "表示";'.encode(),
            "www/js/plugins/Dazed_Update.js": 'var c = "更新";'.encode(),
        }
        data = {name: value for name, value in game.items()}
        result = census.scan(
            sorted(data),
            data.__getitem__,
            Decoders(),
            own=["www/js/plugins/Dazed_Update.js"],
        )
        counted = {(entry["file"], *entry["runs"]) for entry in result["entries"]}
        self.assertEqual(
            counted,
            {
                ("www/js/plugins.js", "所持金"),
                ("www/js/plugins.js", "選択肢ヘルプ"),
                ("www/js/plugins/Hud.js", "表示"),
            },
        )
        report, uncovered = census.coverage(result, ["所持金", "表示"], [], [])
        self.assertEqual((uncovered, report["set_aside"]), ([], 1))
        # MZ loads one plugin by its file name, whatever folder it is in.
        plugins[2]["name"] = "Other/Hud"
        game["www/js/plugins.js"] = f"var $plugins =\n{json.dumps(plugins)};\n".encode()
        for core, runs in (
            ({}, {"所持金", "使わない"}),
            ({"www/js/rmmz_core.js": b""}, {"所持金"}),
        ):
            files = {**game, **core}
            loaded = census.scan(sorted(files), files.__getitem__, Decoders())
            self.assertEqual(
                {
                    run
                    for entry in loaded["entries"]
                    if entry["field"].endswith("/label")
                    for run in entry["runs"]
                },
                runs,
            )

    def test_an_english_game_counts_its_english_and_units_cover_it(self):
        # An English game's text is Latin letters: none of it may read as
        # finished, and codes, tags and Japanese are no English runs.
        files = {
            "data/Map001.json": {
                "displayName": "Starting Village",
                "events": [
                    None,
                    {
                        "pages": [
                            {
                                "list": [
                                    command(401, ["\\C[2]Mika\\C[0]: Welcome!<br>"]),
                                    command(401, ["ようこそ"]),
                                ]
                            }
                        ]
                    },
                ],
            }
        }
        data = {name: json.dumps(value).encode() for name, value in files.items()}
        result = census.scan(
            sorted(data), data.__getitem__, Decoders(), language="English"
        )
        self.assertEqual(
            [entry["runs"] for entry in result["entries"]],
            [["Starting Village"], ["Mika", "Welcome!"]],
        )
        _report, uncovered = census.coverage(
            result, ["Starting Village", "\\C[2]Mika\\C[0]: Welcome!<br>"], [], []
        )
        self.assertEqual(uncovered, [])

    def test_mod_loaders_and_documents_beside_a_game_are_not_its_text(self):
        result = scan(
            {
                "BepInEx/Translation/ja/Text/_AutoGeneratedTranslations.txt": "はい=Yes".encode(),
                "readme.txt": "遊び方".encode(),
                "0.txt": "台詞です".encode(),
                "Game_Data/StreamingAssets/aa/catalog.json": {
                    "m_InternalIds": ["Assets/立ち絵.png"]
                },
            }
        )
        report, uncovered = census.coverage(result, [], [], [])
        self.assertEqual(
            {(entry["kind"], entry["field"]) for entry in uncovered},
            {("text.txt", "line")},
        )
        self.assertEqual(
            {rule["reason"] for rule in report["rules"]},
            {"not_displayed", "identifier"},
        )

    def test_wolf_lines_are_typed_by_wolfdawn_and_always_translated(self):
        document = {
            "kind": "map",
            "scenes": [
                {
                    "event": 1,
                    "lines": [
                        {
                            "speaker_src": "literal_line1_lowconf",
                            "source": "リリ\nこんにちは",
                            "text": "",
                        },
                        {"speaker_src": "ui", "source": "個", "text": ""},
                    ],
                }
            ],
        }
        rows = census.read_wolf(document) or []
        self.assertEqual(
            [(kind, field) for kind, _at, field, _text in rows],
            [("wolf:map", "message"), ("wolf:map", "ui")],
        )
        self.assertTrue(census.protected("wolf:db", "line"))

    def test_a_wolf_pro_game_hands_wolfdawn_its_key_and_renamed_archives(self):
        # A Wolf Pro game with its own archive key keeps it beside archives it
        # may rename. Left out of the copy WolfDawn reads, the key made the
        # census count four runs of such a game instead of every line.
        files = {
            "Data/BasicData.wolf": b"\x12encrypted header",
            "Data/MapData.pak": b"DX archive",
            "Data/Game.wolf": b"\x11key",
            "Data/Picture.wolf": b"DX pictures",
            "Content/Paks/Data.pak": b"PK another engine",
        }
        names = sorted(files)

        def head(name, size):
            return files[name][:size]

        self.assertEqual(
            sorted(census.wanted(names, head)),
            ["Data/BasicData.wolf", "Data/Game.wolf", "Data/MapData.pak"],
        )
        handed = []

        class Wolf(Decoders):
            @staticmethod
            def wolf(names):
                handed.extend(names)
                return []

        result = census.scan(names, files.get, Wolf(), peek=head)
        self.assertEqual(handed, ["Data/BasicData.wolf", "Data/MapData.pak"])
        self.assertEqual(result["opened"], handed)
        self.assertEqual(result["needs_dump"], ["Content/Paks/Data.pak"])
        # The engine's copy of WolfDawn's rule agrees on the same files.
        wolfdawn = engine_package("util/wolfdawn")
        with TemporaryDirectory() as temporary:
            for name, data in files.items():
                path = Path(temporary, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            data = Path(temporary, "Data")
            self.assertEqual(
                [path.name for path in wolfdawn.list_archives(data)],
                ["BasicData.wolf", "MapData.pak", "Picture.wolf"],
            )
            self.assertEqual(wolfdawn.pro_key_file(data), data / "Game.wolf")

    def test_ace_data_archives_and_unreadable_containers(self):
        names = [
            path.relative_to(ACE).as_posix()
            for path in sorted((ACE / "Data").iterdir())
        ]
        result = census.scan(names, lambda name: (ACE / name).read_bytes(), Decoders())
        fields = census.fields(result)
        self.assertIn(
            "events/*/pages/*/list/*[code=401]/parameters/0", fields["rgss:map"]
        )
        self.assertTrue(
            census.protected(
                "rgss:map", "events/*/pages/*/list/*[code=401]/parameters/0"
            )
        )
        self.assertIn("string", fields["rgss:scripts"])
        scenario = {"scenario/first.ks": "#あかね\nようこそ[p]".encode()}
        result = scan(
            {"data.xp3": xp3(scenario), "patch.xp3": xp3(scenario, scramble=True)}
        )
        self.assertEqual(
            (result["opened"], result["needs_dump"]), (["data.xp3"], ["patch.xp3"])
        )
        self.assertEqual(
            {entry["field"] for entry in result["entries"]}, {"speaker", "body"}
        )
        packed = asar({"data/scenario/first.ks": "#あかね\nようこそ[p]".encode()})
        result = scan(
            {"resources/app.asar": packed, "Game_Data/sharedassets0.assets": b"\0"}
        )
        self.assertEqual(result["opened"], ["resources/app.asar"])
        self.assertEqual(result["needs_dump"], ["Game_Data/sharedassets0.assets"])
        self.assertEqual(
            {entry["field"] for entry in result["entries"]}, {"speaker", "body"}
        )
        dumped = census.scan(
            ["Game_Data/sharedassets0.assets"],
            None,
            Decoders(),
            [
                (
                    "ExportedProject/Assets/Dialogue.asset",
                    "  m_Text: こんにちは\n".encode(),
                )
            ],
        )
        self.assertEqual(
            [(entry["field"], entry["source"]) for entry in dumped["entries"]],
            [("m_Text", "assistant_dump")],
        )
        self.assertTrue(dumped["decoded"])

    def test_decoded_scripts_take_rules_and_other_languages_are_set_aside(self):
        # YU-RIS media archives hold no text, so only scripts need decoding.
        names = ["pac/ysbin.ypf", "pac/bgm.ypf", "pac/old.ypf", "data/yst00001.ybn"]
        archives = {
            "pac/ysbin.ypf": ypf(["ysbin\\yst00001.ybn", "ysbin\\ysc.ybn"]),
            "pac/bgm.ypf": ypf(["bgm\\bgm01.ogg", "bgm\\bgm02.ogg"], version=494),
            # An index cut short can't be read, so it is decoded to be sure.
            "pac/old.ypf": ypf(["a.ybn", "b.ogg"])[:40],
        }
        result = census.scan(
            names,
            None,
            Decoders(),
            [
                ("ysbin/main.yst", 'IF[$s=="上2"]\nあら、こんにちは。'.encode()),
                # A dump's top files are the game's text, never a readme.
                ("title.txt", "タイトル".encode()),
                (
                    "TextAsset/Event.txt",
                    "セリフ,こんにちは\nセリフ,またね\nセリフ,セリフ".encode(),
                ),
                (
                    "TextAsset/Chinese.txt",
                    "default\nこんにちは,你好\nまたね,再見".encode(),
                ),
            ],
            peek=lambda name, size: archives[name][:size],
        )
        self.assertEqual(result["opened"], ["pac/bgm.ypf"])
        self.assertEqual(
            result["needs_dump"], ["data/yst00001.ybn", "pac/old.ypf", "pac/ysbin.ypf"]
        )
        # Scripts' Japanese command words and comparisons are the assistant's
        # to set aside; the extracted lines cover the rest, even where a
        # command word is also the text a line shows.
        rules = census.rules_input(
            {
                "version": 1,
                "rules": [
                    {
                        "kind": "text.txt",
                        "field": "column:0",
                        "reason": "identifier",
                        "values": ["セリフ"],
                    },
                    {
                        "kind": "text.txt",
                        "field": "table:key",
                        "reason": "identifier",
                        "file": "TextAsset/*",
                    },
                    {
                        "kind": "script:yst",
                        "field": "line",
                        "reason": "script_code",
                        "values": ["上"],
                    },
                ],
            },
            census.fields(result),
            census.files(result),
        )
        report, uncovered = census.coverage(
            result,
            ["あら、こんにちは。", "こんにちは", "またね", "セリフ", "タイトル"],
            [],
            rules,
        )
        self.assertEqual((report["uncovered"], uncovered), (0, []))
        self.assertEqual(
            {(rule["by"], rule["reason"], rule["runs"]) for rule in report["rules"]},
            {
                ("tool", "other_language", 2),
                ("assistant", "identifier", 3),
                ("assistant", "identifier", 2),
                ("assistant", "script_code", 1),
            },
        )
