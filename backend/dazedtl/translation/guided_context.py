"""Investigation tasks, guidance documents, references and speaker setup."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from dazedtl.storage import write_json

from . import context_setup, reference_folders, speaker_setup
from .files import digest, project_path, read_json
from .helper_command import helper_command

if TYPE_CHECKING:
    from .guided import Guided


class GuidedContext:
    def __init__(self, guided: Guided):
        self.guided = guided

    def skill(self, project_id, name):
        self.guided.clean(project_id)
        project, native = self.guided.record(project_id)
        if name not in {
            "setup",
            "advanced",
            "wrap",
            "plugins",
            "walkthrough",
            "qa",
        }:
            raise ValueError("Choose a task-specific helper.")
        root = Path(native["source"])
        guided = root / ".dazedtl/guided"
        if name == "qa":
            return self.qa_task(project_id, native)
        if name == "advanced":
            request = self.guided.event_text.request(project_id, native)
            command = helper_command(
                self.guided.translation.workspace, project_id, "event-text"
            )
            return {
                "text": self.guided.event_text.instructions(request, command),
                "handoff": {
                    "kind": "event_text",
                    "requestId": request["request_id"],
                    "expects": [guided / "event-text-findings.json"],
                },
            }
        text = self.guided.backend.workflows.skill(
            native["id"],
            name,
            thorough=self.guided.saved_form(project_id)["thorough_investigation"],
        )
        handoff = None
        if name == "walkthrough":
            handoff = {
                "kind": "walkthrough",
                "requestId": "",
                "expects": [root / "WALKTHROUGH.html"],
            }
        if name == "setup":
            schema = self.guided.backend.workflows.state(native["id"])["engine_schema"]
            request = speaker_setup.request(
                self.guided.path(project_id, "speaker-request"),
                project_id,
                native,
                schema,
            )
            command = helper_command(
                self.guided.translation.workspace, project_id, "speakers"
            )
            context_request = context_setup.request(
                self.guided.path(project_id, "context-request"),
                project_id,
                request,
                native["widths"],
            )
            context_command = helper_command(
                self.guided.translation.workspace, project_id, "context"
            )
            text += context_setup.instructions(context_request, context_command)
            documents = self.guided.backend.workflows.documents(native["id"])
            handoff = {
                "kind": "names",
                "requestId": request["request_id"],
                "expects": [
                    guided / "speaker-findings.json",
                    *(
                        documents[key]["path"]
                        for key in context_setup.CORE
                        if key in documents
                    ),
                ],
            }
            text = (
                speaker_setup.instructions(request, command)
                + reference_folders.instructions(
                    reference_folders.records(
                        self.guided.path(project_id, "reference-folders")
                    )
                )
                + "\n## Glossary and context investigation (after the local speaker scan)\n"
                + text
            )
        if name == "wrap":
            path = self.guided.path(project_id, "context-request")
            previous = context_setup.optional_record(path)
            request = context_setup.request(
                path,
                project_id,
                {
                    "request_id": previous.get(
                        "speaker_request_id", context_setup.LAYOUT_REQUEST
                    )
                },
                native["widths"],
            )
            command = helper_command(
                self.guided.translation.workspace, project_id, "context"
            )
            text += context_setup.layout_instructions(request, command)
            handoff = {
                "kind": "line_widths",
                "requestId": request["request_id"],
                "expects": [guided / "context-findings.json"],
            }
        return {
            "text": f"Selected game: {project['source']}\n\nThis is one user-requested Guided Workflow task: {name}. Complete only this task, report what changed and what needs review, then stop. The user controls translation submission, export, versioning and packaging in DazedTL.\n\n"
            + text,
            **({"handoff": handoff} if handoff else {}),
        }

    def qa_task(self, project_id, native):
        """The prepared Text QA task for the saved focus, while it is current."""
        from dazedtl.compatibility.text import qa_handoff

        qa = self.guided.backend.guided_text_state(
            native, self.guided.saved_form(project_id)["text"]["focus"]
        )["qa"]
        if not qa.get("task"):
            raise ValueError("Prepare the text QA task first.")
        if not qa["current"]:
            raise ValueError(qa["message"])
        task = Path(qa["task"])
        helper = helper_command(self.guided.translation.workspace, project_id, "qa")
        return {
            "text": qa_handoff(task, helper),
            "handoff": {
                "kind": "qa",
                "requestId": task.name,
                "expects": [task / "findings.json", task / "correction-map.json"],
            },
        }

    def event_text_request(self, project_id, apply=False):
        """The assistant's view of its request; `apply` saves its findings."""
        if type(apply) is not bool:
            raise ValueError("Choose whether to apply the event text findings.")
        _, native = self.guided.record(project_id)
        if apply:
            findings = self.guided.event_text.inspect(project_id, native)
            self.guided.event_text.apply(
                project_id, native["revision"], findings["reportId"]
            )
            _, native = self.guided.record(project_id)
        path = self.guided.path(project_id, "event-text-request")
        return {
            "request": read_json(path) if path.exists() else None,
            "findings": self.guided.event_text.status(project_id, native),
        }

    def event_text_apply(self, project_id, revision, report_id):
        return self.guided.event_text.apply(project_id, revision, report_id)

    def event_text_view(self, project_id, view):
        return self.guided.event_text.view(project_id, view)

    def event_text_picker(self, project_id, value):
        return self.guided.event_text.picker(project_id, value)

    def comparisons_review(self, project_id, fingerprint, accepted):
        self.guided.idle()
        _, native = self.guided.record(project_id)
        current = self.guided.runs.comparisons(native)
        if (
            accepted is not True
            or not current["matches"]
            or current["fingerprint"] != fingerprint
        ):
            raise ValueError(
                "The saved mappings or selected comparison uses changed. Review them again."
            )
        write_json(
            self.guided.path(project_id, "comparisons-review"),
            {"fingerprint": fingerprint, "accepted": True},
        )
        return {"saved": True}

    def assistant_context(self, project_id):
        """The game's established English beyond its guidance files, for tasks
        that translate text outside Translate runs: the Translate stage's
        output folder, once it exists, and the chosen reference games."""
        _, native = self.guided.record(project_id)
        folder = project_path(
            self.guided.backend.workflows.folder(native["id"]),
            "translated",
            exists=False,
        )
        return {
            "translated": str(folder)
            if folder.is_dir() and any(folder.glob("*.json"))
            else "",
            "references": reference_folders.records(
                self.guided.path(project_id, "reference-folders")
            ),
        }

    def reference_add(self, project_id, folder):
        self.guided.record(project_id)
        return reference_folders.add(
            self.guided.path(project_id, "reference-folders"), folder
        )

    def reference_remove(self, project_id, reference_id):
        self.guided.record(project_id)
        return reference_folders.remove(
            self.guided.path(project_id, "reference-folders"), reference_id
        )

    def context_status(self, project_id, retry_layout=False):
        _, native = self.guided.record(project_id)
        if type(retry_layout) is not bool:
            raise ValueError("Choose whether to retry saving the measured layout.")
        if retry_layout:
            self.guided.layout_failures.pop(project_id, None)
        request_path = self.guided.path(project_id, "context-request")

        def inspect():
            return context_setup.inspect(
                request_path,
                self.guided.path(project_id, "context-review"),
                native,
                project_id,
                self.guided.backend.workflows.documents(native["id"]),
                self.speaker_findings(project_id, native),
                self.speakers(project_id),
                self.guided.observed_digest,
                self.guided.backend.workflows.state(native["id"]).get("references", []),
            )

        setup = inspect()
        update = context_setup.layout_update(
            native, setup, context_setup.optional_record(request_path)
        )
        failure = self.guided.layout_failures.get(project_id)
        if update and failure and failure["reportId"] == update["reportId"]:
            return {**setup, "layoutMessage": failure["message"]}
        draft_path = self.guided.path(project_id, "draft")
        draft = read_json(draft_path) if draft_path.exists() else None
        if (
            update
            and not draft
            and not self.guided.backend.running()
            and not self.guided.translation.jobs.running()
        ):
            try:
                native = self.guided.backend.workflows.apply_layout_settings(
                    native["id"], native["revision"], update
                )
                self.guided.layout_failures.pop(project_id, None)
                setup = inspect()
            except (OSError, ValueError) as exc:
                setup["layoutMessage"] = "Measured layout could not be saved: " + str(
                    exc
                )
                self.guided.layout_failures[project_id] = {
                    "reportId": update["reportId"],
                    "message": setup["layoutMessage"],
                }
        return setup

    def context_review(self, project_id, name, revision, choice):
        self.guided.idle()
        _, native = self.guided.record(project_id)
        documents = self.guided.backend.workflows.documents(native["id"])
        return context_setup.review(
            self.guided.path(project_id, "context-review"),
            documents,
            native,
            name,
            revision,
            choice,
        )

    def speaker_findings(self, project_id, native=None):
        if native is None:
            _, native = self.guided.record(project_id)
        return speaker_setup.inspect(
            self.guided.path(project_id, "speaker-request"),
            native,
            project_id,
            self.guided.observed_digest,
        )

    def apply_speakers(self, project_id, revision, report_id, reset=False):
        self.guided.idle()
        self.guided.clean_options(project_id)
        _, native = self.guided.record(project_id)
        if (
            type(revision) is not int
            or type(reset) is not bool
            or native["revision"] != revision
        ):
            raise ValueError(
                "The guided project changed. Reload before applying speaker findings."
            )
        findings = self.speaker_findings(project_id, native)
        if (
            not report_id
            or findings["reportId"] != report_id
            or findings["status"] not in {"ready", "applied"}
        ):
            raise ValueError(findings["message"])
        if findings["status"] == "applied" and not reset:
            return self.guided.preferences(native)
        options, receipt = speaker_setup.configured(
            self.guided.path(project_id, "speaker-request"),
            native,
            findings,
            reset=reset,
        )
        updated = self.guided.backend.workflows.apply_investigation_settings(
            native["id"], revision, options, "guided_speakers", receipt
        )
        return self.guided.preferences(updated)

    @staticmethod
    def speaker_configuration(native):
        return digest(
            {
                "engine_options": native["engine_options"],
                "phase1_comments": native["phase1_comments"],
            }
        )

    def speakers(self, project_id, scan=False):
        if type(scan) is not bool:
            raise ValueError("Choose whether to run the local speaker scan.")
        _, native = self.guided.record(project_id)
        if scan:
            self.guided.clean_options(project_id)
            findings = self.speaker_findings(project_id, native)
            existing = self.speakers(project_id)
            if findings["status"] == "applied" and (
                existing["current"]
                or existing["job"]
                and existing["job"]["status"] == "running"
            ):
                return existing
            self.guided.idle()
            self.guided.open(project_id)
            _, native = self.guided.record(project_id)
            if findings["status"] not in {"ready", "applied"}:
                raise ValueError(
                    "Identify speaker formats and save their evidence before running the speaker scan."
                )
            self.apply_speakers(project_id, native["revision"], findings["reportId"])
            _, native = self.guided.record(project_id)
            files = self.guided.backend.phase_files(native, "speakers")
            if not files:
                raise ValueError(
                    "Prepare the game’s event JSON before scanning speakers."
                )
            self.guided.backend.operations.start(
                {
                    "project_id": native["id"],
                    "project": deepcopy(native),
                    "folder": str(self.guided.backend.workflows.folder(native["id"])),
                    "action": "speaker_scan",
                    "label": "Scan speaker names",
                    "guard": self.guided.backend.guided_guard(
                        native, self.guided.backend.workflows.folder(native["id"])
                    ),
                    "options": {
                        "files": files,
                        "configuration": self.speaker_configuration(native),
                        "reportId": findings["reportId"],
                    },
                }
            )
        jobs = sorted(
            (
                job
                for job in self.guided.backend.operations.jobs.values()
                if job["project_id"] == native["id"] and job["action"] == "speaker_scan"
            ),
            key=lambda job: job["created"],
            reverse=True,
        )
        job = jobs[0] if jobs else None
        artifact = None
        try:
            artifact = project_path(native["source"], ".dazedtl/guided/speakers.json")
            artifact_hash = self.guided.observed_digest(artifact)
        except OSError, ValueError:
            artifact_hash = None
        saved = next(
            (
                item
                for item in jobs
                if item["status"] == "complete"
                and artifact_hash
                and (item.get("result") or {}).get("artifact_sha256") == artifact_hash
            ),
            None,
        )
        result = saved.get("result") or {} if saved else {}
        available = saved is not None
        current = bool(
            saved
            and job is not None
            and job["id"] == saved["id"]
            and result.get("configuration") == self.speaker_configuration(native)
            and result.get("reportId")
            == native.get("guided_speakers", {}).get("reportId")
            and result.get("reportId")
            == self.speaker_findings(project_id, native)["reportId"]
        )
        if current:
            try:
                root = Path(native["source"])
                data = Path(native["data"])
                data_relative = data.relative_to(root)
                inventory = {
                    path.relative_to(root).as_posix()
                    for path in data.iterdir()
                    if path.is_file() and path.suffix.lower() == ".json"
                }
                scanned = {
                    name
                    for name in result.get("source_inputs", {})
                    if Path(name).parent == data_relative
                    and Path(name).suffix.lower() == ".json"
                }
                current = (
                    inventory == scanned
                    and bool(scanned)
                    and all(
                        self.guided.observed_digest(
                            project_path(native["source"], name)
                        )
                        == sha
                        for name, sha in result["source_inputs"].items()
                    )
                )
            except OSError, ValueError:
                current = False
        return {
            "job": job,
            "available": available,
            "current": current,
            "names": result.get("names", []),
            "actorNames": result.get("actor_names", {}),
            "variableActorIds": result.get("variable_actor_ids", {}),
            "files": result.get("files", 0),
            "savedAt": (saved.get("updated") or saved.get("created"))
            if saved
            else None,
            "path": str(artifact) if available else None,
            "issue": "The saved scan file is missing or no longer matches its saved result."
            if not available and any(item["status"] == "complete" for item in jobs)
            else "",
        }
