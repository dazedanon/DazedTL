"""Completion and review must bind actual current artifacts, not file presence."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dazedtl.storage import write_json
from dazedtl.translation.files import digest
from dazedtl.translation import context_setup as C


class ContextSetupTests(unittest.TestCase):
    def test_context_receipt_requires_current_scan_documents_and_layout_evidence(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            request_path, review_path = root / "profile/request.json", root / "profile/review.json"
            native = {"source": str(root), "widths": C.DEFAULT_WIDTHS}
            docs = {}
            for name in C.CORE:
                path = root / f".dazedtl/{name}.txt"
                path.parent.mkdir(exist_ok=True)
                path.write_text(name)
                docs[name] = {"text": name, "revision": digest(name.encode()), "path": str(path)}
            findings = {"status": "applied", "reportId": "speaker-report"}
            scan = {"current": True, "job": {"result": {"artifact_sha256": "scan-artifact"}}}
            inspect = lambda: C.inspect(request_path, review_path, native, "game", docs, findings, scan, lambda path: digest(path.read_bytes()))
            self.assertEqual(inspect()["status"], "missing")
            request = C.request(request_path, "game", {"request_id": "speaker-request"})
            self.assertEqual(C.request(request_path, "game", {"request_id": "speaker-request"}), request)
            self.assertEqual(inspect()["status"], "waiting")
            report = {"version": 1, "request_id": request["request_id"], "project_id": "game", "speaker_report_id": findings["reportId"],
                      "scan_sha256": "scan-artifact", "references_sha256": digest(()), "documents": {name: {"revision": doc["revision"], "status": "unchanged"} for name, doc in docs.items()}, "layout": None}
            write_json(root / C.REPORT, report)
            self.assertEqual(inspect()["status"], "ready")
            for mutated in ({**report, "project_id": "other"}, {**report, "documents": {"glossary": report["documents"]["glossary"]}}, {**report, "version": True}):
                write_json(root / C.REPORT, mutated)
                self.assertEqual(inspect()["status"], "invalid")
            write_json(root / C.REPORT, {**report, "references_sha256": "changed"})
            self.assertEqual(inspect()["status"], "stale")
            write_json(root / C.REPORT, report)
            scan["current"] = False
            self.assertEqual(inspect()["status"], "stale")
            scan["current"] = True
            docs["game"]["revision"] = "changed"
            self.assertEqual(inspect()["status"], "stale")
            docs["game"]["revision"] = report["documents"]["game"]["revision"]
            (root / "windows.js").write_text("window evidence")
            report["layout"] = {"widths": {**C.DEFAULT_WIDTHS, "width": 55}, "reason": "Measured actual window and font.",
                                "evidence": [{"file": "windows.js", "sha256": digest(b"window evidence"), "location": "message window"}]}
            write_json(root / C.REPORT, report)
            self.assertEqual(inspect()["layout"]["widths"]["width"], 55)
            (root / "windows.js").write_text("changed geometry")
            self.assertEqual(inspect()["status"], "stale")

    def test_empty_review_and_layout_choices_expire_when_saved_values_change(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            request_path, review_path = root / "request.json", root / "review.json"
            native = {"source": str(root), "widths": C.DEFAULT_WIDTHS}
            document = {"text": "", "revision": digest(b""), "path": str(root / "glossary.txt")}
            docs = {"glossary": document}
            args = (request_path, review_path, native, "game", docs, {"reportId": None}, {"current": False}, lambda path: digest(path.read_bytes()))
            with self.assertRaises(ValueError):
                C.review(review_path, docs, native, "glossary", document["revision"], "empty")
            Path(document["path"]).write_text("")
            C.review(review_path, docs, native, "glossary", document["revision"], "empty")
            self.assertTrue(C.inspect(*args)["documents"]["glossary"]["intentionalEmpty"])
            native["phase1_comments"] = True
            self.assertTrue(C.inspect(*args)["documents"]["glossary"]["needsReview"])
            self.assertFalse(C.inspect(*args)["documents"]["glossary"]["reviewed"])
            native["phase1_comments"] = False
            Path(document["path"]).unlink()
            missing = C.inspect(*args)["documents"]["glossary"]
            self.assertFalse(missing["reviewed"])
            self.assertFalse(missing["intentionalEmpty"])
            Path(document["path"]).write_text("")
            document.update(text="updated", revision=digest(b"updated"))
            self.assertFalse(C.inspect(*args)["documents"]["glossary"]["intentionalEmpty"])
            with self.assertRaises(ValueError):
                C.review(review_path, docs, native, "glossary", digest(b""), "review")
            with self.assertRaises(ValueError):
                C.review(review_path, docs, native, "glossary", document["revision"], "empty")
            revision = digest(native["widths"])
            C.review(review_path, docs, native, "layout", revision, "layout")
            self.assertEqual(C.inspect(*args)["layoutStatus"], "saved")
            native["widths"] = {**C.DEFAULT_WIDTHS, "width": 70}
            with self.assertRaises(ValueError):
                C.review(review_path, docs, native, "layout", revision, "layout")
