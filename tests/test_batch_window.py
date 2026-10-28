"""Use the available token pool, not a one-provider-job gate."""

import os
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility.batch_window import (
    BatchWindow,
    active_tokens,
    install_worker,
    reserve_clarification,
    scope,
    workspace_of,
)
from dazedtl.compatibility.process_view import saved
from dazedtl.storage import write_json
from dazedtl.translation.batch_refusals import advance
from dazedtl.translation.files import read_json

from tests.engine import point


class BatchWindowTests(unittest.TestCase):
    def fixture(self, base, name, costs, *, model="fixture", limit=10):
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
                active_tokens(
                    workspace_of(window.root), scope(window.plan), window.count, 10
                ),
                10,
            )
            self.finish(window, 0, status="in_progress", succeeded=1)
            self.assertEqual(
                window.fill(task), 0
            )  # Partial progress cannot free an active job's tokens.
            self.finish(window, 0)
            self.assertEqual(window.fill(task), 1)  # Others are still in progress.
            self.assertEqual(
                active_tokens(
                    workspace_of(window.root), scope(window.plan), window.count, 10
                ),
                9,
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
            )
            self.assertEqual(bounded.fill(task2), 8)
            self.assertEqual(bounded.providers.submit_batch.call_count, 4)
            self.assertEqual(
                active_tokens(
                    workspace_of(bounded.root), scope(bounded.plan), bounded.count, 8
                ),
                8,
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

            # The waits only bound a hang; a slow runner can take over a
            # second to start the worker.
            def submit(*a, **k):
                entered.set()
                if not release.wait(10):
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
                self.assertTrue(entered.wait(10))
                self.assertEqual(second.fill(task2), 0)
            finally:
                release.set()
                worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(second.fill(task2), 0)
            second.providers.submit_batch.assert_not_called()

    def test_poll_refills_before_all_jobs_end_and_fetches_only_after_every_request_is_submitted(
        self,
    ):
        with TemporaryDirectory() as directory:
            window, task = self.fixture(Path(directory), "first", [4, 4, 4], limit=8)
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
                {
                    "_run_batch_poll_fetch": point(
                        lambda _: self.fail("Sequential poll used")
                    )
                },
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
                nullcontext,
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

    def test_guided_worker_on_the_scenario_openai_preset_takes_the_window_path(self):
        # Scenarios point the OpenAI preset at a local stand-in, which counts
        # as OpenAI's own API only through DAZEDTL_TEST_OPENAI_ENDPOINT; a
        # Guided worker that read the hostname instead polled natively.
        stand_in = "http://127.0.0.1:9/v1"
        with (
            TemporaryDirectory() as directory,
            patch.dict(os.environ, {"DAZEDTL_TEST_OPENAI_ENDPOINT": stand_in}),
        ):
            window, task = self.fixture(Path(directory), "guided", [4])
            window.plan["settings"]["api"] = stand_in
            task.should_stop = True
            task_type = type(
                "Task", (), {"_run_batch_poll_fetch": point(lambda _: "native")}
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
                nullcontext,
            )
            self.assertIsNone(task_type._run_batch_poll_fetch(task))

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
                active_tokens(
                    workspace_of(retry.root), scope(retry.plan), retry.count, 10
                ),
                3,
            )

    def test_assistant_led_clarifications_share_the_guided_window(self):
        # An Assistant-led run on a Guided run's OpenAI connection sends its
        # clarification Batch only once the shared window has room, and the
        # window counts the Assistant-led run's provider jobs in flight.
        from dazedtl.translation.jobs import RunStore
        from dazedtl.translation.refusals import POLICY
        from dazedtl.translation.runner import Runner

        from tests.test_translation import BatchProvider, register, request

        with TemporaryDirectory() as directory:
            base = Path(directory)
            game = base / "game"
            game.mkdir()
            register(base, "project", game)
            write_json(
                base / "settings/settings.json",
                {
                    "version": 3,
                    "connections": [
                        {"id": "connection", "runtime_name": "same-connection"}
                    ],
                },
            )
            guided, task = self.fixture(base, "guided", [8])
            guided.fill(task)
            store = RunStore(base)
            job = store.create(
                "project",
                {
                    "version": 1,
                    "kind": "translation",
                    "source": str(game),
                    "complete": True,
                    "requests": [
                        {
                            **request("refused"),
                            "params": {
                                "model": "fixture",
                                "tokens": 3,
                                "messages": [],
                            },
                            "input_tokens": 3,
                        }
                    ],
                    "configuration": {
                        "mode": "batch",
                        "model": "fixture",
                        "connection_id": "connection",
                        "endpoint": "https://api.openai.com/v1",
                        "refusalRetry": POLICY,
                    },
                    "batch_limits": [50, 100000, 10],
                },
                {"cost": 1},
            )
            store.authorize(job)

            class Provider(BatchProvider):
                def input_tokens(self, _params):
                    return 3

                def submit(self, items):
                    super().submit(items)
                    return {"id": "original" if self.calls == 1 else "clarified"}

                def status(self, identity):
                    return {
                        **super().status(identity),
                        "api_status": "completed" if self.ended else "running",
                    }

                def collect(self, _identity, mapping):
                    refusal = {"text": "I cannot translate explicit sexual content."}
                    return {key: refusal for key in mapping.values()}, [], {}

            provider = Provider()

            def step():
                Runner(store, job["id"], provider, lambda: None).step()
                return store.load(job["id"])[0]

            step()
            self.assertEqual(
                active_tokens(base, scope(guided.plan), guided.count, 10), 11
            )
            provider.ended = True
            waiting = step()
            self.assertEqual(waiting["status"], "waiting")
            self.assertEqual(
                waiting["message"], "Waiting for available Batch token capacity."
            )
            self.assertEqual(provider.calls, 1)
            self.finish(guided, 0)
            step()
            self.assertEqual(provider.calls, 2)
            self.assertEqual(
                active_tokens(base, scope(guided.plan), guided.count, 10), 3
            )

    def test_assistant_led_chunks_wait_for_room_beside_a_guided_batch(self):
        # An Assistant-led OpenAI Batch run sends each chunk only once the
        # window it shares with a Guided Batch on the same connection has
        # room; the chunk waits queued, and Cancel settles it unsent. A run
        # frozen before this policy still sends each chunk at once.
        from dazedtl.compatibility.batch_window import RUN_POLICY
        from dazedtl.translation.jobs import RunStore
        from dazedtl.translation.runner import Runner

        from tests.test_translation import BatchProvider, register, request

        with TemporaryDirectory() as directory:
            base = Path(directory)
            game = base / "game"
            game.mkdir()
            register(base, "project", game)
            write_json(
                base / "settings/settings.json",
                {
                    "version": 3,
                    "connections": [
                        {"id": "connection", "runtime_name": "same-connection"}
                    ],
                },
            )
            guided, task = self.fixture(base, "guided", [8])
            guided.fill(task)
            store = RunStore(base)

            def run(prefix, **policy):
                job = store.create(
                    "project",
                    {
                        "version": 1,
                        "kind": "translation",
                        "source": str(game),
                        "complete": True,
                        "requests": [
                            {
                                **request(name),
                                "params": {"model": "fixture", "messages": []},
                                "input_tokens": 3,
                            }
                            for name in (prefix + "-first", prefix + "-second")
                        ],
                        "configuration": {
                            "mode": "batch",
                            "model": "fixture",
                            "connection_id": "connection",
                            "endpoint": "https://api.openai.com/v1",
                        },
                        # One request per provider job.
                        "batch_limits": [1, 100000, 10],
                        **policy,
                    },
                    {"cost": 1},
                )
                store.authorize(job)
                return job["id"], Provider()

            class Provider(BatchProvider):
                def input_tokens(self, _params):
                    return 3

                def submit(self, items):
                    super().submit(items)
                    return {"id": f"provider-{self.calls}"}

                def status(self, identity):
                    return {
                        **super().status(identity),
                        "api_status": "completed" if self.ended else "in_progress",
                    }

            def step(identity, provider):
                Runner(store, identity, provider, lambda: None).step()
                return store.load(identity)[0]

            earlier, provider = run("earlier")
            step(earlier, provider)
            self.assertEqual(provider.calls, 1)
            provider.ended = True
            self.assertEqual(step(earlier, provider)["status"], "complete")
            self.assertEqual(provider.calls, 2)

            canceled, provider = run("canceled", batch_window=RUN_POLICY)
            self.assertEqual(step(canceled, provider)["batches"][0]["state"], "queued")
            write_json(store.folder(canceled) / "cancel.json", {"requested": True})
            settled = step(canceled, provider)
            self.assertEqual(
                [chunk["state"] for chunk in settled["batches"]],
                ["canceled", "canceled"],
            )
            self.assertEqual(provider.calls, 0)

            identity, provider = run("queued", batch_window=RUN_POLICY)
            for _ in range(2):
                queued = step(identity, provider)
                self.assertEqual(queued["status"], "waiting")
                self.assertEqual(
                    queued["message"], "Waiting for available Batch token capacity."
                )
                self.assertEqual(
                    [chunk["state"] for chunk in queued["batches"]],
                    ["queued", "pending"],
                )
                self.assertEqual(
                    {row["state"] for row in queued["states"].values()}, {"pending"}
                )
            self.assertEqual(provider.calls, 0)
            self.finish(guided, 0)
            sent = step(identity, provider)
            self.assertEqual(
                [chunk["state"] for chunk in sent["batches"]], ["submitted", "pending"]
            )
            self.assertEqual(provider.calls, 1)
            self.assertEqual(
                active_tokens(base, scope(guided.plan), guided.count, 10), 3
            )
            # Its own ended chunk frees the room the next one takes.
            provider.ended = True
            step(identity, provider)
            self.assertEqual(provider.calls, 2)

    def test_assistant_led_chunks_take_a_quarter_several_in_flight(self):
        # An Assistant-led OpenAI Batch run frozen with CHUNK_POLICY packs
        # each chunk to a quarter of the Batch token allowance, as Guided
        # packs its provider jobs, and sends the next while the window it
        # shares with Guided has room. After a failed chunk it sends no
        # further chunk but still collects the ones in flight, and a Resume
        # of the failed run sends the rest. A run frozen before it packs one
        # chunk up to the whole allowance.
        from dazedtl.compatibility.batch_window import CHUNK_POLICY, RUN_POLICY
        from dazedtl.translation.jobs import RunStore
        from dazedtl.translation.runner import Runner

        from tests.test_translation import BatchProvider, register, request

        with TemporaryDirectory() as directory:
            base = Path(directory)
            game = base / "game"
            game.mkdir()
            register(base, "project", game)
            write_json(
                base / "settings/settings.json",
                {
                    "version": 3,
                    "connections": [
                        {"id": "connection", "runtime_name": "same-connection"}
                    ],
                },
            )
            guided, task = self.fixture(base, "guided", [8], limit=12)
            guided.fill(task)
            store = RunStore(base)

            class Rejected(Exception):
                status_code = 400

            class Provider(BatchProvider):
                def __init__(self):
                    super().__init__()
                    self.done, self.missing = set(), set()
                    self.rejected = None

                def input_tokens(self, _params):
                    return 3

                def submit(self, items):
                    super().submit(items)
                    if self.calls == self.rejected:
                        raise Rejected
                    return {"id": f"provider-{self.calls}"}

                def status(self, identity):
                    ended = identity in self.done
                    return {
                        "ended": ended,
                        "terminal_failure": False,
                        "api_status": "completed" if ended else "in_progress",
                        "counts": {},
                    }

                def collect(self, identity, mapping):
                    # A request in `missing` comes back as a provider error.
                    responses, _errors, usage = super().collect(identity, mapping)
                    errors = [
                        key for key, row in mapping.items() if row in self.missing
                    ]
                    kept = {
                        key: value
                        for key, value in responses.items()
                        if key not in self.missing
                    }
                    return kept, errors, usage

            def run(prefix, count, **policy):
                job = store.create(
                    "project",
                    {
                        "version": 1,
                        "kind": "translation",
                        "source": str(game),
                        "complete": True,
                        "requests": [
                            {
                                **request(f"{prefix}-{index}"),
                                "params": {"model": "fixture", "messages": []},
                                "input_tokens": 3,
                            }
                            for index in range(count)
                        ],
                        "configuration": {
                            "mode": "batch",
                            "model": "fixture",
                            "connection_id": "connection",
                            "endpoint": "https://api.openai.com/v1",
                        },
                        "batch_limits": [50, 100000, 12],
                        "batch_window": RUN_POLICY,
                        **policy,
                    },
                    {"cost": 1},
                )
                store.authorize(job)
                return job["id"], Provider()

            def step(identity, provider):
                Runner(store, identity, provider, lambda: None).step()
                return store.load(identity)[0]

            def states(job):
                return [chunk["state"] for chunk in job["batches"]]

            def sizes(job):
                return [len(chunk["items"]) for chunk in job["batches"]]

            failure = "Some returned translations failed validation. Later batches have not been submitted."
            # Guided holds 8 of the 12 tokens.
            earlier, provider = run("earlier", 4)
            self.assertEqual(sizes(step(earlier, provider)), [4])
            self.assertEqual(provider.calls, 0)

            identity, provider = run("quarter", 6, batch_chunks=CHUNK_POLICY)
            queued = step(identity, provider)
            self.assertEqual(sizes(queued), [1] * 6)
            self.assertEqual(states(queued), ["submitted", "queued", *["pending"] * 4])
            self.assertEqual(queued["status"], "waiting")
            self.assertEqual(
                queued["message"], "Waiting for available Batch token capacity."
            )
            self.finish(guided, 0)
            several = step(identity, provider)
            self.assertEqual(states(several), [*["submitted"] * 4, "queued", "pending"])
            self.assertEqual(provider.calls, 4)
            self.assertEqual(
                active_tokens(base, scope(guided.plan), guided.count, 12), 12
            )

            # The first chunk fails while the next three are in flight, and
            # the room it frees takes no further chunk.
            first = several["batches"][0]
            provider.done.add(first["id"])
            provider.missing.add(first["items"][0]["request"])
            halted = step(identity, provider)
            self.assertEqual(provider.calls, 4)
            self.assertEqual(halted["status"], "waiting")
            self.assertTrue(halted["message"].startswith(failure), halted["message"])
            self.assertEqual(
                states(halted), ["complete", *["submitted"] * 3, "pending", "pending"]
            )
            provider.done.update(chunk["id"] for chunk in halted["batches"][1:4])
            failed = step(identity, provider)
            self.assertEqual(provider.calls, 4)
            self.assertEqual((failed["status"], failed["message"]), ("failed", failure))
            self.assertEqual(states(failed), [*["complete"] * 4, "pending", "pending"])
            self.assertEqual(
                [row["state"] for row in failed["states"].values()],
                ["failed", *["accepted"] * 3, "pending", "pending"],
            )

            # Resuming the failed run sends the chunks it held back.
            resumed = step(identity, provider)
            self.assertEqual(provider.calls, 6)
            self.assertEqual(
                states(resumed), [*["complete"] * 4, "submitted", "submitted"]
            )
            provider.done.update(chunk["id"] for chunk in resumed["batches"])
            self.assertEqual(states(step(identity, provider)), ["complete"] * 6)

            # A rejected submission stops later sends too, while the chunk
            # sent before it is collected.
            identity, provider = run("rejected", 3, batch_chunks=CHUNK_POLICY)
            provider.rejected = 2
            rejected = step(identity, provider)
            self.assertEqual(states(rejected), ["submitted", "rejected", "pending"])
            self.assertEqual(rejected["status"], "waiting")
            provider.done.add(rejected["batches"][0]["id"])
            failed = step(identity, provider)
            self.assertEqual(
                (failed["status"], failed["message"]),
                ("failed", "Review the rejected submission."),
            )
            self.assertEqual(states(failed), ["complete", "rejected", "pending"])
            self.assertEqual(provider.calls, 2)
