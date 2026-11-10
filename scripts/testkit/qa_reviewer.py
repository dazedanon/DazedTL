"""Plays the AI reviewers of a Text QA task, for test scenarios: workers take
every bundle through this checkout's engine and review it clean, except the
first deep item, which gets a correction so applying has a finding. It ends
when the task is complete and prints what each stage reviewed.

    python scripts/testkit/qa_reviewer.py TASK RESULTS [--clean] [--ask]
        [--corrections FILE]

TASK is the task folder the project helper's `qa --prepare` names; results go
to RESULTS. With --clean, every item is reviewed clean. With --ask, each line
an observation brings to deep review, such as the playtest's, is a question
for the user with a proposal. With --corrections, FILE's corrections replace
the first item's: a JSON list of {translation, correction, category,
summary}, each line whose translation is `translation` sent from the screen to
deep review and corrected there, with the editorial_basis a subjective
category such as fluency needs. A correction with `item`, such as "voice",
is reported only from screen items of that kind.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa


def clean(item):
    return {
        "id": item["id"],
        "disposition": "clean",
        "severity": None,
        "category": "",
        "family_key": "",
        "motif_ids": [],
        "evidence": "Checked; no defect.",
        "correction": None,
        "apply_identities": [],
    }


def screen(bundle, _corrected, corrections=None):
    items = bundle["items"]
    # A scene or voice item lists its lines; another item is its own line.
    lines = [
        (item.get("kind"), line)
        for item in items
        for line in item.get("lines") or [item]
    ]
    return {
        "schema": qa.SCREEN_RESULT_SCHEMA,
        "reviewed_all": True,
        "exceptions": [
            {
                "id": line["id"],
                "verdict": "suspect",
                "categories": [fix["category"]],
                "note": fix["summary"],
            }
            for kind, line in lines
            if "id" in line
            for fix in corrections or []
            if fix["translation"] == line.get("translation")
            and fix.get("item", kind) == kind
        ],
        "motif_reviews": [
            {
                "id": item["id"],
                "disposition": "preserved",
                "note": "Every variant keeps it.",
                "suspect_ids": [],
            }
            for item in items
            if item.get("kind") == "motif-family"
        ],
        "lint_reviews": [
            {"id": item["id"], "rejected": [], "note": ""}
            for item in items
            if item.get("kind") == "lint-family"
        ],
        "declined": [],
        "observations": [],
    }


def deep(bundle, corrected, ask=False, corrections=None):
    reviews = []
    for item in bundle["items"]:
        text = item.get("translation") or ""
        given = next(
            (fix for fix in corrections or [] if fix["translation"] == text), None
        )
        if given:
            corrected.append(item["id"])
            reviews.append(
                {
                    **clean(item),
                    "disposition": "actionable",
                    "severity": "medium",
                    "category": given["category"],
                    "summary": given["summary"],
                    "evidence": "A scripted reviewer makes the corrections it is given.",
                    "correction": given["correction"],
                    **(
                        {"editorial_basis": given["editorial_basis"]}
                        if "editorial_basis" in given
                        else {}
                    ),
                }
            )
        elif ask and any(
            evidence.get("verdict") == "observation"
            for evidence in item.get("screen_evidence") or []
        ):
            reviews.append(
                {
                    **clean(item),
                    "disposition": "uncertain-playtest",
                    "summary": "Only the game shows whether this fits.",
                    "evidence": "A scripted reviewer asks about each observed line.",
                    "correction": f"{text} (asked)",
                }
            )
        elif (
            not corrected
            and corrections is None
            and text
            and "\n" not in text
            and "%" not in item.get("source", "")
        ):
            corrected.append(item["id"])
            reviews.append(
                {
                    **clean(item),
                    "disposition": "actionable",
                    "severity": "medium",
                    "category": "meaning",
                    "summary": "The line needs a plainer word.",
                    "evidence": "A scripted reviewer corrects one line so QA has a finding.",
                    "correction": f"{text} (checked)",
                }
            )
        else:
            reviews.append(clean(item))
    return {"schema": qa.DEEP_RESULT_SCHEMA, "reviews": reviews, "observations": []}


def sweep(bundle, _corrected):
    return {
        "schema": qa.SWEEP_RESULT_SCHEMA,
        "reviews": [
            {"id": item["id"], "rejected": [], "note": ""} for item in bundle["items"]
        ],
        "declined": [],
        "observations": [],
    }


def editorial(bundle, _corrected):
    return {
        "schema": qa.EDITORIAL_RESULT_SCHEMA,
        "reviews": [
            {"id": item["id"], "verdict": "accept", "note": ""}
            for item in bundle["items"]
        ],
        "declined": [],
        "observations": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=str(__doc__).split("\n", 1)[0])
    parser.add_argument("task", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--ask", action="store_true")
    parser.add_argument("--corrections", type=Path)
    args = parser.parse_args()
    corrections = (
        json.loads(args.corrections.read_text(encoding="utf-8"))
        if args.corrections
        else None
    )
    args.results.mkdir(parents=True, exist_ok=True)
    reviewers = {
        "screen": lambda bundle, corrected: screen(bundle, corrected, corrections),
        "deep": lambda bundle, corrected: deep(
            bundle, corrected, args.ask, corrections
        ),
        "sweep": sweep,
        "editorial": editorial,
    }
    # A list, so "--clean" can start it full.
    corrected = ["none"] if args.clean else []
    reviewed: dict[str, int] = {}
    idle = 0
    while True:
        took = False
        # Two workers, so check bundles find a reviewer other than the screener.
        for worker in ("rev-1", "rev-2"):
            row = qa.next_bundle(args.task, worker)
            if not row:
                continue
            bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            kind = row["id"].split("-")[0]
            result = reviewers[kind](bundle, corrected)
            result.update(bundle_id=row["id"], bundle_sha256=row["sha256"])
            path = args.results / f"{row['id']}.json"
            path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            qa.accept_result(args.task, path)
            reviewed[kind] = reviewed.get(kind, 0) + len(bundle["items"])
            took = True
        if took:
            idle = 0
            continue
        stage = qa.status(args.task)["stage"]
        if stage == "complete":
            break
        idle += 1
        if idle > 4:
            raise SystemExit(f"QA stopped moving at the {stage} stage.")
        if stage == "ready-finalize":
            qa.finalize(args.task)
        else:
            qa.advance(args.task)
    print(
        json.dumps({"stage": "complete", "reviewed": reviewed, "corrected": corrected})
    )


if __name__ == "__main__":
    main()
