"""Runs the release playtest and writes the one report the app and the
assistant read: the static checks, then the tour in a hidden window of
DazedTL's own Electron (see util.rpgmaker_window), merged so each problem
shows once with where the tour saw it.

The playtest writes only its output folder; the game folder is read-only to
it, and the tour's saves stay in a session that ends with it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from util import rpgmaker_window
from util.playtest.checks import GROUP_TEXT_LIMIT, HELP_ROWS, static_checks

SCHEMA = "rpgmaker-playtest-report-v1"
LAYOUT_SCHEMA = "rpgmaker-layout-check-v1"
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
LAYOUT_MINUTES = 6
# English for a layout check's lines, cut to the exact width each checks.
LAYOUT_SAMPLE = (
    "Well, I suppose we should keep moving before the snow buries the road "
    "again. Master, look over there, the old bridge is still standing! We can "
    "rest at the village tonight and ask the chief about the mountain shrine. "
    "Nothing about this place makes sense, but I will not give up on finding "
    "a way home for all of us."
).split()
OPENING_SECONDS = 120
BATTLE_SECONDS = 60
# Problems an engine scene shows in its standard help or message window,
# where shorter text fixes them; anywhere else the window is the game's own.
_ENGINE_SCENES = frozenset({
    "Scene_Map", "Scene_Menu", "Scene_Item", "Scene_Skill", "Scene_Equip",
    "Scene_Status", "Scene_Options", "Scene_Save", "Scene_Load", "Scene_GameEnd",
    "Scene_Shop", "Scene_Name", "Scene_Battle", "Scene_Title", "Scene_Gameover",
})


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
    data: Path,
    out: Path,
    stops: list[dict[str, Any]],
    minutes: float,
    log: Callable[[str], None],
    stopped: Callable[[], bool] = lambda: False,
    standard: bool = True,
    overlay: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Plays the game; the runtime part of the report, or why it could not.
    Without the standard tour it only starts a game for `stops`. *overlay*
    serves files, by path under the game's web folder, in place of its own."""
    try:
        web = rpgmaker_window.web_root(data)
    except rpgmaker_window.WindowUnavailable as missing:
        return {"unavailable": str(missing)}
    first = TOUR[:-1] if standard else TOUR[:3]
    plan = {
        "stops": [{"id": stop_id, "title": title} for stop_id, title in first]
        + stops
        + [{"id": TOUR[-1][0], "title": TOUR[-1][1]}],
        "opening": OPENING_SECONDS,
        "battle": BATTLE_SECONDS,
        "battlebacks": battlebacks(web),
    }
    titles = {stop["id"]: stop["title"] for stop in plan["stops"]}

    def status(event: dict[str, Any]) -> str | None:
        if event.get("progress") == "stop":
            return (
                f"Playing {event['index'] + 1} of {event['total']}: "
                f"{titles.get(event['id'], event['id'])}"
            )
        if event.get("progress") == "crash" and event.get("index", 0) > 0:
            # A game that stops before its title, as when the GPU will not
            # draw, is still starting; the report says why.
            return f"The game stopped: {event['note']}"
        return None

    try:
        rpgmaker_window.run(
            HARNESS, web, out, plan,
            seconds=minutes * 60,
            size=rpgmaker_window.screen_size(data),
            overlay=overlay,
            starting="Starting the game",
            status=status,
            log=log,
            stopped=stopped,
        )
    except rpgmaker_window.WindowUnavailable as missing:
        return {"unavailable": str(missing)}
    try:
        return json.loads((out / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"unavailable": "The playtest window closed before it wrote its report."}


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
    gaps = list(static["gaps"])
    if "unavailable" in runtime:
        gaps.append(runtime["unavailable"])
        runtime = {}
    # A description's line count only says where to look: a plugin may draw
    # the help its own way or give the window more lines. It stays a problem
    # where the tour saw the description run past the bottom of its window;
    # one the tour showed otherwise fits, and one it never showed is a gap.
    cut = {
        _identity(event.get("data"))
        for event in runtime.get("overflow", [])
        if event["edge"] == "bottom"
    }
    looked = cut | set(runtime.get("help", []))
    unchecked = [
        problem
        for problem in static["problems"]
        if problem["check"] == "help-rows" and problem["identity"] not in looked
    ]
    problems = [
        dict(problem)
        for problem in static["problems"]
        if problem["check"] != "help-rows" or problem["identity"] in cut
    ]
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
        if event["kind"] == "harness":
            # The tour's own step failed, such as a stop that started an event
            # whose page the game had not turned on; a stop's failure is
            # already among the gaps, with its note.
            if not any(
                event["message"].startswith(stop["id"] + ": ")
                for stop in runtime.get("stops", [])
            ):
                gaps.append(event["message"])
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
    if unchecked:
        gaps.append(_unchecked(unchecked))
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


def _unchecked(problems: list[dict[str, Any]]) -> str:
    """The gap for descriptions longer than the standard help window that the
    tour never showed, by file and entry."""
    entries: dict[str, list[str]] = {}
    for problem in problems[:GROUP_TEXT_LIMIT]:
        name, pointer = problem["identity"].split("#", 1)
        entries.setdefault(name, []).append(pointer.split("/")[1])
    more = len(problems) - GROUP_TEXT_LIMIT
    return (
        f"Descriptions longer than the standard help window's {HELP_ROWS} lines, "
        "which the tour never showed, so whether they fit is unchecked: "
        + "; ".join(f"{name} {', '.join(ids)}" for name, ids in entries.items())
        + (f"; and {more} more" if more > 0 else "")
        + "."
    )


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


LAYOUT_WIDTHS = ("width", "faceWidth", "listWidth", "messageRows")


def read_widths(value: Any) -> dict[str, int]:
    """A layout check's widths, checked: whole characters per line for each
    window and the rows one message shows."""
    if not isinstance(value, dict):
        raise ValueError("Give the layout check's widths as an object.")
    widths = {}
    for key in LAYOUT_WIDTHS:
        number = value.get(key)
        if number is None:
            continue
        limit = 20 if key == "messageRows" else 400
        if type(number) is not int or not 1 <= number <= limit:
            raise ValueError(f"{key} must be a whole number from 1 to {limit}.")
        widths[key] = number
    if not {"width", "faceWidth", "listWidth"} & set(widths):
        raise ValueError("Give at least one of width, faceWidth and listWidth.")
    return widths


def layout_lines(characters: int, count: int) -> list[str]:
    """`count` lines of English prose, each exactly `characters` long."""
    lines = []
    for number in range(count):
        words = LAYOUT_SAMPLE[number * 7 % len(LAYOUT_SAMPLE):] + LAYOUT_SAMPLE
        text = " ".join(words)
        while len(text) <= characters:
            text += " " + " ".join(LAYOUT_SAMPLE)
        line = text[:characters]
        # A line ending at a space would draw one character short.
        lines.append(line[:-1] + "." if line.endswith(" ") else line)
    return lines


def layout_probes(data: Path, widths: dict[str, int]) -> list[dict[str, Any]]:
    """The layout check's stops: a full message window, one under the game's
    first actor face, and a help window, each at its width."""
    rows = int(widths.get("messageRows") or 4)
    face = None
    try:
        for actor in json.loads((data / "Actors.json").read_text(encoding="utf-8-sig")):
            if isinstance(actor, dict) and actor.get("faceName"):
                face = [actor["faceName"], int(actor.get("faceIndex") or 0)]
                break
    except (OSError, ValueError):
        pass
    probes = []
    for key, window, title, count, shown in (
        ("width", "message", "Message", rows, None),
        ("faceWidth", "message", "Message with a face", rows, face),
        ("listWidth", "help", "Help text", 2, None),
    ):
        characters = widths.get(key)
        if not characters or (key == "faceWidth" and not face):
            continue
        probes.append({
            "id": f"layout-{key}",
            "title": f"{title}, {characters} characters",
            "do": "text",
            "window": window,
            "characters": characters,
            "lines": layout_lines(characters, count),
            **({"face": shown} if shown else {}),
        })
    return probes


def layout(
    game_root: str | Path,
    data_root: str | Path,
    out: str | Path,
    widths: dict[str, int],
    log: Callable[[str], None] = print,
    stopped: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Shows English at each width in the game's own windows, measures it
    and captures each; writes layout.json to `out` and changes no game file."""
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    probes = layout_probes(data, widths)
    runtime = tour(data, target, probes, LAYOUT_MINUTES, log, stopped, standard=False)
    reached = {stop["id"]: stop for stop in runtime.get("stops", [])}
    result = {
        "schema": LAYOUT_SCHEMA,
        "widths": widths,
        "probes": runtime.get("layout", []),
        "missing": [
            {
                "title": probe["title"],
                "note": (reached.get(probe["id"]) or {}).get("note", "not reached"),
            }
            for probe in probes
            if probe["title"] not in {row.get("title") for row in runtime.get("layout", [])}
        ],
        "overflow": runtime.get("overflow", []),
        "captures": runtime.get("captures", []),
        **({"unavailable": runtime["unavailable"]} if "unavailable" in runtime else {}),
    }
    (target / "layout.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


def run(
    game_root: str | Path,
    data_root: str | Path,
    out: str | Path,
    stops: Any = None,
    minutes: float = DEFAULT_MINUTES,
    log: Callable[[str], None] = print,
    stopped: Callable[[], bool] = lambda: False,
    previous: dict[str, Any] | None = None,
    kept: Iterable[dict[str, Any]] = (),
    overlay: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """The full playtest of one game; writes report.json to `out`. With the
    previous report, it counts what was fixed since and marks what is new.
    *kept* names the plugin settings the plugin task keeps in Japanese on
    purpose, which it does not report as never translated. *overlay* plays
    files in place of the game's, such as fixes not yet written into it."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    extra = read_stops(stops)
    started = time.time()
    log("Checking the game's files")
    static = static_checks(game, data, kept)
    runtime = tour(data, target, extra, minutes, log, stopped, overlay=overlay)
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
