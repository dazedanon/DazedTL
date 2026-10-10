"""Text QA's engine pipeline on a generated game."""

import unittest

from tests.probe import Probe

# The journey runs in its own interpreter, alongside the rest of the suite,
# because the engine's `util` package would clash with the fakes other tests
# install.
probe = Probe("qa_engine.py")


class QAEngineTests(unittest.TestCase):
    def test_review_journey_gates_and_findings(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
