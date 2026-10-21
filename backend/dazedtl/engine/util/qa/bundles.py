"""Review bundles: grouping items into bundles, the checkpoint rows that
issue them, declined items, and screen checks."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from util.qa.fitting import correction_problems
from util.qa.records import _bundle_row, _helper_of, _item_targets
from util.qa.schema import (
    BUNDLE_SCHEMA,
    DECLINE_REASON_LIMIT,
    DEFAULT_DEEP_CHAR_BUDGET,
    DEFAULT_DEEP_ITEM_LIMIT,
    QAResultError,
    _canonical_bytes,
    _sha256,
)
from util.qa.storage import _atomic_write_json, _read_json
from util.rpgmaker_header_check import check as check_headers

# Occurrences a deep item lists in full; its shapes still cover every one.
DEEP_LOCATOR_LIMIT = 12

# Distinct helpers that must decline an item before it is set aside unreviewed.
DECLINES_TO_SET_ASIDE = 2

# Another reviewer screens at least this share of each reviewer's scene and
# line targets again, starting with its first bundle.
SCREEN_CHECK_SHARE = 0.25
# A reviewer has every bundle checked once checks found at least this many
# problems it missed, and more than it found in the same lines.
SCREEN_CHECK_MISSES = 2


def _header_flags(data: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """The header check's likely Show Text slips, each beside the first line of
    its box the inventory holds, or none when the box was never translated."""
    result = check_headers(data)
    records = {
        (record["file"], record["source_pointer"]): record["identity"]
        for record in manifest["records"]
    }
    for flag in result["flags"]:
        flag["identity"] = next((
            records[(flag["file"], line + "/_original")] for line in flag["lines"]
            if (flag["file"], line + "/_original") in records
        ), "")
    return result


def _candidate(reasons: Iterable[str], identities: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "reasons": sorted(set(reasons)),
        "context_identities": sorted({identity for identity in identities if identity}),
    }


def _merge_candidate(
    candidates: dict[str, dict[str, Any]], cluster_id: str,
    reasons: Iterable[str], identities: Iterable[str] = (),
) -> None:
    existing = candidates.get(cluster_id) or _candidate(())
    candidates[cluster_id] = _candidate(
        [*(existing.get("reasons") or []), *reasons],
        [*(existing.get("context_identities") or []), *identities],
    )


def _bundle_items(
    items: list[dict], *, stage: str, char_budget: int, item_limit: int,
    first: int = 1, screen_index: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    if char_budget < 2_000 or item_limit < 1:
        raise ValueError("QA bundle limits are too small")
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for item in items:
        size = len(_canonical_bytes(item))
        if item.get("exclusive_bundle"):
            if current:
                groups.append(current)
                current, current_chars = [], 0
            groups.append([item])
            continue
        if current and (len(current) >= item_limit or current_chars + size > char_budget):
            groups.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += size
    if current:
        groups.append(current)
    return [
        _make_bundle(
            stage, f"{stage}-{index:04d}", group, _own_index(group, screen_index)
        )
        for index, group in enumerate(groups, start=first)
    ]


def _regrouped(bundles: list[dict], groups: list[list[str]]) -> list[dict]:
    """Screen *bundles* packed again as *groups*, the items of each bundle,
    in order; as they are unless the groups hold every item once."""
    items = {item["id"]: item for bundle in bundles for item in bundle["items"]}
    named = [identity for group in groups for identity in group]
    if not all(groups) or len(named) != len(set(named)) or set(named) != set(items):
        return bundles
    return [
        _make_bundle("screen", f"screen-{index:04d}", [items[name] for name in group])
        for index, group in enumerate(groups, start=1)
    ]


# What a screen item holds only to point its reviewer at a risk, such as the
# glossary terms its English lacks, which QA's rules may word otherwise for
# the same lines.
_SCREEN_HINTS = frozenset({"risk", "glossary"})


def _screen_digest(bundle: dict[str, Any]) -> str:
    """A screen bundle's checksum without its items' hints: the same for a
    bundle of the same lines, which the same review covers."""

    def plain(entry: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in entry.items() if key not in _SCREEN_HINTS}

    return _sha256(_canonical_bytes({
        **{key: value for key, value in bundle.items() if key != "content_sha256"},
        "items": [
            plain(item) | (
                {"lines": [plain(line) for line in item["lines"]]}
                if isinstance(item.get("lines"), list) else {}
            )
            for item in bundle["items"]
        ],
    }))


def _own_index(
    items: list[dict], screen_index: dict[str, dict[str, str]] | None
) -> dict[str, Any]:
    """A follow-up bundle's own screen index, for lines the task's index,
    made before any review, does not hold."""
    entries = {
        target: screen_index[target]
        for item in items for target in _item_targets(item)
        if target in (screen_index or {})
    }
    return {"screen_index": entries} if entries else {}


def _target_entry(
    screen_index: dict[str, dict[str, str]], bundle: dict[str, Any], target: str
) -> dict[str, str]:
    """The cluster and representative line a screen target or context ID names."""
    return (
        (bundle.get("screen_index") or {}).get(target)
        or screen_index.get(target)
        or {}
    )


def _make_bundle(
    stage: str, bundle_id: str, group: list[dict], extra: dict | None = None
) -> dict:
    ordinals = []
    for item in group:
        if item.get("kind") == "scene":
            ordinals.extend(
                line["ordinal"] for line in item["lines"] if "id" in line
            )
        else:
            ordinals.append(item["ordinal"])
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "stage": stage,
        "bundle_id": bundle_id,
        "ordinal_start": min(ordinals),
        "ordinal_end": max(ordinals),
        "item_count": sum(int(item.get("target_count", 1)) for item in group),
        "review_unit_count": len(group),
        "scene_count": sum(item.get("kind") == "scene" for item in group),
        "motif_count": sum(
            item.get("kind") == "motif-family" for item in group
        ),
        "items": group,
        **(extra or {}),
    }
    bundle["content_sha256"] = _sha256(_canonical_bytes(bundle))
    return bundle


def _target_shape(locator: dict[str, Any]) -> dict[str, Any]:
    """The line structure and box of one place an item's text shows."""
    return {
        "event_code": locator.get("event_code"),
        "pointers": len(locator["live_pointers"]),
        "transform": locator.get("live_transform", "identity"),
        **({"box": locator["box"]} if locator.get("box") else {}),
    }


def _shape_problems(
    item: dict[str, Any],
    correction: str,
    shape: dict[str, Any],
    allowed: frozenset[str] = frozenset(),
) -> list[str]:
    """Why a correction of a bundle item would block apply at one shape."""
    return correction_problems(
        str(item["source"]),
        str(item["translation"]),
        correction,
        shape["event_code"],
        ["/"] * shape["pointers"],
        shape["transform"],
        allowed,
        box=shape.get("box"),
    )


def _compact_deep_item(
    item: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """A deep item without its scenes and motif reviews, which its bundle
    prints once, and with long occurrence lists capped."""
    item = dict(item)
    scenes = item.pop("screen_scene_contexts", None) or []
    motifs = item.pop("motif_contexts", None) or []
    locators = item["locators"]
    item["occurrences"] = len(locators)
    shapes = {
        json.dumps(shape): shape for shape in map(_target_shape, locators)
    }
    item["target_shapes"] = [shapes[key] for key in sorted(shapes)]
    if len(locators) > DEEP_LOCATOR_LIMIT:
        first = set(item.get("screen_context_identities") or [])
        kept = sorted(locators, key=lambda row: row["identity"] not in first)
        kept = kept[:DEEP_LOCATOR_LIMIT]
        item["locators"] = kept
        item["identities"] = [locator["identity"] for locator in kept]
    if scenes:
        # The scene shows the lines around it; windows would repeat them.
        item.pop("nearby_commands", None)
        item.pop("suspect_contexts", None)
    return item, scenes, motifs


def _compact_scene(scene: dict[str, Any], marks: dict[str, list[str]]) -> dict:
    """A scene as deep review reads it: each line's text and speaker, and the
    items whose screen evidence names it."""
    lines = []
    for line in scene["lines"]:
        compact = {"source": line["source"], "translation": line["translation"]}
        for key in ("speaker", "event_code", "command"):
            if key in line:
                compact[key] = line[key]
        named = marks.get(line.get("id") or line.get("context_id") or "")
        if named:
            compact["items"] = sorted(set(named))
        lines.append(compact)
    return {"scene_id": scene["scene_id"], "lines": lines}


def _bundle_deep(items: list[dict], first: int = 1) -> list[dict]:
    """Deep bundles grouped by scene, each scene and motif review printed once."""
    prepared = [_compact_deep_item(item) for item in items]
    order = {item["id"]: index for index, (item, _scenes, _motifs) in enumerate(prepared)}

    def scene_key(entry):
        item, scenes, _motifs = entry
        first = scenes[0]["scene_id"] if scenes else str(
            (item["locators"] or [{}])[0].get("file") or ""
        )
        return first, order[item["id"]]

    prepared.sort(key=scene_key)
    groups: list[list[tuple]] = []
    current: list[tuple] = []
    size = 0
    seen: set[str] = set()
    for entry in prepared:
        item, scenes, motifs = entry
        new = [scene for scene in scenes if scene["scene_id"] not in seen] + [
            motif for motif in motifs if motif["id"] not in seen
        ]
        extra = len(_canonical_bytes(item)) + len(_canonical_bytes(new))
        # An item whose scene the bundle prints already stays with it, since
        # another bundle would print that scene again: on Fuuma Chronicle,
        # two items of one 1,117-line scene printed it twice.
        shared = any(scene["scene_id"] in seen for scene in scenes)
        if current and (
            len(current) >= DEFAULT_DEEP_ITEM_LIMIT
            or not shared and size + extra > DEFAULT_DEEP_CHAR_BUDGET
        ):
            groups.append(current)
            current, size, seen = [], 0, set()
            extra = len(_canonical_bytes(item)) + len(_canonical_bytes(scenes + motifs))
        current.append(entry)
        size += extra
        seen |= {scene["scene_id"] for scene in scenes} | {motif["id"] for motif in motifs}
    if current:
        groups.append(current)
    bundles = []
    for index, group in enumerate(groups, start=first):
        scenes: dict[str, dict] = {}
        keys: dict[str, str] = {}
        motifs: dict[str, dict] = {}
        members = []
        # The scene lines each item's screen evidence names.
        marks: dict[str, list[str]] = defaultdict(list)
        for item, _scenes, _motifs in group:
            for evidence in item.get("screen_evidence") or []:
                marks[evidence["target_id"]].append(item["id"])
        for item, item_scenes, item_motifs in group:
            item = dict(item)
            for scene in item_scenes:
                if scene["scene_id"] not in keys:
                    keys[scene["scene_id"]] = f"S{len(keys) + 1}"
                    scenes[keys[scene["scene_id"]]] = _compact_scene(scene, marks)
            if item_scenes:
                item["scenes"] = [keys[scene["scene_id"]] for scene in item_scenes]
            for motif in item_motifs:
                motifs.setdefault(motif["id"], motif)
            if item_motifs:
                item["motifs"] = [motif["id"] for motif in item_motifs]
            members.append(item)
        bundles.append(_make_bundle(
            "deep", f"deep-{index:04d}", members,
            {
                **({"scenes": scenes} if scenes else {}),
                **({"motifs": motifs} if motifs else {}),
            },
        ))
    return bundles


# A family item's own review units, which a reviewer may decline one by one.
_UNIT_LISTS = {
    "lint-family": "proposals", "sweep-family": "candidates", "motif-family": "variants",
}


def _units(item: dict[str, Any]) -> list[dict[str, Any]]:
    """A family item's proposals, candidates or variants; nothing for others."""
    key = _UNIT_LISTS.get(item.get("kind") or "")
    return item[key] if key else []


def _family_part(
    item: dict[str, Any], units: list[dict[str, Any]], part_id: str = ""
) -> dict[str, Any]:
    """The family item holding only these units; a declined part has an ID of
    its own and names the family it came from."""
    part = {**item, _UNIT_LISTS[item["kind"]]: units, "target_count": len(units)}
    if item["kind"] == "motif-family":
        part["variant_count"] = len(units)
    if part_id:
        part["id"] = part_id
        part["part_of"] = item.get("part_of") or item["id"]
    return part


def _partition(
    bundle: dict[str, Any], reasons: dict[str, str], number: int = 0
) -> tuple[list[dict], list[dict]]:
    """The bundle's items split into what was declined and what remains.

    A family with some of its units declined splits in two, and its declined
    part is numbered after the bundle that will hold it.
    """
    declined, remaining = [], []
    for item in bundle["items"]:
        units = _units(item)
        chosen = [unit for unit in units if unit["id"] in reasons]
        if item["id"] in reasons or units and len(chosen) == len(units):
            declined.append(item)
        elif chosen:
            family = item.get("part_of") or item["id"]
            declined.append(_family_part(item, chosen, f"{family}-d{number}"))
            remaining.append(_family_part(
                item, [unit for unit in units if unit["id"] not in reasons]
            ))
        else:
            remaining.append(item)
    return declined, remaining


def _shared_context(bundle: dict[str, Any], items: list[dict]) -> dict[str, Any]:
    """What a bundle made of some of another's items keeps from it: the scenes
    and motif reviews a deep bundle prints once that these items name, and a
    follow-up's own screen index for their lines."""
    shared = _own_index(items, bundle.get("screen_index"))
    for key in ("scenes", "motifs"):
        named = {name for item in items for name in item.get(key) or []}
        if named:
            shared[key] = {
                name: value for name, value in bundle[key].items() if name in named
            }
    return shared


def _add_row(
    root: Path,
    checkpoint: dict[str, Any],
    stage: str,
    bundle: dict[str, Any],
    fields: dict[str, Any],
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a bundle made from another's items and add its checkpoint row,
    after `after` or last."""
    path = root / "bundles" / stage / f"{bundle['bundle_id']}.json"
    _atomic_write_json(path, bundle)
    row = {
        "id": bundle["bundle_id"],
        "path": str(path),
        "sha256": bundle["content_sha256"],
        "item_count": bundle["item_count"],
        "status": "pending",
        "assigned_to": "",
        "result_path": "",
        **fields,
        # The authors of its judgment corrections still cannot confirm them.
        **(
            {"authors": sorted({
                author for item in bundle["items"] for author in item["authors"]
            })}
            if stage == "editorial" else {}
        ),
    }
    rows = checkpoint[stage]["bundles"]
    rows.insert(rows.index(after) + 1 if after else len(rows), row)
    return row


def _next_number(checkpoint: dict[str, Any], stage: str, origin: str) -> int:
    return 1 + sum(
        other.get("origin") == origin for other in checkpoint[stage]["bundles"]
    )


def _split_declined(
    root: Path,
    checkpoint: dict[str, Any],
    stage: str,
    row: dict[str, Any],
    bundle: dict[str, Any],
    reasons: dict[str, str],
    worker: str = "",
) -> tuple[dict[str, Any], list[dict]]:
    """Move declined items into their own bundle for a reviewer on another helper.

    Returns that bundle's row and the items that remain. After enough
    distinct helpers declined the same items, they are set aside unreviewed
    instead. The worker that declined is the bundle's holder unless named.
    """
    worker = worker or str(row.get("assigned_to") or "") or "unnamed reviewer"
    helper = _helper_of(checkpoint, worker)
    declined_helpers = sorted({*(row.get("declined_helpers") or []), helper})
    origin = row.get("origin") or row["id"]
    number = _next_number(checkpoint, stage, origin)
    items, remaining = _partition(bundle, reasons, number)
    split = _make_bundle(
        stage, f"{origin}-d{number}", items, _shared_context(bundle, items)
    )
    return _add_row(root, checkpoint, stage, split, {
        "status": (
            "set-aside"
            if len(declined_helpers) >= DECLINES_TO_SET_ASIDE else "pending"
        ),
        "origin": origin,
        **({"follow_up": True} if row.get("follow_up") else {}),
        "declined_by": sorted({*(row.get("declined_by") or []), worker}),
        "declined_helpers": declined_helpers,
        "declines": [
            *(row.get("declines") or []),
            {"worker": worker, "helper": helper, "reasons": reasons},
        ],
        **({"round": row.get("round")} if stage == "editorial" else {}),
    }), remaining


def _checkable(bundle: dict[str, Any], declined: Iterable[str]) -> list[dict[str, Any]]:
    """The scenes and lines a screen result reviewed, which a check repeats;
    lint and motif families are group reviews and are not repeated."""
    declined = set(declined)
    return [
        item for item in bundle["items"]
        if item.get("kind") in {"scene", "cluster"} and item["id"] not in declined
    ]


def _check_row(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """A second screen of one accepted bundle's reviewed lines, for another reviewer."""
    bundle = _read_json(Path(row["path"]))
    result = _read_json(Path(row["result_path"]))
    items = _checkable(bundle, _declined_items(bundle, result))
    check = _make_bundle(
        "screen", f"{row['id']}-c1", items, _own_index(items, bundle.get("screen_index"))
    )
    path = root / "bundles" / "screen" / f"{check['bundle_id']}.json"
    _atomic_write_json(path, check)
    return {
        "id": check["bundle_id"],
        "path": str(path),
        "sha256": check["content_sha256"],
        "item_count": check["item_count"],
        "status": "pending",
        "assigned_to": "",
        "result_path": "",
        "check_of": row["id"],
        # Anyone but the reviewer that screened these lines may check them; a
        # reviewer that declined them can decline them again.
        "independent_of": [str(row.get("assigned_to") or "")],
    }


def _issue_checks(root: Path, checkpoint: dict[str, Any]) -> int:
    """Open checks until each reviewer has its share of targets checked, its
    earliest bundles first; an escalated reviewer has every bundle checked.

    An accepted check counts the targets it compared, so lines its reviewer
    declined send another bundle to be checked. Returns how many opened.
    """
    rows = checkpoint["screen"]["bundles"]
    escalated = set((checkpoint["screen"].get("checks") or {}).get("escalated") or [])
    checks = {row["check_of"]: row for row in rows if row.get("check_of")}
    by_worker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["status"] == "accepted" and row.get("checkable"):
            by_worker[str(row.get("assigned_to") or "")].append(row)
    opened = 0
    for worker, accepted in sorted(by_worker.items()):
        share = 1.0 if worker in escalated else SCREEN_CHECK_SHARE
        total = sum(row["checkable"] for row in accepted)
        done = sum(
            checks[row["id"]]["compared"]
            if checks[row["id"]]["status"] == "accepted" else row["checkable"]
            for row in accepted if row["id"] in checks
        )
        for row in sorted(accepted, key=lambda row: row["accepted_at"]):
            if done >= share * total:
                break
            if row["id"] not in checks:
                rows.append(_check_row(root, row))
                done += row["checkable"]
                opened += 1
    return opened


def _record_check(
    checkpoint: dict[str, Any], row: dict[str, Any], bundle: dict, result: dict,
    declined: dict[str, str],
) -> None:
    """Compare a check with the screen it repeats, in the lines both reviewed.

    Each reviewer is tallied with what it found and what the other found that
    it did not; one that missed enough, and more than it found, is escalated.
    """
    _stage, original_row = _bundle_row(checkpoint, row["check_of"])
    original = _read_json(Path(original_row["result_path"]))
    reviewed = [item for item in bundle["items"] if item["id"] not in declined]
    row["compared"] = sum(int(item.get("target_count", 1)) for item in reviewed)
    compared = {target for item in reviewed for target in _item_targets(item)}
    first = {exception["id"] for exception in original["exceptions"]} & compared
    second = {exception["id"] for exception in result["exceptions"]}
    state = checkpoint["screen"].setdefault(
        "checks", {"added": 0, "escalated": [], "reviewers": {}}
    )
    state["added"] += len(second - first)
    for worker, found, missed in (
        (str(original_row.get("assigned_to") or ""), first, second - first),
        (str(row.get("assigned_to") or ""), second, first - second),
    ):
        tally = state["reviewers"].setdefault(worker, {"found": 0, "missed": 0})
        tally["found"] += len(found)
        tally["missed"] += len(missed)
        if (
            tally["missed"] >= SCREEN_CHECK_MISSES
            and tally["missed"] > tally["found"]
            and worker not in state["escalated"]
        ):
            state["escalated"].append(worker)


def _check_counts(screen: dict[str, Any]) -> dict[str, Any]:
    """Second screens in targets: compared, opened and expected in all, the
    problems only a check found, and the reviewers checked in full."""
    rows = [row for row in screen["bundles"] if row.get("check_of")]
    state = screen.get("checks") or {}
    total = sum(int(row["item_count"]) for row in rows)
    set_aside = sum(
        int(row["item_count"]) for row in screen["bundles"]
        if row["status"] == "set-aside"
    )
    unscreened = max(
        0, int(screen["total_items"]) - int(screen["accepted_items"]) - set_aside
    )
    return {
        "accepted": sum(
            int(row.get("compared", 0)) for row in rows if row["status"] == "accepted"
        ),
        "total": total,
        "projected": total + math.ceil(SCREEN_CHECK_SHARE * unscreened),
        "added": int(state.get("added", 0)),
        "escalated": sorted(state.get("escalated") or []),
    }


def _write_bundles(
    task_dir: Path, bundles: list[dict], *, recorded_root: Path | None = None
) -> list[dict]:
    summaries = []
    stage = bundles[0]["stage"] if bundles else "screen"
    folder = task_dir / "bundles" / stage
    folder.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        path = folder / f"{bundle['bundle_id']}.json"
        _atomic_write_json(path, bundle)
        recorded_path = (recorded_root or task_dir) / "bundles" / stage / path.name
        summaries.append({
            "id": bundle["bundle_id"],
            "path": str(recorded_path),
            "sha256": bundle["content_sha256"],
            "item_count": bundle["item_count"],
            "status": "pending",
            "assigned_to": "",
            "result_path": "",
        })
    return summaries


def _load_screen_index(root: Path, task: dict[str, Any]) -> dict[str, dict[str, str]]:
    document = _read_json(root / "screen-index.json")
    checksum_value = dict(document)
    claimed = checksum_value.pop("content_sha256", "")
    if (
        document.get("schema") != "rpgmaker-qa-screen-index-v1"
        or claimed != _sha256(_canonical_bytes(checksum_value))
        or claimed != task.get("screen_index_sha256")
    ):
        raise QAResultError("Screen target index checksum is invalid")
    targets = document.get("targets")
    if not isinstance(targets, dict):
        raise QAResultError("Screen target index is invalid")
    return targets


def _screen_target_map(
    bundle: dict[str, Any], screen_index: dict[str, dict[str, str]] | None = None
) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for item in bundle["items"]:
        if item.get("kind") == "scene":
            candidates = [
                {**line, "id": line.get("id") or line["context_id"]}
                for line in item["lines"]
                if "id" in line or "context_id" in line
            ]
        elif item.get("kind") == "cluster":
            candidates = [{**item, "cluster_id": item["id"]}]
        else:
            continue
        for target in candidates:
            identity = target["id"]
            if identity in targets:
                raise QAResultError(f"Duplicate screen target {identity!r}")
            targets[identity] = {
                **target,
                **_target_entry(screen_index or {}, bundle, identity),
            }
    return targets


def _screen_motif_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item for item in bundle["items"]
        if item.get("kind") == "motif-family"
    }


def _declined_items(bundle: dict, result: dict) -> dict[str, str]:
    """The bundle items a reviewer declined, with the one-line reason for each.

    A family's single proposal, candidate or variant may be declined by its
    own ID, and the rest of the family is reviewed as usual.
    """
    declined = result.get("declined", [])
    if not isinstance(declined, list):
        raise QAResultError("Declined items must be a list")
    items = {item["id"] for item in bundle["items"]}
    families = {
        unit["id"]: item["id"] for item in bundle["items"] for unit in _units(item)
    }
    reasons: dict[str, str] = {}
    for entry in declined:
        identity = str((entry or {}).get("id") or "") if isinstance(entry, dict) else ""
        reason = str(entry.get("reason") or "").strip() if isinstance(entry, dict) else ""
        if identity not in items and identity not in families or identity in reasons:
            raise QAResultError(f"Invalid or duplicate declined item {identity!r}")
        if not reason or "\n" in reason or len(reason) > DECLINE_REASON_LIMIT:
            raise QAResultError(
                f"A declined item needs a one-line reason of at most "
                f"{DECLINE_REASON_LIMIT} characters: {identity}"
            )
        reasons[identity] = reason
    for identity in reasons:
        if families.get(identity) in reasons:
            raise QAResultError(
                f"Decline {families[identity]} or some of its units, not both"
            )
    return reasons
