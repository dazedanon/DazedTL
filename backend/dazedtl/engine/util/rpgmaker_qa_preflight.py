"""Preflight for RPG Maker translation QA: Japanese text QA cannot correct.

The QA inventory holds only text the engine translated, which keeps its
Japanese in `_original`. This reports the rest that players may read: lines
and fields without `_original`, custom data files, and plugin parameters.
QA never corrects these; they need translation or a plugin task instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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
SAMPLE_LIMIT = 200
TEXT_LIMIT = 160


def _japanese(value: Any) -> bool:
    return isinstance(value, str) and bool(_JAPANESE_RE.search(value))


def _escape(part: object) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


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


def _entry(rows: list, file: str, pointer: tuple, text: str, kind: str) -> None:
    rows.append({
        "file": file,
        "pointer": "/" + "/".join(_escape(part) for part in pointer),
        "kind": kind,
        "text": text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…",
    })


def _untranslated(name: str, document: Any, covered: set[str], rows: list) -> None:
    def add(pointer: tuple, value: Any, kind: str) -> None:
        if _japanese(value):
            text = "/" + "/".join(_escape(part) for part in pointer)
            if text not in covered:
                _entry(rows, name, pointer, value, kind)

    for list_path, commands in _command_lists(document):
        for index, command in enumerate(commands):
            if not isinstance(command, dict) or "_original" in command:
                continue
            code = command.get("code")
            parameters = command.get("parameters")
            if code not in COMMAND_TEXT or not isinstance(parameters, list):
                continue
            base = list_path + (index, "parameters")
            if code == 102 and parameters and isinstance(parameters[0], list):
                for choice, value in enumerate(parameters[0]):
                    add(base + (0, choice), value, "choice")
                continue
            position = COMMAND_TEXT[code]
            for at, value in enumerate(parameters):
                if position is None or at == position:
                    add(base + (at,), value, "event text")
    if _MAP_RE.fullmatch(name) and isinstance(document, dict):
        add(("displayName",), document.get("displayName"), "map name")
    for field in DATABASE_FIELDS.get(name, ()):
        for index, entry in enumerate(document if isinstance(document, list) else []):
            if isinstance(entry, dict) and not isinstance(entry.get("_original"), dict):
                add((index, field), entry.get(field), "database field")
            elif isinstance(entry, dict) and field not in entry["_original"]:
                add((index, field), entry.get(field), "database field")
    if name == "System.json" and isinstance(document, dict):
        for field in SYSTEM_FIELDS:
            original = document.get("_original")
            if isinstance(original, dict) and field in original:
                continue
            for path, value in _leaves(document.get(field), (field,)):
                add(path, value, "system term")


def preflight(data_root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Japanese that players may read and the QA inventory does not hold."""
    data = Path(data_root).expanduser().resolve()
    covered: dict[str, set[str]] = {}
    for record in manifest["records"]:
        covered.setdefault(record["file"], set()).update(record["live_pointers"])
    untranslated: list[dict[str, Any]] = []
    custom: list[dict[str, Any]] = []
    for path in sorted(data.glob("*.json"), key=lambda item: item.name):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if path.name in STANDARD_FILES or _MAP_RE.fullmatch(path.name):
            _untranslated(path.name, document, covered.get(path.name, set()), untranslated)
        else:
            for pointer, value in _leaves(document):
                if _japanese(value):
                    _entry(custom, path.name, pointer, value, "custom data")
    plugins: list[dict[str, Any]] = []
    script = data.parent / "js" / "plugins.js"
    if script.is_file():
        text = script.read_text(encoding="utf-8-sig")
        match = re.search(r"\$plugins\s*=\s*(\[.*\])\s*;?\s*$", text, re.S)
        try:
            entries = json.loads(match.group(1)) if match else []
        except ValueError:
            entries = []
        for plugin in entries if isinstance(entries, list) else []:
            if not isinstance(plugin, dict) or plugin.get("status") is not True:
                continue
            for pointer, value in _leaves(plugin.get("parameters") or {}):
                if (
                    _japanese(value)
                    and not _SCRIPT_RE.search(value)
                    and not _ASSET_PATH_RE.match(value)
                ):
                    _entry(
                        plugins, "js/plugins.js",
                        (str(plugin.get("name") or ""), *pointer), value,
                        "plugin parameter",
                    )
    return {
        "schema": "rpgmaker-qa-preflight-v1",
        "counts": {
            "untranslated": len(untranslated),
            "custom_data": len(custom),
            "plugin_parameters": len(plugins),
        },
        "untranslated": untranslated[:SAMPLE_LIMIT],
        "custom_data": custom[:SAMPLE_LIMIT],
        "plugin_parameters": plugins[:SAMPLE_LIMIT],
    }
