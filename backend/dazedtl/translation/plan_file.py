"""A run's frozen plan as saved in its plan.json.

Every request of a run carries the same shared guidance, and an API
request's provider payload repeats it: 2,648 requests of a large game made a
165 MB plan, two thirds of it one system prompt. Format 2 saves each long
context text that occurs more than once in the plan a single time, keyed by
its hash, with the places each request holds it, and rebuilds exactly the
same plan when read. The file's own bytes bind it, which is far cheaper to
check than serializing the whole plan again.

Plans saved before this format hold the plan itself, bound by its digest,
and keep loading unchanged.
"""

import json
from collections import Counter

from dazedtl import system

from .files import decode_json, digest

FORMAT = 2
CHANGED = "The saved request plan changed. It cannot be executed."
# Shorter context text stays where it is; a reference would save little.
SHARED = 1024


def _strings(value, path):
    """Each string of at least SHARED characters below value, with its path."""
    stack = [(value, path)]
    while stack:
        value, path = stack.pop()
        if isinstance(value, str):
            if len(value) >= SHARED:
                yield path, value
        elif isinstance(value, dict):
            stack.extend((item, (*path, key)) for key, item in value.items())
        elif isinstance(value, list):
            stack.extend((item, (*path, index)) for index, item in enumerate(value))


def _spans(text, candidates):
    """Where the candidate texts occur in text, longest first, without
    overlapping, in order as (start, end, candidate)."""
    found = []
    for candidate in candidates:
        start = text.find(candidate)
        while start >= 0:
            end = start + len(candidate)
            if all(end <= first or start >= last for first, last, _ in found):
                found.append((start, end, candidate))
            start = text.find(candidate, end)
    return sorted(found)


def _replaced(container, path, value):
    """container with the item at path replaced, copying only along path."""
    if not path:
        return value
    copy = list(container) if isinstance(container, list) else dict(container)
    copy[path[0]] = _replaced(container[path[0]], path[1:], value)
    return copy


def encode(plan):
    """The bytes that save plan."""
    found, counts = [], Counter()
    for row in plan.get("requests", []):
        candidates = sorted(
            {
                value
                for value in row.get("context", {}).values()
                if isinstance(value, str) and len(value) >= SHARED
            },
            key=lambda text: (-len(text), text),
        )
        places = []
        if candidates:
            for path, text in _strings(row, ()):
                spans = _spans(text, candidates)
                if spans:
                    places.append((path, text, spans))
                    counts.update(candidate for _start, _end, candidate in spans)
        found.append(places)
    keys = {text: digest(text.encode("utf-8")) for text, n in counts.items() if n > 1}
    requests, splices = [], []
    for row, places in zip(plan.get("requests", []), found):
        inserts = []
        for path, text, spans in places:
            kept, length, at, offsets = [], 0, 0, []
            for start, end, candidate in spans:
                if candidate in keys:
                    kept.append(text[at:start])
                    length += start - at
                    offsets.append([length, keys[candidate]])
                    at = end
            if offsets:
                kept.append(text[at:])
                row = _replaced(row, path, "".join(kept))
                inserts.append([list(path), offsets])
        requests.append(row)
        splices.append(inserts)
    document = {
        "format": FORMAT,
        "texts": {key: text for text, key in keys.items()},
        "plan": {**plan, "requests": requests} if "requests" in plan else plan,
        "splices": splices,
    }
    return (
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def read(path, expected):
    """The plan saved at path, which must be the plan whose digest the run
    recorded as expected."""
    raw = system.read_bytes(path)
    value = decode_json(raw)
    if not (
        isinstance(value, dict)
        and set(value) == {"format", "texts", "plan", "splices"}
        and value["format"] == FORMAT
    ):
        # A plan saved whole, before format 2. Its digest serializes the
        # whole plan again, so the file's bytes are released first.
        del raw
        if digest(value) != expected:
            raise ValueError(CHANGED)
        return value
    if digest(raw) != expected:
        raise ValueError(CHANGED)
    del raw
    plan, texts = value["plan"], value["texts"]
    try:
        rows = plan.get("requests", [])
        if len(rows) != len(value["splices"]):
            raise ValueError
        for row, inserts in zip(rows, value["splices"]):
            for place, offsets in inserts:
                container = row
                for key in place[:-1]:
                    container = container[key]
                kept, pieces, at = container[place[-1]], [], 0
                for offset, key in offsets:
                    pieces += [kept[at:offset], texts[key]]
                    at = offset
                pieces = [piece for piece in [*pieces, kept[at:]] if piece]
                # A whole value stays the one shared string, so a plan
                # read into memory holds its guidance once too.
                container[place[-1]] = (
                    pieces[0] if len(pieces) == 1 else "".join(pieces)
                )
    except ValueError, LookupError, TypeError, AttributeError:
        raise ValueError("The saved request plan cannot be read.") from None
    return plan
