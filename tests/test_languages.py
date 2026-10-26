"""The language pair (util/languages): what reads as text left to translate
in each source language, and what a Japanese source keeps exactly."""

import hashlib
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from util.game_settings import (
    GameSettingsError,
    game_source_language,
    save_language_pair,
)
from util.languages import ENGLISH, reading, source_pattern
from util.paths import PROMPT_PATH, glossary_base_text
from util.prompt_pair import render, render_for_run
from util.source_text import holds_source, source_left
from util.translation import (
    CONTEXT_SOURCE,
    _context_block,
    createContextParts,
    get_cache_key,
)


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

    def test_the_base_rules_render_for_each_pair(self):
        raw = PROMPT_PATH.read_bytes()
        # The rules every Japanese to English run sent before the languages
        # became a setting, which saved estimates and requests are bound to.
        self.assertEqual(
            hashlib.sha256(render_for_run(raw, {"language": "English"})).hexdigest(),
            "8ceb972d50953a1cd7f0a30922d186d6afbec5e0a8203eed472f56c8b9ff9763",
        )
        english = render(raw.decode("utf-8"), ENGLISH, "Japanese")
        self.assertTrue(english.startswith("You are an expert English-to-Japanese"))
        # Guidance on Japanese itself and English text stays out.
        for japanese_only in ("Fufu", "-senpai", "コイツ", "ASCII apostrophe", "{{"):
            self.assertNotIn(japanese_only, english)
        with self.assertRaises(ValueError):
            render("{{#source Japanese}}\nopen", ENGLISH, "Japanese")
        # Game guidance after the template is kept as written.
        self.assertTrue(
            render(raw.decode("utf-8") + "{{/source}}\n", ENGLISH, "Japanese").endswith(
                "```\r\n{{/source}}\n"
            )
        )

    def test_an_english_sources_requests_read_english(self):
        config = SimpleNamespace(
            prompt="Translate {{source}} into {{target}}.",
            vocab="# Terms\nCat (ネコ)\n",
            language="Japanese",
        )
        with reading(ENGLISH):
            system, glossary, _sfx, _user = createContextParts(
                config, '{"Line1": "Category"}', "json"
            )
            self.assertEqual(system, "Translate English into Japanese.")
            # A term matches whole words of an English source.
            self.assertEqual(glossary, "")
            _system, glossary, _sfx, _user = createContextParts(
                config, '{"Line1": "The Cat sat."}', "json", ["Earlier line"]
            )
            self.assertIn("Cat (ネコ)", glossary)
            self.assertTrue(
                _context_block(["Earlier line"], CONTEXT_SOURCE).startswith(
                    "Preceding English Source Context"
                )
            )
            # The base glossary's Japanese honorifics are no use to it.
            self.assertEqual(glossary_base_text(), "")
