"""The locale a translated RPG Maker MV/MZ game's System.json is written with,
for Guided's Apply and Assistant-led's writer alike.

The engine reads ``locale`` through ``Game_System.isJapanese`` and its
siblings: name entry's letter tables and character width, the letters that
tell apart enemies of one name, and, in MV, the font of a Chinese or Korean
locale. A game translated into a language written in Latin letters gets
``en_US``, so name entry offers Latin letters and enemies read "Slime A";
any other target keeps the game's own locale, whose tables and fonts suit
it better than English ones.
"""

from __future__ import annotations

from util.languages import LATIN, active_target, script

ENGLISH_LOCALE = "en_US"


def write_locale(document, filename: str, target=None, source=None) -> bool:
    """Give *document*, when it is a System.json with a locale, the locale
    for *target*, the run's target when None, in place. The game's own
    locale is the one *source*, the file *document* translates (itself when
    None), keeps under ``_original``, else its live one. Says whether it
    changed."""
    if filename != "System.json" or not isinstance(document, dict):
        return False
    current = document.get("locale")
    if not isinstance(current, str):
        return False
    source = source if isinstance(source, dict) else document
    kept = source.get("_original")
    own = (kept.get("locale") if isinstance(kept, dict) else None) or source.get(
        "locale"
    )
    if not isinstance(own, str) or not own:
        own = current
    locale = ENGLISH_LOCALE if script(target or active_target()) == LATIN else own
    document["locale"] = locale
    return locale != current
