"""Preflight for RPG Maker translation QA: Japanese that was never translated.

The QA inventory holds only text the engine translated, which keeps its
Japanese in `_original`. This reports the rest that players may read: lines
and fields without `_original`, custom data files, and plugin parameters.
QA has no translation of these to review and never corrects them; they need
translation or a plugin task instead. Plugin settings the plugin task keeps in
Japanese on purpose, such as lookup keys, are not reported. Each file or
plugin is one source, with whether players can reach a custom file's or
plugin's text. The report records every plugin setting it read, so it can
follow the plugin task's later decisions without reading the game again.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from util import rpgmaker_blocks as blocks
from util.rpgmaker_markers import (
    MARKER_SETTINGS,
    SUPPORTED_CODE408_MARKERS,
    comment_markers,
    data_plugins,
)
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


def _entry(rows: list, file: str, path: tuple, text: str, kind: str) -> None:
    rows.append({
        "file": file,
        "pointer": pointer(path),
        "kind": kind,
        "text": text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…",
    })


def visible_texts(
    name: str, document: Any, markers: frozenset[str] = SUPPORTED_CODE408_MARKERS
):
    """Each text players read in one data file: its pointer's parts, its
    value, its kind and whether the engine translated it, keeping its
    Japanese in `_original`. Map names keep no `_original`.

    A message's or comment's rows count as translated where a translation
    owns them (see rpgmaker_blocks.owned). Comment lines (408) count under
    the *markers* the game's plugins show, such as a choice's help."""
    for list_path, commands in blocks.command_lists(document):
        translated_rows: set[int] = set()
        comment_rows: set[int] = set()
        for block in blocks.blocks(commands):
            for part in block.parts:
                if part.translated:
                    translated_rows.update(part.commands)
            if block.kind in (blocks.HELP, blocks.COMMENT) and block.shown(markers):
                comment_rows.update(block.rows)
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            code = command.get("code")
            parameters = command.get("parameters")
            if code == 408:
                if index in comment_rows and parameters:
                    base = list_path + (index, "parameters", 0)
                    yield base, parameters[0], "comment text", index in translated_rows
                continue
            if code not in COMMAND_TEXT or not isinstance(parameters, list):
                continue
            translated = (
                index in translated_rows if code in (401, 405) else "_original" in command
            )
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


def _untranslated(
    name: str, document: Any, covered: set[str], markers: frozenset[str], rows: list
) -> None:
    for path, value, kind, translated in visible_texts(name, document, markers):
        if not translated and japanese(value) and pointer(path) not in covered:
            _entry(rows, name, path, value, kind)


def _text(value: str) -> str:
    """A setting's text as the plugin task reads it: plugin editors store some
    settings, such as multi-line text, as JSON strings."""
    while True:
        try:
            inner = json.loads(value)
        except ValueError:
            return value
        if not isinstance(inner, str):
            return value
        value = inner


def _settings(entries: list[Any]) -> list[tuple[tuple, str]]:
    """Each turned-on plugin's Japanese settings that may be text players
    read, rather than code, an asset path or the comment markers it looks
    for, by where they are."""
    found = []
    for plugin in entries:
        if not isinstance(plugin, dict) or plugin.get("status") is not True:
            continue
        for parts, value in _leaves(plugin.get("parameters") or {}):
            if (
                parts[0] not in MARKER_SETTINGS
                and japanese(value)
                and not _SCRIPT_RE.search(value)
                and not _ASSET_PATH_RE.match(value)
            ):
                found.append(((str(plugin.get("name") or ""), *parts), value))
    return found


def kept_digest(kept: Iterable[dict[str, Any]]) -> str:
    """The kept settings' digest, whatever their order."""
    rows = sorted(
        json.dumps(
            [setting["plugin"], [*setting["path"]], setting["value"]],
            ensure_ascii=False,
        )
        for setting in kept
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def preflight(
    data_root: str | Path,
    manifest: dict[str, Any],
    kept: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Japanese that players may read and the QA inventory does not hold.

    *kept* names the plugin settings the plugin task keeps in Japanese on
    purpose, each by plugin, parameter path and the value it decided on; a
    setting is left out while it still holds that value.
    """
    data = Path(data_root).expanduser().resolve()
    covered: dict[str, set[str]] = {}
    for record in manifest["records"]:
        covered.setdefault(record["file"], set()).update(record["live_pointers"])
    entries = list(data_plugins(data))
    reach = Reach(data, entries)
    markers = comment_markers(entries)
    rows: dict[str, list[dict[str, Any]]] = {"untranslated": [], "custom_data": []}
    for path in sorted(data.glob("*.json"), key=lambda item: item.name):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if path.name in STANDARD_FILES or _MAP_RE.fullmatch(path.name):
            _untranslated(
                path.name,
                document,
                covered.get(path.name, set()),
                markers,
                rows["untranslated"],
            )
            reach.scan(path.name, document)
        else:
            for parts, value in _leaves(document):
                if japanese(value):
                    _entry(rows["custom_data"], path.name, parts, value, "custom data")
    settings = _settings(entries)
    plugins = {
        "reach": {
            name: list(reach.plugin(name))
            for name in sorted({location[0] for location, _value in settings})
        },
        "settings": [[list(location), value] for location, value in settings],
    }
    return _report(
        {name: len(found) for name, found in rows.items()},
        _sources(rows, lambda _kind, file, _plugin: reach.data_file(file)),
        plugins,
        kept,
    )


def with_kept(
    document: dict[str, Any], kept: Iterable[dict[str, Any]]
) -> dict[str, Any] | None:
    """A report again for the plugin settings the plugin task keeps now, from
    the settings it recorded, or None for one from before it recorded them."""
    if "plugins" not in document:
        return None
    others = [source for source in document["sources"] if source["kind"] != "plugin"]
    return _report(document["counts"], others, document["plugins"], kept)


def _report(
    counts: dict[str, int],
    others: list[dict[str, Any]],
    plugins: dict[str, Any],
    kept: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """The report from its data and custom file sources and the plugin
    settings it read, leaving out those the plugin task keeps."""
    kept = list(kept)
    decided = {
        (pointer((setting["plugin"], *setting["path"])), setting["value"])
        for setting in kept
    }
    rows: list[dict[str, Any]] = []
    left = 0
    for location, value in plugins["settings"]:
        if (pointer(location), _text(value)) in decided:
            left += 1
            continue
        _entry(rows, "js/plugins.js", location, value, "plugin parameter")
    reached = plugins["reach"]
    sources = _ordered(
        others
        + _sources(
            {"plugin_parameters": rows},
            lambda _kind, _file, plugin: tuple(reached[plugin]),
        )
    )
    return {
        "schema": SCHEMA,
        "counts": {**counts, "plugin_parameters": len(rows)},
        # Plugin settings left out because the plugin task keeps them, and
        # the decisions they were left out by.
        "kept": left,
        "kept_sha256": kept_digest(kept),
        "may_show": sum(item["count"] for item in sources if may_show(item)),
        "sources": sources,
        "plugins": plugins,
    }


def _sources(
    rows: dict[str, list[dict[str, Any]]],
    reach: Callable[[str, str, str], tuple[str, str]] | None,
) -> list[dict]:
    """Rows by file, and plugin settings by plugin, those players may see
    first; *reach* gives a custom file's or plugin's reach and evidence from
    its kind, file and plugin, and without it sources say nothing of it."""
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
                    source["reach"], source["evidence"] = reach(
                        kind, row["file"], plugin
                    )
                source["texts"] = []
            source["count"] += 1
            if len(source["texts"]) < SOURCE_TEXT_LIMIT:
                source["texts"].append(
                    {key: row[key] for key in ("pointer", "kind", "text")}
                )
    return _ordered(list(sources.values()))


def _ordered(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kinds = list(_KINDS.values())
    return sorted(
        sources,
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
