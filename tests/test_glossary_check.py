"""The glossary check: its scan and fixes through the engine, and where the
user's choices leave each line."""

import unittest

from dazedtl.translation.glossary_check import _state

from tests.probe import Probe

# The engine's journey runs in its own interpreter, alongside the suite,
# because the engine's `util` package would clash with the fakes other tests
# install.
probe = Probe("glossary_check.py")


class GlossaryCheckTests(unittest.TestCase):
    def test_scan_flags_proposes_and_writes_fixes(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)

    def test_a_choice_holds_only_for_the_text_it_was_made_for(self):
        line = {"live": "Sonko is here.", "terms": [{"source": "存子"}]}
        kept = {"live": "Sonko is here.", "terms": ["存子"], "choice": "keep"}
        fix = {
            "live": "Sonko is here.",
            "terms": ["存子"],
            "choice": "edit",
            "text": "Sonko is here, Aruko.",
        }
        self.assertEqual(_state(line, kept)["state"], "kept")
        self.assertEqual(
            _state(line, fix), {"state": "fix", "choice": "edit", "text": fix["text"]}
        )
        # Once applied, a fix that still lacks the term is the user's text.
        self.assertEqual(_state({**line, "live": fix["text"]}, fix)["state"], "kept")
        # A line changed elsewhere, or missing another term, is open again.
        self.assertEqual(_state({**line, "live": "Sonko left."}, kept)["state"], "open")
        another = {**line, "terms": [{"source": "存子"}, {"source": "トーラ"}]}
        self.assertEqual(_state(another, kept)["state"], "open")
        self.assertEqual(_state(line, None)["state"], "open")


if __name__ == "__main__":
    unittest.main()
