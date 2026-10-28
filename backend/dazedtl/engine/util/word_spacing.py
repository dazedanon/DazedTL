"""How a translation's words stay together in an RPG Maker MV/MZ plugin
command (code 356) or comment note tag (code 108), whose plugin reads its
arguments by splitting the text on spaces, so an English space can split one
argument into several.

Both methods read this one definition. Guided's Event text investigation
chooses each handler's spacing by :data:`RULE`, told whether the game's font
draws U+00A0 (:func:`nbsp_drawn`), and the engine joins the words with
:func:`join_words`. Len's method reads the same rule and font fact through the
project helper's ``word-spacing`` command, and Assistant-led's
``write_rpgmaker`` lists the commands :func:`split_changes` finds split.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The ways to join a translation's words; "underscore" is the default.
CHOICES = ("underscore", "nbsp", "space")
NBSP = "\u00a0"
# The codes whose commands plugins split on spaces.
CODES = (356, 108)
# The split commands a write lists, as it lists its misfits.
LISTED = 20

RULE = (
    "Plugins read an MV plugin command (356) and many comment note tags (108) "
    "by splitting the text on spaces, so a space in a translation can split one "
    "argument into several, and the plugin then fails or shows only the first "
    "word. Read how each plugin parses and draws its text, then join a "
    'translation\'s words one way: "underscore" (_) by default; "nbsp" '
    "(U+00A0, drawn as a space) only when the plugin splits on the plain space "
    'alone, as command356\'s split(" ") does, uses that argument whole, and the '
    'game\'s main font draws U+00A0; "space" when the plugin reads the rest of '
    "the text or joins the words back, and a space cannot change how it reads "
    "its other arguments, such as a trailing number read as a size. A plugin "
    "that splits on any whitespace, such as a \\s or /\\s+/ pattern, splits "
    "U+00A0 too, so it takes underscore. Read the delimiter from the game's "
    "shipped js/rpg_objects.js (MZ: js/rmmz_objects.js, "
    "Game_Interpreter.prototype.command356) and from each plugin's own parser "
    "rather than assuming it, and again after an engine update. The choice is "
    "right when the finished command, split as its plugin splits it, has the "
    "arguments the plugin expects."
)


def join_words(text: str, spacing: str) -> str:
    """Keeps a translation's words together the way its plugin reads them,
    with *spacing*, one of :data:`CHOICES`."""
    if spacing == "space":
        return text
    return text.replace(" ", NBSP if spacing == "nbsp" else "_")


def chosen(name: str, spaces, nbsp) -> str:
    """The spacing the engine options give one built-in handler or marker:
    "space" in *spaces* (SPACES_356/SPACES_108), "nbsp" in *nbsp*
    (NBSP_356/NBSP_108), else "underscore"."""
    if name in spaces:
        return "space"
    return "nbsp" if name in nbsp else "underscore"


def nbsp_drawn(data: str | Path) -> dict[str, Any]:
    """Whether the game's main font draws U+00A0 (``drawn``), with the font
    file as the layout check names it, or why it was not read (``unread``,
    with ``drawn`` None). *data* is the game's data folder, beside its
    fonts."""
    from util.rpgmaker_fonts import main_cmap

    result, cmap = main_cmap(Path(data))
    if cmap is None:
        return {**result, "drawn": None}
    drawn = cmap.covers(NBSP, damaged=None)
    if drawn is None:
        return {**result, "drawn": None, "unread": "The game's font map is damaged."}
    return {**result, "drawn": drawn}


def split_changes(original: Any, translated: Any) -> list[dict[str, Any]]:
    """The plugin commands and note tags of *translated*, a copy of the
    *original* event data with the same shape, that split on the plain space
    into more arguments than their source: each one's JSON pointer, its
    text, and the two counts. A command of *original* that an earlier write
    translated reads its source from the ``_original`` it kept, which for a
    comment holds its continuation rows after its own."""
    from util.rpgmaker_qa_preflight import pointer

    found: list[dict[str, Any]] = []

    def walk(source, target, path):
        if isinstance(source, dict) and isinstance(target, dict):
            parameters = source.get("parameters")
            written = target.get("parameters")
            if (
                source.get("code") in CODES
                and isinstance(parameters, list)
                and isinstance(written, list)
                and parameters
                and written
                and isinstance(parameters[0], str)
                and isinstance(written[0], str)
            ):
                kept = source.get("_original")
                text = kept if isinstance(kept, str) else parameters[0]
                if source["code"] == 108:
                    text = text.split("\n")[0]
                before = len(text.split(" "))
                after = len(written[0].split(" "))
                if after > before:
                    found.append(
                        {
                            "pointer": pointer((*path, "parameters", 0)),
                            "text": written[0],
                            "arguments": after,
                            "source_arguments": before,
                        }
                    )
            for key, value in source.items():
                if key in target and key != "_original":
                    walk(value, target[key], (*path, key))
        elif isinstance(source, list) and isinstance(target, list):
            for index, (value, other) in enumerate(zip(source, target)):
                walk(value, other, (*path, index))

    walk(original, translated, ())
    return found
