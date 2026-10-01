"""A small project goes from source-bound plans to reusable accepted work."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dazedtl.projects.store import Projects
from dazedtl.settings.store import Settings
from dazedtl.settings.execution import worker_secret, configuration, connection_summary
from dazedtl.storage import write_json
from dazedtl.translation.backups import snapshot, materialized, store_path
from dazedtl.translation.files import digest, read_json, evidence
from dazedtl.translation.operations import lifecycle_path, require_baseline, execute, lifecycle, verify_guided_review
from dazedtl.translation.project import ProjectWorkspace, DEFAULTS, WORK, scope
from dazedtl.translation.compilation import compile_requests
from dazedtl.translation.requests import plan_input
from dazedtl.translation.service import Translation
from dazedtl.translation import delivery


class Engine:
    def __init__(self, source):
        self.source = source
        self.reports = []
        self.pending = []

    def git_status(self, source, *_args):
        return {"repo_root": str(source), "configured": True, "original_version": "1.0", "translation_version": "1.0",
                "current_branch": "main", "translation_branch": "main", "pending_operations": self.pending,
                "asset_sync_pending": False}

    def compile(self, _root, _options, plan, language):
        return [{"context": {"system": "Translate into " + language, "glossary": "Approved names", "sfx_reference": "Advisory SFX",
                  "request_instructions": batch.get("instruction_key", ""), "preceding_japanese_source_context": batch.get("source_context", ""),
                  "user": json.dumps({"sources": batch["sources"], "speakers": batch.get("speakers")}), "reference_translations": {"matches": {}}}}
                for batch in plan["batches"]], "fixture-compiler"

    def payload(self, request, configuration):
        return {"model": configuration["model"], "messages": [{"role": "user", "content": request["context"]["user"]}]}

    def progress(self, _source, _options, report=None, **_kwargs):
        if report is not None:
            self.reports.append(deepcopy(report))
        return self.reports[-1] if self.reports else {}

    def batch_supported(self, _configuration):
        return "openai"

    def batch_limits(self, _configuration):
        return [50, 100000]

    def token_count(self, text):
        return len(text)

    def source_bindings(self, _source, _paths):
        return {}

    def verify_bindings(self, _source, bindings):
        if bindings:
            raise ValueError("Fixture sources are independent files.")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.game.mkdir()
        write_json(self.game / "source.json", {"line": "はい。"})
        self.profile = self.root / "profile"
        self.projects = Projects(self.profile)
        self.record = self.projects.open({"source": str(self.game), "engine": "Investigation pending"})
        self.identity = self.record["id"]
        self.project = ProjectWorkspace(self.game)
        self.project.save("new", {**DEFAULTS, "include_images": False})
        backup = snapshot(self.game, store_path(self.game), source_game=True)
        write_json(lifecycle_path(self.profile, self.identity), {"version": 1, "source_backup": backup})
        connection = {"id": "connection", "name": "Local provider", "provider": "custom", "protocol": "openai", "endpoint": "https://provider.invalid/v1",
                      "secret": "fixture-private-value", "keyless": False, "organization": "", "model": "fixture-model",
                      "model_options": {"fixture-model": {"pricing": "custom", "inputRate": 1, "outputRate": 2, "entriesPerRequest": 50}}}
        settings_data = {"version": 2, "revision": 1, "values": {"language": "English"}, "active": "connection", "connections": [connection]}
        self.settings_data = settings_data
        self.settings = SimpleNamespace(
            _read=lambda: deepcopy(settings_data), _connection=Settings._connection, _configured=Settings._configured,
            adapter=SimpleNamespace(allow_providers=False, running=lambda: False, workflows=SimpleNamespace(projects={}), validate_route=lambda _value: None),
            prepare_engine=lambda: None,
        )
        self.engine = Engine(self.root)
        self.service = Translation(self.profile, self.projects, self.settings, self.engine)
        self.plan_path = WORK + "/work/requests.json"
        write_json(self.game / self.plan_path, {"version": 2, "complete": True, "inputs": ["source.json"], "batches": [{
            "id": "scene", "sources": {"line": "はい。"}, "kinds": {"line": "dialogue"},
            "speakers": {"line": None}, "source_context": "Previous exchange"}]})

    def test_agent_receipt_review_and_mode_switch_keep_the_same_saved_work(self):
        raw = read_json(self.game / self.plan_path)
        note = "Check whether this answer affirms the visitor's question or the guard's."
        raw["batches"][0]["qa_notes"] = {"line": note}
        write_json(self.game / self.plan_path, raw)
        run = self.service.compile(self.identity, self.plan_path)
        self.assertEqual(run["qa_requests"], [{"id": "scene", "index": 0, "notes": 1}])
        preview = self.service.request(self.identity, run["id"], 0)
        self.assertEqual(preview["request"]["context"]["qa_notes"], {"line": note})
        receipt = WORK + "/work/result.json"
        write_json(self.game / receipt, {"request_sha256": preview["request"]["fingerprint"], "translations": {"line": "Yes."}})
        accepted = self.service.accept(self.identity, run["id"], "scene", receipt)
        self.assertEqual(accepted["accepted_units"], 1)
        self.assertEqual(accepted["status"], "complete")
        report = read_json(self.game / (WORK + "/progress-report.json"))
        report.update(phase=None)
        report["phases"].update(translation="complete", injection="complete", qa="complete", patch="complete")
        write_json(self.game / (WORK + "/progress-report.json"), report)
        self.service.review(self.identity, run["id"], "scene", preview["request"]["fingerprint"])
        reviewed = self.service.request(self.identity, run["id"], 0)["result"]
        self.assertIn("line", reviewed["reviewed"])
        exported = read_json(self.game / (WORK + "/work/translation-units.json"))["units"][0]
        self.assertEqual((exported["kind"], exported["speaker"], exported["qa_note"]), ("dialogue", None, note))
        self.assertEqual(self.engine.reports[-1]["phases"]["qa"], "complete")
        selected = self.project.read()
        self.service.save(self.identity, selected["revision"], {**selected["options"], "mode": "live"})
        reused = self.service.compile(self.identity, self.plan_path)
        self.assertEqual(reused["status"], "complete")
        self.assertEqual(reused["quote"]["requests"], 0)
        self.assertEqual(self.engine.reports[-1]["phases"]["qa"], "complete")
        _job, frozen = self.service.jobs.store.load(reused["id"])
        self.assertNotIn("secret", frozen["configuration"])
        self.assertNotIn("fixture-private-value", json.dumps(frozen))
        self.assertIn(note, frozen["requests"][0]["params"]["messages"][0]["content"])
        write_json(self.game / receipt, {"request_sha256": preview["request"]["fingerprint"],
                   "translations": {"line": "That's right."}, "replaces_sha256": reviewed["result_sha256"]})
        self.service.accept(self.identity, reused["id"], "scene", receipt)
        corrected = self.service.request(self.identity, reused["id"], 0)
        self.assertNotIn("reviewed", corrected["result"])
        self.assertEqual(corrected["request"]["context"]["qa_notes"]["line"], note)

    def test_unversioned_saved_run_keeps_results_and_approval_through_compatible_compiler_update(self):
        raw = {"complete": True, "inputs": ["source.json"], "batches": [{"id": "scene", "sources": {"line": "はい。"}}]}
        write_json(self.game / self.plan_path, raw)
        self.assertEqual(plan_input(raw, allow_legacy=True), raw)
        with self.assertRaises(ValueError):
            self.service.compile(self.identity, self.plan_path)
        selected = self.project.read()["options"]
        cfg = configuration(self.settings, "live")
        requests, _compiler = compile_requests(self.engine, self.game, selected, raw, cfg["language"])
        for row in requests:
            row["params"] = self.engine.payload(row, cfg)
        frozen = {"version": 1, "kind": "translation", "source": str(self.game), "options": selected,
                  "scope_sha256": scope(selected), "configuration": cfg, "requests": requests,
                  "complete": True, "evidence": evidence(self.game, [self.plan_path, "source.json"]),
                  "original_bindings": {}, "compiler": "previous-compiler", "input_path": self.plan_path, "batch_limits": None}
        store = self.service.jobs.store
        job = store.create(self.identity, frozen, {"cost": 1})
        store.authorize(job)
        folder = store.folder(job["id"])
        original = {name: (folder / name).read_bytes() for name in ("plan.json", "authorization.json")}
        self.service.validate_current(self.identity, frozen)
        receipt = WORK + "/work/legacy-result.json"
        write_json(self.game / receipt, {"request_sha256": requests[0]["fingerprint"], "translations": {"line": "Yes."}})
        self.service.accept(self.identity, job["id"], "scene", receipt)
        self.service.review(self.identity, job["id"], "scene", requests[0]["fingerprint"])
        preview = self.service.request(self.identity, job["id"], 0)
        self.assertEqual(preview["result"]["translations"], {"line": "Yes."})
        self.assertNotIn("line_kinds", preview["request"]["context"])
        self.assertEqual(original, {name: (folder / name).read_bytes() for name in original})
        self.assertTrue(store.authorized(store.record(job["id"])))
        self.assertEqual(store.view(store.record(job["id"]))["qa_requests"], [])
        with patch.object(self.engine, "payload", return_value={"changed": "provider parameters"}), self.assertRaisesRegex(ValueError, "payload changed"):
            self.service.validate_current(self.identity, frozen)
        changed = deepcopy(requests)
        changed[0]["context"]["system"] = "Changed guidance"
        with patch.object(self.engine, "compile", return_value=(changed, "previous-compiler")), self.assertRaises(ValueError):
            self.service.validate_current(self.identity, frozen)

    def test_changed_inputs_cannot_approve_or_bless_old_results(self):
        selected = self.project.read()
        self.service.save(self.identity, selected["revision"], {**selected["options"], "mode": "live"})
        run = self.service.compile(self.identity, self.plan_path)
        _job, frozen = self.service.jobs.store.load(run["id"])
        before = (self.game / (WORK + "/progress.json")).read_bytes() if (self.game / (WORK + "/progress.json")).exists() else None
        reports = len(self.engine.reports)
        write_json(self.game / "source.json", {"line": "変更。"})
        with self.assertRaises(ValueError):
            self.service.start(self.identity, run["id"], run["approval_token"])
        self.assertFalse(self.service.jobs.store.authorized(self.service.jobs.store.load(run["id"])[0]))
        with self.assertRaises(ValueError):
            self.service.refresh_progress(self.identity, frozen)
        self.assertEqual(len(self.engine.reports), reports)
        if before is not None:
            self.assertEqual((self.game / (WORK + "/progress.json")).read_bytes(), before)

    def test_backups_and_conflict_recovery_are_real_prerequisites(self):
        state = read_json(lifecycle_path(self.profile, self.identity))
        self.engine.pending = ["CHERRY_PICK_HEAD"]
        with self.assertRaises(ValueError):
            require_baseline(self.engine, self.game, DEFAULTS, state)
        self.assertTrue(require_baseline(self.engine, self.game, DEFAULTS, state, allow_pending=True)["configured"])
        self.engine.pending = []
        (Path(state["source_backup"]["path"]) / "manifest.json").unlink()
        with self.assertRaises(ValueError):
            self.service.compile(self.identity, self.plan_path)

    def test_current_selection_excludes_drafts_and_secrets_while_saved_runs_keep_their_route(self):
        selected = self.project.read()
        self.service.save(self.identity, selected["revision"], {**selected["options"], "mode": "live"})
        run = self.service.compile(self.identity, self.plan_path)
        _job, plan = self.service.jobs.store.load(run["id"])
        write_json(self.profile / "settings/settings.json", self.settings_data)
        self.assertEqual(worker_secret(self.profile, plan["configuration"]), "fixture-private-value")
        self.settings_data["draft"] = {"connections": {"connection": {"model": "unsaved-model"}}}
        self.assertEqual(connection_summary(self.settings), {"name": "Local provider", "model": "fixture-model"})
        self.settings_data["connections"].append({**self.settings_data["connections"][0], "id": "second",
                                                 "name": "Another provider", "model": "next-model"})
        self.settings_data["active"] = "second"
        self.assertEqual(connection_summary(self.settings), {"name": "Another provider", "model": "next-model"})
        self.assertEqual(plan["configuration"]["connection_id"], "connection")
        self.settings_data["active"] = ""
        self.assertIsNone(connection_summary(self.settings))
        changed = deepcopy(self.settings_data)
        changed["connections"][0]["endpoint"] = "https://different.invalid/v1"
        write_json(self.profile / "settings/settings.json", changed)
        with self.assertRaises(ValueError):
            worker_secret(self.profile, plan["configuration"])

    def test_backup_never_recurses_into_itself_or_copies_git_and_work_records_as_source(self):
        (self.game / ".git").mkdir()
        (self.game / ".git/config").write_text("local Git state")
        with self.assertRaises(ValueError):
            snapshot(self.game, self.game / "backups", source_game=True)
        result = snapshot(self.game, self.profile / "more-backups", source_game=True)
        files = read_json(Path(result["path"]) / "manifest.json")["files"]
        self.assertEqual(set(files), {"source.json"})
        with materialized(result["path"]) as (restored, _manifest):
            self.assertEqual(digest((restored / "source.json").read_bytes()), files["source.json"])

    def test_checkpoints_use_temporary_verified_originals_and_reuse_workspace_backups(self):
        manifest_path = WORK + "/work/patch-files.json"
        write_json(self.game / manifest_path, ["source.json"])
        asset = self.game / "unchanged-asset.bin"
        asset.write_bytes(b"original asset")
        configured = [False]
        original_status = self.engine.git_status
        self.engine.git_status = lambda source, *args: {**original_status(source, *args),
            "configured": configured[0], "translation_commit": "checkpoint"}
        self.engine.audit_scope = lambda *_args: None
        self.engine.runtime_paths = lambda manifest: list(manifest)
        originals = []
        def setup(_source, _options, _version, original, _untranslated):
            folder = Path(original)
            originals.append(folder)
            self.assertEqual((folder / "unchanged-asset.bin").read_bytes(), b"original asset")
            configured[0] = True
            return self.engine.git_status(self.game)
        self.engine.git_setup = setup
        def git_scope(_source, _options, _manifest, original, _dry_run):
            folder = Path(original)
            originals.append(folder)
            self.assertEqual(read_json(folder / "source.json"), {"line": "はい。"})
            self.assertFalse((folder / "unchanged-asset.bin").exists())
            return {"staged": 1}
        self.engine.git_scope = git_scope
        self.engine.commit = lambda *_args: "checkpoint"
        self.engine.package = lambda *_args: {"path": str(self.root / "patch.zip")}
        self.engine.detect = lambda _source: "Other engine"
        job = {"project_id": self.identity, "id": "b" * 32}
        def operation(action, **arguments):
            return execute(self.engine, self.profile, job, {"source": str(self.game), "options": DEFAULTS,
                "action": action, "arguments": arguments}, lambda: False)
        operation("git_setup", version="1.0", untranslated=True, manifest=manifest_path)
        self.assertTrue(all(not path.exists() for path in originals))
        write_json(self.game / "source.json", {"line": "Yes."})
        delivery.record(self.game, manifest_path, ["source.json"])
        first = operation("checkpoint", manifest=manifest_path)
        second = operation("checkpoint", manifest=manifest_path)
        packaged = operation("package")
        self.assertEqual(first["backup"]["id"], second["backup"]["id"])
        self.assertEqual(second["backup"]["bytes_added"], 0)
        self.assertEqual(packaged["backup"]["id"], first["backup"]["id"])
        self.assertTrue(all(not path.exists() for path in originals))
        self.assertTrue(self.service.backups(self.identity)["snapshots"])
        restored = self.root / "recovered-work"
        operation("restore_backup", backup_id=first["backup"]["id"], destination=str(restored))
        self.assertEqual(read_json(restored / "len-method/work/patch-files.json"), ["source.json"])
        self.assertFalse((restored / "backups").exists())
        official = self.root / "new-official"
        official.mkdir()
        (official / "native.bin").write_bytes(b"new official bytes\r\n")
        staged = operation("stage_update", official=str(official), version="1.1")
        self.assertEqual((Path(staged["official"]) / "native.bin").read_bytes(), b"new official bytes\r\n")
        self.assertTrue(lifecycle(self.profile, self.identity)["workspace_backup"]["reused_snapshot"])

    def test_runtime_changes_invalidate_delivery_even_if_qa_report_is_unchanged(self):
        for action in ('guided_review', 'guided_package'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.service.operation(self.identity, action, {})
        path = WORK + "/work/patch-files.json"
        write_json(self.game / path, ["source.json"])
        delivery.record(self.game, path, ["source.json"])
        delivery.verify(self.game, full=True)
        self.engine.runtime_paths = lambda manifest: manifest['files']
        guided_manifest = '.dazedtl/guided/runtime-manifest.json'
        write_json(self.game / guided_manifest, {'files': ['source.json']})
        execute(self.engine, self.profile, {'project_id': self.identity}, {
            'source': str(self.game), 'options': DEFAULTS, 'action': 'guided_review',
            'arguments': {'manifest': guided_manifest}}, lambda: False)
        verify_guided_review(self.game, lifecycle(self.profile, self.identity))
        write_json(self.game / "source.json", {"line": "Changed after review"})
        with self.assertRaises(ValueError):
            delivery.verify(self.game, full=True)
        with self.assertRaises(ValueError):
            verify_guided_review(self.game, lifecycle(self.profile, self.identity))
