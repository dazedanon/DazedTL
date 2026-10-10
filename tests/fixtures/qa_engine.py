"""A text QA journey through the engine's own commands on a generated game.

Plays every reviewer with fixed results, so the engine's bundles, gates and
findings are checked end to end without an assistant.
"""

import json
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)


def line(original, text, code=401):
    return {"code": code, "indent": 0, "parameters": [text], "_original": original}


def speaker(original, name, face="arina"):
    return {
        "code": 101,
        "indent": 0,
        "parameters": [face, 0, 0, 2, name],
        "_original": original,
    }


def page(*commands):
    return {"list": [*commands, {"code": 0, "indent": 0, "parameters": []}]}


def write(name, value):
    (data / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


STRATUM = line("第1層で休む", "Rest on Stratum 1")
AROUSAL = line("ムラムラが止まらない", "The Arousal won't stop.")
# The source shows Arina's header on the owner's line.
WELCOME = line("いらっしゃい、アリナちゃん", "Welcome, Arina-chan.")
SWORD = "攻撃力+5の剣"
write(
    "Map001.json",
    {
        "events": [
            None,
            {
                "id": 1,
                "pages": [
                    page(
                        speaker("アリナ", "Arina"),
                        STRATUM,
                        line("今日はいい天気だね", "Nice weather today."),
                        # Flags that are style, not defects, force no deep review.
                        line("討伐3体", "Three defeated."),
                        line("100%の力", "100% power"),
                        speaker("店長", "Owner", face="owner"),
                        line("よく来たね", "Glad you came."),
                        speaker("アリナ", "Arina"),
                        WELCOME,
                        # Japanese residue forces deep review, where it is declined.
                        line("朝だ", "It's 朝."),
                        # Two lint families, both accepted.
                        line("あっ…♥すごい", "Ah…h♥Amazing"),
                        # A deep correction whose sweep finds two more lines.
                        AROUSAL,
                        line("ムラムラしてきた…", "The Arousal is building…"),
                        line("ムラムラ！", "Arousal!"),
                        # A message never translated, so outside QA's inventory.
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                        {
                            "code": 401,
                            "indent": 0,
                            "parameters": ["まだ訳されていない"],
                        },
                    )
                ],
            },
            # The scene the screen reviewers decline.
            {
                "id": 2,
                "pages": [
                    page(
                        speaker("案内人", "Guide"),
                        line("ここは暗い森だ", "This is a dark forest."),
                        line("森の奥へ", "Into the 森."),
                    )
                ],
            },
        ]
    },
)
write(
    "Items.json",
    [
        None,
        {
            "id": 1,
            # The same word as a label, which the sweep leaves alone.
            "name": "Arousal",
            # A lint proposal the reviewer rejects.
            "description": "Restores HP.♥Yay",
            "_original": {"name": "ムラムラ", "description": "体力を回復する。♥"},
        },
    ],
)
write(
    "Weapons.json",
    [
        None,
        {
            "id": 1,
            "name": "Sword",
            "description": "A sword with Attack +5",
            "params": [0, 0, 8, 0, 0, 0, 0, 0],
            "price": 300,
            "_original": {"name": "剣", "description": SWORD},
        },
    ],
)
write("System.json", {"gameTitle": "Test"})
# Japanese QA cannot correct: a custom data file and a plugin parameter.
write("Synopsis.json", [{"text": "あらすじ"}])
(game / "js").mkdir()
(game / "js/plugins.js").write_text(
    "var $plugins =\n"
    + json.dumps(
        [
            {
                "name": "Prompt",
                "status": True,
                "parameters": {"text": "スキップしますか？"},
            }
        ],
        ensure_ascii=False,
    )
    + ";\n",
    encoding="utf-8",
)


def source(identity):
    inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
    return next(
        cluster["source"]
        for cluster in inventory["clusters"]
        if cluster["representative"] == identity
    )


storage = temporary / "storage"
task, state = qa.prepare_task(game, data, "release", storage)
assert state["stage"] == "screen", state
forced = json.loads((task / "checkpoint.json").read_text())["deep"]["candidate_reasons"]
assert {source(identity) for identity in forced} == {"朝だ", "森の奥へ"}, forced
assert state["preflight"] == {
    "untranslated": 1,
    "custom_data": 1,
    "plugin_parameters": 1,
}, state["preflight"]


def result_path(name, value):
    path = temporary / f"{name}.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def bundle_of(row):
    return json.loads(Path(row["path"]).read_text(encoding="utf-8"))


def screen_targets(bundle):
    for item in bundle["items"]:
        if item["kind"] == "scene":
            for target in item["lines"]:
                if "id" in target:
                    yield target
        elif item["kind"] == "cluster":
            yield item


def declined_scene(item):
    return item["kind"] == "scene" and "/events/2/" in item["scene_id"]


# Screening flags the stratum line and declines the forest scene; everything
# else is clean.
while row := qa.next_bundle(task, "screen-a"):
    bundle = bundle_of(row)
    declined = [
        {"id": item["id"], "reason": "Outside what this reviewer reviews."}
        for item in bundle["items"]
        if declined_scene(item)
    ]
    lint_reviews = [
        {
            "id": item["id"],
            "rejected": [
                proposal["id"]
                for proposal in item["proposals"]
                if proposal["current"] == "Restores HP.♥Yay"
            ],
            "note": "The item text keeps its house style.",
        }
        for item in bundle["items"]
        if item["kind"] == "lint-family"
    ]
    exceptions = [
        {
            "id": target["id"],
            "verdict": "suspect",
            "categories": ["meaning"],
            "note": "Stratum ordinal reads oddly.",
        }
        for target in screen_targets(bundle)
        if target["source"]
        in {STRATUM["_original"], AROUSAL["_original"], WELCOME["_original"], SWORD}
    ]
    qa.accept_result(
        task,
        result_path(
            row["id"],
            {
                "schema": qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": row["id"],
                "bundle_sha256": row["sha256"],
                "reviewed_all": True,
                "exceptions": exceptions,
                "motif_reviews": [],
                "lint_reviews": lint_reviews,
                "declined": declined,
            },
        ),
    )
# The declined scene moved to a bundle of its own that waits for another
# reviewer: never the one that declined it, and the stage cannot end early.
waiting = [
    row
    for row in json.loads((task / "checkpoint.json").read_text())["screen"]["bundles"]
    if row["status"] == "pending"
]
assert [row["declined_by"] for row in waiting] == [["screen-a"]], waiting
assert qa.status(task)["declined"]["waiting"] == 3
for attempt in (
    lambda: qa.next_bundle(task, "screen-a", waiting[0]["id"]),
    lambda: qa.advance(task),
):
    try:
        attempt()
    except ValueError as error:
        assert "declined" in str(error), error
    else:
        raise AssertionError("A declined bundle was handed back or skipped.")
# A second reviewer claims it by ID and declines too, which sets it aside.
row = qa.next_bundle(task, "screen-b", waiting[0]["id"])
qa.accept_result(
    task,
    result_path(
        row["id"],
        {
            "schema": qa.SCREEN_RESULT_SCHEMA,
            "bundle_id": row["id"],
            "bundle_sha256": row["sha256"],
            "reviewed_all": True,
            "exceptions": [],
            "motif_reviews": [],
            "declined": [
                {"id": item["id"], "reason": "Also declined."}
                for item in bundle_of(row)["items"]
            ],
        },
    ),
)
assert qa.status(task)["declined"] == {"waiting": 0, "set_aside": 3}
state = qa.advance(task)
assert state["stage"] == "deep", state
# Deep review and the context view leave the declined scene out, even its
# Japanese residue, which would otherwise force deep review.
try:
    qa.context_view(task, "Map001.json#/events/2/pages/0/list")
except ValueError as error:
    assert "declined" in str(error), error
else:
    raise AssertionError("The context view showed a declined scene.")
assert "第1層で休む" in qa.context_view(task, "Map001.json#/events/1/pages/0/list/1")


def deep_result(row, corrections):
    bundle = bundle_of(row)
    reviews = []
    for item in bundle["items"]:
        if item["source"] == "朝だ":
            reviews.append(
                {"id": item["id"], "disposition": "declined", "reason": "Not reviewed."}
            )
            continue
        if item["source"] == WELCOME["_original"]:
            reviews.append(
                {
                    "id": item["id"],
                    "disposition": "actionable",
                    "severity": "high",
                    "category": "speaker",
                    "family_key": "",
                    "motif_ids": [],
                    "evidence": "The owner greets Arina; the header shows Arina.",
                    "correction": None,
                    "apply_identities": item["identities"][:1],
                    "source_fix": {
                        "kind": "show-text",
                        "face_name": "owner",
                        "face_index": 0,
                        "name": "Owner",
                    },
                }
            )
            continue
        correction = corrections.get(item["source"])
        sweep = (
            {"find": "Arousal", "replace": "arousal", "source_has": "ムラムラ"}
            if correction and item["source"] == AROUSAL["_original"]
            else None
        )
        reviews.append(
            {
                "id": item["id"],
                "disposition": "actionable" if correction else "clean",
                "severity": "medium" if correction else None,
                "category": ("voice" if sweep else "terminology") if correction else "",
                "family_key": "term:ムラムラ" if sweep else "",
                "sweep": sweep,
                **(
                    {"source_fix": {"kind": "database-numbers"}}
                    if item["source"] == SWORD and correction
                    else {}
                ),
                **(
                    {
                        "editorial_basis": {
                            "defect": "A gauge name reads as a proper noun in speech.",
                            "source_support": "ムラムラ is a feeling here.",
                            "not_preference": True,
                        }
                    }
                    if sweep
                    else {}
                ),
                "motif_ids": [],
                "evidence": "Checked against the source and scene.",
                "correction": correction,
                # A database number fix names the entries it changes.
                "apply_identities": item["identities"]
                if item["source"] == SWORD and correction
                else [],
            }
        )
    return {
        "schema": qa.DEEP_RESULT_SCHEMA,
        "bundle_id": row["id"],
        "bundle_sha256": row["sha256"],
        "reviews": reviews,
    }


row = qa.next_bundle(task, "deep-a")
assert "森の奥へ" not in {item["source"] for item in bundle_of(row)["items"]}
# The scene prints once, marking the lines its items' screen evidence names.
shown = qa.render_bundle(task, row["id"])
assert shown.count("## SCENE S1") == 1 and ">>ITEM" in shown, shown
# A correction that would trip the post-apply regression is refused when it
# is submitted, so it can never reach findings or roll back an apply.
try:
    qa.accept_result(
        task,
        result_path(
            "wrong-number",
            deep_result(row, {STRATUM["_original"]: "Rest on Stratum 2"}),
        ),
    )
except qa.QAResultError as error:
    assert "visible-number-mismatch" in str(error), error
else:
    raise AssertionError("A correction that changes a number was accepted.")
# An ordinal word stands for the source's number.
qa.accept_result(
    task,
    result_path(
        "ordinal",
        deep_result(
            row,
            {
                STRATUM["_original"]: "Rest on the First Stratum",
                AROUSAL["_original"]: "The arousal won't stop.",
                # The entry's attack is 8, so the description may say so.
                SWORD: "A sword with Attack +8",
            },
        ),
    ),
)
assert qa.next_bundle(task, "deep-a") is None
# With no other reviewer for the declined deep item, finalize reports it as
# not reviewed only when asked to.
try:
    qa.finalize(task)
except ValueError as error:
    assert "--skip-declined" in str(error), error
else:
    raise AssertionError("Finalize skipped a declined bundle silently.")
state = qa.finalize(task, skip_declined=True)
# The sweep rule found the other dialogue lines with the word, not the label;
# its reviewer accepts one and rejects the sentence start.
assert state["stage"] == "sweep", state
row = qa.next_bundle(task, "sweep-a")
(family,) = bundle_of(row)["items"]
assert sorted(row["current"] for row in family["candidates"]) == [
    "Arousal!",
    "The Arousal is building…",
], family
qa.accept_result(
    task,
    result_path(
        "sweep",
        {
            "schema": qa.SWEEP_RESULT_SCHEMA,
            "bundle_id": row["id"],
            "bundle_sha256": row["sha256"],
            "reviews": [
                {
                    "id": family["id"],
                    "rejected": [
                        candidate["id"]
                        for candidate in family["candidates"]
                        if candidate["current"] == "Arousal!"
                    ],
                    "note": "A sentence start keeps its capital.",
                }
            ],
        },
    ),
)
qa.record_decision(
    task,
    "stratum names",
    "Strata are ordinal titles",
    "deep-a",
    source="第1層",
    translation="First Stratum",
)
state = qa.finalize(task)
assert state["stage"] == "editorial", state


def editorial(row, verdicts):
    reviews = []
    for item in bundle_of(row)["items"]:
        verdict, replacement = verdicts.get(item["finding"]["source"], ("accept", None))
        reviews.append(
            {
                "id": item["id"],
                "verdict": verdict,
                "note": "Checked."
                if verdict != "accept" or item.get("conflicts")
                else "",
                **({"replacement": replacement} if replacement else {}),
            }
        )
    qa.accept_result(
        task,
        result_path(
            row["id"],
            {
                "schema": qa.EDITORIAL_RESULT_SCHEMA,
                "bundle_id": row["id"],
                "bundle_sha256": row["sha256"],
                "reviews": reviews,
            },
        ),
    )
    return bundle_of(row)


# The author of a voice correction, and of its sweep, never confirms it.
rows = json.loads((task / "checkpoint.json").read_text())["editorial"]["bundles"]
judged = next(row for row in rows if row["authors"])
assert judged["authors"] == ["deep-a", "sweep-a"], judged
assert qa.next_bundle(task, "deep-a")["id"] != judged["id"]
qa.release_bundle(task, next(row["id"] for row in rows if not row["authors"]))
try:
    qa.next_bundle(task, "deep-a", judged["id"])
except ValueError as error:
    assert "independent" in str(error), error
else:
    raise AssertionError("A correction's author claimed its editorial pass.")
# A revision that breaks the recorded decision comes back in a second round.
while row := qa.next_bundle(task, "editor-a"):
    editorial(row, {STRATUM["_original"]: ("revise", "Rest on the first stratum")})
state = qa.finalize(task)
assert state["stage"] == "editorial" and state["editorial"]["round"] == 2, state
(second,) = editorial(
    qa.next_bundle(task, "editor-a"),
    {STRATUM["_original"]: ("revise", "Rest on the First Stratum")},
)["items"]
assert any("decision" in conflict["key"] for conflict in second["conflicts"]), second
state = qa.finalize(task)
assert state["stage"] == "complete", state
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
# Accepted lint families combine into one correction; a rejected one is left out.
assert sorted(row["correction"] for row in findings["findings"]) == [
    "A sword with Attack +8",
    "Ah…♥ Amazing",
    "Owner · owner 0",
    "Rest on the First Stratum",
    "The arousal is building…",
    "The arousal won't stop.",
], findings["findings"]
# Source fixes go through the same correction map, apply and regression the
# app runs on its disposable copy; this game is the test's own copy.
selected = qa.correction_map(task, [row["id"] for row in findings["findings"]])
inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
assert qa._apply_loaded_correction_map(
    task,
    json.loads((task / "task.json").read_text(encoding="utf-8")),
    selected,
    inventory,
    dry_run_name="dry-run.json",
    regression_name="regression.json",
    nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
)["valid"]
headers = [
    command["parameters"]
    for command in json.loads((data / "Map001.json").read_text())["events"][1]["pages"][
        0
    ]["list"]
    if command["code"] == 101
]
assert ["owner", 0, 0, 2, "Owner"] in headers[2:], headers
assert qa.status(task)["screen"]["lint"] == {"accepted": 3, "total": 3}
# The declined scene is a coverage gap, reported once with its reasons.
assert [item["reasons"] for item in findings["declined"]] == [
    ["Outside what this reviewer reviews.", "Also declined."],
    ["Not reviewed."],
], findings["declined"]
assert {row["source"] for row in findings["not_reviewed"]} == {
    "案内人",
    "ここは暗い森だ",
    "森の奥へ",
    "朝だ",
}, findings["not_reviewed"]
print("ok")
