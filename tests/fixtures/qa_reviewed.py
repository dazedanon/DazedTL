"""Text QA builds on earlier reviews: lines a finished task reviewed, and a
version the user says was checked before, are read only as context."""

import hashlib
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
from util import rpgmaker_qa_manifest, rpgmaker_qa_verify
from util.qa import apply as qa_apply
from util.qa import ledger as qa_ledger
from util.qa import prepare as qa_prepare
from util.qa import storage as qa_storage

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


def finish(task, flagged, corrections, asked=None):
    """Review the task to completion: the screen flags *flagged*, deep review
    corrects what *corrections* names, asks the user about what *asked*
    proposes, and editorial accepts; a second reviewer takes the checks and
    editorial the first may not."""
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
                        "disposition": "uncertain-playtest",
                        "severity": None,
                        "category": "",
                        "family_key": "",
                        "motif_ids": [],
                        "summary": "Whether the box fits the greeting.",
                        "evidence": "Only the game shows how wide it draws.",
                        "correction": (asked or {})[item["source"]],
                        "apply_identities": [],
                    }
                    if item["source"] in (asked or {})
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


def labels(task, problems=found, hashes=None):
    """How the playtest's problems on the lines read with *task* as QA's;
    *hashes* gives the data files' as the game holds them."""
    (workflow / "text-qa-release.json").write_text(
        json.dumps({"task": str(task)}), encoding="utf-8"
    )
    review = reviewing(workflow, "release")
    review.read({row["identity"] for row in problems}, hashes or {})
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
# Deep review judged the playtest's first line right as it is, and corrected
# the second: until that correction is in the game, a new task takes the
# second line's observation again. On Fuuma, editorial left two corrected
# descriptions unverified, and the next round left them out as judged.
earlier = qa._earlier_reviews(
    storage / qa._slug(game.name),
    json.loads((first / "context.json").read_text(encoding="utf-8")),
    json.loads((first / "task.json").read_text(encoding="utf-8"))["layout"],
)
assert [
    earlier.observed(source, text, found[0]["note"]) for source, text in LINES[:2]
] == [True, False]
# The playtest's problem on that line then waits for QA's next round once
# other text changed, since preparing again makes a task that takes the line
# back; while nothing changed, preparing again resumes this task.
LINES[2] = ("静かな部屋だ", "So quiet in here.")
write_game(LINES)
hashes = {
    "Map001.json": hashlib.sha256((data / "Map001.json").read_bytes()).hexdigest()
}
assert labels(first, hashes=hashes) == ["reviewed", "waiting"]
LINES[2] = ("静かな部屋だ", "A quiet room.")
write_game(LINES)

# The correction is applied as the app applies it, its rows spread over the
# message's commands, and the glossary entries for 剣 and ミナ gain notes:
# the next task screens only the lines the changed entries govern. Neither
# scene reads the shared line again, since one changed only by a confirmed
# correction and the other only by guidance for other lines.
(finding,) = json.loads(saved)["findings"]
assert qa.apply_loaded_correction_map(
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
finish(everything, set(), {})
# An update that derives otherwise from the text, such as each line's
# mechanical evidence, leaves a task of the same text current: preparing again
# goes on with it, and its inventory reads as the game's.
build, verify = rpgmaker_qa_manifest.build_manifest, rpgmaker_qa_verify.verify_manifest


def rebuilt_manifest(*arguments):
    manifest = build(*arguments)
    del manifest["content_sha256"]
    for record in manifest["records"]:
        record["mechanical"]["source_runtime_tokens"].append("\\n<")
    manifest["content_sha256"] = qa._sha256(qa._canonical_bytes(manifest))
    return manifest


screen_items = qa_prepare._screen_items


def hinted(*arguments):
    """Screen items whose hints the update words otherwise, as one changed
    which glossary terms they name, at such length that the screen would be
    packed into other bundles."""
    items, index = screen_items(*arguments)
    items[0]["risk"] = ["x" * qa.DEFAULT_SCREEN_CHAR_BUDGET]
    return items, index


for module in (qa_ledger, qa_prepare, qa_apply):
    module.build_manifest = rebuilt_manifest
for module in (qa_prepare, qa_apply):
    module.verify_manifest = lambda *_arguments: {"valid": True, "errors": []}
assert prepare() == everything
assert qa.inventory_matches(everything, rebuilt_manifest(data, "release"))
# Bumping QA's rules version makes another task, which a rebuild fills from a
# finished screen read from the same earlier reviews, here every line.
qa_storage.QA_RULES_VERSION = qa_prepare.QA_RULES_VERSION = qa.QA_RULES_VERSION + 1
qa_prepare._screen_items = hinted
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
qa_storage.QA_RULES_VERSION = qa_prepare.QA_RULES_VERSION = qa.QA_RULES_VERSION
for module in (qa_ledger, qa_prepare, qa_apply):
    module.build_manifest = build
for module in (qa_prepare, qa_apply):
    module.verify_manifest = verify
qa_prepare._screen_items = screen_items
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


def made_by_2_24(task):
    """*task* as 2.24.0 and earlier left it: its key and task.json name a hash
    of QA's code files, and its inventory the extractor's own hash."""
    write = lambda name, value: (task / name).write_bytes(
        qa._canonical_bytes(value) + b"\n"
    )
    read = lambda name: json.loads((task / name).read_text(encoding="utf-8"))
    inventory = read("inventory.json")
    del inventory["content_sha256"]
    inventory["extractor_source_sha256"] = "e" * 64
    inventory["content_sha256"] = qa._sha256(qa._canonical_bytes(inventory))
    write("inventory.json", inventory)
    descriptor = read("task.json")
    del descriptor["rules_version"]
    descriptor["engine_fingerprint"] = "f" * 64
    descriptor["manifest_sha256"] = inventory["content_sha256"]
    write("task.json", descriptor)
    checkpoint = read("checkpoint.json")
    checkpoint["task_sha256"] = qa._sha256(qa._canonical_bytes(descriptor))
    write("checkpoint.json", checkpoint)
    baselines = sorted(
        path.stem
        for path in (storage / qa._slug(game.name) / qa.BASELINE_FOLDER).glob("*.json")
    )
    key = hashlib.sha256(
        (
            f"{qa.TASK_SCHEMA}\0{'f' * 64}\0release\0{inventory['content_sha256']}\0"
            f"{descriptor['context_sha256']}\0"
            + qa._sha256(qa._canonical_bytes(descriptor["screen_configuration"]))
            + f"\0baselines:{','.join(baselines)}"
        ).encode()
    ).hexdigest()[:16]
    # Its bundles' paths and the task preparing QA returned last name its key.
    old, new = (json.dumps(str(path))[1:-1] for path in (task, task.with_name(key)))
    text = (task / "checkpoint.json").read_text(encoding="utf-8")
    (task / "checkpoint.json").write_text(text.replace(old, new), encoding="utf-8")
    (task.parent / qa.CURRENT_FILE).write_text(json.dumps({"task": key}))
    return task.rename(task.with_name(key))


# A task 2.24.0 or earlier made of the same text and scope goes on, in review
# here, and its helpers find it current.
scoped = made_by_2_24(scoped)
assert prepare(since="1.10") == prepare() == scoped
qa.require_current(scoped)
row = qa.next_bundle(scoped, "rev-a")
qa.release_bundle(scoped, row["id"])
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

# A question the user answers Keep settles its line: the playtest found the
# first line too long, deep review asked about a shorter one, the user kept
# the line, and other text changed, as once QA's corrections are in. On the
# Text QA page the kept line's problem read waiting and the next round asked
# again. 2.24.0 saved the answer only in the game's workflow folder.
storage = workflow / "text-qa"
kept = [found[0]]
asked = prepare(observations=kept)
finish(asked, set(), {}, {"おはよう": "Hi!"})
(question,) = json.loads((asked / "findings.json").read_text(encoding="utf-8"))[
    "uncertain_playtests"
]
choices = workflow / "text-qa-choices.json"
choices.write_text(json.dumps({str(asked): {question["id"]: "keep"}}), encoding="utf-8")
LINES[2] = ("静かな部屋だ", "Such a quiet room.")
write_game(LINES)
hashes = {
    "Map001.json": hashlib.sha256((data / "Map001.json").read_bytes()).hexdigest()
}
assert labels(asked, kept, hashes) == ["reviewed"]
# The record stays for going back to 2.24.0, and an answer the task holds,
# given since, wins over it.
assert qa.answers(asked) == {question["id"]: "keep"} and choices.exists()
qa.answer(asked, question["id"], "use")
assert labels(asked, kept, hashes) == ["waiting"]
assert qa.answers(asked) == {question["id"]: "use"}
qa.answer(asked, question["id"], "keep")
# The next round reads the kept line as reviewed and leaves its problem out.
again = prepare(observations=kept)
assert again != asked and "おはよう" not in targets(again), targets(again)
assert not json.loads((again / "checkpoint.json").read_text(encoding="utf-8"))[
    "observations"
]
assert labels(again, kept, hashes) == ["reviewed"]

# A moved or renamed game keeps its tasks. Their context names the game's
# files relative to its folder; one a version that named the folder there
# prepared goes on while the game stays where it was.
from unittest import mock

from dazedtl.compatibility import text
from util.qa import selection as qa_selection

LINES[0] = ("おはよう", "Hello there.")
write_game(LINES)
with mock.patch.object(qa_selection, "in_game", lambda path, _root: path):
    legacy = prepare()
assert prepare() == legacy
LINES[0] = ("おはよう", "Good day.")
write_game(LINES)
fresh = prepare()
context = json.loads((fresh / "context.json").read_text(encoding="utf-8"))
assert context["glossary"]["path"] == ".dazedtl/glossary.txt", context["glossary"]
# The app keeps a project's tasks in a folder named for it; the one an
# earlier version named for the game folder goes on, which the task a
# focus's record names shows after a rename.
moved = game.rename(temporary / "Renamed")
plan = {
    "folder": str(workflow),
    "project": {"source": str(moved)},
    "project_id": "project",
    "options": {"focus": "release"},
}
(workflow / "text-qa-release.json").unlink()
assert text._storage_key(plan) == "project"
(workflow / "text-qa-release.json").write_text(json.dumps({"task": str(fresh)}))
assert text._storage_key(plan) == "game"
# Prepared again where it is now, the task in review goes on, its README
# naming the game there, which the app finds through the project.
qa_storage.game_folder.layer("moved", lambda _native, _task, _value: str(moved))
key = text._storage_key(plan)
assert (
    qa.prepare_task(moved, moved / "data", "release", storage, storage_key=key)[0]
    == fresh
)
readme = (fresh / "README.md").read_text(encoding="utf-8")
assert str(moved) in readme and str(game) not in readme
