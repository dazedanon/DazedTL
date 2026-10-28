"""Harvesting translated names into a game's glossary keeps the rows already there."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from util.len_translation import LenProject, import_glossary
from util.paths import ensure_game_glossary
from util.vocab import BASE_SEPARATOR, remove_vocab_section, update_vocab_section

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
        # An overwrite prints the hand-written rows it kept for the run log.
        with redirect_stdout(io.StringIO()):
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

    def test_overwriting_replaces_only_the_sources_it_translated(self):
        # A database pass that translated only the names still in Japanese
        # replaced the whole section with them. The rest must survive, a name
        # translated again takes its new spelling, and a row with a note stays.
        self.write(
            "# Items\n薬 (Potion)\n毒 (Poison)\n剣 (Sword) - hand note\n\n# Skills\n火 (Fire)"
        )
        text = self.update(
            "Items",
            [("★薬", "★Elixir"), ("新薬", "New Potion"), ("剣", "Blade"), ("無", "")],
            merge=True,
            overwrite=True,
        )
        self.assertEqual(
            text,
            "# Items\n薬 (Elixir)\n毒 (Poison)\n剣 (Sword) - hand note\n新薬 (New Potion)\n\n"
            "# Skills\n火 (Fire)\n\n" + BASE,
        )
        # Not merging still replaces the section, as other callers rely on.
        text = self.update("Skills", [("水", "Water")])
        self.assertIn("# Skills\n水 (Water)\n\n", text)

    def test_overwriting_keeps_a_row_that_lists_the_source_as_a_variant(self):
        # A database pass translated ネーナ again and appended "ネーナ (Nena)"
        # beside the hand-written "ニーナ / ネーナ (Nina)", after which
        # Assistant-led's import refused the glossary as conflicting.
        game = "# Game Characters\nニーナ / ネーナ (Nina)\nサンク (Sank) - Male"
        self.write(game)
        with redirect_stdout(io.StringIO()):
            kept = update_vocab_section(
                "Game Characters",
                [
                    ("ネーナ", "Nena"),
                    ("ニーナ", "Nina"),
                    ("サンク", "Sunk"),
                    ("ミカ", "Mika"),
                ],
                merge=True,
                overwrite=True,
                game_root=self.root,
            )
        self.assertEqual(
            kept,
            [
                ("サンク (Sank) - Male", "サンク", "Sunk"),
                ("ニーナ / ネーナ (Nina)", "ネーナ", "Nena"),
            ],
        )
        self.assertEqual(
            self.glossary.read_text(encoding="utf-8"),
            game + "\nミカ (Mika)\n\n" + BASE,
        )
        result = import_glossary(
            LenProject(self.root), {"names": {"リナ": {"en": "Rina"}}}
        )
        self.assertEqual(result["added"], 1)

    def test_a_write_means_every_section_its_category_names(self):
        # Requests read "# Game Characters · キャラクター" and "# game
        # characters" as Game Characters, but merges matched the exact header
        # and appended another section, and a section an older import
        # appended stayed apart, so a merge could add a row it held.
        self.write(
            "# Game Characters · キャラクター\nニーナ / ネーナ (Nina)\nサンク (Sank) - Male\n\n"
            "# Items\n薬 (Potion)\n\n# game characters\nサンク (Sank) - Male\nミカ (Mika)"
        )
        self.assertEqual(
            self.update(
                "Game Characters", [("ミカ", "Mika"), ("リナ", "Rina")], merge=True
            ),
            "# Game Characters · キャラクター\nニーナ / ネーナ (Nina)\nサンク (Sank) - Male\n"
            "ミカ (Mika)\nリナ (Rina)\n\n# Items\n薬 (Potion)\n\n" + BASE,
        )
        # Replacing or removing a category leaves none of its rows behind.
        self.write(
            "# Items\n薬 (Potion)\n\n# Skills\n火 (Fire)\n\n# items\n毒 (Poison)"
        )
        self.assertEqual(
            self.update("Items", [("剣", "Sword")]),
            "# Items\n剣 (Sword)\n\n# Skills\n火 (Fire)\n\n" + BASE,
        )
        self.write(
            "# Items\n薬 (Potion)\n\n# Skills\n火 (Fire)\n\n# items\n毒 (Poison)"
        )
        remove_vocab_section("Items", game_root=self.root)
        self.assertEqual(
            self.glossary.read_text(encoding="utf-8"), "# Skills\n火 (Fire)\n\n" + BASE
        )
        # WOLF writes a section per database note, and two notes may share
        # an English label; each keeps its own rows.
        self.write("# Item · アイテム\n薬 (Potion)\n\n# Item · 道具\n縄 (Rope)")
        self.assertEqual(
            self.update("Item · 道具", [("杖", "Staff")]),
            "# Item · アイテム\n薬 (Potion)\n\n# Item · 道具\n杖 (Staff)\n\n" + BASE,
        )

    def test_importing_adds_to_the_sections_already_there(self):
        # Assistant-led's import appended a second "# Game Characters" header
        # after the existing text, which Guided's merge never read, so it could
        # add a row the second section held.
        self.write("# Game Characters\nサンク (Sank) - Male\nニーナ / ネーナ (Nina)")
        project = LenProject(self.root)
        result = import_glossary(
            project,
            {
                "names": {
                    "リナ": {"en": "Rina", "gender": "female"},
                    "ネーナ": {"en": "Nina"},
                },
                "terms": {"魔石": "Magic Stone"},
            },
        )
        self.assertEqual((result["added"], result["preserved"]), (2, 1))
        merged = (
            "# Game Characters\nサンク (Sank) - Male\nニーナ / ネーナ (Nina)\n"
            "リナ (Rina) - gender: female\n\n# Game Terms\n魔石 (Magic Stone)\n\n"
            + BASE
        )
        self.assertEqual(self.glossary.read_text(encoding="utf-8"), merged)
        # A name a slash variant covers with the same translation is no new row.
        self.assertEqual(
            self.update("Game Characters", [("ニーナ", "Nina")], merge=True), merged
        )
        before = self.glossary.read_bytes()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            import_glossary(
                project, {"names": {"リナ": {"en": "Lina"}, "新人": {"en": "Newbie"}}}
            )
        self.assertEqual(self.glossary.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
