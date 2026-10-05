"""Per-model limits stay with their connection and the approved run."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.settings import preferences, providers, openrouter
from dazedtl.settings.execution import configuration, worker_secret
from dazedtl.settings.store import Settings
from dazedtl.storage import write_json


class SettingsTests(unittest.TestCase):
    def test_openrouter_connection_keeps_its_route_and_secret_through_save_check_and_reload(self):
        # A named OpenRouter preset must not become native OpenAI/Anthropic,
        # expose its key, or accidentally transfer a key to a different server.
        metadata = {'values': {'language': 'English', 'model': 'fixture-model', 'api': '', 'API_PROVIDER': 'openai'}}
        adapter = SimpleNamespace(settings_metadata=lambda: metadata, allow_providers=True,
                                  validate_route=lambda values: ExistingBackend.validate_route(ExistingBackend, values),
                                  provider_defaults=lambda _: {'batch_supported': False},
                                  manual=SimpleNamespace(request_policy=None), install_settings=Mock())
        state = {'version': 2, 'revision': 0, 'values': {'language': 'English', 'model': 'fixture-model'},
                 'legacy': {'values': metadata['values'], 'engines': {}, 'draft': None},
                 'model_options': {}, 'active': '', 'draft': None, 'connections': []}
        with TemporaryDirectory() as temporary:
            write_json(Path(temporary)/'settings/settings.json', state)
            settings = Settings(temporary, adapter)
            with patch.object(providers, 'check') as check:
                view = settings.save_connection(0, 'openrouter', secret='fixture-router-key', organization='ignored')
                check.assert_not_called()
            identity = view['activeConnectionId']
            connection = view['connections'][0]
            self.assertEqual(connection['openrouter_host'], '')
            self.assertEqual((connection['name'], connection['protocol'], connection['organization']), ('OpenRouter', 'openai', ''))
            self.assertEqual(next(item for item in view['providers'] if item['id'] == 'openrouter')['protocol'], 'openai')
            model = 'anthropic/claude-sonnet-4.5'
            options = {model: {'entriesPerRequest': None, 'pricing': 'custom', 'inputRate': 3, 'outputRate': 15}}
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, options)
            automatic = configuration(settings, 'live')
            self.assertNotIn('openrouterHost', automatic)
            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host='deepinfra')
            frozen = configuration(settings, 'live')
            self.assertEqual(frozen['openrouterHost'], 'deepinfra')
            self.assertEqual((frozen['provider'], frozen['protocol'], frozen['endpoint']),
                             ('openrouter', 'openai', 'https://openrouter.ai/api/v1'))
            self.assertNotIn('batchInputTokens', frozen)
            settings.prepare_engine('translate')
            frozen_policy = deepcopy(adapter.manual.request_policy)
            self.assertEqual(frozen_policy['openrouterHost'], 'deepinfra')
            installed = adapter.install_settings.call_args.args[1]
            self.assertEqual((installed['api'], installed['API_PROVIDER'], installed['model']),
                             (frozen['endpoint'], 'openai', model))
            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, name='Renamed')
            self.assertEqual(view['connections'][0]['model'], model)
            self.assertEqual(view['connections'][0]['openrouter_host'], 'deepinfra')
            reloaded = Settings(temporary, adapter)
            self.assertEqual(worker_secret(Path(temporary), frozen), 'fixture-router-key')
            self.assertEqual(configuration(reloaded, 'live'), frozen)
            with self.assertRaisesRegex(ValueError, 'Enter the API key'):
                reloaded.save_connection(view['revision'], 'openai', connection_id=identity)
            with patch.object(providers, 'check', return_value={'check': {'status': 'verified', 'message': 'Checked', 'checkedAt': 'now'},
                                                              'models': [model]}):
                view = reloaded.check_connection(view['revision'], identity)
            self.assertEqual(view['connections'][0]['models'], [model])
            self.assertNotIn('fixture-router-key', str(view))
            for invalid in ('host with spaces', 'https://provider.invalid', ['deepinfra'], 7):
                with self.assertRaisesRegex(ValueError, 'valid OpenRouter host'):
                    reloaded.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host=invalid)
            view = reloaded.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host='novita')
            self.assertEqual(configuration(reloaded, 'live')['openrouterHost'], 'novita')
            # Credentials are resolved through the same route while execution
            # keeps the approved host, even after the connection is edited.
            self.assertEqual(worker_secret(Path(temporary), frozen), 'fixture-router-key')
            self.assertEqual(frozen_policy['openrouterHost'], frozen['openrouterHost'])
            view = reloaded.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host='')
            self.assertEqual(configuration(reloaded, 'live'), automatic)
            reloaded.prepare_engine('translate')
            self.assertNotIn('openrouterHost', adapter.manual.request_policy)
            view = reloaded.save_connection(view['revision'], 'openai', connection_id=identity,
                                            secret='fixture-openai-key', openrouter_host='deepinfra')
            self.assertEqual(view['connections'][0]['openrouter_host'], '')

    def test_openrouter_host_lookup_is_read_only_and_rejects_unusable_catalogs(self):
        # A public suggestion lookup must not send credentials, follow a
        # redirect, or show unrelated hosts for the selected model. Endpoint
        # variants of one host must collapse to the same routing slug.
        requests = []
        body = json.dumps({'data': [{'slug': 'xiaomi', 'name': 'Xiaomi'},
                                    {'slug': 'deepinfra', 'name': 'DeepInfra'}]}).encode()
        status = 200
        def respond(request):
            requests.append(request)
            return httpx.Response(status, stream=httpx.ByteStream(body))
        client = httpx.Client
        def mocked_client(**kwargs):
            self.assertFalse(kwargs['follow_redirects'])
            return client(transport=httpx.MockTransport(respond), **kwargs)
        with patch.object(providers.httpx, 'Client', side_effect=mocked_client):
            self.assertEqual(providers.openrouter_hosts(), [{'slug': 'deepinfra', 'name': 'DeepInfra'},
                                                          {'slug': 'xiaomi', 'name': 'Xiaomi'}])
            self.assertEqual(str(requests[0].url), 'https://openrouter.ai/api/v1/providers')
            self.assertEqual(requests[0].method, 'GET')
            self.assertNotIn('Authorization', requests[0].headers)
            model = 'xiaomi/fixture-model:free'
            body = json.dumps({'data': {'id': model, 'endpoints': [
                {'tag': 'xiaomi/fp8', 'provider_name': 'Xiaomi'},
                {'tag': 'deepinfra/fp8', 'provider_name': 'DeepInfra'},
                {'tag': 'deepinfra/bf16', 'provider_name': 'DeepInfra'},
            ]}}).encode()
            self.assertEqual(providers.openrouter_hosts(model), [{'slug': 'deepinfra', 'name': 'DeepInfra'},
                                                               {'slug': 'xiaomi', 'name': 'Xiaomi'}])
            self.assertEqual(str(requests[-1].url), 'https://openrouter.ai/api/v1/models/xiaomi/fixture-model%3Afree/endpoints')
            self.assertNotIn('Authorization', requests[-1].headers)
            with self.assertRaises(ValueError):
                providers.openrouter_hosts('xiaomi/different-model')
            before = len(requests)
            for invalid in ('../../providers', 'https://example.invalid/model', 7):
                with self.assertRaises(ValueError):
                    providers.openrouter_hosts(invalid)
            self.assertEqual(len(requests), before)
            body = json.dumps({'data': {'id': model, 'endpoints': []}}).encode()
            self.assertEqual(providers.openrouter_hosts(model), [])
            for status, body in ((302, b'{}'), (200, b'{"data":[{"name":"Missing slug"}]}'),
                                 (200, b'{"data":[{"name":"Bad host","slug":"bad host"}]}'),
                                 (200, b'x' * 1_000_001)):
                with self.assertRaises(ValueError):
                    providers.openrouter_hosts()
            body = json.dumps({'data': {'id': model, 'endpoints': [{'tag': None, 'provider_name': 'Unknown'}]}}).encode()
            with self.assertRaises(ValueError):
                providers.openrouter_hosts(model)

    def test_openrouter_checks_authenticated_catalog_without_truncating_it_to_250_models(self):
        # The public /models endpoint can succeed without authenticating a key;
        # large account catalogs must retain later model suggestions as well.
        connection = {'provider': 'openrouter', 'protocol': 'openai', 'endpoint': '',
                      'keyless': False, 'secret': 'fixture-router-key', 'organization': ''}
        models = [f'author/model-{index:03}' for index in range(600)]
        connection['model'] = models[0]
        priced = {'id': models[0], 'pricing': {'prompt': '0.000002', 'completion': '0.000008'},
                  'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']},
                  'supported_parameters': ['response_format']}
        requests = []
        status = 200
        def respond(request):
            requests.append(request)
            if request.url.path.endswith('/endpoints'):
                return httpx.Response(200, json={'data': {'id': models[0] + ':batch', 'endpoints': [
                    {'tag': 'supported', 'supported_parameters': ['response_format', 'structured_outputs'],
                     'pricing': {'prompt': '.0000008', 'completion': '.000003'}},
                    {'tag': 'json-only', 'supported_parameters': ['response_format'],
                     'pricing': {'prompt': '0', 'completion': '0'}},
                    {'tag': 'mixed', 'supported_parameters': ['response_format', 'structured_outputs'],
                     'pricing': {'prompt': '0', 'completion': '0'}},
                    {'tag': 'mixed/legacy', 'supported_parameters': ['response_format']} ]}})
            return httpx.Response(status, stream=httpx.ByteStream(json.dumps(
                {'data': [{'id': model} for model in reversed(models[1:])] + [priced,
                    {**priced, 'id': models[0] + ':batch', 'pricing': {'prompt': '0.0000008', 'completion': '0.000003'}}]}).encode()))
        client = httpx.Client
        def mocked_client(**kwargs):
            self.assertFalse(kwargs['follow_redirects'])
            return client(transport=httpx.MockTransport(respond), **kwargs)
        with patch.object(providers.httpx, 'Client', side_effect=mocked_client):
            result = providers.check(connection)
            self.assertEqual(result['check']['status'], 'verified')
            self.assertEqual(result['models'], models)
            self.assertEqual(str(requests[0].url), 'https://openrouter.ai/api/v1/models/user')
            self.assertEqual(requests[0].headers['Authorization'], 'Bearer fixture-router-key')
            self.assertEqual(requests[0].method, 'GET')
            connection.update(result)
            options = {'entriesPerRequest': None, 'pricing': 'automatic', 'inputRate': None, 'outputRate': None}
            frozen = openrouter.policy(connection, models[0], options, required=True)
            self.assertEqual((frozen['input'], frozen['output']), (.8, 3))
            self.assertEqual(frozen['providers'], ['supported'])
            self.assertTrue(openrouter.describe(connection, models[0])['batchSupported'])
            self.assertFalse(openrouter.describe(connection, models[-1])['batchSupported'])
            connection['batch_endpoints']['rates']['input'] = None
            with self.assertRaisesRegex(ValueError, 'Batch pricing is unavailable'):
                openrouter.policy(connection, models[0], options, required=True)
            custom = preferences.options({**options, 'batchPricing': 'custom', 'batchInputRate': .7, 'batchOutputRate': 2})
            self.assertEqual(openrouter.policy(connection, models[0], custom, required=True)['input'], .7)
            self.assertEqual(frozen['input'], .8)
            with self.assertRaises(ValueError):
                preferences.options({**custom, 'batchOutputRate': None})
            for status, expected in ((401, 'failed'), (302, 'unsupported')):
                result = providers.check(connection)
                self.assertEqual(result['check']['status'], expected)
                self.assertIsNone(result['models'])
            self.assertEqual(len(requests), 4)

    def test_openrouter_batch_catalog_survives_reopen_and_host_changes_cannot_reprice_saved_work(self):
        # Switching a saved model/host must resolve Batch support without a
        # second account check; draft reads and late replies cannot change it.
        from dazedtl.api.server import Application
        model, other = 'author/model', 'author/other'
        metadata = {'values': {'language': 'English', 'model': model, 'api': '', 'API_PROVIDER': 'openai'}}
        adapter = SimpleNamespace(settings_metadata=lambda: metadata, allow_providers=True, validate_route=lambda _: None,
                                  provider_defaults=lambda _: {'batch_supported': False}, manual=SimpleNamespace(request_policy=None), install_settings=Mock())
        adapter.lock = threading.RLock()
        adapter.context = lambda: adapter.lock
        app = Application.__new__(Application)
        app.backend, app.closing = adapter, False
        app.translation = SimpleNamespace(engine=SimpleNamespace(context=lambda: adapter.lock))
        state = {'version': 2, 'revision': 0, 'values': {'language': 'English', 'model': model},
                 'legacy': {'values': metadata['values'], 'engines': {}, 'draft': None}, 'model_options': {},
                 'active': '', 'draft': None, 'connections': []}
        row = {'input': 2, 'output': 8, 'cache_read': None, 'cache_write': None, 'text': True, 'json': True, 'context': 32000, 'max_output': 4096}
        checked = {'check': {'status': 'verified', 'message': 'Checked', 'checkedAt': '2026-10-05T12:00:00+00:00'},
                   'models': [model, other], 'catalog': {model: row, model + ':batch': {**row, 'input': .8, 'output': 3},
                                                       other: row, other + ':batch': row},
                   'batch_endpoints': {'model': model, 'host': '', 'providers': ['supported'],
                       'rates': {'input': .8, 'output': 3, 'cache_read': None, 'cache_write': None}}}
        with TemporaryDirectory() as directory:
            write_json(Path(directory)/'settings/settings.json', state)
            settings = Settings(directory, adapter)
            app.settings = settings
            view = settings.save_connection(0, 'openrouter', secret='fixture-key')
            identity = view['activeConnectionId']
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, {})
            self.assertFalse(settings.translation_defaults()['batch_supported'])
            with patch.object(providers, 'check', return_value=checked):
                view = settings.check_connection(view['revision'], identity)
            settings = Settings(directory, adapter)
            app.settings = settings
            with patch.object(httpx, 'Client', side_effect=AssertionError('Observations cannot contact a provider.')):
                self.assertTrue(settings.translation_defaults()['batch_supported'])
                self.assertEqual(settings.model_defaults(identity, model)['batchInputRate'], .8)
                frozen = configuration(settings, 'batch')
                settings.prepare_engine('batch')
                self.assertEqual(adapter.manual.request_policy['openrouterBatch'], frozen['openrouterBatch'])
                self.assertEqual(adapter.manual.request_policy['openrouterStructuredOutputs'], openrouter.STRUCTURED_OUTPUTS)
                self.assertEqual(frozen['openrouterStructuredOutputs'], openrouter.STRUCTURED_OUTPUTS)
                self.assertNotIn('catalog', settings.describe()['connections'][0])
            original = deepcopy(frozen)
            endpoints = {**checked['batch_endpoints'], 'model': other,
                         'rates': {**checked['batch_endpoints']['rates'], 'input': 1.1}}
            with patch.object(providers, 'check', side_effect=AssertionError('Do not recheck the account on model selection.')), \
                    patch.object(openrouter, 'check_endpoints', return_value=endpoints) as fetch:
                result = app.settings_model_defaults(identity, other)
                self.assertTrue(result['batchSupported'])
                self.assertEqual(result['batchInputRate'], 1.1)
                self.assertEqual(settings.describe()['values']['model'], model)
                self.assertEqual(settings.model_defaults(identity, model)['batchInputRate'], .8)
                view = settings.save(view['revision'], identity, {'language': 'English', 'model': other}, {})
                app.resolve_batch_support(persist=True)
                self.assertEqual(fetch.call_args.args[0]['model'], other)
                self.assertEqual(configuration(settings, 'batch')['openrouterBatch']['input'], 1.1)
                app.resolve_batch_support(persist=True)
                self.assertEqual(fetch.call_count, 2)  # Saved metadata is reused on a revisit.
            settings = Settings(directory, adapter)
            app.settings = settings
            with patch.object(httpx, 'Client', side_effect=AssertionError('Reopening/observations cannot contact a provider.')):
                self.assertTrue(settings.translation_defaults()['batch_supported'])
                self.assertEqual(settings.model_defaults(identity, other)['batchInputRate'], 1.1)
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, {})
            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host='deepinfra')
            self.assertFalse(settings.translation_defaults()['batch_supported'])
            with self.assertRaises(ValueError):
                configuration(settings, 'batch')
            endpoints = {'model': model, 'host': 'deepinfra', 'providers': ['deepinfra'],
                         'rates': {'input': 1.2, 'output': 4, 'cache_read': None, 'cache_write': None}}
            with patch.object(openrouter, 'check_endpoints', return_value=endpoints):
                app.resolve_batch_support(persist=True)
            settings.retain_prices(settings.pricing_lookup(), {'model': model, 'host': 'deepinfra', 'inputRate': 2.4, 'outputRate': 9,
                'source': 'catalog', 'updatedAt': checked['check']['checkedAt'], 'stale': False})
            self.assertEqual(configuration(settings, 'batch')['openrouterBatch']['input'], 1.2)
            self.assertEqual(configuration(settings, 'live')['rates']['input'], 2.4)
            self.assertEqual(frozen, original)
            self.assertEqual(worker_secret(Path(directory), frozen), 'fixture-key')

            # A stalled endpoint read leaves settings observable and cannot
            # publish after a different model, host, key or catalog is selected.
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': other}, {})
            lookup = settings.batch_lookup()
            for change in ({'model': model}, {'openrouter_host': 'novita'}, {'secret': 'replacement'},
                           {'catalog': {}}, {'check': providers.unchecked()}):
                stale = deepcopy(lookup)
                stale['connection'].update(change)
                self.assertIsNone(settings.retain_batch_endpoints(stale, endpoints, persist=True))
            started, release, failures = threading.Event(), threading.Event(), []
            def slow_check(connection, _known):
                started.set()
                self.assertTrue(release.wait(1))
                return {**endpoints, 'model': connection['model']}
            def resolve():
                try:
                    app.resolve_batch_support(persist=True)
                except Exception as error:
                    failures.append(error)
            with patch.object(openrouter, 'check_endpoints', side_effect=slow_check):
                worker = threading.Thread(target=resolve)
                worker.start()
                try:
                    self.assertTrue(started.wait(1))
                    acquired = adapter.lock.acquire(timeout=.1)
                    self.assertTrue(acquired, 'A stalled Batch check held the application lock.')
                    if acquired:
                        try:
                            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, {})
                            self.assertTrue(settings.translation_defaults()['batch_supported'])
                        finally:
                            adapter.lock.release()
                finally:
                    release.set()
                    worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertTrue(settings.translation_defaults()['batch_supported'])
            self.assertEqual(settings.model_defaults(identity, model)['batchInputRate'], 1.2)
            # No endpoint lookup can infer eligibility for an absent model or
            # bypass offline mode and initial account authentication.
            self.assertIsNone(settings.batch_lookup(model='author/absent'))
            adapter.allow_providers = False
            self.assertIsNone(settings.batch_lookup(model=other))
            adapter.allow_providers = True
            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, secret='replacement')
            self.assertIsNone(settings.batch_lookup(model=other))

    def test_pinned_batch_endpoint_prices_do_not_fall_back_and_outages_preserve_authentication(self):
        # A host's price can differ from the model minimum, and a Batch
        # metadata failure must not discard successful key authentication.
        model, status, calls = 'author/model', 200, []
        parameters = ['response_format', 'structured_outputs']
        row = {'id': model, 'pricing': {'prompt': '.000002', 'completion': '.000008'},
               'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']}, 'supported_parameters': ['response_format']}
        connection = {'provider': 'openrouter', 'protocol': 'openai', 'endpoint': '', 'model': model,
                      'openrouter_host': 'deepinfra', 'keyless': False, 'secret': 'fixture-key', 'organization': ''}
        def respond(request):
            calls.append(request)
            if request.url.path.endswith('/models/user'):
                return httpx.Response(200, stream=httpx.ByteStream(json.dumps({'data': [row, {**row, 'id': model + ':batch'}]}).encode()))
            return httpx.Response(status, json={'data': {'id': model + ':batch', 'endpoints': [
                {'tag': 'deepinfra', 'pricing': {'prompt': '.0000012', 'completion': '.000004'}, 'supported_parameters': parameters},
                {'tag': 'other', 'pricing': {'prompt': '.0000001', 'completion': '.0000002'}, 'supported_parameters': ['response_format']}]}})
        client = httpx.Client
        with patch.object(httpx, 'Client', side_effect=lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs)):
            checked = providers.check(connection)
            self.assertEqual(checked['check']['status'], 'verified')
            self.assertEqual(openrouter.describe({**connection, **checked}, model)['batchInputRate'], 1.2)
            self.assertEqual(str(calls[1].url), 'https://openrouter.ai/api/v1/models/author/model:batch/endpoints')
            parameters.remove('structured_outputs')
            unsupported = providers.check(connection)
            self.assertFalse(openrouter.describe({**connection, **unsupported}, model)['batchSupported'])
            status = 500
            checked = providers.check(connection)
            self.assertEqual(checked['check']['status'], 'verified')
            defaults = openrouter.describe({**connection, **checked}, model)
            self.assertIsNone(defaults['inputRate'])  # Batch metadata cannot establish this host's Live price.
            self.assertFalse(defaults['batchSupported'])
            self.assertIn('Check the connection again', defaults['batchReason'])
            self.assertTrue(all(request.method == 'GET' for request in calls))

    def test_legacy_verified_openrouter_prices_load_before_estimation_without_locking_observers_or_crossing_hosts(self):
        # Existing verified connections lack the new catalog. Explicit
        # estimation must repair that gap while snapshots remain read-only;
        # a late price response cannot price a newly selected host.
        from dazedtl.api.server import Application
        model = 'author/model'
        metadata = {'values': {'language': 'English', 'model': model, 'api': '', 'API_PROVIDER': 'openai'}}
        adapter = SimpleNamespace(settings_metadata=lambda: metadata, allow_providers=True, lock=threading.RLock(),
            validate_route=lambda _: None, provider_defaults=lambda _: {'batch_supported': False},
            manual=SimpleNamespace(request_policy=None), install_settings=Mock())
        state = {'version': 2, 'revision': 0, 'values': {'language': 'English', 'model': model},
                 'legacy': {'values': metadata['values'], 'engines': {}, 'draft': None}, 'model_options': {},
                 'active': '', 'draft': None, 'connections': []}
        prices = {'model': model, 'host': 'darkbloom', 'inputRate': .1, 'outputRate': .28, 'source': 'catalog', 'updatedAt': 'now', 'stale': False}
        with TemporaryDirectory() as directory:
            write_json(Path(directory)/'settings/settings.json', state)
            settings = Settings(directory, adapter)
            view = settings.save_connection(0, 'openrouter', secret='fixture-secret', openrouter_host='darkbloom')
            identity = view['activeConnectionId']
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, {})
            with patch.object(providers, 'check', return_value={'check': {'status': 'verified', 'message': 'Checked', 'checkedAt': 'now'}, 'models': [model]}):
                view = settings.check_connection(view['revision'], identity)
            self.assertIsNone(settings.model_defaults(identity, model)['inputRate'])
            app = SimpleNamespace(backend=adapter, settings=settings, closing=False)
            started, release = threading.Event(), threading.Event()
            failures = []
            def lookup(*_args):
                started.set()
                self.assertTrue(release.wait(1))
                return prices
            def prepare():
                try:
                    Application.prepare_model_pricing(app, 'guided_preview', {'action': 'start'})
                except Exception as error:
                    failures.append(error)
            with patch.object(openrouter, 'live_prices', side_effect=lookup) as fetch:
                for operation in ('workspace_snapshot', 'navigate', 'guided_state'):
                    Application.prepare_model_pricing(app, operation, {})
                fetch.assert_not_called()
                worker = threading.Thread(target=prepare)
                worker.start()
                try:
                    self.assertTrue(started.wait(1))
                    acquired = adapter.lock.acquire(timeout=.1)
                    self.assertTrue(acquired, 'A stalled price read held the application lock.')
                    if acquired:
                        try:
                            self.assertEqual(settings.describe()['values']['model'], model)
                            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, openrouter_host='novita')
                        finally:
                            adapter.lock.release()
                finally:
                    release.set()
                    worker.join(1)
            self.assertEqual(len(failures), 1)
            self.assertIn('changed while reading prices', str(failures[0]))
            self.assertIsNone(settings.model_defaults(identity, model)['inputRate'])
            with patch.object(openrouter, 'live_prices', return_value={**prices, 'host': 'novita', 'inputRate': .14}) as fetch:
                Application.prepare_model_pricing(app, 'guided_preview', {'action': 'start'})
                frozen = configuration(settings, 'live')
                self.assertEqual(frozen['rates']['input'], .14)
                self.assertEqual(frozen['openrouterHost'], 'novita')
                settings.prepare_engine('estimate')
                self.assertEqual(adapter.manual.request_policy['inputRate'], .14)
                Application.prepare_model_pricing(app, 'settings_model_defaults', {'connection_id': identity, 'model': model})
                fetch.assert_called_once_with(model, 'novita')
                self.assertFalse(settings.translation_defaults()['batch_supported'])
            cache_key = (identity, model, 'novita')
            settings._openrouter_prices[cache_key] = (0, settings._openrouter_prices[cache_key][1])
            with patch.object(openrouter, 'live_prices', side_effect=ValueError('Catalog unavailable')):
                Application.prepare_model_pricing(app, 'guided_preview', {'action': 'start'})
            self.assertTrue(settings.model_defaults(identity, model)['stale'])
            self.assertEqual(configuration(settings, 'live')['rates'], frozen['rates'])

    def test_public_live_price_lookup_matches_host_variants_and_never_uses_another_host_price(self):
        # Hosts publish endpoint tags such as darkbloom/fp4. Pinning the base
        # host must match those prices, even when another host is cheaper.
        model, calls = 'author/model', []
        rows = [{'tag': 'darkbloom/fp4', 'pricing': {'prompt': '.0000001', 'completion': '.00000028'}, 'max_completion_tokens': 16384},
                {'tag': 'novita/fp8', 'pricing': {'prompt': '.00000001', 'completion': '.00000002'}, 'max_completion_tokens': 65536}]
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={'data': {'id': model, 'endpoints': rows,
                                                     'pricing': {'prompt': '.00000014', 'completion': '.00000028'}}})
        client = httpx.Client
        with patch.object(httpx, 'Client', side_effect=lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs)):
            prices = openrouter.live_prices(model, 'darkbloom')
            self.assertEqual((prices['inputRate'], prices['outputRate']), (.1, .28))
            self.assertEqual(prices['maxOutputTokens'], 16384)
            self.assertEqual(str(calls[-1].url), 'https://openrouter.ai/api/v1/models/author/model/endpoints')
            with self.assertRaisesRegex(ValueError, 'No complete OpenRouter price'):
                openrouter.live_prices(model, 'missing-host')
            self.assertEqual(openrouter.live_prices(model)['inputRate'], .14)
            self.assertEqual(str(calls[-1].url), 'https://openrouter.ai/api/v1/model/author/model')
            self.assertTrue(all(request.method == 'GET' and 'Authorization' not in request.headers for request in calls))

    def test_batch_allowance_survives_drafts_and_model_connection_switches_without_changing_saved_runs(self):
        # Protect against silently losing the allowance in an older settings
        # record, applying another connection's value, or changing a frozen run.
        legacy_options = {'entriesPerRequest': None, 'pricing': 'custom', 'inputRate': 1, 'outputRate': 2}
        connection = {'id': 'first', 'runtime_name': 'first-key', 'name': 'First', 'provider': 'openai',
                      'protocol': 'openai', 'endpoint': '', 'secret': 'fixture-secret', 'keyless': False,
                      'organization': '', 'model': 'model-one', 'model_options': {'model-one': legacy_options},
                      'models': [], 'check': providers.unchecked()}
        metadata = {'values': {'language': 'English', 'model': 'model-one', 'api': '', 'API_PROVIDER': 'openai'}}
        adapter = SimpleNamespace(settings_metadata=lambda: metadata, allow_providers=False,
                                  validate_route=lambda _: None, provider_defaults=lambda _: {'batch_supported': True},
                                  model_defaults=SimpleNamespace(cached=lambda model: {'maxOutputTokens': 8192} if model == 'model-two' else {}),
                                  manual=SimpleNamespace(request_policy=None), install_settings=Mock())
        state = {'version': 2, 'revision': 0, 'values': {'language': 'English', 'model': 'model-one'},
                 'legacy': {'values': metadata['values'], 'engines': {}, 'draft': None},
                 'model_options': {}, 'active': 'first', 'draft': None,
                 'connections': [connection, {**deepcopy(connection), 'id': 'second', 'runtime_name': 'second-key', 'name': 'Second'}]}
        with TemporaryDirectory() as temporary:
            path = Path(temporary)/'settings/settings.json'
            write_json(path, state)
            original = path.read_bytes()
            settings = Settings(temporary, adapter)
            view = settings.describe()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], view['defaultBatchInputTokens'])
            settings.prepare_engine('batch')
            frozen_default = deepcopy(adapter.manual.request_policy)
            self.assertEqual(frozen_default['batchInputTokens'], view['defaultBatchInputTokens'])
            self.assertEqual(frozen_default['maxOutputTokens'], 32768)
            self.assertEqual(configuration(settings, 'live')['maxOutputTokens'], 32768)
            options = {'model-one': {**legacy_options, 'batchInputTokens': 8_000_000, 'maxOutputTokens': 65536},
                       'model-two': {**legacy_options, 'batchInputTokens': 2_000_000, 'maxOutputTokens': 16384}}
            settings.draft(view['revision'], 'first', view['values'], options)
            settings = Settings(temporary, adapter)
            self.assertEqual(settings.describe()['draft']['modelOptions'], options)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], frozen_default['batchInputTokens'])
            self.assertEqual(configuration(settings, 'live')['maxOutputTokens'], 32768)
            view = settings.save(view['revision'], 'first', view['values'], options)
            settings.prepare_engine('batch')
            frozen = deepcopy(adapter.manual.request_policy)
            self.assertEqual(frozen['batchInputTokens'], 8_000_000)
            self.assertEqual(frozen['maxOutputTokens'], 65536)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 8_000_000)
            view = settings.save(view['revision'], 'first', {**view['values'], 'model': 'model-two'}, options)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 2_000_000)
            self.assertEqual(configuration(settings, 'live')['maxOutputTokens'], 8192)
            settings.prepare_engine('translate')
            self.assertEqual(adapter.manual.request_policy['maxOutputTokens'], 8192)
            self.assertEqual(frozen_default['maxOutputTokens'], 32768)
            view = settings.select(view['revision'], 'second')
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], frozen_default['batchInputTokens'])
            view = settings.select(view['revision'], 'first')
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 2_000_000)
            view = settings.save(view['revision'], 'first', view['values'],
                                 {**options, 'model-two': {**legacy_options, 'batchInputTokens': None}})
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], frozen_default['batchInputTokens'])
            # A later default change affects future preparation, never an
            # existing plan's recorded default or an explicit model override.
            with patch.object(preferences, 'DEFAULT_BATCH_INPUT_TOKENS', 350_000):
                settings.prepare_engine('batch')
                self.assertEqual(adapter.manual.request_policy['batchInputTokens'], 350_000)
                self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 350_000)
            self.assertEqual(frozen_default['batchInputTokens'], view['defaultBatchInputTokens'])
            self.assertEqual(frozen['batchInputTokens'], 8_000_000)
            self.assertNotIn('fixture-secret', str(view))
        for invalid in (0, -1, True, 1.5, '8000000', 9_007_199_254_740_992):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                preferences.options({**legacy_options, 'batchInputTokens': invalid})

    def test_compiled_batch_limits_use_the_frozen_allowance_only_for_native_openai(self):
        # Guided and compiled plans must agree on the token allowance; ordinary
        # request/byte limits and other providers retain their own behavior.
        util, translation, batches = (ModuleType(name) for name in ('util', 'util.translation', 'util.batch_providers'))
        translation._openai_batch_token_limit = lambda: 600_000
        batches.batch_limits = lambda _: (50_000, 200_000_000)
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.batch_supported = lambda _: 'openai'
        with patch.dict(sys.modules, {item.__name__: item for item in (util, translation, batches)}):
            config = {'protocol': 'openai', 'endpoint': 'https://api.openai.com/v1', 'batchInputTokens': 8_000_000}
            self.assertEqual(engine.batch_limits(config), [50_000, 200_000_000, 8_000_000])
            self.assertEqual(engine.batch_limits({**config, 'batchInputTokens': None})[-1], 600_000)
            self.assertIsNone(engine.batch_limits({**config, 'endpoint': 'https://fixture.invalid/v1'})[-1])
            self.assertIsNone(engine.batch_limits({**config, 'protocol': 'anthropic'})[-1])

    def test_model_output_limits_survive_catalog_filtering_without_borrowing_a_fuzzy_price_match(self):
        # Price fallbacks may match related model names, but an output limit
        # must be bound to the selected model and never inferred from a price.
        from dazedtl.compatibility.pricing_worker import catalog, model_output_limit
        values = catalog({'model-small': {'input_cost_per_token': .000001, 'output_cost_per_token': .000002, 'max_output_tokens': 8192},
                          'model-large': {'input_cost_per_token': .000001, 'output_cost_per_token': .000002, 'max_output_tokens': 65536},
                          'model-bad': {'input_cost_per_token': .000001, 'output_cost_per_token': .000002, 'max_output_tokens': True}})
        self.assertEqual(model_output_limit(values, 'author/model-small'), 8192)
        self.assertEqual(model_output_limit(values, 'models/model-large'), 65536)
        self.assertIsNone(model_output_limit(values, 'model-small-other'))
        self.assertIsNone(model_output_limit(values, 'model-bad'))
