"""The game variable names an RPG Maker MV/MZ game's plugins draw.

System.json names each game variable (`variables`) for the editor, and the
engine never draws a name. Some plugins do: LL_VariableWindow labels its
window with the name of the variable its showWindow command names. Plugins
and scripts may also look a variable up by its name, so the database pass
translates only the names a plugin draws, never all of them.

A plugin draws the names of the variables its settings and its commands'
arguments name when its code, outside its help, reads `$dataSystem.variables`
and its header declares those settings and arguments `@type variable` (or
`variable[]`), directly or as a field of a `struct<>` they hold.
A name stays as it is wherever code could look it up: where it is a whole
string of a loaded plugin's code or settings, an argument or word of an
event's plugin command, or a note tag's value (`<Tag:name>`) in a data file's
notes or an event's comment, or where it is quoted in a plugin's code or
settings or an event's script (util/rpgmaker_qa_reach `scripts`).

Guided's database pass (modules/rpgmakermvmz), its line counts
(translation/file_lines), Text QA's never-translated report
(util/rpgmaker_qa_preflight), the Final check (util/playtest/checks), the
translation file and Assistant-led's census all read the names this gives.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import PluginList, beside_data, data_plugins, game_data
from util.rpgmaker_qa_reach import event_commands, lex, scripts

# A plugin's code reading the variables' names.
_READS = re.compile(r"\$dataSystem\s*(?:\.\s*variables\b|\[\s*['\"]variables['\"]\s*\])")
# A plugin's header blocks (`/*:` and `/*:ja`) and its structs' (`/*~struct~Name:`).
_HEADER = re.compile(r"/\*(?::[\w-]*|~struct~(\w+):[\w-]*)\s(.*?)\*/", re.S)
_TAG = re.compile(r"^[\s*]*@(\w+)[ \t]*([^\n]*)", re.M)
_STRUCT = re.compile(r"struct<(\w+)>")
_VARIABLE = "variable"
# What separates the words of an MV plugin command, as in `SetVar name,5`
# or `ShowVar "name"`.
_WORDS = re.compile(r"[\s,=:;'\"`]+")
# A note tag's value, as in `<GaugeVar:name>`.
_NOTE_TAG = re.compile(r"<[^<>:\n]+:([^<>\n]+)>")
# Comment commands, whose tags some plugins read.
_COMMENTS = frozenset({108, 408})


class Drawing(NamedTuple):
    """What of a plugin names a variable it draws, each with its declared
    type: its settings, each command's arguments, and its structs' fields."""

    settings: dict[str, str]
    arguments: dict[str, dict[str, str]]
    structs: dict[str, dict[str, str]]


def _carries(kind: str, structs: dict[str, dict[str, str]], seen=frozenset()) -> bool:
    """Whether a value of this declared type can name a variable."""
    kind = kind.removesuffix("[]")
    if kind == _VARIABLE:
        return True
    found = _STRUCT.fullmatch(kind)
    if found is None or found[1] in seen:
        return False
    return any(
        _carries(field, structs, seen | {found[1]})
        for field in structs.get(found[1], {}).values()
    )


# About one game's plugins, whose text _PLUGINS keeps too.
@lru_cache(maxsize=256)
def drawing(source: str) -> Drawing | None:
    """What a plugin's file declares names a variable it draws, or None when
    its code, outside its help, draws no variable name."""
    if not _READS.search(lex(source)[0]):
        return None
    settings: dict[str, str] = {}
    arguments: dict[str, dict[str, str]] = {}
    structs: dict[str, dict[str, str]] = {}
    for struct, header in _HEADER.findall(source):
        command = owner = None
        for tag, value in _TAG.findall(header):
            value = value.strip()
            if tag == "command" and not struct:
                command, owner = value.split()[0] if value else None, None
            elif tag == "param" and value:
                owner = (structs.setdefault(struct, {}) if struct else settings, value)
            elif tag == "arg":
                owner = (
                    (arguments.setdefault(command, {}), value)
                    if command and value and not struct
                    else None
                )
            elif tag == "type" and owner:
                owner[0][owner[1]] = value
                owner = None
    settings = {name: kind for name, kind in settings.items() if _carries(kind, structs)}
    arguments = {
        command: carried
        for command, declared in arguments.items()
        if (carried := {name: kind for name, kind in declared.items() if _carries(kind, structs)})
    }
    if not settings and not arguments:
        return None
    return Drawing(settings, arguments, structs)


def _ids(value: Any, kind: str, structs: dict[str, dict[str, str]], depth=0) -> set[int]:
    """The variable ids a setting or argument of this declared type holds:
    one, a list, or a struct's fields, any of them as JSON text."""
    if depth > 8:
        return set()
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            value = json.loads(value)
        except ValueError:
            return set()
    if isinstance(value, list):
        item = kind.removesuffix("[]")
        return set().union(set(), *(_ids(each, item, structs, depth + 1) for each in value))
    struct = _STRUCT.fullmatch(kind)
    if struct is not None:
        if not isinstance(value, dict):
            return set()
        return set().union(
            set(),
            *(
                _ids(value.get(field), declared, structs, depth + 1)
                for field, declared in structs.get(struct[1], {}).items()
            ),
        )
    if kind.removesuffix("[]") != _VARIABLE or isinstance(value, bool):
        return set()
    try:
        number = int(str(value).strip())
    except ValueError:
        return set()
    return {number} if number > 0 else set()


def _leaves(value: Any) -> Iterator[str]:
    """Every string in a plugin's settings or command arguments, those they
    hold as JSON text included."""
    if isinstance(value, str):
        yield value.strip()
        if value.strip()[:1] in ("[", "{"):
            try:
                yield from _leaves(json.loads(value))
            except ValueError:
                pass
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)


def _notes(document: Any) -> Iterator[str]:
    """Every note a data file holds: its entries', a map's and its events'."""
    if isinstance(document, list):
        for item in document:
            yield from _notes(item)
    elif isinstance(document, dict):
        for key, value in document.items():
            if key == "note" and isinstance(value, str):
                yield value
            elif key != "_original" and isinstance(value, (list, dict)):
                yield from _notes(value)


def _tags(text: str) -> set[str]:
    return {value.strip() for value in _NOTE_TAG.findall(text)}


class Facts(NamedTuple):
    """What one data file tells of variable names: the MZ plugin commands
    its events call, as (plugin, command, arguments), the whole values code
    could look a name up by, and its events' scripts."""

    calls: tuple[tuple[str, str, dict], ...]
    values: frozenset[str]
    scripts: tuple[str, ...]


def facts(name: str, document: Any) -> Facts:
    """The facts of one data file, by its name."""
    calls: list[tuple[str, str, dict]] = []
    values: set[str] = set()
    code: list[str] = []
    if blocks.EVENT_FILE.fullmatch(name):
        for command in event_commands(document):
            parameters = command["parameters"]
            kind = blocks.code(command)
            texts = [value for value in scripts(command) if isinstance(value, str)]
            first = parameters[0] if parameters else None
            if kind == 357:
                if (
                    len(parameters) >= 4
                    and isinstance(parameters[0], str)
                    and isinstance(parameters[1], str)
                    and isinstance(parameters[3], dict)
                ):
                    calls.append((parameters[0], parameters[1], parameters[3]))
                values.update(leaf for text in texts for leaf in _leaves(text))
            elif kind == 356 and isinstance(first, str):
                values.update(_WORDS.split(first))
            elif kind in _COMMENTS and isinstance(first, str):
                values |= _tags(first)
            else:
                code += texts
    for note in _notes(document):
        values |= _tags(note)
    return Facts(tuple(calls), frozenset(values - {""}), tuple(code))


def read_facts(name: str, text: str | None) -> Facts | None:
    """The facts of a data file's text, None when it holds no JSON."""
    try:
        return facts(name, json.loads(text)) if text else None
    except ValueError:
        return None


# About one game's plugins, whose text _PLUGINS keeps too.
@lru_cache(maxsize=256)
def _literals(source: str) -> tuple[str, ...]:
    return tuple(lex(source)[1])


def drawn(
    plugins: PluginList,
    source: Callable[[str], str | None],
    files: Callable[[], Iterable[Facts]],
    system: Any,
) -> frozenset[int]:
    """The ids of the variables whose names in *system* (System.json) the
    loaded *plugins* draw and no code could look up, from each plugin's file
    by its name (*source*, None when unreadable) and the facts of the game's
    other data files, which *files* gives only for a game whose plugins draw
    a name."""
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
    # What code could look a name up by: whole values, and code holding it
    # quoted.
    values: set[str] = set()
    code: list[str] = []
    for text in sources.values():
        literals = _literals(text)
        values.update(literal.strip() for literal in literals)
        code += literals
    for entry in loaded:
        parameters = entry.get("parameters")
        if not isinstance(parameters, dict):
            continue
        leaves = list(_leaves(parameters))
        values.update(leaves)
        code += leaves
        found = drawings.get(entry["name"])
        if found is not None:
            for setting, kind in found.settings.items():
                ids |= _ids(parameters.get(setting), kind, found.structs)
    for fact in files():
        for plugin, command, arguments in fact.calls:
            found = drawings.get(plugin)
            if found is None:
                continue
            for argument, kind in found.arguments.get(command, {}).items():
                ids |= _ids(arguments.get(argument), kind, found.structs)
        values |= fact.values
        code += fact.scripts
    script = "\n".join(code)
    return frozenset(
        id
        for id in ids
        if id < len(names)
        and isinstance(names[id], str)
        and names[id].strip()
        and names[id] not in values
        and names[id].strip() not in values
        and not any(f"{mark}{names[id]}{mark}" in script for mark in "'\"`")
    )


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


# Each game's plugin list, by data folder and the list's stat signature; its
# plugins, by those and its plugin files' signatures; each data file's facts,
# by its path and signature; and the drawn ids, by the plugins' key and the
# data files' signatures. Each is only read and written whole, so threads may
# share them.
_LISTS: dict[tuple, PluginList] = {}
_PLUGINS: dict[tuple, _Plugins] = {}
_FACTS: dict[tuple, Facts | None] = {}
_DRAWN: dict[tuple, frozenset[int]] = {}


def _keep(cache: dict, key: tuple, value: Any, limit: int = 16) -> Any:
    if len(cache) >= limit:
        cache.clear()
    cache[key] = value
    return value


def _plugins(data: Path) -> tuple[tuple, _Plugins]:
    script = beside_data(data)
    js = script.parent / "plugins"
    listed = (str(data), _signature([script]))
    plugins = _LISTS.get(listed)
    if plugins is None:
        plugins = _keep(_LISTS, listed, data_plugins(data))
    names = [entry["name"] for entry in plugins.loaded() if isinstance(entry.get("name"), str)]
    key = (*listed, _signature(js / f"{name}.js" for name in names))
    found = _PLUGINS.get(key)
    if found is None:
        sources = {name: _text(js / f"{name}.js") for name in names}
        found = _keep(
            _PLUGINS,
            key,
            _Plugins(
                plugins,
                sources,
                any(drawing(text) for text in sources.values() if text),
            ),
        )
    return key, found


def _file_facts(path: Path, signature: tuple) -> Facts | None:
    key = (str(path), signature)
    if key in _FACTS:
        return _FACTS[key]
    return _keep(_FACTS, key, read_facts(path.name, _text(path)), 8192)


def data_drawn(data_folder: str | Path) -> frozenset[int]:
    """The ids of the variable names the game whose data folder this is
    draws (:func:`drawn`), read from its files; kept until one changes, and
    each file's facts until it does. A game whose plugins draw none has no
    data file looked at."""
    data = Path(data_folder)
    plugins_key, plugins = _plugins(data)
    if not plugins.draws:
        return frozenset()
    system = data / "System.json"
    files = sorted(path for path in data.glob("*.json") if path != system)
    signatures = _signature([system, *files])
    key = (*plugins_key, signatures)
    found = _DRAWN.get(key)
    if found is None:
        stats = {name: signature for name, *signature in signatures}

        def every():
            for path in files:
                fact = _file_facts(path, tuple(stats.get(path.name, ())))
                if fact is not None:
                    yield fact

        try:
            document = json.loads(_text(system) or "null")
        except ValueError:
            document = None
        found = _keep(
            _DRAWN, key, drawn(plugins.plugins, plugins.sources.get, every, document)
        )
    return found


def game_drawn(game_root: str | Path) -> frozenset[int]:
    """:func:`data_drawn` for a game by its folder (rpgmaker_markers
    `game_data`)."""
    data = game_data(game_root)
    return data_drawn(data) if data is not None else frozenset()


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
