"""Automatic reads/collection cannot resume unsent work or hold the API lock."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from dazedtl.compatibility import batch_control
from dazedtl.storage import write_json
from dazedtl.translation.batch_monitor import BatchMonitor
from dazedtl.translation.files import read_json


class BatchMonitorTests(unittest.TestCase):
    def fixture(self, root):
        batch = {'id': 'paid', 'provider': 'openai', 'custom_ids': {'one': 'key'}}
        write_json(root/'log/batch_history.json', {'batches': [batch]})
        write_json(root/'log/batch_state.json', {'status': 'partially_submitted', 'batches': [batch]})
        write_json(root/'log/batch_requests.json', {'key': {'payload': '{"Line1":"薬"}', 'params': {}},
                                                   'unsent': {'payload': '{"Line1":"盾"}', 'params': {}}})
        job = {'id': 'run', 'mode': 'batch', 'status': 'stopped'}
        source = str(root/'game')
        owner = {'id': 'project', 'backend_id': 'native', 'source': source}
        lock = threading.RLock()
        manual = SimpleNamespace(jobs={'run': job}, folder=lambda _: root,
            controller=lambda _: SimpleNamespace(running=lambda: False), resume=Mock(), save=Mock())
        backend = SimpleNamespace(lock=lock, context=lambda: lock, allow_providers=True, manual=manual,
            saved_run_configuration=lambda _: {'mode': 'batch', 'workflow': {'id': 'native'}},
            workflows=SimpleNamespace(projects={'native': {'id': 'native', 'source': source}}))
        def consume(identity):
            self.assertEqual(identity, 'run')
            self.assertEqual(read_json(root/'log/batch_state.json')['status'], 'fetched')
            job['status'] = 'running'
        manual.consume_batch = Mock(side_effect=consume)
        settings = SimpleNamespace(prepare_engine=Mock(), batch_connection=Mock(return_value={
            'secret': 'fixture', 'endpoint': 'https://fixture.invalid', 'organization': ''}))
        guided = SimpleNamespace(backend=backend, settings=settings, projects=SimpleNamespace(data={'projects': [owner]}))
        return BatchMonitor(guided), job, owner

    def test_old_pauses_monitor_then_consume_once_without_sending_the_unsent_queue(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            provider = Mock()
            provider.status.return_value = {'api_status': 'in_progress', 'counts': {'processing': 1}}
            provider.collect_terminal.return_value = ({'key': {'text': '{"Line1":"Medicine"}'}}, [], {})
            queue = (root/'log/batch_requests.json').read_bytes()
            with patch.object(batch_control, 'TranslationProvider', return_value=provider):
                monitor.backend.allow_providers = False
                monitor.tick()
                provider.status.assert_not_called()
                monitor.backend.allow_providers = True
                for change in ({'status': 'running'}, {'status': 'waiting'}, {'status': 'complete'}, {'dazedtl_preapproval': True}):
                    original = deepcopy(job)
                    job.update(change)
                    monitor.tick()
                    job.clear(); job.update(original)
                provider.status.assert_not_called()
                # Missing state or unsent-only work must never start a worker.
                write_json(root/'log/batch_state.json', {'status': 'queued'})
                monitor.tick()
                provider.status.assert_not_called()
                self.assertEqual(monitor.views['run']['state'], 'blocked')
                write_json(root/'log/batch_state.json', {'status': 'partially_submitted'})
                monitor.tick()
                self.assertEqual(monitor.views['run']['batches'][0]['counts'], {'processing': 1})
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.status.return_value = {'api_status': 'cancelled', 'counts': {'succeeded': 1, 'canceled': 0}}
                monitor.tick()
                monitor.backend.manual.consume_batch.assert_called_once_with('run')
                self.assertEqual((root/'log/batch_requests.json').read_bytes(), queue)
                self.assertEqual(read_json(root/'log/batch_results.json')['key']['text'], '{"Line1":"Medicine"}')
                monitor.tick()
                job['status'] = 'failed'
                monitor.tick()
                self.assertEqual(monitor.views['run']['state'], 'save_error')
                monitor.backend.manual.consume_batch.assert_called_once()
                # Reopening after downloaded responses skips provider reads
                # entirely and performs only the guarded local save.
                reads = provider.status.call_count
                reopened = BatchMonitor(monitor.guided)
                reopened.tick()
                self.assertEqual(provider.status.call_count, reads)
                self.assertEqual(monitor.backend.manual.consume_batch.call_count, 2)
            monitor.backend.manual.resume.assert_not_called()
            provider.submit.assert_not_called(); provider.live.assert_not_called(); provider.cancel.assert_not_called()

    def test_stalled_read_releases_api_lock_and_late_results_cannot_cross_close_or_ownership(self):
        for change in ('close', 'owner'):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory)
                monitor, _, owner = self.fixture(root)
                started, release = threading.Event(), threading.Event()
                provider = Mock()
                def status(_):
                    started.set()
                    if not release.wait(2):
                        raise RuntimeError('Fixture read was not released')
                    return {'api_status': 'completed', 'counts': {'succeeded': 1}}
                provider.status.side_effect = status
                provider.collect_terminal.return_value = ({'key': {'text': 'saved'}}, [], {})
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with patch.object(batch_control, 'TranslationProvider', return_value=provider):
                    thread = threading.Thread(target=monitor.tick)
                    thread.start()
                    try:
                        self.assertTrue(started.wait(1))
                        acquired = monitor.backend.lock.acquire(timeout=.1)
                        self.assertTrue(acquired, 'A stalled provider read held the navigation/API lock')
                        if acquired:
                            if change == 'close': monitor.close()
                            else: owner['source'] = str(root/'another-game')
                            monitor.backend.lock.release()
                    finally:
                        release.set()
                        thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertFalse((root/'log/batch_results.json').exists())
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.submit.assert_not_called(); provider.live.assert_not_called()

    def test_all_rejected_batches_do_not_start_a_futile_save_or_retry_loop(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            provider = Mock()
            provider.status.return_value = {'api_status': 'completed', 'counts': {'succeeded': 0, 'errored': 1, 'processing': 0}}
            provider.collect_terminal.return_value = ({}, ['one'], {})
            with patch.object(batch_control, 'TranslationProvider', return_value=provider):
                monitor.tick()
                reads = provider.status.call_count
                monitor.tick()
                self.assertEqual(provider.status.call_count, reads)
                self.assertNotIn('run', monitor.views)
                self.assertEqual(job['status'], 'failed')
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.submit.assert_not_called(); provider.live.assert_not_called()
