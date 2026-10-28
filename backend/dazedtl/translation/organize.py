"""Turns the lines Len's extractor saved into a source plan, so the assistant
never has to read or rewrite the game's text to group it into requests.

The extractor knows the engine; this module knows only scenes, order and the
per-line facts the extractor recorded, so it works the same for every engine.
"""

from math import ceil
from pathlib import PurePosixPath

from .files import digest
from .project import WORK
from .requests import result_value, scene_list
from .results import unsent_line

VERSION = 1
PLANS = WORK + "/work/plans/"
# API requests hold at most the model's entries per request (see
# settings.execution.entries_per_request) and this much source text, which
# keeps one refused or failed request small.
MAX_CHARACTERS = 8000
# An assistant translating itself reads each request's shared guidance again,
# so Assistant only uses Len's larger batches of about 200-300 short lines.
AGENT_LINES = 250
AGENT_CHARACTERS = 12000
# Earlier lines of a split scene that travel with each later part.
CONTEXT_LINES = 8
# Organize under this policy writes each unit whose source holds no source
# letters itself (unsent), as Guided writes such text without a request; the
# operation's compile record freezes it, so an organize started before sends
# every unit.
UNSENT = "unsent-lines-v1"
# Organize under this policy packs a scene's lines without a translation
# among its translated ones (unit_results), so each request labels every
# stretch of them with the lines just before it and their translation, as
# Guided labels its reuse stretches, and a split part's context counts the
# scene's translated lines too; an organize frozen without it packs the
# untranslated lines as if they were the whole scene.
NEIGHBOURS = "neighbours-v1"
# A Live run compiled by an organize under this policy sends each later part
# of a split scene after the part before it with the translation that part
# got for the earlier lines the later one quotes (layout's preceding;
# runner.Runner.delivered), as Guided's Live chunks carry the previous
# chunk's English; a Batch builds every request before any result exists,
# and a run frozen without the policy sends its parts with their source
# lines alone.
DELIVERED = "delivered-v1"
KINDS = {"dialogue", "narration", "ui", "unknown"}
FIELDS = {
    "id",
    "group",
    "scene",
    "source",
    "kind",
    "speaker",
    "field",
    "tokens",
    "max_lines",
    "max_characters",
}
# A unit is one message as the player sees it: the lines an engine stores
# apart, such as RPG Maker's consecutive 401 commands, joined by newlines.
EXAMPLE = {
    "version": VERSION,
    "units": [
        {
            "id": "Map001/event3/page0/12",
            "group": "Map001",
            "scene": "Map001/event3/page0",
            "source": "\\C[2]リリ\\C[0]、こっちだよ。\nはやく来て！",
            "kind": "dialogue",
            "speaker": "リリ",
            "tokens": ["\\C[2]", "\\C[0]"],
            "max_lines": 4,
        },
        {
            "id": "Items/1/name",
            "group": "Items",
            "scene": "Items",
            "source": "薬",
            "kind": "ui",
            "speaker": None,
            "field": "database.item",
            "max_characters": 20,
        },
    ],
}


def _named(problem, identities):
    shown = list(dict.fromkeys(identities))
    more = len(shown) - 5
    return ValueError(
        problem
        + ": "
        + ", ".join(shown[:5])
        + (f" and {more} more" if more > 0 else "")
        + "."
    )


def units_input(value):
    """The validated units, with defaults filled in; errors name unit IDs and
    never repeat game text."""
    if not isinstance(value, dict) or set(value) != {"version", "units"}:
        raise ValueError(
            "A source units file is an object with version and units. Use units-format for an example."
        )
    if type(value["version"]) is not int or value["version"] != VERSION:
        raise ValueError("Source units require version 1.")
    units = value["units"]
    if not isinstance(units, list) or not units:
        raise ValueError("The source units file lists no units.")
    result = []
    seen = set()
    problems = {}

    def problem(text, identity):
        problems.setdefault(text, []).append(str(identity))

    for position, unit in enumerate(units):
        if not isinstance(unit, dict) or set(unit) - FIELDS:
            problem("Units accept only the fields units-format shows", position)
            continue
        identity = unit.get("id")
        if (
            not isinstance(identity, str)
            or not identity.strip()
            or len(identity) > 240
            or any(char in identity for char in "\r\n\0")
        ):
            problem(
                "Unit IDs must be single-line text of at most 240 characters; positions",
                position,
            )
            continue
        if identity in seen:
            problem("Unit IDs must be unique", identity)
        seen.add(identity)
        scene = unit.get("scene")
        group = unit.get("group", scene)
        for key, name in ((scene, "scene"), (group, "group")):
            if (
                not isinstance(key, str)
                or not key.strip()
                or len(key) > 200
                or any(char in key for char in "\r\n\0")
            ):
                problem(
                    f"Each unit needs a single-line {name} key of at most 200 characters",
                    identity,
                )
        source = unit.get("source")
        if not isinstance(source, str) or not source.strip():
            problem("Units need nonempty source text", identity)
            continue
        kind = unit.get("kind", "unknown")
        if kind not in KINDS:
            problem("Kind must be dialogue, narration, ui or unknown", identity)
        speaker = unit.get("speaker")
        if speaker is not None and (
            not isinstance(speaker, str)
            or not speaker.strip()
            or any(char in speaker for char in "\r\n\0")
        ):
            problem("Speakers must be single-line names or null", identity)
        if kind == "ui" and speaker is not None:
            problem("UI text has no speaker; use null", identity)
        field = unit.get("field")
        if field is not None and (
            not isinstance(field, str) or field.count(".") != 1 or "\n" in field
        ):
            problem("Fields name a template as section.key", identity)
        tokens = unit.get("tokens", [])
        if not isinstance(tokens, list) or not all(
            isinstance(token, str) and token and token in source for token in tokens
        ):
            problem("Protected tokens must appear in the unit's source", identity)
        for bound in ("max_lines", "max_characters"):
            if bound in unit and (type(unit[bound]) is not int or unit[bound] < 1):
                problem("Layout bounds must be positive whole numbers", identity)
        result.append(
            {
                "id": identity,
                "group": group,
                "scene": scene,
                "source": source,
                "kind": kind,
                "speaker": speaker,
                "field": field,
                "constraints": {
                    key: unit[key]
                    for key in ("tokens", "max_lines", "max_characters")
                    if unit.get(key)
                },
            }
        )
    if problems:
        text, identities = next(iter(problems.items()))
        raise _named(text, identities)
    scenes = {}
    for unit in result:
        scenes.setdefault(unit["scene"], []).append(unit)
    order = list(dict.fromkeys(unit["scene"] for unit in result))
    runs = [
        unit["scene"]
        for previous, unit in zip([None, *result], result)
        if previous is None or previous["scene"] != unit["scene"]
    ]
    if len(runs) != len(order):
        raise _named(
            "Keep each scene's units together, in play order; scenes split apart",
            [scene for scene in order if runs.count(scene) > 1],
        )
    for scene, members in scenes.items():
        if len({unit["group"] for unit in members}) > 1:
            raise _named("A scene belongs to one group", [scene])
        if len({unit["field"] for unit in members}) > 1:
            raise _named(
                "A field template applies to a whole scene; give mid-scene choices kind ui instead",
                [scene],
            )
    return result


def unsent(units, language, target, quotes):
    """A run's record of the units no request sends, by unit ID in play
    order: those whose source holds no letters of the source *language*,
    such as 「……」 or ！？, which the export writes as Guided writes such text
    (results.unsent_line), unless that would change a protected token."""
    from util.source_text import holds_source

    record = {}
    for unit in units:
        source = unit["source"]
        if holds_source(source, language):
            continue
        try:
            result_value(
                {
                    "sources": {unit["id"]: source},
                    "constraints": {unit["id"]: unit["constraints"]},
                },
                {unit["id"]: unsent_line(source, target, quotes)},
            )
        except ValueError:
            continue
        record[unit["id"]] = {
            "source": source,
            "kind": unit["kind"],
            "speaker": unit["speaker"],
        }
    return record


def _line(unit):
    """A unit as context reads it, after its speaker."""
    return (unit["speaker"] + ": " if unit["speaker"] else "") + unit["source"]


def _context(units):
    return "\n".join(_line(unit) for unit in units)


def _parts(scene, lines, characters):
    """A scene too large for one request, in even consecutive parts."""
    count = max(
        ceil(len(scene) / lines),
        ceil(sum(len(unit["source"]) for unit in scene) / characters),
    )
    target = ceil(len(scene) / count)
    parts, current, size = [], [], 0
    for unit in scene:
        if current and (
            len(current) >= target or size + len(unit["source"]) > characters
        ):
            parts.append(current)
            current, size = [], 0
        current.append(unit)
        size += len(unit["source"])
    parts.append(current)
    return parts


def _scenes(units):
    """Units in play order as their scenes' lists."""
    scenes = []
    for unit in units:
        if not scenes or scenes[-1][0]["scene"] != unit["scene"]:
            scenes.append([])
        scenes[-1].append(unit)
    return scenes


def _gaps(scene, answered):
    """Each stretch of a scene's units without a translation that follows
    one with, as its units and the units just before it
    (util/request_packing)."""
    from util.request_packing import STRETCH_CONTEXT, stretches

    for start, end in stretches([unit["id"] in answered or None for unit in scene]):
        if start:
            yield scene[start:end], scene[max(0, start - STRETCH_CONTEXT) : start]


def neighbours(units, answered):
    """The IDs of the units of answered whose translation plan quotes under
    NEIGHBOURS, before a stretch of their scene's other units, so only
    their receipts are read."""
    return list(
        dict.fromkeys(
            unit["id"]
            for scene in _scenes(units)
            for _stretch, before in _gaps(scene, answered)
            for unit in before
            if unit["id"] in answered
        )
    )


def _labelled(members, found):
    """The stretches a request's members begin, each with its first and last
    unit ID in the request and the lines before it; a stretch an earlier
    part of a split scene began is that part's."""
    held = {unit["id"] for unit in members}
    labelled = []
    for unit in members:
        if unit["id"] in found:
            ids, before = found[unit["id"]]
            labelled.append(
                {
                    "first": unit["id"],
                    "last": [identity for identity in ids if identity in held][-1],
                    "before": before,
                }
            )
    return labelled


def plan(
    units,
    input_path,
    complete,
    lines,
    characters=MAX_CHARACTERS,
    shared=None,
    translated=None,
):
    """The source plan layout gives."""
    return layout(units, input_path, complete, lines, characters, shared, translated)[0]


def layout(
    units,
    input_path,
    complete,
    lines,
    characters=MAX_CHARACTERS,
    shared=None,
    translated=None,
):
    """A version-2 source plan, with the unit IDs of the earlier lines each
    later part of a split scene quotes as its context, in order, by the
    part's batch ID (DELIVERED).

    Whole scenes of one group and field share a request of at most lines
    units and characters of source, if each has at most shared lines;
    larger scenes split with their earlier lines as context. A request holding several scenes names which lines belong to
    each, so context stays apart. Each request takes its first line's ID.

    Under NEIGHBOURS, units are whole scenes in play order and translated
    holds those of their units an earlier request answered, by unit ID,
    with the translation the game gets where a request quotes it (None
    elsewhere): only the others are packed, a request lists each stretch of
    them it begins with the lines just before it (stretches), and a later
    part of a split scene takes the scene's real earlier lines as context."""
    scenes = _scenes(units)
    found, place = {}, {}
    if translated is not None:
        whole, scenes = scenes, []
        for scene in whole:
            for stretch, before in _gaps(scene, translated):
                found[stretch[0]["id"]] = (
                    [unit["id"] for unit in stretch],
                    [[_line(unit), translated.get(unit["id"])] for unit in before],
                )
            for position, unit in enumerate(scene):
                place[unit["id"]] = (scene, position)
            left = [unit for unit in scene if unit["id"] not in translated]
            if left:
                scenes.append(left)

    def earlier(part, start, scene):
        if translated is None:
            return scene[max(0, start - CONTEXT_LINES) : start]
        whole, position = place[part[0]["id"]]
        return whole[max(0, position - CONTEXT_LINES) : position]

    requests = []
    current = None
    for scene in scenes:
        size = sum(len(unit["source"]) for unit in scene)
        key = (scene[0]["group"], scene[0]["field"])
        if len(scene) > lines or size > characters:
            current = None
            start = 0
            for part in _parts(scene, lines, characters):
                requests.append(
                    {
                        "units": part,
                        "field": key[1],
                        "context": earlier(part, start, scene) if start else [],
                    }
                )
                start += len(part)
            continue
        if shared is not None and len(scene) > shared:
            current = None
            requests.append({"units": list(scene), "field": key[1], "context": []})
            continue
        if (
            current
            and current["key"] == key
            and len(current["units"]) + len(scene) <= lines
            and current["size"] + size <= characters
        ):
            current["units"] += scene
            current["size"] += size
            continue
        current = {"units": list(scene), "field": key[1], "context": []}
        current.update(key=key, size=size)
        requests.append(current)
    batches, preceding = [], {}
    for request in requests:
        members = request["units"]
        batch = {
            "id": members[0]["id"],
            "sources": {unit["id"]: unit["source"] for unit in members},
            "kinds": {unit["id"]: unit["kind"] for unit in members},
            "speakers": {unit["id"]: unit["speaker"] for unit in members},
        }
        if request["context"]:
            batch["source_context"] = _context(request["context"])
            preceding[batch["id"]] = [unit["id"] for unit in request["context"]]
        scenes = {}
        for unit in members:
            scenes.setdefault(unit["scene"], []).append(unit["id"])
        if len(scenes) > 1:
            batch["scene_context"] = scene_list(scenes.items())
        if request["field"]:
            batch["instruction_key"] = request["field"]
        labelled = _labelled(members, found)
        if labelled:
            batch["stretches"] = labelled
        constraints = {
            unit["id"]: unit["constraints"] for unit in members if unit["constraints"]
        }
        if constraints:
            batch["constraints"] = constraints
        batches.append(batch)
    return {
        "version": 2,
        "complete": complete,
        "inputs": [input_path],
        "batches": batches,
    }, preceding


def plan_path(value):
    """Plans are named by their content, so one an older run is bound to is
    never overwritten."""
    return PLANS + digest(value) + ".json"


def owns(relative):
    """Whether a game-relative path names one of organize's plans. Only
    organize compiles them: its run also carries the lines it left out with
    an earlier translation (run_compiler.compile_run's reused), which the
    plan doesn't hold."""
    return (
        str(PurePosixPath(relative).parent).casefold() == PLANS.rstrip("/").casefold()
    )


def summary(units, value):
    kinds = {}
    for unit in units:
        kinds[unit["kind"]] = kinds.get(unit["kind"], 0) + 1
    return {
        "units": len(units),
        "requests": len(value["batches"]),
        "scenes": len({unit["scene"] for unit in units}),
        "kinds": kinds,
        "named_speakers": sum(unit["speaker"] is not None for unit in units),
        "plan": plan_path(value),
    }
