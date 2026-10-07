"""Previews and executes Guided actions behind one-use confirmations."""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from . import backups, preparation
from .files import digest, evidence, project_path, verify_evidence
from .operations import lifecycle, verify_guided_review

if TYPE_CHECKING:
    from .guided import Guided

ADVANCED_CODES = {
    "CODE122",
    "CODE357",
    "CODE355655",
    "CODE657",
    "CODE356",
    "CODE320",
    "CODE324",
    "CODE325",
    "CODE108",
}
NATIVE_ACTIONS = {
    "prepare_game",
    "import",
    "format_data",
    "format_plugins",
    "gameupdate",
    "export_selected",
    "ace_decrypt",
    "ace_extract",
    "ace_pack",
    "rewrap_preview",
    "rewrap_apply",
    "qa_prepare",
    "qa_status",
    "qa_apply",
    "runtime_restore",
    "playtest_install",
    "playtest_status",
    "playtest_apply",
    "inspector_install",
    "inspector_remove",
    "forge_install",
    "forge_remove",
    "editors",
    "release",
    "reference_add",
    "reference_pair",
    "reference_remove",
    "reference_build",
    "images_status",
}
TOOL_ACTIONS = {
    "playtest_install",
    "playtest_apply",
    "inspector_install",
    "inspector_remove",
    "forge_install",
    "forge_remove",
}
SHARED_ACTIONS = {
    "backup_source": "Back up original game",
    "git_setup": "Save game version",
    "checkpoint": "Save translation version",
    "guided_review": "Record playtest review",
    "guided_package": "Build local patch ZIP",
    "release_patch": "Build local patch ZIP",
    "refresh_sources": "Reload selected files from game",
}
MANIFEST = ".dazedtl/guided/runtime-manifest.json"


READY_ACTIONS = {
    "start",
    "export_selected",
    "rewrap_apply",
    "qa_apply",
    "runtime_restore",
    "ace_pack",
    "qa_prepare",
    "playtest_install",
    "checkpoint",
    "guided_review",
    "guided_package",
} | TOOL_ACTIONS
PUBLICATION_ACTIONS = {"rewrap_apply", "qa_apply", "runtime_restore"}


@dataclass
class PreviewContext:
    """The checked request every action family prepares its review from."""

    project_id: str
    action: str
    project: dict[str, Any]
    native: dict[str, Any]
    value: dict[str, Any]
    options: dict[str, Any]
    files: list[str] | None
    run_output: dict[str, Any] | None
    release_status: dict[str, Any] | None


@dataclass
class ActionPlan:
    """What a reviewed run or lifecycle operation will do once confirmed."""

    label: str
    paths: list[str]
    options: dict[str, Any]
    expected: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    run_inputs: dict[str, Any] | None = None
    quote: dict[str, Any] | None = None


class GuidedActions:
    def __init__(self, guided: Guided):
        self.guided = guided

    def require_ready(self, project_id, native, action, changed):
        """Translation readiness and unchanged sources for publishing actions."""
        if action in READY_ACTIONS:
            self.guided.translation.ready(project_id)
        if (
            action in PUBLICATION_ACTIONS
            and self.guided.inputs(native).status(
                sorted(self.guided.supported_files(native))
            )["changed"]
        ):
            raise ValueError(changed)

    def require_idle_files(self, native, files):
        """Refuse a run on files an unfinished run will still save results into.

        Starting copies each file's working translation into the new run's
        inputs, so a run that is still saving would lose its later results.
        A Batch saves only while it consumes provider results; submitting
        and waiting at the provider write nothing.
        """
        from dazedtl.compatibility.preparations import temporary

        busy = sorted(
            {
                name
                for identity in self.guided.owned_runs(native)
                if (job := self.guided.backend.manual.jobs.get(identity))
                and job.get("status") in {"running", "waiting"}
                and not temporary(job)
                and (job.get("mode") != "batch" or job.get("phase") == "consume")
                for name in job.get("files", [])
            }
            & set(files)
        )
        if busy:
            raise ValueError(
                f"{', '.join(busy)} {'is' if len(busy) == 1 else 'are'} still "
                "translating. Wait for that run to finish or stop it first."
            )

    @staticmethod
    def pending_run(value):
        job = value.get("manual_job")
        if job and job.get("status") in {"running", "waiting"}:
            raise ValueError(
                "Wait for the active worker before changing runtime files."
            )

    def submission_overlap(self, native, quote):
        """Advisory for a new cost review, never authority to deny a new run."""
        from dazedtl.compatibility.request_scope import overlap

        current = quote["jobId"]
        job = self.guided.run_view(current, compact=True)
        previous = [
            (
                self.guided.backend.manual.folder(identity),
                self.guided.run_view(identity, compact=True),
            )
            for identity in self.guided.owned_runs(native)
            if identity
            and identity != current
            and identity in self.guided.backend.manual.jobs
        ]
        return overlap(self.guided.backend.manual.folder(current), job, previous)

    def saved_output(self, native, run_id, files):
        """A complete Batch or Live run's retained output, for reapplying."""
        if (
            not isinstance(run_id, str)
            or run_id not in self.guided.owned_runs(native)
            or run_id not in self.guided.backend.manual.jobs
        ):
            raise ValueError("Choose a saved run belonging to this project.")
        plan = self.guided.backend.saved_run_configuration(run_id)
        if (plan.get("workflow") or {}).get("id") != native["id"]:
            raise ValueError("This saved run belongs to another project.")
        job = self.guided.run_view(run_id)
        if (
            job.get("mode") not in {"batch", "translate"}
            or job.get("status") != "complete"
            or job.get("temporary")
        ):
            raise ValueError(
                "Wait for this run to finish saving its results before reapplying it."
            )
        outputs = job.get("outputs", {})
        requested = sorted(outputs) if files is None else files
        if (
            not isinstance(requested, list)
            or not requested
            or any(not isinstance(name, str) for name in requested)
            or len(set(requested)) != len(requested)
            or set(requested)
            - (
                set(outputs)
                & set(job.get("files", []))
                & self.guided.supported_files(native)
            )
        ):
            raise ValueError("Choose retained output files from this run.")
        if set(requested) - set(job.get("availableOutputs", [])):
            raise ValueError(
                "Saved output is missing or changed. Its files cannot be reapplied."
            )
        return {
            "run_id": run_id,
            "folder": str(self.guided.backend.manual.folder(run_id)),
            "outputs": {name: outputs[name] for name in requested},
        }, list(requested)

    def preview(
        self, project_id, action, files=None, options: dict[str, Any] | None = None
    ):
        context = self.preview_context(project_id, action, files, options)
        if action == "start":
            plan = self.plan_run(context)
        elif action in SHARED_ACTIONS:
            plan = self.plan_lifecycle(context)
        else:
            return self.preview_native(context)
        return self.confirm(context, plan)

    def preview_context(self, project_id, action, files, options):
        """Checks every action shares before its family prepares a review."""
        if action != "start":
            self.guided.idle(
                isolated_workers=action in {"export_selected", "refresh_sources"}
            )
        project, native = self.guided.record(project_id)
        self.guided.clean(project_id)
        options = {} if options is None else deepcopy(options)
        if not isinstance(options, dict):
            raise ValueError("Action options must be an object.")
        run_output = None
        if action == "export_selected" and options:
            if set(options) != {"run_id"}:
                raise ValueError("Choose a saved Batch to reapply.")
            run_output, files = self.saved_output(native, options["run_id"], files)
        if action not in NATIVE_ACTIONS | SHARED_ACTIONS.keys() | {"start"}:
            raise ValueError("Choose a supported guided action.")
        self.guided.settings.prepare_engine()
        value = self.guided.backend.workflows.state(native["id"])
        if action != "backup_source":
            self.guided.source_preserved(project_id)
        self.require_ready(
            project_id,
            native,
            action,
            "Original sources changed. Review source changes before replacing runtime text.",
        )
        if action.startswith("ace_") and native["engine"] != "ACE":
            raise ValueError("Ace preparation applies to RPG Maker VX Ace games.")
        if action in {"prepare_game", "format_data"}:
            preparation.require_data(native)
        if action == "format_plugins" and native["engine"] == "ACE":
            raise ValueError("Ace does not use plugins.js.")
        if action in TOOL_ACTIONS | {"playtest_status"} and native["engine"] != "MVMZ":
            raise ValueError("TL Inspector and Forge support RPG Maker MV/MZ games.")
        if action in {"release", "release_patch"}:
            release_status = self.guided.release_ready(project_id, native, value)
        else:
            release_status = None
        if action == "git_setup":
            self.guided.require_preparation(project_id, native)
            if type(options.get("untranslated")) is not bool:
                raise ValueError(
                    "Choose whether this game is untranslated or already contains translations."
                )
        return PreviewContext(
            project_id,
            action,
            project,
            native,
            value,
            options,
            files,
            run_output,
            release_status,
        )

    def plan_run(self, context):
        """A translation, estimate or speaker run for the selected phase."""
        project_id, project = context.project_id, context.project
        native = context.native
        value, options = context.value, context.options
        if (
            set(options) - {"mode", "preparation_mode"}
            or options.get("mode") not in {"batch", "translate", "estimate", "speakers"}
            or "preparation_mode" in options
            and (
                options["mode"] != "estimate"
                or options["preparation_mode"] not in {"batch", "translate"}
            )
        ):
            raise ValueError(
                "Choose Batch, Live API, a cost estimate, or speaker collection."
            )
        mode = options["mode"]
        if (
            options.get("preparation_mode")
            and options["preparation_mode"]
            != self.guided.preferences(native)["values"]["mode"]
        ):
            raise ValueError(
                "Save the intended translation mode before preparing its estimate."
            )
        phase = "speakers" if mode == "speakers" else project["phase"]
        if phase == "speakers" and mode != "speakers":
            raise ValueError("Choose a translation phase first.")
        if phase == "advanced":
            settings = native["engine_options"]
            if not any(settings.get(key) is True for key in ADVANCED_CODES):
                raise ValueError(
                    "Audit advanced text and enable only confirmed player-visible sources, or skip this phase."
                )
            if (
                settings.get("CODE122") is True
                and not settings.get("CODE122_VAR_RANGES", "").strip()
            ):
                raise ValueError(
                    "Enter the variable IDs confirmed by the audit before translating variables (122)."
                )
        paths = [
            name
            for name in self.guided.backend.phase_files(native, phase)
            if name in native["selected"]
        ]
        if not paths:
            raise ValueError("Select game files belonging to this phase first.")
        self.require_idle_files(native, paths)
        if self.guided.inputs(native).status(
            sorted(self.guided.supported_files(native))
        )["changed"]:
            raise ValueError(
                "The original source changed. Review source changes and refresh the working copies before preparing a new run."
            )
        if value["project"].get("collection_error"):
            raise ValueError(value["project"]["collection_error"])
        options["phase"] = phase
        if phase == "variables":
            comparisons = self.guided.runs.comparisons(native)
            if not comparisons["matches"]:
                raise ValueError(
                    "Translate the relevant audited assignments first. No saved mappings match the selected comparisons. "
                    + comparisons["message"]
                )
            if comparisons["status"] != "ready":
                raise ValueError(
                    "Review every matched literal and its variable uses before updating comparisons."
                )
        if phase == "advanced":
            self.guided.event_text.require(project_id, native)
        run_inputs = None
        quote = None
        if mode != "speakers":
            target_mode = (
                self.guided.preferences(native)["values"]["mode"]
                if mode == "estimate"
                else mode
            )
            matched, run_inputs = self.guided.runs.quote(
                project_id, native, phase, target_mode
            )
            if mode != "estimate":
                if not matched["current"]:
                    raise ValueError(
                        "Calculate a current estimate for this phase, selection, and settings before reviewing translation."
                    )
                quote = {
                    "jobId": matched["job"]["id"],
                    "fingerprint": run_inputs["fingerprint"],
                    "value": matched["job"]["estimate"],
                    "model": matched["job"].get("model", ""),
                    "connection": (self.guided.settings.connection_summary() or {}).get(
                        "name", ""
                    ),
                }
                try:
                    quote["repeatSubmission"] = bool(
                        self.submission_overlap(native, quote)
                    )
                except OSError, ValueError, KeyError:
                    # Unreadable historical evidence cannot veto a separately
                    # approved run either; keep the repeat-charge notice.
                    quote["repeatSubmission"] = True
        label = {
            "batch": "Prepare Batch translation",
            "translate": "Start Live API translation",
            "estimate": "Estimate selected phase",
            "speakers": "Collect speaker names",
        }[mode]
        return ActionPlan(label, paths, options, run_inputs=run_inputs, quote=quote)

    def plan_lifecycle(self, context):
        """Backups, version baselines, resync and release lifecycle operations."""
        project_id, action = context.project_id, context.action
        project = context.project
        native, files = context.native, context.files
        options: dict[str, Any] = context.options
        release_status = context.release_status
        paths, expected, manifest = [], None, None
        label = SHARED_ACTIONS[action]
        allowed = (
            {"version", "original", "untranslated"}
            if action == "git_setup"
            else {"reviewed", "playtested"}
            if action == "guided_review"
            else {"output"}
            if action == "release_patch"
            else set()
        )
        if set(options) - allowed:
            raise ValueError("Unknown guided action option.")
        if action == "backup_source":
            saved = lifecycle(self.guided.translation.workspace, project_id).get(
                "source_backup"
            )
            if (
                saved
                and backups.record_status(project["source"], saved, kind="source")[
                    "available"
                ]
            ):
                raise ValueError(
                    "The original is already preserved. Use workspace backups for later milestones."
                )
        if action == "refresh_sources":
            if (
                not isinstance(files, list)
                or not files
                or any(not isinstance(name, str) for name in files)
                or len(set(files)) != len(files)
                or set(files) - self.guided.supported_files(native)
            ):
                raise ValueError("Select supported files to refresh.")
            paths = files
            options = {
                "sources": self.guided.inputs(native).sources(
                    paths, self.guided.inputs(native).record()["inputs"], fresh=True
                )
            }
        if action in {"git_setup", "checkpoint", "guided_review", "release_patch"}:
            paths = self.guided.release_paths(project_id, project["source"], action)
            manifest = self.guided.patch_manifest(project_id, paths, action)
            expected = evidence(project["source"], [*paths, *manifest["inputs"]])
        if action == "release_patch":
            from .release import destination, git_identity, output_hash

            output = destination(
                project["source"],
                self.guided.translation.workspace,
                self.guided.backend.source,
                options.get("output"),
            )
            options = {
                "output": str(output),
                "output_hash": output_hash(output),
                "source_inputs_sha256": digest(self.guided.inputs(native).record()),
                "git": git_identity(release_status),
            }
        if action == "guided_review" and (
            options.get("reviewed") is not True or options.get("playtested") is not True
        ):
            raise ValueError(
                "Review the translated scope and playtest it before recording release readiness."
            )
        if action == "guided_review":
            options["source_inputs_sha256"] = digest(
                self.guided.inputs(native).record()
            )
        if action == "guided_package":
            self.verify_review(project_id, native)
        return ActionPlan(label, paths, options, expected=expected, manifest=manifest)

    def preview_native(self, context):
        """Engine workflow actions, reviewed by the engine's own plan and token."""
        project_id, action = context.project_id, context.action
        project = context.project
        native, value, files = context.native, context.value, context.files
        run_output = context.run_output
        options: dict[str, Any] = context.options
        paths = []
        if action == "import":
            if not isinstance(files, list) or any(
                not isinstance(name, str)
                or name not in self.guided.supported_files(native)
                for name in files
            ):
                raise ValueError(
                    "Select supported RPG Maker files from this project's list."
                )
            options = {"files": files or []}
        elif action == "export_selected" and run_output:
            paths = files
            options = {"files": paths, "run_id": run_output["run_id"]}
        elif action == "export_selected":
            if value["project"].get("collection_error"):
                raise ValueError(value["project"]["collection_error"])
            requested = native["selected"] if files is None else files
            if (
                not isinstance(requested, list)
                or any(not isinstance(name, str) for name in requested)
                or len(set(requested)) != len(requested)
                or set(requested) - set(native["selected"])
            ):
                raise ValueError("Choose saved outputs within the selected scope.")
            paths = [
                name
                for name in requested
                if self.guided.inputs(native).path("translated", name).is_file()
            ]
            if files is not None and paths != files:
                raise ValueError(
                    "The selected run outputs are no longer available. Review current outputs."
                )
            if not paths:
                raise ValueError(
                    "No saved translation output is available for these files yet."
                )
            options = {"files": paths}
        if action == "release":
            from .release import destination

            if set(options) != {"output"}:
                raise ValueError("Choose the release destination.")
            options["output"] = str(
                destination(
                    project["source"],
                    self.guided.translation.workspace,
                    self.guided.backend.source,
                    options["output"],
                )
            )
        result = (
            self.guided.backend.guided_text_preview(native["id"], action, options)
            if action in {"runtime_restore", "qa_apply"}
            else self.guided.backend.guided_export_preview(
                native["id"], paths, run_output=run_output
            )
            if run_output
            else self.guided.backend.guided_export_preview(native["id"], paths)
            if action == "export_selected"
            else self.guided.backend.guided_preparation_preview(
                native["id"], action, options
            )
            if action == "prepare_game"
            else self.guided.backend.workflows.preview(native["id"], action, options)
        )
        token = result["token"]
        if action in TOOL_ACTIONS:
            configured = self.guided.saved_form(project_id)["release"]["tools"]
            if (
                not configured["hotkey"].strip()
                or not configured["forgeHotkey"].strip()
            ):
                raise ValueError("Choose hotkeys for the playtest tools.")
            self.guided.backend.guided_configure_tools(token, configured)
        if action == "release":
            result.update(self.guided.backend.guided_release_preview(token))
        if action == "rewrap_apply":
            result["rewrap"] = self.guided.backend.guided_rewrap_review(
                native["id"], token
            )
        if action in {"export_selected", "rewrap_apply"}:
            result.update(self.guided.backend.guided_text_publication(token))
        reviewed_paths = (
            paths or result.get("paths") or result["options"].get("files", [])
        )
        self.guided.confirmations = {
            token: {
                "project_id": project_id,
                "action": action,
                "native": True,
                "paths": list(reviewed_paths),
                "revision": native["revision"],
                "phase": project["phase"],
                "settings_revision": self.guided.settings.describe()["revision"],
            }
        }
        # Routine preparation uses the same one-use plan and execution checks,
        # without asking the user to confirm the button they just clicked.
        return {
            **result,
            "action": action,
            "paths": reviewed_paths,
            "confirmation": (
                bool(result.get("overwrite"))
                if action == "release"
                else result["confirmation"]
                and action
                not in {
                    "prepare_game",
                    "ace_decrypt",
                    "ace_extract",
                    "format_data",
                    "format_plugins",
                    "gameupdate",
                    "qa_prepare",
                    "playtest_install",
                    "playtest_apply",
                    "inspector_install",
                    "forge_install",
                    "reference_build",
                    "reference_remove",
                }
            ),
        }

    def confirm(self, context, plan):
        """Freezes a reviewed plan behind a one-use token."""
        project_id, action = context.project_id, context.action
        project = context.project
        native, release_status = context.native, context.release_status
        label, paths, options = plan.label, plan.paths, plan.options
        expected, manifest = plan.expected, plan.manifest
        run_inputs, quote = plan.run_inputs, plan.quote
        token = uuid.uuid4().hex
        self.guided.confirmations = {
            token: {
                "project_id": project_id,
                "action": action,
                "options": options,
                "paths": paths,
                "evidence": expected,
                "manifest": manifest,
                "guard": self.guided.backend.guided_guard(
                    native, self.guided.backend.workflows.folder(native["id"])
                ),
                "revision": native["revision"],
                "phase": project["phase"],
                "settings_revision": self.guided.settings.describe()["revision"],
                "run_inputs": run_inputs if action == "start" else None,
                "estimate": quote if action == "start" else None,
            }
        }
        destination = (
            str(backups.store_path(project["source"]))
            if action == "backup_source"
            else options["output"]
            if action == "release_patch"
            else project["source"]
        )
        return {
            "token": token,
            "action": action,
            "label": label,
            "destination": destination,
            "files": len(paths),
            "paths": paths,
            "options": options,
            "estimate": quote if action == "start" else None,
            "run": {
                "model": quote["model"],
                "connection": quote["connection"],
                "mode": options["mode"],
            }
            if action == "start" and quote
            else None,
            "confirmation": (
                bool(
                    lifecycle(self.guided.translation.workspace, project_id).get(
                        "source_backup"
                    )
                )
                if action == "backup_source"
                # Setup saves the version from the form it shows, right after
                # backing up and preparing; execution rechecks the same scope.
                else action != "git_setup"
                and not (action == "start" and options["mode"] == "estimate")
            ),
            "package": {
                "included": len(paths),
                "excluded": int(
                    (Path(project["source"]) / "gameupdate/patch-config.txt").is_file()
                ),
                "exclusions": [
                    {
                        "path": "gameupdate/patch-config.txt",
                        "reason": "GameUpdate disabled in this local patch; publication is separate",
                    }
                ]
                if (Path(project["source"]) / "gameupdate/patch-config.txt").is_file()
                else [],
                "updater": "GameUpdate configuration is omitted from local patches. Publishing is separate.",
                "generated": [".gitignore", ".gitattributes", "README.md"],
            }
            if action == "release_patch"
            else None,
            "overwrite": bool(options.get("output_hash"))
            if action == "release_patch"
            else False,
            "game_version": release_status.get("original_version")
            if action == "release_patch"
            else None,
            "additions": [
                name
                for name, row in manifest["files"].items()
                if row.get("original_sha256", "") is None
            ]
            if manifest
            else [],
        }

    def execute(self, project_id, token):
        confirmed = self.guided.confirmations.get(token)
        if not confirmed or confirmed["project_id"] != project_id:
            raise ValueError("The action changed. Review a new preview.")
        self.guided.clean(project_id)
        project, native = self.guided.record(project_id)
        self.guided.confirmations.pop(token)
        action = confirmed["action"]
        if action != "start":
            self.guided.idle(
                isolated_workers=action in {"export_selected", "refresh_sources"}
            )
        if action != "backup_source":
            self.guided.source_preserved(project_id)
        self.require_ready(
            project_id,
            native,
            action,
            "Original sources changed after review. Review current sources first.",
        )
        if action in {"release", "release_patch"}:
            release_status = self.guided.release_ready(
                project_id, native, self.guided.backend.workflows.state(native["id"])
            )
        else:
            release_status = None
        if confirmed.get("native"):
            if (
                confirmed["revision"] != native["revision"]
                or confirmed["phase"] != project["phase"]
                or confirmed["settings_revision"]
                != self.guided.settings.describe()["revision"]
            ):
                raise ValueError(
                    "The selection or settings changed. Review the action again."
                )
            if action == "release":
                self.guided.backend.guided_release_validate(token)
            return self.guided.backend.workflows.execute(token)
        if (
            confirmed["guard"]
            != self.guided.backend.guided_guard(
                native, self.guided.backend.workflows.folder(native["id"])
            )
            or confirmed["revision"] != native["revision"]
            or confirmed["phase"] != project["phase"]
            or confirmed["settings_revision"]
            != self.guided.settings.describe()["revision"]
        ):
            raise ValueError(
                "The game, selection, or settings changed. Review the action again."
            )
        if confirmed["evidence"]:
            verify_evidence(project["source"], confirmed["evidence"])
            if (
                self.guided.release_paths(project_id, project["source"], action)
                != confirmed["paths"]
            ):
                raise ValueError(
                    "The runtime file list changed. Review the complete patch again."
                )
        options = confirmed["options"]
        if action == "release_patch":
            from .release import git_identity

            if git_identity(release_status) != options["git"]:
                raise ValueError(
                    "Version tracking changed. Review the current patch scope again."
                )
        if action == "start":
            return self.execute_run(project_id, native, confirmed)
        return self.execute_lifecycle(project_id, project, native, confirmed, options)

    def execute_run(self, project_id, native, confirmed):
        """Rechecks a run's estimate binding before starting it."""
        options = confirmed["options"]
        if confirmed["run_inputs"]:
            current = self.guided.runs.inputs(
                project_id,
                native,
                options["phase"],
                confirmed["run_inputs"]["mode"],
            )
            if current["fingerprint"] != confirmed["run_inputs"]["fingerprint"]:
                raise ValueError(
                    "The estimate inputs changed. Refresh the estimate and review this run again."
                )
            if options["mode"] != "estimate":
                matched, _ = self.guided.runs.quote(
                    project_id, native, options["phase"], options["mode"]
                )
                if (
                    not matched["current"]
                    or matched["job"]["id"] != confirmed["estimate"]["jobId"]
                ):
                    raise ValueError(
                        "The matching estimate changed. Review a new preview."
                    )
        return self._start(
            project_id,
            options["mode"],
            options["phase"],
            confirmed["paths"],
            confirmed["run_inputs"],
            confirmed["estimate"],
            options.get("preparation_mode"),
        )

    def execute_lifecycle(self, project_id, project, native, confirmed, options):
        """Runs a reviewed lifecycle operation after rechecking its scope."""
        action = confirmed["action"]
        if action == "refresh_sources":
            return self.guided.backend.guided_refresh(
                native, confirmed["paths"], options["sources"]
            )
        if action == "git_setup":
            self.guided.require_preparation(project_id, native)
        if action in {"git_setup", "checkpoint", "guided_review", "release_patch"}:
            if confirmed["manifest"] != self.guided.patch_manifest(
                project_id, confirmed["paths"], action
            ):
                raise ValueError(
                    "The original or runtime scope changed. Review the patch again."
                )
            write_json(
                project_path(project["source"], MANIFEST, exists=False),
                confirmed["manifest"],
            )
            options = {**options, "manifest": MANIFEST}
        if action == "release_patch":
            from .release import output_hash

            inputs = self.guided.inputs(native)
            current = inputs.record()
            if (
                digest(current) != options["source_inputs_sha256"]
                or output_hash(options["output"]) != options["output_hash"]
            ):
                raise ValueError(
                    "The source pass or release destination changed. Review a new package preview."
                )
            if not inputs.index.exists():
                write_json(inputs.index, current)
            payload = {
                "version": 1,
                "project_id": project_id,
                "source": project["source"],
                "manifest": MANIFEST,
                "evidence": evidence(
                    project["source"],
                    [
                        MANIFEST,
                        *confirmed["paths"],
                        *confirmed["manifest"].get("inputs", []),
                    ],
                ),
                "source_inputs": inputs.index.relative_to(
                    self.guided.translation.workspace
                ).as_posix(),
                "source_inputs_sha256": digest(current),
                "git": options["git"],
                "output": options["output"],
                "output_hash": options["output_hash"],
            }
            path = self.guided.path(project_id, "release-" + uuid.uuid4().hex)
            write_json(path, payload)
            return self.guided.translation.guided_operation(
                project_id,
                "release_patch",
                {
                    "plan": path.relative_to(
                        self.guided.translation.workspace
                    ).as_posix(),
                    "sha256": digest(payload),
                },
            )
        if action == "guided_review":
            inputs = self.guided.inputs(native)
            current = inputs.record()
            if digest(current) != options["source_inputs_sha256"]:
                raise ValueError("Working sources changed. Review this pass again.")
            if not inputs.index.exists():
                write_json(inputs.index, current)
            options = {
                "manifest": MANIFEST,
                "source_inputs": inputs.index.relative_to(
                    self.guided.translation.workspace
                ).as_posix(),
                "source_inputs_sha256": digest(current),
            }
        if action == "guided_package":
            self.verify_review(project_id, native)
        operation = (
            self.guided.translation.guided_operation
            if action in {"guided_review", "guided_package"}
            else self.guided.translation.operation
        )
        return operation(project_id, action, options)

    def verify_review(self, project_id, native):
        state = lifecycle(self.guided.translation.workspace, project_id)
        review = verify_guided_review(
            native["source"],
            state,
            self.guided.translation.workspace,
            self.guided.translation.engine,
        )
        inputs = self.guided.inputs(native)
        if (
            not review.get("source_inputs_sha256")
            and inputs.record().get("last_refresh")
            or inputs.status(sorted(self.guided.supported_files(native)))["changed"]
        ):
            raise ValueError(
                "Source work changed after review. Playtest and record the current pass again."
            )

    def _start(
        self,
        project_id,
        mode,
        phase,
        files,
        run_inputs=None,
        estimate=None,
        preparation_mode=None,
    ):
        _, native = self.guided.record(project_id)
        if self.guided.resyncing(native):
            raise ValueError(
                "Wait for the working files to finish resyncing before preparing translation."
            )
        if mode == "estimate":
            from dazedtl.compatibility.preparations import temporary

            records = self.guided.runs.records(project_id)
            for identity in self.guided.owned_runs(native):
                job = self.guided.backend.manual.jobs.get(identity)
                record = records.get(identity, {})
                if job and temporary(job) and record.get("phase") == phase:
                    self.guided.discard_preparation(project_id, identity)
                elif job and job.get("approval") and record.get("phase") == phase:
                    self.guided.answer(project_id, job["approval"]["token"], False)
        if preparation_mode:
            assert run_inputs is not None  # Preparation follows a confirmed estimate.
            for identity, record in reversed(
                list(self.guided.runs.records(project_id).items())
            ):
                job = self.guided.backend.manual.jobs.get(identity)
                if (
                    job
                    and job.get("mode") == "estimate"
                    and job.get("status") in {"ready", "running", "waiting"}
                    and record.get("preparation_mode") == preparation_mode
                    and record.get("fingerprint") == run_inputs["fingerprint"]
                ):
                    return self.guided.run_view(identity)
        self.require_idle_files(native, files)
        self.guided.inputs(native).prepare(files)
        native["imported"] = list(dict.fromkeys([*native["imported"], *files]))
        self.guided.backend.workflows.save(native)
        self.guided.settings.prepare_engine(mode=mode)
        self.guided.backend.manual.source_versions = (
            run_inputs.get("file_versions", {}) if run_inputs else {}
        )
        self.guided.backend.manual.reused_names = (
            run_inputs.get("reused_names", []) if run_inputs else []
        )
        self.guided.backend.manual.continuation = (
            self.guided.runs.continuation(project_id, native, run_inputs)
            if run_inputs
            else {}
        )
        from dazedtl.compatibility.request_scope import requests

        self.guided.backend.manual.reserved_sources = (
            list(
                requests(
                    self.guided.backend.manual.folder(estimate["jobId"]),
                    self.guided.run_view(estimate["jobId"]),
                )
            )
            if estimate
            else []
        )
        previous_mode = self.guided.preferences(native)["values"]["mode"]
        if mode != "speakers":
            self.guided.backend.workflows.update(
                native["id"], native["revision"], {"mode": mode}
            )
        try:
            self.guided.backend.manual.temporary_preparation = mode in {
                "estimate",
                "batch",
            }
            job = self.guided.backend.guided_phase(native["id"], phase, files)
            if run_inputs:
                self.guided.runs.remember(
                    project_id, job, run_inputs, estimate, preparation_mode
                )
            if estimate and self.guided.backend.manual.jobs.get(
                estimate["jobId"], {}
            ).get("dazedtl_preapproval"):
                self.guided.discard_preparation(project_id, estimate["jobId"])
            return {**job, "logicalPhase": phase, "preparationMode": preparation_mode}
        finally:
            self.guided.backend.manual.temporary_preparation = False
            self.guided.backend.manual.continuation = None
            self.guided.backend.manual.source_versions = None
            self.guided.backend.manual.reused_names = None
            self.guided.backend.manual.reserved_sources = None
            if mode == "estimate":
                current = self.guided.backend.workflows.projects[native["id"]]
                self.guided.backend.workflows.update(
                    native["id"], current["revision"], {"mode": previous_mode}
                )
