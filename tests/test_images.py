"""Protect scoped handoff, stale reviews and all-or-nothing image application."""

import os
import shutil
import time
import unittest
from base64 import b64decode
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl import system
from dazedtl.api import views
from dazedtl.api.contracts.validation import check_response
from dazedtl.compatibility import original_files
from dazedtl.compatibility.images import ImageCompatibility
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.images import ImageService, recipes, validation
from dazedtl.images.inventory import png_metadata
from dazedtl.projects.store import Projects
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.operations import lifecycle_path
from PIL import Image

from tests.fixtures import old_backup
from tests.game_writes import game_write
from tests.test_image_families import TEXTS, backdrop, letter
from tests.test_image_families import png as rgba_png

# Background scans finish in milliseconds, but a slow Windows CI runner took
# over two seconds; like the probes, a stuck scan still fails within the
# suite's budget (scripts/test.mjs).
SCAN_SECONDS = float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10) * 0.8
RENDERER = ".dazedtl/image_translation_resources/scripts/render.py"


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

    def original_bytes(self, root, row, key):
        return ImageCompatibility.original_bytes(self, root, row, key)

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

    def restore(self, root, rows, originals=None):
        for row in rows:
            write_bytes(
                root / row["runtime"],
                (root / row["runtimeBackup"]).read_bytes()
                if row.get("runtimeBackup")
                else (originals or {})[row["runtime"]],
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
            workspace=self.profile,
            idle=lambda _: None,
            clean_drafts=lambda _: None,
            writable=lambda _: None,
        )
        self.backend = SimpleNamespace(
            source=self.root / "engine", context=nullcontext, game_write=game_write
        )
        self.service = ImageService(
            self.projects, self.translation, None, self.backend, adapter=self.adapter
        )
        self.scan()
        # A project set up before original files were kept in Git reads its
        # backup.
        write_json(
            lifecycle_path(self.profile, self.identity),
            {"version": 1, "source_backup": old_backup.snapshot(self.game)},
        )

    def scan(self):
        self.service.action(self.identity, "scan")
        deadline = time.monotonic() + SCAN_SECONDS
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

    def recipe(self, asset, candidate, check=None, renderer=b"# fixture renderer"):
        """Saves the recipe an assistant leaves for an edited image."""
        write_bytes(self.game / RENDERER, renderer)
        path = self.game / ".dazedtl/image_translation_resources/manifest.json"
        manifest = read_json(path) if path.exists() else {"version": 1, "recipes": {}}
        manifest["recipes"][asset["id"]] = {
            "output": digest(candidate),
            "command": ["{python}", RENDERER, asset["id"], "{output}"],
            "inputs": {
                RENDERER: digest(renderer),
                asset["frozen"]: asset["frozenHash"],
            },
            "check": check or {"text": [[0, 0, 8, 8]]},
        }
        write_json(path, manifest)

    def reviewed_candidate(self, identity="img/A.png", color=(2, 3, 4, 100)):
        self.choose([identity])
        self.service.action(self.identity, "prepare")
        request, _ = self.request("edit_task")
        candidate = png(color)
        write_bytes(self.game / (".dazedtl/images/" + identity), candidate)
        self.recipe(request["assets"][0], candidate)
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
        unselected = self.service.state(self.identity)["observationRevision"]
        self.choose(["img/A.png"])
        state = self.service.state(self.identity)
        self.scan()
        scanned = self.service.state(self.identity)
        self.assertEqual(state["revision"], scanned["revision"])
        # A scan reloads the images; the user's own choices never do.
        self.assertEqual(unselected, state["observationRevision"])
        self.assertNotEqual(
            state["observationRevision"], scanned["observationRevision"]
        )
        self.service.update(
            self.identity,
            state["revision"],
            {"view": {"query": "B", "workflowMode": "manual", "scroll": 230}},
        )
        self.assertEqual(
            scanned["observationRevision"],
            self.service.state(self.identity)["observationRevision"],
        )
        searched = self.service.list(self.identity, query="B")
        self.assertEqual(searched["selectedMatched"], 0)
        # The view switch counts each view within the same search.
        self.assertEqual(
            searched["views"],
            {"all": 1, "list": 0, "uncertain": 0, "ready": 0, "applied": 0},
        )
        self.assertEqual(self.service.list(self.identity)["views"]["list"], 1)
        reopened = ImageService(
            self.projects, self.translation, None, self.backend, adapter=self.adapter
        )
        state = reopened.state(self.identity)
        self.assertEqual(state["selection"], ["img/A.png"])
        self.assertEqual(state["view"]["scroll"], 230)
        request, result = self.request("discovery_task")
        self.assertEqual([row["id"] for row in request["assets"]], ["img/A.png"])
        self.assertIn("Copying this task did not start an agent", result["text"])
        # Refreshing before the assistant saves a report leaves the task waiting.
        early = reopened.action(self.identity, "refresh_findings")["state"]
        self.assertEqual(early["discovery"]["status"], "awaiting_results")
        self.assertEqual(early["discovery"]["errors"], [])
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

    def test_investigation_ticks_recommendations_and_translation_makes_its_copies(
        self,
    ):
        # Protect the four steps: recommendations arrive ticked once, the
        # translation task needs no separate copy step, and Apply takes only
        # the list's translated images.
        result = self.service.action(
            self.identity, "discovery_task", {"scope": "remaining"}
        )
        request = read_json(Path(result["request"]))
        hashes = {row["id"]: row["sourceHash"] for row in request["assets"]}
        found = [
            {
                "id": identity,
                "sourceHash": hashes[identity],
                "classification": classification,
                "method": "visual",
                "examined": True,
                "reason": "",
                "evidence": "contact sheet 1",
                "variants": [],
            }
            for identity, classification in (
                ("img/A.png", "recommended"),
                # Scene sound effects are a finding of their own, never ticked.
                ("img/B.png", "sound_effects"),
            )
        ]
        # A report saved on the way holds the images still to come as not
        # examined, so the copied task keeps waiting for them.
        later = {**found[1], "classification": "not_examined", "examined": False}
        state = self.report(request, [found[0], later])["state"]
        self.assertEqual(state["discovery"]["status"], "partial")
        # A report that answers every image completes without its flag.
        state = self.report(request, found)["state"]
        self.assertEqual(state["discovery"]["status"], "complete")
        self.assertEqual(state["selection"], ["img/A.png"])
        self.assertTrue(state["view"]["showSelected"])
        # An image the user took out stays out when the report saves again.
        self.choose([])
        found[0]["reason"] = "Japanese title"
        write_json(request["report"], {**read_json(request["report"]), "assets": found})
        self.service.recheck(self.identity)
        self.assertEqual(self.service.state(self.identity)["selection"], [])
        with self.assertRaisesRegex(ValueError, "Every image has been investigated"):
            self.service.action(self.identity, "discovery_task", {"scope": "remaining"})
        self.choose(["img/A.png"])
        editing, _ = self.request("edit_task")
        self.assertTrue((self.game / ".dazedtl/images/img/A.png").is_file())
        # A list a click replaced in earlier versions gets the copied
        # translation task's images back once.
        saved = self.game / ".dazedtl/image_manager/guided/state.json"
        legacy = read_json(saved)
        del legacy["listVersion"]
        write_json(saved, {**legacy, "selection": ["img/B.png"]})
        self.assertEqual(
            ImageService(
                self.projects,
                self.translation,
                None,
                self.backend,
                adapter=self.adapter,
            ).state(self.identity)["selection"],
            ["img/B.png", "img/A.png"],
        )
        self.reviewed_candidate()
        # Investigating all images again starts over instead of handing out or
        # resuming the finished investigation, and its findings replace the
        # list, except for images already translated.
        self.choose(["img/A.png", "img/B.png"])
        again = self.service.action(self.identity, "discovery_task", {"scope": "all"})
        redo = read_json(Path(again["request"]))
        self.assertNotEqual(redo["id"], request["id"])
        self.assertEqual(redo["resumeReport"], "")
        self.assertIn("starts over", again["text"])
        hashes = {row["id"]: row["sourceHash"] for row in redo["assets"]}
        state = self.report(
            redo,
            [
                {
                    **found[0],
                    "classification": "uncertain",
                    "sourceHash": hashes["img/A.png"],
                },
                # Set aside unexamined, it is settled rather than left to investigate.
                {
                    **found[1],
                    "classification": "excluded",
                    "examined": False,
                    "method": "",
                    "sourceHash": hashes["img/B.png"],
                },
            ],
        )["state"]
        self.assertEqual(
            (state["selection"], state["counts"]["notExamined"]), (["img/A.png"], 0)
        )
        self.choose(["img/A.png", "img/B.png"])
        preview = self.service.action(
            self.identity, "preview_apply", {"ready_only": True}
        )["preview"]
        self.assertEqual(
            ([row["id"] for row in preview["assets"]], preview["blocked"]),
            (["img/A.png"], []),
        )
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.choose(["img/A.png"])
        with self.assertRaisesRegex(ValueError, "already in the game"):
            self.service.action(self.identity, "edit_task")
        # The applied image stays ticked but leaves the Recommended view, also
        # when an earlier version saved that view, and Unsure.
        write_json(
            saved, {**read_json(saved), "view": {"showSelected": True, "status": "all"}}
        )
        state = self.service.state(self.identity)
        listed = self.service.list(
            self.identity,
            filter=state["view"]["status"],
            selected_only=state["view"]["showSelected"],
        )
        self.assertEqual(
            (
                listed["total"],
                self.service.list(self.identity, filter="uncertain")["total"],
                listed["views"],
                state["counts"]["uncertain"],
            ),
            (0, 0, {"all": 2, "list": 0, "uncertain": 0, "ready": 0, "applied": 1}, 0),
        )
        self.assertEqual(editing["assets"][0]["id"], "img/A.png")

    def test_an_assistant_led_assistant_runs_the_steps_and_its_progress_completes(
        self,
    ):
        # Assistant-led packaging needs the image records to complete; before
        # these steps its assistant could not reach the Image Manager at all.
        write_bytes(self.game / "img/C.png", png((9, 9, 9, 255)))
        # The scan runs on; status names the next step once it finishes.
        self.service.assistant(self.identity, "scan")
        deadline = time.monotonic() + SCAN_SECONDS
        while (step := self.service.assistant(self.identity, "status"))[
            "next"
        ] == "scan":
            if time.monotonic() > deadline:
                self.fail("The scan did not finish.")
            time.sleep(0.001)
        self.assertEqual(step["next"], "investigate")
        self.assertEqual(
            self.service.progress_units(self.identity),
            {"complete": False, "units": []},
        )
        step = self.service.assistant(self.identity, "investigate")
        request = read_json(Path(step["task"]).with_suffix(".json"))
        # Its own task continues to the next step instead of stopping.
        text = Path(step["task"]).read_text(encoding="utf-8")
        self.assertIn("Investigate which requested images", text)
        self.assertNotIn("then stop", text)
        self.assertEqual(step["report"], request["report"])
        write_json(
            request["report"],
            {
                "version": 1,
                "kind": "discovery",
                "projectId": self.identity,
                "requestId": request["id"],
                "inventoryRevision": request["inventoryRevision"],
                "complete": True,
                "assets": [
                    {
                        "id": row["id"],
                        "sourceHash": row["sourceHash"],
                        "classification": "no_text"
                        if row["id"] == "img/B.png"
                        else "recommended",
                        "method": "visual",
                        "examined": True,
                        "reason": "",
                        "evidence": "contact sheet 1",
                        "variants": [],
                    }
                    for row in request["assets"]
                ],
            },
        )
        # The next step collects the report; recommendations become the list.
        step = self.service.assistant(self.identity, "translate")
        self.assertEqual((step["next"], step["counts"]["listed"]), ("translate", 2))
        request = read_json(Path(step["task"]).with_suffix(".json"))
        self.assertIn(
            "Review each requested PNG", Path(step["task"]).read_text(encoding="utf-8")
        )
        candidate = png((2, 3, 4, 100))
        write_bytes(self.game / ".dazedtl/images/img/A.png", candidate)
        self.recipe(request["assets"][0], candidate)
        hashes = {row["id"]: row["sourceHash"] for row in request["assets"]}
        review = {
            "version": 1,
            "visual": True,
            "alpha": True,
            "protectedPixels": True,
            "layout": True,
            "evidence": "Compared original/candidate at native resolution.",
        }
        write_json(
            request["report"],
            {
                "version": 1,
                "kind": "editing",
                "projectId": self.identity,
                "requestId": request["id"],
                "inventoryRevision": request["inventoryRevision"],
                "complete": True,
                "assets": [
                    {
                        "id": "img/A.png",
                        "sourceHash": hashes["img/A.png"],
                        "candidateHash": digest(candidate),
                        "status": "edited",
                        "reason": "",
                        "review": review,
                    },
                    {
                        "id": "img/C.png",
                        "sourceHash": hashes["img/C.png"],
                        "candidateHash": hashes["img/C.png"],
                        "status": "skipped",
                        "reason": "Text is part of the artwork.",
                        "review": review,
                    },
                ],
            },
        )
        self.assertEqual(
            self.service.assistant(self.identity, "status")["next"], "apply"
        )
        step = self.service.assistant(self.identity, "apply")
        self.assertEqual((step["next"], step["applied"]), ("done", []))
        self.assertEqual((self.game / "img/A.png").read_bytes(), candidate)
        # The skipped image stays out of the records; the applied one counts
        # from its preserved original.
        progress = self.service.progress_units(self.identity)
        self.assertEqual(
            (progress["complete"], [unit["id"] for unit in progress["units"]]),
            (True, ["img/A.png"]),
        )
        unit = progress["units"][0]
        self.assertEqual(
            unit["translated_from_sha256"],
            digest((self.game / unit["source"]).read_bytes()),
        )
        self.assertEqual((self.game / unit["translation"]).read_bytes(), candidate)

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

    def test_an_edit_counts_as_reviewed_only_with_a_current_recipe_and_valid_pixels(
        self,
    ):
        # Without a recipe the next sibling is reverse-engineered from pixels;
        # the validator command and the report reader must agree on it.
        self.choose(["img/A.png"])
        request, copied = self.request("edit_task")
        [asset] = request["assets"]
        candidate = png((2, 3, 4, 100))
        write_bytes(self.game / ".dazedtl/images/img/A.png", candidate)
        review = {
            "version": 1,
            "visual": True,
            "alpha": True,
            "protectedPixels": True,
            "layout": True,
            "evidence": "Compared original/candidate at native resolution.",
        }
        row = {
            "id": "img/A.png",
            "sourceHash": asset["sourceHash"],
            "candidateHash": digest(candidate),
            "status": "edited",
            "reason": "",
            "review": review,
        }

        def read(check=None):
            if check is not None:
                self.recipe(asset, candidate, check)
            self.report(request, [row], True)
            with redirect_stdout(StringIO()):
                exit_code = recipes.main(["request", copied["request"]])
            item = self.service.list(self.identity, asset_id="img/A.png")["items"][0]
            return item["state"], item["blockedReason"], exit_code

        state, reason, exit_code = read()
        self.assertEqual((state, exit_code), ("needs_review", 1))
        self.assertIn("No reusable recipe", reason)
        # A copied task again says what to fix instead of looking finished.
        again = self.service.action(self.identity, "edit_task")
        self.assertEqual(again["requestId"], request["id"])
        self.assertIn("img/A.png: No reusable recipe", again["text"])
        state, reason, exit_code = read({"text": [[0, 0, 4, 8]]})
        self.assertEqual((state, exit_code), ("needs_review", 1))
        self.assertIn("pixels changed outside the declared regions", reason)
        self.assertEqual(read({"text": [[0, 0, 8, 8]]}), ("ready", "", 0))
        # A shared renderer changed after the edit no longer reproduces it.
        write_bytes(self.game / RENDERER, b"# changed for another image")
        state, reason, _ = read()
        self.assertEqual(state, "needs_review")
        self.assertIn("recipe input scripts/render.py changed", reason)
        # The user's own review stays the explicit way past a held review.
        self.service.action(self.identity, "user_review", {"asset_ids": ["img/A.png"]})
        self.assertEqual(
            self.service.list(self.identity, asset_id="img/A.png")["items"][0]["state"],
            "ready",
        )

    def test_a_scan_hands_each_task_the_family_of_its_images(self):
        # Without its family, an assistant inpaints a backdrop the image's
        # siblings hold exactly.
        base = backdrop()
        for index, strokes in enumerate(TEXTS[:3]):
            write_bytes(
                self.game / f"img/Card{index}.png", rgba_png(letter(base, strokes))
            )
        self.scan()
        request, _ = self.request("discovery_task", ["img/Card0.png"])
        family = request["assets"][0]["family"]
        self.assertEqual(
            [member["id"] for member in family["members"]],
            ["img/Card0.png", "img/Card1.png", "img/Card2.png"],
        )

    def test_validation_catches_metadata_loss_hidden_colour_and_stray_changes(self):
        # A compositor rewrote colour under alpha 0 across a whole canvas and
        # Pillow dropped the original's colour chunks; neither is visible.
        pixels = Image.new("RGBA", (8, 8), (10, 20, 30, 0))
        pixels.paste((90, 90, 90, 255), (4, 0, 8, 8))
        stream = BytesIO()
        pixels.save(stream, format="PNG", dpi=(72, 72), icc_profile=b"profile")
        original = stream.getvalue()

        def encoded(image):
            stream = BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue()

        lettered = pixels.copy()
        lettered.paste((250, 250, 250, 255), (5, 1, 7, 3))
        text = validation.region([[4, 0, 4, 4]], (8, 8), None)
        lost = validation.check(original, encoded(lettered), text=text)
        self.assertEqual(lost["failures"], ["chunks"])
        self.assertIn("(iCCP, pHYs)", validation.summary(lost))
        kept = validation.encode_like(encoded(lettered), original)
        self.assertTrue(validation.check(original, kept, text=text)["ok"])
        # Lettering over the transparent half may change its alpha, never the
        # colour of pixels it leaves fully transparent.
        composited = lettered.copy()
        composited.paste((0, 0, 0, 0), (0, 0, 4, 8))
        composited.paste((255, 255, 255, 255), (1, 1, 3, 2))
        result = validation.check(
            original,
            validation.encode_like(encoded(composited), original),
            intermediate=original,
            text=validation.region([[0, 0, 8, 8]], (8, 8), None),
        )
        self.assertEqual(result["failures"], ["hidden_rgb"])
        stray = validation.check(
            original,
            kept,
            text=validation.region([[5, 1, 1, 2]], (8, 8), None),
            protected=validation.region([[5, 4, 2, 2]], (8, 8), None),
            clearance=3,
        )
        self.assertEqual(stray["failures"], ["confined", "clearance"])

    def test_structural_alpha_loss_and_source_changes_block_reviewed_outputs(self):
        self.reviewed_candidate(color=(2, 3, 4, 255))
        item = self.service.list(self.identity)["items"][0]
        self.assertEqual(item["state"], "blocked")
        self.assertIn("transparency", item["blockedReason"])
        # Previews decode once, so their metadata must still match a full
        # check, and a changed file must never come back from the cache.
        self.service.preview(self.identity, "img/A.png", "source", 4)
        source = png((8, 7, 6, 0), (9, 8))
        write_bytes(self.game / "img/A.png", source)
        changed = self.service.preview(self.identity, "img/A.png", "source", 4)
        expected = png_metadata(source)
        self.assertEqual({key: changed[key] for key in expected}, expected)
        with Image.open(BytesIO(b64decode(changed["url"].split(",")[1]))) as scaled:
            self.assertEqual(scaled.size, (4, 4))
        self.service.refresh_assets(self.identity, ["img/A.png"])
        item = self.service.list(self.identity)["items"][0]
        self.assertFalse(item["aiReviewed"])
        self.assertEqual(item["classification"], "not_examined")
        self.assertIn("source changed", item["blockedReason"])

    def test_an_editable_written_without_prepare_is_held_back_from_apply(self):
        # An edited copy placed by hand has no preserved original to restore.
        write_bytes(self.game / ".dazedtl/images/img/A.png", png((2, 3, 4, 100)))
        self.service.recheck(self.identity)
        self.service.action(self.identity, "user_review", {"asset_ids": ["img/A.png"]})
        item = self.service.list(self.identity)["items"][0]
        self.assertEqual(item["state"], "not_prepared")
        self.assertIn("Prepare this image first", item["blockedReason"])
        self.choose(["img/A.png"])
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        self.assertEqual(preview["included"], 0)
        self.assertEqual(preview["blocked"][0]["id"], "img/A.png")

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
        # A game update's stopped merge holds the write back, and the review
        # still applies once the update is finished.
        with (
            patch.object(
                self.translation, "writable", side_effect=ValueError("unfinished Git")
            ),
            self.assertRaisesRegex(ValueError, "unfinished Git"),
        ):
            self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), original)
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), candidate)
        # The saved receipt then reaches every state read.
        check_response("images_state", self.service.state(self.identity))
        self.assertEqual(
            self.service.list(self.identity)["items"][0]["state"], "applied"
        )
        # Restore reads the original from the game's record of its original
        # files, here a backup from before Git kept them, not a copy of its own.
        self.assertFalse(
            (self.game / ".dazedtl/image_manager/guided/runtime-originals").exists()
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

    def test_originals_come_from_the_record_or_an_older_publishers_backup(self):
        # Nothing copies an image when it changes: Restore reads the game's
        # record of its original files, and an older publisher's backup is
        # only read, by Prepare and family matching.
        write_json(lifecycle_path(self.profile, self.identity), {"version": 1})
        original_files.record(self.game, original_files.FOUND)
        original = (self.game / "img/A.png").read_bytes()
        stored = png((5, 6, 7, 100))
        write_bytes(self.game / ".dazedtl/image_backups/img/B.png", stored)
        write_bytes(self.game / "img/B.png", png((9, 9, 9, 100)))
        self.scan()
        self.choose(["img/A.png", "img/B.png"])
        self.service.action(self.identity, "prepare")
        frozen = self.game / ".dazedtl/image_manager/guided/originals/img"
        self.assertEqual((frozen / "A.png").read_bytes(), original)
        self.assertEqual((frozen / "B.png").read_bytes(), stored)
        candidate = self.reviewed_candidate()
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), candidate)
        restore = self.service.action(self.identity, "preview_restore")["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        self.assertEqual((self.game / "img/A.png").read_bytes(), original)
        self.assertEqual(
            (self.game / ".dazedtl/image_backups/img/B.png").read_bytes(), stored
        )

    def test_an_image_reads_applied_from_its_file_once_checkpoints_move(self):
        # Undoing an apply's or Restore originals' checkpoint, or going back
        # past it, changes the image without the task; Images reads it again
        # once the game's checkpoints move.
        original = (self.game / "img/A.png").read_bytes()
        candidate = self.reviewed_candidate()
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        self.service.action(self.identity, "apply", {"token": preview["token"]})
        restore = self.service.action(self.identity, "preview_restore")["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        identity = ["-c", "user.name=DazedTL", "-c", "user.email=dazedtl@localhost"]
        system.run(["git", "-C", str(self.game), "init", "-q"], check=True)

        def checkpoint(raw):
            write_bytes(self.game / "img/A.png", raw)
            system.run(
                ["git", "-C", str(self.game), *identity, "commit", "-q"]
                + ["--allow-empty", "-m", "checkpoint"],
                check=True,
            )
            self.service.state(self.identity)
            return self.service.list(self.identity)["items"][0]["state"]

        self.assertEqual(checkpoint(original), "needs_review")
        # The restore undone brings back the application it took out.
        self.assertEqual(checkpoint(candidate), "applied")
        self.assertEqual(checkpoint(original), "needs_review")
        self.assertEqual(checkpoint(candidate), "applied")

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
                workspace=profile,
                idle=lambda _: None,
                clean_drafts=lambda _: None,
                writable=lambda _: None,
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

    def test_deleted_inventory_rebuilds_empty_instead_of_failing_the_snapshot(self):
        # If the game's work folder is deleted while the Image Manager holds a
        # cached Index, state() must not raise sqlite3.OperationalError and
        # take the whole workspace snapshot down with it.
        self.assertEqual(self.service.state(self.identity)["counts"]["indexed"], 2)
        shutil.rmtree(self.game / ".dazedtl")
        state = self.service.state(self.identity)
        self.assertEqual(state["counts"]["indexed"], 0)
        self.assertEqual(state["folders"], [])
