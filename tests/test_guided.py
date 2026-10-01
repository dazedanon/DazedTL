"""Guided approvals must retain scope, ownership and one-use submission intent."""

from copy import deepcopy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from dazedtl.projects.store import Projects
from dazedtl.storage import write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import evidence, read_json, digest
from dazedtl.translation.guided import Guided
from dazedtl.translation.guided_inputs import GuidedInputs
from dazedtl.translation.operations import lifecycle_path


class GuidedTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'game'
        write_json(self.source / 'Items.json', [{'name': '薬'}])
        self.projects = Projects(self.root / 'profile')
        self.record = self.projects.open({'source': str(self.source), 'engine': 'MVMZ'})
        self.identity = self.record['id']
        self.record['backend_id'] = 'native'
        self.projects.save()
        self.native = {'id': 'native', 'source': str(self.source), 'engine': 'MVMZ', 'revision': 0,
                       'selected': ['Items.json'], 'imported': ['Items.json'], 'mode': 'batch',
                       'engine_options': {}, 'widths': {'width': 50, 'faceWidth': 40, 'listWidth': 50, 'noteWidth': 50},
                       'phase1_comments': False, 'data': str(self.source)}
        self.started = []
        self.pending = None
        self.folder = self.root / 'work'
        self.folder.mkdir()
        def update(_identity, revision, values):
            if revision != self.native['revision']:
                raise ValueError('Changed')
            self.native.update(values)
            self.native['revision'] += 1
            return {'project': self.native}
        workflows = SimpleNamespace(projects={'native': self.native}, folder=lambda _: self.folder,
            state=lambda _: {'project': self.native, 'manual_job': self.pending}, update=update, save=Mock(),
            phase=lambda owner, phase, sync: self.started.append((owner, phase, sync)) or {'id': 'paid-run'})
        self.backend = SimpleNamespace(workflows=workflows, running=lambda: False,
            phase_files=lambda _native, _phase: ['Items.json'],
            guided_guard=lambda _native, _folder: evidence(self.source, ['Items.json']),
            guided_runtime_files=lambda _source: ['Items.json'])
        self.backend.guided_phase = lambda owner, phase, files: self.backend.workflows.phase(owner, phase, True)
        self.settings_revision = 1
        self.settings = SimpleNamespace(prepare_engine=lambda **_kwargs: None, describe=lambda: {'revision': self.settings_revision})
        self.translation = SimpleNamespace(workspace=self.root / 'profile', jobs=SimpleNamespace(running=lambda: False),
            engine=SimpleNamespace(source_bindings=lambda _source, _paths: {}, original_bytes=lambda *_args: b''),
            clean_drafts=lambda _: None, ready=Mock(), operation=Mock(return_value={'id': 'operation'}))
        self.guided = Guided(self.backend, self.projects, self.settings, self.translation)
        saved = snapshot(self.source, store_path(self.source), source_game=True)
        write_json(lifecycle_path(self.translation.workspace, self.identity), {'version': 1, 'source_backup': saved})

    def preview(self):
        return self.guided.preview(self.identity, 'start', options={'mode': 'batch'})

    def test_submission_preview_rejects_other_owner_changed_inputs_and_repeated_use(self):
        preview = self.preview()
        self.assertTrue(preview['confirmation'])
        other = self.projects.open({'source': str(self.root), 'engine': 'MVMZ'})
        with self.assertRaises(ValueError):
            self.guided.execute(other['id'], preview['token'])
        self.assertEqual(self.started, [])
        # Switching the visible project never retargets an existing approval.
        result = self.guided.execute(self.identity, preview['token'])
        self.assertEqual(result['id'], 'paid-run')
        self.assertEqual(self.started, [('native', 'database', True)])
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        for mutate in (lambda: write_json(self.source / 'Items.json', [{'name': '別'}]),
                       lambda: setattr(self, 'settings_revision', 2),
                       lambda: self.native.update(revision=self.native['revision'] + 1),
                       lambda: self.projects.get(self.identity).update(phase='dialogue')):
            with self.subTest(mutate=mutate):
                preview = self.preview()
                mutate()
                with self.assertRaises(ValueError):
                    self.guided.execute(self.identity, preview['token'])
                write_json(self.source / 'Items.json', [{'name': '薬'}])
        self.assertEqual(len(self.started), 1)
        self.native['manual_job'] = 'paid-run'
        self.backend.manual = SimpleNamespace(export=Mock(return_value={'path': 'saved-output'}))
        self.backend.saved_run_configuration = lambda _: {'workflow': {'id': 'native'}}
        with self.assertRaises(ValueError):
            self.guided.export(self.identity, 'other-project-run')
        self.backend.manual.export.assert_not_called()
        self.guided.export(self.identity, 'paid-run')
        self.backend.manual.export.assert_called_once_with('paid-run')
        self.backend.saved_run_configuration = lambda _: {'workflow': {'id': 'other-project'}}
        with self.assertRaises(ValueError):
            self.guided.export(self.identity, 'paid-run')
        self.assertEqual(self.backend.manual.export.call_count, 1)

    def test_agent_modes_drafts_and_missing_backup_cannot_start_or_mutate(self):
        for mode in ('agent', 'offline', 'live', 'unknown'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.guided.preview(self.identity, 'start', options={'mode': mode})
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, 'import', files=['Unsupported.json'])
        preferences = self.guided.preferences(self.native)
        self.guided.options_draft(self.identity, preferences)
        with self.assertRaises(ValueError):
            self.preview()
        self.guided.save_options(self.identity, preferences['revision'], preferences['values'])
        self.assertIsNotNone(self.preview()['token'])
        lifecycle_path(self.translation.workspace, self.identity).unlink()
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, 'format_data')
        self.assertEqual(self.started, [])

    def test_new_runtime_file_after_git_preview_cannot_enter_the_baseline_unreviewed(self):
        self.backend.guided_runtime_files = lambda _: sorted(path.name for path in self.source.glob('*.json'))
        preview = self.guided.preview(self.identity, 'git_setup', options={'version': '1.0', 'untranslated': True})
        self.assertTrue(preview['confirmation'])
        write_json(self.source / 'NewFile.json', [{'name': 'New scope'}])
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.translation.operation.assert_not_called()

    def test_immediate_preparation_keeps_one_use_execution_and_backup_checks(self):
        self.backend.workflows.preview = lambda _owner, action, options: {
            'token': action + '-token', 'options': options, 'confirmation': True}
        self.backend.workflows.execute = Mock(return_value={'id': 'native-operation'})
        for action in ('format_data', 'format_plugins', 'gameupdate'):
            with self.subTest(action=action):
                preview = self.guided.preview(self.identity, action)
                self.assertFalse(preview['confirmation'])
                self.assertEqual(self.guided.execute(self.identity, preview['token'])['id'], 'native-operation')
                self.backend.workflows.execute.assert_called_with(preview['token'])
                with self.assertRaises(ValueError):
                    self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, 3)
        preview = self.guided.preview(self.identity, 'format_data')
        self.settings_revision += 1
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, 3)
        self.assertTrue(self.guided.preview(self.identity, 'playtest_install')['confirmation'])
        preview = self.guided.preview(self.identity, 'format_data')
        shutil.rmtree(self.source / '.dazedtl')
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, 3)

    def test_an_estimate_cannot_replace_an_interrupted_paid_run_reference(self):
        self.pending = {'id': 'provider-run', 'mode': 'batch', 'status': 'interrupted'}
        for mode in ('batch', 'translate', 'estimate', 'speakers'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.guided.preview(self.identity, 'start', options={'mode': mode})
        self.assertEqual(self.pending['id'], 'provider-run')
        self.assertEqual(self.started, [])

    def test_deleted_backup_can_be_replaced_but_cannot_authorize_preparation(self):
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, 'backup_source')
        previous = read_json(lifecycle_path(self.translation.workspace, self.identity))
        shutil.rmtree(self.source / '.dazedtl')
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, 'format_data')
        preview = self.guided.preview(self.identity, 'backup_source')
        self.assertEqual(preview['destination'], str(self.source / '.dazedtl/backups/v2'))
        self.guided.execute(self.identity, preview['token'])
        self.translation.operation.assert_called_once_with(self.identity, 'backup_source', {})
        self.assertEqual(read_json(lifecycle_path(self.translation.workspace, self.identity)), previous)

    def test_estimate_freezes_estimate_mode_without_changing_the_saved_api_choice(self):
        observed = []
        def phase(*_args):
            observed.append(self.native['mode'])
            return {'id': 'estimate'}
        self.backend.workflows.phase = phase
        for mode in ('translate', 'batch'):
            with self.subTest(mode=mode):
                self.native['mode'] = mode
                preview = self.guided.preview(self.identity, 'start', options={'mode': 'estimate'})
                self.guided.execute(self.identity, preview['token'])
                self.assertEqual(self.guided.preferences(self.native)['values']['mode'], mode)
        self.assertEqual(observed, ['estimate', 'estimate'])

    def test_checkpoint_manifest_distinguishes_new_plugins_from_original_assets(self):
        write_json(self.source / 'new-plugin.js', {'fixture': True})
        manifest = self.guided.patch_manifest(self.identity, ['Items.json', 'new-plugin.js'], 'checkpoint')
        self.assertEqual(manifest['files']['Items.json'], {})
        self.assertEqual(manifest['files']['new-plugin.js'], {'original_sha256': None})
        # A source file already tracked on original is not a translation-only addition.
        self.translation.engine.source_bindings = lambda *_args: {'new-plugin.js': 'original-blob'}
        self.assertEqual(self.guided.patch_manifest(self.identity, ['new-plugin.js'], 'checkpoint')['files']['new-plugin.js'], {})

    def test_reopening_refreshes_inventory_without_losing_options_or_run_ownership(self):
        pending = self.guided.preferences(self.native)
        self.guided.options_draft(self.identity, pending)
        self.native['manual_job'] = 'saved-batch'
        self.backend.describe = lambda _: {'source': str(self.source), 'engine': 'MVMZ',
                                          'files': [{'name': 'Items.json'}, {'name': 'Map002.json'}]}
        self.backend.workflows.save = Mock()
        self.guided.open(self.identity)
        _, refreshed = self.guided.record(self.identity)
        self.assertEqual([row['name'] for row in refreshed['files']], ['Items.json', 'Map002.json'])
        self.assertEqual(refreshed['manual_job'], 'saved-batch')
        self.assertEqual(refreshed['selected'], ['Items.json'])
        self.assertEqual(refreshed['mode'], 'batch')
        self.assertEqual(self.record['backend_id'], 'native')
        self.assertEqual(read_json(self.guided.path(self.identity, 'draft')), pending)

    def test_checked_scope_controls_the_next_run_and_expanding_it_keeps_phase_work(self):
        write_json(self.source/'System.json', {'gameTitle': 'ゲーム'})
        self.backend.phase_files = lambda _native, _phase: ['Items.json', 'System.json']
        self.native['imported'] = ['Items.json', 'System.json']
        write_json(self.folder/'files/System.json', {'gameTitle': 'Saved phase work'})
        calls = []
        self.backend.guided_phase = lambda owner, phase, files: calls.append(files) or {'id': 'run'}
        preview = self.preview()
        self.assertEqual(preview['paths'], ['Items.json'])
        self.guided.execute(self.identity, preview['token'])
        self.assertEqual(calls, [['Items.json']])
        self.assertEqual(read_json(self.folder/'files/System.json'), {'gameTitle': 'Saved phase work'})
        self.assertEqual(read_json(self.folder/'files/Items.json'), [{'name': '薬'}])
        self.native['selected'] = []
        with self.assertRaises(ValueError):
            self.preview()
        self.assertEqual(len(calls), 1)

    def test_source_drift_blocks_new_work_and_refresh_preserves_previous_outputs(self):
        inputs = self.guided.inputs(self.native)
        inputs.prepare(['Items.json'])
        write_json(self.folder/'translated/Items.json', [{'name': 'Potion'}])
        write_json(self.folder/'files/Items.json', [{'name': 'Saved database phase'}])
        write_json(self.source/'Items.json', [{'name': '新しい薬'}])
        with self.assertRaises(ValueError):
            self.preview()
        self.assertEqual(read_json(self.folder/'files/Items.json'), [{'name': 'Saved database phase'}])
        refreshed = inputs.prepare(['Items.json'], refresh=True, expected=inputs.sources(['Items.json'], inputs.record()['inputs']), retired=['former-run'])
        archive = Path(refreshed['archive'])
        self.assertEqual(read_json(archive/'translated/Items.json'), [{'name': 'Potion'}])
        self.assertEqual(read_json(archive/'files/Items.json'), [{'name': 'Saved database phase'}])
        self.assertFalse((self.folder/'translated/Items.json').exists())
        self.assertEqual(inputs.record()['retired_runs'], ['former-run'])
        self.assertEqual(read_json(self.folder/'files/Items.json'), [{'name': '新しい薬'}])
        self.assertIsNotNone(self.preview()['token'])
        with self.assertRaises(ValueError):
            inputs.prepare(['Items.json'], refresh=True, expected={})

    def test_original_blobs_seed_new_work_and_exact_applied_exports_are_not_source_drift(self):
        write_json(self.source/'Items.json', [{'name': 'English runtime'}])
        inputs = GuidedInputs(self.folder, self.source, self.source,
                              lambda *_args: {'Items.json': 'original'}, lambda *_args: b'[{"name":"Japanese baseline"}]')
        inputs.prepare(['Items.json'])
        self.assertEqual(read_json(self.folder/'files/Items.json'), [{'name': 'Japanese baseline'}])
        self.assertEqual(inputs.status(['Items.json'])['changed'], [])
        # Native Ace JSON exports do not live in Git; an exact applied output is
        # still the same source identity, while unrelated edits require review.
        self.guided.inputs(self.native).prepare(['Items.json'], refresh=True)
        write_json(self.folder/'translated/Items.json', [{'name': 'Applied English'}])
        (self.source/'Items.json').write_bytes((self.folder/'translated/Items.json').read_bytes())
        self.assertEqual(self.guided.inputs(self.native).status(['Items.json'])['changed'], [])
        write_json(self.source/'Items.json', [{'name': 'Changed export'}])
        self.assertEqual(self.guided.inputs(self.native).status(['Items.json'])['changed'], ['Items.json'])
        native_inputs = GuidedInputs(self.folder, self.source, self.source,
                                     lambda *_: {'Data/Items.rvdata2': 'native-original'}, lambda *_: b'', native_exports=True)
        native_inputs.prepare(['Items.json'], refresh=True)
        write_json(self.source/'Items.json', [{'name': 'Fitted runtime English'}])
        self.assertEqual(native_inputs.status(['Items.json'])['changed'], [])
        native_inputs.bindings = lambda *_: {'Data/Items.rvdata2': 'new-native-original'}
        self.assertEqual(native_inputs.status(['Items.json'])['changed'], ['Items.json'])

    def test_fitting_does_not_request_reapplication_and_changed_review_or_missing_output_is_pending(self):
        self.native['files'] = [{'name': 'Items.json'}]
        write_json(self.source/'Items.json', [{'name': 'Applied English'}])
        raw = (self.source/'Items.json').read_bytes()
        write_json(self.folder/'translated/Items.json', [{'name': 'Applied English'}])
        write_json(self.folder/'applied-outputs.json', {'version': 1, 'files': {'Items.json': digest(raw)}})
        state = read_json(lifecycle_path(self.translation.workspace, self.identity))
        state['guided_review'] = {'evidence': evidence(self.source, ['Items.json'])}
        write_json(lifecycle_path(self.translation.workspace, self.identity), state)
        first = self.guided.readiness(self.identity, self.native, {'jobs': []})
        self.assertTrue(first['review_current'])
        write_json(self.source/'Items.json', [{'name': 'Fitted\nEnglish'}])
        changed = self.guided.readiness(self.identity, self.native, {'jobs': []})
        self.assertEqual(changed['applied'], ['Items.json'])
        self.assertEqual(changed['runtime_edited'], ['Items.json'])
        self.assertFalse(changed['review_current'])
        (self.folder/'translated/Items.json').unlink()
        self.assertEqual(self.guided.readiness(self.identity, self.native, {'jobs': []})['outputs'], [])
