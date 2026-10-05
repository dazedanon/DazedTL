"""Unapproved scratch files must disappear without losing any approved request."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from dazedtl.compatibility.manual import manual_jobs
from dazedtl.compatibility.preparations import discard, discardable
from dazedtl.storage import write_json


class PreparationTests(unittest.TestCase):
    def test_decline_waits_for_worker_exit_and_approval_is_durable_before_send(self):
        with TemporaryDirectory() as temporary:
            source = Path(temporary)
            module = source / "desktop/backend/manual.py"
            module.parent.mkdir(parents=True)
            module.write_text("""import json, threading
from pathlib import Path
class ManualJobs:
    busy = False
    def __init__(self, workspace, lock, **kwargs):
        self.workspace, self.root, self.lock = workspace, workspace/'manual', lock
        self.jobs, self.worker, self.process, self.active = {}, None, None, ''
        self.stopping, self.allow_providers = threading.Event(), False
        self.load_saved()
    def load_saved(self):
        for path in (self.root/'jobs').glob('*/job.json'):
            value = json.loads(path.read_text()); self.jobs[value['id']] = value
    def folder(self, identity): return self.root/'jobs'/identity
    def running(self): return self.busy
    def save(self, job): (self.folder(job['id'])/'job.json').write_text(json.dumps(job))
    def answer(self, identity, token, approved):
        self.sent = json.loads((self.folder(identity)/'job.json').read_text())
        self.jobs[identity].update(approval=None, status='running')
        self.save(self.jobs[identity]); return dict(self.jobs[identity])
    def stop(self, identity): self.stopping.set()
    def _run(self, identity, resume):
        self.jobs[identity]['status'] = 'complete'; self.save(self.jobs[identity]); self.busy = False
""")
            controller = manual_jobs(
                source, source / "profile", threading.RLock(), False
            )

            def prepared(identity, mode="batch"):
                job = {
                    "id": identity,
                    "mode": mode,
                    "phase": "submit",
                    "status": "waiting",
                    "dazedtl_preapproval": True,
                    "approval": {"token": identity, "detail": {"input_tokens": 40}},
                }
                directory = controller.root / "jobs" / identity
                write_json(directory / "job.json", job)
                write_json(directory / "plan.json", {"workflow": {"id": "owner"}})
                write_json(directory / "translated/Items.json", [{"name": "scratch"}])
                controller.jobs[identity] = job
                child = controller.controller(identity)
                child.active, child.busy = identity, True
                return job, directory, child

            job, directory, child = prepared("declined")
            controller.answer("declined", "declined", False)
            self.assertTrue(directory.exists())  # The worker can still be writing.
            self.assertTrue(child.stopping.is_set())
            child._run("declined", False)
            self.assertFalse(directory.exists())
            self.assertNotIn("declined", controller.jobs)

            job, directory, child = prepared("approved")
            with self.assertRaises(ValueError):
                controller.answer("approved", "foreign-token", True)
            self.assertNotIn("dazedtl_approved", job)
            with patch.object(
                child, "save", side_effect=OSError("fixture write failure")
            ):
                with self.assertRaises(OSError):
                    controller.answer("approved", "approved", True)
            self.assertNotIn("dazedtl_approved", job)
            self.assertFalse(hasattr(child, "sent"))
            controller.answer("approved", "approved", True)
            self.assertTrue(child.sent["dazedtl_approved"])
            with self.assertRaises(ValueError):
                controller.answer("approved", "approved", True)
            with self.assertRaises(ValueError):
                controller.discard_preparation("approved")
            child._run("approved", False)
            self.assertTrue(directory.exists())
            # A later declined main Batch must retain separately approved speakers.
            job["approval"] = {"token": "second", "detail": {}}
            child.active = "approved"
            controller.answer("approved", "second", False)
            self.assertTrue(directory.exists())
            self.assertNotIn("dazedtl_discard_preparation", job)

            draft, draft_directory, _ = prepared("abandoned", "estimate")
            reloaded = manual_jobs(source, source / "profile", threading.RLock(), False)
            self.assertFalse(draft_directory.exists())
            self.assertIn("approved", reloaded.jobs)
            self.assertNotIn("abandoned", reloaded.jobs)

    def test_discard_never_deletes_legacy_or_unresolved_provider_evidence(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "jobs" / "draft"
            job = {
                "id": "draft",
                "mode": "batch",
                "status": "waiting",
                "dazedtl_preapproval": True,
            }
            write_json(root / "plan.json", {})
            write_json(
                root / "log/batch_requests.json",
                {"one": {"payload": '{"Line1":"薬"}', "params": {}}},
            )
            self.assertTrue(discardable(job, root))
            for changes in (
                {"dazedtl_preapproval": False},
                {"dazedtl_approved": True},
                {"dazedtl_submission_intent": True},
            ):
                with self.assertRaises(ValueError):
                    discard({**job, **changes}, root)
                self.assertTrue((root / "plan.json").is_file())
            write_json(
                root / "log/batch_state.json", {"status": "submission_uncertain"}
            )
            with self.assertRaises(ValueError):
                discard(job, root)
            (root / "log/batch_state.json").unlink()
            write_json(
                root / "log/batch_history.json", {"batches": [{"id": "provider-id"}]}
            )
            with self.assertRaises(ValueError):
                discard(job, root)
            (root / "log/batch_history.json").unlink()
            discard(job, root)
            self.assertFalse(root.exists())
