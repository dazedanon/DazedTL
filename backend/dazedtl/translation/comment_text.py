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


def shows_comment_text(data: str | Path, plugins: str | Path) -> bool:
    """Whether a game's turned-on plugins show comment lines that hold
    Japanese, from its data folder and plugin list."""
    from util.rpgmaker_markers import plugin_markers
    from util.rpgmaker_plugin_registry import plugin_entries
    from util.rpgmaker_qa_preflight import japanese, visible_texts

    try:
        entries = plugin_entries(Path(plugins).read_text(encoding="utf-8-sig"))
    except OSError, UnicodeDecodeError, ValueError:
        return False
    markers = plugin_markers(entries)
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
        if any(
            kind == "comment text" and japanese(value)
            for _path, value, kind, _translated in visible_texts(
                path.name, document, markers
            )
        ):
            return True
    return False


def check(workflows: Any, native: dict[str, Any]) -> dict[str, Any]:
    """The project after its one Comment text check: on when the game shows
    comment lines in Japanese, and never turned off."""
    if native.get(CHECKED) or native["engine"] != "MVMZ":
        return native
    if (
        not native["phase1_comments"]
        and native.get("plugins")
        and shows_comment_text(native["data"], native["plugins"])
    ):
        native = workflows.update(
            native["id"], native["revision"], {"phase1_comments": True}
        )["project"]
    native = {**native, CHECKED: True}
    workflows.save(native)
    workflows.projects[native["id"]] = native
    return native
