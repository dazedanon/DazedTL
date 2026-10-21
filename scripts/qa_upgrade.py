"""The previous-release QA check: Text QA tasks the previous release made go on
with this code. See "Previous-release QA check" in docs/development.md.

    qa_upgrade.py game CODE WORK   translates the fixture game into WORK twice
    qa_upgrade.py old CODE WORK    prepares and reviews tasks there with CODE
    qa_upgrade.py new CODE WORK    continues, finishes and applies them

scripts/qa-upgrade.mjs runs `old` with the previous release's code and its
copy of this file, when it has one, and `game` and `new` with this checkout.
Each phase reads and writes WORK/upgrade.json, whose keys stay the same
between releases.
"""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

phase, code, work = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(code / "backend/dazedtl/engine"))
sys.path.insert(0, str(code / "backend"))

# The fixture game's lines its reviewers correct: a message QA corrects, and
# one it asks the user about.
CORRECTED = "おお、ミカよ。よく来てくれた。\n森の奥に魔法の杖が眠っているそうじゃ。"
ASKED = "わかりました！行ってきます！"
JAPANESE = re.compile(r"[　-〿぀-ヿ㐀-鿿＀-￯]")
GAMES = ("finished", "reviewing")


def translated(text):
    """A translation of every line, as the live test's provider answers:
    Japanese becomes a marker unique to the line."""
    kept = re.sub(r"\s+", " ", JAPANESE.sub(" ", text)).strip()
    marker = (
        hashlib.sha256(text.encode("utf-8"))
        .hexdigest()[:8]
        .translate(str.maketrans("0123456789", "ghijklmnop"))
    )
    return f"Tested {marker}" + (f" {kept}" if kept else "")


def translate(value):
    if isinstance(value, str):
        return translated(value) if JAPANESE.search(value) else value
    if isinstance(value, list):
        return [translate(item) for item in value]
    if isinstance(value, dict):
        return {key: translate(item) for key, item in value.items()}
    return value


def game():
    """Two copies of the fixture game, translated as DazedTL writes
    translations, so each keeps its Japanese beside the English."""
    from util.len_originals import write_rpgmaker_json

    staging = work / "staging"
    staging.mkdir(parents=True)
    for name in GAMES:
        folder = work / name
        shutil.copytree(code / "tests/fixtures/mz-game", folder)
        for path in sorted((folder / "data").glob("*.json")):
            staged = staging / path.name
            staged.write_text(
                json.dumps(
                    translate(json.loads(path.read_text("utf-8"))), ensure_ascii=False
                ),
                encoding="utf-8",
            )
            write_rpgmaker_json(path, staged, path)
    shutil.rmtree(staging)


def review(qa, task, stop_at_deep=False):
    """Review *task* as two reviewers would: the screen flags the corrected
    and asked lines, deep review corrects one and asks about the other, and
    the rest reads right. With *stop_at_deep*, stops once deep review waits."""
    results = work / "results"
    results.mkdir(exist_ok=True)
    while row := qa.next_bundle(task, "rev-a") or qa.next_bundle(task, "rev-b"):
        stage = row["id"].split("-")[0]
        if stage == "deep" and stop_at_deep:
            qa.release_bundle(task, row["id"])
            return
        bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        items = bundle["items"]
        if stage == "screen":
            targets = [
                (line["id"], line["source"])
                for item in items
                if item["kind"] == "scene"
                for line in item["lines"]
                if "id" in line
            ] + [
                (item["id"], item["source"])
                for item in items
                if item["kind"] == "cluster"
            ]
            result = {
                "schema": qa.SCREEN_RESULT_SCHEMA,
                "reviewed_all": True,
                "exceptions": [
                    {
                        "id": identity,
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "The tense slips.",
                    }
                    for identity, source in targets
                    if source in (CORRECTED, ASKED)
                ],
                "motif_reviews": [
                    {
                        "id": item["id"],
                        "disposition": "preserved",
                        "note": "Kept as the game has it.",
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
                "declined": [],
                "observations": [],
            }
        elif stage == "deep":
            reviews = []
            for item in items:
                review = {
                    "id": item["id"],
                    "family_key": "",
                    "motif_ids": [],
                    "apply_identities": [],
                }
                if item["source"] in (CORRECTED, ASKED):
                    review.update(
                        disposition="actionable"
                        if item["source"] == CORRECTED
                        else "uncertain-playtest",
                        severity="medium" if item["source"] == CORRECTED else None,
                        category="meaning" if item["source"] == CORRECTED else "",
                        summary="The line slips out of the scene's past tense.",
                        evidence="The scene is told in the past tense.",
                        correction=item["translation"].replace("Tested", "Checked", 1),
                    )
                else:
                    review.update(
                        disposition="clean",
                        severity=None,
                        category="",
                        evidence="Reads right in its scene.",
                        correction=None,
                    )
                reviews.append(review)
            result = {
                "schema": qa.DEEP_RESULT_SCHEMA,
                "reviews": reviews,
                "observations": [],
            }
        elif stage == "sweep":
            result = {
                "schema": qa.SWEEP_RESULT_SCHEMA,
                "reviews": [
                    {"id": item["id"], "rejected": [], "note": ""} for item in items
                ],
            }
        else:
            result = {
                "schema": qa.EDITORIAL_RESULT_SCHEMA,
                "reviews": [
                    {"id": item["id"], "verdict": "accept", "note": ""}
                    for item in items
                ],
                "declined": [],
                "observations": [],
            }
        path = results / f"{task.name}-{row['id']}.json"
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


def old():
    """Tasks of each game as this code leaves them: one finished with a
    correction and a question not applied yet, one in deep review."""
    from util import rpgmaker_qa as qa

    storage = work / "storage"
    tasks = {}
    for name in GAMES:
        task, _state = qa.prepare_task(
            work / name, work / name / "data", "release", storage
        )
        qa.record_decision(
            task,
            "term:village-chief",
            "Render 村長 as Elder.",
            "rev-a",
            "村長",
            "Elder",
        )
        review(qa, task, stop_at_deep=name == "reviewing")
        tasks[name] = {"task": str(task), "stage": qa.status(task)["stage"]}
    (work / "upgrade.json").write_text(
        json.dumps(
            {
                "rules_version": getattr(qa, "QA_RULES_VERSION", 1),
                "storage": str(storage),
                **tasks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def fail(message):
    raise SystemExit("Previous-release QA check failed: " + message)


def apply(qa, task, undo=False):
    """Applies, or with *undo* puts back, a finished task's corrections and
    the question's proposal on a copy of the game's data and copies the
    result back, as the app's Apply does."""
    findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
    corrections = [row["id"] for row in findings["findings"]]
    proposals = [row["id"] for row in findings.get("uncertain_playtests") or []]
    if not corrections or not proposals:
        fail(
            f"{task} found {len(corrections)} corrections and asked "
            f"{len(proposals)} questions, not one of each."
        )
    descriptor = json.loads((task / "task.json").read_text(encoding="utf-8"))
    inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
    selected = qa.correction_map(task, corrections, proposals, undo=undo)
    staging = work / "apply"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(descriptor["data_root"], staging / "data")
    shutil.copyfile(task / "inventory.json", staging / "inventory.json")
    regression = qa._apply_loaded_correction_map(
        staging,
        {**descriptor, "data_root": str(staging / "data")},
        selected,
        inventory,
        dry_run_name="dry-run.json",
        regression_name="regression.json",
        nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    )
    if not regression["valid"]:
        fail(f"applying {task}'s corrections failed: {regression['errors']}")
    for name in {operation["file"] for operation in selected["operations"]}:
        shutil.copyfile(staging / "data" / name, Path(descriptor["data_root"]) / name)
    shutil.rmtree(staging)


def change_detectors():
    """Stands in for an update that changes what QA derives from the text:
    the manifest builder, the verifier and apply's regression check all give
    every line one more mechanical flag."""
    from util.qa import mechanical

    evidence = mechanical.evidence

    def changed(*arguments):
        value = evidence(*arguments)
        return {**value, "flags": [*value["flags"], "changed-detector"]}

    mechanical.evidence = changed


def new():
    """The previous release's tasks with this code and a changed detector:
    the finished one stays current and applies; the one in review goes on to
    the end, or under a new QA_RULES_VERSION is refused and QA prepares a new
    task."""
    from util import rpgmaker_qa as qa

    change_detectors()
    saved = json.loads((work / "upgrade.json").read_text(encoding="utf-8"))
    bumped = saved["rules_version"] != qa.QA_RULES_VERSION
    storage = Path(saved["storage"])

    def prepare(name):
        return qa.prepare_task(work / name, work / name / "data", "release", storage)[0]

    finished = Path(saved["finished"]["task"])
    inventory = json.loads((finished / "inventory.json").read_text(encoding="utf-8"))
    if any(
        "changed-detector" in record["mechanical"]["flags"]
        for record in inventory["records"]
    ):
        fail("the previous release's task already holds the changed detector's flag.")
    state = qa.status(finished)
    if state["stage"] != "complete" or state["rules_changed"]:
        fail(
            f"the finished task reads {state['stage']}, rules changed "
            f"{state['rules_changed']}, instead of complete."
        )
    qa.require_current(finished)
    if not bumped:
        if prepare("finished") != finished:
            fail(
                "preparing QA again made a new task instead of going on with the "
                "finished one. Keep what names a task (its inputs) as it was, or "
                "bump QA_RULES_VERSION if old reviews are wrong now."
            )
        if not qa.inventory_matches(
            finished, qa.build_manifest(work / "finished" / "data", "release")
        ):
            fail("the finished task's inventory no longer reads as the game's.")
    apply(qa, finished)
    apply(qa, finished, undo=True)
    apply(qa, finished)

    reviewing = Path(saved["reviewing"]["task"])
    if bumped:
        if not qa.status(reviewing)["rules_changed"]:
            fail("a task in review under the earlier QA_RULES_VERSION reads current.")
        try:
            qa.next_bundle(reviewing, "rev-a")
        except ValueError:
            pass
        else:
            fail(
                "a task in review under the earlier QA_RULES_VERSION took more review."
            )
        reviewing = prepare("reviewing")
    else:
        qa.require_current(reviewing)
        if qa.status(reviewing)["rules_changed"] or prepare("reviewing") != reviewing:
            fail(
                "the task in review did not go on: preparing QA again made a new "
                "task. Keep what names a task (its inputs) as it was, or bump "
                "QA_RULES_VERSION if old reviews are wrong now."
            )
    review(qa, reviewing)
    if qa.status(reviewing)["stage"] != "complete":
        fail(f"the task in review stopped at {qa.status(reviewing)['stage']}.")
    apply(qa, reviewing)
    print(
        f"Previous-release QA check passed: QA rules version {saved['rules_version']}"
        f" -> {qa.QA_RULES_VERSION}, with a changed detector; the finished task applied, undid and applied "
        "again, and the one in review "
        + ("was prepared again and " if bumped else "")
        + "finished and applied."
    )


{"game": game, "old": old, "new": new}[phase]()
