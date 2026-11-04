"""Compare models (translation/compare.py, compatibility/compare.py): the
lines a comparison sends and shows, and its paid approval."""

import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dazedtl.compatibility.compare import END, cut, rows, sources
from dazedtl.compatibility.compare_units import editable, glossary
from dazedtl.storage import write_json
from dazedtl.translation.compare import Compare
from dazedtl.translation.project import MANUAL_UNITS
from util.paths import GLOSSARY_BASE_SEPARATOR


def command(code, parameters, **extra):
    return {"code": code, "indent": 0, "parameters": parameters, **extra}


def page(*commands):
    return {"pages": [{"list": [*commands, command(0, [])]}]}


class LinesTests(unittest.TestCase):
    def test_the_cut_keeps_whole_pages_and_translations_pair_by_their_source(self):
        # The engine joins a message's rows into one command, so a line's
        # place in the translated file moves; a model's line once landed
        # beside another line, or nowhere.
        original = {
            "displayName": "はじまりの村",
            "events": [
                None,
                page(
                    command(101, ["", 0, 0, 2, "村長"]),
                    command(401, ["おお、ミカよ。"]),
                    command(401, ["森の奥に杖が眠っている。"]),
                    command(101, ["", 0, 0, 2, "ミカ"]),
                    command(401, ["行ってきます！"]),
                ),
                page(
                    command(101, ["", 0, 0, 2, "少年"]),
                    command(401, ["また魔法の練習？"]),
                ),
            ],
        }
        value, kept = cut("Map001.json", original, "dialogue", 2)
        assert isinstance(value, dict)
        # The second line's page stays whole; the next page ends at once.
        self.assertEqual(value["events"][2]["pages"][0]["list"], [END])
        self.assertEqual(len(original["events"][2]["pages"][0]["list"]), 3)
        shown = sources(kept)
        self.assertEqual(
            [(row["speaker"], row["source"]) for row in shown],
            [
                ("村長", "おお、ミカよ。\n森の奥に杖が眠っている。"),
                ("ミカ", "行ってきます！"),
                ("", "はじまりの村"),
            ],
        )
        translated = {
            "displayName": "Starting Village",
            "events": [
                None,
                page(
                    command(101, ["", 0, 0, 2, "Village Chief"], _original="村長"),
                    command(
                        401,
                        ["Ah, Mika.\nA staff sleeps deep in the woods."],
                        _original="おお、ミカよ。\n森の奥に杖が眠っている。",
                    ),
                    command(101, ["", 0, 0, 2, "Mika"], _original="ミカ"),
                    command(401, ["I'm off!"], _original="行ってきます！"),
                ),
                value["events"][2],
            ],
        }
        found = rows("Map001.json", translated, "dialogue", kept)
        self.assertEqual(
            [found.get(row["id"]) for row in shown],
            [
                {
                    "speaker": "Village Chief",
                    "text": "Ah, Mika.\nA staff sleeps deep in the woods.",
                },
                {"speaker": "Mika", "text": "I'm off!"},
                {"speaker": "", "text": "Starting Village"},
            ],
        )

    def test_a_database_cut_keeps_the_entries_before_the_last_line(self):
        items = [None, {"name": "薬", "description": "体力を回復する"}, {"name": "剣"}]
        value, kept = cut("Items.json", items, "database", 2)
        self.assertEqual(value[2], None)
        self.assertEqual(len(kept), 2)


class GlossaryTests(unittest.TestCase):
    def test_a_test_glossary_keeps_the_games_base_section_once(self):
        # Tune starts from the glossary the Context editor shows; sending the
        # whole file back appended the shipped base a second time.
        held = "村長 (Village Chief)\n\n" + GLOSSARY_BASE_SEPARATOR + "魔法 (Magic)\n"
        shown = editable(held)
        self.assertEqual(shown, "村長 (Village Chief)")
        changed = glossary(held, shown + "\nミカ (Mika)")
        self.assertEqual(changed.count(GLOSSARY_BASE_SEPARATOR), 1)
        self.assertEqual(editable(changed), "村長 (Village Chief)\nミカ (Mika)")


class Operations:
    """The app's operation runner, recording the plans it starts."""

    def __init__(self, root):
        self.root = root
        self.jobs = {}

    def start(self, plan):
        identity = uuid.uuid4().hex
        write_json(self.root / identity / "plan.json", plan)
        self.jobs[identity] = {
            "id": identity,
            "action": plan["action"],
            "project_id": plan["project_id"],
            "status": "running",
            "created": str(len(self.jobs)),
            "message": "",
        }
        return self.jobs[identity]


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.game = root / "game"
        self.write_units("村長、ようこそ。")
        connection = {"id": "c1", "name": "Stand-in"}
        self.operations = Operations(root / "operations")
        self.compare = Compare(
            SimpleNamespace(
                idle=lambda **_: None,
                projects=SimpleNamespace(
                    get=lambda _id: {
                        "id": "p1",
                        "method": "manual",
                        "source": str(self.game),
                    }
                ),
                translation=SimpleNamespace(
                    workspace=root / "workspace",
                    api_configuration=lambda mode, _root, choice: (
                        {"mode": mode, "model": choice.model, "rates": {}},
                        None,
                    ),
                    project=lambda _id: (
                        {},
                        SimpleNamespace(read=lambda: {"options": {"mode": "agent"}}),
                    ),
                ),
                settings=SimpleNamespace(
                    _read=dict,
                    _connection=lambda _state, _id: connection,
                    _configured=lambda _connection: True,
                    convert_quotes=lambda: True,
                    source_language=lambda: "Japanese",
                    language=lambda: "English",
                ),
                backend=SimpleNamespace(
                    manual=SimpleNamespace(allow_providers=False),
                    operations=self.operations,
                ),
            )
        )

    def write_units(self, source):
        write_json(
            self.game / MANUAL_UNITS,
            {
                "version": 1,
                "units": [
                    {"id": "u1", "scene": "s1", "group": "Map001", "source": source}
                ],
            },
        )

    def estimated(self):
        job = self.compare.estimate(
            "p1",
            "versus",
            "Map001",
            0,
            [
                {"connection_id": "c1", "model": "a"},
                {"connection_id": "c1", "model": "b"},
            ],
        )
        job.update(
            status="complete",
            result={"models": [{"index": 0, "estimate": {"live_cost": 0.01}}]},
        )
        return job["id"]

    def test_a_price_is_approved_once_and_only_while_its_lines_are_the_same(self):
        estimate = self.estimated()
        started = self.compare.translate("p1", estimate)
        plan = json.loads(
            (self.operations.root / started["id"] / "plan.json").read_text(
                encoding="utf-8"
            )
        )
        # Only the model the estimate priced is sent.
        self.assertEqual([row["model"] for row in plan["options"]["candidates"]], ["a"])
        # A second click, or a retry, sends nothing again.
        with self.assertRaisesRegex(ValueError, "already translated"):
            self.compare.translate("p1", estimate)
        estimate = self.estimated()
        self.write_units("村長、よく来たな。")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.compare.translate("p1", estimate)
        self.assertEqual(
            sum(
                job["action"] == "compare_translate"
                for job in self.operations.jobs.values()
            ),
            1,
        )
