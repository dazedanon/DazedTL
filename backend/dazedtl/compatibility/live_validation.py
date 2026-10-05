"""Reconcile old Live rejection receipts without rewriting runs or sending work."""

from functools import lru_cache
import json
from pathlib import Path
import re

from dazedtl.translation.files import project_path
from .batch_validation import canonical, source_value
from .process_view import (
    _ledger_records,
    _read_cached,
    _verified_digest,
    file_stamp,
    source_values,
)


def finished_files(root):
    try:
        job_path, plan_path = (
            project_path(root, name) for name in ("job.json", "plan.json")
        )
        job = _read_cached(str(job_path), file_stamp(job_path))
        if (
            job.get("mode") != "translate"
            or job.get("status") != "complete"
            or job.get("plan_hash")
            != _verified_digest(str(plan_path), file_stamp(plan_path))
        ):
            return frozenset()
        plan = _read_cached(str(plan_path), file_stamp(plan_path))
        if plan.get("mode") != "translate" or set(plan.get("selected", [])) != set(
            job.get("files", [])
        ):
            return frozenset()
        complete = set(job.get("completed", [])) & set(plan.get("selected", [])) - set(
            job.get("errors", {})
        )
        result = set()
        for name in complete:
            path = project_path(root, "translated/" + name, exists=False)
            if path.is_file() and job.get("outputs", {}).get(name) == _verified_digest(
                str(path), file_stamp(path)
            ):
                result.add(name)
        return frozenset(result)
    except (OSError, ValueError, KeyError):
        return frozenset()


@lru_cache(maxsize=8)
def rejection_log(path, stamp):
    with path.open(encoding="utf-8") as stream:
        text = stream.read(64_000_001)
    if len(text) > 64_000_000 or file_stamp(path) != stamp:
        return {}
    marker = re.compile(
        r"Validation mismatch: ([^\n]+)\nOriginal text kept after (\d+) attempts\.\nInput:\n"
    )
    decoder, offset, result = json.JSONDecoder(), 0, {}
    # Walk complete structured records, never search inside arbitrary provider
    # prose for log-shaped text. An unparseable body ends recovery at that point.
    while offset < len(text):
        match = marker.match(text, offset)
        if not match:
            break
        try:
            source, end = decoder.raw_decode(text, match.end())
            prefix = "\nProvider output:\n"
            if not text.startswith(prefix, end):
                break
            start = end + len(prefix)
            _, end = decoder.raw_decode(text, start)
            if not text.startswith("\n\n", end):
                break
            if source_value(source):
                key = (match[1], canonical(source))
                result.setdefault(key, []).append((int(match[2]), text[start:end]))
            offset = end + 2
        except ValueError:
            break
    return result


@lru_cache(maxsize=8)
def outcomes(root, ledger_stamp, log_stamp, files):
    rows = _ledger_records(root, ledger_stamp, False)
    records = rejection_log(Path(root) / "log/mismatchHistory.txt", log_stamp)
    groups = {}
    for index, row in enumerate(rows):
        source = source_values(row["params"])
        if row["filename"] not in files or source is None:
            continue
        # Native validation retries alter only the final source message. Keep
        # the rest of the frozen payload to reject ambiguous scene associations.
        messages = list(row["params"].get("messages", []))
        for position in range(len(messages) - 1, -1, -1):
            if source_values({"messages": [messages[position]]}) == source:
                messages[position] = {
                    **messages[position],
                    "content": canonical(source),
                }
                break
        context = canonical({**row["params"], "messages": messages})
        key = (row["filename"], canonical(source))
        groups.setdefault(key, []).append((index, context, row))
    result = {}
    for key, group in groups.items():
        evidence = records.get(key, [])
        if (
            len(evidence) != 1
            or len({context for _, context, _ in group}) != 1
            or evidence[0][0] != len(group)
            or any(
                row["state"] != "received" or row["raw_response"] is not None
                for _, _, row in group
            )
        ):
            continue
        for index, _, _ in group:
            result[index] = {
                "state": "rejected",
                "error": {
                    "code": "retained_live_rejection",
                    "message": "Saved validation records confirm this request was rejected and its original text was kept. Individual earlier retry bodies were not retained.",
                },
            }
        # The native log preserves only the final attempt's formatted body.
        # It cannot stand in for any of the earlier responses.
        result[group[-1][0]].update(
            raw_response={"text": evidence[0][1]}, responseOrigin="log"
        )
    return result


def reconcile(root, rows, ledger_stamp):
    if not any(
        row["state"] == "received" and row["raw_response"] is None for row in rows
    ):
        return rows
    files = finished_files(root)
    if not files:
        return rows
    try:
        path = project_path(root, "log/mismatchHistory.txt")
        stamp = file_stamp(path)
        if stamp[1] > 64_000_000:
            return rows
        changes = outcomes(str(root), ledger_stamp, stamp, files)
        return [
            {**row, **changes[index]} if index in changes else row
            for index, row in enumerate(rows)
        ]
    except (OSError, ValueError):
        return rows
