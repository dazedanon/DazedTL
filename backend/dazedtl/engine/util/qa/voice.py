"""Text QA's voice items: one main speaker's lines from across the game, in
play order, under the speaker's glossary line.

Text QA reads one scene at a time, and translation requests can't see each
other's English, so a character's register can change from scene to scene
with nothing wrong inside any one of them: in Labyrinth City Asylum, 15 of
the 32 requests holding four or more of one character's lines gave her
none of the archaic forms her note asked for, and 17 mixed them. A voice
item puts one speaker's lines side by side, for a reviewer to judge each
against the glossary's voice note and the Japanese.

The builder reads plain lines, never a game's files, so every method's
text can feed it: Text QA gives it an inventory's messages
(util/qa/selection `_voice_items`), and an engine Text QA can't read can
give it Assistant-led's units with their translations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from util.qa.schema import (
    DEFAULT_SCREEN_CHAR_BUDGET,
    DEFAULT_SCREEN_ITEM_LIMIT,
    _canonical_bytes,
    _sha256,
)
from util.rpgmaker_qa_glossary import character_notes

KIND = "voice"
# The speakers read: those with the most lines, so the review a game's voice
# items add stays at this many screen bundles however large the game.
SPEAKER_LIMIT = 6
# A speaker with fewer lines, or lines in one scene alone, is read whole by
# its scenes' own reviews.
MIN_LINES = 12
MIN_SCENES = 2


def voice_items(
    lines: Iterable[Mapping[str, Any]],
    glossary_text: str | None,
    *,
    char_budget: int = DEFAULT_SCREEN_CHAR_BUDGET,
    line_limit: int = DEFAULT_SCREEN_ITEM_LIMIT,
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]]]:
    """One review item for each main speaker of *lines*, and the line each
    of its targets names.

    A line is a mapping with `id` (what a correction of it names: one text,
    wherever it repeats), `speaker` (a name the glossary lists, Japanese or
    English), `source`, `translation`, `scene` (the scene or group that holds
    it, shown beside it) and `order` (its place in play order: lines sort by
    it, so every line's must compare with every other's); any other key is
    the caller's own. Give only the lines to review.

    The main speakers are the SPEAKER_LIMIT with the most lines among those
    the game's glossary describes (rpgmaker_qa_glossary `character_notes`)
    with at least MIN_LINES lines from MIN_SCENES scenes. Each item holds the
    speaker's lines in play order under that glossary line, a repeated text
    once: all of them when they fit one screen bundle, of *char_budget*
    characters and *line_limit* lines, and otherwise lines spread evenly
    from the first to the last, so early, middle and late scenes are read
    alike. Its `speaker_lines` counts the speaker's lines and `target_count`
    those it holds; each line's `id` is a review target of its own, which
    the second value maps to the line given.
    """
    notes = character_notes(glossary_text)
    # A character is its glossary line, whichever of its names a line gives:
    # each one's lines by ID, under the name its first line gives.
    spoken: dict[str, tuple[str, dict[str, Mapping[str, Any]]]] = {}
    for line in sorted(lines, key=lambda line: line["order"]):
        speaker = str(line.get("speaker") or "").strip()
        note = notes.get(speaker.casefold())
        if note is not None:
            spoken.setdefault(note, (speaker, {}))[1].setdefault(str(line["id"]), line)
    main = sorted(
        (
            (speaker, note, list(held.values()))
            for note, (speaker, held) in spoken.items()
            if len(held) >= MIN_LINES
            and len({line["scene"] for line in held.values()}) >= MIN_SCENES
        ),
        key=lambda entry: (-len(entry[2]), entry[0]),
    )[:SPEAKER_LIMIT]
    items = []
    index: dict[str, Mapping[str, Any]] = {}
    for speaker, note, held in main:
        count = min(len(held), line_limit)
        while True:
            item, targets = _item(speaker, note, held, count)
            size = len(_canonical_bytes(item))
            if size <= char_budget or count <= MIN_LINES:
                break
            count = max(MIN_LINES, min(count - 1, count * char_budget // size))
        items.append(item)
        index.update(targets)
    return items, index


def _spread(held: list[Any], count: int) -> list[Any]:
    """*count* of *held*, spread evenly from its first to its last."""
    if count >= len(held) or count < 2:
        return held[:count]
    step = (len(held) - 1) / (count - 1)
    return [held[round(position * step)] for position in range(count)]


def _item(
    speaker: str, note: str, held: list[Mapping[str, Any]], count: int
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """A speaker's item of *count* of its lines, and its targets' lines."""
    targets = {
        "voice-target-" + _sha256(f"{speaker}\0{line['id']}")[:20]: line
        for line in _spread(held, count)
    }
    return {
        "kind": KIND,
        "id": "voice-" + _sha256("\0".join([speaker, *targets]))[:20],
        "speaker": speaker,
        "note": note,
        "speaker_lines": len(held),
        "target_count": len(targets),
        "line_count": len(targets),
        "lines": [
            {
                "id": target,
                "scene": str(line["scene"]),
                "source": line["source"],
                "translation": line["translation"],
            }
            for target, line in targets.items()
        ],
        # One speaker is one read, in a bundle of its own.
        "exclusive_bundle": True,
    }, targets
