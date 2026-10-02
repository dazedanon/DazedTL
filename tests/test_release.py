"""A stopped or stale release must not overwrite a previous archive or game."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import zipfile

from dazedtl.storage import write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.operations import execute, lifecycle, lifecycle_path
from dazedtl.translation.release import available, destination, output_hash, publish, git_identity


class ReleaseTests(unittest.TestCase):
    def test_patch_plan_binds_owner_git_sources_and_runtime_before_checkpointing(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game, workspace = root / 'game', root / 'profile'
            write_json(game / 'data.json', {'line': 'translated'})
            manifest_path = '.dazedtl/guided/runtime-manifest.json'
            write_json(game / manifest_path, {'files': {'data.json': {}}})
            saved = snapshot(game, store_path(game), source_game=True)
            write_json(lifecycle_path(workspace, 'owner'), {'version': 1, 'source_backup': saved})
            inputs = {'version': 1, 'inputs': {}}
            write_json(workspace / 'inputs.json', inputs)
            status = {'repo_root': str(game), 'configured': True, 'original_version': '1.0', 'translation_version': '1.0',
                      'current_branch': 'main', 'translation_branch': 'main', 'original_commit': 'original', 'translation_commit': 'before'}
            engine = SimpleNamespace(source=root / 'engine', git_status=lambda *_: dict(status), verify_bindings=Mock(),
                                     git_scope=Mock(return_value={}), commit=Mock(side_effect=lambda *_: status.update(translation_commit='after') or 'after'))
            payload = {'version': 1, 'project_id': 'owner', 'source': str(game), 'manifest': manifest_path,
                       'evidence': evidence(game, [manifest_path, 'data.json']), 'git': git_identity(status),
                       'source_inputs': 'inputs.json', 'source_inputs_sha256': digest(inputs),
                       'output': str(root / 'release.zip'), 'output_hash': None}
            write_json(workspace / 'release-plan.json', payload)
            plan = {'source': str(game), 'options': {}, 'action': 'release_patch',
                    'arguments': {'plan': 'release-plan.json', 'sha256': digest(payload)}}
            def run():
                return execute(engine, workspace, {'id': 'job', 'project_id': 'owner'}, plan, lambda: False)
            for change in ('owner', 'git', 'inputs', 'runtime'):
                with self.subTest(change=change):
                    changed = {**payload, 'project_id': 'other'} if change == 'owner' else payload
                    write_json(workspace / 'release-plan.json', changed)
                    plan['arguments']['sha256'] = digest(changed)
                    status['original_commit'] = 'changed' if change == 'git' else 'original'
                    write_json(workspace / 'inputs.json', {**inputs, 'retired_runs': ['old']} if change == 'inputs' else inputs)
                    write_json(game / 'data.json', {'line': 'changed' if change == 'runtime' else 'translated'})
                    with self.assertRaises(ValueError):
                        run()
                    engine.commit.assert_not_called()
                    engine.git_scope.assert_not_called()
            write_json(game / 'data.json', {'line': 'translated'})
            def package(_source, _options, _manifest, target):
                path = target / 'patch.zip'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.write(game / 'data.json', 'data.json')
                return {'path': str(path), 'commit': 'after'}
            engine.package = package
            result = run()
            self.assertTrue(available(result))
            self.assertEqual(engine.git_scope.call_count, 2)
            engine.commit.assert_called_once()
            state = lifecycle(workspace, 'owner')
            self.assertNotIn('guided_review', state)
            self.assertEqual(state['guided_release']['path'], str(root / 'release.zip'))
            self.assertEqual(read_json(game / 'data.json'), {'line': 'translated'})

    def test_destinations_and_atomic_publication_preserve_the_previous_release(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game, workspace, engine = (root / name for name in ('game', 'profile', 'engine'))
            for protected in (game, workspace, engine):
                protected.mkdir()
                with self.assertRaises(ValueError):
                    destination(game, workspace, engine, str(protected / 'release.zip'))
            output = destination(game, workspace, engine, str(root / 'release.zip'))
            output.write_bytes(b'previous archive')
            expected = output_hash(output)
            staged = root / 'staged.zip'
            with zipfile.ZipFile(staged, 'w') as archive:
                archive.writestr('data/Items.json', '[]')
            with self.assertRaises(InterruptedError):
                publish(staged, output, expected, stopped=lambda: True)
            self.assertEqual(output.read_bytes(), b'previous archive')
            output.write_bytes(b'new user archive')
            with self.assertRaises(ValueError):
                publish(staged, output, expected)
            self.assertEqual(output.read_bytes(), b'new user archive')
            result = publish(staged, output, output_hash(output))
            self.assertTrue(available(result))
            self.assertFalse(staged.exists())
            output.write_bytes(b'replaced externally')
            self.assertFalse(available(result))
            output.unlink()
            self.assertFalse(available(result))
