"""A text QA journey through the engine's own commands on a generated game.

Plays every reviewer with fixed results, so the engine's bundles, gates and
findings are checked end to end without an assistant.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa

# Deep bundles open as soon as one screened cluster is ready.
qa.EARLY_DEEP_BATCH = 1

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
WEATHER = line("今日はいい天気だね", "Nice weather today.")
POWER = line("100%の力", "100% power")
AROUSAL = line("ムラムラが止まらない", "The Arousal won't stop.")
# The source shows Arina's header on the owner's line.
WELCOME = line("いらっしゃい、アリナちゃん", "Welcome, Arina-chan.")
SWORD = "攻撃力+5の剣"
# A line of the declined scene that another scene shows too.
FOREST_EXIT = line("森を抜けよう", "Let's get out of the forest.")
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
                        WEATHER,
                        # Flags that are style, not defects, force no deep review.
                        line("討伐3体", "Three defeated."),
                        POWER,
                        speaker("店長", "Owner", face="owner"),
                        line("よく来たね、アリナちゃん", "Glad you came, Arina-chan."),
                        speaker("アリナ", "Arina"),
                        WELCOME,
                        # Japanese residue forces deep review, where it is
                        # declined; screening flags it too, so it has a scene.
                        line("朝だ", "It's 朝."),
                        # Two automatic lint families, accepted without review.
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
                        # Automatic lint fixes reach a line no reviewer read.
                        line(
                            "ここは暗い森だ…っ♥離れないで",
                            "A dark forest…h♥Stay close.",
                        ),
                        line("森の奥へ", "Into the 森."),
                        FOREST_EXIT,
                    )
                ],
            },
            # Screening targets the shared line in the declined scene, which
            # has more lines to cover.
            {
                "id": 3,
                "pages": [
                    page(
                        speaker("アリナ", "Arina"),
                        FOREST_EXIT,
                        line("ここで休もう", "Let's rest here."),
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
            "description": "Resto'res HP.",
            "_original": {"name": "ムラムラ", "description": "体力を回復す゛る。"},
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
# Japanese never translated: a custom data file no plugin reads, and a
# plugin setting whose plugin file is missing, so nothing rules it out.
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
# Small screen bundles give the first reviewer several to have checked. The
# game's message windows show three rows.
task, state = qa.prepare_task(
    game,
    data,
    "release",
    storage,
    screen_item_limit=3,
    fit={"widths": {"messageRows": 3}},
)
assert state["stage"] == "screen", state
forced = json.loads((task / "checkpoint.json").read_text())["deep"]["candidate_reasons"]
# Japanese residue forces deep review, and so does a likely header slip.
assert {
    source(identity): candidate["reasons"] for identity, candidate in forced.items()
} == {
    "朝だ": ["source-language-residue"],
    "森の奥へ": ["source-language-residue"],
    WELCOME["_original"]: ["show-text-header"],
}, forced
assert state["not_translated"] == {"total": 3, "may_show": 2}, state["not_translated"]
# Assistants write into the task, so it keeps its parent's permissions instead
# of tempfile's private ones, which on Windows lock the app out of the files an
# elevated assistant writes.
assert task.stat().st_mode == task.parent.stat().st_mode, oct(task.stat().st_mode)
# A worker's brief holds every role it may be handed, filled in for this task.
worker = qa.brief(task, "worker")
assert "{{" not in worker and str(task / "context.json") in worker, worker
assert all(f"## {title}" in worker for title in qa._BRIEF_SECTIONS["worker"]), worker


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


# The lines deep review needs, 朝だ so that it has a scene; the first reviewer
# flags only the stratum line.
FLAGGED = {
    STRATUM["_original"],
    AROUSAL["_original"],
    WELCOME["_original"],
    SWORD,
    "よく来たね、アリナちゃん",
    "朝だ",
}


def checkpoint():
    return json.loads((task / "checkpoint.json").read_text())


def screen(row, flagged, declined=(), observations=()):
    bundle = bundle_of(row)
    return result_path(
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
                    "note": "Reads oddly against the source.",
                }
                for target in screen_targets(bundle)
                if target["source"] in flagged
            ],
            "motif_reviews": [],
            "lint_reviews": [
                {
                    "id": item["id"],
                    "rejected": [
                        proposal["id"]
                        for proposal in item["proposals"]
                        if proposal["current"] == "Resto'res HP."
                    ],
                    "note": "The item text keeps its house style.",
                }
                for item in bundle["items"]
                if item["kind"] == "lint-family"
            ],
            "declined": [
                {"id": item["id"], "reason": "Outside what this reviewer reviews."}
                for item in bundle["items"]
                if declined_scene(item) or item["id"] in declined
            ],
            "observations": list(observations),
        },
    )


# The first reviewer declines the forest scene and passes everything else but
# the stratum line. Reviewing lint families, it notices a defect in a scene
# line outside its own items and names it by its event command.
OBSERVATION = {
    "identity": "Map001.json#/events/1/pages/0/list/2",
    "categories": ["voice"],
    "note": "Idle small talk right after deciding to rest.",
}
while row := qa.next_bundle(task, "screen-a"):
    assert row["id"].startswith("screen"), row
    lint_only = all(item["kind"] == "lint-family" for item in bundle_of(row)["items"])
    qa.accept_result(
        task,
        screen(
            row,
            {STRATUM["_original"]},
            observations=[OBSERVATION] if lint_only else [],
        ),
    )
# Only its first bundle is checked, which covers a quarter of its lines, and
# deep review of those lines waits for the check. The declined scene waits for
# a reviewer on another helper and the check for another reviewer, never this
# one or, for the scene, another worker on its helper, and the stage cannot
# end early.
assert not checkpoint()["deep"]["bundles"]
rows = checkpoint()["screen"]["bundles"]
(check,) = [row for row in rows if row.get("check_of")]
(forest,) = [row for row in rows if row.get("declined_by")]
assert check["independent_of"] == forest["declined_by"] == ["screen-a"], rows
assert qa.status(task)["declined"]["waiting"] == 4
for worker, bundle_id, reason in (
    ("screen-a", forest["id"], "declined"),
    ("screen-c", forest["id"], "declined"),
    ("screen-a", check["id"], "independent"),
    (None, None, "check"),
):
    try:
        if bundle_id:
            qa.next_bundle(task, worker, bundle_id)
        else:
            qa.advance(task)
    except ValueError as error:
        assert reason in str(error), error
    else:
        raise AssertionError("A bundle went to its own reviewer or was skipped.")
# A reviewer on another helper claims the declined scene by ID, and only that
# reviewer reads the scene in context, then declines too, which sets it aside.
row = qa.next_bundle(task, "screen-b", forest["id"], helper="other")
FOREST = "Map001.json#/events/2/pages/0/list"
assert "森の奥へ" in qa.context_view(task, FOREST + "/2", worker="screen-b")
for attempt in (
    lambda: qa.context_view(task, FOREST),
    lambda: qa.context_view(task, FOREST, worker="screen-a"),
):
    try:
        attempt()
    except ValueError as error:
        assert "declined" in str(error), error
    else:
        raise AssertionError("Another worker read a declined scene in context.")
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
assert qa.status(task)["declined"] == {"waiting": 0, "set_aside": 4}
# The second reviewer's check finds what the first missed, which goes to deep
# review while screening continues. Checks add no coverage, and a reviewer
# that missed more than it found has every bundle checked.
covered = qa.status(task)["screen"]["accepted"]
row = qa.next_bundle(task, "screen-b", check["id"])
qa.accept_result(task, screen(row, FLAGGED))
state = qa.status(task)
assert state["stage"] == "screen" and checkpoint()["deep"]["bundles"], state
assert state["screen"]["accepted"] == covered, state["screen"]
assert state["screen"]["checks"]["escalated"] == ["screen-a"], state["screen"]
for row in checkpoint()["screen"]["bundles"]:
    if row.get("check_of") and row["status"] == "pending":
        row = qa.next_bundle(task, "screen-b", row["id"])
        qa.accept_result(task, screen(row, FLAGGED))
# Screening does not end there: the set-aside scene's line that another scene
# shows is screened there in a follow-up bundle. Its first reviewer declines
# it too, and another reviewer flags the line.
row = qa.next_bundle(task, "screen-a")
(follow_up,) = bundle_of(row)["items"]
assert follow_up["scene_id"] == "Map001.json#/events/3/pages/0/list", follow_up
assert [line["source"] for line in screen_targets(bundle_of(row))] == [
    FOREST_EXIT["_original"]
], follow_up
qa.accept_result(task, screen(row, set(), declined={follow_up["id"]}))
row = qa.next_bundle(task, "screen-b", row["id"] + "-d1")
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
                    "categories": ["voice"],
                    "note": "Stiff for Arina.",
                }
                for target in screen_targets(bundle_of(row))
            ],
            "motif_reviews": [],
            "declined": [],
        },
    ),
)
# That is the second reviewer's first screen, so it is checked, and the line's
# deep review waits for the check. The reviewer that declined the line may take
# it, and declining it again leaves coverage and the comparison as they were.
assert FOREST_EXIT["_original"] not in {
    item["source"]
    for row in checkpoint()["deep"]["bundles"]
    for item in bundle_of(row)["items"]
}
row = qa.next_bundle(task, "screen-a")
assert row["check_of"] == row["id"].removesuffix("-c1"), row
qa.accept_result(task, screen(row, set(), declined={follow_up["id"]}))
assert not any(
    other.get("origin") == row["id"] for other in checkpoint()["screen"]["bundles"]
)
checks = qa.status(task)["screen"]["checks"]
assert checks["total"] == checks["projected"] == checks["accepted"] + 1, checks
assert checks["added"] == len(FLAGGED) - 1, checks
# Screening is over while early deep bundles wait, so the next claim makes
# deep review the stage instead of leaving screening current.
qa.next_bundle(task, "deep-a")
assert qa.status(task)["stage"] == "deep"
# Deep review and the context view leave the set-aside scene out, even its
# Japanese residue, which would otherwise force deep review, and even for its
# last reviewer.
try:
    qa.context_view(task, FOREST, worker="screen-b")
except ValueError as error:
    assert "declined" in str(error), error
else:
    raise AssertionError("The context view showed a declined scene.")
assert "第1層で休む" in qa.context_view(task, "Map001.json#/events/1/pages/0/list/1")


def deep_result(row, corrections, declined=("朝だ",)):
    bundle = bundle_of(row)
    reviews = []
    for item in bundle["items"]:
        if item["source"] in declined:
            reviews.append(
                {"id": item["id"], "disposition": "declined", "reason": "Not reviewed."}
            )
            continue
        if item["source"] == "よく来たね、アリナちゃん":
            # A question no evidence settles, with a proposal the user may use.
            reviews.append(
                {
                    "id": item["id"],
                    "disposition": "uncertain-playtest",
                    "severity": None,
                    "category": "",
                    "family_key": "",
                    "motif_ids": [],
                    "evidence": "Whether the owner knows Arina depends on an earlier scene.",
                    "correction": "Welcome back.",
                    "apply_identities": [],
                }
            )
            continue
        if item["source"] == WELCOME["_original"]:
            # The header check sent the line too, and says why.
            assert "show-text-header" in item["deep_reasons"], item
            assert any(
                failed["check"] == "show-text-header"
                and "アリナちゃん" in failed["note"]
                for failed in item["checks"]
            ), item
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
# Claiming it again by ID returns the same assignment.
assert qa.next_bundle(task, "deep-a", row["id"]) == row
assert "森の奥へ" not in {item["source"] for item in bundle_of(row)["items"]}
# The scene prints once, marking the lines its items' screen evidence names.
shown = qa.render_bundle(task, row["id"])
assert shown.count("## SCENE S1") == 1 and ">>ITEM" in shown, shown
# The observation became a deep item with its reason as screen evidence, and
# its line is marked in the scene under the command number it was named by.
((observed, weather),) = [
    (bundle, item)
    for bundle in map(bundle_of, checkpoint()["deep"]["bundles"])
    for item in bundle["items"]
    if item["source"] == WEATHER["_original"]
]
assert weather["deep_reasons"] == ["observation"], weather
assert [evidence["note"] for evidence in weather["screen_evidence"]] == [
    OBSERVATION["note"]
], weather
assert any(
    weather["id"] in line.get("items", []) and line["command"] == 2
    for scene in observed["scenes"].values()
    for line in scene["lines"]
    if line["source"] == WEATHER["_original"]
), observed["scenes"]
# A reviewer judges its own items in place; observing one would reopen it.
try:
    qa.accept_result(
        task,
        result_path(
            "own-line",
            {
                **deep_result(row, {}),
                "observations": [
                    {
                        **OBSERVATION,
                        "identity": bundle_of(row)["items"][0]["identities"][0],
                    }
                ],
            },
        ),
    )
except qa.QAResultError as error:
    assert "own lines" in str(error), error
else:
    raise AssertionError("An observation reopened the reviewer's own item.")
# The coordinator relays an observation on the shared line's occurrence in the
# declined scene, which stays out of deep review although the same text was
# screened in another scene.
FOREST_NOTE = "Reads as an order in the dark forest."
qa.record_observation(task, "coordinator", FOREST + "/3", ["voice"], FOREST_NOTE)
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
# A correction is rewrapped to its message's portrait width before its rows
# count, and this one needs a fourth row.
try:
    qa.accept_result(
        task,
        result_path(
            "too-tall",
            deep_result(
                row,
                {
                    STRATUM["_original"]: "Let us rest here on Stratum 1 for a while. "
                    "The long climb left every one of us tired, hungry and sore from "
                    "all the fighting, so nobody should argue."
                },
            ),
        ),
    )
except qa.QAResultError as error:
    assert "needs 4 rows; a message window shows 3" in str(error), error
else:
    raise AssertionError("A correction taller than its message window was accepted.")
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
# The declined item takes its scene to its own bundle, and only the reviewer
# on another helper that claims it reads that scene in context.
(split,) = [
    row
    for row in json.loads((task / "checkpoint.json").read_text())["deep"]["bundles"]
    if row.get("declined_by")
]
assert "## SCENE S1" in qa.render_bundle(task, split["id"])
scene = "Map001.json#/events/1/pages/0/list"
try:
    qa.context_view(task, scene, worker="deep-a")
except ValueError as error:
    assert "declined" in str(error), error
else:
    raise AssertionError("The context view showed a declined deep item's scene.")
qa.next_bundle(task, "deep-b", split["id"], helper="other")
assert "朝だ" in qa.context_view(task, scene, worker="deep-b")
qa.release_bundle(task, split["id"])
# The re-screened line opened deep review once its follow-up was screened,
# without its occurrence in the declined scene.
row = qa.next_bundle(task, "deep-a")
(item,) = bundle_of(row)["items"]
assert [identity.split("/pages")[0] for identity in item["identities"]] == [
    "Map001.json#/events/3"
], item
qa.accept_result(
    task,
    result_path(
        row["id"],
        deep_result(row, {FOREST_EXIT["_original"]: "Let's leave the forest."}),
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
# its reviewer accepts one and declines the other, which a reviewer on another
# helper rejects: a sentence start keeps its capital.
assert state["stage"] == "sweep", state
assert FOREST_NOTE not in {
    evidence["note"]
    for row in checkpoint()["deep"]["bundles"]
    for item in bundle_of(row)["items"]
    for evidence in item.get("screen_evidence") or []
}
# A worker that stops answering loses its bundle to the next idle one.
qa.STALL_MINIMUM_SECONDS = 0
stalled = qa.next_bundle(task, "sweep-slow")
row = qa.next_bundle(task, "sweep-a")
qa.STALL_MINIMUM_SECONDS = 20 * 60
assert row["id"] == stalled["id"] and row["reassigned_from"] == "sweep-slow", row
(family,) = bundle_of(row)["items"]
assert sorted(row["current"] for row in family["candidates"]) == [
    "Arousal!",
    "The Arousal is building…",
], family


def sweep(row, rejected=(), declined=()):
    (family,) = bundle_of(row)["items"]
    qa.accept_result(
        task,
        result_path(
            row["id"],
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
                            if candidate["current"] in rejected
                        ],
                        "note": "A sentence start keeps its capital."
                        if rejected
                        else "",
                    }
                ],
                "declined": [
                    {"id": candidate["id"], "reason": "Not judged."}
                    for candidate in family["candidates"]
                    if candidate["current"] in declined
                ],
            },
        ),
    )


sweep(row, declined={"Arousal!"})
row = qa.next_bundle(task, "sweep-b", helper="other")
assert [
    candidate["current"] for candidate in bundle_of(row)["items"][0]["candidates"]
] == ["Arousal!"], row
sweep(row, rejected={"Arousal!"})
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


def editorial(row, verdicts, observations=()):
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
                "observations": list(observations),
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
# A revision that breaks the recorded decision comes back in a second round,
# which next opens by itself once the first is reviewed.
row = qa.next_bundle(task, "editor-a")
while row and row.get("round", 1) == 1:
    editorial(row, {STRATUM["_original"]: ("revise", "Rest on the first stratum")})
    row = qa.next_bundle(task, "editor-a")
assert qa.status(task)["editorial"]["round"] == 2
# The reviewers convince the coordinator instead: the decision changes and
# the second round accepts the revision, which then stands.
qa.record_decision(
    task,
    "stratum names",
    "Strata are ordinal titles",
    "deep-a",
    source="第1層",
    translation="first stratum",
)
# The editor also notices a defect in a line no finding touches.
(second,) = editorial(
    row,
    {},
    [
        {
            "identity": "Map001.json#/events/1/pages/0/list/4",
            "categories": ["fluency"],
            "note": "A bare fragment where Arina boasts.",
        }
    ],
)["items"]
assert any("decision" in conflict["key"] for conflict in second["conflicts"]), second
# The coordinator relays another reviewer's report on a line already corrected.
qa.record_observation(
    task,
    "coordinator",
    "Map001.json#/events/1/pages/0/list/11",
    ["voice"],
    "The urge reads as a gauge here too.",
)
# Both open a follow-up deep round before QA completes.
row = qa.next_bundle(task, "deep-a")
assert qa.status(task)["stage"] == "deep"
assert sorted(item["source"] for item in bundle_of(row)["items"]) == sorted(
    [POWER["_original"], AROUSAL["_original"]]
), bundle_of(row)
qa.accept_result(
    task,
    result_path(
        row["id"],
        deep_result(
            row,
            {
                POWER["_original"]: "My power, at a full 100%, is more than enough "
                "to beat anyone!"
            },
            declined={AROUSAL["_original"]},
        ),
    ),
)
# Nobody reviews the corrected line again, so its earlier review stands.
(waiting,) = [
    row
    for row in json.loads((task / "checkpoint.json").read_text())["deep"]["bundles"]
    if row["status"] == "pending"
]
row = qa.next_bundle(task, "deep-b", waiting["id"])
qa.accept_result(
    task,
    result_path(row["id"], deep_result(row, {}, declined={AROUSAL["_original"]})),
)
# Only its correction gets an editorial round; earlier verdicts stand.
row = qa.next_bundle(task, "editor-a")
assert [item["finding"]["source"] for item in bundle_of(row)["items"]] == [
    POWER["_original"]
], bundle_of(row)
editorial(row, {})
# With nothing left to review, next completes QA and the engine has timed it.
assert qa.next_bundle(task, "editor-a") is None
state = qa.status(task)
assert state["stage"] == "complete", state
assert (
    state["estimate"]["eta_seconds"] == 0 and "editor-a" in state["estimate"]["workers"]
)
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
# Automatic lint families combine into one correction, also in the declined
# scene; the reviewed fix the reviewer rejected is left out.
assert sorted(row["correction"] for row in findings["findings"]) == [
    "A dark forest…♥ Stay close.",
    "A sword with Attack +8",
    "Ah…♥ Amazing",
    "Let's leave the forest.",
    # Wider than Arina's portrait message, so it is rewrapped there.
    "My power, at a full 100%, is more than enough to\nbeat anyone!",
    "Owner · owner 0",
    "Rest on the first stratum",
    "The arousal is building…",
    "The arousal won't stop.",
], findings["findings"]
# Source fixes go through the same correction map, apply and regression the
# app runs on its disposable copy; this game is the test's own copy.
# The user chose the open question's proposal, so it applies too.
(question,) = findings["uncertain_playtests"]
assert question["source"] == "よく来たね、アリナちゃん" and question["places"] == 1, (
    question
)
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


assert apply(
    qa.correction_map(
        task, [row["id"] for row in findings["findings"]], [question["id"]]
    )
)


def message(source):
    commands = json.loads((data / "Map001.json").read_text())["events"][1]["pages"][0]
    return next(
        command["parameters"][0]
        for command in commands["list"]
        if command.get("_original") == source
    )


assert message("よく来たね、アリナちゃん") == "Welcome back."
# The correction of the re-screened line applies only outside the declined scene.
assert [
    command["parameters"][0]
    for event in json.loads((data / "Map001.json").read_text())["events"][2:]
    for command in event["pages"][0]["list"]
    if command.get("_original") == FOREST_EXIT["_original"]
] == ["Let's get out of the forest.", "Let's leave the forest."]
# The declined scene still gets its automatic lint fix.
assert json.loads((data / "Map001.json").read_text())["events"][2]["pages"][0]["list"][
    1
]["parameters"] == ["A dark forest…♥ Stay close."]
# Undoing one correction puts its line back and leaves the rest.
stratum = next(
    row["id"] for row in findings["findings"] if row["source"] == STRATUM["_original"]
)
assert apply(qa.correction_map(task, [stratum], undo=True))
assert message(STRATUM["_original"]) == "Rest on Stratum 1"
assert message(AROUSAL["_original"]) == "The arousal won't stop."
headers = [
    command["parameters"]
    for command in json.loads((data / "Map001.json").read_text())["events"][1]["pages"][
        0
    ]["list"]
    if command["code"] == 101
]
assert ["owner", 0, 0, 2, "Owner"] in headers[2:], headers
assert qa.status(task)["screen"]["lint"] == {"accepted": 1, "total": 1, "declined": 0}
# The declined scene and items are a coverage gap, reported once with their
# reasons.
assert [item["reasons"] for item in findings["declined"]] == [
    ["Outside what this reviewer reviews.", "Also declined."],
    ["Not reviewed."],
    ["Not reviewed.", "Not reviewed."],
], findings["declined"]
# Only the shared line's occurrence in that scene goes unreviewed.
assert sorted(
    (row["source"], row["identity"].split("/pages")[0])
    for row in findings["not_reviewed"]
) == [
    ("ここは暗い森だ…っ♥離れないで", "Map001.json#/events/2"),
    ("朝だ", "Map001.json#/events/1"),
    ("案内人", "Map001.json#/events/2"),
    ("森の奥へ", "Map001.json#/events/2"),
    ("森を抜けよう", "Map001.json#/events/2"),
], findings["not_reviewed"]
# Japanese never translated is its own gap, never a passing count: each file
# or plugin with whether players can reach it, those that may show first.
untranslated = findings["not_translated"]
assert "never translated" in untranslated["reason"], untranslated
assert [
    (row["kind"], row.get("plugin") or row["file"], row["count"], row.get("reach"))
    for row in untranslated["sources"]
] == [
    ("data", "Map001.json", 1, None),
    ("plugin", "Prompt", 1, "unknown"),
    ("custom", "Synopsis.json", 1, "unread"),
], untranslated["sources"]
# After an update changes the rules, the task still reports where it stood,
# but nothing made under the old rules can be applied.
qa._engine_fingerprint = lambda: "updated"
assert qa.status(task)["rules_changed"]
try:
    qa.correction_map(task, [stratum])
except ValueError as error:
    assert "rules changed" in str(error), error
else:
    raise AssertionError("Corrections from older rules were applied.")

# Database checks send what reviewers read apart to deep review with their
# evidence: two skills that show one name, and an MZ state message that prints
# without its subject.
checks_game = temporary / "checks-game"
(checks_game / "data").mkdir(parents=True)
(checks_game / "js").mkdir()
(checks_game / "js/rmmz_core.js").write_text("")
for name, value in {
    "Skills.json": [
        None,
        {"id": 1, "name": "Sweeping Slash", "_original": {"name": "払い斬り"}},
        {"id": 2, "name": "Sweeping Slash", "_original": {"name": "薙ぎ払い"}},
    ],
    "States.json": [
        None,
        {
            "id": 1,
            "name": "Illusion",
            "message4": "was freed from the Illusion.",
            "_original": {"name": "幻惑", "message4": "の幻惑が解けた"},
        },
    ],
}.items():
    (checks_game / "data" / name).write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )
checked, _state = qa.prepare_task(
    checks_game, checks_game / "data", "release", temporary / "checks-storage"
)
sources = {
    cluster["representative"]: cluster["source"]
    for cluster in json.loads((checked / "inventory.json").read_text())["clusters"]
}
reasons = {
    sources[identity]: candidate["reasons"]
    for identity, candidate in json.loads((checked / "checkpoint.json").read_text())[
        "deep"
    ]["candidate_reasons"].items()
}
assert reasons == {
    "払い斬り": ["name-collision"],
    "薙ぎ払い": ["name-collision"],
    "の幻惑が解けた": ["battler-name"],
}, reasons
for worker in ("screen-a", "screen-b"):
    row = qa.next_bundle(checked, worker)
    assert row["id"].startswith("screen"), row
    qa.accept_result(checked, screen(row, set()))
row = qa.next_bundle(checked, "deep-a")
items = {item["source"]: item for item in bundle_of(row)["items"]}
assert set(items) == {"払い斬り", "薙ぎ払い", "の幻惑が解けた"}, items
assert items["払い斬り"]["deep_reasons"] == ["name-collision"], items
assert "Skills.json 2 薙ぎ払い" in items["払い斬り"]["checks"][0]["note"], items
assert items["の幻惑が解けた"]["checks"][0]["check"] == "battler-name", items
assert "check battler-name: RPG Maker MZ" in qa.render_bundle(checked, row["id"])


# The MZ message may gain the %1 its source forgot, as a battler-name source
# fix and nothing else: not as a plain correction, with another code, or on a
# text that is no battle message.
def checked_deep(name, fixes):
    reviews = [
        {
            "id": item["id"],
            "disposition": "clean",
            "severity": None,
            "category": "",
            "family_key": "",
            "motif_ids": [],
            "evidence": "Checked against the source.",
            "correction": None,
            "apply_identities": [],
            **fixes.get(source, {}),
        }
        for source, item in items.items()
    ]
    return result_path(
        name,
        {
            "schema": qa.DEEP_RESULT_SCHEMA,
            "bundle_id": row["id"],
            "bundle_sha256": row["sha256"],
            "reviews": reviews,
        },
    )


fix = {
    "disposition": "actionable",
    "severity": "medium",
    "category": "runtime",
    "correction": "%1 was freed from the Illusion.",
    "source_fix": {"kind": "battler-name"},
}
for name, fixes, refusal in (
    ("plain", {"の幻惑が解けた": {**fix, "source_fix": None}}, "runtime-token"),
    (
        "other-code",
        {"の幻惑が解けた": {**fix, "correction": "%2 was freed from the Illusion."}},
        "adds the one %1",
    ),
    ("name", {"払い斬り": {**fix, "correction": "%1 Sweeping Slash"}}, "check offers"),
):
    try:
        qa.accept_result(checked, checked_deep(name, fixes))
    except qa.QAResultError as error:
        assert refusal in str(error), error
    else:
        raise AssertionError(f"The {name} correction added a code.")
qa.accept_result(checked, checked_deep("battler-name", {"の幻惑が解けた": fix}))
assert qa.finalize(checked)["stage"] == "editorial"
row = qa.next_bundle(checked, "editor-a")
qa.accept_result(
    checked,
    result_path(
        row["id"],
        {
            "schema": qa.EDITORIAL_RESULT_SCHEMA,
            "bundle_id": row["id"],
            "bundle_sha256": row["sha256"],
            "reviews": [
                {"id": item["id"], "verdict": "accept", "note": ""}
                for item in bundle_of(row)["items"]
            ],
        },
    ),
)
assert qa.next_bundle(checked, "editor-a") is None
(finding,) = json.loads((checked / "findings.json").read_text())["findings"]
assert finding["source_fix"] == "battler-name", finding


def message4():
    return json.loads((checks_game / "data/States.json").read_text())[1]["message4"]


# Apply and undo pass the regression, which allows only that one %1.
for undo, expected in (
    (False, fix["correction"]),
    (True, "was freed from the Illusion."),
):
    assert qa._apply_loaded_correction_map(
        checked,
        json.loads((checked / "task.json").read_text(encoding="utf-8")),
        qa.correction_map(checked, [finding["id"]], undo=undo),
        json.loads((checked / "inventory.json").read_text(encoding="utf-8")),
        dry_run_name="dry-run.json",
        regression_name="regression.json",
    )["valid"]
    assert message4() == expected, message4()


def pace(lanes):
    """A screen stage that reviewed bundles of ten targets in *lanes* at
    once, two minutes each, up to a minute ago, with one bundle waiting."""
    now = datetime.now(UTC)
    rows = [
        {
            "id": f"screen-{index:04d}",
            "status": "accepted",
            # Two names taking turns are still one bundle at a time.
            "assigned_to": f"rev-{index % max(2, lanes)}",
            "assigned_at": (
                now - timedelta(minutes=13 - 2 * (index // lanes))
            ).isoformat(),
            "accepted_at": (
                now - timedelta(minutes=11 - 2 * (index // lanes))
            ).isoformat(),
            "item_count": 10,
        }
        for index in range(6 * lanes)
    ]
    rows.append({"id": "screen-0099", "status": "pending", "item_count": 10})
    seen = {"bundles": 3, "seconds": 360.0, "last_seen": now.isoformat()}
    return qa._estimate(
        {
            "workers": {f"rev-{index}": seen for index in range(max(2, lanes))},
            "screen": {
                "bundles": rows,
                "total_items": 70 * lanes,
                "accepted_items": 60 * lanes,
            },
        }
    )


# Time left follows the bundles in review at once, not the names seen, and
# status says when bundles wait while reviewers take them one at a time.
alone, together = pace(1), pace(4)
assert alone["one_at_a_time"] and alone["in_review_at_once"] == 1.0, alone
assert alone["eta_seconds"] == round(alone["remaining"]["screen"] * 12), alone
assert not together["one_at_a_time"] and together["in_review_at_once"] == 4.0, together
assert together["eta_seconds"] == round(together["remaining"]["screen"] * 12 / 4), (
    together
)
print("ok")
