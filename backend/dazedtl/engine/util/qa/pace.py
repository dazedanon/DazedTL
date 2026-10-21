"""Pace and status: how fast workers review, when a bundle stalls, the
task's status, and its reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from util.qa.bundles import _check_counts
from util.qa.interface import interface_capture
from util.qa.schema import REVIEW_STAGES
from util.qa.storage import (
    _atomic_write_json,
    _decisions,
    _read_json,
    _read_task,
    _task_lock,
    rules_changed,
)
from util.rpgmaker_qa_preflight import (
    REASON as NOT_TRANSLATED_REASON,
)
from util.rpgmaker_qa_preflight import (
    kept_digest,
    read_sources,
    with_kept,
)

# A bundle whose worker has not been seen this long, or three times a typical
# bundle's time when longer, has stalled; the next idle worker takes it.
STALL_MINIMUM_SECONDS = 20 * 60
# Workers seen this recently are active, and reviews in this much of QA's
# latest work measure how many bundles it reviews at once.
ACTIVE_WORKER_SECONDS = 30 * 60

# QA's latest work reviews one bundle at a time while others wait when it held
# this many bundles and fewer than this many were in review at once.
ONE_AT_A_TIME_BUNDLES = 3
ONE_AT_A_TIME_BELOW = 1.5
# Seconds one review target takes, by stage, until the task has measured it.
DEFAULT_SECONDS_PER_ITEM = {"screen": 5.0, "deep": 60.0, "sweep": 4.0, "editorial": 30.0}


def _reviewed_seconds(rows: list[dict[str, Any]]) -> list[tuple[float, int]]:
    """Each accepted bundle's review time and target count."""
    return [
        (
            (
                datetime.fromisoformat(row["accepted_at"])
                - datetime.fromisoformat(row["assigned_at"])
            ).total_seconds(),
            int(row["item_count"]),
        )
        for row in rows
        if row["status"] == "accepted"
        and row.get("assigned_at")
        and row.get("accepted_at")
        and int(row["item_count"])
    ]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    )


def _seconds_per_item(checkpoint: dict[str, Any], stage: str) -> float:
    timed = _reviewed_seconds(checkpoint.get(stage, {}).get("bundles", []))
    if not timed:
        return DEFAULT_SECONDS_PER_ITEM[stage]
    return _median([seconds / count for seconds, count in timed])


def _stall_after(checkpoint: dict[str, Any], stage: str) -> float:
    timed = _reviewed_seconds(checkpoint.get(stage, {}).get("bundles", []))
    typical = _median([seconds for seconds, _count in timed]) if timed else 0.0
    return max(STALL_MINIMUM_SECONDS, 3 * typical)


def _stalled(checkpoint: dict[str, Any], stage: str, row: dict[str, Any]) -> bool:
    if row["status"] != "assigned" or not row.get("assigned_at"):
        return False
    seen = (checkpoint.get("workers") or {}).get(row.get("assigned_to") or "", {})
    last = max(
        datetime.fromisoformat(row["assigned_at"]),
        datetime.fromisoformat(seen.get("last_seen") or row["assigned_at"]),
    )
    idle = (datetime.now(timezone.utc) - last).total_seconds()
    return idle > _stall_after(checkpoint, stage)


def _pace(checkpoint: dict[str, Any], now: datetime) -> tuple[float, int]:
    """How many bundles QA reviewed at once in its latest work, on average,
    and how many bundles that work held.

    Reviewers are counted by the bundles they held, not the names they used:
    one session taking turns under two names reviews one bundle at a time.
    The window ends at the latest review, so a pause leaves the pace as QA
    last worked; idle time between bundles inside it slows the pace, as it
    slows QA.
    """
    spans = []
    for stage in REVIEW_STAGES:
        for row in (checkpoint.get(stage) or {}).get("bundles", []):
            if not row.get("assigned_at"):
                continue
            if row["status"] == "accepted" and row.get("accepted_at"):
                end = datetime.fromisoformat(row["accepted_at"])
            elif row["status"] == "assigned" and not _stalled(checkpoint, stage, row):
                end = now
            else:
                continue
            spans.append((datetime.fromisoformat(row["assigned_at"]), end))
    if not spans:
        return 0.0, 0
    latest = max(end for _start, end in spans)
    recent = [
        span for span in spans
        if span[1] > latest - timedelta(seconds=ACTIVE_WORKER_SECONDS)
    ]
    start = max(
        latest - timedelta(seconds=ACTIVE_WORKER_SECONDS),
        min(begin for begin, _end in recent),
    )
    window = (latest - start).total_seconds()
    reviewing = sum((end - max(begin, start)).total_seconds() for begin, end in recent)
    return (reviewing / window if window > 0 else 1.0), len(recent)


def _estimate(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """The work left by stage and the engine's estimate of its time."""
    now = datetime.now(timezone.utc)
    active = sorted(
        name for name, worker in (checkpoint.get("workers") or {}).items()
        if worker.get("last_seen")
        and (now - datetime.fromisoformat(worker["last_seen"])).total_seconds()
        <= ACTIVE_WORKER_SECONDS
    )
    remaining = {}
    for stage in REVIEW_STAGES:
        state = checkpoint.get(stage) or {}
        total = int(state.get("total_items", 0))
        if stage == "deep":
            total = max(total, int(state.get("projected_items", 0)))
        set_aside = sum(
            row["item_count"] for row in state.get("bundles", [])
            if row["status"] == "set-aside"
        )
        remaining[stage] = max(0, total - int(state.get("accepted_items", 0)) - set_aside)
        if stage == "screen":
            checks = _check_counts(state)
            remaining[stage] += checks["projected"] - checks["accepted"]
    seconds = sum(
        remaining[stage] * _seconds_per_item(checkpoint, stage) for stage in remaining
    )
    measured = any(
        _reviewed_seconds((checkpoint.get(stage) or {}).get("bundles", []))
        for stage in REVIEW_STAGES
    )
    at_once, recent = _pace(checkpoint, now)
    waiting = any(
        row["status"] == "pending" and not row.get("declined_by")
        for stage in REVIEW_STAGES
        for row in (checkpoint.get(stage) or {}).get("bundles", [])
    )
    return {
        "remaining": remaining,
        "workers": active,
        "in_review_at_once": round(at_once, 1),
        # Bundles waited while reviewers took them one after another.
        "one_at_a_time": waiting
        and recent >= ONE_AT_A_TIME_BUNDLES
        and at_once < ONE_AT_A_TIME_BELOW,
        "eta_seconds": round(seconds / (at_once or 1)) if measured else None,
    }


def _stage_metrics(stage: dict[str, Any], *, active: bool) -> dict[str, Any]:
    # A split bundle's items are in the bundles made from it.
    bundles = [row for row in stage["bundles"] if row["status"] != "split"]
    assigned = [row for row in bundles if row["status"] == "assigned"]
    accepted = [row for row in bundles if row["status"] == "accepted"]
    starts = [
        datetime.fromisoformat(row["assigned_at"])
        for row in bundles if row.get("assigned_at")
    ]
    elapsed_seconds = 0.0
    if starts:
        if active:
            end = datetime.now(timezone.utc)
        else:
            accepted_times = [
                datetime.fromisoformat(row["accepted_at"])
                for row in accepted if row.get("accepted_at")
            ]
            end = max(accepted_times) if accepted_times else min(starts)
        elapsed_seconds = max(0.0, (end - min(starts)).total_seconds())
    accepted_items = int(stage["accepted_items"])
    items_per_minute = (
        accepted_items / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    )
    remaining = max(0, int(stage["total_items"]) - accepted_items)
    eta_seconds = remaining / (items_per_minute / 60) if items_per_minute else None
    return {
        "bundles_accepted": len(accepted),
        "bundles_assigned": len(assigned),
        "bundles_pending": sum(row["status"] == "pending" for row in bundles),
        "bundles_total": len(bundles),
        "assigned_workers": sorted({
            str(row.get("assigned_to") or "") for row in assigned
            if str(row.get("assigned_to") or "")
        }),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "items_per_minute": round(items_per_minute, 1),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
    }


def status(task_dir: str | Path) -> dict[str, Any]:
    # A task an update made unusable still reports where it stood.
    root, task, checkpoint = _read_task(task_dir)
    screen = checkpoint["screen"]
    deep = checkpoint["deep"]
    return {
        "task": str(root),
        "focus": task["focus"],
        "rules_changed": rules_changed(task, checkpoint),
        "stage": checkpoint["stage"],
        "mechanical": {
            "checked": task["counts"]["records"],
            "total": task["counts"]["records"],
            "unresolved": task["counts"]["unresolved"],
        },
        "not_translated": _not_translated(root),
        # Lines earlier QA reviewed, unchanged since, which this task reads
        # only as context.
        **(
            {"reviewed_before": task["reviewed_before"]}
            if task.get("reviewed_before") else {}
        ),
        **(
            {"interface": captured["summary"]}
            if (captured := interface_capture(root))
            else {}
        ),
        "screen": {
            "accepted": screen["accepted_items"],
            "total": screen["total_items"],
            "exceptions": len(screen.get("exception_ids") or []),
            "motif_families": {
                "accepted": int(screen.get("motif_accepted", 0)),
                "total": int(screen.get("motif_total", 0)),
            },
            "lint": {
                "accepted": int(screen.get("lint_accepted", 0)),
                "total": int(screen.get("lint_total", 0)),
                "declined": _declined_lint(screen),
            },
            # Second screens add no coverage, so they are counted apart.
            "checks": _check_counts(screen),
            **_stage_metrics(screen, active=checkpoint["stage"] == "screen"),
        },
        "deep": {
            "accepted": deep["accepted_items"],
            "total": deep["total_items"],
            "projected": deep.get("projected_items", deep["total_items"]),
            **_stage_metrics(deep, active=checkpoint["stage"] == "deep"),
        },
        "sweep": {
            "accepted": checkpoint.get("sweep", {}).get("accepted_items", 0),
            "total": checkpoint.get("sweep", {}).get("total_items", 0),
            **_stage_metrics(
                checkpoint.get("sweep") or {
                    "bundles": [], "accepted_items": 0, "total_items": 0,
                },
                active=checkpoint["stage"] == "sweep",
            ),
        },
        "editorial": {
            "accepted": checkpoint.get("editorial", {}).get("accepted_items", 0),
            "total": checkpoint.get("editorial", {}).get("total_items", 0),
            "round": checkpoint.get("editorial", {}).get("round", 0),
            **_stage_metrics(
                checkpoint.get("editorial") or {
                    "bundles": [], "accepted_items": 0, "total_items": 0,
                },
                active=checkpoint["stage"] == "editorial",
            ),
        },
        "decisions": len(_decisions(root)),
        "observations": len(checkpoint.get("observations") or []),
        "estimate": _estimate(checkpoint),
        "declined": _declined_counts(checkpoint),
        "findings_file": checkpoint.get("findings_file") or "",
    }


# Each task's never-translated counts and the plugin decisions they follow,
# kept while its preflight.json is unchanged: the app reads them every poll.
_REPORTS: dict[Path, tuple[tuple[int, int, int], dict[str, Any]]] = {}


def _report_summary(root: Path) -> dict[str, Any]:
    path = root / "preflight.json"
    try:
        stat = path.stat()
    except FileNotFoundError:
        # A task from before the preflight.
        return {"total": 0, "may_show": 0, "kept_sha256": None}
    signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    cached = _REPORTS.get(path)
    if cached and cached[0] == signature:
        return cached[1]
    report = _read_json(path)
    summary = {**_counted(report), "kept_sha256": report.get("kept_sha256")}
    _REPORTS[path] = (signature, summary)
    return summary


def _counted(report: dict[str, Any]) -> dict[str, int]:
    """A report's never-translated text, and what players may see of it; one
    from before reach was read counts it all as what players may see."""
    total = sum(report["counts"].values())
    return {"total": total, "may_show": report.get("may_show", total)}


def _not_translated(root: Path) -> dict[str, int]:
    """Japanese never translated, which QA did not review: all of it, and
    what players may see, as the task's preflight.json reports it now."""
    summary = _report_summary(root)
    return {"total": summary["total"], "may_show": summary["may_show"]}


def _not_translated_report(report: dict[str, Any]) -> dict[str, Any]:
    """Never a passing count: Japanese no reviewer read, by file and plugin,
    with whether players can reach it; preflight.json lists its text."""
    return {
        "reason": NOT_TRANSLATED_REASON,
        **_counted(report),
        "sources": [
            {key: value for key, value in source.items() if key != "texts"}
            for source in read_sources(report)
        ],
    }


def _write_report(root: Path, report: dict[str, Any]) -> None:
    """Saves the never-translated report a task holds now, its findings' copy
    first; the caller holds the task's lock."""
    path = root / "preflight.json"
    if path.is_file() and _read_json(path) == report:
        return
    findings = root / "findings.json"
    if findings.is_file():
        document = _read_json(findings)
        document["not_translated"] = _not_translated_report(report)
        if "coverage" in document:
            document["coverage"]["not_translated"] = _counted(report)
        _atomic_write_json(findings, document)
    _atomic_write_json(path, report)


def refresh_kept(task_dir: str | Path, kept: Iterable[dict[str, Any]]) -> None:
    """Has a task's never-translated report follow the plugin task's
    decisions, which change without changing the game's files, from the
    plugin settings the report recorded.

    Polls call it, so it costs a file check while the decisions are those
    the report followed, and leaves the work to a later call while another
    process holds the task. A report from before it recorded the settings
    waits for the task to be prepared again.
    """
    root = Path(task_dir).expanduser().resolve()
    kept = list(kept)
    recorded = _report_summary(root)["kept_sha256"]
    if recorded is None or recorded == kept_digest(kept):
        return
    with _task_lock(root, wait=False) as locked:
        if not locked:
            return
        report = with_kept(_read_json(root / "preflight.json"), kept)
        if report is None:
            return
        try:
            _write_report(root, report)
        except OSError:
            # Windows can't replace a file another program is reading; a
            # later poll writes it.
            pass


def _declined_lint(screen: dict[str, Any]) -> int:
    """Lint proposals declined and not reviewed since, which lint review no
    longer waits for."""
    if int(screen.get("lint_accepted", 0)) >= int(screen.get("lint_total", 0)):
        return 0
    return sum(
        item["target_count"]
        for row in screen["bundles"]
        if row.get("declined_by")
        and row["status"] in {"pending", "assigned", "set-aside"}
        for item in _read_json(Path(row["path"]))["items"]
        if item.get("kind") == "lint-family"
    )


def _declined_counts(checkpoint: dict[str, Any]) -> dict[str, int]:
    rows = [
        row for stage in REVIEW_STAGES
        for row in checkpoint.get(stage, {}).get("bundles", [])
        if row.get("declined_by")
    ]
    return {
        "waiting": sum(
            row["item_count"] for row in rows
            if row["status"] in {"pending", "assigned"}
        ),
        "set_aside": sum(
            row["item_count"] for row in rows if row["status"] == "set-aside"
        ),
    }
