"""Declined review items in the text QA engine, on a generated game.

Plays every reviewer with fixed results, so where a declined item goes and how
the coverage report names it are checked through the engine's own commands.
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


def line(original, text):
    return {"code": 401, "indent": 0, "parameters": [text], "_original": original}


def speaker(original, name):
    return {
        "code": 101,
        "indent": 0,
        "parameters": [name.lower(), 0, 0, 2, name],
        "_original": original,
    }


def event(number, *commands):
    end = {"code": 0, "indent": 0, "parameters": []}
    return {"id": number, "pages": [{"list": [*commands, end]}]}


WEATHER = "今日はいい天気だね"
SCENE = "Map001.json#/events/{}/pages/0/list"
(data / "Map001.json").write_text(
    json.dumps(
        {
            "events": [
                None,
                event(
                    1,
                    speaker("アリナ", "Arina"),
                    line(WEATHER, "Nice weather today."),
                    line("あっ…♥すごい", "Ah…♥Amazing"),
                    line("ムラムラが止まらない", "The tingling won't stop."),
                ),
                event(
                    2,
                    speaker("店長", "Owner"),
                    line("んっ…♥だめ", "Mm…♥No"),
                    line("ムラムラしてきた", "The urge is rising."),
                ),
                event(
                    3,
                    speaker("案内人", "Guide"),
                    line("ここは暗い森だ", "This is a dark forest."),
                    line("ムラムラ！", "Itchy!"),
                ),
                event(
                    4,
                    speaker("村人", "Villager"),
                    line("森の奥へ", "Into the forest."),
                    line("気をつけて", "Take care."),
                ),
            ]
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")
# A recurring joke, so the screen stage has a motif family across scenes.
(game / ".dazedtl/skills").mkdir(parents=True)
(game / ".dazedtl/skills/quirks.md").write_text(
    "- Running joke: ムラムラ keeps one English gag word.\n", encoding="utf-8"
)


def result_path(name, value):
    path = temporary / f"{name}.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def bundle_of(row):
    return json.loads(Path(row["path"]).read_text(encoding="utf-8"))


def rows(stage):
    checkpoint = json.loads((task / "checkpoint.json").read_text(encoding="utf-8"))
    return checkpoint[stage]["bundles"]


def refused(attempt, words):
    try:
        attempt()
    except ValueError as error:
        assert words in str(error), error
    else:
        raise AssertionError(f"Expected a refusal naming {words!r}.")


def screen(row, declined_scenes=()):
    """Review a screen bundle: flag the weather line, keep the joke and the
    lint fixes, and decline the named scenes."""
    items = bundle_of(row)["items"]
    qa.accept_result(
        task,
        result_path(
            row["id"],
            {
                "schema": qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": row["id"],
                "bundle_sha256": row["sha256"],
                "reviewed_all": True,
                "exceptions": [
                    {
                        "id": target["id"],
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "Odd small talk.",
                    }
                    for item in items
                    if item["kind"] == "scene"
                    and item["scene_id"] not in declined_scenes
                    for target in item["lines"]
                    if target.get("id") and target["source"] == WEATHER
                ],
                "motif_reviews": [
                    {
                        "id": item["id"],
                        "disposition": "preserved",
                        "note": "Each variant keeps the gag.",
                        "suspect_ids": [],
                    }
                    for item in items
                    if item["kind"] == "motif-family"
                ],
                "lint_reviews": [
                    {"id": item["id"], "rejected": [], "note": ""}
                    for item in items
                    if item["kind"] == "lint-family"
                ],
                "declined": [
                    {"id": item["id"], "reason": "Outside what this reviewer reviews."}
                    for item in items
                    if item.get("scene_id") in declined_scenes
                ],
            },
        ),
    )


task, _state = qa.prepare_task(game, data, "release", temporary / "storage")

# A worker declines two scenes; they wait for a reviewer on another helper and
# never go back to a worker on its own, which only checks the rest.
while row := qa.next_bundle(task, "sub-1"):
    screen(row, {SCENE.format(2), SCENE.format(3)})
(waiting,) = [row for row in rows("screen") if row.get("declined_by")]
assert waiting["declined_by"] == ["sub-1"], waiting
row = qa.next_bundle(task, "sub-2")
assert row["check_of"], row
screen(row)
assert qa.next_bundle(task, "sub-2") is None
refused(lambda: qa.next_bundle(task, "sub-2", waiting["id"]), "declined")
refused(lambda: qa.advance(task), "declined")
# A worker keeps the helper it started on.
refused(lambda: qa.next_bundle(task, "sub-1", helper="codex"), "helper")
# A worker on another helper takes them, reviews one scene and declines the
# other, which two helpers have declined now, so it is set aside.
row = qa.next_bundle(task, "other-1", helper="Codex")
assert row["id"] == waiting["id"], row
screen(row, {SCENE.format(3)})
assert qa.status(task)["declined"] == {"waiting": 0, "set_aside": 3}
row = qa.next_bundle(task, "sub-1")
assert row["check_of"] == waiting["id"], row
screen(row)

# A declined deep item waits too; with no worker on another helper, next sets
# it aside once the rest of its stage is reviewed, and carries QA to the end.
row = qa.next_bundle(task, "sub-1")
qa.accept_result(
    task,
    result_path(
        row["id"],
        {
            "schema": qa.DEEP_RESULT_SCHEMA,
            "bundle_id": row["id"],
            "bundle_sha256": row["sha256"],
            "reviews": [
                {"id": item["id"], "disposition": "declined", "reason": "Not reviewed."}
                for item in bundle_of(row)["items"]
            ],
        },
    ),
)
assert qa.next_bundle(task, "sub-1") is None
assert qa.next_bundle(task, "sub-1", skip_declined=True) is None
assert qa.status(task)["stage"] == "complete"
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
assert sorted(row["correction"] for row in findings["findings"]) == [
    "Ah…♥ Amazing",
    "Mm…♥ No",
], findings["findings"]
# The report names who declined each item.
assert [
    (row["stage"], row["declined_by"], row["reasons"]) for row in findings["declined"]
] == [
    (
        "screen",
        ["other-1", "sub-1"],
        ["Outside what this reviewer reviews."] * 2,
    ),
    ("deep", ["sub-1"], ["Not reviewed."]),
], findings["declined"]
assert {row["source"] for row in findings["not_reviewed"]} == {
    "案内人",
    "ここは暗い森だ",
    "ムラムラ！",
    WEATHER,
}, findings["not_reviewed"]

# A declined editorial item keeps the authors of its judgment correction, who
# still may not confirm it.
checkpoint = {"editorial": {"bundles": []}}
qa._split_declined(
    temporary,
    checkpoint,
    "editorial",
    {"id": "editorial-0001", "assigned_to": "editor-a", "round": 1},
    {"items": [{"id": "QA-0001", "ordinal": 1, "authors": ["deep-a"]}]},
    {"QA-0001": "Not reviewed."},
)
(split,) = checkpoint["editorial"]["bundles"]
assert (split["authors"], split["round"]) == (["deep-a"], 1), split
print("ok")
