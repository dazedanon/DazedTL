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


def fake_guided(folder, qa, method="guided"):
    calls = []
    jobs = {}

    def execute(_project_id, token):
        calls.append(("execute", token))
        jobs[token + "-job"] = {"status": "complete", "message": ""}
        return {"id": token + "-job"}

    guided = SimpleNamespace(
        projects=SimpleNamespace(get=lambda _id: {"backend_id": "native"}),
        record=lambda _id: ({}, {"id": "native"}),
        saved_form=lambda _id: {"text": {"focus": "release"}},
        backend=SimpleNamespace(
            guided_text_state=lambda _native, _focus: {"qa": qa},
            operations=SimpleNamespace(jobs=jobs),
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
            qa["questions"][0]["choice"] = "use"
            service.run("project", "apply")
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
            with self.assertRaisesRegex(ValueError, "already applied"):
                service.run("project", "apply")
            # Undo's reply meets the helper contract; one that did not made
            # the page report a finished undo as failed before its checkpoint.
            undone = service.run("project", "undo", findings=["QA-0001"])
            _close_contracts()
            TypeAdapter(TextQaStatus).validate_json(json.dumps(undone), strict=True)
            self.assertEqual(undone["operation"]["kind"], "undo")
