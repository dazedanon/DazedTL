"""A game's version save recovers from its own interruptions without adopting anyone's work."""

import unittest

from tests.probe import Probe

# Real Git launches dominate these journeys, so they run alongside the other tests.
probe = Probe("game_repository.py")


class GameRepositoryTests(unittest.TestCase):
    def test_interrupted_baselines_are_redone_and_index_writes_wait_for_a_status(self):
        # Finish setup refused forever after a forced stop or a lost index-lock
        # race left a half-made baseline; a poll's git status caused that race.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
