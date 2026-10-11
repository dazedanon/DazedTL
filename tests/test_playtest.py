"""The release playtest: its static checks and the tour's in-game hooks."""

import unittest

from tests.probe import Probe

# The checks import the engine's `util` package, which would clash with the
# fakes other tests install, so they run in their own interpreter.
checks = Probe("playtest_checks.py")


class PlaytestTests(unittest.TestCase):
    def test_static_checks_find_what_text_qa_cannot(self):
        returncode, output = checks.result()
        self.assertEqual(returncode, 0, output)
