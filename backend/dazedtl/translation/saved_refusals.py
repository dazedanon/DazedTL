"""Refusal notes that earlier runs saved in place of translations.

Before refusal notes counted as refusals, runs saved notes such as
"[Not translated: ...]" as the translation of their lines. The engine sends
only text that still holds Japanese, so those lines then read as translated.
A line's Japanese source is its `_original`, or the original game file's value
where the engine keeps none, such as event names a label plugin shows.
Putting the source back lets the next run translate the line again; a note
without a known source stays as it is.
"""

import re
from typing import NamedTuple

from .refusals import line_refusal

# A message keeps its whole source on its first command; its translation may
# be laid over the rows after it.
MESSAGES = frozenset({401, 405})
QUOTED = re.compile(r"['\"`](.*)['\"`]")


class Note(NamedTuple):
    paths: tuple
    source: str
    code: int | None
    transform: str


def commands(value):
    """An event command list, which starts with a command."""
    return bool(value) and isinstance(value[0], dict) and "code" in value[0]


def resolve(document, path):
    for part in path:
        document = document[part]
    return document


def find(document, original=lambda: None):
    """The document's saved refusal notes with a known source. `original`
    returns the original game file's document, or None; it is read only when
    a value without `_original` may hold a note."""
    # QA's inventory pairs each `_original` with the text the game shows;
    # importing its mapping keeps QA's extractor hash, and its tasks, current.
    from util.rpgmaker_qa_manifest import live_mapping, read_live, string_leaves

    found, covered, strings = [], set(), []

    # One walk reads both kinds of note: the values an `_original` keeps a
    # source for (`notes`, until a command holds them), and the strings
    # outside event command lists (`fields`), whose source the original
    # game file keeps at the same path.
    def walk(value, path, listed=None, index=None, notes=True, fields=True):
        if isinstance(value, dict):
            code = value.get("code") if isinstance(value.get("code"), int) else None
            if notes and value.get("_original") is not None:
                for relative, source in string_leaves(value["_original"]):
                    mapping = live_mapping(value, path, relative, code, listed, index)
                    if mapping is None:
                        continue
                    try:
                        live, transform = read_live(document, mapping[0], code)
                    except KeyError, IndexError, TypeError, ValueError:
                        continue
                    covered.update(mapping[0])
                    if live != source and line_refusal(live, source):
                        found.append(Note(tuple(mapping[0]), source, code, transform))
            # A command's own parameters hold no `_original` of their own.
            notes = notes and code is None
            inside, pairs = (
                False,
                ((key, child) for key, child in value.items() if key != "_original"),
            )
        else:
            inside = commands(value)
            fields = fields and not inside
            # Lists of numbers, such as a map's tiles, hold no text.
            pairs = (
                enumerate(value)
                if value and not isinstance(value[0], (int, float))
                else ()
            )
        if not (notes or fields):
            return
        for key, child in pairs:
            if isinstance(child, str):
                # An empty source excuses no note, which finds every
                # candidate first.
                if fields and line_refusal(child, ""):
                    strings.append(((*path, key), child))
            elif isinstance(child, (dict, list)):
                walk(
                    child,
                    (*path, key),
                    value if inside else None if isinstance(value, dict) else listed,
                    key if inside else None if isinstance(value, dict) else index,
                    notes,
                    fields,
                )

    walk(document, ())
    # Outside event commands the engine keeps every value where the original
    # has it, so a value without `_original` takes the original's at its path.
    candidates = [(path, value) for path, value in strings if path not in covered]
    source_document = original() if candidates else None
    for path, value in candidates:
        try:
            source = resolve(source_document, path)
        except KeyError, IndexError, TypeError:
            continue
        if isinstance(source, str) and value != source and line_refusal(value, source):
            found.append(Note((path,), source, None, "identity"))
    return found


def restore(document, original=lambda: None):
    """Puts each saved refusal note's source back in place, so the engine
    sends the line again; returns how many lines it restored."""
    from util import rpgmaker_blocks as blocks

    read = []

    def source_document():
        if not read:
            read.append(original())
        return read[0]

    notes = find(document, source_document)
    for note in notes:
        first = note.paths[0]
        if note.code == 408:
            # A comment's translation keeps the rows it owns, read against
            # the original game file where it recorded none, so the next run
            # writes over those and leaves the game's own rows.
            listed, index = resolve(document, first[:-3]), first[-3]
            if blocks.recorded(listed[index]) is None:
                try:
                    theirs = resolve(source_document(), first[:-3])
                except KeyError, IndexError, TypeError:
                    theirs = None
                listed[index][blocks.ROWS] = len(
                    blocks.owned(
                        listed,
                        index,
                        original=theirs if isinstance(theirs, list) else None,
                    )
                )
        parent, key = resolve(document, first[:-1]), first[-1]
        if note.code in MESSAGES:
            # Each line is (..., command list, position, "parameters", 0); the
            # source goes back over every row, so the event keeps them all.
            blocks.write_text(
                resolve(document, first[:-3]),
                tuple(path[-3] for path in note.paths),
                note.source,
                joined=False,
            )
        elif note.transform != "identity":
            match = QUOTED.search(parent[key])
            assert match  # find read the note between these quote marks.
            parent[key] = (
                parent[key][: match.start(1)]
                + note.source
                + parent[key][match.end(1) :]
            )
        else:
            parent[key] = note.source
    return len(notes)
