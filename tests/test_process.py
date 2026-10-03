"""Hermetic process evidence and state response mapping, without providers."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from dazedtl.compatibility import state_requests, process_view, request_scope
from dazedtl.compatibility.run_evidence import Evidence
from dazedtl.storage import write_json
from dazedtl.translation.files import digest


class ProcessTests(unittest.TestCase):
    def test_fresh_start_requires_complete_terminal_rejection_receipts(self):
        # A failed worker is not proof of no provider work. Protect missing,
        # pending, partial-success, conflicting, and duplicate submission evidence.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {'mode': 'batch'}
            write_json(root/'plan.json', plan)
            job = {'mode': 'batch', 'status': 'failed', 'plan_hash': digest((root/'plan.json').read_bytes())}
            queue = {'one': {'payload': '{"Line1":"防御"}', 'params': {}, 'provider':'openai'},
                     'two': {'payload': '{"Line1":"毒"}', 'params': {}, 'provider':'openai'}}
            batch = {'id':'batch-generated', 'provider':'openai', 'api_status':'completed',
                     'custom_ids':{'req-1':'one'}, 'request_counts':{'processing':0,'succeeded':0,'errored':1,'canceled':0,'expired':0}}
            state = {'status':'partially_submitted','batches':[{'id':batch['id'],'custom_ids':batch['custom_ids']}]}
            write_json(root/'log/batch_requests.json', queue)
            write_json(root/'log/batch_history.json', {'batches':[batch]})
            write_json(root/'log/batch_state.json', state)
            baseline = {path:path.read_bytes() for path in root.rglob('*') if path.is_file()}
            proof = process_view.fresh_start(root, job)
            self.assertTrue(proof['eligible']); self.assertEqual((proof['failed'],proof['remaining']),(1,1))
            changes = [lambda b,s,j: b.update(api_status='in_progress'),
                       lambda b,s,j: b.update(provider='unknown'),
                       lambda b,s,j: b['request_counts'].update(succeeded=1),
                       lambda b,s,j: b['request_counts'].update(processing=1),
                       lambda b,s,j: b['request_counts'].pop('succeeded'),
                       lambda b,s,j: b['request_counts'].update(errored=True),
                       lambda b,s,j: b.update(output_file_id='file-success'),
                       lambda b,s,j: s.update(status='submission_uncertain'),
                       lambda b,s,j: s['batches'].append({'id':'unknown','custom_ids':{'unknown':'two'}}),
                       lambda b,s,j: s['batches'][0].update(custom_ids={'req-1':'two'}),
                       lambda b,s,j: j.update(status='interrupted'),
                       lambda b,s,j: j.update(status='running'),
                       lambda b,s,j: j.update(completed=['States.json']),
                       lambda b,s,j: j.update(outputs={'States.json':{}}),
                       lambda b,s,j: j.update(approval={'token':'pending'})]
            for change in changes:
                b,s,j=deepcopy(batch),deepcopy(state),deepcopy(job); change(b,s,j)
                write_json(root/'log/batch_history.json', {'batches':[b]});write_json(root/'log/batch_state.json',s)
                self.assertFalse(process_view.fresh_start(root,j)['eligible'], change)
            for path,raw in baseline.items():path.write_bytes(raw)
            write_json(root/'log/batch_results.json',{'one':{'text':'Paid result'}})
            self.assertFalse(process_view.fresh_start(root,job)['eligible'])
            (root/'log/batch_results.json').unlink()
            duplicate=deepcopy(batch);duplicate['id']='batch-duplicate'
            write_json(root/'log/batch_history.json',{'batches':[batch,duplicate]})
            write_json(root/'log/batch_state.json',{**state,'batches':[*state['batches'],{'id':duplicate['id'],'custom_ids':duplicate['custom_ids']}]})
            self.assertFalse(process_view.fresh_start(root,job)['eligible'])
            for path,raw in baseline.items():path.write_bytes(raw)
            self.assertEqual(process_view.fresh_start(root,job),proof)
            self.assertEqual({path:path.read_bytes() for path in baseline},baseline)

    def test_source_overlap_survives_new_chunking_and_protects_approval_send_gap(self):
        # Protect duplicated payment when a second review arrives before the
        # first approved Batch has written its remote manifest. Model/chunk IDs
        # do not identify the logical source, and disjoint fields stay usable.
        with TemporaryDirectory() as temporary:
            root = Path(temporary); old, new = root/'old', root/'new'
            a, b = request_scope.identities('Items.json', 'database', ['薬', '毒'])
            row = lambda text, keys: {'payload': json.dumps({'Line1': text}), 'params': {}, 'provider': 'openai',
                                     'dazedtl_sources': keys, 'dazedtl_file': 'Items.json'}
            write_json(old/'log/batch_requests.json', {'old-hash': row('薬', [a])})
            write_json(old/'log/batch_state.json', {'status': 'queued'})
            write_json(new/'log/estimate_requests.json', {'different-model-hash': row('薬', [a])})
            job = {'id': 'old', 'mode': 'batch', 'files': ['Items.json'], 'logicalPhase': 'database', 'status': 'running'}
            estimate = {**job, 'id': 'new', 'mode': 'estimate'}
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))
            job['dazedtl_submission_intent'] = True
            self.assertEqual(len(request_scope.overlap(new, estimate, [(old, job)])), 1)
            write_json(new/'log/estimate_requests.json', {'different-group': row('毒', [b])})
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))
            job['logicalPhase'] = 'dialogue'
            write_json(new/'log/estimate_requests.json', {'different-group': row('薬', [a])})
            self.assertFalse(request_scope.overlap(new, estimate, [(old, job)]))

    def test_state_coalescing_preserves_fields_controls_originals_and_saved_consume_mapping(self):
        # Protect the 45 calls / 112 fields -> 8 compatible calls case, including
        # exact writer association, glossary separation and no duplicate consume.
        counts = [1]*15 + [3]*20 + [5]*3 + [2] + [3]*4 + [4]*2
        fields = ['name', 'description', 'message1', 'message2', 'message3', 'message4']
        data = [None] + [{ 'id': i+1, **{field: f'項目{i+1}_{field}' + (f'語彙{i}' if i >= 39 else '')
                                       for field in fields[:count]}} for i, count in enumerate(counts)]
        data[1]['name'] += r'\C[2]'
        emitted = []
        malformed = [False]
        module = SimpleNamespace(TRANSLATION_CONFIG=SimpleNamespace(langRegex='項目|他'))
        module._entry_field_needs_translation = lambda item, field: str(item.get(field, '')).startswith('項目')
        def translate(text, history, *extra):
            emitted.append((deepcopy(text), history, extra))
            values = ['EN:'+value for value in text]
            return [values[:-1] if malformed[0] else values, [len(text), len(text)*2]]
        module.translateAI = translate
        def search(item, _bar):
            keys = [key for key in fields if item.get(key) and module._entry_field_needs_translation(item, key)]
            if not keys: return [0, 0]
            source = [item.get('_original', {}).get(key, item[key]) for key in keys]
            output, tokens = module.translateAI(source, 'State instructions', False)
            item.setdefault('_original', {}).update(zip(keys, source))
            item.update(zip(keys, output))
            return tokens
        module.searchSS = search
        def parse(values, _filename):
            for item in values:
                if item: module.searchSS(item, None)
            return values
        module.parseSS = parse
        def context(_config, payload, _format, _history):
            values = list(json.loads(payload).values())
            glossary = next((value.split('語彙')[1] for value in values if '語彙' in value), '')
            return 'Frozen game context', glossary, '', payload
        translation = SimpleNamespace(protect_script_codes=lambda value: (value, {}), createContextParts=context)
        with TemporaryDirectory() as temporary:
            state_requests.configure(module, translation, temporary, 50)
            actual = module.parseSS(deepcopy(data), 'States.json')
            self.assertEqual(len(emitted), 8)
            self.assertEqual(sum(len(row[0]) for row in emitted), 112)
            self.assertTrue(all(len(row[0]) <= 50 for row in emitted))
            self.assertIn('"stateId": 1', emitted[0][1])
            self.assertIn('"field": "name"', emitted[0][1])
            for before, after in zip(data[1:], actual[1:]):
                self.assertEqual(after['id'], before['id'])
                for field in before.keys()-{'id'}:
                    self.assertEqual(after[field], 'EN:'+before[field])
                    self.assertEqual(after['_original'][field], before[field])
            saved = next((Path(temporary)/'log').glob('dazedtl-state-groups-*.json'))
            frozen = saved.read_bytes()
            # A growing consume-time glossary must not regroup paid requests.
            translation.createContextParts = Mock(side_effect=AssertionError('Must use saved mapping'))
            emitted.clear()
            self.assertEqual(module.parseSS(deepcopy(data), 'States.json'), actual)
            self.assertEqual(len(emitted), 8)
            self.assertEqual(saved.read_bytes(), frozen)
            partial = deepcopy(data)
            partial[1:21] = deepcopy(actual[1:21])
            emitted.clear()
            self.assertEqual(module.parseSS(partial, 'States.json'), actual)
            self.assertEqual(len(emitted), 8)
            malformed[0] = True
            untouched = deepcopy(data)
            with self.assertRaisesRegex(ValueError, 'response IDs'):
                module.parseSS(untouched, 'States.json')
            self.assertEqual(untouched, data)
            malformed[0] = False
            emitted.clear()
            self.assertEqual(module.translateAI(['他'], 'Other database field')[0], ['EN:他'])
            self.assertEqual(len(emitted), 1)
            changed = deepcopy(data); changed[1]['name'] += '変更'
            with self.assertRaisesRegex(ValueError, 'frozen source'):
                module.parseSS(changed, 'States.json')
            self.assertEqual(len(emitted), 1)
            state_requests.restore(module)
            self.assertIs(module.translateAI, translate)

    def test_process_counts_payload_and_partial_failure_do_not_rewrite_queue(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = {'a': {'payload': '{"Line1":"防御"}', 'params': {'model': 'fixture', 'messages': []}, 'provider': 'openai'},
                     'b': {'payload': '{"Line1":"毒"}', 'params': {'model': 'fixture', 'messages': []}, 'provider': 'openai'}}
            write_json(root/'log/batch_requests.json', {'a': queue['a']})
            write_json(root/'log/batch_requests.json.parts/fragment.json', {'b': queue['b']})
            # A newly accepted Batch has null counts/errors while validating.
            # Its screen refresh and saved payload must stay readable, and
            # unknown work must remain protected from another submission.
            write_json(root/'log/batch_history.json', {'batches': [{'id': 'batch-fixture', 'custom_ids': {'req-000000': 'a'},
                        'api_status': 'in_progress', 'request_counts': None, 'provider_errors': None}]})
            pending = process_view.summary(root, {'mode': 'batch', 'status': 'running'})
            self.assertEqual((pending['failed'], pending['errors'], pending['batches'][0]['counts']), (0, [], {}))
            self.assertTrue(pending['retryBlocked'])
            provider = SimpleNamespace(_openai_batch_body=lambda _provider, params: params)
            with patch.dict('sys.modules', {'util.batch_providers': provider}):
                self.assertEqual(process_view.payload(root, 0)['state'], 'uncertain')
            write_json(root/'log/batch_history.json', {'batches': [{'id': 'batch-fixture', 'custom_ids': {'req-000000': 'a'},
                        'api_status': 'completed', 'request_counts': {'errored': 1}, 'provider_errors': [{'message': 'Unsupported temperature'}]}]})
            frozen = (root/'log/batch_requests.json').read_bytes()
            value = process_view.summary(root, {'mode': 'batch', 'completed': [], 'appliedOutputs': []})
            self.assertEqual((value['prepared'], value['submitted'], value['remaining'], value['received'], value['failed']), (2, 1, 1, 0, 1))
            self.assertTrue(value['retryBlocked'])  # Missing manifest/count proof remains unresolved.
            self.assertIsNone(value['usage'])
            provider = SimpleNamespace(_openai_batch_body=lambda _provider, params: params)
            with patch.dict('sys.modules', {'util.batch_providers': provider}):
                self.assertEqual(process_view.payload(root, 0)['exact']['custom_id'], 'req-000000')
                self.assertEqual(process_view.payload(root, 1)['state'], 'queued')
            with self.assertRaises(ValueError): process_view.payload(root, True)
            self.assertEqual((root/'log/batch_requests.json').read_bytes(), frozen)
            self.assertNotIn('sk-fixture', process_view.clean_message('Bearer sk-fixture; api_key=private-value'))

    def test_provider_error_read_is_sanitized_scoped_and_never_submits_or_rewrites(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            history = {'batches': [{'id': 'batch-fixture', 'provider': 'openai', 'key_name': 'fixture-key', 'custom_ids': {'req-1': 'source-hash'}}]}
            write_json(root/'log/batch_history.json', history)
            frozen = (root/'log/batch_history.json').read_bytes()
            client = Mock(); client.with_options.return_value = client
            package = ModuleType('util')
            package.batch_history = SimpleNamespace(_client_for_entry=Mock(return_value=client))
            package.api_keys = SimpleNamespace(get_secret=Mock(return_value='fixture-private-value'))
            package.batch_providers = SimpleNamespace(retrieve_batch=Mock(return_value={
                'api_status':'completed', 'counts':{'errored':1}, 'errors':[], 'error_file_id':'file-fixture'}),
                _download_file_text=Mock(return_value=json.dumps({'custom_id':'req-1', 'response':{'body':{'error':{
                    'code':'unsupported_value','param':'temperature','message':'Unsupported temperature 0. fixture-private-value'}}}})+'\n'+
                    json.dumps({'custom_id':'unrelated-request','error':{'message':'Unrelated private request'}})))
            with patch.dict('sys.modules', {'util':package}):
                result = process_view.provider_details(root)
            error = result['batches'][0]['errors'][0]
            self.assertEqual((error['code'], error['param']), ('unsupported_value','temperature'))
            self.assertIn('Unsupported temperature 0.', error['message'])
            self.assertNotIn('fixture-private-value', json.dumps(result))
            self.assertNotIn('Unrelated private request', json.dumps(result))
            client.with_options.assert_called_once_with(timeout=20,max_retries=0)
            client.batches.create.assert_not_called(); client.files.create.assert_not_called(); client.batches.cancel.assert_not_called()
            self.assertEqual((root/'log/batch_history.json').read_bytes(), frozen)

    def test_live_receipt_usage_and_validation_are_separate_from_preparation(self):
        with TemporaryDirectory() as temporary:
            evidence = Evidence(temporary, 'translate')
            evidence.prepared({'model': 'fixture', 'messages': []})
            summary = lambda: process_view.summary(temporary, {'mode': 'translate'})
            self.assertEqual((summary()['prepared'], summary()['received'], summary()['validated']), (1, 0, 0))
            interrupted = lambda: process_view.summary(temporary, {'mode': 'translate', 'status': 'interrupted'})
            # A stopped worker may have sent its last payload before receiving or
            # validating it. The saved run must not offer an unguarded retry.
            self.assertFalse(interrupted()['retryBlocked'])
            self.assertEqual(interrupted()['uncertain'], 0)
            evidence.update('submitted')
            self.assertTrue(interrupted()['retryBlocked'])
            self.assertEqual(interrupted()['uncertain'], 1)
            evidence.update('received', {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15})
            self.assertEqual((summary()['received'], summary()['validated']), (1, 0))
            self.assertTrue(interrupted()['retryBlocked'])
            self.assertEqual(interrupted()['uncertain'], 0)
            self.assertEqual(summary()['usage']['total_tokens'], 15)
            evidence.update('validated', {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15})
            self.assertEqual(summary()['validated'], 1)
            self.assertFalse(interrupted()['retryBlocked'])
            self.assertEqual(process_view.payload(temporary, 0)['state'], 'validated')
