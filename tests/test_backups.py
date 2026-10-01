"""Small real files protect deduplicated recovery and the no-overwrite boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import nullcontext
import os
import shutil
import unittest
from unittest.mock import patch

from dazedtl.storage import write_json, WorkspaceLock
from dazedtl.translation import backups
from dazedtl.translation.files import digest


class BackupTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.game = self.root / "game"
        self.work = self.game / ".dazedtl"
        self.work.mkdir(parents=True)
        self.store = backups.store_path(self.game)
        self.asset = self.game / "runtime.bin"
        self.asset.write_bytes(b"unchanged native asset\0" * 100)
        (self.work / "translations.json").write_text('{"line":"English"}')

    def objects(self):
        return {path.name: path.read_bytes() for path in (self.store / "objects").glob("*/*")}

    def test_saved_reference_does_not_claim_missing_payloads_or_deleted_store_are_available(self):
        saved = backups.snapshot(self.game, self.store, source_game=True)
        before = dict(saved)
        self.assertTrue(backups.record_status(self.game, saved, kind="source")["available"])
        next((self.store / "objects").glob("*/*")).unlink()
        self.assertFalse(backups.record_status(self.game, saved, kind="source")["available"])
        backups.snapshot(self.game, self.store, source_game=True)
        self.assertTrue(backups.record_status(self.game, saved, kind="source")["available"])
        shutil.rmtree(self.work)
        missing = backups.record_status(self.game, saved, kind="source")
        self.assertFalse(missing["available"])
        self.assertTrue(missing["issue"])
        self.assertFalse(self.work.exists())
        self.assertEqual(saved, before)

    def test_checkpoint_reuses_content_and_remains_independently_restorable_after_move(self):
        original = backups.snapshot(self.game, self.store, source_game=True)
        (self.work / "copied-asset.bin").write_bytes(self.asset.read_bytes())
        (self.work / "empty").mkdir()
        script = self.work / "tool.sh"
        script.write_bytes(b"#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        (self.work / "backups/earlier-manual-copy").mkdir()
        (self.work / "backups/earlier-manual-copy/keep.txt").write_text("Earlier user backup")
        first = backups.snapshot(self.work, self.store)
        objects = self.objects()
        again = backups.snapshot(self.work, self.store)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(again["bytes_added"], 0)
        self.assertTrue(again["reused_snapshot"])
        self.assertEqual(self.objects(), objects)
        self.assertEqual(first["bytes_reused"], self.asset.stat().st_size)
        self.assertFalse(any(name.startswith("backups/") for name in backups.manifest(first["path"])["files"]))
        self.assertEqual(len(list((self.store / "snapshots").iterdir())), 2)
        # An in-place edit must never modify the older backup or its shared asset.
        (self.work / "translations.json").write_text('{"line":"Corrected English"}')
        changed = backups.snapshot(self.work, self.store)
        self.assertEqual(changed["bytes_added"], (self.work / "translations.json").stat().st_size)
        moved = self.root / "moved-game"
        self.game.rename(moved)
        available = backups.record_status(moved, first, kind="workspace")
        self.assertTrue(available["available"])
        self.assertTrue(Path(available["path"]).is_relative_to(moved))
        for identity, expected in ((first["id"], '{"line":"English"}'), (changed["id"], '{"line":"Corrected English"}')):
            with self.subTest(identity=identity):
                saved = backups.lookup(moved, self.root / "absent-profile", identity)
                target = self.root / identity
                backups.restore(saved, target)
                self.assertEqual((target / "translations.json").read_text(), expected)
                self.assertTrue((target / "empty").is_dir())
                self.assertEqual((target / "copied-asset.bin").read_bytes(), (moved / "runtime.bin").read_bytes())
                if os.name != "nt":
                    self.assertEqual((target / "tool.sh").stat().st_mode & 0o777, 0o755)
                (target / "copied-asset.bin").write_bytes(b"independent restored edits")
                backups.verify(saved)
                with self.assertRaises(ValueError):
                    backups.restore(saved, moved / "unsafe-restore")
        self.assertTrue((moved / ".dazedtl/backups/earlier-manual-copy/keep.txt").is_file())
        self.assertEqual(len(backups.catalog(moved, self.root / "absent-profile")["snapshots"]), 3)
        backups.verify(backups.lookup(moved, self.root / "absent-profile", original["id"]))

    def test_cancelled_changed_or_failed_capture_leaves_previous_snapshots_and_no_new_payloads(self):
        saved = backups.snapshot(self.work, self.store)
        previous = self.objects()
        for failure in ("cancel", "source_changed", "inventory_changed", "write_failed"):
            with self.subTest(failure=failure):
                current = self.work / "translations.json"
                current.write_text(failure)
                stop = [False]
                def progressed(_count, _name):
                    if failure == "cancel": stop[0] = True
                    if failure == "source_changed": current.write_text("Another writer's update")
                    if failure == "inventory_changed": (self.work / "new-file.txt").write_text("Added while backing up")
                writer = patch("dazedtl.translation.backups.write_json", side_effect=OSError("No disk space"))
                with writer if failure == "write_failed" else nullcontext():
                    with self.assertRaises((InterruptedError, ValueError, OSError)):
                        backups.snapshot(self.work, self.store, stopped=lambda: stop[0], progress=progressed)
                self.assertEqual(self.objects(), previous)
                self.assertEqual(list((self.store / "temporary").iterdir()), [])
                self.assertEqual(len(list((self.store / "snapshots").iterdir())), 1)
                backups.verify(saved["path"])
                (self.work / "new-file.txt").unlink(missing_ok=True)
        lock = WorkspaceLock(self.store)
        try:
            with self.assertRaises(ValueError):
                backups.snapshot(self.work, self.store)
        finally:
            lock.close()

    def test_corruption_and_destination_races_never_publish_a_restore_or_overwrite_user_files(self):
        saved = backups.snapshot(self.work, self.store)
        target = self.root / "restored"
        target.mkdir()
        (target / "keep.txt").write_text("User work")
        with self.assertRaises(ValueError): backups.restore(saved["path"], target)
        self.assertEqual((target / "keep.txt").read_text(), "User work")
        racing = self.root / "racing-destination"
        def create_destination(_count, _name):
            racing.mkdir(exist_ok=True)
            (racing / "keep.txt").write_text("Concurrent work")
        with self.assertRaises(ValueError): backups.restore(saved["path"], racing, progress=create_destination)
        self.assertEqual((racing / "keep.txt").read_text(), "Concurrent work")
        blob = next((self.store / "objects").glob("*/*"))
        blob.write_bytes(b"x" * blob.stat().st_size)
        with self.assertRaises(ValueError): backups.verify(saved["path"])
        with self.assertRaises(ValueError): backups.restore(saved["path"], self.root / "failed")
        self.assertFalse((self.root / "failed").exists())
        self.assertEqual(list(self.root.glob(".dazedtl-restore-*")), [])

    def test_legacy_full_copy_restores_and_rejects_traversal_without_conversion(self):
        legacy_root = self.root / "old-profile/backups/project"
        identity = "a" * 32
        directory = legacy_root / identity
        (directory / "files").mkdir(parents=True)
        original = b"source bytes\r\n"
        (directory / "files/source.dat").write_bytes(original)
        value = {"version": 1, "id": identity, "source": str(self.game), "kind": "source",
                 "created": "2026-09-30T00:00:00+00:00", "files": {"source.dat": digest(original)}}
        write_json(directory / "manifest.json", value)
        before = (directory / "manifest.json").read_bytes()
        restored = self.root / "legacy-restore"
        backups.restore(backups.lookup(self.game, legacy_root, identity), restored)
        self.assertEqual((restored / "source.dat").read_bytes(), original)
        self.assertEqual((directory / "manifest.json").read_bytes(), before)
        self.assertEqual(backups.catalog(self.game, legacy_root)["snapshots"][0]["version"], 1)
        for name in ("../outside", "/outside", "C:/outside", "folder\\outside"):
            with self.subTest(name=name):
                write_json(directory / "manifest.json", {**value, "files": {name: digest(original)}})
                with self.assertRaises(ValueError): backups.restore(directory, self.root / "bad-manifest")
        self.assertFalse((self.root / "bad-manifest").exists())

    def test_links_and_unmanaged_nested_stores_are_rejected(self):
        with self.assertRaises(ValueError): backups.snapshot(self.game, self.game / "other-backups", source_game=True)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.store.parent.mkdir(parents=True)
        self.store.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError): backups.snapshot(self.work, self.store)
        self.store.unlink()
        link = self.work / "linked"
        link.symlink_to(self.asset)
        with self.assertRaises(ValueError): backups.snapshot(self.work, self.store)
        link.unlink()
        saved = backups.snapshot(self.work, self.store)
        blob = next((self.store / "objects").glob("*/*"))
        content = blob.read_bytes()
        blob.unlink()
        external = elsewhere / "payload"
        external.write_bytes(content)
        blob.symlink_to(external)
        with self.assertRaises(ValueError): backups.restore(saved["path"], self.root / "linked-restore")
