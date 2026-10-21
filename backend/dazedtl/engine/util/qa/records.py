"""Small readers of task records: a manifest's record maps, JSON pointers,
checkpoint bundle rows and workers, and the changes a finding makes."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from util.qa.schema import DEFAULT_HELPER, REVIEW_STAGES, QAResultError, _utc_now
from util.qa.storage import _read_json


def _record_maps(manifest: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    records = {record["identity"]: record for record in manifest["records"]}
    clusters = {cluster["representative"]: cluster for cluster in manifest["clusters"]}
    return records, clusters


def _result_declines(result: dict[str, Any]) -> set[str]:
    """The items and units an accepted result declined."""
    return {entry["id"] for entry in result.get("declined") or []}


def _helper_of(checkpoint: dict[str, Any], worker: str) -> str:
    return str(
        ((checkpoint.get("workers") or {}).get(worker) or {}).get("helper")
        or DEFAULT_HELPER
    )


def _register_worker(
    checkpoint: dict[str, Any], worker: str, helper: str | None
) -> str:
    """Record the worker as seen and return its helper, which it keeps."""
    record = checkpoint.setdefault("workers", {}).setdefault(
        worker, {"bundles": 0, "seconds": 0.0}
    )
    named = " ".join(str(helper or "").split()).casefold()
    if len(named) > 60:
        raise ValueError("A helper name is one short line")
    if named and record.get("helper", named) != named:
        raise ValueError(
            f"{worker} runs on the {record['helper']} helper; give a worker on "
            "another helper a name of its own"
        )
    record["helper"] = record.get("helper") or named or DEFAULT_HELPER
    record["last_seen"] = _utc_now()
    return record["helper"]


def _split_notice(row: dict[str, Any]) -> str:
    return f"{row['id']} was split when a worker declined some of its items; " + (
        f"review {row['remainder']} instead" if row.get("remainder")
        else "every item was declined"
    )


def _bundle_row(checkpoint: dict, bundle_id: str) -> tuple[str, dict]:
    for stage in REVIEW_STAGES:
        for row in checkpoint.get(stage, {}).get("bundles", []):
            if row["id"] == bundle_id:
                return stage, row
    raise QAResultError(f"Unknown bundle id {bundle_id!r}")


def _item_targets(item: dict[str, Any]) -> set[str]:
    """The screen target and context IDs one bundle item holds."""
    if item.get("kind") == "scene":
        return {
            line.get("id") or line["context_id"]
            for line in item["lines"]
            if "id" in line or "context_id" in line
        }
    return {item["id"]}


def _decode_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer {pointer!r}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _resolve_parts(value: Any, parts: Iterable[str]) -> Any:
    current = value
    for part in parts:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _latest_deep_reviews(
    checkpoint: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Each cluster's latest accepted deep review, with its item and row; a
    later review saw everything the earlier one did."""
    latest = {}
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] != "accepted":
            continue
        items = {item["id"]: item for item in _read_json(Path(row["path"]))["items"]}
        for review in _read_json(Path(row["result_path"]))["reviews"]:
            if review["disposition"] != "declined":
                latest[review["id"]] = (review, items[review["id"]], row)
    return latest


def _changes(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """The text a finding changes, line by line: a scene correction's lines,
    or one correction of every line it targets."""
    if finding.get("kind") == "scene":
        return finding["lines"]
    return [{
        "source": finding["source"],
        "current": finding["current"],
        "correction": finding["correction"],
        "identities": finding["target_identities"],
    }]


def _finding_families(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding["family_key"]:
            members_by_key[finding["family_key"]].append(finding)
    families = []
    for family_key, members in sorted(members_by_key.items()):
        if len(members) < 2:
            continue
        families.append({
            "id": f"QAF-{len(families) + 1:04d}",
            "family_key": family_key,
            "severity": min(
                (item["severity"] for item in members),
                key={"critical": 0, "high": 1, "medium": 2}.__getitem__,
            ),
            "categories": sorted({item["category"] for item in members}),
            "finding_ids": [item["id"] for item in members],
            "affected_occurrences": sum(
                len(item["target_identities"]) for item in members
            ),
        })
    return families


def _set_pointer(document: Any, pointer: str, value: str) -> None:
    parts = _decode_pointer(pointer)
    if not parts:
        raise ValueError("Refusing to replace an entire JSON document")
    parent = _resolve_parts(document, parts[:-1])
    key = parts[-1]
    if isinstance(parent, list):
        parent[int(key)] = value
    else:
        parent[key] = value
