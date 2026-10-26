"""Install TranslationUpdateCheck into an RPG Maker MV or MZ game."""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.game_settings import game_target_language
from util.rpgmaker_plugin_registry import entry_texts, update_plugin_entry, with_entries

PLUGIN_NAME = "TranslationUpdateCheck"
PLUGIN_DESCRIPTION = "Translation update warning"
DEFAULT_PLUGIN_SRC = (
    Path(__file__).resolve().parents[2]
    / "gameupdate"
    / "gameupdate"
    / f"{PLUGIN_NAME}.js"
)
# The text players see, by the game's target language. Other languages show
# the plugin's English defaults, so their parameters stay empty.
MESSAGES = Path(__file__).with_name("messages.json")


def _detect_engine(game_root: Path) -> tuple[str, Path, Path] | None:
    root = Path(game_root)
    mv_plugins = root / "www" / "js" / "plugins.js"
    mz_plugins = root / "js" / "plugins.js"
    if mv_plugins.is_file():
        return "MV", mv_plugins, root / "www" / "js" / "plugins"
    if mz_plugins.is_file():
        return "MZ", mz_plugins, root / "js" / "plugins"
    return None


def _declared(content: str) -> bool:
    return bool(re.search(r'"name"\s*:\s*"TranslationUpdateCheck"', content))


def parameters(language: str, current: dict) -> dict:
    """*current*, the plugin's parameters, with its text in *language*. A
    value someone wrote in plugins.js themselves is kept."""
    catalog = json.loads(MESSAGES.read_text(encoding="utf-8"))
    wanted = next(
        (text for name, text in catalog.items() if name.casefold() == language.strip().casefold()),
        {},
    )
    result = dict(current)
    # In the catalog's order, so installing again writes the same file.
    for key in dict.fromkeys(key for text in catalog.values() for key in text):
        value = result.get(key)
        if value not in (None, "") and all(text.get(key) != value for text in catalog.values()):
            continue
        if key in wanted:
            result[key] = wanted[key]
        else:
            result.pop(key, None)
    return result


def _with_parameters(content: str, language: str, newline: str) -> str:
    """plugins.js with each update check entry's text in *language*, in its
    place in the list."""
    entries, changed = [], None
    for value, raw in entry_texts(content):
        if value.get("name") == PLUGIN_NAME:
            current = value.get("parameters")
            wanted = parameters(language, current if isinstance(current, dict) else {})
            if wanted != current:
                raw = changed = json.dumps({**value, "parameters": wanted}, ensure_ascii=False)
        entries.append(raw)
    if changed is None:
        return content
    updated = with_entries(content, entries)
    # A layout of its own: the canonical one, with one entry.
    return updated if updated is not None else update_plugin_entry(content, PLUGIN_NAME, changed, newline)


def install(game_root: str | Path, *, settings_root: str | Path | None = None) -> tuple[bool, str]:
    """Copy and enable the checker, its text in the target language of the
    game at *settings_root*, the game itself unless named. Repeated installs
    leave one declaration."""
    detected = _detect_engine(Path(game_root))
    if detected is None:
        return False, "Translation update check skipped (not an RPG Maker MV/MZ game)."
    engine, plugins_js, plugins_dir = detected
    if not DEFAULT_PLUGIN_SRC.is_file():
        return False, f"Translation update checker not found: {DEFAULT_PLUGIN_SRC}"

    try:
        language = game_target_language(settings_root or game_root)
        content = plugins_js.read_text(encoding="utf-8")
        newline = "\r\n" if "\r\n" in content else "\n"
        list_end = content.rfind("];")
        if not _declared(content) and list_end < 0:
            return False, "Could not find the plugin list end in plugins.js."

        plugins_dir.mkdir(parents=True, exist_ok=True)
        target = plugins_dir / f"{PLUGIN_NAME}.js"
        target.write_bytes(DEFAULT_PLUGIN_SRC.read_bytes())

        if _declared(content):
            updated = _with_parameters(content, language, newline)
        else:
            entry = json.dumps(
                {
                    "name": PLUGIN_NAME,
                    "status": True,
                    "description": PLUGIN_DESCRIPTION,
                    "parameters": parameters(language, {}),
                },
                ensure_ascii=False,
            )
            before = content[:list_end].rstrip()
            separator = newline if before.endswith((",", "[")) else "," + newline
            updated = before + separator + "        " + entry + newline + "    " + content[list_end:]
        if updated != content:
            plugins_js.write_text(updated, encoding="utf-8", newline="")
    except Exception as exc:
        return False, f"Could not install translation update check: {exc}"

    return True, f"Translation update check installed for RPG Maker {engine}."
