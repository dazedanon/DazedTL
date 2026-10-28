"""Text QA's corrections as a measured dataset (util/qa_corrections.py)."""

import unittest

from tests.probe import Probe

# The engine's `util` package would clash with the fakes other tests install,
# so the journey runs in its own interpreter alongside the suite.
probe = Probe("qa_corrections.py")


class QACorrectionsTest(unittest.TestCase):
    def test_tasks_and_receipts_count_once_labelled_and_read_only(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
