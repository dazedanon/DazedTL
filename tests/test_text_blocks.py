"""The one definition of RPG Maker text blocks (util/rpgmaker_blocks.py) that
translation, fitting, Text QA, Assistant-led and the playtest read."""

import json
import tempfile
import unittest
from pathlib import Path

from dazedtl.translation import comment_text, file_lines
from util import original_values
from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import comment_markers, data_plugins, game_plugins
from util.rpgmaker_rewrap import Layout, fit_document, wrap_help


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
    def test_a_line_left_in_japanese_shows_its_japanese_as_its_source(self):
        # The engine keeps no `_original` for text a model gave back as it
        # was, so the live text is its own source, with a speaker's name.
        speaker = command(101, ["", 0, 0, 2, "Traveler"], _original="旅人")
        listed = [
            speaker,
            command(401, ["まだ訳せない。"]),
            command(101, ["", 0, 0, 2, ""]),
            command(401, ["え？"]),
            command(0, []),
        ]
        rows = file_lines.left(
            "CommonEvents.json", [None, {"list": listed}], "dialogue", frozenset()
        )
        self.assertEqual(
            [row["source"] for row in rows], ["旅人\nまだ訳せない。", "え？"]
        )

    def test_guided_lines_read_past_a_malformed_command(self):
        # A command whose code is no number, or that is no command at all,
        # stopped Guided's Lines and file status with a TypeError.
        def listing(*malformed):
            return [
                command(101, ["", 0, 0, 2, ""]),
                command(401, ["まだ訳せない。"]),
                *malformed,
                command(0, []),
            ]

        def game(commands):
            return {"events": [None, {"pages": [{"list": commands}]}]}

        current = listing({"code": [408], "parameters": []}, "?", None)
        # A translation that added a window pairs commands by their codes.
        original = listing(command(101, ["", 0, 0, 2, ""]), {"code": [408]})
        rows = file_lines.left(
            "Map001.json",
            game(current),
            "dialogue",
            frozenset(),
            lambda: game(original),
        )
        self.assertEqual([row["text"] for row in rows], ["まだ訳せない。"])
        self.assertEqual(
            original_values.commands(current, original)[:2], [(0, 0), (1, 1)]
        )

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
        used = blocks.write_help(listed, (5, 6, 7), ["Short help."])
        self.assertEqual(used, 1)
        self.assertEqual(len(listed), count)
        self.assertEqual(
            [row["parameters"][0] for row in listed[5:9]],
            ["Short help.", "(1/3)", "", ""],
        )
        self.assertEqual(listed[5][blocks.ROWS], 1)
        # Lines past its rows stack in its last one.
        blocks.write_help(listed, (5,), ["One", "Two"])
        self.assertEqual(listed[5]["parameters"], ["One\nTwo"])
        # A later translation keeps its place, which Text QA and saved notes
        # know it by; the spare rows stop before it.
        listed = choosing(
            [
                command(408, ["Long help"], 1, _original="長い説明", _rows=2),
                command(408, ["in two rows."], 1),
                command(408, ["(1/3)"], 1),
                command(408, ["Watch it first."], 1, _original="初回は見て"),
            ]
        )
        blocks.write_help(listed, (5, 6), ["Short help."])
        self.assertEqual(
            [row["parameters"][0] for row in listed[5:9]],
            ["Short help.", "(1/3)", "", "Watch it first."],
        )
        self.assertEqual(listed[8]["_original"], "初回は見て")

    def test_help_fitted_shorter_leaves_its_spare_rows_after_the_games_own(self):
        # Fitted to fewer rows than its translation owns, help reads on into
        # the page number the game shows below it, with no blank row between.
        listed = choosing(
            [
                command(
                    408,
                    [
                        "Takes about twenty minutes from start to end, so watch it first."
                    ],
                    1,
                    _original="所要時間は二十分です。初回は見てください。",
                    _rows=3,
                ),
                command(408, ["Really."], 1),
                command(408, ["Yes."], 1),
                command(408, ["(1/3)"], 1),
            ]
        )
        count = len(listed)
        layout = Layout(50, 50, 74, 45, 4)
        self.assertTrue(fit_document({"list": listed}, "Map001.json", layout).changes)
        self.assertEqual(len(listed), count)
        self.assertEqual(
            [row["parameters"][0] for row in listed[5:9]],
            [
                "Takes about twenty minutes from start to end,",
                "so watch it first. Really. Yes.",
                "(1/3)",
                "",
            ],
        )
        self.assertEqual(listed[5][blocks.ROWS], 2)
        self.assertFalse(fit_document({"list": listed}, "Map001.json", layout).changes)

    def test_help_rows_assistant_led_left_as_the_game_wrote_them_keep_their_row(self):
        # Assistant-led keeps the comment's Japanese on its 108 and writes
        # each row; the page number it left as it was is the game's own, so
        # fitting never flows it into the prose around it.
        listed = choosing(
            [
                command(
                    408,
                    [
                        "Watching the opening takes about twenty minutes from start to end."
                    ],
                    1,
                ),
                command(408, ["(1/3)"], 1),
                command(
                    408, ["We strongly recommend watching it on your first run."], 1
                ),
            ]
        )
        listed[4]["_original"] = (
            "選択肢ヘルプ\n所要時間は二十分です。\n(1/3)\n初回は見ることを推奨します。"
        )
        (part,) = blocks.block_at(listed, 5).parts
        self.assertEqual(blocks.kept(listed, part), (6,))
        count = len(listed)
        layout = Layout(40, 40, 74, 45, 4)
        report = fit_document({"list": listed}, "Map001.json", layout)
        self.assertTrue(report.changes)
        self.assertEqual(len(listed), count)
        rows = [row["parameters"][0] for row in listed[5:8]]
        self.assertEqual(rows[1], "(1/3)", rows)
        # The window shows the whole help, its page number included.
        shown = "\n".join(rows).count("\n") + 1
        self.assertEqual(
            [misfit["reason"] for misfit in report.misfits],
            [f"needs {shown} rows; its window shows 4"],
        )
        self.assertTrue(
            all(len(line) <= 40 for row in rows for line in row.split("\n"))
        )
        self.assertFalse(fit_document({"list": listed}, "Map001.json", layout).changes)

    def test_help_translated_in_parts_is_checked_as_the_window_shows_it(self):
        # Guided translation writes each Japanese row of the scroll-pages
        # help on its own around the game's "(1/3)"; each part fits the
        # window, but the window shows them all.
        listed = choosing(
            [
                command(
                    408,
                    [
                        "Watching the opening takes about twenty minutes from start to end."
                    ],
                    1,
                    _original="所要時間は二十分です。",
                    _rows=1,
                ),
                command(408, ["(1/3)"], 1),
                command(
                    408,
                    [
                        "We strongly recommend watching it all the way through on your first run."
                    ],
                    1,
                    _original="初回は見ることを推奨します。",
                    _rows=1,
                ),
            ],
            face="",
        )
        layout = Layout(30, 30, 74, 45, 4)
        report = fit_document({"list": listed}, "Map001.json", layout)
        rows = "\n".join(row["parameters"][0] for row in listed[5:8]).split("\n")
        self.assertEqual(rows[rows.index("(1/3)") - 1][-4:], "end.", rows)
        self.assertEqual(
            [(misfit["pointer"], misfit["reason"]) for misfit in report.misfits],
            [("/list/5/parameters/0", f"needs {len(rows)} rows; its window shows 4")],
        )
        # Help whose parts fit the window together is fitted as before.
        listed = choosing(
            [
                command(
                    408,
                    ["About twenty minutes."],
                    1,
                    _original="所要時間は二十分です。",
                ),
                command(408, ["(1/3)"], 1),
                command(
                    408,
                    ["Watch it first."],
                    1,
                    _original="初回は見ることを推奨します。",
                ),
            ],
            face="",
        )
        self.assertFalse(fit_document({"list": listed}, "Map001.json", layout).misfits)
        # A line too wide is named where it is written.
        listed[7]["parameters"] = ["See https://example.com/opening-guide"]
        self.assertEqual(
            [
                misfit["pointer"]
                for misfit in fit_document(
                    {"list": listed}, "Map001.json", layout
                ).misfits
            ],
            ["/list/7/parameters/0"],
        )

    def test_help_fitted_narrower_is_laid_out_again_once_the_width_grows(self):
        # Dialogue 60, then 45 (5 of 4 rows), then 60 again: the breaks the
        # fit at 45 wrote go, as if the help had been fitted at 60 directly.
        def translated():
            return choosing(
                [
                    command(
                        408,
                        ["Watching the opening takes about twenty minutes."],
                        1,
                        _original="所要時間は二十分です。",
                        _rows=1,
                    ),
                    command(408, ["(1/3)"], 1),
                    command(
                        408,
                        ["We strongly recommend watching it on your first run."],
                        1,
                        _original="初回は見ることを推奨します。",
                        _rows=1,
                    ),
                ],
                face="",
            )

        wide, narrow = Layout(60, 60, 74, 45, 4), Layout(45, 45, 74, 45, 4)
        direct = translated()
        self.assertFalse(fit_document({"list": direct}, "Map001.json", wide).changes)
        listed = translated()
        self.assertTrue(fit_document({"list": listed}, "Map001.json", narrow).misfits)
        report = fit_document({"list": listed}, "Map001.json", wide, resized=True)
        self.assertEqual(listed, direct)
        self.assertFalse(report.misfits)
        # A message's spare commands at the end are no part of its layout.
        message = [
            "The forest road is dangerous at",
            "night, so please be careful.",
            "",
        ]
        listed[1:2] = [command(401, [row]) for row in message]
        fit_document({"list": listed}, "Map001.json", wide, resized=True)
        self.assertEqual(
            [row["parameters"][0] for row in listed[1:4]],
            ["The forest road is dangerous at night, so please be careful.", "", ""],
        )
        del listed[2:4]
        # Rows a translator laid out are no layout of the fitter's: they stay.
        listed[7]["parameters"] = ["Watch it. It takes\nabout twenty\nminutes."]
        self.assertFalse(
            fit_document({"list": listed}, "Map001.json", wide, resized=True).changes
        )

    def test_message_paged_narrower_is_laid_out_again_once_the_width_grows(self):
        # At 45 the message takes two windows, the first filled with blank
        # rows; at 60 again it reads as if fitted at 60 directly.
        def translated(text, japanese):
            return [
                command(101, ["", 0, 0, 2, ""]),
                command(401, [text], _original=japanese),
                command(0, []),
            ]

        wide, narrow = Layout(60, 60, 74, 45, 4), Layout(45, 45, 74, 45, 4)
        for text, japanese in (
            (
                (
                    "Bandits wait by the old bridge tonight. Keep your sword ready. "
                    "The road through the forest is dangerous at night, and the "
                    "wolves come down from the hills whenever the moon is hidden "
                    "behind the clouds."
                ),
                "今夜は古い橋で盗賊が待っている。剣を構えておけ。",
            ),
            # A blank row the Japanese has is the author's, even where it ends
            # a page as the fitter's empty rows would.
            (
                (
                    "The road through the forest is dangerous at night, and the old "
                    "bridge has fallen. Keep your sword ready.\n\n"
                    "The village will take you in if you reach it before the rain "
                    "starts. Hurry now, and do not look back."
                ),
                "森の道は夜は危険です。\n\n村が迎えてくれます。",
            ),
        ):
            direct = translated(text, japanese)
            fit_document({"list": direct}, "Map001.json", wide)
            listed = translated(text, japanese)
            fit_document({"list": listed}, "Map001.json", narrow)
            self.assertNotEqual(listed, direct)
            fit_document({"list": listed}, "Map001.json", wide, resized=True)
            self.assertEqual(listed, direct)

    def test_assistant_led_writes_a_messages_spacing_as_guided_does(self):
        # Guided writes "! Who" and "Wait \|" into a message; Assistant-led's
        # writer wrote the assistant's "!Who" and "Wait\|" as they came.
        from util.len_originals import write_rpgmaker_json

        def page(rows):
            return {
                "list": [
                    command(101, ["", 0, 0, 2, ""]),
                    *(command(401, [row]) for row in rows),
                    command(105, [2, False]),
                    command(405, [rows[0]]),
                    command(0, []),
                ]
            }

        source = page(["\\SE[1]\\.あっ！誰？", "待って\\|", "……"])
        staged = page(["\\SE[1]\\.Ah!Who?", "Wait\\|", "……"])
        with tempfile.TemporaryDirectory() as folder:
            files = {
                name: Path(folder, name + ".json") for name in ("source", "staged")
            }
            files["source"].write_text(json.dumps(source, ensure_ascii=False), "utf-8")
            files["staged"].write_text(json.dumps(staged, ensure_ascii=False), "utf-8")
            game = Path(folder, "Map001.json")
            # The codes in front of it keep no space after them.
            for target, spaced in (
                ("English", ("\\SE[1]\\.Ah! Who?", "Wait \\|")),
                ("Japanese", ("\\SE[1]\\.Ah!Who?", "Wait\\|")),
            ):
                layout = Layout(60, 60, 74, 45, 4, target)
                write_rpgmaker_json(files["source"], files["staged"], game, layout)
                written = game.read_bytes()
                listed = json.loads(written)["list"]
                shown = "\n".join(blocks.text(listed[at]) for at in (1, 2, 3))
                for text in spaced:
                    self.assertIn(text, shown, target)
                self.assertEqual(blocks.text(listed[5]), spaced[0], target)
                # Writing it again changes nothing.
                write_rpgmaker_json(files["source"], files["staged"], game, layout)
                self.assertEqual(game.read_bytes(), written)
                game.unlink()

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

    def test_markers_come_only_from_the_plugin_entries_the_game_loads(self):
        # A repeated enabled entry of a plugin never loads, nor on MZ one
        # whose file name an earlier entry shares, so a marker only it lists
        # marks no comment players read, where Guided's Comment text looks.
        def choice_ex(name, marker):
            parameters = {"Choice Help Commands": json.dumps([marker])}
            return json.dumps({"name": name, "status": True, "parameters": parameters})

        games = {
            "mv": ("MPP_ChoiceEX", "MPP_ChoiceEX", False),
            "mz": ("Mine/MPP_ChoiceEX", "Other/MPP_ChoiceEX", True),
        }
        unused = [command(108, ["Unused"]), command(408, ["使われない"])]
        with tempfile.TemporaryDirectory() as folder:
            for kind, (first, repeat, mz) in games.items():
                game = Path(folder) / kind
                (game / "data").mkdir(parents=True)
                (game / "js").mkdir()
                if mz:
                    (game / "js/rmmz_core.js").write_text("", encoding="utf-8")
                entries = (
                    choice_ex(first, "ChoiceHelp") + ",\n" + choice_ex(repeat, "Unused")
                )
                (game / "js/plugins.js").write_text(
                    f"var $plugins =\n[\n{entries}\n];\n", encoding="utf-8"
                )
                (game / "data/Map001.json").write_text(
                    json.dumps({"events": [{"pages": [{"list": unused}]}]}),
                    encoding="utf-8",
                )
                for read in (game_plugins(game), data_plugins(game / "data")):
                    self.assertIn("ChoiceHelp", comment_markers(read), kind)
                    self.assertNotIn("Unused", comment_markers(read), kind)
                self.assertNotIn("Unused", comment_text.markers(game), kind)
                self.assertFalse(
                    comment_text.shows_comment_text(
                        game / "data", game / "js/plugins.js"
                    ),
                    kind,
                )
