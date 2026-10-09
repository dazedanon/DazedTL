"""Shared request acceptance and paid-work recovery, with no provider or game dependencies."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path
from dazedtl.translation.jobs import RunStore
from dazedtl.translation.project import ProjectWorkspace, scope
from dazedtl.translation.requests import logical_request, plan_input, result_value
from dazedtl.translation.results import Results
from dazedtl.translation.runner import Runner


def request(identity="scene", speaker="Lili"):
    return logical_request(
        {
            "id": identity,
            "sources": {"line": "はい。⟦P0⟧"},
            "constraints": {"line": {"tokens": ["⟦P0⟧"], "max_lines": 1}},
        },
        {"speakers": {"line": speaker}},
    )


class LiveProvider:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def live(self, _params):
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }


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
        return {
            "ended": self.ended,
            "terminal_failure": False,
            "api_status": "complete" if self.ended else "running",
            "counts": {},
        }

    def collect(self, _identity, mapping):
        if self.unrelated:
            return {}, [], {}
        return (
            {
                key: {"text": '{"line":"Yes. ⟦P0⟧"}'}
                for key in reversed(list(mapping.values()))
            },
            [],
            {"input_tokens": 10},
        )


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
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "complete": True,
            "requests": rows,
            "configuration": {"mode": mode, "model": "fixture"},
            "batch_limits": [50, 100000],
        }
        job = self.store.create("project", plan, {"cost": 1})
        self.store.authorize(job)
        return job, plan

    def test_result_validation_preserves_ids_masks_and_distinct_speakers(self):
        first = request()
        second = request(speaker="Theo")
        results = Results(self.game)
        results.accept(first, {"line": "Yes. ⟦P0⟧"}, {"mode": "agent"})
        self.assertIsNone(results.get(second))
        relocated = logical_request(
            {
                "id": first["id"],
                "sources": first["sources"],
                "constraints": first["constraints"],
            },
            {
                **first["context"],
                "context_sha256": "relocated-guidance-path",
                "request_sha256": "new-bookkeeping-hash",
            },
        )
        self.assertIsNotNone(results.get(relocated))
        for invalid in (
            {"other": "Yes. ⟦P0⟧"},
            {"line": "Yes."},
            {"line": "Yes. ⟦P0⟧\nExtra"},
            '{"line":"Yes. ⟦P0⟧","line":"No. ⟦P0⟧"}',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                result_value(first, invalid)
        with self.assertRaises(ValueError):
            results.accept(first, {"line": "Different. ⟦P0⟧"}, {})
        self.assertEqual(results.get(first)["translations"]["line"], "Yes. ⟦P0⟧")

    def test_reviewed_correction_retains_history_and_rejects_a_stale_result_hash(self):
        row = request()
        results = Results(self.game)
        old = results.accept(row, {"line": "Yes. ⟦P0⟧"}, {})
        changed = results.correct(
            row, {"line": "Of course. ⟦P0⟧"}, old["result_sha256"], {"correction": True}
        )
        self.assertNotEqual(old["result_sha256"], changed["result_sha256"])
        self.assertNotIn("reviewed", changed)
        with self.assertRaises(ValueError):
            results.correct(row, {"line": "No. ⟦P0⟧"}, old["result_sha256"], {})
        history = list(
            (self.game / ".dazedtl/len-method/work/accepted-history").rglob("*.json")
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(
            json.loads(history[0].read_text())["translations"], old["translations"]
        )

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
                return {
                    "ended": True,
                    "terminal_failure": True,
                    "api_status": "cancelled",
                    "counts": {},
                }

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

    def test_failed_or_uncertain_live_call_is_never_retried_implicitly(self):
        rejection = ValueError("Provider rejected the request")
        rejection.status_code = 404
        for error, status in ((TimeoutError(), "uncertain"), (rejection, "failed")):
            with self.subTest(status=status):
                job, plan = self.run_record(requests=[request(speaker=status)])
                provider = LiveProvider(error)
                Runner(self.store, job["id"], provider, lambda: None).step()
                current, _plan = self.store.load(job["id"])
                self.assertEqual(current["status"], status)
                # Reading a retired terminal label must keep the receipt and
                # request state authoritative, including the duplicate guard.
                current["status"] = "retired_status"
                self.store.save(current)
                before = (self.store.folder(job["id"]) / "job.json").read_bytes()
                self.assertEqual(self.store.view(current)["status"], "failed")
                self.assertEqual(
                    (self.store.folder(job["id"]) / "job.json").read_bytes(), before
                )
                Runner(self.store, job["id"], provider, lambda: None).step()
                self.assertEqual(provider.calls, 1)
                self.assertEqual(self.store.load(job["id"])[0]["status"], status)
                if status == "uncertain":
                    with self.assertRaises(ValueError):
                        self.store.overlapping(
                            "project", {plan["requests"][0]["fingerprint"]}
                        )

    def test_refusal_clarification_is_bounded_and_retains_both_paid_attempts(self):
        # A refusal in valid JSON used to pass output validation. A repeated
        # refusal or lost retry response must not become dialogue or another bill.
        from dazedtl.translation.refusals import CLARIFICATION, POLICY, refused

        refusal = {
            "text": '{"line":"I cannot translate explicit sexual content."}',
            "prompt_tokens": 7,
            "completion_tokens": 3,
        }
        valid = {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }
        for index, outcome in enumerate((valid, refusal, TimeoutError())):
            with self.subTest(outcome=outcome):
                job, plan = self.run_record(requests=[request(speaker=str(index))])
                plan["configuration"]["refusalRetry"] = POLICY
                write_json(self.store.folder(job["id"]) / "plan.json", plan)
                job["plan_sha256"] = digest(plan)
                self.store.save(job)
                calls = []

                class Provider:
                    def live(self, params):
                        calls.append(deepcopy(params))
                        if len(calls) == 1:
                            return refusal
                        if isinstance(outcome, Exception):
                            raise outcome
                        return outcome

                provider = Provider()
                Runner(self.store, job["id"], provider, lambda: None).step()
                Runner(self.store, job["id"], provider, lambda: None).step()
                current, frozen = self.store.load(job["id"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(
                    calls[1]["messages"], [{"role": "user", "content": CLARIFICATION}]
                )
                self.assertEqual(frozen, plan)
                self.assertEqual(
                    current["states"]["scene"]["state"],
                    "uncertain"
                    if isinstance(outcome, Exception)
                    else "failed"
                    if outcome == refusal
                    else "accepted",
                )
                self.assertEqual(
                    current["usage"]["input_tokens"],
                    7
                    if isinstance(outcome, Exception)
                    else 7 + outcome["prompt_tokens"],
                )
                self.assertEqual(
                    current["usage"]["output_tokens"],
                    3
                    if isinstance(outcome, Exception)
                    else 3 + outcome["completion_tokens"],
                )
                self.assertEqual(
                    Results(self.game).get(plan["requests"][0]) is not None,
                    outcome == valid,
                )
        self.assertFalse(
            refused({"text": '{"line":"I refuse. Sorry, I cannot help you."}'})
        )
        self.assertFalse(
            refused(
                {"text": refusal["text"]},
                ["I cannot translate explicit sexual content."],
            )
        )
        for text in (
            "I'm unable to translate graphic content.",
            "I can't help with sexually explicit content.",
            "I'm sorry, but I cannot assist with this request.",
        ):
            self.assertTrue(refused({"text": text}), text)

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

    def test_google_structured_batches_split_before_submission_and_keep_saved_groups(
        self,
    ):
        # Google rejects different response schemas in one Batch. Splitting
        # must retain ownership and leave matching schemas together on resume.
        from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS
        from dazedtl.translation.requests import output_schema

        rows = [
            logical_request(
                {"id": key, "sources": {"line" if index == 0 else "other": "薬"}}, {}
            )
            for index, key in enumerate(("one", "two", "three"))
        ]
        for row in rows:
            row["params"] = {
                "model": "google/fixture",
                "messages": [],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "translation",
                        "strict": True,
                        "schema": output_schema(row["sources"]),
                    },
                },
            }
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "complete": True,
            "requests": rows,
            "configuration": {
                "mode": "batch",
                "model": "google/fixture",
                "openrouterStructuredOutputs": STRUCTURED_OUTPUTS,
            },
            "batch_limits": [50, 100000],
        }
        job = self.store.create("project", plan, {"cost": 1})
        self.store.authorize(job)
        provider = BatchProvider()
        for _ in range(2):
            Runner(self.store, job["id"], provider, lambda: None).step()
        current, _ = self.store.load(job["id"])
        self.assertEqual(
            [
                [item["request"] for item in chunk["items"]]
                for chunk in current["batches"]
            ],
            [["one"], ["two", "three"]],
        )
        self.assertEqual(provider.calls, 1)

    def test_batch_refusals_retry_only_rejected_rows_in_batch_and_keep_original_usage(
        self,
    ):
        # A Batch refusal must not become a Live call, resend successful rows,
        # or reset its retry allowance when polling resumes in another worker.
        from dazedtl.translation.refusals import CLARIFICATION, POLICY

        refusal = {
            "text": "I cannot translate explicit sexual content.",
            "prompt_tokens": 3,
            "completion_tokens": 2,
        }
        valid = {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }
        for repeated in (False, True):
            job, plan = self.run_record(
                "batch",
                [request("good", str(repeated)), request("refused", str(repeated))],
            )
            plan["configuration"]["refusalRetry"] = POLICY
            write_json(self.store.folder(job["id"]) / "plan.json", plan)
            job["plan_sha256"] = digest(plan)
            self.store.save(job)

            class Provider(BatchProvider):
                def submit(self, items):
                    super().submit(items)
                    return {"id": "original" if self.calls == 1 else "clarification"}

                def collect(self, identity, mapping):
                    return (
                        {
                            key: (
                                refusal
                                if key == "refused"
                                and (identity == "original" or repeated)
                                else valid
                            )
                            for key in mapping.values()
                        },
                        [],
                        {
                            "input_tokens": 8
                            if identity == "original"
                            else 3
                            if repeated
                            else 5,
                            "output_tokens": 6
                            if identity == "original"
                            else 2
                            if repeated
                            else 4,
                        },
                    )

            provider = Provider()
            provider.ended = True
            Runner(self.store, job["id"], provider, lambda: None).step()
            current, _ = self.store.load(job["id"])
            self.assertEqual(current["status"], "waiting")
            self.assertEqual(current["states"]["good"]["state"], "accepted")
            self.assertEqual(len(provider.items), 1)
            self.assertEqual(
                provider.items[0]["params"]["messages"],
                [{"role": "user", "content": CLARIFICATION}],
            )
            Runner(self.store, job["id"], provider, lambda: None).step()
            Runner(self.store, job["id"], provider, lambda: None).step()
            current, frozen = self.store.load(job["id"])
            self.assertEqual(provider.calls, 2)
            self.assertEqual(frozen, plan)
            self.assertEqual(
                current["states"]["refused"]["state"],
                "failed" if repeated else "accepted",
            )
            self.assertEqual(current["usage"]["input_tokens"], 11 if repeated else 13)
            self.assertEqual(current["usage"]["output_tokens"], 8 if repeated else 10)
        # An upload/create timeout may still have created a remote Batch. A
        # restarted worker must retain uncertainty instead of creating another.
        job, plan = self.run_record("batch", [request("refused", "lost-batch")])
        plan["configuration"]["refusalRetry"] = POLICY
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)

        class LostProvider(Provider):
            def submit(self, items):
                result = super().submit(items)
                if self.calls == 2:
                    raise TimeoutError()
                return result

        provider = LostProvider()
        provider.ended = True
        with self.assertRaises(TimeoutError):
            Runner(self.store, job["id"], provider, lambda: None).step()
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(provider.calls, 2)
        self.assertEqual(self.store.load(job["id"])[0]["status"], "uncertain")

    def test_unknown_batch_submission_and_wrong_job_results_stay_blocked(self):
        for failure in (True, False):
            with self.subTest(submission_failure=failure):
                job, plan = self.run_record(
                    "batch", [request("failure" if failure else "wrong-job")]
                )
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

    def test_older_operation_indexes_gain_action_identity_without_rewriting_the_frozen_plan(
        self,
    ):
        plan = {
            "version": 1,
            "kind": "operation",
            "action": "backup_source",
            "source": str(self.game),
            "label": "Preserve source",
        }
        job = self.store.create("project", plan)
        del job["action"]
        self.store.save(job)
        updated = job["updated"]
        plan_path = self.store.folder(job["id"]) / "plan.json"
        before = plan_path.read_bytes()
        restored = self.store.record(job["id"])
        self.assertEqual(self.store.view(restored)["action"], "backup_source")
        self.assertEqual(restored["updated"], updated)
        self.assertEqual(plan_path.read_bytes(), before)
        del restored["action"]
        self.store.save(restored)
        write_json(plan_path, {**plan, "action": "package"})
        with self.assertRaises(ValueError):
            self.store.record(job["id"])

    def test_portable_options_import_without_replacing_legacy_or_stale_edits(self):
        legacy = self.game / ".dazedtl/len-method/project.json"
        write_json(
            legacy,
            {
                "version": 3,
                "mode": "api",
                "include_images": False,
                "instructions": "Keep this",
                "install_forge": False,
            },
        )
        original = legacy.read_bytes()
        project = ProjectWorkspace(self.game)
        value = project.read()
        self.assertEqual(value["options"]["mode"], "batch")
        saved = project.save(value["revision"], {**value["options"], "mode": "live"})
        with self.assertRaises(ValueError):
            project.save(value["revision"], value["options"])
        self.assertEqual(project.read(), saved)
        self.assertEqual(legacy.read_bytes(), original)
        # Options saved before the investigation choice existed still open,
        # and their saved runs keep the scope their quotes were bound to.
        older = {
            "mode": "batch",
            "instructions": "Keep this",
            "include_images": False,
            "include_glossary_base": True,
            "install_forge": False,
        }
        write_json(project.path, {"version": 1, "options": older})
        value = project.read()
        self.assertFalse(value["options"]["thorough_investigation"])
        bound = digest({k: v for k, v in older.items() if k != "mode"})
        self.assertEqual(scope(value["options"]), bound)
        self.assertEqual(
            scope({**value["options"], "thorough_investigation": True}), bound
        )

    def test_project_paths_and_plan_constraints_reject_unsafe_inputs(self):
        for relative in (
            "../outside.json",
            ".git/config",
            str(self.root / "outside.json"),
        ):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                project_path(self.game, relative, exists=False)
        plan = {
            "version": 2,
            "complete": True,
            "inputs": ["source.json"],
            "batches": [
                {
                    "id": "one",
                    "sources": {"line": "はい。"},
                    "kinds": {"line": "dialogue"},
                    "speakers": {"other": None},
                }
            ],
        }
        with self.assertRaises(ValueError):
            plan_input(plan)
        plan["batches"][0]["speakers"] = {"line": None}
        self.assertEqual(plan_input(plan), plan)

    def test_line_classification_requires_explicit_speakers_but_unknown_is_valid(self):
        batch = {
            "id": "scene",
            "sources": {
                "dialogue": "行った。",
                "narration": "夜が明けた。",
                "ui": "戻る",
                "other": "……",
            },
            "kinds": {
                "dialogue": "dialogue",
                "narration": "narration",
                "ui": "ui",
                "other": "unknown",
            },
            "speakers": {
                "dialogue": None,
                "narration": None,
                "ui": None,
                "other": None,
            },
        }
        plan = {
            "version": 2,
            "complete": True,
            "inputs": ["source.json"],
            "batches": [batch],
        }
        self.assertEqual(plan_input(plan), plan)
        original = {"user": "Japanese source", "request_sha256": "before"}
        row = logical_request(batch, original)
        self.assertEqual(
            original, {"user": "Japanese source", "request_sha256": "before"}
        )
        self.assertEqual(row["context"]["speakers"]["dialogue"], None)
        self.assertEqual(row["context"]["qa_notes"], {})
        job, _plan = self.run_record(requests=[row])
        self.assertEqual(self.store.view(job)["qa_requests"], [])
        for update in (
            {"speakers": None},
            {"speakers": {}},
            {"speakers": {**batch["speakers"], "dialogue": " "}},
            {"speakers": {**batch["speakers"], "ui": "Lili"}},
            {"kinds": {}},
            {"kinds": {**batch["kinds"], "ui": "guess"}},
            {"qa_notes": {"missing": "Who left?"}},
            {"qa_notes": {"dialogue": " "}},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                plan_input({**plan, "batches": [{**batch, **update}]})
        for field in ("kinds", "speakers"):
            with self.subTest(missing=field), self.assertRaises(ValueError):
                plan_input(
                    {
                        **plan,
                        "batches": [
                            {key: value for key, value in batch.items() if key != field}
                        ],
                    }
                )
        classified = logical_request(
            {**batch, "kinds": {**batch["kinds"], "other": "dialogue"}}, original
        )
        flagged = logical_request(
            {**batch, "qa_notes": {"dialogue": "Check who left."}}, original
        )
        self.assertNotEqual(row["fingerprint"], classified["fingerprint"])
        self.assertNotEqual(row["fingerprint"], flagged["fingerprint"])
