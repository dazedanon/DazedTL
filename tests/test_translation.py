"""Shared request acceptance and paid-work recovery, with no provider or game dependencies."""

import json
import os
import stat
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dazedtl.api.contracts.translation import TranslationBatch
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.projects.store import SCHEMA_VERSION
from dazedtl.storage import WorkspaceLock, write_json
from dazedtl.translation import jobs, organize
from dazedtl.translation.files import digest, project_path
from dazedtl.translation.jobs import Jobs, RunStore, scratch
from dazedtl.translation.project import ProjectWorkspace, scope
from dazedtl.translation.requests import (
    LINE_KEYS,
    logical_request,
    plan_input,
    provider_view,
    result_value,
)
from dazedtl.translation.results import Results, review_digest
from dazedtl.translation.runner import SHARED_PAYLOADS, Runner, askers
from pydantic import TypeAdapter


def request(identity="scene", speaker="Lili"):
    return logical_request(
        {
            "id": identity,
            "sources": {"line": "はい。⟦P0⟧"},
            "constraints": {"line": {"tokens": ["⟦P0⟧"], "max_lines": 1}},
        },
        {"speakers": {"line": speaker}},
    )


class LiveProvider:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def live(self, _params):
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }


class BatchProvider:
    def __init__(self, error=None):
        self.calls = 0
        self.items = []
        self.error = error
        self.ended = False
        self.unrelated = False

    def submit(self, items):
        self.calls += 1
        self.items = items
        if self.error:
            raise self.error
        return {"id": "provider-job"}

    def status(self, _identity):
        return {
            "ended": self.ended,
            "terminal_failure": False,
            "api_status": "complete" if self.ended else "running",
            "counts": {},
        }

    def collect(self, _identity, mapping):
        if self.unrelated:
            return {}, [], {}
        return (
            {
                key: {"text": '{"line":"Yes. ⟦P0⟧"}'}
                for key in reversed(list(mapping.values()))
            },
            [],
            {"input_tokens": 10},
        )


def register(profile, project_id, game):
    """The project list, which says where the game of project_id's runs is."""
    write_json(
        Path(profile) / "projects.json",
        {
            "version": SCHEMA_VERSION,
            "current_id": "",
            "screen": "project",
            "projects": [
                {
                    "id": project_id,
                    "name": "game",
                    "source": str(game),
                    "engine": "MVMZ",
                    "method": "len",
                    "phase": "database",
                }
            ],
        },
    )


class TranslationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.game.mkdir()
        # Runs find their game through their project's record.
        register(self.root / "profile", "project", self.game)
        self.store = RunStore(self.root / "profile")

    def run_record(self, mode="live", requests=None):
        rows = deepcopy(requests or [request()])
        for row in rows:
            row["params"] = {"model": "fixture", "messages": []}
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "complete": True,
            "requests": rows,
            "configuration": {"mode": mode, "model": "fixture"},
            "batch_limits": [50, 100000],
        }
        job = self.store.create("project", plan, {"cost": 1})
        self.store.authorize(job)
        return job, plan

    def test_result_validation_preserves_ids_masks_and_distinct_speakers(self):
        first = request()
        second = request(speaker="Theo")
        results = Results(self.game)
        results.accept(first, {"line": "Yes. ⟦P0⟧"}, {"mode": "agent"})
        self.assertIsNone(results.get(second))
        relocated = logical_request(
            {
                "id": first["id"],
                "sources": first["sources"],
                "constraints": first["constraints"],
            },
            {
                **first["context"],
                "context_sha256": "relocated-guidance-path",
                "request_sha256": "new-bookkeeping-hash",
            },
        )
        self.assertIsNotNone(results.get(relocated))
        for invalid in (
            {"other": "Yes. ⟦P0⟧"},
            {"line": "Yes."},
            {"line": "Yes. ⟦P0⟧\nExtra"},
            '{"line":"Yes. ⟦P0⟧","line":"No. ⟦P0⟧"}',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                result_value(first, invalid)
        with self.assertRaises(ValueError):
            results.accept(first, {"line": "Different. ⟦P0⟧"}, {})
        self.assertEqual(results.get(first)["translations"]["line"], "Yes. ⟦P0⟧")
        # An assistant's refusal note never becomes a saved translation.
        with self.assertRaises(ValueError):
            results.accept(second, {"line": "[Not translated] ⟦P0⟧"}, {})
        self.assertIsNone(results.get(second))

    def test_results_pass_guided_content_check_and_export_its_cleanup(self):
        # Assistant-led accepted any nonempty text with its tokens kept, so a
        # reply collapsed to a mark or repeating without end reached the game.
        sources = {"line": "今日はとても良い天気ですね。", "moan": "ん♥っ…"}
        row = logical_request({"id": "scene", "sources": sources}, {"user": ""})
        results = Results(self.game)
        for invalid in (".", "a" * 50, "It hurts. " * 30):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                results.accept(row, {**sources, "line": invalid}, {})
        # Masks are no text: a line collapsed to its masks and a mark is
        # as short as the mark.
        masked = logical_request(
            {
                "id": "masked",
                "sources": {"line": "⟦P0⟧今日はとても良い天気ですね。⟦P1⟧"},
            },
            {"user": ""},
        )
        with self.assertRaisesRegex(ValueError, "unusually short"):
            results.accept(masked, {"line": "⟦P0⟧.⟦P1⟧"}, {})
        self.assertIsNone(results.get(row))
        # A Live reply with one failing line keeps that line in its source
        # text, as Guided keeps it, and the lines that passed, so no retry
        # pays for them again; nothing is sent twice.
        live = logical_request({"id": "scene", "sources": sources}, {"user": "Live"})
        reply = {"text": json.dumps({"line": ".", "moan": "Mm♥Ah"})}
        provider = LiveProvider()
        provider.live = lambda _params: (
            provider.__dict__.update(calls=provider.calls + 1) or deepcopy(reply)
        )
        job, _plan = self.run_record(requests=[live])
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _plan = self.store.load(job["id"])
        self.assertEqual(current["status"], "complete")
        self.assertIn(
            "line (Translation unusually short", current["states"]["scene"]["message"]
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            results.get(live)["translations"],
            {"line": sources["line"], "moan": "Mm♥Ah"},
        )
        # A line given back as its source is saved, as Guided keeps it, but
        # is no translation: the export reads it left.
        accepted = {"line": sources["line"], "moan": "Mm♥Ah...h"}
        saved = results.accept(row, accepted, {})
        # The export gets Guided's automatic lint fixes; the receipt and a
        # review of it stay as accepted.
        saved["reviewed"] = {
            identity: review_digest(sources[identity], text)
            for identity, text in accepted.items()
        }
        write_json(project_path(self.game, results.relative(row)), saved)
        self.assertEqual(results.get(row)["translations"], accepted)
        units = {
            unit["source_id"]: unit for unit in results.units([row], results.listing())
        }
        self.assertEqual(units["moan"]["translation"], "Mm♥ Ah...")
        self.assertNotIn("translation", units["line"])
        self.assertEqual(
            units["moan"]["reviewed_sha256"],
            review_digest(sources["moan"], "Mm♥ Ah..."),
        )

    def test_a_batch_keeps_the_passing_lines_of_a_reply_and_goes_on(self):
        # One failing line failed its packed Batch request, which stopped the
        # run before its later provider jobs, and the retry paid for every
        # line of the request again.
        sources = {"line": "今日はとても良い天気ですね。", "moan": "ん♥っ…"}
        rows = [
            logical_request({"id": name, "sources": sources}, {"user": name})
            for name in ("partly", "later", "whole")
        ]
        replies = {
            "partly": {"line": "a" * 50, "moan": "Mm♥Ah"},
            # With no line that passes, the request fails, and a retry
            # sends only lines that failed.
            "whole": {"line": ".", "moan": "ん♥っ…"},
            "later": {"line": "Lovely weather today.", "moan": "Mm♥Ah"},
        }
        job, plan = self.run_record("batch", rows)
        # Two requests per provider job, so the last is sent only after the
        # first two are collected.
        plan["batch_limits"] = [2, 100000]
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)

        class Provider(BatchProvider):
            def collect(self, _identity, mapping):
                return (
                    {
                        name: {"text": json.dumps(replies[name])}
                        for name in mapping.values()
                    },
                    [],
                    {"input_tokens": 10},
                )

        provider = Provider()
        provider.ended = True
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _plan = self.store.load(job["id"])
        self.assertEqual(provider.calls, 2)
        self.assertEqual(
            {name: row["state"] for name, row in current["states"].items()},
            {"partly": "accepted", "later": "accepted", "whole": "failed"},
        )
        results = Results(self.game)
        self.assertEqual(
            results.get(rows[0])["translations"],
            {"line": sources["line"], "moan": "Mm♥Ah"},
        )
        self.assertIn(
            "Excessive character repetition", current["states"]["partly"]["message"]
        )
        # A later poll recovers the run and keeps that note.
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(
            self.store.load(job["id"])[0]["states"]["partly"],
            current["states"]["partly"],
        )

    def test_api_requests_key_lines_by_position_and_save_replies_by_unit_id(self):
        # Unit IDs can be long paths, and a request repeated each in every
        # list it held and the reply; API payloads now key lines 1 to N.
        line = "www/data/Map001.json/events/1/pages/0/list/"
        units = organize.units_input(
            {
                "version": 1,
                "units": [
                    {
                        "id": line + "3",
                        "group": "Map001",
                        "scene": "A",
                        "source": "\\C[2]行こう。",
                        "kind": "dialogue",
                        "speaker": "リリ",
                        "tokens": ["\\C[2]"],
                    },
                    {
                        "id": line + "5",
                        "group": "Map001",
                        "scene": "A",
                        "source": "夜が明けた。",
                        "kind": "narration",
                    },
                    {
                        "id": line + "9",
                        "group": "Map001",
                        "scene": "B",
                        "source": "戻る",
                        "kind": "ui",
                    },
                ],
            }
        )
        batch = organize.plan(units, "work/units.json", True, 50)["batches"][0]
        row = logical_request(
            batch, {"user": "", "scene_context": batch["scene_context"]}
        )
        configuration = {"mode": "live", "model": "fixture", "lineKeys": LINE_KEYS}
        view = provider_view(row, configuration)
        self.assertEqual(
            view["sources"], {"1": "\\C[2]行こう。", "2": "夜が明けた。", "3": "戻る"}
        )
        self.assertEqual(view["constraints"], {"1": {"tokens": ["\\C[2]"]}})
        # Only named lines are listed; kinds and scenes go by line range.
        self.assertIn("\nリリ: 1\n\n", view["user"])
        self.assertIn("dialogue 1; narration 2; ui 3", view["user"])
        self.assertTrue(view["scene_context"].endswith("\n- A: lines 1-2\n- B: line 3"))
        self.assertNotIn("www/data", view["user"] + view["scene_context"])
        # Earlier runs, and scene notes written another way, keep unit IDs.
        foreign = logical_request(batch, {"user": "", "scene_context": "At the gate"})
        for kept, policy in ((row, {}), (foreign, configuration)):
            self.assertEqual(provider_view(kept, policy)["sources"], row["sources"])
        row["params"] = {"model": "fixture", "messages": []}
        replies = iter(
            [
                '{"1": "\\\\C[2]Let\'s go.", "2": "Dawn broke.", "3": "Back"}',
                '{"1": "\\\\C[2]Let\'s go.", "2": "Dawn broke."}',
            ]
        )

        class Keyed(LiveProvider):
            def live(self, _params):
                return {"text": next(replies)}

        accepted = None
        for state in ("accepted", "failed"):
            (self.game / state).mkdir()
            # Each attempt is a game of its own.
            register(self.root / "profile", state, self.game / state)
            plan = {
                "version": 1,
                "kind": "translation",
                "source": str(self.game / state),
                "complete": True,
                "requests": [row],
                "configuration": configuration,
                "batch_limits": [50, 100000],
            }
            job = self.store.create(state, plan, {"cost": 1})
            self.store.authorize(job)
            Runner(self.store, job["id"], Keyed(), lambda: None).step()
            current, _plan = self.store.load(job["id"])
            self.assertEqual(current["states"][row["id"]]["state"], state)
            accepted = accepted or Results(self.game / state).get(row)
        self.assertEqual(
            accepted["translations"],
            {
                line + "3": "\\C[2]Let's go.",
                line + "5": "Dawn broke.",
                line + "9": "Back",
            },
        )

    def test_reviewed_correction_retains_history_and_rejects_a_stale_result_hash(self):
        row = request()
        results = Results(self.game)
        old = results.accept(row, {"line": "Yes. ⟦P0⟧"}, {})
        changed = results.correct(
            row, {"line": "Of course. ⟦P0⟧"}, old["result_sha256"], {"correction": True}
        )
        self.assertNotEqual(old["result_sha256"], changed["result_sha256"])
        self.assertNotIn("reviewed", changed)
        with self.assertRaises(ValueError):
            results.correct(row, {"line": "No. ⟦P0⟧"}, old["result_sha256"], {})
        history = list(
            (self.game / ".dazedtl/len-method/work/accepted-history").rglob("*.json")
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(
            json.loads(history[0].read_text(encoding="utf-8"))["translations"],
            old["translations"],
        )

    def test_a_receipt_of_refusal_notes_or_source_text_reads_as_not_translated(self):
        # Receipts from before 2.34.5 kept "Declined." as a translation; they
        # were exported, counted translated and never resent. So was one
        # giving every line back in its source text, as a reply kept whole is.
        refused, kept, echoed = request("refused"), request("kept"), request("echoed")
        results = Results(self.game)
        for row, text in (
            (refused, "Declined. ⟦P0⟧"),
            (kept, "Yes. ⟦P0⟧"),
            (echoed, echoed["sources"]["line"]),
        ):
            translations = {"line": text}
            write_json(
                project_path(self.game, results.relative(row), exists=False),
                {
                    "version": 1,
                    "request_sha256": row["fingerprint"],
                    "sources_sha256": digest(row["sources"]),
                    "translations": translations,
                    "result_sha256": digest(translations),
                    "provenance": {},
                },
            )
        self.assertIsNone(results.get(refused))
        self.assertIsNone(results.get(echoed))
        self.assertEqual(results.get(kept)["translations"], {"line": "Yes. ⟦P0⟧"})
        # Translating it again replaces the note and archives its receipt.
        saved = results.accept(refused, {"line": "Yes. ⟦P0⟧"}, {})
        self.assertEqual(results.get(refused), saved)
        # Source text given back is refused now, as a refusal note is.
        with self.assertRaisesRegex(ValueError, "every line is its source text"):
            results.accept(echoed, echoed["sources"], {})
        results.accept(echoed, {"line": "Yes. ⟦P0⟧"}, {})
        history = (self.game / ".dazedtl/len-method/work/accepted-history").rglob(
            "*.json"
        )
        self.assertEqual(
            sorted(
                json.loads(path.read_text(encoding="utf-8"))["translations"]["line"]
                for path in history
            ),
            ["Declined. ⟦P0⟧", "はい。⟦P0⟧"],
        )

    def test_requests_sharing_a_payload_are_sent_once_and_answered_alike(self):
        # A scene two maps repeat made two requests the provider reads the
        # same, and both were paid; Guided queues it once for both files.
        rule = {"tokens": ["⟦P0⟧"], "max_lines": 1}
        copy = logical_request(
            {
                "id": "copy",
                "sources": {"again": "はい。⟦P0⟧"},
                "constraints": {"again": rule},
            },
            {"speakers": {"again": "Lili"}},
        )
        rows = [request(), copy]
        for row in rows:
            row["params"] = {"model": "fixture", "messages": []}
        self.assertEqual(askers(rows), {"copy": "scene"})
        rejection = ValueError("Provider rejected the request")
        rejection.status_code = 400
        for mode, policy, calls in (
            ("live", SHARED_PAYLOADS, 1),
            ("batch", SHARED_PAYLOADS, 1),
            # A run frozen before the policy sends each.
            ("older", None, 2),
            # A request whose answer failed leaves its askers unsent.
            ("rejected", SHARED_PAYLOADS, 1),
        ):
            with self.subTest(mode=mode):
                game = self.game / mode
                game.mkdir()
                register(self.root / "profile", mode, game)
                plan = {
                    "version": 1,
                    "kind": "translation",
                    "source": str(game),
                    "complete": True,
                    "requests": rows,
                    "configuration": {
                        "mode": "batch" if mode == "batch" else "live",
                        "model": "fixture",
                    },
                    "batch_limits": [50, 100000],
                }
                if policy:
                    plan.update(shared_payloads=policy, askers={"copy": "scene"})
                job = self.store.create(mode, plan, {"cost": 1})
                self.store.authorize(job)
                provider = (
                    BatchProvider()
                    if mode == "batch"
                    else LiveProvider(rejection if mode == "rejected" else None)
                )
                provider.ended = True
                Runner(self.store, job["id"], provider, lambda: None).step()
                current, _plan = self.store.load(job["id"])
                self.assertEqual(provider.calls, calls)
                if mode == "rejected":
                    self.assertEqual(current["states"]["copy"]["state"], "failed")
                    self.assertIn("Not sent", current["states"]["copy"]["message"])
                    continue
                self.assertEqual(len(current["request_usage"]), calls)
                if not policy:
                    continue
                self.assertEqual(current["status"], "complete")
                self.assertEqual(
                    Results(game).get(copy)["translations"], {"again": "Yes. ⟦P0⟧"}
                )
                if mode == "batch":
                    self.assertEqual(
                        [item["request"] for item in current["batches"][0]["items"]],
                        ["scene"],
                    )

    def test_worker_owner_loss_stops_before_another_paid_request(self):
        alive = [True]
        job, _plan = self.run_record(requests=[request("one"), request("two")])
        store = RunStore(self.store.workspace, owner_alive=lambda: alive[0])

        class Provider(LiveProvider):
            def live(self, params):
                result = super().live(params)
                alive[0] = False
                return result

        provider = Provider()
        Runner(store, job["id"], provider, lambda: None).step()
        current, _plan = store.load(job["id"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["status"], "stopped")
        self.assertEqual(current["states"]["one"]["state"], "accepted")
        self.assertEqual(current["states"]["two"]["state"], "pending")

    def test_a_killed_workers_temporary_files_go_once_the_app_sees_it_gone(self):
        # A killed worker never runs its own cleanup, so every forced stop
        # during Set up left a restored copy of the game in the temp folder.
        plan = {"version": 1, "kind": "operation", "source": str(self.game)}
        stopped, held = (self.store.create("project", plan) for _ in range(2))
        self.enterContext(patch.object(tempfile, "tempdir", str(self.root)))
        for job in (stopped, held):
            restored = scratch(job["id"]) / "dazedtl-restore-1/data/System.json"
            restored.parent.mkdir(parents=True)
            restored.write_text("{}", encoding="utf-8")
            os.chmod(restored, stat.S_IREAD)
        worker = WorkspaceLock(self.store.folder(held["id"]))
        jobs = Jobs(self.store.workspace, False)
        worker.close()
        self.assertFalse(scratch(stopped["id"]).exists())
        self.assertTrue(scratch(held["id"]).exists())

        class Process:
            pid = 0
            exited = False

            def poll(self):
                return 0 if self.exited else None

        process = Process()
        with patch("subprocess.Popen", return_value=process) as launch:
            jobs.start(stopped["id"], "project")
        environment = launch.call_args.kwargs["env"]
        self.assertEqual(
            {environment[key] for key in ("TEMP", "TMP", "TMPDIR")},
            {str(scratch(stopped["id"]))},
        )
        (scratch(stopped["id"]) / "dazedtl-git-index-1").write_bytes(b"DIRC")
        process.exited = True
        jobs.reconcile()
        self.assertFalse(scratch(stopped["id"]).exists())

    def test_cancellation_retains_completed_rows_and_does_not_submit_later_chunks(self):
        job, plan = self.run_record("batch", [request("one"), request("two")])
        # One request per provider job makes the remaining-work safeguard
        # observable: the runner counts each request's tokens, and two
        # exceed the allowance.
        plan["batch_limits"] = [50, 100000, 10]
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)

        class Provider(BatchProvider):
            canceled = False

            def input_tokens(self, _params):
                return 6

            def cancel(self, _identity):
                self.canceled = True

            def status(self, identity):
                if not self.canceled:
                    return super().status(identity)
                return {
                    "ended": True,
                    "terminal_failure": True,
                    "api_status": "cancelled",
                    "counts": {},
                }

            def collect_terminal(self, identity, mapping):
                return self.collect(identity, mapping)

        provider = Provider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        write_json(self.store.folder(job["id"]) / "cancel.json", {"requested": True})
        # The worker exits once a pass leaves the run not waiting, so the pass
        # that collects the canceled job settles the later chunk too.
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _plan = self.store.load(job["id"])
        self.assertTrue(provider.canceled)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["states"]["one"]["state"], "accepted")
        self.assertEqual(current["states"]["two"]["state"], "failed")
        self.assertEqual(current["batches"][1]["state"], "canceled")
        # The chunk canceled before submission has no provider status.
        _close_contracts()
        TypeAdapter(list[TranslationBatch]).validate_json(
            json.dumps(self.store.view(current)["batches"]), strict=True
        )

    def test_agent_results_are_reused_by_api_without_another_call(self):
        row = request()
        Results(self.game).accept(row, {"line": "Yes. ⟦P0⟧"}, {"mode": "agent"})
        job, plan = self.run_record(requests=[row])
        provider = LiveProvider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(provider.calls, 0)
        self.assertEqual(self.store.load(job["id"])[0]["status"], "complete")
        _path, changed = Results(self.game).export(plan)
        self.assertTrue(changed)
        _path, changed = Results(self.game).export(plan)
        self.assertFalse(changed)

    def test_saved_response_recovers_without_rebilling_after_an_interruption(self):
        job, plan = self.run_record()
        job["states"]["scene"]["state"] = "sending"
        self.store.save(job)
        provider = LiveProvider()
        runner = Runner(self.store, job["id"], provider, lambda: None)
        write_json(runner.response_path("scene"), {"text": '{"line":"Yes. ⟦P0⟧"}'})
        runner.step()
        self.assertEqual(provider.calls, 0)
        self.assertIsNotNone(Results(self.game).get(plan["requests"][0]))
        self.assertEqual(self.store.load(job["id"])[0]["status"], "complete")

    def test_failed_or_uncertain_live_call_is_never_retried_implicitly(self):
        rejection = ValueError("Provider rejected the request")
        rejection.status_code = 404
        for error, status in ((TimeoutError(), "uncertain"), (rejection, "failed")):
            with self.subTest(status=status):
                job, plan = self.run_record(requests=[request(speaker=status)])
                provider = LiveProvider(error)
                Runner(self.store, job["id"], provider, lambda: None).step()
                current, _plan = self.store.load(job["id"])
                self.assertEqual(current["status"], status)
                # Reading a retired terminal label must keep the receipt and
                # request state authoritative, including the duplicate guard.
                current["status"] = "retired_status"
                self.store.save(current)
                before = (self.store.folder(job["id"]) / "job.json").read_bytes()
                self.assertEqual(self.store.view(current)["status"], "failed")
                self.assertEqual(
                    (self.store.folder(job["id"]) / "job.json").read_bytes(), before
                )
                Runner(self.store, job["id"], provider, lambda: None).step()
                self.assertEqual(provider.calls, 1)
                self.assertEqual(self.store.load(job["id"])[0]["status"], status)
                if status == "uncertain":
                    with self.assertRaises(ValueError):
                        self.store.overlapping(
                            "project", {plan["requests"][0]["fingerprint"]}
                        )

    def test_refusal_clarification_is_bounded_and_retains_both_paid_attempts(self):
        # A refusal in valid JSON used to pass output validation, and so did a
        # note in place of a line. A repeated refusal or lost retry response
        # must not become dialogue or another bill.
        from dazedtl.translation.refusals import CLARIFICATION, POLICY, refused

        refusal = {
            "text": '{"line":"Translation declined. ⟦P0⟧"}',
            "prompt_tokens": 7,
            "completion_tokens": 3,
        }
        valid = {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }
        for index, outcome in enumerate((valid, refusal, TimeoutError())):
            with self.subTest(outcome=outcome):
                job, plan = self.run_record(requests=[request(speaker=str(index))])
                plan["configuration"]["refusalRetry"] = POLICY
                write_json(self.store.folder(job["id"]) / "plan.json", plan)
                job["plan_sha256"] = digest(plan)
                self.store.save(job)
                calls = []

                class Provider:
                    def live(self, params):
                        calls.append(deepcopy(params))
                        if len(calls) == 1:
                            return refusal
                        if isinstance(outcome, Exception):
                            raise outcome
                        return outcome

                provider = Provider()
                Runner(self.store, job["id"], provider, lambda: None).step()
                Runner(self.store, job["id"], provider, lambda: None).step()
                current, frozen = self.store.load(job["id"])
                self.assertEqual(len(calls), 2)
                self.assertEqual(
                    calls[1]["messages"], [{"role": "user", "content": CLARIFICATION}]
                )
                self.assertEqual(frozen, plan)
                self.assertEqual(
                    current["states"]["scene"]["state"],
                    "uncertain"
                    if isinstance(outcome, Exception)
                    else "failed"
                    if outcome == refusal
                    else "accepted",
                )
                self.assertEqual(
                    current["usage"]["input_tokens"],
                    7
                    if isinstance(outcome, Exception)
                    else 7 + outcome["prompt_tokens"],
                )
                self.assertEqual(
                    current["usage"]["output_tokens"],
                    3
                    if isinstance(outcome, Exception)
                    else 3 + outcome["completion_tokens"],
                )
                self.assertEqual(
                    Results(self.game).get(plan["requests"][0]) is not None,
                    outcome == valid,
                )
        self.assertFalse(
            refused({"text": '{"line":"I refuse. Sorry, I cannot help you."}'})
        )
        self.assertFalse(
            refused(
                {"text": '{"line":"I cannot translate explicit sexual content."}'},
                ["I cannot translate explicit sexual content."],
            )
        )
        for text in (
            "I'm unable to translate graphic content.",
            "I can't help with sexually explicit content.",
            "I'm sorry, but I cannot assist with this request.",
        ):
            self.assertTrue(refused({"text": text}), text)
        # A note in or in place of one line is a refusal of the whole reply,
        # unless that line's own source explains it.
        sources = {"Line1": "はい。", "Line2": "（中略）"}
        for lines, expected in (
            ({"Line1": "Yes.", "Line2": "[Not\ntranslated: sexual content]"}, True),
            ({"Line1": "Yes. \\C[27][omitted]\\C[0]", "Line2": "(Omitted)"}, True),
            ({"Line1": "I can't help it...", "Line2": "(Omitted)"}, False),
        ):
            text = json.dumps(lines)
            self.assertEqual(refused({"text": text}, sources), expected, text)
        # The model talking about its task in any sentence shape is a
        # refusal, unless the line's source talks about the same thing.
        from dazedtl.translation.refusals import line_refusal

        moan = "あっ、んっ……そこ、だめぇ……！"
        for text, source, expected in (
            (
                (
                    "I won't produce sexual content\ninvolving a character who "
                    "reads as a\nminor, even in translation."
                ),
                moan,
                True,
            ),
            ("Send another batch and I'll\ncontinue.", moan, True),
            (
                "I can translate adult scenes where every participant is adult.",
                moan,
                True,
            ),
            ("Declined.", moan, True),
            ("I can't help with this. It is explicit sexual content.", moan, True),
            ("I'm sorry, but I can't help with this request.", "お願い！", True),
            ("I'll continue the mission a little longer.", "任務を継続する。", False),
            ("I'm wasting this batch just to mess with you.", "嫌がらせ用だ。", False),
            ("I'll continue with the next batch of potions.", "次の分を作る。", False),
            ("I can't stand such lewd material!", "こんなエロ本……！", False),
            ("I can't translate this inscription.", "この碑文は翻訳できない。", False),
            ("I can't help with your request.", "その依頼は受けられない。", False),
            ("Declined.", "断られた。", False),
            # A model that refuses in the target language says the same in
            # it: Chinese for a Japanese game, Japanese for an English one.
            ("抱歉，我无法翻译这段内容。", moan, True),
            ("很抱歉，我不能提供涉及未成年人的色情内容。", moan, True),
            ("请发送下一批，我会继续翻译。", moan, True),
            ("【未翻译：色情内容】", moan, True),
            ("申し訳ありませんが、この内容は翻訳できません。", "Ahh...!", True),
            ("次のバッチを送ってください。続きを翻訳します。", "Ahh...!", True),
            ("我无法翻译这块碑文。", "この碑文は翻訳できない。", False),
            ("我不能再继续了……", "もう続けられない……", False),
            ("我不能接受你的要求！", "その要求は呑めない！", False),
            ("这批药水我不能卖给你。", "この薬は売れない。", False),
            ("我们接着走下一段路吧。", "次の道を進もう。", False),
            ("我不能帮助未成年人买酒。", "未成年に酒は売れない。", False),
            ("私人物品不能翻译给你看。", "個人の物だから見せられない。", False),
            ("この碑文は翻訳できない。", "I can't translate this inscription.", False),
            (
                "申し訳ありませんが、そのご依頼はお受けできません。",
                "Sorry, but I can't take that job.",
                False,
            ),
            ("私はこんな内容の本は書けません！", "I can't write such content!", False),
        ):
            self.assertEqual(line_refusal(text, source), expected, text)

    def test_saved_refusal_notes_get_their_source_back(self):
        from dazedtl.translation.saved_refusals import find, restore

        def command(code, parameters, original=None):
            value = {"code": code, "indent": 0, "parameters": parameters}
            return value if original is None else {**value, "_original": original}

        def game(name, commands):
            page = {"list": [*commands, command(0, [])]}
            return {"events": [None, {"id": 1, "name": name, "pages": [page]}]}

        saved = game(
            "[Not_translated]",
            [
                command(101, ["", 0, 0, 2, "[Not translated]"], "小町"),
                command(
                    401, ["Yes...\n[Not translated: sexual content]"], "はい…\n続き"
                ),
                # A message keeps every row its translation was laid over.
                command(401, ["(Not translated)"], "一行目\n二行目\n三行目"),
                command(401, ["second line"]),
                command(405, ["(Line left untranslated)"], "一行目\n二行目"),
                command(405, ["second line"]),
                command(405, ["third line"]),
                command(102, [["Go", "[Omitted]"], -1, 0, 1, 0], ["行く", "えっち"]),
                # The source explains this note, so it is a translation.
                command(102, [["(Omitted)"], -1, 0, 1, 0], ["（中略）"]),
                command(122, [1, 1, 0, 4, '"[Not translated]"'], "名前"),
                # Nothing records this line's source.
                command(401, ["[Not translated]"]),
            ],
        )
        original = game("ちん嗅ぎ", [])
        self.assertEqual(restore(saved, lambda: original), 7)
        self.assertEqual(
            saved,
            game(
                "ちん嗅ぎ",
                [
                    command(101, ["", 0, 0, 2, "小町"], "小町"),
                    command(401, ["はい…\n続き"], "はい…\n続き"),
                    command(401, ["一行目"], "一行目\n二行目\n三行目"),
                    command(401, ["二行目\n三行目"]),
                    command(405, ["一行目"], "一行目\n二行目"),
                    command(405, ["二行目"]),
                    command(405, [""]),
                    command(102, [["Go", "えっち"], -1, 0, 1, 0], ["行く", "えっち"]),
                    command(102, [["(Omitted)"], -1, 0, 1, 0], ["（中略）"]),
                    command(122, [1, 1, 0, 4, '"名前"'], "名前"),
                    command(401, ["[Not translated]"]),
                ],
            ),
        )
        self.assertEqual(find(saved, lambda: original), [])

        def unread():
            raise AssertionError("the original file was read")

        # Database fields keep their source in `_original`, and a file whose
        # other values hold no note never reads the original game file.
        items = [None, {"id": 1, "name": "[Omitted]", "_original": {"name": "薬"}}]
        self.assertEqual(restore(items, unread), 1)
        self.assertEqual(items[1]["name"], "薬")

        # A choice's help translated before translation recorded its rows
        # gets them recorded from the original game file, so the next run
        # writes over its own rows and not the game's "(1/3)".
        def helped(*rows):
            return game(
                "x", [command(402, [0, "Go"]), command(108, ["選択肢ヘルプ"]), *rows]
            )

        original_help = helped(
            command(408, ["所要時間:20分"]),
            command(408, ["(1/3)"]),
            command(408, ["二行目"]),
        )
        saved_help = helped(
            command(408, ["[Not translated: sexual"], "所要時間:20分"),
            command(408, ["content]"]),
            command(408, ["(1/3)"]),
            command(408, ["Line two."], "二行目"),
        )
        self.assertEqual(restore(saved_help, lambda: original_help), 1)
        rows = saved_help["events"][1]["pages"][0]["list"][2:6]
        self.assertEqual(
            [row["parameters"][0] for row in rows],
            ["所要時間:20分", "content]", "(1/3)", "Line two."],
        )
        self.assertEqual(rows[0]["_rows"], 2)

    def test_batch_wait_resume_and_unordered_collection_keep_one_submission(self):
        job, plan = self.run_record(
            "batch", [request("one"), request("two"), request("three")]
        )
        provider = BatchProvider()

        # Approval leaves comparing the compiled requests to the worker, so a
        # plan whose guidance changed since its estimate must send nothing.
        def stale():
            raise ValueError("Shared guidance changed.")

        with self.assertRaisesRegex(ValueError, "guidance changed"):
            Runner(self.store, job["id"], provider, stale).step()
        self.assertEqual(provider.calls, 0)
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(self.store.load(job["id"])[0]["status"], "waiting")
        Runner(self.store, job["id"], provider, lambda: None).step()
        provider.ended = True
        # A collection does not rewrite its record per response. Interrupted
        # between acceptances, it resumes from the saved responses and
        # results and collects the same provider job again.
        accept = Results.accept

        def interrupted(results, request, *args):
            if request["id"] == "two":
                raise KeyboardInterrupt
            return accept(results, request, *args)

        with (
            patch("dazedtl.translation.runner.SAVE_INTERVAL", 3600),
            patch.object(Results, "accept", interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(
            {row["state"] for row in self.store.load(job["id"])[0]["states"].values()},
            {"queued"},
        )
        Runner(self.store, job["id"], provider, lambda: None).step()
        current = self.store.load(job["id"])[0]
        self.assertEqual(provider.calls, 1)
        self.assertEqual(current["status"], "complete")
        self.assertEqual(current["usage"], {"input_tokens": 10})
        self.assertTrue(all(Results(self.game).get(row) for row in plan["requests"]))

    def test_google_structured_batches_split_before_submission_and_keep_saved_groups(
        self,
    ):
        # Google rejects different response schemas in one Batch. Splitting
        # must retain ownership and leave matching schemas together on resume.
        from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS
        from dazedtl.translation.requests import output_schema

        rows = [
            logical_request(
                {"id": key, "sources": {"line" if index == 0 else "other": "薬"}}, {}
            )
            for index, key in enumerate(("one", "two", "three"))
        ]
        for row in rows:
            row["params"] = {
                "model": "google/fixture",
                "messages": [],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "translation",
                        "strict": True,
                        "schema": output_schema(row["sources"]),
                    },
                },
            }
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "complete": True,
            "requests": rows,
            "configuration": {
                "mode": "batch",
                "model": "google/fixture",
                "openrouterStructuredOutputs": STRUCTURED_OUTPUTS,
            },
            "batch_limits": [50, 100000],
        }
        job = self.store.create("project", plan, {"cost": 1})
        self.store.authorize(job)
        provider = BatchProvider()
        for _ in range(2):
            Runner(self.store, job["id"], provider, lambda: None).step()
        current, _ = self.store.load(job["id"])
        self.assertEqual(
            [
                [item["request"] for item in chunk["items"]]
                for chunk in current["batches"]
            ],
            [["one"], ["two", "three"]],
        )
        self.assertEqual(provider.calls, 1)

    def test_batch_refusals_retry_only_rejected_rows_in_batch_and_keep_original_usage(
        self,
    ):
        # A Batch refusal must not become a Live call, resend successful rows,
        # or reset its retry allowance when polling resumes in another worker.
        # Its journal keeps the original responses, so an interruption before
        # their acceptance loses none and the original job is collected once.
        from dazedtl.translation.refusals import CLARIFICATION, POLICY

        refusal = {
            "text": "I cannot translate explicit sexual content.",
            "prompt_tokens": 3,
            "completion_tokens": 2,
        }
        valid = {
            "text": '{"line":"Yes. ⟦P0⟧"}',
            "prompt_tokens": 5,
            "completion_tokens": 4,
        }
        for repeated in (False, True):
            job, plan = self.run_record(
                "batch",
                [request("good", str(repeated)), request("refused", str(repeated))],
            )
            plan["configuration"]["refusalRetry"] = POLICY
            write_json(self.store.folder(job["id"]) / "plan.json", plan)
            job["plan_sha256"] = digest(plan)
            self.store.save(job)

            collected = []

            class Provider(BatchProvider):
                def submit(self, items):
                    super().submit(items)
                    return {"id": "original" if self.calls == 1 else "clarification"}

                def collect(self, identity, mapping):
                    collected.append(identity)
                    return (
                        {
                            key: (
                                refusal
                                if key == "refused"
                                and (identity == "original" or repeated)
                                else valid
                            )
                            for key in mapping.values()
                        },
                        [],
                        {
                            "input_tokens": 8
                            if identity == "original"
                            else 3
                            if repeated
                            else 5,
                            "output_tokens": 6
                            if identity == "original"
                            else 2
                            if repeated
                            else 4,
                        },
                    )

            provider = Provider()
            provider.ended = True
            accept = Runner.accept

            def interrupted(runner, identity, response):
                if identity == "good":
                    raise KeyboardInterrupt
                accept(runner, identity, response)

            with (
                patch.object(Runner, "accept", interrupted),
                self.assertRaises(KeyboardInterrupt),
            ):
                Runner(self.store, job["id"], provider, lambda: None).step()
            self.assertEqual(len(provider.items), 1)
            self.assertEqual(
                provider.items[0]["params"]["messages"],
                [{"role": "user", "content": CLARIFICATION}],
            )
            provider.ended = False
            Runner(self.store, job["id"], provider, lambda: None).step()
            current, _ = self.store.load(job["id"])
            self.assertEqual(current["status"], "waiting")
            self.assertEqual(current["states"]["good"]["state"], "accepted")
            provider.ended = True
            Runner(self.store, job["id"], provider, lambda: None).step()
            Runner(self.store, job["id"], provider, lambda: None).step()
            current, frozen = self.store.load(job["id"])
            self.assertEqual(provider.calls, 2)
            self.assertEqual(collected, ["original", "clarification"])
            self.assertEqual(frozen, plan)
            self.assertEqual(
                current["states"]["refused"]["state"],
                "failed" if repeated else "accepted",
            )
            self.assertEqual(current["usage"]["input_tokens"], 11 if repeated else 13)
            self.assertEqual(current["usage"]["output_tokens"], 8 if repeated else 10)
        # An upload/create timeout may still have created a remote Batch. A
        # restarted worker must retain uncertainty instead of creating another.
        job, plan = self.run_record("batch", [request("refused", "lost-batch")])
        plan["configuration"]["refusalRetry"] = POLICY
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)

        class LostProvider(Provider):
            def submit(self, items):
                result = super().submit(items)
                if self.calls == 2:
                    raise TimeoutError()
                return result

        provider = LostProvider()
        provider.ended = True
        with self.assertRaises(TimeoutError):
            Runner(self.store, job["id"], provider, lambda: None).step()
        Runner(self.store, job["id"], provider, lambda: None).step()
        self.assertEqual(provider.calls, 2)
        self.assertEqual(self.store.load(job["id"])[0]["status"], "uncertain")

    def test_cancel_during_batch_clarification_cancels_it_and_keeps_its_results(
        self,
    ):
        # Cancelling while a clarification waits must cancel that Batch once,
        # not the ended original, submit nothing more, and keep the rows and
        # usage the provider finished before it stopped.
        from dazedtl.translation.batch_refusals import journal
        from dazedtl.translation.refusals import POLICY

        job, plan = self.run_record(
            "batch",
            [request("good"), request("first"), request("second"), request("later")],
        )
        plan["configuration"]["refusalRetry"] = POLICY
        # Each clarification fills a provider job's token allowance, so the
        # second waits for the first; the last request waits in a later chunk.
        plan["batch_limits"] = [3, 100000, 10]
        for row in plan["requests"]:
            row["input_tokens"] = 3
        write_json(self.store.folder(job["id"]) / "plan.json", plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)
        valid = {"text": '{"line":"Yes. ⟦P0⟧"}'}

        class Provider(BatchProvider):
            def __init__(self):
                super().__init__()
                self.canceled, self.collected, self.stopped = [], [], False

            def input_tokens(self, _params):
                return 10

            def submit(self, items):
                super().submit(items)
                return {"id": "original" if self.calls == 1 else "clarification"}

            def cancel(self, identity):
                self.canceled.append(identity)

            def status(self, identity):
                ended = identity == "original" or self.stopped
                return {
                    "ended": ended,
                    "terminal_failure": identity != "original" and ended,
                    "api_status": "cancelled"
                    if self.stopped
                    else "completed"
                    if ended
                    else "in_progress",
                    "counts": {},
                }

            def collect(self, identity, mapping):
                self.collected.append(identity)
                return (
                    {
                        key: valid
                        if key == "good"
                        else {"text": "I cannot translate explicit sexual content."}
                        for key in mapping.values()
                    },
                    [],
                    {"input_tokens": 8, "output_tokens": 6},
                )

            def collect_terminal(self, identity, mapping):
                self.collected.append(identity)
                return (
                    {key: valid for key in mapping.values()},
                    [],
                    {"input_tokens": 5, "output_tokens": 4},
                )

        provider = Provider()
        Runner(self.store, job["id"], provider, lambda: None).step()
        write_json(self.store.folder(job["id"]) / "cancel.json", {"requested": True})
        # A restarted worker does not ask the provider again.
        for _ in range(2):
            Runner(self.store, job["id"], provider, lambda: None).step()
        current, _ = self.store.load(job["id"])
        self.assertEqual(current["status"], "waiting")
        self.assertEqual(provider.canceled, ["clarification"])
        provider.stopped = True
        Runner(self.store, job["id"], provider, lambda: None).step()
        current, _ = self.store.load(job["id"])
        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.canceled, ["clarification"])
        self.assertEqual(provider.collected, ["original", "clarification"])
        self.assertEqual(
            {key: value["state"] for key, value in current["states"].items()},
            {
                "good": "accepted",
                "first": "accepted",
                "second": "failed",
                "later": "failed",
            },
        )
        # Inspect opens a failure by its position in the plan.
        self.assertEqual(
            [
                (issue["id"], issue["index"])
                for issue in self.store.view(current)["issues"]
            ],
            [("second", 2), ("later", 3)],
        )
        self.assertEqual(current["usage"]["input_tokens"], 13)
        self.assertEqual(current["usage"]["output_tokens"], 10)
        self.assertEqual(current["status"], "failed")
        self.assertTrue(current["message"].startswith("Canceled."))
        record = json.loads(
            journal(self.store.folder(job["id"]), "original").read_bytes()
        )
        self.assertEqual(
            [batch["state"] for batch in record["batches"]], ["complete", "failed"]
        )

    def test_clarification_journal_keeps_its_scope_and_continues_earlier_records(
        self,
    ):
        # The journal sends only its saved clarified payloads, so a changed
        # request or Batch must stop it. A record from before version 2, which
        # kept every original request, must still continue its run.
        from contextlib import nullcontext

        from dazedtl.translation.batch_refusals import advance, journal

        def send(*args):
            return advance(*args, reserve=lambda _items: nullcontext(True))

        requests = {
            "good": {
                "model": "fixture",
                "messages": [{"role": "user", "content": "a"}],
            },
            "refused": {
                "model": "fixture",
                "messages": [{"role": "user", "content": "b"}],
            },
        }
        responses = {
            "good": {"text": '{"line":"Yes."}'},
            "refused": {"text": "I cannot translate explicit sexual content."},
        }

        class Provider:
            def submit(self, _items):
                return {"id": "clarification"}

            def status(self, _identity):
                return {"ended": False, "api_status": "running", "counts": {}}

        send(self.root, "original", requests, responses, {}, Provider())
        path = journal(self.root, "original")
        record = json.loads(path.read_bytes())
        self.assertNotIn("requests", record)
        changed = {**requests, "refused": {**requests["refused"], "model": "other"}}
        for version in (2, None):
            with self.subTest(version=version):
                waiting = send(self.root, "original", requests, None, None, Provider())
                self.assertEqual(waiting["responses"], responses)
                for other in (changed, {"good": requests["good"]}):
                    with self.assertRaises(ValueError):
                        send(self.root, "original", other, None, None, Provider())
            # The same journal as an earlier version wrote it.
            record = {
                key: value
                for key, value in record.items()
                if key not in {"version", "keys"}
            }
            write_json(path, {**record, "requests": requests})

    def test_unknown_batch_submission_and_wrong_job_results_stay_blocked(self):
        for failure in (True, False):
            with self.subTest(submission_failure=failure):
                job, plan = self.run_record(
                    "batch", [request("failure" if failure else "wrong-job")]
                )
                provider = BatchProvider(TimeoutError() if failure else None)
                provider.ended = True
                provider.unrelated = not failure
                Runner(self.store, job["id"], provider, lambda: None).step()
                Runner(self.store, job["id"], provider, lambda: None).step()
                self.assertEqual(provider.calls, 1)
                self.assertEqual(self.store.load(job["id"])[0]["status"], "uncertain")
                self.assertIsNone(Results(self.game).get(plan["requests"][0]))

    def test_approval_binds_project_plan_and_quote_and_boolean_is_insufficient(self):
        job, plan = self.run_record()
        self.assertTrue(self.store.authorized(job))
        with self.assertRaises(ValueError):
            self.store.load(job["id"], "another-project")
        modified = deepcopy(job)
        modified["quote"]["cost"] = 0
        self.assertFalse(self.store.authorized(modified))
        (self.store.folder(job["id"]) / "authorization.json").unlink()
        self.assertTrue(job["approved"])
        self.assertFalse(self.store.authorized(job))
        path = self.store.folder(job["id"]) / "plan.json"
        saved = path.read_bytes()
        path.write_bytes(saved.replace("はい。".encode(), "いいえ".encode()))
        with self.assertRaises(ValueError):
            self.store.load(job["id"])
        # Plans saved whole, before shared guidance, stay bound by their digest.
        write_json(path, plan)
        job["plan_sha256"] = digest(plan)
        self.store.save(job)
        self.assertEqual(self.store.load(job["id"])[1], plan)
        write_json(path, {**plan, "complete": False})
        with self.assertRaises(ValueError):
            self.store.load(job["id"])

    def test_saved_plans_hold_repeated_guidance_once_and_read_back_exactly(self):
        # Each request of a large game held the system prompt in its context
        # and again in its payload: 2,648 requests made a 165 MB plan.
        system = "Keep every speaker's voice. " * 50
        rows = []
        for index in range(3):
            user = f"Translate scene {index}. " * 60
            row = logical_request(
                {"id": f"scene-{index}", "sources": {"line": "はい。"}},
                {"system": system, "user": user, "glossary": "リリ = Lili"},
            )
            row["params"] = {
                # OpenAI-compatible routes join the system blocks into one
                # string; Anthropic sends the shared one as its own block.
                "system": [{"type": "text", "text": f"```\n{system}\n```"}],
                "messages": [
                    {"role": "system", "content": f"```\n{system}\n```\n\nリリ = Lili"},
                    {"role": "user", "content": f"```\n{user}\n```"},
                ],
            }
            rows.append(row)
        plan = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "complete": True,
            "requests": rows,
            "configuration": {"mode": "batch", "model": "fixture"},
            "batch_limits": [50, 100000],
        }
        job = self.store.create("project", plan, {"cost": 1})
        saved = (self.store.folder(job["id"]) / "plan.json").read_bytes()
        for text in (system, rows[0]["context"]["user"]):
            self.assertEqual(saved.count(text.encode()), 1)
        # The provider receives exactly the payload bytes that were approved.
        self.assertEqual(
            json.dumps(self.store.load(job["id"])[1], ensure_ascii=False),
            json.dumps(
                {**jobs.stored(plan), "source": plan["source"]}, ensure_ascii=False
            ),
        )
        # The plan names no game folder: a moved game's approved run reads
        # its game where the project list says it is now, still approved.
        self.assertNotIn(str(self.game).encode(), saved)
        self.store.authorize(job)
        moved = self.root / "moved"
        register(self.root / "profile", "project", moved)
        job, loaded = self.store.load(job["id"])
        self.assertEqual(loaded["source"], str(moved))
        self.assertTrue(self.store.authorized(job))

    def test_stale_sources_stop_before_any_provider_call(self):
        job, _plan = self.run_record()
        provider = LiveProvider()

        def stale():
            raise ValueError("Sources changed")

        with self.assertRaisesRegex(ValueError, "Sources changed"):
            Runner(self.store, job["id"], provider, stale).step()
        self.assertEqual(provider.calls, 0)

    def test_older_operation_indexes_gain_action_identity_without_rewriting_the_frozen_plan(
        self,
    ):
        plan = {
            "version": 1,
            "kind": "operation",
            "action": "backup_source",
            "source": str(self.game),
            "label": "Preserve source",
        }
        job = self.store.create("project", plan)
        del job["action"]
        self.store.save(job)
        updated = job["updated"]
        plan_path = self.store.folder(job["id"]) / "plan.json"
        before = plan_path.read_bytes()
        restored = self.store.record(job["id"])
        self.assertEqual(self.store.view(restored)["action"], "backup_source")
        self.assertEqual(restored["updated"], updated)
        self.assertEqual(plan_path.read_bytes(), before)
        del restored["action"]
        self.store.save(restored)
        write_json(plan_path, {**plan, "action": "package"})
        with self.assertRaises(ValueError):
            self.store.record(job["id"])

    def test_portable_options_import_without_replacing_legacy_or_stale_edits(self):
        legacy = self.game / ".dazedtl/len-method/project.json"
        write_json(
            legacy,
            {
                "version": 3,
                "mode": "api",
                "include_images": False,
                "instructions": "Keep this",
                "install_forge": False,
            },
        )
        original = legacy.read_bytes()
        project = ProjectWorkspace(self.game)
        value = project.read()
        self.assertEqual(value["options"]["mode"], "batch")
        saved = project.save(value["revision"], {**value["options"], "mode": "live"})
        with self.assertRaises(ValueError):
            project.save(value["revision"], value["options"])
        self.assertEqual(project.read(), saved)
        self.assertEqual(legacy.read_bytes(), original)
        # Options saved before the investigation choice existed still open,
        # and their saved runs keep the scope their quotes were bound to.
        older = {
            "mode": "batch",
            "instructions": "Keep this",
            "include_images": False,
            "include_glossary_base": True,
            "install_forge": False,
        }
        write_json(project.path, {"version": 1, "options": older})
        value = project.read()
        self.assertFalse(value["options"]["thorough_investigation"])
        bound = digest({k: v for k, v in older.items() if k != "mode"})
        self.assertEqual(scope(value["options"]), bound)
        self.assertEqual(
            scope({**value["options"], "thorough_investigation": True}), bound
        )

    def test_project_paths_and_plan_constraints_reject_unsafe_inputs(self):
        for relative in (
            "../outside.json",
            ".git/config",
            str(self.root / "outside.json"),
        ):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                project_path(self.game, relative, exists=False)
        plan = {
            "version": 2,
            "complete": True,
            "inputs": ["source.json"],
            "batches": [
                {
                    "id": "one",
                    "sources": {"line": "はい。"},
                    "kinds": {"line": "dialogue"},
                    "speakers": {"other": None},
                }
            ],
        }
        with self.assertRaises(ValueError):
            plan_input(plan)
        plan["batches"][0]["speakers"] = {"line": None}
        self.assertEqual(plan_input(plan), plan)

    def test_line_classification_requires_explicit_speakers_but_unknown_is_valid(self):
        batch = {
            "id": "scene",
            "sources": {
                "dialogue": "行った。",
                "narration": "夜が明けた。",
                "ui": "戻る",
                "other": "……",
            },
            "kinds": {
                "dialogue": "dialogue",
                "narration": "narration",
                "ui": "ui",
                "other": "unknown",
            },
            "speakers": {
                "dialogue": None,
                "narration": None,
                "ui": None,
                "other": None,
            },
        }
        plan = {
            "version": 2,
            "complete": True,
            "inputs": ["source.json"],
            "batches": [batch],
        }
        self.assertEqual(plan_input(plan), plan)
        original = {"user": "Japanese source", "request_sha256": "before"}
        row = logical_request(batch, original)
        self.assertEqual(
            original, {"user": "Japanese source", "request_sha256": "before"}
        )
        self.assertEqual(row["context"]["speakers"]["dialogue"], None)
        self.assertEqual(row["context"]["qa_notes"], {})
        job, _plan = self.run_record(requests=[row])
        self.assertEqual(self.store.view(job)["qa_requests"], [])
        for update in (
            {"speakers": None},
            {"speakers": {}},
            {"speakers": {**batch["speakers"], "dialogue": " "}},
            {"speakers": {**batch["speakers"], "ui": "Lili"}},
            {"kinds": {}},
            {"kinds": {**batch["kinds"], "ui": "guess"}},
            {"qa_notes": {"missing": "Who left?"}},
            {"qa_notes": {"dialogue": " "}},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                plan_input({**plan, "batches": [{**batch, **update}]})
        for field in ("kinds", "speakers"):
            with self.subTest(missing=field), self.assertRaises(ValueError):
                plan_input(
                    {
                        **plan,
                        "batches": [
                            {key: value for key, value in batch.items() if key != field}
                        ],
                    }
                )
        classified = logical_request(
            {**batch, "kinds": {**batch["kinds"], "other": "dialogue"}}, original
        )
        flagged = logical_request(
            {**batch, "qa_notes": {"dialogue": "Check who left."}}, original
        )
        self.assertNotEqual(row["fingerprint"], classified["fingerprint"])
        self.assertNotEqual(row["fingerprint"], flagged["fingerprint"])

    def test_organized_plan_packs_whole_scenes_and_splits_large_ones_with_context(
        self,
    ):
        def unit(identity, scene, **values):
            return {"id": identity, "scene": scene, "source": identity + "。", **values}

        units = organize.units_input(
            {
                "version": 1,
                "units": [
                    unit("a1", "A", group="Map", kind="dialogue", speaker="リリ"),
                    unit("a2", "A", group="Map", tokens=["。"], max_lines=2),
                    unit("b1", "B", group="Map"),
                    *(
                        unit(f"c{n}", "C", group="Map", speaker="ゴウ")
                        for n in range(5)
                    ),
                    unit("d1", "Items", kind="ui", field="database.item"),
                ],
            }
        )
        value = organize.plan(units, "work/source-units.json", False, 4)
        self.assertEqual(plan_input(value), value)
        self.assertEqual(value["inputs"], ["work/source-units.json"])
        batches = {batch["id"]: batch for batch in value["batches"]}
        # Whole small scenes of one group share a request; a scene over the
        # limit splits evenly, and later parts carry its earlier lines.
        self.assertEqual(list(batches), ["a1", "c0", "c3", "d1"])
        self.assertEqual(list(batches["a1"]["sources"]), ["a1", "a2", "b1"])
        self.assertEqual(len(batches["c0"]["sources"]), 3)
        self.assertNotIn("source_context", batches["c0"])
        # Packed scenes are named, so the model keeps their context apart.
        self.assertIn(
            "- A: 2 lines, a1 to a2\n- B: 1 line, b1 to b1",
            batches["a1"]["scene_context"],
        )
        self.assertNotIn("scene_context", batches["c3"])
        self.assertEqual(
            batches["c3"]["source_context"], "ゴウ: c0。\nゴウ: c1。\nゴウ: c2。"
        )
        self.assertEqual(batches["a1"]["kinds"]["a1"], "dialogue")
        self.assertEqual(batches["a1"]["kinds"]["b1"], "unknown")
        self.assertEqual(
            batches["a1"]["speakers"], {"a1": "リリ", "a2": None, "b1": None}
        )
        self.assertEqual(
            batches["a1"]["constraints"], {"a2": {"tokens": ["。"], "max_lines": 2}}
        )
        self.assertEqual(batches["d1"]["instruction_key"], "database.item")
        self.assertNotIn("instruction_key", batches["a1"])
        # The same units always give the same plan and plan file.
        again = organize.plan(units, "work/source-units.json", False, 4)
        self.assertEqual(organize.plan_path(again), organize.plan_path(value))
        # Only short scenes share a request when shared is set, so a
        # conversation never takes another scene's speakers and subjects.
        for shared, expected in ((None, [8, 1]), (2, [3, 5, 1])):
            larger = organize.plan(
                units, "work/source-units.json", False, 50, shared=shared
            )
            self.assertEqual([len(b["sources"]) for b in larger["batches"]], expected)
        summary = organize.summary(units, value)
        self.assertEqual(
            (summary["units"], summary["requests"], summary["scenes"]), (9, 4, 4)
        )

    def test_organizing_rejects_units_by_id_without_repeating_game_text(self):
        valid = {"id": "one", "scene": "A", "source": "秘密の台詞"}
        for units, named in (
            ([valid, {**valid}], "one"),
            ([{**valid, "tokens": ["\\C[9]"]}], "one"),
            ([{**valid, "kind": "ui", "speaker": "リリ"}], "one"),
            ([{**valid, "kind": "guess"}], "one"),
            ([{**valid, "source": " "}], "one"),
            (
                [valid, {**valid, "id": "two", "scene": "B"}, {**valid, "id": "3"}],
                "A",
            ),
            (
                [valid, {**valid, "id": "two", "field": "database.item"}],
                "A",
            ),
        ):
            with self.subTest(units=units):
                with self.assertRaises(ValueError) as caught:
                    organize.units_input({"version": 1, "units": units})
                self.assertIn(named, str(caught.exception))
                self.assertNotIn("秘密", str(caught.exception))
