"""Use the available token pool, not a one-provider-job gate."""

from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock

from dazedtl.compatibility.batch_window import (
    BatchWindow,
    active_tokens,
    install_worker,
    reserve_clarification,
    scope,
)
from dazedtl.compatibility.process_view import saved
from dazedtl.storage import write_json
from dazedtl.translation.batch_refusals import advance
from dazedtl.translation.files import read_json


class BatchWindowTests(unittest.TestCase):
    def fixture(self, base, name, costs, *, model="fixture", limit=10, target=5):
        root = base / "engine/manual/jobs" / name
        plan = {
            "settings": {"api": "https://api.openai.com/v1", "model": model},
            "key_name": "same-connection",
            "dazedtl_request_policy": {"batchInputTokens": limit},
        }
        state = {
            "status": "queued",
            "run_id": name,
            "model": model,
            "provider": "openai",
            "endpoint": plan["settings"]["api"],
            "batches": [],
            "file_set": ["Map001.json"],
        }
        queue = {
            f"key-{i}": {"params": {"model": model, "tokens": cost, "messages": []}}
            for i, cost in enumerate(costs)
        }
        write_json(root / "log/batch_requests.json", queue)
        write_json(root / "log/batch_state.json", state)
        write_json(root / "job.json", {"estimate": {"requests": len(queue)}})
        count = lambda params: params["tokens"]
        translation = SimpleNamespace(
            _estimate_openai_batch_input_tokens=count,
            _batch_submit_lock=nullcontext,
            _batch_entry_context_is_current=lambda _: True,
            _read_batch_file=lambda path, **_: read_json(path),
            _openai_batch_token_limit=lambda: limit,
            OPENAI_BATCH_SEQUENTIAL_ENQUEUED_TOKEN_LIMIT=target,
        )
        providers = SimpleNamespace(
            batch_limits=lambda _: (50_000, 200_000_000),
            submit_batch=Mock(
                side_effect=lambda *a, **k: {
                    "id": f"{name}-{providers.submit_batch.call_count}"
                }
            ),
        )

        def record(batches, **fields):
            old = saved(root, "batch_history.json").get("batches", [])
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": old
                    + [
                        {**fields, **batch, "api_status": "in_progress"}
                        for batch in batches
                    ]
                },
            )

        window = BatchWindow(root, plan, translation, providers, Mock(), Mock(), record)
        task = SimpleNamespace(
            should_stop=False,
            emit_log=Mock(),
            _emit_batch_phase=Mock(),
            status_signal=SimpleNamespace(emit=Mock()),
            _emit_batch_output=lambda fn: fn(),
        )
        return window, task

    def finish(self, window, index, *, status="completed", succeeded=None):
        history = read_json(window.root / "log/batch_history.json")
        history["batches"][index]["api_status"] = status
        history["batches"][index]["request_counts"] = {"succeeded": succeeded}
        write_json(window.root / "log/batch_history.json", history)

    def test_fill_multiple_batches_and_refill_on_any_completion_without_releasing_partial_tokens(
        self,
    ):
        with TemporaryDirectory() as directory:
            window, task = self.fixture(Path(directory), "first", [4, 4, 2, 3])
            self.assertEqual(window.fill(task), 3)
            self.assertEqual(window.providers.submit_batch.call_count, 3)
            self.assertEqual(
                active_tokens(window.root, scope(window.plan), window.count, 10), 10
            )
            self.finish(window, 0, status="in_progress", succeeded=1)
            self.assertEqual(
                window.fill(task), 0
            )  # Partial progress cannot free an active job's tokens.
            self.finish(window, 0)
            self.assertEqual(window.fill(task), 1)  # Others are still in progress.
            self.assertEqual(
                active_tokens(window.root, scope(window.plan), window.count, 10), 9
            )
            self.assertEqual(
                read_json(window.root / "log/batch_state.json")["status"], "submitted"
            )
            ids = [
                row["custom_id"]
                for call in window.providers.submit_batch.call_args_list
                for row in call.args[1]
            ]
            self.assertEqual(ids, [f"req-{i:06d}" for i in range(4)])
            self.assertEqual(window.fill(task), 0)
            bounded, task2 = self.fixture(
                Path(directory),
                "bounded",
                [1] * 8,
                model="bounded-model",
                limit=8,
                target=100,
            )
            self.assertEqual(bounded.fill(task2), 8)
            self.assertEqual(bounded.providers.submit_batch.call_count, 4)
            self.assertEqual(
                active_tokens(bounded.root, scope(bounded.plan), bounded.count, 8), 8
            )
            state = read_json(window.root / "log/batch_state.json")
            state["batches"].pop()
            write_json(window.root / "log/batch_state.json", state)
            with self.assertRaisesRegex(ValueError, "receipts conflict"):
                window.fill(task)
            self.assertEqual(window.providers.submit_batch.call_count, 4)

    def test_shared_scope_reserves_uncertain_creates_and_leaves_other_models_independent(
        self,
    ):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            first, task = self.fixture(base, "first", [8])
            first.fill(task)
            second, task2 = self.fixture(base, "second", [4, 2])
            self.assertEqual(
                second.fill(task2), 1
            )  # Backfill the two-token gap, retaining stable request IDs.
            self.assertEqual(
                second.providers.submit_batch.call_args.args[1][0]["custom_id"],
                "req-000001",
            )
            other, task3 = self.fixture(base, "other", [9], model="other-model")
            self.assertEqual(other.fill(task3), 1)
            self.finish(first, 0)
            self.assertEqual(second.fill(task2), 1)
            pending = base / "engine/manual/jobs/uncertain"
            write_json(
                pending / "log/dazedtl-batch-submission.json",
                {
                    "intent": {
                        "receipt": None,
                        "key_name": "same-connection",
                        "endpoint": "https://api.openai.com/v1",
                        "model": "fixture",
                        "estimated_input_tokens": 4,
                    }
                },
            )
            blocked, task4 = self.fixture(base, "blocked", [1])
            self.assertEqual(blocked.fill(task4), 0)
            blocked.providers.submit_batch.assert_not_called()
            # Older uncertain journals have no token/route fields. Their known
            # connection must still reserve capacity instead of disappearing.
            write_json(
                pending / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "old-completed",
                            "key_name": "same-connection",
                            "endpoint": "https://api.openai.com/v1",
                            "model": "fixture",
                            "api_status": "completed",
                        }
                    ]
                },
            )
            write_json(
                pending / "log/dazedtl-batch-submission.json",
                {"intent": {"receipt": None}},
            )
            self.assertEqual(blocked.fill(task4), 0)
            window, task5 = self.fixture(base, "stale", [1], model="stale-model")
            window.translation._batch_entry_context_is_current = lambda _: False
            with self.assertRaisesRegex(ValueError, "unsupported request context"):
                window.fill(task5)
            window.providers.submit_batch.assert_not_called()

    def test_two_workers_cannot_allocate_the_same_available_capacity(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            first, task = self.fixture(base, "first", [8])
            second, task2 = self.fixture(base, "second", [3])
            entered, release = threading.Event(), threading.Event()
            failures = []

            def submit(*a, **k):
                entered.set()
                if not release.wait(1):
                    raise TimeoutError("Fixture was not released")
                return {"id": "paid-first"}

            first.providers.submit_batch.side_effect = submit

            def fill():
                try:
                    first.fill(task)
                except Exception as error:
                    failures.append(error)

            worker = threading.Thread(target=fill)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(second.fill(task2), 0)
            finally:
                release.set()
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(second.fill(task2), 0)
            second.providers.submit_batch.assert_not_called()

    def test_poll_refills_before_all_jobs_end_and_fetches_only_after_every_request_is_submitted(
        self,
    ):
        with TemporaryDirectory() as directory:
            window, task = self.fixture(
                Path(directory), "first", [4, 4, 4], limit=8, target=4
            )
            original_create = window.providers.submit_batch.side_effect

            def submit(*args, **kwargs):
                if window.providers.submit_batch.call_count == 3:
                    task.should_stop = True
                return original_create(*args, **kwargs)

            window.providers.submit_batch.side_effect = submit

            def statuses(**_):
                self.finish(window, 0)
                rows = saved(window.root, "batch_history.json")["batches"]
                return all(row["api_status"] == "completed" for row in rows), rows

            window.translation.checkTranslationBatchStatuses = statuses
            window.translation.failedTranslationBatchStatuses = lambda rows: []
            window.translation.fetchTranslationBatches = Mock(return_value=(3, 0))
            task_type = type(
                "Task",
                (),
                {"_run_batch_poll_fetch": lambda _: self.fail("Sequential poll used")},
            )
            install_worker(
                window.root,
                window.plan,
                window.translation,
                window.providers,
                task_type,
                window.approve,
                window.recover,
                window.record,
            )
            self.assertIsNone(task_type._run_batch_poll_fetch(task))
            self.assertEqual(window.providers.submit_batch.call_count, 3)
            window.translation.fetchTranslationBatches.assert_not_called()
            self.finish(window, 1)
            self.finish(window, 2)
            task.should_stop = False
            self.assertEqual(task_type._run_batch_poll_fetch(task), (3, 0))
            window.translation.fetchTranslationBatches.assert_called_once()
            self.assertEqual(window.providers.submit_batch.call_count, 3)

    def test_clarifications_wait_for_the_shared_budget_without_becoming_uncertain(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            other, task = self.fixture(base, "other", [8])
            other.fill(task)
            retry, _ = self.fixture(base, "retry", [3])
            write_json(
                retry.root / "log/batch_history.json",
                {
                    "batches": [
                        {
                            "id": "original",
                            "key_name": "same-connection",
                            "endpoint": "https://api.openai.com/v1",
                            "model": "fixture",
                            "api_status": "completed",
                            "custom_ids": {"req-000000": "key-0"},
                        }
                    ]
                },
            )
            params = {"model": "fixture", "tokens": 3, "messages": []}
            provider = Mock()
            provider.submit.return_value = {"id": "retry-provider"}

            def retry_once():
                return advance(
                    retry.root,
                    "original",
                    {"key-0": params},
                    {
                        "key-0": {
                            "text": "I cannot help with this translation.",
                            "refusal": True,
                        }
                    },
                    {},
                    provider,
                    input_tokens=retry.count,
                    limits=(50_000, 200_000_000, 10),
                    reserve=lambda items: reserve_clarification(
                        retry.root, retry.plan, items, retry.count, 10
                    ),
                )

            outcome = retry_once()
            self.assertTrue(outcome["waiting_capacity"])
            self.assertEqual(outcome["batches"][0]["state"], "pending")
            provider.submit.assert_not_called()
            self.finish(other, 0)
            self.assertFalse(retry_once()["ready"])
            provider.submit.assert_called_once()
            self.assertEqual(
                active_tokens(retry.root, scope(retry.plan), retry.count, 10), 3
            )
