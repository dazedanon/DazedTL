"""How much of a game data file is translated, read from the file itself.

Guided's Database files and Maps & events count each file's lines in its
newest copy, so the count is right whichever runs wrote it, and a file reads
finished only when nothing in it is left for the engine to send. Text QA's
never-translated report lists the text players read (util/rpgmaker_qa_preflight
`visible_texts`); this groups it into the lines a person reads: one message (a
101's name box with its 401 rows), scrolling text block (405 rows), choice of
a 102, choice help block (a 108 marker's 408 rows, with Comment text on), map
display name, database field and system term, and leaves out what another
task translates or no task does.

A line is in scope when its source holds Japanese: the source the engine keeps
in `_original`, else the text itself. The engine sends a value while it holds
Japanese, whatever `_original` says, so a line is translated when no part of
it holds Japanese letters outside control-code arguments (of a name box, the
name the engine translates), unless it holds a refusal note an earlier run
saved in place of a translation (`saved_refusals`). A translated map display
name keeps no `_original`, so whether it had Japanese takes the original game
file. The engine probe (tests/fixtures/engine_runtime.py) checks the two agree.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

# Japanese letters still to translate: the engine's own range
# (rpgmakermvmz LANGREGEX) without its punctuation and brackets. A
# translation keeps 【Name】 labels, which the engine reads as names and never
# sends again; the engine probe checks the two ranges agree on every letter.
_JAPANESE = re.compile(
    r"[\u3005-\u3007\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF"
    r"\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]"
)
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


# A control code's argument, such as \SA[びっくり], names a plugin's asset or
# setting: it is never text to translate.
_CODE_ARGUMENT = re.compile(r"\\+[A-Za-z]+\[[^\]\n]*\]")


def japanese(value: Any) -> bool:
    """Whether a value still holds Japanese letters outside control codes."""
    return isinstance(value, str) and bool(
        _JAPANESE.search(_CODE_ARGUMENT.sub("", value))
    )


class Line(NamedTuple):
    """One line a person reads: its kind, the paths of its values, their
    text, and the Japanese source the engine keeps for them."""

    kind: str
    paths: tuple[tuple, ...]
    texts: tuple[str, ...]
    sources: tuple[str, ...]


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


def _system_original(document: Any, path: tuple) -> tuple[str, ...]:
    """A system term's source in System.json's root `_original`, which keys
    list positions as text."""
    value = document.get("_original") if isinstance(document, dict) else None
    for part in path:
        if not isinstance(value, dict):
            return ()
        value = value.get(str(part) if isinstance(part, int) else part)
    return (value,) if isinstance(value, str) else ()


def _visible(
    name: str, document: Any, markers: frozenset[str] = frozenset()
) -> Iterator[tuple[tuple[Any, ...], Any, str, bool]]:
    """Text QA's reader (a QA engine source, read unchanged so its tasks'
    fingerprint holds): each text's path, value, kind and `_original` flag."""
    from util.rpgmaker_qa_preflight import visible_texts

    yield from visible_texts(name, document, markers)


def lines(
    name: str, document: Any, phase: str, markers: frozenset[str] = frozenset()
) -> list[Line]:
    """Each line of a phase's scope ("database" or "dialogue") in one data
    file, in file order, whether or not it is in scope. Choice help counts
    under *markers*, the comment markers Comment text translates; none while
    it is off."""
    if phase == "database":
        return _database(name, document)
    found: list[Line] = []
    if not (_MAP.fullmatch(name) or name in {"CommonEvents.json", "Troops.json"}):
        return found
    readable = _events(name, document)
    # The open message, scrolling text or help block: its kind, command list
    # and the position of its last command.
    group: tuple[str, tuple, int] | None = None
    for path, value, kind, _translated in _visible(name, readable, markers):
        if kind == "map name":
            if isinstance(value, str):
                found.append(Line(kind, (path,), (value,), ()))
            continue
        if kind == "choice":
            command = _resolve(readable, path[:-3])
            original = command.get("_original")
            source = (
                (original[path[-1]],)
                if isinstance(original, list)
                and path[-1] < len(original)
                and isinstance(original[path[-1]], str)
                else ()
            )
            found.append(Line(kind, (path,), (str(value),), source))
            group = None
            continue
        listed, index = path[:-3], path[-3]
        command = _resolve(readable, path[:-2])
        code = command.get("code")
        if kind == "comment text":
            unit = "help"
        elif code in (101, 401):
            unit = "message"
        elif code == 405:
            unit = "scroll"
        else:
            # Actor names and profiles are Other event text; a scrolling
            # text's own command holds none.
            continue
        commands = _resolve(readable, listed)
        joined = (
            group is not None
            and group[0] == unit
            and group[1] == listed
            and code != 101
            and all(
                isinstance(between, dict) and between.get("code") == -1
                for between in commands[group[2] + 1 : index]
            )
        )
        text = value if isinstance(value, str) else ""
        sources = _command_original(command)
        if code == 101:
            text, sources = speaker_name(text), tuple(map(speaker_name, sources))
        if joined:
            last = found[-1]
            found[-1] = last._replace(
                paths=last.paths + (path,),
                texts=last.texts + (text,),
                sources=last.sources + sources,
            )
        else:
            found.append(Line(unit, (path,), (text,), sources))
        group = (unit, listed, index)
    return found


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
    for path, value, kind, _translated in _visible(name, _fields(name, document)):
        if kind == "database field" and isinstance(value, str):
            source = _entry_original(document, path)
        elif kind == "system term" and isinstance(value, str):
            if path[0] in _KEPT_SYSTEM:
                continue
            source = _system_original(document, path)
        else:
            continue
        found.append(Line(kind, (path,), (value,), source))
    return found


def state(line: Line, notes: frozenset[str]) -> str | None:
    """Whether a line is "translated", "untranslated" or holds a refusal
    "note"; None when it is out of scope, and "unknown" for a translated map
    name, whose source only the original game file has."""
    # Notes are rare: only then do the lines' paths become pointers.
    if notes and any(_pointer(path) in notes for path in line.paths):
        return "note"
    if any(japanese(text) for text in line.texts):
        return "untranslated"
    if any(japanese(source) for source in line.sources):
        return "translated"
    if line.kind == "map name" and any(text.strip() for text in line.texts):
        return "unknown"
    return None


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


def count(
    name: str,
    document: Any,
    phase: str,
    markers: frozenset[str],
    original: Callable[[], Any] = lambda: None,
) -> dict[str, Any]:
    """A file's line counts: lines in scope, those translated, those holding
    a refusal note and the choice help left; `otherNotes` counts refusal notes
    in values outside these lines, such as Other event text, and `mapName`
    is a translated map display name whose source decides its scope."""
    notes = note_pointers(document, original)
    counted: set[str] = set()
    result: dict[str, Any] = {"lines": 0, "translated": 0}
    for line in lines(name, document, phase, markers):
        if notes:
            counted.update(map(_pointer, line.paths))
        found = state(line, notes)
        if found == "unknown":
            result["mapName"] = line.texts[0]
            continue
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
                "source": "\n".join(line.sources),
                "reason": "note"
                if found == "note"
                else "help"
                if line.kind == "help"
                else "untranslated",
            }
        )
    return rows
