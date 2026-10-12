"""Captures of an RPG Maker MV/MZ game's interface screens.

The game runs read-only in a hidden Electron window (see rpgmaker_window,
capture.cjs and harness.js): its title, menu, item, skill, equipment,
status, shop, options and battle screens open one by one with every entry
filled in, and each capture lists the text the game drew on it, measured with
the game's own fonts, including what it squeezed into less space than it
needs or drew past its window. Choice lists are captured when the game cuts
them off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from util import rpgmaker_window
from util.rpgmaker_window import WindowUnavailable, web_root

HERE = Path(__file__).resolve().parent
# Captures of a large game take a few minutes; a game that never finishes
# starting stops here.
DEFAULT_TIMEOUT = 600


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _command_lists(node: Any, pointer: str = ""):
    if isinstance(node, dict):
        commands = node.get("list")
        if isinstance(commands, list) and any(
            isinstance(item, dict) and isinstance(item.get("code"), int) for item in commands
        ):
            yield commands, pointer + "/list"
        for key, value in node.items():
            if key not in {"list", "_original"}:
                yield from _command_lists(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _command_lists(value, f"{pointer}/{index}")


def choice_sets(data_root: str | Path) -> list[dict[str, Any]]:
    """Every distinct choice list the game's events show, with where the first
    one is, as the capture plan takes them."""
    root = Path(data_root)
    sets: dict[tuple, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        if not (
            path.name in {"CommonEvents.json", "Troops.json"}
            or (path.name.startswith("Map") and path.stem[3:].isdigit())
        ):
            continue
        try:
            document = _load(path)
        except (OSError, ValueError):
            continue
        for commands, pointer in _command_lists(document):
            for index, command in enumerate(commands):
                params = command.get("parameters") if isinstance(command, dict) else None
                if (
                    command.get("code") != 102
                    or not isinstance(params, list)
                    or not params
                    or not isinstance(params[0], list)
                    or not all(isinstance(choice, str) for choice in params[0])
                ):
                    continue
                key = (tuple(params[0]), *(params[1:5] if len(params) >= 5 else ()))
                sets.setdefault(key, {
                    "key": f"{path.name}#{pointer}/{index}",
                    "choices": params[0],
                    "cancelType": params[1] if len(params) > 1 else -1,
                    "defaultType": params[2] if len(params) > 2 else 0,
                    "positionType": params[3] if len(params) > 3 else 2,
                    "background": params[4] if len(params) > 4 else 0,
                })
    return list(sets.values())


def capture(
    data_root: str | Path,
    out_dir: str | Path,
    *,
    overlay: dict[str, str | Path] | None = None,
    screens: Iterable[str] | None = None,
    choices: list[dict[str, Any]] | None = None,
    all_choices: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Capture the game's screens into *out_dir* and return what screens.json
    lists. *overlay* serves corrected data files, by path under the game's web
    folder such as ``data/Items.json``, in place of the game's own; *screens*
    limits the capture to those screens; *choices* replaces the game's choice
    lists, each captured with *all_choices* and otherwise only when the game
    cuts it off. *progress* hears which screen the capture is on, and its
    ``stopped``, when it has one, stops the capture."""
    web = web_root(data_root)
    out = Path(out_dir)
    played = rpgmaker_window.run(
        HERE / "capture.cjs",
        web,
        out,
        {
            "choices": choice_sets(data_root) if choices is None else choices,
            "allChoices": all_choices,
            "screens": list(screens) if screens is not None else None,
        },
        seconds=timeout,
        size=rpgmaker_window.screen_size(data_root),
        overlay=overlay,
        starting="Capturing the game's screens",
        status=lambda event: (
            f"Capturing the game's screens: {event['title']}" if "captured" in event else None
        ),
        log=progress or (lambda _text: None),
        stopped=getattr(progress, "stopped", lambda: False),
    )
    listing = out / "screens.json"
    if not listing.is_file():
        raise WindowUnavailable(
            "The capture stopped before writing its results"
            + (f": {played.errors}" if played.errors else ".")
        )
    return _load(listing)
