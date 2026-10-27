"""One project service shared by the Electron UI and the external agent helper."""

import json
import re
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from dazedtl.actions import history_label
from dazedtl.compatibility.estimate_prices import usage_cost
from dazedtl.freshness import Basis, compare
from dazedtl.languages import pair_note
from dazedtl.settings import language_pair
from dazedtl.settings.execution import (
    configuration,
    connection_summary,
    entries_per_request,
)
from dazedtl.settings.preferences import BATTLE_MESSAGE_USERS
from dazedtl.storage import write_bytes, write_json

from . import (
    backups,
    checkpoint_records,
    delivery,
    organize,
    originals,
    progress_report,
    repricing,
    run_compiler,
    skill_users,
    unit_results,
)
from .assistant_release import AssistantRelease, PackageRefusal
from .census import HELP_SEGMENT
from .compilation import verify_compilation
from .files import digest, evidence, project_path, read_json, verify_evidence
from .game_update import GameUpdate
from .helper_command import LOOPBACK_NOTE, helper_command, windows_note
from .jobs import Jobs, declined_message, now
from .operations import (
    census_stale,
    checkout_issue,
    lifecycle,
    require_baseline,
    runtime_manifest,
)
from .playtest import game_fixes
from .project import ADDED, WORK, ProjectWorkspace, options, scope
from .requests import LINE_KEYS, counted, price, repriceable, sent_text
from .results import Results, exported, left_lines, review_digest

# The lifecycle record's fields the renderer reads; a ZIP's file stamps stay
# in the backend, which compares them.
DELIVERY_FIELDS = ("path", "commit", "game_version", "updater_stamp", "files")


def lifecycle_view(state):
    value = {key: item for key, item in state.items() if key != "release"}
    if isinstance(state.get("delivery"), dict):
        value["delivery"] = {
            key: state["delivery"][key]
            for key in DELIVERY_FIELDS
            if key in state["delivery"]
        }
    return value


def priced_mode(finishes, run_mode, project_mode):
    """The mode whose current settings an estimate must still match: the
    project's, or its own for an estimate of declined lines, which an
    Assistant only project asks for in an API mode."""
    return run_mode if finishes else project_mode


def changed_since(current, frozen_sha256, frozen, *, reprice=True):
    """Whether the settings a run would freeze now differ from those it froze;
    ``current`` is None when they can't form a run. With ``reprice``, prices
    not looked up since DazedTL started read as unchanged while everything
    else matches, so a restart alone never outdates a quote; a run saved
    before its record kept its configuration can only be compared once they
    are known."""
    if current is None:
        return True
    # A run's settings are its whole basis; its requests are checked apart.
    return bool(
        compare(
            Basis(
                None,
                {},
                frozen_sha256,
                None if frozen is None else digest(repricing.unpriced(frozen)),
            ),
            Basis(None, {}, digest(current), digest(repricing.unpriced(current))),
            prices_unknown=reprice
            and frozen is not None
            and repricing.unknown_prices(frozen, current),
        )
    )


# Set while the project helper, run by the user's assistant, makes a request.
assistant_request = ContextVar("assistant_request", default=False)

OPERATIONS = {
    "record_original": ("Record the original game files", set()),
    "restore_backup": (
        "Restore backup into a new folder",
        {"backup_id", "destination"},
    ),
    "rpgmaker_prepare": ("Prepare RPG Maker files", {"data_path"}),
    "git_setup": (
        history_label("git_setup"),
        {"version", "original", "untranslated", "manifest"},
    ),
    "line_widths": ("Save the game's Line widths", {"widths"}),
    "write_rpgmaker": (
        "Write source-preserving game JSON",
        {"source", "translated", "output", "backup_id"},
    ),
    "rebase_rpgmaker": (
        "Rebase source metadata to the current original",
        {"source", "translated", "output", "backup_id", "expected_original_commit"},
    ),
    "census": ("Find the game's text to translate", {"decoded"}),
    "checkpoint": (history_label("checkpoint"), {"manifest", "message"}),
    "package": ("Package local translation patch", set()),
    "gameupdate": ("Install GameUpdate", set()),
    "stage_update": (
        "Copy the new release for comparison",
        {"official", "version", "patch"},
    ),
    "version_preview": (
        "Compare the new release with the game",
        {"official", "version", "baseline", "patch_overlay"},
    ),
    "version_apply": ("Apply the game update", {"preview_id"}),
    "version_continue": ("Finish the stopped game update", set()),
    "version_abort": ("Cancel the game update", set()),
    "version_handoff": ("Prepare the post-update task", set()),
    "discard_release": ("Discard the new release", {"stage"}),
}

GUIDED_OPERATIONS = {
    "release_patch": (history_label("release_patch"), {"plan", "sha256"}),
}

# The Image Manager's progress as Len image records, which the app writes.
IMAGE_UNITS = WORK + "/work/image-units.json"

# Started only from the app's own controls; the project helper cannot reach
# these, so an assistant can never start its own project over.
USER_OPERATIONS = {
    "start_over": ("Start over from the original game", {"keep_context"}),
    # The Checkpoints tab's; each goes back, undoes or copies through Git,
    # and History names the checkpoint instead.
    "checkpoint_back": ("Go back to a checkpoint", {"commit"}),
    "checkpoint_undo": ("Undo a checkpoint", {"commit"}),
    "checkpoint_copy": ("Save a copy of a checkpoint", {"commit", "destination"}),
    # Release's builds of the ZIP its review planned: a clean game ZIP, and
    # the assistant's patch saved where the user chose.
    "release": (history_label("release"), {"plan", "sha256"}),
    "package": (history_label("release_patch"), {"plan", "sha256"}),
}


def _commit_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise ValueError("Choose a checkpoint from the list.")
    return value


class Translation:
    def __init__(self, workspace, projects, settings, engine, *, jobs=None):
        self.workspace = Path(workspace)
        self.projects = projects
        self.settings = settings
        self.engine = engine
        self.jobs = jobs or Jobs(workspace, settings.adapter.allow_providers)
        self.contacts = {}
        self.contact_lock = threading.Lock()
        # The API server installs handlers for the retained legacy run actions.
        self.legacy_actions: dict[str, Callable[..., Any]] = {}
        # And the Image Manager's progress for Assistant-led image records.
        self.image_units: Callable[[str], dict | None] | None = None
        self.game_update = GameUpdate(self)
        self.releases = AssistantRelease(self)

    def project(self, identity):
        record = self.projects.get(identity)
        return record, ProjectWorkspace(record["source"])

    def contact_path(self, project_id):
        return self.workspace / "translation/projects" / project_id / "assistant.json"

    def contacted(self, project_id):
        """Note that the user's assistant reached this project through the
        helper, at most once a minute, so Progress shows its run started
        before the first report. Only an Assistant-led project counts it."""
        if not isinstance(project_id, str):
            return
        with self.contact_lock:
            last = self.contacts.get(project_id)
            if last is not None and time.monotonic() - last < 60:
                return
            try:
                # Guided tasks use the helper too; they are not the assistant.
                if self.projects.get(project_id).get("method") != "len":
                    return
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

    def writable(self, project_id):
        """Refuses a change to a game whose Git checkout cannot take one, as
        every write does: a file written during a game update's stopped
        merge leaves Versions unable to cancel the update."""
        _record, project = self.project(project_id)
        status = self.engine.git_status(project.root, project.read()["options"])
        if status.get("configured") and (issue := checkout_issue(status)):
            raise ValueError(issue)

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
        refused = checkout_issue(git) if git and git.get("configured") else ""
        if refused:
            warnings.append(refused)
        self.jobs.reconcile()
        saved_jobs = self.jobs.store.list(project_id)[:30]
        warnings.extend(self.jobs.store.warnings)
        status = project_path(project.root, WORK + "/status.md", exists=False)
        identification = (
            self.workspace / "translation/projects" / project_id / "engine.json"
        )
        engine = self.engine.detect(project.root)
        saved_lifecycle = lifecycle(self.workspace, project_id)
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
            "coverage": run_compiler.saved_coverage(
                self.workspace, project_id, project.root, saved_lifecycle
            ),
            "git": git,
            "gameUpdate": self.game_update.state(project_id),
            "lifecycle": lifecycle_view(saved_lifecycle),
            "release": self.releases.view(project_id, project.root, saved_lifecycle)
            if record.get("method") == "len"
            else None,
            "originalsRecorded": originals.available(
                self.workspace, project_id, project.root, saved_lifecycle
            ),
            "jobs": self.job_views(
                saved_jobs, selected["options"]["mode"], project.root
            ),
            "active": self.jobs.running(project_id),
            "warnings": warnings,
            "checkoutIssue": refused,
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
        return self.handoff(project_id)

    def update_task(self, project_id):
        """The starting prompt again for an applied official update, its
        steps from census on, prepared as copying the starting prompt is."""
        _record, project = self.project(project_id)
        version = self.engine.applied_update(project.root)
        return {
            "version": version,
            "prompt": self.handoff(project_id, version)["handoff"],
        }

    def handoff(self, project_id, update=None):
        """Prepares the game and saves its prompt; `update` is the version an
        applied official update brought, whose task it then is."""
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
        # Set up starts: the game keeps the language pair Settings name.
        language_pair.record(self.settings, project.root)
        languages = language_pair.pair(self.settings, project.root)
        mode = self.default_mode()
        selected = project.read(mode)
        if not selected["initialized"]:
            self.idle(project_id)
            selected = project.save(selected["revision"], selected["options"], mode)
        setup = self.engine.prepare(
            project.root,
            selected["options"],
            language=languages["target"],
            refresh=not frozen,
        )
        handoff = windows_note() + self.starting_prompt(
            project_id, project, selected["options"], setup, languages, update
        )
        write_bytes(
            handoff_path := project_path(
                project.root, WORK + "/handoff.md", exists=False
            ),
            handoff.encode("utf-8"),
        )
        return {"handoff": handoff, "path": str(handoff_path)}

    def starting_prompt(
        self, project_id, project, selected, setup, languages, update=None
    ):
        """Len's pipeline as numbered steps, which the starting prompt and
        the task after an official update share; `update` is the version that
        update applied."""
        source, target = languages["source"], languages["target"]
        command = helper_command(self.workspace, project_id)
        mode = {
            "agent": "Assistant only (you translate every line in this session; DazedTL makes no translation API calls)",
            "live": "Live API (DazedTL sends one request at a time through the user's API connection)",
            "batch": "API Batch (DazedTL submits provider Batch jobs through the user's API connection)",
        }[selected["mode"]]
        investigation = (
            "Investigation: done before this update. Add to the glossary and game.md only what the new text needs."
            if update is not None
            else "Investigation: thorough. Run setup.md's Three-pass discovery as written."
            if selected["thorough_investigation"]
            else "Investigation: standard. setup.md describes One-pass discovery; follow it, and don't run the three blind passes some skill references describe."
        )
        instructions = selected["instructions"].strip() or "(none)"
        images = (
            "\n9. Images: translate them through DazedTL's Images steps rather than Len's manual image pipeline; "
            "images --status says which step comes next, and the steps resume where they stopped. "
            "images --scan indexes the game's images, decrypting encrypted ones. "
            "When images --status finds no folder of loose images because the game keeps them in archives, decode those archives with Len's tools into a folder in the game, "
            "the folder census --decoded reads if you decoded the text there too, and run images --scan --root <folder>; the other steps then read and write that folder. "
            "images --investigate saves a task file and the report path it expects: follow the task to find the images with text players read, then save the report. "
            "Your recommendations become the list. images --translate makes editable copies of the listed images and saves the translation task, "
            "which carries the image skill and the local inpainting tools; follow it and save its report. "
            "Change only the text and the pixels it covers. Report an image you can't or won't edit as skipped, with the reason; it stays out of the patch. "
            "images --apply puts the translated, reviewed images into the game, encrypted as the game expects, and its checkpoint takes the files it changed into the patch. "
            "If they went into a decoded folder the game doesn't read loose, pack it into its archive again with Len's tools and add the archive to the runtime manifest. "
            "Repeat until images --status reports done. The app records image progress from these steps, so leave image records out of your progress reports; images is a phase of its own. "
            "Only if the game's images can't be decoded into PNG files, follow Len's image reference and report images in your progress records."
            if selected["include_images"]
            else ""
        )
        injection, qa = ("10", "11") if images else ("9", "10")
        from util.game_settings import ACE_WRAP_WIDTHS as stock

        ace_widths = (
            f"{stock['width']} characters, {stock['faceWidth']} beside a face and "
            f"{stock['messageRows']} rows, which DazedTL uses until you save widths"
        )
        fixes = game_fixes(
            "playtest",
            "DazedTL then saves the fixes in a checkpoint; every later checkpoint "
            "and the patch carry them.",
        )
        if update is None:
            opening = "Translate this game and deliver a verified local patch using Len's maintained game-translation skills."
            resume, first = "", "preparation"
        else:
            approval = (
                "Translate those yourself as step 6 says."
                if selected["mode"] == "agent"
                else "DazedTL prices those in the selected mode, and only the user approves the estimate, with the button on DazedTL's Progress tab, as step 7 says."
            )
            opening = f"Official update {json.dumps(update, ensure_ascii=False)} is applied to this game. Translate the text it added or changed and deliver a verified local patch again using Len's maintained game-translation skills."
            resume = f"""

Game update: preparation is done and the update keeps it, so after step 1's state read continue from step 4, without recording the original, setting up Git, running the canary or investigating again. Run census again, since the scope is now the new version's text. Reuse your extractor and injector in .dazedtl/len-method/work, adapting them to anything the update changed, extract the updated game's units with current source mappings and run organize --complete: requests whose lines and context are unchanged keep their translations, so only new and changed requests are left. {approval} Then {"translate its images as step 9 says, " if images else ""}inject, run QA and the playtest, and package the patch, as steps {injection} and {qa} say."""
            first = "extraction"
        return f"""{pair_note(source, target)}{opening}

Game: {json.dumps(str(project.root), ensure_ascii=False)}
Skill: {json.dumps(setup["skill"], ensure_ascii=False)}
Setup instructions: {json.dumps(setup["setup"], ensure_ascii=False)}
Selected execution mode: {mode}
Image translation: {"included" if selected["include_images"] else "excluded; report remaining baked text separately"}
{investigation}{resume}

Work autonomously from start to finish. Ask the user only when the work cannot continue without them: approving API spending, a missing or failing API connection in an API mode, access that is denied, or a decision only the user can make that no source evidence settles. Never ask for routine confirmations, permission to continue, or checks you could make or record yourself. When a check needs something you cannot do, such as capturing the game window, use the mechanical alternative, record the remaining check as pending in status.md and continue. Finish all independent work before asking, and report only such a question as the progress blocker, with the exact answer you need as next_action.

The user's assistant plan pays for this session, so keep it economical. Read the skill and the detected engine's reference first; read each other reference when its phase begins, and only the sections the current step needs: project-lifecycle before backup and Git, glossary-and-prompts before guidance, text-fitting before injection, playtesting-and-release before the canary and QA, and version-updates only for an official game update. Prefer scripts and the helper over reading or pasting large files, and don't reread files already in context.

Work in the numbered order below. Send your first progress report, with {first} active, right after the first state read and before any other work; then report each phase when you enter it: preparation is steps 1-3 and the delivery canary, extraction is steps 4-5, translation is steps 6-8, {"images is step 9, " if images else ""}injection is step {injection}, qa is step {qa}'s checks, and patch is packaging. Mark a phase complete once its work is saved.

Retain engine-specific methodology and existing valid work. Use the shared glossary, game.md, quirks.md, custom skills, and registered reference games. Preserve uncertainty, speaker identities, scene boundaries, protected controls, and source-supported character voice.

This project uses the new DazedTL app as its state and execution owner. Keep the app open. Use this helper for project operations instead of the legacy Len CLI commands named in historical references:

{command} state
{command} --help

{LOOPBACK_NOTE} If permission is denied or unavailable, report that restriction as the blocker.

After a connection failure, inspect state and the relevant run before retrying any state-changing command; a lost response does not prove the action failed. Never blindly repeat a paid submission or project operation. The helper prints structured JSON; never copy API keys or the local connection token into game files, prompts, or arguments. If the app remains unreachable with permitted access, save local work and resume with the same prompt once the app is available. The app does not run the coding assistant itself.

1. Inspect saved state, artifacts, existing Git branches and runs. Identify the engine using identify --engine <name> --evidence <project-relative investigation report>. Reuse valid work. When resuming, check the game files against Git and any saved hashes before trusting earlier notes, since a crash can undo a finished step such as a canary restore; restore and recheck anything changed, and record only checks whose output you saw. Do not re-submit in-flight work or regenerate reviewed translations merely because a session resumed. If state includes a legacyRun, recover it with legacy --action resume/export; only the user approves its submissions, in DazedTL. Preserve and review its exported results before importing matching receipts into the new request store.
2. Before modifying runtime game files yourself, run operation record_original and wait for its saved job to complete. DazedTL keeps the original game's files in the game's own Git repository, under refs/dazedtl/originals, and records them itself before its first write to the game. Do not create full workspace copies, timestamped checkpoint directories or ZIPs inside .dazedtl. Keep existing older backups in .dazedtl/backups; never manually edit or prune them. Investigate the engine and adapt Len's tools in .dazedtl/len-method/work. RPG Maker uses operation rpgmaker_prepare. For VX Ace it first converts Data into ace_json, the files you translate and write, and sets an archive beside Game.exe aside in .dazedtl/ace, since the game reads nothing else while it is there. Honor the saved Forge choice. For WOLF, Unity and TyranoScript, run operation gameupdate, which installs GameUpdate so players can update the patch; GameUpdate copies the patch over the game and takes out a WOLF game's Data.wolf, so ship WOLF data loose in Data, never a repacked Data.wolf. Other engines keep their native preparation and byte-preservation rules.
3. Prepare a complete runtime patch-file manifest and establish Git through operation git_setup, supplying the actual game version, manifest, and untranslated-source attestation after inspecting the game. Existing baselines and branches must be reused. Never place {target} on original. DazedTL records the prepared game's files in Git too, for source mappings. Do not invent a source release number; use initial-unversioned when no official label exists. Then prove the delivery path with the skill's canary before bulk translation: write a few visible strings through the real injection path, verify that they read back from the installed files and survive the engine's round trip, read the window title with a script where the engine allows, and restore the game byte for byte, checked against hashes saved before the canary. Looking at the running game is optional; if you cannot capture it, record the visual check as pending and continue.
4. Complete the shared setup investigation. Keep glossary, context and voice guidance in their shared files; preserve user edits. Record what runtime substitutions stand for, such as \\N[1] or \\V[3] or the engine's equivalents, in game.md, which every request carries. Then run census, which counts every piece of {source} text in the original game itself, and wait for its run. What it counts is the scope: every map, event, scene, database entry, script and plugin the game loads, including ones that look unused; it leaves out plugins the game's plugin list turns off or lists again. Never leave text out because of its content; scope is not yours to decide. If census lists archives it can't read, decode them with Len's tools into a folder in the game and run census --decoded <folder>.
5. Write Len's extractor for this engine as code and save everything in scope as source units in the format units-format prints: one unit per message the player reads at once, with lines the engine stores separately, such as RPG Maker's consecutive 401 commands, joined by newlines; IDs your injector maps back, scene and group keys in play order, each line's kind, the speaker the engine's own evidence names (nameplates, face or speaker codes) or null, and literal protected tokens and layout bounds. Never inherit the previous speaker or infer identity or gender from speech style; unknown speakers are valid. Apart from requests you translate or review yourself, move game text only with scripts: never paste, retype, summarize or quote {source} or translated game text in your replies or in files you write by hand. Run organize --input <project-relative units file>, adding --complete once the units cover the census, as API estimates require. It groups the lines into requests, compiles the run and replies with counts; when it names text that isn't extracted, fix the extractor and organize again, using the locations in census-uncovered.json. Text players never see, such as file names, internal names, comments, script code and another language's translation table, can be set aside only by rules in .dazedtl/len-method/work/scope-rules.json: version 1, rules of kind, field and reason (asset_name, identifier, comment, script_code, not_displayed or other_language), each optionally limited to files matching a path pattern (file) or to exact runs (values), such as a script format's {source} command words. Dialogue, choices and names in formats DazedTL reads itself can't be set aside, nor can comment lines a game's plugins show players, such as RPG Maker choice help (field {HELP_SEGMENT}): extract each comment's lines as one unit and leave the marker line above them as the game wrote it, since the plugin finds them by it. Keep the units file unchanged while its run is in use. The translating model reads the surrounding {source}, so scene and line notes are not needed.
6. Assistant only: read request --run <id> --index <n>, translate with your own session using every context field, perform the source-checked dialogue pass, and save a JSON receipt with request_sha256 and translations. Use accept --run <id> --batch <id> --input <project-relative receipt>. If you won't translate a request, run decline --run <id> --batch <id> --reason <one line without game text> instead of softening, shortening or leaving out lines, and go on with the next; declining is the only way not to translate something, and its lines stay in scope. When only declined requests remain, don't report them as a blocker: Progress shows them to the user, who has another model translate them. Report next_action as waiting for the declined lines, finish all independent work, then wait with run --run <id> --wait <minutes> until they are saved. DazedTL makes no translation API calls in this mode unless the user approves one for declined lines. Follow the user's delegation instructions.
7. Live API or API Batch: if no API connection is saved, finish all independent work first, then ask the user to add one in DazedTL's Settings. Inspect the run and its quote with run --run <id>; don't read requests merely to check them. Only the user approves spending, with the button on DazedTL's Progress tab, which starts the run; you can't start a run they haven't approved there. Tell them the estimate is ready there and report that as the progress blocker, finish all independent work, then wait with run --run <id> --wait <minutes> until it starts. Each new organize or compile replaces the estimate waiting for approval, so prepare one only when its inputs or the API settings changed. DazedTL runs the job; while it works, continue independent work such as images and fitting or injection tools. To wait, use run --run <id> --wait <minutes>, which returns when the run finishes or changes state, with a command timeout longer than the wait, instead of polling repeatedly. Resume saved jobs the user approved with start --run <id>. If the connection cannot run Batch, or a Batch run fails, prepare a Live quote for the remaining work and ask the user to approve it; never replace Batch with Live silently. Reconcile uncertain submissions before any retry; use attach-batch only with the matching provider job ID. Prepare a new remaining-work quote for failed requests. Do not ask the user to return to the app or copy another prompt at routine phase boundaries.
8. Save translation records and report progress after each saved milestone, before waits, and at least every ten minutes. Use progress --input <project-relative report> for the maintained Len progress format. Routine progress reporting is lightweight. DazedTL saves your changes to the game in its Git history itself, as checkpoints: each operation that writes the game, each progress report for the phase you were in and each run's end. Don't commit them yourself. Keep detailed evidence in status.md. Translation counts, source-checked review, images, injection, runtime QA and packaging are separate. Check every accepted line mechanically with scripts: IDs, protected tokens, layout bounds and untranslated text. Review accepted requests with review only after actually checking them, and any qa_notes they carry, against the {source}; review the ones you are willing to read, record the rest as not reviewed in status.md, and go on. Preserve intentional ambiguity in the translation; retain any unresolved blocker in status.md. Fingerprints are evidence, not counters to fabricate. For a correction, include the current result_sha256 as replaces_sha256 in the receipt and use accept again. It archives the previous result and invalidates affected review/QA; ordinary retries cannot overwrite accepted translations.{images}
{injection}. Get the translations with results --run <id>, which writes them by line ID to a file, and inject from that file with scripts. For RPG Maker, first measure the game's message and help windows as text-fitting describes and write the widths you find as JSON (width, faceWidth, listWidth, noteWidth, messageRows). Confirm them on screen: for MV/MZ with playtest --layout FILE --wait 10, and for VX Ace, which that check can't play, by running the game yourself, since its scripts often change the stock windows' {ace_widths}. Then save that file's project-relative path as widths with operation line_widths, which also fits text you wrote earlier to them, and put each message's lines in the commands that held its {source}, stage translated JSON and use operation write_rpgmaker with matching source, translated and output paths (or with backup_id, a commit of refs/dazedtl/originals or a backup from backups, naming the saved original the source path is read from). This preserves _original, refuses unsafe structural remapping and fits the text to the saved Line widths, laying each message out over its own commands, so don't wrap it yourself; shorten the text its result lists under misfits, which a window of fixed height cuts off, and write that file again. After an official source update, use rebase_rpgmaker with the current expected_original_commit when old metadata needs rebasing; it requires source bytes matching that exact original-branch file. Ordinary corrections keep their existing {source}. Other engines retain native source/injection sidecars, fit using the actual engine/renderer and use their own verified reconstruction tools. Record unresolved extraction explicitly.
{qa}. Inject and verify the actual installed game. Keep the runtime manifest complete: every file the patch changes or adds, which checkpoints take into the patch. Complete targeted structural, source/live and runtime QA; unavailable checks remain pending. For RPG Maker MV/MZ, the release playtest is DazedTL's too: after injection, run playtest --run --wait 20, which checks the game's files and plays it in a hidden window without writing to it, and read the report playtest --report names. Each problem names its fix: translate `plugin-files` and `translate` problems, {source} a plugin or the game's data still holds, through your extraction and injection steps; leave `text-qa` problems, its findings in translated text, to text QA, which reviews them; and a `game` problem is {fixes} Run it again with --stops FILE for places its report lists as not reached when you know the event or map that leads there. Report anything still out of reach as a coverage gap; never ask the user to play. For RPG Maker MV/MZ and VX Ace, text QA is DazedTL's own: after injection and any playtest, run qa --prepare and follow the README of the task it names until qa reports the task complete, shortening the plugin labels qa lists as squeezed on the game's screens as its next step says, then run qa --apply --wait 60, which applies the findings through DazedTL as their own checkpoint. The user answers QA's open questions in DazedTL while apply waits. For MV/MZ, run playtest --run --wait 20 again after QA's apply and fix what it finds the same way; text problems it counts as waiting go to QA's next round, which qa --prepare starts, so review and apply that round and play again, as playtest's next step says. DazedTL keeps the qa phase open until the playtest settles; then report its problems and coverage. DazedTL shows QA's stage and counts on Progress from its task, so report the qa phase without QA counts. Use operation package for a local Git patch after QA is complete; it needs organize --complete after the latest census, with every unit it accepted in your text export. Public publishing, uploads, remotes and pushes remain separate requests.

For official updates, use stage_update with the new official folder/version to record its files in the game's Git and create a working copy. A folder holding fewer than half of the game's files is staged as a patch, whose files are copied over the game while every file it leaves out stays; pass patch true or false to override that, and check the returned layout for the folder that lined up with the game. It applies shared preparation to MV/MZ; complete the relevant skill's decryption, conversion or other prerequisites for other engines in the returned copy. Preview that prepared original with version_preview, inspect its saved result, then version_apply with that preview_id. Preserve conflict recovery and continue/abort through the helper. After a completed update, version_handoff returns the task that finishes it. Extract the updated game's units with current source mappings and organize them again; requests whose lines and context are unchanged keep their translations, and positional offsets alone are not stable across releases.

Use backups to list backups saved before the original game's files were kept in Git, including older profile backups. operation restore_backup accepts backup_id and an absolute destination for a new folder outside the game; it verifies all restored bytes and never overwrites an existing folder.

Finish the local delivery. Stop early only for a question from the list above, recorded as the blocker with the exact next action; continue automatically across every routine phase.

Additional project instructions:
{instructions}
"""

    def job_views(self, jobs, mode, root):
        """Saved runs as pages show them. An estimate waiting for approval
        takes the current settings' prices when they change only its price
        (see repricing), with an approval token for that price; otherwise it
        notes that the settings it priced have changed. An estimate for
        declined requests keeps its own mode, whatever the project's. A
        run's recorded usage is priced at the rates it froze."""
        current = {}
        views = []
        newest = max(
            (
                job["created"]
                for job in jobs
                if job["kind"] == "translation" and job["quote"] is not None
            ),
            default="",
        )
        for job in jobs:
            view = self.jobs.store.view(job, newest)
            if job["usage"] and (job.get("configuration") or {}).get("model"):
                try:
                    provider = self.engine.batch_supported(job["configuration"])
                except KeyError, ValueError:
                    # A frozen OpenRouter policy this version refuses.
                    provider = None
                view["usage_cost"] = usage_cost(
                    job["usage"], job["configuration"], provider
                )
            frozen = job.get("configuration_sha256")
            if (
                frozen
                and view["status"] == "ready"
                and view["quote"]
                and not view["approved"]
            ):
                priced = priced_mode(job.get("finishes"), view["mode"], mode)
                if priced not in current:
                    # Cached prices only, so a snapshot never waits on a
                    # pricing lookup; approval itself checks fully. Settings
                    # that can't form a run at all leave nothing to approve.
                    try:
                        current[priced] = self.api_configuration(
                            priced, root, cached_only=True, unpriced=True
                        )
                    except ValueError:
                        current[priced] = None, None
                settings, provider = current[priced]
                view["settings_changed"] = changed_since(
                    settings, frozen, job.get("configuration")
                )
                if view["settings_changed"] and self.repriceable(
                    job.get("configuration"), settings, provider, job["quote"]
                ):
                    view.update(
                        mode=settings["mode"],
                        quote=price(counted(job["quote"]), settings, provider),
                        approval_token=repricing.approval_token(
                            job["approval_token"], settings
                        ),
                        settings_changed=False,
                    )
            views.append(view)
        return views

    @staticmethod
    def repriceable(before, after, provider, quote):
        """Whether a run frozen with ``before`` keeps its requests under
        ``after``, which then only prices its ``quote`` again; a Batch also
        needs a route that runs one."""
        return bool(
            before
            and after
            and repricing.priced(after)
            and (after["mode"] != "batch" or provider)
            and repricing.same_requests(before, after)
            and repriceable(quote, provider)
        )

    def reprice(self, job, plan, configuration, provider):
        """Freezes a waiting run again with settings that only price it
        differently: each request's parameters for them, carrying the same
        text, and its counts' quote at their rates."""
        requests = []
        for row in plan["requests"]:
            params = self.engine.payload(row, configuration)
            if sent_text(params) != sent_text(row["params"]):
                raise ValueError(
                    "Requests for the new settings differ from this estimate's. Estimate again."
                )
            # The Batch runner counts the new parameters' tokens itself.
            row = {key: item for key, item in row.items() if key != "input_tokens"}
            requests.append({**row, "params": params})
        limits = self.engine.batch_limits(configuration) if provider else None
        plan = {
            **plan,
            "configuration": configuration,
            "requests": requests,
            "batch_limits": limits,
        }
        quote = price(counted(job["quote"]), configuration, provider)
        return self.jobs.store.replan(job, plan, quote), plan

    def reestimate(self, project_id, run_id):
        """Estimates a run waiting for approval again with the current
        settings, without the assistant. Looking up their prices is all a
        switch that keeps its requests needs (see job_views); any other
        change repeats the preparation that made the run."""
        job, plan = self.jobs.store.load(run_id, project_id)
        if (
            plan["kind"] != "translation"
            or plan.get("finishes")
            or job["status"] != "ready"
            or job["quote"] is None
            or self.jobs.store.authorized(job)
            or job["created"] < self.jobs.store.newest_estimate(project_id)
        ):
            raise ValueError("Only an estimate waiting for approval can be redone.")
        _record, project = self.project(project_id)
        mode = project.read()["options"]["mode"]
        if mode == "agent":
            raise ValueError(
                "Choose API Batch or Live API in Options to estimate this run again."
            )
        current, provider = self.api_configuration(mode, project.root)
        if not changed_since(
            current, job["configuration_sha256"], plan["configuration"], reprice=False
        ) or self.repriceable(plan["configuration"], current, provider, job["quote"]):
            return self.jobs.store.view(job)
        preparation = next(
            (
                row
                for row in self.jobs.store.list(project_id)
                if row["kind"] == "operation"
                and (row.get("result") or {}).get("run") == run_id
            ),
            None,
        )
        if preparation is None:
            raise ValueError(
                "DazedTL has no record of how this estimate was prepared. Ask your assistant for a new one."
            )
        _job, steps = self.jobs.store.load(preparation["id"], project_id)
        return self._prepare(project_id, steps["action"], steps["arguments"])

    def backups(self, project_id):
        _record, project = self.project(project_id)
        return backups.catalog(project.root, self.workspace / "backups" / project_id)

    def checkpoints(self, project_id):
        """The Checkpoints tab's timeline; read when the tab opens and after
        each write, never by a poll."""
        from dazedtl.compatibility.checkpoint_history import timeline

        _record, project = self.project(project_id)
        options = project.read()["options"]
        if not self.engine.git_status(project.root, options).get("configured"):
            return {"version": "", "outside": [], "versions": [], "backups": None}
        return timeline(project.root)

    def checkpoint_changes(self, project_id, commit):
        """What one checkpoint changed, file by file and line by line."""
        from dazedtl.compatibility.checkpoint_history import changes

        _record, project = self.project(project_id)
        return changes(project.root, _commit_id(commit))

    def checkpoint(self, project_id, action, commit, destination=None):
        """Goes back to, undoes or saves a copy of one checkpoint, as an
        operation only the user starts."""
        if action not in {"checkpoint_back", "checkpoint_undo", "checkpoint_copy"}:
            raise ValueError("Choose go back, undo or save a copy.")
        arguments = {"commit": _commit_id(commit)}
        extra = {}
        if action == "checkpoint_copy":
            arguments["destination"] = (
                destination if isinstance(destination, str) else ""
            )
        else:
            # The text batches whose records follow an undo or a go back.
            folder = checkpoint_records.publications(
                self.settings.adapter, self.projects.get(project_id)
            )
            if folder is not None:
                extra["publications"] = str(folder)
        from dazedtl.compatibility.checkpoint_history import named

        _record, project = self.project(project_id)
        label = named(project.root, action, arguments["commit"])
        fields = USER_OPERATIONS[action][1]
        return self._operation(project_id, action, arguments, (label, fields), extra)

    def release(self, project_id, folder):
        """How a new official release's folder lines up with the game, as a
        complete game and as a patch, before anything is copied."""
        _record, project = self.project(project_id)
        if not isinstance(folder, str) or not folder.strip() or "\0" in folder:
            raise ValueError("Choose the new release's folder.")
        release = Path(folder).expanduser()
        if not release.is_absolute():
            raise ValueError("Choose the new release's folder.")
        release = release.resolve()
        if not release.is_dir():
            raise ValueError("That folder doesn't exist.")
        if (
            release == project.root
            or release.is_relative_to(project.root)
            or project.root.is_relative_to(release)
        ):
            raise ValueError("Choose a separate new official game folder.")
        return self.engine.release_inspect(project.root, release)

    def compile(self, project_id, input_path):
        return self._prepare(project_id, "compile", {"input_path": input_path})

    def _prepare(self, project_id, action, arguments, *, mode=None, finishes=None):
        """Starts the operation that compiles a run. Only drafts, ownership
        and the settings the run freezes are read here: compiling, pricing and
        saving a big game's requests take a worker tens of seconds, which must
        not hold the dispatch the interface and the helper share. A run that
        finishes another run's declined requests uses the API mode given."""
        if self.jobs.running(project_id, "operation"):
            # An assistant whose command timed out may organize again.
            preparing = next(
                (
                    job
                    for job in self.jobs.store.list(project_id)
                    if job.get("action") in run_compiler.ACTIONS
                    and job["status"] in {"running", "waiting"}
                ),
                None,
            )
            if preparing:
                raise ValueError(
                    f"DazedTL is still preparing requests in run {preparing['id']}. Wait for that run to finish first."
                )
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
        if "input_path" in arguments:
            project.artifact(arguments["input_path"])
            if action == "compile" and organize.owns(arguments["input_path"]):
                # Its run would miss the lines organize kept from earlier
                # requests, as would an estimate repeating such a compile.
                raise ValueError(
                    "This plan is organize's own, without the lines it kept from earlier requests. Run organize --input with your units file again; it compiles the plan itself."
                )
        selected = project.read()["options"]
        cfg, batch_provider = self.api_configuration(
            mode or selected["mode"], project.root
        )
        if cfg["mode"] == "batch" and not batch_provider:
            raise ValueError(
                "This route does not support Batch execution. Choose a supported connection or explicitly select Live."
            )
        frozen = {"configuration": cfg, "batch": bool(batch_provider)}
        if action == "organize":
            from util.request_packing import SHARED_LINES

            frozen.update(
                lines=organize.AGENT_LINES
                if selected["mode"] == "agent"
                else entries_per_request(self.settings),
                characters=organize.AGENT_CHARACTERS
                if selected["mode"] == "agent"
                else organize.MAX_CHARACTERS,
                shared=None if selected["mode"] == "agent" else SHARED_LINES,
                # Lines with a current translation keep it; an organize
                # frozen without the policy packs every line.
                reuse=unit_results.POLICY,
            )
        job = self.jobs.store.create(
            project_id,
            {
                "version": 1,
                "kind": "operation",
                "source": str(project.root),
                "options": selected,
                "action": action,
                "arguments": arguments,
                "label": "Estimate declined lines"
                if finishes
                else "Prepare translation requests",
                "compile": frozen,
                "finishes": finishes,
            },
        )
        return self.jobs.start(job["id"], project_id)

    def api_configuration(self, mode, root, *, cached_only=False, unpriced=False):
        """The settings a run on the game at *root* compiled now would
        freeze, with the Batch route that sets its price factor."""
        cfg = configuration(
            self.settings,
            mode,
            cached_only=cached_only,
            unpriced=unpriced,
            pair=language_pair.pair(self.settings, root),
        )
        # A skill's battle messages name its users; earlier runs keep their
        # requests without (translation/skill_users).
        cfg[skill_users.BATTLE_USERS_KEY] = BATTLE_MESSAGE_USERS
        batch_provider = None
        if cfg["mode"] != "agent":
            # Earlier runs froze no policy and keep sending unit IDs.
            cfg["lineKeys"] = LINE_KEYS
            batch_provider = self.engine.batch_supported(cfg)
            cfg["rates"]["batch_factor"] = self.engine.batch_factor(batch_provider)
        return cfg, batch_provider

    def organize(self, project_id, input_path, complete=False):
        """Starts compiling a run from the lines Len's extractor saved, so the
        assistant never reads or rewrites the game's text to group it; the
        helper waits for the run."""
        if type(complete) is not bool:
            raise ValueError("Say whether the line inventory is complete.")
        _record, project = self.project(project_id)
        if project.read()["options"]["mode"] != "agent" and not complete:
            raise ValueError(
                "API estimates need every line extracted. Run census, cover it, then organize again with --complete."
            )
        return self._prepare(
            project_id, "organize", {"input_path": input_path, "complete": complete}
        )

    def require_inventory(self, project_id, translated):
        """A patch holds the whole census: it counted the game's current
        version, organize --complete accepted the units against it, and the
        text export counts them all."""
        _record, project = self.project(project_id)
        if census_stale(self.workspace, project_id, project.root):
            raise PackageRefusal(
                "The census no longer counts the game as it is: the game was updated, or this DazedTL counts more of its text. Run census again, then organize --complete with your units, before packaging.",
                "The game changed since your assistant counted its text; it counts it again first.",
            )
        try:
            inventory = read_json(
                run_compiler.inventory_path(self.workspace, project_id)
            )
        except ValueError, OSError:
            inventory = None
        if not inventory or inventory["census_sha256"] != run_compiler.census_sha256(
            self.workspace, project_id
        ):
            raise PackageRefusal(
                "Package needs the whole census extracted: run organize --complete with your units after the latest census.",
                "Your assistant finishes extracting the game's text first.",
            )
        if translated < inventory["units"]:
            raise PackageRefusal(
                f"The text export counts {translated:,} lines, fewer than the {inventory['units']:,} organize --complete accepted. Export every unit before packaging.",
                "Your assistant saves every translated line first.",
            )

    def package_ready(self, project_id):
        """Refuses a patch of a translation that isn't finished and checked:
        QA complete with current evidence, the audited scope translated and
        the whole census extracted. Each refusal also says why in the user's
        terms, which Release shows."""
        _record, project = self.project(project_id)
        selected = project.read()["options"]
        manifest = lifecycle(self.workspace, project_id).get("runtime_manifest")
        if not manifest:
            raise PackageRefusal(
                "Register the patch's runtime manifest with Git setup first.",
                "Your assistant sets up the game's version tracking first.",
            )
        self.sync_images(project_id)
        progress = self.engine.progress(project.root, selected, verify=True)
        if progress.get("warnings") or progress["phases"].get("qa") != "complete":
            raise PackageRefusal(
                "Complete and record current QA evidence before packaging the translation.",
                "The patch waits for your assistant's QA.",
            )
        images = selected["include_images"]
        for metric in ("text", "images") if images else ("text",):
            counts = progress["metrics"][metric]
            if counts["total"] is None or counts["translated"] != counts["total"]:
                raise PackageRefusal(
                    "Finish the audited translation scope before packaging; unknown totals are not complete.",
                    "Your assistant finishes translating the game's text and images first."
                    if images
                    else "Your assistant finishes translating the game first.",
                )
        self.require_inventory(project_id, progress["metrics"]["text"]["total"])
        try:
            delivery.require_patch(project.root, manifest)
        except ValueError as error:
            # Missing, older or stale QA evidence: QA is to record again.
            raise PackageRefusal(
                str(error), "The patch waits for your assistant's QA."
            ) from error

    def validate_current(self, project_id, plan, *, compiled=True, index=None):
        """Refuses a plan its project, sources or baseline no longer match.
        With compiled, it also compiles its requests again to compare them,
        which takes seconds on a big plan, or only the one at index."""
        _record, project = self.project(project_id)
        if scope(project.read()["options"]) != plan["scope_sha256"]:
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
        if compiled:
            verify_compilation(self.engine, self.workspace, project_id, plan, index)

    def run(self, project_id, run_id):
        self.jobs.reconcile()
        job = self.jobs.store.record(run_id, project_id)
        waiting = job["status"] == "ready" and job["quote"] is not None
        return self.jobs.store.view(
            job, self.jobs.store.newest_estimate(project_id) if waiting else ""
        )

    def request(self, project_id, run_id, index):
        _job, plan = self.jobs.store.load(run_id, project_id)
        if (
            plan["kind"] != "translation"
            or type(index) is not int
            or not 0 <= index < len(plan["requests"])
        ):
            raise ValueError("Choose a request in this run.")
        request = plan["requests"][index]
        result = Results(plan["source"]).get(request)
        return {
            "run_id": run_id,
            "index": index,
            "total": len(plan["requests"]),
            # An OpenAI Batch run also keeps each request's input tokens for
            # the provider's queue limit; a reader needs what was sent.
            "request": {
                key: request[key]
                for key in (
                    "id",
                    "sources",
                    "fingerprint",
                    "constraints",
                    "context",
                    "params",
                )
                if key in request
            },
            # The saved record also holds its hashes and provenance; a reader
            # needs the translations and the hash a correction replaces.
            "result": result
            and {
                key: result[key]
                for key in ("translations", "result_sha256", "reviewed")
                if key in result
            },
        }

    def requests(self, project_id, run_id):
        """Each request's ID and state in plan order, read from the run's
        record alone: a large run's plan takes far longer to read."""
        job = self.jobs.store.settled(self.jobs.store.record(run_id, project_id))
        if job["kind"] != "translation":
            raise ValueError("Choose a translation run.")
        return [
            {"id": identity, "state": row["state"]}
            for identity, row in job["states"].items()
        ]

    def results(self, project_id, run_id):
        """Writes the run's accepted translations by line ID for the engine's
        injector, and replies with counts only."""
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Results belong to translation runs.")
        reused = plan.get("reused") or {"units": {}}
        identities = [
            *(key for request in plan["requests"] for key in request["sources"]),
            *reused["units"],
        ]
        if len(set(identities)) != len(identities):
            raise ValueError(
                "Line IDs repeat across this run's requests. Read each request's result instead."
            )
        # Guidance may change after translating; the lines the IDs name may not.
        guidance = set(run_compiler.guidance_inputs(plan["source"]))
        sources = {
            path: value
            for path, value in plan["evidence"].items()
            if path not in guidance and path != plan["input_path"]
        }
        try:
            if sources:
                verify_evidence(plan["source"], sources)
            self.engine.verify_bindings(plan["source"], plan["original_bindings"])
        except ValueError:
            raise ValueError(
                "The extracted lines changed since this run was organized. Organize them again; unchanged requests keep their translations."
            ) from None
        saved = Results(plan["source"])
        translations, missing, reopened = {}, {}, False
        for request in plan["requests"]:
            value = saved.get(request)
            if value:
                # A line saved in its source text is no translation; the
                # next organize sends it again.
                left = left_lines(request, value)
                translations.update(
                    (identity, text)
                    for identity, text in exported(request, value).items()
                    if identity not in left
                )
                missing.update(dict.fromkeys(left, "untranslated"))
                continue
            row = job["states"][request["id"]]
            if row["state"] == "accepted":
                # Its saved result holds a refusal note (Results.get), so it
                # waits to be translated again.
                row = job["states"][request["id"]] = {"state": "pending", "message": ""}
                reopened = True
            missing.update(dict.fromkeys(request["sources"], row["state"]))
        # Lines an earlier request translated, which organize left out; one
        # whose translation is gone waits for the next organize.
        for row in saved.reused_units(reused, list(reused["units"]), saved.listing()):
            if "translation" in row:
                translations[row["source_id"]] = row["translation"]
            else:
                missing[row["source_id"]] = "pending"
        # An Assistant only run has no worker that owns its record; an API
        # run's next organize resends the request instead.
        if reopened and job["mode"] == "agent":
            if job["status"] == "complete":
                job.update(status="ready", message="Ready")
            self.jobs.store.save(job)
        relative = WORK + "/work/results/" + run_id + ".json"
        write_json(
            project_path(plan["source"], relative, exists=False),
            {"run_id": run_id, "translations": translations, "missing": missing},
        )
        counts = {}
        for state in missing.values():
            counts[state] = counts.get(state, 0) + 1
        return {"path": relative, "translated": len(translations), "missing": counts}

    def start(self, project_id, run_id, approval_token=""):
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Use the project operation controls for this job.")
        if not self.jobs.store.authorized(job):
            # Spending is the user's decision, made with the app's own button;
            # the helper only resumes runs the user approved there.
            if assistant_request.get():
                raise ValueError(
                    "Only the user approves API spending, with the button on DazedTL's Progress tab, which starts the run. Tell them the estimate is ready there, then wait with run --run "
                    + run_id
                    + " --wait <minutes>."
                )
            self.clean_drafts(project_id)
            if not approval_token:
                raise ValueError(
                    "Review and approve this exact quote before submitting."
                )
            if job["status"] != "ready" or job[
                "created"
            ] < self.jobs.store.newest_estimate(project_id):
                raise ValueError(
                    "This estimate was canceled or replaced by a newer one, so it can no longer be approved."
                )
            # The quote priced the settings the run froze; approving it after
            # they change would approve a cost the user no longer sees. A
            # quote priced again with the current settings (job_views) has
            # its own token, and its approval freezes the run with them.
            _record, project = self.project(project_id)
            current, provider = self.api_configuration(
                priced_mode(
                    plan.get("finishes"),
                    plan["configuration"]["mode"],
                    project.read()["options"]["mode"],
                ),
                project.root,
            )
            if approval_token == job["approval_token"]:
                if changed_since(
                    current,
                    digest(plan["configuration"]),
                    plan["configuration"],
                    reprice=False,
                ):
                    raise ValueError(
                        "API settings or the translation mode changed after this estimate. Compile and review a new plan."
                    )
            elif approval_token == repricing.approval_token(
                job["approval_token"], current
            ) and self.repriceable(
                plan["configuration"], current, provider, job["quote"]
            ):
                job, plan = self.reprice(job, plan, current, provider)
            else:
                raise ValueError(
                    "This estimate's price changed since it was shown. Review it again before approving."
                )
            # The run's worker compiles the requests again and compares them
            # before it sends anything. Doing it here as well held every other
            # request to the app for as long: 32 s on a user's big plan.
            self.validate_current(project_id, plan, compiled=False)
            self.jobs.store.authorize(job)
        return self.jobs.start(run_id, project_id)

    def stop(self, project_id, run_id, cancel_provider=False):
        if type(cancel_provider) is not bool:
            raise ValueError(
                "Choose whether to pause locally or cancel the provider batch."
            )
        if cancel_provider:
            job, plan = self.jobs.store.load(run_id, project_id)
            if plan["kind"] != "translation" or job["quote"] is None:
                raise ValueError("Provider cancellation applies to Batch runs.")
            if job["status"] == "complete":
                return self.jobs.store.view(job)
            # An estimate nobody approved sent nothing, whatever its mode.
            if not self.jobs.store.authorized(job):
                for row in job["states"].values():
                    if row["state"] == "pending":
                        row.update(
                            state="failed", message="Canceled before submission."
                        )
                job.update(
                    status="canceled",
                    message="Canceled before submission; no requests were sent.",
                )
                self.jobs.store.save(job)
                return self.jobs.store.view(job)
            if plan["configuration"]["mode"] != "batch":
                raise ValueError("Provider cancellation applies to Batch runs.")
            if plan["configuration"].get("provider") == "openrouter":
                raise ValueError(
                    "OpenRouter does not expose Batch cancellation. Pause locally to stop future submissions; submitted work continues at the provider."
                )
            write_json(
                self.jobs.store.folder(run_id) / "cancel.json", {"requested": True}
            )
            return self.jobs.start(run_id, project_id)
        self.jobs.store.stop(run_id, project_id)
        return self.run(project_id, run_id)

    def accept(self, project_id, run_id, batch_id, input_path):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Result receipts belong to translation runs.")
        job = self.jobs.store.settled(job)
        index = next(
            (n for n, row in enumerate(plan["requests"]) if row["id"] == batch_id),
            None,
        )
        if index is None:
            raise ValueError("Unknown request ID.")
        # An assistant imports one receipt per request, so each checks only its own.
        self.validate_current(project_id, plan, index=index)
        request = plan["requests"][index]
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
        finished = all(row["state"] == "accepted" for row in job["states"].values())
        if finished:
            job.update(
                status="complete",
                message="Translations saved. Injection and runtime QA remain separate.",
            )
        self.jobs.store.save(job)
        self.refresh_progress(project_id, plan)
        if finished:
            progress_report.checkpoint(
                self.engine, self.workspace, project_id, plan["source"]
            )
        return self.jobs.store.view(job)

    def declined_record(self, project_id, run_id):
        """An Assistant only run's index, without reading its plan."""
        job = self.jobs.store.record(run_id, project_id)
        if job["kind"] != "translation" or job["mode"] != "agent":
            raise ValueError(
                "Only Assistant only runs have declined requests; API runs retry provider refusals themselves."
            )
        return self.jobs.store.settled(job)

    def declined_run(self, project_id, run_id):
        job = self.declined_record(project_id, run_id)
        return job, self.jobs.store.load(run_id, project_id)[1]

    def decline(self, project_id, run_id, batch_id, reason):
        """Sets aside a request the assistant won't translate, so it carries
        on and another model can finish it."""
        self.idle(project_id)
        job, plan = self.declined_run(project_id, run_id)
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 300
            or any(char in reason for char in "\r\n\0")
        ):
            raise ValueError(
                "Give a one-line reason of at most 300 characters, without game text."
            )
        request = next((row for row in plan["requests"] if row["id"] == batch_id), None)
        if not request:
            raise ValueError("Unknown request ID.")
        # A saved result that holds a refusal note is none (Results.get).
        if Results(plan["source"]).get(request):
            raise ValueError("This request already has a saved translation.")
        job["states"][batch_id] = {"state": "declined", "message": reason.strip()}
        job["message"] = declined_message(job)
        self.jobs.store.save(job)
        return self.jobs.store.view(job)

    def finish(self, project_id, run_id):
        """An API estimate for the requests the assistant declined. It
        compiles the same plan, so their translations land where the
        assistant's run reads them."""
        job = self.declined_record(project_id, run_id)
        states = {row["state"] for row in job["states"].values()}
        if "declined" not in states:
            raise ValueError("No declined requests remain in this run.")
        if "pending" in states:
            raise ValueError(
                "Your assistant is still translating this run. Estimate the declined requests once it has finished."
            )
        return self._prepare(
            project_id, "compile", {}, mode=self.default_mode(), finishes=run_id
        )

    def translator_prompt(self, project_id, run_id):
        """A prompt for another assistant that translates only the declined
        requests, through the same helper and receipts."""
        job, plan = self.declined_run(project_id, run_id)
        declined = [
            (index, row["id"])
            for index, row in enumerate(plan["requests"])
            if job["states"][row["id"]]["state"] == "declined"
        ]
        if not declined:
            raise ValueError("No declined requests remain in this run.")
        _record, project = self.project(project_id)
        command = helper_command(self.workspace, project_id)
        listing = "\n".join(f"- {index}: {identity}" for index, identity in declined)
        source = language_pair.run_source(plan["configuration"])
        target = plan["configuration"]["language"]
        handoff = f"""{pair_note(source, target)}Translate the requests listed below in a DazedTL translation run, then stop. Another assistant prepared this game and declined them; it carries on once their translations are saved.

Game: {json.dumps(str(project.root), ensure_ascii=False)}
Run: {run_id}

Requests (index: request ID):
{listing}

Read each request with:

{command} request --run {run_id} --index <index>

It holds the {source} lines by ID with their full context: instructions, glossary, speakers, line kinds, earlier lines and constraints. Translate every line into {target}, keeping each ID, protected token and layout bound. Use the speakers and earlier lines for voice and who is addressed. Translate faithfully; never soften, shorten or leave out a line. Save a JSON receipt under {WORK}/work/receipts/ with request_sha256 set to the request's fingerprint and translations mapping every ID to its translation, then accept it with:

{command} accept --run {run_id} --batch <request ID> --input <the receipt's path relative to the game>

If you won't translate a request, skip it and go on; it stays declined. Use the helper only to read requests and accept receipts, and change nothing else in the project. When you finish, report only how many requests you saved.

{LOOPBACK_NOTE}
"""
        handoff = windows_note() + handoff
        path = project_path(project.root, WORK + "/translator-handoff.md", exists=False)
        write_bytes(path, handoff.encode("utf-8"))
        return {"handoff": handoff, "path": str(path)}

    def review(self, project_id, run_id, batch_id, request_sha256):
        self.idle(project_id)
        _job, plan = self.jobs.store.load(run_id, project_id)
        index = next(
            (
                n
                for n, row in enumerate(plan["requests"])
                if row["id"] == batch_id and row["fingerprint"] == request_sha256
            ),
            None,
        )
        if index is None:
            raise ValueError("Review must refer to the exact saved request.")
        self.validate_current(project_id, plan, index=index)
        request = plan["requests"][index]
        results = Results(plan["source"])
        value = results.get(request)
        if not value:
            raise ValueError(
                "Save accepted translations before recording their source-checked review."
            )
        value["reviewed"] = {
            identity: review_digest(source, value["translations"][identity])
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
            manifest = runtime_manifest(project.root, manifest_path)
            proof = delivery.record(
                project.root, manifest_path, self.engine.runtime_paths(manifest)
            )
            report = {
                **report,
                "inputs": list(dict.fromkeys([*report.get("inputs", []), proof])),
            }
        # Each report ends a stretch of the assistant's work, saved as a
        # checkpoint of the phase it was in.
        progress_report.checkpoint(
            self.engine,
            self.workspace,
            project_id,
            project.root,
            report if isinstance(report, dict) else None,
        )
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
        if action == "version_handoff":
            # The task Checkpoints copies after an update, prepared as the
            # starting prompt is rather than as a saved job.
            if arguments != {}:
                raise ValueError("Unknown operation or operation fields.")
            return self.update_task(project_id)
        return self._operation(project_id, action, arguments, OPERATIONS[action])

    def user_operation(self, project_id, action, arguments):
        """An operation started from the app's own controls, which the
        project helper cannot reach, such as Release's builds."""
        return self._operation(project_id, action, arguments, USER_OPERATIONS[action])

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
        # The text batches whose records follow, as after an undo.
        folder = checkpoint_records.publications(
            self.settings.adapter, self.projects.get(project_id)
        )
        return self._operation(
            project_id,
            "start_over",
            {"keep_context": keep_context},
            USER_OPERATIONS["start_over"],
            {"publications": str(folder)} if folder is not None else None,
        )

    def _operation(self, project_id, action, arguments, specification, extra=None):
        self.idle(project_id)
        # Finishing or cancelling a stopped game update reads no guidance or
        # options, and drafts can't be saved until it is done.
        if action not in {"version_continue", "version_abort"}:
            self.clean_drafts(project_id)
        if not isinstance(arguments, dict) or set(arguments) - specification[1]:
            raise ValueError("Unknown operation or operation fields.")
        required = {
            "restore_backup": {"backup_id", "destination"},
            "git_setup": {"version"},
            "line_widths": {"widths"},
            "write_rpgmaker": {"source", "translated", "output"},
            "rebase_rpgmaker": {
                "source",
                "translated",
                "output",
                "expected_original_commit",
            },
            "stage_update": {"official", "version"},
            "version_preview": {"official", "version"},
            "version_apply": {"preview_id"},
            "discard_release": {"stage"},
            "release_patch": {"plan", "sha256"},
            "release": {"plan", "sha256"},
            "checkpoint_back": {"commit"},
            "checkpoint_undo": {"commit"},
            "checkpoint_copy": {"commit", "destination"},
        }.get(action, set())
        if any(
            not isinstance(arguments.get(key), str) or not arguments[key].strip()
            for key in required
        ):
            raise ValueError(
                "Required operation arguments: " + ", ".join(sorted(required))
            )
        for key, value in arguments.items():
            if key in {"untranslated", "patch", "patch_overlay", "keep_context"}:
                if type(value) is not bool:
                    raise ValueError("Operation flags must be true or false.")
            elif not isinstance(value, str) or len(value) > 10000 or "\0" in value:
                raise ValueError("Operation paths and labels must be bounded text.")
        _record, project = self.project(project_id)
        selected = project.read()["options"]
        if action == "version_preview":
            # A staged release compares as what it was staged as: a patch
            # compared as a complete game would remove every file it leaves out.
            official = Path(arguments["official"]).expanduser().resolve()
            stage = next(
                (
                    job["result"]
                    for job in self.jobs.store.list(project_id)
                    if job["action"] == "stage_update"
                    and job["status"] == "complete"
                    and isinstance(job.get("result"), dict)
                    and Path(job["result"]["official"]).resolve() == official
                ),
                None,
            )
            if stage is not None:
                patch = stage.get("patch", False)
                if arguments.get("patch_overlay", patch) != patch:
                    raise ValueError(
                        "This release was staged as a patch."
                        if patch
                        else "This release was staged as a complete game."
                    )
                arguments = {**arguments, "patch_overlay": patch}
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
        if action in {"version_apply", "version_continue"}:
            # A VX Ace game's data is packed once its update completes, which
            # saves the packing receipt there.
            folder = checkpoint_records.publications(
                self.settings.adapter, self.projects.get(project_id)
            )
            if folder is not None:
                extra = {**(extra or {}), "publications": str(folder)}
        if action == "package":
            self.package_ready(project_id)
            # The patch carries GameUpdate's current config.
            self.game_update.sync(project_id)
        self.settings.prepare_engine()
        plan = {
            "version": 1,
            "kind": "operation",
            "source": str(project.root),
            "options": selected,
            "action": action,
            "arguments": arguments,
            "label": specification[0],
            **(extra or {}),
        }
        bound = []
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
            if approved and assistant_request.get():
                raise ValueError(
                    "Only the user approves API spending, in DazedTL. Tell them the saved run waits for their approval there."
                )
            return handlers[action](project_id, token, approved)
        return handlers[action](project_id)
