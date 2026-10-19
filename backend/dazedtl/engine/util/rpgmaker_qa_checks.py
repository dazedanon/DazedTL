"""Deterministic checks that send database text to deep review.

Each check finds a defect that sits between texts a reviewer reads apart: two
entries of one database that show the same English name, and a battle message
that RPG Maker's battler name leaves without a subject or runs into. A check
only escalates; a deep reviewer judges the text and writes any correction. A
glossary term rendered another way is the glossary lint family's.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

# Players never read MapInfos.json names; a map shows its own display name.
UNSEEN_NAMES = frozenset({"MapInfos.json"})
# Battle messages RPG Maker joins to the battler's name: MZ formats the name
# into %1, and MV writes the name directly before the message.
BATTLE_MESSAGES = {
    "MZ": {
        "Skills.json": ("message1", "message2"),
        "States.json": ("message1", "message2", "message3", "message4"),
    },
    "MV": {
        "Skills.json": ("message1",),
        "States.json": ("message1", "message2", "message3", "message4"),
    },
}
# Other entries a collision names before it only counts the rest.
COLLISION_LIMIT = 6
# A particle opening a battle message's source, as in は幻惑に囚われた！, shows
# the game meant the battler's name to stand before it.
_PARTICLE_START_RE = re.compile(r"^[はがのをにへともで](?![ぁ-ゖ])")
# English opening with a verb has no subject of its own, as in "Was caught in
# an Illusion!" or "Called for allies!".
_VERB_START_RE = re.compile(
    r"^(?:(?:was|were|is|are|has|have|had|will|would|can|could|cannot|can't|"
    r"won't|isn't|wasn't|doesn't|didn't|does|did|gets|got|became|becomes|"
    r"fell|falls|took|takes|lost|loses|began|begins|feels|felt|seems|looks)"
    r"(?![\w'])|\w+ed\b)",
    re.IGNORECASE,
)


def runtime(data_root: str | Path) -> str:
    """The RPG Maker runtime beside a data folder: "MZ", "MV", or "" when unknown."""
    scripts = Path(data_root).parent / "js"
    if (scripts / "rmmz_core.js").is_file():
        return "MZ"
    if (scripts / "rpg_core.js").is_file():
        return "MV"
    return ""


def _key(text: str) -> str:
    """Letters and digits only, so spacing, punctuation and case never count."""
    return "".join(
        char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum()
    )


def _term(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _entry(record: dict[str, Any]) -> str:
    entity = record.get("database_entity") or {}
    return f"{record['file']} {entity.get('id')} {record['source']}"


def _collisions(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        field = (record.get("database_entity") or {}).get("field")
        key = _key(str(record["live"]))
        if field == "name" and key and record["file"] not in UNSEEN_NAMES:
            groups[(record["file"], key)].append(record)
    notes: dict[str, list[str]] = defaultdict(list)
    for group in groups.values():
        if len({_term(str(record["source"])) for record in group}) < 2:
            continue
        for record in group:
            others = [
                _entry(other) for other in group
                if _term(str(other["source"])) != _term(str(record["source"]))
            ]
            more = len(others) - COLLISION_LIMIT
            notes[record["identity"]].append(
                f'Also shown as "{record["live"]}": '
                + "; ".join(others[:COLLISION_LIMIT])
                + (f" and {more} more" if more > 0 else "")
            )
    return notes


def battler_name_note(engine: str, live: str, source: str = "") -> str:
    """Why a battle message reads wrong once RPG Maker adds the battler's
    name, or "" when it reads right."""
    if not live.strip() or "%1" in live:
        return ""
    if engine == "MZ":
        # The name goes only where %1 is, so a predicate such as "was freed",
        # "'s Illusion" or, after a source that starts with a particle,
        # "Called for allies!" has no subject.
        text = re.sub(r"^[\s\"“”'’….]+", "", live)
        if text[:1].islower() or (
            "%1" not in source
            and _PARTICLE_START_RE.match(source.strip())
            and _VERB_START_RE.match(text)
        ):
            return (
                "RPG Maker MZ shows the battler's name only in place of %1, "
                "so this message prints without a subject; a battler-name "
                "source fix may add the %1."
            )
    elif engine == "MV" and re.match(r"[A-Za-z0-9]", live):
        return (
            "RPG Maker MV prints the battler's name directly before this "
            f'message ("Name{live}"), so it needs a leading space or possessive.'
        )
    return ""


def _battler_names(records: list[dict[str, Any]], engine: str) -> dict[str, list[str]]:
    fields = BATTLE_MESSAGES.get(engine, {})
    notes: dict[str, list[str]] = {}
    for record in records:
        field = (record.get("database_entity") or {}).get("field")
        if field not in fields.get(record["file"], ()):
            continue
        if note := battler_name_note(engine, str(record["live"]), str(record["source"])):
            notes[record["identity"]] = [note]
    return notes


def database_checks(
    manifest: dict[str, Any], engine: str
) -> dict[str, list[dict[str, str]]]:
    """Each cluster's failed checks, by its representative identity, with the
    evidence a reviewer needs and the source fix a check allows."""
    records = [
        record for record in manifest["records"]
        if record.get("classification") == "database"
    ]
    cluster_of = {
        identity: cluster["representative"]
        for cluster in manifest["clusters"]
        for identity in cluster["identities"]
    }
    found: dict[str, list[dict[str, str]]] = defaultdict(list)
    for check, notes in (
        ("name-collision", _collisions(records)),
        ("battler-name", _battler_names(records, engine)),
    ):
        for identity in sorted(notes):
            cluster = cluster_of[identity]
            for note in notes[identity]:
                entry = {"check": check, "note": note}
                if check == "battler-name" and engine == "MZ":
                    # MZ formats the name into %1, so the message may gain the
                    # one its source forgot.
                    entry["source_fix"] = "battler-name"
                if entry not in found[cluster]:
                    found[cluster].append(entry)
    return dict(found)
