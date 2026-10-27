"""Whether players can reach a plugin's text, read from the game's own files.

Text QA reports Japanese that was never translated. For plugin settings and
the custom data files plugins read, this says what runs the plugin: an event
calling its commands, an event script or another running plugin using what it
defines, or the plugin changing the game's screens itself. It reads code as
text and follows no data flow, so each state is the evidence it found; a
plugin nothing calls can show text only through code this cannot follow.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import PluginList

# Something runs the plugin, or its file could not be read, so players may
# see its text.
MAY_SHOW = frozenset({"called", "runs", "unknown"})
# A custom file takes the first of its readers' states in this order.
_PRECEDENCE = ("called", "runs", "unknown", "uncalled")
# Engine objects a plugin may change without putting text on a screen:
# loading, settings, saving, assets and input.
_SETUP_OWNERS = frozenset({
    "AudioManager", "ConfigManager", "DataManager", "EffectManager",
    "FontManager", "Graphics", "ImageManager", "Input", "JsonEx",
    "PluginManager", "Scene_Boot", "StorageManager", "TouchInput", "Utils",
})
# Without the engine's own scripts, a change to anything named like these
# counts as changing a screen.
_ENGINE_NAME_RE = re.compile(
    r"^(?:Scene|Window|Sprite|Spriteset|Game)_|^(?:Bitmap|Sprite|Window)$|Manager$"
)
_CLASS_NAME_RE = re.compile(r"^(?:Scene|Window|Sprite|Spriteset|Game)_\w+$")
_DEFINITION_RE = re.compile(
    r"^[ \t]*(?:function\s*([A-Za-z_$][\w$]*)\s*\(|class\s+([A-Za-z_$][\w$]*))", re.M
)
_MEMBER_RE = re.compile(
    r"(?<![\w$.])([A-Z][\w$]*)\.(prototype\.)?([A-Za-z_$][\w$]*)\s*=(?![=>])"
)
_GLOBAL_RE = re.compile(
    r"(?<![\w$.])(?:window|globalThis)\.([A-Za-z_$][\w$]*)\s*=(?![=>])"
)
# The engine's globals, such as `$gameMessage = null;` or `var $dataActors`.
_VARIABLE_RE = re.compile(r"^(?:(?:var|let|const)\s+)?([A-Za-z_$][\w$]*)\s*=(?![=>])", re.M)
# Other ways to change an engine object: Object.assign(Window_Base.prototype,
# ...), Object.defineProperty(...) and Window_Base.prototype["name"] = ....
_PATCH_RE = re.compile(
    r"Object\.(?:assign|defineProperty|defineProperties)\(\s*([A-Z][\w$]*)\b"
    r"|(?<![\w$.])([A-Z][\w$]*)(?:\.prototype)?\[[^\]]+\]\s*=(?![=>])"
)
# Code that puts its own elements or dialogs on the game's page; reading
# document.currentScript, as plugins do to learn their name, is not.
_PAGE = "page"
_PAGE_RE = re.compile(
    r"(?<![\w$.])(?:document\s*\.\s*(?:body|createElement|getElement|querySelector|write)"
    r"|alert\s*\(|confirm\s*\(|prompt\s*\()"
)
_COMMAND_RE = re.compile(r"^\s*\*?\s*@command\s+(\S+)", re.M)
_REGISTER_RE = re.compile(r"registerCommand\s*\(\s*[^,()]+,\s*(['\"`])([^'\"`]+)\1")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][\w$]*")
_WORD_RE = re.compile(r"[\w.:-]+")
# Names shorter than this are too common to tie a use to one plugin.
_NAME_MINIMUM = 4
_EVENT_FILE_RE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")


def _lex(source: str) -> tuple[str, list[str]]:
    """Code without its comments, and its string literals."""
    code: list[str] = []
    strings: list[str] = []
    start = index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if source.startswith("//", index) or source.startswith("/*", index):
            line = source[index + 1] == "/"
            end = source.find("\n" if line else "*/", index + 2)
            end = length if end < 0 else end + (0 if line else 2)
            code.append(source[start:index] + " ")
            start = index = end
        elif char in "'\"`":
            end = index + 1
            while end < length and source[end] != char:
                if source[end] == "\\":
                    end += 1
                elif source[end] == "\n" and char != "`":
                    break
                end += 1
            strings.append(source[index + 1 : end])
            index = end + 1
        else:
            index += 1
    code.append(source[start:])
    return "".join(code), strings


def _leaves(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _leaves(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _leaves(child)


class _Core:
    """What the engine's own scripts define, to tell a plugin's changes to
    them from what it adds."""

    def __init__(self) -> None:
        self.owners: set[str] = set()
        self.members: set[tuple[str, bool, str]] = set()
        self.names: set[str] = set()


def _core(js: Path) -> _Core:
    core = _Core()
    for path in sorted(js.glob("rmmz_*.js")) or sorted(js.glob("rpg_*.js")):
        try:
            code, _strings = _lex(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            continue
        core.owners.update(
            one or two for one, two in _DEFINITION_RE.findall(code)
        )
        core.names.update(_VARIABLE_RE.findall(code))
        for owner, prototype, name in _MEMBER_RE.findall(code):
            core.members.add((owner, bool(prototype), name))
            core.names.add(name)
    return core


class _Plugin:
    def __init__(self, name: str, enabled: bool) -> None:
        self.name = name
        # Whether the game loads it, and why not.
        self.enabled = enabled
        self.unloaded = "It is turned off in js/plugins.js."
        self.readable = False
        self.commands: list[str] = []
        # Words MV-style plugin commands may start with.
        self.words: set[str] = set()
        # Engine objects it changes in ways that can show text.
        self.changes: set[str] = set()
        # Names it adds for other code to use.
        self.defines: set[str] = set()
        self.settings: list[str] = []
        # What its code and settings use.
        self.tokens: set[str] = set()
        self.strings: list[str] = []

    @property
    def names(self) -> set[str]:
        """How other code names the plugin itself, as in
        PluginManager.parameters("Name")."""
        return {
            name for name in (self.name, PurePosixPath(self.name).name)
            if len(name) >= _NAME_MINIMUM
        }


def _plugin(js: Path, entry: dict[str, Any], loaded: bool, core: _Core) -> _Plugin:
    plugin = _Plugin(entry["name"], loaded)
    if not loaded and entry.get("status") is True:
        plugin.unloaded = "Another entry of it in js/plugins.js loads instead."
    plugin.settings = list(_leaves(entry.get("parameters") or {}))
    plugin.strings = list(plugin.settings)
    for value in plugin.settings:
        plugin.tokens.update(_IDENTIFIER_RE.findall(value))
    try:
        source = (js / "plugins" / f"{entry['name']}.js").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return plugin
    plugin.readable = True
    code, strings = _lex(source)
    plugin.strings += strings
    plugin.tokens.update(_IDENTIFIER_RE.findall(code))
    for string in strings:
        plugin.tokens.update(_IDENTIFIER_RE.findall(string))
    plugin.commands = list(dict.fromkeys(
        _COMMAND_RE.findall(source) + [name for _quote, name in _REGISTER_RE.findall(code)]
    ))
    own = {one or two for one, two in _DEFINITION_RE.findall(code)}
    for owner, prototype, name in _MEMBER_RE.findall(code):
        if owner in own and owner not in core.owners:
            continue
        if not core.owners:
            if _ENGINE_NAME_RE.search(owner) and owner not in _SETUP_OWNERS:
                plugin.changes.add(owner)
        elif owner not in core.owners:
            continue
        elif (owner, bool(prototype), name) in core.members or name in core.names:
            if owner == "Game_Interpreter" and name == "pluginCommand":
                plugin.words = {
                    value.casefold() for value in strings if _WORD_RE.fullmatch(value)
                }
            elif owner not in _SETUP_OWNERS:
                plugin.changes.add(owner)
        else:
            plugin.defines.add(name)
    for first, second in _PATCH_RE.findall(code):
        owner = first or second
        if owner not in _SETUP_OWNERS and (
            owner in core.owners
            or not core.owners and owner not in own and _ENGINE_NAME_RE.search(owner)
        ):
            plugin.changes.add(owner)
    if _PAGE_RE.search(code):
        plugin.changes.add(_PAGE)
    plugin.defines.update(_GLOBAL_RE.findall(code))
    plugin.defines.update(name for name in own if _CLASS_NAME_RE.match(name))
    plugin.defines = {
        name for name in plugin.defines
        if len(name) >= _NAME_MINIMUM
        and name not in core.names
        and name not in core.owners
    }
    return plugin


def _script(command: dict[str, Any]) -> list[str]:
    """The script an event command runs: Script, a Conditional Branch or
    Control Variables script, a movement route's Script, or a plugin
    command's arguments."""
    code, parameters = command["code"], command["parameters"]
    if code in (355, 655):
        return parameters[:1]
    if code == 111 and parameters[:1] == [12]:
        return parameters[1:2]
    if code == 122 and len(parameters) > 4 and parameters[3] == 4:
        return parameters[4:5]
    if code == 205 and len(parameters) > 1 and isinstance(parameters[1], dict):
        return [
            step["parameters"][0]
            for step in parameters[1].get("list") or []
            if isinstance(step, dict) and step.get("code") == 45
            and isinstance(step.get("parameters"), list) and step["parameters"]
        ]
    if code == 357:
        return list(_leaves(parameters[3:]))
    return []


def _commands(document: Any):
    if isinstance(document, list):
        for child in document:
            yield from _commands(child)
    elif isinstance(document, dict):
        if blocks.code(document) is not None and isinstance(
            document.get("parameters"), list
        ):
            yield document
        for key, child in document.items():
            if key != "_original":
                yield from _commands(child)


class Reach:
    """Each plugin's and custom data file's reach in one game. Scan its event
    files, then ask; the answer is a state and the evidence for it."""

    def __init__(self, data_root: str | Path, plugins: PluginList):
        self._js = Path(data_root).parent / "js"
        # Each plugin by name: the entry the game loads, or else its first
        # entry, which the game does not load.
        self._entries: dict[str, tuple[dict[str, Any], bool]] = {
            entry["name"]: (entry, True) for entry in plugins.loaded()
        }
        for entry in plugins:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                self._entries.setdefault(entry["name"], (entry, False))
        # MZ plugin commands by plugin: the count and the first one's
        # command and file.
        self._calls: dict[str, list] = {}
        # Every command events call, by plugin.
        self._called: dict[str, set[str]] = {}
        # MV plugin commands by their first word: the count and first file.
        self._words: dict[str, list] = {}
        # Names event scripts use, with the first file.
        self._scripts: dict[str, str] = {}
        self._states: dict[str, tuple[str, str]] | None = None
        self._plugins: dict[str, _Plugin] = {}

    def scan(self, name: str, document: Any) -> None:
        """Record the plugin commands and script one event file holds."""
        if not _EVENT_FILE_RE.fullmatch(name):
            return
        for command in _commands(document):
            parameters = command["parameters"]
            if command["code"] == 357 and len(parameters) > 1 and all(
                isinstance(value, str) for value in parameters[:2]
            ):
                row = self._calls.setdefault(parameters[0], [0, parameters[1], name])
                row[0] += 1
                self._called.setdefault(parameters[0], set()).add(parameters[1])
            elif command["code"] == 356 and parameters and isinstance(parameters[0], str):
                words = parameters[0].split()
                if words:
                    self._words.setdefault(words[0].casefold(), [0, name])[0] += 1
            for value in _script(command):
                if isinstance(value, str):
                    for token in _IDENTIFIER_RE.findall(value):
                        self._scripts.setdefault(token, name)

    def commands(self, name: str) -> set[str]:
        """The commands of an MZ plugin that events call."""
        return set(self._called.get(name, ()))

    def script_names(self) -> set[str]:
        """Every name an event script uses."""
        return set(self._scripts)

    def plugin(self, name: str) -> tuple[str, str]:
        """The reach of a turned-on plugin's settings."""
        return self._resolve().get(
            name, ("unknown", "It is not listed in js/plugins.js.")
        )

    def data_file(self, name: str) -> tuple[str, str]:
        """The reach of a custom data file: its readers' best."""
        self._resolve()
        stem = PurePosixPath(name).stem
        readers = [
            plugin for plugin in self._plugins.values()
            if any(name in value for value in plugin.strings)
            or stem in plugin.settings
        ]
        running = [plugin.name for plugin in readers if plugin.enabled]
        if not running:
            off = [plugin.name for plugin in readers]
            return "unread", "No turned-on plugin names this file." + (
                f" Only {_join(off)}, turned off, names it." if off else ""
            )
        best = min(
            running,
            key=lambda reader: _PRECEDENCE.index(self._states[reader][0]),
        )
        state, evidence = self._states[best]
        evidence = evidence[0].lower() + evidence[1:]
        if len(running) == 1:
            return state, f"Read by {best}: {evidence}"
        return state, f"Read by {_join(running)}; {best}: {evidence}"

    def _resolve(self) -> dict[str, tuple[str, str]]:
        if self._states is not None:
            return self._states
        core = _core(self._js)
        self._plugins = {
            name: _plugin(self._js, entry, loaded, core)
            for name, (entry, loaded) in self._entries.items()
        }
        running = [
            plugin for plugin in self._plugins.values()
            if plugin.enabled and plugin.readable
        ]
        # A name two plugins define is shared, so it ties a use to neither.
        defined: dict[str, int] = {}
        for plugin in running:
            for name in plugin.defines:
                defined[name] = defined.get(name, 0) + 1
        for plugin in running:
            plugin.defines = {name for name in plugin.defines if defined[name] == 1}
        states: dict[str, tuple[str, str]] = {}
        for plugin in self._plugins.values():
            if not plugin.enabled:
                states[plugin.name] = ("off", plugin.unloaded)
            elif not plugin.readable:
                states[plugin.name] = (
                    "unknown", f"Its file js/plugins/{plugin.name}.js could not be read."
                )
            elif called := self._called_by_events(plugin):
                states[plugin.name] = ("called", called)
        active = [
            plugin for plugin in running
            if plugin.name in states or plugin.changes
        ]
        # A plugin a running plugin uses runs too, and may run others.
        changed = True
        while changed:
            changed = False
            for plugin in running:
                if plugin.name in states:
                    continue
                for user in active:
                    used = sorted(
                        (user.tokens & plugin.defines)
                        | (set(user.strings) & plugin.names)
                    )
                    if used and user is not plugin:
                        states[plugin.name] = (
                            "called", f"The {user.name} plugin uses {used[0]}."
                        )
                        if plugin not in active:
                            active.append(plugin)
                        changed = True
                        break
        for plugin in running:
            if plugin.name in states:
                continue
            if plugin.changes:
                owners = sorted(plugin.changes - {_PAGE})
                changes = [
                    "changes " + _join(owners[:3] + (
                        [f"{len(owners) - 3} more"] if len(owners) > 3 else []
                    )) + " itself"
                ] if owners else []
                if _PAGE in plugin.changes:
                    changes.append("adds its own elements to the game's page")
                states[plugin.name] = (
                    "runs",
                    f"It {' and '.join(changes)}, so it can show text without being called.",
                )
            else:
                commands = (
                    f"its commands ({', '.join(plugin.commands)})"
                    if plugin.commands else "it"
                )
                states[plugin.name] = (
                    "uncalled",
                    f"No event calls {commands}, no event script or running plugin "
                    "uses it, and it changes no game screen itself.",
                )
        self._states = states
        return states

    def _called_by_events(self, plugin: _Plugin) -> str:
        count, command, place = self._calls.get(plugin.name, [0, "", ""])
        for word in sorted(plugin.words & set(self._words)):
            seen, file = self._words[word]
            if not count:
                command, place = word, file
            count += seen
        if count:
            more = count - 1
            return f"Events call its command {command} in {place}" + (
                f" and {more:,} more {'time' if more == 1 else 'times'}." if more else "."
            )
        used = sorted(
            name for name in plugin.defines | plugin.names if name in self._scripts
        )
        if used:
            return f"An event script in {self._scripts[used[0]]} uses {used[0]}."
        return ""


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
