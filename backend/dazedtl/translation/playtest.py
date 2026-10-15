"""The release playtest, started from the Playtest task or by the assistant
through the project helper.

The app plays the game in a hidden window and keeps one report; it writes
nothing into the game. Findings in text QA's lines go to QA's review, and
the rest name the task that fixes them.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from .files import read_json

if TYPE_CHECKING:
    from .guided import Guided
    from .text_qa import TextQA

STEPS = ("status", "report", "run", "layout")


class Playtest:
    def __init__(self, guided: Guided, text_qa: TextQA):
        self.guided = guided
        self.text_qa = text_qa

    def run(self, project_id, step, stops=None, widths=None):
        if step not in STEPS:
            raise ValueError("Choose a playtest step: " + ", ".join(STEPS) + ".")
        native = self.native(project_id)
        if step == "run":
            self.start(project_id, stops)
        if step == "layout":
            self.check_layout(project_id, widths)
        return self.status(project_id, native, report=step == "report")

    def native(self, project_id):
        """The game's Guided workspace, which keeps the playtest's reports;
        an Assistant-led game gets the one Guided would use."""
        project = self.guided.projects.get(project_id)
        if not project.get("backend_id"):
            engine = self.guided.backend.describe(project["source"])["engine"]
            if engine != "MVMZ":
                raise ValueError(
                    "The release playtest plays RPG Maker MV and MZ games."
                )
            self.guided.open(project_id)
        native = self.guided.record(project_id)[1]
        if native["engine"] != "MVMZ":
            raise ValueError("The release playtest plays RPG Maker MV and MZ games.")
        return native

    def start(self, project_id, stops):
        if stops is not None and not isinstance(stops, list):
            raise ValueError("Give the playtest's stops as a list.")
        preview = self.guided.preview(
            project_id,
            "release_playtest",
            None,
            {"stops": stops or [], "focus": self.text_qa.focus(project_id)},
        )
        job = self.guided.execute(project_id, preview["token"])
        write_json(
            self.guided.path(project_id, "playtest-operation"), {"id": job["id"]}
        )

    def check_layout(self, project_id, widths):
        """Shows English at the given widths in the game's own windows; it
        keeps its own report, never the playtest's."""
        preview = self.guided.preview(
            project_id, "layout_capture", None, {"widths": widths}
        )
        job = self.guided.execute(project_id, preview["token"])
        write_json(self.guided.path(project_id, "layout-operation"), {"id": job["id"]})

    def layout(self, project_id, native):
        """The latest layout check: each window's fit and its capture."""
        from dazedtl.compatibility.playtest import latest_layout

        operation = self.operation(project_id, "layout-operation")
        try:
            saved = latest_layout(self.guided.backend.workflows.folder(native["id"]))
        except OSError, ValueError, KeyError, TypeError:
            saved = None
        if not operation and not saved:
            return None
        result: dict[str, Any] = {"operation": operation} if operation else {}
        if saved:
            files = {capture["name"]: capture["file"] for capture in saved["captures"]}
            result.update(
                finished_at=saved["finished_at"],
                widths=saved["widths"],
                probes=[
                    {
                        **{
                            key: probe[key]
                            for key in (
                                "title",
                                "fits",
                                "widest",
                                "room",
                                "lines",
                                "rows",
                            )
                        },
                        **(
                            {
                                "capture": str(
                                    Path(saved["folder"]) / files[probe["capture"]]
                                )
                            }
                            if probe.get("capture") in files
                            else {}
                        ),
                    }
                    for probe in saved["probes"]
                ],
                missing=saved["missing"],
                **(
                    {"unavailable": saved["unavailable"]}
                    if saved.get("unavailable")
                    else {}
                ),
            )
        return result

    def operation(self, project_id, pointer="playtest-operation"):
        """The last playtest started, with its current state."""
        path = self.guided.path(project_id, pointer)
        if not path.exists():
            return None
        identity = read_json(path)["id"]
        operations = self.guided.backend.operations
        job = operations.jobs.get(identity) or {}
        state = job.get("status", "interrupted")
        # A job reports its end before its worker exits.
        if operations.active == identity:
            state = "running"
        return {
            "id": identity,
            "status": state,
            "message": str(job.get("message") or ""),
        }

    def status(self, project_id, native, report=False):
        state = self.guided.backend.guided_text_state(
            native, self.text_qa.focus(project_id)
        )["playtest"]
        operation = self.operation(project_id)
        problems = state["problems"]
        stops = (state.get("coverage") or {}).get("stops", [])
        if operation and operation["status"] == "running":
            following = "The playtest is running; wait with playtest --run --wait MINUTES or check again."
        elif not state.get("report"):
            following = "Run playtest --run."
        elif not state["current"]:
            following = "The game changed after the last playtest; run playtest --run."
        elif problems or state["gaps"]:
            following = (
                "Read the report: fix crashes and plugin text through their tasks, let "
                "text QA correct its lines, add stops for what the tour could not "
                "reach, then run playtest --run again."
            )
        else:
            following = (
                "The playtest found nothing to fix; report it with its coverage."
            )
        result = {
            "current": state["current"],
            "finished_at": state.get("finished_at", ""),
            "problems": dict(Counter(problem["fix"] for problem in problems)),
            "seen": sum(bool(problem.get("seen")) for problem in problems),
            "gaps": len(state["gaps"]),
            "reached": f"{sum(stop['status'] == 'done' for stop in stops)} of {len(stops)}",
            "next": following,
            **({"operation": operation} if operation else {}),
        }
        layout = self.layout(project_id, native)
        if layout:
            result["layout"] = layout
        if report and state.get("report"):
            from dazedtl.compatibility.playtest import STORAGE

            result["report"] = str(
                Path(self.guided.backend.workflows.folder(native["id"]))
                / STORAGE
                / state["report"]
                / "report.json"
            )
        return result

    def capture(self, project_id, name):
        from dazedtl.compatibility.playtest import capture

        native = self.guided.record(project_id)[1]
        return capture(self.guided.backend.workflows.folder(native["id"]), name)
