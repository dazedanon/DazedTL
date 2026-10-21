"""Text QA's helper steps apply findings only through the app's publication."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dazedtl.api.contracts.guided import TextQaStatus
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.translation.text_qa import CHECKPOINT_MESSAGE, TextQA
from pydantic import TypeAdapter
from util import rpgmaker_qa


def fake_guided(folder, qa, method="guided"):
    calls = []
    jobs = {}

    def execute(_project_id, token):
        calls.append(("execute", token))
        jobs[token + "-job"] = {"status": "complete", "message": ""}
        return {"id": token + "-job"}

    guided = SimpleNamespace(
        projects=SimpleNamespace(get=lambda _id: {"backend_id": "native"}),
        record=lambda _id: ({}, {"id": "native", "source": str(folder)}),
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
            project=lambda _id: ({"method": method}, None),
            run=lambda _id, job: {"status": jobs[job]["status"], "message": ""},
        ),
    )
    return guided, calls


class TextQATests(unittest.TestCase):
    def test_apply_publishes_every_finding_then_saves_a_checkpoint(self):
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
            with self.assertRaisesRegex(ValueError, "Apply or undo"):
                service.run("project", "checkpoint")
            service.run("project", "choose", question="Map001.json#/1", choice="use")
            # The task keeps the answer, where its ledger reads it.
            self.assertEqual(rpgmaker_qa.answers(task), {"Map001.json#/1": "use"})
            qa["questions"][0]["choice"] = "use"
            # A version takes every change in the game, so QA's waits while
            # the playtest's fixes are in none, as Fuuma's took them.
            fixes = Path(folder) / "js/plugins/DazedTL_Fixes.js"
            fixes.parent.mkdir(parents=True)
            fixes.write_text("// Fix\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "playtest --checkpoint"):
                service.run("project", "apply")
            fixes.unlink()
            applied = service.run("project", "apply")
            # The playtest's fixes wait in turn for QA's version.
            with self.assertRaisesRegex(ValueError, "qa --checkpoint"):
                service.require_saved("project")
            # The job reports its end before its worker exits; the checkpoint
            # waits for the worker, so the apply still reads as running.
            guided.backend.operations.active = applied["operation"]["id"]
            self.assertEqual(
                service.run("project", "status")["operation"]["status"], "running"
            )
            guided.backend.operations.active = ""
            state = service.run("project", "checkpoint")
            service.require_saved("project")
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
                    ("preview", "checkpoint", {"message": CHECKPOINT_MESSAGE}),
                    ("execute", "checkpoint"),
                ],
            )
            self.assertEqual(state["operation"]["kind"], "checkpoint")
            # A checkpoint that failed runs again for the apply before it;
            # once one saves, there is nothing left to save.
            guided.backend.operations.jobs["checkpoint-job"]["status"] = "failed"
            service.run("project", "checkpoint")
            self.assertEqual(calls[-2][2], {"message": CHECKPOINT_MESSAGE})
            with self.assertRaisesRegex(ValueError, "Apply or undo"):
                service.run("project", "checkpoint")
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
            service.run("project", "checkpoint")
            qa["applied"] = True
            qa["findings"][-1]["state"] = "applied"
            # Undo's reply meets the helper contract; one that did not made
            # the page report a finished undo as failed before its checkpoint.
            undone = service.run("project", "undo", findings=["QA-0001"])
            _close_contracts()
            TypeAdapter(TextQaStatus).validate_json(json.dumps(undone), strict=True)
            self.assertEqual(undone["operation"]["kind"], "undo")
            # Apply again runs an apply batch of its own, and its checkpoint
            # records an apply.
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
            service.run("project", "checkpoint")
            self.assertEqual(calls[-2][2], {"message": CHECKPOINT_MESSAGE})
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
            (task / "interface" / "capture.json").write_text(
                json.dumps({"round": 1, "folder": "round-1", "summary": {}}),
                encoding="utf-8",
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
