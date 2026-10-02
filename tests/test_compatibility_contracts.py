"""Focused contracts at the maintained-engine boundary, without importing a sibling checkout."""

from dataclasses import dataclass
import json
from pathlib import Path
from types import ModuleType
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock

from dazedtl.compatibility.translation import TranslationEngine, ProviderFailure, provider_errors
from dazedtl.translation.compilation import compile_requests
from dazedtl.compatibility.manual import manual_jobs
from dazedtl.compatibility.guided import rewrap_review, run_ace, runtime_files, apply_selected, phased_workflows
from dazedtl.compatibility.speaker_scan import collect as collect_speakers
from dazedtl.storage import write_json
from dazedtl.translation.files import digest


class CompatibilityContracts(unittest.TestCase):
    def test_preparation_preview_keeps_native_guards_and_public_configuration(self):
        from dazedtl.compatibility.dazedmtl import ExistingBackend
        backend = ExistingBackend.__new__(ExistingBackend)
        plans = {}
        def preview(owner, action, options):
            self.assertEqual((owner, action, options), ("fixture", "prepare", {}))
            plans["token"] = {"action": action, "label": "Prepare game files", "guard": {"data": "source-hash"},
                              "options": {"public_settings": {"gameUpdateUsername": "fixture"}}}
            return {"token": "token", "options": plans["token"]["options"]}
        backend.workflows = SimpleNamespace(previews=plans, preview=preview)
        result = backend.guided_preparation_preview("fixture", "prepare_game", {})
        self.assertEqual(plans["token"]["action"], "prepare_game")
        self.assertEqual(plans["token"]["guard"], {"data": "source-hash"})
        self.assertEqual(result["options"]["public_settings"]["gameUpdateUsername"], "fixture")

    def test_speaker_scan_rejects_partial_parser_results_without_finalizing_names(self):
        engine = SimpleNamespace(SPEAKER_COLLECTED=[], MISMATCH=[], resetSpeakerState=Mock(), setSpeakerParseMode=Mock(),
                                 finalizeSpeakerParse=Mock(side_effect=AssertionError('Must not translate names')))
        engine.openFiles = lambda name: ({}, [0, 0], ValueError('broken JSON') if name == 'bad.json' else None)
        def handle(name, _estimate):
            engine.openFiles(name)
            engine.SPEAKER_COLLECTED.extend(['リーナ', 'リーナ'])
        engine.handleMVMZ = handle
        self.assertEqual(collect_speakers(engine, ['good.json'], lambda _: None), ['リーナ'])
        with self.assertRaisesRegex(ValueError, 'bad.json'):
            collect_speakers(engine, ['good.json', 'bad.json'], lambda _: None)
        engine.setSpeakerParseMode.assert_called_with(False)
        engine.finalizeSpeakerParse.assert_not_called()

    def test_apply_uses_reviewed_selection_even_when_other_outputs_are_prepared(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {'options': {'files': ['Items.json']}, 'folder': str(root/'work'),
                    'project': {'source': str(root/'game'), 'data': str(root/'game/data'), 'engine': 'MVMZ'},
                    'guard': {'files': {'Items.json': 'input', 'System.json': 'input'},
                              'translated': {'Items.json': 'output', 'System.json': 'output'}}}
            actions = ModuleType('desktop.backend.workflow_actions')
            actions.validate_plan = Mock()
            actions.regular = lambda _root, path: path
            scanner = ModuleType('util.project_scanner')
            scanner.export_to_game = Mock(return_value=(1, []))
            with patch.dict(sys.modules, {actions.__name__: actions, scanner.__name__: scanner}):
                self.assertEqual(apply_selected(plan, lambda _: None)['files'], 1)
                self.assertEqual(scanner.export_to_game.call_args.kwargs['filenames'], ['Items.json'])
                actions.validate_plan.assert_called_once_with(plan)
                plan['options']['files'] = ['Missing.json']
                with self.assertRaises(ValueError):
                    apply_selected(plan, lambda _: None)
                self.assertEqual(scanner.export_to_game.call_count, 1)

    def test_guided_patch_proposal_keeps_previously_tracked_runtime_assets(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root/'game'
            write_json(game/'data/Items.json', [None])
            (game/'img').mkdir()
            (game/'img/title.png').write_bytes(b'generated asset fixture')
            (game/'README.md').write_text('Repository metadata')
            preparation = ModuleType('util.project_preparation')
            preparation.rpgmaker_layout = lambda _: {'engine': 'MVMZ', 'data_path': game/'data', 'plugins_js': None}
            preparation.RPG_GAMEUPDATE_COPY_SKIP_NAMES = set()
            paths = ModuleType('util.paths'); paths.PROJECT_ROOT = root/'engine'
            scope = ModuleType('util.len_patch_scope'); scope.patch_manifest = lambda value: value
            git = ModuleType('util.version_update.git_workflow')
            git._run_git = lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='img/title.png\0README.md\0')
            with patch.dict(sys.modules, {module.__name__: module for module in (preparation, paths, scope, git)}):
                self.assertEqual(runtime_files(game), ['data/Items.json', 'img/title.png'])

    def test_ace_reported_error_is_failure_even_with_zero_exit_and_tools_use_profile_cache(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / 'engine/util/ace/offline/RV2JSON.exe'
            tool.parent.mkdir(parents=True)
            tool.write_bytes(b'fixture executable, never launched')
            folder = root / 'profile/workflows/project'
            folder.mkdir(parents=True)
            paths = ModuleType('util.paths')
            paths.PROJECT_ROOT = root / 'engine'
            actions = ModuleType('desktop.backend.workflow_actions')
            actions.validate_plan = lambda _plan: None
            child = Mock(stdout=['\x1b[?25lERROR: Could not load scripts\x1b[?25h\n'])
            child.wait.return_value = 0
            process = Mock()
            process.__enter__ = Mock(return_value=child)
            process.__exit__ = Mock(return_value=False)
            with patch.dict(sys.modules, {'util.paths': paths, 'desktop.backend.workflow_actions': actions}), \
                 patch('dazedtl.compatibility.guided.ace_available', return_value=True), \
                 patch('dazedtl.compatibility.guided.shutil.which', return_value='wine'), \
                 patch('dazedtl.compatibility.guided.subprocess.Popen', return_value=process) as launch:
                with self.assertRaisesRegex(ValueError, 'Could not load scripts'):
                    run_ace({'action': 'ace_extract', 'folder': str(folder), 'project': {'source': str(root/'game')}}, lambda _line: None)
                child.stdout = ['error: XDG_RUNTIME_DIR is invalid or not set\n', 'Dumping of 0 scripts done\n']
                self.assertEqual(run_ace({'action': 'ace_extract', 'folder': str(folder), 'project': {'source': str(root/'game')}}, lambda _line: None), {'completed': 'ace_extract'})
            self.assertEqual((root/'profile/tools/ace/RV2JSON.exe').read_bytes(), tool.read_bytes())
            self.assertEqual(launch.call_args.kwargs['stdin'], subprocess.DEVNULL)
            if sys.platform != 'win32':
                self.assertEqual(launch.call_args.kwargs['env']['WINEPREFIX'], str(root/'profile/tools/ace/wine'))

    def test_phased_worker_launcher_preserves_pipe_controls_and_isolates_the_child(self):
        # The native runner failed before launch when PIPE was absent from its substituted namespace.
        with TemporaryDirectory() as temporary:
            source = Path(temporary)
            module = source / 'desktop/backend/manual.py'
            module.parent.mkdir(parents=True)
            module.write_text('''import subprocess, sys
from pathlib import Path
class ManualJobs:
    def __init__(self, *args, **kwargs): pass
    def start(self, source, engine, files, *args, **kwargs): return files
    def launch(self):
        return subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('manual_worker.py')), 'run'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={})
''')
            with patch('subprocess.Popen') as launch:
                controller = manual_jobs(source, source / 'profile', None, False)
                controller.launch()
                args, kwargs = launch.call_args
                self.assertEqual(Path(args[0][2]).name, 'manual_worker.py')
                self.assertNotEqual(Path(args[0][2]).parent, module.parent)
                self.assertEqual((kwargs['stdin'], kwargs['stdout']), (subprocess.PIPE, subprocess.PIPE))
                self.assertEqual(kwargs['env']['DAZEDTL_ENGINE_SOURCE'], str(source))
                self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
                # The preserved phase may find more files than the user checked.
                # Filter only its new run, preserving its native phase setup.
                with controller.selected_workflow('owner', ['Items.json']):
                    self.assertEqual(controller.start('work', 'engine', ['Items.json', 'System.json'], workflow={'id': 'owner'}), ['Items.json'])
                    with self.assertRaises(ValueError):
                        controller.start('work', 'engine', ['Items.json'], workflow={'id': 'another-owner'})
                self.assertEqual(controller.start('work', 'engine', ['Items.json', 'System.json']), ['Items.json', 'System.json'])
            workflow = ModuleType('desktop.backend.workflow')
            collected = []
            class Workflows:
                def __init__(self, workspace, *_): self.root = workspace
                def folder(self, identity): return self.root/identity
                def _collect(self, project): collected.append(project['manual_job'])
            workflow.Workflows = Workflows
            with patch.dict(sys.modules, {workflow.__name__: workflow}):
                phases = phased_workflows(source/'phases', None, None, controller)
                write_json(phases.folder('owner')/'source-inputs.json', {'version': 1, 'inputs': {}, 'retired_runs': ['older-source-run']})
                phases._collect({'id': 'owner', 'manual_job': 'older-source-run'})
                self.assertEqual(collected, [])
                phases._collect({'id': 'owner', 'manual_job': 'current-source-run'})
                self.assertEqual(collected, ['current-source-run'])

    def test_rewrap_apply_requires_the_same_completed_scan_and_settings(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {'options': {'width': 50}, 'guard': {'data': 'reviewed'}}
            path = root / 'scan/plan.json'
            write_json(path, plan)
            job = {'id': 'scan', 'project_id': 'game', 'action': 'rewrap_preview', 'status': 'complete',
                   'created': 'today', 'result': {'changes_found': 1}, 'plan_hash': digest(path.read_bytes())}
            backend = SimpleNamespace(operations=SimpleNamespace(root=root, jobs={'scan': job}),
                                      workflows=SimpleNamespace(previews={'token': plan}))
            self.assertEqual(rewrap_review(backend, 'game', 'token'), {'changes_found': 1})
            for current in ({**plan, 'options': {'width': 60}}, {**plan, 'guard': {'data': 'changed'}}):
                backend.workflows.previews['token'] = current
                with self.assertRaises(ValueError):
                    rewrap_review(backend, 'game', 'token')
            with self.assertRaises(ValueError):
                rewrap_review(backend, 'other-game', 'token')

    def test_line_metadata_reaches_both_provider_payloads_without_changing_the_legacy_batch_contract(self):
        package, context_module, skill_module, provider_module = (ModuleType(name) for name in
            ("util", "util.len_translation", "util.skills", "util.translation"))
        note = "Check whether the visitor or guard left."
        source_context = "門に二人がいる。"
        def contexts(_project, batches):
            self.assertEqual(set(batches[0]), {"id", "sources", "speakers", "source_context", "instruction_key"})
            self.assertEqual(batches[0]["speakers"], {"line": None})
            return [{"context": {"system": "Translate into English", "glossary": "Approved names and voice",
                     "sfx_reference": "SFX", "user": json.dumps(batch["sources"], ensure_ascii=False),
                     "preceding_japanese_source_context": batch["source_context"], "request_instructions": "Field guidance"}}
                    for batch in batches]
        context_module.request_contexts = contexts
        skill_module.ctx = lambda *_args, **_kwargs: "Field guidance"
        provider_module.buildClaudeRequest = lambda **kwargs: {"captured": kwargs}
        provider_module.buildOpenAIRequest = lambda **kwargs: {"captured": kwargs}
        modules = {module.__name__: module for module in (package, context_module, skill_module, provider_module)}
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.project = lambda *_args: None
        engine.compiler_fingerprint = lambda: "compiler"
        plan = {"batches": [{"id": "scene", "sources": {"line": "行った。"}, "kinds": {"line": "dialogue"},
                            "speakers": {"line": None}, "qa_notes": {"line": note}, "source_context": source_context,
                            "scene_context": "Two people at the gate", "instruction_key": "dialogue"}]}
        with patch.dict(sys.modules, modules):
            rows, _compiler = compile_requests(engine, "unused", {}, plan, "English")
            row = rows[0]
            self.assertEqual(row["context"]["line_kinds"], {"line": "dialogue"})
            self.assertEqual(row["context"]["qa_notes"], {"line": note})
            for protocol, mode in (("openai", "live"), ("anthropic", "batch")):
                with self.subTest(protocol=protocol):
                    payload = engine.payload(row, {"protocol": protocol, "provider": protocol,
                                                  "mode": mode, "model": "fixture", "endpoint": "https://provider.invalid/v1"})
                    sent = payload["captured"]
                    self.assertEqual(sent["user"], row["context"]["user"])
                    self.assertIn(note, sent["user"])
                    self.assertEqual(sent["history"], source_context)
                    self.assertIn("Approved names and voice", sent["vocab_text"])
                    self.assertIn("Two people at the gate", sent["request_instructions"])

    def test_native_update_completion_property_survives_public_serialization(self):
        @dataclass
        class Update:
            translation_commit: str | None
            pending_conflicts: tuple = ()
            @property
            def complete(self):
                return self.translation_commit is not None and not self.pending_conflicts
        package = ModuleType("util")
        module = ModuleType("util.version_update")
        package.version_update = module
        engine = TranslationEngine.__new__(TranslationEngine)
        for result in (Update("saved"), Update(None, ("data/Items.json",))):
            with self.subTest(result=result):
                module.continue_with_official = lambda _source: result
                with patch.dict(sys.modules, {"util": package, "util.version_update": module}):
                    value = engine.version(Path("unused"), "continue", {})
                self.assertEqual(value["complete"], result.complete)
                self.assertEqual(value["pending_conflicts"], result.pending_conflicts)

    def test_provider_errors_do_not_reveal_credentials_or_request_bodies(self):
        @provider_errors
        def request():
            raise ValueError("Invalid Authorization header: Bearer fixture-private-key; private request body")
        with self.assertRaises(ProviderFailure) as raised:
            request()
        self.assertNotIn("fixture-private-key", str(raised.exception))
        self.assertNotIn("private request body", str(raised.exception))
        self.assertIsNone(raised.exception.status_code)
