"""A translated game's window title: "<English title> v<version> | TL: <translator>".

`form` is the one rule for the text, `text` reads its parts for a game, and a
game shows it through `sync` on RPG Maker MV/MZ or `ini_title` on VX Ace.

The translator's name is a setting (`SETTING`); while it is empty DazedTL
leaves every window title as the game sets it. The English title is the
game's translated title, which on MV/MZ and VX Ace is also the title the game
draws, so it stays as translation wrote it; the version is the one the
game's `original` branch registers. Only a game whose Git is set up gets the
title, so preparation, the record of the original files and the copies a
game update stages never hold it: their files are what an update's merge
compares, and a title in them would make every new version conflict there.

Values that name the save folder or that saves are matched by are never
written: NW.js `package.json` `name`, and the title saves compare.
"""

from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Callable
from pathlib import Path

SETTING = "translatorName"
PLUGIN_NAME = "DazedTLWindowTitle"
PLUGIN_SOURCE = Path(__file__).with_name(f"{PLUGIN_NAME}.js")
_PLUGIN_DESCRIPTION = "Translation window title"
_TITLE_TAG = re.compile(r"(<title[^>]*>)(.*?)(</title\s*>)", re.IGNORECASE | re.DOTALL)
_WINDOW_KEY = re.compile(r'"window"\s*:\s*\{')
# Registered versions by repository and `original` commit, which fixes them.
_versions: dict[tuple[str, str], str | None] = {}
_TITLE_KEY = re.compile(r'"title"\s*:\s*"(?:[^"\\]|\\.)*"')


def form(title: object, version: object, translator: object) -> str:
    """The window title, or "" when there is no title or translator name.
    " v<version>" is left out while no version is registered."""
    def clean(value):
        return " ".join(value.split()) if isinstance(value, str) else ""

    title, version, translator = clean(title), clean(version), clean(translator)
    if not title or not translator:
        return ""
    version = version[1:] if version[:1] in {"v", "V"} and version[1:2].isdigit() else version
    return f"{title}{f' v{version}' if version else ''} | TL: {translator}"


def translator() -> str:
    """The translator's name from Settings, read where the engine runs: the
    app profile an operation names, or else the environment of a command
    run outside the app."""
    from util.paths import runtime_profile

    profile = runtime_profile()
    if profile is not None:
        # The engine's profile is the app profile's engine folder.
        from dazedtl.settings.store import saved_translator

        return saved_translator(profile.parent).strip()
    return os.environ.get(SETTING, "").strip()


def version(checkout) -> str | None:
    """The game version the repository's `original` branch registers, read
    once per `original` commit, so a write pays no Git launch for it."""
    from util.version_update.git_workflow import original_version

    if checkout is None or not checkout.original_commit:
        return None
    key = (str(checkout.repo), checkout.original_commit)
    if key not in _versions:
        _versions[key] = original_version(checkout)
    return _versions[key]


def text(root: str | Path, title: str | None = None, checkout=None, name: str | None = None) -> str:
    """The game's window title, or "" when it gets none: no translator name,
    its Git not set up, or no title. `title` defaults to the RPG Maker
    game's translated `gameTitle`; `checkout` is the game's `read_checkout`
    when the caller has it; `name` the translator's when known."""
    from util.paths import game_git_set_up

    name = translator() if name is None else name
    if not name or not game_git_set_up(root):
        return ""
    if title is None:
        title = _game_title(Path(root))
    if not title:
        return ""
    if checkout is None:
        from util.version_update.git_workflow import read_checkout

        checkout = read_checkout(root)
    return form(title, version(checkout), name)


def preview(root: str | Path | None, name: str) -> str:
    """The window title `name` gives the game at `root`, for Settings to
    show while the name is typed, or an example without a game; a
    placeholder stands for a title DazedTL can't read, such as one an
    assistant translates."""
    from util.paths import game_git_set_up

    title = _game_title(Path(root)) if root else ""
    checkout = None
    if root and game_git_set_up(root):
        from util.version_update.git_workflow import read_checkout

        checkout = read_checkout(root)
    return form(title or "<English title>", version(checkout), name)


def ini_title(root: str | Path, title: object) -> object:
    """The title a VX Ace game's Game.ini gets for its `gameTitle`: the
    window title when the game gets one, else `title` as it is. The
    title the game draws stays in its System data."""
    return (text(root, title) if isinstance(title, str) else "") or title


def sync(root: str | Path, put: Callable[[str, bytes], None], checkout=None,
         log: Callable[[str], None] = lambda _line: None) -> list[str]:
    """Shows the window title in an RPG Maker MV/MZ game: its plugin, which
    keeps the title once the game boots, with the title in plugins.js, and
    NW.js's `package.json` `window.title` and `index.html` `<title>`, shown
    while it loads. `put(relative, raw)` writes one game file. Returns the
    files it changed; none while the game gets no title."""
    from util.project_preparation import rpgmaker_layout

    root = Path(root)
    name = translator()
    layout = rpgmaker_layout(root) if name else None
    if not layout or layout["engine"] != "MVMZ":
        return []
    wanted = text(root, checkout=checkout, name=name)
    if not wanted:
        return []
    plugins_js = layout["plugins_js"]
    web = plugins_js.parent.parent
    changes = {
        plugins_js.parent / "plugins" / f"{PLUGIN_NAME}.js": PLUGIN_SOURCE.read_bytes(),
        plugins_js: _registry(plugins_js, wanted),
        root / "package.json": _package(root / "package.json", wanted),
        web / "index.html": _index(web / "index.html", wanted),
    }
    written = []
    for path, raw in changes.items():
        if raw is None or (path.is_file() and path.read_bytes() == raw):
            continue
        relative = path.relative_to(root).as_posix()
        put(relative, raw)
        written.append(relative)
    if written:
        log(f"Window title: {wanted}")
    return written


def _game_title(root: Path) -> str:
    from util.project_preparation import rpgmaker_layout

    layout = rpgmaker_layout(root)
    if not layout:
        return ""
    system = layout["data_path"] / "System.json"
    try:
        value = json.loads(system.read_text(encoding="utf-8-sig")).get("gameTitle")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def _registry(path: Path, title: str) -> bytes | None:
    """plugins.js with the plugin on, its title `title`, kept in its place."""
    from util.rpgmaker_plugin_registry import (
        PluginRegistryError,
        entry_texts,
        update_plugin_entry,
        with_entries,
    )

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    newline = "\r\n" if "\r\n" in content else "\n"
    entry = json.dumps(
        {"name": PLUGIN_NAME, "status": True, "description": _PLUGIN_DESCRIPTION,
         "parameters": {"title": title}},
        ensure_ascii=False,
    )
    try:
        entries = entry_texts(content)
        if any(value.get("name") == PLUGIN_NAME for value, _ in entries):
            updated = with_entries(content, [
                entry if value.get("name") == PLUGIN_NAME else raw for value, raw in entries
            ])
            if updated is None:
                updated = update_plugin_entry(content, PLUGIN_NAME, entry, newline)
        else:
            updated = update_plugin_entry(content, PLUGIN_NAME, entry, newline)
    except PluginRegistryError:
        return None
    return updated.encode("utf-8")


def _package(path: Path, title: str) -> bytes | None:
    """NW.js's package.json with `window.title` set and every other byte
    kept; None when the game has none NW.js reads."""
    try:
        content = path.read_text(encoding="utf-8-sig")
        value = json.loads(content)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("window"), dict):
        return None
    window = _WINDOW_KEY.search(content)
    if window is None:
        return None
    encoded = json.dumps(title, ensure_ascii=False)
    start = window.end()
    if "title" in value["window"]:
        found = _TITLE_KEY.search(content, start)
        if found is None:
            return None
        updated = content[: found.start()] + f'"title": {encoded}' + content[found.end():]
    else:
        updated = content[:start] + f'"title": {encoded}, ' + content[start:]
    try:
        if json.loads(updated)["window"].get("title") != title:
            return None
    except (ValueError, KeyError):
        return None
    bom = path.read_bytes().startswith(b"\xef\xbb\xbf")
    return (b"\xef\xbb\xbf" if bom else b"") + updated.encode("utf-8")


def _index(path: Path, title: str) -> bytes | None:
    """index.html with its `<title>` text set; None without one."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    found = _TITLE_TAG.search(content)
    if found is None:
        return None
    updated = content[: found.start(2)] + html.escape(title, quote=False) + content[found.end(2):]
    return updated.encode("utf-8")
