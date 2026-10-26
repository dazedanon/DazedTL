"""Declined review items in the text QA engine, on a generated game.

Plays every reviewer with fixed results, so where a declined item or family
member goes, what its bundle leaves out and how the coverage report names it
are checked through the engine's own commands.
"""

import json
import shutil
import sys
from pathlib import Path
from unittest import mock

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa
from util.qa import prepare as qa_prepare
from util.qa import selection as qa_selection
from util.qa import storage as qa_storage

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
                    line("す゛ごい", "So ama'zing"),
                    line("ムラムラが止まらない", "The tingling won't stop."),
                ),
                event(
                    2,
                    speaker("店長", "Owner"),
                    line("や゛めて", "Sto'p"),
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


REASON = "Outside what this reviewer reviews."


def in_scenes(unit, scenes):
    place = unit.get("scene") or unit.get("representative_identity") or ""
    return any(place == scene or place.startswith(scene + "/") for scene in scenes)


def screen(row, declined_scenes=(), declined_items=()):
    """Review a screen bundle: flag the weather line and keep the joke and the
    lint fixes, but decline the named scenes with their proposals and
    variants, and the named items whole."""
    items = bundle_of(row)["items"]
    whole = [
        item["id"]
        for item in items
        if item.get("scene_id") in declined_scenes or item["id"] in declined_items
    ]
    reviewed = [item for item in items if item["id"] not in whole]
    units = [
        unit["id"]
        for item in reviewed
        for unit in item.get("proposals") or item.get("variants") or []
        if in_scenes(unit, declined_scenes)
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
                "exceptions": [
                    {
                        "id": target["id"],
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "Odd small talk.",
                    }
                    for item in reviewed
                    if item["kind"] == "scene"
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
                    for item in reviewed
                    if item["kind"] == "motif-family"
                ],
                "lint_reviews": [
                    {"id": item["id"], "rejected": [], "note": ""}
                    for item in reviewed
                    if item["kind"] == "lint-family"
                ],
                "declined": [
                    {"id": identity, "reason": REASON} for identity in whole + units
                ],
            },
        ),
    )


# Prepared as versions up to 2.34.3 did, its context naming the game folder,
# which a rebuild under new rules still reads as the same context.
with mock.patch.object(qa_selection, "in_game", lambda path, _root: path):
    task, _state = qa.prepare_task(game, data, "release", temporary / "storage")
lint, motif, scenes = rows("screen")
(lint_family,) = bundle_of(lint)["items"]
(motif_family,) = bundle_of(motif)["items"]
(owner_fix,) = [row for row in lint_family["proposals"] if row["current"] == "Sto'p"]
owner_scene = next(
    item["id"]
    for item in bundle_of(scenes)["items"]
    if item["scene_id"] == SCENE.format(2)
)
(owner_variant,) = [
    variant
    for variant in motif_family["variants"]
    if in_scenes(variant, [SCENE.format(2)])
]

# The coordinator read the scene bundle and the joke's family and declines the
# owner's scene and its variant before any worker claims them. The rest of
# each bundle moves to a new one in its place, so no worker sees what it
# declined, and the decline is the coordinator's.
declined = qa.decline_items(
    task, "coord", scenes["id"], [{"id": owner_scene, "reason": REASON}]
)
assert declined["remainder"]["id"] == "screen-0003-r2", declined
assert declined["declined"]["declined_by"] == ["coord"], declined
qa.decline_items(
    task, "coord", motif["id"], [{"id": owner_variant["id"], "reason": REASON}]
)
refused(lambda: qa.render_bundle(task, scenes["id"]), "screen-0003-r2")
refused(lambda: qa.context_view(task, SCENE.format(2)), "declined")
shown = qa.render_bundle(task, "screen-0003-r2")
assert WEATHER in shown and "や゛めて" not in shown, shown
assert "The urge is rising." not in qa.render_bundle(task, "screen-0002-r2")

# A worker on the coordinator's helper reviews the rest and declines one more
# scene, with the lint fix and the joke's variant from those scenes. What its
# helper declined waits for a reviewer on another helper and never comes back
# to it or to another worker on its helper, which only checks its screening.
while row := qa.next_bundle(task, "sub-1"):
    assert not row.get("declined_by"), row
    screen(row, {SCENE.format(2), SCENE.format(3)})
assert [
    row["id"]
    for row in rows("screen")
    if row.get("declined_by") and row["status"] == "pending"
] == [
    "screen-0003-d1",
    "screen-0002-d1",
    "screen-0001-d1",
    "screen-0002-d3",
    "screen-0003-d3",
], rows("screen")
# Lint review is over; the declined proposal waits for another helper.
assert qa.status(task)["screen"]["lint"] == {"accepted": 1, "total": 2, "declined": 1}
row = qa.next_bundle(task, "sub-2")
assert row["check_of"] == "screen-0003-r2", row
screen(row)
assert qa.next_bundle(task, "sub-2") is None
refused(lambda: qa.next_bundle(task, "sub-2", "screen-0003-d1"), "declined")
refused(lambda: qa.advance(task), "declined")
# A worker keeps the helper it started on.
refused(lambda: qa.next_bundle(task, "coord", helper="codex"), "helper")
# A worker on another helper reviews the owner's scene and variant but declines
# the lint fix too, which two helpers have declined now, so it is set aside.
for expected in ("screen-0003-d1", "screen-0002-d1", "screen-0001-d1"):
    row = qa.next_bundle(task, "other-1", helper="Codex")
    assert row["id"] == expected, row
    screen(row, declined_items={lint_family["id"] + "-d1"})
assert qa.status(task)["declined"] == {"waiting": 4, "set_aside": 1}
row = qa.next_bundle(task, "sub-1")
assert row["check_of"] == "screen-0003-d1", row
screen(row)
# With no worker on another helper for the rest, next sets it aside once the
# rest of screening is reviewed, and every target is accounted for.
assert qa.next_bundle(task, "sub-1") is None
row = qa.next_bundle(task, "sub-1", skip_declined=True)
assert qa.status(task)["declined"] == {"waiting": 0, "set_aside": 5}
checkpoint = json.loads((task / "checkpoint.json").read_text(encoding="utf-8"))
assert (
    checkpoint["screen"]["accepted_items"] + 5 == checkpoint["screen"]["total_items"]
), checkpoint["screen"]
# An update that bumps QA's rules version keeps this screen, declines and
# all: the coordinator's and reviewers' declines move the same items to the
# same bundles, and what was set aside is set aside again.
qa_storage.QA_RULES_VERSION = qa_prepare.QA_RULES_VERSION = qa.QA_RULES_VERSION + 1
rebuilt, state = qa.rebuild_deep_from_screen(task)
qa_storage.QA_RULES_VERSION = qa_prepare.QA_RULES_VERSION = qa.QA_RULES_VERSION
assert state["declined"] == {"waiting": 0, "set_aside": 5}, state
again = json.loads((rebuilt / "checkpoint.json").read_text(encoding="utf-8"))
assert [(row["id"], row["status"]) for row in again["screen"]["bundles"]] == [
    (row["id"], row["status"]) for row in checkpoint["screen"]["bundles"]
], again["screen"]["bundles"]
shutil.rmtree(rebuilt)

# A declined deep item waits too, and next sets it aside the same way.
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
(deep,) = [row for row in rows("deep") if row.get("declined_by")]
assert qa.next_bundle(task, "sub-1") is None
assert qa.next_bundle(task, "sub-1", skip_declined=True) is None
assert qa.status(task)["stage"] == "complete"

# Only the lint fix a reviewer judged became a finding, and the joke counts as
# reviewed once, on the variants its reviews covered.
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
assert [row["correction"] for row in findings["findings"]] == ["So amazing"], findings[
    "findings"
]
assert [(row["id"], row["variant_count"]) for row in findings["motif_families"]] == [
    (motif_family["id"], 1),
    (motif_family["id"] + "-d1", 1),
], findings["motif_families"]
assert qa.status(task)["screen"]["motif_families"] == {"accepted": 1, "total": 1}
# The report names who declined each item, and a family's declined part by its
# proposals or variants.
forest = next(
    item["id"]
    for item in bundle_of(scenes)["items"]
    if item["scene_id"] == SCENE.format(3)
)
(weather,) = bundle_of(deep)["items"]
assert [
    (row["id"], row["declined_by"], row["reasons"], row.get("units"))
    for row in findings["declined"]
] == [
    (
        motif_family["id"] + "-d3",
        ["sub-1"],
        [REASON],
        [
            variant["id"]
            for variant in motif_family["variants"]
            if in_scenes(variant, [SCENE.format(3)])
        ],
    ),
    (forest, ["sub-1"], [REASON], None),
    (
        lint_family["id"] + "-d1",
        ["other-1", "sub-1"],
        [REASON, REASON],
        [owner_fix["id"]],
    ),
    (weather["id"], ["sub-1"], ["Not reviewed."], None),
], findings["declined"]
# Only lines no reviewer judged are reported as not reviewed: the owner's
# scene was, by the other helper.
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
