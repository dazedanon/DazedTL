"""Text QA's helper steps apply findings only through the app's publication."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dazedtl.api.contracts.guided import TextQaStatus
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.translation import census
from dazedtl.translation.operations import census_path
from dazedtl.translation.run_compiler import SCOPE_RULES
from dazedtl.translation.text_qa import UNTRANSLATED_FILE, UNTRANSLATED_STEP, TextQA
from pydantic import TypeAdapter
from util import rpgmaker_qa
from util.rpgmaker_qa_preflight import preflight


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
                SimpleNamespace(root=Path(folder)),
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
