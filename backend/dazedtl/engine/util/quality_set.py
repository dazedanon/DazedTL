"""A frozen translation-quality regression set, built from what Text QA
corrected (util/qa_corrections' export).

An item is one line to translate again, inside the chunk of its scene a
request sends, with everything that request needs so a run never reads a
game: the chunk's source lines in order, the preceding source lines, each
line's speaker and line kind, and its game's guidance (the overlays its
system prompt adds and its glossary, kept once per QA task in the header's
``contexts``). A defect item is a line QA corrected: it keeps the first draft,
the correction and the reviewer's reason, and, for a glossary fix, the
glossary rows the correction follows. A control item is a line QA's screen
read without a finding, with the accepted translation.

The set is JSON Lines: a header (``schema`` SCHEMA, ``format`` FORMAT, the
set's own ``version``, ``kind`` "set" or "targeted"), then one item per line
(ITEM_FIELDS). A regression set's items are split once into a tune half and a
held-out half, each recurring group whole on one side. A targeted item file,
which a change brings for the cases where it fires, has the same form with
``kind`` "targeted", its own ``version`` and no split; it never joins the
held-out half. docs/development.md#quality-measurement says how to make one.

Read-only: building reads the export, the QA tasks it names and, for games
whose tasks are gone, their Git history; it writes only the set its caller
names, outside the source tree, the games and their tasks, since it holds
game text.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from util import qa_corrections, system
from util.languages import source_pattern
from util.paths import (
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
    LEGACY_GAME_GLOSSARY_RELATIVE,
    LEGACY_GAME_SKILL_RELATIVE,
    LEGACY_QUIRKS_FILENAME,
)
from util.qa.selection import _scene_records
from util.skills.system import prompt_overlays

SCHEMA = "dazedtl-quality-set"
# The item form: raise it when a field or its meaning changes.
FORMAT = 1
# The regression set built from the QA export: raise it when the selection,
# the chunking or the split changes, so runs on an older set are known as such.
VERSION = 1
KINDS = ("set", "targeted")
SPLITS = ("tune", "held-out")
METHODS = ("guided", "assistant-led")
LINE_KINDS = ("dialogue", "narration", "ui", "unknown")
# Lines per chunk and preceding lines, as Guided sends a scene: chunks from
# the scene's start and the previous chunk's last ten lines as context
# (TranslationConfig.maxHistory).
CHUNK_LINES = 10
HISTORY_LINES = 10
# The corrections a request can repeat. Fit and format fixes are left out:
# automatic fitting and the layout lint make them after translation, so a
# request's reply does not show them.
DEFECT_KINDS = ("glossary/name", "meaning", "fluency", "legacy output", "other")
DEFECTS = 300
CONTROLS = 300
# Controls come from tasks whose screen read at least this share of its
# items: a task counts its coverage per item, not per line, so a line of one
# that read 99% was left unread at most about one time in a hundred.
SCREENED = 0.99
# Items one recurring group may give, so a fix repeated across a game counts
# a few times, not dozens.
GROUP_ITEMS = 3
SEED = "dazedtl-quality-set-1"
ITEM_FIELDS = (
    "id", "type", "split", "game", "context", "kind", "category", "group",
    "file", "scene", "lines", "history", "target", "draft", "accepted",
    "reason", "glossary",
)
LINE_FIELDS = ("source", "speaker", "speaker_name", "kind")
_JAPANESE = re.compile(source_pattern())


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _order(seed: str, key: str) -> str:
    return _digest(seed, key)


# Reading what QA saw


@dataclass
class Material:
    """One QA run's lines as it read them and its game's guidance then."""

    key: str
    game: str
    origin: str
    task: str
    records: dict[str, dict[str, Any]]
    scenes: dict[str, list[dict[str, Any]]]
    context: dict[str, Any]
    screened: bool = False
    unread: set[str] = field(default_factory=set)
    _positions: dict[str, tuple[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for scene, ordered in self.scenes.items():
            for index, record in enumerate(ordered):
                self._positions[record["identity"]] = (scene, index)

    def position(self, identity: str) -> tuple[str, int] | None:
        return self._positions.get(identity)


def _context(game: str, origin: str, task: str, skill: str, quirks: str,
             custom: Iterable[tuple[str, str]], glossary: str, read: str) -> dict[str, Any]:
    return {
        "game": game,
        "origin": origin,
        "task": task,
        "overlays": prompt_overlays(skill, quirks, custom),
        "glossary": glossary,
        "read": read,
    }


def _text(value: Any) -> str:
    return value.get("text") or "" if isinstance(value, dict) else ""


def _task_material(game: str, source: dict[str, Any]) -> Material:
    """A task's inventory, as its screen and deep review read it, and the
    guidance its context recorded."""
    folder = Path(source["path"])
    inventory = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
    findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
    recorded = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    screen = ((findings.get("coverage") or {}).get("screen")) or {}
    custom = [
        (Path(str(overlay.get("path") or "skill")).stem, _text(overlay))
        for overlay in recorded.get("overlays") or []
        if isinstance(overlay, dict)
    ]
    return Material(
        key=f"{game}#{source['task']}",
        game=game,
        origin="task",
        task=source["task"],
        records={record["identity"]: record for record in inventory["records"]},
        scenes=_scene_records(inventory),
        context=_context(
            game, "task", source["task"], _text(recorded.get("game")),
            _text(recorded.get("quirks")), custom, _text(recorded.get("glossary")),
            "task context",
        ),
        screened=bool(screen.get("total")) and screen.get("accepted", 0) >= SCREENED * screen["total"],
        unread={row.get("identity") for row in findings.get("not_reviewed") or []},
    )


def _receipts_material(
    game: str, root: Path, source: dict[str, Any], files: set[str], staging: Path
) -> Material:
    """The data files and guidance a receipts game held before the commit
    that applied its QA, read from Git."""
    history = qa_corrections._History(root, staging)
    parent = source["commit"] + "^"
    history.read(parent, files)
    records: dict[str, dict[str, Any]] = {}
    for name in sorted(files):
        records.update(history.records(parent, name))
    relative = root.resolve().relative_to(history.repo)

    def show(path: str) -> str | None:
        done = system.run(
            ["git", "-C", str(history.repo), "show", f"{parent}:{path}"],
            capture_output=True,
        )
        return done.stdout.decode("utf-8") if done.returncode == 0 else None

    def shown(*candidates: Path) -> str:
        for candidate in candidates:
            text = show((relative / candidate).as_posix())
            if text is not None:
                return text
        return ""

    listing = history.git(
        "ls-tree", "--name-only", "-z", parent, "--", (relative / GAME_SKILLS_RELATIVE).as_posix() + "/"
    ).decode("utf-8").split("\0")
    reserved = {name.lower() for name in GAME_SKILL_RESERVED_NAMES}
    custom = [
        (Path(path).stem, show(path) or "")
        for path in sorted(listing, key=str.lower)
        if path.lower().endswith(".md") and Path(path).name.lower() not in reserved
    ]
    return Material(
        key=f"{game}#{source['task']}",
        game=game,
        origin="receipts",
        task=source["task"],
        records=records,
        scenes=_scene_records({"records": list(records.values())}),
        context=_context(
            game, "receipts", source["task"],
            shown(GAME_SKILL_RELATIVE, LEGACY_GAME_SKILL_RELATIVE),
            shown(GAME_QUIRKS_RELATIVE, Path(LEGACY_QUIRKS_FILENAME)),
            custom,
            shown(GAME_GLOSSARY_RELATIVE, LEGACY_GAME_GLOSSARY_RELATIVE),
            "git " + parent,
        ),
    )


def read_export(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The QA export's header and rows, refusing another form or VERSION."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    if header.get("schema") != qa_corrections.EXPORT_SCHEMA or header.get("version") != qa_corrections.VERSION:
        raise ValueError(
            f"{path} is not a version {qa_corrections.VERSION} {qa_corrections.EXPORT_SCHEMA} export"
        )
    return header, [json.loads(line) for line in lines[1:] if line.strip()]


# Items


def _speakers(ordered: list[dict[str, Any]]) -> dict[str, tuple[str | None, str | None]]:
    """Each message's speaker as (source name, shown name): the name box
    heading it, when the record names that box as its speaker."""
    found: dict[str, tuple[str | None, str | None]] = {}
    box: dict[str, Any] | None = None
    for record in ordered:
        if record.get("display_shape") == "name-box":
            box = record
            continue
        speaker = record.get("speaker") or {}
        name = speaker.get("display_name") or None
        source = None
        if (
            name
            and box is not None
            and speaker.get("provenance") in {"code-101", "adjacent-code-101"}
            and box.get("live") == name
        ):
            source = box.get("source") or None
        found[record["identity"]] = (source, name)
        if record.get("display_shape") == "message":
            box = None
    return found


def _line(record: dict[str, Any], speakers: dict[str, tuple[str | None, str | None]]) -> dict[str, Any]:
    source, name = speakers.get(record["identity"], (None, None))
    return {
        "source": record["source"],
        "speaker": source or name,
        "speaker_name": name,
        # A line without a named speaker may still be speech, so its kind
        # stays unknown instead of guessed.
        "kind": "dialogue" if name else "unknown",
    }


def _messages(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in ordered if record.get("display_shape") == "message"]


def _chunk(material: Material, identity: str) -> dict[str, Any] | None:
    """The chunk holding *identity*, its preceding lines and its place."""
    place = material.position(identity)
    if place is None:
        return None
    scene, _index = place
    ordered = material.scenes[scene]
    messages = _messages(ordered)
    positions = [record["identity"] for record in messages]
    if identity not in positions:
        return None
    at = positions.index(identity)
    start = at // CHUNK_LINES * CHUNK_LINES
    speakers = _speakers(ordered)
    chunk = messages[start:start + CHUNK_LINES]
    return {
        "file": material.records[identity]["file"],
        "scene": scene,
        "lines": [_line(record, speakers) for record in chunk],
        "history": [_line(record, speakers) for record in messages[max(0, start - HISTORY_LINES):start]],
        "target": at - start,
    }


def glossary_rows(glossary: str, source: str, before: str, after: str) -> list[dict[str, str]]:
    """The glossary rows a correction follows: their source term is in the
    line, and their English is in the correction but not in the draft."""
    from util.translation import parseVocabWithCategories, split_vocab_source_aliases

    rows: dict[tuple[str, str], dict[str, str]] = {}
    for term, _line, _category in parseVocabWithCategories(glossary):
        if not isinstance(term, tuple):
            continue
        japanese, english = term
        if not english or english in before or english not in after:
            continue
        if any(alias and alias in source for alias in [japanese, *split_vocab_source_aliases(japanese)]):
            rows[(japanese, english)] = {"source": japanese, "target": english}
    return list(rows.values())


def _item(material: Material, identity: str, kind: str, **values: Any) -> dict[str, Any] | None:
    record = material.records.get(identity)
    if record is None or not _JAPANESE.search(record.get("source") or ""):
        return None
    chunk = _chunk(material, identity)
    if chunk is None:
        return None
    item_type = values.pop("type")
    item = {
        "id": _digest(material.key, identity, item_type)[:16],
        "type": item_type,
        "game": material.game,
        "context": material.key,
        "kind": kind,
        **chunk,
        **values,
    }
    return item


def _defect(material: Material, row: dict[str, Any]) -> dict[str, Any] | None:
    before, after = row.get("before") or "", row.get("after") or ""
    if (
        row.get("kind") not in DEFECT_KINDS
        or row.get("applied") is False
        or row.get("requa")
        or not before.strip()
        or not after.strip()
        or before == after
    ):
        return None
    item = _item(
        material, row["identity"], row["kind"], type="defect",
        category=row.get("category") or "", group=row.get("recurring") or None,
        draft=before, accepted=after, reason=row.get("reason") or "",
    )
    if item is None:
        return None
    item["glossary"] = (
        glossary_rows(material.context["glossary"], material.records[row["identity"]]["source"], before, after)
        if row["kind"] == "glossary/name"
        else []
    )
    return item


def _controls(material: Material, corrected: set[str]) -> list[dict[str, Any]]:
    found = []
    for ordered in material.scenes.values():
        for record in _messages(ordered):
            identity = record["identity"]
            live = record.get("live") or ""
            if identity in corrected or identity in material.unread or not live.strip() or live == record["source"]:
                continue
            item = _item(
                material, identity, "control", type="control", category="",
                group=None, draft=live, accepted=live, reason="", glossary=[],
            )
            if item is not None:
                found.append(item)
    return found


def _balanced(cells: dict[tuple[str, ...], list[dict[str, Any]]], count: int, seed: str) -> list[dict[str, Any]]:
    """Up to *count* items taken a cell at a time, in a seeded order, with at
    most GROUP_ITEMS of one recurring group."""
    queues = {
        key: sorted(items, key=lambda item: _order(seed, item["id"]))
        for key, items in cells.items()
    }
    order = sorted(queues, key=lambda key: _order(seed, "/".join(key)))
    taken: list[dict[str, Any]] = []
    groups: dict[str, int] = defaultdict(int)
    while len(taken) < count and any(queues.values()):
        for key in order:
            queue = queues[key]
            while queue:
                item = queue.pop(0)
                group = item["group"]
                if group and groups[group] >= GROUP_ITEMS:
                    continue
                if group:
                    groups[group] += 1
                taken.append(item)
                break
            if len(taken) >= count:
                break
    return taken


def split_of(item: dict[str, Any], seed: str = SEED) -> str:
    """The half an item belongs to, by its recurring group when it has one,
    so a group never sits on both sides."""
    key = item["group"] or "item:" + item["id"]
    return SPLITS[int(_order(seed, key)[:8], 16) % 2]


def build(export: Path, *, defects: int = DEFECTS, controls: int = CONTROLS,
          seed: str = SEED) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The regression set from a QA export: its header and items."""
    header, rows = read_export(export)
    games = {game["game"]: game for game in header["games"]}
    by_origin: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_origin[(row["game"], row["task"])].append(row)
    corrected: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        corrected[row["game"]].update(row.get("places") or [row["identity"]])
    materials: list[Material] = []
    skipped: list[str] = []
    with system.staging_folder(tempfile.gettempdir(), "dazedtl-quality-set-") as staging:
        for name, game in games.items():
            for source in game["sources"]:
                key = (name, source["task"])
                try:
                    if source["origin"] == "task":
                        materials.append(_task_material(name, source))
                    elif key in by_origin:
                        files = {row["file"] for row in by_origin[key]}
                        materials.append(
                            _receipts_material(name, Path(game["game_root"]), source, files, staging)
                        )
                except (OSError, ValueError, KeyError) as exc:
                    skipped.append(f"{name} {source['task']}: {exc}")
    defect_cells: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    control_cells: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for material in materials:
        for row in by_origin.get((material.game, material.task), []):
            item = _defect(material, row)
            if item is not None:
                defect_cells[(item["game"], item["kind"])].append(item)
        if material.screened:
            for item in _controls(material, corrected[material.game]):
                control_cells[(item["game"],)].append(item)
    # A line two tasks of one game each hold is one control.
    seen: set[tuple[str, str]] = set()
    for key, items in control_cells.items():
        unique = []
        for item in sorted(items, key=lambda item: item["id"]):
            line = (item["game"], item["lines"][item["target"]]["source"])
            if line not in seen:
                seen.add(line)
                unique.append(item)
        control_cells[key] = unique
    items = _balanced(defect_cells, defects, seed) + _balanced(control_cells, controls, seed)
    for item in items:
        item["split"] = split_of(item, seed)
    used = {item["context"] for item in items}
    set_header = {
        "schema": SCHEMA,
        "format": FORMAT,
        "version": VERSION,
        "kind": "set",
        "name": "qa-corrections",
        "created": datetime.now(timezone.utc).isoformat(),
        "inputs": {"export": str(Path(export).resolve()), "export_version": header["version"]},
        "seed": seed,
        "chunk_lines": CHUNK_LINES,
        "history_lines": HISTORY_LINES,
        "language": {"source": "Japanese", "target": "English"},
        "contexts": {
            material.key: material.context for material in materials if material.key in used
        },
        "skipped": skipped,
    }
    set_header["counts"] = counts(items)
    return set_header, [_ordered_item(item) for item in items]


def _ordered_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ITEM_FIELDS if key in item}


def counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Items by type, split, game and kind."""
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        for name, value in (
            ("type", item["type"]),
            ("split", item.get("split") or "targeted"),
            ("game", item["game"]),
            ("kind", item["kind"]),
            ("type/split", f"{item['type']}/{item.get('split') or 'targeted'}"),
        ):
            table[name][value] += 1
    return {name: dict(sorted(values.items())) for name, values in table.items()}


# Files


def write(path: Path, header: dict[str, Any], items: list[dict[str, Any]]) -> Path:
    """Writes a set or targeted item file outside the source tree; it holds
    game text."""
    target = Path(path).expanduser().resolve()
    if target == qa_corrections.SOURCE_TREE or qa_corrections.SOURCE_TREE in target.parents:
        raise ValueError(f"A quality set holds game text; write it outside {qa_corrections.SOURCE_TREE}")
    validate(header, items)
    lines = [json.dumps(header, ensure_ascii=False)]
    lines += [json.dumps(item, ensure_ascii=False) for item in items]
    system.write_text(target, "\n".join(lines) + "\n")
    return target


def load(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A set or targeted item file's header and items, validated."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")
    header = json.loads(lines[0])
    items = [json.loads(line) for line in lines[1:] if line.strip()]
    validate(header, items, name=str(path))
    return header, items


def validate(header: dict[str, Any], items: list[dict[str, Any]], *, name: str = "set") -> None:
    """Refuses a file another form, or an item its requests cannot be built
    from without reading a game."""
    if header.get("schema") != SCHEMA or header.get("format") != FORMAT:
        raise ValueError(f"{name} is not a format {FORMAT} {SCHEMA} file")
    if header.get("kind") not in KINDS:
        raise ValueError(f"{name}: kind must be one of {', '.join(KINDS)}")
    if type(header.get("version")) is not int or header["version"] < 1:
        raise ValueError(f"{name}: version must be a whole number from 1")
    if not str(header.get("name") or "").strip():
        raise ValueError(f"{name}: name the file")
    language = header.get("language") or {}
    if not all(isinstance(language.get(side), str) and language[side] for side in ("source", "target")):
        raise ValueError(f"{name}: name the language pair")
    contexts = header.get("contexts")
    if not isinstance(contexts, dict):
        raise ValueError(f"{name}: contexts must map a context ID to its guidance")
    for key, context in contexts.items():
        if (
            not isinstance(context, dict)
            or not isinstance(context.get("glossary"), str)
            or not isinstance(context.get("overlays"), list)
            or not all(isinstance(part, str) for part in context["overlays"])
        ):
            raise ValueError(f"{name}: context {key} needs its overlays and glossary")
    seen: set[str] = set()
    for item in items:
        identity = item.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", identity) or identity in seen:
            raise ValueError(f"{name}: every item needs a unique ID of letters, digits, '.', '_' or '-'")
        seen.add(identity)
        label = f"{name} item {identity}"
        if item.get("type") not in ("defect", "control"):
            raise ValueError(f"{label}: type must be defect or control")
        if header["kind"] == "set" and item.get("split") not in SPLITS:
            raise ValueError(f"{label}: a set item needs a split")
        if header["kind"] == "targeted" and "split" in item:
            raise ValueError(f"{label}: a targeted item never joins a split")
        if item.get("context") not in contexts:
            raise ValueError(f"{label}: its context is not in the header")
        lines = item.get("lines")
        if not isinstance(lines, list) or not lines or not isinstance(item.get("history"), list):
            raise ValueError(f"{label}: needs its lines and history")
        for line in [*lines, *item["history"]]:
            if not isinstance(line, dict) or not isinstance(line.get("source"), str) or not line["source"].strip():
                raise ValueError(f"{label}: every line needs its source text")
            if "kind" in line and line["kind"] not in LINE_KINDS:
                raise ValueError(f"{label}: a line kind is one of {', '.join(LINE_KINDS)}")
        target = item.get("target")
        if type(target) is not int or not 0 <= target < len(lines):
            raise ValueError(f"{label}: target must be the index of one of its lines")
        for key in ("draft", "accepted"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"{label}: needs its {key} translation")
        if item["type"] == "defect" and not str(item.get("reason") or "").strip():
            raise ValueError(f"{label}: a defect needs the reviewer's reason")
        rows = item.get("glossary", [])
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get("source"), str) and isinstance(row.get("target"), str)
            and row["target"] for row in rows
        ):
            raise ValueError(f"{label}: glossary rows need their source and target")


def unavailable(item: dict[str, Any], method: str) -> str | None:
    """Why *method*'s request cannot be built from *item* without inventing
    context, or None when it can. Guided needs each line's speaker name
    stated (null for none); Assistant-led also needs its speaker and kind."""
    lines = [*item["lines"], *item["history"]]
    if method == "guided":
        missing = [key for key in ("speaker_name",) if any(key not in line for line in lines)]
    elif method == "assistant-led":
        missing = [key for key in ("speaker", "kind") if any(key not in line for line in item["lines"])]
    else:
        raise ValueError(f"Unknown method {method!r}; use one of {', '.join(METHODS)}")
    if missing:
        return "lines without " + " or ".join(missing)
    return None
