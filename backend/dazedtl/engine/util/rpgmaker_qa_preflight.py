"""Preflight for RPG Maker translation QA: Japanese that was never translated.

The QA inventory holds only text the engine translated, which keeps its
Japanese in `_original`. This reports the rest that players may read: lines
and fields without `_original`, custom data files, and plugin parameters.
QA has no translation of these to review and never corrects them; they need
translation or a plugin task instead. Each file or plugin is one source, with
whether players can reach a custom file's or plugin's text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from util.rpgmaker_qa_reach import MAY_SHOW, Reach

_JAPANESE_RE = re.compile(r"[ぁ-ゔァ-ヴ一-龠々〆〤]")
_MAP_RE = re.compile(r"Map\d+\.json")
# Plugin parameters that hold code or an asset path rather than text.
_SCRIPT_RE = re.compile(r"\bthis\.|\$(?:game|data)[A-Z]|=>|\breturn\b|(?:^|[;\s])//")
_ASSET_PATH_RE = re.compile(r"^[^\s。、！？]+/[^\s。、！？]+$")
STANDARD_FILES = frozenset({
    "Actors.json", "Animations.json", "Armors.json", "Classes.json",
    "CommonEvents.json", "Enemies.json", "Items.json", "MapInfos.json",
    "Skills.json", "States.json", "System.json", "Tilesets.json", "Troops.json",
    "Weapons.json",
})
# Database fields players read, by file.
DATABASE_FIELDS = {
    "Actors.json": ("name", "nickname", "profile"),
    "Armors.json": ("name", "description"),
    "Classes.json": ("name",),
    "Enemies.json": ("name",),
    "Items.json": ("name", "description"),
    "Skills.json": ("name", "description", "message1", "message2"),
    "States.json": ("name", "message1", "message2", "message3", "message4"),
    "Weapons.json": ("name", "description"),
}
SYSTEM_FIELDS = (
    "gameTitle", "currencyUnit", "armorTypes", "elements", "equipTypes",
    "skillTypes", "weaponTypes", "terms",
)
# Event commands whose parameters players read: the parameter index, or None
# for every string parameter.
COMMAND_TEXT = {101: 4, 102: 0, 105: None, 320: 1, 324: 1, 325: 1, 401: 0, 405: 0}
SCHEMA = "rpgmaker-qa-preflight-v2"
# Texts each source lists; its count covers them all.
SOURCE_TEXT_LIMIT = 50
TEXT_LIMIT = 160
REASON = (
    "This Japanese was never translated, so QA had no translation to review "
    "and did not correct it. Translate what players can see in its own task."
)
# Sources by kind: game data without `_original`, custom data files and
# plugin settings.
_KINDS = {"untranslated": "data", "custom_data": "custom", "plugin_parameters": "plugin"}


def japanese(value: Any) -> bool:
    """Whether a value holds Japanese; ・ and ー alone do not count."""
    return isinstance(value, str) and bool(_JAPANESE_RE.search(value))


def _escape(part: object) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def pointer(parts: tuple) -> str:
    """A JSON pointer to a value from its path's parts."""
    return "/" + "/".join(_escape(part) for part in parts)


def _leaves(value: Any, path: tuple = ()):
    """Every string inside a value, decoding parameters stored as JSON text."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "[{":
            try:
                decoded = json.loads(stripped)
            except ValueError:
                decoded = None
            if isinstance(decoded, (list, dict)):
                yield from _leaves(decoded, path)
                return
        yield path, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, path + (index,))
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _leaves(value[key], path + (key,))


def _command_lists(document: Any, path: tuple = ()):
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


def _entry(rows: list, file: str, path: tuple, text: str, kind: str) -> None:
    rows.append({
        "file": file,
        "pointer": pointer(path),
        "kind": kind,
        "text": text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…",
    })


def visible_texts(name: str, document: Any):
    """Each text players read in one data file: its pointer's parts, its
    value, its kind and whether the engine translated it, keeping its
    Japanese in `_original`. Map names keep no `_original`."""
    for list_path, commands in _command_lists(document):
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            code = command.get("code")
            parameters = command.get("parameters")
            if code not in COMMAND_TEXT or not isinstance(parameters, list):
                continue
            translated = "_original" in command
            base = list_path + (index, "parameters")
            if code == 102 and parameters and isinstance(parameters[0], list):
                for choice, value in enumerate(parameters[0]):
                    yield base + (0, choice), value, "choice", translated
                continue
            position = COMMAND_TEXT[code]
            for at, value in enumerate(parameters):
                if position is None or at == position:
                    yield base + (at,), value, "event text", translated
    if _MAP_RE.fullmatch(name) and isinstance(document, dict):
        yield ("displayName",), document.get("displayName"), "map name", False
    for field in DATABASE_FIELDS.get(name, ()):
        for index, entry in enumerate(document if isinstance(document, list) else []):
            if isinstance(entry, dict):
                original = entry.get("_original")
                translated = isinstance(original, dict) and field in original
                yield (index, field), entry.get(field), "database field", translated
    if name == "System.json" and isinstance(document, dict):
        original = document.get("_original")
        for field in SYSTEM_FIELDS:
            translated = isinstance(original, dict) and field in original
            for path, value in _leaves(document.get(field), (field,)):
                yield path, value, "system term", translated


def _untranslated(name: str, document: Any, covered: set[str], rows: list) -> None:
    for path, value, kind, translated in visible_texts(name, document):
        if not translated and japanese(value) and pointer(path) not in covered:
            _entry(rows, name, path, value, kind)


def _plugin_entries(script: Path) -> list[Any]:
    """The game's plugin list in js/plugins.js, or none it can read."""
    try:
        text = script.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    match = re.search(r"\$plugins\s*=\s*(\[.*\])\s*;?\s*$", text, re.S)
    try:
        entries = json.loads(match.group(1)) if match else []
    except ValueError:
        return []
    return entries if isinstance(entries, list) else []


def preflight(data_root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Japanese that players may read and the QA inventory does not hold."""
    data = Path(data_root).expanduser().resolve()
    covered: dict[str, set[str]] = {}
    for record in manifest["records"]:
        covered.setdefault(record["file"], set()).update(record["live_pointers"])
    entries = _plugin_entries(data.parent / "js" / "plugins.js")
    reach = Reach(data, entries)
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in _KINDS}
    for path in sorted(data.glob("*.json"), key=lambda item: item.name):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if path.name in STANDARD_FILES or _MAP_RE.fullmatch(path.name):
            _untranslated(
                path.name, document, covered.get(path.name, set()), rows["untranslated"]
            )
            reach.scan(path.name, document)
        else:
            for pointer, value in _leaves(document):
                if japanese(value):
                    _entry(rows["custom_data"], path.name, pointer, value, "custom data")
    for plugin in entries:
        if not isinstance(plugin, dict) or plugin.get("status") is not True:
            continue
        for pointer, value in _leaves(plugin.get("parameters") or {}):
            if (
                japanese(value)
                and not _SCRIPT_RE.search(value)
                and not _ASSET_PATH_RE.match(value)
            ):
                _entry(
                    rows["plugin_parameters"], "js/plugins.js",
                    (str(plugin.get("name") or ""), *pointer), value,
                    "plugin parameter",
                )
    sources = _sources(rows, reach)
    return {
        "schema": SCHEMA,
        "counts": {name: len(rows[name]) for name in _KINDS},
        "may_show": sum(item["count"] for item in sources if may_show(item)),
        "sources": sources,
    }


def _sources(rows: dict[str, list[dict[str, Any]]], reach: Reach | None) -> list[dict]:
    """Rows by file, and plugin settings by plugin, those players may see
    first; without reach, sources say nothing of it."""
    sources: dict[tuple[str, str, str], dict[str, Any]] = {}
    for category, kind in _KINDS.items():
        for row in rows.get(category, []):
            plugin = _unescape(row["pointer"].split("/")[1]) if kind == "plugin" else ""
            source = sources.get((kind, row["file"], plugin))
            if source is None:
                source = sources[(kind, row["file"], plugin)] = {
                    "kind": kind,
                    "file": row["file"],
                    **({"plugin": plugin} if kind == "plugin" else {}),
                    "count": 0,
                }
                if reach and kind != "data":
                    source["reach"], source["evidence"] = (
                        reach.plugin(plugin) if kind == "plugin"
                        else reach.data_file(row["file"])
                    )
                source["texts"] = []
            source["count"] += 1
            if len(source["texts"]) < SOURCE_TEXT_LIMIT:
                source["texts"].append(
                    {key: row[key] for key in ("pointer", "kind", "text")}
                )
    kinds = list(_KINDS.values())
    return sorted(
        sources.values(),
        key=lambda item: (
            not may_show(item), kinds.index(item["kind"]),
            item["file"], item.get("plugin", ""),
        ),
    )


def _unescape(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def may_show(source: dict[str, Any]) -> bool:
    """Whether players may see a source's text: game data and whatever no
    evidence rules out."""
    return source.get("reach", "unknown") in MAY_SHOW


def read_sources(document: dict[str, Any]) -> list[dict[str, Any]]:
    """A preflight's sources. One prepared before sources listed its first
    texts by category, with no reach; those texts make its sources."""
    return document["sources"] if "sources" in document else _sources(document, None)
