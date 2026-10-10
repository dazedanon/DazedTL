"""Text QA steps the assistant runs through the project helper, and the
Text QA task in the app.

The engine reviews and makes findings; the app applies them as a reviewed
text batch through the Guided publication flow, which History can restore,
then records a checkpoint commit. Open questions wait for the user's choice,
and an applied correction can be undone one at a time. No step writes game
files itself, and pushing or publishing stays the user's.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from .files import read_json
from .operations import lifecycle

if TYPE_CHECKING:
    from .guided import Guided

STEPS = (
    "status",
    "report",
    "prepare",
    "apply",
    "checkpoint",
    "undo",
    "choose",
)
CHOICES = ("keep", "use")
CHECKPOINT_MESSAGE = "qa: apply text QA corrections"
UNDO_MESSAGE = "qa: undo text QA corrections"


def _save_task_record(folder: Path, name: str, task: str, value) -> None:
    """Saves one QA task's entry in a per-game record, such as its choices."""
    path = folder / name
    document = read_json(path) if path.exists() else {}
    write_json(path, {**document, task: value})


class TextQA:
    def __init__(self, guided: Guided):
        self.guided = guided

    def run(self, project_id, step, findings=None, question="", choice=""):
        if step not in STEPS:
            raise ValueError("Choose a text QA step: " + ", ".join(STEPS) + ".")
        native = self.native(project_id)
        if step == "prepare":
            self.prepare(project_id)
        elif step == "apply":
            self.apply(project_id, native)
        elif step == "checkpoint":
            self.checkpoint(project_id)
        elif step == "undo":
            self.undo(project_id, native, findings)
        elif step == "choose":
            self.choose(project_id, native, question, choice)
        return self.status(project_id, native, report=step == "report")

    def native(self, project_id):
        """The game's QA workspace; an Assistant-led game gets the one Guided
        would use, which holds its QA tasks and text batches."""
        project = self.guided.projects.get(project_id)
        if not project.get("backend_id"):
            engine = self.guided.backend.describe(project["source"])["engine"]
            if engine not in {"MVMZ", "ACE"}:
                raise ValueError(
                    "Text QA reads RPG Maker MV/MZ and VX Ace data; check this engine "
                    "with Len's runtime QA instead."
                )
            self.guided.open(project_id)
        return self.guided.record(project_id)[1]

    def folder(self, native) -> Path:
        return Path(self.guided.backend.workflows.folder(native["id"]))

    def focus(self, project_id):
        return self.guided.saved_form(project_id)["text"]["focus"]

    def qa(self, project_id, native):
        return self.guided.backend.guided_text_state(native, self.focus(project_id))[
            "qa"
        ]

    def prepare(self, project_id):
        preview = self.guided.preview(
            project_id, "qa_prepare", None, {"focus": self.focus(project_id)}
        )
        self.started(
            project_id, "prepare", self.guided.execute(project_id, preview["token"])
        )

    def apply(self, project_id, native):
        """Every finding, and each proposal the user chose, as one reviewed
        text batch, once no question waits for the user."""
        qa = self.qa(project_id, native)
        if not qa.get("task") or qa["status"].get("stage") != "complete":
            raise ValueError("Finish QA review first; apply follows a complete task.")
        if not qa["current"]:
            raise ValueError(qa["message"])
        if qa["applied"]:
            raise ValueError("This task's findings are already applied.")
        waiting = [row for row in qa["questions"] if "choice" not in row]
        if waiting:
            raise ValueError(
                f"{len(waiting)} question(s) wait for the user's choice in DazedTL's "
                "Text QA task; apply follows their answers."
            )
        chosen = [row["id"] for row in qa["findings"]]
        proposals = [row["id"] for row in qa["questions"] if row["choice"] == "use"]
        if not chosen + proposals:
            raise ValueError("QA found nothing to correct.")
        preview = self.guided.preview(
            project_id,
            "qa_apply",
            None,
            {
                "focus": self.focus(project_id),
                "task": qa["task"],
                "findings": chosen,
                "proposals": proposals,
            },
        )
        self.started(
            project_id, "apply", self.guided.execute(project_id, preview["token"])
        )

    def undo(self, project_id, native, findings):
        """Puts back the lines of applied corrections, as a batch of its own."""
        qa = self.qa(project_id, native)
        if (
            not isinstance(findings, list)
            or not findings
            or any(not isinstance(value, str) for value in findings)
        ):
            raise ValueError("Choose the corrections to undo.")
        questions = {row["id"] for row in qa["questions"]}
        preview = self.guided.preview(
            project_id,
            "qa_undo",
            None,
            {
                "focus": self.focus(project_id),
                "task": qa["task"],
                "findings": [value for value in findings if value not in questions],
                "proposals": [value for value in findings if value in questions],
            },
        )
        self.started(
            project_id, "undo", self.guided.execute(project_id, preview["token"])
        )

    def choose(self, project_id, native, question, choice):
        """The user's answer to an open question: keep the line, or use the
        proposal the reviewer gave."""
        qa = self.qa(project_id, native)
        row = next((row for row in qa["questions"] if row["id"] == question), None)
        if row is None:
            raise ValueError("That question is no longer open.")
        if choice not in CHOICES or choice == "use" and "proposal" not in row:
            raise ValueError("Keep the current text, or use the reviewer's proposal.")
        if qa["applied"]:
            raise ValueError("This task's findings are already applied.")
        folder = self.folder(native)
        path = folder / "text-qa-choices.json"
        saved = (read_json(path) if path.exists() else {}).get(qa["task"]) or {}
        _save_task_record(
            folder, "text-qa-choices.json", qa["task"], {**saved, question: choice}
        )

    def reviewed(self, project_id, identities):
        """Lines the user read themselves from the optional not-reviewed list."""
        native = self.native(project_id)
        qa = self.qa(project_id, native)
        if not qa.get("task"):
            raise ValueError("Prepare text QA first.")
        if not isinstance(identities, list) or any(
            not isinstance(value, str) for value in identities
        ):
            raise ValueError("Choose the lines you reviewed.")
        folder = self.folder(native)
        path = folder / "text-qa-reviewed.json"
        saved = (read_json(path) if path.exists() else {}).get(qa["task"]) or []
        _save_task_record(
            folder,
            "text-qa-reviewed.json",
            qa["task"],
            sorted(set(saved) | set(identities)),
        )
        return self.report(project_id)

    def report(self, project_id):
        from dazedtl.compatibility.text import qa_report

        native = self.native(project_id)
        return qa_report(
            {
                "project_id": native["id"],
                "project": native,
                "folder": str(self.folder(native)),
                "guard": self.guided.backend.guided_guard(native, self.folder(native)),
                "options": {"focus": self.focus(project_id)},
            }
        )

    def checkpoint(self, project_id):
        """The commit that records applied or undone corrections in the
        game's history."""
        saved = self.operation(project_id)
        # A checkpoint that did not finish runs again for the step before it.
        kind = (
            read_json(self.guided.path(project_id, "text-qa-operation")).get("after")
            if saved and saved["kind"] == "checkpoint" and saved["status"] != "complete"
            else saved and saved["status"] == "complete" and saved["kind"]
        )
        if kind not in {"apply", "undo"}:
            raise ValueError(
                "Apply or undo QA corrections before saving their checkpoint."
            )
        message = CHECKPOINT_MESSAGE if kind == "apply" else UNDO_MESSAGE
        record, _project = self.guided.translation.project(project_id)
        if record.get("method") == "len":
            # The assistant's own checkpoints name the runtime files of its patch.
            manifest = lifecycle(self.guided.translation.workspace, project_id).get(
                "runtime_manifest"
            )
            if not manifest:
                raise ValueError(
                    "Save a checkpoint with the patch's runtime manifest first; QA "
                    "commits its corrections with the same manifest."
                )
            job = self.guided.translation.operation(
                project_id, "checkpoint", {"manifest": manifest, "message": message}
            )
        else:
            preview = self.guided.preview(
                project_id, "checkpoint", None, {"message": message}
            )
            job = self.guided.execute(project_id, preview["token"])
        self.started(project_id, "checkpoint", job, runner="translation", after=kind)

    def started(self, project_id, kind, job, runner="native", after=""):
        write_json(
            self.guided.path(project_id, "text-qa-operation"),
            {
                "kind": kind,
                "id": job["id"],
                "runner": runner,
                **({"after": after} if after else {}),
            },
        )

    def operation(self, project_id) -> dict[str, Any] | None:
        """The last QA step the helper started, with its current state."""
        path = self.guided.path(project_id, "text-qa-operation")
        if not path.exists():
            return None
        saved = read_json(path)
        if saved["runner"] == "native":
            operations = self.guided.backend.operations
            job = operations.jobs.get(saved["id"]) or {}
            state, message = job.get("status", "interrupted"), job.get("message", "")
            # A job reports its end before its worker exits, and the next
            # step, such as the checkpoint, waits for the worker.
            if operations.active == saved["id"]:
                state = "running"
        else:
            job = self.guided.translation.run(project_id, saved["id"])
            state, message = job["status"], job.get("message", "")
        return {
            "kind": saved["kind"],
            "id": saved["id"],
            "status": state,
            "message": str(message or ""),
        }

    def status(self, project_id, native, report=False):
        qa = self.qa(project_id, native)
        stage = str(qa["status"].get("stage") or "")
        waiting = [row for row in qa["questions"] if "choice" not in row]
        operation = self.operation(project_id)
        if not qa.get("task"):
            following = "Run qa --prepare."
        elif qa["applied"]:
            following = (
                "Findings are applied and saved as a version; report the qa phase "
                "complete."
                if operation
                and operation["kind"] == "checkpoint"
                and operation["status"] == "complete"
                else "Findings are applied; save their checkpoint with qa --checkpoint."
            )
        elif not qa["current"]:
            following = qa["message"] + " Run qa --prepare."
        elif stage == "complete" and waiting:
            following = (
                "The user answers the open questions in DazedTL; run qa --apply "
                "--wait <minutes>, which applies once they have."
            )
        elif stage == "complete":
            following = "Run qa --apply."
        else:
            following = (
                "Review with the task README's commands until status reports complete."
            )
        state = {
            "focus": self.focus(project_id),
            "task": qa.get("task", ""),
            "stage": stage,
            "current": qa["current"],
            "applied": qa["applied"],
            "findings": len(qa["findings"]),
            "questions": len(waiting),
            "message": qa["message"],
            "next": following,
            "progress": qa["status"],
            **({"operation": operation} if operation else {}),
        }
        if report and qa.get("task"):
            state["report"] = str(Path(qa["task"]) / "findings.json")
        return state
