"""Automatic reads/collection cannot resume unsent work or hold the API lock."""

import sys
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility import batch_control
from dazedtl.storage import write_json
from dazedtl.translation.batch_monitor import BatchMonitor
from dazedtl.translation.files import read_json


class BatchMonitorTests(unittest.TestCase):
    def fixture(self, root):
        batch = {"id": "paid", "provider": "openai", "custom_ids": {"one": "key"}}
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json",
            {"status": "partially_submitted", "batches": [batch]},
        )
        write_json(
            root / "log/batch_requests.json",
            {
                "key": {"payload": '{"Line1":"薬"}', "params": {}},
                "unsent": {"payload": '{"Line1":"盾"}', "params": {}},
            },
        )
        job = {"id": "run", "mode": "batch", "status": "stopped"}
        source = str(root / "game")
        owner = {"id": "project", "backend_id": "native", "source": source}
        lock = threading.RLock()
        manual = SimpleNamespace(
            jobs={"run": job},
            folder=lambda _: root,
            controller=lambda _: SimpleNamespace(running=lambda: False),
            resume=Mock(),
            save=Mock(),
        )
        backend = SimpleNamespace(
            lock=lock,
            context=lambda: lock,
            allow_providers=True,
            manual=manual,
            saved_run_configuration=lambda _: {
                "mode": "batch",
                "workflow": {"id": "native"},
            },
            workflows=SimpleNamespace(
                projects={"native": {"id": "native", "source": source}}
            ),
        )

        def consume(identity):
            self.assertEqual(identity, "run")
            self.assertEqual(
                read_json(root / "log/batch_state.json")["status"], "fetched"
            )
            job["status"] = "running"

        manual.consume_batch = Mock(side_effect=consume)
        settings = SimpleNamespace(
            prepare_engine=Mock(),
            batch_connection=Mock(
                return_value={
                    "secret": "fixture",
                    "endpoint": "https://fixture.invalid",
                    "organization": "",
                }
            ),
        )
        guided = SimpleNamespace(
            backend=backend,
            settings=settings,
            projects=SimpleNamespace(data={"projects": [owner]}),
        )
        return BatchMonitor(guided), job, owner

    def test_openrouter_missing_results_block_consumption_and_survive_monitor_restart(
        self,
    ):
        # Provider completion/retention expiry must not become a consume/retry
        # loop or authorize replacement calls after reopening the application.
        from dazedtl.compatibility.openrouter_batch import ResultsUnavailable

        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            batch = {
                "id": "paid",
                "provider": "openrouter",
                "custom_ids": {"one": "key"},
            }
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            write_json(
                root / "log/batch_state.json",
                {"status": "submitted", "batches": [batch]},
            )
            provider = Mock()
            provider.status.return_value = {
                "api_status": "completed",
                "counts": {"succeeded": 1},
            }
            provider.collect_terminal.side_effect = ResultsUnavailable(
                "Results expired; saved receipts were retained."
            )
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                monitor.tick()
                self.assertEqual(monitor.views["run"]["state"], "blocked")
                self.assertIn("expired", job["dazedtl_batch_results_error"])
                self.assertEqual(
                    read_json(root / "log/batch_state.json")["status"], "submitted"
                )
                previous = provider.status.call_count
                BatchMonitor(monitor.guided).tick()
                self.assertEqual(provider.status.call_count, previous)
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.submit.assert_not_called()

    def test_refused_batch_reopens_its_retry_before_consume_without_resubmission(self):
        # Automatic collection must wait for an already authorized clarification
        # Batch and retain its receipt across app restart, without a Live fallback.
        # A second refusal must stay visible in the inspector even though native
        # consume receives an empty body to prevent accepting it as dialogue.
        from dazedtl.compatibility.process_view import batch_results, payload, summary
        from dazedtl.translation.refusals import CLARIFICATION, POLICY

        for retry_text in (
            '{"Line1":"Potion"}',
            "I cannot help with this translation.",
        ):
            with self.subTest(retry=retry_text), TemporaryDirectory() as directory:
                root = Path(directory)
                monitor, job, _ = self.fixture(root)
                plan = {
                    "mode": "batch",
                    "workflow": {"id": "native"},
                    "dazedtl_request_policy": {"refusalRetry": POLICY},
                }
                monitor.backend.saved_run_configuration = lambda _: plan
                write_json(
                    root / "log/batch_requests.json",
                    {
                        "key": {
                            "payload": '{"Line1":"薬"}',
                            "params": {
                                "model": "fixture",
                                "messages": [
                                    {"role": "user", "content": '{"Line1":"薬"}'}
                                ],
                            },
                        }
                    },
                )
                original = {
                    "key": {
                        "text": "I cannot translate explicit sexual content.",
                        "prompt_tokens": 3,
                        "completion_tokens": 1,
                    }
                }
                provider = Mock()
                provider.status.return_value = {
                    "api_status": "completed",
                    "counts": {"succeeded": 1},
                    "ended": True,
                    "terminal_failure": False,
                }
                provider.collect_terminal.return_value = (
                    original,
                    [],
                    {"input_tokens": 3, "output_tokens": 1},
                )
                retry = {
                    "key": {
                        "text": retry_text,
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                    }
                }
                provider.collect.return_value = (
                    retry,
                    [],
                    {"input_tokens": 5, "output_tokens": 2},
                )
                provider.submit.return_value = {"id": "retry"}
                provider.input_tokens.return_value = 10
                module = ModuleType("util.batch_providers")
                module.batch_limits = lambda _: (50, 100_000)
                module._openai_batch_body = lambda provider, params: params
                with (
                    patch.object(
                        batch_control, "TranslationProvider", return_value=provider
                    ),
                    patch.dict(sys.modules, {"util.batch_providers": module}),
                ):
                    monitor.tick()
                    monitor.backend.manual.consume_batch.assert_not_called()
                    provider.submit.assert_called_once()
                    sent = provider.submit.call_args.args[0]
                    self.assertEqual(
                        sent[0]["params"]["messages"][-1]["content"], CLARIFICATION
                    )
                    self.assertEqual(batch_results(root), original)
                    self.assertEqual(
                        summary(root, job)["requests"][0]["state"], "submitted"
                    )
                    pending = payload(root, 0)["responseAttempts"]
                    self.assertEqual(
                        [attempt["kind"] for attempt in pending],
                        ["original", "clarification"],
                    )
                    self.assertEqual(
                        [attempt["batchId"] for attempt in pending], ["paid", "retry"]
                    )
                    self.assertEqual(pending[0]["response"], original["key"])
                    self.assertIsNone(pending[1]["response"])
                    self.assertEqual(pending[1]["payload"]["state"], "submitted")
                    self.assertEqual(
                        pending[1]["payload"]["messages"], sent[0]["params"]["messages"]
                    )
                    reopened = BatchMonitor(monitor.guided)
                    reopened.tick()
                    monitor.backend.manual.consume_batch.assert_called_once_with("run")
                    self.assertEqual(
                        batch_results(root)["key"]["text"],
                        "" if retry_text.startswith("I cannot") else retry_text,
                    )
                    before = {
                        path: path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    }
                    inspected = payload(root, 0)
                    self.assertEqual(
                        inspected["state"],
                        "rejected" if retry_text.startswith("I cannot") else "received",
                    )
                    self.assertEqual(
                        [
                            {key: attempt[key] for key in ("kind", "response")}
                            for attempt in inspected["responseAttempts"]
                        ],
                        [
                            {"kind": "original", "response": original["key"]},
                            {"kind": "clarification", "response": retry["key"]},
                        ],
                    )
                    original_detail, retry_detail = [
                        attempt["payload"] for attempt in inspected["responseAttempts"]
                    ]
                    self.assertEqual(
                        original_detail["usage"],
                        {"input_tokens": 3, "output_tokens": 1},
                    )
                    self.assertEqual(
                        retry_detail["usage"], {"input_tokens": 5, "output_tokens": 2}
                    )
                    self.assertEqual(original_detail["state"], "rejected")
                    self.assertEqual(retry_detail["state"], inspected["state"])
                    self.assertEqual(original_detail["exact"]["custom_id"], "one")
                    self.assertEqual(
                        retry_detail["exact"]["custom_id"], sent[0]["custom_id"]
                    )
                    self.assertEqual(
                        inspected["usage"], {"input_tokens": 8, "output_tokens": 3}
                    )
                    self.assertEqual(
                        {path: path.read_bytes() for path in before}, before
                    )
                    self.assertEqual(
                        summary(root, job)["usage"],
                        {"input_tokens": 8, "output_tokens": 3},
                    )
                    self.assertEqual(
                        [row["id"] for row in summary(root, job)["batches"]],
                        ["paid", "retry"],
                    )
                    self.assertEqual(
                        [
                            row["requestIndices"]
                            for row in summary(root, job)["batches"]
                        ],
                        [[0], [0]],
                    )
                    self.assertEqual(
                        summary(root, job)["batches"][1]["originalBatchId"], "paid"
                    )
                    provider.submit.assert_called_once()
                    provider.live.assert_not_called()
                    job["status"] = "stopped"
                    BatchMonitor(monitor.guided).tick()
                    provider.submit.assert_called_once()

    def test_old_pauses_monitor_then_consume_once_without_resubmitting(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            write_json(
                root / "log/batch_requests.json",
                {"key": {"payload": '{"Line1":"薬"}', "params": {}}},
            )
            provider = Mock()
            provider.status.return_value = {
                "api_status": "in_progress",
                "counts": {"processing": 1},
            }
            provider.collect_terminal.return_value = (
                {"key": {"text": '{"Line1":"Medicine"}'}},
                [],
                {},
            )
            queue = (root / "log/batch_requests.json").read_bytes()
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                monitor.backend.allow_providers = False
                monitor.tick()
                provider.status.assert_not_called()
                monitor.backend.allow_providers = True
                for change in (
                    {"status": "running"},
                    {"status": "waiting"},
                    {"status": "complete"},
                    {"dazedtl_preapproval": True},
                ):
                    original = deepcopy(job)
                    job.update(change)
                    monitor.tick()
                    job.clear()
                    job.update(original)
                provider.status.assert_not_called()
                # Missing state or unsent-only work must never start a worker.
                write_json(root / "log/batch_state.json", {"status": "queued"})
                monitor.tick()
                provider.status.assert_not_called()
                self.assertEqual(monitor.views["run"]["state"], "blocked")
                write_json(
                    root / "log/batch_state.json", {"status": "partially_submitted"}
                )
                monitor.tick()
                self.assertEqual(
                    monitor.views["run"]["batches"][0]["counts"], {"processing": 1}
                )
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.status.return_value = {
                    "api_status": "cancelled",
                    "counts": {"succeeded": 1, "canceled": 0},
                }
                monitor.tick()
                monitor.backend.manual.consume_batch.assert_called_once_with("run")
                self.assertEqual((root / "log/batch_requests.json").read_bytes(), queue)
                self.assertEqual(
                    read_json(root / "log/batch_results.json")["key"]["text"],
                    '{"Line1":"Medicine"}',
                )
                monitor.tick()
                job["status"] = "failed"
                monitor.tick()
                self.assertEqual(monitor.views["run"]["state"], "save_error")
                monitor.backend.manual.consume_batch.assert_called_once()
                # Reopening after downloaded responses skips provider reads
                # entirely and performs only the guarded local save.
                reads = provider.status.call_count
                reopened = BatchMonitor(monitor.guided)
                reopened.tick()
                self.assertEqual(provider.status.call_count, reads)
                self.assertEqual(monitor.backend.manual.consume_batch.call_count, 2)
            monitor.backend.manual.resume.assert_not_called()
            provider.submit.assert_not_called()
            provider.live.assert_not_called()
            provider.cancel.assert_not_called()

    def test_unapproved_partial_queue_cannot_start_a_full_consume_even_after_restart(
        self,
    ):
        # Downloading one terminal chunk used to convert the whole queue to
        # fetched, then launch a worker that failed on every unsent file.
        from dazedtl.translation.refusals import POLICY

        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, _job, _ = self.fixture(root)
            provider = Mock()
            provider.status.return_value = {
                "api_status": "completed",
                "counts": {"succeeded": 1},
            }
            provider.collect_terminal.return_value = (
                {"key": {"text": "retained"}},
                [],
                {},
            )
            frozen = (root / "log/batch_requests.json").read_bytes()
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                monitor.tick()
                self.assertEqual(monitor.views["run"]["state"], "blocked")
                self.assertEqual(batch_control.unsent_requests(root), {"unsent"})
                self.assertEqual(
                    read_json(root / "log/batch_state.json")["status"], "fetched"
                )
                self.assertEqual(
                    read_json(root / "log/batch_results.json"),
                    {"key": {"text": "retained"}},
                )
                monitor.consumed.add("run")  # A worker launched by the older bug.
                monitor.backend.saved_run_configuration = lambda _: {
                    "mode": "batch",
                    "workflow": {"id": "native"},
                    "dazedtl_request_policy": {"refusalRetry": POLICY},
                }
                observed = []

                def reconcile(*_args, **_kwargs):
                    # Auto-refresh may observe the monitor between its local
                    # checks; a fetched, blocked run must stay inactive then.
                    observed.append(deepcopy(monitor.views.get("run")))
                    return {"ready": True, "batches": []}

                with patch(
                    "dazedtl.compatibility.batch_refusals.advance_guided",
                    side_effect=reconcile,
                ):
                    monitor.tick()
                    monitor.tick()
                self.assertEqual(
                    [view["state"] for view in observed], ["blocked", "blocked"]
                )
                self.assertEqual(monitor.views["run"]["state"], "blocked")
                reads = provider.status.call_count
                monitor = BatchMonitor(monitor.guided)
                with patch(
                    "dazedtl.compatibility.batch_refusals.advance_guided",
                    side_effect=reconcile,
                ):
                    monitor.tick()
                self.assertIsNone(observed[-1])
                self.assertEqual(monitor.views["run"]["state"], "blocked")
                self.assertEqual(provider.status.call_count, reads)
                with self.assertRaisesRegex(
                    ValueError, "1 requests were not submitted"
                ):
                    batch_control.require_complete_submission(root)
            self.assertEqual((root / "log/batch_requests.json").read_bytes(), frozen)
            monitor.backend.manual.consume_batch.assert_not_called()
            provider.submit.assert_not_called()
            provider.live.assert_not_called()

    def test_approved_remainder_continues_once_but_stopped_or_superseded_runs_do_not(
        self,
    ):
        # The original cost approval covers later chunks after an app restart.
        # It must not restart a withdrawn or overlapping superseded approval.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            job.update(
                dazedtl_approved=True,
                created="2026-10-05T00:00:00Z",
                files=["Map001.json"],
            )
            monitor.backend.manual.continue_batch = Mock(
                side_effect=lambda _: job.update(status="running")
            )
            provider = Mock()
            provider.status.return_value = {"api_status": "in_progress", "counts": {}}
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                monitor.tick()
                monitor.backend.manual.continue_batch.assert_called_once_with("run")
                provider.status.assert_not_called()
                monitor.tick()
                monitor.backend.manual.continue_batch.assert_called_once()
                job["status"] = "stopped"
                for guard in ("stopped", "canceled", "superseded"):
                    if guard == "stopped":
                        job["dazedtl_batch_stopped"] = True
                    if guard == "canceled":
                        job["dazedtl_batch_cancellations"] = {
                            "paid": {"status": "canceling"}
                        }
                    if guard == "superseded":
                        monitor.backend.manual.jobs["newer"] = {
                            **job,
                            "id": "newer",
                            "created": "2026-10-05T01:00:00Z",
                        }
                    monitor.check("run")
                    monitor.backend.manual.continue_batch.assert_called_once()
                    job.pop("dazedtl_batch_stopped", None)
                    job.pop("dazedtl_batch_cancellations", None)
                monitor.backend.manual.jobs.pop("newer")
            monitor.backend.manual.consume_batch.assert_not_called()
            provider.submit.assert_not_called()
            provider.live.assert_not_called()

    def test_stalled_read_releases_api_lock_and_late_results_cannot_cross_close_owner_or_worker(
        self,
    ):
        for change in ("close", "owner", "complete", "resume"):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory)
                monitor, job, owner = self.fixture(root)
                started, release = threading.Event(), threading.Event()
                provider = Mock()

                def status(_):
                    started.set()
                    if not release.wait(2):
                        raise RuntimeError("Fixture read was not released")
                    return {
                        "api_status": "in_progress"
                        if change == "complete"
                        else "completed",
                        "counts": {"succeeded": 1},
                    }

                provider.status.side_effect = status
                provider.collect_terminal.return_value = (
                    {"key": {"text": "saved"}},
                    [],
                    {},
                )
                before = {
                    path: path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                with patch.object(
                    batch_control, "TranslationProvider", return_value=provider
                ):
                    thread = threading.Thread(target=monitor.tick)
                    thread.start()
                    try:
                        self.assertTrue(started.wait(1))
                        acquired = monitor.backend.lock.acquire(timeout=0.1)
                        self.assertTrue(
                            acquired,
                            "A stalled provider read held the navigation/API lock",
                        )
                        if acquired:
                            if change == "close":
                                monitor.close()
                            elif change == "owner":
                                owner["source"] = str(root / "another-game")
                            else:
                                job["status"] = (
                                    "complete" if change == "complete" else "running"
                                )
                            monitor.backend.lock.release()
                    finally:
                        release.set()
                        thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertFalse((root / "log/batch_results.json").exists())
                self.assertNotIn(
                    monitor.views.get("run", {}).get("state"),
                    {"monitoring", "collecting"},
                )
                provider.collect_terminal.assert_not_called()
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.submit.assert_not_called()
                provider.live.assert_not_called()

    def test_all_rejected_batches_do_not_start_a_futile_save_or_retry_loop(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            monitor, job, _ = self.fixture(root)
            provider = Mock()
            provider.status.return_value = {
                "api_status": "completed",
                "counts": {"succeeded": 0, "errored": 1, "processing": 0},
            }
            provider.collect_terminal.return_value = ({}, ["one"], {})
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                monitor.tick()
                reads = provider.status.call_count
                monitor.tick()
                self.assertEqual(provider.status.call_count, reads)
                self.assertNotIn("run", monitor.views)
                self.assertEqual(job["status"], "failed")
                monitor.backend.manual.consume_batch.assert_not_called()
                provider.submit.assert_not_called()
                provider.live.assert_not_called()
