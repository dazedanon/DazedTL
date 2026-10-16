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

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from util import rpgmaker_window
from util.rpgmaker_window import WindowUnavailable, web_root

HERE = Path(__file__).resolve().parent
# Captures of a large game take a few minutes; a game that never finishes
# starting stops here.
DEFAULT_TIMEOUT = 600
# A capture's file name before its page number, and the screen that makes it.
_CAPTURE_SCREENS = {
    "title": "title", "menu": "menu", "items": "items", "skills": "skills",
    "equip": "equipment", "status": "status", "shop": "shop",
    "options": "options", "game-end": "options", "battle": "battles",
    "choices": "choices",
}
# Control codes the game turns into colors, icons or values as it draws text.
_DRAW_CODE_RE = re.compile(r"\\+[A-Za-z]+\[[^\]]*\]|\\+[A-Za-z{}|.!><^$]")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def shown_text(text: Any) -> str:
    """Text as the game draws it, without the codes it turns into colors."""
    return _DRAW_CODE_RE.sub("", str(text or "")).strip()


def screen_of(capture: str | Path) -> str:
    """The screen, as *screens* names it, that makes a capture file, or ""."""
    return _CAPTURE_SCREENS.get(Path(capture).stem.split("-")[0], "")


def plugins_sha256(data_root: str | Path) -> str:
    """A digest of the game's plugin list and plugin code beside *data_root*,
    which change what its screens draw without changing its data."""
    web = Path(data_root).resolve().parent
    folder = web / "js" / "plugins"
    files = [web / "js" / "plugins.js"]
    if folder.is_dir():
        files += sorted(path for path in folder.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        if path.is_file():
            digest.update(path.relative_to(web).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


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


# How many files and labels one label check takes.
LABEL_CHECK_LIMIT = 200


def read_label_plan(value: Any, game_root: str | Path) -> dict[str, Any]:
    """A label check's plan, checked: the working copies it serves in place of
    the game's files, each by its path in the game folder, its path under the
    web folder and its hash; the labels it measures, each with its screen,
    the capture that found it and the text it should draw now; and the
    request they belong to."""
    if not isinstance(value, dict):
        raise ValueError("Give the label check's plan as an object.")
    root = Path(game_root).resolve()
    files, labels = value.get("files"), value.get("labels")
    if not isinstance(files, list) or not 0 < len(files) <= LABEL_CHECK_LIMIT:
        raise ValueError("Give the label check the working copies it serves.")
    checked = []
    for row in files:
        fields = ("path", "serve", "candidate", "hash")
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) and row[key] for key in fields
        ):
            raise ValueError("Each served file needs its path, web path, copy and hash.")
        serve = row["serve"]
        if (
            serve.startswith("/")
            or "\\" in serve
            or any(part in {"", ".", ".."} for part in serve.split("/"))
        ):
            raise ValueError("Serve each file by its path under the game's web folder.")
        candidate = (root / row["candidate"]).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("Serve working copies from the game folder.")
        checked.append({key: row[key] for key in fields})
    if not isinstance(labels, list) or not 0 < len(labels) <= LABEL_CHECK_LIMIT:
        raise ValueError("Give the label check the labels it measures.")
    for label in labels:
        if (
            not isinstance(label, dict)
            or not all(
                isinstance(label.get(key), str) and label[key]
                for key in ("text", "title", "capture")
            )
            or not screen_of(label["capture"])
            or not isinstance(label.get("shows"), list)
            or not label["shows"]
            or not all(isinstance(text, str) and text for text in label["shows"])
        ):
            raise ValueError(
                "Each label needs its text, its screen, the capture that found it "
                "and the text it draws now."
            )
    if not isinstance(value.get("request"), str) or not value["request"]:
        raise ValueError("Name the request whose working copies the check serves.")
    return {
        "files": checked,
        "labels": [
            {key: label[key] for key in ("text", "title", "capture", "shows")}
            for label in labels
        ],
        "request": value["request"],
    }


def label_fits(
    labels: list[dict[str, Any]], listing: dict[str, Any], out: str | Path
) -> list[dict[str, Any]]:
    """How each label shows on its screen captured again: whether the game
    draws the text it should show now in full, with how short of room that
    text or the label's old text still is, and the capture."""
    rows = []
    for label in labels:
        screen = screen_of(label["capture"])
        screens = [
            place for place in listing["screens"] if place["title"] == label["title"]
        ]
        # A screen whose pages moved shows the text under another title.
        screens = screens or [
            place for place in listing["screens"] if screen_of(place["file"]) == screen
        ]
        row = {key: label[key] for key in ("text", "title", "shows")}
        if not screens:
            rows.append(
                {**row, "fits": False, "note": f"The capture did not reach {label['title']}."}
            )
            continue
        drawn = [
            (place, shown_text(item["text"]), item)
            for place in screens
            for item in place.get("labels") or []
        ]
        now = [entry for entry in drawn if entry[1] in label["shows"]]
        old = [
            entry
            for entry in drawn
            if entry[1] == label["text"] and label["text"] not in label["shows"]
        ]
        short = [entry for entry in now + old if _short(entry[2])]
        found = short[0] if short else (now or old or [(screens[0], "", {})])[0]
        row["capture"] = str(Path(out) / found[0]["file"])
        row["fits"] = bool(now) and not short and not old
        row.update(
            {key: found[2][key] for key in ("squeezed", "clipped") if key in found[2]}
            if short
            else {}
        )
        shows = " or ".join(label["shows"])
        if old:
            # The plugin draws another setting there.
            how = next((_how(entry[2]) for entry in old if _short(entry[2])), "")
            row["note"] = (
                f"The game still draws {label['text']} there"
                + (f", {how}" if how else "")
                + f", not {shows}."
            )
        elif short:
            row["note"] = f"The game draws {short[0][1]} {_how(short[0][2])}."
        elif not now:
            row["note"] = f"The game draws no {shows} on {found[0]['title']}."
        else:
            row["note"] = f"The game draws {now[0][1]} in full."
        rows.append(row)
    return rows


def _short(label: dict[str, Any]) -> bool:
    return bool(label.get("clipped")) or label.get("squeezed", 1) < 1


def _how(label: dict[str, Any]) -> str:
    if label.get("clipped"):
        return "cut off at its window's edge"
    return f"squeezed to {round(label['squeezed'] * 100)}% of the width it needs"
