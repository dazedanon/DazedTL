"""Hangs and worker crashes leave a record of where they happened, without
flooding the report or copying what the error said."""

import json
import os
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.diagnostics import FOLDER, Diagnostics
from dazedtl.watchdog import Watchdog

from tests.probe import Background, bytecode

ROOT = Path(__file__).resolve().parents[1]


class HangTests(unittest.TestCase):
    def test_a_stall_records_where_it_waits_and_its_resumption_within_the_limit(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        diagnostics = Diagnostics(temporary.name, ROOT, ROOT / "backend/dazedtl/engine")
        self.addCleanup(diagnostics.close)
        stalled, never = threading.Event(), threading.Event()

        def report(state, request, seconds, frame):
            diagnostics.hang(
                "backend." + state,
                seconds,
                diagnostics.stack(frame),
                operation=request[0],
                request_id=request[1],
            )
            if state == "stalled":
                stalled.set()

        watchdog = Watchdog(0.02, report, limit=1)

        def blocked(event, seconds):
            event.wait(seconds)

        watchdog.busy(("guided_preview", 7))
        # Waits until the stall is reported.
        blocked(stalled, 10)
        watchdog.beat()
        # A second quiet period of the same work is past its report limit.
        blocked(never, 0.12)
        watchdog.idle()

        records = [
            json.loads(line)
            for line in (Path(temporary.name) / "backend-failures.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(
            [
                (record["event"], record["operation"], record["requestId"])
                for record in records
            ],
            [
                ("backend.stalled", "guided_preview", 7),
                ("backend.resumed", "guided_preview", 7),
            ],
        )
        files = [
            (frame["file"], frame["function"])
            for frame in records[0]["causes"][0]["frames"]
        ]
        self.assertEqual(
            files[-3:],
            [
                ("app/tests/test_diagnostics.py", "blocked"),
                ("python/threading.py", "wait"),
                ("python/threading.py", "wait"),
            ],
        )
        # Runtime frames between the code's call and the wait are left out.
        self.assertFalse(
            any(
                all(name.startswith("python/") for name, _ in files[index : index + 3])
                for index in range(len(files) - 2)
            )
        )
        self.assertNotIn("causes", records[1])


def worker(script, plan, *arguments, attempt=None):
    """Launches a worker as the app launches it, with a run of `plan` and,
    when given, `attempt`. It runs beside the rest of the suite."""
    background = Background()
    # The error messages hold the run's path, as a provider's can hold a
    # key or the game's text.
    run = background.folder / "sk-ant-api03-FAKEKEY 日本語のテキスト"
    run.mkdir()
    (run / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if attempt is not None:
        (run / "attempt.json").write_text(json.dumps(attempt), encoding="utf-8")
    return background.start(
        [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            *bytecode(),
            str(ROOT / "backend/dazedtl/compatibility" / script),
            str(run),
            *arguments,
        ],
        env={**os.environ, FOLDER: str(background.folder / "diagnostics")},
    )


def worker_log(background):
    """The worker's diagnostics log, once it has ended."""
    try:
        background.wait()
        return (background.folder / "diagnostics/backend-failures.jsonl").read_text(
            encoding="utf-8"
        )
    finally:
        background.close()


ESTIMATE = {"mode": "estimate", "engine": "No such engine"}
# Without its attempt the worker crashes before it can report anything; with
# one, it reports the unknown engine as a generic failure.
unprepared = worker("manual_worker.py", ESTIMATE)
prepared = worker("manual_worker.py", ESTIMATE, attempt={"files": [], "resume": False})
# Its list of files never arrives, as when the coordinator's pipe breaks.
per_file = worker(
    "manual_file_worker.py",
    {"mode": "translate"},
    "RPG Maker MV/MZ",
    "--files-from-stdin",
    "False",
)


class WorkerCrashTests(unittest.TestCase):
    def test_a_crashing_run_worker_records_where_without_what_it_said(self):
        log = worker_log(unprepared) + worker_log(prepared)
        records = [json.loads(line) for line in log.splitlines()]
        self.assertEqual(
            [
                (record["event"], record["action"], record["causes"][0]["type"])
                for record in records
            ],
            [
                ("worker.error", "manual_estimate", "FileNotFoundError"),
                ("worker.error", "manual_estimate", "StopIteration"),
            ],
        )
        self.assertEqual(records[0]["errno"], 2)
        engine = "app/backend/dazedtl/engine/desktop/backend/"
        self.assertIn(
            (engine + "manual_worker.py", "main"),
            [
                (frame["file"], frame["function"])
                for frame in records[0]["causes"][0]["frames"]
            ],
        )
        self.assertEqual(
            records[1]["causes"][0]["frames"][-1]["file"],
            engine + "manual_environment.py",
        )
        self.assertTrue(
            all(
                type(frame["line"]) is int and frame["line"] > 0
                for record in records
                for frame in record["causes"][0]["frames"]
            )
        )
        self.assertNotIn("FAKEKEY", log)
        self.assertNotIn("日本語", log)
        self.assertNotIn("\\u65e5", log)

    def test_a_per_file_worker_that_crashes_at_startup_records_where(self):
        (record,) = [json.loads(line) for line in worker_log(per_file).splitlines()]
        self.assertEqual(
            (record["event"], record["action"], record["causes"][0]["type"]),
            ("worker.error", "manual_translate", "JSONDecodeError"),
        )
        self.assertIn(
            ("app/backend/dazedtl/engine/util/subprocess_runner.py", "file_arguments"),
            [
                (frame["file"], frame["function"])
                for frame in record["causes"][0]["frames"]
            ],
        )
