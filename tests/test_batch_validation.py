"""Consumed validation receipts settle only the requests they actually prove."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility import process_view, request_scope
from dazedtl.compatibility.batch_validation import install, recorded_outcomes
from dazedtl.compatibility.run_evidence import Evidence
from dazedtl.storage import write_json
from dazedtl.translation.files import digest

from tests.engine import point, replaced_modules


class BatchValidationTests(unittest.TestCase):
    def test_native_receipts_bind_failures_to_exact_responses_and_leave_interrupted_validation_unsettled(
        self,
    ):
        # A crash during validation or a changed reply must never inherit a
        # rejection receipt that releases its paid-work guard. Accepted chunks
        # remain accepted when a later chunk fails in the same native call,
        # and one kept but for a line failing validation names that line.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sources = ["薬", "毒", "盾"]
            queue = {
                key: {
                    "payload": json.dumps({"Line1": text}),
                    "dazedtl_file": "Items.json",
                }
                for key, text in zip(("good", "bad", "interrupted"), sources)
            }
            responses = {
                key: {"text": text}
                for key, text in zip(
                    queue, ('{"Line1":"Potion"}', "Malformed JSON", "")
                )
            }
            by_source = {entry["payload"]: key for key, entry in queue.items()}

            def native(text, filename=None):
                for key in text:
                    payload = queue[key]["payload"]
                    translator.require_batch_result(
                        payload, "English", request_context="frozen"
                    )
                    if key == "good":
                        translator.cache_translation(
                            payload, ["Potion"], "English", request_context="frozen"
                        )
                        translator.keep_original_lines(
                            payload,
                            "English",
                            request_context="frozen",
                            lines={2: "Empty translation"},
                        )
                    if key == "interrupted":
                        raise InterruptedError("Stopped while validating")
                return text

            translator = SimpleNamespace(
                translateAI=point(native),
                _batch_results=responses,
                get_cache_key=lambda payload, *_: by_source[payload],
                require_batch_result=point(
                    lambda payload, *_: responses[by_source[payload]]
                ),
                cache_translation=point(lambda *_: None),
                keep_original_lines=point(lambda *_: None),
            )
            install(Evidence(root, "batch"), translator)
            translator.translateAI(["good", "bad"], filename="Items.json")
            with self.assertRaises(InterruptedError):
                translator.translateAI(["interrupted"], filename="Items.json")
            rows = recorded_outcomes(root, queue, responses)
            self.assertEqual(
                {key: row["state"] for key, row in rows.items()},
                {"good": "validated", "bad": "rejected"},
            )
            self.assertEqual(rows["bad"]["error"]["code"], "validation_failed")
            self.assertEqual(
                rows["good"]["keptLines"],
                [{"line": "Line2", "reason": "Empty translation"}],
            )
            before = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            for field, value in (
                ("payload", '{"Line1":"別"}'),
                ("dazedtl_file", "Other.json"),
            ):
                changed = {**queue, "bad": {**queue["bad"], field: value}}
                self.assertNotIn("bad", recorded_outcomes(root, changed, responses))
            self.assertNotIn(
                "bad",
                recorded_outcomes(
                    root, queue, {**responses, "bad": {"text": "Changed reply"}}
                ),
            )
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_a_batch_result_is_paid_for_once_by_the_file_reading_it_first(self):
        # A file's cost added what each attempt read: a reply failing
        # validation, never saved for reuse, read again by a retry; the files
        # a stopped consume had saved, read again on resume; and a request two
        # files share, read by each. The ledger keeps each result once, as its
        # first read in the run counted it.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            keys = ("failing", "saved", "shared", "older")
            responses = {key: {"text": key} for key in keys}
            # A run started before results were counted read "older" then:
            # its saved receipts hold that, so reading it again pays nothing.
            older = Evidence(root, "batch")
            with older.connect() as connection:
                connection.execute(
                    "CREATE TABLE batch_validation (request_key TEXT PRIMARY KEY,"
                    " filename TEXT, source TEXT, response_hash TEXT, state TEXT)"
                )
                connection.execute(
                    "INSERT INTO batch_validation VALUES (?,?,?,?,?)",
                    (
                        "older",
                        "Items.json",
                        "{}",
                        digest(responses["older"]),
                        "received",
                    ),
                )

            def native(text, config, filename=None):
                for key in text:
                    translator.require_batch_result(json.dumps({"Line1": key}), "en")
                return text

            translator = SimpleNamespace(
                translateAI=point(native),
                _batch_results=responses,
                get_cache_key=lambda payload, *_: json.loads(payload)["Line1"],
                require_batch_result=point(
                    lambda payload, *_: responses[json.loads(payload)["Line1"]]
                ),
                batch_result_paid=lambda _result, model: {
                    "input": 10,
                    "output": 2,
                    "cost": 0.5 if model == "fixture" else 9.0,
                    "usage": {},
                },
                cache_translation=point(lambda *_: None),
            )
            install(Evidence(root, "batch"), translator)
            config = SimpleNamespace(model="fixture")
            for _attempt in range(2):
                translator.translateAI(
                    ["failing", "saved", "shared", "older"],
                    config,
                    filename="Items.json",
                )
                translator.translateAI(["shared"], config, filename="Weapons.json")
            self.assertEqual(
                process_view.paid_receipts(root),
                {"Items.json": {"input": 30, "output": 6, "cost": 1.5}},
            )

    def test_a_recovered_run_without_a_request_policy_counts_its_batch_results(self):
        # A Batch recovery imported from the original tool freezes no request
        # policy, so its workers kept no evidence ledger and, once results
        # were counted there, its files' cost and TOTAL showed only time. Its
        # workers keep the results they read in the ledger's batch_validation
        # part; a run whose attempts saved receipts without one keeps those,
        # since its results read again would count twice.
        from dazedtl.compatibility import openrouter_batch
        from dazedtl.compatibility.worker_policy import install as install_policy
        from util import extensions, translation_task

        responses = {"potion": {"text": '{"Line1":"Potion"}'}}

        def native(text, config, filename=None):
            for key in text:
                translation.require_batch_result(json.dumps({"Line1": key}), "en")
            return text

        environment = ModuleType("desktop.backend.manual_environment")
        environment.prepare = point(Mock(return_value="prepared"))
        translation = ModuleType("util.translation")
        for name in (
            "estimateCostComparison",
            "estimateBatchCost",
            "unestimatedThinking",
            "translateText",
            "buildOpenAIRequest",
            "buildClaudeRequest",
            "_translation_completion_limit",
            "_openai_batch_token_limit",
            "_load_litellm_pricing",
            "batch_usage_cost",
            "_clear_run_batch_queue",
            "batch_failure_reason",
        ):
            setattr(translation, name, point(Mock()))
        vars(translation).update(
            translateAI=point(native),
            _batch_results=responses,
            get_cache_key=lambda payload, *_: json.loads(payload)["Line1"],
            require_batch_result=point(
                lambda payload, *_: responses[json.loads(payload)["Line1"]]
            ),
            batch_result_paid=lambda _result, _model: {
                "input": 10,
                "output": 2,
                "cost": 0.5,
                "usage": {},
            },
            cache_translation=point(lambda *_: None),
            get_batch_phase=lambda: "consume",
        )
        config = SimpleNamespace(model="claude-fixture")
        with (
            TemporaryDirectory() as directory,
            replaced_modules(
                {module.__name__: module for module in (environment, translation)}
            ),
            patch.multiple(
                openrouter_batch,
                _worker_policy=None,
                _worker_root=None,
                _worker_configured=False,
            ),
            patch.dict(extensions._layers),
        ):
            install_policy()
            for earlier, expected in (
                (
                    {"Items.json": {"cost": 0.25, "seconds": 1.0}},
                    {"cost": 0.25, "seconds": 1.0},
                ),
                ({}, {"cost": 0.5, "seconds": 3.0}),
            ):
                root = Path(directory) / str(len(earlier))
                write_json(
                    root / "plan.json",
                    {
                        "mode": "batch",
                        "engine": "JSON",
                        "settings": {"model": config.model, "batchsize": 20},
                        "legacy_origin": {"root": "original", "batch_id": "b1"},
                    },
                )
                write_json(
                    root / "attempt.json",
                    {"files": ["Items.json"], "receipts": earlier},
                )
                job = {
                    "mode": "batch",
                    "files": ["Items.json"],
                    "file_metrics": earlier,
                    "file_seconds": {"Items.json": 3.0},
                }
                with self.subTest(earlier=earlier):
                    for _attempt in range(2):
                        environment.prepare(root)
                        translation.translateAI(
                            ["potion"], config, filename="Items.json"
                        )
                    self.assertEqual(
                        process_view.file_metrics(root, job), {"Items.json": expected}
                    )
                    # The run's TOTAL reads its receipts by the same rule.
                    self.assertEqual(
                        translation_task.run_receipts(
                            earlier, translation_task.paid_receipts(root), {}
                        )["Items.json"]["cost"],
                        expected["cost"],
                    )

    def choice_fixture(self, root):
        source = ["特別な品", "やめる"]

        def menu(identity, translated=False):
            command = {
                "code": 102,
                "parameters": [
                    source
                    if not translated
                    else ["Special Goods" if identity == 1 else "Rare Goods", "Cancel"]
                ],
            }
            if translated:
                command["_original"] = source
            return {"id": identity, "pages": [{"list": [command]}]}

        before = {"events": [None, menu(1), menu(2)]}
        after = {"events": [None, menu(1, True), menu(2, True)]}
        write_json(root / "files/Map001.json", before)
        write_json(root / "translated/Map001.json", after)
        plan = {
            "mode": "batch",
            "engine": "RPG Maker MV/MZ",
            "selected": ["Map001.json"],
            "files": [
                {
                    "name": "Map001.json",
                    "sha256": digest((root / "files/Map001.json").read_bytes()),
                }
            ],
        }
        write_json(root / "plan.json", plan)
        job = {
            "id": "old",
            "mode": "batch",
            "status": "complete",
            "logicalPhase": "dialogue",
            "files": ["Map001.json"],
            "completed": ["Map001.json"],
            "mismatches": {"Map001.json": "Another chunk was rejected"},
            "outputs": {
                "Map001.json": digest((root / "translated/Map001.json").read_bytes())
            },
            "plan_hash": digest((root / "plan.json").read_bytes()),
        }
        write_json(root / "job.json", job)
        payload = json.dumps(
            dict(zip(("Line1", "Line2"), source)), indent=4, ensure_ascii=False
        )
        queue = {
            key: {
                "payload": payload,
                "params": {},
                "dazedtl_file": "Map001.json",
                "dazedtl_sources": ["one", "two"],
                "request_context": json.dumps(
                    {
                        "instructions": ["Translate choices"],
                        "source_items": [key] if key != "extra" else [],
                    }
                ),
            }
            for key in ("first", "second", "extra")
        }
        responses = {
            key: {"text": json.dumps({"Line1": wording, "Line2": "Cancel"}, indent=4)}
            for key, wording in zip(
                queue, ("Special Goods", "Rare Goods", "Special Items")
            )
        }
        batch = {
            "id": "paid",
            "status": "consumed",
            "api_status": "completed",
            "custom_ids": {key: key for key in queue},
        }
        write_json(root / "log/batch_requests.json", queue)
        write_json(root / "log/batch_results.json", responses)
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json", {"status": "fetched", "batches": [batch]}
        )
        (root / "log/translation.txt").write_text(
            "".join(
                "[BATCH] Applied provider batch result\nInput:\n"
                + payload
                + "\nOutput:\n"
                + responses[key]["text"]
                + "\n"
                for key in ("first", "second")
            ),
            encoding="utf-8",
        )
        return job, plan, queue, responses, before, after

    def test_unused_choice_response_requires_every_menu_to_have_a_different_verified_response(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, _, _queue, responses, _, _ = self.choice_fixture(root)
            before = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            rows = list(request_scope.requests(root, job))
            self.assertEqual(
                [row["state"] for row in rows], ["validated", "validated", "unused"]
            )
            self.assertEqual(rows[2]["unused"], {"appliedRequests": [0, 1]})
            self.assertEqual(rows[2]["response"], responses["extra"])
            value = process_view.summary(root, job)
            self.assertEqual(
                (value["validated"], value["unused"], value["retryBlocked"]),
                (2, 1, False),
            )
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_similar_or_missing_choice_evidence_cannot_hide_an_unresolved_response(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for change in (
                "source",
                "output",
                "location",
                "menu_count",
                "context",
                "identity",
                "policy",
                "receipt",
            ):
                job, plan, queue, responses, source, output = self.choice_fixture(root)
                if change == "source":
                    write_json(root / "files/Map001.json", {"events": []})
                if change == "output":
                    write_json(root / "translated/Map001.json", {"events": []})
                if change == "location":
                    output["events"][1]["pages"][0]["list"][0]["_original"] = [
                        "Different source",
                        "やめる",
                    ]
                if change == "menu_count":
                    source["events"][2]["pages"][0]["list"] *= 2
                    output["events"][2]["pages"][0]["list"] *= 2
                    write_json(root / "files/Map001.json", source)
                    plan["files"][0]["sha256"] = digest(
                        (root / "files/Map001.json").read_bytes()
                    )
                if change in {"location", "menu_count"}:
                    write_json(root / "translated/Map001.json", output)
                    job["outputs"]["Map001.json"] = digest(
                        (root / "translated/Map001.json").read_bytes()
                    )
                if change == "context":
                    queue["extra"]["request_context"] = json.dumps(
                        {
                            "instructions": ["Translate choices"],
                            "source_items": ["Another scene"],
                        }
                    )
                if change == "identity":
                    queue["extra"]["dazedtl_sources"] = ["other", "identity"]
                if change == "policy":
                    plan["dazedtl_request_policy"] = {
                        "choiceCollection": "event-choices-once-v1"
                    }
                if change == "receipt":
                    responses["second"]["text"] = (
                        '{"Line1":"Different provider response","Line2":"Cancel"}'
                    )
                    write_json(root / "log/batch_results.json", responses)
                write_json(root / "plan.json", plan)
                job["plan_hash"] = digest((root / "plan.json").read_bytes())
                write_json(root / "job.json", job)
                write_json(root / "log/batch_requests.json", queue)
                value = process_view.summary(root, job)
                rows = process_view.request_view(root, job)["rows"]
                self.assertEqual(rows[2]["state"], "received", change)
                self.assertEqual(value["unused"], 0, change)
                self.assertTrue(value["retryBlocked"], change)

    def fixture(self, root):
        sources = ["薬", "__PROTECTED_0__毒", "未確認"]
        responses = ["Potion", "Poison", "Unverified"]
        queue = {
            key: {
                "payload": json.dumps({"Line1": source}),
                "params": {},
                "dazedtl_file": "Items.json",
                "dazedtl_sources": [key],
            }
            for key, source in zip(("good", "bad", "unknown"), sources)
        }
        results = {
            key: {"text": json.dumps({"Line1": value}, indent=4, ensure_ascii=False)}
            for key, value in zip(queue, responses)
        }
        batch = {
            "id": "paid",
            "status": "consumed",
            "api_status": "completed",
            "custom_ids": {key: key for key in queue},
        }
        plan = {"mode": "batch", "selected": ["Items.json"]}
        write_json(root / "plan.json", plan)
        write_json(root / "translated/Items.json", responses)
        job = {
            "id": "old",
            "mode": "batch",
            "status": "complete",
            "logicalPhase": "database",
            "files": ["Items.json"],
            "completed": ["Items.json"],
            "mismatches": {"Items.json": "Native validation failed"},
            "outputs": {
                "Items.json": digest((root / "translated/Items.json").read_bytes())
            },
            "plan_hash": digest((root / "plan.json").read_bytes()),
        }
        write_json(root / "job.json", job)
        write_json(root / "log/batch_requests.json", queue)
        write_json(root / "log/batch_results.json", results)
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json", {"status": "fetched", "batches": [batch]}
        )
        good = (
            "[BATCH] Applied provider batch result\nInput:\n"
            + queue["good"]["payload"]
            + "\nOutput:\n"
            + results["good"]["text"]
            + "\n"
        )
        bad = (
            "Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n"
            + queue["bad"]["payload"]
            + "\nProvider output:\n"
            + results["bad"]["text"]
            + "\n\n"
        )
        (root / "log/translation.txt").write_text(good, encoding="utf-8")
        (root / "log/mismatchHistory.txt").write_text(bad, encoding="utf-8")
        return job, queue, results

    def test_one_bad_response_does_not_block_validated_or_rejected_requests_in_the_same_file(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "old"
            job, queue, _ = self.fixture(root)
            before = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            value = process_view.summary(root, job)
            self.assertEqual(
                [row["state"] for row in process_view.request_view(root, job)["rows"]],
                ["validated", "rejected", "received"],
            )
            self.assertEqual(
                (
                    value["received"],
                    value["validated"],
                    value["rejected"],
                    value["validatedFiles"],
                ),
                (3, 1, 1, 0),
            )
            self.assertEqual(
                value["validationIssues"], [{"file": "Items.json", "rejected": 1}]
            )
            self.assertTrue(
                value["retryBlocked"]
            )  # The unverified response keeps its own guard.
            rows = list(request_scope.requests(root, job))
            self.assertIn("protected", rows[1]["error"]["message"])
            current = Path(directory) / "new"
            estimate = {**job, "id": "new", "mode": "estimate"}
            for key in ("good", "bad", "unknown"):
                write_json(current / "log/estimate_requests.json", {key: queue[key]})
                matches = request_scope.overlap(current, estimate, [(root, job)])
                self.assertEqual(bool(matches), key == "unknown", key)
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_missing_changed_conflicting_or_ambiguous_receipts_keep_the_request_protected(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for change in (
                "response",
                "output",
                "plan",
                "manifest",
                "conflict",
                "identity",
                "missing",
            ):
                job, queue, results = self.fixture(root)
                if change == "response":
                    results["bad"]["text"] = '{"Line1":"Different response"}'
                    write_json(root / "log/batch_results.json", results)
                if change == "output":
                    write_json(root / "translated/Items.json", ["Changed later"])
                if change == "plan":
                    write_json(
                        root / "plan.json",
                        {"mode": "batch", "selected": ["Other.json"]},
                    )
                if change == "manifest":
                    write_json(
                        root / "log/batch_state.json",
                        {"status": "fetched", "batches": []},
                    )
                if change == "conflict":
                    with (root / "log/translation.txt").open(
                        "a", encoding="utf-8"
                    ) as stream:
                        stream.write(
                            "[BATCH] Applied provider batch result\nInput:\n"
                            + queue["bad"]["payload"]
                            + "\nOutput:\n"
                            + results["bad"]["text"]
                            + "\n"
                        )
                if change == "identity":
                    queue["other"] = {
                        **queue["bad"],
                        "dazedtl_sources": ["different"],
                        "dazedtl_file": "Other.json",
                    }
                    write_json(root / "log/batch_requests.json", queue)
                if change == "missing":
                    (root / "log/mismatchHistory.txt").unlink()
                value = process_view.summary(root, job)
                rows = process_view.request_view(root, job)["rows"]
                self.assertEqual(rows[1]["state"], "received", change)
                self.assertTrue(value["retryBlocked"], change)
                self.assertEqual(
                    value["validationIssues"],
                    [{"file": "Items.json", "rejected": None}],
                    change,
                )

    def test_malformed_rejected_body_and_provider_array_schema_keep_their_exact_association(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, queue, results = self.fixture(root)
            results["good"]["text"] = '{"translations":["Potion"]}'
            results["bad"]["text"] = "Not JSON at all"
            write_json(root / "log/batch_results.json", results)
            (root / "log/mismatchHistory.txt").write_text(
                "Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n"
                + queue["bad"]["payload"]
                + "\nProvider output:\nNot JSON at all\n\n",
                encoding="utf-8",
            )
            rows = list(request_scope.requests(root, job))
            self.assertEqual(
                [row["state"] for row in rows], ["validated", "rejected", "received"]
            )
            self.assertEqual(rows[1]["error"]["code"], "invalid_response")
            # Provider text that resembles a record must stay inside its own
            # response; it cannot release another request's recovery guard.
            forged = (
                "Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n"
                + queue["unknown"]["payload"]
                + "\nProvider output:\n"
                + results["unknown"]["text"]
            )
            results["bad"]["text"] = "Malformed response\n" + forged
            write_json(root / "log/batch_results.json", results)
            (root / "log/mismatchHistory.txt").write_text(
                "Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n"
                + queue["bad"]["payload"]
                + "\nProvider output:\n"
                + results["bad"]["text"]
                + "\n\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [row["state"] for row in request_scope.requests(root, job)],
                ["validated", "rejected", "received"],
            )


if __name__ == "__main__":
    unittest.main()
