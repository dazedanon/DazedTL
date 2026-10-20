"""The release playtest's static checks for an RPG Maker MV/MZ game.

They read the game's files the way it ships them and run none of its code:
whether it starts, Japanese players can read, battle messages and event pages
that lost a name or code their original shows, descriptions longer than the
help window, and Japanese strings in plugin code with the evidence for whether
they can show. Each problem names the task that fixes it; nothing here
changes the game.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from util.rpgmaker_plugin_registry import PluginRegistryError, plugin_entries
from util.rpgmaker_qa_checks import BATTLE_MESSAGES, battler_name_note, runtime
from util.rpgmaker_qa_preflight import (
    STANDARD_FILES,
    japanese,
    pointer,
    preflight,
    read_sources,
    visible_texts,
)
from util.rpgmaker_qa_reach import Reach
from util.runtime_text import without_control_codes

SCHEMA = "rpgmaker-playtest-static-v1"
TEXT_LIMIT = 160
# Texts a grouped problem lists; its count covers them all.
GROUP_TEXT_LIMIT = 20
# Lines the standard help window shows, in MV and MZ.
HELP_ROWS = 2
DESCRIBED_FILES = ("Items.json", "Weapons.json", "Armors.json", "Skills.json")
# Glyphs Japanese text uses for a hidden word, as in "Day ◯/30".
_PLACEHOLDER_RE = re.compile(r"[◯〇]|○○")
# Codes that put something on screen: a variable's value, an actor's or party
# member's name, an icon and the currency unit.
_SHOWN_CODE_RE = re.compile(r"\\([VNPI])\[(\d+)\]|\\(G)(?![A-Za-z\[])", re.IGNORECASE)
_PLACEHOLDER_NUMBER_RE = re.compile(r"%\d")
_MAP_RE = re.compile(r"Map\d+\.json")
_EVENT_FILE_RE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")
# Event commands whose text the page check reads; the 101 nameplate is its
# fifth parameter.
_PAGE_TEXT = {101: 4, 401: 0, 405: 0, 320: 1, 324: 1, 325: 1}
CODE_SCRIPT = Path(__file__).with_name("code.cjs")
# A plugin string's reach, from most to least likely to show.
LITERAL_REACH = ("drawn", "may-show", "disabled", "uncalled")


def _excerpt(text: Any) -> str:
    text = str(text)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def _problem(kind: str, check: str, file: str, note: str, fix: str, **detail) -> dict:
    return {"kind": kind, "check": check, "file": file, "note": note, "fix": fix} | {
        key: value for key, value in detail.items() if value not in (None, "")
    }


def _shown_codes(text: Any) -> Counter:
    if not isinstance(text, str):
        return Counter()
    return Counter(
        ("\\G" if match.group(3) else f"\\{match.group(1).upper()}[{match.group(2)}]")
        for match in _SHOWN_CODE_RE.finditer(text)
    )


def _original(entry: Any, *keys: Any) -> Any:
    """The `_original` an entry keeps for a field, read through the string keys
    it uses for list indices, or None."""
    value = entry.get("_original") if isinstance(entry, dict) else None
    for key in keys:
        if isinstance(value, dict):
            value = value.get(str(key))
        elif isinstance(value, list) and isinstance(key, int) and key < len(value):
            value = value[key]
        else:
            return None
    return value


def _command_lists(document: Any, path: tuple = ()):
    """Every event command list in a document, as an event page holds it."""
    if isinstance(document, list):
        if any(isinstance(item, dict) and "code" in item for item in document):
            yield path, document
            return
        for index, child in enumerate(document):
            yield from _command_lists(child, path + (index,))
    elif isinstance(document, dict):
        for key, child in document.items():
            if key != "_original":
                yield from _command_lists(child, path + (key,))


class _Checks:
    def __init__(self, game: Path, data: Path):
        self.game = game
        self.data = data
        self.prefix = data.relative_to(game).as_posix()
        self.engine = runtime(data)
        self.problems: list[dict[str, Any]] = []
        self.gaps: list[str] = []
        self.documents: dict[str, Any] = {}

    def path(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix != "." else name

    def add(self, *args, **detail) -> None:
        self.problems.append(_problem(*args, **detail))

    def starts(self) -> list[dict[str, Any]]:
        """Data files that parse, and every plugin js/plugins.js lists."""
        for path in sorted(self.data.glob("*.json"), key=lambda item: item.name):
            try:
                self.documents[path.name] = json.loads(path.read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError:
                self.add(
                    "crash", "json", self.path(path.name),
                    "The game can't read this data file: it is not UTF-8 text.", "game",
                )
            except ValueError as exc:
                self.add(
                    "crash", "json", self.path(path.name),
                    f"The game can't load this data file: {exc.msg} at line "
                    f"{exc.lineno}, column {exc.colno}.", "game", line=exc.lineno,
                    column=exc.colno,
                )
            except OSError as exc:
                self.gaps.append(f"{self.path(path.name)} could not be read: {exc.strerror}.")
        registry = self.data.parent / "js" / "plugins.js"
        if not registry.is_file():
            return []
        try:
            entries = plugin_entries(registry.read_text(encoding="utf-8-sig"))
        except (PluginRegistryError, ValueError, UnicodeDecodeError) as exc:
            self.add(
                "crash", "plugin-list", self._js("plugins.js"),
                f"The game can't read its plugin list: {exc}", "game",
            )
            return []
        return [
            entry for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        ]

    def _js(self, name: str) -> str:
        js = (self.data.parent / "js").relative_to(self.game).as_posix()
        return f"{js}/{name}" if js != "." else name

    def japanese(self) -> None:
        """Japanese left in translated text players read, and placeholder
        glyphs; text never translated comes from preflight."""
        for name, document in self.documents.items():
            if name not in STANDARD_FILES and not _MAP_RE.fullmatch(name):
                continue
            for parts, value, kind, translated in visible_texts(name, document):
                if not isinstance(value, str) or not translated:
                    continue
                location = pointer(parts)
                # A code's argument, such as the font of \fn[和風], is not
                # drawn; a name window's <名前> is.
                shown = without_control_codes(value)
                if japanese(shown):
                    note = "Japanese is left in this translated text."
                    check = "visible-text"
                elif _PLACEHOLDER_RE.search(shown):
                    note = (
                        "A Japanese placeholder glyph is left in this English text; "
                        "English readers take it for a missing character."
                    )
                    check = "placeholder-glyph"
                else:
                    continue
                self.add(
                    "japanese", check, self.path(name), note, "text-qa",
                    pointer=location, text=_excerpt(value), place=kind,
                    identity=f"{name}#{location}",
                )

    def untranslated(self, kept: Iterable[dict[str, Any]]) -> None:
        """Text never translated, by file or plugin, with its reach, but for
        plugin settings the plugin task keeps in Japanese on purpose."""
        found = preflight(self.data, {"records": []}, kept)
        for source in read_sources(found):
            kind = source["kind"]
            file = (
                self._js("plugins.js") if kind == "plugin" else self.path(source["file"])
            )
            self.add(
                "japanese", "untranslated", file,
                "This text was never translated."
                if kind == "data"
                else "A plugin shows this text, which was never translated."
                if kind == "plugin"
                else "A plugin reads this data file, whose text was never translated.",
                "translate" if kind == "data" else "plugin-files",
                plugin=source.get("plugin"), count=source["count"],
                reach=source.get("reach"), evidence=source.get("evidence"),
                texts=[
                    {"pointer": row["pointer"], "text": row["text"]}
                    for row in source["texts"][:GROUP_TEXT_LIMIT]
                ],
            )

    def codes(self) -> None:
        """Battle messages and terms that lost a %n or their battler's name,
        and event pages that lost a code their original shows."""
        for name, fields in BATTLE_MESSAGES.get(self.engine, {}).items():
            for index, entry in enumerate(self.documents.get(name) or []):
                if not isinstance(entry, dict):
                    continue
                for field in fields:
                    live = entry.get(field)
                    if not isinstance(live, str):
                        continue
                    source = _original(entry, field)
                    source = source if isinstance(source, str) else live
                    note = battler_name_note(self.engine, live, source)
                    if note:
                        # Text QA's review decides the fix; the reader needs
                        # only what goes wrong.
                        note = note.split("; a battler-name source fix", 1)[0]
                        note = note if note.endswith(".") else note + "."
                        self._code(name, (index, field), live, source, note, "battler-name")
        for name, fields in (
            ("Skills.json", ("message1", "message2")),
            ("States.json", ("message1", "message2", "message3", "message4")),
        ):
            for index, entry in enumerate(self.documents.get(name) or []):
                if isinstance(entry, dict):
                    for field in fields:
                        self._placeholders(name, (index, field), entry.get(field), _original(entry, field))
        system = self.documents.get("System.json")
        messages = (system or {}).get("terms", {}).get("messages") if isinstance(system, dict) else None
        if isinstance(messages, dict):
            for key, live in messages.items():
                self._placeholders(
                    "System.json", ("terms", "messages", key), live,
                    _original(system, "terms", "messages", key),
                )
        for name, document in self.documents.items():
            if _EVENT_FILE_RE.fullmatch(name):
                for path, commands in _command_lists(document):
                    self._page(name, path, commands)

    def _code(self, name, parts, live, source, note, check) -> None:
        location = pointer(parts)
        self.add(
            "codes", check, self.path(name), note, "text-qa", pointer=location,
            text=_excerpt(live), original=_excerpt(source), identity=f"{name}#{location}",
        )

    def _placeholders(self, name, parts, live, source) -> None:
        if not isinstance(live, str) or not isinstance(source, str):
            return
        lost = Counter(_PLACEHOLDER_NUMBER_RE.findall(source)) - Counter(
            _PLACEHOLDER_NUMBER_RE.findall(live)
        )
        if lost:
            codes = " and ".join(sorted(lost))
            self._code(
                name, parts, live, source,
                f"The original shows {codes} here, and this text does not, so "
                "that value never shows.", "placeholder",
            )

    def _page(self, name: str, path: tuple, commands: list) -> None:
        """Codes an event page's original shows and its text lost, counted
        over the page so a code a rewrap moved to another line is not lost."""
        before: Counter = Counter()
        after: Counter = Counter()
        first: dict[str, int] = {}
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            code, parameters = command.get("code"), command.get("parameters")
            if not isinstance(parameters, list):
                continue
            if code == 102 and parameters and isinstance(parameters[0], list):
                texts = parameters[0]
                originals = command.get("_original")
                originals = originals if isinstance(originals, list) else None
            elif code in _PAGE_TEXT and len(parameters) > _PAGE_TEXT[code]:
                texts = [parameters[_PAGE_TEXT[code]]]
                originals = [command["_original"]] if "_original" in command else None
            else:
                continue
            for at, text in enumerate(texts):
                shown = _shown_codes(text)
                after += shown
                if originals is not None and at < len(originals):
                    original = _shown_codes(originals[at])
                elif japanese(text):
                    # Never translated: it is its own original.
                    original = shown
                else:
                    # English the engine added beside a translated line.
                    original = Counter()
                before += original
                for value in original:
                    first.setdefault(value, index)
        lost = before - after
        if not lost:
            return
        codes = sorted(lost)
        command = min(first[value] for value in codes)
        location = pointer(path + (command,))
        self.add(
            "codes", "event-codes", self.path(name),
            f"The original of this page shows {' and '.join(codes)}, which its "
            "English dropped, so that name, value or icon never shows.",
            "text-qa", pointer=location, codes=codes,
            text=_excerpt(_page_text(commands[command])),
            identity=f"{name}#{location}",
        )

    def descriptions(self) -> None:
        """Descriptions with more lines than the standard help window shows,
        for the tour to look at: a plugin may draw the help its own way or
        give the window more lines."""
        for name in DESCRIBED_FILES:
            for index, entry in enumerate(self.documents.get(name) or []):
                text = entry.get("description") if isinstance(entry, dict) else None
                if not isinstance(text, str) or not text.strip():
                    continue
                rows = len(text.rstrip("\n").split("\n"))
                if rows > HELP_ROWS:
                    location = pointer((index, "description"))
                    self.add(
                        "fit", "help-rows", self.path(name),
                        f"This description has {rows} lines, and the standard help "
                        f"window shows {HELP_ROWS}, so the rest is cut off.",
                        "text-qa", pointer=location, text=_excerpt(text), rows=rows,
                        identity=f"{name}#{location}",
                    )

    def plugin_code(self, plugins: list[dict[str, Any]], reach: Reach) -> None:
        """Plugins that do not compile, and Japanese strings in their code."""
        if not plugins:
            return
        node = shutil.which("node")
        acorn = _acorn()
        if not node or not acorn:
            self.gaps.append(
                "Plugin code was not checked: it needs the app's Node runtime "
                "and Acorn parser."
            )
            return
        js = self.data.parent / "js"
        core = sorted(js.glob("rmmz_*.js")) or sorted(js.glob("rpg_*.js"))
        request = {
            "acorn": str(acorn),
            "core": [str(path) for path in core],
            "tokens": sorted(reach.script_names()),
            "plugins": [
                {
                    "name": entry["name"],
                    "file": str(js / "plugins" / f"{entry['name']}.js"),
                    "parameters": entry.get("parameters") or {},
                    "commands": sorted(reach.commands(entry["name"])),
                }
                for entry in plugins
            ],
        }
        try:
            response = subprocess.run(
                [node, str(CODE_SCRIPT)],
                input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                capture_output=True,
                timeout=120 + 5 * len(plugins),
                check=False,
            )
            results = json.loads(response.stdout) if not response.returncode else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            results = None
        if not isinstance(results, list):
            self.gaps.append("Plugin code was not checked: the code reader failed.")
            return
        for result in results:
            name = result["name"]
            file = self._js(f"plugins/{name}.js")
            if "missing" in result:
                self.add(
                    "crash", "plugin-missing", file,
                    f"The plugin list turns on {name}, whose file is missing, so the "
                    "game stops at its error screen when it starts.", "game",
                    plugin=name,
                )
            elif "issue" in result:
                issue = result["issue"]
                self.add(
                    "crash", "plugin-syntax", file,
                    f"This plugin does not compile: {issue['message']}. The game "
                    "stops at its error screen when it loads it.", "game",
                    plugin=name, line=issue["line"], column=issue["column"],
                    text=issue["code"],
                )
            elif "unreadable" in result:
                self.gaps.append(
                    f"{file} compiles, but its Japanese strings were not read: "
                    f"{result['unreadable']}."
                )
            elif result["literals"]:
                self._literals(name, file, result["literals"], reach)

    def _literals(self, name, file, literals, reach: Reach) -> None:
        """One problem a plugin for its Japanese strings and one for its
        placeholder glyphs, each listing its strings with their reach."""
        state, evidence = reach.plugin(name)
        groups: dict[bool, list[dict[str, Any]]] = {}
        for literal in literals:
            # A plugin nothing runs shows none of its strings.
            if state == "uncalled":
                literal = {**literal, "reach": "uncalled", "evidence": evidence}
            groups.setdefault(bool(literal.pop("glyph", False)), []).append(literal)
        for glyph, texts in sorted(groups.items()):
            reaches = Counter(text["reach"] for text in texts)
            self.add(
                "japanese", "placeholder-glyph" if glyph else "plugin-text", file,
                "A Japanese placeholder glyph is left in this plugin's English text."
                if glyph else "Japanese is left in this plugin's code.",
                "plugin-files", plugin=name, count=len(texts),
                reach=next(value for value in LITERAL_REACH if reaches[value]),
                reaches=dict(reaches), texts=texts,
            )


def _page_text(command: dict[str, Any]) -> str:
    parameters = command.get("parameters") or []
    code = command.get("code")
    if code == 102 and parameters and isinstance(parameters[0], list):
        return " / ".join(str(value) for value in parameters[0])
    position = _PAGE_TEXT.get(code, 0)
    return str(parameters[position]) if len(parameters) > position else ""


def _acorn() -> Path | None:
    """The app's Acorn package, beside the engine in DazedTL's checkout."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "app" / "node_modules" / "acorn"
        if (candidate / "package.json").is_file():
            return candidate
    return None


def static_checks(
    game_root: str | Path,
    data_root: str | Path,
    kept: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Every static problem in a game, with what the checks could not read.
    File paths are relative to the game folder; *kept* names the plugin
    settings the plugin task keeps in Japanese on purpose."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if game not in data.parents:
        raise ValueError("The data folder must be inside the game folder.")
    checks = _Checks(game, data)
    entries = checks.starts()
    reach = Reach(data, entries)
    for name, document in checks.documents.items():
        reach.scan(name, document)
    checks.japanese()
    checks.untranslated(kept)
    checks.codes()
    checks.descriptions()
    checks.plugin_code(
        [entry for entry in entries if entry.get("status") is True], reach
    )
    return {
        "schema": SCHEMA,
        "engine": checks.engine,
        "problems": checks.problems,
        "gaps": checks.gaps,
    }
