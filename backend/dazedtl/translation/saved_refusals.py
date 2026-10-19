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

# A message keeps its whole source on its first command, which holds the
# translation; following lines are ones the engine added after it.
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


def children(value):
    """A value's lists and objects. Lists of numbers, such as a map's tiles,
    hold no text and are skipped whole."""
    if isinstance(value, dict):
        items = ((key, child) for key, child in value.items() if key != "_original")
    elif value and not isinstance(value[0], (int, float)):
        items = enumerate(value)
    else:
        return
    for key, child in items:
        if isinstance(child, (dict, list)):
            yield key, child


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
    from util.rpgmaker_qa_manifest import _live_mapping, _read_live, _string_leaves

    found, covered = [], set()

    def walk(value, path, listed=None, index=None):
        if isinstance(value, dict):
            code = value.get("code") if isinstance(value.get("code"), int) else None
            if value.get("_original") is not None:
                for relative, source in _string_leaves(value["_original"]):
                    mapping = _live_mapping(value, path, relative, code, listed, index)
                    if mapping is None:
                        continue
                    try:
                        live, transform = _read_live(document, mapping[0], code)
                    except KeyError, IndexError, TypeError, ValueError:
                        continue
                    covered.update(mapping[0])
                    if live != source and line_refusal(live, source):
                        found.append(Note(tuple(mapping[0]), source, code, transform))
            # A command's own parameters hold no `_original` of their own.
            if code is None:
                for key, child in children(value):
                    walk(child, path + (key,))
        else:
            inside = commands(value)
            for position, child in children(value):
                walk(
                    child,
                    path + (position,),
                    value if inside else listed,
                    position if inside else index,
                )

    walk(document, ())
    # Outside event commands the engine keeps every value where the original
    # has it, so a value without `_original` takes the original's at its path.
    # An empty source excuses no note, which finds every candidate first.
    candidates = []

    def fields(value, path):
        if isinstance(value, list) and commands(value):
            return
        pairs = (
            ((key, child) for key, child in value.items() if key != "_original")
            if isinstance(value, dict)
            else enumerate(value)
            if value and not isinstance(value[0], (int, float))
            else ()
        )
        for key, child in pairs:
            if isinstance(child, str):
                if (*path, key) not in covered and line_refusal(child, ""):
                    candidates.append(((*path, key), child))
            elif isinstance(child, (dict, list)):
                fields(child, (*path, key))

    fields(document, ())
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
    notes = find(document, original)
    added = []
    for note in notes:
        first = note.paths[0]
        parent, key = resolve(document, first[:-1]), first[-1]
        if note.transform != "identity":
            match = QUOTED.search(parent[key])
            assert match  # find read the note between these quote marks.
            parent[key] = (
                parent[key][: match.start(1)]
                + note.source
                + parent[key][match.end(1) :]
            )
        else:
            parent[key] = note.source
        if note.code in MESSAGES:
            # Each following line is (..., command list, position, "parameters", 0).
            added.extend((path[:-3], path[-3]) for path in note.paths[1:])
    # Later positions first, so removing a line moves none still to remove.
    for listed, position in sorted(added, key=lambda item: item[1], reverse=True):
        del resolve(document, listed)[position]
    return len(notes)
