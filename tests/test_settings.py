"""Per-model limits stay with their connection and the approved run."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import httpx

from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.settings import preferences, providers
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
            self.assertEqual((connection['name'], connection['protocol'], connection['organization']), ('OpenRouter', 'openai', ''))
            self.assertEqual(next(item for item in view['providers'] if item['id'] == 'openrouter')['protocol'], 'openai')
            model = 'anthropic/claude-sonnet-4.5'
            options = {model: {'entriesPerRequest': None, 'pricing': 'custom', 'inputRate': 3, 'outputRate': 15}}
            view = settings.save(view['revision'], identity, {'language': 'English', 'model': model}, options)
            frozen = configuration(settings, 'live')
            self.assertEqual((frozen['provider'], frozen['protocol'], frozen['endpoint']),
                             ('openrouter', 'openai', 'https://openrouter.ai/api/v1'))
            self.assertNotIn('batchInputTokens', frozen)
            settings.prepare_engine('translate')
            installed = adapter.install_settings.call_args.args[1]
            self.assertEqual((installed['api'], installed['API_PROVIDER'], installed['model']),
                             (frozen['endpoint'], 'openai', model))
            view = settings.save_connection(view['revision'], 'openrouter', connection_id=identity, name='Renamed')
            self.assertEqual(view['connections'][0]['model'], model)
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

    def test_openrouter_checks_authenticated_catalog_without_truncating_it_to_250_models(self):
        # The public /models endpoint can succeed without authenticating a key;
        # large account catalogs must retain later model suggestions as well.
        connection = {'provider': 'openrouter', 'protocol': 'openai', 'endpoint': '',
                      'keyless': False, 'secret': 'fixture-router-key', 'organization': ''}
        models = [f'author/model-{index:03}' for index in range(600)]
        requests = []
        status = 200
        def respond(request):
            requests.append(request)
            return httpx.Response(status, stream=httpx.ByteStream(json.dumps(
                {'data': [{'id': model} for model in reversed(models)]}).encode()))
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
            for status, expected in ((401, 'failed'), (302, 'unsupported')):
                result = providers.check(connection)
                self.assertEqual(result['check']['status'], expected)
                self.assertIsNone(result['models'])
            self.assertEqual(len(requests), 3)

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
            options = {'model-one': {**legacy_options, 'batchInputTokens': 8_000_000},
                       'model-two': {**legacy_options, 'batchInputTokens': 2_000_000}}
            settings.draft(view['revision'], 'first', view['values'], options)
            settings = Settings(temporary, adapter)
            self.assertEqual(settings.describe()['draft']['modelOptions'], options)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], frozen_default['batchInputTokens'])
            view = settings.save(view['revision'], 'first', view['values'], options)
            settings.prepare_engine('batch')
            frozen = deepcopy(adapter.manual.request_policy)
            self.assertEqual(frozen['batchInputTokens'], 8_000_000)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 8_000_000)
            view = settings.save(view['revision'], 'first', {**view['values'], 'model': 'model-two'}, options)
            self.assertEqual(configuration(settings, 'batch')['batchInputTokens'], 2_000_000)
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
