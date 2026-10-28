"""The one word-spacing rule for plugin commands and note tags
(engine/util/word_spacing.py) that Guided and Assistant-led read."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from util.word_spacing import chosen, join_words, nbsp_drawn, split_changes

from tests.fonts import truetype


def command(code, text):
    return {"code": code, "indent": 0, "parameters": [text]}


class WordSpacingTests(unittest.TestCase):
    def test_words_join_the_way_each_handler_was_chosen(self):
        # Options list a handler under the spacing found for its plugin.
        spaces, nbsp = ["text_indicator"], ["CommonPopup"]
        for name, joined in (
            ("text_indicator", "Resonance +3"),
            ("CommonPopup", "Resonance\u00a0+3"),
            ("D_TEXT ", "Resonance_+3"),
        ):
            with self.subTest(name=name):
                spacing = chosen(name, spaces, nbsp)
                self.assertEqual(join_words("Resonance +3", spacing), joined)

    def test_a_translation_splitting_into_more_arguments_is_found(self):
        # Japanese sets no spaces, so English words become extra arguments
        # unless they are joined; the same count is fine. A file an earlier
        # write translated counts from the source it kept, so writing the
        # split again still lists it.
        original = {
            "events": [
                None,
                {
                    "pages": [
                        {
                            "list": [
                                command(356, "D_TEXT 時刻 24"),
                                command(356, "D_TEXT 地図 24"),
                                # A comment keeps its continuation rows too.
                                {
                                    **command(108, "<namePop:Floor_Movement>"),
                                    "_original": "<namePop:階層移動>\nwith rows below",
                                },
                                command(401, "こんにちは"),
                                {
                                    **command(356, "CommonPopup add text:Resonance +3"),
                                    "_original": "CommonPopup add text:共鳴度+3",
                                },
                            ]
                        }
                    ]
                },
            ]
        }
        translated = json.loads(json.dumps(original))
        rows = translated["events"][1]["pages"][0]["list"]
        rows[0]["parameters"] = ["D_TEXT Current time 24"]
        rows[1]["parameters"] = ["D_TEXT World_map 24"]
        rows[2]["parameters"] = ["<namePop:Floor Movement>"]
        rows[3]["parameters"] = ["Hello there."]
        self.assertEqual(
            split_changes(original, translated),
            [
                {
                    "pointer": "/events/1/pages/0/list/0/parameters/0",
                    "text": "D_TEXT Current time 24",
                    "arguments": 4,
                    "source_arguments": 3,
                },
                {
                    "pointer": "/events/1/pages/0/list/2/parameters/0",
                    "text": "<namePop:Floor Movement>",
                    "arguments": 2,
                    "source_arguments": 1,
                },
                {
                    "pointer": "/events/1/pages/0/list/4/parameters/0",
                    "text": "CommonPopup add text:Resonance +3",
                    "arguments": 4,
                    "source_arguments": 3,
                },
            ],
        )

    def test_nbsp_is_drawn_only_by_a_font_whose_map_holds_it(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            fonts = Path(temporary) / "fonts"
            self.assertEqual(
                nbsp_drawn(data),
                {"drawn": None, "unread": "The game names no font file."},
            )
            fonts.mkdir()
            # MV names its font in gamefont.css.
            (fonts / "gamefont.css").write_text(
                '@font-face { font-family: GameFont; src: url("mplus.ttf"); }',
                encoding="utf-8",
            )
            for ranges, drawn in (
                (((0x20, 0x7E),), False),
                (((0x20, 0x7E), (0xA0, 0xA0)), True),
            ):
                (fonts / "mplus.ttf").write_bytes(truetype(*ranges))
                with self.subTest(drawn=drawn):
                    self.assertEqual(
                        nbsp_drawn(data), {"font": "fonts/mplus.ttf", "drawn": drawn}
                    )


if __name__ == "__main__":
    unittest.main()
