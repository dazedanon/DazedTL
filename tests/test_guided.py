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
from dazedtl.translation import speaker_setup, preparation, context_setup, event_text


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
        choices = {'CODE357': ['TextPicture', 'QuestSystem'], 'CODE355655': ['var text', 'gameVariables.setValue']}
        self.catalog = {'fingerprint': 'fixture-definitions', 'source': 'fixture-parser.py', 'controls': [
            {'key': key, 'label': key, 'coverage': 'Installed fixture coverage.', 'selector': event_text.SELECTORS.get(key),
             'choices': [{'id': name, 'group': 'Fixture entries', 'details': name} for name in choices.get(key, [])],
             'builtins': ['BuiltinPlugin'] if key == 'CODE357' else ['AddCmnt('] if key == 'CODE355655' else []}
            for key in event_text.CODES]}
        self.backend.guided_event_text_catalog = lambda: deepcopy(self.catalog)
        def validate_event_options(values):
            if set(values) - set(event_text.FIELDS): raise ValueError('Unknown setting')
            for key, value in values.items():
                if key in event_text.CODES and type(value) is not bool: raise ValueError('Invalid boolean')
                if key == 'CODE122_VAR_RANGES' and not isinstance(value, str): raise ValueError('Invalid ranges')
                for code, selector in event_text.SELECTORS.items():
                    if key == selector and (not isinstance(value, list) or any(item not in choices[code] for item in value)): raise ValueError('Unknown registry identifier')
            return deepcopy(values)
        self.backend.guided_event_text_options = validate_event_options
        self.backend.operations = SimpleNamespace(jobs={}, start=Mock())
        self.backend.describe = lambda _: dict(self.native)
        self.backend.guided_phase = lambda owner, phase, files: self.backend.workflows.phase(owner, phase, True)
        self.settings_revision = 1
        self.configuration = {'model': 'fixture-model', 'endpoint': 'https://provider.invalid/v1', 'rates': {'input': 1, 'output': 2}, 'language': 'English'}
        self.settings = SimpleNamespace(prepare_engine=lambda **_kwargs: None, describe=lambda: {'revision': self.settings_revision},
            guided_configuration=lambda mode: {**deepcopy(self.configuration), 'mode': mode, 'revision': self.settings_revision},
            connection_summary=lambda: {'name': 'Fixture connection'})
        self.backend.manual = SimpleNamespace(jobs={}, folder=lambda identity: self.root / 'runs' / identity)
        self.backend.saved_run_configuration = lambda identity: {'workflow': {'id': 'native', 'phase': self.guided.runs.records(self.identity)[identity]['phase']}}
        self.backend.guided_run_context = lambda: {'system.md': 'fixture-context'}
        self.translation = SimpleNamespace(workspace=self.root / 'profile', jobs=SimpleNamespace(running=lambda: False),
            engine=SimpleNamespace(source_bindings=lambda _source, _paths: {}, original_bytes=lambda *_args: b''),
            clean_drafts=lambda _: None, ready=Mock(), operation=Mock(return_value={'id': 'operation'}))
        self.git_configured = False
        self.translation.project = lambda _: (self.record, SimpleNamespace(root=self.source, read=lambda: {"options": {}}))
        self.translation.engine.git_status = lambda *_: {"configured": self.git_configured}
        self.guided = Guided(self.backend, self.projects, self.settings, self.translation)
        saved = snapshot(self.source, store_path(self.source), source_game=True)
        write_json(lifecycle_path(self.translation.workspace, self.identity), {'version': 1, 'source_backup': saved})

    def test_matching_estimates_survive_reopening_and_reject_each_changed_input(self):
        with self.assertRaisesRegex(ValueError, 'current estimate'):
            self.guided.preview(self.identity, 'start', options={'mode': 'batch'})
        identity = self.seed_estimate()
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        quote, _ = reopened.runs.quote(self.identity, self.native, 'database', 'batch')
        self.assertTrue(quote['current'])
        preview = reopened.preview(self.identity, 'start', options={'mode': 'batch'})
        self.assertEqual(preview['estimate']['jobId'], identity)
        self.assertEqual(preview['estimate']['value'], self.backend.manual.jobs[identity]['estimate'])
        originals = deepcopy(self.native), deepcopy(self.configuration)
        changes = [lambda: self.native['widths'].update(width=51),
                   lambda: self.native['engine_options'].update(NAMES=True),
                   lambda: self.native.update(phase1_comments=True),
                   lambda: self.configuration.update(model='changed-model'),
                   lambda: self.configuration.update(endpoint='https://changed.invalid/v1'),
                   lambda: self.configuration['rates'].update(input=3),
                   lambda: self.configuration.update(language='French')]
        for change in changes:
            change()
            with self.subTest(change=change):
                self.assertFalse(reopened.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
                with self.assertRaises(ValueError):
                    reopened.preview(self.identity, 'start', options={'mode': 'batch'})
            self.native.clear(); self.native.update(deepcopy(originals[0]))
            self.configuration.clear(); self.configuration.update(deepcopy(originals[1]))
        self.assertFalse(reopened.runs.quote(self.identity, self.native, 'database', 'translate')[0]['current'])
        self.backend.guided_run_context = lambda: {'system.md': 'changed-context'}
        self.assertFalse(reopened.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
        self.backend.guided_run_context = lambda: {'system.md': 'fixture-context'}
        self.backend.guided_guard = lambda *_: {'glossary': 'changed-guidance'}
        self.assertFalse(reopened.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
        self.backend.guided_guard = lambda *_: evidence(self.source, ['Items.json'])
        write_json(self.source / 'Items.json', [{'name': '別'}])
        self.assertFalse(reopened.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
        self.assertEqual(self.started, [])

    def test_a_quote_cannot_start_after_pricing_or_runtime_context_changes_in_review(self):
        preview = self.preview()
        self.configuration['rates']['input'] = 3
        with self.assertRaisesRegex(ValueError, 'estimate inputs changed'):
            self.guided.execute(self.identity, preview['token'])
        preview = self.preview()
        self.backend.guided_run_context = lambda: {'system.md': 'new-system-prompt'}
        with self.assertRaisesRegex(ValueError, 'estimate inputs changed'):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.started, [])

    def test_independent_selection_and_refresh_do_not_reuse_a_retired_quote(self):
        write_json(self.source / 'Map001.json', {'events': []})
        self.backend.phase_files = lambda _native, phase: ['Items.json'] if phase == 'database' else ['Map001.json']
        identity = self.seed_estimate()
        self.native['selected'].append('Map001.json')
        self.assertTrue(self.guided.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
        self.native['selected'].remove('Items.json')
        self.assertFalse(self.guided.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])
        self.native['selected'].append('Items.json')
        write_json(self.folder / 'source-inputs.json', {'version': 1, 'inputs': {}, 'retired_runs': [identity]})
        self.assertFalse(self.guided.runs.quote(self.identity, self.native, 'database', 'batch')[0]['current'])

    def test_completed_phase_and_apply_status_require_that_runs_verified_outputs(self):
        identity = 'completed-database'
        output = [{'name': 'Fixture term'}]
        raw = __import__('json').dumps(output).encode()
        write_json(self.backend.manual.folder(identity) / 'translated/Items.json', output)
        expected = digest((self.backend.manual.folder(identity) / 'translated/Items.json').read_bytes())
        job = {'id': identity, 'mode': 'batch', 'status': 'complete', 'files': ['Items.json'], 'outputs': {'Items.json': expected}, 'log': []}
        self.backend.manual.jobs[identity] = job
        self.guided.runs.remember(self.identity, job, self.guided.runs.inputs(self.identity, self.native, 'database', 'batch'))
        self.native['manual_job'] = identity
        status = self.guided.runs.snapshot(self.identity, self.native, {'changed': [], 'retired': []})
        self.assertTrue(status['phase_runs']['database']['scopeComplete'])
        self.assertNotIn('dialogue', status['phase_runs'])
        self.assertEqual(status['phase_runs']['database']['appliedOutputs'], [])
        write_json(self.folder / 'applied-outputs.json', {'files': {'Items.json': expected}})
        self.assertEqual(self.guided.run_view(identity)['appliedOutputs'], ['Items.json'])
        write_json(self.backend.manual.folder(identity) / 'translated/Items.json', [{'name': 'Changed output'}])
        self.assertFalse(self.guided.runs.snapshot(self.identity, self.native, {'changed': []})['phase_runs']['database']['scopeComplete'])

    def test_comparisons_require_exact_usable_mappings_for_the_selected_event_scope(self):
        self.backend.phase_files = lambda _native, phase: ['Items.json'] if phase == 'database' else ['Map001.json', 'Map002.json']
        self.native['selected'] = ['Items.json', 'Map001.json']
        self.native['engine_options'] = {'IGNORETLTEXT': True}
        self.projects.get(self.identity)['phase'] = 'variables'
        write_json(self.source / 'Map001.json', {'list': [{'code': 111, 'parameters': [12, '$gameVariables.value(1) === "日本語"']}]})
        write_json(self.source / 'Map002.json', {'list': [{'code': 111, 'parameters': [12, '$gameVariables.value(1) === "別の語"']}]})
        for mapping in ({}, {'日本語': '日本語'}, {'別の語': 'Other fixture'}):
            write_json(self.folder / 'log/var_translation_map.json', mapping)
            self.assertEqual(self.guided.runs.comparisons(self.native)['matches'], 0)
            with self.assertRaisesRegex(ValueError, 'audited assignments'):
                self.guided.preview(self.identity, 'start', options={'mode': 'estimate'})
        write_json(self.folder / 'log/var_translation_map.json', {'日本語': 'Fixture English'})
        comparisons = self.guided.runs.comparisons(self.native)
        self.assertEqual(comparisons['files'], ['Map001.json'])
        self.assertEqual(comparisons['status'], 'review_needed')
        self.assertEqual(comparisons['rows'][0]['variables'], ['1'])
        with self.assertRaisesRegex(ValueError, 'Review every matched'):
            self.guided.preview(self.identity, 'start', options={'mode': 'estimate'})
        self.guided.comparisons_review(self.identity, comparisons['fingerprint'], True)
        self.assertEqual(self.guided.runs.comparisons(self.native)['status'], 'ready')
        self.seed_estimate('variables')
        preview = self.guided.preview(self.identity, 'start', options={'mode': 'batch'})
        write_json(self.folder / 'log/var_translation_map.json', {'日本語': 'Changed fixture'})
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.started, [])
        write_json(self.folder / 'log/var_translation_map.json', {'日本語': 7})
        self.assertEqual(self.guided.runs.comparisons(self.native)['status'], 'recovery_needed')
        write_json(self.folder / 'log/var_translation_map.json', {})
        self.assertEqual(self.guided.runs.comparisons(self.native)['status'], 'not_needed')

    def test_apply_review_keeps_a_completed_scope_and_does_not_apply_another_phases_output(self):
        write_json(self.source / 'System.json', {'gameTitle': 'Fixture'})
        self.native['selected'] = ['Items.json', 'System.json']
        self.backend.phase_files = lambda *_: ['Items.json', 'System.json']
        write_json(self.folder / 'translated/Items.json', [{'name': 'Fixture output'}])
        write_json(self.folder / 'translated/System.json', {'gameTitle': 'Other output'})
        self.backend.workflows.preview = lambda *_: {'token': 'apply-preview', 'confirmation': True, 'options': {}}
        self.backend.guided_export_preview = Mock(side_effect=lambda _owner, paths: self.backend.workflows.preview())
        preview = self.guided.preview(self.identity, 'export_selected', files=['Items.json'])
        self.assertEqual(preview['paths'], ['Items.json'])
        self.backend.guided_export_preview.assert_called_once_with('native', ['Items.json'])
        self.assertEqual(read_json(self.source / 'Items.json'), [{'name': '薬'}])
        self.assertEqual(self.native['selected'], ['Items.json', 'System.json'])
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, 'export_selected', files=['Foreign.json'])

    def test_document_selection_migrates_review_positions_and_stays_with_its_project(self):
        self.backend.workflows.documents = lambda _: {"glossary": {}, "quirks": {}, "game": {}}
        position = self.guided.path(self.identity, "position")
        selected = self.guided.path(self.identity, "context-document")
        write_json(position, {"step": "context", "task": "guidance"})
        self.guided.position(self.identity, "context", "guidance")
        self.assertEqual(read_json(selected), {"name": "quirks"})
        self.guided.position(self.identity, "context", "guidance", "game")
        self.guided.position(self.identity, "context", "speakers")
        self.assertEqual(read_json(selected), {"name": "game"})
        with self.assertRaises(ValueError):
            self.guided.position(self.identity, "context", "guidance", "foreign-document")
        selected.unlink()
        write_json(position, {"step": "context", "task": "glossary"})
        self.guided.position(self.identity, "context", "guidance")
        self.assertEqual(read_json(selected), {"name": "glossary"})
        self.backend.workflows.state = lambda _: {"draft": {"documents": {"custom:notes": {"text": "Retained draft", "revision": "previous"}}}}
        self.guided.position(self.identity, "context", "guidance", "custom:notes")
        self.assertEqual(read_json(selected), {"name": "custom:notes"})
        recovered = context_setup.retained_documents(self.source, {}, {"custom:notes": {}})
        self.assertEqual(recovered["custom:notes"]["revision"], digest(b""))
        self.assertEqual(recovered["custom:notes"]["text"], "")
        other = self.projects.open({"source": str(self.root / "other-game"), "engine": "MVMZ"})
        self.assertFalse(self.guided.path(other["id"], "context-document").exists())

    def seed_estimate(self, phase=None, mode='batch'):
        phase = phase or self.projects.get(self.identity)['phase']
        identity = 'estimate-' + str(len(self.guided.runs.records(self.identity)))
        job = {'id': identity, 'mode': 'estimate', 'status': 'complete', 'model': 'fixture-model', 'log': [],
               'files': self.guided.runs.files(self.native, phase), 'estimate': {'requests': 1, 'live_cost': .01, 'batch_cost': .005}, 'outputs': {}}
        self.backend.manual.jobs[identity] = job
        self.native.setdefault('collected', []).append(identity)
        self.guided.runs.remember(self.identity, job, self.guided.runs.inputs(self.identity, self.native, phase, mode))
        return identity

    def preview(self):
        self.seed_estimate()
        return self.guided.preview(self.identity, 'start', options={'mode': 'batch'})

    def speaker_report(self):
        schema = [{'key': key, 'label': key, 'type': 'boolean'} for key in speaker_setup.KEYS[1:5]]
        self.backend.workflows.state = lambda _: {'project': self.native, 'manual_job': self.pending, 'engine_schema': schema}
        self.backend.workflows.skill = lambda *_: 'Investigate this game.'
        def apply(_identity, revision, options, receipt):
            self.assertEqual(revision, self.native['revision'])
            self.native.update(engine_options=options, guided_speakers=receipt, revision=revision + 1)
            return self.native
        self.backend.workflows.apply_speaker_settings = Mock(side_effect=apply)
        self.guided.skill(self.identity, 'setup')
        request = read_json(self.guided.path(self.identity, 'speaker-request'))
        report = {key: request[key] for key in ('version', 'request_id', 'project_id', 'engine')}
        report['rules'] = {field['key']: {'decision': 'skip', 'confidence': 'high', 'reason': 'No supported pattern in the inspected corpus.',
            'evidence': [{'file': 'Items.json', 'sha256': evidence(self.source, ['Items.json'])['Items.json'], 'location': 'item 0, name'}]}
            for field in schema}
        return report

    def test_speaker_findings_require_current_complete_evidence_and_never_start_paid_work(self):
        report = self.speaker_report()
        path = self.source / speaker_setup.REPORT
        self.assertEqual(self.guided.speaker_findings(self.identity)['status'], 'waiting')
        self.guided.skill(self.identity, 'setup')
        self.assertEqual(read_json(self.guided.path(self.identity, 'speaker-request'))['request_id'], report['request_id'])
        with self.assertRaises(ValueError):
            self.guided.speakers(self.identity, scan=True)
        for change, status in (('owner', 'waiting'), ('request', 'waiting'), ('missing', 'invalid'),
                               ('unknown', 'invalid'), ('evidence', 'invalid'), ('stale', 'stale'), ('escape', 'invalid')):
            value = deepcopy(report)
            rule = value['rules']['INLINE401SPEAKERS']
            if change == 'owner': value['project_id'] = 'other-game'
            if change == 'request': value['request_id'] = 'older-task'
            if change == 'missing': value['rules'].pop('FACENAME101')
            if change == 'unknown': value['rules']['CODE122'] = deepcopy(rule)
            if change == 'evidence': rule['evidence'] = []
            if change == 'stale': rule['evidence'][0]['sha256'] = '0' * 64
            if change == 'escape': rule['evidence'][0]['file'] = '../Items.json'
            write_json(path, value)
            with self.subTest(change=change):
                self.assertEqual(self.guided.speaker_findings(self.identity)['status'], status)
                with self.assertRaises(ValueError):
                    self.guided.apply_speakers(self.identity, self.native['revision'], digest(value))
        self.backend.workflows.apply_speaker_settings.assert_not_called()
        report['rules']['INLINE401SPEAKERS'].update(decision='enable', confidence='high')
        report['rules']['FIRSTLINESPEAKERS'].update(decision='enable', confidence='medium')
        write_json(path, report)
        draft = self.guided.preferences(self.native)
        self.guided.options_draft(self.identity, draft)
        with self.assertRaises(ValueError):
            self.guided.apply_speakers(self.identity, 0, digest(report))
        self.guided.options_draft(self.identity, None)
        self.backend.running = lambda: True
        with self.assertRaises(ValueError):
            self.guided.apply_speakers(self.identity, 0, digest(report))
        self.backend.running = lambda: False
        saved = self.guided.apply_speakers(self.identity, 0, digest(report))
        self.assertTrue(saved['values']['engine_options']['INLINE401SPEAKERS'])
        self.assertFalse(saved['values']['engine_options']['FIRSTLINESPEAKERS'])
        self.assertEqual(self.guided.speaker_findings(self.identity)['status'], 'applied')
        self.assertEqual(self.started, [])
        self.assertTrue(self.guided.preview(self.identity, 'start', options={'mode': 'speakers'})['confirmation'])
        # An amended finding can turn off an earlier automatic recommendation;
        # its earlier application must not be misidentified as a manual edit.
        report['rules']['INLINE401SPEAKERS']['decision'] = 'skip'
        write_json(path, report)
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native['engine_options']['INLINE401SPEAKERS'])
        self.assertEqual(self.guided.speaker_findings(self.identity)['overrides'], [])

    def test_local_speaker_scan_keeps_project_ownership_and_reuses_only_current_results(self):
        report = self.speaker_report()
        write_json(self.source / speaker_setup.REPORT, report)
        # A dormant API run must neither block this local task nor be resumed,
        # canceled, or detached by applying rules and scanning new names.
        self.pending = {'id': 'saved-api-run', 'mode': 'batch', 'status': 'interrupted',
                        'provider_job': 'retained-provider-job', 'approval': {'token': 'retained-approval'}}
        self.native['manual_job'] = self.pending['id']
        preserved = deepcopy(self.pending)
        def start(plan):
            self.assertEqual(plan['project_id'], 'native')
            self.assertEqual(plan['options']['files'], ['Items.json'])
            result = {'names': ['リーナ', '\\N[1]'], 'files': 1, 'source_inputs': evidence(self.source, ['Items.json']),
                      'configuration': plan['options']['configuration'], 'reportId': plan['options']['reportId']}
            artifact = self.source / '.dazedtl/guided/speakers.json'
            write_json(artifact, result)
            result['artifact_sha256'] = digest(artifact.read_bytes())
            self.backend.operations.jobs['scan'] = {'id': 'scan', 'action': 'speaker_scan', 'project_id': 'native',
                'created': '2026-01-01', 'status': 'complete', 'result': result, 'message': 'Scanned', 'log': []}
        self.backend.operations.start.side_effect = start
        self.backend.running = lambda: True
        with self.assertRaises(ValueError): self.guided.speakers(self.identity, scan=True)
        self.backend.operations.start.assert_not_called()
        self.backend.running = lambda: False
        value = self.guided.speakers(self.identity, scan=True)
        self.assertTrue(value['current'])
        self.assertEqual(value['names'], ['リーナ', '\\N[1]'])
        self.guided.speakers(self.identity, scan=True)
        self.assertEqual(self.backend.operations.start.call_count, 1)
        self.assertEqual(self.started, [])
        self.assertEqual(self.pending, preserved)
        self.assertEqual(self.native['manual_job'], preserved['id'])
        with self.assertRaises(ValueError): self.preview()
        other = self.projects.open({'source': str(self.root), 'engine': 'MVMZ'})
        with self.assertRaises(ValueError): self.guided.speakers(other['id'], scan=True)
        self.native['engine_options']['FIRSTLINESPEAKERS'] = True
        self.assertFalse(self.guided.speakers(self.identity)['current'])
        self.native['engine_options']['FIRSTLINESPEAKERS'] = False
        artifact = self.source / '.dazedtl/guided/speakers.json'
        artifact.unlink()
        self.assertFalse(self.guided.speakers(self.identity)['current'])
        self.guided.speakers(self.identity, scan=True)
        write_json(self.source / 'NewPluginData.JSON', {'events': []})
        self.assertFalse(self.guided.speakers(self.identity)['current'])
        (self.source / 'NewPluginData.JSON').unlink()
        write_json(self.source / 'Items.json', [{'name': 'changed'}])
        self.assertFalse(self.guided.speakers(self.identity)['current'])

    def test_speaker_application_preserves_overrides_and_recovered_preferences_across_new_findings(self):
        report = self.speaker_report()
        report['rules']['INLINE401SPEAKERS'].update(decision='enable', confidence='high')
        write_json(self.source / speaker_setup.REPORT, report)
        # An edit made after copying setup belongs to the user, including an enable.
        self.native['engine_options']['FACENAME101'] = True
        self.guided.apply_speakers(self.identity, 0, digest(report))
        self.assertTrue(self.native['engine_options']['FACENAME101'])
        self.native['engine_options']['INLINE401SPEAKERS'] = False
        # Repeated observation/application cannot reset a subsequent manual edit.
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native['engine_options']['INLINE401SPEAKERS'])
        self.assertEqual(self.backend.workflows.apply_speaker_settings.call_count, 1)
        report = self.speaker_report()
        report['rules']['INLINE401SPEAKERS'].update(decision='enable', confidence='high')
        write_json(self.source / speaker_setup.REPORT, report)
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native['engine_options']['INLINE401SPEAKERS'])
        self.assertTrue(self.native['engine_options']['FACENAME101'])
        self.guided.apply_speakers(self.identity, 2, digest(report), reset=True)
        self.assertTrue(self.native['engine_options']['INLINE401SPEAKERS'])
        self.assertFalse(self.native['engine_options']['FACENAME101'])
        # Translation can subsequently alter runtime files without erasing the finding.
        write_json(self.source / 'Items.json', [{'name': 'Medicine'}])
        self.assertEqual(self.guided.speaker_findings(self.identity)['status'], 'applied')
        self.assertEqual(self.started, [])

    def test_existing_forms_gain_release_defaults_without_rewriting_user_values(self):
        previous = {'version': '1.00', 'original': '/original', 'untranslated': False, 'only_overflow': False}
        path = self.guided.path(self.identity, 'form')
        write_json(path, previous)
        raw = path.read_bytes()
        value = self.guided.saved_form(self.identity)
        self.assertEqual({key: value[key] for key in previous}, previous)
        self.assertEqual(value['release']['kind'], 'game')
        self.assertEqual(path.read_bytes(), raw)
        value['release']['tools']['forgeHotkey'] = 'F8'
        self.guided.form(self.identity, value)
        self.assertEqual(self.guided.saved_form(self.identity), value)
        write_json(path, {**value, 'release': None})
        invalid = path.read_bytes()
        with self.assertRaises(ValueError):
            self.guided.saved_form(self.identity)
        self.assertEqual(path.read_bytes(), invalid)

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

    def complete_preparation(self):
        return preparation.run({"action": "prepare_game", "project": self.native, "folder": str(self.folder)},
                               lambda _: None, lambda *_: {"files": 1}, lambda *_: {})

    def test_baseline_needs_current_preparation_but_reuses_existing_baselines(self):
        options = {"version": "1.0", "untranslated": True}
        with self.assertRaisesRegex(ValueError, "Complete game preparation first"):
            self.guided.preview(self.identity, "git_setup", options=options)
        self.complete_preparation()
        preview = self.guided.preview(self.identity, "git_setup", options=options)
        # Receipt loss after review also blocks execution.
        (self.folder / "preparation.json").unlink()
        with self.assertRaisesRegex(ValueError, "Complete game preparation first"):
            self.guided.execute(self.identity, preview["token"])
        self.translation.operation.assert_not_called()
        self.git_configured = True
        self.assertTrue(self.guided.preview(self.identity, "git_setup", options=options)["confirmation"])
        self.assertIsNone(self.guided.saved_form(self.identity)["untranslated"])
        with self.assertRaisesRegex(ValueError, "Choose whether"):
            self.guided.preview(self.identity, "git_setup", options={"version": "1.0"})

    def test_new_runtime_file_after_git_preview_cannot_enter_the_baseline_unreviewed(self):
        self.complete_preparation()
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
        self.backend.guided_configure_tools = Mock()
        self.backend.guided_preparation_preview = self.backend.workflows.preview
        data = self.native["data"]
        self.native.update(engine="ACE", data=str(self.source / "ace_json"))
        for action in ("prepare_game", "format_data"):
            with self.assertRaisesRegex(ValueError, "Convert the native Ace data"):
                self.guided.preview(self.identity, action)
        self.native.update(engine="MVMZ", data=data)
        immediate = ('prepare_game', 'format_data', 'format_plugins', 'gameupdate', 'playtest_install', 'inspector_install', 'forge_install', 'playtest_apply')
        for action in immediate:
            with self.subTest(action=action):
                preview = self.guided.preview(self.identity, action)
                self.assertFalse(preview['confirmation'])
                self.assertEqual(self.guided.execute(self.identity, preview['token'])['id'], 'native-operation')
                self.backend.workflows.execute.assert_called_with(preview['token'])
                with self.assertRaises(ValueError):
                    self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, len(immediate))
        self.backend.guided_configure_tools.assert_called_with('playtest_apply-token', self.guided.release_defaults(self.identity)['tools'])
        preview = self.guided.preview(self.identity, 'format_data')
        self.settings_revision += 1
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, len(immediate))
        self.assertTrue(self.guided.preview(self.identity, 'inspector_remove')['confirmation'])
        preview = self.guided.preview(self.identity, 'format_data')
        shutil.rmtree(self.source / '.dazedtl')
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.backend.workflows.execute.call_count, len(immediate))

    def test_an_estimate_cannot_replace_an_interrupted_paid_run_reference(self):
        self.pending = {'id': 'provider-run', 'mode': 'batch', 'status': 'interrupted'}
        for mode in ('batch', 'translate', 'estimate', 'speakers'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.guided.preview(self.identity, 'start', options={'mode': mode})
        self.assertEqual(self.pending['id'], 'provider-run')
        self.assertEqual(self.started, [])

    def test_advanced_runs_require_a_source_and_explicit_variable_ids(self):
        # An empty selection wastes paid work; a blank 122 range silently uses
        # the engine's legacy min/max IDs, which may belong to another game.
        self.projects.get(self.identity)['phase'] = 'advanced'
        for options in ({}, {'CODE122': True}, {'CODE122': True, 'CODE122_VAR_RANGES': ' '}):
            self.native['engine_options'] = options
            for mode in ('batch', 'translate', 'estimate'):
                with self.subTest(options=options, mode=mode), self.assertRaises(ValueError):
                    self.guided.preview(self.identity, 'start', options={'mode': mode})
        self.assertEqual(self.started, [])
        for options in ({'CODE122': True, 'CODE122_VAR_RANGES': '5,10-18,42'}, {'CODE357': True, 'ENABLED_PLUGINS_357': ['TextPicture']}):
            self.native['engine_options'] = options
            current = self.guided.event_text.status(self.identity, self.native)
            with self.assertRaises(ValueError):
                self.guided.event_text_review(self.identity, self.native['revision'], current['binding'], None)
            self.guided.event_text_review(self.identity, self.native['revision'], current['binding'], None, 'Explicit fixture-only coverage review', True)
            preview = self.preview()
            self.guided.execute(self.identity, preview['token'])
        self.assertEqual(self.started, [('native', 'advanced', True)] * 2)

    def event_report(self):
        write_json(self.source / 'Map001.json', {'list': [{'code': 357, 'parameters': ['TextPicture', 'show', '', {'text': '表示'}]}]})
        self.backend.phase_files = lambda _native, phase: ['Items.json'] if phase == 'database' else ['Map001.json']
        self.native['selected'] = ['Items.json', 'Map001.json']
        request = self.guided.event_text.request(self.identity, self.native)
        report = {key: request[key] for key in ('version', 'request_id', 'project_id', 'engine', 'fingerprint')}
        ref = {'file': 'Map001.json', 'sha256': request['dependencies']['Map001.json'], 'location': 'event 1, page 1, command 1'}
        report['sources'] = {key: {'decision': 'skip', 'confidence': 'high', 'coverage': 'none', 'reason': 'Fixture inspected; no safe display use.',
            'targets': '' if key == 'CODE122' else [], 'observations': [], 'exclusions': [], 'evidence': [ref]} for key in event_text.CODES}
        report['sources']['CODE357'].update(decision='enable', coverage='safe', targets=['TextPicture'], observations=['TextPicture show: text is displayed.'])
        write_json(self.source / event_text.REPORT, report)
        return request, report

    def test_event_findings_stage_exact_selectors_and_bind_review_to_sources_and_definitions(self):
        # Prevent recommendations silently enabling settings, selector swaps,
        # stale source approvals, and old reports configuring a new request.
        request, report = self.event_report()
        self.assertEqual(self.guided.event_text.request(self.identity, self.native)['request_id'], request['request_id'])
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings['status'], 'ready')
        self.assertEqual(self.native['engine_options'], {})
        self.assertEqual(findings['recommended']['ENABLED_PLUGINS_357'], ['TextPicture'])
        self.assertEqual(findings['recommended']['ENABLED_PATTERNS_355655'], [])
        self.native['engine_options'] = findings['recommended']
        findings = self.guided.event_text.status(self.identity, self.native)
        self.guided.event_text_review(self.identity, 0, findings['binding'], findings['reportId'])
        review = self.guided.event_text.require(self.identity, self.native)
        self.assertEqual(review['settings']['ENABLED_PLUGINS_357'], ['TextPicture'])
        self.native['engine_options']['AUTONAMEPOPUP101'] = True
        with self.assertRaises(ValueError): self.guided.event_text.require(self.identity, self.native)
        self.native['engine_options'].pop('AUTONAMEPOPUP101')
        self.assertTrue(self.guided.event_text.status(self.identity, self.native)['accepted'])
        self.projects.get(self.identity)['phase'] = 'advanced'
        quote = self.preview()
        self.catalog['fingerprint'] = 'changed-installed-parser'
        self.assertEqual(self.guided.event_text.status(self.identity, self.native)['status'], 'stale')
        with self.assertRaises(ValueError): self.guided.execute(self.identity, quote['token'])
        self.assertEqual(self.started, [])
        self.catalog['fingerprint'] = 'fixture-definitions'
        write_json(self.source / 'Map001.json', {'list': []})
        self.assertEqual(self.guided.event_text.status(self.identity, self.native)['status'], 'stale')
        self.assertEqual(self.native['selected'], ['Items.json', 'Map001.json'])
        plugin = self.source / 'js/plugins/Display.js'
        plugin.parent.mkdir(parents=True)
        plugin.write_text('original display implementation')
        relative = 'js/plugins/Display.js'
        self.translation.engine.source_bindings = lambda _root, paths: {relative: 'original-plugin-blob'} if relative in paths else {}
        self.translation.engine.original_bytes = lambda *_args: b'original display implementation'
        before = self.guided.event_text.context(self.identity, self.native, self.catalog)
        plugin.write_text('modified logic implementation')
        after = self.guided.event_text.context(self.identity, self.native, self.catalog)
        self.assertEqual(before['dependencies'][relative], after['dependencies'][relative])
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_event_findings_reject_foreign_partial_unknown_targets_and_keep_mixed_coverage_off(self):
        _, report = self.event_report()
        for mutate, status in ((lambda r: r.update(project_id='foreign'), 'stale'),
                               (lambda r: r['sources'].pop('CODE356'), 'invalid'),
                               (lambda r: r['sources']['CODE357'].update(targets=['mock-placeholder']), 'invalid'),
                               (lambda r: r['sources']['CODE356'].update(targets=['D_TEXT']), 'invalid')):
            value = deepcopy(report); mutate(value); write_json(self.source / event_text.REPORT, value)
            with self.subTest(status=status):
                self.assertEqual(self.guided.event_text.status(self.identity, self.native)['status'], status)
        report['sources']['CODE357'].update(coverage='mixed', exclusions=['Same handler also consumes an internal key.'])
        write_json(self.source / event_text.REPORT, report)
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings['status'], 'ready')
        self.assertFalse(findings['recommended']['CODE357'])
        self.native['engine_options'] = {**findings['recommended'], 'CODE357': True, 'ENABLED_PLUGINS_357': ['TextPicture']}
        current = self.guided.event_text.status(self.identity, self.native)
        with self.assertRaises(ValueError): self.guided.event_text_review(self.identity, 0, current['binding'], current['reportId'])
        self.guided.event_text_review(self.identity, 0, current['binding'], current['reportId'], 'User-reviewed mixed fixture coverage', True)
        self.assertEqual(self.guided.event_text.require(self.identity, self.native)['manual'], ['CODE357'])
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertEqual(reopened.event_text.status(self.identity, self.native)['manualReason'], 'User-reviewed mixed fixture coverage')
        self.native['engine_options']['ENABLED_PLUGINS_357'] = ['not-installed']
        with self.assertRaises(ValueError): reopened.event_text.require(self.identity, self.native)

    def test_empty_registry_selection_needs_effective_builtin_coverage_and_picker_is_project_owned(self):
        # Empty filters must not authorize meaningless runs; built-in coverage
        # is explicit and cannot be mistaken for per-handler isolation.
        self.event_report()
        self.native['engine_options'] = {'CODE357': True, 'ENABLED_PLUGINS_357': []}
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertTrue(findings['errors'])
        with self.assertRaises(ValueError): self.guided.event_text_review(self.identity, 0, findings['binding'], findings['reportId'], 'Manual', True)
        write_json(self.source / 'Map001.json', {'list': [{'code': 357, 'parameters': ['BuiltinPlugin', 'show', '', {'text': '表示'}]}]})
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings['builtinHits']['CODE357'], ['BuiltinPlugin'])
        self.assertEqual(findings['errors'], [])
        draft = {'key': 'ENABLED_PLUGINS_357', 'selected': ['TextPicture', 'QuestSystem'], 'baseline': [], 'query': 'hidden', 'filter': 'selected'}
        self.guided.event_text_picker(self.identity, draft)
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertEqual(reopened.event_text.status(self.identity, self.native)['picker'], draft)
        self.guided.event_text_picker(self.identity, None)
        self.assertIsNone(reopened.event_text.status(self.identity, self.native)['picker'])
        with self.assertRaises(ValueError): self.guided.event_text_picker(self.identity, {**draft, 'key': 'ENABLED_PLUGINS_356'})

    def test_new_games_do_not_inherit_another_games_advanced_targets(self):
        self.record.pop('backend_id')
        self.backend.workflows.projects.clear()
        self.native['engine_options'] = {'CODE122': True, 'CODE357': True, 'CODE122_VAR_RANGES': '17,26',
            'ENABLED_PLUGINS_357': ['TextPicture'], 'ENABLED_PATTERNS_355655': ['gameVariables.setValue'], 'FIXTEXTWRAP': True}
        self.translation.drafts = lambda _: {'documents': {}}
        self.backend.describe = lambda source: {'source': source, 'engine': 'MVMZ'}
        def open_workflow(_source):
            self.backend.workflows.projects['native'] = self.native
            return {'project': self.native}
        self.backend.workflows.open = open_workflow
        self.guided.open(self.identity)
        options = self.native['engine_options']
        self.assertFalse(options['CODE122'])
        self.assertFalse(options['CODE357'])
        self.assertEqual(options['CODE122_VAR_RANGES'], '')
        self.assertEqual(options['ENABLED_PLUGINS_357'], [])
        self.assertEqual(options['ENABLED_PATTERNS_355655'], [])
        self.assertTrue(options['FIXTEXTWRAP'])
        # Reopening a game retains its own reviewed choices and saved run.
        options.update(CODE122=True, CODE122_VAR_RANGES='5,10-18')
        self.native['manual_job'] = 'existing-run'
        self.guided.open(self.identity)
        self.assertTrue(self.native['engine_options']['CODE122'])
        self.assertEqual(self.native['engine_options']['CODE122_VAR_RANGES'], '5,10-18')
        self.assertEqual(self.native['manual_job'], 'existing-run')

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
