"""Shared RPG Maker markers that identify player-facing comment blocks."""

from __future__ import annotations

import json
from pathlib import Path
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


def game_plugins(game_root: str | Path) -> tuple[dict, ...]:
    """A game's plugin list, or none it can read."""
    from util.rpgmaker_plugin_registry import plugin_entries

    root = Path(game_root)
    for path in (root / "js/plugins.js", root / "www/js/plugins.js"):
        if path.is_file():
            try:
                return plugin_entries(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError):
                return ()
    return ()
