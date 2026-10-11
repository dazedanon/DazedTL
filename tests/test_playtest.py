"""The release playtest: its static checks, and how the tour's findings join them."""

import unittest

from tests.probe import Probe

# The checks import the engine's `util` package, which would clash with the
# fakes other tests install, so they run in their own interpreter.
checks = Probe("playtest_checks.py")


class PlaytestTests(unittest.TestCase):
    def test_checks_and_tour_find_what_text_qa_cannot(self):
        returncode, output = checks.result()
        self.assertEqual(returncode, 0, output)
