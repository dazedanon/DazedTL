"""Forge plugin build — install-time hotkey injection.

Canonical Forge_MV.js / Forge_MZ.js sources stay untouched under ``upstream/``.
Patches are applied in memory when installing or applying settings to a game.

MV and MZ use the rewritten unified ``Forge_MZ.js`` bundle.  The pre-rewrite
``Forge_MV.js`` remains bundled as an explicit fallback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.playtest.config import load_config
from util.forge.modern_patches import apply_modern_forge_patches

_PKG_ROOT = Path(__file__).resolve().parent

PLUGIN_BY_ENGINE = {
    "MV": "Forge_MV",
    "MZ": "Forge_MZ",
}

SOURCE_PLUGIN_BY_ENGINE = {
    "MV": "Forge_MZ",
    "MZ": "Forge_MZ",
}


def bundled_plugin_path(engine: str) -> Path:
    name = SOURCE_PLUGIN_BY_ENGINE.get(engine)
    if not name:
        raise ValueError(f"Unsupported engine: {engine}")
    return _PKG_ROOT / "upstream" / f"{name}.js"


def _js_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def plugin_entry(engine: str, hotkey: str, *, modern: bool = False) -> str:
    name = PLUGIN_BY_ENGINE[engine]
    if modern:
        return (
            f'        {{ "name": "{name}", "status": true, '
            f'"description": "Forge — in-game cheat & editor overlay", '
            f'"parameters": {{}} }}'
        )
    hk = _js_literal(hotkey.strip() or "F10")
    if engine == "MZ":
        return (
            f'        {{ "name": "{name}", "status": true, '
            f'"description": "Forge — in-game cheat & editor overlay", '
            f'"parameters": {{ "hotkey": {hk}, "speedKey": "Control", '
            f'"startOpen": "false", "itemMaxOverride": "0" }} }}'
        )
    return (
        f'        {{ "name": "{name}", "status": true, '
        f'"description": "Forge — in-game cheat & editor overlay", '
        f'"parameters": {{ "Hotkey": {hk}, "SpeedKey": "Control", '
        f'"StartOpen": "false", "ItemMaxOverride": "0" }} }}'
    )


def _patch_forge_hotkey(forge_text: str, hotkey: str, engine: str) -> str:
    hk = hotkey.strip() or "F10"
    if engine == "MZ":
        pattern = (
            r"(\* @param hotkey\s*\n"
            r"(?:\s*\*[^\n]*\n)*?"
            r"\s*\* @default )F10"
        )
        forge_text, n = re.subn(pattern, rf"\g<1>{hk}", forge_text, count=1)
        if n == 0:
            raise ValueError("Could not patch @default hotkey in Forge_MZ.js")
        return forge_text

    pattern = (
        r"(\* @param Hotkey\s*\n"
        r"(?:\s*\*[^\n]*\n)*?"
        r"\s*\* @default )F10"
    )
    forge_text, n = re.subn(pattern, rf"\g<1>{hk}", forge_text, count=1)
    if n == 0:
        raise ValueError("Could not patch @default Hotkey in Forge_MV.js")
    return forge_text


def _patch_forge_mtc_defaults(forge_text: str, hotkey: str) -> str:
    hk = json.dumps(hotkey.strip() or "F10")
    return re.sub(r"_hotkey: 'F10'", f"_hotkey: {hk}", forge_text, count=1)


def _patch_forge_runtime(forge_text: str, hotkey: str, engine: str) -> str:
    hk = json.dumps(hotkey.strip() or "F10")
    param = "hotkey" if engine == "MZ" else "Hotkey"
    return re.sub(
        rf"window\.Forge\._hotkey = \(P\.{param} \|\| '[^']*'\)\.trim\(\);",
        f"window.Forge._hotkey = {hk};",
        forge_text,
        count=1,
    )


def _remove_legacy_launcher(forge_text: str) -> str:
    """Keep legacy Forge shortcut-only by leaving its launcher detached."""
    marker = "    rootEl.appendChild(launcher);"
    if forge_text.count(marker) != 1:
        raise ValueError("Could not disable legacy Forge launcher")
    return forge_text.replace(
        marker,
        "    // Floating launcher disabled; use the configured Forge shortcut.",
        1,
    )


def is_legacy_forge_plugin(text: str) -> bool:
    """True for pre-rewrite Forge_MV/MZ plugins with RPG Maker @param blocks."""
    return "@param Hotkey" in text or "@param hotkey" in text


def prepare_forge_js(engine: str, source: Path | None = None, cfg: dict | None = None) -> str:
    """Build the Forge plugin written into a game folder (vanilla source + Dazed patches)."""
    src = source or bundled_plugin_path(engine)
    text = src.read_text(encoding="utf-8")
    effective = {**load_config(), **(cfg or {})}
    hotkey = effective.get("forgeHotkey", "F10")

    if not is_legacy_forge_plugin(text):
        return apply_modern_forge_patches(text, hotkey)

    text = _patch_forge_hotkey(text, hotkey, engine)
    text = _patch_forge_mtc_defaults(text, hotkey)
    text = _patch_forge_runtime(text, hotkey, engine)
    text = _remove_legacy_launcher(text)
    return text


# Back-compat alias
def prepare_forge_mz_js(source: Path | None = None, cfg: dict | None = None) -> str:
    return prepare_forge_js("MZ", source, cfg)
