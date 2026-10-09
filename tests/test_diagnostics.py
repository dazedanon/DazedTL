"""A hang leaves a record of where it waited, without flooding the report."""

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.diagnostics import Diagnostics
from dazedtl.watchdog import Watchdog

ROOT = Path(__file__).resolve().parents[1]


class HangTests(unittest.TestCase):
    def test_a_stall_records_where_it_waits_and_its_resumption_within_the_limit(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        diagnostics = Diagnostics(temporary.name, ROOT, ROOT / "backend/dazedtl/engine")
        self.addCleanup(diagnostics.close)
        watchdog = Watchdog(
            0.02,
            lambda state, request, seconds, frame: diagnostics.hang(
                "backend." + state,
                seconds,
                diagnostics.stack(frame),
                operation=request[0],
                request_id=request[1],
            ),
            limit=1,
        )
        never = threading.Event()

        def blocked():
            never.wait(0.12)

        watchdog.busy(("guided_preview", 7))
        blocked()
        watchdog.beat()
        # A second quiet period of the same work is past its report limit.
        blocked()
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
