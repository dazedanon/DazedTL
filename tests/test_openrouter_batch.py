"""Inline transport, retained receipts, and absolute Batch prices without APIs."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

import httpx
from dazedtl.compatibility import openrouter_batch as batch
from dazedtl.compatibility import openrouter_pricing
from dazedtl.settings import openrouter
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.requests import quote

from tests.engine import engine_module, point, replaced_modules

MODEL = "author/model"
POLICY = {
    "transport": openrouter.TRANSPORT,
    "model": MODEL,
    "host": "",
    "input": 0.8,
    "output": 3,
    "cache_read": 0.2,
    "cache_write": None,
    "max_requests": 1000,
    "max_bytes": 10_000_000,
}


def request(identity="one"):
    return {
        "custom_id": identity,
        "params": {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Preserve names and control codes."},
                {"role": "user", "content": r'{"line":"薬\\C[0]"}'},
            ],
            "response_format": {"type": "json_object"},
        },
    }


def result(identity, text='{"line":"Potion\\\\C[0]"}', **extra):
    return {
        "custom_id": identity,
        "response": {
            "status_code": 200,
            "body": {
                "choices": [{"message": {"content": text, **extra}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 2},
                },
            },
        },
    }


# 108 input tokens at 0.8 and 250 output tokens at 3 per million, the Batch
# rates POLICY gives MODEL.
QUOTED = (108 * 0.8 + 250 * 3) / 1_000_000


class OpenRouterQuoteTests(unittest.TestCase):
    """A quote reads the real engine and needs none of the Batch tests'
    stand-ins."""

    def test_quotes_use_absolute_batch_rates_once(self):
        # Input/output discounts can differ. An estimate may not halve
        # already discounted rates again.
        cfg = {
            "mode": "batch",
            "model": MODEL,
            "provider": "openrouter",
            "openrouterBatch": POLICY,
            "rates": {"input": 2, "output": 8},
        }
        # Each request also counts 8 tokens of message framing.
        quoted = quote(
            [{"params": {}, "sources": {"line": "薬"}}],
            cfg,
            "openrouter",
            lambda _: 100,
        )
        self.assertEqual(quoted["cost"], QUOTED)

    def test_batch_file_lines_and_total_price_results_alike(self):
        # An OpenRouter Batch's file line and TOTAL price its fetched results
        # at the policy's rates; every other Batch keeps the model's Live
        # rates with its cache prices, then the Batch discount.
        import os
        import threading
        from unittest.mock import patch

        from util import batch_history, extensions, translation

        claude = "anthropic/claude-sonnet-5-5"
        policy = {**POLICY, "model": claude, "cache_write": 1.875}
        # 100k uncached input, 900k cache reads, 50k five-minute writes and
        # 10k output, at $3 and $15 per 1M Live.
        counters = {
            "file_batch_regular": 100_000,
            "file_batch_output": 10_000,
            "file_batch_read": 900_000,
            "file_batch_write": 50_000,
            "file_batch_write_1h": 0,
        }
        for endpoint, model, cost in (
            (
                batch.BASE_URL,
                claude,
                openrouter_pricing.batch_cost(policy, 100_000, 10_000, 900_000, 50_000),
            ),
            ("", "claude-sonnet-5-5", (0.3 + 2.7 * 0.05 + 0.15 * 1.25 + 0.15) / 2),
            (
                "https://api.openai.com/v1",
                "gpt-5.4-mini",
                (0.3 + 2.7 * 0.1 + 0.15 + 0.15) / 2,
            ),
        ):
            with (
                self.subTest(model=model, endpoint=endpoint),
                patch.dict(os.environ, {"api": endpoint, "API_PROVIDER": "openai"}),
                # Restores the host layers this test adds to the engine.
                patch.dict(extensions._layers),
                patch.object(
                    translation,
                    "getPricingConfig",
                    return_value={"inputAPICost": 3, "outputAPICost": 15},
                ),
                patch.object(translation, "_thread_local", threading.local()),
                patch.object(translation, "_global_accurate_cost", 0.0),
            ):
                batch.install()
                openrouter_pricing.configure(translation, policy)
                local = translation._thread_local
                # Two calls fetch half the file's results each, which the
                # TOTAL adds as they arrive.
                for share in (2, 1):
                    before = translation._batch_usage()
                    for name, count in counters.items():
                        setattr(local, name, count // share)
                    translation._record_batch_cost(before, model)
                local.file_cost_window_active = True
                for _call in ("file", "TOTAL"):
                    self.assertAlmostEqual(translation.calculateCost(1, 1, model), cost)
                # The Batch history never presents OpenRouter's reported
                # charges as the cost of inference.
                self.assertIsNone(
                    batch_history._price_usage(
                        {"input_tokens": 1}, claude, "openrouter"
                    )
                )


class OpenRouterBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The layers these tests add go onto a private copy of the engine's
        # Batch providers, never onto the one later tests import.
        cls.native = engine_module("util/batch_providers.py")

    def setUp(self):
        self.modules = replaced_modules({"util.batch_providers": self.native})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_inline_submission_preserves_payload_and_pinned_host_without_upload_or_retry(
        self,
    ):
        # Protect against accidentally calling OpenAI's file API or sending
        # SDK-only provider settings inside each OpenRouter request body.
        calls = []

        def respond(req):
            calls.append(req)
            return httpx.Response(202, json={"id": "paid", "status": "validating"})

        item = request()
        item["params"]["extra_body"] = {
            "provider": {"only": ["deepinfra"], "allow_fallbacks": False}
        }
        original = deepcopy(item)
        with (
            TemporaryDirectory() as directory,
            batch.Client(
                "fixture-key",
                policy={**POLICY, "host": "deepinfra"},
                receipt_root=directory,
                transport=httpx.MockTransport(respond),
            ) as client,
        ):
            self.assertEqual(client.submit([item])["id"], "paid")
            body = json.loads(calls[0].content)
            self.assertEqual(
                list(body),
                ["endpoint", "model", "completion_window", "provider", "requests"],
            )
            self.assertEqual(body["provider"], {"only": ["deepinfra"]})
            self.assertEqual(
                body["requests"][0]["body"],
                {
                    key: value
                    for key, value in item["params"].items()
                    if key != "extra_body"
                },
            )
            self.assertEqual(str(calls[0].url), batch.BASE_URL + "/batches")
            self.assertEqual(calls[0].method, "POST")
            self.assertEqual(item, original)
            self.assertTrue(
                (
                    Path(directory) / f"log/openrouter/{digest('paid')}-submission.json"
                ).is_file()
            )
            for invalid in (
                [item, item],
                [item, request("other")],
                [{**item, "params": {**item["params"], "model": "different"}}],
            ):
                with self.assertRaises(ValueError):
                    client.submit(invalid)
            self.assertEqual(len(calls), 1)
            # Structured Batch routing must survive serialization, and a
            # weakened format or a different endpoint must fail before POST.
            from dazedtl.compatibility.request_parameters import (
                batch_routing,
                structured_output,
            )

            client.policy = {
                **POLICY,
                "structuredOutputs": openrouter.STRUCTURED_OUTPUTS,
                "providers": ["deepinfra", "fireworks"],
            }
            schema = {
                "type": "object",
                "properties": {"line": {"type": "string"}},
                "required": ["line"],
                "additionalProperties": False,
            }
            strict = {
                "custom_id": "strict",
                "params": batch_routing(
                    structured_output(request()["params"], schema, live=False),
                    client.policy,
                ),
            }
            client.submit([strict])
            wire = json.loads(calls[-1].content)
            self.assertEqual(wire["provider"], {"only": ["deepinfra", "fireworks"]})
            self.assertEqual(
                wire["requests"][0]["body"]["response_format"],
                strict["params"]["response_format"],
            )
            self.assertNotIn("provider", wire["requests"][0]["body"])
            for changes in (
                {"response_format": {"type": "json_object"}},
                {"response_format": {}},
                {"extra_body": {}},
            ):
                with self.assertRaises(ValueError):
                    client.submit(
                        [{**strict, "params": {**strict["params"], **changes}}]
                    )
            self.assertEqual(len(calls), 2)
        for failure in (httpx.ReadTimeout("lost response"), 500, 408):
            attempts = []

            def lost(req):
                attempts.append(req)
                if isinstance(failure, Exception):
                    raise failure
                return httpx.Response(failure)

            with batch.Client(
                "fixture-key", policy=POLICY, transport=httpx.MockTransport(lost)
            ) as client:
                with self.assertRaises((httpx.ReadTimeout, batch.RequestError)):
                    client.submit([request()])
                self.assertEqual(len(attempts), 1)
        # A refusal keeps OpenRouter's reason, such as which credit limit a
        # 402 hit, without any credential it echoes back.
        refusal = {
            "error": {
                "code": 402,
                "message": "Budget too small for fixture-key.",
                "metadata": {"limit_source": "in_flight_budget", "echo": "input"},
            }
        }
        with (
            batch.Client(
                "fixture-key",
                policy=POLICY,
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(402, json=refusal)
                ),
            ) as client,
            self.assertRaises(batch.RequestError) as raised,
        ):
            client.submit([request()])
        self.assertEqual(raised.exception.status_code, 402)
        self.assertIn("limit: in_flight_budget", str(raised.exception))
        self.assertNotIn("fixture-key", str(raised.exception))
        self.assertNotIn("input", str(raised.exception))

    def test_openrouter_preview_shows_live_routing_as_a_chat_completion(self):
        # A Live estimate's queue carries OpenRouter preferences such as
        # require_parameters, which are not a Batch host; previewing it crashed.
        from dazedtl.compatibility.process_view import batch_payload

        entry = {"payload": '{"Line1":"薬"}', "provider": "openrouter"}
        live = {
            "model": "openai/gpt-6-luna",
            "messages": [],
            "extra_body": {"provider": {"require_parameters": True}},
        }
        exact = batch_payload(0, 1, entry, None, live, None, "")["exact"]
        self.assertEqual(exact["url"], "/v1/chat/completions")
        self.assertEqual(exact["body"]["provider"], {"require_parameters": True})
        pinned = {"only": ["deepinfra"], "allow_fallbacks": False}
        batch = {**live, "extra_body": {"provider": pinned}}
        exact = batch_payload(0, 1, entry, "one", batch, None, "")["exact"]
        self.assertEqual(exact["provider"], {"only": ["deepinfra"]})
        self.assertNotIn("provider", exact["requests"][0]["body"])

    def test_unordered_inline_results_keep_original_bodies_refusals_and_billing_after_expiry(
        self,
    ):
        # Downloaded paid responses must survive provider retention expiry and
        # preserve refusals and BYOK fees without recalculating billed amounts.
        received = {
            "id": "paid",
            "status": "completed",
            "request_counts": {"total": 3, "completed": 2, "failed": 1},
            "results": [
                result("two", "Cannot translate this.", refusal="declined"),
                {"custom_id": "three", "error": {"code": "rejected"}},
                result("one"),
            ],
            "usage": {
                "cost": 0.0042,
                "is_byok": True,
                "cost_details": {"upstream_inference_cost": 0.2},
            },
        }
        calls = []

        def respond(req):
            calls.append(req)
            return httpx.Response(200, json=received)

        with TemporaryDirectory() as directory:
            with batch.Client(
                "fixture-key",
                policy=POLICY,
                receipt_root=directory,
                transport=httpx.MockTransport(respond),
            ) as client:
                parts, errors, usage = client.collect(
                    "paid", {"one": "key1", "two": "key2", "three": "key3"}
                )
                self.assertEqual(set(parts), {"key1", "key2"})
                self.assertEqual(
                    parts["key1"]["provider_response"],
                    received["results"][2]["response"]["body"],
                )
                self.assertTrue(parts["key2"]["refusal"])
                self.assertEqual([row[0] for row in errors], ["three"])
                self.assertEqual(usage["openrouter_cost"], 0.0042)
                self.assertEqual(usage["upstream_inference_cost"], 0.2)
                self.assertEqual(
                    (
                        usage["input_tokens"],
                        usage["cache_read_input_tokens"],
                        usage["output_tokens"],
                    ),
                    (16, 4, 8),
                )
                self.assertEqual(
                    batch.normalize(received, "paid")["counts"]["succeeded"], 2
                )
            with batch.Client(
                "fixture-key",
                policy=POLICY,
                receipt_root=directory,
                transport=httpx.MockTransport(
                    lambda _: self.fail(
                        "Retained results must not require a provider read."
                    )
                ),
            ) as reopened:
                self.assertEqual(
                    reopened.collect(
                        "paid", {"one": "key1", "two": "key2", "three": "key3"}
                    ),
                    (parts, errors, usage),
                )
            self.assertEqual(len(calls), 1)

    def test_missing_conflicting_and_expired_results_remain_unresolved_and_are_retained(
        self,
    ):
        # Neither terminal status nor aggregate success counts prove a request
        # response exists. Wrong/duplicate IDs must never enter local consume.
        for rows in (
            None,
            [result("one")],
            [result("one"), result("one")],
            [result("one"), result("foreign")],
        ):
            with self.subTest(rows=rows), TemporaryDirectory() as directory:
                received = {
                    "id": "paid",
                    "status": "completed",
                    "request_counts": {"total": 2, "completed": 2, "failed": 0},
                    "results": rows,
                }
                with (
                    batch.Client(
                        "fixture-key",
                        policy=POLICY,
                        receipt_root=directory,
                        transport=httpx.MockTransport(
                            lambda _: httpx.Response(200, json=received)
                        ),
                    ) as client,
                    self.assertRaises(batch.ResultsUnavailable),
                ):
                    client.collect("paid", {"one": "key1", "two": "key2"})
                self.assertEqual(
                    read_json(
                        Path(directory)
                        / f"log/openrouter/{digest('paid')}-results.json"
                    ),
                    received,
                )
                self.assertFalse(
                    (
                        Path(directory)
                        / f"log/openrouter/{digest('paid')}-accepted.json"
                    ).exists()
                )
        for status in ("failed", "expired", "cancelled"):
            received = {
                "id": "paid",
                "status": status,
                "request_counts": {"total": 2, "completed": 1, "failed": 1},
                "results": None,
            }
            with (
                batch.Client(
                    "fixture-key",
                    policy=POLICY,
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=received)
                    ),
                ) as client,
                self.assertRaises(batch.ResultsUnavailable),
            ):
                client.collect("paid", {"one": "key1", "two": "key2"})
        received["request_counts"].update(completed=0, failed=2)
        with batch.Client(
            "fixture-key",
            policy=POLICY,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=received)),
        ) as client:
            self.assertEqual(
                {
                    row[0]
                    for row in client.collect("paid", {"one": "key1", "two": "key2"})[1]
                },
                {"one", "two"},
            )
        with (
            batch.Client(
                "fixture-key",
                policy=POLICY,
                transport=httpx.MockTransport(lambda _: httpx.Response(410)),
            ) as client,
            self.assertRaisesRegex(batch.ResultsUnavailable, "expired"),
        ):
            client.collect("paid", {"one": "key1"})

    def test_native_batch_prices_use_absolute_batch_rates_once(self):
        # Input/output discounts can differ. The engine's quotes and its price
        # of fetched results may not halve already discounted rates again.
        native_value = {
            "model": MODEL,
            "provider": "openrouter",
            "input_tokens": 108,
            "output_tokens": 250,
            "batch_cost": 0.0011,
        }
        history = ModuleType("util.batch_history")
        history._price_usage = point(lambda *_: 999)
        translation = SimpleNamespace(
            estimateCostComparison=point(lambda *_: native_value),
            batch_usage_cost=point(lambda *_: 999),
        )
        usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 10,
        }
        with replaced_modules({"util.batch_history": history}):
            for _ in range(2):
                openrouter_pricing.configure(translation, POLICY)
                self.assertEqual(
                    translation.estimateCostComparison()["batch_cost"], QUOTED
                )
                self.assertAlmostEqual(
                    translation.batch_usage_cost(usage, MODEL, "openrouter"),
                    (110 * 0.8 + 30 * 0.2 + 20 * 3) / 1_000_000,
                )
            self.assertEqual(translation.batch_usage_cost(usage, MODEL, "openai"), 999)
            self.assertIsNone(
                history._price_usage({"openrouter_cost": 1}, MODEL, "openrouter")
            )
            self.assertEqual(history._price_usage({}, "other", "openai"), 999)
