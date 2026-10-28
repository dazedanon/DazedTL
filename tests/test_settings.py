"""Per-model limits stay with their connection and the approved run."""

import json
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.settings import openrouter, preferences, providers
from dazedtl.settings.execution import configuration, worker_secret
from dazedtl.settings.store import Settings
from dazedtl.storage import write_json
from dazedtl.translation.requests import LINE_KEYS, logical_request

from tests.engine import replaced_modules


class SettingsTests(unittest.TestCase):
    def test_openrouter_connection_keeps_its_route_and_secret_through_save_check_and_reload(
        self,
    ):
        # A named OpenRouter preset must not become native OpenAI/Anthropic,
        # expose its key, or accidentally transfer a key to a different server.
        metadata = {
            "values": {
                "language": "English",
                "model": "fixture-model",
                "api": "",
                "API_PROVIDER": "openai",
            }
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            allow_providers=True,
            validate_route=lambda values: ExistingBackend.validate_route(
                ExistingBackend, values
            ),
            provider_defaults=lambda _: {"batch_supported": False},
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        state = {
            "version": 2,
            "revision": 0,
            "values": {"language": "English", "model": "fixture-model"},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "",
            "draft": None,
            "connections": [],
        }
        with TemporaryDirectory() as temporary:
            write_json(Path(temporary) / "settings/settings.json", state)
            settings = Settings(temporary, adapter)
            with patch.object(providers, "check") as check:
                view = settings.save_connection(
                    0, "openrouter", secret="fixture-router-key", organization="ignored"
                )
                check.assert_not_called()
            identity = view["activeConnectionId"]
            connection = view["connections"][0]
            self.assertEqual(connection["openrouter_host"], "")
            self.assertEqual(
                (
                    connection["name"],
                    connection["protocol"],
                    connection["organization"],
                ),
                ("OpenRouter", "openai", ""),
            )
            self.assertEqual(
                next(item for item in view["providers"] if item["id"] == "openrouter")[
                    "protocol"
                ],
                "openai",
            )
            model = "anthropic/claude-sonnet-4.5"
            options = {
                model: {
                    "entriesPerRequest": None,
                    "pricing": "custom",
                    "inputRate": 3,
                    "outputRate": 15,
                }
            }
            view = settings.save(
                view["revision"],
                identity,
                {"language": "English", "model": model, "sourceLanguage": "Japanese"},
                options,
            )
            automatic = configuration(settings, "live")
            self.assertNotIn("openrouterHost", automatic)
            view = settings.save_connection(
                view["revision"],
                "openrouter",
                connection_id=identity,
                openrouter_host="deepinfra",
            )
            frozen = configuration(settings, "live")
            self.assertEqual(frozen["openrouterHost"], "deepinfra")
            self.assertEqual(
                (frozen["provider"], frozen["protocol"], frozen["endpoint"]),
                ("openrouter", "openai", "https://openrouter.ai/api/v1"),
            )
            self.assertNotIn("batchInputTokens", frozen)
            settings.prepare_engine("translate")
            frozen_policy = deepcopy(adapter.manual.request_policy)
            self.assertEqual(frozen_policy["openrouterHost"], "deepinfra")
            installed = adapter.install_settings.call_args.args[1]
            self.assertEqual(
                (installed["api"], installed["API_PROVIDER"], installed["model"]),
                (frozen["endpoint"], "openai", model),
            )
            view = settings.save_connection(
                view["revision"], "openrouter", connection_id=identity, name="Renamed"
            )
            self.assertEqual(view["connections"][0]["model"], model)
            self.assertEqual(view["connections"][0]["openrouter_host"], "deepinfra")
            reloaded = Settings(temporary, adapter)
            self.assertEqual(
                worker_secret(Path(temporary), frozen), "fixture-router-key"
            )
            self.assertEqual(configuration(reloaded, "live"), frozen)
            with self.assertRaisesRegex(ValueError, "Enter the API key"):
                reloaded.save_connection(
                    view["revision"], "openai", connection_id=identity
                )
            with patch.object(
                providers,
                "check",
                return_value={
                    "check": {
                        "status": "verified",
                        "message": "Checked",
                        "checkedAt": "now",
                    },
                    "models": [model],
                },
            ):
                view = reloaded.check_connection(view["revision"], identity)
            self.assertEqual(view["connections"][0]["models"], [model])
            self.assertNotIn("fixture-router-key", str(view))
            for invalid in (
                "host with spaces",
                "https://provider.invalid",
                ["deepinfra"],
                7,
            ):
                with self.assertRaisesRegex(ValueError, "valid OpenRouter host"):
                    reloaded.save_connection(
                        view["revision"],
                        "openrouter",
                        connection_id=identity,
                        openrouter_host=invalid,
                    )
            view = reloaded.save_connection(
                view["revision"],
                "openrouter",
                connection_id=identity,
                openrouter_host="novita",
            )
            self.assertEqual(
                configuration(reloaded, "live")["openrouterHost"], "novita"
            )
            # Credentials are resolved through the same route while execution
            # keeps the approved host, even after the connection is edited.
            self.assertEqual(
                worker_secret(Path(temporary), frozen), "fixture-router-key"
            )
            self.assertEqual(frozen_policy["openrouterHost"], frozen["openrouterHost"])
            view = reloaded.save_connection(
                view["revision"],
                "openrouter",
                connection_id=identity,
                openrouter_host="",
            )
            self.assertEqual(configuration(reloaded, "live"), automatic)
            reloaded.prepare_engine("translate")
            self.assertNotIn("openrouterHost", adapter.manual.request_policy)
            view = reloaded.save_connection(
                view["revision"],
                "openai",
                connection_id=identity,
                secret="fixture-openai-key",
                openrouter_host="deepinfra",
            )
            self.assertEqual(view["connections"][0]["openrouter_host"], "")

    def test_removing_a_connection_forgets_its_key_and_respects_saved_runs(self):
        # Removal must not strand a run silently or leave the removed key in the engine's derived key cache.
        metadata = {
            "values": {
                "language": "English",
                "model": "fixture-model",
                "api": "",
                "API_PROVIDER": "openai",
            }
        }
        jobs = {
            "old": {"mode": "batch", "status": "failed"},
            "done": {"mode": "translate", "status": "complete"},
            "quote": {"mode": "estimate", "status": "stopped"},
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            allow_providers=True,
            manual=SimpleNamespace(request_policy=None, jobs=jobs),
            saved_run_configuration=lambda identity: {"key_name": key_name},
            install_settings=Mock(),
        )
        state = {
            "version": 2,
            "revision": 0,
            "values": {"language": "English", "model": "fixture-model"},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "",
            "draft": None,
            "connections": [],
        }
        with TemporaryDirectory() as temporary:
            write_json(Path(temporary) / "settings/settings.json", state)
            settings = Settings(temporary, adapter)
            view = settings.save_connection(0, "openrouter", secret="router-key")
            router = view["activeConnectionId"]
            view = settings.save_connection(
                view["revision"], "openai", secret="openai-key"
            )
            native = view["activeConnectionId"]
            key_name = "connection-" + router
            # Only the failed Batch counts: complete runs and estimates are done.
            self.assertEqual(settings.connection_usage(router), {"unfinished": 1})
            with self.assertRaisesRegex(ValueError, "changed"):
                settings.remove_connection(view["revision"], router, 0)
            view = settings.select(view["revision"], router)
            view = settings.remove_connection(view["revision"], router, 1)
            self.assertEqual(
                (
                    [item["id"] for item in view["connections"]],
                    view["activeConnectionId"],
                ),
                ([native], native),
            )
            vault = adapter.install_settings.call_args.args[3]
            self.assertNotIn(key_name, vault["keys"])
            view = settings.remove_connection(view["revision"], native, 0)
            self.assertEqual(
                (view["connections"], view["activeConnectionId"]), ([], "")
            )

    def test_openrouter_host_lookup_is_read_only_and_rejects_unusable_catalogs(self):
        # A public suggestion lookup must not send credentials, follow a
        # redirect, or show unrelated hosts for the selected model. Endpoint
        # variants of one host must collapse to the same routing slug.
        requests = []
        body = json.dumps(
            {
                "data": [
                    {"slug": "xiaomi", "name": "Xiaomi"},
                    {"slug": "deepinfra", "name": "DeepInfra"},
                ]
            }
        ).encode()
        status = 200

        def respond(request):
            requests.append(request)
            return httpx.Response(status, stream=httpx.ByteStream(body))

        client = httpx.Client

        def mocked_client(**kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            return client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(providers.httpx, "Client", side_effect=mocked_client):
            self.assertEqual(
                providers.openrouter_hosts(),
                [
                    {"slug": "deepinfra", "name": "DeepInfra"},
                    {"slug": "xiaomi", "name": "Xiaomi"},
                ],
            )
            self.assertEqual(
                str(requests[0].url), "https://openrouter.ai/api/v1/providers"
            )
            self.assertEqual(requests[0].method, "GET")
            self.assertNotIn("Authorization", requests[0].headers)
            model = "xiaomi/fixture-model:free"
            body = json.dumps(
                {
                    "data": {
                        "id": model,
                        "endpoints": [
                            {"tag": "xiaomi/fp8", "provider_name": "Xiaomi"},
                            {"tag": "deepinfra/fp8", "provider_name": "DeepInfra"},
                            {"tag": "deepinfra/bf16", "provider_name": "DeepInfra"},
                        ],
                    }
                }
            ).encode()
            self.assertEqual(
                providers.openrouter_hosts(model),
                [
                    {"slug": "deepinfra", "name": "DeepInfra"},
                    {"slug": "xiaomi", "name": "Xiaomi"},
                ],
            )
            self.assertEqual(
                str(requests[-1].url),
                "https://openrouter.ai/api/v1/models/xiaomi/fixture-model%3Afree/endpoints",
            )
            self.assertNotIn("Authorization", requests[-1].headers)
            with self.assertRaises(ValueError):
                providers.openrouter_hosts("xiaomi/different-model")
            before = len(requests)
            for invalid in ("../../providers", "https://example.invalid/model", 7):
                with self.assertRaises(ValueError):
                    providers.openrouter_hosts(invalid)
            self.assertEqual(len(requests), before)
            body = json.dumps({"data": {"id": model, "endpoints": []}}).encode()
            self.assertEqual(providers.openrouter_hosts(model), [])
            for status, body in (
                (302, b"{}"),
                (200, b'{"data":[{"name":"Missing slug"}]}'),
                (200, b'{"data":[{"name":"Bad host","slug":"bad host"}]}'),
                (200, b"x" * 1_000_001),
            ):
                with self.assertRaises(ValueError):
                    providers.openrouter_hosts()
            body = json.dumps(
                {
                    "data": {
                        "id": model,
                        "endpoints": [{"tag": None, "provider_name": "Unknown"}],
                    }
                }
            ).encode()
            with self.assertRaises(ValueError):
                providers.openrouter_hosts(model)

    def test_openrouter_checks_authenticated_catalog_without_truncating_it_to_250_models(
        self,
    ):
        # The public /models endpoint can succeed without authenticating a key;
        # large account catalogs must retain later model suggestions as well.
        connection = {
            "provider": "openrouter",
            "protocol": "openai",
            "endpoint": "",
            "keyless": False,
            "secret": "fixture-router-key",
            "organization": "",
        }
        models = [f"author/model-{index:03}" for index in range(600)]
        connection["model"] = models[0]
        priced = {
            "id": models[0],
            "pricing": {"prompt": "0.000002", "completion": "0.000008"},
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["response_format"],
        }
        requests = []
        status = 200

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/endpoints"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "id": models[0] + ":batch",
                            "endpoints": [
                                {
                                    "tag": "supported",
                                    "supported_parameters": [
                                        "response_format",
                                        "structured_outputs",
                                    ],
                                    "pricing": {
                                        "prompt": ".0000008",
                                        "completion": ".000003",
                                    },
                                },
                                {
                                    "tag": "json-only",
                                    "supported_parameters": ["response_format"],
                                    "pricing": {"prompt": "0", "completion": "0"},
                                },
                                {
                                    "tag": "mixed",
                                    "supported_parameters": [
                                        "response_format",
                                        "structured_outputs",
                                    ],
                                    "pricing": {"prompt": "0", "completion": "0"},
                                },
                                {
                                    "tag": "mixed/legacy",
                                    "supported_parameters": ["response_format"],
                                },
                            ],
                        }
                    },
                )
            return httpx.Response(
                status,
                stream=httpx.ByteStream(
                    json.dumps(
                        {
                            "data": [{"id": model} for model in reversed(models[1:])]
                            + [
                                priced,
                                {
                                    **priced,
                                    "id": models[0] + ":batch",
                                    "pricing": {
                                        "prompt": "0.0000008",
                                        "completion": "0.000003",
                                    },
                                },
                            ]
                        }
                    ).encode()
                ),
            )

        client = httpx.Client

        def mocked_client(**kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            return client(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(providers.httpx, "Client", side_effect=mocked_client):
            result = providers.check(connection)
            self.assertEqual(result["check"]["status"], "verified")
            self.assertEqual(result["models"], models)
            # The list's effort data is kept where a row has any: this model
            # shows no reasoning parameter, the others nothing at all.
            self.assertEqual(result["efforts"][models[0]]["levels"], [])
            self.assertNotIn(models[1], result["efforts"])
            self.assertEqual(
                str(requests[0].url), "https://openrouter.ai/api/v1/models/user"
            )
            self.assertEqual(
                requests[0].headers["Authorization"], "Bearer fixture-router-key"
            )
            self.assertEqual(requests[0].method, "GET")
            connection.update(result)
            options = {
                "entriesPerRequest": None,
                "pricing": "automatic",
                "inputRate": None,
                "outputRate": None,
            }
            frozen = openrouter.policy(connection, models[0], options, required=True)
            self.assertEqual((frozen["input"], frozen["output"]), (0.8, 3))
            self.assertEqual(frozen["providers"], ["supported"])
            self.assertTrue(
                openrouter.describe(connection, models[0])["batchSupported"]
            )
            self.assertFalse(
                openrouter.describe(connection, models[-1])["batchSupported"]
            )
            connection["batch_endpoints"]["rates"]["input"] = None
            with self.assertRaisesRegex(ValueError, "Batch pricing is unavailable"):
                openrouter.policy(connection, models[0], options, required=True)
            custom = preferences.options(
                {
                    **options,
                    "batchPricing": "custom",
                    "batchInputRate": 0.7,
                    "batchOutputRate": 2,
                }
            )
            self.assertEqual(
                openrouter.policy(connection, models[0], custom, required=True)[
                    "input"
                ],
                0.7,
            )
            self.assertEqual(frozen["input"], 0.8)
            with self.assertRaises(ValueError):
                preferences.options({**custom, "batchOutputRate": None})
            for status, expected in ((401, "failed"), (302, "unsupported")):
                result = providers.check(connection)
                self.assertEqual(result["check"]["status"], expected)
                self.assertIsNone(result["models"])
            self.assertEqual(len(requests), 4)

    def test_openrouter_batch_catalog_survives_reopen_and_host_changes_cannot_reprice_saved_work(
        self,
    ):
        # Switching a saved model/host must resolve Batch support without a
        # second account check; draft reads and late replies cannot change it.
        from dazedtl.api.server import Application

        model, other = "author/model", "author/other"
        metadata = {
            "values": {
                "language": "English",
                "model": model,
                "api": "",
                "API_PROVIDER": "openai",
            }
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            allow_providers=True,
            validate_route=lambda _: None,
            provider_defaults=lambda _: {"batch_supported": False},
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        adapter.lock = threading.RLock()
        adapter.context = lambda: adapter.lock
        app = Application.__new__(Application)
        app.backend, app.closing = adapter, False
        app.translation = SimpleNamespace(
            engine=SimpleNamespace(context=lambda: adapter.lock)
        )
        state = {
            "version": 2,
            "revision": 0,
            "values": {"language": "English", "model": model},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "",
            "draft": None,
            "connections": [],
        }
        row = {
            "input": 2,
            "output": 8,
            "cache_read": None,
            "cache_write": None,
            "text": True,
            "json": True,
            "context": 32000,
            "max_output": 4096,
        }
        checked = {
            "check": {
                "status": "verified",
                "message": "Checked",
                "checkedAt": "2026-10-05T12:00:00+00:00",
            },
            "models": [model, other],
            "catalog": {
                model: row,
                model + ":batch": {**row, "input": 0.8, "output": 3},
                other: row,
                other + ":batch": row,
            },
            "batch_endpoints": {
                "model": model,
                "host": "",
                "providers": ["supported"],
                "rates": {
                    "input": 0.8,
                    "output": 3,
                    "cache_read": None,
                    "cache_write": None,
                },
            },
        }
        with TemporaryDirectory() as directory:
            write_json(Path(directory) / "settings/settings.json", state)
            settings = Settings(directory, adapter)
            app.settings = settings
            view = settings.save_connection(0, "openrouter", secret="fixture-key")
            identity = view["activeConnectionId"]
            view = settings.save(
                view["revision"],
                identity,
                {"language": "English", "model": model, "sourceLanguage": "Japanese"},
                {},
            )
            self.assertFalse(settings.translation_defaults()["batch_supported"])
            with patch.object(providers, "check", return_value=checked):
                view = settings.check_connection(view["revision"], identity)
            settings = Settings(directory, adapter)
            app.settings = settings
            with patch.object(
                httpx,
                "Client",
                side_effect=AssertionError("Observations cannot contact a provider."),
            ):
                self.assertTrue(settings.translation_defaults()["batch_supported"])
                self.assertEqual(
                    settings.model_defaults(identity, model)["batchInputRate"], 0.8
                )
                frozen = configuration(settings, "batch")
                settings.prepare_engine("batch")
                self.assertEqual(
                    adapter.manual.request_policy["openrouterBatch"],
                    frozen["openrouterBatch"],
                )
                self.assertEqual(
                    adapter.manual.request_policy["openrouterStructuredOutputs"],
                    openrouter.STRUCTURED_OUTPUTS,
                )
                self.assertEqual(
                    frozen["openrouterStructuredOutputs"], openrouter.STRUCTURED_OUTPUTS
                )
                self.assertNotIn("catalog", settings.describe()["connections"][0])
            original = deepcopy(frozen)
            endpoints = {
                **checked["batch_endpoints"],
                "model": other,
                "rates": {**checked["batch_endpoints"]["rates"], "input": 1.1},
            }
            with (
                patch.object(
                    providers,
                    "check",
                    side_effect=AssertionError(
                        "Do not recheck the account on model selection."
                    ),
                ),
                patch.object(
                    openrouter, "check_endpoints", return_value=endpoints
                ) as fetch,
            ):
                result = app.settings_model_defaults(identity, other)
                self.assertTrue(result["batchSupported"])
                self.assertEqual(result["batchInputRate"], 1.1)
                self.assertEqual(settings.describe()["values"]["model"], model)
                self.assertEqual(
                    settings.model_defaults(identity, model)["batchInputRate"], 0.8
                )
                view = settings.save(
                    view["revision"],
                    identity,
                    {
                        "language": "English",
                        "model": other,
                        "sourceLanguage": "Japanese",
                    },
                    {},
                )
                app.resolve_batch_support(persist=True)
                self.assertEqual(fetch.call_args.args[0]["model"], other)
                self.assertEqual(
                    configuration(settings, "batch")["openrouterBatch"]["input"], 1.1
                )
                app.resolve_batch_support(persist=True)
                self.assertEqual(
                    fetch.call_count, 2
                )  # Saved metadata is reused on a revisit.
            settings = Settings(directory, adapter)
            app.settings = settings
            with patch.object(
                httpx,
                "Client",
                side_effect=AssertionError(
                    "Reopening/observations cannot contact a provider."
                ),
            ):
                self.assertTrue(settings.translation_defaults()["batch_supported"])
                self.assertEqual(
                    settings.model_defaults(identity, other)["batchInputRate"], 1.1
                )
            view = settings.save(
                view["revision"],
                identity,
                {"language": "English", "model": model, "sourceLanguage": "Japanese"},
                {},
            )
            view = settings.save_connection(
                view["revision"],
                "openrouter",
                connection_id=identity,
                openrouter_host="deepinfra",
            )
            self.assertFalse(settings.translation_defaults()["batch_supported"])
            with self.assertRaises(ValueError):
                configuration(settings, "batch")
            endpoints = {
                "model": model,
                "host": "deepinfra",
                "providers": ["deepinfra"],
                "rates": {
                    "input": 1.2,
                    "output": 4,
                    "cache_read": None,
                    "cache_write": None,
                },
            }
            with patch.object(openrouter, "check_endpoints", return_value=endpoints):
                app.resolve_batch_support(persist=True)
            settings.retain_prices(
                settings.pricing_lookup(),
                {
                    "model": model,
                    "host": "deepinfra",
                    "inputRate": 2.4,
                    "outputRate": 9,
                    "source": "catalog",
                    "updatedAt": checked["check"]["checkedAt"],
                    "stale": False,
                },
            )
            self.assertEqual(
                configuration(settings, "batch")["openrouterBatch"]["input"], 1.2
            )
            self.assertEqual(configuration(settings, "live")["rates"]["input"], 2.4)
            self.assertEqual(frozen, original)
            self.assertEqual(worker_secret(Path(directory), frozen), "fixture-key")

            # A stalled endpoint read leaves settings observable and cannot
            # publish after a different model, host, key or catalog is selected.
            view = settings.save(
                view["revision"],
                identity,
                {"language": "English", "model": other, "sourceLanguage": "Japanese"},
                {},
            )
            lookup = settings.batch_lookup()
            for change in (
                {"model": model},
                {"openrouter_host": "novita"},
                {"secret": "replacement"},
                {"catalog": {}},
                {"check": providers.unchecked()},
            ):
                stale = deepcopy(lookup)
                stale["connection"].update(change)
                self.assertIsNone(
                    settings.retain_batch_endpoints(stale, endpoints, persist=True)
                )
            started, release, failures = threading.Event(), threading.Event(), []

            def slow_check(connection, _known):
                started.set()
                self.assertTrue(release.wait(1))
                return {**endpoints, "model": connection["model"]}

            def resolve():
                try:
                    app.resolve_batch_support(persist=True)
                except Exception as error:
                    failures.append(error)

            with patch.object(openrouter, "check_endpoints", side_effect=slow_check):
                worker = threading.Thread(target=resolve)
                worker.start()
                try:
                    self.assertTrue(started.wait(1))
                    acquired = adapter.lock.acquire(timeout=0.1)
                    self.assertTrue(
                        acquired, "A stalled Batch check held the application lock."
                    )
                    if acquired:
                        try:
                            view = settings.save(
                                view["revision"],
                                identity,
                                {
                                    "language": "English",
                                    "model": model,
                                    "sourceLanguage": "Japanese",
                                },
                                {},
                            )
                            self.assertTrue(
                                settings.translation_defaults()["batch_supported"]
                            )
                        finally:
                            adapter.lock.release()
                finally:
                    release.set()
                    worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertTrue(settings.translation_defaults()["batch_supported"])
            self.assertEqual(
                settings.model_defaults(identity, model)["batchInputRate"], 1.2
            )
            # No endpoint lookup can infer eligibility for an absent model or
            # bypass offline mode and initial account authentication.
            self.assertIsNone(settings.batch_lookup(model="author/absent"))
            adapter.allow_providers = False
            self.assertIsNone(settings.batch_lookup(model=other))
            adapter.allow_providers = True
            view = settings.save_connection(
                view["revision"],
                "openrouter",
                connection_id=identity,
                secret="replacement",
            )
            self.assertIsNone(settings.batch_lookup(model=other))

    def test_pinned_batch_endpoint_prices_do_not_fall_back_and_outages_preserve_authentication(
        self,
    ):
        # A host's price can differ from the model minimum, and a Batch
        # metadata failure must not discard successful key authentication.
        model, status, calls = "author/model", 200, []
        parameters = ["response_format", "structured_outputs"]
        row = {
            "id": model,
            "pricing": {"prompt": ".000002", "completion": ".000008"},
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["response_format"],
        }
        connection = {
            "provider": "openrouter",
            "protocol": "openai",
            "endpoint": "",
            "model": model,
            "openrouter_host": "deepinfra",
            "keyless": False,
            "secret": "fixture-key",
            "organization": "",
        }

        def respond(request):
            calls.append(request)
            if request.url.path.endswith("/models/user"):
                return httpx.Response(
                    200,
                    stream=httpx.ByteStream(
                        json.dumps(
                            {"data": [row, {**row, "id": model + ":batch"}]}
                        ).encode()
                    ),
                )
            return httpx.Response(
                status,
                json={
                    "data": {
                        "id": model + ":batch",
                        "endpoints": [
                            {
                                "tag": "deepinfra",
                                "pricing": {
                                    "prompt": ".0000012",
                                    "completion": ".000004",
                                },
                                "supported_parameters": parameters,
                            },
                            {
                                "tag": "other",
                                "pricing": {
                                    "prompt": ".0000001",
                                    "completion": ".0000002",
                                },
                                "supported_parameters": ["response_format"],
                            },
                        ],
                    }
                },
            )

        client = httpx.Client
        with patch.object(
            httpx,
            "Client",
            side_effect=lambda **kwargs: client(
                transport=httpx.MockTransport(respond), **kwargs
            ),
        ):
            checked = providers.check(connection)
            self.assertEqual(checked["check"]["status"], "verified")
            self.assertEqual(
                openrouter.describe({**connection, **checked}, model)["batchInputRate"],
                1.2,
            )
            self.assertEqual(
                str(calls[1].url),
                "https://openrouter.ai/api/v1/models/author/model:batch/endpoints",
            )
            parameters.remove("structured_outputs")
            unsupported = providers.check(connection)
            self.assertFalse(
                openrouter.describe({**connection, **unsupported}, model)[
                    "batchSupported"
                ]
            )
            status = 500
            checked = providers.check(connection)
            self.assertEqual(checked["check"]["status"], "verified")
            defaults = openrouter.describe({**connection, **checked}, model)
            self.assertIsNone(
                defaults["inputRate"]
            )  # Batch metadata cannot establish this host's Live price.
            self.assertFalse(defaults["batchSupported"])
            self.assertIn("Check the connection again", defaults["batchReason"])
            self.assertTrue(all(request.method == "GET" for request in calls))

    def test_legacy_verified_openrouter_prices_load_before_estimation_without_locking_observers_or_crossing_hosts(
        self,
    ):
        # Existing verified connections lack the new catalog. Explicit
        # estimation must repair that gap while snapshots remain read-only;
        # a late price response cannot price a newly selected host.
        from dazedtl.api.server import Application

        model = "author/model"
        metadata = {
            "values": {
                "language": "English",
                "model": model,
                "api": "",
                "API_PROVIDER": "openai",
            }
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            allow_providers=True,
            lock=threading.RLock(),
            validate_route=lambda _: None,
            provider_defaults=lambda _: {"batch_supported": False},
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        state = {
            "version": 2,
            "revision": 0,
            "values": {"language": "English", "model": model},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "",
            "draft": None,
            "connections": [],
        }
        prices = {
            "model": model,
            "host": "darkbloom",
            "inputRate": 0.1,
            "outputRate": 0.28,
            "source": "catalog",
            "updatedAt": "now",
            "stale": False,
        }
        with TemporaryDirectory() as directory:
            write_json(Path(directory) / "settings/settings.json", state)
            settings = Settings(directory, adapter)
            view = settings.save_connection(
                0, "openrouter", secret="fixture-secret", openrouter_host="darkbloom"
            )
            identity = view["activeConnectionId"]
            view = settings.save(
                view["revision"],
                identity,
                {"language": "English", "model": model, "sourceLanguage": "Japanese"},
                {},
            )
            with patch.object(
                providers,
                "check",
                return_value={
                    "check": {
                        "status": "verified",
                        "message": "Checked",
                        "checkedAt": "now",
                    },
                    "models": [model],
                },
            ):
                view = settings.check_connection(view["revision"], identity)
            self.assertIsNone(settings.model_defaults(identity, model)["inputRate"])
            app = SimpleNamespace(backend=adapter, settings=settings, closing=False)
            started, release = threading.Event(), threading.Event()
            failures = []

            def lookup(*_args):
                started.set()
                self.assertTrue(release.wait(1))
                return prices

            def prepare():
                try:
                    Application.prepare_model_pricing(
                        app, "guided_preview", {"action": "start"}
                    )
                except Exception as error:
                    failures.append(error)

            with patch.object(openrouter, "live_prices", side_effect=lookup) as fetch:
                for operation in ("workspace_snapshot", "navigate", "guided_state"):
                    Application.prepare_model_pricing(app, operation, {})
                fetch.assert_not_called()
                worker = threading.Thread(target=prepare)
                worker.start()
                try:
                    self.assertTrue(started.wait(1))
                    acquired = adapter.lock.acquire(timeout=0.1)
                    self.assertTrue(
                        acquired, "A stalled price read held the application lock."
                    )
                    if acquired:
                        try:
                            self.assertEqual(
                                settings.describe()["values"]["model"], model
                            )
                            view = settings.save_connection(
                                view["revision"],
                                "openrouter",
                                connection_id=identity,
                                openrouter_host="novita",
                            )
                        finally:
                            adapter.lock.release()
                finally:
                    release.set()
                    worker.join(1)
            self.assertEqual(len(failures), 1)
            self.assertIn("changed while reading prices", str(failures[0]))
            self.assertIsNone(settings.model_defaults(identity, model)["inputRate"])
            with patch.object(
                openrouter,
                "live_prices",
                return_value={**prices, "host": "novita", "inputRate": 0.14},
            ) as fetch:
                Application.prepare_model_pricing(
                    app, "guided_preview", {"action": "start"}
                )
                frozen = configuration(settings, "live")
                self.assertEqual(frozen["rates"]["input"], 0.14)
                self.assertEqual(frozen["openrouterHost"], "novita")
                settings.prepare_engine("estimate")
                self.assertEqual(adapter.manual.request_policy["inputRate"], 0.14)
                Application.prepare_model_pricing(
                    app,
                    "settings_model_defaults",
                    {"connection_id": identity, "model": model},
                )
                fetch.assert_called_once_with(model, "novita")
                self.assertFalse(settings.translation_defaults()["batch_supported"])
            cache_key = (identity, model, "novita")
            # An hour old; a monotonic clock's zero can be minutes ago.
            settings._openrouter_prices[cache_key] = (
                time.monotonic() - 3600,
                settings._openrouter_prices[cache_key][1],
            )
            with patch.object(
                openrouter, "live_prices", side_effect=ValueError("Catalog unavailable")
            ):
                Application.prepare_model_pricing(
                    app, "guided_preview", {"action": "start"}
                )
            self.assertTrue(settings.model_defaults(identity, model)["stale"])
            self.assertEqual(configuration(settings, "live")["rates"], frozen["rates"])

    def test_public_live_price_lookup_matches_host_variants_and_never_uses_another_host_price(
        self,
    ):
        # Hosts publish endpoint tags such as darkbloom/fp4. Pinning the base
        # host must match those prices, even when another host is cheaper.
        model, calls = "author/model", []
        rows = [
            {
                "tag": "darkbloom/fp4",
                "pricing": {"prompt": ".0000001", "completion": ".00000028"},
                "max_completion_tokens": 16384,
            },
            {
                "tag": "novita/fp8",
                "pricing": {"prompt": ".00000001", "completion": ".00000002"},
                "max_completion_tokens": 65536,
            },
        ]

        def respond(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": model,
                        "endpoints": rows,
                        "pricing": {"prompt": ".00000014", "completion": ".00000028"},
                    }
                },
            )

        client = httpx.Client
        with patch.object(
            httpx,
            "Client",
            side_effect=lambda **kwargs: client(
                transport=httpx.MockTransport(respond), **kwargs
            ),
        ):
            prices = openrouter.live_prices(model, "darkbloom")
            self.assertEqual((prices["inputRate"], prices["outputRate"]), (0.1, 0.28))
            self.assertEqual(prices["maxOutputTokens"], 16384)
            self.assertEqual(
                str(calls[-1].url),
                "https://openrouter.ai/api/v1/models/author/model/endpoints",
            )
            with self.assertRaisesRegex(ValueError, "No complete OpenRouter price"):
                openrouter.live_prices(model, "missing-host")
            self.assertEqual(openrouter.live_prices(model)["inputRate"], 0.14)
            self.assertEqual(
                str(calls[-1].url), "https://openrouter.ai/api/v1/model/author/model"
            )
            self.assertTrue(
                all(
                    request.method == "GET" and "Authorization" not in request.headers
                    for request in calls
                )
            )

    def test_batch_allowance_survives_drafts_and_model_connection_switches_without_changing_saved_runs(
        self,
    ):
        # Protect against silently losing the allowance in an older settings
        # record, applying another connection's value, or changing a frozen run.
        legacy_options = {
            "entriesPerRequest": None,
            "pricing": "custom",
            "inputRate": 1,
            "outputRate": 2,
        }
        connection = {
            "id": "first",
            "runtime_name": "first-key",
            "name": "First",
            "provider": "openai",
            "protocol": "openai",
            "endpoint": "",
            "secret": "fixture-secret",
            "keyless": False,
            "organization": "",
            "model": "model-one",
            "model_options": {"model-one": legacy_options},
            "models": [],
            "check": providers.unchecked(),
        }
        metadata = {
            "values": {
                "language": "English",
                "model": "model-one",
                "api": "",
                "API_PROVIDER": "openai",
            }
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata,
            allow_providers=False,
            validate_route=lambda _: None,
            provider_defaults=lambda _: {"batch_supported": True},
            model_defaults=SimpleNamespace(
                cached=lambda model: (
                    {"maxOutputTokens": 8192} if model == "model-two" else {}
                )
            ),
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        state = {
            "version": 3,
            "revision": 0,
            "sourceLanguage": "Japanese",
            "values": {"language": "English", "model": "model-one"},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "first",
            "draft": None,
            "connections": [
                connection,
                {
                    **deepcopy(connection),
                    "id": "second",
                    "runtime_name": "second-key",
                    "name": "Second",
                },
            ],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings/settings.json"
            write_json(path, state)
            original = path.read_bytes()
            settings = Settings(temporary, adapter)
            view = settings.describe()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"],
                view["defaultBatchInputTokens"],
            )
            settings.prepare_engine("batch")
            frozen_default = deepcopy(adapter.manual.request_policy)
            self.assertEqual(
                frozen_default["batchInputTokens"], view["defaultBatchInputTokens"]
            )
            self.assertEqual(frozen_default["maxOutputTokens"], 32768)
            self.assertEqual(configuration(settings, "live")["maxOutputTokens"], 32768)
            options = {
                "model-one": {
                    **legacy_options,
                    "batchInputTokens": 8_000_000,
                    "maxOutputTokens": 65536,
                },
                "model-two": {
                    **legacy_options,
                    "batchInputTokens": 2_000_000,
                    "maxOutputTokens": 16384,
                },
            }
            settings.draft(view["revision"], "first", view["values"], options)
            settings = Settings(temporary, adapter)
            self.assertEqual(settings.describe()["draft"]["modelOptions"], options)
            # Another connection's draft must not block this one's model menu.
            other = settings.select(view["revision"], "second")
            self.assertNotIn("draft", other)
            view = settings.select(other["revision"], "first")
            self.assertEqual(view["draft"]["modelOptions"], options)
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"],
                frozen_default["batchInputTokens"],
            )
            self.assertEqual(configuration(settings, "live")["maxOutputTokens"], 32768)
            view = settings.save(view["revision"], "first", view["values"], options)
            settings.prepare_engine("batch")
            frozen = deepcopy(adapter.manual.request_policy)
            # A run freezes how its replies are read, which its estimate's
            # identity leaves out, so the estimate stays current.
            self.assertEqual(frozen["smallKana"], preferences.SMALL_KANA)
            self.assertNotIn("smallKana", settings.guided_configuration("batch"))
            self.assertEqual(frozen["batchInputTokens"], 8_000_000)
            self.assertEqual(frozen["maxOutputTokens"], 65536)
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"], 8_000_000
            )
            view = settings.save(
                view["revision"],
                "first",
                {**view["values"], "model": "model-two"},
                options,
            )
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"], 2_000_000
            )
            self.assertEqual(configuration(settings, "live")["maxOutputTokens"], 8192)
            settings.prepare_engine("translate")
            self.assertEqual(adapter.manual.request_policy["maxOutputTokens"], 8192)
            self.assertEqual(frozen_default["maxOutputTokens"], 32768)
            view = settings.select(view["revision"], "second")
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"],
                frozen_default["batchInputTokens"],
            )
            view = settings.select(view["revision"], "first")
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"], 2_000_000
            )
            view = settings.save(
                view["revision"],
                "first",
                view["values"],
                {**options, "model-two": {**legacy_options, "batchInputTokens": None}},
            )
            self.assertEqual(
                configuration(settings, "batch")["batchInputTokens"],
                frozen_default["batchInputTokens"],
            )
            # A later default change affects future preparation, never an
            # existing plan's recorded default or an explicit model override.
            with patch.object(preferences, "DEFAULT_BATCH_INPUT_TOKENS", 350_000):
                settings.prepare_engine("batch")
                self.assertEqual(
                    adapter.manual.request_policy["batchInputTokens"], 350_000
                )
                self.assertEqual(
                    configuration(settings, "batch")["batchInputTokens"], 350_000
                )
            self.assertEqual(
                frozen_default["batchInputTokens"], view["defaultBatchInputTokens"]
            )
            self.assertEqual(frozen["batchInputTokens"], 8_000_000)
            self.assertNotIn("fixture-secret", str(view))
        for invalid in (0, -1, True, 1.5, "8000000", 9_007_199_254_740_992):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                preferences.options({**legacy_options, "batchInputTokens": invalid})

    def test_a_thinking_effort_is_sent_only_where_its_model_takes_it(self):
        # A level a provider rejects fails a paid run, so a choice reaches a
        # request only when its provider, exact model and level are a row of
        # the effort table; a saved level the model stops taking reads as the
        # provider default, and a run without a choice keeps its settings.
        from dazedtl.compatibility.translation import request_payload
        from dazedtl.settings import effort

        self.assertEqual(
            effort.describe("anthropic", "claude-opus-5-5")["options"][:2],
            [
                {"value": None, "label": "Provider default (Medium)"},
                {"value": "low", "label": "Low"},
            ],
        )
        for provider, model in (
            ("custom", "gpt-6.1-sol"),
            ("openai", "gpt-6.1-sol-2026-09-01"),
            ("openrouter", "anthropic/claude-haiku-4.5"),
        ):
            self.assertEqual(effort.levels(provider, model), ())
        # Routed models offer only what both their own provider and
        # OpenRouter list: Opus 5.5 never turns thinking off.
        self.assertNotIn(
            "none", effort.levels("openrouter", "anthropic/claude-opus-5.5")
        )
        self.assertNotIn("none", effort.levels("kimi", "kimi-k3"))
        sent = {"model": "m", "temperature": 0, "frequency_penalty": 0.05}
        for provider, model, level, written in (
            (
                "anthropic",
                "claude-opus-5-5",
                "low",
                {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
            ),
            (
                "anthropic",
                "claude-opus-4-8",
                "none",
                {"thinking": {"type": "disabled"}},
            ),
            # Sonnet 5.5 refuses "disabled".
            (
                "anthropic",
                "claude-sonnet-5-5",
                "none",
                {"thinking": {"type": "between_tools"}},
            ),
            ("openai", "gpt-6.1-sol", "xhigh", {"reasoning_effort": "xhigh"}),
            (
                "gemini",
                "models/gemini-3.1-pro-preview",
                "low",
                {"reasoning_effort": "low"},
            ),
            ("deepseek", "deepseek-flash", "max", {"reasoning_effort": "max"}),
            (
                "deepseek",
                "deepseek-flash",
                "none",
                {"extra_body": {"thinking": {"type": "disabled"}}},
            ),
            (
                "kimi",
                "kimi-k2.6",
                "none",
                {"extra_body": {"thinking": {"type": "disabled"}}},
            ),
            (
                "openrouter",
                "openai/gpt-6.1-sol",
                "high",
                {"extra_body": {"reasoning": {"effort": "high"}}},
            ),
        ):
            with self.subTest(provider=provider, model=model, level=level):
                # Sampling settings stay with thinking off and on Gemini.
                kept = sent if level == "none" or provider == "gemini" else {}
                self.assertEqual(
                    effort.apply(sent, provider, model, level),
                    {"model": "m", **kept, **written},
                )
                self.assertEqual(effort.thinks(provider, model, level), level != "none")
        for provider, model, level in (
            ("openai", "gpt-6.1-sol", "none"),
            ("openai", "gpt-4.1", "low"),
            ("custom", "local-model", "high"),
            ("anthropic", "claude-opus-5-5", None),
        ):
            self.assertIs(effort.apply(sent, provider, model, level), sent)
        # A Gemini thinking budget beside an effort is refused.
        self.assertEqual(
            effort.apply(
                {"extra_body": {"extra_body": {"google": {"thinking_config": {}}}}},
                "gemini",
                "gemini-2.5-flash",
                "low",
            ),
            {"reasoning_effort": "low"},
        )

        options = {
            "entriesPerRequest": None,
            "pricing": "custom",
            "inputRate": 1,
            "outputRate": 2,
        }
        connection = {
            "id": "first",
            "runtime_name": "first-key",
            "name": "First",
            "provider": "openai",
            "protocol": "openai",
            "endpoint": "",
            "secret": "fixture-secret",
            "keyless": False,
            "organization": "",
            "model": "gpt-6.1-sol",
            "model_options": {"gpt-6.1-sol": options},
            "models": [],
            "check": providers.unchecked(),
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: {
                "values": {
                    "language": "English",
                    "model": "gpt-6.1-sol",
                    "api": "",
                    "API_PROVIDER": "openai",
                }
            },
            allow_providers=False,
            validate_route=lambda _: None,
            provider_defaults=lambda _: {"batch_supported": True},
            model_defaults=SimpleNamespace(cached=lambda _model: {}),
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        state = {
            "version": 3,
            "revision": 0,
            "sourceLanguage": "Japanese",
            "values": {"language": "English", "model": "gpt-6.1-sol"},
            "legacy": {"values": {}, "engines": {}, "draft": None},
            "model_options": {},
            "active": "first",
            "draft": None,
            "connections": [connection],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings/settings.json"
            write_json(path, state)
            settings = Settings(temporary, adapter)
            view = settings.describe()
            # Without a choice a run freezes exactly the settings it froze
            # before, so waiting estimates stay current.
            self.assertNotIn("thinkingEffort", configuration(settings, "live"))
            with self.assertRaisesRegex(ValueError, "doesn't take thinking effort Off"):
                settings.save(
                    view["revision"],
                    "first",
                    view["values"],
                    {"gpt-6.1-sol": {**options, "thinkingEffort": "none"}},
                )
            with self.assertRaises(ValueError):
                preferences.options({**options, "thinkingEffort": "extreme"})
            view = settings.save(
                view["revision"],
                "first",
                view["values"],
                {"gpt-6.1-sol": {**options, "thinkingEffort": "high"}},
            )
            frozen = configuration(settings, "live")
            self.assertEqual(frozen["thinkingEffort"], "high")
            settings.prepare_engine("translate")
            self.assertEqual(adapter.manual.request_policy["thinkingEffort"], "high")
            # The Assistant-led request carries it as Guided's does.
            row = logical_request(
                {"id": "scene", "sources": {"line": "はい。"}},
                {
                    "user": "Lines:",
                    "system": "Translate.",
                    "glossary": "",
                    "sfx_reference": "",
                    "preceding_japanese_source_context": "",
                    "request_instructions": "",
                },
            )
            payload = request_payload(row, {**frozen, "lineKeys": LINE_KEYS})
            self.assertEqual(payload["reasoning_effort"], "high")
            self.assertNotIn("temperature", payload)
            self.assertNotIn(
                "reasoning_effort",
                request_payload(
                    row,
                    {
                        key: value
                        for key, value in frozen.items()
                        if key != "thinkingEffort"
                    }
                    | {"lineKeys": LINE_KEYS},
                ),
            )
            # A level the table stops holding stays saved, reads as the
            # provider default and does not block saving other options.
            with patch.dict(
                effort._NATIVE["openai"], {"gpt-6.1-sol": (("low",), "medium")}
            ):
                self.assertNotIn("thinkingEffort", configuration(settings, "live"))
                settings.prepare_engine("translate")
                self.assertNotIn("thinkingEffort", adapter.manual.request_policy)
                settings.save(
                    view["revision"],
                    "first",
                    view["values"],
                    {
                        "gpt-6.1-sol": {
                            **options,
                            "thinkingEffort": "high",
                            "maxOutputTokens": 4096,
                        }
                    },
                )

    def test_a_model_list_decides_which_efforts_its_models_take(self):
        # Where a provider's own model list says which efforts a model takes,
        # Settings and runs follow it instead of DazedTL's notes, never a mix
        # of both, so a level the provider stopped taking is never sent; rows
        # that say nothing, and connections checked before, keep the notes,
        # and a run keeps the record it froze.
        from dazedtl.compatibility.translation import request_payload
        from dazedtl.settings import effort

        full = ("low", "medium", "high", "xhigh", "max")

        def claude(model, levels=full, types=("adaptive",)):
            kinds = ("adaptive", "disabled", "between_tools", "enabled")
            return {
                "id": model,
                "capabilities": {
                    "effort": {
                        "supported": True,
                        **{level: {"supported": level in levels} for level in full},
                    },
                    "thinking": {
                        "supported": True,
                        "types": {kind: {"supported": kind in types} for kind in kinds},
                    },
                },
            }

        listed = effort.model_list(
            "anthropic",
            [
                claude("claude-opus-5-5"),
                claude("claude-sonnet-5-5", types=("adaptive", "between_tools")),
                # Narrower than the notes: no xhigh or max.
                claude(
                    "claude-opus-5", ("low", "medium", "high"), ("adaptive", "disabled")
                ),
                # Unknown to the notes, with effort but no adaptive thinking.
                claude("claude-opus-4-5", ("low", "medium", "high"), ("disabled",)),
                {
                    "id": "claude-haiku-4-5",
                    "capabilities": {"effort": {"supported": False}},
                },
                {"id": "no-capabilities"},
                {"id": "malformed", "capabilities": {"effort": {"supported": "yes"}}},
                {
                    "id": "no-thinking-types",
                    "capabilities": {"effort": {"supported": True}, "thinking": {}},
                },
                {"id": 7},
                "row",
            ],
        )
        self.assertEqual(
            sorted(listed),
            [
                "claude-haiku-4-5",
                "claude-opus-4-5",
                "claude-opus-5",
                "claude-opus-5-5",
                "claude-sonnet-5-5",
            ],
        )
        for record in listed.values():
            self.assertIs(effort.valid(record), record)
        self.assertEqual(effort.model_list("openai", [{"id": "gpt-6.1-sol"}]), {})
        sonnet, opus, older = (
            listed[model]
            for model in ("claude-sonnet-5-5", "claude-opus-5", "claude-opus-4-5")
        )
        self.assertEqual(sonnet["levels"], ["none", *full])
        self.assertEqual(
            effort.apply({}, "anthropic", "claude-sonnet-5-5", "none", sonnet),
            {"thinking": {"type": "between_tools"}},
        )
        self.assertFalse(effort.takes("anthropic", "claude-opus-5", "max", opus))
        sent = {"model": "claude-opus-5", "temperature": 0}
        self.assertIs(
            effort.apply(sent, "anthropic", "claude-opus-5", "max", opus), sent
        )
        # Anthropic's list names no default, so the notes' default stands.
        self.assertEqual(
            effort.describe("anthropic", "claude-opus-5", opus),
            {
                "options": [
                    {"value": None, "label": "Provider default (High)"},
                    {"value": "none", "label": "Off"},
                    {"value": "low", "label": "Low"},
                    {"value": "medium", "label": "Medium"},
                    {"value": "high", "label": "High"},
                ],
                "source": "From Anthropic's model list",
            },
        )
        self.assertEqual(
            effort.apply(sent, "anthropic", "claude-opus-4-5", "low", older),
            {"model": "claude-opus-5", "output_config": {"effort": "low"}},
        )
        # Sent alone, that effort turns no thinking on.
        self.assertFalse(effort.thinks("anthropic", "claude-opus-4-5", "low", older))
        self.assertEqual(
            effort.describe(
                "anthropic", "claude-haiku-4-5", listed["claude-haiku-4-5"]
            ),
            {
                "options": [{"value": None, "label": "Provider default"}],
                "source": "From Anthropic's model list",
            },
        )
        self.assertEqual(
            effort.describe("anthropic", "claude-opus-5").get("source"),
            "From DazedTL's model notes",
        )
        self.assertNotIn("source", effort.describe("custom", "local-model"))
        # Only Anthropic's and OpenRouter's lists say anything about effort.
        self.assertEqual(
            effort.levels("openai", "gpt-6.1-sol", older),
            effort.levels("openai", "gpt-6.1-sol"),
        )

        routed = effort.model_list(
            "openrouter",
            [
                {
                    "id": "anthropic/claude-opus-5.5",
                    "supported_parameters": ["reasoning", "response_format"],
                    "reasoning": {
                        "supported_efforts": ["max", "high", "low", "none"],
                        "default_effort": "high",
                        "mandatory": True,
                    },
                },
                {
                    "id": "z-ai/glm-6",
                    "reasoning": {
                        "supported_efforts": ["high", "extreme", None, "low"],
                        "default_enabled": False,
                    },
                },
                {"id": "openai/gpt-4.1", "supported_parameters": ["response_format"]},
                {"id": "x/no-allowlist", "reasoning": {"supported_efforts": None}},
                {"id": "x/malformed", "reasoning": "high"},
                {"id": "x/other-field", "supported_parameters": ["reasoning_effort"]},
            ],
        )
        self.assertEqual(
            routed,
            {
                "anthropic/claude-opus-5.5": {
                    "levels": ["low", "high", "max"],
                    "default": "high",
                    "off": None,
                    "adaptive": False,
                },
                "z-ai/glm-6": {
                    "levels": ["low", "high"],
                    "default": "none",
                    "off": None,
                    "adaptive": False,
                },
                "openai/gpt-4.1": {
                    "levels": [],
                    "default": None,
                    "off": None,
                    "adaptive": False,
                },
            },
        )
        glm = routed["z-ai/glm-6"]
        self.assertEqual(
            [
                option["label"]
                for option in effort.describe("openrouter", "z-ai/glm-6", glm)[
                    "options"
                ]
            ],
            ["Provider default (Off)", "Low", "High"],
        )
        self.assertEqual(
            effort.apply({}, "openrouter", "z-ai/glm-6", "high", glm),
            {"extra_body": {"reasoning": {"effort": "high"}}},
        )
        # The notes would offer Medium for Opus 5.5; OpenRouter's list does not.
        self.assertFalse(
            effort.takes(
                "openrouter",
                "anthropic/claude-opus-5.5",
                "medium",
                routed["anthropic/claude-opus-5.5"],
            )
        )
        self.assertEqual(
            effort.summary("openrouter", "z-ai/glm-6", None, glm),
            "Provider default (Off)",
        )

        # A run freezes the record only where it, not the notes, decides what
        # the run sends or the default its review names.
        self.assertEqual(
            effort.frozen(
                "anthropic",
                "claude-opus-5-5",
                {"thinkingEffort": "low"},
                listed["claude-opus-5-5"],
            ),
            {"thinkingEffort": "low"},
        )
        self.assertEqual(effort.frozen("anthropic", "claude-opus-4-5", {}, older), {})
        self.assertEqual(
            effort.frozen(
                "anthropic", "claude-opus-4-5", {"thinkingEffort": "low"}, older
            ),
            {"thinkingEffort": "low", "thinkingEffortListed": older},
        )
        self.assertEqual(
            effort.frozen("openrouter", "z-ai/glm-6", {}, glm),
            {"thinkingEffortListed": glm},
        )
        for invalid in (
            {**older, "levels": ["low", "low"]},
            {**older, "levels": ["high", "low"]},
            {**older, "default": "extreme"},
            {**older, "off": "sometimes"},
            {**older, "adaptive": 1},
            {**older, "extra": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                effort.valid(invalid)
        with self.assertRaises(ValueError):
            effort.valid_list({"": older})

        options = {
            "entriesPerRequest": None,
            "pricing": "custom",
            "inputRate": 1,
            "outputRate": 2,
        }
        connection = {
            "id": "first",
            "runtime_name": "first-key",
            "name": "First",
            "provider": "anthropic",
            "protocol": "anthropic",
            "endpoint": "",
            "secret": "fixture-secret",
            "keyless": False,
            "organization": "",
            "model": "claude-opus-4-5",
            "model_options": {"claude-opus-4-5": options},
            "models": [],
            "check": providers.unchecked(),
        }
        adapter = SimpleNamespace(
            settings_metadata=lambda: {
                "values": {
                    "language": "English",
                    "model": "claude-opus-4-5",
                    "api": "",
                    "API_PROVIDER": "anthropic",
                }
            },
            allow_providers=True,
            validate_route=lambda _: None,
            provider_defaults=lambda _: {"batch_supported": True},
            model_defaults=SimpleNamespace(
                cached=lambda _model: {}, describe=lambda _model: {}
            ),
            manual=SimpleNamespace(request_policy=None),
            install_settings=Mock(),
        )
        state = {
            "version": 3,
            "revision": 0,
            "sourceLanguage": "Japanese",
            "values": {"language": "English", "model": "claude-opus-4-5"},
            "legacy": {"values": {}, "engines": {}, "draft": None},
            "model_options": {},
            "active": "first",
            "draft": None,
            "connections": [connection],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings/settings.json"
            write_json(path, state)
            settings = Settings(temporary, adapter)
            view = settings.describe()
            # A connection checked before records were kept: the notes,
            # which don't know this model, decide.
            self.assertEqual(
                settings.model_defaults("first", "claude-opus-4-5")["thinkingEffort"],
                {"options": [{"value": None, "label": "Provider default"}]},
            )
            with self.assertRaisesRegex(ValueError, "doesn't take thinking effort Low"):
                settings.save(
                    view["revision"],
                    "first",
                    view["values"],
                    {"claude-opus-4-5": {**options, "thinkingEffort": "low"}},
                )
            checked = {
                "check": {
                    "status": "verified",
                    "message": "Authentication verified.",
                    "checkedAt": "2026-10-28T00:00:00+00:00",
                },
                "models": ["claude-opus-4-5"],
                "efforts": {"claude-opus-4-5": older},
            }
            with patch.object(providers, "check", return_value=checked):
                view = settings.check_connection(view["revision"], "first")
            self.assertEqual(
                settings.model_defaults("first", "claude-opus-4-5")["thinkingEffort"][
                    "source"
                ],
                "From Anthropic's model list",
            )
            view = settings.save(
                view["revision"],
                "first",
                view["values"],
                {"claude-opus-4-5": {**options, "thinkingEffort": "low"}},
            )
            frozen = configuration(settings, "live")
            self.assertEqual(frozen["thinkingEffortListed"], older)
            settings.prepare_engine("translate")
            self.assertEqual(
                adapter.manual.request_policy["thinkingEffortListed"], older
            )
            row = logical_request(
                {"id": "scene", "sources": {"line": "はい。"}},
                {
                    "user": "Lines:",
                    "system": "Translate.",
                    "glossary": "",
                    "sfx_reference": "",
                    "preceding_japanese_source_context": "",
                    "request_instructions": "",
                },
            )
            payload = request_payload(row, {**frozen, "lineKeys": LINE_KEYS})
            self.assertEqual(payload["output_config"]["effort"], "low")
            self.assertNotIn("thinking", payload)
            # A later check that drops the level leaves the frozen run as it
            # was, and new runs fall back to the provider default.
            with patch.object(
                providers,
                "check",
                return_value={
                    **checked,
                    "efforts": {"claude-opus-4-5": {**older, "levels": ["high"]}},
                },
            ):
                settings.check_connection(view["revision"], "first")
            self.assertEqual(
                request_payload(row, {**frozen, "lineKeys": LINE_KEYS})[
                    "output_config"
                ]["effort"],
                "low",
            )
            self.assertNotIn("thinkingEffort", configuration(settings, "live"))
            # The saved records survive a reload.
            reloaded = Settings(temporary, adapter)._read()["connections"][0]
            self.assertEqual(reloaded["efforts"]["claude-opus-4-5"]["levels"], ["high"])

    def test_compiled_batch_limits_use_the_frozen_allowance_only_for_native_openai(
        self,
    ):
        # Guided and compiled plans must agree on the token allowance; ordinary
        # request/byte limits and other providers retain their own behavior.
        translation, batches = (
            ModuleType(name) for name in ("util.translation", "util.batch_providers")
        )
        translation._openai_batch_token_limit = lambda: 600_000
        batches.batch_limits = lambda _: (50_000, 200_000_000)
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.batch_supported = lambda _: "openai"
        with replaced_modules({item.__name__: item for item in (translation, batches)}):
            config = {
                "protocol": "openai",
                "endpoint": "https://api.openai.com/v1",
                "batchInputTokens": 8_000_000,
            }
            self.assertEqual(
                engine.batch_limits(config), [50_000, 200_000_000, 8_000_000]
            )
            self.assertEqual(
                engine.batch_limits({**config, "batchInputTokens": None})[-1], 600_000
            )
            self.assertIsNone(
                engine.batch_limits(
                    {**config, "endpoint": "https://fixture.invalid/v1"}
                )[-1]
            )
            self.assertIsNone(
                engine.batch_limits({**config, "protocol": "anthropic"})[-1]
            )

    def test_model_output_limits_survive_catalog_filtering_without_borrowing_a_fuzzy_price_match(
        self,
    ):
        # Price fallbacks may match related model names, but an output limit
        # must be bound to the selected model and never inferred from a price.
        from dazedtl.compatibility.pricing_worker import catalog, model_output_limit

        values = catalog(
            {
                "model-small": {
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                    "max_output_tokens": 8192,
                },
                "model-large": {
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                    "max_output_tokens": 65536,
                },
                "model-bad": {
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                    "max_output_tokens": True,
                },
            }
        )
        self.assertEqual(model_output_limit(values, "author/model-small"), 8192)
        self.assertEqual(model_output_limit(values, "models/model-large"), 65536)
        self.assertIsNone(model_output_limit(values, "model-small-other"))
        self.assertIsNone(model_output_limit(values, "model-bad"))

    def test_a_models_looked_up_prices_outlast_a_restart_for_snapshots(self):
        # Snapshots compare estimates with cached prices only. Kept in memory,
        # they were gone after every restart, so estimates priced for another
        # model read Outdated until something looked them up again.
        from dazedtl.compatibility.model_defaults import ModelDefaults

        found = {"model": "fixture-model", "inputRate": 1.0, "outputRate": 2.0}
        with (
            TemporaryDirectory() as temporary,
            patch(
                "dazedtl.compatibility.model_defaults.subprocess.run",
                return_value=SimpleNamespace(stdout=json.dumps(found)),
            ),
        ):
            folder = Path(temporary) / "model-cache"
            self.assertEqual(ModelDefaults(folder, False).cached("fixture-model"), {})
            self.assertEqual(
                ModelDefaults(folder, False).describe("fixture-model"), found
            )
            self.assertEqual(
                ModelDefaults(folder, False).cached("fixture-model"), found
            )

    def test_a_slow_price_catalog_download_ends_at_its_deadline(self):
        # The download's own limits let a slow link run past the 12 seconds
        # its caller waits, so prices never loaded and the catalog was never
        # saved for the next lookup.
        from dazedtl.compatibility import pricing_worker

        release = threading.Event()

        class Stalled:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def stream(self, *_args, **_kwargs):
                release.wait(5)
                raise httpx.ConnectError("released")

        with (
            patch.object(httpx, "Client", Stalled),
            patch.object(pricing_worker, "DOWNLOAD_SECONDS", 0.05),
        ):
            started = time.monotonic()
            try:
                self.assertIsNone(pricing_worker.download("https://catalog.invalid"))
            finally:
                release.set()
        self.assertLess(time.monotonic() - started, 1)

    def test_settings_from_before_the_source_read_japanese_and_refuse_one_script_pairs(
        self,
    ):
        # Upgrading must keep every existing run Japanese, freezing nothing
        # new into its settings, while a pair a run can't tell apart is
        # refused before it is saved.
        metadata = {"values": {"language": "English", "model": "fixture-model"}}
        adapter = SimpleNamespace(
            settings_metadata=lambda: metadata, allow_providers=False
        )
        state = {
            "version": 2,
            "revision": 0,
            "values": {"language": "English", "model": "fixture-model"},
            "legacy": {"values": metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
            "active": "",
            "draft": None,
            "connections": [],
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings/settings.json"
            write_json(path, state)
            settings = Settings(temporary, adapter)
            self.assertEqual(settings.source_language(), "Japanese")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 3)
            self.assertEqual(
                configuration(settings, "agent"),
                {
                    "mode": "agent",
                    "language": "English",
                    "model": "",
                    "connection_id": "",
                    "entries_per_request": None,
                },
            )
            english = {"source": "English", "target": "Japanese"}
            frozen = configuration(settings, "agent", pair=english)
            self.assertEqual(
                (frozen["language"], frozen["sourceLanguage"]), ("Japanese", "English")
            )
            japanese = {
                "language": "Japanese",
                "model": "m",
                "sourceLanguage": "Japanese",
            }
            with self.assertRaisesRegex(ValueError, "same script"):
                settings.save(0, "", japanese, {})
            self.assertEqual(settings.language(), "English")
            # New games start in the source Settings name, kept beside the
            # target through a draft and a save.
            english_source = {**japanese, "sourceLanguage": "english"}
            settings.draft(0, "", english_source, {})
            draft = settings.describe()["draft"]["values"]
            self.assertEqual(draft["sourceLanguage"], "English")
            view = settings.save(0, "", english_source, {})
            self.assertEqual(
                (view["values"]["sourceLanguage"], view["values"]["language"]),
                ("English", "Japanese"),
            )
            self.assertNotIn("draft", view)
            self.assertEqual(settings.source_language(), "English")
