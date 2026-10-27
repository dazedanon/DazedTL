"""Runs the release playtest and writes the one report the app and the
assistant read: the static checks, then the tour in a hidden window of
DazedTL's own Electron (see util.rpgmaker_window), merged so each problem
shows once with where the tour saw it.

The playtest writes only its output folder; the game folder is read-only to
it, and the tour's saves stay in a session that ends with it.
"""

from __future__ import annotations

import json
import math
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Iterable

from util import languages, rpgmaker_blocks, rpgmaker_fonts, rpgmaker_window
from util.dazedwrap import breaks_characters, cells
from util.original_values import Originals
from util.game_settings import game_source_language, game_target_language
from util.playtest.checks import GROUP_TEXT_LIMIT, HELP_ROWS, reading, static_checks
from util.rpgmaker_markers import comment_markers, data_plugins
from util.rpgmaker_qa_preflight import pointer

SCHEMA = "rpgmaker-playtest-report-v1"
LAYOUT_SCHEMA = "rpgmaker-layout-check-v2"
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
# Prose for a layout check's lines in the game's target language, cut to the
# exact width each checks: English, or for a target that breaks between
# characters its own (see util.dazedwrap.breaks_characters).
LAYOUT_SAMPLE = (
    "Well, I suppose we should keep moving before the snow buries the road "
    "again. Master, look over there, the old bridge is still standing! We can "
    "rest at the village tonight and ask the chief about the mountain shrine. "
    "Nothing about this place makes sense, but I will not give up on finding "
    "a way home for all of us."
).split()
LAYOUT_SAMPLES = {
    "japanese": (
        "雪が道を埋める前に、そろそろ先へ進まないとね。ほら、あそこを見て！"
        "古い橋がまだ残ってる。今夜は村で休んで、山の祠のことを村長に聞いて"
        "みよう。わからないことばかりだけど、みんなで家に帰る方法をあきらめないよ。"
    ),
    "chinese": (
        "我们得在大雪再次掩埋道路之前继续前进。快看那边，那座旧桥还在！今晚"
        "可以在村子里休息，再向村长打听山上神社的事。这里的一切都说不通，但我"
        "绝不会放弃为大家找到回家的路。"
    ),
}
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
        "blocks": block_index(data, overlay),
        "stops": [{"id": stop_id, "title": title} for stop_id, title in first]
        + stops
        + [{"id": TOUR[-1][0], "title": TOUR[-1][1]}],
        "opening": OPENING_SECONDS,
        "battle": BATTLE_SECONDS,
        "battlebacks": battlebacks(web),
        "source": reading(),
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


_EVENT_FILES = ("CommonEvents.json", "Troops.json")


def block_index(data: Path, overlay: dict[str, Path] | None = None) -> dict[str, Any]:
    """The text blocks of every event command list the game plays, by file
    and list pointer, for the tour to name what it sees as the static checks
    do (see harness/page.js textBlocks). *overlay* holds files played in
    place of the game's."""
    markers = comment_markers(data_plugins(data))
    files = {path.name: path for path in data.glob("*.json")}
    # The web folder holds the data folder (see rpgmaker_window.web_root).
    prefix = data.name
    for relative, path in (overlay or {}).items():
        if relative.startswith(prefix + "/") and "/" not in relative[len(prefix) + 1 :]:
            files[relative[len(prefix) + 1 :]] = Path(path)
    index: dict[str, Any] = {}
    for name, path in sorted(files.items()):
        if not (name in _EVENT_FILES or (name.startswith("Map") and name[3:-5].isdigit())):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        lists: dict[str, list] = {}
        for parts, commands in rpgmaker_blocks.command_lists(document):
            found = [
                [
                    block.kind,
                    -1 if block.head is None else block.head,
                    block.rows[0],
                    block.rows[-1],
                    int(not any(
                        part.translated and set(part.rows) & set(block.rows)
                        for part in block.parts
                    )),
                    block.marker,
                    int(block.shown(markers)),
                ]
                for block in rpgmaker_blocks.blocks(commands)
                if block.rows and block.kind != rpgmaker_blocks.CHOICE
            ]
            if found:
                lists[pointer(parts)] = found
        if lists:
            index[name] = lists
    return index


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


def _within(pointer: str, parent: str) -> bool:
    """Whether a JSON pointer is *parent* or inside it."""
    return pointer == parent or pointer.startswith(parent + "/")


def _holds(data: dict[str, Any], pointer: str) -> bool:
    """Whether what the tour saw, a block of text rows or a value, holds the
    value at *pointer* of its data file."""
    if "last" not in data:
        return _within(pointer, data["pointer"])
    base, first = data["pointer"].rsplit("/", 1)
    return any(
        _within(pointer, f"{base}/{row}") for row in range(int(first), int(data["last"]) + 1)
    )


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
    # Each line the static check found never translated, by its data file.
    never: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for problem in problems:
        if problem["check"] == "untranslated":
            for text in problem.get("texts", []):
                if "pointer" in text:
                    never.setdefault(problem["file"], []).append((problem, text))
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
        data = event.get("data") or {}
        identity = _identity(data)
        # Text the engine never translated is translation's to fix: text QA
        # reviews only what was translated.
        untranslated = bool(data.get("untranslated"))
        if untranslated:
            listed = next(
                (
                    row for row in never.get(f"{data_prefix}/{data['file']}", [])
                    if _holds(data, row[1]["pointer"])
                ),
                None,
            )
            if listed:
                listed[1].setdefault("seen", _seen(event))
                seen(listed[0], event)
                continue
        target = next(
            (
                problem for problem in problems
                if identity and problem.get("identity", "").startswith(f"{data['file']}#")
                and _holds(data, problem["identity"].split("#", 1)[1])
                or problem["check"] in {"visible-text", "placeholder-glyph"}
                and problem.get("text") and problem["text"] in event["text"]
            ),
            None,
        )
        if target:
            seen(target, event)
            continue
        plugin = located.get("file", "").startswith("js/plugins/")
        comment = untranslated and "comment" in data
        problems.append({
            "kind": "japanese",
            # DazedTL translates the comments under a marker it knows players
            # read once comment text is on.
            "check": (
                "untranslated-comment"
                if comment and data.get("shown")
                else "seen-glyph" if event.get("glyph") else "seen-text"
            ),
            "file": (f"{data_prefix}/{event['data']['file']}" if event.get("data") else located.get("file", "")),
            "note": (
                "A plugin shows this event comment, which was never translated."
                if comment
                else "This text was never translated."
                if untranslated
                else "A Japanese placeholder glyph showed on screen."
                if event.get("glyph")
                else f"{languages.active_source()} showed on screen."
            ),
            "fix": (
                "translate" if untranslated
                else "text-qa" if identity
                else "plugin-files" if plugin
                else "game"
            ),
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
                + ("." if engine else f", a window sized for the {languages.active_source()}.")
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


def observation(problem: dict[str, Any]) -> dict[str, Any] | None:
    """A problem text QA can correct, as an observation of its line; None
    for any other problem."""
    if problem.get("fix") != "text-qa" or not problem.get("identity"):
        return None
    category = {"japanese": "meaning", "fit": "ui", "codes": "runtime"}.get(
        problem["kind"], "other"
    )
    note = problem["note"]
    if problem.get("seen"):
        note += f" Seen on {problem['seen'].get('scene', 'screen')} in the playtest."
    return {
        "identity": problem["identity"],
        "categories": [category],
        # One line, cut short, as QA keeps an observation's note, so the
        # problem's label finds it there.
        "note": " ".join(note.split())[:480].rstrip(),
    }


def observations(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The problems text QA can correct, as observations of its lines."""
    return [found for problem in report["problems"] if (found := observation(problem))]


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


def layout_lines(characters: int, count: int, target: str = "English") -> list[str]:
    """`count` lines of prose in *target*, each exactly `characters` long:
    English, or for a target that breaks between characters its own prose,
    each line exactly `characters` half-width cells (see
    util.dazedwrap.cells), as Line widths count them."""
    if breaks_characters(target):
        return _full_width_lines(characters, count, target)
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


def _full_width_lines(characters: int, count: int, target: str) -> list[str]:
    sample = LAYOUT_SAMPLES.get(languages.script(target), LAYOUT_SAMPLES["japanese"])
    lines = []
    for number in range(count):
        start = number * 11 % len(sample)
        text, width = "", 0
        for character in (sample[start:] + sample) * (characters // len(sample) + 2):
            if width + cells(character) > characters:
                break
            text, width = text + character, width + cells(character)
        # When a full-width character is too wide for the last cell, a
        # half-width full stop takes it.
        lines.append(text + "." * (characters - width))
    return lines


# The characters a width keeps spare on a window's widest line: a width that
# fits to the last pixel leaves no room for a glyph the game's font lacks,
# which the fallback font draws at a width that varies by operating system.
LAYOUT_HEADROOM = 3


def layout_probes(
    data: Path,
    widths: dict[str, int],
    glyphs: Iterable[str] = (),
    target: str = "English",
) -> list[dict[str, Any]]:
    """The layout check's stops: a full message window, one under the game's
    first actor face, and a help window, each at its width, in prose of the
    game's *target* language. The first also measures *glyphs*, the
    characters the game's font lacks."""
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
            "lines": layout_lines(characters, count, target),
            **({"face": shown} if shown else {}),
        })
    if probes and glyphs:
        probes[0]["glyphs"] = list(glyphs)
    return probes


def layout_fit(measured: dict[str, Any]) -> dict[str, Any]:
    """A layout probe as the game measured it, with the room it keeps spare.
    Its lines fit when the window shows every row and keeps LAYOUT_HEADROOM
    characters spare after the widest line, counted at that line's average
    character width; *suggested* is the most characters that keep it."""
    widest, room = measured["widest"], measured["room"]
    row = {**measured, "spare": room - widest}
    if widest <= 0:
        return {**row, "fits": False}
    # Each line is exactly `characters` long (see layout_lines).
    most = math.floor(room * measured["characters"] / widest)
    return {
        **row,
        "spareCharacters": most - measured["characters"],
        "suggested": most - LAYOUT_HEADROOM,
        "fits": measured["lines"] <= measured["rows"]
        and most - measured["characters"] >= LAYOUT_HEADROOM,
    }


def layout(
    game_root: str | Path,
    data_root: str | Path,
    out: str | Path,
    widths: dict[str, int],
    log: Callable[[str], None] = print,
    stopped: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Shows prose in the game's target language at each width in the game's
    own windows, measures it and captures each; writes layout.json to `out`
    and changes no game file.

    It plays only the title, New Game and the opening, and keeps its own
    reports apart from the playtest's. It confirms a setup task's measured
    widths on screen where that task had improvised a browser session, and
    lists the characters of the game's text its font lacks, as wide as its
    message window draws them."""
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    log("Reading the game's font")
    try:
        fallback = rpgmaker_fonts.fallback_glyphs(data, _source(game_root))
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        # The widths are the check's job; a game the scan cannot read still gets them.
        fallback = {"unread": f"The game's text could not be read for its font: {error}"}
    probes = layout_probes(
        data,
        widths,
        [glyph["character"] for glyph in fallback.get("glyphs", [])],
        game_target_language(game_root),
    )
    runtime = tour(data, target, probes, LAYOUT_MINUTES, log, stopped, standard=False)
    reached = {stop["id"]: stop for stop in runtime.get("stops", [])}
    measured = [layout_fit(row) for row in runtime.get("layout", [])]
    drawn = next((row for row in measured if row.get("glyphs") and row["widest"] > 0), None)
    for glyph in fallback.get("glyphs", []):
        pixels = drawn["glyphs"].get(glyph["character"]) if drawn else None
        if pixels is not None:
            # In the probe line's characters, the unit Line widths count.
            glyph["pixels"] = pixels
            glyph["drawn"] = round(pixels * drawn["characters"] / drawn["widest"], 1)
    result = {
        "schema": LAYOUT_SCHEMA,
        "widths": widths,
        "headroom": LAYOUT_HEADROOM,
        "probes": [
            {key: value for key, value in row.items() if key != "glyphs"}
            for row in measured
        ],
        "fallback": fallback,
        "missing": [
            {
                "title": probe["title"],
                "note": (reached.get(probe["id"]) or {}).get("note", "not reached"),
            }
            for probe in probes
            if probe["title"] not in {row.get("title") for row in measured}
        ],
        "overflow": runtime.get("overflow", []),
        "captures": runtime.get("captures", []),
        **({"unavailable": runtime["unavailable"]} if "unavailable" in runtime else {}),
    }
    (target / "layout.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


def _source(game_root: str | Path) -> str | None:
    """The source language of the game at *game_root*, or None, the active
    source, when its settings can't be read."""
    try:
        return game_source_language(game_root)
    except (OSError, ValueError):
        return None


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
    literals: Iterable[dict[str, Any]] = (),
    originals: Originals | None = None,
) -> dict[str, Any]:
    """The full playtest of one game; writes report.json to `out`. With the
    previous report, it counts what was fixed since and marks what is new.
    *kept* names the plugin settings the plugin task keeps in Japanese on
    purpose, which it does not report as never translated, and *literals* the
    strings in plugin code, which it reports only once drawn. *overlay* plays
    files in place of the game's, such as fixes not yet written into it.
    *originals*, the game's original files where the app recorded them, give
    text that keeps no source its source (util/original_values)."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    extra = read_stops(stops)
    started = time.time()
    source = _source(game)
    with (
        languages.reading(source, game_target_language(game))
        if source
        else nullcontext()
    ):
        log("Checking the game's files")
        static = static_checks(game, data, kept, literals, originals)
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
