"""Shared RPG Maker markers that identify player-facing comment blocks."""

from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import Any, Iterable

SUPPORTED_CODE408_MARKERS = frozenset({"選択肢ヘルプ"})
# Plugin settings that list the comment (108) markers whose lines (408) the
# plugin shows players, such as MPP_ChoiceEX's choice help.
MARKER_SETTINGS = frozenset({"Choice Help Commands"})


class PluginList(tuple):
    """A game's plugin list entries in list order, with whether the game is
    MZ, whose loader tells plugins apart by file name. The plugin readers
    below return one, so what reads markers from it can apply the loader
    rule (rpgmaker_plugin_registry.loads)."""

    mz: bool

    def __new__(cls, entries: Iterable[Any] = (), mz: bool = False):
        plugins = super().__new__(cls, entries)
        plugins.mz = mz
        return plugins

    def loads(self) -> tuple[bool, ...]:
        """Whether the game loads each entry, in order."""
        from util.rpgmaker_plugin_registry import loads

        return loads(self, self.mz)

    def loaded(self) -> tuple[dict, ...]:
        """The entries the game loads, in order."""
        return tuple(entry for entry, load in zip(self, self.loads(), strict=True) if load)


def plugin_markers(plugins: PluginList) -> frozenset[str]:
    """The comment markers the plugins the game loads show the lines of, as
    their settings list them."""
    found = set()
    for plugin in plugins.loaded():
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


def comment_markers(plugins: PluginList) -> frozenset[str]:
    """The markers whose comment lines players read in a game with these
    plugins."""
    return SUPPORTED_CODE408_MARKERS | plugin_markers(plugins)


PLUGIN_LIST = "js/plugins.js"
# The core script an MZ game loads beside its plugin list, which tells MZ's
# loader rule from MV's (rpgmaker_plugin_registry.loads).
MZ_CORE = "js/rmmz_core.js"


def lists_mz(script: str | Path) -> bool:
    """Whether the plugin list (js/plugins.js) at *script* is an MZ game's:
    its core script sits beside it."""
    return (Path(script).parent / PurePath(MZ_CORE).name).is_file()


def read_plugin_list(text: str, mz: bool) -> PluginList:
    """A plugin list's text as the game loads it, or none it can read. The
    one reader for what a game's plugins show."""
    from util.rpgmaker_plugin_registry import loaded_entries

    try:
        return PluginList(loaded_entries(text), mz)
    except ValueError:
        return PluginList((), mz)


def plugin_list(script: str | Path) -> PluginList:
    """A plugin list (js/plugins.js) as the game loads it, or none it can
    read."""
    mz = lists_mz(script)
    try:
        return read_plugin_list(Path(script).read_text(encoding="utf-8-sig"), mz)
    except (OSError, UnicodeDecodeError):
        return PluginList((), mz)


def beside_data(data_folder: PurePath) -> PurePath:
    """Where the plugin list of the game whose data folder this is sits: in
    the js folder beside it, which the game loads with it."""
    return data_folder.parent / PLUGIN_LIST


def data_plugins(data_folder: str | Path) -> PluginList:
    """The plugin list of the game whose data folder this is."""
    return plugin_list(beside_data(Path(data_folder)))


def game_plugins(game_root: str | Path) -> PluginList:
    """A game's plugin list, or none it can read: beside its data folder,
    which a deployed MV game keeps in www."""
    root = Path(game_root)
    for base in (root, root / "www"):
        if (base / "data").is_dir() and (base / "js/plugins.js").is_file():
            return data_plugins(base / "data")
    for base in (root, root / "www"):
        if (base / "js/plugins.js").is_file():
            return plugin_list(base / "js/plugins.js")
    return PluginList()
