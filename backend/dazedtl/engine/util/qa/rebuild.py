"""Rebuilding a task's deep review from a finished screen of an earlier task."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from util import system
from util.qa.acceptance import _accept
from util.qa.advance import _advance_unlocked, advance
from util.qa.bundles import _next_number, _screen_digest
from util.qa.claims import _decline, _stage_finished
from util.qa.pace import status
from util.qa.prepare import _inventory_text, prepare_task
from util.qa.records import _bundle_row
from util.qa.schema import (
    BUNDLE_SCHEMA,
    CHECKPOINT_SCHEMA,
    DEFAULT_HELPER,
    DEFAULT_SCREEN_CHAR_BUDGET,
    DEFAULT_SCREEN_ITEM_LIMIT,
    FINISHED_STATUSES,
    TASK_SCHEMA,
    QAResultError,
    _canonical_bytes,
    _sha256,
)
from util.qa.storage import (
    _atomic_write_json,
    _load_task,
    _read_json,
    _read_task,
    _slug,
    _task_lock,
)
from util.qa.validation import _validate_screen_result


def rebuild_deep_from_screen(
    source_task_dir: str | Path, output_root: str | Path | None = None
) -> tuple[Path, dict[str, Any]]:
    """Create a current task by replaying immutable receipts from a completed screen."""
    source = Path(source_task_dir).expanduser().resolve()
    source_task = _read_json(source / "task.json")
    source_checkpoint = _read_json(source / "checkpoint.json")
    if (
        source_task.get("schema") != TASK_SCHEMA
        or source_checkpoint.get("schema") != CHECKPOINT_SCHEMA
        or source_checkpoint.get("task_sha256")
        != _sha256(_canonical_bytes(source_task))
    ):
        raise ValueError(f"Unsupported or corrupt source QA task: {source}")
    source_rows = source_checkpoint["screen"]["bundles"]
    # Declined items finish a screen too: reviewed on another helper, or set
    # aside as not reviewed.
    if not source_rows or any(
        row.get("status") not in FINISHED_STATUSES for row in source_rows
    ):
        raise ValueError("The source task must have a finished screen stage")

    reusable_results: dict[str, Path] = {}
    digests: dict[str, str] = {}
    items: dict[str, list[str]] = {}
    groups: list[list[str]] = []
    for row in source_rows:
        bundle_path = source / "bundles" / "screen" / f"{row['id']}.json"
        result_path = source / "results" / "screen" / f"{row['id']}.json"
        bundle = _read_json(bundle_path)
        checksum_value = dict(bundle)
        claimed = checksum_value.pop("content_sha256", "")
        if (
            bundle.get("schema") != BUNDLE_SCHEMA
            or bundle.get("stage") != "screen"
            or bundle.get("bundle_id") != row["id"]
            or claimed != row.get("sha256")
            or claimed != _sha256(_canonical_bytes(checksum_value))
        ):
            raise ValueError(f"Source screen bundle checksum is invalid: {row['id']}")
        digests[row["id"]] = _screen_digest(bundle)
        items[row["id"]] = [item["id"] for item in bundle["items"]]
        if _first_screen(row):
            groups.append(items[row["id"]])
        if row["status"] != "accepted":
            continue
        result = _read_json(result_path)
        if result.get("bundle_sha256") != claimed:
            raise ValueError(f"Source screen result checksum is invalid: {row['id']}")
        _validate_screen_result(bundle, result)
        reusable_results[row["id"]] = result_path
    declines = _source_declines(source_rows, items)

    destination_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else source.parents[2]
    )
    tasks = (
        destination_root
        / _slug(Path(source_task["game_root"]).expanduser().resolve().name)
        / source_task["focus"]
    )
    before = {path.name for path in tasks.iterdir()} if tasks.is_dir() else set()
    rebuilt, _state = prepare_task(
        source_task["game_root"],
        source_task["data_root"],
        source_task["focus"],
        destination_root,
        screen_char_budget=int(
            (source_task.get("screen_configuration") or {}).get(
                "char_budget", DEFAULT_SCREEN_CHAR_BUDGET
            )
        ),
        screen_item_limit=int(
            (source_task.get("screen_configuration") or {}).get(
                "item_limit", DEFAULT_SCREEN_ITEM_LIMIT
            )
        ),
        fit=source_task.get("layout"),
        # The earlier reviews its source read, so its screen holds the same
        # lines.
        origins=(source_task.get("reviewed_before") or {}).get("from") or [],
        # Its screen packed as the source's, whose hints may have been
        # longer or shorter.
        screen_groups=groups,
    )
    if rebuilt == source:
        raise ValueError("The source task already uses the current QA rules")
    try:
        _replay_screen(
            source,
            source_task,
            source_checkpoint,
            reusable_results,
            digests,
            declines,
            rebuilt,
        )
    except ValueError:
        # A task this rebuild made but could not fill is no task to go on with.
        if rebuilt.name not in before:
            with _task_lock(tasks):
                system.remove_tree(rebuilt, ignore_errors=True)
        raise
    # Declined items the source reported as not reviewed are set aside again.
    skipped = any(row.get("skipped") for row in source_rows)
    if _stage_finished(_read_task(rebuilt)[2], ["screen"], skipped):
        return rebuilt, advance(rebuilt, skipped)
    return rebuilt, status(rebuilt)


def _first_screen(row: dict[str, Any]) -> bool:
    """Whether a screen row is one of the bundles a task was prepared with,
    rather than a check of one, the items a reviewer declined from one or a
    follow-up of lines set aside."""
    return not (row.get("check_of") or row.get("origin") or row.get("follow_up"))


def _source_declines(
    rows: list[dict[str, Any]], items: dict[str, list[str]]
) -> dict[str, dict[str, Any]]:
    """Each screen bundle a worker split by declining some of its items
    unreviewed (see decline_items): the number of the bundle the declined
    items moved to, that decline (its worker, helper and reasons) and the
    bundles made before it, which rows list in the order they were made,
    except a split's remainder, listed in its place. *items* holds each
    bundle's item IDs."""
    by_id = {row["id"]: row for row in rows}
    remainders = {row.get("remainder") for row in rows if row["status"] == "split"}
    found = {}
    for row in rows:
        if row["status"] != "split":
            continue
        origin = row.get("origin") or row["id"]
        if row.get("remainder"):
            # The rest moved to the bundle numbered right after.
            number = int(row["remainder"].rsplit("-r", 1)[1]) - 1
        else:
            # Every item moved: to the first bundle made after this one from
            # its origin with its items and earlier declines.
            own = 0 if row["id"] == origin else int(row["id"].rsplit("-", 1)[1][1:])
            numbers = [
                int(match[1])
                for other in rows
                if (match := re.fullmatch(re.escape(origin) + r"-d(\d+)", other["id"]))
                and int(match[1]) > own
                and items[other["id"]] == items[row["id"]]
                and (other.get("declines") or [])[:-1] == (row.get("declines") or [])
            ]
            number = min(numbers, default=0)
        declined = by_id.get(f"{origin}-d{number}")
        if not declined or not declined.get("declines"):
            raise ValueError(f"Source screen declines are incomplete: {row['id']}")
        found[row["id"]] = {
            "number": number,
            "decline": declined["declines"][-1],
            "after": [
                other["id"]
                for other in rows[: rows.index(declined)]
                if other["id"] not in remainders
            ],
        }
    return found


def _replay_declines(rebuilt: Path, declines: dict[str, dict[str, Any]]) -> None:
    """Split the rebuilt task's bundles as their source's workers did, each
    once the bundle waits and the bundles made before it in the source are
    made, so later bundles are numbered and listed alike. Removes what it
    replayed from *declines*."""
    while declines:
        with _task_lock(rebuilt):
            _root, _task, checkpoint = _load_task(rebuilt)
            rows = {row["id"]: row for row in checkpoint["screen"]["bundles"]}
            ready = [
                bundle_id
                for bundle_id, split in declines.items()
                if bundle_id in rows
                and rows[bundle_id]["status"] in {"pending", "assigned"}
                and all(made in rows for made in split["after"])
                and split["number"] == _next_number(
                    checkpoint, "screen", rows[bundle_id].get("origin") or bundle_id
                )
            ]
            if not ready:
                return
            entry = declines.pop(ready[0])["decline"]
            _decline(
                rebuilt,
                checkpoint,
                entry["worker"],
                entry["helper"],
                ready[0],
                [{"id": key, "reason": reason} for key, reason in entry["reasons"].items()],
            )


def _replay_screen(
    source: Path,
    source_task: dict[str, Any],
    source_checkpoint: dict[str, Any],
    reusable_results: dict[str, Path],
    digests: dict[str, str],
    declines: dict[str, dict[str, Any]],
    rebuilt: Path,
) -> None:
    """Accept a finished screen's results in a rebuilt task, once its screen
    bundles hold the same lines; *digests* are the source's bundles' (see
    _screen_digest), as the rebuilt task's hints may read otherwise. Items
    the source's workers declined are declined alike (see _source_declines),
    and set aside again as the source set them aside."""
    source_rows = source_checkpoint["screen"]["bundles"]
    _rebuilt_root, rebuilt_task, rebuilt_checkpoint = _load_task(rebuilt)
    if _inventory_text(_read_json(rebuilt / "inventory.json")) != _inventory_text(
        _read_json(source / "inventory.json")
    ):
        raise ValueError("Cannot reuse screening after the game's text changed")
    if rebuilt_task.get("context_sha256") != source_task.get("context_sha256"):
        raise ValueError("Cannot reuse screening after QA's context changed")
    rebuilt_summaries = {
        row["id"]: (_screen_digest(_read_json(Path(row["path"]))), int(row["item_count"]))
        for row in rebuilt_checkpoint["screen"]["bundles"]
        if _first_screen(row)
    }
    if rebuilt_summaries != {
        row["id"]: (digests[row["id"]], int(row["item_count"]))
        for row in source_rows
        if _first_screen(row)
    }:
        raise ValueError("Current screen bundles differ; screening cannot be reused")

    if rebuilt_checkpoint["stage"] != "screen":
        return
    differ = "Current screen checks differ; screening cannot be reused"
    with _task_lock(rebuilt):
        # Its workers keep their helpers, which decide who may take what
        # they declined.
        _rebuilt_root, _task, checkpoint = _load_task(rebuilt)
        workers = checkpoint.setdefault("workers", {})
        for name, record in (source_checkpoint.get("workers") or {}).items():
            if record.get("helper") not in (None, "", DEFAULT_HELPER):
                workers.setdefault(name, {"bundles": 0, "seconds": 0.0}).setdefault(
                    "helper", record["helper"]
                )
        _atomic_write_json(rebuilt / "checkpoint.json", checkpoint)
    skipped = any(row.get("skipped") for row in source_rows)
    # Accepted in their order under the same reviewers, the results open the
    # same checks, which take their own results in turn.
    accepted = sorted(
        (row for row in source_rows if row["status"] == "accepted"),
        key=lambda row: row.get("accepted_at") or "",
    )
    for source_row in accepted:
        _replay_declines(rebuilt, declines)
        with _task_lock(rebuilt):
            _rebuilt_root, _task, checkpoint = _load_task(rebuilt)
            if (
                skipped
                and source_row["id"] not in {row["id"] for row in checkpoint["screen"]["bundles"]}
                and _stage_finished(checkpoint, ["screen"], skip_declined=True)
            ):
                # The source set declined items aside here, which sent their
                # lines to follow-up bundles.
                _advance_unlocked(rebuilt, skip_declined=True)
                _rebuilt_root, _task, checkpoint = _load_task(rebuilt)
            try:
                _stage, row = _bundle_row(checkpoint, source_row["id"])
            except QAResultError as error:
                raise ValueError(differ) from error
            if _screen_digest(_read_json(Path(row["path"]))) != digests[source_row["id"]]:
                raise ValueError(differ)
            if row["status"] != "accepted":
                row["status"] = "assigned"
                row["assigned_to"] = str(source_row.get("assigned_to") or "")
                _atomic_write_json(rebuilt / "checkpoint.json", checkpoint)
            checksum = row["sha256"]
        # The same review of the same lines, for the bundle as the rebuilt
        # task words its hints.
        _accept(
            rebuilt,
            {**_read_json(reusable_results[source_row["id"]]), "bundle_sha256": checksum},
        )
    _replay_declines(rebuilt, declines)
    # Every bundle of the source's screen is the rebuilt task's, holding the
    # same lines and as finished, but for what its source set aside on
    # request, which waits for that request (see rebuild_deep_from_screen).
    rows = {row["id"]: row for row in _read_task(rebuilt)[2]["screen"]["bundles"]}
    if declines or any(
        row["id"] not in rows
        or _screen_digest(_read_json(Path(rows[row["id"]]["path"]))) != digests[row["id"]]
        or rows[row["id"]]["status"]
        not in {row["status"], "pending" if row.get("skipped") else row["status"]}
        for row in source_rows
    ):
        raise ValueError(differ)
