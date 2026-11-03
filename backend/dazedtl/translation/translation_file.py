"""The translation file: a game's text, line by line, with its translation,
in one format every method reads and writes, so a translation can leave
DazedTL at any point, be edited or shared, and come back
(docs/translation-contract.md, Translation files).

A line is a source unit (organize) with its translation: a stable ID, the
source text exactly as the game holds it and the translation, or null where
there is none yet. IDs come from whoever extracted the text: Guided names
each line by its place in the original game's files, an assistant's or the
user's own extractor by its own scheme. A file is read as JSON or as a CSV
view of its lines; the JSON form also carries the language pair and the
game's glossary. A plain units file reads as a translation file without
translations, so the user's own extractor can write either.

Importing matches each line by ID and requires its source to be the text the
project holds there now, so a line of another game version never lands on a
changed line.
"""

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from dazedtl import system

from . import organize
from .files import decode_json, digest

FORMAT = "dazedtl-translation"
VERSION = 1
SUFFIXES = {".json", ".csv"}
# A file this size holds every line of the largest games with room to spare;
# a Manual load checks its units file against JSON_LIMIT itself.
LIMIT = 256_000_000
# A line's fields: a source unit's, with its translation.
FIELDS = organize.FIELDS | {"translation"}
# The CSV view's columns, in the order an export writes them; the ones after
# translation are written only when a line has them.
COLUMNS = ("id", "scene", "group", "kind", "speaker", "source", "translation")
BOUNDS = ("max_lines", "max_characters")
CSV_COLUMNS = (*COLUMNS, "field", *BOUNDS)
GLOSSARY_FIELDS = {"section", "source", "translation", "note"}
# How many skipped lines an import names, each with why.
LISTED = 20


def _single_line(value, limit):
    return (
        isinstance(value, str)
        and value.strip()
        and len(value) <= limit
        and not any(char in value for char in "\r\n\0")
    )


def _problem(text, places):
    shown = list(dict.fromkeys(str(place) for place in places))
    more = len(shown) - 5
    return ValueError(
        text
        + ": "
        + ", ".join(shown[:5])
        + (f" and {more} more" if more > 0 else "")
        + "."
    )


def _lines(rows, place):
    """The file's lines, each with a single-line ID, unique in the file, its
    source text and its translation or None; their other fields are a source
    unit's, which units() checks. Errors name the lines by *place* (their
    position or CSV row) and never repeat game text."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("The translation file lists no lines.")
    problems: dict[str, list] = {}
    seen = set()
    lines = []
    for position, row in enumerate(rows):
        where = place(position)
        if not isinstance(row, dict):
            problems.setdefault("Each line must be an object", []).append(where)
            continue
        unknown = set(row) - FIELDS
        if unknown:
            problems.setdefault(
                "Lines accept only "
                + ", ".join(sorted(FIELDS))
                + f"; found {', '.join(sorted(unknown))} on lines",
                [],
            ).append(where)
            continue
        identity = row.get("id")
        if not _single_line(identity, 240):
            problems.setdefault(
                "Line IDs must be single-line text of at most 240 characters; lines",
                [],
            ).append(where)
            continue
        if identity in seen:
            problems.setdefault("Line IDs must be unique", []).append(identity)
            continue
        seen.add(identity)
        source = row.get("source")
        if not isinstance(source, str) or not source.strip():
            problems.setdefault("Lines need nonempty source text", []).append(identity)
            continue
        translation = row.get("translation")
        if translation is not None and not isinstance(translation, str):
            problems.setdefault(
                "A translation is text, or null where there is none", []
            ).append(identity)
            continue
        lines.append(
            {
                **row,
                "translation": translation
                if translation and translation.strip()
                else None,
            }
        )
    if problems:
        text, places = next(iter(problems.items()))
        raise _problem(text, places)
    return lines


def _languages(value):
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"source", "target"}
        or not all(_single_line(value[key], 40) for key in value)
    ):
        raise ValueError(
            'The file\'s languages name its source and target, such as {"source": "Japanese", "target": "English"}.'
        )
    return dict(value)


def _glossary(rows):
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("The file's glossary is a list of entries.")
    entries = []
    for position, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or set(row) - GLOSSARY_FIELDS
            or not _single_line(row.get("section"), 200)
            or not _single_line(row.get("source"), 400)
            or not _single_line(row.get("translation"), 400)
            or not (row.get("note") is None or isinstance(row["note"], str))
            or "\n" in (row.get("note") or "")
        ):
            raise ValueError(
                f"Glossary entry {position} needs a section, source and translation on one line each, and an optional note."
            )
        entries.append(
            {
                "section": row["section"].strip(),
                "source": row["source"].strip(),
                "translation": row["translation"].strip(),
                "note": (row.get("note") or "").strip(),
            }
        )
    return entries


def _json(raw):
    value = decode_json(raw)
    if isinstance(value, dict) and value.get("format") == FORMAT:
        if type(value.get("version")) is not int or value["version"] != VERSION:
            raise ValueError(
                "This translation file is from a newer DazedTL. Update DazedTL to read it."
            )
        known = {
            "format",
            "version",
            "languages",
            "game",
            "exported",
            "lines",
            "glossary",
        }
        if set(value) - known:
            raise ValueError(
                "A translation file holds only " + ", ".join(sorted(known)) + "."
            )
        return {
            "languages": _languages(value.get("languages")),
            "lines": _lines(value.get("lines"), lambda at: at + 1),
            "glossary": _glossary(value.get("glossary")),
        }
    if isinstance(value, dict) and set(value) == {"version", "units"}:
        # A plain source units file, as an extractor writes for organize.
        if value["version"] != organize.VERSION:
            raise ValueError("Source units require version 1.")
        return {
            "languages": None,
            "lines": _lines(value["units"], lambda at: at + 1),
            "glossary": [],
        }
    raise ValueError(
        f'This is not a translation file: one is a JSON object with "format": "{FORMAT}" and its lines, or a CSV file with id, scene, source and translation columns.'
    )


def _csv(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Save the CSV file as UTF-8, then choose it again.") from error
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("The CSV file is empty.") from None
    names = [name.strip().lower() for name in header]
    unknown = [name for name in names if name not in CSV_COLUMNS]
    if unknown or len(set(names)) != len(names):
        raise ValueError(
            "A translation CSV has a header row of these columns, each once: "
            + ", ".join(CSV_COLUMNS)
            + (f". Found {', '.join(unknown)}." if unknown else ".")
        )
    if not {"id", "source"} <= set(names):
        raise ValueError("A translation CSV needs at least the id and source columns.")
    rows = []
    for number, cells in enumerate(reader, 2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) > len(names):
            raise ValueError(
                f"Row {number} of the CSV file has more cells than its header."
            )
        row: dict = {}
        for name, cell in zip(names, cells, strict=False):
            if not cell:
                continue
            if name in BOUNDS:
                if not cell.strip().isdigit():
                    raise ValueError(
                        f"Row {number}'s {name} must be a positive whole number."
                    )
                row[name] = int(cell)
            else:
                row[name] = cell
        rows.append((number, row))
    numbers = [number for number, _row in rows]
    return {
        "languages": None,
        "lines": _lines([row for _number, row in rows], lambda at: numbers[at]),
        "glossary": [],
    }


def read(path):
    """The translation file at *path*: its language pair (None when it names
    none, as a CSV file never does), lines and glossary entries, and its
    bytes' digest, which an import checks it still has."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("Choose a translation file ending in .json or .csv.")
    if path.is_symlink() or not path.is_file():
        raise ValueError("That translation file doesn't exist.")
    if path.stat().st_size > LIMIT:
        raise ValueError("That file is too large for a translation file.")
    raw = system.read_bytes(path)
    value = _json(raw) if suffix == ".json" else _csv(raw)
    return {**value, "sha256": digest(raw)}


def units(lines):
    """The file's lines as organize's validated source units, for a Manual
    project, whose own extractor wrote them."""
    return organize.units_input(
        {
            "version": organize.VERSION,
            "units": [
                {key: value for key, value in line.items() if key != "translation"}
                for line in lines
            ],
        }
    )


def destination(path, game):
    """*path* as where an export may write: a .json or .csv file outside
    the game folder at *game*, so it never joins the game's files, in a
    folder that exists."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Choose where to save the translation file.")
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ValueError("Choose where to save the translation file.")
    if target.suffix.lower() not in SUFFIXES:
        raise ValueError("Save the translation file as .json or .csv.")
    if target.is_symlink() or target.is_dir():
        raise ValueError("Choose a file name, not a folder or a link.")
    folder = target.parent.resolve()
    if not folder.is_dir():
        raise ValueError("That folder doesn't exist.")
    target = folder / target.name
    root = Path(game).resolve()
    if target == root or target.is_relative_to(root):
        raise ValueError(
            "Save the translation file outside the game folder, so it never joins the game's files."
        )
    return target


def document(languages, lines, glossary=(), game=None):
    """A translation file of *lines*, in play order, each a source unit's
    fields with its translation or None, for the game *game* describes."""
    value = {
        "format": FORMAT,
        "version": VERSION,
        "languages": dict(languages),
        "game": game or {},
        "exported": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "lines": [
            {
                key: line[key]
                for key in (*COLUMNS, *sorted(FIELDS - set(COLUMNS)))
                if key in line
            }
            for line in lines
        ],
    }
    if glossary:
        value["glossary"] = list(glossary)
    return value


def example(languages):
    """An example file for a user's own extractor, in the project's
    *languages*: organize's example units, the first waiting for its
    translation and the second translated, which a Manual load keeps, and a
    glossary entry, so it shows every field a file holds and loads as is."""
    first, second = organize.EXAMPLE["units"]
    return document(
        languages,
        [{**first, "translation": None}, {**second, "translation": "Medicine"}],
        [
            {
                "section": "Game Characters",
                "source": "リリ",
                "translation": "Lili",
                "note": "The heroine",
            }
        ],
    )


def write(path, value):
    """Writes the translation file *value* to *path*, as JSON or as the CSV
    view of its lines by the path's suffix. The CSV file starts with a byte
    order mark, so spreadsheet programs read it as UTF-8."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        columns = [
            name
            for name in CSV_COLUMNS
            if name in COLUMNS or any(name in line for line in value["lines"])
        ]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(columns)
        for line in value["lines"]:
            writer.writerow(
                ["" if line.get(name) is None else line[name] for name in columns]
            )
        content = ("﻿" + stream.getvalue()).encode("utf-8")
    else:
        content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
    # Others read a shared file, unlike the workspace's own files.
    system.write_bytes(path, content, mode=0o644)


def check_languages(found, languages):
    """Refuses a file whose language pair *found* is not the project's
    *languages*; a file naming none, such as a CSV file, is read in the
    project's."""
    if found and (found["source"], found["target"]) != (
        languages["source"],
        languages["target"],
    ):
        raise ValueError(
            f"This file translates {found['source']} into {found['target']}, but this game translates {languages['source']} into {languages['target']}."
        )


def matched(lines, current, problems):
    """What importing *lines* does to the project's *current* lines, each a
    source and its translation or None by ID: the translations to write by
    ID, how many add a translation or replace one, and the lines skipped,
    by why. A line is written only where its ID names a line whose source
    is still the text the file holds, and only if *problems*, given the
    translations to write by ID, finds nothing wrong with it: the checks a
    saved translation passes, by ID with why."""
    write, before = {}, {}
    counts = {
        "lines": len(lines),
        "added": 0,
        "replaced": 0,
        "unchanged": 0,
        "empty": 0,
    }
    skipped: dict[str, list] = {"unknown": [], "changed": []}
    for line in lines:
        here = current.get(line["id"])
        if here is None:
            skipped["unknown"].append(line["id"])
        elif here["source"] != line["source"]:
            skipped["changed"].append(line["id"])
        elif line["translation"] is None:
            counts["empty"] += 1
        elif line["translation"] == here["translation"]:
            counts["unchanged"] += 1
        else:
            write[line["id"]] = line["translation"]
            before[line["id"]] = here["translation"]
    refused = problems(write) if write else {}
    for identity in refused:
        del write[identity]
    for identity in write:
        counts["added" if before[identity] is None else "replaced"] += 1
    return write, summary(counts, skipped, refused)


REASONS = {
    "unknown": "No line of this game has this ID.",
    "changed": "The game's source text for this ID is different.",
}


def summary(counts, skipped, refused):
    """An import's counts with the skipped lines named, up to LISTED of them,
    each with why; *refused* holds the lines whose translation failed the
    checks a saved translation passes, by ID with why."""
    listed = [
        {"id": identity, "reason": REASONS[kind]}
        for kind in ("changed", "unknown")
        for identity in skipped[kind]
    ] + [{"id": identity, "reason": reason} for identity, reason in refused.items()]
    return {
        **counts,
        "unknown": len(skipped["unknown"]),
        "changed": len(skipped["changed"]),
        "refused": len(refused),
        "skipped": listed[:LISTED],
    }
