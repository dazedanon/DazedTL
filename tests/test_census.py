"""The tool's own count of a game's Japanese text, which decides whether the
assistant's extraction is complete."""

import importlib
import json
import struct
import unittest
from pathlib import Path

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
}


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
            },
        )
        fields = census.fields(result)
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
                    "file": "x",
                },
                "only for code",
            ),
            (
                {"kind": "rpgmaker:system", "field": "gameTitle", "reason": "content"},
                "reason",
            ),
        ):
            with self.subTest(rule=rule), self.assertRaisesRegex(ValueError, refused):
                census.rules_input({"version": 1, "rules": [rule]}, fields)
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
