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
from dazedtl.settings.store import Settings


class ProcessTests(unittest.TestCase):
    def test_checkpoint_resume_reads_partial_json_without_mutating_frozen_inputs(self):
        from dazedtl.compatibility import checkpoints
        from dazedtl.storage import write_bytes
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = [{'name': '薬', 'description': '説明'}]
            partial = [{'name': 'Potion', 'description': '説明', '_original': {'name': '薬'}}]
            plan = {'mode': 'translate', 'files': [{'name': 'Items.json'}]}
            write_json(root/'plan.json', plan)
            write_json(root/'files/Items.json', source)
            original = (root/'files/Items.json').read_bytes()
            module = SimpleNamespace(saveProgress=lambda data, name, **_: (write_json(root/'translated'/name, data), True)[1])
            checkpoints.install(module, root, plan)
            module.saveProgress(partial, 'Items.json')
            self.assertIn('Items.json', checkpoints.outputs(root, plan))
            # A fresh worker sees the checkpoint even if the previous process died.
            replacement = SimpleNamespace(saveProgress=module.saveProgress)
            checkpoints.install(replacement, root, plan)
            with replacement.open(root/'files/Items.json', encoding='utf-8') as stream:
                self.assertEqual(json.load(stream), partial)
            self.assertEqual((root/'files/Items.json').read_bytes(), original)
            # Never bless bytes written after the last durable checkpoint receipt.
            write_bytes(root/'translated/Items.json', b'{"different":"unreceipted"}')
            self.assertEqual(checkpoints.outputs(root, plan), {})
            # Batch consumption keeps its frozen request grouping and uses receipts.
            plan['mode'] = 'batch'
            write_json(root/'plan.json', plan)
            (root/checkpoints.INDEX).unlink()
            batch = SimpleNamespace(saveProgress=lambda data, name, **_: (write_json(root/'translated'/name, data), True)[1])
            checkpoints.install(batch, root, plan)
            batch.saveProgress(partial, 'Items.json')
            with batch.open(root/'files/Items.json', encoding='utf-8') as stream:
                self.assertEqual(json.load(stream), source)
            write_json(root/'plan.json', {**plan, 'files': [{'name': 'Foreign.json'}]})
            with self.assertRaises(ValueError):
                checkpoints.outputs(root, plan)

    def test_reopened_evidence_reuses_its_own_validated_results(self):
        with TemporaryDirectory() as temporary:
            evidence = Evidence(temporary, 'translate')
            with evidence.connect() as connection:
                connection.execute('INSERT INTO validated_items VALUES (?,?,?)', ('item', '薬', '"Potion"'))
            reopened = Evidence(temporary, 'translate', {'dazedtl_continuation': {'item': {'source': '薬', 'response': 'Older'}}})
            self.assertEqual(reopened.reused['item'], {'source': '薬', 'response': 'Potion'})

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
            job.update(keptForHistory=True, created='2020-01-01', status='interrupted')
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
            pending_batch = process_view.saved(root, 'batch_history.json')['batches'][0]
            rejected_batch = {**pending_batch, 'id': 'batch-rejected', 'api_status': 'completed',
                              'request_counts': {'processing':0, 'succeeded':0, 'errored':1, 'canceled':0, 'expired':0}}
            write_json(root/'log/batch_state.json', {'status':'submitted', 'batches':[
                {'id': row['id'], 'custom_ids':row['custom_ids']} for row in [pending_batch, rejected_batch]]})
            # A rejected duplicate must not release still-pending work, in
            # either receipt order. Known pending work is not "uncertain".
            for rows in [[pending_batch, rejected_batch], [rejected_batch, pending_batch]]:
                write_json(root/'log/batch_history.json', {'batches':rows})
                known = process_view.summary(root, {'mode':'batch'})
                self.assertTrue(known['retryBlocked']); self.assertEqual(known['uncertain'], 0)
                with patch.dict('sys.modules', {'util.batch_providers': provider}):
                    self.assertEqual(process_view.payload(root, 0)['state'], 'submitted')
            (root/'log/batch_state.json').unlink()
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
                # Per-request usage must not inherit whole-Batch totals, or
                # turn missing/invalid provider counts into zero-token usage.
                self.assertIsNone(process_view.payload(root, 0)['usage'])
                write_json(root/'log/batch_results.json', {'results': {'a': {
                    'text': '{"Line1":"Guard"}', 'prompt_tokens': 42, 'completion_tokens': 5,
                    'cache_read_input_tokens': 0, 'thinking_tokens': None, 'total_tokens': -1,
                    'cache_creation_input_tokens': True}}})
                self.assertEqual(process_view.payload(root, 0)['usage'],
                                 {'input_tokens': 42, 'output_tokens': 5, 'cache_read_input_tokens': 0})
                self.assertIsNone(process_view.payload(root, 1)['usage'])
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
            connection = {'runtime_name': 'fixture-key', 'provider': 'openai', 'protocol': 'openai',
                          'secret': 'fixture-private-value', 'keyless': False, 'endpoint': 'https://provider.invalid/v1', 'organization': 'fixture-org'}
            # The submitted account must resolve from canonical settings even
            # when another account is active and the legacy vault is absent.
            settings = object.__new__(Settings)
            current = {'connections': [connection, {**connection, 'runtime_name': 'other-key', 'secret': 'other-fixture-value'}], 'active': 'other-key'}
            settings._read = lambda: deepcopy(current)
            plan = {'settings': {'api': connection['endpoint'], 'organization': 'fixture-org'}}
            resolve = lambda batch: settings.batch_connection(batch, plan)
            package.batch_providers = SimpleNamespace(retrieve_batch=Mock(return_value={
                'api_status':'completed', 'counts':{'errored':1}, 'errors':[], 'error_file_id':'file-fixture'}),
                get_client=Mock(return_value=client),
                _download_file_text=Mock(return_value=json.dumps({'custom_id':'req-1', 'response':{'body':{'error':{
                    'code':'unsupported_value','param':'temperature','message':'Unsupported temperature 0. fixture-private-value'}}}})+'\n'+
                    json.dumps({'custom_id':'unrelated-request','error':{'message':'Unrelated private request'}})))
            with patch.dict('sys.modules', {'util':package}):
                result = process_view.provider_details(root, resolve)
            error = result['batches'][0]['errors'][0]
            self.assertEqual((error['code'], error['param']), ('unsupported_value','temperature'))
            self.assertIn('Unsupported temperature 0.', error['message'])
            self.assertNotIn('fixture-private-value', json.dumps(result))
            self.assertNotIn('Unrelated private request', json.dumps(result))
            package.batch_providers.get_client.assert_called_once_with('openai',api_key='fixture-private-value',api_url=connection['endpoint'],max_retries=0)
            client.with_options.assert_called_once_with(timeout=20,max_retries=0,organization='fixture-org')
            client.batches.create.assert_not_called(); client.files.create.assert_not_called(); client.batches.cancel.assert_not_called()
            self.assertEqual((root/'log/batch_history.json').read_bytes(), frozen)
            for change in [lambda: current['connections'].pop(0), lambda: connection.update(endpoint='https://other.invalid/v1'),
                           lambda: connection.update(organization='different-org')]:
                baseline = deepcopy(current)
                change()
                with patch.dict('sys.modules', {'util':package}), self.assertRaises(ValueError):
                    process_view.provider_details(root, resolve)
                current.clear(); current.update(baseline); connection = current['connections'][0]
            package.batch_providers.get_client.assert_called_once()

    def test_batch_phase_feedback_uses_receipts_instead_of_stale_scan_progress(self):
        job = {'mode': 'batch', 'status': 'waiting', 'phase': 'submit', 'message': 'Scanning speakers… 3/3',
               'progress': {'current':3,'total':3,'file':'Classes.json'}, 'approval': {'kind':'batch'}}
        frozen = deepcopy(job)
        waiting = process_view.phase_feedback(job)
        self.assertIn('Review the cost', waiting['message']); self.assertIsNone(waiting['progress'])
        self.assertEqual(job, frozen)
        job.update(status='running', phase='poll_status', approval=None,
                   process={'batches':[{'counts':{'succeeded':7,'processing':1}}]})
        polling = process_view.phase_feedback(job)
        self.assertIn('7 completed, 1 processing', polling['message']); self.assertIsNone(polling['progress'])
        job['status'] = 'stopped'
        self.assertIn('monitoring is paused', process_view.phase_feedback(job)['message'])
        job['process']['batches'][0]['status'] = 'completed'
        self.assertIn('Provider work has finished', process_view.phase_feedback(job)['message'])
        job.update(status='failed',message='Actual provider failure')
        self.assertEqual(process_view.phase_feedback(job), {})

    def test_live_receipt_usage_and_validation_are_separate_from_preparation(self):
        with TemporaryDirectory() as temporary:
            evidence = Evidence(temporary, 'translate')
            evidence.prepared({'model': 'fixture', 'messages': []})
            self.assertIsNone(process_view.payload(temporary, 0)['usage'])
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
            self.assertEqual(process_view.payload(temporary, 0)['usage'],
                             {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15})
