"""Text batches must retain exact approved bytes through failure and restart."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import publication as p
from dazedtl.translation.files import read_json


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "game"
        self.folder = Path(temporary.name) / "profile"
        self.folder.mkdir()
        self.before = {
            "data/A.json": b'{"text":"before A"}',
            "data/B.json": b'{"text":"before B"}',
        }
        self.after = {
            name: raw.replace(b"before", b"after") for name, raw in self.before.items()
        }
        for name, raw in self.before.items():
            write_bytes(self.root / name, raw)

    def test_empty_canceled_stale_and_repeated_reviews_never_publish(self):
        with self.assertRaises(ValueError):
            p.freeze(self.folder, self.root, {}, "export_selected")
        canceled = p.freeze(self.folder, self.root, self.after, "export_selected")
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.before}, self.before
        )
        changed = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_bytes(self.root / "data/A.json", b"newer")
        with self.assertRaisesRegex(ValueError, "changed"):
            p.publish(self.folder, self.root, changed)
        self.assertEqual(
            (self.root / "data/B.json").read_bytes(), self.before["data/B.json"]
        )
        write_bytes(self.root / "data/A.json", self.before["data/A.json"])
        p.publish(self.folder, self.root, canceled)
        with self.assertRaisesRegex(ValueError, "already used"):
            p.publish(self.folder, self.root, canceled)

    def test_explicit_overwrite_uses_frozen_output_and_backs_up_latest_game_edits(self):
        plan = p.freeze(
            self.folder, self.root, self.after, "export_selected", overwrite=True
        )
        newer = b'{"text":"manual edit after preview"}'
        write_bytes(self.root / "data/A.json", newer)
        result = p.publish(self.folder, self.root, plan)
        self.assertEqual(
            (self.root / "data/A.json").read_bytes(), self.after["data/A.json"]
        )
        restore, _ = p.restore_candidates(self.folder, self.root, result["publication"])
        self.assertEqual(restore["data/A.json"], newer)
        with self.assertRaises(ValueError):
            p.publish(self.folder, self.root, plan)

    def test_write_then_raise_rolls_back_the_attempted_batch_and_retains_backups(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")

        def failing(path, raw):
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated second-file write failure")

        with (
            patch.object(p, "write_bytes", side_effect=failing),
            self.assertRaisesRegex(ValueError, "rolled back"),
        ):
            p.publish(self.folder, self.root, plan)
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.before}, self.before
        )
        self.assertEqual(p.records(self.folder)[0]["state"], "rolled_back")

    def test_restart_retains_applied_receipt_and_reviewed_restore_rejects_newer_edits(
        self,
    ):
        plan = p.freeze(
            self.folder,
            self.root,
            self.after,
            "export_selected",
            outputs={"A.json": "approved-output"},
        )
        result = p.publish(self.folder, self.root, plan)
        rows = p.records(self.folder)
        self.assertEqual(rows[0]["id"], result["publication"])
        write_bytes(self.root / "data/A.json", b"new fitting or QA edit")
        with self.assertRaisesRegex(ValueError, "Newer runtime edits"):
            p.restore_candidates(self.folder, self.root, result["publication"])
        write_bytes(self.root / "data/A.json", self.after["data/A.json"])
        candidates, record = p.restore_candidates(
            self.folder, self.root, result["publication"]
        )
        restore = p.freeze(
            self.folder, self.root, candidates, "runtime_restore", restore=record
        )
        p.publish(self.folder, self.root, restore)
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.before}, self.before
        )
        self.assertEqual(read_json(self.folder / "applied-outputs.json")["files"], {})

    def test_failed_rollback_and_interrupted_publication_offer_only_exact_authorized_restore(
        self,
    ):
        plan = p.freeze(self.folder, self.root, self.after, "rewrap_apply")

        def failing(path, raw):
            if path == self.root / "data/A.json" and raw == self.before["data/A.json"]:
                raise OSError("generated rollback failure")
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated publication failure")

        with (
            patch.object(p, "write_bytes", side_effect=failing),
            self.assertRaisesRegex(ValueError, "Review restore"),
        ):
            p.publish(self.folder, self.root, plan)
        self.assertEqual(p.records(self.folder)[0]["state"], "recovery_needed")
        candidates, record = p.restore_candidates(self.folder, self.root, plan["id"])
        recovered = p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, candidates, "runtime_restore", restore=record
            ),
        )
        self.assertEqual(
            next(row for row in p.history(self.folder) if row["id"] == plan["id"])[
                "state"
            ],
            "restored",
        )
        candidates, record = p.restore_candidates(
            self.folder, self.root, recovered["publication"]
        )
        undone = p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, candidates, "runtime_restore", restore=record
            ),
        )
        self.assertEqual(
            next(row for row in p.history(self.folder) if row["id"] == plan["id"])[
                "state"
            ],
            "recovery_needed",
        )
        candidates, record = p.restore_candidates(
            self.folder, self.root, undone["publication"]
        )
        p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, candidates, "runtime_restore", restore=record
            ),
        )
        self.assertEqual(
            next(row for row in p.history(self.folder) if row["id"] == plan["id"])[
                "state"
            ],
            "restored",
        )
        interrupted = p.freeze(self.folder, self.root, self.after, "export_selected")
        path = self.folder / "text-publications" / interrupted["id"] / "receipt.json"
        record = read_json(path)
        record["state"] = "publishing"
        write_json(path, record)
        write_bytes(self.root / "data/A.json", self.after["data/A.json"])
        candidates, record = p.restore_candidates(
            self.folder, self.root, interrupted["id"]
        )
        p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, candidates, "runtime_restore", restore=record
            ),
        )
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.before}, self.before
        )

    def test_frozen_candidates_and_source_bindings_cannot_change_after_review(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_bytes(
            self.folder / "text-publications" / plan["id"] / "0.after", b"tampered"
        )
        with self.assertRaisesRegex(ValueError, "frozen candidate changed"):
            p.publish(self.folder, self.root, plan)
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")
        write_json(self.folder / "source-inputs.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "source bindings changed"):
            p.publish(self.folder, self.root, plan)

    def test_a_chosen_proposal_applies_and_undoes_like_a_finding(self):
        # Applying with a proposal the user chose was refused as a changed
        # correction, because only findings were looked up.
        from dazedtl.compatibility.text import qa_selection

        state = {
            "findings": [{"id": "QA-0001"}],
            "questions": [
                {"id": "use", "choice": "use"},
                {"id": "keep", "choice": "keep"},
            ],
        }
        options = {"findings": ["QA-0001"], "proposals": ["use"]}
        self.assertEqual(
            qa_selection(state, "qa_apply", options), (["QA-0001"], ["use"])
        )
        with self.assertRaisesRegex(ValueError, "changed"):
            qa_selection(state, "qa_apply", {"proposals": ["keep"]})
        state["questions"][0]["state"] = "applied"
        self.assertEqual(
            qa_selection(state, "qa_undo", {"proposals": ["use"]}), ([], ["use"])
        )

    def test_saved_qa_findings_reach_the_app_as_contract_findings(self):
        # Engine findings carry extra engine fields; passing them through broke
        # the workspace snapshot contract. Corrections come from the findings.
        import json
        import sys
        from types import ModuleType

        from dazedtl.api.contracts.guided import QaState
        from dazedtl.api.contracts.validation import _close_contracts
        from dazedtl.compatibility import text
        from dazedtl.translation.files import digest
        from pydantic import TypeAdapter

        task_dir = self.folder / "text-qa/database/task"
        for name in (
            "task.json",
            "inventory.json",
            "context.json",
            "screen-index.json",
        ):
            write_json(task_dir / name, {})
        task = {
            "game_root": str(self.root),
            "data_root": str(self.root / "data"),
            "created_at": "2026-10-07T10:00:00+00:00",
            "engine_fingerprint": "rules",
        }
        engine = ModuleType("util.rpgmaker_qa")
        engine._read_task = lambda path: (Path(path), task, {"stage": "complete"})
        engine._engine_fingerprint = lambda: "rules"
        engine.FINDINGS_SCHEMA = "findings"
        engine._sha256 = lambda value: "task"
        engine._canonical_bytes = lambda value: b""
        engine.status = lambda root: {}
        write_json(
            task_dir / "findings.json",
            {
                "schema": "findings",
                "task_sha256": "task",
                "findings": [
                    {
                        "id": "QA-0001",
                        "category": "terminology",
                        "cluster_id": "MapInfos.json#/1/name@a",
                        "correction": "Arjilee Plateau",
                        "current": "Arjilee Highlands",
                        "evidence": "Other maps use Plateau.",
                        "family_key": "term:アージリー高原",
                        "severity": "medium",
                        "source": "アージリー高原",
                        "target_identities": ["MapInfos.json#/1/name@a"],
                    }
                ],
            },
        )
        plan = {
            "folder": str(self.folder),
            "options": {"focus": "database"},
            "project_id": "project",
            "project": {"source": str(self.root), "data": str(self.root / "data")},
            "guard": {},
        }
        write_json(
            self.folder / "text-qa-database.json",
            {
                "task": str(task_dir),
                "binding": text.binding(plan),
                "immutable": {
                    name: digest((task_dir / name).read_bytes())
                    for name in (
                        "task.json",
                        "inventory.json",
                        "context.json",
                        "screen-index.json",
                    )
                },
            },
        )
        package = ModuleType("util")
        package.rpgmaker_qa = engine
        with patch.dict(sys.modules, {"util": package, "util.rpgmaker_qa": engine}):
            state = text.qa_state(plan)
        _close_contracts()
        TypeAdapter(QaState).validate_json(json.dumps(state), strict=True)
        self.assertEqual(state["findings"][0]["correction"], "Arjilee Plateau")
        self.assertEqual(state["findings"][0]["files"], ["MapInfos.json"])
        # Corrections applied from this task, and only this task, stay applied
        # once something else is applied later.
        applied = []
        for task_path, candidates, kind in (
            ("another-task", self.after, "qa_apply"),
            (str(task_dir), self.before, "qa_apply"),
            (None, self.after, "export_selected"),
        ):
            p.publish(
                self.folder,
                self.root,
                p.freeze(self.folder, self.root, candidates, kind, task=task_path),
            )
            with patch.dict(sys.modules, {"util": package, "util.rpgmaker_qa": engine}):
                applied.append(text.qa_state(plan)["applied"])
        self.assertEqual(applied, [False, True, True])
