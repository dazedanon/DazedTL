"""Text QA's voice items: one speaker's lines read across scenes.

The builder takes plain lines, here an Assistant-led game's units, and Text
QA makes its items from a generated game whose speaker turns from lordly to
casual between two scenes. Plays every reviewer with fixed results, through
the engine's own commands: a task prepared before voice items goes on,
applies and undoes, and a line the voice item's reviewer reports is
corrected, applied and undone like any finding.
"""

import json
import sys
from pathlib import Path
from unittest import mock

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa
from util.qa import selection, voice

CHAR = (
    "シャル (Char) - Female. Lordly, old-fashioned speech: そなた → thou, "
    'whenever she addresses one person ("Thou art late."); no contractions.'
)
GLOSSARY = f"# Game Characters\n{CHAR}\nイリス (Iris) - Female\n商人 (Merchant) - Polite.\n"

# Lines no RPG Maker file holds: units of a script engine, their speaker
# named in Japanese, one text said twice, and more of one speaker than an
# item holds.
units = [
    {
        "id": f"first.ks/{number:03d}",
        "speaker": "シャル",
        "source": f"そなたに{number}度目の礼を言う。",
        "translation": f"I thank thee a {number}th time.",
        "scene": f"scenario/chapter{number // 10}.ks",
        "order": number,
        "unit": number,
    }
    for number in range(40)
]
units += [
    {**units[3], "order": 100},
    # Speakers the glossary gives no note, or too few lines, get no item.
    *({**unit, "id": "iris/" + unit["id"], "speaker": "イリス"} for unit in units),
    *({**unit, "id": "shop/" + unit["id"], "speaker": "Merchant"} for unit in units[:11]),
]
(item,), targets = voice.voice_items(reversed(units), GLOSSARY, line_limit=16)
assert (item["kind"], item["speaker"], item["note"]) == ("voice", "シャル", CHAR), item
assert (item["speaker_lines"], item["target_count"]) == (40, 16), item
held = [targets[line["id"]]["unit"] for line in item["lines"]]
# Spread from the first line to the last, in play order.
assert held == sorted(held) and (held[0], held[-1]) == (0, 39), held
assert len({line["scene"] for line in item["lines"]}) == 4, item["lines"]
assert item["lines"][1] == {
    "id": item["lines"][1]["id"],
    "scene": "scenario/chapter0.ks",
    "source": "そなたに3度目の礼を言う。",
    "translation": "I thank thee a 3th time.",
}, item["lines"][1]
# An item fits one bundle's characters, and only the most-spoken are read.
(small,), _targets = voice.voice_items(units, GLOSSARY, char_budget=4_000)
assert 12 <= small["target_count"] < 40, small["target_count"]
assert len(json.dumps(small, ensure_ascii=False)) <= 4_000
with mock.patch.object(voice, "SPEAKER_LIMIT", 0):
    assert voice.voice_items(units, GLOSSARY) == ([], {})

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)
(game / ".dazedtl").mkdir()
(game / ".dazedtl/glossary.txt").write_text(GLOSSARY, encoding="utf-8")
LORDLY = [
    ("そなたは何者じゃ？", "Who art thou?"),
    ("わらわはこの街の主じゃ。", "I am the master of this city."),
    ("そなたの名を聞こう。", "I would hear thy name."),
    ("うむ、よい名じゃ。", "Indeed, a fine name."),
    ("そなたに頼みがある。", "I have a request of thee."),
    ("ついて参れ。", "Follow me."),
]
CASUAL = [
    ("そなたは遅いのう。", "You're late."),
    ("わらわは待ちくたびれたぞ。", "I'm tired of waiting."),
    ("そなたの剣を見せよ。", "Show me your sword."),
    ("うむ、悪くない。", "Yeah, not bad."),
    ("そなたを信じておる。", "I believe in you."),
    ("では行くぞ。", "Okay, let's go."),
]
FIXES = {"You're late.": "Thou art late.", "Show me your sword.": "Show me thy sword."}


def command(code, parameters, original=None):
    entry = {"code": code, "indent": 0, "parameters": parameters}
    return entry if original is None else {**entry, "_original": original}


def named(lines):
    """Messages under a Show Text header that names their speaker."""
    return [
        entry
        for source, english in lines
        for entry in (
            command(101, ["", 0, 0, 2, "Char"], "シャル"),
            command(401, [english], source),
            command(101, ["", 0, 0, 2, "Iris"], "イリス"),
            command(401, ["I see."], "なるほど。"),
        )
    ]


def first_row(lines):
    """Messages whose first row is their speaker's nameplate."""
    return [
        entry
        for source, english in lines
        for entry in (
            command(101, ["", 0, 0, 2]),
            command(401, ["【Char】"], "【シャル】"),
            command(401, [english], source),
        )
    ]


def page(commands):
    return {"list": [*commands, command(0, [])]}


(data / "Map001.json").write_text(
    json.dumps(
        {
            "events": [
                None,
                {"id": 1, "pages": [page(named(LORDLY))]},
                {"id": 2, "pages": [page(first_row(CASUAL))]},
            ]
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")


def bundle_of(row):
    return json.loads(Path(row["path"]).read_text(encoding="utf-8"))


def accept(row, result):
    path = temporary / f"{row['id']}.json"
    path.write_text(
        json.dumps(
            {"bundle_id": row["id"], "bundle_sha256": row["sha256"], **result},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    qa.accept_result(task, path)


def review(reports):
    """Reviews the task to its end: screen reviewers report the targets of
    *reports* item kinds whose English FIXES corrects, deep review corrects
    them, and editorial accepts. Returns the bundles each stage read."""
    read = {"screen": [], "deep": []}
    claimed = True
    while claimed:
        claimed = False
        for worker in ("screen-a", "screen-b"):
            row = qa.next_bundle(task, worker)
            if row is None or not row["id"].startswith("screen"):
                if row:
                    qa.release_bundle(task, row["id"])
                continue
            claimed = True
            bundle = bundle_of(row)
            read["screen"].append(bundle)
            accept(
                row,
                {
                    "schema": qa.SCREEN_RESULT_SCHEMA,
                    "reviewed_all": True,
                    "exceptions": [
                        {
                            "id": line["id"],
                            "verdict": "suspect",
                            "categories": ["voice"],
                            "note": "Plain 'you' where her note fixes thou.",
                        }
                        for item in bundle["items"]
                        if item["kind"] in reports
                        for line in item["lines"]
                        if "id" in line and line["translation"] in FIXES
                    ],
                    "motif_reviews": [],
                    "lint_reviews": [],
                    "declined": [],
                },
            )
    # `next` moves the task on once deep review ends.
    while row := qa.next_bundle(task, "deep-a"):
        if not row["id"].startswith("deep"):
            qa.release_bundle(task, row["id"])
            break
        bundle = bundle_of(row)
        read["deep"].append((row, bundle))
        accept(
            row,
            {
                "schema": qa.DEEP_RESULT_SCHEMA,
                "reviews": [
                    {
                        "id": item["id"],
                        "disposition": "actionable",
                        "severity": "medium",
                        "category": "voice",
                        "family_key": "voice:char",
                        "motif_ids": [],
                        "summary": "Char says a plain 'you' here.",
                        "evidence": "Her glossary line fixes そなた as thou.",
                        "correction": FIXES[item["translation"]],
                        "apply_identities": [],
                        "editorial_basis": {
                            "defect": "Her register changes between scenes.",
                            "source_support": "The Japanese keeps そなた.",
                            "not_preference": True,
                        },
                    }
                    if item["translation"] in FIXES
                    else {
                        "id": item["id"],
                        "disposition": "clean",
                        "severity": None,
                        "category": "",
                        "family_key": "",
                        "motif_ids": [],
                        "evidence": "Checked against the source.",
                        "correction": None,
                        "apply_identities": [],
                    }
                    for item in bundle["items"]
                ],
            },
        )
    while row := qa.next_bundle(task, "editor-a"):
        accept(
            row,
            {
                "schema": qa.EDITORIAL_RESULT_SCHEMA,
                "reviews": [
                    {"id": item["id"], "verdict": "accept", "note": ""}
                    for item in bundle_of(row)["items"]
                ],
            },
        )
    assert qa.status(task)["stage"] == "complete", qa.status(task)
    return read


def game_text():
    events = json.loads((data / "Map001.json").read_text(encoding="utf-8"))["events"]
    return [
        entry["parameters"][0]
        for event in events[1:]
        for entry in event["pages"][0]["list"]
        if entry["code"] == 401
    ]


def apply_and_undo():
    """Applies the task's findings, which correct FIXES' lines, and undoes
    them through the engine's own correction maps."""
    findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
    ids = [finding["id"] for finding in findings["findings"]]
    assert sorted(finding["correction"] for finding in findings["findings"]) == sorted(
        FIXES.values()
    ), findings["findings"]
    inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
    before = game_text()
    for undo in (False, True):
        assert qa.apply_loaded_correction_map(
            task,
            json.loads((task / "task.json").read_text(encoding="utf-8")),
            qa.correction_map(task, ids, undo=undo),
            inventory,
            dry_run_name="dry-run.json",
            regression_name="regression.json",
        )["valid"]
        assert game_text() == (
            before if undo else [FIXES.get(text, text) for text in before]
        ), game_text()
    return findings


# A task prepared before voice items holds none. Preparing again goes on
# with it as it is, and it completes, applies and undoes.
with mock.patch.object(selection, "_voice_items", lambda *_args, **_more: ([], {})):
    before, state = qa.prepare_task(game, data, "release", temporary / "storage")
assert "voice" not in json.loads(
    (before / "checkpoint.json").read_text(encoding="utf-8")
)["screen"]
task, state = qa.prepare_task(game, data, "release", temporary / "storage")
assert task == before and state["screen"]["voice"] == {"items": 0, "lines": 0}, state
read = review({"scene"})
# No item of it puts her two scenes' lines together.
lordly, casual = ({source for source, _english in side} for side in (LORDLY, CASUAL))
for bundle in read["screen"]:
    for item in bundle["items"]:
        sources = {line["source"] for line in item["lines"]}
        assert item["kind"] == "scene", item
        assert not (sources & lordly and sources & casual), item
apply_and_undo()

# A task prepared now reads her lines from both scenes as one item, in play
# order under her glossary line, whichever way a scene names her.
task, state = qa.prepare_task(
    game, data, "release", temporary / "storage", earlier=False
)
assert task != before and state["screen"]["voice"] == {"items": 1, "lines": 12}, state
checkpoint = json.loads((task / "checkpoint.json").read_text(encoding="utf-8"))
(row,) = [
    row
    for row in checkpoint["screen"]["bundles"]
    if bundle_of(row)["items"][0]["kind"] == "voice"
]
(item,) = bundle_of(row)["items"]
assert [line["source"] for line in item["lines"]] == [
    source for source, _english in LORDLY + CASUAL
], item["lines"]
assert (item["speaker"], item["note"], item["speaker_lines"]) == ("Char", CHAR, 12), item
shown = qa.render_bundle(task, row["id"])
assert f"### VOICE {item['id']} Char (the speaker's 12 lines, in play order)" in shown
assert f"glossary: {CHAR}" in shown and shown.count("  -- Map001.json#/events/") == 2
assert f"[T {item['lines'][6]['id']}] JP: そなたは遅いのう。" in shown, shown
# Only the voice item's reviewer reports the casual lines; deep review reads
# each in its scene, marked, and its correction applies and undoes.
read = review({"voice"})
reviewed = [item for _row, bundle in read["deep"] for item in bundle["items"]]
assert sorted(item["translation"] for item in reviewed) == sorted(FIXES), reviewed
assert all(
    item["deep_reasons"] == ["voice-suspect"] and item["scenes"] for item in reviewed
), reviewed
shown = qa.render_bundle(task, read["deep"][0][0]["id"])
assert "voice review of Char [suspect] (voice): Plain 'you'" in shown, shown
assert ">>ITEM" in shown and CHAR in shown, shown
findings = apply_and_undo()
assert {finding["category"] for finding in findings["findings"]} == {"voice"}
print("ok")
