"""Shared request acceptance and paid-work recovery, with no provider or game dependencies."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path
from dazedtl.translation.project import ProjectWorkspace
from dazedtl.translation.requests import logical_request, plan_input, result_value
from dazedtl.translation.results import Results
from dazedtl.translation.jobs import RunStore
from dazedtl.translation.runner import Runner


def request(identity="scene", speaker="Lili"):
    return logical_request({"id": identity, "sources": {"line": "はい。⟦P0⟧"},
                            "constraints": {"line": {"tokens": ["⟦P0⟧"], "max_lines": 1}}}, {"speakers": {"line": speaker}})


class LiveProvider:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def live(self, _params):
        self.calls += 1
        if self.error:
            raise self.error
        return {"text": '{"line":"Yes. ⟦P0⟧"}', "prompt_tokens": 5, "completion_tokens": 4}


class BatchProvider:
    def __init__(self, error=None):
        self.calls = 0
        self.items = []
        self.error = error
        self.ended = False
        self.unrelated = False

    def submit(self, items):
        self.calls += 1
        self.items = items
        if self.error:
            raise self.error
        return {"id": "provider-job"}

    def status(self, _identity):
        return {"ended": self.ended, "terminal_failure": False, "api_status": "complete" if self.ended else "running", "counts": {}}

    def collect(self, _identity, mapping):
        if self.unrelated:
            return {}, [], {}
        return {key: {"text": '{"line":"Yes. ⟦P0⟧"}'} for key in reversed(list(mapping.values()))}, [], {"input_tokens": 10}


class TranslationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.game.mkdir()
        self.store = RunStore(self.root / "profile")

    def run_record(self, mode="live", requests=None):
        rows = deepcopy(requests or [request()])
        for row in rows:
            row["params"] = {"model": "fixture", "messages": []}
        plan = {"version": 1, "kind": "translation", "source": str(self.game), "complete": True,
                "requests": rows, "configuration": {"mode": mode, "model": "fixture"}, "batch_limits": [50, 100000]}
        job = self.store.create("project", plan, {"cost": 1})
        self.store.authorize(job)
        return job, plan

    def test_result_validation_preserves_ids_masks_and_distinct_speakers(self):
        first = request()
        second = request(speaker="Theo")
        results = Results(self.game)
        results.accept(first, {"line": "Yes. ⟦P0⟧"}, {"mode": "agent"})
        self.assertIsNone(results.get(second))
        relocated = logical_request({"id": first["id"], "sources": first["sources"], "constraints": first["constraints"]},
                                    {**first["context"], "context_sha256": "relocated-guidance-path", "request_sha256": "new-bookkeeping-hash"})
        self.assertIsNotNone(results.get(relocated))
        for invalid in ({"other": "Yes. ⟦P0⟧"}, {"line": "Yes."}, {"line": "Yes. ⟦P0⟧\nExtra"},
                        '{"line":"Yes. ⟦P0⟧","line":"No. ⟦P0⟧"}'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                result_value(first, invalid)
        with self.assertRaises(ValueError):
            results.accept(first, {"line": "Different. ⟦P0⟧"}, {})
        self.assertEqual(results.get(first)["translations"]["line"], "Yes. ⟦P0⟧")

    def test_reviewed_correction_retains_history_and_rejects_a_stale_result_hash(self):
        row = request()
        results = Results(self.game)
        old = results.accept(row, {"line": "Yes. ⟦P0⟧"}, {})
        changed = results.correct(row, {"line": "Of course. ⟦P0⟧"}, old["result_sha256"], {"correction": True})
        self.assertNotEqual(old["result_sha256"], changed["result_sha256"])
        self.assertNotIn("reviewed", changed)
        with self.assertRaises(ValueError):
            results.correct(row, {"line": "No. ⟦P0⟧"}, old["result_sha256"], {})
        history = list((self.game / ".dazedtl/len-method/work/accepted-history").rglob("*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0].read_text())["translations"], old["translations"])

    def test_worker_owner_loss_stops_before_another_paid_request(self):
        alive = [True]
        job, _plan = self.run_record(requests=[request("one"), request("two")])
        store = RunStore(self.store.workspace, owner_alive=lambda: alive[0])
        class Provider(LiveProvider):
            def live(self, params):
                result = super().live(params)
                alive[0] = False
                return result
        provider = Provider()
        Runner(store, job["id"], provider, lambda: None).step()
        current, _plan = store.load(job["id"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["status"], "stopped")
        self.assertEqual(current["states"]["one"]["state"], "accepted")
        self.assertEqual(current["states"]["two"]["state"], "pending")

    def test_cancellation_retains_completed_rows_and_does_not_submit_later_chunks(self):
        job, plan = self.run_record("batch", [request("one"), request("two")])
        # One request per provider job makes the remaining-work safeguard observable.
        plan["batch_limits"] = [1, 100000]
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)
        class Provider(BatchProvider):
            canceled = False
            def cancel(self, _identity):
                self.canceled = True
            def status(self, identity):
                if not self.canceled:
                    return super().status(identity)
                return {"ended": True, "terminal_failure": True, "api_status": "cancelled", "counts": {}}
            def collect_terminal(self, identity, mapping):
                return self.collect(identity, mapping)
        provider = Provider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        write_json(self.store.folder(job["id"]) / "cancel.json", {"requested": True})
        Runner(self.store, job["id"], provider, lambda: None).step()
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _plan = self.store.load(job["id"])
        self.assertTrue(provider.canceled)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["states"]["one"]["state"], "accepted")
        self.assertEqual(current["states"]["two"]["state"], "failed")

    def test_agent_results_are_reused_by_api_without_another_call(self):
        row = request()
        Results(self.game).accept(row, {"line": "Yes. ⟦P0⟧"}, {"mode": "agent"})
        job, plan = self.run_record(requests=[row])
        provider = LiveProvider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(provider.calls, 0)
        self.assertEqual(self.store.load(job["id"])[0]["status"], "complete")
        _path, changed = Results(self.game).export(plan)
        self.assertTrue(changed)
        _path, changed = Results(self.game).export(plan)
        self.assertFalse(changed)

    def test_saved_response_recovers_without_rebilling_after_an_interruption(self):
        job, plan = self.run_record()
        job["states"]["scene"]["state"] = "sending"
        self.store.save(job)
        provider = LiveProvider()
        runner = Runner(self.store, job["id"], provider, lambda: None)
        write_json(runner.response_path("scene"), {"text": '{"line":"Yes. ⟦P0⟧"}'})
        runner.step()
        self.assertEqual(provider.calls, 0)
        self.assertIsNotNone(Results(self.game).get(plan["requests"][0]))
        self.assertEqual(self.store.load(job["id"])[0]["status"], "complete")

    def test_uncertain_live_call_is_never_retried_implicitly(self):
        job, _plan = self.run_record()
        provider = LiveProvider(TimeoutError())
        Runner(self.store, job["id"], provider, lambda: None).step()
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _plan = self.store.load(job["id"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["status"], "uncertain")
        with self.assertRaises(ValueError):
            self.store.overlapping("project", {request()["fingerprint"]})

    def test_batch_wait_resume_and_unordered_collection_keep_one_submission(self):
        job, plan = self.run_record("batch", [request("one"), request("two")])
        provider = BatchProvider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(self.store.load(job["id"])[0]["status"], "waiting")
        Runner(self.store, job["id"], provider, lambda: None).step()
        provider.ended = True
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.store.load(job["id"])[0]["status"], "complete")
        self.assertTrue(all(Results(self.game).get(row) for row in plan["requests"]))

    def test_unknown_batch_submission_and_wrong_job_results_stay_blocked(self):
        for failure in (True, False):
            with self.subTest(submission_failure=failure):
                job, plan = self.run_record("batch", [request("failure" if failure else "wrong-job")])
                provider = BatchProvider(TimeoutError() if failure else None)
                provider.ended = True
                provider.unrelated = not failure
                Runner(self.store, job["id"], provider, lambda: None).step()
                Runner(self.store, job["id"], provider, lambda: None).step()
                self.assertEqual(provider.calls, 1)
                self.assertEqual(self.store.load(job["id"])[0]["status"], "uncertain")
                self.assertIsNone(Results(self.game).get(plan["requests"][0]))

    def test_approval_binds_project_plan_and_quote_and_boolean_is_insufficient(self):
        job, _plan = self.run_record()
        self.assertTrue(self.store.authorized(job))
        with self.assertRaises(ValueError):
            self.store.load(job["id"], "another-project")
        modified = deepcopy(job)
        modified["quote"]["cost"] = 0
        self.assertFalse(self.store.authorized(modified))
        (self.store.folder(job["id"]) / "authorization.json").unlink()
        self.assertTrue(job["approved"])
        self.assertFalse(self.store.authorized(job))
        path = self.store.folder(job["id"]) / "plan.json"
        changed = json.loads(path.read_text())
        changed["requests"][0]["sources"]["line"] = "Changed source"
        write_json(path, changed)
        with self.assertRaises(ValueError):
            self.store.load(job["id"])

    def test_stale_sources_stop_before_any_provider_call(self):
        job, _plan = self.run_record()
        provider = LiveProvider()
        def stale():
            raise ValueError("Sources changed")
        with self.assertRaisesRegex(ValueError, "Sources changed"):
            Runner(self.store, job["id"], provider, stale).step()
        self.assertEqual(provider.calls, 0)

    def test_portable_options_import_without_replacing_legacy_or_stale_edits(self):
        legacy = self.game / ".dazedtl/len-method/project.json"
        write_json(legacy, {"version": 3, "mode": "api", "include_images": False, "instructions": "Keep this", "install_forge": False})
        original = legacy.read_bytes()
        project = ProjectWorkspace(self.game)
        value = project.read()
        self.assertEqual(value["options"]["mode"], "batch")
        saved = project.save(value["revision"], {**value["options"], "mode": "live"})
        with self.assertRaises(ValueError):
            project.save(value["revision"], value["options"])
        self.assertEqual(project.read(), saved)
        self.assertEqual(legacy.read_bytes(), original)

    def test_project_paths_and_plan_constraints_reject_unsafe_inputs(self):
        for relative in ("../outside.json", ".git/config", str(self.root / "outside.json")):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                project_path(self.game, relative, exists=False)
        plan = {"version": 2, "complete": True, "inputs": ["source.json"], "batches": [{
            "id": "one", "sources": {"line": "はい。"}, "kinds": {"line": "dialogue"}, "speakers": {"other": None}}]}
        with self.assertRaises(ValueError):
            plan_input(plan)
        plan["batches"][0]["speakers"] = {"line": None}
        self.assertEqual(plan_input(plan), plan)

    def test_line_classification_requires_explicit_speakers_but_unknown_is_valid(self):
        batch = {"id": "scene", "sources": {"dialogue": "行った。", "narration": "夜が明けた。", "ui": "戻る", "other": "……"},
                 "kinds": {"dialogue": "dialogue", "narration": "narration", "ui": "ui", "other": "unknown"},
                 "speakers": {"dialogue": None, "narration": None, "ui": None, "other": None}}
        plan = {"version": 2, "complete": True, "inputs": ["source.json"], "batches": [batch]}
        self.assertEqual(plan_input(plan), plan)
        original = {"user": "Japanese source", "request_sha256": "before"}
        row = logical_request(batch, original)
        self.assertEqual(original, {"user": "Japanese source", "request_sha256": "before"})
        self.assertEqual(row["context"]["speakers"]["dialogue"], None)
        self.assertEqual(row["context"]["qa_notes"], {})
        job, _plan = self.run_record(requests=[row])
        self.assertEqual(self.store.view(job)["qa_requests"], [])
        for update in ({"speakers": None}, {"speakers": {}}, {"speakers": {**batch["speakers"], "dialogue": " "}},
                       {"speakers": {**batch["speakers"], "ui": "Lili"}}, {"kinds": {}},
                       {"kinds": {**batch["kinds"], "ui": "guess"}}, {"qa_notes": {"missing": "Who left?"}},
                       {"qa_notes": {"dialogue": " "}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                plan_input({**plan, "batches": [{**batch, **update}]})
        for field in ("kinds", "speakers"):
            with self.subTest(missing=field), self.assertRaises(ValueError):
                plan_input({**plan, "batches": [{key: value for key, value in batch.items() if key != field}]})
        classified = logical_request({**batch, "kinds": {**batch["kinds"], "other": "dialogue"}}, original)
        flagged = logical_request({**batch, "qa_notes": {"dialogue": "Check who left."}}, original)
        self.assertNotEqual(row["fingerprint"], classified["fingerprint"])
        self.assertNotEqual(row["fingerprint"], flagged["fingerprint"])
