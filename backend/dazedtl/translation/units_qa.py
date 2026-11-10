"""Text QA's reviewed task for an Assistant-led game on an engine Text QA
can't read, made from the game's units and exported translations.

Text QA reads RPG Maker MV/MZ and VX Ace data itself (text_qa); on any other
engine, Len's per-game extractor and injector own the game's files, and the
units the assistant last organized, with the English the run's export gives
the game, are the task's text (engine util/qa/units). The task is Text QA's
own, its review the same; only where its text comes from and where its
corrections go differ:

- An operation worker prepares it, since a big game's task takes seconds.
- The project's records keep it beside its other app records, with a pointer
  of the same form an RPG Maker task's Guided workspace keeps, so its state
  is read by the same rule (compatibility/text `qa_state`).
- It is current while the units and their English are the ones it reviewed,
  with its own corrections in place.
- Apply saves its findings as correction receipts of the requests that
  answer their lines, through Assistant-led's writer (Translation
  `correct_lines`), and the assistant writes them into the game with its own
  injector; undo and apply again save receipts back the same way. A record
  beside the task keeps each, as History's publications do for RPG Maker.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dazedtl.freshness import signature
from dazedtl.storage import write_json

from . import exchange
from .files import project_path, read_json
from .project import WORK
from .results import EXPORT, exported_translations

# The record of the task's applies and undos, beside its pointer.
APPLIED = "text-qa-units-applied.json"
# Each project's units and English as the task reads them, while the files
# they come from are unchanged: a state poll reads them every few seconds.
_LINES: dict[str, tuple[Any, list[dict[str, Any]]]] = {}


def reads(root) -> bool:
    """Whether Text QA reads the game at *root* by its units: any game but
    RPG Maker MV/MZ and VX Ace, whose data it reads itself."""
    from util.project_preparation import rpgmaker_layout

    return rpgmaker_layout(root) is None


def applies(method, workspace_id, root) -> bool:
    """Whether a project's Text QA task is one of its units: an
    Assistant-led (*method* len) game Text QA doesn't read itself, which no
    Guided workspace (*workspace_id*) holds the QA of."""
    return method == "len" and not workspace_id and reads(root)


def folder(workspace, project_id) -> Path:
    """The project's records, which hold its units tasks and their pointers
    as a Guided workspace holds an RPG Maker game's."""
    return Path(workspace) / "translation/projects" / project_id


def plan(workspace, project_id, root, focus) -> dict[str, Any]:
    """The record of a units task the shared QA readers take: where its tasks
    are, its game and focus, and as its data folder the work folder its units
    come from, which the task reads nothing in."""
    root = Path(root).resolve()
    return {
        "folder": str(folder(workspace, project_id)),
        "project_id": project_id,
        "project": {
            "source": str(root),
            "data": str(project_path(root, WORK + "/work", exists=False).resolve()),
        },
        "options": {"focus": focus},
    }


def _export_signature(root) -> tuple:
    """The stat signatures of the run's export, whose parts hold the English."""
    index = project_path(root, EXPORT, exists=False)
    try:
        saved = read_json(index)
        parts = saved.get("parts") if isinstance(saved, dict) else None
        stamps = [signature(index.stat())]
        for part in parts or []:
            stamps.append(signature(project_path(root, part).stat()))
        return tuple(stamps)
    except OSError, ValueError:
        return ()


def lines(store, project_id, root, jobs: Iterable[dict] | None = None) -> list[dict]:
    """The units the assistant last organized, in play order, each with the
    English the game gets as the run's export holds it (results
    `exported_translations`), or None where the export holds none for its
    source: a line DazedTL writes itself, which no request sends
    (organize.unsent), has no request to correct. *jobs*, the project's runs
    newest first, spares listing them again. Read again only once the units
    file or the export changed."""
    found = exchange.assistant_run(store, project_id, jobs)
    if found is None:
        return []
    job, relative = found
    try:
        units_path = project_path(root, relative)
        key = (job["id"], job["plan_sha256"], relative, signature(units_path.stat()))
    except OSError, ValueError:
        return []
    key += _export_signature(root)
    saved = _LINES.get(project_id)
    if saved and saved[0] == key:
        return saved[1]
    units = exchange.units_file(root, relative)
    english = {
        row["source_id"]: row
        for row in exported_translations(root)
        if not row.get("converted")
    }
    value = [
        {
            "id": unit["id"],
            "scene": unit["scene"],
            "group": unit["group"],
            "kind": unit["kind"],
            "speaker": unit["speaker"],
            "field": unit["field"],
            "source": unit["source"],
            "translation": row["translation"]
            if (row := english.get(unit["id"])) and row["source"] == unit["source"]
            else None,
        }
        for unit in units
    ]
    _LINES[project_id] = (key, value)
    return value


def inventory(store, project_id, root, focus, jobs=None) -> dict[str, Any]:
    """Text QA's inventory of *focus* over the game's units now."""
    from util.qa import units

    return units.inventory(lines(store, project_id, root, jobs), focus)


def text(store, project_id, root, focus, jobs=None) -> str:
    """The text digest of the units and English the game holds now, which a
    task is current with while it is the one it reviewed (qa.text_digest),
    whatever QA rules version made the task, since every one reads units
    alike."""
    from util import rpgmaker_qa as qa

    return qa.text_digest(inventory(store, project_id, root, focus, jobs))


def prepare(workspace, project_id, root, focus, everything, progress) -> dict[str, Any]:
    """Prepares or resumes the task of *focus* over the game's units, in an
    operation worker, and saves the pointer its state is read by; returns the
    task's folder."""
    from util import rpgmaker_qa as qa

    from dazedtl.compatibility.text import qa_prepared

    from .jobs import RunStore

    store = RunStore(workspace)
    manifest = inventory(store, project_id, root, focus)
    if not manifest["records"]:
        raise ValueError(
            "No translated line to review yet: organize the units, translate "
            "them and get the run's results, then run qa --prepare."
        )
    record = plan(workspace, project_id, root, focus)
    data = Path(record["project"]["data"])
    data.mkdir(parents=True, exist_ok=True)
    progress(f"Text QA reads {len(manifest['records']):,} translated lines")
    task, _state = qa.prepare_task(
        root,
        data,
        focus,
        Path(record["folder"]) / "text-qa",
        earlier=not everything,
        storage_key=project_id,
        inventory=manifest,
    )
    qa_prepared(record, task, qa.text_digest(manifest))
    return {"task": str(task)}


def state(store, workspace, project_id, root, focus, jobs=None) -> dict[str, Any]:
    """The task of *focus* as the Text QA page and the helper read it; one
    the app can't read or trust reads blocked, with why. *focus* None, the
    review off, and a project with no task read as none prepared."""
    from dazedtl.compatibility.text import qa_state, qa_unreadable

    record = plan(workspace, project_id, root, focus or "release")
    none = {
        "current": False,
        "applied": False,
        "status": {},
        "findings": [],
        "questions": [],
        "message": "No QA task prepared for this focus."
        if focus
        else "Text QA's review is off in Options; only its checks run.",
    }
    if not focus or not (Path(record["folder"]) / f"text-qa-{focus}.json").is_file():
        return none
    try:
        return qa_state(
            record,
            text=lambda _rules: text(store, project_id, root, focus, jobs),
            history=history(workspace, project_id),
        )
    except (ValueError, OSError, KeyError, TypeError) as error:
        return qa_unreadable(record, error)


def correct(translation, project_id, root, focus, action, options) -> None:
    """Saves the corrections an apply, undo or apply again names, as
    correction receipts of the requests that answer their lines, and records
    the batch. As an RPG Maker task's apply checks its game, this checks each
    line against the English QA reviewed or corrected it to, and an apply
    needs the task current, except an apply again of undone corrections."""
    from util import rpgmaker_qa as qa

    from dazedtl.compatibility.text import _bind, _in_game, qa_selection

    store, workspace = translation.jobs.store, translation.workspace
    record = plan(workspace, project_id, root, focus)
    current = state(store, workspace, project_id, root, focus)
    if current.get("unreadable") or not current.get("task"):
        raise ValueError(current["message"])
    if options.get("task") != current["task"]:
        raise ValueError(
            "The QA task changed. Choose corrections from the current findings."
        )
    chosen, proposals = qa_selection(current, action, options)
    undone = {
        row["id"]
        for row in current["findings"] + current["questions"]
        if row.get("state") == "undone"
    }
    again = action == "qa_apply" and set(chosen + proposals) <= undone
    if action == "qa_apply" and not again and not current["current"]:
        raise ValueError(current["message"])
    selected = qa.correction_map(
        current["task"], chosen, proposals, undo=action == "qa_undo"
    )
    changes = {
        row["identity"]: (row["expected"], row["replacement"])
        for row in selected["operations"]
    }
    try:
        translation.correct_lines(
            project_id, changes, {"text_qa": Path(current["task"]).name}
        )
    except LookupError as error:
        raise ValueError(
            "A line changed since QA corrected it, so the correction can't be "
            "undone here; correct it with a receipt of your own."
            if action == "qa_undo"
            else "A line changed since QA reviewed it, so the correction can't be "
            "applied. Run qa --prepare to review it again."
        ) from error
    named = set(chosen + proposals)
    record_batch(workspace, project_id, action, current["task"], sorted(named))
    # The receipts changed the export; its stamps may not have yet.
    _LINES.pop(project_id, None)
    if current["current"]:
        # The units' English with this batch in it is the task's own, so its
        # apply or undo leaves the task current.
        in_game = set(_in_game(current["findings"], current["questions"]))
        after = in_game | named if action == "qa_apply" else in_game - named
        _bind(
            record,
            current["task"],
            {tuple(sorted(after)): text(store, project_id, root, focus)},
        )


def history(workspace, project_id) -> list[dict[str, Any]]:
    """The task's applies and undos, oldest first, in the form the shared
    state reads publications in."""
    path = folder(workspace, project_id) / APPLIED
    try:
        rows = read_json(path)["rows"]
    except OSError, ValueError, KeyError, TypeError:
        return []
    return rows if isinstance(rows, list) else []


def record_batch(workspace, project_id, kind, task, findings) -> None:
    """Records one apply or undo of a task's corrections, which the state
    reads each correction's own state from."""
    rows = history(workspace, project_id)
    rows.append(
        {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "state": "complete",
            "task": str(task),
            "findings": list(findings),
            "created": time.time(),
        }
    )
    path = folder(workspace, project_id) / APPLIED
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"version": 1, "rows": rows})
