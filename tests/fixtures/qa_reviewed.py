"""Text QA builds on earlier reviews: lines a finished task reviewed, and a
version the user says was checked before, are read only as context."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from dazedtl.compatibility.playtest import reviewing
from util import rpgmaker_qa as qa

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)
(game / ".dazedtl").mkdir()
storage = temporary / "storage"


def line(original, text):
    """A message's commands: the first holds its Japanese, and each a row."""
    first, *rows = text.split("\n")
    return [
        {"code": 401, "indent": 0, "parameters": [first], "_original": original},
        *({"code": 401, "indent": 0, "parameters": [row]} for row in rows),
    ]


# A third-person line both scenes repeat, which each scene's screen reads as a
# target of its own.
PRONOUN = ("彼女はもう帰った", "She already went home.")


def write_game(lines):
    """Two scenes of the given (original, text) lines, three and the rest,
    each ending with the shared line."""
    pages = [[*lines[:3], PRONOUN], [*lines[3:], PRONOUN]]
    document = {
        "events": [None]
        + [
            {
                "id": number,
                "pages": [
                    {
                        "list": [
                            *(command for pair in page for command in line(*pair)),
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
    # A message over two commands.
    ("扉を開けた", "I open\nthe door."),
    ("静かな部屋だ", "A quiet room."),
    ("剣を抜け", "Draw your sword!"),
    ("ミナが来る", "Mina comes."),
]
write_game(LINES)
glossary("剣 (sword)\nミナ (Mina)\n")


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
                        "summary": "The line breaks the scene's past tense.",
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
    if qa.status(task)["stage"] == "ready-finalize":
        qa.finalize(task)
    assert qa.status(task)["stage"] == "complete", qa.status(task)


# The playtest found two lines running past their window.
probe = prepare()
found = [
    {
        "identity": name,
        "categories": ["ui"],
        "note": "This text runs past the right edge of Window_Message.",
    }
    for name in (
        "Map001.json#/events/1/pages/0/list/0/_original",
        "Map001.json#/events/1/pages/0/list/1/_original",
    )
]
shutil.rmtree(probe)
first = prepare(observations=found)
assert targets(first) == sorted(
    [*(source for source, _text in LINES), PRONOUN[0], PRONOUN[0]]
), targets(first)
finish(first, {"扉を開けた"}, {"扉を開けた": "I opened the door."})
# Nothing changed, so preparing again is the same, finished task.
assert prepare() == first
workflow = temporary / "workflow"
workflow.mkdir()


def labels(task, problems=found):
    """How the playtest's problems on the lines read with *task* as QA's."""
    (workflow / "text-qa-release.json").write_text(
        json.dumps({"task": str(task)}), encoding="utf-8"
    )
    review = reviewing(workflow, "release")
    review.read({row["identity"] for row in problems}, {})
    return [review.state(row["identity"], row["note"]) for row in problems]


# A problem on a reviewed line for a reason the task never took waits for
# QA's next round, so the final check doesn't finish without it.
squeezed = {**found[0], "note": "Squeezed into the name box."}
assert labels(first, [*found, squeezed]) == ["reviewed", "reviewed", "waiting"]
# Findings another task made are no review of this one, and a task the app
# set aside as unreadable is no review to build on, even with its ledger
# saved before.
findings = first / "findings.json"
saved = findings.read_bytes()
findings.write_text(
    json.dumps({**json.loads(saved), "task_sha256": "0" * 64}), encoding="utf-8"
)
assert qa._task_ledger(first) is None
findings.write_bytes(saved)
assert qa._task_ledger(first)
# A ledger an earlier version saved is derived again.
cached = first / qa.REVIEWED_FILE
cached.write_text(
    json.dumps(
        {**json.loads(cached.read_text(encoding="utf-8")), "version": 1, "pairs": []}
    ),
    encoding="utf-8",
)
assert qa._task_ledger(first)["pairs"]
aside = first.rename(first.with_name(first.name + "-unreadable"))
assert len(targets(prepare())) == 7
shutil.rmtree(first)
aside.rename(first)

# The correction is applied as the app applies it, its rows spread over the
# message's commands, and the glossary entries for 剣 and ミナ gain notes:
# the next task screens only the lines the changed entries govern. Neither
# scene reads the shared line again, since one changed only by a confirmed
# correction and the other only by guidance for other lines.
(finding,) = json.loads(saved)["findings"]
assert qa._apply_loaded_correction_map(
    first,
    json.loads((first / "task.json").read_text(encoding="utf-8")),
    qa.correction_map(first, [finding["id"]]),
    json.loads((first / "inventory.json").read_text(encoding="utf-8")),
    dry_run_name="dry-run.json",
    regression_name="regression.json",
)["valid"]
LINES[1] = ("扉を開けた", "I opened the door.\n")
written = json.loads((data / "Map001.json").read_text(encoding="utf-8"))
write_game(LINES)
assert json.loads((data / "Map001.json").read_text(encoding="utf-8")) == written
# The playtest still finds the corrected line too long: the task reviewed
# its earlier text, so that problem waits for QA's next round.
assert labels(first) == ["reviewed", "waiting"]
glossary("剣 (sword) - The hero's only weapon.\nミナ (Mina) - Calls herself Mina.\n")
second = prepare(observations=found)
assert second != first
# The first task's path now refuses work and names the task that replaced
# it: on Fuuma, a coordinator kept running the old README's commands, read
# "complete" and never reviewed the new round.
try:
    qa.require_current(first)
except ValueError as error:
    assert str(second) in str(error), error
else:
    raise AssertionError("A replaced task still took work.")
qa.require_current(second)
assert targets(second) == ["ミナが来る", "剣を抜け"], targets(second)
# The next round reviews the corrected line, and leaves out the other, which
# deep review judged for the same text and reason: it reads as reviewed,
# never as outside QA's review, while it was judged for that reason only.
assert labels(second, [*found, squeezed]) == ["reviewed", "reviewing", "waiting"]
assert prepare(observations=found) == second
assert [
    row["note"]
    for row in json.loads((second / "checkpoint.json").read_text(encoding="utf-8"))[
        "observations"
    ]
] == [found[1]["note"]]
# Lines count every place a text shows, so the shared line counts twice; the
# corrected line the playtest still flags is this round's to check.
assert qa.status(second)["reviewed_before"] == {
    "lines": 4,
    "from": [f"task {first.name}"],
}, qa.status(second)["reviewed_before"]
# A retranslated line is screened, and so is the shared line in its scene,
# whose text changed.
LINES[2] = ("静かな部屋だ", "It's a quiet room.")
write_game(LINES)
assert targets(prepare()) == [
    "ミナが来る",
    "剣を抜け",
    "彼女はもう帰った",
    "静かな部屋だ",
]
# The same, reviewing everything, is another task, which preparing again
# goes on with.
everything = prepare(earlier=False)
assert len(targets(everything)) == 7 and everything != second
assert prepare() == everything
# A task whose screen is done is rebuilt under rules an update changed from
# the same earlier reviews it read, so it keeps that screen, here every line.
finish(everything, set(), {})
fingerprint = qa._engine_fingerprint
qa._engine_fingerprint = lambda: "updated rules"
# The update changed the extractor's code too, which its inventories name, and
# what it derives from the text, such as each line's mechanical evidence.
build, verify = qa.build_manifest, qa.verify_manifest


def rebuilt_manifest(*arguments):
    manifest = build(*arguments)
    del manifest["content_sha256"]
    manifest["extractor_source_sha256"] = "0" * 64
    for record in manifest["records"]:
        record["mechanical"]["source_runtime_tokens"].append("\\n<")
    manifest["content_sha256"] = qa._sha256(qa._canonical_bytes(manifest))
    return manifest


screen_items = qa._screen_items


def hinted(*arguments):
    """Screen items whose hints the update words otherwise, as one changed
    which glossary terms they name, at such length that the screen would be
    packed into other bundles."""
    items, index = screen_items(*arguments)
    items[0]["risk"] = ["x" * qa.DEFAULT_SCREEN_CHAR_BUDGET]
    return items, index


qa.build_manifest = rebuilt_manifest
qa.verify_manifest = lambda *_arguments: {"valid": True, "errors": []}
qa._screen_items = hinted
rebuilt, state = qa.rebuild_deep_from_screen(everything)
assert rebuilt != everything and state["screen"]["accepted"] == 7, state
# One that can't keep it leaves no task behind.
write_game([*LINES[:4], ("ミナが来る", "Here comes Mina.")])
tasks = set(rebuilt.parent.iterdir())
try:
    qa.rebuild_deep_from_screen(everything)
except ValueError as error:
    assert "text changed" in str(error), error
else:
    raise AssertionError("A screen of other text was reused.")
assert set(rebuilt.parent.iterdir()) == tasks
qa._engine_fingerprint = fingerprint
qa.build_manifest, qa.verify_manifest = build, verify
qa._screen_items = screen_items
write_game(LINES)


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
# Both scenes changed since the baseline, so each reads the shared line again.
assert targets(scoped) == ["おはよう", PRONOUN[0], PRONOUN[0], "新しい台詞"], targets(
    scoped
)
# Preparing again goes on with the scope named last.
assert prepare(earlier=False) != scoped
assert prepare(since="1.10") == prepare() == scoped
# The scope stays in effect for the game's later tasks, and naming a version
# the game was never updated to is refused.
LINES[3] = ("剣を抜け", "Unsheathe your sword!")
write_game(LINES)
assert targets(prepare()) == [
    "おはよう",
    "剣を抜け",
    PRONOUN[0],
    PRONOUN[0],
    "新しい台詞",
]
try:
    prepare(since="9.99")
except ValueError as error:
    assert "9.99" in str(error), error
else:
    raise AssertionError("An unknown version scoped QA.")
