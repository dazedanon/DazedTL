"""Warm history must stay cheap without hiding changed ownership or receipts."""

import os
import re
import sqlite3
import time
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.compatibility import process_view
from dazedtl.compatibility.dazedmtl import ExistingBackend
from dazedtl.compatibility.observations import RunObservations
from dazedtl.compatibility.run_evidence import Evidence
from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path


class ObservationTests(unittest.TestCase):
    def test_plan_observations_follow_replacements_and_never_replace_execution_validation(
        self,
    ):
        # Same-size replacements with a retained mtime must not keep an old
        # owner, and a warm UI must not bypass the execution plan hash check.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            plan = {
                "workflow": {"id": "first"},
                "settings": {"language": "English"},
                "dazedtl_continuation": {"text": "Not needed in a history observation"},
            }
            write_json(path, plan)
            backend = ExistingBackend.__new__(ExistingBackend)
            backend.manual = SimpleNamespace(
                folder=lambda _: root,
                jobs={"run": {"plan_hash": digest(path.read_bytes())}},
            )
            cache = RunObservations()
            with patch.object(
                backend,
                "saved_run_configuration",
                wraps=backend.saved_run_configuration,
            ) as read:
                for _ in range(2):
                    with cache.read():
                        view = cache.configuration(backend, "run")
                        self.assertEqual(view["workflow"]["id"], "first")
                        self.assertNotIn("dazedtl_continuation", view)
                self.assertEqual(read.call_count, 1)
                self.assertIn(
                    "dazedtl_continuation", cache.configuration(backend, "run")
                )
                self.assertEqual(read.call_count, 2)
                before = path.stat()
                write_json(path, {**plan, "workflow": {"id": "other"}})
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertEqual(path.stat().st_size, before.st_size)
                with (
                    cache.read(),
                    self.assertRaisesRegex(ValueError, "configuration changed"),
                ):
                    cache.configuration(backend, "run")
                backend.manual.jobs["run"]["plan_hash"] = digest(path.read_bytes())
                with cache.read():
                    self.assertEqual(
                        cache.configuration(backend, "run")["workflow"]["id"], "other"
                    )
                path.unlink()
                with cache.read(), self.assertRaises(ValueError):
                    cache.configuration(backend, "run")

    def test_history_cache_refreshes_output_loss_fragments_and_poll_changes_without_cross_run_leaks(
        self,
    ):
        # Positive saved-output evidence must disappear on disk changes even
        # when the in-memory job is unchanged; new fragments and polling
        # receipts must update independently, without sharing mutable UI rows.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            filename = "Map001.json"
            output = root / "translated" / filename
            write_json(output, {"text": "Potion"})
            plan = {"mode": "batch", "selected": [filename]}
            write_json(root / "plan.json", plan)
            job = {
                "id": "run",
                "mode": "batch",
                "status": "complete",
                "phase": "done",
                "files": [filename],
                "completed": [filename],
                "outputs": {filename: digest(output.read_bytes())},
                "plan_hash": digest((root / "plan.json").read_bytes()),
            }
            write_json(root / "job.json", job)
            entry = {
                "payload": '{"Line1":"薬"}',
                "params": {},
                "dazedtl_file": filename,
                "dazedtl_sources": ["owned"],
            }
            write_json(root / "log/batch_requests.json", {"request": entry})
            batch = {
                "id": "batch",
                "status": "consumed",
                "api_status": "completed",
                "custom_ids": {"one": "request"},
                "request_counts": {"succeeded": 1},
            }
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            write_json(
                root / "log/batch_state.json", {"status": "fetched", "batches": [batch]}
            )
            write_json(
                root / "log/batch_results.json",
                {"request": {"text": '{"translations":["Potion"]}'}},
            )
            cache = RunObservations()

            def observe(folder=root, current=job):
                with cache.read():
                    return cache.process(folder, current, plan)

            with (
                patch.object(
                    process_view, "summary", wraps=process_view.summary
                ) as summarize,
                patch.object(
                    process_view, "request_view", wraps=process_view.request_view
                ) as read_requests,
            ):
                first = observe()
                self.assertEqual(first["files"][filename]["states"], ["saved"])
                first["files"][filename]["states"][0] = "changed by UI"
                self.assertEqual(observe()["files"][filename]["states"], ["saved"])
                self.assertEqual(summarize.call_count, 1)
                # The inspector's request pages reuse the observed requests.
                with cache.read():
                    view = cache.requests(root, job, plan)
                self.assertEqual(view["files"][filename]["states"], ["saved"])
                self.assertEqual(read_requests.call_count, 1)
                output.unlink()
                self.assertTrue(observe()["retryBlocked"])
                self.assertEqual(summarize.call_count, 2)
                fragment = root / "log/batch_requests.json.parts/new.json"
                write_json(
                    fragment, {"later": {**entry, "payload": '{"Line1":"回復"}'}}
                )
                # A fragment still being written is no evidence yet, and a
                # changed run reads its queue (every fragment) once.
                writing = fragment.with_name("next.json.1.2.tmp")
                writing.write_text('{"partial', encoding="utf-8")
                with patch.object(
                    process_view, "queue", wraps=process_view.queue
                ) as read_queue:
                    self.assertEqual(observe()["prepared"], 2)
                self.assertEqual(read_queue.call_count, 1)
                writing.unlink()
                fragment.unlink()
                self.assertEqual(observe()["prepared"], 1)
                # Another project can use the same run ID; absolute roots own
                # the cached evidence, and action reads still reconstruct it.
                other = root / "other"
                other.mkdir()
                self.assertEqual(observe(other)["prepared"], 0)
                before = summarize.call_count
                cache.process(root, job, plan)
                self.assertEqual(summarize.call_count, before + 1)
                write_json(
                    root / "log/batch_history.json",
                    {"batches": [{**batch, "api_status": "in_progress"}]},
                )
                pending = {
                    **deepcopy(job),
                    "status": "running",
                    "phase": "poll_status",
                    "batch_detail": [
                        {
                            "id": "batch",
                            "api_status": "finalizing",
                            "counts": {"succeeded": 1},
                        }
                    ],
                }
                self.assertEqual(
                    observe(current=pending)["batches"][0]["status"], "finalizing"
                )
                pending["dazedtl_batch_cancellations"] = {
                    "batch": {"status": "cancelling"}
                }
                self.assertEqual(
                    observe(current=pending)["batches"][0]["status"], "cancelling"
                )

    def test_new_and_wal_ledger_writes_invalidate_both_summary_and_ledger_caches(
        self,
    ):
        # A worker opens its ledger before creating the tables, so a poll can
        # read an empty database. A committed WAL update need not touch the
        # main database file. Caching only that file leaves prepared rows
        # visible after provider submission.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "log/dazedtl-process.sqlite3"
            path.parent.mkdir()
            sqlite3.connect(path).close()
            cache = RunObservations()
            job, plan = (
                {"mode": "translate", "status": "running"},
                {"mode": "translate"},
            )
            with cache.read():
                self.assertEqual(cache.process(root, job, plan)["files"], {})
            evidence = Evidence(root, "translate")
            evidence.local.filename, evidence.local.sources = "Map001.json", ["owned"]
            evidence.prepared(
                {"messages": [{"role": "user", "content": '{"Line1":"薬"}'}]}
            )
            connection = sqlite3.connect(path)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA wal_autocheckpoint=0")
                signature = process_view.file_stamp(path)
                with cache.read():
                    self.assertEqual(
                        cache.process(root, job, plan)["files"]["Map001.json"][
                            "states"
                        ],
                        ["prepared"],
                    )
                connection.execute("UPDATE requests SET state='submitted'")
                connection.commit()
                self.assertEqual(process_view.file_stamp(path), signature)
                with cache.read():
                    view = cache.process(root, job, plan)
                    self.assertEqual(
                        view["files"]["Map001.json"]["states"], ["submitted"]
                    )
                    self.assertTrue(view["retryBlocked"])
            finally:
                connection.close()

    def test_a_polls_file_view_answers_like_project_path_and_rereads_changed_files(
        self,
    ):
        # Polls list each folder once and reuse digests by stat signature. A
        # wrong answer would let a link through or show a changed game file's
        # estimate as current; a file rewritten within one clock tick keeps
        # its signature.
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "www/data/Map001.json"
            write_json(path, {"text": "one"})
            cache = RunObservations()

            def observed(read):
                with cache.read():
                    return read(cache.files())

            self.assertEqual(
                observed(
                    lambda files: files.project_path(root, "www/data/Map001.json")
                ),
                project_path(root, "www/data/Map001.json"),
            )
            try:
                (root / "www/data/Linked.json").symlink_to(path)
            except OSError:  # Windows without the symbolic link privilege
                pass
            for relative in (
                "www/data/Linked.json",
                "www/data/Missing.json",
                "../Map001.json",
                "www\\data\\Map001.json",
            ):
                with self.assertRaises(ValueError) as expected:
                    project_path(root, relative)
                with self.assertRaisesRegex(
                    ValueError, re.escape(str(expected.exception))
                ):
                    observed(lambda files: files.project_path(root, relative))
            self.assertEqual(
                observed(lambda files: files.digest(path)), digest(path.read_bytes())
            )
            stamp = path.stat()
            path.write_bytes(path.read_bytes().replace(b"one", b"two"))
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(
                observed(lambda files: files.digest(path)), digest(path.read_bytes())
            )
            # A settled file is read once, then again only after it changes.
            settled = time.time_ns() - 3600 * 10**9
            os.utime(path, ns=(settled, settled))
            current = observed(lambda files: files.digest(path))
            with patch("builtins.open", side_effect=AssertionError("read again")):
                self.assertEqual(observed(lambda files: files.digest(path)), current)
            write_json(path, {"text": "three"})
            os.utime(path, ns=(settled, settled))
            self.assertEqual(
                observed(lambda files: files.digest(path)), digest(path.read_bytes())
            )
