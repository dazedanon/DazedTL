"""Returning a task to deep review for new evidence: observations made
later, and interface screens captured again."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from util import rpgmaker_screens, system
from util.paths import unlink_with_retry
from util.qa.advance import _issue_deep
from util.qa.interface import (
    INTERFACE_FOLDER,
    RECAPTURE_OBSERVER,
    _capture_record,
    _capture_round,
    _save_capture_record,
)
from util.qa.ledger import REVIEWED_FILE
from util.qa.schema import _utc_now
from util.qa.storage import (
    JUDGED_BEFORE,
    _atomic_write_json,
    _load_task,
    _observation_key,
    _task_lock,
)


def _recapture(
    root: Path,
    data: Path,
    manifest: dict[str, Any],
    progress: Callable[[str], None] | None,
) -> None:
    """Capture a reused task's interface screens again once the plugin files
    they ran with changed, keeping its review. Lines the new capture finds
    squeezed go to deep review as observations; a complete task goes back to
    deep review for them, as for an observation made after deep review.

    A reused task always holds the text it reviewed, since applying its
    corrections changes the inventory and so the task, so no correction of
    it is in the game when its findings are made again."""
    previous = _capture_record(root)
    if previous is None or previous.get(
        "plugins_sha256"
    ) == rpgmaker_screens.plugins_sha256(data):
        return
    record, places = _capture_round(
        data, root, previous["round"] + 1, manifest, progress
    )
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        complete = checkpoint["stage"] == "complete"
        candidates = checkpoint["deep"].get("candidate_reasons") or {}
        # A line observed for another reason, such as by the playtest, was
        # not judged squeezed.
        observed = {
            row["cluster_id"] for row in checkpoint.get("observations") or []
            if row.get("worker") == RECAPTURE_OBSERVER
        }
        fresh = sorted(
            cluster_id for cluster_id in places
            if "interface-fit" not in (candidates.get(cluster_id) or {}).get("reasons", [])
            and cluster_id not in observed
        )
        # Deep items read the squeezed places from the latest capture.
        _save_capture_record(root, record)
        if fresh:
            # A cluster is named by its representative line.
            _note_observations(
                checkpoint,
                [
                    {
                        "identity": cluster_id,
                        "cluster_id": cluster_id,
                        "categories": ["ui"],
                        "note": "The game draws this text with too little room on a "
                        "screen captured again after its plugin files changed.",
                    }
                    for cluster_id in fresh
                ],
                checkpoint["stage"],
                RECAPTURE_OBSERVER,
            )
            checkpoint["updated_at"] = _utc_now()
            _atomic_write_json(root / "checkpoint.json", checkpoint)
            if complete:
                _follow_up(root, checkpoint)
            else:
                _issue_new_evidence(root, checkpoint)
    if complete:
        # Review bundles name the captures they were made with; a follow-up
        # round's name only the latest.
        for folder in (root / INTERFACE_FOLDER).glob("round-*"):
            if folder.name != record["folder"]:
                system.remove_tree(folder, ignore_errors=True)


def _observe_again(
    root: Path, observations: list[dict[str, Any]], observer: str
) -> None:
    """Observations a reused task does not hold yet, such as a later
    playtest's, go to its review: at once while it reviews, and in a
    follow-up deep round once complete, keeping the review done so far."""
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        known = {
            _observation_key(row)
            for row in [
                *(checkpoint.get("observations") or []),
                *(checkpoint.get(JUDGED_BEFORE) or []),
            ]
        }
        fresh = [row for row in observations if _observation_key(row) not in known]
        if not fresh:
            return
        _note_observations(checkpoint, fresh, checkpoint["stage"], observer)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        if checkpoint["stage"] == "complete":
            _follow_up(root, checkpoint)
        else:
            _issue_new_evidence(root, checkpoint)


def _note_observations(
    checkpoint: dict[str, Any],
    observations: list[dict[str, Any]],
    stage: str,
    worker: str,
    bundle_id: str = "",
) -> None:
    checkpoint.setdefault("observations", []).extend(
        {
            **observation,
            "stage": stage,
            "worker": worker,
            **({"bundle": bundle_id} if bundle_id else {}),
            "at": _utc_now(),
        }
        for observation in observations
    )


def _issue_new_evidence(root: Path, checkpoint: dict[str, Any]) -> None:
    """Open deep items for new evidence while QA still takes them: in early
    batches while screening continues and at once during deep review. Later
    stages leave it for a follow-up deep round."""
    stage = checkpoint["stage"]
    if stage in {"screen", "deep"} and _issue_deep(
        root, checkpoint, final=stage == "deep"
    ):
        _atomic_write_json(root / "checkpoint.json", checkpoint)


def _follow_up(root: Path, checkpoint: dict[str, Any]) -> bool:
    """Return QA to deep review for observations made after its last deep
    round; a complete task's findings are made again once that round ends."""
    observations = len(checkpoint.get("observations") or [])
    if observations <= int(checkpoint["deep"].get("observed", 0)):
        return False
    if not _issue_deep(root, checkpoint, final=True):
        return False
    checkpoint["stage"] = "deep"
    checkpoint["findings_file"] = ""
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    # Nothing applies findings of a task in review, and later tasks build on
    # its reviews only once it is complete again; the app's polls read these
    # files, and Windows can't remove a file while one does.
    for name in ("findings.json", REVIEWED_FILE):
        if (root / name).is_file():
            unlink_with_retry(root / name)
    return True
