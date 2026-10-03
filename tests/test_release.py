"""A stopped or stale release must not overwrite a previous archive or game."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
from contextlib import closing
import sqlite3
import json

from dazedtl.storage import write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.operations import execute, lifecycle, lifecycle_path
from dazedtl.translation.release import (available, destination, output_hash, publish, git_identity,
                                        inventory, write_archive, applied_assets, runtime_asset, packing_state, packing_inputs)


class ReleaseTests(unittest.TestCase):
    def test_actual_clean_archive_preserves_player_docs_and_excludes_private_local_material(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / 'generated-game'
            root.mkdir()
            included = {'Game.exe', 'README.md', 'PlayerManual.pdf', 'docs/controls.md', 'LICENSE.txt', 'data/Items.json'}
            private = {'.api_key', 'api_keys.json', 'provider_key.txt', '.env.local', 'debug.log', '.venv/bin/python',
                       'www/save/file.rpgsave', 'nested/logs/debug.txt', 'data/Items.json.bak', 'cache/scan.json',
                       'AGENTS.md', '.dazedtl/backups/current.json', 'gameupdate/previous_patch_sha.txt'}
            for name in included | private | {'gameupdate/patch-config.txt'}:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic fixture value')
            scope = inventory(root)
            self.assertEqual(set(scope['files']), included)
            output = Path(folder) / 'clean.zip'
            write_archive(root, output, scope, lambda _: None)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {'generated-game/' + name for name in included})
            # Stopping after the first entry never publishes a partial replacement.
            previous = output.read_bytes()
            staged = Path(folder) / 'partial.zip'
            log = Mock()
            log.stopped.side_effect = [False, True]
            with self.assertRaises(InterruptedError):
                write_archive(root, staged, scope, log)
            self.assertEqual(log.call_count, 1)
            self.assertEqual(output.read_bytes(), previous)
            # A reviewed public stamp retains its config and generates only the matching state.
            stamped = inventory(root, 'a' * 40)
            write_archive(root, output, stamped, lambda _: None)
            with zipfile.ZipFile(output) as archive:
                self.assertIn('generated-game/gameupdate/patch-config.txt', archive.namelist())
                self.assertEqual(archive.read('generated-game/gameupdate/previous_patch_sha.txt'), ('a' * 40 + '\n').encode())
            (root / 'data/Items.json').write_text('changed after inspection')
            with self.assertRaises(ValueError):
                write_archive(root, output, scope, lambda _: None)

    def test_patch_asset_receipts_and_explicit_fonts_bind_exact_safe_runtime_paths(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / 'www/img/pictures/Menu.png'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'generated image bytes')
            font = root / 'www/fonts/Translation.woff2'
            font.parent.mkdir(parents=True)
            font.write_bytes(b'generated font bytes')
            index = root / '.dazedtl/image_manager/guided/inventory.sqlite3'
            index.parent.mkdir(parents=True)
            row = {'runtime': image.relative_to(root).as_posix(), 'applied': {'runtimeHash': digest(image.read_bytes())}}
            with closing(sqlite3.connect(index)) as db:
                db.execute('CREATE TABLE assets (data TEXT)')
                db.execute('INSERT INTO assets VALUES (?)', (json.dumps(row),))
                db.commit()
            self.assertEqual(applied_assets(root), ['www/img/pictures/Menu.png'])
            self.assertEqual(runtime_asset(root, 'www/fonts/Translation.woff2'), 'www/fonts/Translation.woff2')
            for name in ('.dazedtl/image_manager/guided/inventory.sqlite3', 'www/fonts/../fonts/Translation.woff2'):
                with self.assertRaises(ValueError):
                    runtime_asset(root, name)
            image.write_bytes(b'later image edit')
            with self.assertRaisesRegex(ValueError, 'applied image changed'):
                applied_assets(root)

    def test_ace_release_requires_complete_receipt_matching_current_json_and_native_bytes(self):
        with TemporaryDirectory() as folder:
            root, work = Path(folder) / 'game', Path(folder) / 'work'
            write_json(root / 'ace_json/Items.json', [{'name': 'generated translation'}])
            data = root / 'Data/Items.rvdata2'
            data.parent.mkdir()
            data.write_bytes(b'\x04\x08generated native data')
            native = {'source': str(root), 'data': str(root / 'ace_json'), 'engine': 'ACE'}
            self.assertFalse(packing_state(native, work)['current'])
            receipt = {'source': str(root), 'inputs': packing_inputs(native), 'outputs': evidence(root, ['Data/Items.rvdata2'])}
            write_json(work / 'ace-packing.json', receipt)
            self.assertTrue(packing_state(native, work)['current'])
            write_json(root / 'ace_json/Items.json', [{'name': 'later fitting edit'}])
            self.assertFalse(packing_state(native, work)['current'])
            receipt['inputs'] = packing_inputs(native)
            write_json(work / 'ace-packing.json', receipt)
            data.write_bytes(b'\x04\x08later native edit')
            self.assertFalse(packing_state(native, work)['current'])
            write_json(root / 'ace_json/Actors.json', [{'name': 'new JSON export'}])
            receipt['inputs'] = packing_inputs(native)
            write_json(work / 'ace-packing.json', receipt)
            self.assertFalse(packing_state(native, work)['current'])

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
            with patch('dazedtl.translation.release.os.replace', side_effect=OSError('generated replacement failure')):
                with self.assertRaises(OSError):
                    publish(staged, output, output_hash(output))
            self.assertEqual(output.read_bytes(), b'new user archive')
            self.assertTrue(staged.is_file())
            result = publish(staged, output, output_hash(output))
            self.assertTrue(available(result))
            self.assertFalse(staged.exists())
            output.write_bytes(b'replaced externally')
            self.assertFalse(available(result))
            output.unlink()
            self.assertFalse(available(result))
