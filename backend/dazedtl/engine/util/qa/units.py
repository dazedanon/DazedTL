"""Text QA's inventory of an Assistant-led game on an engine Text QA can't
read: the units Len's extractor saved, with the English the game gets, in
place of RPG Maker data.

Text QA reads RPG Maker MV/MZ and VX Ace data itself. On any other engine,
Len's per-game extractor and injector own the game's files, and its units
already carry what Text QA's items need: each line's scene and group in play
order, its speaker by the engine's own evidence and its source; the run's
exported results carry its English. This inventory holds them as Text QA's
records, so the same task reviews them: scenes read in order, each main
speaker's voice across scenes, sampled checks by a second reviewer, deep
review, sweeps and the editorial pass. A record names its unit by its ID and
places it in its scene by its position there, which scene corrections number
lines by; it points into no file, so the steps that read RPG Maker data, such
as the never-translated report, Show Text headers and window fits, have
nothing to read in it. Findings go back as Assistant-led's correction
receipts, which the assistant's own injector writes into the game.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from util.qa import mechanical
from util.qa.schema import _canonical_bytes, _sha256
from util.rpgmaker_qa_manifest import FOCUSES, _length_band, clustered

SCHEMA = "units-qa-manifest-v1"
# A record's mapping: a unit, by its ID, rather than a place in a game file.
MAPPING = "unit"


def classification(field: str | None) -> str:
    """A unit's QA class: a field table's lines, such as a database's items,
    are database text, and every other scene's lines dialogue, read in order
    as a scene."""
    return "database" if field else "dialogue"


def inventory(lines: Iterable[Mapping[str, Any]], focus: str) -> dict[str, Any]:
    """The QA inventory of *focus* over *lines* in play order, each a unit's
    `id`, `scene`, `group`, `kind`, `speaker`, `field`, `source` and
    `translation`; a line whose translation is None is left out, keeping
    the numbers of the lines after it in its scene."""
    if focus not in FOCUSES:
        raise ValueError(f"unknown focus: {focus!r}")
    records: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    seen: set[str] = set()
    for order, line in enumerate(lines):
        identity = str(line["id"])
        if identity in seen:
            raise ValueError(f"A unit ID repeats: {identity}")
        seen.add(identity)
        scene = str(line["scene"])
        # Its place in its scene counts every line of it, so a focus that
        # leaves some out numbers the rest as the whole scene does.
        position = positions.get(scene, 0)
        positions[scene] = position + 1
        field = line.get("field") or None
        kind = classification(field)
        if focus not in {"release", kind} or line.get("translation") is None:
            continue
        source, live = str(line["source"]), str(line["translation"])
        record: dict[str, Any] = {
            "identity": identity,
            "file": str(line.get("group") or scene),
            "scene": scene,
            "position": position,
            "order": order,
            "source_pointer": "",
            "live_pointers": [],
            "source_sha256": _sha256(source),
            "source": source,
            "live": live,
            "classification": kind,
            "mapping": MAPPING,
            "live_transform": "identity",
            "event_code": None,
            "display_shape": str(line.get("kind") or "unknown"),
            "source_char_length": len(source),
            "live_char_length": len(live),
            "length_band": _length_band(live),
            "mechanical": mechanical.evidence(source, live, None),
            "speaker": {
                "display_name": str(line.get("speaker") or ""),
                "face_name": "",
                "provenance": "unit",
            },
        }
        if field:
            record["field"] = str(field)
        records.append(record)
    clusters, review_sequence = clustered(records, focus)
    groups = sorted({record["file"] for record in records})
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "focus": focus,
        "files": [],
        "records": records,
        "unresolved": [],
        "clusters": clusters,
        "review_sequence": review_sequence,
        "counts": {
            "files": len(groups),
            "records": len(records),
            "clusters": len(clusters),
            "unresolved": 0,
        },
    }
    manifest["content_sha256"] = _sha256(_canonical_bytes(manifest))
    return manifest


def verify(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Whether *manifest* is a units inventory as `inventory` made it, in
    the form Text QA's validation of an RPG Maker inventory takes."""
    errors = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"unsupported schema: {manifest.get('schema')!r}")
    unsigned = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if manifest.get("content_sha256") != _sha256(_canonical_bytes(unsigned)):
        errors.append("content_sha256 does not match the inventory")
    records = manifest.get("records") or []
    if not all(held(record) for record in records):
        errors.append("a record is no unit's")
    if len({record.get("identity") for record in records}) != len(records):
        errors.append("a unit ID repeats")
    return {
        "schema": "rpgmaker-qa-validation-v1",
        "manifest_sha256": manifest.get("content_sha256"),
        "valid": not errors,
        "errors": errors,
        "counts": manifest.get("counts"),
    }


def held(record: Mapping[str, Any]) -> bool:
    """Whether an inventory record is a unit's."""
    return record.get("mapping") == MAPPING


def of_task(task: Mapping[str, Any]) -> bool:
    """Whether a task reviews a units inventory, as prepare_task records."""
    return task.get("inventory") == SCHEMA


def scene_line(record: Mapping[str, Any]) -> dict[str, Any]:
    """What a scene's line of a unit adds for its reviewer: its unit's ID,
    which an observation names it by, and its number in the scene, which a
    scene correction names it by."""
    return {"unit": record["identity"], "command": record["position"]}
