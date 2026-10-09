"""Turns the lines Len's extractor saved into a source plan, so the assistant
never has to read or rewrite the game's text to group it into requests.

The extractor knows the engine; this module knows only scenes, order and the
per-line facts the extractor recorded, so it works the same for every engine.
"""

from math import ceil

from .files import digest
from .project import WORK

VERSION = 1
PLANS = WORK + "/work/plans/"
# Requests hold at most the model's entries per request (see
# settings.execution.entries_per_request) and this much source text, which
# keeps one refused or failed request small.
MAX_CHARACTERS = 8000
# Earlier lines of a split scene that travel with each later part.
CONTEXT_LINES = 8
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
EXAMPLE = {
    "version": VERSION,
    "units": [
        {
            "id": "Map001/event3/page0/12",
            "group": "Map001",
            "scene": "Map001/event3/page0",
            "source": "\\C[2]リリ\\C[0]、こっちだよ。",
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


def _context(units):
    return "\n".join(
        (unit["speaker"] + ": " if unit["speaker"] else "") + unit["source"]
        for unit in units
    )


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


def plan(units, input_path, complete, lines):
    """A version-2 source plan: whole scenes of one group and field share a
    request of at most lines units; larger scenes split with their earlier
    lines as context. Each request takes its first line's ID."""
    scenes = []
    for unit in units:
        if not scenes or scenes[-1][0]["scene"] != unit["scene"]:
            scenes.append([])
        scenes[-1].append(unit)
    requests = []
    current = None
    for scene in scenes:
        size = sum(len(unit["source"]) for unit in scene)
        key = (scene[0]["group"], scene[0]["field"])
        if len(scene) > lines or size > MAX_CHARACTERS:
            current = None
            start = 0
            for part in _parts(scene, lines, MAX_CHARACTERS):
                requests.append(
                    {
                        "units": part,
                        "field": key[1],
                        "context": scene[max(0, start - CONTEXT_LINES) : start],
                    }
                )
                start += len(part)
            continue
        if (
            current
            and current["key"] == key
            and len(current["units"]) + len(scene) <= lines
            and current["size"] + size <= MAX_CHARACTERS
        ):
            current["units"] += scene
            current["size"] += size
            continue
        current = {"units": list(scene), "field": key[1], "context": []}
        current.update(key=key, size=size)
        requests.append(current)
    batches = []
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
        if request["field"]:
            batch["instruction_key"] = request["field"]
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
    }


def plan_path(value):
    """Plans are named by their content, so one an older run is bound to is
    never overwritten."""
    return PLANS + digest(value) + ".json"


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
