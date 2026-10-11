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
import queue
import shutil
import signal
import subprocess
import sys
import threading
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
    stopped: Callable[[], bool] = lambda: False,
    software: bool = False,
) -> dict[str, Any]:
    """Plays the game; the runtime part of the report, or why it could not."""
    binary = electron()
    if binary is None:
        return {"unavailable": "The playtest needs DazedTL's Electron, which is missing."}
    if not (web_root / "index.html").is_file():
        return {"unavailable": "The game folder has no index.html to play."}
    if not any((web_root / "js" / name).is_file() for name in ("rmmz_core.js", "rpg_core.js")):
        return {"unavailable": "The game folder has no RPG Maker engine scripts to play."}
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
    linux = sys.platform.startswith("linux")
    if linux:
        # The window is offscreen and needs no display.
        command.append("--ozone-platform=headless")
    # WebGL draws with the GPU, through the display on Linux, and with
    # SwiftShader on the CPU where there is none.
    if software or linux and not os.environ.get("DISPLAY"):
        command.append("--use-angle=swiftshader")
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
        # Its own process group, so a stop ends Electron's helpers with it.
        **(
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        ),
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + minutes * 60 + 120
    status = "Starting the game"
    said = time.monotonic()
    try:
        while True:
            if stopped():
                raise InterruptedError("The playtest was stopped.")
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                line = ""
            if line is None or time.monotonic() > deadline:
                break
            try:
                event = json.loads(line) if line else {}
            except ValueError:
                event = {}
            if event.get("progress") == "stop":
                status = (
                    f"Playing {event['index'] + 1} of {event['total']}: "
                    f"{titles.get(event['id'], event['id'])}"
                )
            elif event.get("progress") == "crash" and event.get("index", 0) > 0:
                # A game that stops before its title, as when the GPU will
                # not draw, is still starting; the report says why.
                status = f"The game stopped: {event['note']}"
            elif event.get("progress") == "done":
                break
            # Progress at least every 20 seconds, so a long stop never reads
            # as a stalled action.
            if event.get("progress") in {"stop", "crash"} or time.monotonic() - said > 20:
                log(status)
                said = time.monotonic()
    finally:
        # Electron gets a moment to exit after its report, unless the user
        # stopped the playtest; then it is ended.
        try:
            process.wait(timeout=0 if stopped() else 30)
        except subprocess.TimeoutExpired:
            pass
        if process.poll() is None:
            _end(process)
        process.wait()
        # The tour's saves and caches, which Windows keeps locked until
        # Electron has exited.
        shutil.rmtree(out / ".profile", ignore_errors=True)
    try:
        return json.loads((out / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"unavailable": "The playtest window closed before it wrote its report."}


def _not_started(runtime: dict[str, Any]) -> bool:
    """The game never reached its title, as when the GPU will not draw for an
    offscreen window."""
    stops = runtime.get("stops") or []
    return "unavailable" not in runtime and (
        not stops or stops[0].get("status") != "done"
    )


def _end(process: subprocess.Popen) -> None:
    """Ends Electron and the processes it started."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def _seen(event: dict[str, Any], titles: dict[str, str] | None = None) -> dict[str, Any]:
    """Where the tour saw something: its stop by title, screen, map and capture."""
    seen = {
        key: event[key] for key in ("stop", "scene", "map", "capture") if event.get(key)
    }
    if titles and seen.get("stop") in titles:
        seen["stop"] = titles[seen["stop"]]
    return seen


def _identity(data: dict[str, Any] | None) -> str:
    return f"{data['file']}#{data['pointer']}" if data else ""


def merge(static: dict[str, Any], runtime: dict[str, Any], data_prefix: str) -> dict[str, Any]:
    """Static problems, with what the tour saw added to them or beside them,
    and the coverage the tour reached."""
    problems = [dict(problem) for problem in static["problems"]]
    gaps = list(static["gaps"])
    titles = {
        stop["id"]: stop.get("title") or stop["id"] for stop in runtime.get("stops", [])
    }
    by_identity = {problem["identity"]: problem for problem in problems if problem.get("identity")}
    literals = {
        (problem["file"], text["line"]): (problem, text)
        for problem in problems
        if problem["check"] in {"plugin-text", "placeholder-glyph"}
        for text in problem.get("texts", [])
    }

    def seen(problem: dict[str, Any], event: dict[str, Any]) -> None:
        problem.setdefault("seen", _seen(event, titles))

    if "unavailable" in runtime:
        gaps.append(runtime["unavailable"])
        runtime = {}
    errors: dict[tuple[str, str], dict[str, Any]] = {}
    # The engine writes the error that stopped the game to the console too.
    crashes = [
        event["message"] for event in runtime.get("errors", []) if event["kind"] == "crash"
    ]
    for event in runtime.get("errors", []):
        if event["kind"] != "crash" and any(
            event["message"].split("\n", 1)[0] in crash for crash in crashes
        ):
            continue
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
            "seen": _seen(event, titles),
        }
    problems += errors.values()
    # A plugin draws its strings from a drawing call elsewhere in its code,
    # so the text itself ties what was drawn to the string.
    by_text: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for problem, text in literals.values():
        by_text.setdefault(text["text"].strip(), []).append((problem, text))
    for event in runtime.get("japanese", []):
        located = event.get("source") or {}
        match = literals.get((located.get("file"), located.get("line")))
        drawn = event["text"].strip()
        found = by_text.get(drawn) or (
            # A line a plugin wrapped from a longer string.
            [row for key, rows in by_text.items() if drawn in key for row in rows]
            if len(drawn) >= 4
            else []
        )
        if not match and found:
            match = next(
                (row for row in found if row[0]["file"] == located.get("file")), found[0]
            )
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
            "seen": _seen(event, titles),
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
            **({"pointer": event["data"]["pointer"]} if event.get("data") else {}),
            "note": (
                f"This text runs past the {'right' if event['edge'] == 'right' else 'bottom'} "
                f"edge of {event['window']} on {event['scene']}"
                + ("." if engine else ", a window sized for the Japanese.")
            ),
            "fix": "text-qa" if identity and engine else "game",
            "text": event["text"],
            "window": event["window"],
            **({"identity": identity} if identity else {}),
            "seen": _seen(event, titles),
        })
    stops = runtime.get("stops", [])
    for stop in stops:
        if stop["id"] == "screens" and stop.get("stopped"):
            # The tour opened them without what the game sets up first, so
            # players may never open them this way.
            gaps.append(
                "Plugin screens that stopped the game when the tour opened them "
                "on their own: " + ", ".join(stop["stopped"]) + "."
            )
        if stop["id"] == "screens" and stop.get("crashed"):
            stop["note"] = (
                "A screen the tour opened on its own stopped the game, so the "
                "screens after it were not opened."
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
        "played": any(stop["status"] == "done" for stop in stops),
        "complete": bool(runtime.get("complete")),
    }


def _where(event: dict[str, Any]) -> str:
    located = event.get("source") or {}
    return located.get("file") or event.get("scene") or "A script"


def _keys(problem: dict[str, Any]) -> list[tuple]:
    """What identifies a problem across runs: each of a group's strings, or
    the problem's place and text."""
    base = (problem["check"], problem["file"])
    if problem.get("texts"):
        return [base + (text["text"],) for text in problem["texts"]]
    return [base + (problem.get("pointer") or problem.get("line") or "", problem.get("text", ""))]


def compare(previous: dict[str, Any], report: dict[str, Any]) -> dict[str, int]:
    """Problems fixed since the previous run and new in this one; a group's
    strings count one by one. Marks the new problems."""
    before = {key for problem in previous.get("problems", []) for key in _keys(problem)}
    now = set()
    new = 0
    for problem in report["problems"]:
        keys = _keys(problem)
        now.update(keys)
        if not any(key in before for key in keys):
            problem["new"] = True
            new += 1
    return {"fixed": len(before - now), "new": new}


def observations(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The problems text QA can correct, as observations of its lines."""
    found = []
    for problem in report["problems"]:
        if problem.get("fix") != "text-qa" or not problem.get("identity"):
            continue
        category = {"japanese": "meaning", "fit": "ui", "codes": "runtime"}.get(
            problem["kind"], "other"
        )
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
    stopped: Callable[[], bool] = lambda: False,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The full playtest of one game; writes report.json to `out`. With the
    previous report, it counts what was fixed since and marks what is new."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    extra = read_stops(stops)
    started = time.time()
    log("Checking the game's files")
    static = static_checks(game, data)
    log("Starting the game")
    size = resolution(data)
    runtime = tour(data.parent, target, size, extra, minutes, log, stopped)
    if _not_started(runtime):
        # The GPU may not draw for an offscreen window; play on the CPU.
        log("Starting the game again without the GPU")
        runtime = tour(data.parent, target, size, extra, minutes, log, stopped, True)
    merged = merge(static, runtime, data.relative_to(game).as_posix())
    report = {
        "schema": SCHEMA,
        "engine": static["engine"],
        "seconds": round(time.time() - started, 1),
        **merged,
    }
    report["observations"] = observations(report)
    if previous:
        report["since"] = compare(previous, report)
    (target / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report
