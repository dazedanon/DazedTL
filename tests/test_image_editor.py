"""Retained native image work and paid scope checks, without native workers or OCR."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dazedtl.images.editor import ImageEditor, validate_blocks
from dazedtl.images.native_translation import ImageNativeTranslation
from dazedtl.storage import write_json, write_bytes
from dazedtl.translation.files import digest, read_json


class Box:
    def __init__(self, value): self.value = value
    def as_xywh(self): return self.value


class Block:
    def __init__(self, value):
        self.value = deepcopy(value)
        self.block_id, self.box = value["id"], Box(value["box"])
        self.source_text, self.target_text = value["source"], value["target"]
        self.skip = value.get("skip", False)
    def to_dict(self): return {**self.value, "target": self.target_text, "skip": self.skip}


class Entry:
    def __init__(self, value):
        self.value = deepcopy(value)
        self.relpath, self.width, self.height = value["image"], value.get("width", 64), value.get("height", 32)
        self.status, self.error, self.engine = value.get("status", "pending"), value.get("error", ""), value.get("engine", "")
        self.blocks = [Block(block) for block in value.get("blocks", [])]
    def to_dict(self):
        return {**self.value, "image": self.relpath, "width": self.width, "height": self.height, "status": self.status,
                "error": self.error, "blocks": [block.to_dict() for block in self.blocks]}
    def block(self, identity): return next(block for block in self.blocks if block.block_id == identity)


class Job:
    def __init__(self, root, work, assets):
        self.root, self.work, self.path, self.language = root, work, work / "image_job.json", "English"
        self.images = [Entry(item) for item in read_json(self.path).get("images", [])] if self.path.exists() else []
        self.originals = {item["relative"]: item.get("original") for item in assets}
        present = {entry.relpath for entry in self.images}
        self.images.extend(Entry({"image": item["relative"]}) for item in assets if item["relative"] not in present)
    def find(self, relative): return next(entry for entry in self.images if entry.relpath == relative)
    def source_path(self, entry): return self.originals.get(entry.relpath) or self.root / entry.relpath
    def to_dict(self): return {"format": "dazedtl-image-job", "version": 4, "root": str(self.root), "language": self.language, "images": [entry.to_dict() for entry in self.images]}


def exchange(job, relatives, path):
    payload = {"format": "dazedtl-image-text", "version": 3, "root": str(job.root), "language": job.language, "images": []}
    for entry in job.images:
        if entry.relpath not in relatives or entry.status not in {"confirmed", "translated", "rendered"}:
            continue
        payload["images"].append({"image": entry.relpath, "regions": [{"id": block.block_id, "source": block.source_text, "target": block.target_text, "box": block.box.as_xywh()} for block in entry.blocks if not block.skip]})
    write_json(path, payload)
    return payload


class EditorTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.root = self.base / "game"; self.work = self.root / ".dazedtl/image_manager/guided"
        self.ids = ["img/A.png", "img/B.png"]
        for identity in self.ids:
            write_bytes(self.root / identity, b"runtime-original")
            write_bytes(self.root / ".dazedtl/images" / identity, b"editable-original")
            write_bytes(self.work / "original" / identity, b"frozen-original")
        self.backend = SimpleNamespace(context=nullcontext, workspace=self.base / "profile", allow_providers=True, running=lambda: False)
        self.configuration = {"mode": "translate", "model": "fixture", "language": "English", "endpoint": "https://provider.invalid", "entries_per_request": 20, "rates": {"input": 1, "output": 2}}
        self.settings = SimpleNamespace(guided_configuration=lambda mode: deepcopy(self.configuration), prepare_engine=Mock(), translation_defaults=lambda: {"batch_supported": True})
        def record(identity):
            if identity != "project": raise ValueError("Unknown project")
            return {}, self.root
        def rows(_project, identities):
            return [{"id": identity, "path": identity, "sourceHash": digest((self.root / identity).read_bytes()),
                     "candidateHash": digest((self.root / ".dazedtl/images" / identity).read_bytes()),
                     "editablePath": str(self.root / ".dazedtl/images" / identity), "frozenPath": str(self.work / "original" / identity)} for identity in identities]
        self.core = SimpleNamespace(record=record, workspace=lambda _: self.work, resolve_assets=rows,
                                    refresh_assets=Mock(), backend=self.backend, settings=self.settings,
                                    translation=SimpleNamespace(jobs=SimpleNamespace(running=lambda: False)))
        self.backend.manual = SimpleNamespace(jobs={}, active=None, running=lambda: False, resume=Mock())
        self.backend.guided_run_context = lambda: {"system.md": "fixture-context"}
        self.backend.saved_run_configuration = lambda identity: {"engine": "Image Text", "selected": ["image_text.json"], "mode": self.backend.manual.jobs[identity]["mode"]}
        for name, function in {"load": Job, "image_size": lambda _: (64, 32), "fonts": lambda: [], "local_ocr": lambda: {"available": False, "detail": "Fixture OCR blocked"}, "exchange": exchange,
                               "set_entry": lambda job, value: setattr(job, "images", [Entry(value) if entry.relpath == value["image"] else entry for entry in job.images])}.items():
            patcher = patch("dazedtl.images.editor.native." + name, side_effect=function); patcher.start(); self.addCleanup(patcher.stop)
        self.editor = ImageEditor(self.core)
        self.translator = ImageNativeTranslation(self.core, self.editor)

    def save(self, identities=None):
        identities = self.ids if identities is None else identities
        state = self.editor.state("project", identities)
        changes = [{"assetId": image["assetId"], "sourceHash": image["sourceHash"], "candidateHash": image["candidateHash"], "status": "confirmed",
                    "blocks": [{"id": image["assetId"], "box": [2, 3, 20, 12], "source": "日本語", "target": "", "angle": 0, "skip": False}]} for image in state["images"]]
        return self.editor.save("project", state["revision"], changes, identities)

    def exported(self):
        state = self.save()
        return self.editor.action("project", state["revision"], "export", self.ids)

    def test_subset_and_empty_scope_do_not_remove_other_saved_images(self):
        self.save()
        only = self.save([self.ids[0]])
        self.assertEqual(len(only["images"]), 1)
        all_images = self.editor.state("project", self.ids)
        self.assertEqual([image["blocks"][0]["source"] for image in all_images["images"]], ["日本語", "日本語"])
        self.assertEqual(self.editor.state("project", [])["images"], [])
        saved = read_json(self.work / "native-editor/image_job.json")
        self.assertEqual(set(saved["bindings"]), set(self.ids))

    def test_external_pixel_change_and_invalid_geometry_block_draft_save(self):
        state = self.save()
        old = deepcopy(state["images"][0])
        old = {key: old[key] for key in ("assetId", "sourceHash", "candidateHash", "blocks")}; old["status"] = "confirmed"
        write_bytes(self.root / ".dazedtl/images" / self.ids[0], b"externally-changed")
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            self.editor.save("project", state["revision"], [old], self.ids)
        bad = [{"id": "bad", "box": [60, 1, 10, 10], "source": "x", "target": "", "skip": False}]
        with self.assertRaisesRegex(ValueError, "inside"):
            validate_blocks(bad, 64, 32)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_blocks([{**bad[0], "box": [1, 1, 10, 10]}, {**bad[0], "box": [2, 2, 10, 10]}], 64, 32)
        with self.assertRaisesRegex(ValueError, "font family"):
            validate_blocks([{**bad[0], "box": [1, 1, 10, 10], "style": {"font": "/secrets"}}], 64, 32)

    def test_import_validates_every_region_before_copying_only_targets(self):
        exported = self.exported(); path = Path(exported["result"]["path"])
        payload = read_json(path)
        for image in payload["images"]: image["regions"][0]["target"] = "English"
        changed = deepcopy(payload); changed["images"][1]["regions"][0]["box"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, "Source text or box"):
            self.editor.action("project", exported["state"]["revision"], "import", self.ids, {"payload": changed})
        before = self.editor.state("project", self.ids)
        self.assertEqual([image["blocks"][0]["target"] for image in before["images"]], ["", ""])
        result = self.editor.action("project", before["revision"], "import", self.ids, {"payload": payload})
        self.assertEqual(result["result"]["applied"], 2)
        self.assertEqual(result["state"]["images"][0]["blocks"][0]["box"], [2, 3, 20, 12])

    def test_export_scope_contains_only_confirmed_images_and_render_progress_survives_failure(self):
        state = self.save()
        changes = [{key: image[key] for key in ("assetId", "sourceHash", "candidateHash", "blocks")} for image in state["images"]]
        for index, item in enumerate(changes):
            item["status"] = "confirmed" if index == 0 else "needs_review"
            item["blocks"][0]["target"] = "English"
        state = self.editor.save("project", state["revision"], changes, self.ids)
        exported = self.editor.action("project", state["revision"], "export", self.ids)
        self.assertEqual(exported["result"]["assetIds"], [self.ids[0]])
        originals = [(self.work / "original" / identity).read_bytes() for identity in self.ids]
        def render(job, entry, **_kwargs):
            write_bytes(job.root / entry.relpath, b"rendered-fixture")
            entry.status = "rendered"
            return []
        with patch("dazedtl.images.editor.native.render", side_effect=render):
            result = self.editor.action("project", exported["state"]["revision"], "render", self.ids)
        self.assertEqual(result["result"]["completed"], [self.ids[0]])
        self.assertIn(self.ids[1], result["result"]["errors"])
        reopened = self.editor.state("project", self.ids)
        self.assertEqual(reopened["images"][0]["status"], "rendered")
        self.assertEqual(reopened["images"][0]["blocks"][0]["target"], "English")
        self.assertEqual([(self.work / "original" / identity).read_bytes() for identity in self.ids], originals)

    def test_paid_preview_is_one_use_source_bound_and_owned_before_launch(self):
        self.exported()
        quote_preview = self.translator.preview("project", "estimate")
        def create(_backend, _inventory, _root, mode):
            identity = "estimate" if mode == "estimate" else "paid"
            job = {"id": identity, "engine": "Image Text", "source": str(self.backend.workspace / "asset-projects/project/translation-input"),
                   "mode": mode, "status": "stopped", "message": "Fixture", "files": ["image_text.json"], "outputs": {}, "model": "fixture", "log": []}
            self.backend.manual.jobs[identity] = job
            return deepcopy(job)
        def resume(identity):
            records = read_json(self.work / "native-editor/native-runs.json")["runs"]
            self.assertIn(identity, records)
            self.backend.manual.jobs[identity]["status"] = "running"
        self.backend.manual.resume.side_effect = resume
        with patch("dazedtl.images.native_translation.native.stage", return_value={"revision": "fixture"}), patch("dazedtl.images.native_translation.native.create", side_effect=create) as created:
            self.translator.start("project", quote_preview["token"], False)
            quote = self.backend.manual.jobs["estimate"]; quote.update(status="complete", estimate={"requests": 1, "live_cost": .01, "batch_cost": .005})
            paid = self.translator.preview("project", "translate")
            self.configuration["model"] = "changed-model"
            with self.assertRaisesRegex(ValueError, "changed after review"):
                self.translator.start("project", paid["token"], True)
            with self.assertRaisesRegex(ValueError, "expired"):
                self.translator.start("project", paid["token"], True)
            self.assertEqual(created.call_count, 1)
            self.configuration["model"] = "fixture"
            paid = self.translator.preview("project", "translate")
            self.translator.start("project", paid["token"], True)
            self.assertEqual(created.call_count, 2)
            with self.assertRaisesRegex(ValueError, "expired"):
                self.translator.start("project", paid["token"], True)
