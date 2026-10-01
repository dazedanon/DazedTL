"""Regression coverage for retaining recoverable state during storage failures."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dazedtl.storage import WorkspaceError, read_versioned_json, write_bytes, write_json


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "project.json"

    def test_upgrade_keeps_exact_backup_and_does_not_repeat(self):
        original = b'{"version":1,"name":"example","items":["saved"]}\n'
        self.path.write_bytes(original)
        calls = []

        def upgrade(value):
            calls.append(value["version"])
            value["title"] = value.pop("name")
            return value

        def validate(value):
            if not isinstance(value.get("title"), str):
                raise ValueError("Missing title")

        expected = {"version": 2, "title": "example", "items": ["saved"]}
        self.assertEqual(read_versioned_json(self.path, {"version": 2}, {1: upgrade}, validate), expected)
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        backups = list((self.root / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(read_versioned_json(self.path, {"version": 2}, {1: upgrade}, validate), expected)
        self.assertEqual(calls, [1])
        self.assertEqual(list((self.root / "backups").iterdir()), backups)

    def test_unreadable_or_unsupported_state_is_never_replaced(self):
        for original in (b'{broken', b'[]', b'{"version":99,"saved":"keep"}'):
            with self.subTest(original=original):
                self.path.write_bytes(original)
                with self.assertRaises(WorkspaceError):
                    read_versioned_json(self.path, {"version": 2}, {}, lambda value: None)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertFalse((self.root / "backups").exists())

    def test_failed_migration_or_backup_preserves_source(self):
        original = b'{"version":1,"saved":"keep"}'

        def invalid(value):
            value.pop("saved")
            raise ValueError("Migration failed")

        self.path.write_bytes(original)
        with self.assertRaises(WorkspaceError) as error:
            read_versioned_json(self.path, {"version": 2}, {1: invalid}, lambda value: None)
        self.assertEqual(error.exception.code, "workspace_upgrade")
        self.assertEqual(self.path.read_bytes(), original)
        with patch("dazedtl.storage.write_bytes", side_effect=OSError("No space")):
            with self.assertRaises(WorkspaceError) as error:
                read_versioned_json(self.path, {"version": 2}, {1: lambda value: value}, lambda value: None)
        self.assertEqual(error.exception.code, "workspace_backup")
        self.assertEqual(self.path.read_bytes(), original)

    def test_concurrent_source_edit_aborts_upgrade(self):
        original = b'{"version":1,"saved":"first"}'
        newer = b'{"version":1,"saved":"edited elsewhere"}'
        self.path.write_bytes(original)

        def backup_then_edit(path, content):
            write_bytes(path, content)
            self.path.write_bytes(newer)

        with patch("dazedtl.storage.write_bytes", side_effect=backup_then_edit):
            with self.assertRaises(WorkspaceError):
                read_versioned_json(self.path, {"version": 2}, {1: lambda value: value}, lambda value: None)
        self.assertEqual(self.path.read_bytes(), newer)
        self.assertEqual(next((self.root / "backups").iterdir()).read_bytes(), original)

    def test_interrupted_atomic_replace_keeps_saved_file_and_cleans_temporary(self):
        original = b'{"saved":"keep"}'
        self.path.write_bytes(original)
        with patch("dazedtl.storage.os.replace", side_effect=OSError("Replace failed")):
            with self.assertRaises(OSError):
                write_json(self.path, {"saved": "new"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])
