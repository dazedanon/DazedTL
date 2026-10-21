"""Workers claiming, declining and releasing bundles."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from util.qa.acceptance import accept_result
from util.qa.advance import _advance_unlocked
from util.qa.briefs import _decision_line, render_bundle
from util.qa.bundles import (
    _add_row,
    _declined_items,
    _make_bundle,
    _next_number,
    _shared_context,
    _split_declined,
)
from util.qa.editorial import _finalize_unlocked
from util.qa.pace import _stalled, status
from util.qa.records import _bundle_row, _register_worker
from util.qa.schema import FINISHED_STATUSES, REVIEW_STAGES, _utc_now
from util.qa.storage import (
    _atomic_write_json,
    _decisions,
    _load_task,
    _read_json,
    _read_task,
    _task_lock,
)

# A worker's run reviews this many bundles, then a fresh run of it continues,
# which keeps each review's context small.
RUN_BUNDLES = 6


def next_bundle(
    task_dir: str | Path,
    worker: str,
    bundle_id: str | None = None,
    *,
    helper: str | None = None,
    skip_declined: bool = False,
) -> dict[str, Any] | None:
    """Assign the worker its next bundle, or the named one.

    A worker never receives a bundle a worker on its helper declined; a worker
    on another helper can claim that bundle. With `skip_declined`, declined
    bundles nobody else took are set aside when their stage is otherwise
    reviewed, as advance and finalize would with it.
    """
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "worker")
    with _task_lock(root):
        for _transition in range(8):
            row, moved = _next_unlocked(root, worker, bundle_id, helper, skip_declined)
            if row is not None or not moved:
                return row
        return None


def claim(
    task_dir: str | Path,
    worker: str,
    bundle_id: str | None = None,
    *,
    helper: str | None = None,
    skip_declined: bool = False,
) -> str:
    """What a worker reads when it asks for a bundle: the bundle as text, with
    the decisions recorded since its last bundle, or why none waits for it."""
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "worker")
    row = next_bundle(
        root, worker, bundle_id, helper=helper, skip_declined=skip_declined
    )
    if row is None:
        return _no_bundle(root, worker)
    with _task_lock(root):
        _root, _task, checkpoint = _load_task(root)
        record = checkpoint["workers"][worker]
        seen = str(record.get("decisions_seen") or "")
        newer = [entry for entry in _decisions(root) if str(entry["at"]) > seen]
        if newer:
            record["decisions_seen"] = max(str(entry["at"]) for entry in newer)
            _atomic_write_json(root / "checkpoint.json", checkpoint)
    text = render_bundle(root, row["id"])
    if newer:
        text += "\n## DECISIONS recorded since your last bundle\n" + "\n".join(
            map(_decision_line, newer)
        ) + "\n"
    return text


def _no_bundle(root: Path, worker: str) -> str:
    state = status(root)
    stage = state["stage"]
    if stage not in REVIEW_STAGES:
        return f"No bundle for {worker}: QA is {stage}.\n"
    metrics = state[stage]
    return (
        f"No bundle for {worker} now: the {stage} stage has "
        f"{metrics['bundles_pending']} waiting for another reviewer and "
        f"{metrics['bundles_assigned']} in review.\n"
    )


def accept_text(
    task_dir: str | Path,
    result_path: str | Path,
    *,
    worker: str = "",
    then_next: bool = False,
) -> str:
    """Accept a result and say so in one line; with *then_next*, also claim
    and print the worker's next bundle, so each bundle costs one round."""
    root = Path(task_dir).expanduser().resolve()
    accept_result(root, result_path)
    bundle_id = str(_read_json(Path(result_path).expanduser().resolve())["bundle_id"])
    text = f"Accepted {bundle_id}.\n"
    if not then_next:
        return text
    _root, _task, checkpoint = _read_task(root)
    worker = worker or str(_bundle_row(checkpoint, bundle_id)[1].get("assigned_to") or "")
    if not worker:
        return text + "Name your worker to claim the next bundle.\n"
    started = str((checkpoint.get("workers") or {}).get(worker, {}).get("run_started") or "")
    reviewed = sum(
        row["status"] == "accepted" and row.get("assigned_to") == worker
        and str(row.get("accepted_at") or "") >= started
        for stage in REVIEW_STAGES for row in checkpoint[stage]["bundles"]
    )
    if started and reviewed >= RUN_BUNDLES:
        return text + (
            f"This run has reviewed {reviewed} bundles: stop now and end with your "
            "one-line report; a fresh run continues.\n"
        )
    return text + "\n" + claim(root, worker)


def _stage_finished(
    checkpoint: dict[str, Any], stages: list[str], skip_declined: bool = False
) -> bool:
    return all(
        row["status"] in FINISHED_STATUSES
        or skip_declined and row["status"] == "pending" and row.get("declined_by")
        for stage in stages for row in checkpoint[stage]["bundles"]
    )


def _next_unlocked(
    root: Path,
    worker: str,
    bundle_id: str | None,
    helper: str | None = None,
    skip_declined: bool = False,
) -> tuple[dict[str, Any] | None, bool]:
    """One assignment attempt; True when it moved QA to its next stage instead."""
    root, task, checkpoint = _load_task(root)
    helper = _register_worker(checkpoint, worker, helper)
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    stage = checkpoint["stage"]
    if stage not in REVIEW_STAGES:
        if bundle_id:
            raise ValueError(f"No bundle can be claimed in the {stage} stage")
        return None, False
    if stage == "screen" and _stage_finished(checkpoint, ["screen"]):
        # Screening ended while early deep bundles wait: deep review is the
        # stage now, as advance would make it.
        _advance_unlocked(root)
        return None, True
    # Deep bundles open while screening continues; screening comes first.
    stages = ["screen", "deep"] if stage == "screen" else [stage]
    bundles = [row for name in stages for row in checkpoint[name]["bundles"]]
    if bundle_id:
        claimed_stage, pending = _bundle_row(checkpoint, bundle_id)
        if claimed_stage not in stages:
            raise ValueError(f"{bundle_id} belongs to the {claimed_stage} stage")
        if pending["status"] == "assigned" and pending.get("assigned_to") == worker:
            return copy.deepcopy(pending), False
        if pending["status"] != "pending":
            raise ValueError(f"{bundle_id} is {pending['status']}, not waiting")
        if helper in (pending.get("declined_helpers") or []):
            raise ValueError(
                f"{worker} runs on the {helper} helper, which declined {bundle_id}; "
                "only a worker on another helper can claim it"
            )
        if worker in (pending.get("authors") or []):
            raise ValueError(
                f"{worker} wrote corrections in {bundle_id}; an independent "
                "reviewer must confirm them"
            )
        if worker in (pending.get("independent_of") or []):
            raise ValueError(
                f"{worker} screened the lines {bundle_id} checks; an independent "
                "reviewer must check them"
            )
    else:
        for row in bundles:
            if row["status"] == "assigned" and row.get("assigned_to") == worker:
                return copy.deepcopy(row), False
        eligible = [
            (name, row) for name in stages for row in checkpoint[name]["bundles"]
            if helper not in (row.get("declined_helpers") or [])
            and worker not in (row.get("authors") or [])
            and worker not in (row.get("independent_of") or [])
        ]
        pending = next(
            (row for _name, row in eligible if row["status"] == "pending"), None
        )
        stalled = next(
            (row for name, row in eligible if _stalled(checkpoint, name, row)),
            None,
        )
        if pending is None and stalled is not None:
            # Its worker stopped answering; the first result accepted counts.
            pending = stalled
            pending["reassigned_from"] = pending.get("assigned_to") or ""
        if pending is None:
            if not _stage_finished(checkpoint, [stage], skip_declined):
                return None, False
            # Every bundle of the stage is reviewed: move QA on, as advance
            # and finalize would.
            if stage == "screen":
                _advance_unlocked(root, skip_declined)
            else:
                _finalize_unlocked(root, skip_declined)
            after = _read_json(root / "checkpoint.json")
            # QA moved to another stage, or opened more bundles of this one.
            return None, after["stage"] != stage or (
                after["stage"] in REVIEW_STAGES
                and not _stage_finished(after, [after["stage"]])
            )
    pending["status"] = "assigned"
    pending["assigned_to"] = worker
    pending["assigned_at"] = _utc_now()
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return copy.deepcopy(pending), False


def decline_items(
    task_dir: str | Path,
    worker: str,
    bundle_id: str,
    declined: list[dict[str, str]],
    *,
    helper: str | None = None,
) -> dict[str, Any]:
    """Decline items of a bundle that no other worker holds, without
    reviewing the rest, as a coordinator does for items it read.

    The declined items move to a bundle of their own, as a result's declines
    do, and the rest to a new bundle in the same place and with the same
    holder, so the next reviewer never sees what was declined.
    """
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "").strip()
    if not worker:
        raise ValueError("Name the worker that declines")
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        helper = _register_worker(checkpoint, worker, helper)
        return _decline(root, checkpoint, worker, helper, bundle_id, declined)


def _decline(
    root: Path,
    checkpoint: dict[str, Any],
    worker: str,
    helper: str,
    bundle_id: str,
    declined: list[dict[str, str]],
) -> dict[str, Any]:
    """decline_items under the task's lock, for a worker on *helper*."""
    stage, row = _bundle_row(checkpoint, bundle_id)
    holder = str(row.get("assigned_to") or "")
    if row["status"] == "assigned" and holder != worker:
        raise ValueError(
            f"{holder} holds {bundle_id} and declines items in its result"
        )
    if row["status"] not in {"pending", "assigned"}:
        raise ValueError(
            f"{bundle_id} is {row['status']}; only a waiting bundle's items "
            "can be declined"
        )
    if row.get("check_of"):
        raise ValueError(
            f"{bundle_id} checks lines screened already; its reviewer declines "
            "items in its result"
        )
    if helper in (row.get("declined_helpers") or []):
        raise ValueError(f"A worker on the {helper} helper declined {bundle_id}")
    bundle = _read_json(Path(row["path"]))
    reasons = _declined_items(bundle, {"declined": declined})
    if not reasons:
        raise ValueError("Name each item to decline with a one-line reason")
    split, remaining = _split_declined(
        root, checkpoint, stage, row, bundle, reasons, worker
    )
    remainder = None
    if remaining:
        origin = row.get("origin") or row["id"]
        rest = _make_bundle(
            stage,
            f"{origin}-r{_next_number(checkpoint, stage, origin)}",
            remaining,
            _shared_context(bundle, remaining),
        )
        remainder = _add_row(root, checkpoint, stage, rest, {
            **{
                key: row[key]
                for key in (
                    "status", "assigned_to", "assigned_at", "follow_up",
                    "declined_by", "declined_helpers", "declines", "round",
                )
                if key in row
            },
            "origin": origin,
        }, after=row)
    row["status"] = "split"
    row["remainder"] = remainder["id"] if remainder else ""
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return {
        "declined": copy.deepcopy(split),
        "remainder": copy.deepcopy(remainder),
    }


def release_bundle(task_dir: str | Path, bundle_id: str) -> dict[str, Any]:
    """Return one unfinished assignment to the queue without changing coverage."""
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        _stage, row = _bundle_row(checkpoint, bundle_id)
        if row["status"] == "accepted":
            raise ValueError("An accepted QA bundle cannot be released")
        if row["status"] != "assigned":
            raise ValueError("Only an assigned QA bundle can be released")
        row["status"] = "pending"
        row["assigned_to"] = ""
        row.pop("assigned_at", None)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)
