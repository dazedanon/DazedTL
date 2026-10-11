"""A game update carries a translation onto the new release by value."""

import json
import unittest

from tests.engine import engine_module

json_merge = engine_module("util/version_update/json_merge.py")


def prepared(value):
    return json.dumps(value, ensure_ascii=False, indent=4).encode("utf-8")


def line(text, original=None):
    command = {"code": 401, "indent": 0, "parameters": [text]}
    if original is not None:
        command["_original"] = original
    return command


def merged(base, translated, official):
    result = json_merge.merge_json(
        prepared(base), prepared(translated), prepared(official)
    )
    return None if result is None else json.loads(result)


class JsonMergeTests(unittest.TestCase):
    def test_lines_the_release_left_keep_their_translation_and_its_source(self):
        # Inserting beside a translated line conflicted by line and dropped
        # the translation; a line the release changed must come back to
        # Japanese without the old source note naming text no longer there.
        base = [line("おお、ミカよ。"), line("頼んだぞ。")]
        translated = [
            line("Oh, Mika.", "おお、ミカよ。"),
            line("I'm counting on you.", "頼んだぞ。"),
        ]
        official = [
            line("今日はいい天気じゃな。"),
            line("おお、ミカよ。"),
            line("頼んだぞ、ミカ。"),
        ]
        self.assertEqual(
            merged(base, translated, official),
            [line("今日はいい天気じゃな。"), translated[0], line("頼んだぞ、ミカ。")],
        )

    def test_a_record_keeps_the_fields_whose_translation_carries_over(self):
        # Field-keyed notes follow their fields; the release's other changes,
        # such as a price, come through.
        base = [None, {"id": 1, "name": "剣", "description": "普通の剣", "price": 100}]
        translated = [
            None,
            {
                "id": 1,
                "name": "Sword",
                "description": "An ordinary sword",
                "price": 100,
                "_original": {"name": "剣", "description": "普通の剣"},
            },
        ]
        official = [
            None,
            {"id": 1, "name": "剣", "description": "よく切れる剣", "price": 120},
        ]
        self.assertEqual(
            merged(base, translated, official),
            [
                None,
                {
                    "id": 1,
                    "name": "Sword",
                    "description": "よく切れる剣",
                    "price": 120,
                    "_original": {"name": "剣"},
                },
            ],
        )

    def test_files_that_cannot_line_up_by_value_are_left_to_the_line_merge(self):
        base = [line("おお、ミカよ。")]
        official = [line("おお、ミカよ。"), line("気をつけるのじゃぞ。")]
        # A translation that split a line into two changed the data's shape.
        split = [line("Oh,", "おお、ミカよ。"), line("Mika.")]
        self.assertIsNone(merged(base, split, official))
        # A release file in an engine's own layout is not reformatted.
        native = json.dumps(official, ensure_ascii=False).encode("utf-8")
        self.assertIsNone(
            json_merge.merge_json(prepared(base), prepared([line("Oh, Mika.")]), native)
        )
