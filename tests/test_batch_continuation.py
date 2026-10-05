"""Approved remainder recovery must neither strand work nor duplicate payment."""
from copy import deepcopy
from contextlib import closing, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import json
import sqlite3
import sys
import unittest
from unittest.mock import Mock, patch

from dazedtl.compatibility import batch_continuation as continuation
from dazedtl.compatibility import batch_refusals
from dazedtl.storage import write_json
from dazedtl.translation.files import digest, read_json


class BatchContinuationTests(unittest.TestCase):
    def fixture(self, root):
        plan = {'mode': 'batch', 'selected': ['Map001.json'], 'settings': {'model': 'fixture', 'api': 'https://fixture.invalid'},
                'key_name': 'saved-key', 'workflow': {'id': 'project'}}
        write_json(root/'plan.json', plan)
        requests = {key: {'provider': 'openai', 'payload': json.dumps({'Line1': key}), 'params': {'model': 'fixture', 'messages': [{'role': 'user', 'content': key}]}}
                    for key in ('one', 'two')}
        quote = {'requests': 2, 'provider': 'openai', 'model': 'fixture'}
        state = {'status': 'queued', 'run_id': 'frozen-run', 'model': 'fixture', 'provider': 'openai', 'endpoint': 'https://fixture.invalid',
                 'file_set': ['Map001.json'], 'batches': [], 'queued_request_count': 2, 'cost_estimate': quote}
        job = {'id': 'run', 'mode': 'batch', 'files': ['Map001.json'], 'estimate': quote, 'plan_hash': digest((root/'plan.json').read_bytes()),
               'dazedtl_approved': True, 'dazedtl_submission_intent': True, 'status': 'stopped'}
        write_json(root/'log/batch_requests.json', requests)
        write_json(root/'log/batch_state.json', state)
        job[continuation.APPROVAL] = continuation.binding(root, job, plan, quote=quote)
        write_json(root/'job.json', job)
        return job, plan, requests, state

    def test_approved_partial_fetch_restores_submission_without_changing_paid_results(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, requests, state = self.fixture(root)
            batch = {'id': 'paid', 'custom_ids': {'req-000000': 'one'}}
            state.update(status='fetched', batches=[batch])
            write_json(root/'log/batch_state.json', state)
            write_json(root/'log/batch_history.json', {'batches': [batch]})
            write_json(root/'log/batch_results.json', {'one': {'text': 'received'}})
            frozen = {p: p.read_bytes() for p in (root/'plan.json', root/'log/batch_requests.json', root/'log/batch_results.json', root/'log/batch_history.json')}
            continuation.prepare_continuation(root, job, plan)
            self.assertEqual(read_json(root/'log/batch_state.json')['status'], 'partially_submitted')
            self.assertTrue(job['dazedtl_continue_batch'])
            self.assertEqual({p: p.read_bytes() for p in frozen}, frozen)
            for flag in ('dazedtl_batch_stopped', 'dazedtl_batch_cancellations'):
                with self.assertRaisesRegex(ValueError, 'stopped or canceled'):
                    continuation.prepare_continuation(root, {**job, flag: True}, plan)
            explicitly_resumed = {**job, 'dazedtl_batch_stopped': True}
            continuation.prepare_continuation(root, explicitly_resumed, plan, explicit=True)
            self.assertNotIn('dazedtl_batch_stopped', explicitly_resumed)
            changed = deepcopy(requests); changed['two']['params']['messages'][0]['content'] = 'changed'
            write_json(root/'log/batch_requests.json', changed)
            with self.assertRaisesRegex(ValueError, 'approved Batch requests changed'):
                continuation.prepare_continuation(root, job, plan)
            write_json(root/'log/batch_requests.json', requests)
            # Old runs may adopt their matching preparation ledger and original
            # quote. A speaker-only approval or changed request cannot do so.
            job.pop(continuation.APPROVAL)
            with closing(sqlite3.connect(root/'log/dazedtl-process.sqlite3')) as db:
                db.execute('CREATE TABLE requests (params TEXT)')
                db.executemany('INSERT INTO requests VALUES (?)', [(json.dumps(row['params']),) for row in requests.values()])
                db.commit()
            self.assertEqual(continuation.approved_binding(root, job, plan)['requests'], 2)
            with self.assertRaises(ValueError):
                continuation.approved_binding(root, {**job, 'estimate': {**job['estimate'], 'requests': 1}}, plan)

    def test_submission_journal_recovers_returned_ids_and_blocks_uncertain_creates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job, plan, requests, state = self.fixture(root)
            util, translation, providers, task, history = [ModuleType(name) for name in
                ('util', 'util.translation', 'util.batch_providers', 'util.translation_task', 'util.batch_history')]
            util.translation, util.batch_providers = translation, providers
            translation._batch_submit_lock = nullcontext
            create = Mock(side_effect=[{'id': 'first'}, {'id': 'second'}])
            create._dazedtl_native = create
            providers.submit_batch = create
            providers.get_client = Mock(return_value=SimpleNamespace(with_options=lambda **_: object()))
            task.TranslationTask = type('Task', (), {'_wait_batch_submit': Mock(return_value=False)})
            def record_submit(batches, **fields):
                previous = continuation.saved(root, 'batch_history.json').get('batches', [])
                write_json(root/'log/batch_history.json', {'batches': previous + [{**fields, **row} for row in batches]})
            history.record_submit = Mock(side_effect=record_submit)
            modules = {module.__name__: module for module in (util, translation, providers, task, history)}
            def request(index):return {'custom_id': f'req-{index:06}', 'params': list(requests.values())[index]['params']}
            with patch.dict(sys.modules, modules):
                continuation.install_worker(root, plan)
                self.assertTrue(task.TranslationTask._wait_batch_submit(SimpleNamespace(should_stop=False), job['estimate']))
                providers.submit_batch('openai', [request(0)])
                self.assertEqual(create.call_count, 1)
                # Simulate loss between the HTTP response and native checkpoint.
                continuation.install_worker(root, plan)
                self.assertEqual(read_json(root/'log/batch_state.json')['batches'][0]['id'], 'first')
                self.assertEqual(read_json(root/'log/batch_history.json')['batches'][0]['id'], 'first')
                continuation.install_worker(root, plan)
                self.assertEqual(create.call_count, 1)
                with self.assertRaisesRegex(ValueError, 'already has a provider receipt'):
                    providers.submit_batch('openai', [request(0)])
                providers.submit_batch('openai', [request(1)])
                continuation.install_worker(root, plan)
                self.assertEqual(read_json(root/'log/batch_state.json')['status'], 'submitted')
                self.assertEqual(create.call_count, 2)
                receipt = read_json(root/'log'/continuation.JOURNAL)
                receipt['intent']['receipt'] = None
                write_json(root/'log'/continuation.JOURNAL, receipt)
                with self.assertRaisesRegex(ValueError, 'uncertain'):
                    continuation.install_worker(root, plan)
                self.assertEqual(create.call_count, 2)

    def test_later_chunks_extend_settled_clarifications_without_losing_or_repeating_them(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'one': {'text': 'refusal'}}
            effective = {'one': {'text': 'retained clarification'}}
            new = {'two': {'text': 'new response'}}
            write_json(root/'log'/batch_refusals.RESULTS, {'original': original, 'results': effective})
            self.assertEqual(batch_refusals.effective_results(root, {**original, **new}, {**original, **new}), {**effective, **new})
            self.assertEqual(batch_refusals.effective_results(root, {}, effective), effective)
            with self.assertRaisesRegex(ValueError, 'conflict'):
                batch_refusals.effective_results(root, {}, {'one': {'text': 'different'}})
            from dazedtl.compatibility.batch_evidence import preserve, ARCHIVE
            write_json(root/'log/batch_history.json', {'batches': [{'id': 'paid', 'custom_ids': {'r1': 'one', 'r2': 'two'}}]})
            preserve(root, {'one': {}, 'two': {}}, {**original, **new}, {})
            preserve(root, {}, {**effective, **new}, {})
            self.assertEqual(read_json(root/'log'/ARCHIVE)['results'], {**original, **new})
