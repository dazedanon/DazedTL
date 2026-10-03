"""Text batches must retain exact approved bytes through failure and restart."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import read_json
from dazedtl.translation import publication as p


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "game"
        self.folder = Path(temporary.name) / "profile"
        self.folder.mkdir()
        self.before = {"data/A.json": b'{"text":"before A"}', "data/B.json": b'{"text":"before B"}'}
        self.after = {name: raw.replace(b"before", b"after") for name, raw in self.before.items()}
        for name, raw in self.before.items():
            write_bytes(self.root / name, raw)

    def test_empty_canceled_stale_and_repeated_reviews_never_publish(self):
        with self.assertRaises(ValueError):
            p.freeze(self.folder, self.root, {}, "export_selected")
        canceled = p.freeze(self.folder, self.root, self.after, "export_selected")
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.before}, self.before)
        changed = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_bytes(self.root / "data/A.json", b'newer')
        with self.assertRaisesRegex(ValueError, "changed"):
            p.publish(self.folder, self.root, changed)
        self.assertEqual((self.root / "data/B.json").read_bytes(), self.before["data/B.json"])
        write_bytes(self.root / "data/A.json", self.before["data/A.json"])
        p.publish(self.folder, self.root, canceled)
        with self.assertRaisesRegex(ValueError, "already used"):
            p.publish(self.folder, self.root, canceled)

    def test_write_then_raise_rolls_back_the_attempted_batch_and_retains_backups(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")
        def failing(path, raw):
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated second-file write failure")
        with patch.object(p, "write_bytes", side_effect=failing), self.assertRaisesRegex(ValueError, "rolled back"):
            p.publish(self.folder, self.root, plan)
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.before}, self.before)
        self.assertEqual(p.records(self.folder)[0]["state"], "rolled_back")

    def test_restart_retains_applied_receipt_and_reviewed_restore_rejects_newer_edits(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected", outputs={"A.json": "approved-output"})
        result = p.publish(self.folder, self.root, plan)
        rows = p.records(self.folder)
        self.assertEqual(rows[0]["id"], result["publication"])
        write_bytes(self.root / "data/A.json", b'new fitting or QA edit')
        with self.assertRaisesRegex(ValueError, "Newer runtime edits"):
            p.restore_candidates(self.folder, self.root, result["publication"])
        write_bytes(self.root / "data/A.json", self.after["data/A.json"])
        candidates, record = p.restore_candidates(self.folder, self.root, result["publication"])
        restore = p.freeze(self.folder, self.root, candidates, "runtime_restore", restore=record)
        p.publish(self.folder, self.root, restore)
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.before}, self.before)
        self.assertEqual(read_json(self.folder / "applied-outputs.json")["files"], {})

    def test_failed_rollback_and_interrupted_publication_offer_only_exact_authorized_restore(self):
        plan = p.freeze(self.folder, self.root, self.after, "rewrap_apply")
        def failing(path, raw):
            if path == self.root / "data/A.json" and raw == self.before["data/A.json"]:
                raise OSError("generated rollback failure")
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated publication failure")
        with patch.object(p, "write_bytes", side_effect=failing), self.assertRaisesRegex(ValueError, "Review restore"):
            p.publish(self.folder, self.root, plan)
        self.assertEqual(p.records(self.folder)[0]["state"], "recovery_needed")
        candidates, record = p.restore_candidates(self.folder, self.root, plan["id"])
        recovered = p.publish(self.folder, self.root, p.freeze(self.folder, self.root, candidates, "runtime_restore", restore=record))
        self.assertEqual(next(row for row in p.history(self.folder) if row["id"] == plan["id"])["state"], "restored")
        candidates, record = p.restore_candidates(self.folder, self.root, recovered["publication"])
        undone = p.publish(self.folder, self.root, p.freeze(self.folder, self.root, candidates, "runtime_restore", restore=record))
        self.assertEqual(next(row for row in p.history(self.folder) if row["id"] == plan["id"])["state"], "recovery_needed")
        candidates, record = p.restore_candidates(self.folder, self.root, undone["publication"])
        p.publish(self.folder, self.root, p.freeze(self.folder, self.root, candidates, "runtime_restore", restore=record))
        self.assertEqual(next(row for row in p.history(self.folder) if row["id"] == plan["id"])["state"], "restored")
        interrupted = p.freeze(self.folder, self.root, self.after, "export_selected")
        path = self.folder / "text-publications" / interrupted["id"] / "receipt.json"
        record = read_json(path)
        record["state"] = "publishing"
        write_json(path, record)
        write_bytes(self.root / "data/A.json", self.after["data/A.json"])
        candidates, record = p.restore_candidates(self.folder, self.root, interrupted["id"])
        p.publish(self.folder, self.root, p.freeze(self.folder, self.root, candidates, "runtime_restore", restore=record))
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.before}, self.before)

    def test_frozen_candidates_and_source_bindings_cannot_change_after_review(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_bytes(self.folder / "text-publications" / plan["id"] / "0.after", b"tampered")
        with self.assertRaisesRegex(ValueError, "frozen candidate changed"):
            p.publish(self.folder, self.root, plan)
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_json(self.folder / "source-inputs.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "source bindings changed"):
            p.publish(self.folder, self.root, plan)
