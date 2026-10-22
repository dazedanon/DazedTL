"""A game's version history recovers from its own interruptions, adopts no
one's work, and carries a translation onto a patched or new release."""

import unittest

from tests.probe import Probe

# Real Git launches dominate these journeys, so they run alongside the other tests.
probe = Probe("game_repository.py")
patch = Probe("release_patch.py")
ace = Probe("ace_update.py")


class GameRepositoryTests(unittest.TestCase):
    def test_interrupted_baselines_are_redone_and_index_writes_wait_for_a_status(self):
        # Finish setup refused forever after a forced stop or a lost index-lock
        # race left a half-made baseline; a poll's git status caused that race.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)

    def test_a_patch_keeps_the_files_it_leaves_out_and_unchanged_translations(self):
        # A patch applied as a complete game removed every file it left out,
        # its unformatted maps replaced their translated copies whole, and a
        # conflict among hundreds of inserted lines replaced translations it
        # never touched.
        returncode, output = patch.result()
        self.assertEqual(returncode, 0, output)

    def test_a_vx_ace_patch_leaves_out_ace_json_and_an_update_keeps_it(self):
        # 2.27.0 let each apply's ace_json into the patch: Release refused
        # its paths as duplicates, and an update replaced the translation
        # with the release's, as the original branch held no ace_json; an
        # encrypted release was staged unprepared.
        returncode, output = ace.result()
        self.assertEqual(returncode, 0, output)
