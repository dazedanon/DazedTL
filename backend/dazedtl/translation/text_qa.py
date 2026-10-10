"""Text QA steps the assistant runs through the project helper.

The engine reviews and makes findings; the app applies them as a reviewed
text batch through the Guided publication flow, which History can restore,
then records a checkpoint commit. No step writes game files itself, and
pushing or publishing stays the user's.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from .files import read_json
from .operations import lifecycle

if TYPE_CHECKING:
    from .guided import Guided

STEPS = ("status", "report", "prepare", "apply", "checkpoint")
CHECKPOINT_MESSAGE = "qa: apply text QA corrections"


class TextQA:
    def __init__(self, guided: Guided):
        self.guided = guided

    def run(self, project_id, step, leave_uncertain=False):
        if step not in STEPS:
            raise ValueError("Choose a text QA step: " + ", ".join(STEPS) + ".")
        if type(leave_uncertain) is not bool:
            raise ValueError("Choose whether to leave open questions unchanged.")
        native = self.native(project_id)
        if step == "prepare":
            self.prepare(project_id)
        elif step == "apply":
            self.apply(project_id, native, leave_uncertain)
        elif step == "checkpoint":
            self.checkpoint(project_id)
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

    def apply(self, project_id, native, leave_uncertain):
        """Every finding, as one reviewed text batch, once nothing needs the user."""
        qa = self.qa(project_id, native)
        if not qa.get("task") or qa["status"].get("stage") != "complete":
            raise ValueError("Finish QA review first; apply follows a complete task.")
        if not qa["current"]:
            raise ValueError(qa["message"])
        if qa["applied"]:
            raise ValueError("This task's findings are already applied.")
        findings = read_json(Path(qa["task"]) / "findings.json")
        open_questions = findings.get("uncertain_playtests") or []
        if open_questions and not leave_uncertain:
            raise ValueError(
                f"{len(open_questions)} playtest or context question(s) are open: "
                + ", ".join(row["id"] for row in open_questions[:5])
                + ". Ask the user, then apply with --leave-uncertain to leave them "
                "unchanged, or settle them first."
            )
        chosen = [row["id"] for row in findings.get("findings") or []]
        if not chosen:
            raise ValueError("QA found nothing to correct.")
        preview = self.guided.preview(
            project_id,
            "qa_apply",
            None,
            {"focus": self.focus(project_id), "task": qa["task"], "findings": chosen},
        )
        self.started(
            project_id, "apply", self.guided.execute(project_id, preview["token"])
        )

    def checkpoint(self, project_id):
        """The commit that records applied corrections in the game's history."""
        saved = self.operation(project_id)
        if not saved or saved["kind"] != "apply" or saved["status"] != "complete":
            raise ValueError("Apply QA's findings before saving their checkpoint.")
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
                project_id,
                "checkpoint",
                {"manifest": manifest, "message": CHECKPOINT_MESSAGE},
            )
        else:
            preview = self.guided.preview(
                project_id, "checkpoint", None, {"message": CHECKPOINT_MESSAGE}
            )
            job = self.guided.execute(project_id, preview["token"])
        self.started(project_id, "checkpoint", job, runner="translation")

    def started(self, project_id, kind, job, runner="native"):
        write_json(
            self.guided.path(project_id, "text-qa-operation"),
            {"kind": kind, "id": job["id"], "runner": runner},
        )

    def operation(self, project_id) -> dict[str, Any] | None:
        """The last QA step the helper started, with its current state."""
        path = self.guided.path(project_id, "text-qa-operation")
        if not path.exists():
            return None
        saved = read_json(path)
        if saved["runner"] == "native":
            job = self.guided.backend.operations.jobs.get(saved["id"]) or {}
            state, message = job.get("status", "interrupted"), job.get("message", "")
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
        findings = [row for row in qa["findings"] if not row.get("classification")]
        operation = self.operation(project_id)
        if not qa.get("task"):
            following = "Run qa --prepare."
        elif not qa["current"]:
            following = "The game text changed since this task; run qa --prepare."
        elif qa["applied"]:
            following = (
                "Findings are applied; save their checkpoint with qa --checkpoint "
                "if it has not run."
            )
        elif stage == "complete":
            following = "Run qa --apply."
        else:
            following = (
                "Review with the task README's commands, running finalize after "
                "each stage, until it reports complete."
            )
        state = {
            "focus": self.focus(project_id),
            "task": qa.get("task", ""),
            "stage": stage,
            "current": qa["current"],
            "applied": qa["applied"],
            "findings": len(findings),
            "questions": len(qa["findings"]) - len(findings),
            "message": qa["message"],
            "next": following,
            "progress": qa["status"],
            **({"operation": operation} if operation else {}),
        }
        if report and qa.get("task"):
            state["report"] = str(Path(qa["task"]) / "findings.json")
        return state
