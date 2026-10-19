"""Text QA builds on earlier reviews: lines a finished task reviewed, and a
version the user says was checked before, are read only as context."""

import json
import subprocess
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)
(game / ".dazedtl").mkdir()
storage = temporary / "storage"


def line(original, text):
    return {"code": 401, "indent": 0, "parameters": [text], "_original": original}


def write_game(lines):
    """Two scenes of the given (original, text) lines, three and the rest."""
    pages = [lines[:3], lines[3:]]
    document = {
        "events": [None]
        + [
            {
                "id": number,
                "pages": [
                    {
                        "list": [
                            *(line(*pair) for pair in page),
                            {"code": 0, "indent": 0, "parameters": []},
                        ]
                    }
                ],
            }
            for number, page in enumerate(pages, start=1)
        ]
    }
    (data / "Map001.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )


def glossary(text):
    (game / ".dazedtl/glossary.txt").write_text(text, encoding="utf-8")


LINES = [
    ("おはよう", "Good morning."),
    ("扉を開けた", "I open the door."),
    ("静かな部屋だ", "A quiet room."),
    ("剣を抜け", "Draw your sword!"),
    ("魔王が来る", "The Demon King comes."),
]
write_game(LINES)
glossary("剣 (sword)\n")


def targets(task):
    """The Japanese this task's screen bundles hold as targets."""
    found = []
    checkpoint = json.loads((task / "checkpoint.json").read_text(encoding="utf-8"))
    for row in checkpoint["screen"]["bundles"]:
        for item in json.loads(Path(row["path"]).read_text(encoding="utf-8"))["items"]:
            if item["kind"] == "scene":
                found += [
                    target["source"] for target in item["lines"] if "id" in target
                ]
            elif item["kind"] == "cluster":
                found.append(item["source"])
    return sorted(found)


def prepare(**options):
    return qa.prepare_task(game, data, "release", storage, **options)[0]


def finish(task, flagged, corrections):
    """Review the task to completion: the screen flags *flagged*, deep review
    corrects what *corrections* names and editorial accepts; a second
    reviewer takes the checks and editorial the first may not."""
    while row := qa.next_bundle(task, "rev-a") or qa.next_bundle(task, "rev-b"):
        bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        if row["id"].startswith("screen"):
            result = {
                "schema": qa.SCREEN_RESULT_SCHEMA,
                "reviewed_all": True,
                "exceptions": [
                    {
                        "id": target["id"],
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "Tense slips.",
                    }
                    for item in bundle["items"]
                    if item["kind"] == "scene"
                    for target in item["lines"]
                    if "id" in target and target["source"] in flagged
                ],
                "motif_reviews": [],
                "lint_reviews": [],
                "declined": [],
                "observations": [],
            }
        elif row["id"].startswith("deep"):
            result = {
                "schema": qa.DEEP_RESULT_SCHEMA,
                "reviews": [
                    {
                        "id": item["id"],
                        "disposition": "actionable",
                        "severity": "medium",
                        "category": "meaning",
                        "family_key": "",
                        "motif_ids": [],
                        "evidence": "The scene is told in the past tense.",
                        "correction": corrections[item["source"]],
                        "apply_identities": [],
                    }
                    if item["source"] in corrections
                    else {
                        "id": item["id"],
                        "disposition": "clean",
                        "severity": None,
                        "category": "",
                        "family_key": "",
                        "motif_ids": [],
                        "evidence": "Reads right in its scene.",
                        "correction": None,
                        "apply_identities": [],
                    }
                    for item in bundle["items"]
                ],
                "observations": [],
            }
        else:
            result = {
                "schema": qa.EDITORIAL_RESULT_SCHEMA,
                "reviews": [
                    {"id": item["id"], "verdict": "accept", "note": ""}
                    for item in bundle["items"]
                ],
                "declined": [],
                "observations": [],
            }
        path = temporary / f"{row['id']}.json"
        path.write_text(
            json.dumps(
                {**result, "bundle_id": row["id"], "bundle_sha256": row["sha256"]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        qa.accept_result(task, path)
    assert qa.status(task)["stage"] == "complete", qa.status(task)


first = prepare()
assert targets(first) == sorted(source for source, _text in LINES), targets(first)
finish(first, {"扉を開けた"}, {"扉を開けた": "I opened the door."})
# Nothing changed, so preparing again is the same, finished task.
assert prepare() == first

# The correction is applied, one line is retranslated, and the glossary entry
# for 剣 gains a note: the next task screens the retranslated line and the
# line the changed entry governs, and reads the rest only as context.
LINES[1] = ("扉を開けた", "I opened the door.")
LINES[4] = ("魔王が来る", "Here comes the Demon King.")
write_game(LINES)
glossary("剣 (sword) - The hero's only weapon.\n")
second = prepare()
assert second != first
assert targets(second) == ["剣を抜け", "魔王が来る"], targets(second)
assert qa.status(second)["reviewed_before"] == {
    "lines": 3,
    "from": [f"task {first.name}"],
}, qa.status(second)["reviewed_before"]
# The first scene holds no line to review, so no reviewer reads it again.
assert "おはよう" not in "".join(
    qa.render_bundle(second, row["id"])
    for row in json.loads((second / "checkpoint.json").read_text())["screen"]["bundles"]
)
# The same, reviewing everything, is another task.
everything = prepare(earlier=False)
assert len(targets(everything)) == 5 and everything != second


# The user says text from before the 1.10 update was checked elsewhere. The
# game's history records that update, after which a line was added and two
# were translated.
def git(*arguments):
    subprocess.run(
        [
            "git",
            "-C",
            str(game),
            "-c",
            "user.name=QA",
            "-c",
            "user.email=qa@example.invalid",
            *arguments,
        ],
        check=True,
        capture_output=True,
    )


git("init", "-q")
git("add", "-A")
git("commit", "-q", "-m", "Translate 1.01")
LINES.append(("新しい台詞", "誰だ"))
write_game(LINES)
git(
    "commit",
    "-q",
    "-am",
    "patch: update original game files to 1.10\n\nDazedTL-Version: 1.10",
)
LINES[5] = ("新しい台詞", "A new line.")
LINES[0] = ("おはよう", "Morning!")
write_game(LINES)
git("commit", "-q", "-am", "Translate 1.10")
scoped = prepare(since="1.10")
assert targets(scoped) == ["おはよう", "新しい台詞"], targets(scoped)
# The scope stays in effect for the game's later tasks, and naming a version
# the game was never updated to is refused.
LINES[3] = ("剣を抜け", "Unsheathe your sword!")
write_game(LINES)
assert targets(prepare()) == ["おはよう", "剣を抜け", "新しい台詞"]
try:
    prepare(since="9.99")
except ValueError as error:
    assert "9.99" in str(error), error
else:
    raise AssertionError("An unknown version scoped QA.")
