"""A stopped or stale release must not overwrite a previous archive or game."""

import json
import sqlite3
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility import original_files
from dazedtl.storage import write_json
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.game_update import ABSENT, GameUpdate
from dazedtl.translation.operations import execute, lifecycle, lifecycle_path
from dazedtl.translation.originals import game_names
from dazedtl.translation.release import (
    applied_assets,
    archive_stem,
    available,
    current,
    destination,
    exclusion,
    game_folder,
    git_identity,
    inventory,
    output_hash,
    packing_inputs,
    packing_state,
    publish,
    runtime_asset,
    write_archive,
)


class ReleaseTests(unittest.TestCase):
    def test_actual_clean_archive_preserves_player_docs_and_excludes_private_local_material(
        self,
    ):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "generated-game"
            root.mkdir()
            included = {
                "Game.exe",
                "README.md",
                "PlayerManual.pdf",
                "docs/controls.md",
                "LICENSE.txt",
                # MV's layout, as Windows has one folder for data and Ace's Data.
                "www/data/Items.json",
            }
            private = {
                ".api_key",
                "api_keys.json",
                "provider_key.txt",
                ".env.local",
                "debug.log",
                ".venv/bin/python",
                "www/save/file.rpgsave",
                "nested/logs/debug.txt",
                "www/data/Items.json.bak",
                "cache/scan.json",
                "AGENTS.md",
                ".dazedtl/backups/current.json",
                "Data/backups/Actors.rvdata2",
                "gameupdate/previous_patch_sha.txt",
            }
            for name in included | private | {"gameupdate/patch-config.txt"}:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic fixture value", encoding="utf-8")
            # A temporary-file write leaves a game file owner-only; players
            # still get ordinary permissions.
            (root / "www/data/Items.json").chmod(0o600)
            scope = inventory(root)
            self.assertEqual(set(scope["files"]), included)
            # Players get the archive's name as the game's folder, not the
            # source folder's: an Ace game won't start on English Windows from
            # a Japanese one, and extracting in Explorer adds a folder of the
            # archive's name.
            output = Path(folder) / "Orc's Revenge-game.zip"
            top = game_folder(output, "ACE")
            self.assertEqual(top, "Orc's Revenge-game")
            self.assertEqual(
                game_folder(Path("逆襲のオーク.zip"), "MVMZ"), "逆襲のオーク"
            )
            for name, engine in (("逆襲のオーク.zip", "ACE"), ("game..zip", "MVMZ")):
                with self.assertRaises(ValueError):
                    game_folder(Path(folder) / name, engine)
            # The default name is the game folder's wherever the check takes
            # it, else its ASCII form, else a plain one.
            for name, engine, stem in (
                ("逆襲のオーク", "MVMZ", "逆襲のオーク"),
                ("逆襲のオーク", "ACE", "translated"),
                ("Orcの逆襲 Ver.2 ～Revenge～", "ACE", "Orc Ver.2 ~Revenge~"),
                ("CON", "MVMZ", "translated"),
            ):
                self.assertEqual(archive_stem(name, engine), stem)
            write_archive(root, output, scope, lambda _: None, folder=top)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {top + "/" + name for name in included},
                )
                items = archive.getinfo(top + "/www/data/Items.json")
                self.assertEqual(items.external_attr >> 16, 0o100644)
            # Stopping after the first entry never publishes a partial replacement.
            previous = output.read_bytes()
            staged = Path(folder) / "partial.zip"
            log = Mock()
            log.stopped.side_effect = [False, True]
            with self.assertRaises(InterruptedError):
                write_archive(root, staged, scope, log, folder=top)
            self.assertEqual(log.call_count, 1)
            self.assertEqual(output.read_bytes(), previous)
            # A reviewed public stamp retains its config and generates only the matching state.
            stamped = inventory(root, "a" * 40)
            write_archive(root, output, stamped, lambda _: None, folder=top)
            with zipfile.ZipFile(output) as archive:
                self.assertIn(top + "/gameupdate/patch-config.txt", archive.namelist())
                stamp = archive.getinfo(top + "/gameupdate/previous_patch_sha.txt")
                self.assertEqual(archive.read(stamp), ("a" * 40 + "\n").encode())
                self.assertEqual(stamp.external_attr >> 16, 0o100644)
            (root / "www/data/Items.json").write_text(
                "changed after inspection", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                write_archive(root, output, scope, lambda _: None, folder=top)
            # Only the game, as its recorded original files have it, and the
            # translation's files ship; files added while working stay out,
            # and a folder of only such files is one entry. A spelling's case
            # doesn't matter.
            original_files.record(root, original_files.FOUND)
            for name in (
                "ci.html",
                "Dictionaries/en-US-9-0.bdic",
                "www/data/notes.txt",
                "www/data/Map001.json",
            ):
                (root / name).parent.mkdir(exist_ok=True)
                (root / name).write_text("added while translating", encoding="utf-8")
            known = game_names(None, None, root, {"version": 1})
            scope = inventory(root, None, known | {"www/data/map001.json"})
            self.assertLessEqual(
                {"ci.html", "Dictionaries/", "www/data/notes.txt"},
                {row["path"] for row in scope["exclusions"]},
            )
            write_archive(root, output, scope, lambda _: None, folder=top)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {top + "/" + name for name in included | {"www/data/Map001.json"}},
                )
            # Windows can't extract these names, such as a pager's stray
            # "\x1bq" file, so they never ship; they can't be made on Windows.
            for name in ("\x1bq", "notes?.txt", "aux.json", "data/old./Map001.json"):
                self.assertIsNotNone(exclusion(name))
            self.assertIsNone(exclusion("img/pictures/メニュー画面_ロゴ.png"))

    def test_patch_asset_receipts_and_explicit_fonts_bind_exact_safe_runtime_paths(
        self,
    ):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "www/img/pictures/Menu.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"generated image bytes")
            font = root / "www/fonts/Translation.woff2"
            font.parent.mkdir(parents=True)
            font.write_bytes(b"generated font bytes")
            index = root / ".dazedtl/image_manager/guided/inventory.sqlite3"
            index.parent.mkdir(parents=True)
            row = {
                "runtime": image.relative_to(root).as_posix(),
                "applied": {"runtimeHash": digest(image.read_bytes())},
            }
            with closing(sqlite3.connect(index)) as db:
                db.execute("CREATE TABLE assets (data TEXT)")
                db.execute("INSERT INTO assets VALUES (?)", (json.dumps(row),))
                db.commit()
            self.assertEqual(applied_assets(root), ["www/img/pictures/Menu.png"])
            self.assertEqual(
                runtime_asset(root, "www/fonts/Translation.woff2"),
                "www/fonts/Translation.woff2",
            )
            # A VX Ace game's images are in Graphics, which refused its
            # applied images and so the whole patch.
            title = root / "Graphics/Titles1/title.png"
            title.parent.mkdir(parents=True)
            title.write_bytes(b"generated title")
            self.assertEqual(
                runtime_asset(root, "Graphics/Titles1/title.png"),
                "Graphics/Titles1/title.png",
            )
            for name in (
                ".dazedtl/image_manager/guided/inventory.sqlite3",
                "www/fonts/../fonts/Translation.woff2",
            ):
                with self.assertRaises(ValueError):
                    runtime_asset(root, name)
            image.write_bytes(b"later image edit")
            with self.assertRaisesRegex(ValueError, "applied image changed"):
                applied_assets(root)

    def test_ace_release_requires_complete_receipt_matching_current_json_and_native_bytes(
        self,
    ):
        with TemporaryDirectory() as folder:
            root, work = Path(folder) / "game", Path(folder) / "work"
            write_json(
                root / "ace_json/Items.json", [{"name": "generated translation"}]
            )
            data = root / "Data/Items.rvdata2"
            data.parent.mkdir()
            data.write_bytes(b"\x04\x08generated native data")
            script = root / "ace_json/scripts/1_Main.rb"
            script.parent.mkdir()
            script.write_text("generated script", encoding="utf-8")
            (root / "Data/Scripts.rvdata2").write_bytes(b"\x04\x08generated scripts")
            native = {
                "source": str(root),
                "data": str(root / "ace_json"),
                "engine": "ACE",
            }
            self.assertFalse(packing_state(native, work)["current"])
            receipt = {
                "source": str(root),
                "inputs": packing_inputs(native),
                "outputs": evidence(
                    root, ["Data/Items.rvdata2", "Data/Scripts.rvdata2"]
                ),
            }
            # A receipt from before packing wrote Game.ini's title would ship
            # the original caption, and one from before packing wrote text
            # variables as Ruby strings a game that freezes at them.
            for version, current in ((None, False), (2, False), (3, True)):
                receipt["version"] = version
                write_json(work / "ace-packing.json", receipt)
                self.assertEqual(packing_state(native, work)["current"], current)
            # A script translated after packing needs packing again too.
            script.write_text("later script translation", encoding="utf-8")
            self.assertFalse(packing_state(native, work)["current"])
            receipt["inputs"] = packing_inputs(native)
            write_json(work / "ace-packing.json", receipt)
            self.assertTrue(packing_state(native, work)["current"])
            write_json(root / "ace_json/Items.json", [{"name": "later fitting edit"}])
            self.assertFalse(packing_state(native, work)["current"])
            receipt["inputs"] = packing_inputs(native)
            write_json(work / "ace-packing.json", receipt)
            data.write_bytes(b"\x04\x08later native edit")
            self.assertFalse(packing_state(native, work)["current"])
            write_json(root / "ace_json/Actors.json", [{"name": "new JSON export"}])
            receipt["inputs"] = packing_inputs(native)
            write_json(work / "ace-packing.json", receipt)
            self.assertFalse(packing_state(native, work)["current"])

    def test_patch_plan_binds_owner_git_sources_and_runtime_before_checkpointing(
        self,
    ):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game, workspace = root / "game", root / "profile"
            write_json(game / "data.json", {"line": "translated"})
            manifest_path = ".dazedtl/guided/runtime-manifest.json"
            write_json(game / manifest_path, {"files": {"data.json": {}}})
            write_json(lifecycle_path(workspace, "owner"), {"version": 1})
            inputs = {"version": 1, "inputs": {}}
            write_json(workspace / "inputs.json", inputs)
            status = {
                "repo_root": str(game),
                "configured": True,
                "original_version": "1.0",
                "translation_version": "1.0",
                "current_branch": "main",
                "translation_branch": "main",
                "original_commit": "original",
                "translation_commit": "before",
            }
            engine = SimpleNamespace(
                source=root / "engine",
                git_status=lambda *_: dict(status),
                verify_bindings=Mock(),
                runtime_paths=lambda manifest: list(manifest["files"]),
                outside_edits=Mock(),
                checkpoint=Mock(
                    side_effect=lambda *_: (
                        status.update(translation_commit="after") or "after"
                    )
                ),
            )
            payload = {
                "version": 1,
                "project_id": "owner",
                "source": str(game),
                "manifest": manifest_path,
                "evidence": evidence(game, [manifest_path, "data.json"]),
                "git": git_identity(status),
                "source_inputs": "inputs.json",
                "source_inputs_sha256": digest(inputs),
                "output": str(root / "release.zip"),
                "output_hash": None,
            }
            write_json(workspace / "release-plan.json", payload)
            plan = {
                "source": str(game),
                "options": {},
                "action": "release_patch",
                "arguments": {"plan": "release-plan.json", "sha256": digest(payload)},
            }

            def run():
                return execute(
                    engine,
                    workspace,
                    {"id": "job", "project_id": "owner"},
                    plan,
                    lambda: False,
                )

            for change in ("owner", "git", "inputs", "runtime"):
                with self.subTest(change=change):
                    changed = (
                        {**payload, "project_id": "other"}
                        if change == "owner"
                        else payload
                    )
                    write_json(workspace / "release-plan.json", changed)
                    plan["arguments"]["sha256"] = digest(changed)
                    status["original_commit"] = (
                        "changed" if change == "git" else "original"
                    )
                    write_json(
                        workspace / "inputs.json",
                        {**inputs, "retired_runs": ["old"]}
                        if change == "inputs"
                        else inputs,
                    )
                    write_json(
                        game / "data.json",
                        {"line": "changed" if change == "runtime" else "translated"},
                    )
                    with self.assertRaises(ValueError):
                        run()
                    engine.checkpoint.assert_not_called()
            write_json(game / "data.json", {"line": "translated"})

            def package(
                _source, _options, _manifest, target, updater=True, original_names=()
            ):
                # The translation version keeps GameUpdate's config; the
                # local patch leaves it out.
                self.assertFalse(updater)
                path = target / "patch.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.write(game / "data.json", "data.json")
                return {"path": str(path), "commit": "after"}

            engine.package = package
            result = run()
            self.assertTrue(available(result))
            # Edits made outside DazedTL go first, then the release's own
            # checkpoint takes the manifest's files into the patch.
            engine.outside_edits.assert_called_once()
            self.assertEqual(engine.checkpoint.call_args.args[2], ["data.json"])
            state = lifecycle(workspace, "owner")
            self.assertNotIn("guided_review", state)
            self.assertEqual(state["guided_release"]["path"], str(root / "release.zip"))
            self.assertEqual(read_json(game / "data.json"), {"line": "translated"})
            # The saved ZIP stays current until its runtime files change or
            # another image is applied; one saved before inputs were recorded
            # cannot be compared.
            release = state["guided_release"]
            self.assertTrue(current(release, game))
            legacy = {key: value for key, value in release.items() if key != "inputs"}
            self.assertIsNone(current(legacy, game))
            image = game / "img/pictures/Menu.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"applied image")
            index = game / ".dazedtl/image_manager/guided/inventory.sqlite3"
            index.parent.mkdir(parents=True)
            row = {
                "runtime": "img/pictures/Menu.png",
                "applied": {"runtimeHash": digest(image.read_bytes())},
            }
            with closing(sqlite3.connect(index)) as db:
                db.execute("CREATE TABLE assets (data TEXT)")
                db.execute("INSERT INTO assets VALUES (?)", (json.dumps(row),))
                db.commit()
            self.assertFalse(current(release, game))
            index.unlink()
            self.assertTrue(current(release, game))
            write_json(game / "data.json", {"line": "edited later"})
            self.assertFalse(current(release, game))

    def test_releases_wait_only_for_a_gameupdate_config_that_cannot_be_written(self):
        # Writing the config first means a repository origin just named is
        # used; a game whose GameUpdate is off, or whose file was edited by
        # hand, still builds.
        calls, current = [], {}
        engine = SimpleNamespace(
            game_update=lambda _root, _defaults, action=None, _repo=None: (
                calls.append(action) or current
            )
        )
        busy = {"value": False}
        update = GameUpdate(
            SimpleNamespace(
                project=lambda _: (None, SimpleNamespace(root=Path("game"))),
                jobs=SimpleNamespace(running=lambda *_: busy["value"]),
                settings=SimpleNamespace(
                    game_update=dict,
                    adapter=SimpleNamespace(running=lambda: False),
                ),
                engine=engine,
            )
        )
        for state in ("needs_repo", "pending"):
            current.update(ABSENT, state=state)
            with self.assertRaises(ValueError):
                update.require_ready("project")
        for state in ("absent", "unconfigured", "edited", "ready"):
            current.update(ABSENT, state=state)
            update.require_ready("project")
        self.assertEqual(calls.count("sync"), 6)
        # A running operation owns the game, so nothing writes beside it.
        busy["value"] = True
        update.sync("project")
        self.assertEqual(calls.count("sync"), 6)
        with self.assertRaises(ValueError):
            update.act("project", "save", "other")

    def test_destinations_and_atomic_publication_preserve_the_previous_release(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game, workspace, engine = (
                root / name for name in ("game", "profile", "engine")
            )
            for protected in (game, workspace, engine):
                protected.mkdir()
                with self.assertRaises(ValueError):
                    destination(game, workspace, engine, str(protected / "release.zip"))
            output = destination(game, workspace, engine, str(root / "release.zip"))
            output.write_bytes(b"previous archive")
            expected = output_hash(output)
            staged = root / "staged.zip"
            with zipfile.ZipFile(staged, "w") as archive:
                archive.writestr("data/Items.json", "[]")
            with self.assertRaises(InterruptedError):
                publish(staged, output, expected, stopped=lambda: True)
            self.assertEqual(output.read_bytes(), b"previous archive")
            output.write_bytes(b"new user archive")
            with self.assertRaises(ValueError):
                publish(staged, output, expected)
            self.assertEqual(output.read_bytes(), b"new user archive")
            with (
                patch(
                    "dazedtl.translation.release.os.replace",
                    side_effect=OSError("generated replacement failure"),
                ),
                self.assertRaises(OSError),
            ):
                publish(staged, output, output_hash(output))
            self.assertEqual(output.read_bytes(), b"new user archive")
            self.assertTrue(staged.is_file())
            result = publish(staged, output, output_hash(output))
            self.assertTrue(available(result))
            self.assertFalse(staged.exists())
            output.write_bytes(b"replaced externally")
            self.assertFalse(available(result))
            output.unlink()
            self.assertFalse(available(result))
