"""One project service shared by the Electron UI and the external agent helper."""

import json
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from dazedtl.settings.execution import configuration, connection_summary
from dazedtl.storage import write_bytes, write_json

from . import backups, delivery, progress_report
from .compilation import compile_requests, verify_compilation
from .files import digest, evidence, project_path, read_json, verify_evidence
from .helper_command import git_note, helper_command
from .jobs import Jobs, now
from .operations import (
    checkout_issue,
    lifecycle,
    reconcile_missing_backups,
    require_baseline,
)
from .project import ADDED, WORK, ProjectWorkspace, options, scope
from .requests import plan_input, quote
from .results import Results

# Set while the project helper, run by the user's assistant, makes a request.
assistant_request = ContextVar("assistant_request", default=False)

OPERATIONS = {
    "backup_source": ("Back up original game", set()),
    "use_source_backup": ("Use the game's saved original", {"backup_id"}),
    "backup_workspace": ("Back up project files", set()),
    "restore_backup": (
        "Restore backup into a new folder",
        {"backup_id", "destination"},
    ),
    "rpgmaker_prepare": ("Prepare RPG Maker files", {"data_path"}),
    "git_setup": (
        "Save game version",
        {"version", "original", "untranslated", "manifest"},
    ),
    "write_rpgmaker": (
        "Write source-preserving game JSON",
        {"source", "translated", "output", "backup_id"},
    ),
    "rebase_rpgmaker": (
        "Rebase source metadata to the current original",
        {"source", "translated", "output", "backup_id", "expected_original_commit"},
    ),
    "checkpoint": ("Save translation version", {"manifest", "message"}),
    "package": ("Package local translation patch", set()),
    "stage_update": (
        "Stage a new original for engine preparation",
        {"official", "version"},
    ),
    "version_preview": (
        "Preview official game update",
        {"official", "version", "baseline", "patch_overlay"},
    ),
    "version_apply": ("Apply reviewed official update", {"preview_id"}),
    "version_continue": ("Continue resolved official update", set()),
    "version_abort": ("Abort official update", set()),
    "version_handoff": ("Prepare post-update translation prompt", set()),
    "discard_release": ("Discard a staged official release", {"stage"}),
}

GUIDED_OPERATIONS = {
    "guided_review": (
        "Record guided playtest review",
        {"manifest", "source_inputs", "source_inputs_sha256"},
    ),
    "guided_package": ("Package reviewed guided patch", set()),
    "release_patch": ("Build local patch ZIP", {"plan", "sha256"}),
}

# The Image Manager's progress as Len image records, which the app writes.
IMAGE_UNITS = WORK + "/work/image-units.json"

# Started only from the app's own controls; the project helper cannot reach
# these, so an assistant can never start its own project over.
USER_OPERATIONS = {
    "start_over": ("Start over from the original game", {"keep_context"}),
}


class Translation:
    def __init__(self, workspace, projects, settings, engine, *, jobs=None):
        self.workspace = Path(workspace)
        self.projects = projects
        self.settings = settings
        self.engine = engine
        self.originals = {}
        self.jobs = jobs or Jobs(workspace, settings.adapter.allow_providers)
        self.contacts = {}
        self.contact_lock = threading.Lock()
        # The API server installs handlers for the retained legacy run actions.
        self.legacy_actions: dict[str, Callable[..., Any]] = {}
        # And the Image Manager's progress for Assistant-led image records.
        self.image_units: Callable[[str], dict | None] | None = None

    def project(self, identity):
        record = self.projects.get(identity)
        return record, ProjectWorkspace(record["source"])

    def contact_path(self, project_id):
        return self.workspace / "translation/projects" / project_id / "assistant.json"

    def contacted(self, project_id):
        """Note that the user's assistant reached this project through the
        helper, at most once a minute, so Progress shows its run started
        before the first report."""
        if not isinstance(project_id, str):
            return
        with self.contact_lock:
            last = self.contacts.get(project_id)
            if last is not None and time.monotonic() - last < 60:
                return
            try:
                self.projects.get(project_id)
                write_json(self.contact_path(project_id), {"seen_at": now()})
            except ValueError, OSError:
                # An unknown project or a failed note never fails the call.
                return
            self.contacts[project_id] = time.monotonic()

    def seen(self, project_id):
        """When the user's assistant last reached this project, if ever."""
        try:
            return read_json(self.contact_path(project_id))["seen_at"]
        except OSError, ValueError, KeyError, TypeError:
            return None

    def default_mode(self):
        """New projects start on Batch, or on Live when the active connection
        cannot run Batch, as Guided does."""
        connection = connection_summary(self.settings)
        return (
            "live"
            if connection
            and connection["model"]
            and not self.settings.translation_defaults().get("batch_supported")
            else "batch"
        )

    def options(self, project):
        return project.read(self.default_mode())

    def idle(self, identity, kind=None):
        if self.jobs.running(identity, kind):
            raise ValueError(
                "Pause this project's active operation before changing its inputs."
            )
        if self.settings.adapter.running():
            raise ValueError(
                "Finish or pause the existing phased run before changing project inputs."
            )

    def draft_path(self, identity):
        self.projects.get(identity)
        return self.workspace / "translation/projects" / identity / "draft.json"

    def drafts(self, identity):
        path = self.draft_path(identity)
        value = (
            read_json(path, limit=4_000_000)
            if path.exists()
            else {"options": None, "documents": {}}
        )
        value["options"] = self.pending_options(identity, value["options"])
        record = self.projects.get(identity)
        legacy = record.get("backend_id")
        if legacy and legacy in self.settings.adapter.workflows.projects:
            value["documents"] = (
                self.settings.adapter.workflows.state(legacy)
                .get("draft", {})
                .get("documents", {})
            )
        return value

    def pending_options(self, identity, value):
        """An options draft, or None when it matches the saved options, such
        as after turning a choice off and on again: it holds no edit to save,
        so it must not hold up preparing or running work."""
        if not value:
            return None
        # Drafts saved before an option existed take its default.
        value = {**value, "options": {**ADDED, **value["options"]}}
        _record, project = self.project(identity)
        return None if value["options"] == self.options(project)["options"] else value

    def draft(self, project_id, section, value):
        if section not in {"options", "documents"}:
            raise ValueError("Unknown project draft.")
        if section == "options" and value is not None:
            if (
                not isinstance(value, dict)
                or set(value) != {"revision", "options"}
                or not isinstance(value["revision"], str)
            ):
                raise ValueError("Invalid options draft.")
            options(value["options"])
            value = self.pending_options(project_id, value)
        if section == "documents":
            if (
                not isinstance(value, dict)
                or len(json.dumps(value).encode("utf-8")) > 3_500_000
            ):
                raise ValueError("Invalid guidance draft.")
            for name, document in value.items():
                if (
                    not self.engine.valid_document(name)
                    or not isinstance(document, dict)
                    or set(document) != {"text", "revision"}
                    or not all(isinstance(item, str) for item in document.values())
                ):
                    raise ValueError("Invalid guidance draft.")
        current = self.drafts(project_id)
        legacy = self.projects.get(project_id).get("backend_id")
        if (
            section == "documents"
            and legacy
            and legacy in self.settings.adapter.workflows.projects
        ):
            before = self.settings.adapter.workflows.state(legacy).get("draft", {})
            return self.settings.adapter.workflows.draft(
                legacy, {**before, "documents": value}
            )
        current[section] = value
        if legacy:
            current["documents"] = {}
        write_json(self.draft_path(project_id), current)
        return {"saved": True}

    def save(self, project_id, revision, values):
        self.idle(project_id)
        _record, project = self.project(project_id)
        saved = project.save(revision, values, self.default_mode())
        self.draft(project_id, "options", None)
        return saved

    def documents(self, project_id):
        record, _project = self.project(project_id)
        return self.engine.documents(record["source"])

    def save_document(self, project_id, name, revision, text):
        self.idle(project_id)
        record, _project = self.project(project_id)
        result = self.engine.document_save(record["source"], name, revision, text)
        pending = self.drafts(project_id)["documents"]
        pending.pop(name, None)
        self.draft(project_id, "documents", pending)
        return result

    def clean_drafts(self, project_id):
        value = self.drafts(project_id)
        if value["options"] or value["documents"]:
            raise ValueError(
                "Save or discard project drafts before preparing or running work."
            )

    def legacy_record(self, project_id):
        record = self.projects.get(project_id)
        backend_id = record.get("backend_id")
        native = self.settings.adapter.workflows.projects.get(backend_id)
        return (
            self.settings.adapter.manual.jobs.get(native.get("manual_job"))
            if native
            else None
        )

    def ready(self, project_id):
        _record, project = self.project(project_id)
        return require_baseline(
            self.engine,
            project.root,
            project.read()["options"],
            lifecycle(self.workspace, project_id),
        )

    def state(self, project_id):
        record, project = self.project(project_id)
        selected = self.options(project)
        warnings = []
        try:
            progress = self.engine.progress(project.root, selected["options"])
        except ValueError, OSError, TypeError, KeyError:
            progress = None
            warnings.append(
                "Saved progress could not be read. Inspect the workspace before continuing."
            )
        if progress and progress["phases"].get("qa") == "complete":
            try:
                delivery.verify(project.root)
            except ValueError, OSError, KeyError, TypeError:
                warnings.append(
                    "Runtime QA evidence is missing or stale. Review affected outputs before packaging."
                )
        try:
            git = self.engine.git_status(project.root, selected["options"])
        except Exception:  # noqa: BLE001
            git = None
            warnings.append(
                "Git status is unavailable. Git must be installed and this game's baselines verified before translation."
            )
        # The checkout problem that would refuse every change to the game.
        if git and git.get("configured") and (issue := checkout_issue(git)):
            warnings.append(issue)
        self.jobs.reconcile()
        saved_jobs = self.jobs.store.list(project_id)[:30]
        warnings.extend(self.jobs.store.warnings)
        status = project_path(project.root, WORK + "/status.md", exists=False)
        identification = (
            self.workspace / "translation/projects" / project_id / "engine.json"
        )
        engine = self.engine.detect(project.root)
        saved_lifecycle = lifecycle(self.workspace, project_id)
        stored = (
            None
            if saved_lifecycle.get("source_backup")
            else self.stored_original(project.root)
        )
        titles = {
            "source_backup": "Source backup",
            "game_backup": "Latest game backup",
            "prepared_source": "Prepared original backup",
            "workspace_backup": "Workspace backup",
        }
        for key, kind in (
            ("source_backup", "source"),
            ("game_backup", "source"),
            ("prepared_source", "source"),
            ("workspace_backup", "workspace"),
        ):
            if saved_lifecycle.get(key):
                saved_lifecycle[key] = backups.record_status(
                    project.root, saved_lifecycle[key], kind=kind
                )
        # A deleted store leaves nothing to recover, so retire its records
        # instead of warning about them on every read. A store that kept its
        # snapshots but lost a recorded one still warns, for recovery.
        reconcile_missing_backups(
            self.workspace, project_id, project.root, saved_lifecycle
        )
        for key, title in titles.items():
            entry = saved_lifecycle.get(key)
            if entry and not entry["available"]:
                warnings.append(title + " is unavailable. " + entry["issue"])
        if identification.is_file():
            identified = read_json(identification)
            try:
                verify_evidence(project.root, identified["evidence"])
                engine = identified["engine"]
            except ValueError, OSError:
                warnings.append(
                    "The reported engine evidence changed. Recheck the engine before adapting its tools."
                )
        legacy = self.legacy_record(project_id)
        return {
            "projectId": project_id,
            **selected,
            "drafts": self.drafts(project_id),
            "engine": engine,
            "documents": self.documents(project_id),
            "progress": progress,
            "assistantSeenAt": self.seen(project_id),
            "git": git,
            "lifecycle": saved_lifecycle,
            **(
                {
                    "storedOriginal": {
                        key: stored[key]
                        for key in (
                            "id",
                            "kind",
                            "created",
                            "files",
                            "version",
                            "bytes_total",
                        )
                    }
                }
                if stored
                else {}
            ),
            "jobs": self.job_views(saved_jobs, selected["options"]["mode"]),
            "active": self.jobs.running(project_id),
            "warnings": warnings,
            "statusText": status.read_text(encoding="utf-8")[:250_000]
            if status.is_file() and status.stat().st_size <= 5_000_000
            else "",
            "providerEnabled": self.settings.adapter.allow_providers,
            "connection": connection_summary(self.settings),
            "batchSupported": bool(
                self.settings.translation_defaults().get("batch_supported")
            ),
            "legacyRun": (
                {
                    key: value
                    for key, value in legacy.items()
                    if key
                    in {
                        "id",
                        "mode",
                        "status",
                        "phase",
                        "message",
                        "approval",
                        "outputs",
                    }
                }
                if legacy
                else None
            ),
            "legacyAvailable": bool(
                record.get("backend_id") in self.settings.adapter.workflows.projects
            ),
        }

    def prepare(self, project_id):
        # An API run can wait hours at the provider, and its frozen requests
        # depend on the guidance preparing rewrites. Meanwhile the prompt is
        # built on the inputs already prepared, so the assistant can resume.
        frozen = self.jobs.running(project_id) and not self.jobs.running(
            project_id, "operation"
        )
        if not frozen:
            self.idle(project_id)
        self.clean_drafts(project_id)
        _record, project = self.project(project_id)
        mode = self.default_mode()
        selected = project.read(mode)
        if not selected["initialized"]:
            self.idle(project_id)
            selected = project.save(selected["revision"], selected["options"], mode)
        setup = self.engine.prepare(
            project.root, selected["options"], refresh=not frozen
        )
        command = helper_command(self.workspace, project_id)
        mode = {
            "agent": "Assistant only (you translate every line in this session; DazedTL makes no translation API calls)",
            "live": "Live API (DazedTL sends one request at a time through the user's API connection)",
            "batch": "API Batch (DazedTL submits provider Batch jobs through the user's API connection)",
        }[selected["options"]["mode"]]
        investigation = (
            "Investigation: thorough. Run setup.md's Three-pass discovery as written."
            if selected["options"]["thorough_investigation"]
            else "Investigation: standard. setup.md describes One-pass discovery; follow it, and don't run the three blind passes some skill references describe."
        )
        instructions = selected["options"]["instructions"].strip() or "(none)"
        images = (
            "\n9. Images: translate them through DazedTL's Images steps rather than Len's manual image pipeline; "
            "images --status says which step comes next, and the steps resume where they stopped. "
            "images --scan indexes the game's images, decrypting encrypted ones. "
            "images --investigate saves a task file and the report path it expects: follow the task to find the images with text players read, then save the report. "
            "Your recommendations become the list. images --translate makes editable copies of the listed images and saves the translation task, "
            "which carries the image skill and the local inpainting tools; follow it and save its report. "
            "Change only the text and the pixels it covers. Report an image you can't or won't edit as skipped, with the reason; it stays out of the patch. "
            "images --apply puts the translated, reviewed images into the game, encrypted as the game expects, and lists the runtime files it changed: "
            "add them to the runtime patch manifest before QA and the checkpoint. "
            "Repeat until images --status reports done. The app records image progress from these steps, so leave image records out of your progress reports; images is a phase of its own. "
            "If images --status reports that DazedTL can't read this engine's images, follow Len's image reference and report images in your progress records."
            if selected["options"]["include_images"]
            else ""
        )
        injection, qa = ("10", "11") if images else ("9", "10")
        handoff = f"""Translate this game and deliver a verified local patch using Len's maintained game-translation skills.

Game: {json.dumps(str(project.root), ensure_ascii=False)}
Skill: {json.dumps(setup["skill"], ensure_ascii=False)}
Setup instructions: {json.dumps(setup["setup"], ensure_ascii=False)}
Selected execution mode: {mode}
Image translation: {"included" if selected["options"]["include_images"] else "excluded; report remaining baked text separately"}
{investigation}

Work autonomously from start to finish. Ask the user only when the work cannot continue without them: approving API spending, a missing or failing API connection in an API mode, access that is denied, or a decision only the user can make that no source evidence settles. Never ask for routine confirmations, permission to continue, or checks you could make or record yourself. When a check needs something you cannot do, such as capturing the game window, use the mechanical alternative, record the remaining check as pending in status.md and continue. Finish all independent work before asking, and report only such a question as the progress blocker, with the exact answer you need as next_action.

The user's assistant plan pays for this session, so keep it economical. Read the skill and the detected engine's reference first; read each other reference when its phase begins, and only the sections the current step needs: project-lifecycle before backup and Git, glossary-and-prompts before guidance, text-fitting before injection, playtesting-and-release before the canary and QA, and version-updates only for an official game update. Prefer scripts and the helper over reading or pasting large files, and don't reread files already in context.

Work in the numbered order below. Send your first progress report, with preparation active, right after the first state read and before any other work; then report each phase when you enter it: preparation is steps 1-3 and the delivery canary, extraction is steps 4-5, translation is steps 6-8, {"images is step 9, " if images else ""}injection is step {injection}, qa is step {qa}'s checks, and patch is packaging. Mark a phase complete once its work is saved.

Retain engine-specific methodology and existing valid work. Use the shared glossary, game.md, quirks.md, custom skills, and registered reference games. Preserve uncertainty, speaker identities, scene boundaries, protected controls, and source-supported character voice.

This project uses the new DazedTL app as its state and execution owner. Keep the app open. Use this helper for project operations instead of the legacy Len CLI commands named in historical references:

{command} state
{command} --help

{git_note()}The helper connects to the running app over authenticated loopback HTTP (127.0.0.1). A coding assistant's network sandbox can block that connection even while DazedTL is open. If loopback access is restricted, use the assistant's normal permission/escalation flow for this helper before running state (in Codex, sandbox_permissions="require_escalated" when required). Reuse valid permission already granted. A failed sandboxed connection does not mean the app is closed: retry the read-only state command with permitted access before asking the user to reopen DazedTL. If permission is denied or unavailable, report that restriction as the blocker.

After a connection failure, inspect state and the relevant run before retrying any state-changing command; a lost response does not prove the action failed. Never blindly repeat a paid submission or project operation. The helper prints structured JSON; never copy API keys or the local connection token into game files, prompts, or arguments. If the app remains unreachable with permitted access, save local work and resume with the same prompt once the app is available. The app does not run the coding assistant itself.

1. Inspect saved state, artifacts, existing Git branches and runs. Identify the engine using identify --engine <name> --evidence <project-relative investigation report>. Reuse valid work. When resuming, check the game files against Git and any saved hashes before trusting earlier notes, since a crash can undo a finished step such as a canary restore; restore and recheck anything changed, and record only checks whose output you saw. Do not re-submit in-flight work or regenerate reviewed translations merely because a session resumed. If state includes a legacyRun, recover it with legacy --action resume/answer/export; inspect its frozen approval before authorizing any additional submission. Preserve and review its exported results before importing matching receipts into the new request store.
2. Before modifying runtime game files, run operation backup_source and wait for its saved job to complete. Use the app backup operations for all source/workspace checkpoints. They keep a deduplicated store in .dazedtl/backups/v2, exclude .dazedtl/backups from workspace snapshots, and reuse unchanged files and snapshots. Do not create additional full workspace copies, timestamped checkpoint directories or ZIPs inside .dazedtl. Keep existing older backups; never manually edit or prune the managed store. Investigate the engine and adapt Len's tools in .dazedtl/len-method/work. RPG Maker uses operation rpgmaker_prepare; Ace must first complete its reviewed decryption/conversion prerequisite. Honor the saved Forge choice. Other engines keep their native preparation and byte-preservation rules.
3. Prepare a complete runtime patch-file manifest and establish Git through operation git_setup, supplying the actual game version, manifest, and untranslated-source attestation after inspecting the game. Existing baselines and branches must be reused. Never place English on original. The helper retains a second prepared-source snapshot for source mappings. Do not invent a source release number; use initial-unversioned when no official label exists. Then prove the delivery path with the skill's canary before bulk translation: write a few visible strings through the real injection path, verify that they read back from the installed files and survive the engine's round trip, read the window title with a script where the engine allows, and restore the game byte for byte, checked against hashes saved before the canary. Looking at the running game is optional; if you cannot capture it, record the visual check as pending and continue.
4. Complete the shared setup investigation and independently audit the source inventory, including plugins/scripts, dynamic text, and images in scope. Keep glossary, context and voice guidance in their shared files; preserve user edits. Mark coverage provisional until the inventory is audited.
5. Save a version-2 source-bound request plan using the format returned by plan-format. Classify every source ID in kinds as dialogue, narration, ui, or unknown when evidence cannot establish the text type. Supply a complete speakers map: use an evidenced name or null for unknown/inapplicable speakers; UI always has a null speaker. Never inherit the previous speaker or infer identity or gender from speech style. Unknown speakers are valid and do not block translation. Group coherent exchanges; include relevant Japanese from the same scene/event branch, scene/context notes and runtime substitution meanings, field instruction keys, and explicit engine-specific protected tokens/layout bounds. Resolve subjects and addressees separately from the speaker; preserve voice supported by the Japanese without inventing an identity. Add qa_notes keyed by source ID only for concrete uncertainty that could change meaning, gender, perspective or a plot fact. State the ambiguity and evidence to check; do not flag every unknown speaker or turn guesses into established facts. Declare immutable source exports as inputs, not a store whose translation fields change while you work. Tracked game-source files bind to original so ordinary English injection does not invalidate their source. Use compile --input <project-relative plan>. The helper supplies the same compiled context and validators in every mode. For API work, respect the configured request size and include source overlap when an exchange spans requests.
6. Assistant only: read request --run <id> --index <n>, translate with your own session using every context field, perform the source-checked dialogue pass, and save a JSON receipt with request_sha256 and translations. Use accept --run <id> --batch <id> --input <project-relative receipt>. DazedTL makes no translation API calls in this mode. Follow the user's delegation instructions.
7. Live API or API Batch: if no API connection is saved, finish all independent work first, then ask the user to add one in DazedTL's Settings. Inspect the exact compiled request and quote. Obtain any missing spending authorization in this same conversation, then use start --run <id> --approve <quote token>. This submits only the frozen reviewed request set. When you ask, tell the user they can also approve with the button on DazedTL's Progress tab, which starts the run itself; inspect the run before starting it. DazedTL runs the job; while it works, continue independent work such as images and fitting or injection tools. To wait, use run --run <id> --wait <minutes>, which returns when the run finishes or changes state, with a command timeout longer than the wait, instead of polling repeatedly. Resume saved jobs with start --run <id>. If the connection cannot run Batch, or a Batch run fails, prepare a Live quote for the remaining work and ask for its approval; never replace Batch with Live silently. Reconcile uncertain submissions before any retry; use attach-batch only with the matching provider job ID. Prepare a new remaining-work quote for failed requests. Do not ask the user to return to the app or copy another prompt at routine phase boundaries.
8. Save translation records and report progress after each saved milestone, before waits, and at least every ten minutes. Use progress --input <project-relative report> for the maintained Len progress format. Routine progress reporting is lightweight; use operation backup_workspace or checkpoint for meaningful recovery milestones. Keep detailed evidence in status.md. Translation counts, source-checked review, images, injection, runtime QA and packaging are separate. Inspect each request's qa_notes and check flagged lines against surrounding source, relevant script branches or the installed scene. Preserve intentional ambiguity in the translation; retain any unresolved blocker in status.md. Review accepted requests with review only after actually checking them and their flagged ambiguities against the source; fingerprints are evidence, not counters to fabricate. For a correction, include the current result_sha256 as replaces_sha256 in the receipt and use accept again. It archives the previous result and invalidates affected review/QA; ordinary retries cannot overwrite accepted translations.{images}
{injection}. Fit using the actual engine/renderer. For MV/MZ, stage translated JSON and use operation write_rpgmaker with matching source, translated and output paths (or a registered backup_id). This preserves _original and refuses unsafe structural remapping. After an official source update, use rebase_rpgmaker with the current expected_original_commit when old metadata needs rebasing; it requires source bytes matching that exact original-branch file. Ordinary corrections keep their existing Japanese. Other engines retain native source/injection sidecars and use their own verified reconstruction tools. Record unresolved or excluded content explicitly.
{qa}. Inject and verify the actual installed game. Use operation checkpoint with the complete runtime manifest to align original/main and create a local checkpoint plus a deduplicated workspace snapshot. Packaging reuses that snapshot when its contents are unchanged. Complete targeted structural, source/live and runtime QA; unavailable checks remain pending. Use operation package for a local Git patch after QA is complete. Public publishing, uploads, remotes and pushes remain separate requests.

For official updates, use stage_update with the new official folder/version to preserve it and create a working copy. It applies shared preparation to MV/MZ; complete the relevant skill's decryption, conversion or other prerequisites for other engines in the returned copy. Preview that prepared original with version_preview, inspect its saved result, then version_apply with that preview_id. Preserve conflict recovery and continue/abort through the helper. Use version_handoff after a completed update. Recompile only changed/new work with current source mappings; positional offsets alone are not stable across releases.

Use backups to list restore points, including older profile backups. operation restore_backup accepts backup_id and an absolute destination for a new folder outside the game; it verifies all restored bytes and never overwrites an existing folder.

Finish the local delivery. Stop early only for a question from the list above, recorded as the blocker with the exact next action; continue automatically across every routine phase.

Additional project instructions:
{instructions}
"""
        write_bytes(
            handoff_path := project_path(
                project.root, WORK + "/handoff.md", exists=False
            ),
            handoff.encode("utf-8"),
        )
        return {"handoff": handoff, "path": str(handoff_path)}

    def job_views(self, jobs, mode):
        """Saved runs as pages show them; an estimate waiting for approval
        notes when the settings it priced have changed since."""
        current = None
        views = []
        for job in jobs:
            view = self.jobs.store.view(job)
            frozen = job.get("configuration_sha256")
            if (
                frozen
                and view["status"] == "ready"
                and view["quote"]
                and not view["approved"]
            ):
                if current is None:
                    # Cached prices only, so a snapshot never waits on a
                    # pricing lookup; approval itself checks fully.
                    try:
                        current = digest(
                            self.api_configuration(mode, cached_only=True)[0]
                        )
                    except ValueError:
                        current = ""
                view["settings_changed"] = bool(current) and current != frozen
            views.append(view)
        return views

    def stored_original(self, root):
        """The original backup a game folder already holds, for a project
        without one; kept until the store's snapshots change."""
        try:
            signature = (backups.store_path(root) / "snapshots").stat().st_mtime_ns
        except OSError, ValueError:
            return None
        saved = self.originals.get(str(root))
        if not saved or saved[0] != signature:
            saved = (signature, backups.original(root))
            self.originals[str(root)] = saved
        return saved[1]

    def backups(self, project_id):
        _record, project = self.project(project_id)
        return backups.catalog(project.root, self.workspace / "backups" / project_id)

    def compile(self, project_id, input_path):
        self.idle(project_id)
        self.clean_drafts(project_id)
        legacy = self.legacy_record(project_id)
        if (
            legacy
            and legacy["mode"] not in {"estimate", "offline"}
            and legacy["status"] != "complete"
        ):
            raise ValueError(
                "Resume and reconcile the saved phased run before creating a new request corpus. Its paid work and outputs were retained."
            )
        _record, project = self.project(project_id)
        selected = project.read()["options"]
        require_baseline(
            self.engine, project.root, selected, lifecycle(self.workspace, project_id)
        )
        raw_path = project.artifact(input_path)
        raw = plan_input(read_json(raw_path))
        cfg, batch_provider = self.api_configuration(selected["mode"])
        if cfg["mode"] != "agent" and not raw["complete"]:
            raise ValueError(
                "API cost review requires the complete independently audited request corpus."
            )
        if cfg["entries_per_request"] and any(
            len(batch["sources"]) > cfg["entries_per_request"]
            for batch in raw["batches"]
        ):
            raise ValueError(
                "A batch exceeds the configured entries per request. Split at a coherent boundary with source context, or adjust the model setting."
            )
        inputs = list(
            dict.fromkeys(
                [input_path, *raw["inputs"], *self.guidance_inputs(project.root)]
            )
        )
        for path in inputs:
            project_path(project.root, path, exists=False)
        bindings = self.engine.source_bindings(project.root, raw["inputs"])
        before = evidence(
            project.root, [path for path in inputs if path not in bindings]
        )
        requests, compiler = compile_requests(
            self.engine, project.root, selected, raw, cfg["language"]
        )
        verify_evidence(project.root, before)
        self.engine.verify_bindings(project.root, bindings)
        self.jobs.store.overlapping(
            project_id, {row["fingerprint"] for row in requests}
        )
        limits = None
        if cfg["mode"] != "agent":
            if cfg["mode"] == "batch" and not batch_provider:
                raise ValueError(
                    "This route does not support Batch execution. Choose a supported connection or explicitly select Live."
                )
            limits = self.engine.batch_limits(cfg) if batch_provider else None
            for request in requests:
                request["params"] = self.engine.payload(request, cfg)
                if limits and len(limits) > 2 and limits[2]:
                    request["input_tokens"] = self.engine.input_tokens(
                        request["params"]
                    )
        results = Results(project.root)
        pending = [row for row in requests if not results.get(row)]
        estimate = (
            quote(pending, cfg, self.engine.token_count)
            if cfg["mode"] != "agent"
            else None
        )
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(project.root),
            "options": selected,
            "scope_sha256": scope(selected),
            "configuration": cfg,
            "requests": requests,
            "complete": raw["complete"],
            "evidence": before,
            "original_bindings": bindings,
            "compiler": compiler,
            "input_path": input_path,
            "batch_limits": limits,
        }
        job = self.jobs.store.create(project_id, plan, estimate)
        self.refresh_progress(project_id, plan)
        return self.jobs.store.view(job)

    def api_configuration(self, mode, *, cached_only=False):
        """The settings a run compiled now would freeze, with the Batch route
        that sets its price factor."""
        cfg = configuration(self.settings, mode, cached_only=cached_only)
        batch_provider = None
        if cfg["mode"] != "agent":
            batch_provider = self.engine.batch_supported(cfg)
            cfg["rates"]["batch_factor"] = (
                0.5 if batch_provider and batch_provider != "openrouter" else None
            )
        return cfg, batch_provider

    def guidance_inputs(self, source):
        root = Path(source)
        result = []
        for relative in (
            ".dazedtl/glossary.txt",
            ".dazedtl/reference-games.json",
            ".dazedtl/skills/game.md",
            ".dazedtl/skills/quirks.md",
        ):
            path = project_path(root, relative, exists=False)
            if path.is_file():
                result.append(relative)
        folder = root / ".dazedtl/skills"
        if folder.is_dir():
            result.extend(
                path.relative_to(root).as_posix()
                for path in folder.glob("*.md")
                if path.relative_to(root).as_posix() not in result
            )
        return result

    def validate_current(self, project_id, plan):
        _record, project = self.project(project_id)
        if (
            str(project.root) != plan["source"]
            or scope(project.read()["options"]) != plan["scope_sha256"]
        ):
            raise ValueError(
                "The project scope changed. Compile and review a new plan."
            )
        verify_evidence(project.root, plan["evidence"])
        self.engine.verify_bindings(project.root, plan["original_bindings"])
        require_baseline(
            self.engine,
            project.root,
            plan["options"],
            lifecycle(self.workspace, project_id),
        )
        verify_compilation(self.engine, plan)

    def run(self, project_id, run_id):
        self.jobs.reconcile()
        job = self.jobs.store.record(run_id, project_id)
        return self.jobs.store.view(job)

    def request(self, project_id, run_id, index):
        _job, plan = self.jobs.store.load(run_id, project_id)
        if (
            plan["kind"] != "translation"
            or type(index) is not int
            or not 0 <= index < len(plan["requests"])
        ):
            raise ValueError("Choose a request in this run.")
        return {
            "run_id": run_id,
            "index": index,
            "total": len(plan["requests"]),
            "request": plan["requests"][index],
            "result": Results(plan["source"]).get(plan["requests"][index]),
        }

    def start(self, project_id, run_id, approval_token=""):
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Use the project operation controls for this job.")
        if not self.jobs.store.authorized(job):
            self.clean_drafts(project_id)
            if not approval_token or approval_token != job["approval_token"]:
                raise ValueError(
                    "Review and approve this exact quote before submitting."
                )
            # The quote priced the settings the run froze; approving it after
            # they change would approve a cost the user no longer sees.
            _record, project = self.project(project_id)
            current, _provider = self.api_configuration(
                project.read()["options"]["mode"]
            )
            if digest(current) != digest(plan["configuration"]):
                raise ValueError(
                    "API settings or the translation mode changed after this estimate. Compile and review a new plan."
                )
            self.validate_current(project_id, plan)
            self.jobs.store.authorize(job, in_app=not assistant_request.get())
        return self.jobs.start(run_id, project_id)

    def stop(self, project_id, run_id, cancel_provider=False):
        if type(cancel_provider) is not bool:
            raise ValueError(
                "Choose whether to pause locally or cancel the provider batch."
            )
        if cancel_provider:
            job, plan = self.jobs.store.load(run_id, project_id)
            if (
                plan["kind"] != "translation"
                or plan["configuration"]["mode"] != "batch"
            ):
                raise ValueError("Provider cancellation applies to Batch runs.")
            if plan["configuration"].get("provider") == "openrouter":
                raise ValueError(
                    "OpenRouter does not expose Batch cancellation. Pause locally to stop future submissions; submitted work continues at the provider."
                )
            if job["status"] == "complete":
                return self.jobs.store.view(job)
            write_json(
                self.jobs.store.folder(run_id) / "cancel.json", {"requested": True}
            )
            if self.jobs.store.authorized(job):
                return self.jobs.start(run_id, project_id)
            for row in job["states"].values():
                if row["state"] == "pending":
                    row.update(state="failed", message="Canceled before submission.")
            job.update(
                status="canceled",
                message="Canceled before submission; no requests were sent.",
            )
            self.jobs.store.save(job)
            return self.jobs.store.view(job)
        self.jobs.store.stop(run_id, project_id)
        return self.run(project_id, run_id)

    def accept(self, project_id, run_id, batch_id, input_path):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Result receipts belong to translation runs.")
        self.validate_current(project_id, plan)
        request = next((row for row in plan["requests"] if row["id"] == batch_id), None)
        if not request:
            raise ValueError("Unknown request ID.")
        if job["states"][batch_id]["state"] in {"sending", "queued", "uncertain"}:
            raise ValueError(
                "Reconcile in-flight work before importing a replacement result."
            )
        self.jobs.store.overlapping(
            project_id, {request["fingerprint"]}, exclude=run_id
        )
        receipt = read_json(project_path(plan["source"], input_path))
        if (
            not isinstance(receipt, dict)
            or receipt.get("request_sha256") != request["fingerprint"]
            or "translations" not in receipt
        ):
            raise ValueError(
                "The receipt must bind translations to this request_sha256."
            )
        results = Results(plan["source"])
        provenance = {
            "run_id": run_id,
            "mode": "agent"
            if plan["configuration"]["mode"] == "agent"
            else "reviewed_import",
        }
        if "replaces_sha256" in receipt:
            results.correct(
                request,
                receipt["translations"],
                receipt["replaces_sha256"],
                {**provenance, "correction": True},
            )
        else:
            results.accept(request, receipt["translations"], provenance)
        job["states"][batch_id] = {"state": "accepted", "message": ""}
        if all(row["state"] == "accepted" for row in job["states"].values()):
            job.update(
                status="complete",
                message="Translations saved. Injection and runtime QA remain separate.",
            )
        self.jobs.store.save(job)
        self.refresh_progress(project_id, plan)
        return self.jobs.store.view(job)

    def review(self, project_id, run_id, batch_id, request_sha256):
        self.idle(project_id)
        _job, plan = self.jobs.store.load(run_id, project_id)
        self.validate_current(project_id, plan)
        request = next(
            (
                row
                for row in plan["requests"]
                if row["id"] == batch_id and row["fingerprint"] == request_sha256
            ),
            None,
        )
        if not request:
            raise ValueError("Review must refer to the exact saved request.")
        results = Results(plan["source"])
        value = results.get(request)
        if not value:
            raise ValueError(
                "Save accepted translations before recording their source-checked review."
            )
        value["reviewed"] = {
            identity: digest(
                (
                    digest(source.encode("utf-8"))
                    + ":"
                    + digest(value["translations"][identity].encode("utf-8"))
                ).encode("ascii")
            )
            for identity, source in request["sources"].items()
        }
        write_json(project_path(plan["source"], results.relative(request)), value)
        self.refresh_progress(project_id, plan)
        return {"saved": True}

    def refresh_progress(self, project_id, plan):
        progress_report.refresh(self.workspace, project_id, self.engine, plan)

    def image_progress(self, project_id):
        """Saves the Image Manager's progress as the image records an
        Assistant-led report counts. None when the assistant keeps its own
        image records, as for an engine the Image Manager can't read."""
        _record, project = self.project(project_id)
        if not project.read()["options"]["include_images"] or not self.image_units:
            return None
        value = self.image_units(project_id)
        if value is None:
            return None
        write_json(project_path(project.root, IMAGE_UNITS, exists=False), value)
        return IMAGE_UNITS

    def sync_images(self, project_id):
        """Republishes the last report with the Image Manager's current counts."""
        images = self.image_progress(project_id)
        if not images:
            return
        _record, project = self.project(project_id)
        progress_report.update(
            self.workspace,
            project_id,
            self.engine,
            project.root,
            project.read()["options"],
            lambda report: report.update(images=images),
        )

    def progress(self, project_id, input_path):
        # An API run can wait hours at the provider while the assistant works
        # on and reports; only operations change the game under a report.
        self.idle(project_id, "operation")
        _record, project = self.project(project_id)
        report = read_json(project.artifact(input_path))
        images = self.image_progress(project_id)
        if images and isinstance(report, dict):
            report = {**report, "images": images}
        if (
            isinstance(report, dict)
            and report.get("phases", {}).get("qa") == "complete"
        ):
            state = lifecycle(self.workspace, project_id)
            manifest_path = state.get("runtime_manifest") or state.get(
                "checkpoint", {}
            ).get("manifest")
            if not manifest_path:
                raise ValueError(
                    "Register the reviewed runtime patch manifest before reporting completed QA."
                )
            manifest = read_json(project.artifact(manifest_path))
            proof = delivery.record(
                project.root, manifest_path, self.engine.runtime_paths(manifest)
            )
            report = {
                **report,
                "inputs": list(dict.fromkeys([*report.get("inputs", []), proof])),
            }
        return progress_report.publish(
            self.workspace,
            project_id,
            self.engine,
            project.root,
            project.read()["options"],
            report,
        )

    def operation(self, project_id, action, arguments):
        if action not in OPERATIONS:
            raise ValueError("Choose an operation exposed by the project helper.")
        return self._operation(project_id, action, arguments, OPERATIONS[action])

    def guided_operation(self, project_id, action, arguments):
        # Called only after the UI's one-use guided preview is consumed. This
        # entrypoint is deliberately absent from the RPC/helper method table.
        if action not in GUIDED_OPERATIONS:
            raise ValueError("Unknown guided review operation.")
        return self._operation(project_id, action, arguments, GUIDED_OPERATIONS[action])

    def start_over(self, project_id, keep_context):
        """Puts the game back to its original and sets the assistant's work
        aside, so the next starting prompt begins again."""
        record, _project = self.project(project_id)
        if record.get("method") != "len":
            raise ValueError("Start over is for Assistant-led projects.")
        if type(keep_context) is not bool:
            raise ValueError("Choose whether to keep the glossary and notes.")
        for job in self.jobs.store.list(project_id):
            if job["kind"] == "translation" and job["status"] in {
                "running",
                "waiting",
                "uncertain",
            }:
                raise ValueError(
                    "Pause this project's API run, or settle its uncertain "
                    "submission, before starting over."
                )
        return self._operation(
            project_id,
            "start_over",
            {"keep_context": keep_context},
            USER_OPERATIONS["start_over"],
        )

    def _operation(self, project_id, action, arguments, specification):
        self.idle(project_id)
        self.clean_drafts(project_id)
        if not isinstance(arguments, dict) or set(arguments) - specification[1]:
            raise ValueError("Unknown operation or operation fields.")
        required = {
            "use_source_backup": {"backup_id"},
            "restore_backup": {"backup_id", "destination"},
            "git_setup": {"version"},
            "write_rpgmaker": {"source", "translated", "output"},
            "rebase_rpgmaker": {
                "source",
                "translated",
                "output",
                "expected_original_commit",
            },
            "checkpoint": {"manifest"},
            "guided_review": {"manifest"},
            "stage_update": {"official", "version"},
            "version_preview": {"official", "version"},
            "version_apply": {"preview_id"},
            "discard_release": {"stage"},
            "release_patch": {"plan", "sha256"},
        }.get(action, set())
        if any(
            not isinstance(arguments.get(key), str) or not arguments[key].strip()
            for key in required
        ):
            raise ValueError(
                "Required operation arguments: " + ", ".join(sorted(required))
            )
        for key, value in arguments.items():
            if key in {"untranslated", "patch_overlay", "keep_context"}:
                if type(value) is not bool:
                    raise ValueError("Operation flags must be true or false.")
            elif not isinstance(value, str) or len(value) > 10000 or "\0" in value:
                raise ValueError("Operation paths and labels must be bounded text.")
        _record, project = self.project(project_id)
        selected = project.read()["options"]
        if action == "guided_package":
            from .operations import verify_guided_review

            verify_guided_review(
                project.root,
                lifecycle(self.workspace, project_id),
                self.workspace,
                self.engine,
            )
        if action == "version_apply":
            previous, preview = self.jobs.store.load(
                arguments.get("preview_id", ""), project_id
            )
            if (
                previous["status"] != "complete"
                or preview.get("action") != "version_preview"
            ):
                raise ValueError("Review a completed official-update preview first.")
            arguments = {**preview["arguments"], "preview": previous["result"]}
        if action == "package":
            self.sync_images(project_id)
            progress = self.engine.progress(project.root, selected, verify=True)
            if progress.get("warnings") or progress["phases"].get("qa") != "complete":
                raise ValueError(
                    "Complete and record current QA evidence before packaging the translation."
                )
            for metric in (
                ("text", "images") if selected["include_images"] else ("text",)
            ):
                counts = progress["metrics"][metric]
                if counts["total"] is None or counts["translated"] != counts["total"]:
                    raise ValueError(
                        "Finish the audited translation scope before packaging; unknown totals are not complete."
                    )
            delivery.verify(project.root, full=True)
        self.settings.prepare_engine()
        plan = {
            "version": 1,
            "kind": "operation",
            "source": str(project.root),
            "options": selected,
            "action": action,
            "arguments": arguments,
            "label": specification[0],
        }
        bound = []
        if action == "guided_review":
            manifest = read_json(project_path(project.root, arguments["manifest"]))
            bound.extend(
                [*self.engine.runtime_paths(manifest), *manifest.get("inputs", [])]
            )
        for key in ("manifest", "translated", "output", "source"):
            if arguments.get(key) and not (
                key == "source" and arguments.get("backup_id")
            ):
                path = project_path(
                    project.root, arguments[key], exists=key != "output"
                )
                if path.is_file():
                    bound.append(arguments[key])
        if bound:
            plan["evidence"] = evidence(project.root, list(dict.fromkeys(bound)))
        job = self.jobs.store.create(project_id, plan)
        return self.jobs.start(job["id"], project_id)

    def attach_batch(self, project_id, run_id, index, provider_job_id):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if (
            plan["kind"] != "translation"
            or plan["configuration"]["mode"] != "batch"
            or type(index) is not int
            or not 0 <= index < len(job["batches"])
        ):
            raise ValueError("Choose an uncertain Batch submission.")
        chunk = job["batches"][index]
        if (
            chunk["state"] not in {"submitting", "unmatched"}
            or not isinstance(provider_job_id, str)
            or not provider_job_id.strip()
            or len(provider_job_id) > 500
        ):
            raise ValueError(
                "Only an uncertain submission can be attached to its matching provider job."
            )
        if chunk["id"]:
            chunk.setdefault("previous_ids", []).append(chunk["id"])
        chunk.update(id=provider_job_id.strip(), state="submitted", attached=True)
        for item in chunk["items"]:
            job["states"][item["request"]] = {
                "state": "queued",
                "message": "Provider job attached; awaiting collection.",
            }
        job.update(
            status="stopped",
            message="Provider job attached. Resume to verify and collect its request IDs.",
        )
        self.jobs.store.save(job)
        return self.jobs.store.view(job)

    def resolve_uncertain(
        self, project_id, run_id, batch_id, request_sha256, retry_reviewed
    ):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if (
            plan["kind"] != "translation"
            or plan["configuration"]["mode"] != "live"
            or retry_reviewed is not True
        ):
            raise ValueError(
                "Explicitly review the uncertain Live request before preparing a new paid attempt."
            )
        request = next(
            (
                row
                for row in plan["requests"]
                if row["id"] == batch_id and row["fingerprint"] == request_sha256
            ),
            None,
        )
        if not request or job["states"][batch_id]["state"] != "uncertain":
            raise ValueError("Choose the exact unresolved Live request.")
        job["states"][batch_id] = {
            "state": "failed",
            "message": "Uncertain outcome reviewed. A new remaining-work quote is required before another attempt.",
        }
        job.update(
            status="failed",
            message="Outcome reviewed. Compile and approve a new quote for remaining work.",
        )
        self.jobs.store.save(job)
        return self.jobs.store.view(job)

    def identify(self, project_id, engine, evidence_file):
        self.idle(project_id)
        _record, project = self.project(project_id)
        if (
            not isinstance(engine, str)
            or not engine.strip()
            or len(engine) > 120
            or any(ord(char) < 32 for char in engine)
        ):
            raise ValueError(
                "Use a short engine name supported by the investigation evidence."
            )
        value = {
            "engine": engine.strip(),
            "evidence": evidence(project.root, [evidence_file]),
        }
        write_json(
            self.workspace / "translation/projects" / project_id / "engine.json", value
        )
        return {"saved": True}

    def legacy(self, project_id, action, token="", approved=False):
        if self.jobs.running(project_id) or not self.legacy_record(project_id):
            raise ValueError(
                "Choose an available saved phased run with no competing project operation."
            )
        handlers = getattr(self, "legacy_actions", {})
        if action not in handlers:
            raise ValueError(
                "Supported saved-run actions are resume, stop, answer, and export."
            )
        if action == "answer":
            return handlers[action](project_id, token, approved)
        return handlers[action](project_id)
