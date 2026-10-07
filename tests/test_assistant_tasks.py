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


if __name__ == "__main__":
    unittest.main()
