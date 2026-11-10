"""Text QA's helper steps apply findings only through the app's publication."""

import hashlib
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from dazedtl.api.contracts.guided import QaState, TextQaCheck, TextQaStatus
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.storage import write_json
from dazedtl.translation import census, progress_report, qa_size, units_qa
from dazedtl.translation.operations import census_path, execute
from dazedtl.translation.project import WORK, review_focus
from dazedtl.translation.result_checks import CHECK_FILE, CHECK_STEP, CHECK_VERSION
from dazedtl.translation.results import Results, exported_translations
from dazedtl.translation.run_compiler import SCOPE_RULES
from dazedtl.translation.text_qa import (
    REVIEW_OFF,
    UNITS_APPLIED,
    UNTRANSLATED_FILE,
    UNTRANSLATED_STEP,
    TextQA,
)
from pydantic import TypeAdapter
from util import rpgmaker_qa
from util.rpgmaker_qa_preflight import preflight

from tests import test_workflow


def fake_guided(folder, qa, method="guided"):
    calls = []
    jobs = {}

    def execute(_project_id, token):
        calls.append(("execute", token))
        jobs[token + "-job"] = {"status": "complete", "message": ""}
        return {"id": token + "-job"}

    guided = SimpleNamespace(
        projects=SimpleNamespace(get=lambda _id: {"backend_id": "native"}),
        record=lambda _id: (
            {},
            {"id": "native", "source": str(folder), "data": str(Path(folder) / "data")},
        ),
        saved_form=lambda _id: {"text": {"focus": "release"}},
        qa_focus=lambda _id: "release",
        backend=SimpleNamespace(
            guided_text_state=lambda _native, _focus: {"qa": qa},
            operations=SimpleNamespace(jobs=jobs, active=""),
            workflows=SimpleNamespace(folder=lambda _id: Path(folder)),
        ),
        preview=lambda _id, action, _files, options: (
            calls.append(("preview", action, options)) or {"token": action}
        ),
        execute=execute,
        path=lambda _id, name: Path(folder) / f"{name}.json",
        translation=SimpleNamespace(
            project=lambda _id: (
                {"method": method},
                SimpleNamespace(root=Path(folder), read=lambda: {"options": {}}),
            ),
            run=lambda _id, job: {"status": jobs[job]["status"], "message": ""},
            workspace=Path(folder) / "workspace",
            jobs=SimpleNamespace(
                store=SimpleNamespace(declined_sources=lambda _id: [])
            ),
        ),
    )
    return guided, calls


class TextQATests(unittest.TestCase):
    def test_apply_publishes_every_finding_as_one_batch(self):
        # The assistant once applied corrections with engine commands that
        # wrote the game directly, so History could not restore them.
        with TemporaryDirectory() as folder:
            task = Path(folder) / "task"
            task.mkdir()
            (task / "task.json").write_text(
                json.dumps({"schema": rpgmaker_qa.TASK_SCHEMA}), encoding="utf-8"
            )
            (task / "checkpoint.json").write_text(
                json.dumps({"schema": rpgmaker_qa.CHECKPOINT_SCHEMA}), encoding="utf-8"
            )
            qa = {
                "task": str(task),
                "current": True,
                "applied": False,
                "message": "",
                "findings": [{"id": "QA-0001"}, {"id": "QA-0002"}],
                "questions": [{"id": "Map001.json#/1", "proposal": "Better."}],
                "status": {"stage": "complete"},
            }
            guided, calls = fake_guided(folder, qa)
            service = TextQA(guided)  # type: ignore[arg-type]
            # An open question waits for the user's answer, given in the app.
            with self.assertRaisesRegex(ValueError, "user's choice"):
                service.run("project", "apply")
            service.run("project", "choose", question="Map001.json#/1", choice="use")
            # The task keeps the answer, where its ledger reads it.
            self.assertEqual(rpgmaker_qa.answers(task), {"Map001.json#/1": "use"})
            qa["questions"][0]["choice"] = "use"
            applied = service.run("project", "apply")
            # The job reports its end before its worker exits; the next step
            # waits for the worker, so the apply still reads as running.
            guided.backend.operations.active = applied["operation"]["id"]
            self.assertEqual(
                service.run("project", "status")["operation"]["status"], "running"
            )
            guided.backend.operations.active = ""
            # The apply is its own checkpoint; an assistant started before
            # then still saves one, which changes nothing.
            state = service.run("project", "checkpoint")
            self.assertEqual(
                calls,
                [
                    (
                        "preview",
                        "qa_apply",
                        {
                            "focus": "release",
                            "task": str(task),
                            "findings": ["QA-0001", "QA-0002"],
                            "proposals": ["Map001.json#/1"],
                        },
                    ),
                    ("execute", "qa_apply"),
                ],
            )
            self.assertEqual(state["operation"]["kind"], "apply")
            # Applied findings are not applied twice.
            qa["applied"] = True
            for row in qa["findings"] + qa["questions"]:
                row["state"] = "applied"
            with self.assertRaisesRegex(ValueError, "already applied"):
                service.run("project", "apply")
            # A follow-up round after the apply applies only its own finding;
            # the task read as applied, so it never applied.
            qa["applied"] = False
            qa["findings"].append({"id": "QA-0003"})
            service.run("project", "apply")
            self.assertEqual(calls[-2][2]["findings"], ["QA-0003"])
            self.assertEqual(calls[-2][2]["proposals"], [])
            qa["applied"] = True
            qa["findings"][-1]["state"] = "applied"
            # Undo's reply meets the helper contract; one that did not made
            # the page report a finished undo as failed before its checkpoint.
            undone = service.run("project", "undo", findings=["QA-0001"])
            _close_contracts()
            TypeAdapter(TextQaStatus).validate_json(json.dumps(undone), strict=True)
            self.assertEqual(undone["operation"]["kind"], "undo")
            # Apply again runs an apply batch of its own.
            again = service.run("project", "reapply", findings=["QA-0001"])
            TypeAdapter(TextQaStatus).validate_json(json.dumps(again), strict=True)
            self.assertEqual(
                calls[-2],
                (
                    "preview",
                    "qa_apply",
                    {
                        "focus": "release",
                        "task": str(task),
                        "findings": ["QA-0001"],
                        "proposals": [],
                    },
                ),
            )
            # A task the app can't read sent the assistant to prepare again,
            # which returned it, apply said to finish review and undo failed
            # without a reason; each names the task and its error instead.
            qa.clear()
            qa.update(
                current=False,
                applied=False,
                message="DazedTL isn't allowed to read this QA task's files.",
                findings=[],
                questions=[],
                status={},
                unreadable={"path": str(task), "error": "PermissionError: denied"},
            )
            step = service.run("project", "status")["next"]
            self.assertIn(f"{task}: PermissionError: denied", step)
            for step_name in ("apply", "undo"):
                with self.assertRaises(ValueError) as refused:
                    service.run("project", step_name, findings=["QA-0001"])
                self.assertEqual(str(refused.exception), step)

    def test_start_over_waits_for_running_steps_and_clears_the_playtest_if_asked(
        self,
    ):
        # A task stuck in review offered only Copy QA task, and preparing
        # again resumed it; starting over must not race a running step.
        with TemporaryDirectory() as folder:
            root = Path(folder)
            qa = {
                "current": False,
                "applied": False,
                "status": {},
                "findings": [],
                "questions": [],
                "message": "No QA task prepared for this focus.",
            }
            guided, _calls = fake_guided(folder, qa)
            operations = guided.backend.operations
            operations.lock = threading.Lock()
            operations.running = lambda: bool(operations.active)
            service = TextQA(guided)  # type: ignore[arg-type]
            pointer = root / "text-qa-release.json"
            playtest = root / "playtest.json"
            stops = root / "playtest-stops.json"

            def prepared(key):
                task = root / "text-qa/project/release" / key
                task.mkdir(parents=True)
                pointer.write_text(json.dumps({"task": str(task)}), encoding="utf-8")
                for path in (playtest, stops, root / "playtest/report/report.json"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}", encoding="utf-8")
                return task

            task = prepared("a" * 16)
            operations.jobs["play"] = {"label": "Play the game"}
            operations.active = "play"
            with self.assertRaisesRegex(ValueError, "Wait for Play the game"):
                service.start_over("project", True)
            self.assertTrue(pointer.exists() and task.is_dir() and playtest.exists())
            operations.active = ""
            state = service.start_over("project")
            self.assertFalse(pointer.exists() or task.exists())
            self.assertTrue(task.with_name(task.name + "-discarded").is_dir())
            self.assertEqual(state["next"], "Run qa --prepare.")
            # The playtest's results stay unless the user clears them; its
            # saved stops stay either way.
            self.assertTrue(playtest.exists())
            prepared("b" * 16)
            service.start_over("project", True)
            self.assertFalse(playtest.exists() or (root / "playtest").exists())
            self.assertTrue(stops.exists())
            with self.assertRaisesRegex(ValueError, "No QA task"):
                service.start_over("project")

    def test_assistant_led_start_over_reopens_the_assistants_qa(self):
        # After a start over, Progress kept the assistant's report of QA as
        # done, and a resumed assistant could go on to Patch unreviewed.
        with TemporaryDirectory() as folder:
            root = Path(folder)
            qa = {
                "current": False,
                "applied": False,
                "status": {},
                "findings": [],
                "questions": [],
                "message": "No QA task prepared for this focus.",
            }
            guided, _calls = fake_guided(folder, qa, method="len")
            published = []
            guided.translation.engine = SimpleNamespace(
                progress=lambda _source, _options, report: published.append(report)
            )
            guided.backend.operations.lock = threading.Lock()
            guided.backend.operations.running = lambda: False
            task = root / "text-qa/project/release" / ("a" * 16)
            task.mkdir(parents=True)
            (root / "text-qa-release.json").write_text(
                json.dumps({"task": str(task)}), encoding="utf-8"
            )
            phases = ("translation", "injection", "qa", "patch")
            kept = progress_report.kept(guided.translation.workspace, "project")
            kept.parent.mkdir(parents=True)
            kept.write_text(
                json.dumps(
                    {
                        "version": progress_report.VERSION,
                        "report": {
                            "phase": "patch",
                            "phases": dict.fromkeys(phases, "complete"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            TextQA(guided).start_over("project")  # type: ignore[arg-type]
            report = json.loads(kept.read_text(encoding="utf-8"))["report"]
            self.assertEqual(published, [report])
            self.assertEqual(report["phase"], "qa")
            self.assertEqual(
                report["next_action"],
                "Check the game's files again, then continue from QA.",
            )
            self.assertEqual(
                report["phases"],
                {
                    "translation": "complete",
                    "injection": "complete",
                    "qa": "active",
                    "patch": "pending",
                },
            )

    def test_assistant_led_status_lists_labels_qa_cannot_correct(self):
        # Once the Text QA page stopped listing them, nothing told an
        # Assistant-led assistant about plugin labels the capture found
        # squeezed, and no task of its own shortens them.
        with TemporaryDirectory() as folder:
            task = Path(folder) / "task"
            screens = task / "interface" / "round-1"
            screens.mkdir(parents=True)
            # A capture of the game as it is, which has no plugins.
            capture = {
                "round": 1,
                "folder": "round-1",
                "summary": {},
                "plugins_sha256": hashlib.sha256().hexdigest(),
            }
            (task / "interface" / "capture.json").write_text(
                json.dumps(capture), encoding="utf-8"
            )
            (screens / "screens.json").write_text(
                json.dumps(
                    {
                        "screens": [
                            {
                                "title": "Menu",
                                "file": "menu.png",
                                "labels": [
                                    {"text": "Adventure Records", "squeezed": 0.8},
                                    {"text": "Items"},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (task / "inventory.json").write_text(
                json.dumps({"records": [], "clusters": []}), encoding="utf-8"
            )
            qa = {
                "task": str(task),
                "current": True,
                "applied": False,
                "message": "",
                "findings": [],
                "questions": [],
                "status": {"stage": "screen"},
            }
            guided, _calls = fake_guided(folder, qa, method="len")
            state = TextQA(guided).run("project", "status")  # type: ignore[arg-type]
            _close_contracts()
            TypeAdapter(TextQaStatus).validate_json(json.dumps(state), strict=True)
            self.assertEqual(
                state["labels"],
                [
                    {
                        "text": "Adventure Records",
                        "title": "Menu",
                        "capture": str(screens / "menu.png"),
                        "squeezed": 0.8,
                    }
                ],
            )
            self.assertIn("Before qa --apply", state["next"])
            self.assertNotIn("captures them again", state["next"])
            # The assistant's own fixes change the game's plugins during
            # review, which leaves the text QA reviews current: preparing
            # again captures the screens again and keeps the review.
            (Path(folder) / "js").mkdir()
            (Path(folder) / "js" / "plugins.js").write_text("[]", encoding="utf-8")
            state = TextQA(guided).run("project", "status")  # type: ignore[arg-type]
            self.assertIn("run qa --prepare, which captures them again", state["next"])
            # A capture taken again after the corrections change the game's
            # text needs a fresh task, so applied QA lists none; Guided's
            # Plugin files shortens them itself.
            qa["applied"] = True
            self.assertNotIn("labels", TextQA(guided).run("project", "status"))  # type: ignore[arg-type]
            qa["applied"] = False
            guided, _calls = fake_guided(folder, qa)
            state = TextQA(guided).run("project", "status")  # type: ignore[arg-type]
            self.assertNotIn("labels", state)
            self.assertNotIn("Before qa --apply", state["next"])

    def test_assistant_led_status_sends_never_translated_text_to_extraction(self):
        # QA's report of Japanese no line covered only asked the assistant to
        # name it, so text its own extractor or injector missed shipped while
        # coverage read complete.
        with TemporaryDirectory() as folder:
            game = Path(folder) / "game"
            (game / "data").mkdir(parents=True)
            (game / "js").mkdir()

            def message(*lines):
                return [{"code": 401, "parameters": [line]} for line in lines]

            def write_game(hello, welcome):
                (game / "data/Map001.json").write_text(
                    json.dumps(
                        {
                            "displayName": "",
                            "events": [
                                None,
                                {
                                    "name": "EV001",
                                    "pages": [
                                        {
                                            "list": [
                                                *message(hello),
                                                *message("さようなら"),
                                                {"code": 0, "parameters": []},
                                            ]
                                        }
                                    ],
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                plugins = [
                    {"name": "TitleMessage", "parameters": {"text": welcome}},
                    # A face file, which the census sets aside itself.
                    {"name": "Faces", "parameters": {"faceName": "主人公"}},
                    # A note the assistant's scope rule sets aside.
                    {"name": "Debug", "parameters": {"memo": "テスト用"}},
                ]
                (game / "js/plugins.js").write_text(
                    "var $plugins =\n"
                    + json.dumps(
                        [{**plugin, "status": True} for plugin in plugins],
                        ensure_ascii=False,
                    )
                    + ";\n",
                    encoding="utf-8",
                )

            write_game("こんにちは", "ようこそ")
            files = {
                name: (game / name).read_bytes()
                for name in ("data/Map001.json", "js/plugins.js")
            }
            workspace = Path(folder) / "workspace"
            counted = census_path(workspace, "project")
            counted.parent.mkdir(parents=True)
            counted.write_text(
                json.dumps(
                    census.scan(sorted(files), files.__getitem__, None),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rules = game / SCOPE_RULES
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "kind": "rpgmaker:plugins",
                                "field": "Debug/*",
                                "reason": "not_displayed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            task = Path(folder) / "task"
            task.mkdir()
            (task / "task.json").write_text(
                json.dumps({"schema": rpgmaker_qa.TASK_SCHEMA}), encoding="utf-8"
            )

            def prepare():
                (task / "preflight.json").write_text(
                    json.dumps(preflight(game / "data", {"records": []})),
                    encoding="utf-8",
                )

            prepare()
            qa = {
                "task": str(task),
                "current": True,
                "applied": False,
                "message": "",
                "findings": [],
                "questions": [],
                "status": {"stage": "screen"},
            }
            guided, _calls = fake_guided(game, qa, method="len")
            guided.translation.workspace = workspace
            # The assistant declined the line it would not translate.
            guided.translation.jobs.store.declined_sources = lambda _id: ["さようなら"]
            service = TextQA(guided)  # type: ignore[arg-type]
            state = service.run("project", "status")
            _close_contracts()
            TypeAdapter(TextQaStatus).validate_json(json.dumps(state), strict=True)
            self.assertEqual(state["untranslated"], 2)
            self.assertTrue(state["next"].startswith(UNTRANSLATED_STEP))
            listed = json.loads((game / UNTRANSLATED_FILE).read_text(encoding="utf-8"))
            self.assertEqual(
                [(row["file"], row["pointer"]) for row in listed["texts"]],
                [
                    ("data/Map001.json", "/events/1/pages/0/list/0/parameters/0"),
                    ("js/plugins.js", "/TitleMessage/text"),
                ],
            )
            # Once both are translated and QA reads the game again, the step
            # ends: what the census sets aside and the declined line stay
            # reported only.
            write_game("Hello", "Welcome")
            prepare()
            state = service.run("project", "status")
            self.assertNotIn("untranslated", state)
            self.assertNotIn(UNTRANSLATED_STEP, state["next"])
            self.assertFalse((game / UNTRANSLATED_FILE).exists())
            self.assertEqual(
                sum(
                    source["count"]
                    for source in json.loads(
                        (task / "preflight.json").read_text(encoding="utf-8")
                    )["sources"]
                ),
                3,
            )
            # Guided's user translates the report's text through Event text
            # or Plugin files.
            write_game("こんにちは", "ようこそ")
            prepare()
            guided.translation.project = lambda _id: ({"method": "guided"}, game)
            self.assertNotIn("untranslated", TextQA(guided).run("project", "status"))  # type: ignore[arg-type]

    def test_check_lists_text_only_hits_on_engines_text_qa_cannot_read(self):
        # Text QA refuses engines other than RPG Maker, so a WOLF or
        # TyranoScript game's glossary misses and changed numbers reached
        # its patch without any tool check.
        with TemporaryDirectory() as folder:
            game = Path(folder)
            (game / "tyrano").mkdir()
            glossary = game / ".dazedtl/glossary.txt"
            glossary.parent.mkdir()
            glossary.write_text(
                "エルフの森 (Elven Woods)\nミナ (Mina) - Female\n", encoding="utf-8"
            )

            def row(unit, source, translation=None):
                value = {"batch": "scene-1", "source_id": unit, "source": source}
                if translation is not None:
                    value.update(
                        translation=translation,
                        translated_from_sha256=hashlib.sha256(
                            source.encode("utf-8")
                        ).hexdigest(),
                        request_sha256="a" * 64,
                    )
                return value

            def export(*rows):
                part = WORK + "/work/translation-units/part-0001.json"
                (game / part).parent.mkdir(parents=True, exist_ok=True)
                (game / part).write_text(
                    json.dumps({"units": list(rows)}, ensure_ascii=False),
                    encoding="utf-8",
                )
                (game / WORK / "work/translation-units.json").write_text(
                    json.dumps({"complete": True, "parts": [part], "version": 3}),
                    encoding="utf-8",
                )

            welcome = row(
                "first/1", "エルフの森へようこそ。", "Welcome to the Elf Forest."
            )
            price = row("first/2", "宿代は100ゴールドだよ。", "The inn costs 10 gold.")
            label = row("first/3", "【噂Lv】3", "[Rumor Lv.]3")
            export(
                welcome,
                price,
                label,
                row("first/4", "はい。", "Yes."),
                row("first/5", "いいえ。"),
                # A pronoun against the glossary's gender, and a censor mask
                # spelled out.
                row("first/6", "ミナは剣を抜いた。", "Mina drew his sword."),
                row("first/7", "ま〇こ", "pussy"),
            )
            guided, _calls = fake_guided(game, {}, method="len")
            guided.translation.settings = SimpleNamespace(
                language=lambda: "English", source_language=lambda: "Japanese"
            )
            service = TextQA(guided)  # type: ignore[arg-type]
            state = service.check("project")
            _close_contracts()
            TypeAdapter(TextQaCheck).validate_json(json.dumps(state), strict=True)
            self.assertEqual(
                (state["lines"], state["open"], state["rules"]),
                (
                    6,
                    5,
                    {
                        "censor-mask-mismatch": 1,
                        "gender-pronoun": 1,
                        "glossary": 1,
                        "lint:level-tag-spacing": 1,
                        "visible-number-mismatch": 1,
                    },
                ),
            )
            self.assertEqual(state["next"], CHECK_STEP)
            report = json.loads((game / CHECK_FILE).read_text(encoding="utf-8"))
            self.assertEqual(report["basis"]["version"], CHECK_VERSION)
            found = {hit["rule"]: hit for hit in report["hits"]}
            self.assertEqual(
                found["glossary"]["terms"], [["エルフの森", "Elven Woods"]]
            )
            self.assertEqual(
                found["lint:level-tag-spacing"]["proposed"], "[Rumor Lv.] 3"
            )
            self.assertEqual(
                found["gender-pronoun"]["pronouns"], [["Mina", "Female", "his"]]
            )
            self.assertEqual(
                found["visible-number-mismatch"]["units"],
                [{"unit": "first/2", "batch": "scene-1", "request_sha256": "a" * 64}],
            )
            # The assistant answers a line it finds right, and the answer
            # stays while the line does.
            answers = {found["lint:level-tag-spacing"]["id"]: "The game writes it so."}
            self.assertEqual(service.check("project", answers)["open"], 4)
            self.assertEqual(service.check("project")["answered"], 1)
            with self.assertRaisesRegex(ValueError, "No current hit"):
                service.check("project", {"0" * 16: "Right."})
            # Its corrections leave no hit open.
            export(
                {**welcome, "translation": "Welcome to the Elven Woods."},
                {**price, "translation": "The inn costs 100 gold."},
                label,
            )
            state = service.check("project")
            self.assertEqual((state["hits"], state["open"]), (1, 0))
            # Text QA reads RPG Maker games itself.
            (game / "tyrano").rmdir()
            (game / "data").mkdir()
            (game / "data/System.json").write_text("{}", encoding="utf-8")
            (game / "js").mkdir()
            (game / "js/plugins.js").write_text("var $plugins = [];", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qa --prepare"):
                service.check("project")
            # With the review off in Options, these checks are all that run
            # there: the helper prepares no review and says so.
            guided.qa_focus = lambda _id: None
            self.assertEqual(service.check("project")["hits"], 1)
            for step in ("prepare", "apply", "choose"):
                with self.subTest(step=step), self.assertRaises(ValueError) as off:
                    service.run("project", step)
                self.assertEqual(str(off.exception), REVIEW_OFF)
            guided.backend.guided_text_state = lambda _native, _focus: {
                "qa": {
                    "current": False,
                    "applied": False,
                    "status": {},
                    "findings": [],
                    "questions": [],
                    "message": "",
                }
            }
            state = service.run("project", "status")
            TypeAdapter(TextQaStatus).validate_json(json.dumps(state), strict=True)
            self.assertEqual((state["focus"], state["next"]), ("checks", REVIEW_OFF))

    def test_size_counts_what_each_focus_reviews_from_either_source(self):
        # Neither method said how much of the game a review reads before it
        # started, though a full review of a big game takes much of an
        # assistant plan's usage.
        def say(original, text):
            return {
                "code": 401,
                "indent": 0,
                "parameters": [text],
                "_original": original,
            }

        def page(*commands):
            return {"list": [*commands, {"code": 0, "indent": 0, "parameters": []}]}

        def entry(file, location, kind, code=None):
            field = (
                f"events/*/pages/*/list/*[code={code}]/parameters/0"
                if code
                else "*/name"
            )
            return {"file": file, "location": location, "kind": kind, "field": field}

        dialogue = {"lines": 3, "scenes": 2}
        expected = {
            "release": {"lines": 4, "scenes": 2},
            "database": {"lines": 1, "scenes": 0},
            "dialogue": dialogue,
            "risky-codes": {"lines": 0, "scenes": 0},
        }
        with TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            data.mkdir()
            self.assertEqual(qa_size.of_game(data)["focuses"], None)
            (data / "Map001.json").write_text(
                json.dumps(
                    {
                        "events": [
                            None,
                            {
                                "id": 1,
                                "pages": [
                                    page(say("はい", "Yes."), say("いいえ", "No.")),
                                    page(say("またね", "Bye.")),
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (data / "Actors.json").write_text(
                json.dumps(
                    [None, {"id": 1, "name": "Hero", "_original": {"name": "勇者"}}]
                ),
                encoding="utf-8",
            )
            # Guided counts the game's translated text as Text QA reads it.
            self.assertEqual(
                qa_size.of_game(data), {"counting": False, "focuses": expected}
            )
            # Assistant-led counts its census of the original game the same
            # way, VX Ace's data and all, but not the plugins QA can't read.
            map_line = "events/1/pages/{}/list/{}/parameters/0"
            rows = [
                entry("data/Map001.json", map_line.format(0, 0), "rpgmaker:map", 401),
                entry("data/Map001.json", map_line.format(0, 1), "rpgmaker:map", 401),
                entry("Data/Map002.rvdata2", map_line.format(0, 0), "rgss:map", 401),
                entry("data/Actors.json", "1/name", "rpgmaker:database:Actors"),
                entry("js/plugins/Menu.js", "3:4", "js:plugin"),
                entry("Data/Scripts.rvdata2", "0:1", "rgss:scripts"),
            ]
            path = Path(folder) / "census.json"
            path.write_text(json.dumps({"entries": rows}), encoding="utf-8")
            self.assertEqual(qa_size.of_census(path)["focuses"], expected)
            self.assertEqual(
                qa_size.of_census(Path(folder) / "none.json"),
                {"counting": False, "focuses": None},
            )
            # A big game is counted off the request, which reads as counting
            # until it ends.
            path.write_text(json.dumps({"entries": rows[:1]}), encoding="utf-8")
            with mock.patch.object(qa_size, "INLINE_BYTES", 0):
                self.assertEqual(qa_size.of_census(path)["counting"], True)
                for _ in range(500):
                    size = qa_size.of_census(path)
                    if not size["counting"]:
                        break
                    threading.Event().wait(0.01)
            self.assertEqual(size["focuses"]["dialogue"], {"lines": 1, "scenes": 1})


class UnitsTextQATests(unittest.TestCase):
    """An Assistant-led game on an engine Text QA can't read, a TyranoScript
    one here, gets Text QA's reviewed task from its units, and its findings
    land as correction receipts."""

    prepared = test_workflow.WorkflowTests.prepared

    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        (self.game / "tyrano").mkdir()
        self.projects.choose_method(self.identity, "len")
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        self.guided = SimpleNamespace(
            projects=self.projects,
            qa_focus=lambda _id: review_focus(self.project.read()["options"]),
            translation=self.service,
            path=lambda _id, name: self.root / f"guided-{name}.json",
            backend=SimpleNamespace(operations=SimpleNamespace(jobs={}, active="")),
        )
        self.qa = TextQA(self.guided)  # type: ignore[arg-type]

    def translate(self, units, english):
        """Organizes *units*, accepts *english* for every request through the
        helper's own accept, and returns the run."""
        path = WORK + "/work/source-units.json"
        write_json(self.game / path, {"version": 1, "units": units})
        run = self.prepared(self.service.organize(self.identity, path))["run"]["id"]
        for index in range(len(self.service.jobs.store.load(run)[1]["requests"])):
            request = self.service.request(self.identity, run, index)["request"]
            receipt = WORK + f"/work/receipt-{index}.json"
            write_json(
                self.game / receipt,
                {
                    "request_sha256": request["fingerprint"],
                    "translations": {key: english[key] for key in request["sources"]},
                },
            )
            self.service.accept(self.identity, run, request["id"], receipt)
        return run

    def step(self, step, **details):
        """One qa step, running the operation it starts as its worker would."""
        state = self.qa.run(self.identity, step, **details)
        operation = state.get("operation") or {}
        if operation.get("status") == "running":
            job, plan = self.service.jobs.store.load(operation["id"], self.identity)
            result = execute(self.engine, self.profile, job, plan, lambda: False)
            job.update(status="complete", result=result)
            self.service.jobs.store.save(job)
            state = self.qa.run(self.identity, "status")
        _close_contracts()
        TypeAdapter(TextQaStatus).validate_json(json.dumps(state), strict=True)
        return state

    def english(self):
        return {
            row["source_id"]: row["translation"]
            for row in exported_translations(self.game)
        }

    def test_a_game_text_qa_reads_by_its_units_is_reviewed_and_corrected(self):
        # Text QA refused every engine but RPG Maker, so qa --prepare gave
        # this game no reviewed task, only the text-only checks.
        units = [
            {
                "id": "a/1",
                "scene": "a",
                "source": "エルフの森へようこそ。",
                "kind": "dialogue",
                "speaker": "リリ",
            },
            {
                "id": "a/2",
                "scene": "a",
                "source": "宿代は百ゴールドだよ。",
                "kind": "dialogue",
            },
            {
                "id": "b/1",
                "scene": "b",
                "source": "おやすみなさい。",
                "kind": "dialogue",
                "speaker": "リリ",
            },
        ]
        english = {
            "a/1": "Welcome to the Elven Woods.",
            "a/2": "The inn is a hundred gold.",
            "b/1": "Good mornin.",
        }
        run = self.translate(units, english)
        self.assertEqual(
            self.qa.run(self.identity, "status")["next"], "Run qa --prepare."
        )
        state = self.step("prepare")
        self.assertEqual(state["stage"], "screen")
        task = Path(state["task"])
        # Scenes in play order, each line with its speaker, both languages,
        # its unit and its number in the scene.
        bundles = [
            json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            for row in rpgmaker_qa.read_task(task)[2]["screen"]["bundles"]
        ]
        scenes = {
            item["scene_id"]: item["lines"]
            for bundle in bundles
            for item in bundle["items"]
            if item["kind"] == "scene"
        }
        fields = ("unit", "command", "speaker", "source", "translation")
        self.assertEqual(
            [{key: line.get(key) for key in fields} for line in scenes["a"]],
            [
                {
                    "unit": "a/1",
                    "command": 0,
                    "speaker": "リリ",
                    "source": units[0]["source"],
                    "translation": english["a/1"],
                },
                {
                    "unit": "a/2",
                    "command": 1,
                    "speaker": None,
                    "source": units[1]["source"],
                    "translation": english["a/2"],
                },
            ],
        )
        # The reviewers report b/1, deep review corrects it and the editor
        # accepts the correction.
        review(task, {"Good mornin.": "Good night."})
        state = self.step("status")
        self.assertEqual((state["stage"], state["findings"]), ("complete", 1))
        self.assertEqual(state["next"], "Run qa --apply.")
        shown = self.service.state(self.identity)["textQa"]
        self.assertEqual(shown["findings"][0]["correction"], "Good night.")
        # Apply saves it as a correction receipt of the request b/1 is in.
        state = self.step("apply")
        self.assertEqual((state["applied"], state["next"]), (True, UNITS_APPLIED))
        self.assertEqual(self.english()["b/1"], "Good night.")
        _job, plan = self.service.jobs.store.load(run)
        (request,) = [row for row in plan["requests"] if "b/1" in row["sources"]]
        receipt = Results(self.game).get(request)
        self.assertEqual(receipt["translations"]["b/1"], "Good night.")
        self.assertEqual(
            (receipt["provenance"]["correction"], receipt["provenance"]["text_qa"]),
            (True, task.name),
        )
        # Progress reads the task and its applied finding, still current.
        shown = self.service.state(self.identity)["textQa"]
        TypeAdapter(QaState).validate_json(json.dumps(shown), strict=True)
        finding = shown["findings"][0]["id"]
        self.assertEqual(
            (shown["current"], shown["findings"][0]["state"]), (True, "applied")
        )
        # Undo puts the line back as another receipt, and apply again redoes it.
        self.step("undo", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Good mornin.")
        shown = self.service.state(self.identity)["textQa"]
        self.assertEqual(
            (shown["current"], shown["findings"][0]["state"]), (True, "undone")
        )
        self.step("reapply", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Good night.")
        # Once the line changed otherwise, undo refuses and says why.
        value = Results(self.game).get(request)
        write_json(
            self.game / WORK / "work/correction.json",
            {
                "request_sha256": request["fingerprint"],
                "replaces_sha256": value["result_sha256"],
                "translations": {**value["translations"], "b/1": "Sleep well."},
            },
        )
        self.service.accept(
            self.identity, run, request["id"], WORK + "/work/correction.json"
        )
        with self.assertRaisesRegex(ValueError, "changed since QA corrected it"):
            self.qa.run(self.identity, "undo", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Sleep well.")
        self.assertFalse(self.service.state(self.identity)["textQa"]["current"])
        # Organized again, the run keeps every line from the requests that
        # translated them, and a new review's correction goes back through
        # the request it keeps the line from.
        self.prepared(
            self.service.organize(self.identity, WORK + "/work/source-units.json")
        )
        with self.assertRaisesRegex(ValueError, "--since reads earlier text"):
            self.qa.run(self.identity, "prepare", since="1.0")
        task = Path(self.step("prepare")["task"])
        review(task, {"Sleep well.": "Good night."})
        self.assertTrue(self.step("apply")["applied"])
        self.assertEqual(self.english()["b/1"], "Good night.")
        self.assertEqual(
            Results(self.game).get(request)["translations"]["b/1"], "Good night."
        )
        # Starting QA over sets the task aside, so QA reads as not started.
        self.assertEqual(self.qa.start_over(self.identity)["next"], "Run qa --prepare.")
        self.assertNotIn("task", self.service.state(self.identity)["textQa"])
        # The text-only checks still run there, with or without the review,
        # and the usage note counts the units.
        self.assertEqual(self.qa.check(self.identity)["lines"], 3)
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "text_qa": "checks"},
        )
        with self.assertRaises(ValueError) as off:
            self.qa.run(self.identity, "prepare")
        self.assertEqual(str(off.exception), REVIEW_OFF)
        self.assertEqual(self.qa.check(self.identity)["lines"], 3)
        lines = units_qa.lines(self.service.jobs.store, self.identity, self.game)
        self.assertEqual(
            qa_size.of_units(lines)["focuses"]["release"], {"lines": 3, "scenes": 2}
        )

    def test_a_correction_reads_and_undoes_as_the_game_gets_it(self):
        # The export writes a reviewer's curly apostrophe and dash in its own
        # form, so undo read the line as changed and refused, and the tab
        # showed text the game never got.
        self.translate(
            [{"id": "b/1", "scene": "b", "source": "おやすみなさい。"}],
            {"b/1": "Good mornin."},
        )
        task = Path(self.step("prepare")["task"])
        review(task, {"Good mornin.": "It’s late—good night."})
        self.assertTrue(self.step("apply")["applied"])
        written = self.english()["b/1"]
        self.assertNotEqual(written, "It’s late—good night.")
        (finding,) = self.service.state(self.identity)["textQa"]["findings"]
        self.assertEqual(finding["correction"], written)
        # Preparing again goes on with the applied task, whose undo stays.
        self.assertEqual(self.step("prepare")["task"], str(task))
        self.step("undo", findings=[finding["id"]])
        self.assertEqual(self.english()["b/1"], "Good mornin.")


def review(task, fixes):
    """Plays Text QA's reviewers through the engine: screening reports each
    line whose English *fixes* corrects, deep review corrects it, and the
    editor accepts every finding."""

    def accept(row, result):
        path = Path(task).parent / f"{row['id']}.result.json"
        path.write_text(
            json.dumps(
                {"bundle_id": row["id"], "bundle_sha256": row["sha256"], **result},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rpgmaker_qa.accept_result(task, path)

    def items(row):
        return json.loads(Path(row["path"]).read_text(encoding="utf-8"))["items"]

    clean = {
        "disposition": "clean",
        "severity": None,
        "category": "",
        "family_key": "",
        "motif_ids": [],
        "evidence": "Checked against the source.",
        "correction": None,
        "apply_identities": [],
    }
    for name in ("screen-a", "screen-b", "deep-a", "editor-a"):
        while row := rpgmaker_qa.next_bundle(task, name):
            if row["id"].startswith("screen"):
                exceptions = [
                    {
                        "id": line["id"],
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "Wrong time of day.",
                    }
                    for item in items(row)
                    for line in item.get("lines") or [item]
                    if "id" in line and line.get("translation") in fixes
                ]
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                        "reviewed_all": True,
                        "exceptions": exceptions,
                        "motif_reviews": [],
                        "lint_reviews": [
                            {"id": item["id"], "rejected": [], "note": ""}
                            for item in items(row)
                            if item["kind"] == "lint-family"
                        ],
                        "declined": [],
                    },
                )
            elif row["id"].startswith("deep"):
                reviews = [
                    {
                        **clean,
                        "id": item["id"],
                        "disposition": "actionable",
                        "severity": "high",
                        "category": "meaning",
                        "summary": "It wishes a good morning at bedtime.",
                        "evidence": "おやすみなさい is good night.",
                        "correction": fixes[item["translation"]],
                    }
                    if item["translation"] in fixes
                    else {**clean, "id": item["id"]}
                    for item in items(row)
                ]
                accept(
                    row, {"schema": rpgmaker_qa.DEEP_RESULT_SCHEMA, "reviews": reviews}
                )
            elif row["id"].startswith("sweep"):
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.SWEEP_RESULT_SCHEMA,
                        "reviews": [
                            {"id": item["id"], "rejected": [], "note": ""}
                            for item in items(row)
                        ],
                        "declined": [],
                    },
                )
            else:
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.EDITORIAL_RESULT_SCHEMA,
                        "reviews": [
                            {"id": item["id"], "verdict": "accept", "note": ""}
                            for item in items(row)
                        ],
                    },
                )
