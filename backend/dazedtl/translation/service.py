"""One project service shared by the Electron UI and the external agent helper."""

import json
import os
from pathlib import Path
import shlex
import sys

from dazedtl.storage import write_json, write_bytes
from dazedtl.settings.execution import configuration, connection_summary
from .files import digest, read_json, project_path, evidence, verify_evidence
from .project import ProjectWorkspace, WORK, options, scope
from .requests import plan_input, quote
from .compilation import compile_requests, verify_compilation
from .results import Results
from .operations import lifecycle, require_baseline
from .jobs import Jobs
from . import delivery, backups


OPERATIONS = {
    "backup_source": ("Preserve source game", set()),
    "backup_workspace": ("Back up translation workspace", set()),
    "restore_backup": ("Restore backup into a new folder", {"backup_id", "destination"}),
    "rpgmaker_prepare": ("Prepare RPG Maker files", {"data_path"}),
    "git_setup": ("Establish version baselines", {"version", "original", "untranslated", "manifest"}),
    "write_rpgmaker": ("Write source-preserving game JSON", {"source", "translated", "output", "backup_id"}),
    "rebase_rpgmaker": ("Rebase source metadata to the current original", {"source", "translated", "output", "backup_id", "expected_original_commit"}),
    "checkpoint": ("Checkpoint reviewed runtime patch", {"manifest", "message"}),
    "package": ("Package local translation patch", set()),
    "stage_update": ("Stage a new original for engine preparation", {"official", "version"}),
    "version_preview": ("Preview official game update", {"official", "version", "baseline", "patch_overlay"}),
    "version_apply": ("Apply reviewed official update", {"preview_id"}),
    "version_continue": ("Continue resolved official update", set()),
    "version_abort": ("Abort official update", set()),
    "version_handoff": ("Prepare post-update translation prompt", set()),
}


class Translation:
    def __init__(self, workspace, projects, settings, engine, *, jobs=None):
        self.workspace = Path(workspace)
        self.projects = projects
        self.settings = settings
        self.engine = engine
        self.jobs = jobs or Jobs(workspace, engine.source, settings.adapter.allow_providers)

    def project(self, identity):
        record = self.projects.get(identity)
        return record, ProjectWorkspace(record["source"])

    def idle(self, identity):
        if self.jobs.running(identity):
            raise ValueError("Pause this project's active operation before changing its inputs.")
        if self.settings.adapter.running():
            raise ValueError("Finish or pause the existing phased run before changing project inputs.")

    def draft_path(self, identity):
        self.projects.get(identity)
        return self.workspace / "translation/projects" / identity / "draft.json"

    def drafts(self, identity):
        path = self.draft_path(identity)
        value = read_json(path, limit=4_000_000) if path.exists() else {"options": None, "documents": {}}
        record = self.projects.get(identity)
        legacy = record.get("backend_id")
        if legacy and legacy in self.settings.adapter.workflows.projects:
            value["documents"] = self.settings.adapter.workflows.state(legacy).get("draft", {}).get("documents", {})
        return value

    def draft(self, project_id, section, value):
        if section not in {"options", "documents"}:
            raise ValueError("Unknown project draft.")
        if section == "options" and value is not None:
            if not isinstance(value, dict) or set(value) != {"revision", "options"} or not isinstance(value["revision"], str):
                raise ValueError("Invalid options draft.")
            options(value["options"])
        if section == "documents":
            if not isinstance(value, dict) or len(json.dumps(value).encode("utf-8")) > 3_500_000:
                raise ValueError("Invalid guidance draft.")
            for name, document in value.items():
                if not self.engine.valid_document(name) or not isinstance(document, dict) or set(document) != {"text", "revision"} or not all(isinstance(item, str) for item in document.values()):
                    raise ValueError("Invalid guidance draft.")
        current = self.drafts(project_id)
        legacy = self.projects.get(project_id).get("backend_id")
        if section == "documents" and legacy and legacy in self.settings.adapter.workflows.projects:
            before = self.settings.adapter.workflows.state(legacy).get("draft", {})
            return self.settings.adapter.workflows.draft(legacy, {**before, "documents": value})
        current[section] = value
        if legacy:
            current["documents"] = {}
        write_json(self.draft_path(project_id), current)
        return {"saved": True}

    def save(self, project_id, revision, values):
        self.idle(project_id)
        _record, project = self.project(project_id)
        saved = project.save(revision, values)
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
            raise ValueError("Save or discard project drafts before preparing or running work.")

    def legacy_record(self, project_id):
        record = self.projects.get(project_id)
        backend_id = record.get("backend_id")
        native = self.settings.adapter.workflows.projects.get(backend_id)
        return self.settings.adapter.manual.jobs.get(native.get("manual_job")) if native else None

    def ready(self, project_id):
        _record, project = self.project(project_id)
        return require_baseline(self.engine, project.root, project.read()["options"], lifecycle(self.workspace, project_id))

    def state(self, project_id):
        record, project = self.project(project_id)
        selected = project.read()
        warnings = []
        try:
            progress = self.engine.progress(project.root, selected["options"])
        except (ValueError, OSError, TypeError, KeyError):
            progress = None
            warnings.append("Saved progress could not be read. Inspect the workspace before continuing.")
        if progress and progress["phases"].get("qa") == "complete":
            try:
                delivery.verify(project.root)
            except (ValueError, OSError, KeyError, TypeError):
                warnings.append("Runtime QA evidence is missing or stale. Review affected outputs before packaging.")
        try:
            git = self.engine.git_status(project.root, selected["options"])
        except Exception:
            git = None
            warnings.append("Git status is unavailable. Git must be installed and this game's baselines verified before translation.")
        self.jobs.reconcile()
        saved_jobs = self.jobs.store.list(project_id)[:30]
        warnings.extend(self.jobs.store.warnings)
        handoff = project_path(project.root, WORK + "/handoff.md", exists=False)
        status = project_path(project.root, WORK + "/status.md", exists=False)
        identification = self.workspace / "translation/projects" / project_id / "engine.json"
        engine = self.engine.detect(project.root)
        if identification.is_file():
            identified = read_json(identification)
            try:
                verify_evidence(project.root, identified["evidence"])
                engine = identified["engine"]
            except (ValueError, OSError):
                warnings.append("The reported engine evidence changed. Recheck the engine before adapting its tools.")
        return {"projectId": project_id, **selected, "drafts": self.drafts(project_id),
                "engine": engine,
                "documents": self.documents(project_id), "progress": progress, "git": git,
                "lifecycle": lifecycle(self.workspace, project_id), "jobs": [self.jobs.store.view(job) for job in saved_jobs],
                "active": self.jobs.running(project_id), "warnings": warnings,
                "statusText": status.read_text(encoding="utf-8")[:250_000] if status.is_file() and status.stat().st_size <= 5_000_000 else "",
                "handoff": handoff.read_text(encoding="utf-8") if handoff.is_file() and handoff.stat().st_size < 250_000 else "",
                "providerEnabled": self.settings.adapter.allow_providers,
                "connection": connection_summary(self.settings),
                "legacyRun": ({key: value for key, value in self.legacy_record(project_id).items()
                               if key in {"id", "mode", "status", "phase", "message", "approval", "outputs"}}
                              if self.legacy_record(project_id) else None),
                "legacyAvailable": bool(record.get("backend_id") in self.settings.adapter.workflows.projects)}

    def prepare(self, project_id):
        self.idle(project_id)
        self.clean_drafts(project_id)
        record, project = self.project(project_id)
        selected = project.read()
        if not selected["initialized"]:
            selected = project.save(selected["revision"], selected["options"])
        setup = self.engine.prepare(project.root, selected["options"])
        helper = Path(__file__).resolve().parents[3] / "scripts/project.py"
        arguments = [sys.executable, str(helper), "--workspace", str(self.workspace), "--project", project_id]
        command = ("& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
                   if os.name == "nt" else shlex.join(arguments))
        mode = {"agent": "Agent Translation", "live": "Live API Translation", "batch": "API Batch Translation"}[selected["options"]["mode"]]
        instructions = selected["options"]["instructions"].strip() or "(none)"
        handoff = f'''Translate this game and deliver a verified local patch using Len's maintained game-translation skills.

Game: {json.dumps(str(project.root), ensure_ascii=False)}
Skill: {json.dumps(setup['skill'], ensure_ascii=False)}
Setup instructions: {json.dumps(setup['setup'], ensure_ascii=False)}
Selected execution mode: {mode}
Image translation: {'included' if selected['options']['include_images'] else 'excluded; report remaining baked text separately'}

Read the skill and relevant engine, project-lifecycle, glossary, fitting, QA, and version-update references. Retain engine-specific methodology and existing valid work. Use the shared glossary, game.md, quirks.md, custom skills, and registered reference games. Preserve uncertainty, speaker identities, scene boundaries, protected controls, and source-supported character voice.

This project uses the new DazedTL app as its state and execution owner. Keep the app open. Use this helper for project operations instead of the legacy Len CLI commands named in historical references:

{command} state
{command} --help

The helper connects to the running app over authenticated loopback HTTP (127.0.0.1). A coding assistant's network sandbox can block that connection even while DazedTL is open. If loopback access is restricted, use the assistant's normal permission/escalation flow for this helper before running state (in Codex, sandbox_permissions="require_escalated" when required). Reuse valid permission already granted. A failed sandboxed connection does not mean the app is closed: retry the read-only state command with permitted access before asking the user to reopen DazedTL. If permission is denied or unavailable, report that restriction as the blocker.

After a connection failure, inspect state and the relevant run before retrying any state-changing command; a lost response does not prove the action failed. Never blindly repeat a paid submission or project operation. The helper prints structured JSON; never copy API keys or the local connection token into game files, prompts, or arguments. If the app remains unreachable with permitted access, save local work and resume with the same prompt once the app is available. The app does not run the coding assistant itself.

1. Inspect saved state, artifacts, existing Git branches and runs. Identify the engine using identify --engine <name> --evidence <project-relative investigation report>. Reuse valid work. Do not re-submit in-flight work or regenerate reviewed translations merely because a session resumed. If state includes a legacyRun, recover it with legacy --action resume/answer/export; inspect its frozen approval before authorizing any additional submission. Preserve and review its exported results before importing matching receipts into the new request store.
2. Before modifying runtime game files, run operation backup_source and wait for its saved job to complete. Use the app backup operations for all source/workspace checkpoints. They keep a deduplicated store in .dazedtl/backups/v2, exclude .dazedtl/backups from workspace snapshots, and reuse unchanged files and snapshots. Do not create additional full workspace copies, timestamped checkpoint directories or ZIPs inside .dazedtl. Keep existing older backups; never manually edit or prune the managed store. Investigate the engine and adapt Len's tools in .dazedtl/len-method/work. RPG Maker uses operation rpgmaker_prepare; Ace must first complete its reviewed decryption/conversion prerequisite. Honor the saved Forge choice. Other engines keep their native preparation and byte-preservation rules.
3. Prepare a complete runtime patch-file manifest and establish Git through operation git_setup, supplying the actual game version, manifest, and untranslated-source attestation after inspecting the game. Existing baselines and branches must be reused. Never place English on original. The helper retains a second prepared-source snapshot for source mappings. Do not invent a source release number; use initial-unversioned when no official label exists.
4. Complete the shared setup investigation and independently audit the source inventory, including plugins/scripts, dynamic text, and images in scope. Keep glossary, context and voice guidance in their shared files; preserve user edits. Mark coverage provisional until the inventory is audited.
5. Save a version-2 source-bound request plan using the format returned by plan-format. Classify every source ID in kinds as dialogue, narration, ui, or unknown when evidence cannot establish the text type. Supply a complete speakers map: use an evidenced name or null for unknown/inapplicable speakers; UI always has a null speaker. Never inherit the previous speaker or infer identity or gender from speech style. Unknown speakers are valid and do not block translation. Group coherent exchanges; include relevant Japanese from the same scene/event branch, scene/context notes and runtime substitution meanings, field instruction keys, and explicit engine-specific protected tokens/layout bounds. Resolve subjects and addressees separately from the speaker; preserve voice supported by the Japanese without inventing an identity. Add qa_notes keyed by source ID only for concrete uncertainty that could change meaning, gender, perspective or a plot fact. State the ambiguity and evidence to check; do not flag every unknown speaker or turn guesses into established facts. Declare immutable source exports as inputs, not a store whose translation fields change while you work. Tracked game-source files bind to original so ordinary English injection does not invalidate their source. Use compile --input <project-relative plan>. The helper supplies the same compiled context and validators in every mode. For API work, respect the configured request size and include source overlap when an exchange spans requests.
6. Agent Translation: read request --run <id> --index <n>, translate with your own session using every context field, perform the source-checked dialogue pass, and save a JSON receipt with request_sha256 and translations. Use accept --run <id> --batch <id> --input <project-relative receipt>. DazedTL makes no translation API calls in this mode. Follow the user's delegation instructions.
7. Live/Batch API Translation: inspect the exact compiled request and quote. Obtain any missing spending authorization in this same conversation, then use start --run <id> --approve <quote token>. This submits only the frozen reviewed request set. Poll run for status; resume saved jobs with start --run <id>. Never replace Batch with Live silently. Reconcile uncertain submissions before any retry; use attach-batch only with the matching provider job ID. Prepare a new remaining-work quote for failed requests. Do not ask the user to return to the app or copy another prompt at routine phase boundaries.
8. Save translation records and report progress after each saved milestone, before waits, and at least every ten minutes. Use progress --input <project-relative report> for the maintained Len progress format. Routine progress reporting is lightweight; use operation backup_workspace or checkpoint for meaningful recovery milestones. Keep detailed evidence in status.md. Translation counts, source-checked review, images, injection, runtime QA and packaging are separate. Inspect each request's qa_notes and check flagged lines against surrounding source, relevant script branches or the installed scene. Preserve intentional ambiguity in the translation; retain any unresolved blocker in status.md. Review accepted requests with review only after actually checking them and their flagged ambiguities against the source; fingerprints are evidence, not counters to fabricate. For a correction, include the current result_sha256 as replaces_sha256 in the receipt and use accept again. It archives the previous result and invalidates affected review/QA; ordinary retries cannot overwrite accepted translations.
9. Fit using the actual engine/renderer. For MV/MZ, stage translated JSON and use operation write_rpgmaker with matching source, translated and output paths (or a registered backup_id). This preserves _original and refuses unsafe structural remapping. After an official source update, use rebase_rpgmaker with the current expected_original_commit when old metadata needs rebasing; it requires source bytes matching that exact original-branch file. Ordinary corrections keep their existing Japanese. Other engines retain native source/injection sidecars and use their own verified reconstruction tools. Record unresolved or excluded content explicitly.
10. Inject and verify the actual installed game. Use operation checkpoint with the complete runtime manifest to align original/main and create a local checkpoint plus a deduplicated workspace snapshot. Packaging reuses that snapshot when its contents are unchanged. Complete targeted structural, source/live and runtime QA; unavailable checks remain pending. Use operation package for a local Git patch after QA is complete. Public publishing, uploads, remotes and pushes remain separate requests.

For official updates, use stage_update with the new official folder/version to preserve it and create a working copy. It applies shared preparation to MV/MZ; complete the relevant skill's decryption, conversion or other prerequisites for other engines in the returned copy. Preview that prepared original with version_preview, inspect its saved result, then version_apply with that preview_id. Preserve conflict recovery and continue/abort through the helper. Use version_handoff after a completed update. Recompile only changed/new work with current source mappings; positional offsets alone are not stable across releases.

Use backups to list restore points, including older profile backups. operation restore_backup accepts backup_id and an absolute destination for a new folder outside the game; it verifies all restored bytes and never overwrites an existing folder.

Finish the local delivery or record a concrete blocker and exact next action. Continue automatically across routine phases.

Additional project instructions:
{instructions}
'''
        write_bytes(handoff_path := project_path(project.root, WORK + "/handoff.md", exists=False), handoff.encode("utf-8"))
        return {"handoff": handoff, "path": str(handoff_path)}

    def backups(self, project_id):
        _record, project = self.project(project_id)
        return backups.catalog(project.root, self.workspace / "backups" / project_id)

    def compile(self, project_id, input_path):
        self.idle(project_id)
        self.clean_drafts(project_id)
        legacy = self.legacy_record(project_id)
        if legacy and legacy["mode"] not in {"estimate", "offline"} and legacy["status"] != "complete":
            raise ValueError("Resume and reconcile the saved phased run before creating a new request corpus. Its paid work and outputs were retained.")
        record, project = self.project(project_id)
        selected = project.read()["options"]
        require_baseline(self.engine, project.root, selected, lifecycle(self.workspace, project_id))
        raw_path = project.artifact(input_path)
        raw = plan_input(read_json(raw_path))
        cfg = configuration(self.settings, selected["mode"])
        if cfg["mode"] != "agent" and not raw["complete"]:
            raise ValueError("API cost review requires the complete independently audited request corpus.")
        if cfg["entries_per_request"] and any(len(batch["sources"]) > cfg["entries_per_request"] for batch in raw["batches"]):
            raise ValueError("A batch exceeds the configured entries per request. Split at a coherent boundary with source context, or adjust the model setting.")
        inputs = list(dict.fromkeys([input_path, *raw["inputs"], *self.guidance_inputs(project.root)]))
        for path in inputs:
            project_path(project.root, path, exists=False)
        bindings = self.engine.source_bindings(project.root, raw["inputs"])
        before = evidence(project.root, [path for path in inputs if path not in bindings])
        requests, compiler = compile_requests(self.engine, project.root, selected, raw, cfg["language"])
        verify_evidence(project.root, before)
        self.engine.verify_bindings(project.root, bindings)
        self.jobs.store.overlapping(project_id, {row["fingerprint"] for row in requests})
        limits = None
        if cfg["mode"] != "agent":
            batch_provider = self.engine.batch_supported(cfg)
            cfg["rates"]["batch_factor"] = 0.5 if batch_provider else None
            if cfg["mode"] == "batch" and not batch_provider:
                raise ValueError("This route does not support Batch execution. Choose a supported connection or explicitly select Live.")
            limits = self.engine.batch_limits(cfg) if batch_provider else None
            for request in requests:
                request["params"] = self.engine.payload(request, cfg)
                if limits and len(limits) > 2 and limits[2]:
                    request["input_tokens"] = self.engine.input_tokens(request["params"])
        results = Results(project.root)
        pending = [row for row in requests if not results.get(row)]
        estimate = quote(pending, cfg, self.engine.token_count) if cfg["mode"] != "agent" else None
        plan = {"version": 1, "kind": "translation", "source": str(project.root), "options": selected,
                "scope_sha256": scope(selected), "configuration": cfg, "requests": requests,
                "complete": raw["complete"], "evidence": before, "original_bindings": bindings, "compiler": compiler,
                "input_path": input_path, "batch_limits": limits}
        job = self.jobs.store.create(project_id, plan, estimate)
        self.refresh_progress(project_id, plan)
        return self.jobs.store.view(job)

    def guidance_inputs(self, source):
        root = Path(source)
        result = []
        for relative in (".dazedtl/glossary.txt", ".dazedtl/reference-games.json", ".dazedtl/skills/game.md", ".dazedtl/skills/quirks.md"):
            path = project_path(root, relative, exists=False)
            if path.is_file():
                result.append(relative)
        folder = root / ".dazedtl/skills"
        if folder.is_dir():
            result.extend(path.relative_to(root).as_posix() for path in folder.glob("*.md") if path.relative_to(root).as_posix() not in result)
        return result

    def validate_current(self, project_id, plan):
        record, project = self.project(project_id)
        if str(project.root) != plan["source"] or scope(project.read()["options"]) != plan["scope_sha256"]:
            raise ValueError("The project scope changed. Compile and review a new plan.")
        verify_evidence(project.root, plan["evidence"])
        self.engine.verify_bindings(project.root, plan["original_bindings"])
        require_baseline(self.engine, project.root, plan["options"], lifecycle(self.workspace, project_id))
        verify_compilation(self.engine, plan)

    def run(self, project_id, run_id):
        self.jobs.reconcile()
        job = self.jobs.store.record(run_id, project_id)
        return self.jobs.store.view(job)

    def request(self, project_id, run_id, index):
        _job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation" or type(index) is not int or not 0 <= index < len(plan["requests"]):
            raise ValueError("Choose a request in this run.")
        return {"run_id": run_id, "index": index, "total": len(plan["requests"]), "request": plan["requests"][index],
                "result": Results(plan["source"]).get(plan["requests"][index])}

    def start(self, project_id, run_id, approval_token=""):
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation":
            raise ValueError("Use the project operation controls for this job.")
        if not self.jobs.store.authorized(job):
            self.clean_drafts(project_id)
            if not approval_token or approval_token != job["approval_token"]:
                raise ValueError("Review and approve this exact quote before submitting.")
            self.validate_current(project_id, plan)
            self.jobs.store.authorize(job)
        return self.jobs.start(run_id, project_id)

    def stop(self, project_id, run_id, cancel_provider=False):
        if type(cancel_provider) is not bool:
            raise ValueError("Choose whether to pause locally or cancel the provider batch.")
        if cancel_provider:
            job, plan = self.jobs.store.load(run_id, project_id)
            if plan["kind"] != "translation" or plan["configuration"]["mode"] != "batch":
                raise ValueError("Provider cancellation applies to Batch runs.")
            if job["status"] == "complete":
                return self.jobs.store.view(job)
            write_json(self.jobs.store.folder(run_id) / "cancel.json", {"requested": True})
            if self.jobs.store.authorized(job):
                return self.jobs.start(run_id, project_id)
            for row in job["states"].values():
                if row["state"] == "pending":
                    row.update(state="failed", message="Canceled before submission.")
            job.update(status="needs_attention", message="Canceled before submission; no requests were sent.")
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
            raise ValueError("Reconcile in-flight work before importing a replacement result.")
        self.jobs.store.overlapping(project_id, {request["fingerprint"]}, exclude=run_id)
        receipt = read_json(project_path(plan["source"], input_path))
        if not isinstance(receipt, dict) or receipt.get("request_sha256") != request["fingerprint"] or "translations" not in receipt:
            raise ValueError("The receipt must bind translations to this request_sha256.")
        results = Results(plan["source"])
        provenance = {"run_id": run_id, "mode": "agent" if plan["configuration"]["mode"] == "agent" else "reviewed_import"}
        if "replaces_sha256" in receipt:
            results.correct(request, receipt["translations"], receipt["replaces_sha256"], {**provenance, "correction": True})
        else:
            results.accept(request, receipt["translations"], provenance)
        job["states"][batch_id] = {"state": "accepted", "message": ""}
        if all(row["state"] == "accepted" for row in job["states"].values()):
            job.update(status="complete", message="Translations saved. Injection and runtime QA remain separate.")
        self.jobs.store.save(job)
        self.refresh_progress(project_id, plan)
        return self.jobs.store.view(job)

    def review(self, project_id, run_id, batch_id, request_sha256):
        self.idle(project_id)
        _job, plan = self.jobs.store.load(run_id, project_id)
        self.validate_current(project_id, plan)
        request = next((row for row in plan["requests"] if row["id"] == batch_id and row["fingerprint"] == request_sha256), None)
        if not request:
            raise ValueError("Review must refer to the exact saved request.")
        results = Results(plan["source"])
        value = results.get(request)
        if not value:
            raise ValueError("Save accepted translations before recording their source-checked review.")
        value["reviewed"] = {identity: digest((digest(source.encode("utf-8")) + ":" + digest(value["translations"][identity].encode("utf-8"))).encode("ascii"))
                             for identity, source in request["sources"].items()}
        write_json(project_path(plan["source"], results.relative(request)), value)
        self.refresh_progress(project_id, plan)
        return {"saved": True}

    def refresh_progress(self, project_id, plan):
        verify_evidence(plan["source"], plan["evidence"])
        self.engine.verify_bindings(plan["source"], plan["original_bindings"])
        relative, changed = Results(plan["source"]).export(plan)
        report_path = project_path(plan["source"], WORK + "/progress-report.json", exists=False)
        report = read_json(report_path) if report_path.exists() else {"phases": {}}
        report.update(text=relative, inputs=list(plan["evidence"]))
        if changed:
            report.update(phase="translation", blocker="", next_action="Continue remaining translations, then perform fitting, injection and QA.")
            report.setdefault("phases", {}).update(translation="active", injection="pending", qa="pending", patch="pending")
        self.engine.progress(plan["source"], plan["options"], report)
        write_json(report_path, report)

    def progress(self, project_id, input_path):
        self.idle(project_id)
        _record, project = self.project(project_id)
        report = read_json(project.artifact(input_path))
        if isinstance(report, dict) and report.get("phases", {}).get("qa") == "complete":
            state = lifecycle(self.workspace, project_id)
            manifest_path = state.get("runtime_manifest") or state.get("checkpoint", {}).get("manifest")
            if not manifest_path:
                raise ValueError("Register the reviewed runtime patch manifest before reporting completed QA.")
            manifest = read_json(project.artifact(manifest_path))
            proof = delivery.record(project.root, manifest_path, self.engine.runtime_paths(manifest))
            report = {**report, "inputs": list(dict.fromkeys([*report.get("inputs", []), proof]))}
        value = self.engine.progress(project.root, project.read()["options"], report)
        write_json(project_path(project.root, WORK + "/progress-report.json", exists=False), report)
        return value

    def operation(self, project_id, action, arguments):
        self.idle(project_id)
        self.clean_drafts(project_id)
        if action not in OPERATIONS or not isinstance(arguments, dict) or set(arguments) - OPERATIONS[action][1]:
            raise ValueError("Unknown operation or operation fields.")
        required = {
            "restore_backup": {"backup_id", "destination"},
            "git_setup": {"version"}, "write_rpgmaker": {"source", "translated", "output"},
            "rebase_rpgmaker": {"source", "translated", "output", "expected_original_commit"},
            "checkpoint": {"manifest"}, "stage_update": {"official", "version"},
            "version_preview": {"official", "version"}, "version_apply": {"preview_id"},
        }.get(action, set())
        if any(not isinstance(arguments.get(key), str) or not arguments[key].strip() for key in required):
            raise ValueError("Required operation arguments: " + ", ".join(sorted(required)))
        for key, value in arguments.items():
            if key in {"untranslated", "patch_overlay"}:
                if type(value) is not bool:
                    raise ValueError("Operation flags must be true or false.")
            elif not isinstance(value, str) or len(value) > 10000 or "\0" in value:
                raise ValueError("Operation paths and labels must be bounded text.")
        _record, project = self.project(project_id)
        selected = project.read()["options"]
        if action == "version_apply":
            previous, preview = self.jobs.store.load(arguments.get("preview_id", ""), project_id)
            if previous["status"] != "complete" or preview.get("action") != "version_preview":
                raise ValueError("Review a completed official-update preview first.")
            arguments = {**preview["arguments"], "preview": previous["result"]}
        if action == "package":
            progress = self.engine.progress(project.root, selected, verify=True)
            if progress.get("warnings") or progress["phases"].get("qa") != "complete":
                raise ValueError("Complete and record current QA evidence before packaging the translation.")
            for metric in ("text", "images") if selected["include_images"] else ("text",):
                counts = progress["metrics"][metric]
                if counts["total"] is None or counts["translated"] != counts["total"]:
                    raise ValueError("Finish the audited translation scope before packaging; unknown totals are not complete.")
            delivery.verify(project.root, full=True)
        self.settings.prepare_engine()
        plan = {"version": 1, "kind": "operation", "source": str(project.root), "options": selected,
                "action": action, "arguments": arguments, "label": OPERATIONS[action][0]}
        bound = []
        for key in ("manifest", "translated", "output", "source"):
            if arguments.get(key) and not (key == "source" and arguments.get("backup_id")):
                path = project_path(project.root, arguments[key], exists=key != "output")
                if path.is_file():
                    bound.append(arguments[key])
        if bound:
            plan["evidence"] = evidence(project.root, list(dict.fromkeys(bound)))
        job = self.jobs.store.create(project_id, plan)
        return self.jobs.start(job["id"], project_id)

    def attach_batch(self, project_id, run_id, index, provider_job_id):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation" or plan["configuration"]["mode"] != "batch" or type(index) is not int or not 0 <= index < len(job["batches"]):
            raise ValueError("Choose an uncertain Batch submission.")
        chunk = job["batches"][index]
        if chunk["state"] not in {"submitting", "unmatched"} or not isinstance(provider_job_id, str) or not provider_job_id.strip() or len(provider_job_id) > 500:
            raise ValueError("Only an uncertain submission can be attached to its matching provider job.")
        if chunk["id"]:
            chunk.setdefault("previous_ids", []).append(chunk["id"])
        chunk.update(id=provider_job_id.strip(), state="submitted", attached=True)
        for item in chunk["items"]:
            job["states"][item["request"]] = {"state": "queued", "message": "Provider job attached; awaiting collection."}
        job.update(status="stopped", message="Provider job attached. Resume to verify and collect its request IDs.")
        self.jobs.store.save(job)
        return self.jobs.store.view(job)

    def resolve_uncertain(self, project_id, run_id, batch_id, request_sha256, retry_reviewed):
        self.idle(project_id)
        job, plan = self.jobs.store.load(run_id, project_id)
        if plan["kind"] != "translation" or plan["configuration"]["mode"] != "live" or retry_reviewed is not True:
            raise ValueError("Explicitly review the uncertain Live request before preparing a new paid attempt.")
        request = next((row for row in plan["requests"] if row["id"] == batch_id and row["fingerprint"] == request_sha256), None)
        if not request or job["states"][batch_id]["state"] != "uncertain":
            raise ValueError("Choose the exact unresolved Live request.")
        job["states"][batch_id] = {"state": "failed", "message": "Uncertain outcome reviewed. A new remaining-work quote is required before another attempt."}
        job.update(status="needs_attention", message="Outcome reviewed. Compile and approve a new quote for remaining work.")
        self.jobs.store.save(job)
        return self.jobs.store.view(job)

    def identify(self, project_id, engine, evidence_file):
        self.idle(project_id)
        _record, project = self.project(project_id)
        if not isinstance(engine, str) or not engine.strip() or len(engine) > 120 or any(ord(char) < 32 for char in engine):
            raise ValueError("Use a short engine name supported by the investigation evidence.")
        value = {"engine": engine.strip(), "evidence": evidence(project.root, [evidence_file])}
        write_json(self.workspace / "translation/projects" / project_id / "engine.json", value)
        return {"saved": True}

    def legacy(self, project_id, action, token="", approved=False):
        if self.jobs.running(project_id) or not self.legacy_record(project_id):
            raise ValueError("Choose an available saved phased run with no competing project operation.")
        handlers = getattr(self, "legacy_actions", {})
        if action not in handlers:
            raise ValueError("Supported saved-run actions are resume, stop, answer, and export.")
        if action == "answer":
            return handlers[action](project_id, token, approved)
        return handlers[action](project_id)
