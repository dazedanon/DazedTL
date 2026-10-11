"""Text QA's engine: its mechanical rules, and its pipeline on a generated game."""

import unittest

from tests.engine import engine_module
from tests.probe import Probe

# The journeys run in their own interpreters, alongside the rest of the suite,
# because the engine's `util` package would clash with the fakes other tests
# install.
probe = Probe("qa_engine.py")
declines = Probe("qa_declines.py")
manifest = engine_module("util/rpgmaker_qa_manifest.py")
verify = engine_module("util/rpgmaker_qa_verify.py")
lint = engine_module("util/rpgmaker_qa_lint.py")


class QAEngineTests(unittest.TestCase):
    def test_review_journey_gates_and_findings(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)

    def test_declined_items_stay_within_their_helper(self):
        returncode, output = declines.result()
        self.assertEqual(returncode, 0, output)

    def test_numbers_beside_stat_letters_count(self):
        # Skill descriptions from a release, where English moves the stat away
        # from its number.
        for source, live in (
            (
                "敵全体へ90%威力の旋風斬り。TP24増加。",
                "A whirlwind slash against all enemies at 90% power. Increases TP by 24.",
            ),
            ("ＴＰ２０増加", "Increases TP by 20."),
            ("1000Gを手に入れた", "Obtained 1,000 G."),
        ):
            evidence = manifest._mechanical_evidence(source, live, None)
            self.assertNotIn("visible-number-mismatch", evidence["flags"], source)
            # The verifier recomputes the evidence, so it must count the same.
            self.assertEqual(verify._mechanical(source, live, None), evidence)
        # Runtime codes and identifiers still show no number.
        evidence = manifest._mechanical_evidence(
            "\\V[5]でHP30回復、EV024", "Restores 30 HP with \\V[5], EV024", None
        )
        self.assertEqual(evidence["source_visible_numbers"], ["30"])

    def test_dakuten_apostrophes_spare_slurs_and_moans(self):
        # Lines from a release whose reviewer rejected the proposed fixes.
        for source, live in (
            ("頭がぐるぐるしゅる゛…", "My head'sh shpinning"),
            ("うおぉ゛…お゛ぉ", "Whoa'…o'oh"),
        ):
            self.assertEqual(lint.proposals(source, live, {}), {}, live)
        # An apostrophe inside or after an ordinary word is still a leftover.
        self.assertEqual(
            lint.proposals("な゛んで…や゛めて", "Wh'y… Sto'p it'…", {}),
            {"lint:dakuten-apostrophe": "Why… Stop it…"},
        )
