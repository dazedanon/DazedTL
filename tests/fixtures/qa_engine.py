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


# Screening flags the stratum line; everything else is clean.
while row := qa.next_bundle(task, "screen-a"):
    bundle = bundle_of(row)
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
            },
        ),
    )
state = qa.advance(task)
assert state["stage"] == "deep", state


def deep_result(row, corrections):
    bundle = bundle_of(row)
    reviews = []
    for item in bundle["items"]:
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
qa.finalize(task)
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
assert [row["correction"] for row in findings["findings"]] == [
    "Rest on the First Stratum"
], findings["findings"]
print("ok")
