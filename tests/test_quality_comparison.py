"""Measured translation-quality comparisons (util/quality_set.py and
util/evaluation_quality.py)."""

import unittest

from tests.probe import Probe

# The engine's `util` package would clash with the fakes other tests install,
# so the journey runs in its own interpreter alongside the suite.
probe = Probe("quality_comparison.py")


class QualityComparisonTest(unittest.TestCase):
    def test_set_runs_judging_and_verdicts_from_the_set_alone(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
