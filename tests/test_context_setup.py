"""Guidance completion follows file presence; optional layout keeps its own evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, read_json
from dazedtl.translation import context_setup as C


class ContextSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.request_path, self.review_path = (
            self.root / "profile/request.json",
            self.root / "profile/review.json",
        )
        self.native = {"source": str(self.root), "widths": dict(C.DEFAULT_WIDTHS)}
        self.docs = {}
        for name in C.CORE:
            path = self.root / f".dazedtl/{name}.txt"
            path.parent.mkdir(exist_ok=True)
            self.docs[name] = {"text": "", "revision": digest(b""), "path": str(path)}
        self.findings = {"status": "stale", "reportId": None}
        self.scan = {"current": False, "job": None}

    def inspect(self):
        return C.inspect(
            self.request_path,
            self.review_path,
            self.native,
            "game",
            self.docs,
            self.findings,
            self.scan,
            lambda path: digest(path.read_bytes()),
            ["changed references"],
        )

    def test_guidance_completion_requires_only_existing_core_files(self):
        self.assertEqual(self.inspect()["status"], "missing")
        for doc in self.docs.values():
            Path(doc["path"]).write_text("")
        self.assertEqual(self.inspect()["status"], "ready")
        request = C.request(
            self.request_path, "game", {"request_id": "speaker-request"}
        )
        self.assertEqual(
            C.request(self.request_path, "game", {"request_id": "speaker-request"}),
            request,
        )
        write_json(
            self.review_path,
            {
                "documents": {
                    "glossary": {"revision": "old", "scope": "old", "choice": "review"}
                }
            },
        )
        self.native.update(engine_options={"NAMES": True}, phase1_comments=True)
        self.docs["glossary"]["text"] = "Updated glossary"
        self.docs["glossary"]["revision"] = "changed"
        Path(self.docs["glossary"]["path"]).write_text("Updated glossary")
        for report in (
            {"project_id": "another game"},
            {"documents": {"glossary": {"revision": "old"}}},
            [],
        ):
            write_json(self.root / C.REPORT, report)
            observed = self.inspect()
            self.assertEqual(observed["status"], "ready")
            self.assertFalse(observed["documents"]["glossary"]["needsReview"])
        (self.root / C.REPORT).write_text("unfinished report")
        self.request_path.write_text("unfinished request")
        self.review_path.write_text("unfinished review")
        self.assertEqual(self.inspect()["status"], "ready")
        Path(self.docs["game"]["path"]).unlink()
        self.assertNotEqual(self.inspect()["status"], "ready")
        self.assertFalse(self.inspect()["documents"]["game"]["exists"])
        Path(self.docs["game"]["path"]).touch()
        self.assertEqual(self.inspect()["status"], "ready")

    def test_optional_layout_evidence_does_not_gate_saved_guidance(self):
        for doc in self.docs.values():
            Path(doc["path"]).touch()
        request = C.request(
            self.request_path, "game", {"request_id": "speaker-request"}
        )
        (self.root / "windows.js").write_text("window evidence")
        report = {
            "version": 1,
            "request_id": request["request_id"],
            "project_id": "game",
            "layout": {
                "widths": {**C.DEFAULT_WIDTHS, "width": 55},
                "reason": "Measured actual window and font.",
                "evidence": [
                    {
                        "file": "windows.js",
                        "sha256": digest(b"window evidence"),
                        "location": "message window",
                    }
                ],
            },
        }
        write_json(self.root / C.REPORT, report)
        self.assertEqual(self.inspect()["layout"]["widths"]["width"], 55)
        # Legacy context receipts remain usable for layout without any of their
        # former document, reference, speaker or scan bindings.
        write_json(
            self.root / C.REPORT,
            {
                **report,
                "documents": {"game": {"revision": "old"}},
                "scan_sha256": "old",
            },
        )
        self.assertEqual(self.inspect()["layout"]["widths"]["width"], 55)
        for invalid in (
            {**report, "project_id": "other"},
            {**report, "version": True},
            {**report, "layout": {}},
        ):
            write_json(self.root / C.REPORT, invalid)
            self.assertIsNone(self.inspect()["layout"])
            self.assertEqual(self.inspect()["status"], "ready")
        write_json(self.root / C.REPORT, report)
        (self.root / "windows.js").write_text("changed geometry")
        self.assertIsNone(self.inspect()["layout"])
        self.assertEqual(self.inspect()["status"], "ready")
        C.review(self.review_path, self.docs, self.native, "game", "old", "empty")
        self.assertFalse(self.review_path.exists())
        revision = digest(self.native["widths"])
        C.review(self.review_path, self.docs, self.native, "layout", revision, "layout")
        self.assertEqual(read_json(self.review_path), {"layout": revision})
        self.assertEqual(self.inspect()["layoutStatus"], "saved")
        self.native["widths"]["width"] = 70
        with self.assertRaises(ValueError):
            C.review(
                self.review_path, self.docs, self.native, "layout", revision, "layout"
            )
