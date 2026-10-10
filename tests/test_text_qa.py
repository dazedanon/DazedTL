"""Text QA's helper steps apply findings only through the app's publication."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dazedtl.storage import write_json
from dazedtl.translation.text_qa import CHECKPOINT_MESSAGE, TextQA


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
            write_json(
                task / "findings.json",
                {
                    "findings": [{"id": "QA-0001"}, {"id": "QA-0002"}],
                    "uncertain_playtests": [{"id": "Map001.json#/1"}],
                },
            )
            qa = {
                "task": str(task),
                "current": True,
                "applied": False,
                "message": "",
                "findings": [],
                "status": {"stage": "complete"},
            }
            guided, calls = fake_guided(folder, qa)
            service = TextQA(guided)  # type: ignore[arg-type]
            with self.assertRaisesRegex(ValueError, "question"):
                service.run("project", "apply")
            with self.assertRaisesRegex(ValueError, "Apply QA's findings"):
                service.run("project", "checkpoint")
            service.run("project", "apply", leave_uncertain=True)
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
                        },
                    ),
                    ("execute", "qa_apply"),
                    ("preview", "checkpoint", {"message": CHECKPOINT_MESSAGE}),
                    ("execute", "checkpoint"),
                ],
            )
            self.assertEqual(state["operation"]["kind"], "checkpoint")
            # Applied findings are not applied twice.
            qa["applied"] = True
            with self.assertRaisesRegex(ValueError, "already applied"):
                service.run("project", "apply", leave_uncertain=True)
