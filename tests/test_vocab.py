"""Harvesting translated names into a game's glossary keeps the rows already there."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util.paths import ensure_game_glossary
from util.vocab import BASE_SEPARATOR, update_vocab_section

BASE = BASE_SEPARATOR + "# Honorifics\nさん (san)\n"


class GlossarySectionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.glossary = ensure_game_glossary(self.root)
        # Collect-phase runs skip harvesting; the environment must not leak in.
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("BATCH_PHASE", None)

    def write(self, game):
        self.glossary.write_text(game + "\n\n" + BASE, encoding="utf-8", newline="\n")

    def update(self, category, pairs, **options):
        update_vocab_section(category, pairs, game_root=self.root, **options)
        return self.glossary.read_text(encoding="utf-8")

    def test_merging_keeps_a_row_with_a_note_after_its_translation(self):
        # A curated row such as "サンク (Sank) - Male" does not end with its
        # closing parenthesis; merging parsed only plain rows and dropped it,
        # so adding one character erased the voice notes of the others.
        self.write(
            "# Game Characters\nサンク (Sank) - Male, gruff\nリナ (Rina)\n\n# Items\n薬 (Potion)"
        )
        text = self.update(
            "Game Characters", [("リナ", "Lina"), ("新人", "Newbie")], merge=True
        )
        self.assertEqual(
            text,
            "# Game Characters\nサンク (Sank) - Male, gruff\nリナ (Rina)\n新人 (Newbie)\n\n"
            "# Items\n薬 (Potion)\n\n" + BASE,
        )


if __name__ == "__main__":
    unittest.main()
