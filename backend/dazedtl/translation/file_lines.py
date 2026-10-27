"""How much of a game data file is translated, read from the file itself.

Guided's Database files and Maps & events count each file's lines in its
newest copy, so the count is right whichever runs wrote it, and a file reads
finished only when nothing in it is left for the engine to send. A line is
what a person reads as one: in an event file, the game text
util/rpgmaker_scope lists (an event text block as util/rpgmaker_blocks
defines it: a message, with its name box; scrolling text; one choice of a
menu; a choice's help, or another comment a plugin shows, with Comment text
on; an actor name, nickname or profile an event changes; a map display
name; an event's note label), and the database fields and
system terms Text QA's never-translated report lists
(util/rpgmaker_qa_preflight `visible_texts`). What another task translates,
or no task does, is left out.

A line is in scope when its source holds Japanese (util/source_text): the
source the engine keeps in `_original`, else the text itself. The engine
sends a value while it holds Japanese read against that source, so a line is
translated when no part of it holds Japanese left (of a name box, the name the
engine translates), unless it holds a refusal note an earlier run saved in
place of a translation (`saved_refusals`). A translated map display name or
note label keeps no `_original`, so whether it had Japanese takes the
original game file, and any Japanese it holds is left. The engine probe
(tests/fixtures/engine_runtime.py) checks that the engine sends only the
lines left.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

from . import refusals

_MAP = re.compile(r"Map\d+\.json")
# Database fields the database pass translates, beyond those players read in
# menus: map names, which some plugins show.
_MAP_INFOS = "MapInfos.json"
# System values the engine leaves as they are.
_KEPT_SYSTEM = frozenset({"currencyUnit"})


# A 101's name window may wrap its name in colour codes and 【】, and hold
# more after it; the engine translates only the name (rpgmakermvmz
# _101_speaker_name).
_NAME_COLOURS = re.compile(r"^(?:[\\]+[cC]\[\d+\]\s*)+")
_BRACKETED_NAME = re.compile(r"^【\s*([^】]+?)\s*】")
_PLAIN_NAME = re.compile(r"^([^\\]+)")


def speaker_name(value: Any) -> str:
    """The part of a 101's name window the engine translates."""
    name = _NAME_COLOURS.sub("", str(value or "").strip())
    found = _BRACKETED_NAME.match(name) or _PLAIN_NAME.match(name)
    return found.group(1).strip() if found else ""


class Line(NamedTuple):
    """One line a person reads: its kind, the paths of its values, their
    text, and the Japanese source the engine keeps for them. A line of more
    than one value names the text the engine sends as one in *units*, each
    with its source, or None for text the engine keeps none for."""

    kind: str
    paths: tuple[tuple, ...]
    texts: tuple[str, ...]
    sources: tuple[str, ...]
    units: tuple[tuple[str, str | None], ...] = ()

    def sent(self) -> tuple[tuple[str, str | None], ...]:
        """The text the engine sends as one, each with its source."""
        if self.units:
            return self.units
        if len(self.texts) == 1:
            return ((self.texts[0], self.sources[0] if self.sources else None),)
        return tuple((text, None) for text in self.texts)

    def shown_source(self) -> str:
        """The Japanese a person compares the line with: each sent text's
        source, else the text itself, which is its own source while the engine
        keeps none (util/source_text)."""
        shown = (
            source if source and source.strip() else text
            for text, source in self.sent()
        )
        return "\n".join(value for value in shown if value.strip())


def _resolve(document: Any, path: tuple) -> Any:
    for part in path:
        document = document[part]
    return document


def _command_original(command: Any) -> tuple[str, ...]:
    original = command.get("_original") if isinstance(command, dict) else None
    return (original,) if isinstance(original, str) else ()


def _entry_original(document: Any, path: tuple) -> tuple[str, ...]:
    """A database field's source in its entry's `_original`, by its path."""
    try:
        entry = _resolve(document, path[:-1])
    except KeyError, IndexError, TypeError:
        return ()
    original = entry.get("_original") if isinstance(entry, dict) else None
    value = original.get(path[-1]) if isinstance(original, dict) else None
    return (value,) if isinstance(value, str) else ()


def _visible(
    name: str, document: Any, markers: frozenset[str] = frozenset()
) -> Iterator[tuple[tuple[Any, ...], Any, str, bool, str | None]]:
    """Text QA's reader (a QA engine source, read unchanged so its tasks'
    fingerprint holds): each text's path, value, kind, `_original` flag and
    the source it keeps there."""
    from util.rpgmaker_qa_preflight import visible_texts

    yield from visible_texts(name, document, markers)


def lines(
    name: str, document: Any, phase: str, markers: frozenset[str] = frozenset()
) -> list[Line]:
    """Each line of a phase's scope ("database" or "dialogue") in one data
    file, in file order, whether or not it is in scope. Event text reads its
    blocks as util/rpgmaker_blocks defines them; choice help, and other
    comments a plugin shows, count under *markers*, the comment markers
    Comment text translates, none while it is off."""
    from util import rpgmaker_blocks as blocks
    from util.rpgmaker_scope import changes, kept

    if phase == "database":
        return _database(name, document)
    found: list[Line] = []
    if not (_MAP.fullmatch(name) or name in {"CommonEvents.json", "Troops.json"}):
        return found
    readable = _events(name, document)
    for listed, commands in blocks.command_lists(readable):
        listing: list[Line] = []
        for change in changes(commands):
            command = commands[change.index]
            path = (*listed, change.index, "parameters", 1)
            listing.append(
                Line(
                    change.kind,
                    (path,),
                    (command["parameters"][1],),
                    _command_original(command),
                )
            )
        for block in blocks.blocks(commands):
            if block.kind == blocks.CHOICE and block.head is not None:
                command = commands[block.head]
                choices = command["parameters"][0]
                original = command.get("_original")
                for choice, value in enumerate(choices):
                    source = (
                        (original[choice],)
                        if isinstance(original, list)
                        and choice < len(original)
                        and isinstance(original[choice], str)
                        else ()
                    )
                    path = (*listed, block.head, "parameters", 0, choice)
                    listing.append(Line(blocks.CHOICE, (path,), (str(value),), source))
                continue
            if block.kind in (blocks.HELP, blocks.COMMENT):
                if not block.shown(markers):
                    continue
                kind = blocks.HELP
            else:
                kind = block.kind
            paths: list[tuple] = []
            texts: list[str] = []
            sources: list[str] = []
            units: list[tuple[str, str | None]] = []
            head = commands[block.head] if block.head is not None else None
            parameters = (
                head.get("parameters")
                if isinstance(head, dict) and blocks.code(head) == 101
                else None
            )
            if (
                head is not None
                and isinstance(parameters, list)
                and len(parameters) > 4
            ):
                # The name box: only its name is translated.
                paths.append((*listed, block.head, "parameters", 4))
                texts.append(speaker_name(parameters[4]))
                named = tuple(map(speaker_name, _command_original(head)))
                sources.extend(named)
                units.append((texts[-1], named[0] if named else None))
            for row in block.rows:
                paths.append((*listed, row, "parameters", 0))
                texts.append(blocks.text(commands[row]))
            for part in block.parts:
                source = blocks.source(commands, part)
                if source is not None:
                    sources.append(source)
                rows = (blocks.text(commands[row]) for row in part.rows)
                units.append(("\n".join(row for row in rows if row.strip()), source))
            if paths:
                listing.append(
                    Line(kind, tuple(paths), tuple(texts), tuple(sources), tuple(units))
                )
        # In file order: by the command each line starts at.
        listing.sort(key=lambda line: line.paths[0][len(listed)])
        found.extend(listing)
    if _MAP.fullmatch(name) and isinstance(readable, dict):
        value = readable.get("displayName")
        if isinstance(value, str):
            source = kept(document, "displayName")
            found.append(Line("map name", (("displayName",),), (value,), _kept(source)))
        found.extend(_labels(document))
    return found


def _labels(document: Any) -> Iterator[Line]:
    """A map's note labels (util/rpgmaker_scope), each at the field holding
    it, with the source its event keeps for it."""
    from util.rpgmaker_scope import labels

    events = document.get("events") if isinstance(document, dict) else None
    for index, event in enumerate(events if isinstance(events, list) else ()):
        for label in labels(event):
            path = (("events", index, label.field),)
            yield Line("label", path, (label.text,), _kept(label.source))


def _kept(source: str | None) -> tuple[str, ...]:
    """A map name's or label's sources: the one its map or event keeps."""
    return () if source is None else (source,)


def _pages(owner: Any, key: str) -> Any:
    """An event's, or a troop's, pages with their command lists alone."""
    if not isinstance(owner, dict) or not isinstance(owner.get(key), list):
        return owner
    return {
        key: [
            {"list": page["list"]}
            if isinstance(page, dict) and "list" in page
            else page
            for page in owner[key]
        ]
    }


def _events(name: str, document: Any) -> Any:
    """The parts of an event file the engine reads lines from, at their own
    paths: a map's name and its events' command lists, a common event's list
    and a troop's pages. The reader would walk the rest, such as a map's
    tiles and each page's settings, value by value."""
    if _MAP.fullmatch(name) and isinstance(document, dict):
        events = document.get("events")
        return {
            "displayName": document.get("displayName"),
            "events": [_pages(event, "pages") for event in events]
            if isinstance(events, list)
            else events,
        }
    if not isinstance(document, list):
        return document
    if name == "CommonEvents.json":
        return [
            {"list": event["list"]}
            if isinstance(event, dict) and "list" in event
            else event
            for event in document
        ]
    return [_pages(troop, "pages") for troop in document]


def _fields(name: str, document: Any) -> Any:
    """The database text fields the engine translates, with each entry's
    `_original`, at their own paths; the reader would walk every effect and
    trait otherwise."""
    from util.rpgmaker_qa_preflight import DATABASE_FIELDS, SYSTEM_FIELDS

    fields = (*DATABASE_FIELDS.get(name, ()), "_original")
    if isinstance(document, list):
        return [
            {key: entry[key] for key in fields if key in entry}
            if isinstance(entry, dict)
            else entry
            for entry in document
        ]
    if name == "System.json" and isinstance(document, dict):
        return {
            key: document[key]
            for key in (*SYSTEM_FIELDS, "_original")
            if key in document
        }
    return document


def _database(name: str, document: Any) -> list[Line]:
    found = []
    if name == _MAP_INFOS:
        entries = (
            document.items()
            if isinstance(document, dict)
            else enumerate(document)
            if isinstance(document, list)
            else ()
        )
        for key, entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                path = (key, "name")
                found.append(
                    Line(
                        "database field",
                        (path,),
                        (entry["name"],),
                        _entry_original(document, path),
                    )
                )
        return found
    for path, value, kind, _translated, source in _visible(
        name, _fields(name, document)
    ):
        if not isinstance(value, str) or kind not in ("database field", "system term"):
            continue
        if kind == "system term" and path[0] in _KEPT_SYSTEM:
            continue
        found.append(
            Line(kind, (path,), (value,), (source,) if source is not None else ())
        )
    return found


# Lines whose source no `_original` keeps.
_UNKEPT = frozenset({"map name", "label"})


def state(line: Line, notes: frozenset[str]) -> str | None:
    """Whether a line is "translated", "untranslated" or holds a refusal
    "note"; None when it is out of scope, and "unknown" for a translated map
    name or note label, whose source only the original game file has."""
    from util.source_text import holds_source, source_left

    # Notes are rare: only then do the lines' paths become pointers.
    if notes and any(_pointer(path) in notes for path in line.paths):
        return "note"
    if any(source_left(text, source) for text, source in line.sent()):
        return "untranslated"
    if any(holds_source(source) for source in line.sources):
        return "translated"
    if line.kind in _UNKEPT and any(text.strip() for text in line.texts):
        return "unknown"
    return None


def _original_labels(original: Any) -> dict[tuple, list[str]]:
    """The original game file's note labels, by the field holding them."""
    found: dict[tuple, list[str]] = {}
    for line in _labels(original):
        found.setdefault(line.paths[0], []).append(line.texts[0])
    return found


def _pointer(path: tuple) -> str:
    from util.rpgmaker_qa_preflight import pointer

    return pointer(path)


def note_pointers(document: Any, original: Callable[[], Any]) -> frozenset[str]:
    """The pointers of every value holding a refusal note with a known source;
    a pointer reads a list position the same whether a path names it as a
    number or, as System.json's `_original` does, as text."""
    from .saved_refusals import find

    return frozenset(
        _pointer(path) for note in find(document, original) for path in note.paths
    )


def may_hold_notes(raw: bytes, original_blob: str | None) -> bool:
    """Whether a file's bytes can hold a refusal note an earlier run saved
    (saved_refusals). Without an `_original`, a note is a value that differs
    from the original game file's at its path: a file without a known
    original, or byte for byte its original's (the Git blob `original_blob`),
    holds none."""
    # An escaped key could spell `_original` too.
    if b'"_original"' in raw or b"\\u" in raw:
        return True
    if original_blob is None:
        return False
    if not isinstance(original_blob, str) or len(original_blob) not in (40, 64):
        return True
    import hashlib

    blob = hashlib.new("sha1" if len(original_blob) == 40 else "sha256")
    blob.update(b"blob %d\0" % len(raw))
    blob.update(raw)
    return blob.hexdigest() != original_blob


# Raise when count() or read_counts() return other counts for the same bytes
# and inputs, such as after a change to what counts as a line or as
# translated: the counts the profile keeps (translation/derived) are then read
# again. What counts as a refusal note is refusals.RULES_VERSION, which their
# section names too (`counts_section`).
COUNT_VERSION = 1


def counts_section() -> str:
    """The derived store section of the counts read_counts() gives."""
    return f"lines/{COUNT_VERSION}.{refusals.RULES_VERSION}"


def read_counts(
    name: str,
    raw: bytes,
    phase: str,
    markers: frozenset[str],
    original_blob: str | None = None,
    original: Callable[[], Any] = lambda: None,
) -> dict[str, Any] | None:
    """count() of a file's bytes, None when they hold no game data it reads;
    `original_blob` is the original game file's Git blob, when known, and
    `original` reads its document."""
    from .files import decode_json

    try:
        return count(
            name,
            decode_json(raw),
            phase,
            markers,
            original,
            look_for_notes=may_hold_notes(raw, original_blob),
        )
    except ValueError:
        return None
    except AttributeError, IndexError, KeyError, TypeError:
        # Data shaped unlike RPG Maker's, such as a comment whose parameters
        # are an object, has no lines to count.
        return None


def count(
    name: str,
    document: Any,
    phase: str,
    markers: frozenset[str],
    original: Callable[[], Any] = lambda: None,
    *,
    look_for_notes: bool = True,
) -> dict[str, Any]:
    """A file's line counts: lines in scope, those translated, those holding
    a refusal note and the choice help left; `otherNotes` counts refusal notes
    in a Maps & events file's values outside these lines, such as Other event
    text (a database file counts them as lines left), and `mapName`
    is a translated map display name whose source decides its scope.
    `look_for_notes` false skips looking for notes in a file that holds
    none (may_hold_notes())."""
    from util.source_text import holds_source

    notes = note_pointers(document, original) if look_for_notes else frozenset()
    counted: set[str] = set()
    result: dict[str, Any] = {"lines": 0, "translated": 0}
    sources: dict[tuple, list[str]] | None = None
    taken: dict[tuple, int] = {}
    for line in lines(name, document, phase, markers):
        if notes:
            counted.update(map(_pointer, line.paths))
        found = state(line, notes)
        if found == "unknown" and line.kind == "map name":
            result["mapName"] = line.texts[0]
            continue
        at = 0
        if line.kind == "label":
            at = taken[line.paths[0]] = taken.get(line.paths[0], -1) + 1
        if found == "unknown":
            # A finished label is a line when the original's label in the
            # same place held Japanese.
            if sources is None:
                sources = _original_labels(original())
            theirs = sources.get(line.paths[0], [])
            found = (
                "translated" if at < len(theirs) and holds_source(theirs[at]) else None
            )
        if found is None:
            continue
        result["lines"] += 1
        if found == "translated":
            result["translated"] += 1
        elif found == "note":
            result["notes"] = result.get("notes", 0) + 1
        elif line.kind == "help":
            result["help"] = result.get("help", 0) + 1
    if other := len(notes - counted):
        if phase == "database":
            # The database pass translates note tags too: a note there is
            # one more line left.
            result["lines"] += other
            result["notes"] = result.get("notes", 0) + other
        else:
            result["otherNotes"] = other
    return result


def left(
    name: str,
    document: Any,
    phase: str,
    markers: frozenset[str],
    original: Callable[[], Any] = lambda: None,
) -> list[dict[str, str]]:
    """The lines still left in a file, with their location, text and why."""
    notes = note_pointers(document, original)
    rows = []
    for line in lines(name, document, phase, markers):
        found = state(line, notes)
        if found not in {"untranslated", "note"}:
            continue
        rows.append(
            {
                "location": _pointer(line.paths[0]),
                "text": "\n".join(text for text in line.texts if text),
                "source": line.shown_source(),
                "reason": "note"
                if found == "note"
                else "help"
                if line.kind == "help"
                else "untranslated",
            }
        )
    return rows
