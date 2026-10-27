"""The language pair (util/languages): what reads as text left to translate
in each source language, and what a Japanese source keeps exactly."""

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from util import dazedwrap, target_text
from util import rpgmaker_qa_glossary as glossary_rules
from util import rpgmaker_qa_lint as lint
from util import rpgmaker_rewrap as rewrap
from util.game_encoding import UnwritableText, writable
from util.game_settings import (
    GameSettingsError,
    binding_bytes,
    game_source_language,
    save_game_wrap_widths,
    save_language_pair,
)
from util.languages import ENGLISH, reading, source_pattern
from util.paths import PROMPT_PATH, glossary_base_text
from util.playtest.checks import reading as playtest_reading
from util.prompt_pair import render, render_for_run
from util.qa.mechanical import evidence
from util.qa.selection import _number_defect
from util.rpgmaker_qa_preflight import _untranslated as preflight_untranslated
from util.source_text import holds_source, source_left
from util.speakers import inline_speaker, strip_echoed_speaker, translate_speaker
from util.translation import (
    CONTEXT_SOURCE,
    _context_block,
    createContextParts,
    extractTranslation,
    get_cache_key,
    validate_translation_content,
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
            # On screen, an abbreviation a translation keeps in capitals is
            # no English left.
            screen = re.compile(playtest_reading()["pattern"])
            self.assertTrue(screen.search("テスト Potion"))
            self.assertFalse(screen.search("HP 100/100 テスト"))

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

    def test_recording_a_japanese_pair_leaves_the_settings_work_binds(self):
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            settings = game / ".dazedtl/settings.json"
            save_game_wrap_widths(game, {"width": 50})
            before = settings.read_bytes()
            save_language_pair(game, "Japanese", "Spanish")
            self.assertNotEqual(settings.read_bytes(), before)
            self.assertEqual(binding_bytes(settings.read_bytes()), before)
            save_language_pair(game, "English", "Japanese")
            self.assertNotEqual(binding_bytes(settings.read_bytes()), before)

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

    def test_a_japanese_target_keeps_its_punctuation_through_output_cleanup(self):
        # Cleanup written for English output deleted every small っ, turned
        # 。 into a period and 「」【】 into ASCII, and title-cased names.
        reply = '```json\n{"Line1": "「頼んだぞっ。」【村長】ッ〜’"}\n```'
        cleaned = target_text.clean_reply(reply, "Japanese")
        line = extractTranslation(cleaned, True, None, "Japanese")[0]
        self.assertEqual(line, "「頼んだぞっ。」【村長】ッ〜’")
        self.assertEqual(target_text.corner_quotes(line, "Japanese"), line)
        for form in (target_text.ROWS, target_text.SKIPPED, target_text.BRACKETS):
            self.assertEqual(
                target_text.unsent_text("・・・・・。「？」", "Japanese", form),
                "・・・・・。「？」",
            )
        self.assertEqual(
            target_text.full_stops("...。", "Japanese", target_text.AFTER_ELLIPSIS),
            "...。",
        )
        self.assertEqual(
            target_text.title_case("村長 the elder", "Japanese"), "村長 the elder"
        )
        self.assertTrue(target_text.name_translated("村長", "Japanese"))
        self.assertEqual(
            strip_echoed_speaker("テスト(はい)", "Japanese"), "テスト(はい)"
        )
        # English output is written as it always was.
        self.assertEqual(strip_echoed_speaker("ミカ: Hello", "English"), "Hello")
        self.assertEqual(
            target_text.clean_reply("「頼んだぞっ。」【村長】", "English"),
            "「頼んだぞ.」[村長]",
        )

    def test_the_plain_engines_translate_a_speaker_name_the_same_way(self):
        asked = []

        def translate(text, prompt, history):
            asked.append((text, prompt))
            return (
                ["Speaker: gran'S", [1, 1]]
                if len(asked) == 1
                else ["old 'S man", [1, 1]]
            )

        names = []
        first = translate_speaker("老人", names, "English", translate)
        self.assertEqual(first, ["Gran's", [1, 1]])
        self.assertEqual(
            asked, [("老人", "Reply with the English translation of the NPC name.")]
        )
        self.assertEqual(
            translate_speaker("老人", names, "English", translate), ["Gran's", [0, 0]]
        )
        self.assertEqual(len(asked), 1)
        # A reply with no letters is asked for once more.
        asked.clear()
        retry = translate_speaker(
            "店主",
            names,
            "English",
            lambda *a: (
                asked.append(a),
                ["店主", [0, 0]] if len(asked) == 1 else ["Shop Owner", [0, 0]],
            )[1],
        )
        self.assertEqual((retry[0], len(asked)), ("Shop Owner", 2))
        self.assertEqual(
            translate_speaker("？？？", names, "English", translate), ["???", [0, 0]]
        )
        self.assertEqual(
            translate_speaker("ファイン", [], "English", translate), ["Fine", [0, 0]]
        )
        self.assertEqual(translate_speaker("", [], "English", translate), ["", [0, 0]])
        asked.clear()
        translate_speaker("ファイン", [], "French", translate)
        self.assertEqual(len(asked), 1)

    def test_an_inline_speaker_reads_the_same_for_every_caller(self):
        # Format detection and the MV/MZ parser each kept a copy of the rule
        # and read the same line differently. Detection reads the source
        # form; the parser also the forms a re-export or English game holds.
        for line, source, written_back in (
            ("ミカ「やあ」", ("ミカ", "ミカ"), ("ミカ", "ミカ")),
            ("ミカ：「やあ」", ("ミカ：", "ミカ："), ("ミカ：", "ミカ：")),
            ("ミカ: 「やあ」", ("ミカ", "ミカ: "), ("ミカ", "ミカ: ")),
            ("ミカ 「やあ」", ("ミカ", "ミカ "), ("ミカ", "ミカ ")),
            ("ミカ(小声)「やあ」", None, ("ミカ", "ミカ")),
            ('Mika: "Hi"', None, ("Mika", "Mika: ")),
            ("Mika “Hi”", None, ("Mika", "Mika ")),
            ("Mika (sighs)", None, ("Mika", "Mika ")),
            ("[Mika] Hi", None, ("Mika", "[Mika] ")),
            ("「やあ」", None, None),
            (r"\C[2]ミカ「やあ」", None, None),
            ("こんにちは", None, None),
        ):
            for form, expected in ((False, source), (True, written_back)):
                found = inline_speaker(line, written_back=form)
                self.assertEqual(found and found[:2], expected, (line, form))
                if found:
                    self.assertEqual(found.prefix + found.speech, line)

    def test_punctuation_only_text_keeps_each_writers_english_form(self):
        # One rule with each writer's form, so Japanese to English output
        # stays byte for byte what runs wrote before the rule was merged.
        cases = {
            target_text.ROWS: (".....?", '"……"', "!"),
            target_text.SKIPPED: ("・・・・・.？", "「……」", "！"),
            target_text.BRACKETS: ("・・・・・。？", '"……"', "！"),
        }
        for form, expected in cases.items():
            quotes = form != target_text.SKIPPED
            self.assertEqual(
                tuple(
                    target_text.unsent_text(text, "English", form, quotes)
                    for text in ("・・・・・。？", "「……」", "！")
                ),
                expected,
                form,
            )

    def test_a_translation_into_another_script_is_checked_and_written_for_it(self):
        with reading(ENGLISH):
            pattern = source_pattern("mvmz")
            # English left in a Japanese reply fails, and an abbreviation
            # the source holds stays.
            valid, failed, _reasons = validate_translation_content(
                ["Restores 50 HP.", "Thank you for coming."],
                ["HPを50回復する。", "Thank youございます。"],
                pattern,
                "Japanese",
            )
            self.assertEqual((valid, failed), (False, [1]))
        # Lint's English fixes leave Japanese alone.
        self.assertEqual(lint.normalize("っ…", "えっ…h", "Japanese"), "えっ…h")
        self.assertEqual(lint.normalize("っ…", "Eh…h", "English"), "Eh…")
        # A counter a Japanese translation writes as a digit is no defect.
        self.assertFalse(_number_defect("three potions", "ポーション3個", "Japanese"))
        self.assertTrue(_number_defect("three potions", "Potion 3", "English"))
        self.assertTrue(_number_defect("3回攻撃", "攻击5次", "Chinese"))
        self.assertFalse(_number_defect("50ゴールド", "五十金币", "Chinese"))
        # A letter Shift-JIS can't write fails the file, naming its line; an
        # accented one loses its accent, and a symbol such as ♥ is left out
        # on writing as it always was.
        self.assertEqual(
            writable(["Ahh♥ Señor\n"], "cp932", "scene.ks"), ["Ahh♥ Senor\n"]
        )
        with self.assertRaisesRegex(UnwritableText, "line 2 holds 안"):
            writable(["はい\n", "안녕\n"], "cp932", "scene.ks")

    def test_text_left_reads_for_the_language_pair(self):
        # Read as Japanese, a Chinese translation's hanzi were all left, so
        # nothing was fitted, and an English source's HP kept in Japanese
        # was English left, so its row overflowed unfitted.
        chinese = "测试：恢复50点生命值。这是一个很长的说明文字，一直延续下去。"
        # However the target names Chinese, its hanzi are its own text.
        with reading("Japanese", "Simplified Chinese"):
            self.assertEqual(source_left(chinese, "テスト：ＨＰを回復する。"), [])
            self.assertEqual(source_left("测试ですね", "テストです"), ["测试ですね"])
            # A name kept letter for letter is translated; text without a
            # source may be text never translated.
            self.assertEqual(source_left("魔王", "魔王"), [])
            self.assertTrue(holds_source("魔王"))
            # Text QA reads a line against its source too, so it no longer
            # finds Japanese left in every line.
            residue = "source-language-residue"
            self.assertNotIn(residue, evidence("魔王が来た", "魔王来了", 401)["flags"])
            self.assertIn(residue, evidence("魔王が来た", "魔王が来了", 401)["flags"])
            # Its glossary check reads a target written without spaces as
            # text: a line holding the term uses it, and one that renders it
            # another way or leaves it out misses it, as does one keeping
            # kanji the glossary gives as other hanzi, its full-width
            # qualifier left out; a row still giving English is not checked.
            # Only a name that is the term alone gets a fix.
            records = [
                {
                    "file": "Map001.json",
                    "source": "アリス",
                    "live": "艾莉丝",
                    "event_code": 101,
                }
            ]
            game = lint.game(
                {"clusters": [], "records": records},
                "アリス (爱丽丝)\n勇者 (勇士)\nニーナ (妮娜（女仆）)\nセルリア (Cerulia)\n",
                "Simplified Chinese",
            )
            for source, live, missed in (
                ("アリスが来た。", "爱丽丝来了。", []),
                ("アリスが来た。", "艾莉丝来了。", ["アリス"]),
                ("アリスはどこ？", "她在哪里？", ["アリス"]),
                ("勇者が来た。", "勇士来了。", []),
                ("勇者が来た。", "勇者来了。", ["勇者"]),
                ("ニーナが来た。", "妮娜来了。", []),
                ("セルリアが来た。", "塞露莉亚来了。", []),
            ):
                found = glossary_rules.missing(source, live, game.glossary)
                self.assertEqual([term.source for term, *_span in found], missed)
            family = "lint:glossary-term"
            self.assertEqual(
                lint.proposals("アリス", "艾莉丝", game), {family: "爱丽丝"}
            )
            self.assertEqual(lint.proposals("アリスが来た。", "艾莉丝来了。", game), {})
            # The playtest reads only kana on screen.
            screen = re.compile(playtest_reading()["pattern"])
            self.assertFalse(screen.search("魔王城"))
            self.assertTrue(screen.search("魔王です"))
            self.assertEqual(
                validate_translation_content(
                    ["テストです", "魔王"],
                    ["测试です", "魔王"],
                    source_pattern(),
                    "Chinese",
                )[1],
                [0],
            )
        layout = {"width": 30, "listWidth": 30}
        cases = (
            ("Japanese", "繁體中文", chinese, "テスト：ＨＰを５０回復する。"),
            (
                ENGLISH,
                "Japanese",
                "テストHPを50回復するッ。とても長い説明文がここに続いていて幅を超える。",
                "Test: restores 50 HP. A long description.",
            ),
        )
        for source, target, text, original in cases:
            message = [
                {"code": 101, "parameters": ["", 0, 0, 2]},
                {"code": 401, "parameters": [text], "_original": original},
                {"code": 0, "parameters": []},
            ]
            items = [
                None,
                {"description": text, "_original": {"description": original}},
            ]
            with reading(source, target):
                for document, name in (
                    ([{"list": message}], "Map001.json"),
                    (items, "Items.json"),
                ):
                    report = rewrap.fit_document(
                        document, name, rewrap.Layout.from_widths(layout, target)
                    )
                    self.assertEqual(len(report.changes), 1, (source, name))
        # An English game's currency unit and abbreviations are no text
        # left to translate in Text QA's never-translated report.
        rows = []
        with reading(ENGLISH):
            preflight_untranslated(
                "System.json",
                {"currencyUnit": "G", "terms": {"basic": ["Level", "HP", "EXP"]}},
                set(),
                frozenset(),
                rows,
            )
        self.assertEqual([row["text"] for row in rows], ["Level"])

    def test_a_guided_action_reads_its_games_source(self):
        # Read as Japanese, an English game's Apply took its Japanese
        # translation for text left to translate and never fitted it.
        from desktop.backend.workflow_worker import reading_plan

        with TemporaryDirectory() as temporary:
            save_language_pair(temporary, "English", "Japanese")
            with reading_plan({"project": {"source": temporary}}):
                self.assertFalse(holds_source("テスト了解っ！"))
            self.assertTrue(holds_source("テスト了解っ！"))
            with reading_plan({"kind": "batch"}):
                self.assertTrue(holds_source("テスト了解っ！"))

    def test_a_japanese_translation_breaks_between_characters_and_fits(self):
        # An English game's Japanese translation has no spaces to break at:
        # read as English, a message was one word too wide to fit anywhere.
        message = (
            "テスト了解っ！　すぐ行くね〜。「それから、あの山の向こうにある"
            "\\C[2]村\\C[0]まで一緒に行こうよ！」ポーション……持った？"
        )
        no_start, no_end = "、。！？」ー〜…っ", "「"

        def check(text, width):
            rows = text.split("\n")
            self.assertEqual(re.sub(r"\s", "", text), re.sub(r"\s", "", message))
            self.assertNotIn(" ", text)
            for row in rows:
                self.assertLessEqual(rewrap.visible_width(row), width, rows)
                self.assertNotIn(row[:1] or "x", no_start, rows)
                self.assertNotIn(row[-1:] or "x", no_end, rows)
            self.assertEqual(text.count("\\C[2]村\\C[0]"), 1, rows)
            return rows

        with reading(ENGLISH):
            check(rewrap.wrap_message(message, 20, target="Japanese"), 20)
            # Its full-width space stays where no line breaks.
            rows = check(rewrap.wrap_message(message, 44, target="Japanese"), 44)
            self.assertIn("了解っ！　すぐ", rows[0])
            check(dazedwrap.wrapText(message, 16, target="Japanese"), 16)
            # A half-width word stays whole, its combining marks too.
            self.assertIn("cafés", dazedwrap.character_words("カフェcafésです").words)
            # Apply fits a game's text as its recorded target breaks it.
            document = [
                {
                    "list": [
                        {"code": 101, "parameters": ["", 0, 0, 2, "Mika"]},
                        {"code": 401, "parameters": [message]},
                        {"code": 0, "parameters": []},
                    ]
                }
            ]
            widths = {"width": 24, "messageRows": 4}
            self.assertTrue(
                rewrap.fit_document(
                    copy.deepcopy(document),
                    "Map001.json",
                    rewrap.Layout.from_widths(widths),
                ).misfits
            )
            report = rewrap.fit_document(
                document, "Map001.json", rewrap.Layout.from_widths(widths, "Japanese")
            )
            self.assertEqual(report.misfits, [])
            fitted = document[0]["list"][1]["parameters"][0]
            check(re.sub(r"\n+", "\n", fitted), 24)
            # A text variable's line never starts with "[", which would make
            # its break a name code.
            variable = rewrap.wrap_variable(
                "`あいうえおかきくけこさしすせそ[1]たちつてと`", 10, "Japanese"
            )
            self.assertIn("\\n", variable)
            self.assertNotIn("\\n[", variable)
