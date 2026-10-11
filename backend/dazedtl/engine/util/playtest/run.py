"""Runs the release playtest and writes the one report the app and the
assistant read: the static checks, then the tour in a hidden window of
DazedTL's own Electron, merged so each problem shows once with where the tour
saw it.

The playtest writes only its output folder; the game folder is read-only to
it, and the tour's saves stay in a browser profile it deletes afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from util.playtest.checks import static_checks

SCHEMA = "rpgmaker-playtest-report-v1"
HARNESS = Path(__file__).with_name("harness") / "main.cjs"
# The tour every run takes, in order.
TOUR = (
    ("title", "Title screen"),
    ("new-game", "New Game"),
    ("opening", "Opening"),
    ("menu", "Menu screens"),
    ("save-load", "Save and load"),
    ("shop", "Shop"),
    ("battle", "Battle"),
    ("screens", "Plugin screens"),
    ("end", "Back to the title"),
)
# What an assistant's stop may do, and the fields each needs.
STOP_KINDS = {
    "map": ("map",),
    "event": ("event",),
    "common-event": ("id",),
    "battle": ("troop",),
    "scene": ("scene",),
    "script": ("script",),
}
DEFAULT_MINUTES = 15
OPENING_SECONDS = 120
BATTLE_SECONDS = 60
# Problems an engine scene shows in its standard help or message window,
# where shorter text fixes them; anywhere else the window is the game's own.
_ENGINE_SCENES = frozenset({
    "Scene_Map", "Scene_Menu", "Scene_Item", "Scene_Skill", "Scene_Equip",
    "Scene_Status", "Scene_Options", "Scene_Save", "Scene_Load", "Scene_GameEnd",
    "Scene_Shop", "Scene_Name", "Scene_Battle", "Scene_Title", "Scene_Gameover",
})


def electron() -> Path | None:
    """DazedTL's own Electron, beside the engine in its checkout."""
    for parent in Path(__file__).resolve().parents:
        package = parent / "app" / "node_modules" / "electron"
        try:
            name = (package / "path.txt").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        binary = package / "dist" / name
        return binary if binary.is_file() else None
    return None


def resolution(data: Path) -> tuple[int, int]:
    """The game's screen size: MZ keeps it in System.json; MV starts at
    816x624, and the tour follows a plugin that changes it."""
    try:
        advanced = json.loads((data / "System.json").read_text(encoding="utf-8-sig")).get(
            "advanced"
        ) or {}
        width, height = int(advanced["screenWidth"]), int(advanced["screenHeight"])
        if 160 <= width <= 4096 and 120 <= height <= 4096:
            return width, height
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return 816, 624


def battlebacks(web_root: Path) -> list[str]:
    """A battle background pair the game ships, for battles the tour starts
    on maps that name none; empty names show none."""
    names = []
    for folder in ("battlebacks1", "battlebacks2"):
        found = sorted(
            path.name.split(".", 1)[0]
            for path in (web_root / "img" / folder).glob("*")
            if path.suffix.lower() in {".png", ".png_", ".rpgmvp"}
        ) if (web_root / "img" / folder).is_dir() else []
        names.append(found[0] if found else "")
    return names


def read_stops(value: Any) -> list[dict[str, Any]]:
    """An assistant's stops, checked: each names what it does and a title."""
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        value = value.get("stops")
    if not isinstance(value, list):
        raise ValueError("Give the playtest's stops as a list.")
    stops = []
    for number, stop in enumerate(value, start=1):
        if not isinstance(stop, dict) or stop.get("do") not in STOP_KINDS:
            raise ValueError(
                f"Stop {number} must do one of: " + ", ".join(STOP_KINDS) + "."
            )
        missing = [key for key in STOP_KINDS[stop["do"]] if key not in stop]
        if missing:
            raise ValueError(f"Stop {number} needs {', '.join(missing)}.")
        title = str(stop.get("title") or "").strip()
        if not title:
            raise ValueError(f"Stop {number} needs a title that says where it goes.")
        stops.append({**stop, "id": f"stop-{number}", "title": title[:80]})
    return stops


def tour(
    web_root: Path,
    out: Path,
    size: tuple[int, int],
    stops: list[dict[str, Any]],
    minutes: float,
    log: Callable[[str], None],
) -> dict[str, Any]:
    """Plays the game; the runtime part of the report, or why it could not."""
    binary = electron()
    if binary is None:
        return {"unavailable": "The playtest needs DazedTL's Electron, which is missing."}
    if not (web_root / "index.html").is_file():
        return {"unavailable": "The game folder has no index.html to play."}
    plan = {
        "stops": [{"id": stop_id, "title": title} for stop_id, title in TOUR[:-1]]
        + stops
        + [{"id": TOUR[-1][0], "title": TOUR[-1][1]}],
        "opening": OPENING_SECONDS,
        "battle": BATTLE_SECONDS,
        "battlebacks": battlebacks(web_root),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    command = [str(binary)]
    if sys.platform.startswith("linux"):
        # No display: the window is offscreen.
        command.append("--ozone-platform=headless")
    command += [
        str(HARNESS), "--game", str(web_root), "--out", str(out),
        "--plan", str(out / "plan.json"), "--width", str(size[0]),
        "--height", str(size[1]), "--minutes", str(minutes),
    ]
    environment = {
        key: value for key, value in os.environ.items()
        if key not in {"ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"}
    }
    titles = {stop["id"]: stop["title"] for stop in plan["stops"]}
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        cwd=str(out),
        text=True,
        encoding="utf-8",
        errors="replace",
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    started = time.monotonic()
    assert process.stdout is not None
    for line in process.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("progress") == "stop":
            log(
                f"Playing {event['index'] + 1} of {event['total']}: "
                f"{titles.get(event['id'], event['id'])}"
            )
        elif event.get("progress") == "crash":
            log(f"The game stopped: {event['note']}")
        if time.monotonic() - started > minutes * 60 + 120:
            break
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    try:
        return json.loads((out / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"unavailable": "The playtest window closed before it wrote its report."}


def _seen(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event[key] for key in ("stop", "scene", "map", "capture") if event.get(key)
    }


def _identity(data: dict[str, Any] | None) -> str:
    return f"{data['file']}#{data['pointer']}" if data else ""


def merge(static: dict[str, Any], runtime: dict[str, Any], data_prefix: str) -> dict[str, Any]:
    """Static problems, with what the tour saw added to them or beside them,
    and the coverage the tour reached."""
    problems = [dict(problem) for problem in static["problems"]]
    gaps = list(static["gaps"])
    by_identity = {problem["identity"]: problem for problem in problems if problem.get("identity")}
    literals = {
        (problem["file"], text["line"]): (problem, text)
        for problem in problems
        if problem["check"] in {"plugin-text", "placeholder-glyph"}
        for text in problem.get("texts", [])
    }

    def seen(problem: dict[str, Any], event: dict[str, Any]) -> None:
        problem.setdefault("seen", _seen(event))

    if "unavailable" in runtime:
        gaps.append(f"The game was not played: {runtime['unavailable']}")
        runtime = {}
    errors: dict[tuple[str, str], dict[str, Any]] = {}
    for event in runtime.get("errors", []):
        if event.get("stop", "").startswith("screen "):
            # The tour opened this screen itself, without what the game sets
            # up first, so its failure says nothing about the game.
            gaps.append(
                f"{event['stop'][7:]} could not be opened on its own: {event['message']}"
            )
            continue
        if event["kind"] == "nwjs":
            gaps.append(
                f"{_where(event)} needs the game's own runtime, which the playtest "
                f"lacks: {event['message']}"
            )
            continue
        located = event.get("source") or {}
        key = (event["message"], located.get("file", ""))
        if key in errors:
            continue
        errors[key] = {
            "kind": "crash",
            "check": "runtime-error" if event["kind"] != "crash" else "runtime-crash",
            "file": located.get("file", ""),
            "note": (
                "The game stopped at its error screen: "
                if event["kind"] == "crash"
                else "A script failed while the game ran: "
            ) + event["message"],
            "fix": "game",
            **({"line": located["line"]} if located.get("line") else {}),
            "seen": _seen(event),
        }
    problems += errors.values()
    for event in runtime.get("japanese", []):
        located = event.get("source") or {}
        match = literals.get((located.get("file"), located.get("line")))
        if match:
            problem, text = match
            text.setdefault("seen", _seen(event))
            seen(problem, event)
            continue
        identity = _identity(event.get("data"))
        target = next(
            (
                problem for problem in problems
                if identity and problem.get("identity", "").startswith(identity)
                or problem["check"] in {"visible-text", "placeholder-glyph"}
                and problem.get("text") and problem["text"] in event["text"]
            ),
            None,
        )
        if target:
            seen(target, event)
            continue
        plugin = located.get("file", "").startswith("js/plugins/")
        problems.append({
            "kind": "japanese",
            "check": "seen-glyph" if event.get("glyph") else "seen-text",
            "file": (f"{data_prefix}/{event['data']['file']}" if event.get("data") else located.get("file", "")),
            "note": (
                "A Japanese placeholder glyph showed on screen."
                if event.get("glyph")
                else "Japanese showed on screen."
            ),
            "fix": "text-qa" if identity else "plugin-files" if plugin else "game",
            "text": event["text"],
            **({"identity": identity} if identity else {}),
            **({"line": located["line"]} if plugin and located.get("line") else {}),
            "seen": _seen(event),
        })
    for event in runtime.get("overflow", []):
        identity = _identity(event.get("data"))
        if identity in by_identity:
            seen(by_identity[identity], event)
            by_identity[identity].setdefault("window", event["window"])
            continue
        engine = event["scene"] in _ENGINE_SCENES and event["window"].startswith("Window_")
        problems.append({
            "kind": "fit",
            "check": "overflow",
            "file": f"{data_prefix}/{event['data']['file']}" if event.get("data") else "",
            "note": (
                f"This text runs past the {'right' if event['edge'] == 'right' else 'bottom'} "
                f"edge of {event['window']} on {event['scene']}"
                + ("." if engine else ", a window sized for the Japanese.")
            ),
            "fix": "text-qa" if identity and engine else "game",
            "text": event["text"],
            "window": event["window"],
            **({"identity": identity} if identity else {}),
            "seen": _seen(event),
        })
    stops = runtime.get("stops", [])
    for stop in stops:
        if stop["id"] == "screens" and stop.get("crashed"):
            gaps.append(
                "Plugin screens: a screen the tour opened on its own stopped the "
                "game, so the screens after it were not opened."
            )
            continue
        if stop["status"] in {"failed", "skipped", "not-reached"}:
            gaps.append(
                f"{stop.get('title') or stop['id']}: "
                + (stop.get("note") or "The tour did not reach it.")
            )
        if stop["id"] == "screens" and stop.get("screens"):
            opened = {scene["scene"] for scene in runtime.get("scenes", [])}
            missed = [name for name in stop["screens"] if name not in opened]
            if missed:
                gaps.append("Plugin screens the tour could not open: " + ", ".join(missed) + ".")
    return {
        "problems": problems,
        "gaps": gaps,
        "coverage": {
            "stops": stops,
            "reached": sum(stop["status"] == "done" for stop in stops),
            "scenes": [scene["scene"] for scene in runtime.get("scenes", [])],
            "messages": (runtime.get("messages") or {}).get("shown", 0),
            "choices": (runtime.get("messages") or {}).get("choices", 0),
            "message_sources": len((runtime.get("messages") or {}).get("sources", {})),
            "battle_lines": runtime.get("battle", 0),
        },
        "captures": runtime.get("captures", []),
        "resolution": runtime.get("resolution"),
        "played": bool(stops),
        "complete": bool(runtime.get("complete")),
    }


def _where(event: dict[str, Any]) -> str:
    located = event.get("source") or {}
    return located.get("file") or event.get("scene") or "A script"


def observations(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The problems text QA can correct, as observations of its lines."""
    found = []
    for problem in report["problems"]:
        if problem.get("fix") != "text-qa" or not problem.get("identity"):
            continue
        category = {
            "japanese": "untranslated",
            "fit": "fit",
            "codes": "control-code",
        }.get(problem["kind"], "meaning")
        note = problem["note"]
        if problem.get("seen"):
            note += f" Seen on {problem['seen'].get('scene', 'screen')} in the playtest."
        found.append({
            "identity": problem["identity"],
            "categories": [category],
            "note": note[:480],
        })
    return found


def run(
    game_root: str | Path,
    data_root: str | Path,
    out: str | Path,
    stops: Any = None,
    minutes: float = DEFAULT_MINUTES,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """The full playtest of one game; writes report.json to `out`."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    extra = read_stops(stops)
    started = time.time()
    log("Checking the game's files")
    static = static_checks(game, data)
    log("Starting the game")
    runtime = tour(data.parent, target, resolution(data), extra, minutes, log)
    merged = merge(static, runtime, data.relative_to(game).as_posix())
    report = {
        "schema": SCHEMA,
        "engine": static["engine"],
        "seconds": round(time.time() - started, 1),
        **merged,
    }
    report["observations"] = observations(report)
    (target / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report
