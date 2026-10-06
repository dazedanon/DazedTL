"""Hermetic process evidence and state response mapping, without providers."""

import json
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from dazedtl.compatibility import process_view, request_scope, state_requests
from dazedtl.compatibility.run_evidence import Evidence, keep_aligned_partial_results
from dazedtl.settings.store import Settings
from dazedtl.storage import write_json
from dazedtl.translation.files import digest

from tests.engine import point


class ProcessTests(unittest.TestCase):
    def test_live_provider_errors_retain_sanitized_bodies_without_changing_submission_guards(
        self,
    ):
        # OpenRouter's useful failure was in metadata.raw; retaining only its
        # generic message hid the cause. Wrapped SDK and text errors also lost
        # their bodies. Retention must not expose secrets or authorize a retry.
        secret = "fixture-private-value"
        raw = json.dumps(
            {
                "error": "Unsupported response schema",
                "api_key": "nested-private-value",
                "detail": "x" * 2200 + " tail detail",
                "authorization": "Bearer hidden",
            }
        )
        nested = {
            "error": {
                "message": "Provider returned error",
                "code": 400,
                "metadata": {
                    "provider_name": "Fixture host",
                    "raw": raw,
                    "echo": secret,
                    "X-API-Key": "header-private-value",
                },
            }
        }
        cases = [
            ("nested", nested, 400, False),
            ("wrapped", nested, 400, True),
            (
                "text",
                "Upstream unavailable\nBearer sk-fixture-token\n" + secret,
                502,
                False,
            ),
            ("http_body", None, 503, False),
            ("transport", None, None, False),
            ("bounded", "x" * 63_998 + secret + "tail" * 1000, 500, False),
        ]
        with TemporaryDirectory() as temporary:
            for name, body, status, wrapped in cases:
                with self.subTest(name=name):
                    root = Path(temporary) / name
                    evidence = Evidence(root, "translate")
                    failure = RuntimeError(
                        "Private exception request headers must not be saved: " + secret
                    )
                    failure.body, failure.status_code = body, status
                    if name == "http_body":
                        failure.response = SimpleNamespace(
                            text="<html>Gateway unavailable</html>"
                        )
                    params = {
                        "model": "fixture",
                        "messages": [{"role": "user", "content": '{"Line1":"薬"}'}],
                    }
                    calls = []

                    def native(user):
                        calls.append(user)
                        evidence.record(params)
                        if wrapped:
                            try:
                                raise failure
                            except RuntimeError:
                                raise ValueError(
                                    "Native wrapper also contains private request details"
                                )
                        raise failure

                    translation = SimpleNamespace(
                        queue_batch_request=point(lambda *_: "unused"),
                        _write_request_debug_log=point(lambda *_: None),
                        translateText=point(native),
                        translateAI=point(lambda text: None),
                        openai=SimpleNamespace(api_key=secret),
                    )
                    evidence.install(translation)
                    with self.assertRaises((RuntimeError, ValueError)):
                        translation.translateText('{"Line1":"薬"}')
                    payload = process_view.payload(root, 0)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(
                        payload["state"],
                        "failed" if status == 400 and not wrapped else "uncertain",
                    )
                    self.assertIsNone(payload["response"])
                    self.assertIsNone(payload["translations"])
                    self.assertIsNone(payload["usage"])
                    detail = payload["error"]
                    self.assertEqual(detail["status"], status)
                    retained = json.dumps(detail)
                    for private in (
                        secret,
                        "nested-private-value",
                        "header-private-value",
                        "sk-fixture-token",
                        "Bearer hidden",
                        "Private exception",
                        "Native wrapper",
                    ):
                        self.assertNotIn(private, retained)
                    if name in {"nested", "wrapped"}:
                        metadata = detail["body"]["error"]["metadata"]
                        self.assertEqual(metadata["provider_name"], "Fixture host")
                        self.assertEqual(
                            json.loads(metadata["raw"])["error"],
                            "Unsupported response schema",
                        )
                        self.assertTrue(
                            json.loads(metadata["raw"])["detail"].endswith(
                                "tail detail"
                            )
                        )
                    elif name == "text":
                        self.assertIn("Upstream unavailable", detail["body"])
                    elif name == "http_body":
                        self.assertEqual(
                            detail["body"], "<html>Gateway unavailable</html>"
                        )
                    elif name == "transport":
                        self.assertNotIn("body", detail)
                    elif name == "bounded":
                        self.assertTrue(detail["body"].endswith("[response truncated]"))
                        self.assertLess(len(detail["body"]), 64_100)
                    # Reading the saved failure cannot change its receipt.
                    before = evidence.path.read_bytes()
                    self.assertEqual(process_view.payload(root, 0)["error"], detail)
                    self.assertEqual(evidence.path.read_bytes(), before)

    def test_live_clarification_groups_require_exact_ownership_and_preserve_each_receipt(
        self,
    ):
        # Interleaved retries used to become unrelated selector rows. Grouping
        # must preserve both bodies/usage and never merge similar game requests.
        from dazedtl.translation.refusals import clarified

        for legacy in (False, True):
            with self.subTest(legacy=legacy), TemporaryDirectory() as temporary:
                root = Path(temporary)
                evidence = Evidence(root, "translate")
                params = {
                    "model": "fixture",
                    "messages": [{"role": "user", "content": '{"Line1":"薬"}'}],
                }
                refusal = {"text": "I cannot help with this translation."}

                def record(
                    parameters,
                    filename="Items.json",
                    sources=("owned",),
                    response=None,
                    parent=None,
                ):
                    evidence.local.filename, evidence.local.sources = (
                        filename,
                        list(sources),
                    )
                    evidence.prepared(
                        parameters,
                        "rejected" if response else "submitted",
                        clarification_of=parent,
                    )
                    identity = evidence.local.current
                    if response:
                        with evidence.connect() as connection:
                            connection.execute(
                                "UPDATE requests SET raw_response=?,usage=? WHERE id=?",
                                (
                                    json.dumps(response),
                                    json.dumps(
                                        {"prompt_tokens": 3, "completion_tokens": 1}
                                    ),
                                    identity,
                                ),
                            )
                    return identity

                original = record(params, response=refusal)
                record(params, filename="Other.json", response=refusal)
                retry = record(clarified(params), parent=None if legacy else original)
                before = evidence.path.read_bytes()
                summary = process_view.summary(
                    root, {"mode": "translate", "status": "running"}
                )
                self.assertEqual(
                    [row.get("clarificationOf") for row in summary["requests"]],
                    [None, None, 0],
                )
                self.assertTrue(summary["retryBlocked"])
                original_payload = process_view.payload(root, 0)
                retry_payload = process_view.payload(root, 2)
                self.assertEqual(
                    original_payload["responseAttempts"],
                    retry_payload["responseAttempts"],
                )
                self.assertEqual(
                    [
                        attempt["payload"]["index"]
                        for attempt in retry_payload["responseAttempts"]
                    ],
                    [0, 2],
                )
                self.assertEqual(
                    retry_payload["responseAttempts"][0]["response"], refusal
                )
                self.assertIsNone(retry_payload["responseAttempts"][1]["response"])
                self.assertEqual(evidence.path.read_bytes(), before)
                accepted = {"text": '{"Line1":"Potion"}'}
                with evidence.connect() as connection:
                    connection.execute(
                        "UPDATE requests SET state='validated',raw_response=?,response=?,usage=? WHERE id=?",
                        (
                            json.dumps(accepted),
                            '["Potion"]',
                            '{"prompt_tokens":5,"completion_tokens":2}',
                            retry,
                        ),
                    )
                attempts = process_view.payload(root, 0)["responseAttempts"]
                self.assertEqual(attempts[1]["payload"]["translations"], ["Potion"])
                self.assertEqual(
                    attempts[1]["payload"]["usage"],
                    {"input_tokens": 5, "output_tokens": 2},
                )
                self.assertEqual(
                    attempts[0]["payload"]["usage"],
                    {"input_tokens": 3, "output_tokens": 1},
                )
                self.assertEqual(attempts[0]["payload"]["exact"], params)
                self.assertEqual(attempts[1]["payload"]["exact"], clarified(params))
                # A changed owner, context, or ambiguous historical parent must
                # leave the raw request independently inspectable.
                for changed in ("file", "source", "context", "ambiguous"):
                    with (
                        self.subTest(changed=changed),
                        evidence.connect() as connection,
                    ):
                        if changed == "file":
                            connection.execute(
                                "UPDATE requests SET filename='Foreign.json' WHERE id=?",
                                (retry,),
                            )
                        if changed == "source":
                            connection.execute(
                                "UPDATE requests SET sources='[\"other\"]' WHERE id=?",
                                (retry,),
                            )
                        if changed == "context":
                            connection.execute(
                                "UPDATE requests SET params=? WHERE id=?",
                                (
                                    json.dumps(
                                        clarified({**params, "model": "different"})
                                    ),
                                    retry,
                                ),
                            )
                        if changed == "ambiguous":
                            connection.execute(
                                "UPDATE requests SET clarification_of=NULL WHERE id=?",
                                (retry,),
                            )
                            connection.execute(
                                "UPDATE requests SET filename='Items.json' WHERE id=2"
                            )
                    self.assertNotIn("responseAttempts", process_view.payload(root, 2))
                    with evidence.connect() as connection:
                        connection.execute(
                            "UPDATE requests SET filename=?,sources=?,params=? WHERE id=?",
                            (
                                "Items.json",
                                '["owned"]',
                                json.dumps(clarified(params)),
                                retry,
                            ),
                        )

    def test_completed_live_rejections_release_only_exact_returned_attempts(self):
        # Old Live rows stopped at "received" and blocked all later estimates.
        # Only a complete, unchanged run and exact unambiguous rejection record
        # can settle them; earlier response bodies must not be invented.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root, "translate")
            source = {"Line1": "薬"}
            evidence.local.filename, evidence.local.sources = "Map001.json", ["owned"]
            for prefix in ("", "Retry formatting. ", "Retry formatting. "):
                evidence.prepared(
                    {
                        "messages": [
                            {"role": "system", "content": "Frozen context"},
                            {"role": "user", "content": prefix + json.dumps(source)},
                        ]
                    },
                    "received",
                )
            plan = {"mode": "translate", "selected": ["Map001.json"]}
            write_json(root / "plan.json", plan)
            output = {"name": "薬"}
            write_json(root / "translated/Map001.json", output)
            job = {
                "id": "old",
                "mode": "translate",
                "status": "complete",
                "files": ["Map001.json"],
                "completed": ["Map001.json"],
                "logicalPhase": "dialogue",
                "outputs": {
                    "Map001.json": digest(
                        (root / "translated/Map001.json").read_bytes()
                    )
                },
                "plan_hash": digest((root / "plan.json").read_bytes()),
            }
            write_json(root / "job.json", job)
            path = root / "log/mismatchHistory.txt"
            body = json.dumps({"Line1": "I cannot translate explicit sexual content."})
            record = (
                "Validation mismatch: Map001.json\nOriginal text kept after 3 attempts.\nInput:\n"
                + json.dumps(source)
                + "\nProvider output:\n"
                + body
                + "\n\n"
            )
            path.write_text(record)
            original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            value = process_view.summary(root, job)
            self.assertEqual(
                (value["received"], value["rejected"], value["retryBlocked"]),
                (3, 3, False),
            )
            self.assertEqual(
                [process_view.payload(root, i)["response"] for i in range(3)],
                [None, None, {"text": body}],
            )
            self.assertEqual(process_view.payload(root, 2)["responseOrigin"], "log")
            self.assertEqual({p: p.read_bytes() for p in original}, original)
            current = root / "estimate"
            write_json(
                current / "log/estimate_requests.json",
                {
                    "request": {
                        "payload": json.dumps(source),
                        "params": {},
                        "dazedtl_file": "Map001.json",
                        "dazedtl_sources": ["owned"],
                    }
                },
            )
            estimate = {**job, "mode": "estimate"}
            self.assertEqual(
                request_scope.overlap(current, estimate, [(root, job)]), []
            )
            for change in (
                "output",
                "plan",
                "running",
                "missing",
                "context",
                "uncertain",
                "ambiguous",
                "forged",
            ):
                with self.subTest(change=change):
                    if change == "output":
                        write_json(root / "translated/Map001.json", {"name": "Changed"})
                    if change == "plan":
                        write_json(
                            root / "plan.json", {**plan, "selected": ["Other.json"]}
                        )
                    if change == "running":
                        write_json(root / "job.json", {**job, "status": "running"})
                    if change == "missing":
                        path.unlink()
                    if change == "context":
                        with evidence.connect() as connection:
                            connection.execute(
                                "UPDATE requests SET params=? WHERE id=1",
                                (
                                    json.dumps(
                                        {
                                            "messages": [
                                                {
                                                    "role": "system",
                                                    "content": "Other scene",
                                                },
                                                {
                                                    "role": "user",
                                                    "content": json.dumps(source),
                                                },
                                            ]
                                        }
                                    ),
                                ),
                            )
                    if change == "uncertain":
                        with evidence.connect() as connection:
                            connection.execute(
                                "UPDATE requests SET state='submitted' WHERE id=1"
                            )
                    if change == "ambiguous":
                        path.write_text(record + record)
                    if change == "forged":
                        path.write_text("Malformed provider output\n" + record)
                    self.assertTrue(process_view.summary(root, job)["retryBlocked"])
                    self.assertTrue(
                        request_scope.overlap(current, estimate, [(root, job)])
                    )
                    for p, data in original.items():
                        p.write_bytes(data)

    def test_completed_batch_waits_for_download_without_losing_submission_protection(
        self,
    ):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = {
                "payload": '{"Line1":"薬"}',
                "params": {},
                "dazedtl_file": "Items.json",
            }
            write_json(root / "log/batch_requests.json", {"one": entry, "two": entry})
            first = {
                "id": "first",
                "custom_ids": {"first-request": "one"},
                "api_status": "completed",
                "request_counts": {
                    "processing": 0,
                    "succeeded": 1,
                    "errored": 0,
                    "canceled": 0,
                    "expired": 0,
                },
            }
            second = {
                "id": "second",
                "custom_ids": {"second-request": "two"},
                "api_status": "validating",
            }
            state = {"status": "partially_submitted", "batches": [first, second]}
            write_json(root / "log/batch_history.json", {"batches": [first, second]})
            write_json(root / "log/batch_state.json", state)
            job = {"mode": "batch", "status": "running"}
            value = process_view.summary(root, job)
            self.assertEqual(
                [row["state"] for row in value["requests"]], ["submitted", "submitted"]
            )
            self.assertEqual(
                [batch["requestIndices"] for batch in value["batches"]], [[0], [1]]
            )
            # The inspector may identify finished rows without pretending a
            # response was downloaded or authorizing another paid submission.
            self.assertEqual(
                [row.get("providerFinished", False) for row in value["requests"]],
                [True, False],
            )
            self.assertEqual(
                [row["preview"] for row in value["requests"]], ["薬", "薬"]
            )
            self.assertEqual((value["uncertain"], value["received"]), (0, 0))
            self.assertTrue(value["retryBlocked"])
            # Known completion does not excuse missing downloaded responses,
            # broken mappings, incomplete counts or a conflicting submission.
            for change in ("fetched", "mapping", "counts", "duplicate"):
                history, manifest = deepcopy([first, second]), deepcopy(state)
                if change == "fetched":
                    manifest["status"] = "fetched"
                if change == "mapping":
                    manifest["batches"][0]["custom_ids"] = {"other-request": "one"}
                if change == "counts":
                    history[0]["request_counts"].pop("succeeded")
                if change == "duplicate":
                    history.append({**first, "id": "unmatched"})
                write_json(root / "log/batch_history.json", {"batches": history})
                write_json(root / "log/batch_state.json", manifest)
                value = process_view.summary(root, job)
                self.assertEqual(value["requests"][0]["state"], "uncertain", change)
                self.assertNotIn("providerFinished", value["requests"][0], change)
                self.assertTrue(value["retryBlocked"], change)
            # Aggregate partial success cannot identify which source finished;
            # a new clarification must not inherit the original's completion.
            write_json(root / "log/batch_history.json", {"batches": [first, second]})
            write_json(root / "log/batch_state.json", state)
            clarification = [
                {
                    "batches": [
                        {"id": "retry", "state": "submitted", "items": [{"key": "one"}]}
                    ]
                }
            ]
            with patch(
                "dazedtl.compatibility.batch_refusals.records",
                return_value=clarification,
            ):
                rows = list(request_scope.requests(root, job))
            self.assertFalse(rows[0]["providerFinished"])
            partial = {
                **first,
                "custom_ids": {"first-request": "one", "second-request": "two"},
                "request_counts": {**first["request_counts"], "errored": 1},
            }
            write_json(root / "log/batch_history.json", {"batches": [partial]})
            write_json(
                root / "log/batch_state.json",
                {"status": "submitted", "batches": [partial]},
            )
            self.assertFalse(
                any(
                    row.get("providerFinished")
                    for row in process_view.summary(root, job)["requests"]
                )
            )
            # A long source stays bounded on the observer, not the full prompt.
            self.assertEqual(
                len(
                    process_view.source_preview(
                        {"Line1": "a" * 5000, "Line2": "b" * 5000}
                    )
                ),
                161,
            )

    def test_source_locations_accept_native_event_originals_without_indexing_metadata(
        self,
    ):
        # Estimation previously crashed on valid scalar/list event originals
        # before preparing any request. Database field originals still apply.
        data = {
            "events": [
                None,
                {
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 101,
                                    "parameters": ["", 0, 0, 2, "Name"],
                                    "_original": "名前",
                                },
                                {
                                    "code": 401,
                                    "parameters": ["残りの台詞"],
                                    "_original": "保存済みの台詞",
                                },
                                {
                                    "code": 102,
                                    "parameters": [["選択肢", "Quit"], 0],
                                    "_original": ["元の選択肢", "やめる"],
                                },
                                {
                                    "code": 401,
                                    "parameters": ["別の台詞"],
                                    "_original": None,
                                },
                            ]
                        }
                    ]
                },
            ],
            "item": {"name": "Potion", "_original": {"name": "薬"}},
        }
        before = json.dumps(data, ensure_ascii=False)
        locations = request_scope.source_locations(data)
        self.assertEqual(
            locations["残りの台詞"], ["/events/1/pages/0/list/1/parameters/0"]
        )
        self.assertEqual(
            locations["選択肢"], ["/events/1/pages/0/list/2/parameters/0/0"]
        )
        self.assertEqual(
            locations["別の台詞"], ["/events/1/pages/0/list/3/parameters/0"]
        )
        self.assertEqual(locations["薬"], ["/item/name"])
        for metadata in ("名前", "保存済みの台詞", "元の選択肢", "やめる", "Potion"):
            self.assertNotIn(metadata, locations)
        self.assertEqual(json.dumps(data, ensure_ascii=False), before)

    def test_continuation_translates_new_text_inside_a_previously_translated_file_only_once(
        self,
    ):
        from dazedtl.translation.guided_runs import GuidedRuns

        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "current"
            data = [{"name": "Potion", "_original": {"name": "薬"}}, {"name": "毒"}]
            write_json(root / "files/Items.json", data)
            key = request_scope.identities(
                "Items.json", "database", ["薬"], request_scope.source_locations(data)
            )[0]
            inputs = {
                "phase": "database",
                "files": ["Items.json", "States.json"],
                "source": {
                    "Items.json": {"identity": "items-source"},
                    "States.json": {"identity": "states-source"},
                },
            }
            record = {
                **inputs,
                "files": ["Items.json"],
                "source": {"Items.json": inputs["source"]["Items.json"]},
            }
            jobs = {
                "older": {
                    "created": "2026-10-04T18:00:00Z",
                    "updated": "2026-10-04T23:00:00Z",
                },
                "newer": {
                    "created": "2026-10-04T20:00:00Z",
                    "updated": "2026-10-04T20:00:00Z",
                },
            }
            folder = lambda identity: Path(temporary) / identity
            records = {"newer": record, "older": record}
            runs = GuidedRuns(
                SimpleNamespace(
                    backend=SimpleNamespace(
                        manual=SimpleNamespace(jobs=jobs, folder=folder),
                        saved_run_configuration=lambda _: {
                            "workflow": {"id": "project"}
                        },
                    )
                )
            )
            runs.records = lambda _: records
            history = []
            for identity, wording in [("older", "Medicine"), ("newer", "Potion")]:
                saved = Evidence(folder(identity), "translate")
                with saved.connect() as connection:
                    connection.execute(
                        "INSERT INTO validated_items VALUES (?,?,?)",
                        (key, "薬", json.dumps(wording)),
                    )
                    if identity == "newer":
                        connection.execute(
                            "INSERT INTO validated_provenance VALUES (?,?)",
                            (key, "Items.json"),
                        )
                history.append(saved.path)
            before = {
                path: path.read_bytes()
                for path in [*history, root / "files/Items.json"]
            }
            continuation = runs.continuation("project", {"id": "project"}, inputs)
            self.assertEqual(continuation[key], {"source": "薬", "response": "Potion"})
            records = dict(reversed(list(records.items())))
            self.assertEqual(
                runs.continuation("project", {"id": "project"}, inputs), continuation
            )
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            plan = {
                "workflow": {"phase": "database"},
                "dazedtl_continuation": continuation,
            }
            sent = []

            def native_ai(text, history, filename):
                sent.append(text)
                return [
                    [{"薬": "Potion", "毒": "Poison"}[value] for value in text],
                    [3, 4],
                ]

            def translator():
                return SimpleNamespace(
                    queue_batch_request=point(lambda *_: "unused"),
                    BATCH_LOCK=threading.RLock(),
                    _batch_queue_pending={},
                    _write_request_debug_log=point(lambda *_: None),
                    translateText=point(lambda *_: None),
                    translateAI=point(native_ai),
                    _thread_local=threading.local(),
                    last_translation_had_mismatch=lambda: False,
                    get_batch_phase=lambda: None,
                )

            first = translator()
            Evidence(root, "translate", plan).install(first)
            self.assertEqual(
                first.translateAI(["薬", "毒"], [], "Items.json")[0],
                ["Potion", "Poison"],
            )
            self.assertEqual(sent, [["毒"]])
            again = translator()
            Evidence(root, "translate", plan).install(again)
            self.assertEqual(
                again.translateAI(["薬", "毒"], [], "Items.json")[0],
                ["Potion", "Poison"],
            )
            self.assertEqual(sent, [["毒"]])
            # An estimate needs no request for reused text, but the file still
            # has text to write and must not look finished. Translated names
            # the grouped map-name pass sends unfiltered need nothing.
            estimate_root = Path(temporary) / "estimate"
            write_json(estimate_root / "files/Items.json", data)
            self.assertIsNone(process_view.translatable_files(root))
            estimated = translator()
            estimated.translateAI = point(
                lambda text, history, config, filename: (
                    sent.append(text) or [text, [0, 0]]
                )
            )
            Evidence(estimate_root, "estimate", plan).install(estimated)
            config = SimpleNamespace(langRegex="[぀-ヿ一-鿿]")
            estimated.translateAI(["薬"], [], config, "Items.json")
            estimated.translateAI(["Village"], [], config, "Map001.json")
            self.assertEqual(sent, [["毒"], ["Village"]])
            self.assertEqual(
                process_view.translatable_files(estimate_root), {"Items.json"}
            )
            # A failed segment before a reusable span must not discard earlier
            # successes, omit its usage, or prevent the later segment running.
            retry_root = Path(temporary) / "mixed"
            values = ["失敗", "既存", "成功"]
            write_json(retry_root / "files/Items.json", values)
            keys = request_scope.identities(
                "Items.json", "database", values, request_scope.source_locations(values)
            )
            mixed_plan = {
                "workflow": {"phase": "database"},
                "dazedtl_continuation": {
                    keys[1]: {"source": values[1], "response": "Reused"}
                },
            }
            mixed = translator()
            calls = []

            def mixed_ai(text, history, filename):
                calls.append(text)
                mixed._thread_local.last_translation_had_mismatch = text == [values[0]]
                return [text if text == [values[0]] else ["Translated"], [3, 4]]

            mixed.translateAI = point(mixed_ai)
            mixed.last_translation_had_mismatch = lambda: getattr(
                mixed._thread_local, "last_translation_had_mismatch", False
            )
            Evidence(retry_root, "translate", mixed_plan).install(mixed)
            self.assertEqual(
                mixed.translateAI(values, [], "Items.json"),
                [[values[0], "Reused", "Translated"], [6, 8]],
            )
            self.assertEqual(calls, [[values[0]], [values[2]]])
            self.assertTrue(mixed.last_translation_had_mismatch())
            self.assertEqual(
                Evidence(retry_root, "translate", mixed_plan).reused[keys[2]][
                    "response"
                ],
                "Translated",
            )
            # The native comment handler may consume aligned mixed results;
            # malformed lengths and name-preflight failures keep their guard.
            module = SimpleNamespace(
                THREAD_CTX=SimpleNamespace(), MISMATCH=["Items.json"]
            )

            def native_module(text):
                module.THREAD_CTX.last_translation_had_mismatch = True
                return [[text[0], "Translated"], [3, 4]]

            module.translateAI = point(native_module)
            keep_aligned_partial_results(module)
            self.assertEqual(
                module.translateAI(values[:2]), [[values[0], "Translated"], [3, 4]]
            )
            self.assertFalse(module.THREAD_CTX.last_translation_had_mismatch)
            self.assertEqual(module.MISMATCH, ["Items.json"])
            module.translateAI(values)
            self.assertTrue(module.THREAD_CTX.last_translation_had_mismatch)
            module.THREAD_CTX.in_speaker = True
            module.translateAI(values[:2])
            self.assertTrue(module.THREAD_CTX.last_translation_had_mismatch)

    def test_finished_batch_receipts_are_settled_only_with_verified_unmodified_output(
        self,
    ):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "old"
            current = Path(temporary) / "new"
            plan = {"mode": "batch", "selected": ["Items.json"]}
            write_json(root / "plan.json", plan)
            output = [{"name": "Potion"}]
            write_json(root / "translated/Items.json", output)
            job = {
                "id": "old",
                "mode": "batch",
                "status": "complete",
                "logicalPhase": "database",
                "files": ["Items.json"],
                "completed": ["Items.json"],
                "outputs": {
                    "Items.json": digest((root / "translated/Items.json").read_bytes())
                },
                "plan_hash": digest((root / "plan.json").read_bytes()),
            }
            write_json(root / "job.json", job)
            entry = {
                "payload": '{"Line1":"薬"}',
                "params": {},
                "dazedtl_sources": ["item"],
                "dazedtl_file": "Items.json",
            }
            write_json(root / "log/batch_requests.json", {"key": entry})
            write_json(
                root / "log/batch_results.json", {"key": {"text": '{"Line1":"Potion"}'}}
            )
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "paid",
                            "status": "consumed",
                            "api_status": "completed",
                            "custom_ids": {"one": "key"},
                        }
                    ]
                },
            )
            write_json(current / "log/estimate_requests.json", {"key": entry})
            new = {**job, "id": "new", "mode": "estimate"}
            self.assertEqual(
                next(iter(request_scope.requests(root, job)))["state"], "saved"
            )
            self.assertEqual(request_scope.overlap(current, new, [(root, job)]), [])
            write_json(root / "translated/Items.json", [{"name": "Unverified edit"}])
            self.assertEqual(
                next(iter(request_scope.requests(root, job)))["state"], "received"
            )
            self.assertTrue(request_scope.overlap(current, new, [(root, job)]))
            write_json(root / "translated/Items.json", output)
            write_json(root / "job.json", {**job, "mismatches": {"Items.json": 1}})
            self.assertTrue(request_scope.overlap(current, new, [(root, job)]))
            # Expanding file scope must not match identical text from a
            # different known file, or resurrect explicitly retired sources.
            write_json(
                current / "log/estimate_requests.json",
                {
                    "other": {
                        **entry,
                        "dazedtl_sources": [],
                        "dazedtl_file": "States.json",
                    }
                },
            )
            scope = ["Items.json", "States.json"]
            self.assertEqual(
                request_scope.overlap(
                    current, {**new, "files": scope}, [(root, {**job, "files": scope})]
                ),
                [],
            )
            write_json(current / "log/estimate_requests.json", {"key": entry})
            self.assertEqual(
                request_scope.overlap(
                    current, new, [(root, {**job, "retiredFiles": ["Items.json"]})]
                ),
                [],
            )

    def test_batch_skipped_file_labels_require_complete_provenance_and_preserve_deduplicated_callers(
        self,
    ):
        from dazedtl.settings.preferences import GENERATION_PARAMETERS

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = ["Actors.json", "Classes.json", "Armors.json"]
            plan = {
                "mode": "batch",
                "selected": files,
                "dazedtl_request_policy": {
                    "generationParameters": GENERATION_PARAMETERS
                },
            }
            write_json(root / "plan.json", plan)
            evidence = Evidence(root, "batch")
            # Two files may share one provider request; neither was skipped.
            for name in files[:2]:
                evidence.local.filename, evidence.local.sources = (
                    name,
                    ["source-" + name],
                )
                evidence.prepared({"messages": []})
            items = [{"file": "Classes.json"}]
            job = {"mode": "batch", "phase": "poll_status", "files": files}
            self.assertEqual(
                process_view.no_request_files(root, job, items), ["Armors.json"]
            )
            self.assertEqual(
                process_view.no_request_files(root, {**job, "phase": "collect"}, items),
                [],
            )
            write_json(root / "log/batch_state.json", {"status": "submitted"})
            self.assertEqual(
                process_view.no_request_files(root, {**job, "phase": "failed"}, items),
                ["Armors.json"],
            )
            self.assertEqual(
                process_view.no_request_files(
                    root, {**job, "mode": "translate"}, items
                ),
                [],
            )
            self.assertEqual(
                process_view.no_request_files(
                    root, {**job, "errors": {"Armors.json": "Parse failed"}}, items
                ),
                [],
            )
            self.assertEqual(
                process_view.no_request_files(root, job, [{"file": None}]), []
            )
            write_json(root / "plan.json", {**plan, "dazedtl_request_policy": {}})
            self.assertEqual(process_view.no_request_files(root, job, items), [])
            write_json(root / "plan.json", plan)
            evidence.local.filename = None
            evidence.prepared({"messages": []})
            self.assertEqual(process_view.no_request_files(root, job, items), [])

    def test_checkpoint_resume_reads_partial_json_without_mutating_frozen_inputs(self):
        from dazedtl.compatibility import checkpoints
        from dazedtl.storage import write_bytes

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = [{"name": "薬", "description": "説明"}]
            partial = [
                {"name": "Potion", "description": "説明", "_original": {"name": "薬"}}
            ]
            plan = {"mode": "translate", "files": [{"name": "Items.json"}]}
            write_json(root / "plan.json", plan)
            write_json(root / "files/Items.json", source)
            original = (root / "files/Items.json").read_bytes()
            module = SimpleNamespace(
                saveProgress=point(
                    lambda data, name, **_: (
                        write_json(root / "translated" / name, data),
                        True,
                    )[1]
                ),
                open=point(open),
            )
            checkpoints.install(module, root, plan)
            module.saveProgress(partial, "Items.json")
            self.assertIn("Items.json", checkpoints.outputs(root, plan))
            # A fresh worker sees the checkpoint even if the previous process died.
            replacement = SimpleNamespace(
                saveProgress=module.saveProgress, open=point(open)
            )
            checkpoints.install(replacement, root, plan)
            with replacement.open(
                root / "files/Items.json", encoding="utf-8"
            ) as stream:
                self.assertEqual(json.load(stream), partial)
            self.assertEqual((root / "files/Items.json").read_bytes(), original)
            # Never bless bytes written after the last durable checkpoint receipt.
            write_bytes(root / "translated/Items.json", b'{"different":"unreceipted"}')
            self.assertEqual(checkpoints.outputs(root, plan), {})
            # Batch consumption keeps its frozen request grouping and uses receipts.
            plan["mode"] = "batch"
            write_json(root / "plan.json", plan)
            (root / checkpoints.INDEX).unlink()
            batch = SimpleNamespace(
                saveProgress=point(
                    lambda data, name, **_: (
                        write_json(root / "translated" / name, data),
                        True,
                    )[1]
                ),
                open=point(open),
            )
            checkpoints.install(batch, root, plan)
            batch.saveProgress(partial, "Items.json")
            with batch.open(root / "files/Items.json", encoding="utf-8") as stream:
                self.assertEqual(json.load(stream), source)
            write_json(
                root / "plan.json", {**plan, "files": [{"name": "Foreign.json"}]}
            )
            with self.assertRaises(ValueError):
                checkpoints.outputs(root, plan)

    def test_consumed_batch_recovers_only_exact_validated_translations_without_inventing_raw_responses(
        self,
    ):
        # Native cleanup used to leave successful requests looking merely
        # prepared. Local accepted values are usable only with exact identities.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root, "batch")
            params = {"messages": [{"role": "user", "content": '{"Line1":"薬"}'}]}
            evidence.local.sources = ["owned-source"]
            evidence.local.filename = "Items.json"
            evidence.prepared(params)
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "paid",
                            "status": "consumed",
                            "api_status": "completed",
                            "custom_ids": {"one": "key"},
                        }
                    ]
                },
            )
            with evidence.connect() as connection:
                connection.execute(
                    "INSERT INTO validated_items VALUES (?,?,?)",
                    ("owned-source", "薬", '"Potion"'),
                )
            before = evidence.path.read_bytes()
            payload = process_view.payload(root, 0)
            self.assertEqual(
                (payload["state"], payload["response"], payload["responseOrigin"]),
                ("validated", ["Potion"], "validated"),
            )
            self.assertEqual(
                process_view.summary(root, {"mode": "batch"})["received"], 1
            )
            self.assertEqual(evidence.path.read_bytes(), before)
            with evidence.connect() as connection:
                connection.execute(
                    "UPDATE validated_items SET source='Different source'"
                )
            payload = process_view.payload(root, 0)
            self.assertIsNone(payload["response"])
            self.assertEqual(payload["state"], "uncertain")

    def test_batch_cleanup_preserves_exact_requests_responses_and_submission_mapping(
        self,
    ):
        # Normal fetch and consume clear native scratch files; the inspector
        # and overlap checks must retain the original paid request evidence.
        from dazedtl.compatibility import batch_evidence

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = {
                "payload": '{"Line1":"薬"}',
                "params": {"messages": []},
                "provider": "openai",
            }
            requests, results = (
                {"key": entry},
                {"key": {"text": '{"Line1":"Potion"}', "prompt_tokens": 12}},
            )
            queue_file, result_file, state_file = (
                root / "log" / name
                for name in (
                    "batch_requests.json",
                    "batch_results.json",
                    "batch_state.json",
                )
            )
            state = {
                "status": "submitted",
                "batches": [{"id": "paid", "custom_ids": {"one": "key"}}],
            }
            for path, value in (
                (queue_file, requests),
                (result_file, results),
                (state_file, state),
            ):
                write_json(path, value)
            read = lambda path, **_: (
                json.loads(path.read_bytes()) if path.exists() else {}
            )
            native = SimpleNamespace(
                BATCH_QUEUE_FILE=queue_file,
                BATCH_RESULTS_FILE=result_file,
                BATCH_STATE_FILE=state_file,
                _read_batch_queue=lambda **_: read(queue_file),
                _read_batch_file=read,
                _clear_run_batch_queue=point(
                    lambda **_: queue_file.unlink(missing_ok=True)
                ),
            )
            batch_evidence.install(native, root, {"mode": "translate"})
            with patch.object(batch_evidence, "preserve") as preserve:
                native._clear_run_batch_queue(queue_file=queue_file)
            preserve.assert_not_called()
            write_json(queue_file, requests)
            batch_evidence.install(native, root, {"mode": "batch"})
            # Unapproved preparation creates no durable archive.
            native._clear_run_batch_queue(queue_file=queue_file)
            self.assertFalse((root / "log" / batch_evidence.ARCHIVE).exists())
            write_json(queue_file, requests)
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            **state["batches"][0],
                            "status": "fetched",
                            "api_status": "completed",
                        }
                    ]
                },
            )
            native._clear_run_batch_queue(queue_file=queue_file)
            write_json(state_file, {"status": "fetched", "batches": []})
            native._clear_run_batch_queue(queue_file=queue_file)
            result_file.unlink()
            state_file.unlink()
            with patch.dict(
                "sys.modules",
                {
                    "util.batch_providers": SimpleNamespace(
                        _openai_batch_body=lambda _p, params: params
                    )
                },
            ):
                payload = process_view.payload(root, 0)
            self.assertEqual(
                (payload["state"], payload["response"], payload["exact"]["custom_id"]),
                ("received", results["key"], "one"),
            )
            self.assertEqual(process_view.queue(root), requests)
            self.assertTrue(
                process_view.summary(root, {"mode": "batch"})["resultsCollected"]
            )
            with self.assertRaisesRegex(ValueError, "conflicts"):
                batch_evidence.preserve(
                    root, {"key": {**entry, "payload": '{"Line1":"Changed"}'}}, {}, {}
                )

    def test_fresh_start_requires_complete_terminal_rejection_receipts(self):
        # A failed worker is not proof of no provider work. Protect missing,
        # pending, partial-success, conflicting, and duplicate submission evidence.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {"mode": "batch"}
            write_json(root / "plan.json", plan)
            job = {
                "mode": "batch",
                "status": "failed",
                "plan_hash": digest((root / "plan.json").read_bytes()),
            }
            queue = {
                "one": {
                    "payload": '{"Line1":"防御"}',
                    "params": {},
                    "provider": "openai",
                },
                "two": {
                    "payload": '{"Line1":"毒"}',
                    "params": {},
                    "provider": "openai",
                },
            }
            batch = {
                "id": "batch-generated",
                "provider": "openai",
                "api_status": "completed",
                "custom_ids": {"req-1": "one"},
                "request_counts": {
                    "processing": 0,
                    "succeeded": 0,
                    "errored": 1,
                    "canceled": 0,
                    "expired": 0,
                },
            }
            state = {
                "status": "partially_submitted",
                "batches": [{"id": batch["id"], "custom_ids": batch["custom_ids"]}],
            }
            write_json(root / "log/batch_requests.json", queue)
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            write_json(root / "log/batch_state.json", state)
            baseline = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            proof = process_view.fresh_start(root, job)
            self.assertTrue(proof["eligible"])
            self.assertEqual((proof["failed"], proof["remaining"]), (1, 1))
            changes = [
                lambda b, s, j: b.update(api_status="in_progress"),
                lambda b, s, j: b.update(provider="unknown"),
                lambda b, s, j: b["request_counts"].update(succeeded=1),
                lambda b, s, j: b["request_counts"].update(processing=1),
                lambda b, s, j: b["request_counts"].pop("succeeded"),
                lambda b, s, j: b["request_counts"].update(errored=True),
                lambda b, s, j: b.update(output_file_id="file-success"),
                lambda b, s, j: s.update(status="submission_uncertain"),
                lambda b, s, j: s["batches"].append(
                    {"id": "unknown", "custom_ids": {"unknown": "two"}}
                ),
                lambda b, s, j: s["batches"][0].update(custom_ids={"req-1": "two"}),
                lambda b, s, j: j.update(status="interrupted"),
                lambda b, s, j: j.update(status="running"),
                lambda b, s, j: j.update(completed=["States.json"]),
                lambda b, s, j: j.update(outputs={"States.json": {}}),
                lambda b, s, j: j.update(approval={"token": "pending"}),
            ]
            for change in changes:
                b, s, j = deepcopy(batch), deepcopy(state), deepcopy(job)
                change(b, s, j)
                write_json(root / "log/batch_history.json", {"batches": [b]})
                write_json(root / "log/batch_state.json", s)
                self.assertFalse(process_view.fresh_start(root, j)["eligible"], change)
            for path, raw in baseline.items():
                path.write_bytes(raw)
            write_json(
                root / "log/batch_results.json", {"one": {"text": "Paid result"}}
            )
            self.assertFalse(process_view.fresh_start(root, job)["eligible"])
            (root / "log/batch_results.json").unlink()
            duplicate = deepcopy(batch)
            duplicate["id"] = "batch-duplicate"
            write_json(root / "log/batch_history.json", {"batches": [batch, duplicate]})
            write_json(
                root / "log/batch_state.json",
                {
                    **state,
                    "batches": [
                        *state["batches"],
                        {"id": duplicate["id"], "custom_ids": duplicate["custom_ids"]},
                    ],
                },
            )
            self.assertFalse(process_view.fresh_start(root, job)["eligible"])
            for path, raw in baseline.items():
                path.write_bytes(raw)
            self.assertEqual(process_view.fresh_start(root, job), proof)
            self.assertEqual({path: path.read_bytes() for path in baseline}, baseline)

    def test_source_overlap_survives_new_chunking_and_protects_approval_send_gap(self):
        # Protect duplicated payment when a second review arrives before the
        # first approved Batch has written its remote manifest. Model/chunk IDs
        # do not identify the logical source, and disjoint fields stay usable.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new = root / "old", root / "new"
            a, b = request_scope.identities("Items.json", "database", ["薬", "毒"])
            row = lambda text, keys: {
                "payload": json.dumps({"Line1": text}),
                "params": {},
                "provider": "openai",
                "dazedtl_sources": keys,
                "dazedtl_file": "Items.json",
            }
            write_json(old / "log/batch_requests.json", {"old-hash": row("薬", [a])})
            write_json(old / "log/batch_state.json", {"status": "queued"})
            write_json(
                new / "log/estimate_requests.json",
                {"different-model-hash": row("薬", [a])},
            )
            job = {
                "id": "old",
                "mode": "batch",
                "files": ["Items.json"],
                "logicalPhase": "database",
                "status": "running",
            }
            estimate = {**job, "id": "new", "mode": "estimate"}
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))
            job["dazedtl_submission_intent"] = True
            self.assertEqual(len(request_scope.overlap(new, estimate, [(old, job)])), 1)
            job.update(keptForHistory=True, created="2020-01-01", status="interrupted")
            self.assertEqual(len(request_scope.overlap(new, estimate, [(old, job)])), 1)
            write_json(
                new / "log/estimate_requests.json", {"different-group": row("毒", [b])}
            )
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))
            job["logicalPhase"] = "dialogue"
            write_json(
                new / "log/estimate_requests.json", {"different-group": row("薬", [a])}
            )
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))

    def test_state_coalescing_preserves_fields_controls_originals_and_saved_consume_mapping(
        self,
    ):
        # Protect the 45 calls / 112 fields -> 8 compatible calls case, including
        # exact writer association, glossary separation and no duplicate consume.
        counts = [1] * 15 + [3] * 20 + [5] * 3 + [2] + [3] * 4 + [4] * 2
        fields = ["name", "description", "message1", "message2", "message3", "message4"]
        data: list[Any] = [None] + [
            {
                "id": i + 1,
                **{
                    field: f"項目{i + 1}_{field}" + (f"語彙{i}" if i >= 39 else "")
                    for field in fields[:count]
                },
            }
            for i, count in enumerate(counts)
        ]
        data[1]["name"] += r"\C[2]"
        emitted = []
        malformed = [False]
        module = SimpleNamespace(
            TRANSLATION_CONFIG=SimpleNamespace(langRegex="項目|他")
        )
        module._entry_field_needs_translation = lambda item, field: str(
            item.get(field, "")
        ).startswith("項目")

        def translate(text, history, *extra):
            emitted.append((deepcopy(text), history, extra))
            values = ["EN:" + value for value in text]
            return [values[:-1] if malformed[0] else values, [len(text), len(text) * 2]]

        module.translateAI = point(translate)

        def search(item, _bar):
            keys = [
                key
                for key in fields
                if item.get(key) and module._entry_field_needs_translation(item, key)
            ]
            if not keys:
                return [0, 0]
            source = [item.get("_original", {}).get(key, item[key]) for key in keys]
            output, tokens = module.translateAI(source, "State instructions", False)
            item.setdefault("_original", {}).update(zip(keys, source))
            item.update(zip(keys, output))
            return tokens

        module.searchSS = search

        def parse(values, _filename):
            for item in values:
                if item:
                    module.searchSS(item, None)
            return values

        module.parseSS = point(parse)

        def context(_config, payload, _format, _history):
            values = list(json.loads(payload).values())
            glossary = next(
                (value.split("語彙")[1] for value in values if "語彙" in value), ""
            )
            return "Frozen game context", glossary, "", payload

        translation = SimpleNamespace(
            protect_script_codes=lambda value: (value, {}), createContextParts=context
        )
        with TemporaryDirectory() as temporary:
            state_requests.configure(module, translation, temporary, 50)
            actual = module.parseSS(deepcopy(data), "States.json")
            self.assertEqual(len(emitted), 8)
            self.assertEqual(sum(len(row[0]) for row in emitted), 112)
            self.assertTrue(all(len(row[0]) <= 50 for row in emitted))
            self.assertIn('"stateId": 1', emitted[0][1])
            self.assertIn('"field": "name"', emitted[0][1])
            for before, after in zip(data[1:], actual[1:]):
                self.assertEqual(after["id"], before["id"])
                for field in before.keys() - {"id"}:
                    self.assertEqual(after[field], "EN:" + before[field])
                    self.assertEqual(after["_original"][field], before[field])
            saved = next((Path(temporary) / "log").glob("dazedtl-state-groups-*.json"))
            frozen = saved.read_bytes()
            # A growing consume-time glossary must not regroup paid requests.
            translation.createContextParts = Mock(
                side_effect=AssertionError("Must use saved mapping")
            )
            emitted.clear()
            self.assertEqual(module.parseSS(deepcopy(data), "States.json"), actual)
            self.assertEqual(len(emitted), 8)
            self.assertEqual(saved.read_bytes(), frozen)
            partial = deepcopy(data)
            partial[1:21] = deepcopy(actual[1:21])
            emitted.clear()
            self.assertEqual(module.parseSS(partial, "States.json"), actual)
            self.assertEqual(len(emitted), 8)
            malformed[0] = True
            untouched = deepcopy(data)
            with self.assertRaisesRegex(ValueError, "response IDs"):
                module.parseSS(untouched, "States.json")
            self.assertEqual(untouched, data)
            malformed[0] = False
            emitted.clear()
            self.assertEqual(
                module.translateAI(["他"], "Other database field")[0], ["EN:他"]
            )
            self.assertEqual(len(emitted), 1)
            changed = deepcopy(data)
            changed[1]["name"] += "変更"
            with self.assertRaisesRegex(ValueError, "frozen source"):
                module.parseSS(changed, "States.json")
            self.assertEqual(len(emitted), 1)
            state_requests.restore(module)
            # Native per-state requests resume, without grouped field context.
            emitted.clear()
            module.parseSS(changed, "States.json")
            self.assertTrue(emitted)
            self.assertEqual({row[1] for row in emitted}, {"State instructions"})

    def test_process_counts_payload_and_partial_failure_do_not_rewrite_queue(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = {
                "a": {
                    "payload": '{"Line1":"防御"}',
                    "params": {"model": "fixture", "messages": []},
                    "provider": "openai",
                },
                "b": {
                    "payload": '{"Line1":"毒"}',
                    "params": {"model": "fixture", "messages": []},
                    "provider": "openai",
                },
            }
            write_json(root / "log/batch_requests.json", {"a": queue["a"]})
            write_json(
                root / "log/batch_requests.json.parts/fragment.json", {"b": queue["b"]}
            )
            # A newly accepted Batch has null counts/errors while validating.
            # Its screen refresh and saved payload must stay readable, and
            # unknown work must remain protected from another submission.
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "batch-fixture",
                            "custom_ids": {"req-000000": "a"},
                            "api_status": "in_progress",
                            "request_counts": None,
                            "provider_errors": None,
                        }
                    ]
                },
            )
            pending = process_view.summary(root, {"mode": "batch", "status": "running"})
            self.assertEqual(
                (pending["failed"], pending["errors"], pending["batches"][0]["counts"]),
                (0, [], {}),
            )
            self.assertTrue(pending["retryBlocked"])
            provider = SimpleNamespace(
                _openai_batch_body=lambda _provider, params: params
            )
            with patch.dict("sys.modules", {"util.batch_providers": provider}):
                self.assertEqual(process_view.payload(root, 0)["state"], "uncertain")
            pending_batch = process_view.saved(root, "batch_history.json")["batches"][0]
            rejected_batch = {
                **pending_batch,
                "id": "batch-rejected",
                "api_status": "completed",
                "request_counts": {
                    "processing": 0,
                    "succeeded": 0,
                    "errored": 1,
                    "canceled": 0,
                    "expired": 0,
                },
            }
            write_json(
                root / "log/batch_state.json",
                {
                    "status": "submitted",
                    "batches": [
                        {"id": row["id"], "custom_ids": row["custom_ids"]}
                        for row in [pending_batch, rejected_batch]
                    ],
                },
            )
            # A rejected duplicate must not release still-pending work, in
            # either receipt order. Known pending work is not "uncertain".
            for rows in [
                [pending_batch, rejected_batch],
                [rejected_batch, pending_batch],
            ]:
                write_json(root / "log/batch_history.json", {"batches": rows})
                known = process_view.summary(root, {"mode": "batch"})
                self.assertTrue(known["retryBlocked"])
                self.assertEqual(known["uncertain"], 0)
                with patch.dict("sys.modules", {"util.batch_providers": provider}):
                    self.assertEqual(
                        process_view.payload(root, 0)["state"], "submitted"
                    )
            (root / "log/batch_state.json").unlink()
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "batch-fixture",
                            "custom_ids": {"req-000000": "a"},
                            "api_status": "completed",
                            "request_counts": {"errored": 1},
                            "provider_errors": [{"message": "Batch stopped"}],
                        }
                    ]
                },
            )
            frozen = (root / "log/batch_requests.json").read_bytes()
            value = process_view.summary(
                root, {"mode": "batch", "completed": [], "appliedOutputs": []}
            )
            self.assertEqual(
                (
                    value["prepared"],
                    value["submitted"],
                    value["remaining"],
                    value["received"],
                    value["failed"],
                ),
                (2, 1, 1, 0, 1),
            )
            self.assertTrue(
                value["retryBlocked"]
            )  # Missing manifest/count proof remains unresolved.
            self.assertIsNone(value["usage"])
            # A request error must stay beside its own response; a Batch-wide
            # error must not be assigned to an unsent request with no ID.
            history = process_view.saved(root, "batch_history.json")
            history["batches"][0]["provider_errors"].append(
                {"custom_id": "req-000000", "message": "Unsupported temperature"}
            )
            write_json(root / "log/batch_history.json", history)
            value = process_view.summary(root, {"mode": "batch"})
            self.assertEqual(value["runErrors"], ["Batch stopped"])
            self.assertEqual(
                value["errors"], ["Batch stopped", "Unsupported temperature"]
            )
            provider = SimpleNamespace(
                _openai_batch_body=lambda _provider, params: params
            )
            with patch.dict("sys.modules", {"util.batch_providers": provider}):
                self.assertEqual(
                    process_view.payload(root, 0)["exact"]["custom_id"], "req-000000"
                )
                self.assertEqual(
                    process_view.payload(root, 0)["error"]["message"],
                    "Unsupported temperature",
                )
                self.assertEqual(process_view.payload(root, 1)["state"], "queued")
                self.assertIsNone(process_view.payload(root, 1)["error"])
                # Per-request usage must not inherit whole-Batch totals, or
                # turn missing/invalid provider counts into zero-token usage.
                self.assertIsNone(process_view.payload(root, 0)["usage"])
                write_json(
                    root / "log/batch_results.json",
                    {
                        "results": {
                            "a": {
                                "text": '{"Line1":"Guard"}',
                                "prompt_tokens": 42,
                                "completion_tokens": 5,
                                "cache_read_input_tokens": 0,
                                "thinking_tokens": None,
                                "total_tokens": -1,
                                "cache_creation_input_tokens": True,
                            }
                        }
                    },
                )
                self.assertEqual(
                    process_view.payload(root, 0)["usage"],
                    {
                        "input_tokens": 42,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                    },
                )
                self.assertIsNone(process_view.payload(root, 1)["usage"])
            with self.assertRaises(ValueError):
                process_view.payload(root, True)
            self.assertEqual((root / "log/batch_requests.json").read_bytes(), frozen)
            self.assertNotIn(
                "sk-fixture",
                process_view.clean_message("Bearer sk-fixture; api_key=private-value"),
            )

    def test_provider_error_read_is_sanitized_scoped_and_never_submits_or_rewrites(
        self,
    ):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            history = {
                "batches": [
                    {
                        "id": "batch-fixture",
                        "provider": "openai",
                        "key_name": "fixture-key",
                        "custom_ids": {"req-1": "source-hash"},
                    }
                ]
            }
            write_json(root / "log/batch_history.json", history)
            frozen = (root / "log/batch_history.json").read_bytes()
            client = Mock()
            client.with_options.return_value = client
            package = ModuleType("util")
            connection = {
                "runtime_name": "fixture-key",
                "provider": "openai",
                "protocol": "openai",
                "secret": "fixture-private-value",
                "keyless": False,
                "endpoint": "https://provider.invalid/v1",
                "organization": "fixture-org",
            }
            # The submitted account must resolve from canonical settings even
            # when another account is active and the legacy vault is absent.
            settings = object.__new__(Settings)
            current = {
                "connections": [
                    connection,
                    {
                        **connection,
                        "runtime_name": "other-key",
                        "secret": "other-fixture-value",
                    },
                ],
                "active": "other-key",
            }
            settings._read = lambda: deepcopy(current)
            plan = {
                "settings": {
                    "api": connection["endpoint"],
                    "organization": "fixture-org",
                }
            }
            resolve = lambda batch: settings.batch_connection(batch, plan)
            package.batch_providers = SimpleNamespace(
                retrieve_batch=Mock(
                    return_value={
                        "api_status": "completed",
                        "counts": {"errored": 1},
                        "errors": [],
                        "error_file_id": "file-fixture",
                    }
                ),
                get_client=Mock(return_value=client),
                _download_file_text=Mock(
                    return_value=json.dumps(
                        {
                            "custom_id": "req-1",
                            "response": {
                                "body": {
                                    "error": {
                                        "code": "unsupported_value",
                                        "param": "temperature",
                                        "message": "Unsupported temperature 0. fixture-private-value",
                                    }
                                }
                            },
                        }
                    )
                    + "\n"
                    + json.dumps(
                        {
                            "custom_id": "unrelated-request",
                            "error": {"message": "Unrelated private request"},
                        }
                    )
                ),
            )
            with patch.dict("sys.modules", {"util": package}):
                result = process_view.provider_details(root, resolve)
            error = result["batches"][0]["errors"][0]
            self.assertEqual(
                (error["code"], error["param"]), ("unsupported_value", "temperature")
            )
            self.assertIn("Unsupported temperature 0.", error["message"])
            self.assertNotIn("fixture-private-value", json.dumps(result))
            self.assertNotIn("Unrelated private request", json.dumps(result))
            package.batch_providers.get_client.assert_called_once_with(
                "openai",
                api_key="fixture-private-value",
                api_url=connection["endpoint"],
                max_retries=0,
            )
            client.with_options.assert_called_once_with(
                timeout=20, max_retries=0, organization="fixture-org"
            )
            client.batches.create.assert_not_called()
            client.files.create.assert_not_called()
            client.batches.cancel.assert_not_called()
            self.assertEqual((root / "log/batch_history.json").read_bytes(), frozen)
            for change in [
                lambda: current["connections"].pop(0),
                lambda: connection.update(endpoint="https://other.invalid/v1"),
                lambda: connection.update(organization="different-org"),
            ]:
                baseline = deepcopy(current)
                change()
                with (
                    patch.dict("sys.modules", {"util": package}),
                    self.assertRaises(ValueError),
                ):
                    process_view.provider_details(root, resolve)
                current.clear()
                current.update(baseline)
                connection = current["connections"][0]
            package.batch_providers.get_client.assert_called_once()

    def test_batch_phase_feedback_uses_receipts_instead_of_stale_scan_progress(self):
        job = {
            "mode": "batch",
            "status": "waiting",
            "phase": "submit",
            "message": "Scanning speakers… 3/3",
            "progress": {"current": 3, "total": 3, "file": "Classes.json"},
            "approval": {"kind": "batch"},
        }
        frozen = deepcopy(job)
        waiting = process_view.phase_feedback(job)
        self.assertIn("Review the cost", waiting["message"])
        self.assertIsNone(waiting["progress"])
        self.assertEqual(job, frozen)
        job.update(
            status="running",
            phase="poll_status",
            approval=None,
            process={"batches": [{"counts": {"succeeded": 7, "processing": 1}}]},
        )
        polling = process_view.phase_feedback(job)
        self.assertIn("7 completed, 1 processing", polling["message"])
        self.assertIsNone(polling["progress"])
        job["status"] = "stopped"
        self.assertEqual(process_view.phase_feedback(job), polling)
        job["process"]["batches"][0]["status"] = "completed"
        self.assertIn(
            "Provider work has finished", process_view.phase_feedback(job)["message"]
        )
        job.update(status="failed", message="Actual provider failure")
        self.assertEqual(process_view.phase_feedback(job), {})
        job.update(mode="translate", status="running", phase="translate")
        self.assertEqual(process_view.phase_feedback(job), {})
        job.update(
            phase="preparing",
            process={"requests": [{"state": "submitted"}]},
            itemProgress={"file": "Map010.json", "current": 25, "total": 5887},
        )
        live = process_view.phase_feedback(job)
        self.assertEqual(live["phase"], "translate")
        self.assertEqual({**job, **live}["itemProgress"], job["itemProgress"])
        self.assertIn("Waiting", live["message"])
        # Rejected receipts do not end the worker's parsing of this file.
        job["process"]["requests"] = [{"state": "rejected"}]
        self.assertEqual(
            {**job, **process_view.phase_feedback(job)}["itemProgress"],
            job["itemProgress"],
        )
        job.update(
            status="complete", process={"validationIssues": [{"file": "Map001.json"}]}
        )
        finished = process_view.phase_feedback(job)
        self.assertEqual(finished["phase"], "done")
        self.assertIsNone(finished["progress"])
        self.assertIsNone(finished["itemProgress"])
        self.assertIn("rejected", finished["message"])

    def test_live_receipt_usage_and_validation_are_separate_from_preparation(self):
        with TemporaryDirectory() as temporary:
            evidence = Evidence(temporary, "translate")
            evidence.prepared({"model": "fixture", "messages": []})
            self.assertIsNone(process_view.payload(temporary, 0)["usage"])
            summary = lambda: process_view.summary(temporary, {"mode": "translate"})
            self.assertEqual(
                (summary()["prepared"], summary()["received"], summary()["validated"]),
                (1, 0, 0),
            )
            interrupted = lambda: process_view.summary(
                temporary, {"mode": "translate", "status": "interrupted"}
            )
            # A stopped worker may have sent its last payload before receiving or
            # validating it. The saved run must not offer an unguarded retry.
            self.assertFalse(interrupted()["retryBlocked"])
            self.assertEqual(interrupted()["uncertain"], 0)
            evidence.update("submitted")
            self.assertTrue(interrupted()["retryBlocked"])
            self.assertEqual(interrupted()["uncertain"], 1)
            evidence.update(
                "received",
                {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            )
            self.assertEqual((summary()["received"], summary()["validated"]), (1, 0))
            self.assertTrue(interrupted()["retryBlocked"])
            self.assertEqual(interrupted()["uncertain"], 0)
            self.assertEqual(summary()["usage"]["total_tokens"], 15)
            evidence.update(
                "validated",
                {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            )
            self.assertEqual(summary()["validated"], 1)
            self.assertFalse(interrupted()["retryBlocked"])
            self.assertEqual(process_view.payload(temporary, 0)["state"], "validated")
            self.assertEqual(
                process_view.payload(temporary, 0)["usage"],
                {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            )
            # Live request failures likewise must not become run-wide errors.
            evidence.update(
                "rejected",
                error=json.dumps({"message": "Response did not match the source IDs."}),
            )
            self.assertIn("Response did not match the source IDs.", summary()["errors"])
            self.assertEqual(summary()["runErrors"], [])
            self.assertEqual(
                process_view.payload(temporary, 0)["error"]["message"],
                "Response did not match the source IDs.",
            )
