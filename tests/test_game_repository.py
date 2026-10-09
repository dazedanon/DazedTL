"""A game's version save holds up against other Git processes in the game's repository."""

import unittest

from tests.probe import Probe

# Real Git launches dominate this journey, so it runs alongside the other tests.
probe = Probe("game_repository.py")


class GameRepositoryTests(unittest.TestCase):
    def test_index_writes_wait_for_a_status_holding_the_lock(self):
        # Set up failed on Windows when a poll's git status held the index lock.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
