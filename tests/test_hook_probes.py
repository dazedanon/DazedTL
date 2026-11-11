"""A runtime hook's coverage probes (translation/hook_probes): each line as the
game shows it, its placeholders filled, and what makes the game's answer for
one no clean English."""

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.translation import hook_probes
from util.languages import UNTRANSLATED_TEXT
from util.paths import SKILLS_DIR

REWARD = "クエストクリア！\r\n報酬{0}ゴールドをもらった。"
PROBE = {"speaker": None, "text": "報酬101ゴールド", "values": ["101"]}


class ProbeTests(unittest.TestCase):
    def test_each_placeholder_takes_a_value_no_line_holds(self):
        probes = hook_probes.probes(
            [
                {"id": "reward", "source": REWARD, "speaker": None},
                # The lowest values are held: in a source, full-width, and
                # in a translation.
                {"id": "price", "source": "１０１円と102円", "speaker": "Shop"},
                {
                    "id": "count",
                    "source": "{0}匹と{1}匹、{0}匹",
                    "speaker": None,
                    "translation": "x103",
                },
            ]
        )
        self.assertEqual(
            probes["reward"],
            {
                "speaker": None,
                "text": "クエストクリア！\r\n報酬104ゴールドをもらった。",
                "values": ["104"],
            },
        )
        self.assertEqual(probes["count"]["text"], "104匹と105匹、104匹")
        self.assertEqual(probes["count"]["values"], ["104", "105"])
        self.assertEqual(
            probes["price"],
            {"speaker": "Shop", "text": "１０１円と102円", "values": []},
        )

    def test_a_format_item_shows_as_net_formats_it(self):
        probes = hook_probes.probes(
            [
                {"id": identity, "source": source, "speaker": None}
                for identity, source in {
                    "plain": "{0:F0}G",
                    "fixed": "{0:F2}%",
                    "grouped": "{0:N0}",
                    "padded": "[{0,5}]",
                    "zeros": "No.{0:D5}",
                    "custom": "{0:#,0}円",
                    "literal": "{{0}}は{0}",
                }.items()
            ]
        )
        shown = {identity: probe["text"] for identity, probe in probes.items()}
        self.assertEqual(
            shown,
            {
                "plain": "101G",
                "fixed": "101.00%",
                "grouped": "101",
                "padded": "[  101]",
                "zeros": "No.00101",
                "custom": "101円",
                # string.Format shows a doubled brace as one.
                "literal": "{0}は101",
            },
        )
        self.assertEqual(probes["padded"]["values"], ["101"])

    def test_a_token_is_filled_unless_it_is_markup(self):
        probe = hook_probes.probes(
            [
                {
                    "id": "line",
                    "source": "<color=red>[PLAYER]</color>は\\C[2]{0}\\C[0]を得た",
                    "speaker": None,
                    "tokens": ["<color=red>", "</color>", "[PLAYER]", "\\C[2]", "{0}"],
                }
            ]
        )["line"]
        self.assertEqual(probe["text"], "<color=red>102</color>は\\C[2]101\\C[0]を得た")
        self.assertEqual(probe["values"], ["101", "102"])


class ProblemTests(unittest.TestCase):
    def test_clean_english_holding_the_filled_value_passes(self):
        self.assertIsNone(hook_probes.problem(PROBE, "Received 101 gold."))

    def test_each_kind_of_unclean_answer_refuses(self):
        for shown, expected in {
            None: "no English",
            "Quest clear!\r\nReceived 101 gold.": "carriage return",
            "Received 101 ゴールド.": "still shows ゴールド",
            # A punctuation-only line is untranslated too.
            "……。": "still shows …。",
            "Received ───101": "still shows ─",
            "Received {0} gold.": "drops the value the game fills in (101)",
            "Received 1101 gold.": "drops the value the game fills in (101)",
            # A store that holds an empty English shows a blank line.
            " ": "no English",
        }.items():
            with self.subTest(shown=shown):
                self.assertIn(expected, hook_probes.problem(PROBE, shown))

    def test_a_line_without_untranslated_text_needs_no_english_of_its_own(self):
        # The hook's gate never looks it up, so the game shows it as it is.
        probe = {"speaker": None, "text": "HP 101/101", "values": ["101"]}
        self.assertIsNone(hook_probes.problem(probe, None))

    def test_marks_the_game_keeps_on_purpose_pass_and_no_others(self):
        # Labyrinth City Asylum draws ＜＞ around telepathy.
        self.assertIsNone(
            hook_probes.problem(PROBE, "＜Can you hear me? 101＞", kept="＜＞")
        )
        self.assertEqual(
            hook_probes.problem(PROBE, "＜……101＞", kept="＜＞"),
            "its English still shows …",
        )
        self.assertEqual(
            hook_probes.problem(PROBE, "＜Can you hear me? 101＞"),
            "its English still shows ＜＞",
        )

    def test_marks_a_translation_keeps_are_no_untranslated_text(self):
        # Ideographic space and the censor glyphs stay out of the class.
        self.assertIsNone(hook_probes.problem(PROBE, "Got 101　〇〇 ●"))


class GateTests(unittest.TestCase):
    def test_a_damaged_judgement_reads_as_none(self):
        # Release's review must name the check, not fail on the record.
        with TemporaryDirectory() as folder:
            records = Path(folder) / "translation/projects/p"
            records.mkdir(parents=True)
            (records / hook_probes.REQUIRED).write_text("{}", encoding="utf-8")
            (records / hook_probes.EVIDENCE).write_text(
                json.dumps({"version": hook_probes.VERSION}), encoding="utf-8"
            )
            self.assertEqual(
                hook_probes.require(
                    folder, "p", folder, ["BepInEx/plugins/Mod/Mod.dll"]
                ),
                hook_probes.UNCHECKED,
            )


class UntranslatedClassTests(unittest.TestCase):
    def test_the_skill_states_the_class_the_code_checks_by(self):
        # The guidance's copy, which assistants and hooks use, must match the
        # class coverage reads the game's answers by, character for character.
        skill = (SKILLS_DIR / "game-translation/SKILL.md").read_text(encoding="utf-8")
        block = skill.split("JP_TEXT = (", 1)[1].split("```", 1)[0]
        stated = re.compile("".join(re.findall(r'r"([^"]*)"', block)))
        code = re.compile(UNTRANSLATED_TEXT)
        self.assertEqual(
            [c for c in map(chr, range(0x10000)) if stated.match(c)],
            [c for c in map(chr, range(0x10000)) if code.match(c)],
        )


if __name__ == "__main__":
    unittest.main()
