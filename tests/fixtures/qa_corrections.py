"""What Text QA corrected, as data (util/qa_corrections.py): a game's
finished tasks and an older game's receipts are each read once, deduplicated,
labelled, grouped and counted per translated line, and nothing they read is
written."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from util import qa_corrections as corrections
from util.qa.schema import (
    CHECKPOINT_SCHEMA,
    DEEP_RESULT_SCHEMA,
    FINDINGS_SCHEMA,
    SCREEN_RESULT_SCHEMA,
    TASK_SCHEMA,
)
from util.qa.storage import ANSWERS_SCHEMA
from util.rpgmaker_qa_manifest import build_manifest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_map(game, events):
    """A map whose events each say their (Japanese, English) lines."""
    write(
        game / "data/Map001.json",
        {
            "events": [None]
            + [
                {
                    "id": number,
                    "pages": [
                        {
                            "list": [
                                *(
                                    {
                                        "code": 401,
                                        "indent": 0,
                                        "parameters": [english],
                                        "_original": japanese,
                                    }
                                    for japanese, english in lines
                                ),
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                }
                for number, lines in enumerate(events, 1)
            ],
        },
    )


def identities(manifest, source):
    return [
        record["identity"]
        for record in manifest["records"]
        if record["source"] == source
    ]


# A game reviewed twice, with a third round still in review.
game = temporary / "Game A"
(game / ".dazedtl").mkdir(parents=True)
LINES = {
    "lock": ("鍵を閉めた。", "She unlocked the door."),
    "morning": ("おはよう、ボス。", "Morning, boss."),
    "go": ("ボス、行こう。", "Let's go, boss."),
    "strong": ("ボスは強い。", "The boss is strong."),
    "cat": ("猫がいる。", "There's a cat."),
    "kitten": ("猫だ。", "A cat."),
    "yes": ("はい", "Yes."),
    "stop": ("やめて", "Arina: Arina: Stop."),
    "mina": ("ミナが来た。", "Mina's here."),
    "monster": ("魔物だ！", "A monster!"),
    "who": ("誰？", "Who?"),
    "rain": ("雨だ。", "It's rain."),
    "maybe": ("そうかもね。", "Maybe so."),
    "probably": ("たぶんね。", "Probably."),
    "sky": ("空だ。", "The sky."),
}


def write_game(**changed):
    """The game's lines, a second event repeating two of them, which share
    their translation."""
    lines = {
        key: (japanese, changed.get(key, english))
        for key, (japanese, english) in LINES.items()
    }
    write_map(game, [list(lines.values()), [lines["yes"], lines["sky"]]])


write_game()
first_inventory = build_manifest(game / "data", "release")
storage = temporary / "workspace"


def finding(number, key, correction, category, inventory=first_inventory, **extra):
    source, current = LINES[key]
    return {
        "id": f"QA-{number:04d}",
        "category": category,
        "severity": "medium",
        "family_key": "",
        "source": source,
        "current": current,
        "correction": correction,
        "target_identities": identities(inventory, source),
        "evidence": "",
        **extra,
    }


def task(
    name, created, inventory, findings, questions=(), chosen=None, stage="complete"
):
    folder = storage / "engine/workflows/p1/text-qa/Game-A/release" / name
    write(
        folder / "task.json",
        {
            "schema": TASK_SCHEMA,
            "game_root": str(game),
            "data_root": str(game / "data"),
            "focus": "release",
            "created_at": created,
        },
    )
    write(folder / "checkpoint.json", {"schema": CHECKPOINT_SCHEMA, "stage": stage})
    write(folder / "inventory.json", inventory)
    write(
        folder / "findings.json",
        {
            "schema": FINDINGS_SCHEMA,
            "findings": findings,
            "uncertain_playtests": list(questions),
            "not_reviewed": [],
        },
    )
    if chosen:
        write(folder / "answers.json", {"schema": ANSWERS_SCHEMA, "answers": chosen})
    return folder


task(
    "1111111111111111",
    "2026-01-01T00:00:00+00:00",
    first_inventory,
    [
        finding(
            1,
            "lock",
            "She locked the door.",
            "meaning",
            evidence="The action is reversed.",
        ),
        finding(2, "morning", "Morning, chief.", "voice"),
        finding(3, "go", "Let's go, chief.", "voice"),
        finding(4, "strong", "The chief is strong.", "voice"),
        finding(5, "cat", "There's a kitten.", "fluency"),
        finding(6, "kitten", "A kitten.", "fluency"),
        finding(7, "yes", "Yes!", "fluency"),
        finding(
            8,
            "stop",
            "Arina: Stop.",
            "fluency",
            evidence="The speaker name is doubled.",
        ),
        finding(9, "mina", "Meena's here.", "terminology"),
        finding(
            10,
            "monster",
            "A Monster!",
            "formatting",
            lint_only=True,
            lint_families=["lint:glossary-term"],
        ),
        finding(11, "who", "Who is it?", "speaker"),
        finding(12, "rain", "It's raining.", "fluency"),
        # Editorial review turned this one down.
        finding(
            13,
            "sky",
            "The heavens.",
            "fluency",
            editorial={"verdict": "reject", "note": "No."},
        ),
    ],
)
# Its rain fix went in before the next round, which read the game again.
write_game(rain="It's raining.")
second_inventory = build_manifest(game / "data", "release")
LINES["rain"] = ("雨だ。", "It's raining.")


def question(key, correction):
    source, current = LINES[key]
    return {
        "id": identities(second_inventory, source)[0],
        "source": source,
        "current": current,
        "correction": correction,
        "evidence": "Reads stiff.",
    }


task(
    "2222222222222222",
    "2026-02-01T00:00:00+00:00",
    second_inventory,
    [
        finding(1, "lock", "She locked the door.", "meaning", second_inventory),
        finding(2, "rain", "It is raining.", "fluency", second_inventory),
    ],
    [question("maybe", "Could be."), question("probably", "Maybe.")],
    {
        identities(second_inventory, "そうかもね。")[0]: "use",
        identities(second_inventory, "たぶんね。")[0]: "keep",
    },
)
task(
    "3333333333333333",
    "2026-03-01T00:00:00+00:00",
    second_inventory,
    [],
    stage="screen",
)
# The game now holds some of the corrections; a later edit replaced one.
write_game(
    lock="She locked the door.", rain="It is raining.", maybe="Could be.", yes="Yes!"
)
# Receipts the game's tasks already hold.
write(
    game / ".dazedtl/qa-receipts/1111111111111111/deep-1.json",
    {"schema": DEEP_RESULT_SCHEMA},
)

# An older game kept only receipts; Git holds its text before and after QA.
older = temporary / "Game B"
(older / ".dazedtl").mkdir(parents=True)
OLD = {
    "sword": ("剣を取れ。", "Take a sword."),
    "run": ("走れ！", "Run!"),
    "stop": ("止まれ。", "Stop."),
    "wait": ("待て。", "Wait."),
}


def write_older(**changed):
    """Game B's lines, the last one twice, which one review corrects."""
    lines = {
        key: (japanese, changed.get(key, english))
        for key, (japanese, english) in OLD.items()
    }
    write_map(older, [[*lines.values(), lines["wait"]]])


write_older()
old_inventory = build_manifest(older / "data", "release")
START = 1_700_000_000


def commit(message, at):
    stamp = f"@{START + at} +0000"
    subprocess.run(
        [
            "git",
            "-C",
            str(older),
            "-c",
            "user.name=QA",
            "-c",
            "user.email=qa@example.invalid",
            "commit",
            "-q",
            "-am" if at else "-m",
            message,
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    return subprocess.run(
        ["git", "-C", str(older), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


subprocess.run(["git", "-C", str(older), "init", "-q"], check=True, capture_output=True)
subprocess.run(
    ["git", "-C", str(older), "add", "data"], check=True, capture_output=True
)
commit("Translate", 0)
run = older / ".dazedtl/qa-receipts/4444444444444444"
write(
    run / "deep-1.json",
    {
        "schema": DEEP_RESULT_SCHEMA,
        "reviews": [
            {
                "id": identities(old_inventory, "剣を取れ。")[0],
                "disposition": "actionable",
                "correction": "Take the sword.",
                "category": "meaning",
                "evidence": "One sword is meant.",
            },
            {"id": identities(old_inventory, "走れ！")[0], "disposition": "clean"},
            {
                "id": identities(old_inventory, "止まれ。")[0],
                "disposition": "actionable",
                "correction": "Halt.",
                "category": "voice",
                "evidence": "A guard's order.",
            },
            # No lines named: the fix is its cluster's.
            {
                "id": identities(old_inventory, "待て。")[0],
                "disposition": "actionable",
                "correction": "Wait there.",
                "category": "fluency",
                "evidence": "Too curt.",
            },
        ],
    },
)
# A later review of a line replaces the earlier one; a header's fix is no
# line's text.
write(
    run / "deep-2.json",
    {
        "schema": DEEP_RESULT_SCHEMA,
        "reviews": [
            {
                "id": identities(old_inventory, "止まれ。")[0],
                "disposition": "actionable",
                "correction": "Halt!",
                "category": "voice",
                "evidence": "A guard's shout.",
            },
            {
                "id": identities(old_inventory, "走れ！")[0],
                "disposition": "actionable",
                "correction": "Guard",
                "source_fix": {"kind": "show-text"},
            },
        ],
    },
)
write(
    run / "screen-1.json",
    {
        "schema": SCREEN_RESULT_SCHEMA,
        "reviews": [
            {
                "id": identities(old_inventory, "走れ！")[0],
                "disposition": "actionable",
                "correction": "Go!",
            },
        ],
    },
)
for receipt in run.iterdir():
    os.utime(receipt, (START + 100, START + 100))
os.utime(run / "deep-2.json", (START + 150, START + 150))
# An edit after QA began that applied none of it, QA's commit, and a later edit.
write_older(run="Run!!")
commit("Polish", 200)
write_older(run="Run!!", sword="Take the sword.", stop="Halt!", wait="Wait there.")
qa_commit = commit("QA Pass", 300)
write_older(run="Run!!", sword="Take the sword.", stop="Stop it.", wait="Wait there.")
commit("Later", 400)


def snapshot():
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in (game, older, storage)
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


before = snapshot()
origins, skipped = corrections.find_origins([storage / "engine/workflows", game, older])
assert [(origin.kind, origin.task) for origin in origins] == [
    ("task", "1111111111111111"),
    ("task", "2222222222222222"),
    ("receipts", "4444444444444444"),
], origins
assert any("3333333333333333: still in review" in reason for reason in skipped), skipped
assert any(
    "1111111111111111: receipts of a game whose tasks are read" in reason
    for reason in skipped
), skipped
# A game folder finds its tasks in the workspace named.
assert [origin.task for origin in corrections.find_origins([game], storage)[0]] == [
    "1111111111111111",
    "2222222222222222",
]
found = corrections.collect(origins, skipped)
rows = {(row["game"], row["source"], row["after"]): row for row in found.rows}
assert len(rows) == len(found.rows) == 17, sorted(rows)


def row(source, after, name="Game A"):
    return rows[(name, source, after)]


# Dedupe: the second round's same fix of the lock line is the first's, a
# repeated line's fix is one row of two places, and a fix of an earlier fix
# is kept as one.
assert row("鍵を閉めた。", "She locked the door.")["task"] == "1111111111111111"
assert len(row("はい", "Yes!")["places"]) == 2
assert row("雨だ。", "It is raining.")["requa"] is True
assert row("雨だ。", "It is raining.")["before"] == "It's raining."
assert row("雨だ。", "It's raining.")["requa"] is False
# Turned down by editorial, or kept by the user: no correction.
assert ("Game A", "空だ。", "The heavens.") not in rows
assert ("Game A", "たぶんね。", "Maybe.") not in rows
assert row("そうかもね。", "Could be.")["finding_kind"] == "question"
# Labels.
assert {
    source: row(source, after)["kind"]
    for (_game, source, after) in rows
    if _game == "Game A"
} == {
    "鍵を閉めた。": "meaning",
    "おはよう、ボス。": "fluency",
    "ボス、行こう。": "fluency",
    "ボスは強い。": "fluency",
    "猫がいる。": "fluency",
    "猫だ。": "fluency",
    "はい": "fit/format",
    "やめて": "legacy output",
    "ミナが来た。": "glossary/name",
    "魔物だ！": "glossary/name",
    "誰？": "other",
    "雨だ。": "fluency",
    "そうかもね。": "other",
}, rows
# Recurring: three lines with one fix are a group, two are not.
assert {
    source for (_game, source, _after), item in rows.items() if item["recurring"]
} == {
    "おはよう、ボス。",
    "ボス、行こう。",
    "ボスは強い。",
}, [(key, item["recurring"]) for key, item in rows.items()]
assert (
    row("ボスは強い。", "The chief is strong.")["recurring"] == "change:boss -> chief"
)
# Applied: what the game holds now, for a task; at QA's commit, for receipts.
assert row("鍵を閉めた。", "She locked the door.")["applied"] is True
assert row("おはよう、ボス。", "Morning, chief.")["applied"] is False
assert row("雨だ。", "It's raining.")["applied"] is None
assert row("雨だ。", "It is raining.")["applied"] is True
# Receipts: QA's commit is the one that brought their fixes, past an edit made
# while QA ran; the text before is its parent's, and screen results are not fixes.
receipts = [item for item in found.rows if item["game"] == "Game B"]
assert {
    (item["source"], item["before"], item["after"], item["kind"], item["applied"])
    for item in receipts
} == {
    ("剣を取れ。", "Take a sword.", "Take the sword.", "meaning", True),
    ("止まれ。", "Stop.", "Halt!", "fluency", True),
    ("待て。", "Wait.", "Wait there.", "fluency", True),
}, receipts
assert len(row("待て。", "Wait there.", "Game B")["places"]) == 2
assert found.games[1]["sources"][0]["commit"] == qa_commit, found.games
assert found.games[1]["sources"][0]["left_out"] == "1 header or scene corrections"
assert receipts[0]["scene"] == "Map001.json#/events/1/pages/0/list", receipts[0]
# Denominator: a game's translated lines, one per source text of a file.
report = corrections.summary(found)
tally = {game_tally["game"]: game_tally for game_tally in report["games"]}
assert tally["Game A"]["translated_lines"] == len(LINES), tally["Game A"]
assert tally["Game A"]["corrected_lines"] == 13, tally["Game A"]
assert tally["Game A"]["places"] == 15, tally["Game A"]
assert tally["Game A"]["per_1000"] == round(13000 / len(LINES), 2)
assert {kind: value["lines"] for kind, value in tally["Game A"]["kinds"].items()} == {
    "fit/format": 1,
    "glossary/name": 2,
    "meaning": 1,
    "fluency": 6,
    "legacy output": 1,
    "other": 2,
}, tally["Game A"]["kinds"]
assert (
    tally["Game B"]["translated_lines"] == 4
    and report["pooled"]["corrected_lines"] == 16
)
assert report["pooled"]["recurring"]["groups"] == 1
assert "change:boss -> chief" in corrections.render(report)
# The export: a versioned header, then rows of the documented fields, never
# inside a game, a task, its workspace or the source tree.
for refused in (
    game / "out.jsonl",
    origins[0].path / "out.jsonl",
    storage / "out.jsonl",
    root / "out.jsonl",
):
    try:
        corrections.check_destination(refused, origins)
    except ValueError:
        pass
    else:
        raise AssertionError(f"export allowed into {refused}")
out = corrections.check_destination(temporary / "out.jsonl", origins)
assert corrections.export(found, out) == 17
header, *lines = [
    json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()
]
assert (
    header["schema"] == corrections.EXPORT_SCHEMA
    and header["version"] == corrections.VERSION
)
assert all(tuple(line) == corrections.EXPORT_FIELDS for line in lines), lines[0]
assert snapshot() == before, "reading QA records changed a file"
