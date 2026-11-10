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

from dazedtl.freshness import signature, signature_settled
from dazedtl.storage import write_json

from . import exchange
from .files import project_path, read_json
from .project import WORK
from .results import EXPORT, exported_translations

# The record of the task's applies and undos, beside its pointer.
APPLIED = "text-qa-units-applied.json"
# Each project's units and English as the task reads them, and the text
# digest of each focus's inventory of them, while the files they come from
# are unchanged: a state poll reads them every few seconds.
_LINES: dict[str, tuple[Any, list[dict[str, Any]]]] = {}
_TEXTS: dict[tuple[str, str], tuple[Any, str]] = {}


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


def _export_stamps(root) -> tuple:
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


def _key(store, project_id, root, jobs) -> tuple | None:
    """What the game's lines are read from now: the newest organized run,
    its units file and the export's files, by their stat signatures; None
    before a run organize compiled."""
    found = exchange.assistant_run(store, project_id, jobs)
    if found is None:
        return None
    job, organized = found
    try:
        stamp = signature(project_path(root, organized["units"]).stat())
    except OSError, ValueError:
        return None
    return (
        job["id"],
        job["plan_sha256"],
        organized["units"],
        stamp,
        *_export_stamps(root),
    )


def _kept(key) -> bool:
    """Whether a value read from the files *key* names may be kept: each
    file is older than one clock tick, so a change since gives it a new
    signature (freshness.signature_settled)."""
    return all(signature_settled(stamp) for stamp in key[3:])


def lines(store, project_id, root, jobs: Iterable[dict] | None = None) -> list[dict]:
    """The units the assistant last organized, in play order, each with the
    English the game gets as the run's export holds it (results
    `exported_translations`), or None where the export holds none for its
    source: a line DazedTL writes itself, which no request sends
    (organize.unsent), has no request to correct. *jobs*, the project's runs
    newest first, spares listing them again. Read again only once the units
    file or the export changed."""
    key = _key(store, project_id, root, jobs)
    if key is None:
        return []
    saved = _LINES.get(project_id)
    if saved and saved[0] == key:
        return saved[1]
    relative = key[2]
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
            "constraints": unit["constraints"],
            "translation": row["translation"]
            if (row := english.get(unit["id"])) and row["source"] == unit["source"]
            else None,
        }
        for unit in units
    ]
    if _kept(key):
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
    alike. Made again only once the files it is read from changed, since an
    inventory of a big game takes most of a second."""
    from util import rpgmaker_qa as qa

    key = _key(store, project_id, root, jobs)
    saved = _TEXTS.get((project_id, focus))
    if key is not None and saved and saved[0] == key:
        return saved[1]
    value = qa.text_digest(inventory(store, project_id, root, focus, jobs))
    if key is not None and _kept(key):
        _TEXTS[(project_id, focus)] = (key, value)
    return value


def _forget(project_id) -> None:
    """Reads the project's lines again next time, as after its receipts
    changed within one clock tick of an earlier read."""
    _LINES.pop(project_id, None)
    for key in [key for key in _TEXTS if key[0] == project_id]:
        _TEXTS.pop(key, None)


def prepare(workspace, project_id, root, focus, everything, progress) -> dict[str, Any]:
    """Prepares or resumes the task of *focus* over the game's units, in an
    operation worker, and saves the pointer its state is read by; returns the
    task's folder. A task whose corrections are applied, and whose text the
    game still holds with them, is the one QA goes on with, unless
    *everything* reviews every line again: no playtest brings it lines to
    look at again, and a new round would hide its corrections' undo."""
    from util import rpgmaker_qa as qa

    from dazedtl.compatibility.text import qa_prepared

    from .jobs import RunStore

    store = RunStore(workspace)
    if not everything:
        held = state(store, workspace, project_id, root, focus)
        if held.get("task") and held["applied"] and held["current"]:
            progress("Text QA's corrections are applied and current")
            return {"task": held["task"]}
    manifest = inventory(store, project_id, root, focus)
    if not manifest["records"]:
        if any(
            line["translation"] is not None for line in lines(store, project_id, root)
        ):
            raise ValueError(
                "Text QA's choice in this project's Options reads none of this "
                "game's lines; the user chooses another there."
            )
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
        return qa_state(record, Lines(store, workspace, project_id, root, focus, jobs))
    except (ValueError, OSError, KeyError, TypeError) as error:
        return qa_unreadable(record, error)


class Lines:
    """What the shared QA state (compatibility/text `qa_state`) reads of a
    task of the game's units, in place of the game's data and publications:
    the text the game holds now, the task's applies and undos, and its
    findings' corrections as the game gets them."""

    def __init__(self, store, workspace, project_id, root, focus, jobs=None):
        self.store, self.workspace, self.project_id = store, workspace, project_id
        self.root, self.focus, self.jobs = root, focus, jobs

    def text(self, _rules) -> str:
        """The text_digest of the game's units now, which every QA rules
        version reads alike."""
        return text(self.store, self.project_id, self.root, self.focus, self.jobs)

    def history(self) -> list[dict[str, Any]]:
        return history(self.workspace, self.project_id)

    def written(self, document: dict[str, Any]) -> dict[str, Any]:
        """A findings document with each correction and proposal as the run's
        export writes it for its line (results.exported_line), as its apply
        saves it, so the page shows what the game gets: a reviewer's curly
        apostrophe reads as the export writes it."""
        from .results import exported_line

        found = exchange.assistant_run(self.store, self.project_id, self.jobs)
        if found is None:
            return document
        organized = found[1]
        by_id = {
            line["id"]: line
            for line in lines(self.store, self.project_id, self.root, self.jobs)
        }

        def game(identities, value):
            line = next((by_id[item] for item in identities if item in by_id), None)
            if line is None or not isinstance(value, str):
                return value
            request = {
                "sources": {line["id"]: line["source"]},
                "constraints": {line["id"]: line["constraints"]},
                "context": {"target_language": organized["target"]},
            }
            return exported_line(request, line["id"], value, organized["quotes"])

        document = {**document}
        findings = []
        for row in document.get("findings", []):
            row = {**row}
            if row.get("kind") == "scene":
                row["lines"] = [
                    {**line, "correction": game(line["identities"], line["correction"])}
                    for line in row["lines"]
                ]
            elif row.get("kind") != "show-text":
                row["correction"] = game(row["target_identities"], row["correction"])
            findings.append(row)
        document["findings"] = findings
        document["uncertain_playtests"] = [
            {**row, "correction": game([row["id"]], row.get("correction"))}
            if row.get("correction")
            else row
            for row in document.get("uncertain_playtests", [])
        ]
        return document


def correct(translation, project_id, root, focus, action, options) -> None:
    """Saves the corrections an apply, undo or apply again names, as
    correction receipts of the requests that answer their lines, and records
    the batch. As an RPG Maker task's apply checks its game, this checks each
    line against the English QA reviewed or corrected it to, and an apply
    needs the task current, except an apply again of undone corrections.
    A correction with a line the receipt check refuses is left out and the
    rest saved (Translation `correct_lines`); the record keeps each one left
    out with why, which the task's state reports."""
    from util import rpgmaker_qa as qa
    from util.qa.schema import NEWLINE_MARK

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
    # The English the game holds, for an undo of a correction an apply wrote
    # before QA read a reviewer's ⏎ as a line break: it holds the mark.
    held = (
        {line["id"]: line["translation"] for line in lines(store, project_id, root)}
        if any(row.get("also_expected") for row in selected["operations"])
        else {}
    )
    # A finding's lines, such as a scene correction's, go in together.
    changes: dict[str, dict[str, tuple[str, str]]] = {}
    for row in selected["operations"]:
        expected = row["expected"]
        game = held.get(row["identity"])
        for other in row.get("also_expected") or ():
            if isinstance(game, str) and (NEWLINE_MARK in game) == (
                NEWLINE_MARK in other
            ) != (NEWLINE_MARK in expected):
                expected = other
        changes.setdefault(row["finding_id"], {})[row["identity"]] = (
            expected,
            row["replacement"],
        )
    try:
        left_out = translation.correct_lines(
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
    named = set(chosen + proposals) - set(left_out)
    record_batch(
        workspace, project_id, action, current["task"], sorted(named), left_out
    )
    # The receipts changed the export; its stamps may not have yet.
    _forget(project_id)
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


def record_batch(workspace, project_id, kind, task, findings, left_out) -> None:
    """Records one apply or undo of a task's corrections, which the state
    reads each correction's own state from, with why each one it left out
    was (*left_out*, by finding ID)."""
    rows = history(workspace, project_id)
    rows.append(
        {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "state": "complete",
            "task": str(task),
            "findings": list(findings),
            **(
                {
                    "left_out": [
                        {"id": key, "reason": left_out[key]} for key in sorted(left_out)
                    ]
                }
                if left_out
                else {}
            ),
            "created": time.time(),
        }
    )
    path = folder(workspace, project_id) / APPLIED
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"version": 1, "rows": rows})
