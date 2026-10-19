"""The release playtest in the game's Guided workspace: the action that
plays the game, the report it keeps, and the observations it hands to text
QA so a deep reviewer corrects what the playtest found in translated text."""

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path, read_json

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

    from dazedtl.plugins.service import kept_settings

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
        kept=kept_settings(plan["project"]["source"]),
    )
    write_json(
        folder / POINTER,
        {
            "report": name,
            "binding": binding(plan["guard"]),
            "finished_at": datetime.now(UTC).isoformat(),
        },
    )
    _prune(storage, name)
    observed = observe(folder, plan["options"]["focus"], report)
    if observed:
        log(f"Handed {observed} finding(s) to text QA's review")
    return {
        "problems": len(report["problems"]),
        "observed": observed,
        "seconds": report["seconds"],
    }


# A fix check keeps its report apart until its fixes go into the game; then
# it is the playtest's latest, since it played the game as it now is.
FIX_POINTER = "playtest-fix.json"
FIX_STORAGE = "playtest-fix"
# The assistant's working copy of the game's fixes plugin.
FIXES = ".dazedtl/playtest/DazedTL_Fixes.js"


def fixes_copy(root, web):
    """The working copy of the fixes plugin, made from the game's own, or an
    empty plugin before the game has one."""
    from util.playtest import fixes

    path = project_path(root, FIXES, exists=False)
    if not path.exists():
        current = web / fixes.PLUGIN
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            current.read_bytes()
            if current.is_file()
            else fixes.TEMPLATE.encode("utf-8")
        )
    return path


def fixes_saved(source):
    """Whether the translation branch's latest commit holds the game's fixes
    as they are, or None for a game without fixes."""
    from util.playtest.fixes import patch_files
    from util.version_update.git_workflow import _run_git

    root = Path(source)
    names = patch_files(root)
    if not names:
        return None
    for name in names:
        committed = _run_git(
            root, "rev-parse", "--verify", "--quiet", f"HEAD:{name}", check=False
        )
        if (
            committed.returncode
            or committed.stdout.strip()
            != _run_git(root, "hash-object", "--no-filters", "--", name).stdout.strip()
        ):
            return False
    return True


def run_fixes(plan, log):
    """Plays the game with the assistant's fixes in place of the game's files;
    once nothing new breaks and something the last playtest found is gone,
    writes them as one batch History can restore, and the play becomes the
    playtest's latest report."""
    from desktop.backend.workflow_actions import action_guard, validate_plan
    from util import rpgmaker_window
    from util.playtest import fixes
    from util.playtest.run import run

    from dazedtl.plugins.service import kept_settings
    from dazedtl.translation import publication

    validate_plan(plan)
    folder = Path(plan["folder"])
    root = Path(plan["project"]["source"])
    data = Path(plan["project"]["data"])
    found = latest(folder)
    if not found or found[0]["binding"] != binding(plan["guard"]):
        raise ValueError(
            "Run the playtest first: fixes are checked against a playtest of the "
            "game as it is now."
        )
    raw = project_path(root, FIXES).read_bytes()
    if digest(raw) != plan["options"]["fixes"]:
        raise ValueError("The fixes changed after the check started. Check them again.")
    fixes.check(raw)
    web = rpgmaker_window.web_root(data)
    prefix = web.relative_to(root.resolve()).as_posix()
    names = {
        key: (key if prefix == "." else f"{prefix}/{key}")
        for key in (fixes.PLUGIN, fixes.MAIN)
    }
    plugin = web / fixes.PLUGIN
    if plugin.is_file() and plugin.read_bytes() == raw:
        raise ValueError("The game already has these fixes.")
    storage = folder / FIX_STORAGE
    storage.mkdir(exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    out = storage / name
    served = fixes.served(web, raw, out)
    log("Playing the game with the fixes in place")
    report = run(
        root,
        data,
        out,
        stops=plan["options"]["stops"],
        log=log,
        stopped=getattr(log, "stopped", lambda: False),
        previous=found[1],
        kept=kept_settings(root),
        overlay=served,
    )
    reason = fixes.refusal(found[1], report)
    record = {
        "report": name,
        "finished_at": datetime.now(UTC).isoformat(),
        "fixes": digest(raw),
        "since": report.get("since") or {},
        "reason": reason,
    }
    if not reason:
        try:
            validate_plan(plan)
        except ValueError:
            record["reason"] = reason = (
                "The game changed while the fixes were played. Check them again."
            )
    if not reason:
        candidates = {names[fixes.PLUGIN]: raw}
        main = served[fixes.MAIN].read_bytes()
        if main != (web / fixes.MAIN).read_bytes():
            candidates[names[fixes.MAIN]] = main
        frozen = publication.freeze(
            folder, root, candidates, "playtest_fix", created={names[fixes.PLUGIN]}
        )
        log("Writing the fixes into the game; History can restore them")
        record["publication"] = publication.publish(folder, root, frozen, log)[
            "publication"
        ]
        # The play matched the game as it now is, so it is the latest report.
        shutil.rmtree(out / "served", ignore_errors=True)
        out.rename(folder / STORAGE / name)
        write_json(
            folder / POINTER,
            {
                "report": name,
                "binding": binding(action_guard(plan["project"], folder)),
                "finished_at": record["finished_at"],
            },
        )
        _prune(folder / STORAGE, name)
        observe(folder, plan["options"]["focus"], report)
    write_json(folder / FIX_POINTER, record)
    _prune(storage, name)
    if reason:
        raise ValueError(reason)
    return {
        "publication": record["publication"],
        "fixed": record["since"].get("fixed", 0),
        "new": record["since"].get("new", 0),
        "problems": len(report["problems"]),
    }


def _prune(storage, keep):
    """Removes all but the newest reports, never `keep`."""
    for old in sorted(path for path in storage.iterdir() if path.is_dir())[:-KEEP]:
        if old.name != keep:
            shutil.rmtree(old, ignore_errors=True)


def fixes_state(folder, root, web):
    """The working copy of the fixes plugin, whether the game has it as it
    is, and the latest check of it."""
    from util.playtest.fixes import PLUGIN

    copy = fixes_copy(root, web)
    game = web / PLUGIN
    result = {
        "file": str(copy),
        "in_game": game.is_file() and game.read_bytes() == copy.read_bytes(),
    }
    pointer = Path(folder) / FIX_POINTER
    try:
        check = read_json(pointer) if pointer.exists() else None
    except OSError, ValueError:
        check = None
    if check:
        result["check"] = {
            key: check[key]
            for key in ("finished_at", "reason", "publication")
            if check.get(key)
        } | {
            "fixed": check["since"].get("fixed", 0),
            "new": check["since"].get("new", 0),
        }
    return result


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
    _prune(storage, name)
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


# A label check keeps its own reports too: the labels Plugin files shortens,
# on their screens captured with its working copies served in place of the
# game's files.
LABELS_POINTER = "label-check.json"
LABELS_STORAGE = "label-check"


def run_labels(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util import rpgmaker_screens

    validate_plan(plan)
    folder = Path(plan["folder"])
    options = plan["options"]
    storage = folder / LABELS_STORAGE
    storage.mkdir(exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    out = storage / name
    source = Path(plan["project"]["source"])
    # The working copies are served as they were when the check started, so
    # its report shows the bytes it names.
    overlay = {}
    for row in options["files"]:
        raw = project_path(source, row["candidate"]).read_bytes()
        if digest(raw) != row["hash"]:
            raise ValueError(
                "A working copy changed after the label check started. Capture again."
            )
        served = out / "served" / row["serve"]
        served.parent.mkdir(parents=True, exist_ok=True)
        served.write_bytes(raw)
        overlay[row["serve"]] = served
    screens = sorted(
        {rpgmaker_screens.screen_of(label["capture"]) for label in options["labels"]}
    )
    try:
        listing = rpgmaker_screens.capture(
            plan["project"]["data"], out, overlay=overlay, screens=screens, progress=log
        )
        result = {
            "labels": rpgmaker_screens.label_fits(options["labels"], listing, out)
        }
    except rpgmaker_screens.WindowUnavailable as error:
        result = {"labels": [], "unavailable": str(error)}
    write_json(out / "labels.json", result)
    write_json(
        folder / LABELS_POINTER,
        {
            "report": name,
            "finished_at": datetime.now(UTC).isoformat(),
            "request": options["request"],
            "files": {row["path"]: row["hash"] for row in options["files"]},
        },
    )
    _prune(storage, name)
    return {
        "labels": len(result["labels"]),
        "fit": sum(row["fits"] for row in result["labels"]),
    }


def latest_labels(folder) -> dict | None:
    """The latest label check, with its folder, or None."""
    pointer = Path(folder) / LABELS_POINTER
    if not pointer.exists():
        return None
    saved = read_json(pointer)
    path = project_path(Path(folder) / LABELS_STORAGE, saved["report"] + "/labels.json")
    return {**read_json(path), **saved, "folder": str(path.parent)}


def latest(folder) -> tuple[dict, dict] | None:
    """The pointer to the latest report and the report, or None."""
    pointer = Path(folder) / POINTER
    if not pointer.exists():
        return None
    saved = read_json(pointer)
    path = project_path(Path(folder) / STORAGE, saved["report"] + "/report.json")
    return saved, read_json(path)


def seen_plugin_text(folder):
    """Japanese the latest playtest saw a plugin draw, each with where, for
    Plugin files to decide again: players see it."""
    try:
        found = latest(folder)
    except ValueError, OSError, KeyError, TypeError:
        return {"report": "", "texts": []}
    if not found:
        return {"report": "", "texts": []}
    saved, report = found
    captures = Path(folder) / STORAGE / saved["report"] / "captures"
    texts = {}

    def add(text, seen):
        text = str(text or "").strip()
        if text and text not in texts:
            texts[text] = {
                "text": text,
                "where": "Seen on "
                + (seen.get("scene") or seen.get("stop") or "screen")
                # A screen the tour opened itself, as players may never.
                + (
                    ", which the playtest opened on its own"
                    if str(seen.get("stop", "")).startswith("screen ")
                    else ""
                ),
                **(
                    {"capture": str(captures / (seen["capture"] + ".jpg"))}
                    if seen.get("capture")
                    else {}
                ),
            }

    for problem in report.get("problems", []):
        if problem.get("fix") != "plugin-files" or problem["kind"] != "japanese":
            continue
        for row in problem.get("texts") or []:
            if row.get("seen"):
                add(row["text"], row["seen"])
        if problem.get("seen") and problem.get("text"):
            add(problem["text"], problem["seen"])
    return {"report": saved["report"], "texts": list(texts.values())}


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


def task_observations(folder, focus, found):
    """The playtest findings QA prepares its task with: the ones a task still
    under review was prepared with, so preparing again, as after a plugin or
    playtest fix, resumes it rather than starting a new review; else `found`,
    the current report's."""
    under_review = reviewing(folder, focus)
    if under_review and not under_review[2]:
        pointer = Path(folder) / ("text-qa-" + focus + ".json")
        return list(read_json(pointer).get("observations") or [])
    return found


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
