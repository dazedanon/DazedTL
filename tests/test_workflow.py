"""A small project goes from source-bound plans to reusable accepted work."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from dazedtl.projects.store import Projects
from dazedtl.settings.store import Settings
from dazedtl.settings.execution import worker_secret
from dazedtl.storage import write_json
from dazedtl.translation.backups import snapshot
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.operations import lifecycle_path, require_baseline
from dazedtl.translation.project import ProjectWorkspace, DEFAULTS, WORK
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
        backup = snapshot(self.game, self.profile / "backups" / self.identity, source_game=True)
        write_json(lifecycle_path(self.profile, self.identity), {"version": 1, "source_backup": backup})
        connection = {"id": "connection", "provider": "custom", "protocol": "openai", "endpoint": "https://provider.invalid/v1",
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
        write_json(self.game / self.plan_path, {"complete": True, "inputs": ["source.json"], "batches": [{
            "id": "scene", "sources": {"line": "はい。"}, "speakers": {"line": "Lili"}, "source_context": "Previous exchange"}]})

    def test_agent_receipt_review_and_mode_switch_keep_the_same_saved_work(self):
        run = self.service.compile(self.identity, self.plan_path)
        preview = self.service.request(self.identity, run["id"], 0)
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

    def test_worker_credentials_cannot_silently_follow_a_changed_connection(self):
        selected = self.project.read()
        self.service.save(self.identity, selected["revision"], {**selected["options"], "mode": "live"})
        run = self.service.compile(self.identity, self.plan_path)
        _job, plan = self.service.jobs.store.load(run["id"])
        write_json(self.profile / "settings/settings.json", self.settings_data)
        self.assertEqual(worker_secret(self.profile, plan["configuration"]), "fixture-private-value")
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
        self.assertEqual(digest((Path(result["path"]) / "files/source.json").read_bytes()), files["source.json"])

    def test_runtime_changes_invalidate_delivery_even_if_qa_report_is_unchanged(self):
        path = WORK + "/work/patch-files.json"
        write_json(self.game / path, ["source.json"])
        delivery.record(self.game, path, ["source.json"])
        delivery.verify(self.game, full=True)
        write_json(self.game / "source.json", {"line": "Changed after review"})
        with self.assertRaises(ValueError):
            delivery.verify(self.game, full=True)
