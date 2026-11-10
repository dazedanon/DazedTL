"""Text QA's review of an Assistant-led game on an engine it can't read,
from the game's units and their English (util/qa/units).

Before, Text QA read RPG Maker data alone, so such a game got only the
text-only checks. A TyranoScript-like game's units now make the same task:
scenes in play order with their speakers and both languages, its main
speaker's voice across scenes, observations and scene corrections naming
units, and findings whose corrections name the units they change. Plays
every reviewer with fixed results through the engine's own commands.
"""

import json
import sys
from pathlib import Path
from unittest import mock

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa
from util.qa import prepare, storage, units

CHAR = (
    "シャル (Char) - Female. Lordly, old-fashioned speech: そなた → thou, "
    'whenever she addresses one person ("Thou art late."); no contractions.'
)
GLOSSARY = f"# Game Characters\n{CHAR}\nリリ (Lili) - Female\n"
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


def scene(name, spoken):
    """A scenario file's units: Char's lines, each answered by Lili."""
    return [
        unit
        for number, (source, english) in enumerate(spoken)
        for unit in (
            {"id": f"{name}/{2 * number:03d}", "speaker": "シャル",
             "source": source, "translation": english},
            {"id": f"{name}/{2 * number + 1:03d}", "speaker": "リリ",
             "source": "なるほど。", "translation": "I see."},
        )
    ]


lines = [
    {"scene": "scenario/first.ks", "group": "scenario/first.ks", "kind": "dialogue",
     "field": None, **unit}
    for unit in scene("first.ks", LORDLY)
] + [
    {"scene": "scenario/second.ks", "group": "scenario/second.ks", "kind": "dialogue",
     "field": None, **unit}
    for unit in scene("second.ks", CASUAL)
] + [
    # A menu table, read as database text rather than a scene, and a line
    # not translated yet, which keeps the numbers of the lines after it.
    {"id": "menu/1", "scene": "menu", "group": "system", "kind": "ui",
     "speaker": None, "field": "database.item", "source": "薬草",
     "translation": "Herb"},
    {"id": "menu/2", "scene": "menu", "group": "system", "kind": "ui",
     "speaker": None, "field": "database.item", "source": "毒消し",
     "translation": None},
    {"id": "menu/3", "scene": "menu", "group": "system", "kind": "ui",
     "speaker": None, "field": "database.item", "source": "聖水",
     "translation": "Holy Water"},
]

manifest = units.inventory(lines, "release")
assert units.verify(manifest)["valid"], units.verify(manifest)
records = {record["identity"]: record for record in manifest["records"]}
assert len(records) == 26 and "menu/2" not in records, sorted(records)
assert (records["menu/3"]["classification"], records["menu/3"]["position"]) == (
    "database",
    2,
), records["menu/3"]
assert records["second.ks/004"]["order"] == 16, records["second.ks/004"]
# A focus reads its own lines, whatever the rest.
assert {
    record["classification"] for record in units.inventory(lines, "dialogue")["records"]
} == {"dialogue"}
assert not units.inventory(lines, "risky-codes")["records"]

game = temporary / "game"
work = game / ".dazedtl/len-method/work"
work.mkdir(parents=True)
(game / ".dazedtl/glossary.txt").write_text(GLOSSARY, encoding="utf-8")
# Nothing in the work folder is game data, whatever its name.
(work / "Map001.json").write_text("not json", encoding="utf-8")
task, state = qa.prepare_task(game, work, "release", temporary / "storage", inventory=manifest)
task_json = json.loads((task / "task.json").read_text(encoding="utf-8"))
assert units.of_task(task_json) and task_json["counts"]["records"] == 26, task_json
assert state["screen"]["voice"] == {"items": 1, "lines": 12, "speakers": ["Char"]}, state
assert "Units: this game's engine" in (task / "README.md").read_text(encoding="utf-8")
# The same units prepare the same task; changed English makes another.
again, _state = qa.prepare_task(game, work, "release", temporary / "storage", inventory=manifest)
assert again == task, again
changed = units.inventory(
    [{**line, "translation": "Hi."} if line["id"] == "menu/1" else line for line in lines],
    "release",
)
assert not qa.inventory_matches(task, changed) and qa.inventory_matches(task, manifest)


def bundle_of(row):
    return json.loads(Path(row["path"]).read_text(encoding="utf-8"))


checkpoint = json.loads((task / "checkpoint.json").read_text(encoding="utf-8"))
items = [
    item
    for row in checkpoint["screen"]["bundles"]
    for item in bundle_of(row)["items"]
]
scenes = {item["scene_id"]: item for item in items if item["kind"] == "scene"}
assert set(scenes) == {"scenario/first.ks", "scenario/second.ks"}, set(scenes)
second = scenes["scenario/second.ks"]["lines"]
# Each line in play order with its speaker, both languages, its unit and its
# number in the scene.
assert [(line["unit"], line["command"]) for line in second] == [
    (f"second.ks/{number:03d}", number) for number in range(12)
], second
assert {key: second[0][key] for key in ("speaker", "source", "translation")} == {
    "speaker": "シャル",
    "source": "そなたは遅いのう。",
    "translation": "You're late.",
}, second[0]
assert all("event_code" not in line for line in second), second
(voice,) = [item for item in items if item["kind"] == "voice"]
assert [line["source"] for line in voice["lines"]] == [
    source for source, _english in [*LORDLY, *CASUAL]
], voice["lines"]
assert {item["id"] for item in items if item["kind"] == "cluster"} >= {
    "menu/1",
    "menu/3",
}, items
(row,) = [
    row
    for row in checkpoint["screen"]["bundles"]
    if any(item.get("scene_id") == "scenario/second.ks" for item in bundle_of(row)["items"])
]
shown = qa.render_bundle(task, row["id"])
assert "   #0 [T " in shown and "(second.ks/000) JP: <シャル> そなたは遅いのう。" in shown, shown
assert "EN: You're late." in shown, shown
# Context names a line by its unit, and reads no game file.
context = qa.context_view(task, "second.ks/004")
assert context.splitlines()[0] == "scenario/second.ks lines 0-11", context
assert ">>#4 (second.ks/004) JP=<シャル> そなたの剣を見せよ。 EN=Show me your sword." in context, context


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


def clean(item):
    return {
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


# Screen: the voice item's reviewer reports her casual lines; the second
# scene's reviewer observes Lili's line in the first scene by its unit.
observed = False
while row := qa.next_bundle(task, "screen-a") or qa.next_bundle(task, "screen-b"):
    if not row["id"].startswith("screen"):
        qa.release_bundle(task, row["id"])
        break
    bundle = bundle_of(row)
    exceptions = [
        {"id": line["id"], "verdict": "suspect", "categories": ["voice"],
         "note": "Plain 'you' where her note fixes thou."}
        for item in bundle["items"] if item["kind"] == "voice"
        for line in item["lines"] if line["translation"] in FIXES
    ]
    observations = []
    if not observed and any(item.get("kind") == "scene" for item in bundle["items"]):
        observed = True
        own = {
            line.get("unit") for item in bundle["items"] for line in item.get("lines") or []
        }
        other = "first.ks/001" if "first.ks/001" not in own else "second.ks/001"
        observations = [
            {"identity": other, "categories": ["fluency"], "note": "Flat reply."}
        ]
    accept(row, {
        "schema": qa.SCREEN_RESULT_SCHEMA,
        "reviewed_all": True,
        "exceptions": exceptions,
        "motif_reviews": [],
        "lint_reviews": [
            {"id": item["id"], "rejected": [], "note": ""}
            for item in bundle["items"] if item["kind"] == "lint-family"
        ],
        "declined": [],
        "observations": observations,
    })
assert observed
# Deep: the first casual line's review corrects both her casual lines of its
# scene together, named by their numbers there; the rest are clean.
reviewed = []
while row := qa.next_bundle(task, "deep-a"):
    if not row["id"].startswith("deep"):
        qa.release_bundle(task, row["id"])
        break
    bundle = bundle_of(row)
    reviews = []
    for item in bundle["items"]:
        reviewed.append(item)
        if item["translation"] == "You're late.":
            (key,) = [
                key for key, value in bundle["scenes"].items()
                if value["scene_id"] == "scenario/second.ks"
            ]
            reviews.append({
                **clean(item),
                "disposition": "actionable",
                "severity": "medium",
                "category": "voice",
                "family_key": "voice:char",
                "summary": "Char says a plain 'you' here.",
                "evidence": "Her glossary line fixes そなた as thou.",
                "editorial_basis": {
                    "defect": "Her register changes between scenes.",
                    "source_support": "The Japanese keeps そなた.",
                    "not_preference": True,
                },
                "scene_correction": {
                    "scene": key,
                    "lines": [
                        {"command": 0, "current": "You're late.",
                         "correction": FIXES["You're late."]},
                        {"command": 4, "current": "Show me your sword.",
                         "correction": FIXES["Show me your sword."]},
                    ],
                },
            })
        elif item["translation"] in FIXES:
            reviews.append({**clean(item), "evidence": "The scene correction fixes it."})
        else:
            reviews.append(clean(item))
    accept(row, {"schema": qa.DEEP_RESULT_SCHEMA, "reviews": reviews})
assert {item["translation"] for item in reviewed} >= {*FIXES, "I see."}, reviewed
while row := qa.next_bundle(task, "editor-a"):
    if row["id"].startswith("sweep"):
        accept(row, {"schema": qa.SWEEP_RESULT_SCHEMA, "reviews": [
            {"id": item["id"], "rejected": [], "note": ""}
            for item in bundle_of(row)["items"]
        ], "declined": []})
        continue
    shown = qa.render_bundle(task, row["id"])
    assert "(second.ks/004) JP: <シャル> そなたの剣を見せよ。" in shown, shown
    accept(row, {
        "schema": qa.EDITORIAL_RESULT_SCHEMA,
        "reviews": [
            {"id": item["id"], "verdict": "accept", "note": ""}
            for item in bundle_of(row)["items"]
        ],
    })
assert qa.status(task)["stage"] == "complete", qa.status(task)
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
(finding,) = findings["findings"]
assert finding["kind"] == "scene" and finding["category"] == "voice", finding
# The correction names the units it changes, with their English now and then.
operations = qa.correction_map(task, [finding["id"]])["operations"]
assert [
    (row["identity"], row["expected"], row["replacement"]) for row in operations
] == [
    ("second.ks/000", "You're late.", "Thou art late."),
    ("second.ks/004", "Show me your sword.", "Show me thy sword."),
], operations
undo = qa.correction_map(task, [finding["id"]], undo=True)["operations"]
assert [(row["expected"], row["replacement"]) for row in undo] == [
    ("Thou art late.", "You're late."),
    ("Show me thy sword.", "Show me your sword."),
], undo
assert findings["not_translated"]["total"] == 0, findings["not_translated"]

# Once QA's rules change, the finished screen carries over to a task of the
# same units under the new rules.
with (
    mock.patch.object(prepare, "QA_RULES_VERSION", 6),
    mock.patch.object(storage, "QA_RULES_VERSION", 6),
):
    rebuilt, state = qa.rebuild_deep_from_screen(task)
assert rebuilt != task and state["stage"] != "screen", state
assert units.of_task(json.loads((rebuilt / "task.json").read_text(encoding="utf-8")))
print("ok")
