"""The language pair (util/languages): what reads as text left to translate
in each source language, and what a Japanese source keeps exactly."""

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from util.game_settings import (
    GameSettingsError,
    game_source_language,
    save_language_pair,
)
from util.languages import ENGLISH, reading, source_pattern
from util.source_text import holds_source, source_left
from util.translation import get_cache_key


class LanguageTests(unittest.TestCase):
    def test_an_english_source_reads_latin_letters_outside_codes_as_left(self):
        # Japanese stays the default, so an English line reads finished.
        self.assertFalse(holds_source("Hello"))
        with reading(ENGLISH):
            self.assertTrue(holds_source("\\C[2]Mika\\C[0], welcome!"))
            # A translation keeps codes, tags and placeholders, whose names
            # and arguments are Latin letters but no text.
            self.assertFalse(holds_source("\\fn[Arial]\\C[2]ようこそ<br>{name}さん"))
            # A lone letter the source holds is a symbol it keeps; a line
            # given back unchanged is all left.
            self.assertEqual(source_left("ポーション x2", "Potion x2"), [])
            self.assertEqual(source_left("Hello", "Hello"), ["Hello"])
            # The engines' send pattern takes each code whole.
            pattern = source_pattern("mvmz")
            self.assertIsNone(re.search(pattern, "\\N[1]\\V[3]__PROTECTED_0__"))
            self.assertIsNotNone(re.search(pattern, "\\V[3] gold"))

    def test_cache_keys_name_only_a_source_other_than_japanese(self):
        payload = json.dumps({"Line1": "はい"}, ensure_ascii=False)
        # The key every Japanese run had before the source became a setting.
        self.assertEqual(
            get_cache_key(payload, "English"), "1df594c4b6291191d51cd3b5ff95c7cd"
        )
        with reading(ENGLISH):
            self.assertNotEqual(
                get_cache_key(payload, "English"), "1df594c4b6291191d51cd3b5ff95c7cd"
            )

    def test_a_games_pair_is_two_scripts_and_names_its_source(self):
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            self.assertEqual(game_source_language(game), "Japanese")
            with self.assertRaises(GameSettingsError):
                save_language_pair(game, "English", "French")
            save_language_pair(game, "english", "Japanese")
            self.assertEqual(game_source_language(game), "English")
            settings = game / ".dazedtl/settings.json"
            saved = json.loads(settings.read_text(encoding="utf-8"))
            saved["languages"]["target"] = "Spanish"
            settings.write_text(json.dumps(saved), encoding="utf-8")
            with self.assertRaises(GameSettingsError):
                game_source_language(game)
