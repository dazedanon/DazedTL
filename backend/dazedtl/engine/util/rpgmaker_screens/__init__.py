"""Captures of an RPG Maker MV/MZ game's interface screens.

The game runs read-only in a hidden Electron window (see capture.cjs and
harness.js): its title, menu, item, skill, equipment, status, shop, options
and battle screens open one by one with every entry filled in, and each
capture lists the text the game drew on it, measured with the game's own
fonts, including what it squeezed into less space than it needs or drew past
its window. Choice lists are captured when the game cuts them off.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from util.paths import PROJECT_ROOT

HERE = Path(__file__).resolve().parent
# Captures of a large game take a few minutes; a game that never finishes
# starting stops here.
DEFAULT_TIMEOUT = 600
# The application's Electron, which the app names for its workers.
ELECTRON_ENV = "DAZEDTL_ELECTRON"


class CaptureUnavailable(Exception):
    """The screens cannot be captured on this machine or for this game."""


def electron() -> Path:
    """The Electron that runs the capture: the app's own, or the checkout's."""
    named = os.environ.get(ELECTRON_ENV, "").strip()
    if named and Path(named).is_file():
        return Path(named)
    package = PROJECT_ROOT.parents[2] / "app" / "node_modules" / "electron"
    try:
        binary = package / "dist" / (package / "path.txt").read_text(encoding="utf-8").strip()
    except OSError:
        binary = None
    if binary and binary.is_file():
        return binary
    raise CaptureUnavailable("DazedTL's Electron isn't installed, so it can't run the game.")


def web_root(data_root: str | Path) -> Path:
    """The folder that holds the game's index.html, beside its data folder."""
    root = Path(data_root).resolve().parent
    if not (root / "index.html").is_file():
        raise CaptureUnavailable("The game has no index.html to start it from.")
    return root


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def screen_size(data_root: str | Path) -> tuple[int, int] | None:
    """The game's screen size as MZ records it; MV's comes from its scripts."""
    try:
        advanced = _load(Path(data_root) / "System.json").get("advanced") or {}
        return int(advanced["screenWidth"]), int(advanced["screenHeight"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


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


def _has_display() -> bool:
    return sys.platform in {"win32", "darwin"} or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def capture(
    data_root: str | Path,
    out_dir: str | Path,
    *,
    overlay: dict[str, str | Path] | None = None,
    screens: Iterable[str] | None = None,
    choices: list[dict[str, Any]] | None = None,
    all_choices: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Capture the game's screens into *out_dir* and return what screens.json
    lists. *overlay* serves corrected data files, by path under the game's web
    folder such as ``data/Items.json``, in place of the game's own; *screens*
    limits the capture to those screens; *choices* replaces the game's choice
    lists, each captured with *all_choices* and otherwise only when the game
    cuts it off."""
    if not _has_display():
        raise CaptureUnavailable("There's no display to run the game on.")
    binary = electron()
    web = web_root(data_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    size = screen_size(data_root)
    plan = {
        "web": str(web),
        "out": str(out),
        "timeout": timeout,
        "choices": choice_sets(data_root) if choices is None else choices,
        "allChoices": all_choices,
        "screens": list(screens) if screens is not None else None,
        "overlay": {key: str(value) for key, value in (overlay or {}).items()},
        **({"width": size[0], "height": size[1]} if size else {}),
    }
    # Electron's helper processes may still hold its profile for a moment.
    with tempfile.TemporaryDirectory(
        prefix="dazedtl-capture-", ignore_cleanup_errors=True
    ) as temporary:
        plan["profile"] = str(Path(temporary) / "profile")
        plan_path = Path(temporary) / "plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        environment = {
            key: value for key, value in os.environ.items()
            if key not in {"ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"}
        }
        # The window is never shown, so X11, which Wayland desktops also
        # offer, serves wherever it exists.
        platform = (
            ["--ozone-platform=x11"] if sys.platform.startswith("linux") and os.environ.get("DISPLAY")
            else ["--ozone-platform=wayland"] if sys.platform.startswith("linux")
            else []
        )
        try:
            completed = subprocess.run(
                [str(binary), *platform, str(HERE / "capture.cjs"), str(plan_path)],
                cwd=temporary,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout + 60,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CaptureUnavailable("The game didn't finish its screens in time.") from error
    listing = out / "screens.json"
    if not listing.is_file():
        tail = completed.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise CaptureUnavailable(
            "The capture stopped before writing its results"
            + (": " + " ".join(tail) if tail else ".")
        )
    return _load(listing)
