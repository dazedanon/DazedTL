"""Text batches must retain exact approved bytes through failure and restart."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dazedtl.compatibility import game_write
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
        # The batch backs up every file before its first write, so an edit
        # made in between must be backed up again before it is overwritten.
        during = b'{"text":"manual edit while publishing"}'

        def editing(path, raw, mode=0o644):
            write_bytes(path, raw)
            if path == self.root / "data/A.json":
                write_bytes(self.root / "data/B.json", during)

        with patch.object(game_write, "write_bytes", side_effect=editing):
            result = p.publish(self.folder, self.root, plan)
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.after}, self.after
        )
        restore, _ = p.restore_candidates(self.folder, self.root, result["publication"])
        self.assertEqual(restore, {"data/A.json": newer, "data/B.json": during})
        with self.assertRaises(ValueError):
            p.publish(self.folder, self.root, plan)

    def test_a_batch_that_adds_a_file_takes_it_out_again_on_restore(self):
        added = {
            "js/plugins/Fixes.js": b"// fix",
            "data/A.json": self.after["data/A.json"],
        }
        with self.assertRaisesRegex(ValueError, "no file"):
            p.freeze(self.folder, self.root, added, "playtest_fix")
        plan = p.freeze(
            self.folder,
            self.root,
            added,
            "playtest_fix",
            created={"js/plugins/Fixes.js"},
        )
        result = p.publish(self.folder, self.root, plan)
        self.assertEqual((self.root / "js/plugins/Fixes.js").read_bytes(), b"// fix")
        # A later Apply of another file, which History can't restore, left
        # the fixes unrestorable; a later batch on the same file must go
        # first, and says so.
        p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder,
                self.root,
                {"data/B.json": self.after["data/B.json"]},
                "export_selected",
                outputs={"B.json": "applied"},
                overwrite=True,
            ),
        )
        corrected = p.publish(
            self.folder,
            self.root,
            p.freeze(self.folder, self.root, {"data/A.json": b"qa"}, "qa_apply"),
        )["publication"]
        self.assertEqual(
            p.blocker(p.history(self.folder), result["publication"]),
            {"id": corrected, "kind": "qa_apply", "files": ["data/A.json"]},
        )
        with self.assertRaisesRegex(ValueError, "later batch also changed data/A"):
            p.restore_candidates(self.folder, self.root, result["publication"])
        restore, record = p.restore_candidates(self.folder, self.root, corrected)
        p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, restore, "runtime_restore", restore=record
            ),
        )
        restore, record = p.restore_candidates(
            self.folder, self.root, result["publication"]
        )
        self.assertEqual(
            restore,
            {"js/plugins/Fixes.js": None, "data/A.json": self.before["data/A.json"]},
        )
        p.publish(
            self.folder,
            self.root,
            p.freeze(
                self.folder, self.root, restore, "runtime_restore", restore=record
            ),
        )
        self.assertFalse((self.root / "js/plugins/Fixes.js").exists())
        self.assertEqual(
            (self.root / "data/A.json").read_bytes(), self.before["data/A.json"]
        )
        # The later Apply stays in the game and applied.
        self.assertEqual(
            (self.root / "data/B.json").read_bytes(), self.after["data/B.json"]
        )
        self.assertEqual(
            read_json(self.folder / "applied-outputs.json")["files"],
            {"B.json": "applied"},
        )

    def test_write_then_raise_rolls_back_the_attempted_batch_and_retains_backups(self):
        plan = p.freeze(self.folder, self.root, self.after, "export_selected")

        def failing(path, raw, mode=0o644):
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated second-file write failure")

        with (
            patch.object(game_write, "write_bytes", side_effect=failing),
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
        plan = p.freeze(self.folder, self.root, self.after, "fit_text")

        def failing(path, raw, mode=0o644):
            if path == self.root / "data/A.json" and raw == self.before["data/A.json"]:
                raise OSError("generated rollback failure")
            write_bytes(path, raw)
            if path == self.root / "data/B.json" and raw == self.after["data/B.json"]:
                raise OSError("generated publication failure")

        with (
            patch.object(game_write, "write_bytes", side_effect=failing),
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

    def test_finished_and_expired_reviews_keep_only_backups(self):
        # Each review froze a copy of every file it would write, kept after
        # publishing or expiring: gigabytes on a large game.
        abandoned = p.freeze(self.folder, self.root, self.after, "export_selected")
        published = p.freeze(self.folder, self.root, self.after, "export_selected")
        p.publish(self.folder, self.root, published)
        base = self.folder / "text-publications"
        self.assertEqual(
            sorted(path.name for path in (base / published["id"]).iterdir()),
            ["0.before", "1.before", "receipt.json"],
        )
        path = base / abandoned["id"] / "receipt.json"
        record = read_json(path)
        record["created"] -= p.REVIEW_SECONDS + 1
        write_json(path, record)
        # Batches that earlier versions finished kept their copies too.
        write_bytes(base / published["id"] / "0.after", self.after["data/A.json"])
        fresh = p.freeze(self.folder, self.root, self.before, "export_selected")
        self.assertEqual(
            sorted(path.name for path in base.iterdir()),
            sorted([published["id"], fresh["id"]]),
        )
        self.assertFalse((base / published["id"] / "0.after").exists())

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
        # Apply publishes a saved output itself, checked by hash: copying it
        # took a large game's review seconds per hundred files on Windows.
        output = self.folder / "translated/A.json"
        write_bytes(output, self.after["data/A.json"])
        candidate = {"data/A.json": self.after["data/A.json"]}
        plan = p.freeze(
            self.folder,
            self.root,
            candidate,
            "export_selected",
            overwrite=True,
            sources={"data/A.json": output},
        )
        frozen = self.folder / "text-publications" / plan["id"]
        self.assertFalse((frozen / "0.after").exists())
        write_bytes(output, b"changed after review")
        with self.assertRaisesRegex(ValueError, "frozen candidate changed"):
            p.publish(self.folder, self.root, plan)
        write_bytes(output, self.after["data/A.json"])
        p.publish(self.folder, self.root, plan)
        self.assertEqual(
            (self.root / "data/A.json").read_bytes(), self.after["data/A.json"]
        )

    def test_a_restore_review_diffs_a_large_file_by_its_actual_edits(self):
        # difflib matched whole files: on commands whose codes repeat, like
        # these 40,000 lines, it took over a minute, and a large game's restore
        # review took many. The review shows only the start of each diff.
        from dazedtl.compatibility.text import comparison

        lines = []
        for index in range(8000):
            lines += [
                "{",
                f'"code": {index % 150},',
                f'"indent": {index % 7},',
                f'"text": "台詞{index}"',
                "},",
            ]
        before = "\n".join(lines).encode()
        translated = comparison(before, before.replace("台詞".encode(), b"Line "))
        self.assertTrue(translated["truncated"])
        self.assertLessEqual(len(translated["diff"]), 16000)
        changed = [
            line for line in translated["diff"].split("\n")[2:] if line[0] in "+-"
        ]
        self.assertEqual(
            changed[:4],
            [
                '-"text": "台詞0"',
                '+"text": "Line 0"',
                '-"text": "台詞1"',
                '+"text": "Line 1"',
            ],
        )
        # An insertion and a deletion that keep the line count, as in a game
        # update or a QA correction, show as just those lines.
        after = list(lines)
        del after[30003]
        after[20003] = "replaced"
        after.insert(10003, "inserted")
        edited = comparison(before, "\n".join(after).encode())
        self.assertFalse(edited["truncated"])
        diff = edited["diff"].split("\n")
        self.assertEqual(
            [line for line in diff[2:] if line[0] in "+-"],
            ["+inserted", "-" + lines[20003], "+replaced", "-" + lines[30003]],
        )
        self.assertEqual(
            [line for line in diff if line.startswith("@@")],
            [
                "@@ -10002,4 +10002,5 @@",
                "@@ -20002,5 +20003,5 @@",
                "@@ -30002,5 +30003,4 @@",
            ],
        )

    def test_a_chosen_proposal_applies_undoes_and_applies_again_like_a_finding(
        self,
    ):
        # Applying with a proposal the user chose was refused as a changed
        # correction, because only findings were looked up.
        from dazedtl.compatibility.text import qa_selection

        state = {
            "applied": False,
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
        # After the task's first apply, an undone correction applies again;
        # the first apply's rule refused it as a changed correction. So does a
        # finding never applied, such as a follow-up round's, but no applied
        # correction applies twice.
        state["applied"] = True
        state["questions"][0]["state"] = "undone"
        self.assertEqual(
            qa_selection(state, "qa_apply", {"proposals": ["use"]}), ([], ["use"])
        )
        self.assertEqual(
            qa_selection(state, "qa_apply", {"findings": ["QA-0001"]}),
            (["QA-0001"], []),
        )
        state["findings"][0]["state"] = "applied"
        with self.assertRaisesRegex(ValueError, "already applied"):
            qa_selection(state, "qa_apply", {"findings": ["QA-0001"]})

    def test_saved_qa_findings_and_unreadable_tasks_reach_the_app_by_contract(self):
        # Engine findings carry extra engine fields; passing them through broke
        # the workspace snapshot contract. Corrections come from the findings.
        import json
        import sys
        from types import ModuleType, SimpleNamespace

        from dazedtl.api.contracts.guided import QaState
        from dazedtl.api.contracts.validation import _close_contracts
        from dazedtl.compatibility import text
        from dazedtl.compatibility.dazedmtl import ExistingBackend
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
        }
        engine = ModuleType("util.rpgmaker_qa")
        engine.read_task = lambda path: (Path(path), task, {"stage": "complete"})
        engine.rules_changed = lambda task, checkpoint: False
        engine.FINDINGS_SCHEMA = "findings"
        engine.task_sha256 = lambda task: "task"
        engine.status = lambda root: {"stage": "complete"}
        engine.answers = lambda root: {}
        refreshed = []
        engine.refresh_kept = lambda root, kept: refreshed.append((root, kept))
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
                        "summary": "Other maps call this place a plateau.",
                        "evidence": "Other maps use Plateau.",
                        "family_key": "term:アージリー高原",
                        "severity": "medium",
                        "source": "アージリー高原",
                        "target_identities": ["MapInfos.json#/1/name@a"],
                    },
                    # A scene correction has lines instead of one text.
                    {
                        "id": "QA-0002",
                        "kind": "scene",
                        "category": "fluency",
                        "cluster_id": "Map001.json#/list/1@b",
                        "evidence": "The narration turns present.",
                        "family_key": "narration-tense",
                        "severity": "medium",
                        "scene_id": "Map001.json#/list",
                        "lines": [
                            {
                                "position": number - 1,
                                "command": number,
                                "cluster_id": identity,
                                "source": source,
                                "current": current,
                                "correction": correction,
                                "identities": [identity],
                            }
                            for number, identity, source, current, correction in (
                                (
                                    2,
                                    "Map001.json#/list/1@b",
                                    "扉",
                                    "It opens.",
                                    "It opened.",
                                ),
                                (
                                    3,
                                    "Map001.json#/list/2@c",
                                    "中",
                                    "She goes.",
                                    "She went.",
                                ),
                            )
                        ],
                        "target_identities": [
                            "Map001.json#/list/1@b",
                            "Map001.json#/list/2@c",
                        ],
                    },
                ],
                # An older task's question without a proposal, which the user
                # could only answer by keeping the line; it held up apply.
                "uncertain_playtests": [
                    {
                        "id": "Map029.json#/events/57@d",
                        "source": "解放条件",
                        "current": "Unlock\nCondition",
                        "evidence": "Apply refused every fix.",
                        "places": 1,
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
        # A current task's never-translated report follows what Plugin files
        # keeps, here nothing.
        self.assertEqual(refreshed, [(task_dir, [])])
        self.assertEqual(state["findings"][0]["correction"], "Arjilee Plateau")
        # The page reads the reviewer's plain sentence, or the evidence of a
        # task made before reviewers wrote one; the inspector keeps the rest.
        self.assertEqual(
            [row["reason"] for row in state["findings"]],
            ["Other maps call this place a plateau.", "The narration turns present."],
        )
        self.assertEqual(
            [
                (row["id"], row["current"], row["evidence"])
                for row in text.review_notes(read_json(task_dir / "findings.json"))
            ],
            [
                ("QA-0001", "Arjilee Highlands", "Other maps use Plateau."),
                ("QA-0002", "It opens.\nShe goes.", "The narration turns present."),
            ],
        )
        # It asks nothing, and the History inspector lists it as not corrected.
        self.assertEqual(state["questions"], [])
        self.assertEqual(
            text.not_corrected(read_json(task_dir / "findings.json")),
            [
                {
                    "id": "Map029.json#/events/57@d",
                    "file": "Map029.json",
                    "source": "解放条件",
                    "current": "Unlock\nCondition",
                    "reason": "Apply refused every fix.",
                    "places": 1,
                }
            ],
        )
        self.assertEqual(state["findings"][0]["files"], ["MapInfos.json"])
        scene = state["findings"][1]
        self.assertEqual((scene["kind"], scene["places"]), ("scene", 2))
        self.assertEqual(
            [line["correction"] for line in scene["lines"]], ["It opened.", "She went."]
        )
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
                p.freeze(
                    self.folder,
                    self.root,
                    candidates,
                    kind,
                    task=task_path,
                    findings=["QA-0001", "QA-0002"] if task_path else None,
                ),
            )
            with patch.dict(sys.modules, {"util": package, "util.rpgmaker_qa": engine}):
                applied.append(text.qa_state(plan)["applied"])
        self.assertEqual(applied, [False, True, True])
        # A follow-up round's finding, made after the apply, waits to be
        # applied; the task read as applied, so nothing ever applied it.
        document = read_json(task_dir / "findings.json")
        document["findings"].append({**document["findings"][0], "id": "QA-0003"})
        write_json(task_dir / "findings.json", document)
        with patch.dict(sys.modules, {"util": package, "util.rpgmaker_qa": engine}):
            state = text.qa_state(plan)
        self.assertFalse(state["applied"])
        self.assertEqual(
            [row.get("state", "") for row in state["findings"]],
            ["applied", "applied", ""],
        )

        # A task the app couldn't read read as Not started with no reason, and
        # preparing again returned the same task; it reads as blocked, and
        # preparing sets it aside, never a task the app can read.
        def denied(path):
            raise PermissionError(13, "Permission denied", str(path))

        log = []
        with patch.dict(sys.modules, {"util": package, "util.rpgmaker_qa": engine}):
            text._set_aside(plan, log.append)
            self.assertEqual((log, task_dir.is_dir()), ([], True))
            engine.read_task = denied
            with self.assertRaises(PermissionError) as raised:
                text.qa_state(plan)
            state = text.qa_unreadable(plan, raised.exception)
            text._set_aside(plan, log.append)
        TypeAdapter(QaState).validate_json(json.dumps(state), strict=True)
        self.assertEqual(
            (state["message"], state["unreadable"]["path"]),
            ("DazedTL isn't allowed to read this QA task's files.", str(task_dir)),
        )
        self.assertTrue((task_dir.parent / "task-unreadable/findings.json").is_file())
        self.assertIn("PermissionError", log[0])
        # A game file the app couldn't read was called this task's, and the
        # assistant was told to set the task aside; the error names the game.
        backend = ExistingBackend.__new__(ExistingBackend)
        backend.workflows = SimpleNamespace(folder=lambda _id: self.folder)
        backend.guided_guard = lambda *_: denied(self.root / "data/Map001.json")
        with self.assertRaisesRegex(ValueError, "can't read this game's files.*Map001"):
            backend.guided_text_state({**plan["project"], "id": "project"}, "database")
