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
                        # Japanese residue forces deep review, where it is declined.
                        line("朝だ", "It's 朝."),
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
            "name": "Potion",
            "description": "Restores HP.",
            "_original": {"name": "薬", "description": "体力を回復する。"},
        },
    ],
)
write("System.json", {"gameTitle": "Test"})

storage = temporary / "storage"
task, state = qa.prepare_task(game, data, "release", storage)
assert state["stage"] == "screen", state


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
    exceptions = [
        {
            "id": target["id"],
            "verdict": "suspect",
            "categories": ["meaning"],
            "note": "Stratum ordinal reads oddly.",
        }
        for target in screen_targets(bundle)
        if target["source"] == STRATUM["_original"]
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
        correction = corrections.get(item["source"])
        reviews.append(
            {
                "id": item["id"],
                "disposition": "actionable" if correction else "clean",
                "severity": "medium" if correction else None,
                "category": "terminology" if correction else "",
                "family_key": "",
                "motif_ids": [],
                "evidence": "Checked against the source and scene.",
                "correction": correction,
                "apply_identities": [],
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
        "ordinal", deep_result(row, {STRATUM["_original"]: "Rest on the First Stratum"})
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
qa.finalize(task, skip_declined=True)
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
assert [row["correction"] for row in findings["findings"]] == [
    "Rest on the First Stratum"
], findings["findings"]
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
