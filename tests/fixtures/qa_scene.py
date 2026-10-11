"""Scene corrections in the text QA engine, on a generated game.

Plays every reviewer with fixed results, so a deep review that corrects
several lines of one scene is checked from its result to its apply and undo
through the engine's own commands.
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


def page(*commands):
    narration = {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]}
    end = {"code": 0, "indent": 0, "parameters": []}
    return {"list": [narration, *commands, end]}


# Narration that turns present at the door, so moving one line only moves the
# switch. The second line also has the wrong pronoun, which its own correction
# fixes everywhere, and the last needs a lint fix.
DOOR = line("扉が開く", "The door opens.")
INSIDE = line("彼女は中に入る", "He steps inside.")
ROOM = line("部屋は暗い♥静か", "The room is dark.♥So quiet.")
NARRATION = page(
    line("彼女は森を歩いた", "She walked through the woods."), DOOR, INSIDE, ROOM
)
# A scene with a line the deep reviewer declines.
INN = line("宿で休む", "Rest at the inn.")
(data / "Map001.json").write_text(
    json.dumps(
        {
            "events": [
                None,
                {
                    "id": 1,
                    "pages": [
                        page(
                            INN,
                            line("今日はいい天気だね", "Nice weather today."),
                            line("朝だ", "It's 朝."),
                        )
                    ],
                },
                # The narration, an exact copy of it, and the second line alone.
                {"id": 2, "pages": [NARRATION]},
                {"id": 3, "pages": [NARRATION]},
                {"id": 4, "pages": [page(INSIDE)]},
            ]
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")
task, _state = qa.prepare_task(game, data, "release", temporary / "storage")
FLAGGED = {DOOR["_original"], INSIDE["_original"], INN["_original"], "朝だ"}


def result_path(name, value):
    path = temporary / f"{name}.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def bundle_of(row):
    return json.loads(Path(row["path"]).read_text(encoding="utf-8"))


def refused(result, words):
    try:
        qa.accept_result(task, result_path("refused", result))
    except qa.QAResultError as error:
        assert words in str(error), error
    else:
        raise AssertionError(f"Expected a refusal naming {words!r}.")


# Two reviewers screen every bundle and check each other's, flagging the
# narration's first present line, the pronoun, the inn and the residue.
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
                            "categories": ["fluency"],
                            "note": "Reads oddly in its scene.",
                        }
                        for item in bundle["items"]
                        if item["kind"] == "scene"
                        for target in item["lines"]
                        if "id" in target and target["source"] in FLAGGED
                    ],
                    "motif_reviews": [],
                    "lint_reviews": [
                        {"id": item["id"], "rejected": [], "note": ""}
                        for item in bundle["items"]
                        if item["kind"] == "lint-family"
                    ],
                    "declined": [],
                },
            ),
        )
row = qa.next_bundle(task, "deep-a")
assert row["id"].startswith("deep") and qa.status(task)["stage"] == "deep", row
bundle = bundle_of(row)
items = {item["source"]: item for item in bundle["items"]}
# The bundle prints each scene line under its event command.
shown = qa.render_bundle(task, row["id"])
assert "#2 >>ITEM" in shown and "#3 >>ITEM" in shown, shown


def scene_review(source, fixes, scene=None):
    """A scene correction of the lines of the item's scene that `fixes` names
    by their current text."""
    item = items[source]
    key = scene or item["scenes"][0]
    return {
        "id": item["id"],
        "disposition": "actionable",
        "severity": "medium",
        "category": "fluency",
        "family_key": "narration-tense",
        "motif_ids": [],
        "evidence": "The narration turns present partway through.",
        "correction": None,
        "apply_identities": [],
        "editorial_basis": {
            "defect": "The tense changes within one continuous action.",
            "source_support": "The scene opens in the past tense.",
            "not_preference": True,
        },
        "scene_correction": {
            "scene": key,
            "lines": [
                {
                    "command": shown_line["command"],
                    "current": shown_line["translation"],
                    "correction": fixes[shown_line["translation"]],
                }
                for shown_line in bundle["scenes"][key]["lines"]
                if shown_line["translation"] in fixes
            ],
        },
    }


def deep_result(scene):
    """`scene` for its item, the residue declined, the pronoun fixed
    everywhere, and the rest clean."""
    reviews = []
    for source, item in items.items():
        if item["id"] == scene["id"]:
            reviews.append(scene)
        elif source == "朝だ":
            reviews.append(
                {"id": item["id"], "disposition": "declined", "reason": "Not reviewed."}
            )
        else:
            correction = "She steps inside." if source == INSIDE["_original"] else None
            reviews.append(
                {
                    "id": item["id"],
                    "disposition": "actionable" if correction else "clean",
                    "severity": "high" if correction else None,
                    "category": "meaning" if correction else "",
                    "family_key": "",
                    "motif_ids": [],
                    "evidence": "彼女 is Arina, not a man."
                    if correction
                    else "Checked against the source.",
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


RETENSED = {
    "The door opens.": "The door opened.",
    "He steps inside.": "She stepped inside.",
    "The room is dark.♥So quiet.": "The room was dark.♥So quiet.",
}
# Each line passes apply's checks, is named by the command and text the scene
# prints, and lies outside what reviewers declined: this result declines the
# residue, whose scene the inn shares.
misnamed = scene_review(DOOR["_original"], RETENSED)
misnamed["scene_correction"]["lines"][0]["command"] += 1
for scene, words in (
    (
        scene_review(
            DOOR["_original"], {**RETENSED, ROOM["parameters"][0]: "It was dark at 9."}
        ),
        "visible-number-mismatch",
    ),
    (misnamed, "check the command number"),
    (
        scene_review(
            INN["_original"],
            {
                "Rest at the inn.": "We rested at the inn.",
                "Nice weather today.": "Nice weather, today.",
            },
        ),
        "declined",
    ),
):
    refused(deep_result(scene), words)
qa.accept_result(
    task, result_path(row["id"], deep_result(scene_review(DOOR["_original"], RETENSED)))
)
state = qa.finalize(task, skip_declined=True)
assert state["stage"] == "editorial", state


def editorial(row, scene_verdict):
    reviews = []
    for item in bundle_of(row)["items"]:
        verdict, revision = (
            scene_verdict
            if item["finding"].get("kind") == "scene"
            else ("accept", None)
        )
        reviews.append(
            {
                "id": item["id"],
                "verdict": verdict,
                "note": "Checked."
                if verdict != "accept" or item.get("conflicts")
                else "",
                **({"replacements": revision} if revision else {}),
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
    return bundle_of(row)["items"]


# Editorial reads the whole scene with each fix, and revises one line by its
# command and text. The pronoun fix also corrects a line the scene correction
# changes, so the scene correction comes back until a round accepts it.
row = qa.next_bundle(task, "editor-a")
assert "SCENE CORRECTION of 3 lines" in qa.render_bundle(task, row["id"])
revision = [
    {"command": 2, "current": "The door opens.", "replacement": "The door swung open."}
]
first = editorial(row, ("revise", revision))
while row := qa.next_bundle(task, "editor-a"):
    if row.get("round", 1) == 1:
        first += editorial(row, ("revise", revision))
        continue
    (second,) = editorial(row, ("accept", None))
    assert [conflict["key"].split(":")[0] for conflict in second["conflicts"]] == [
        "overlap"
    ], second
assert qa.status(task)["stage"] == "complete"
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
(scene,) = [row for row in findings["findings"] if row.get("kind") == "scene"]
(inside,) = [row for row in findings["findings"] if row.get("kind") != "scene"]
# The correction keeps its revision and its last line's lint fix, covers both
# copies of the scene, and replaces the pronoun fix there; the lint fix's own
# finding is gone, and the pronoun fix keeps the line outside the scene.
assert [line["correction"] for line in scene["lines"]] == [
    "The door swung open.",
    "She stepped inside.",
    "The room was dark.♥ So quiet.",
], scene
assert len(scene["target_identities"]) == 6, scene
assert [identity.split("/")[2] for identity in inside["target_identities"]] == ["4"]
assert findings["superseded"] == [
    {"id": inside["id"], "by": [scene["id"]], "places": 2}
], findings["superseded"]
inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))


def apply(document):
    return qa._apply_loaded_correction_map(
        task,
        json.loads((task / "task.json").read_text(encoding="utf-8")),
        document,
        inventory,
        dry_run_name="dry-run.json",
        regression_name="regression.json",
        nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    )["valid"]


def text(event, original):
    commands = json.loads((data / "Map001.json").read_text())["events"][event]["pages"][
        0
    ]
    return next(
        command["parameters"][0]
        for command in commands["list"]
        if command.get("_original") == original["_original"]
    )


def narration(event):
    return [text(event, original) for original in (DOOR, INSIDE, ROOM)]


# The scene correction applies as one, in both copies, and undoes as one,
# leaving the pronoun fix outside the scene.
assert apply(qa.correction_map(task, [scene["id"], inside["id"]]))
assert narration(2) == narration(3) == [line["correction"] for line in scene["lines"]]
assert text(4, INSIDE) == "She steps inside."
assert apply(qa.correction_map(task, [scene["id"]], undo=True))
assert (
    narration(2)
    == narration(3)
    == [original["parameters"][0] for original in (DOOR, INSIDE, ROOM)]
)
assert text(4, INSIDE) == "She steps inside."
print("ok")
