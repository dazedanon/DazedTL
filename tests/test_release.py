"""A stopped or stale release must not overwrite a previous archive or game."""

import json
import os
import sqlite3
import subprocess
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility import original_files
from dazedtl.compatibility.translation import TranslationEngine, gameupdate_refusal
from dazedtl.storage import write_json
from dazedtl.translation.assistant_release import AssistantRelease, PackageRefusal
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.game_update import ABSENT, GameUpdate
from dazedtl.translation.git_status_cache import RepositoryStatusCache
from dazedtl.translation.operations import (
    execute,
    lifecycle,
    lifecycle_path,
    outdate_patch,
)
from dazedtl.translation.originals import game_names
from dazedtl.translation.release import (
    applied_assets,
    archive_stem,
    available,
    build_game,
    current,
    destination,
    exclusion,
    game_folder,
    game_scope,
    git_identity,
    inventory,
    output_hash,
    packing_inputs,
    packing_state,
    publish,
    runtime_asset,
    write_archive,
)
from dazedtl.translation.service import lifecycle_view


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

            # Guided bound data.json's working copy to the original version
            # it came from; a game update then moved `original`. Releases
            # failed as if a new request plan were needed.
            def git(*arguments):
                return subprocess.run(
                    ["git", "-C", str(game), *arguments],
                    capture_output=True,
                    encoding="utf-8",
                    check=True,
                ).stdout.strip()

            git("init", "-q", "-b", "original")
            identity = ("-c", "user.name=Test", "-c", "user.email=test@example.invalid")
            write_json(game / "data.json", {"line": "1.0"})
            git("add", "data.json")
            git(*identity, "commit", "-qm", "1.0")
            bound = git("rev-parse", "original:data.json")
            write_json(game / "data.json", {"line": "1.1"})
            git(*identity, "commit", "-qam", "1.1")
            write_json(game / "data.json", {"line": "translated"})
            real = TranslationEngine.__new__(TranslationEngine)
            real.original_trees = RepositoryStatusCache(stable=True)
            inputs = {
                "version": 1,
                "inputs": {
                    "data.json": {
                        "relative": "data.json",
                        "identity": {"original": bound},
                    }
                },
            }
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
                verify_bindings=real.verify_bindings,
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

            def package(_source, _options, _manifest, target, original_names=()):
                path = target / "patch.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.write(game / "data.json", "data.json")
                return {"path": str(path), "commit": "after", "paths": ["data.json"]}

            engine.package = package
            result = run()
            self.assertTrue(available(result))
            # Edits made outside DazedTL go first, then the release's own
            # checkpoint takes the manifest's files into the patch.
            engine.outside_edits.assert_called_once()
            self.assertEqual(engine.checkpoint.call_args.args[2], ["data.json"])
            state = lifecycle(workspace, "owner")
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
            # A checkpoint restore writes the bytes the archive holds again.
            data = game / "data.json"
            data.write_bytes(data.read_bytes())
            os.utime(data, ns=(1, 1))
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

    def test_assistant_led_release_builds_what_its_review_read(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game, workspace = root / "Game", root / "profile"
            for name in ("Game.exe", "Game_Data/resources.assets"):
                (game / name).parent.mkdir(parents=True, exist_ok=True)
                (game / name).write_text("original", encoding="utf-8")
            original_files.record(game, original_files.FOUND)
            # The translation's files ship beside the game's; notes added to
            # the folder while working stay out, whatever the engine.
            name = "BepInEx/plugins/GameTL.dll"
            plugin = game / name
            plugin.parent.mkdir(parents=True)
            plugin.write_text("plugin", encoding="utf-8")
            (game / "notes.txt").write_text("my notes", encoding="utf-8")
            # An image applied into a folder the assistant decoded, which
            # Guided's image folders don't hold, keeps the ZIPs current.
            image = "decoded/title.png"
            (game / "decoded").mkdir()
            (game / image).write_bytes(b"translated title")
            index = game / ".dazedtl/image_manager/guided/inventory.sqlite3"
            index.parent.mkdir(parents=True)
            applied = {"runtimeHash": digest((game / image).read_bytes())}
            row = {"runtime": image, "applied": applied}
            with closing(sqlite3.connect(index)) as db:
                db.execute("CREATE TABLE assets (data TEXT)")
                db.execute("INSERT INTO assets VALUES (?)", (json.dumps(row),))
                db.commit()
            write_json(
                lifecycle_path(workspace, "owner"),
                {"version": 1, "runtime_manifest": "patch-files.json"},
            )
            write_json(game / "patch-files.json", {"files": {}})
            status = {
                "repo_root": str(game.resolve()),
                "configured": True,
                "original_version": "1.0",
                "translation_version": "1.0",
                "current_branch": "main",
                "translation_branch": "main",
                "original_commit": "original",
                "translation_commit": "after",
            }

            def package(_source, _options, _manifest, target, original_names=()):
                path = Path(target) / "after.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.write(plugin, name)
                    archive.write(game / image, image)
                return {"path": str(path), "commit": "after", "paths": [name, image]}

            engine = SimpleNamespace(
                source=root / "engine",
                detect=lambda _root: "Unity",
                git_status=lambda *_: dict(status),
                patch_files=lambda *_args, **_kwargs: {
                    "files": [name, image],
                    "omitted": [],
                    "updater_stamp": None,
                },
                runtime_paths=lambda manifest: list(manifest["files"]),
                outside_edits=Mock(),
                checkpoint=Mock(return_value="after"),
                package=package,
            )
            ready = Mock()
            releases = AssistantRelease(
                SimpleNamespace(
                    workspace=workspace,
                    engine=engine,
                    project=lambda _id: (
                        {"method": "len"},
                        SimpleNamespace(root=game, read=lambda: {"options": {}}),
                    ),
                    game_update=SimpleNamespace(require_ready=Mock()),
                    idle=Mock(),
                    package_ready=ready,
                )
            )
            self.assertEqual(releases.form("owner")["directory"], str(root))

            def build(kind, preview):
                job = {"id": "job-" + kind, "project_id": "owner"}
                plan = {
                    "source": str(game),
                    "options": {},
                    "action": "release" if kind == "game" else "package",
                    "arguments": {"plan": preview["plan"], "sha256": preview["sha256"]},
                }
                # The runtime manifest's QA is recorded.
                with patch(
                    "dazedtl.translation.delivery.verify",
                    return_value={"files": ["patch-files.json"]},
                ):
                    return execute(engine, workspace, job, plan, lambda: False)

            output = str(root / "Game-game.zip")
            preview = releases.preview("owner", "game", output)
            self.assertEqual(
                preview["paths"],
                [name, "Game.exe", "Game_Data/resources.assets", image],
            )
            self.assertIn(
                "notes.txt", [row["path"] for row in preview["package"]["exclusions"]]
            )
            # A build refuses a plan its review didn't save, and contents that
            # changed after the review.
            with self.assertRaisesRegex(ValueError, "plan changed"):
                build("game", {**preview, "sha256": "0" * 64})
            plugin.write_text("plugin, edited", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contents"):
                build("game", preview)
            build("game", releases.preview("owner", "game", output))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "Game-game/" + name,
                        "Game-game/Game.exe",
                        "Game-game/Game_Data/resources.assets",
                        "Game-game/" + image,
                    ],
                )
            # The patch is the assistant's package, with its checks, saved
            # where the user chose; a file that appeared there after the
            # review is not replaced.
            patch_output = str(root / "Game-patch.zip")
            # A patch that isn't ready says why in the user's terms; the
            # helper keeps the assistant's.
            ready.side_effect = PackageRefusal(
                "Run organize --complete first.", "Your assistant finishes first."
            )
            with self.assertRaisesRegex(ValueError, "^Your assistant finishes first.$"):
                releases.preview("owner", "patch", patch_output)
            ready.side_effect = None
            preview = releases.preview("owner", "patch", patch_output)
            self.assertEqual(ready.call_count, 2)
            self.assertEqual(preview["paths"], [name, image])
            Path(patch_output).write_bytes(b"someone else's file")
            with self.assertRaisesRegex(ValueError, "destination changed"):
                build("patch", preview)
            Path(patch_output).unlink()
            build("patch", releases.preview("owner", "patch", patch_output))
            with zipfile.ZipFile(patch_output) as archive:
                self.assertEqual(archive.namelist(), [name, image])
            state = lifecycle(workspace, "owner")
            rows = releases.view("owner", game, state)["artifacts"]
            self.assertEqual(
                [(row["kind"], row["path"], row["current"]) for row in rows],
                [("game", output, True), ("patch", patch_output, True)],
            )
            # An undo, a game update or a new write outdates the patch,
            # which stays listed.
            outdate_patch(state)
            rows = releases.view("owner", game, state)["artifacts"]
            self.assertEqual([row["current"] for row in rows], [True, False])
            plugin.write_text("translated again", encoding="utf-8")
            rows = releases.view("owner", game, state)["artifacts"]
            self.assertEqual([row["current"] for row in rows], [False, False])
            # The renderer gets the patch's identity, not its file stamps.
            self.assertNotIn("inputs", lifecycle_view(state)["delivery"])
            self.assertNotIn("release", lifecycle_view(state))

    def test_a_clean_game_zip_reads_outdated_once_a_checkpoint_adds_a_file(self):
        # Its inputs are only the translation's files, so a game update that
        # adds a map changes none of them; the checkpoint it made does.
        with TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / "Game"
            (game / "data").mkdir(parents=True)
            write_json(game / "data/Map001.json", {"line": "translated"})
            (game / "Game.exe").write_text("game", encoding="utf-8")

            def git(*arguments):
                subprocess.run(["git", "-C", str(game), *arguments], check=True)

            def checkpoint():
                git("add", "-A")
                identity = ("-c", "user.name=T", "-c", "user.email=t@example.invalid")
                git(*identity, "commit", "-qm", "checkpoint")

            (game / "img").mkdir()
            (game / "img/title.png").write_bytes(b"title")
            git("init", "-q", "-b", "main")
            checkpoint()
            # An edit made outside DazedTL ships as it is, and the
            # checkpoint that later takes it in changes nothing.
            (game / "Game.exe").write_text("edited", encoding="utf-8")
            output = root / "Game-game.zip"
            release = build_game(
                game,
                output,
                game_scope(game, None),
                output_hash(output),
                lambda *_: None,
                engine="MVMZ",
                inputs=lambda: ["data/Map001.json"],
            )
            checkpoint()
            self.assertTrue(current(release, game))
            write_json(game / "data/Map002.json", {"line": "new map"})
            checkpoint()
            self.assertFalse(current(release, game))
            # Undoing it puts the game back as the ZIP holds it.
            (game / "data/Map002.json").unlink()
            checkpoint()
            self.assertTrue(current(release, game))
            # DazedTL's own records never ship, so committing them changes
            # nothing; a record saved before checkpoints were kept reads by
            # its inputs.
            write_json(game / ".dazedtl/glossary.json", {})
            checkpoint()
            self.assertTrue(current(release, game))
            (game / "img/title.png").write_bytes(b"updated title")
            checkpoint()
            self.assertFalse(current(release, game))
            self.assertTrue(current({**release, "checkpoint": None}, game))

    def test_gameupdate_installs_only_where_it_updates_a_patch(self):
        # GameUpdate takes a WOLF game's Data.wolf out once it unpacks the
        # loose Data folder, a patch's repacked one too.
        self.assertIsNotNone(gameupdate_refusal("WOLF", ["Data.wolf", "Game.exe"]))
        self.assertIsNone(gameupdate_refusal("WOLF", ["Data/Picture.wolf"]))
        self.assertIsNone(gameupdate_refusal("Unity", ["Data.wolf"]))
        engine = TranslationEngine.__new__(TranslationEngine)
        with TemporaryDirectory() as folder:
            game = Path(folder)
            for detected, refusal in (
                ("MVMZ", "rpgmaker_prepare"),
                ("Investigation pending", "recognizes"),
            ):
                engine.detect = lambda _root, name=detected: name
                with self.assertRaisesRegex(ValueError, refusal):
                    engine.install_gameupdate(game)
            engine.detect = lambda _root: "Unity"
            written = []
            with patch("dazedtl.compatibility.game_write.write_game") as write_game:
                write_game.return_value.__enter__.return_value.wrote = lambda *names: (
                    written.extend(names)
                )
                engine.install_gameupdate(game)
            self.assertTrue((game / "gameupdate/patch.sh").is_file())
            self.assertFalse((game / "UberWolfCli.exe").exists())
            # The write names what it installed, so its checkpoint takes the
            # files into the patch.
            self.assertLessEqual(
                {"GameUpdate.bat", "gameupdate/patch.sh", "README.md"}, set(written)
            )
