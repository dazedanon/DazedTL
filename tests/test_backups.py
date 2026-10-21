"""Backups saved before checkpoints stay restorable, and never into existing files."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.storage import write_json
from dazedtl.translation import backups
from dazedtl.translation.files import digest

from tests.fixtures import old_backup


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
        (self.work / "translations.json").write_text(
            '{"line":"English"}', encoding="utf-8"
        )

    def test_corruption_and_destination_races_never_publish_a_restore_or_overwrite_user_files(
        self,
    ):
        saved = old_backup.snapshot(self.game)
        target = self.root / "restored"
        target.mkdir()
        (target / "keep.txt").write_text("User work", encoding="utf-8")
        with self.assertRaises(ValueError):
            backups.restore(saved["path"], target)
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "User work")
        racing = self.root / "racing-destination"

        def create_destination(_count, _name):
            racing.mkdir(exist_ok=True)
            (racing / "keep.txt").write_text("Concurrent work", encoding="utf-8")

        with self.assertRaises(ValueError):
            backups.restore(saved["path"], racing, progress=create_destination)
        self.assertEqual(
            (racing / "keep.txt").read_text(encoding="utf-8"), "Concurrent work"
        )
        blob = next((self.store / "objects").glob("*/*"))
        blob.write_bytes(b"x" * blob.stat().st_size)
        with self.assertRaises(ValueError):
            backups.verify(saved["path"])
        with self.assertRaises(ValueError):
            backups.restore(saved["path"], self.root / "failed")
        self.assertFalse((self.root / "failed").exists())
        self.assertEqual(list(self.root.glob(".dazedtl-restore-*")), [])

    def test_legacy_full_copy_restores_and_rejects_traversal_without_conversion(self):
        legacy_root = self.root / "old-profile/backups/project"
        identity = "a" * 32
        directory = legacy_root / identity
        (directory / "files").mkdir(parents=True)
        original = b"source bytes\r\n"
        (directory / "files/source.dat").write_bytes(original)
        value = {
            "version": 1,
            "id": identity,
            "source": str(self.game),
            "kind": "source",
            "created": "2026-09-30T00:00:00+00:00",
            "files": {"source.dat": digest(original)},
        }
        write_json(directory / "manifest.json", value)
        before = (directory / "manifest.json").read_bytes()
        restored = self.root / "legacy-restore"
        backups.restore(backups.lookup(self.game, legacy_root, identity), restored)
        self.assertEqual((restored / "source.dat").read_bytes(), original)
        self.assertEqual((directory / "manifest.json").read_bytes(), before)
        self.assertEqual(
            backups.catalog(self.game, legacy_root)["snapshots"][0]["version"], 1
        )
        for name in ("../outside", "/outside", "C:/outside", "folder\\outside"):
            with self.subTest(name=name):
                write_json(
                    directory / "manifest.json",
                    {**value, "files": {name: digest(original)}},
                )
                with self.assertRaises(ValueError):
                    backups.restore(directory, self.root / "bad-manifest")
        self.assertFalse((self.root / "bad-manifest").exists())

    def test_restores_refuse_linked_payloads(self):
        saved = old_backup.snapshot(self.game)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        blob = next((self.store / "objects").glob("*/*"))
        content = blob.read_bytes()
        blob.unlink()
        external = elsewhere / "payload"
        external.write_bytes(content)
        blob.symlink_to(external)
        with self.assertRaises(ValueError):
            backups.restore(saved["path"], self.root / "linked-restore")
        with self.assertRaises(ValueError):
            backups.verify(saved["path"], full=False)
        blob.unlink()
        blob.write_bytes(content)
        shard = blob.parent
        moved = elsewhere / shard.name
        shard.rename(moved)
        shard.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            backups.verify(saved["path"], full=False)
