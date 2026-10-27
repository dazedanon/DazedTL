"""Shared RPG Maker markers that identify player-facing comment blocks."""

from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import Any, Iterable

SUPPORTED_CODE408_MARKERS = frozenset({"選択肢ヘルプ"})
# Plugin settings that list the comment (108) markers whose lines (408) the
# plugin shows players, such as MPP_ChoiceEX's choice help.
MARKER_SETTINGS = frozenset({"Choice Help Commands"})


def plugin_markers(entries: Iterable[Any]) -> frozenset[str]:
    """The comment markers turned-on plugins show the lines of, as their
    settings list them."""
    found = set()
    for plugin in entries:
        if not isinstance(plugin, dict) or plugin.get("status") is not True:
            continue
        parameters = plugin.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in MARKER_SETTINGS & parameters.keys():
            value = parameters[key]
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                continue
            if isinstance(value, list):
                found.update(
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                )
    return frozenset(found)


def comment_markers(entries: Iterable[Any]) -> frozenset[str]:
    """The markers whose comment lines players read in a game with these
    plugins."""
    return SUPPORTED_CODE408_MARKERS | plugin_markers(entries)


PLUGIN_LIST = "js/plugins.js"


def read_plugin_list(text: str) -> tuple[dict, ...]:
    """A plugin list's text as the game loads it, or none it can read. The
    one reader for what a game's plugins show."""
    from util.rpgmaker_plugin_registry import loaded_entries

    try:
        return loaded_entries(text)
    except ValueError:
        return ()


def plugin_list(script: str | Path) -> tuple[dict, ...]:
    """A plugin list (js/plugins.js) as the game loads it, or none it can
    read."""
    try:
        return read_plugin_list(Path(script).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return ()


def beside_data(data_folder: PurePath) -> PurePath:
    """Where the plugin list of the game whose data folder this is sits: in
    the js folder beside it, which the game loads with it."""
    return data_folder.parent / PLUGIN_LIST


def data_plugins(data_folder: str | Path) -> tuple[dict, ...]:
    """The plugin list of the game whose data folder this is."""
    return plugin_list(beside_data(Path(data_folder)))


def game_plugins(game_root: str | Path) -> tuple[dict, ...]:
    """A game's plugin list, or none it can read: beside its data folder,
    which a deployed MV game keeps in www."""
    root = Path(game_root)
    for base in (root, root / "www"):
        if (base / "data").is_dir() and (base / "js/plugins.js").is_file():
            return data_plugins(base / "data")
    for base in (root, root / "www"):
        if (base / "js/plugins.js").is_file():
            return plugin_list(base / "js/plugins.js")
    return ()
