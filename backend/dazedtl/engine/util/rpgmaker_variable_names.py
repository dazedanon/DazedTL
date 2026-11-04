"""The game variable names an RPG Maker MV/MZ game's plugins draw.

System.json names each game variable (`variables`) for the editor, and the
engine never draws a name. Some plugins do: LL_VariableWindow labels its
window with the name of the variable its showWindow command names. Plugins
and scripts may also look a variable up by its name, so the database pass
translates only the names a plugin draws, never all of them.

A plugin draws the names of the variables its settings and its commands'
arguments name when its code reads `$dataSystem.variables` and its header
declares those settings and arguments `@type variable` (or `variable[]`).
A name stays as it is wherever code could look it up: where it appears in a
string of a loaded plugin's code or its settings, or in an event's script,
plugin command (util/rpgmaker_qa_reach `scripts`) or comment.

Guided's database pass (modules/rpgmakermvmz), its line counts
(translation/file_lines), Text QA's never-translated report
(util/rpgmaker_qa_preflight), the translation file and Assistant-led's
census all read the names this gives.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import PluginList, beside_data, data_plugins
from util.rpgmaker_qa_reach import event_commands, lex, scripts

# A plugin's code reading the variables' names.
_READS = re.compile(r"\$dataSystem\s*(?:\.\s*variables\b|\[\s*['\"]variables['\"]\s*\])")
# A plugin's header blocks (`/*:` and `/*:ja`), not its structs' (`/*~struct~`).
_HEADER = re.compile(r"/\*:[\w-]*\s(.*?)\*/", re.S)
_TAG = re.compile(r"^[\s*]*@(\w+)[ \t]*(\S*)", re.M)
_TYPES = frozenset({"variable", "variable[]"})
_EVENT_FILE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")
# Event commands whose text a plugin may read a variable's name from: a
# comment and its lines, and an MV plugin command.
_NAMING = frozenset({108, 408, 356})


class Drawing(NamedTuple):
    """What of a plugin names a variable it draws: its settings, and each
    command's arguments."""

    settings: frozenset[str]
    arguments: dict[str, frozenset[str]]


def drawing(source: str) -> Drawing | None:
    """What a plugin's file declares names a variable it draws, or None when
    its code draws no variable name."""
    if not _READS.search(source):
        return None
    settings: set[str] = set()
    arguments: dict[str, set[str]] = {}
    for header in _HEADER.findall(source):
        command = owner = None
        for tag, value in _TAG.findall(header):
            if tag == "command":
                command, owner = value or None, None
            elif tag == "param":
                owner = (None, value) if value else None
            elif tag == "arg":
                owner = (command, value) if command and value else None
            elif tag == "type" and owner and value in _TYPES:
                at, name = owner
                if at is None:
                    settings.add(name)
                else:
                    arguments.setdefault(at, set()).add(name)
    if not settings and not arguments:
        return None
    return Drawing(
        frozenset(settings),
        {command: frozenset(names) for command, names in arguments.items()},
    )


def _ids(value: Any) -> set[int]:
    """The variable ids a setting or argument holds: one, or a list as JSON
    text."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                return set()
        else:
            value = text
    if isinstance(value, list):
        return set().union(*(_ids(item) for item in value)) if value else set()
    try:
        number = int(value)
    except TypeError, ValueError:
        return set()
    return {number} if number > 0 else set()


def drawn(
    plugins: PluginList,
    source: Callable[[str], str | None],
    files: Sequence[tuple[str, Callable[[], str | None]]],
    system: Any,
) -> frozenset[int]:
    """The ids of the variables whose names in *system* (System.json) the
    loaded *plugins* draw and no code could look up, from each plugin's file
    by its name (*source*, None when unreadable) and the game's event files
    (*files*: each name with a reader of its text, None when unreadable). A
    game whose plugins draw no names has none of its event files read."""
    names = variable_names(system)
    loaded = [entry for entry in plugins.loaded() if isinstance(entry.get("name"), str)]
    sources = {entry["name"]: source(entry["name"]) or "" for entry in loaded}
    drawings = {
        name: found
        for name, text in sources.items()
        if (found := drawing(text)) is not None
    }
    if not names or not drawings:
        return frozenset()
    ids: set[int] = set()
    # What code could look a name up by: plugins' string literals, outside
    # their help, and settings.
    looked: list[str] = [
        literal for text in sources.values() for literal in lex(text)[1]
    ]
    for entry in loaded:
        parameters = entry.get("parameters")
        if not isinstance(parameters, dict):
            continue
        looked += [value for value in parameters.values() if isinstance(value, str)]
        found = drawings.get(entry["name"])
        if found is not None:
            for setting in found.settings:
                ids |= _ids(parameters.get(setting))
    events = [(name, read) for name, read in files if _EVENT_FILE.fullmatch(name)]
    # Event files hold a plugin's name as the game writes it, or escaped.
    calls = [
        json.dumps(name, ensure_ascii=ascii)
        for name in drawings
        for ascii in (False, True)
    ]
    for _name, document in _documents(events, lambda text: any(call in text for call in calls)):
        for command in event_commands(document):
            parameters = command["parameters"]
            if blocks.code(command) != 357 or len(parameters) < 4:
                continue
            found = drawings.get(parameters[0])
            arguments = parameters[3]
            if found is None or not isinstance(arguments, dict):
                continue
            for argument in found.arguments.get(parameters[1], ()):
                ids |= _ids(arguments.get(argument))
    ids = {
        id
        for id in ids
        if id < len(names) and isinstance(names[id], str) and names[id].strip()
    }
    # Only files that hold a drawn name can look it up.
    wanted = {
        form
        for id in ids
        for form in (names[id], json.dumps(names[id])[1:-1])
    }
    for _name, document in _documents(events, lambda text: any(name in text for name in wanted)):
        for command in event_commands(document):
            looked += [value for value in scripts(command) if isinstance(value, str)]
            if blocks.code(command) in _NAMING:
                looked += [
                    value for value in command["parameters"] if isinstance(value, str)
                ]
    text = "\n".join(looked)
    return frozenset(id for id in ids if names[id] not in text)


def _documents(files, holds: Callable[[str], bool]) -> Iterator[tuple[str, Any]]:
    """The event files whose text *holds* says to read, parsed."""
    for name, read in files:
        text = read()
        if not text or not holds(text):
            continue
        try:
            yield name, json.loads(text)
        except ValueError:
            continue


def _signature(paths: Iterable[Path]) -> tuple:
    found = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            continue
        found.append((path.name, info.st_mtime_ns, info.st_size))
    return tuple(found)


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError, UnicodeDecodeError:
        return None


class _Plugins(NamedTuple):
    """A game's loaded plugins and their files' text, by plugin name, and
    whether any of them draws a variable name."""

    plugins: PluginList
    sources: dict[str, str | None]
    draws: bool


# Each game's plugins, by data folder and its plugin list's and plugin files'
# stat signatures, and the drawn ids, by those and its event files'.
_PLUGINS: dict[tuple, _Plugins] = {}
_DRAWN: dict[tuple, frozenset[int]] = {}


def _plugins(data: Path) -> tuple[tuple, _Plugins]:
    script = beside_data(data)
    js = script.parent / "plugins"
    listed = (str(data), _signature([script]))
    known = next((found for key, found in _PLUGINS.items() if key[:2] == listed), None)
    plugins = known.plugins if known else data_plugins(data)
    names = [entry["name"] for entry in plugins.loaded() if isinstance(entry.get("name"), str)]
    key = (*listed, _signature(js / f"{name}.js" for name in names))
    found = _PLUGINS.get(key)
    if found is None:
        sources = {name: _text(js / f"{name}.js") for name in names}
        found = _Plugins(
            plugins,
            sources,
            any(drawing(text) for text in sources.values() if text),
        )
        if len(_PLUGINS) >= 16:
            _PLUGINS.clear()
        _PLUGINS[key] = found
    return key, found


def data_drawn(data_folder: str | Path) -> frozenset[int]:
    """The ids of the variable names the game whose data folder this is
    draws (:func:`drawn`), read from its files; kept until one changes. A
    game whose plugins draw none has no event file looked at."""
    data = Path(data_folder)
    plugins_key, plugins = _plugins(data)
    if not plugins.draws:
        return frozenset()
    files = sorted(
        path for path in data.glob("*.json") if _EVENT_FILE.fullmatch(path.name)
    )
    key = (*plugins_key, _signature([data / "System.json", *files]))
    found = _DRAWN.get(key)
    if found is None:
        try:
            system = json.loads(_text(data / "System.json") or "null")
        except ValueError:
            system = None
        found = drawn(
            plugins.plugins,
            plugins.sources.get,
            [(path.name, lambda path=path: _text(path)) for path in files],
            system,
        )
        if len(_DRAWN) >= 16:
            _DRAWN.clear()
        _DRAWN[key] = found
    return found


def game_drawn(game_root: str | Path) -> frozenset[int]:
    """:func:`data_drawn` for a game by its folder, whose data folder a
    deployed MV game keeps in www."""
    root = Path(game_root)
    for base in (root, root / "www"):
        if (base / "data/System.json").is_file():
            return data_drawn(base / "data")
    return frozenset()


def variable_names(system: Any) -> list:
    """System.json's variable names as the game shipped them: each from
    `_original` where a translation keeps it."""
    if not isinstance(system, dict) or not isinstance(system.get("variables"), list):
        return []
    names = list(system["variables"])
    original = system.get("_original")
    kept = original.get("variables") if isinstance(original, dict) else None
    if isinstance(kept, dict):
        for key, value in kept.items():
            if str(key).isdigit() and int(key) < len(names) and isinstance(value, str):
                names[int(key)] = value
    return names
