"""Comment text for games whose plugins show players comment lines.

A plugin such as MPP_ChoiceEX shows the comment lines (408) under a marker
its settings list as a choice's help. Maps & events translates them only with
Comment text on, so a project turns it on the first time it opens when the
game shows such lines in Japanese. The check runs once per project: what the
user chooses afterwards stays.
"""

import json
from pathlib import Path
from typing import Any

# The project record key saying the check ran.
CHECKED = "comment_text_checked"


# Comment markers per game, by its plugin lists' stat signatures.
_MARKERS: dict[tuple, frozenset[str]] = {}


def _japanese_lines(name: str, document: Any, markers: frozenset[str]) -> list:
    """The comment lines under *markers* that a data file holds in Japanese;
    a file shaped unlike RPG Maker's, such as a plugin's own data, holds none."""
    from util.rpgmaker_qa_preflight import visible_texts
    from util.source_text import holds_source

    try:
        return [
            value
            for _path, value, kind, _translated, _source in visible_texts(
                name, document, markers
            )
            if kind == "comment text" and holds_source(value)
        ]
    except AttributeError, IndexError, KeyError, TypeError:
        return []


def markers(source: str | Path) -> frozenset[str]:
    """The markers whose comment lines a Maps & events run with Comment text
    on translates, read from the game's plugin list as the engine reads it."""
    from util.rpgmaker_markers import comment_markers, game_plugins

    root = Path(source)
    signature: list[Any] = [str(root)]
    for path in (root / "js/plugins.js", root / "www/js/plugins.js"):
        try:
            info = path.stat()
            signature.append((info.st_mtime_ns, info.st_size))
        except OSError:
            signature.append(None)
    key = tuple(signature)
    if key not in _MARKERS:
        if len(_MARKERS) >= 64:
            _MARKERS.clear()
        _MARKERS[key] = comment_markers(game_plugins(root))
    return _MARKERS[key]


def shows_comment_text(data: str | Path, plugins: str | Path) -> bool:
    """Whether a game's turned-on plugins show comment lines that hold
    Japanese, from its data folder and plugin list."""
    from util.rpgmaker_markers import plugin_list, plugin_markers

    markers = plugin_markers(plugin_list(plugins))
    if not markers:
        return False
    for path in sorted(Path(data).glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8-sig")
            # Most files hold no marker; only those that do are parsed.
            if not any(marker in text for marker in markers):
                continue
            document = json.loads(text)
        except OSError, UnicodeDecodeError, ValueError:
            continue
        if any(_japanese_lines(path.name, document, markers)):
            return True
    return False


def check(workflows: Any, native: dict[str, Any]) -> None:
    """Record a project's one Comment text check, turning Comment text on
    when the game shows comment lines in Japanese; it never turns it off."""
    if native.get(CHECKED) or native["engine"] != "MVMZ":
        return
    values: dict[str, bool] = {CHECKED: True}
    if (
        not native["phase1_comments"]
        and native.get("plugins")
        and shows_comment_text(native["data"], native["plugins"])
    ):
        values["phase1_comments"] = True
    workflows.update(native["id"], native["revision"], values)
