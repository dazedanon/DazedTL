"""Copied assistant tasks say what is still waiting without asking each feature."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.translation.assistant_tasks import AssistantTasks

PROJECT = "0123456789abcdef0123456789abcdef"


class AssistantTaskTests(unittest.TestCase):
    def test_results_count_only_after_the_copy_and_dismissal_lasts_until_copied_again(
        self,
    ):
        with TemporaryDirectory() as folder:
            tasks = AssistantTasks(folder)
            report = Path(folder, "report.json")
            # A result from an earlier copy must not finish the new one.
            report.write_text("{}")
            os.utime(report, (1_000_000_000, 1_000_000_000))
            handoff = {"kind": "qa", "requestId": "task", "expects": [report]}
            tasks.copied(PROJECT, handoff)
            [row] = tasks.view(PROJECT)
            self.assertLess(row["resultAt"], row["copiedAt"])
            # Saved after the copy; set explicitly, since file times come
            # from a coarser clock than the copy time.
            report.write_text('{"saved": true}')
            later = time.time() + 1
            os.utime(report, (later, later))
            [row] = tasks.view(PROJECT)
            self.assertGreaterEqual(row["resultAt"], row["copiedAt"])
            self.assertNotIn("finishedAt", row)
            # A task that keeps working after its results reads its last one.
            last = Path(folder, "last.json")
            tasks.copied(PROJECT, {**handoff, "finish": last})
            self.assertIsNone(tasks.view(PROJECT)[0]["finishedAt"])
            last.write_text("{}")
            os.utime(last, (later, later))
            [row] = tasks.view(PROJECT)
            self.assertGreaterEqual(row["finishedAt"], row["copiedAt"])

            tasks.dismiss(PROJECT, "qa")
            self.assertTrue(AssistantTasks(folder).view(PROJECT)[0]["dismissed"])
            tasks.copied(PROJECT, handoff)
            self.assertFalse(tasks.view(PROJECT)[0]["dismissed"])
            # A task copied before records existed can be dismissed too.
            tasks.dismiss(PROJECT, "plugins")
            self.assertTrue(
                {row["kind"]: row for row in tasks.view(PROJECT)}["plugins"][
                    "dismissed"
                ]
            )
            with self.assertRaises(ValueError):
                tasks.copied(PROJECT, {**handoff, "kind": "unknown"})

    def test_a_validation_report_is_read_again_once_it_changes(self):
        # A failing report read as passing, or a later passing one hidden by
        # the cache, would end the walkthrough early or never.
        with TemporaryDirectory() as folder:
            tasks = AssistantTasks(folder)
            report = Path(folder, "validation-report.json")
            tasks.copied(
                PROJECT,
                {
                    "kind": "walkthrough",
                    "requestId": "",
                    "expects": [Path(folder, "WALKTHROUGH.html")],
                    "validation": report,
                },
            )
            self.assertIsNone(tasks.view(PROJECT)[0]["validation"])
            moment = time.time()
            for text, outcome in (
                ('{"status": "failed", "summary": {"errors": 2}}', (False, 2)),
                # The same size as the failing report; only its time changed.
                ('{"status": "passed", "summary": {"errors": 0}}', (True, 0)),
                # A report still being written has no outcome yet.
                ('{"status": "pass', None),
            ):
                report.write_text(text)
                moment += 1
                os.utime(report, (moment, moment))
                validation = tasks.view(PROJECT)[0]["validation"]
                self.assertEqual(
                    validation and (validation["passed"], validation["errors"]),
                    outcome,
                )


if __name__ == "__main__":
    unittest.main()
