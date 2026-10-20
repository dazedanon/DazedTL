"""The one definition of RPG Maker text blocks (util/rpgmaker_blocks.py) that
translation, fitting, Text QA, Assistant-led and the playtest read."""

import tempfile
import unittest
from pathlib import Path

from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import comment_markers, data_plugins, game_plugins
from util.rpgmaker_rewrap import wrap_help


def command(code, parameters, indent=0, **extra):
    return {"code": code, "indent": indent, "parameters": parameters, **extra}


def choosing(help_rows, face="Actor1"):
    """A message with a face, its choice, and the choice's help."""
    return [
        command(101, [face, 0, 0, 2, ""]),
        command(401, ["What will you do?"], _original="どうする？"),
        command(102, [["Watch", "Skip"], 1, 0, 2, 0], _original=["見る", "見ない"]),
        command(402, [0, "Watch"]),
        command(108, ["選択肢ヘルプ"], 1),
        *help_rows,
        command(0, [], 1),
        command(404, []),
    ]


class TextBlockTests(unittest.TestCase):
    def test_help_translated_before_rows_were_recorded_leaves_the_games_rows(self):
        # 2.24.0 inserted a row for a long line and wrote no record of it;
        # "(1/3)" and the blank row are the game's own.
        original = choosing(
            [
                command(408, ["所要時間:20分"], 1),
                command(408, ["(1/3)"], 1),
                command(408, ["二行目の説明です。"], 1),
                command(408, [""], 1),
            ]
        )
        translated = choosing(
            [
                command(408, ["所要時間:20分"], 1, _original="所要時間:20分"),
                command(408, ["(1/3)"], 1),
                command(
                    408, ["This is the second line"], 1, _original="二行目の説明です。"
                ),
                command(408, ["of the explanation text."], 1),
                command(408, [""], 1),
            ]
        )
        self.assertEqual(blocks.owned(translated, 5, original=original), (5,))
        self.assertEqual(blocks.owned(translated, 7, original=original), (7, 8))
        # Without the original, rows that hold no text are never the
        # translation's; its record wins over both.
        self.assertEqual(blocks.owned(translated, 7), (7, 8))
        translated[7][blocks.ROWS] = 1
        self.assertEqual(blocks.owned(translated, 7, original=original), (7,))
        # Comments that are no choice's help, and messages, own their rows up
        # to the next translation, as Assistant-led writes them.
        notes = [
            command(108, ["メモ"]),
            command(408, ["Note"], _original="メモ書き"),
            command(408, [""]),
            command(408, ["続き"]),
        ]
        self.assertEqual(blocks.owned(notes, 1), (1, 2, 3))

    def test_comment_translated_on_its_marker_reads_as_one_block(self):
        # Assistant-led keeps a comment's Japanese, marker first, on the 108.
        listed = choosing(
            [
                command(408, ["It takes twenty minutes."], 1),
                command(408, ["Watch it first."], 1),
            ]
        )
        listed[4]["_original"] = (
            "選択肢ヘルプ\n所要時間:20分\n初回は見ることを推奨します。"
        )
        (help_block,) = [
            block for block in blocks.blocks(listed) if block.kind == blocks.HELP
        ]
        self.assertEqual(help_block.marker, "選択肢ヘルプ")
        self.assertTrue(help_block.face)
        (part,) = help_block.parts
        self.assertEqual(
            (part.anchor, part.rows, part.commands), (4, (5, 6), (4, 5, 6))
        )
        self.assertEqual(
            blocks.source(listed, part), "所要時間:20分\n初回は見ることを推奨します。"
        )

    def test_help_beside_a_portrait_while_translation_joins_message_rows(self):
        # The engine empties the rows it joins into the first until it writes
        # the list back; the help still shows beside the message's face.
        listed = choosing([command(408, ["選択肢の説明"], 1)])
        listed[1:2] = [listed[1], command(-1, []), command(-1, [])]
        self.assertTrue(blocks.block_at(listed, 7).face)
        self.assertFalse(
            blocks.block_at(choosing([command(408, ["説明"], 1)], ""), 5).face
        )

    def test_help_written_again_keeps_every_command(self):
        listed = choosing(
            [
                command(408, ["Long help"], 1, _original="長い説明", _rows=3),
                command(408, ["that took"], 1),
                command(408, ["three rows."], 1),
                command(408, ["(1/3)"], 1),
            ]
        )
        count = len(listed)
        block = blocks.block_at(listed, 5)
        used = blocks.write_help(listed, block, (5, 6, 7), ["Short help."])
        self.assertEqual(used, 1)
        self.assertEqual(len(listed), count)
        self.assertEqual(
            [row["parameters"][0] for row in listed[5:9]],
            ["Short help.", "(1/3)", "", ""],
        )
        self.assertEqual(listed[5][blocks.ROWS], 1)
        # Lines past its rows stack in its last one.
        block = blocks.block_at(listed, 5)
        blocks.write_help(listed, block, (5,), ["One", "Two"])
        self.assertEqual(listed[5]["parameters"], ["One\nTwo"])

    def test_list_items_of_the_japanese_keep_a_row_each_beside_a_face(self):
        help_text = wrap_help(
            "Effects: ・Attack power rises greatly for the rest of the battle "
            "・Defense rises ・Agility rises a little bit for three turns",
            45,
            source="効果：\n・攻撃力が大きく上がる\n・防御力が上がる\n・素早さが少し上がる",
        )
        self.assertEqual(
            help_text.split("\n"),
            [
                "Effects:",
                "・Attack power rises greatly",
                "for the rest of the battle",
                "・Defense rises",
                "・Agility rises a little bit for three turns",
            ],
        )

    def test_every_reader_takes_markers_from_the_list_the_game_loads(self):
        plugin = (
            '{"name":"MPP_ChoiceEX","status":true,"description":"",'
            '"parameters":{"Choice Help Commands":"[\\"ChoiceHelp\\"]"}}'
        )
        layouts = {
            "no semicolon": f"var $plugins =\n[\n{plugin}\n]\n",
            "comma after the last": f"var $plugins =\n[\n{plugin},\n];\n",
            "code after it": f"var $plugins =\n[\n{plugin}\n];\nconsole.log(1);\n",
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, text in layouts.items():
                game = Path(folder) / name
                (game / "data").mkdir(parents=True)
                (game / "js").mkdir()
                (game / "js/plugins.js").write_text(text, encoding="utf-8")
                for read in (game_plugins(game), data_plugins(game / "data")):
                    self.assertIn("ChoiceHelp", comment_markers(read), name)
            # A deployed MV game's list sits beside its data in www.
            game = Path(folder) / "deployed"
            (game / "www/data").mkdir(parents=True)
            (game / "www/js").mkdir(parents=True)
            (game / "js").mkdir()
            (game / "www/js/plugins.js").write_text(
                layouts["no semicolon"], encoding="utf-8"
            )
            (game / "js/plugins.js").write_text(
                "var $plugins = [];\n", encoding="utf-8"
            )
            self.assertIn("ChoiceHelp", comment_markers(game_plugins(game)))
