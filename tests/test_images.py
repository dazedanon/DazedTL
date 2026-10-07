"""Protect scoped handoff, stale reviews and all-or-nothing image application."""

import time
import unittest
from contextlib import nullcontext
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.api import views
from dazedtl.api.contracts.validation import check_response
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.images import ImageService
from dazedtl.projects.store import Projects
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.operations import lifecycle_path
from PIL import Image


def png(color=(0, 0, 0, 0), size=(8, 8)):
    stream = BytesIO()
    Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


class FixtureImages:
    """A disk-only fixture boundary; no engine, provider or network imports."""

    def __init__(self):
        self.calls = []

    def profile(self, root, engine, image_root=""):
        return {
            "id": "generic",
            "label": "Loose PNGs",
            "imageRoot": "img",
            "supported": True,
            "reason": "",
            "context": "",
        }

    def key(self, *_):
        return None

    def inventory(self, root, profile, stopped):
        for path in sorted((root / "img").rglob("*.png")):
            if stopped():
                return
            relative = path.relative_to(root).as_posix()
            yield {
                "id": relative,
                "path": relative,
                "runtime": relative,
                "destination": relative,
                "editable": ".dazedtl/images/" + relative,
                "profile": "generic",
                "encrypted": False,
            }

    def source_bytes(self, root, row, key):
        return (root / row["runtime"]).read_bytes()

    def prepare(self, root, profile, rows, key):
        completed, skipped = 0, 0
        for row in rows:
            target = root / row["editable"]
            if target.exists():
                skipped += 1
            else:
                write_bytes(target, (root / row["runtime"]).read_bytes())
                completed += 1
        return {"completed": completed, "skipped": skipped, "errors": []}

    def apply(self, root, profile, rows, key):
        self.calls.append([row["id"] for row in rows])
        for row in rows:
            write_bytes(root / row["runtime"], (root / row["editable"]).read_bytes())
        return {"completed": len(rows), "skipped": 0, "errors": []}

    def restore(self, root, rows):
        for row in rows:
            write_bytes(
                root / row["runtime"], (root / row["runtimeBackup"]).read_bytes()
            )
        return {"completed": len(rows), "errors": []}

    def output_hash(self, root, row, key):
        return digest((root / row["editable"]).read_bytes())

    def skill(self, *_):
        return "Review every PNG in the editable folder using original pixels."

    def census_reference(self):
        return "fixture-image-methodology.md"


class ImageTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        write_bytes(self.game / "img/A.png", png())
        write_bytes(self.game / "img/B.png", png((1, 2, 3, 100)))
        self.profile = self.root / "profile"
        self.projects = Projects(self.profile)
        self.project = self.projects.open({"source": str(self.game), "engine": "MVMZ"})
        self.identity = self.project["id"]
        self.adapter = FixtureImages()
        self.translation = SimpleNamespace(
            workspace=self.profile, idle=lambda _: None, clean_drafts=lambda _: None
        )
        self.backend = SimpleNamespace(source=self.root / "engine", context=nullcontext)
        self.service = ImageService(
            self.projects, self.translation, None, self.backend, adapter=self.adapter
        )
        self.scan()
        saved = snapshot(self.game, store_path(self.game), source_game=True)
        write_json(
            lifecycle_path(self.profile, self.identity),
            {"version": 1, "source_backup": saved},
        )

    def scan(self):
        self.service.action(self.identity, "scan")
        deadline = time.monotonic() + 2
        while self.service.state(self.identity)["job"]["status"] == "running":
            if time.monotonic() > deadline:
                self.fail("Fixture scan did not finish.")
            time.sleep(0.001)
        self.assertEqual(self.service.state(self.identity)["job"]["status"], "complete")

    def choose(self, identities):
        state = self.service.state(self.identity)
        return self.service.update(
            self.identity, state["revision"], {"selection": identities}
        )

    def request(self, action, identities=None):
        if identities is not None:
            self.choose(identities)
        result = self.service.action(self.identity, action, {"scope": "selected"})
        # A copied task's reply must match the contract the renderer validates.
        check_response("images_action", views.image_action(result))
        return read_json(Path(result["request"])), result

    def report(self, request, rows, complete=False):
        write_json(
            request["report"],
            {
                "version": 1,
                "kind": request["kind"],
                "projectId": self.identity,
                "requestId": request["id"],
                "inventoryRevision": request["inventoryRevision"],
                "complete": complete,
                "assets": rows,
            },
        )
        return self.service.action(
            self.identity,
            "refresh_findings" if request["kind"] == "discovery" else "refresh_results",
        )

    def reviewed_candidate(self, identity="img/A.png", color=(2, 3, 4, 100)):
        self.choose([identity])
        self.service.action(self.identity, "prepare")
        request, _ = self.request("edit_task")
        candidate = png(color)
        write_bytes(self.game / (".dazedtl/images/" + identity), candidate)
        self.report(
            request,
            [
                {
                    "id": identity,
                    "sourceHash": request["assets"][0]["sourceHash"],
                    "candidateHash": digest(candidate),
                    "status": "edited",
                    "reason": "",
                    "review": {
                        "version": 1,
                        "visual": True,
                        "alpha": True,
                        "protectedPixels": True,
                        "layout": True,
                        "evidence": "Compared original/candidate at native resolution.",
                    },
                }
            ],
            True,
        )
        return candidate

    def test_selection_and_scoped_handoff_survive_filters_and_restart(self):
        self.choose(["img/A.png"])
        state = self.service.state(self.identity)
        self.scan()
        self.assertEqual(
            state["revision"], self.service.state(self.identity)["revision"]
        )
        self.assertNotEqual(
            state["observationRevision"],
            self.service.state(self.identity)["observationRevision"],
        )
        self.service.update(
            self.identity,
            state["revision"],
            {"view": {"query": "B", "workflowMode": "manual", "scroll": 230}},
        )
        self.assertEqual(
            self.service.list(self.identity, query="B")["selectedMatched"], 0
        )
        reopened = ImageService(
            self.projects, self.translation, None, self.backend, adapter=self.adapter
        )
        state = reopened.state(self.identity)
        self.assertEqual(state["selection"], ["img/A.png"])
        self.assertEqual(state["view"]["scroll"], 230)
        request, result = self.request("discovery_task")
        self.assertEqual([row["id"] for row in request["assets"]], ["img/A.png"])
        self.assertIn("Copying this task did not start an agent", result["text"])
        with self.assertRaisesRegex(ValueError, "expired"):
            reopened.action(self.identity, "apply", {"token": "foreign"})
        # The copy says what it expects back, for the assistant task list.
        self.assertEqual(
            result["handoff"],
            {
                "kind": "image_discovery",
                "requestId": request["id"],
                "expects": [request["report"]],
            },
        )
        # Returning to the window picks up a saved report, validated as
        # Refresh results does; a rejected one is reported once, not retried.
        report = {
            "version": 1,
            "kind": "discovery",
            "projectId": "another-project",
            "requestId": request["id"],
            "inventoryRevision": request["inventoryRevision"],
            "complete": True,
            "assets": [
                {
                    "id": "img/A.png",
                    "sourceHash": request["assets"][0]["sourceHash"],
                    "classification": "recommended",
                    "method": "visual",
                    "examined": True,
                    "reason": "Japanese label",
                    "evidence": "contact sheet 1, cell 1",
                    "variants": [],
                }
            ],
        }
        write_json(request["report"], report)
        reopened.recheck(self.identity)
        rejected = reopened.state(self.identity)["discovery"]
        self.assertEqual(rejected["status"], "awaiting_results")
        self.assertIn("belongs to another", rejected["rejected"])
        with patch.object(
            reopened, "_refresh_report", side_effect=AssertionError("retried")
        ):
            reopened.recheck(self.identity)
        write_json(request["report"], {**report, "projectId": self.identity})
        reopened.recheck(self.identity)
        imported = reopened.state(self.identity)["discovery"]
        self.assertEqual(imported["status"], "complete")
        self.assertNotIn("rejected", imported)

    def test_partial_reports_do_not_certify_detector_misses_or_replace_manual_exclusions(
        self,
    ):
        request, _ = self.request("discovery_task", ["img/A.png", "img/B.png"])
        self.service.action(
            self.identity,
            "exclude",
            {"asset_ids": ["img/B.png"], "reason": "User keeps this variant."},
        )
        assets = {row["id"]: row for row in request["assets"]}
        self.report(
            request,
            [
                {
                    "id": "img/A.png",
                    "sourceHash": assets["img/A.png"]["sourceHash"],
                    "classification": "no_text",
                    "method": "detector_no_ocr",
                    "examined": True,
                    "reason": "No CJK hit",
                    "evidence": "Detector returned zero hits",
                    "variants": [],
                }
            ],
            True,
        )
        state = self.service.state(self.identity)
        self.assertEqual(state["counts"]["examined"], 0)
        self.assertEqual(state["discovery"]["status"], "partial")
        self.assertEqual(
            self.service.list(self.identity, asset_id="img/A.png")["items"][0][
                "classification"
            ],
            "not_examined",
        )
        self.report(
            request,
            [
                {
                    "id": "img/B.png",
                    "sourceHash": assets["img/B.png"]["sourceHash"],
                    "classification": "recommended",
                    "method": "visual",
                    "examined": True,
                    "reason": "Japanese label",
                    "evidence": "contact sheet 2, cell 3",
                    "variants": [],
                }
            ],
        )
        self.assertEqual(
            self.service.list(self.identity, asset_id="img/B.png")["items"][0][
                "classification"
            ],
            "excluded",
        )
        self.assertEqual(self.service.state(self.identity)["counts"]["examined"], 1)
        self.service.action(self.identity, "include", {"asset_ids": ["img/B.png"]})
        self.assertEqual(
            self.service.list(self.identity, asset_id="img/B.png")["items"][0][
                "classification"
            ],
            "recommended",
        )

    def test_changed_candidates_invalidate_review_and_batch_authorization_is_one_use(
        self,
    ):
        self.reviewed_candidate()
        item = self.service.list(self.identity)["items"][0]
        self.assertEqual(item["state"], "ready")
        self.assertTrue(item["aiReviewed"])
        self.assertFalse(item["userReviewed"])
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        write_bytes(self.game / ".dazedtl/images/img/A.png", png((9, 8, 7, 100)))
        # Returning to the window notices an edit made in another editor.
        self.assertEqual(self.service.recheck(self.identity), 1)
        self.assertEqual(
            self.service.list(self.identity)["items"][0]["state"], "needs_review"
        )
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertEqual(self.adapter.calls, [])
        with self.assertRaisesRegex(ValueError, "expired"):
            self.service.action(self.identity, "apply", {"token": preview["token"]})
        item = self.service.list(self.identity)["items"][0]
        self.assertEqual(item["state"], "needs_review")
        self.assertFalse(item["aiReviewed"])

    def test_structural_alpha_loss_and_source_changes_block_reviewed_outputs(self):
        self.reviewed_candidate(color=(2, 3, 4, 255))
        item = self.service.list(self.identity)["items"][0]
        self.assertEqual(item["state"], "blocked")
        self.assertIn("transparency", item["blockedReason"])
        write_bytes(self.game / "img/A.png", png((8, 7, 6, 0), (9, 8)))
        self.service.refresh_assets(self.identity, ["img/A.png"])
        item = self.service.list(self.identity)["items"][0]
        self.assertFalse(item["aiReviewed"])
        self.assertEqual(item["classification"], "not_examined")
        self.assertIn("source changed", item["blockedReason"])

    def test_applied_receipt_and_reviewed_restore_preserve_frozen_original_and_existing_copies(
        self,
    ):
        original = (self.game / "img/A.png").read_bytes()
        candidate = self.reviewed_candidate()
        self.service.action(self.identity, "prepare")
        self.assertEqual(
            (self.game / ".dazedtl/images/img/A.png").read_bytes(), candidate
        )
        reviewed = self.service.action(self.identity, "preview_apply")
        # The review must match the contract the renderer validates.
        check_response("images_action", reviewed)
        preview = reviewed["preview"]
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), candidate)
        # The saved receipt then reaches every state read.
        check_response("images_state", self.service.state(self.identity))
        self.assertEqual(
            self.service.list(self.identity)["items"][0]["state"], "applied"
        )
        restore = self.service.action(self.identity, "preview_restore")["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), original)
        self.assertEqual(
            (self.game / ".dazedtl/images/img/A.png").read_bytes(), candidate
        )
        self.assertEqual(len(self.service.state(self.identity)["receipts"]), 2)
        # A process interruption after runtime publication but before the app receipt
        # must still leave exact reviewed output identifiable and recoverable.
        self.reviewed_candidate()
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        publish = self.adapter.apply

        def interrupted(*arguments):
            publish(*arguments)
            raise KeyboardInterrupt("fixture interruption after publication")

        with (
            patch.object(self.adapter, "apply", side_effect=interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.service.action(self.identity, "apply", {"token": preview["token"]})
        reopened = ImageService(
            self.projects, self.translation, None, self.backend, adapter=self.adapter
        )
        saved = read_json(self.game / ".dazedtl/image_manager/guided/state.json")
        binding = next(iter(saved["pendingPublications"].values()))
        journal_path = self.game / binding["path"]
        journal = read_json(journal_path)
        tampered = deepcopy(journal)
        tampered["assets"][0]["expectedRuntimeHash"] = "0" * 64
        write_json(journal_path, tampered)
        with self.assertRaisesRegex(ValueError, "journal changed"):
            reopened.state(self.identity)
        write_json(journal_path, journal)
        recovered = reopened.state(self.identity)
        self.assertEqual(recovered["lastAction"]["status"], "recovered")
        self.assertEqual(reopened.list(self.identity)["items"][0]["state"], "applied")
        restore = reopened.action(self.identity, "preview_restore")["preview"]
        reopened.action(self.identity, "restore", {"token": restore["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), original)

    def test_another_projects_work_is_taken_over_on_request_or_set_aside(self):
        # A copied game, a new profile or a reinstall opens this folder as a
        # new project; its saved work waits for the user's choice.
        original = (self.game / "img/A.png").read_bytes()
        self.reviewed_candidate()
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        copied, _ = self.request("discovery_task", ["img/B.png"])
        backup = read_json(lifecycle_path(self.profile, self.identity))

        def reopened(name):
            profile = self.root / name
            projects = Projects(profile)
            project = projects.open({"source": str(self.game), "engine": "MVMZ"})
            write_json(lifecycle_path(profile, project["id"]), backup)
            translation = SimpleNamespace(
                workspace=profile, idle=lambda _: None, clean_drafts=lambda _: None
            )
            service = ImageService(
                projects, translation, None, self.backend, adapter=self.adapter
            )
            with self.assertRaises(ForeignWorkError) as raised:
                service.state(project["id"])
            return project["id"], service, raised.exception.summary

        self.identity, self.service, saved = reopened("fresh-profile")
        self.assertEqual((saved["applied"], saved["restorable"]), (1, 1))
        reply = self.service.adopt(self.identity, saved["binding"])
        check_response("images_adopt", reply)
        self.assertEqual(reply["state"]["discovery"]["status"], "idle")
        # The other project's task is resumed by a new one, never handed out again.
        again, _ = self.request("discovery_task", ["img/B.png"])
        self.assertNotEqual(again["id"], copied["id"])
        self.assertEqual(again["resumeFrom"], copied["id"])
        # Restores keep the original saved in the game folder.
        self.choose(["img/A.png"])
        restore = self.service.action(self.identity, "preview_restore")["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), original)

        identity, service, saved = reopened("reinstalled-profile")
        service.start_over(identity, saved["binding"])
        [archived] = (self.game / ".dazedtl/archived").iterdir()
        self.assertTrue((archived / "inventory.sqlite3").is_file())
        self.assertEqual(service.state(identity)["inventoryRevision"], "")
