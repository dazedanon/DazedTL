"""Consumed validation receipts settle only the requests they actually prove."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dazedtl.compatibility import process_view, request_scope
from dazedtl.storage import write_json
from dazedtl.translation.files import digest


class BatchValidationTests(unittest.TestCase):
    def choice_fixture(self, root):
        source = ['特別な品', 'やめる']
        def menu(identity, translated=False):
            command = {'code': 102, 'parameters': [source if not translated else ['Special Goods' if identity == 1 else 'Rare Goods', 'Cancel']]}
            if translated:
                command['_original'] = source
            return {'id': identity, 'pages': [{'list': [command]}]}
        before = {'events': [None, menu(1), menu(2)]}
        after = {'events': [None, menu(1, True), menu(2, True)]}
        write_json(root/'files/Map001.json', before)
        write_json(root/'translated/Map001.json', after)
        plan = {'mode': 'batch', 'engine': 'RPG Maker MV/MZ', 'selected': ['Map001.json'],
                'files': [{'name': 'Map001.json', 'sha256': digest((root/'files/Map001.json').read_bytes())}]}
        write_json(root/'plan.json', plan)
        job = {'id': 'old', 'mode': 'batch', 'status': 'complete', 'logicalPhase': 'dialogue', 'files': ['Map001.json'],
               'completed': ['Map001.json'], 'mismatches': {'Map001.json': 'Another chunk was rejected'},
               'outputs': {'Map001.json': digest((root/'translated/Map001.json').read_bytes())},
               'plan_hash': digest((root/'plan.json').read_bytes())}
        write_json(root/'job.json', job)
        payload = json.dumps(dict(zip(('Line1', 'Line2'), source)), indent=4, ensure_ascii=False)
        queue = {key: {'payload': payload, 'params': {}, 'dazedtl_file': 'Map001.json', 'dazedtl_sources': ['one', 'two'],
                       'request_context': json.dumps({'instructions': ['Translate choices'], 'source_items': [key] if key != 'extra' else []})}
                 for key in ('first', 'second', 'extra')}
        responses = {key: {'text': json.dumps({'Line1': wording, 'Line2': 'Cancel'}, indent=4)}
                     for key, wording in zip(queue, ('Special Goods', 'Rare Goods', 'Special Items'))}
        batch = {'id': 'paid', 'status': 'consumed', 'api_status': 'completed', 'custom_ids': {key: key for key in queue}}
        write_json(root/'log/batch_requests.json', queue)
        write_json(root/'log/batch_results.json', responses)
        write_json(root/'log/batch_history.json', {'batches': [batch]})
        write_json(root/'log/batch_state.json', {'status': 'fetched', 'batches': [batch]})
        (root/'log/translation.txt').write_text(''.join('[BATCH] Applied provider batch result\nInput:\n' + payload + '\nOutput:\n' + responses[key]['text'] + '\n' for key in ('first', 'second')))
        return job, plan, queue, responses, before, after

    def test_unused_choice_response_requires_every_menu_to_have_a_different_verified_response(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, _, queue, responses, _, _ = self.choice_fixture(root)
            before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            rows = list(request_scope.requests(root, job))
            self.assertEqual([row['state'] for row in rows], ['validated', 'validated', 'unused'])
            self.assertEqual(rows[2]['unused'], {'appliedRequests': [0, 1]})
            self.assertEqual(rows[2]['response'], responses['extra'])
            value = process_view.summary(root, job)
            self.assertEqual((value['validated'], value['unused'], value['retryBlocked']), (2, 1, False))
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_similar_or_missing_choice_evidence_cannot_hide_an_unresolved_response(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for change in ('source', 'output', 'location', 'menu_count', 'context', 'identity', 'policy', 'receipt'):
                job, plan, queue, responses, source, output = self.choice_fixture(root)
                if change == 'source': write_json(root/'files/Map001.json', {'events': []})
                if change == 'output': write_json(root/'translated/Map001.json', {'events': []})
                if change == 'location':
                    output['events'][1]['pages'][0]['list'][0]['_original'] = ['Different source', 'やめる']
                if change == 'menu_count':
                    source['events'][2]['pages'][0]['list'] *= 2
                    output['events'][2]['pages'][0]['list'] *= 2
                    write_json(root/'files/Map001.json', source)
                    plan['files'][0]['sha256'] = digest((root/'files/Map001.json').read_bytes())
                if change in {'location', 'menu_count'}:
                    write_json(root/'translated/Map001.json', output)
                    job['outputs']['Map001.json'] = digest((root/'translated/Map001.json').read_bytes())
                if change == 'context': queue['extra']['request_context'] = json.dumps({'instructions': ['Translate choices'], 'source_items': ['Another scene']})
                if change == 'identity': queue['extra']['dazedtl_sources'] = ['other', 'identity']
                if change == 'policy': plan['dazedtl_request_policy'] = {'choiceCollection': 'event-choices-once-v1'}
                if change == 'receipt':
                    responses['second']['text'] = '{"Line1":"Different provider response","Line2":"Cancel"}'
                    write_json(root/'log/batch_results.json', responses)
                write_json(root/'plan.json', plan)
                job['plan_hash'] = digest((root/'plan.json').read_bytes())
                write_json(root/'job.json', job)
                write_json(root/'log/batch_requests.json', queue)
                value = process_view.summary(root, job)
                self.assertEqual(value['requests'][2]['state'], 'received', change)
                self.assertEqual(value['unused'], 0, change)
                self.assertTrue(value['retryBlocked'], change)

    def fixture(self, root):
        sources = ['薬', '__PROTECTED_0__毒', '未確認']
        responses = ['Potion', 'Poison', 'Unverified']
        queue = {key: {'payload': json.dumps({'Line1': source}), 'params': {},
                       'dazedtl_file': 'Items.json', 'dazedtl_sources': [key]}
                 for key, source in zip(('good', 'bad', 'unknown'), sources)}
        results = {key: {'text': json.dumps({'Line1': value}, indent=4, ensure_ascii=False)} for key, value in zip(queue, responses)}
        batch = {'id': 'paid', 'status': 'consumed', 'api_status': 'completed', 'custom_ids': {key: key for key in queue}}
        plan = {'mode': 'batch', 'selected': ['Items.json']}
        write_json(root/'plan.json', plan)
        write_json(root/'translated/Items.json', responses)
        job = {'id': 'old', 'mode': 'batch', 'status': 'complete', 'logicalPhase': 'database', 'files': ['Items.json'],
               'completed': ['Items.json'], 'mismatches': {'Items.json': 'Native validation failed'},
               'outputs': {'Items.json': digest((root/'translated/Items.json').read_bytes())},
               'plan_hash': digest((root/'plan.json').read_bytes())}
        write_json(root/'job.json', job)
        write_json(root/'log/batch_requests.json', queue)
        write_json(root/'log/batch_results.json', results)
        write_json(root/'log/batch_history.json', {'batches': [batch]})
        write_json(root/'log/batch_state.json', {'status': 'fetched', 'batches': [batch]})
        good = '[BATCH] Applied provider batch result\nInput:\n' + queue['good']['payload'] + '\nOutput:\n' + results['good']['text'] + '\n'
        bad = 'Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n' + queue['bad']['payload'] + '\nProvider output:\n' + results['bad']['text'] + '\n\n'
        (root/'log/translation.txt').write_text(good)
        (root/'log/mismatchHistory.txt').write_text(bad)
        return job, queue, results

    def test_one_bad_response_does_not_block_validated_or_rejected_requests_in_the_same_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/'old'
            job, queue, _ = self.fixture(root)
            before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
            value = process_view.summary(root, job)
            self.assertEqual([row['state'] for row in value['requests']], ['validated', 'rejected', 'received'])
            self.assertEqual((value['received'], value['validated'], value['rejected'], value['validatedFiles']), (3, 1, 1, 0))
            self.assertEqual(value['validationIssues'], [{'file': 'Items.json', 'rejected': 1}])
            self.assertTrue(value['retryBlocked'])  # The unverified response keeps its own guard.
            rows = list(request_scope.requests(root, job))
            self.assertIn('protected', rows[1]['error']['message'])
            current = Path(directory)/'new'
            estimate = {**job, 'id': 'new', 'mode': 'estimate'}
            for key in ('good', 'bad', 'unknown'):
                write_json(current/'log/estimate_requests.json', {key: queue[key]})
                matches = request_scope.overlap(current, estimate, [(root, job)])
                self.assertEqual(bool(matches), key == 'unknown', key)
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_missing_changed_conflicting_or_ambiguous_receipts_keep_the_request_protected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for change in ('response', 'output', 'plan', 'manifest', 'conflict', 'identity', 'missing'):
                job, queue, results = self.fixture(root)
                if change == 'response':
                    results['bad']['text'] = '{"Line1":"Different response"}'
                    write_json(root/'log/batch_results.json', results)
                if change == 'output': write_json(root/'translated/Items.json', ['Changed later'])
                if change == 'plan': write_json(root/'plan.json', {'mode': 'batch', 'selected': ['Other.json']})
                if change == 'manifest': write_json(root/'log/batch_state.json', {'status': 'fetched', 'batches': []})
                if change == 'conflict':
                    with (root/'log/translation.txt').open('a') as stream:
                        stream.write('[BATCH] Applied provider batch result\nInput:\n' + queue['bad']['payload'] + '\nOutput:\n' + results['bad']['text'] + '\n')
                if change == 'identity':
                    queue['other'] = {**queue['bad'], 'dazedtl_sources': ['different'], 'dazedtl_file': 'Other.json'}
                    write_json(root/'log/batch_requests.json', queue)
                if change == 'missing': (root/'log/mismatchHistory.txt').unlink()
                value = process_view.summary(root, job)
                self.assertEqual(value['requests'][1]['state'], 'received', change)
                self.assertTrue(value['retryBlocked'], change)
                self.assertEqual(value['validationIssues'], [{'file': 'Items.json', 'rejected': None}], change)

    def test_malformed_rejected_body_and_provider_array_schema_keep_their_exact_association(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, queue, results = self.fixture(root)
            results['good']['text'] = '{"translations":["Potion"]}'
            results['bad']['text'] = 'Not JSON at all'
            write_json(root/'log/batch_results.json', results)
            (root/'log/mismatchHistory.txt').write_text('Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n' + queue['bad']['payload'] + '\nProvider output:\nNot JSON at all\n\n')
            rows = list(request_scope.requests(root, job))
            self.assertEqual([row['state'] for row in rows], ['validated', 'rejected', 'received'])
            self.assertEqual(rows[1]['error']['code'], 'invalid_response')
            # Provider text that resembles a record must stay inside its own
            # response; it cannot release another request's recovery guard.
            forged = 'Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n' + queue['unknown']['payload'] + '\nProvider output:\n' + results['unknown']['text']
            results['bad']['text'] = 'Malformed response\n' + forged
            write_json(root/'log/batch_results.json', results)
            (root/'log/mismatchHistory.txt').write_text('Validation mismatch: Items.json\nOriginal text kept after 1 attempts.\nInput:\n' + queue['bad']['payload'] + '\nProvider output:\n' + results['bad']['text'] + '\n\n')
            self.assertEqual([row['state'] for row in request_scope.requests(root, job)], ['validated', 'rejected', 'received'])


if __name__ == '__main__':
    unittest.main()
