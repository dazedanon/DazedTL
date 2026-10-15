"""The release playtest in the game's Guided workspace: the action that
plays the game, the report it keeps, and the observations it hands to text
QA so a deep reviewer corrects what the playtest found in translated text."""

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import project_path, read_json

POINTER = "playtest.json"
STORAGE = "playtest"
# Reports kept beside the latest, for comparing runs.
KEEP = 3


def binding(guard):
    """What a report describes: the game's data, plugin list and plugins."""
    return {
        key: guard.get(key) for key in ("layout", "data", "plugins", "plugin_files")
    }


def run_playtest(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util.playtest.run import run

    validate_plan(plan)
    folder = Path(plan["folder"])
    storage = folder / STORAGE
    storage.mkdir(exist_ok=True)
    try:
        before = latest(folder)
    except ValueError, OSError, KeyError, TypeError:
        before = None
    name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    report = run(
        plan["project"]["source"],
        plan["project"]["data"],
        storage / name,
        stops=plan["options"]["stops"],
        log=log,
        stopped=getattr(log, "stopped", lambda: False),
        previous=before[1] if before else None,
    )
    write_json(
        folder / POINTER,
        {
            "report": name,
            "binding": binding(plan["guard"]),
            "finished_at": datetime.now(UTC).isoformat(),
        },
    )
    for old in sorted(path for path in storage.iterdir() if path.is_dir())[:-KEEP]:
        if old.name != name:
            shutil.rmtree(old, ignore_errors=True)
    observed = observe(folder, plan["options"]["focus"], report)
    if observed:
        log(f"Handed {observed} finding(s) to text QA's review")
    return {
        "problems": len(report["problems"]),
        "observed": observed,
        "seconds": report["seconds"],
    }


# A layout check keeps its own reports, so it never replaces the playtest's.
LAYOUT_POINTER = "layout-check.json"
LAYOUT_STORAGE = "layout-check"


def run_layout(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util.playtest.run import layout

    validate_plan(plan)
    folder = Path(plan["folder"])
    storage = folder / LAYOUT_STORAGE
    storage.mkdir(exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    result = layout(
        plan["project"]["source"],
        plan["project"]["data"],
        storage / name,
        plan["options"]["widths"],
        log=log,
        stopped=getattr(log, "stopped", lambda: False),
    )
    write_json(
        folder / LAYOUT_POINTER,
        {"report": name, "finished_at": datetime.now(UTC).isoformat()},
    )
    for old in sorted(path for path in storage.iterdir() if path.is_dir())[:-KEEP]:
        if old.name != name:
            shutil.rmtree(old, ignore_errors=True)
    return {
        "probes": len(result["probes"]),
        "fit": sum(probe["fits"] for probe in result["probes"]),
    }


def latest_layout(folder) -> dict | None:
    """The latest layout check, with its folder, or None."""
    pointer = Path(folder) / LAYOUT_POINTER
    if not pointer.exists():
        return None
    saved = read_json(pointer)
    path = project_path(Path(folder) / LAYOUT_STORAGE, saved["report"] + "/layout.json")
    return {
        **read_json(path),
        "finished_at": saved["finished_at"],
        "folder": str(path.parent),
    }


def latest(folder) -> tuple[dict, dict] | None:
    """The pointer to the latest report and the report, or None."""
    pointer = Path(folder) / POINTER
    if not pointer.exists():
        return None
    saved = read_json(pointer)
    path = project_path(Path(folder) / STORAGE, saved["report"] + "/report.json")
    return saved, read_json(path)


def pending(folder, guard):
    """The latest playtest's findings in translated text, while the game is
    as it played it."""
    found = latest(folder)
    if not found or found[0]["binding"] != binding(guard):
        return []
    return list(found[1].get("observations") or [])


def reviewing(folder, focus):
    """The focus's QA task, and every name of the lines it already takes
    from observations, or None."""
    from util import rpgmaker_qa as qa

    pointer = Path(folder) / ("text-qa-" + focus + ".json")
    if not pointer.exists():
        return None
    task = str(read_json(pointer)["task"])
    try:
        complete = qa.status(task).get("stage") == "complete"
        return task, qa.observed_names(task), complete
    except ValueError, OSError, KeyError, TypeError:
        return None


def observe(folder, focus, report):
    """Records the report's findings in translated text in the focus's QA
    task while it still reviews, each once; a line the task does not hold
    stays in the report, and a task already complete takes them when QA runs
    again."""
    from util import rpgmaker_qa as qa

    found = reviewing(folder, focus)
    if not report.get("observations") or not found:
        return 0
    task, known, complete = found
    if complete:
        return 0
    count = 0
    for row in report["observations"]:
        if row["identity"] in known:
            continue
        try:
            qa.record_observation(
                task, "playtest", row["identity"], row["categories"], row["note"]
            )
        except ValueError:
            # The task's inventory does not hold this line.
            continue
        known.add(row["identity"])
        count += 1
    return count


# What the app shows of each problem; the report keeps everything.
PROBLEM_KEYS = (
    "kind",
    "check",
    "file",
    "note",
    "fix",
    "pointer",
    "line",
    "plugin",
    "text",
    "original",
    "count",
    "reach",
    "evidence",
    "window",
    "rows",
    "codes",
    "reaches",
    "new",
)
# Strings a grouped problem shows; its count covers them all.
SHOWN_TEXTS = 20


def _seen(value):
    return {key: value[key] for key in ("stop", "scene", "capture") if value.get(key)}


def _problem(row, review):
    problem = {key: row[key] for key in PROBLEM_KEYS if key in row}
    if row.get("fix") == "text-qa" and row.get("identity"):
        task = review or (None, set(), False)
        problem["review"] = (
            "waiting"
            if row["identity"] not in task[1]
            else "reviewed"
            if task[2]
            else "reviewing"
        )
    if row.get("seen"):
        problem["seen"] = _seen(row["seen"])
    if row.get("texts"):
        problem["texts"] = [
            {
                key: text[key]
                for key in ("pointer", "line", "text", "reach", "evidence")
                if key in text
            }
            | ({"seen": _seen(text["seen"])} if text.get("seen") else {})
            for text in row["texts"][:SHOWN_TEXTS]
        ]
    return problem


def playtest_state(folder, guard, focus="release"):
    """The latest report, as the Playtest task shows it, with where text QA
    stands on each problem it corrects."""
    try:
        found = latest(folder)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {
            "current": False,
            "problems": [],
            "gaps": [],
            "unreadable": f"DazedTL can't read the last playtest's report: {exc}",
        }
    if not found:
        return {"current": False, "problems": [], "gaps": []}
    saved, report = found
    coverage = report.get("coverage") or {}
    review = reviewing(folder, focus)
    return {
        "report": saved["report"],
        "current": saved["binding"] == binding(guard),
        "finished_at": saved["finished_at"],
        "seconds": report.get("seconds", 0),
        "played": bool(report.get("played")),
        "complete": bool(report.get("complete")),
        "problems": [_problem(row, review) for row in report["problems"]],
        **({"since": report["since"]} if report.get("since") else {}),
        "gaps": list(report.get("gaps") or []),
        "coverage": {
            "stops": [
                {
                    key: stop[key]
                    for key in ("id", "title", "status", "note")
                    if stop.get(key) is not None
                }
                for stop in coverage.get("stops", [])
            ],
            "reached": coverage.get("reached", 0),
            "messages": coverage.get("messages", 0),
            "choices": coverage.get("choices", 0),
            "battle_lines": coverage.get("battle_lines", 0),
            "scenes": len(set(coverage.get("scenes", []))),
        },
    }


def capture(folder, name):
    """One capture of the latest report, as a data URL."""
    import base64
    import re

    found = latest(folder)
    if (
        not found
        or not re.fullmatch(r"\d{3}-[a-z]+", str(name))
        or not any(row["name"] == name for row in found[1].get("captures", []))
    ):
        raise ValueError("That capture is not in the latest playtest.")
    saved = found[0]
    path = project_path(
        Path(folder) / STORAGE, f"{saved['report']}/captures/{name}.jpg"
    )
    return {
        "url": "data:image/jpeg;base64,"
        + base64.b64encode(path.read_bytes()).decode("ascii")
    }
