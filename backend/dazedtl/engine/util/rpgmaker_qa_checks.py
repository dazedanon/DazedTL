"""Deterministic checks that send database text to deep review.

Each check finds a defect that sits between texts a reviewer reads apart: two
entries of one database that show the same English name, a glossary term whose
English a database text lacks, and a battle message that RPG Maker's battler
name leaves without a subject or runs into. A check only escalates; a deep
reviewer judges the text and writes any correction.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

# Players never read MapInfos.json names; a map shows its own display name.
UNSEEN_NAMES = frozenset({"MapInfos.json"})
# A shorter glossary term inside a longer text is too often an ordinary word,
# such as 風 in 疾風; it still counts when it is the whole text.
GLOSSARY_TERM_MIN = 3
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


def _glossary_misses(
    records: list[dict[str, Any]], glossary: list[tuple[str, str]]
) -> dict[str, list[str]]:
    terms = [(_term(source), source, english) for source, english in glossary]
    notes: dict[str, list[str]] = defaultdict(list)
    for record in records:
        source = _term(str(record["source"]))
        hits = [
            (term, original, english) for term, original, english in terms
            if term and (
                term == source or len(term) >= GLOSSARY_TERM_MIN and term in source
            )
        ]
        # A term inside a longer matched term, such as なぎ払い inside
        # 大なぎ払い, is that longer term's word.
        hits = [
            hit for hit in hits
            if not any(hit[0] != other[0] and hit[0] in other[0] for other in hits)
        ]
        live = _key(str(record["live"]))
        for _term_key, original, english in hits:
            if not any(_key(form) in live for form in english.split("/")):
                notes[record["identity"]].append(
                    f'The glossary gives {original} as "{english}", which this text lacks.'
                )
    return notes


def _battler_names(records: list[dict[str, Any]], engine: str) -> dict[str, list[str]]:
    fields = BATTLE_MESSAGES.get(engine, {})
    notes: dict[str, list[str]] = {}
    for record in records:
        field = (record.get("database_entity") or {}).get("field")
        live = str(record["live"])
        if field not in fields.get(record["file"], ()) or not live.strip() or "%1" in live:
            continue
        if engine == "MZ":
            # The name goes only where %1 is, so a predicate such as "was
            # freed" or "'s Illusion" has no subject.
            if re.sub(r"^[\s\"“”'’….]+", "", live)[:1].islower():
                notes[record["identity"]] = [
                    "RPG Maker MZ shows the battler's name only in place of %1, "
                    "so this message prints without a subject; a battler-name "
                    "source fix may add the %1."
                ]
        elif re.match(r"[A-Za-z0-9]", live):
            notes[record["identity"]] = [
                "RPG Maker MV prints the battler's name directly before this "
                f'message ("Name{live}"), so it needs a leading space or possessive.'
            ]
    return notes


def database_checks(
    manifest: dict[str, Any], glossary: list[tuple[str, str]], engine: str
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
        ("glossary-missing", _glossary_misses(records, glossary)),
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
