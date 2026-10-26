"""Install / uninstall TLInspector into an RPG Maker MV or MZ game folder.

The Inspector's file embeds the translator's editor command, so it stays on
the translator's computer: patches leave it out, and plugins.js, which every
patch carries, never lists it. The update check Set up installs loads it
where its file is (TranslationUpdateCheck.js), so installing, removing and
configuring it change no file a patch holds.

Credits: Idea by Sakura · Plugin by Kao_SSS
"""

from __future__ import annotations

import re
from pathlib import Path

from util import system
from util.rpgmaker_plugin_registry import (
    atomic_write_text,
    loaded_entries,
    update_plugin_entry,
)

PLUGIN_NAME = "TLInspector"
# Older installs listed it in plugins.js with this description.
_DESCRIPTION = "TL source inspector"

_PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_PLUGIN_SRC = _PKG_ROOT / "TLInspector.js"


def is_plugin_file(relative: str) -> bool:
    """Whether a game-relative path is the Inspector's file, in any letter
    case, as Windows loads it; no patch holds it."""
    return relative.replace("\\", "/").casefold() in {
        f"{web}js/plugins/{PLUGIN_NAME}.js".casefold() for web in ("", "www/")
    }


def bundled_plugin_path() -> Path:
    return DEFAULT_PLUGIN_SRC


def detect_engine(game_root: Path) -> tuple[str, Path, Path] | None:
    """Return (engine, plugins_js, plugins_dir) or None if not MV/MZ."""
    root = Path(game_root)
    mv_js = root / "www" / "js" / "plugins.js"
    mz_js = root / "js" / "plugins.js"
    if mv_js.is_file():
        return "MV", mv_js, root / "www" / "js" / "plugins"
    if mz_js.is_file():
        return "MZ", mz_js, root / "js" / "plugins"
    return None


def _read_plugins_js(plugins_js: Path) -> tuple[str, str]:
    content = plugins_js.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in content else "\n"
    return content, nl


def _is_listed(content: str) -> bool:
    return bool(
        re.search(r'"name"\s*:\s*"TLInspector"', content)
        or re.search(r'"description"\s*:\s*"TL source inspector"', content)
    )


def _loads(content: str, plugins_dir: Path) -> bool:
    """Whether the game loads the Inspector's file: the update check holding
    its loader is switched on, or plugins.js still lists it."""
    from util.translation_update_check.installer import PLUGIN_NAME as UPDATE_CHECK

    try:
        entries = loaded_entries(content)
    except ValueError:
        return False
    on = {entry.get("name") for entry in entries if entry.get("status")}
    if PLUGIN_NAME in on:
        return True
    if UPDATE_CHECK not in on:
        return False
    try:
        loader = (plugins_dir / f"{UPDATE_CHECK}.js").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return False
    return f"js/plugins/{PLUGIN_NAME}.js" in loader


def status(game_root: Path) -> dict:
    """Return install state for the game folder. `declared` says whether the
    game loads the Inspector, as Forge's says plugins.js lists Forge."""
    info = detect_engine(game_root)
    if info is None:
        return {
            "ok": False,
            "engine": None,
            "installed": False,
            "declared": False,
            "plugin_file": None,
            "message": "No RPG Maker MV/MZ game found (missing plugins.js).",
        }
    engine, plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, _ = _read_plugins_js(plugins_js)
    file_there = target.is_file()
    loaded = file_there and _loads(content, plugins_dir)
    present = file_there or _is_listed(content)
    return {
        "ok": True,
        "engine": engine,
        "installed": present,
        "declared": loaded,
        "plugin_file": file_there,
        "plugins_js": str(plugins_js),
        "target": str(target),
        "message": (
            "Installed"
            if loaded
            else "Partially installed"
            if present
            else "Not installed"
        ),
    }


def listed(game_root: Path) -> bool:
    """Whether the game's plugins.js lists the Inspector, as older installs
    did, so a patch of it asks players' game for a file it lacks."""
    info = detect_engine(game_root)
    return info is not None and _is_listed(_read_plugins_js(info[1])[0])


def _unlist(plugins_js: Path) -> None:
    content, nl = _read_plugins_js(plugins_js)
    if _is_listed(content):
        atomic_write_text(
            plugins_js,
            update_plugin_entry(
                content, PLUGIN_NAME, None, nl, description_prefixes=(_DESCRIPTION,)
            ),
        )


def unlist(game_root: Path) -> tuple[bool, str]:
    """Takes the Inspector out of plugins.js and, while its file is in the
    game, has the update check load it, so the translator keeps their hotkey.
    Installing the check again writes the current one, which holds the
    loader, and lists it where plugins.js lacks it; a game set up with the
    current check stays as it is."""
    from util.translation_update_check.installer import install as install_check

    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."
    _, plugins_js, plugins_dir = info
    try:
        _unlist(plugins_js)
    except (OSError, ValueError) as exc:
        return False, f"Could not take TLInspector out of plugins.js: {exc}"
    if (plugins_dir / f"{PLUGIN_NAME}.js").is_file():
        ok, message = install_check(game_root)
        if not ok:
            return False, message
        if not _loads(_read_plugins_js(plugins_js)[0], plugins_dir):
            # A check someone switched off keeps its place in plugins.js.
            return False, (
                "TLInspector loads through TranslationUpdateCheck, which plugins.js "
                "switches off. Switch it on to use TL Inspector."
            )
    return True, "TLInspector is no longer listed in plugins.js."


def install(game_root: Path, source_js: Path | None = None, cfg: dict | None = None) -> tuple[bool, str]:
    """Copy TLInspector.js into the game, where the update check loads it."""
    from util.tl_inspector.config import load_config, prepare_plugin_js

    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, _, plugins_dir = info
    src = Path(source_js) if source_js else DEFAULT_PLUGIN_SRC
    if not src.is_file():
        return False, f"TLInspector.js not found: {src}"

    target = plugins_dir / f"{PLUGIN_NAME}.js"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return False, f"Plugin destination is not a regular file: {target}"
    try:
        effective_cfg = cfg if cfg is not None else load_config()
        plugin_content = prepare_plugin_js(src, effective_cfg)
        plugins_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, plugin_content)
    except (OSError, ValueError) as exc:
        return False, f"Could not install TLInspector: {exc}"
    ok, message = unlist(game_root)
    if not ok:
        return False, message

    return True, (
        f"TLInspector installed for RPG Maker {engine}. "
        f"Press {(cfg or {}).get('hotkey', 'F9')} in-game to open."
    )


def uninstall(game_root: Path) -> tuple[bool, str]:
    """Delete the plugin file, and take it out of plugins.js where an older
    install listed it."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    _, plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return False, f"Plugin destination is not a regular file: {target}"

    try:
        _unlist(plugins_js)
        if target.is_file():
            system.unlink(target)
    except (OSError, ValueError) as exc:
        return False, f"Could not uninstall TLInspector: {exc}"

    return True, "TLInspector uninstalled."


def apply_config(game_root: Path, cfg: dict | None = None) -> tuple[bool, str]:
    """Rewrite an installed TLInspector.js with current editor settings."""
    from util.tl_inspector.config import load_config, prepare_plugin_js

    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    _, _, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    if not target.is_file():
        return False, "TLInspector is not installed in this game folder."

    effective_cfg = cfg if cfg is not None else load_config()
    try:
        plugin_content = prepare_plugin_js(DEFAULT_PLUGIN_SRC, effective_cfg)
        atomic_write_text(target, plugin_content)
    except (OSError, ValueError) as exc:
        return False, f"Could not apply TLInspector settings: {exc}"
    return True, "TL Inspector editor settings applied to the installed plugin."
