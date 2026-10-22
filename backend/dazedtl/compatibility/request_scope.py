"""Local source identity, receipts and protection across independently saved runs.

Identity excludes model, prompt and chunk size. Legacy queues lack file/field
provenance, so their source text is matched only inside the saved phase/files.
"""

import json

from dazedtl.translation.files import digest, read_json

from .batch_evidence import served_files
from .process_view import (
    batch_results,
    batch_state,
    consumed_files,
    evidence_root,
    kept_lines,
    ledger_records,
    queue,
    saved,
    source_values,
)


def identities(filename, phase, values, locations=None):
    return [
        digest(
            {
                "file": filename,
                "phase": phase,
                "source": text,
                **({"locations": locations.get(text, [])} if locations else {}),
            }
        )
        for text in values
    ]


_SCALARS = {int, float, bool, type(None)}


def source_locations(value, path=""):
    """Each string's paths in document order."""
    result = {}
    if isinstance(value, str):
        result[value] = [path]
    else:
        _index_strings(value, path, result)
    return result


def _index_strings(value, path, result):
    if isinstance(value, list):
        # A map's tile data holds tens of thousands of numbers.
        if set(map(type, value)) <= _SCALARS:
            return
        children = enumerate(value)
    elif not isinstance(value, dict):
        return
    elif "_original" in value:
        # Database originals map field names; event originals may instead be
        # a dialogue string or choice list. Those are not field overlays: keep
        # indexing the current parameters that the native parser will inspect.
        original = value["_original"]
        fields = original if isinstance(original, dict) else {}
        children = (
            (key, fields.get(key, item))
            for key, item in value.items()
            if key != "_original"
        )
    else:
        children = value.items()
    for key, item in children:
        if isinstance(item, str):
            result.setdefault(item, []).append(path + "/" + str(key))
        elif isinstance(item, (list, dict)):
            _index_strings(item, path + "/" + str(key), result)


def columns(connection):
    return {row[1] for row in connection.execute("PRAGMA table_info(requests)")}


def requests(root, job, queued=None, records=None):
    """Only positive rejection receipts release a submitted Batch request.

    A caller that already read the run's queue or ledger passes it in.
    """
    queued = queue(root) if queued is None else queued
    if queued:
        evidence = evidence_root(root)
        batches = saved(evidence, "batch_history.json").get("batches", [])
        state = batch_state(evidence)
        results = batch_results(evidence)
        manifests = {
            row["id"]: row.get("custom_ids", {})
            for row in state.get("batches", [])
            if row.get("id")
        }
        outcomes, provider_finished = {}, {}
        for batch in batches:
            mapping = batch.get("custom_ids", {})
            counts = batch.get("request_counts") or {}
            rejected = (
                batch.get("api_status")
                in {"completed", "ended", "cancelled", "canceled", "expired"}
                and manifests.get(batch.get("id")) == mapping
                and all(
                    type(counts.get(key)) is int and counts[key] == 0
                    for key in ("processing", "succeeded")
                )
                and all(
                    type(counts.get(key, 0)) is int and counts.get(key, 0) >= 0
                    for key in ("errored", "canceled", "expired")
                )
                and sum(
                    counts.get(key, 0) for key in ("errored", "canceled", "expired")
                )
                == len(mapping)
            )
            # An ended provider receipt whose counts cover every request proves
            # submission until its results are downloaded: while the native
            # runner waits for other batches, and after a cancellation or
            # expiry until the app collects what the provider returned. Keep
            # the paid-work guard until download; a fetched-but-missing
            # response or mismatched manifest remains uncertain.
            awaiting_results = (
                batch.get("api_status")
                in {"completed", "ended", "cancelled", "canceled", "expired"}
                and state.get("status") in {"submitted", "partially_submitted"}
                and manifests.get(batch.get("id")) == mapping
                and bool(mapping)
                and all(
                    type(counts.get(key)) is int and counts[key] >= 0
                    for key in (
                        "processing",
                        "succeeded",
                        "errored",
                        "canceled",
                        "expired",
                    )
                )
                and counts["processing"] == 0
                and sum(
                    counts[key]
                    for key in ("succeeded", "errored", "canceled", "expired")
                )
                == len(mapping)
            )
            for custom, key in mapping.items():
                # Display evidence only: the provider finished every request of
                # an ended Batch, but its counts never say which succeeded, and
                # finishing never releases the paid-work guard.
                provider_finished[key] = (
                    provider_finished.get(key, True) and awaiting_results
                )
                error = next(
                    (
                        row
                        for row in (batch.get("provider_errors") or [])
                        if row.get("custom_id") == custom
                    ),
                    None,
                )
                # Multiple submissions retain the strictest known outcome. A
                # Batch being canceled is still at the provider.
                pending = (
                    batch.get("api_status")
                    in {
                        "validating",
                        "in_progress",
                        "finalizing",
                        "cancelling",
                        "canceling",
                    }
                    and manifests.get(batch.get("id")) == mapping
                )
                outcome = (
                    "received"
                    if key in results
                    else "failed"
                    if rejected or error
                    else "submitted"
                    if pending or awaiting_results
                    else "uncertain"
                )
                priority = {"failed": 0, "submitted": 1, "received": 2, "uncertain": 3}
                if priority[outcome] >= priority.get(outcomes.get(key, ""), -1):
                    outcomes[key] = outcome
        for manifest in state.get("batches", []):
            for key in manifest.get("custom_ids", {}).values():
                outcomes.setdefault(key, "uncertain")
        from .batch_continuation import JOURNAL, refused_create, unsent

        journal = saved(root, JOURNAL)
        intent = journal.get("intent")
        # The latest journaled create may be at the provider until its receipt
        # reaches the saved manifests, even beside earlier submitted chunks.
        if intent and not refused_create(intent):
            for key in (intent.get("custom_ids") or {}).values():
                outcomes.setdefault(key, "uncertain")
        unknown_submission = (
            state.get("status") in {"submission_uncertain", "submitting", "corrupt"}
            or job.get("dazedtl_submission_intent")
            and state.get("status")
            not in {"partially_submitted", "submitted", "fetched"}
            # A create the provider refused, or an attempt that failed before
            # any create, left nothing to duplicate.
            and not refused_create(intent)
            and not unsent(journal, job)
        )
        complete = consumed_files(root)
        from .batch_validation import outcomes as validation_outcomes

        validation = validation_outcomes(root, queued, results)
        from dazedtl.translation.refusals import MESSAGE, refused

        from .batch_refusals import records as clarification_records

        clarification_pending = {
            item["key"]: "uncertain" if batch["state"] == "sending" else "submitted"
            for record in clarification_records(evidence)
            for batch in record["batches"]
            if batch["state"] in {"pending", "sending", "submitted"}
            for item in batch["items"]
        }
        for index, (key, entry) in enumerate(queued.items()):
            outcome = outcomes.get(key, "uncertain" if unknown_submission else "queued")
            receipt = validation.get(key, {}) if outcome == "received" else {}
            if receipt:
                outcome = receipt["state"]
            elif outcome == "received" and complete.issuperset(served_files(entry)):
                outcome = "saved"
            if key in clarification_pending:
                outcome, receipt = clarification_pending[key], {}
            elif key in results and refused(results[key], json.loads(entry["payload"])):
                outcome, receipt = (
                    "rejected",
                    {"error": {"code": "provider_refusal", "message": MESSAGE}},
                )
            yield {
                "index": index,
                "state": outcome,
                "providerFinished": outcome == "submitted"
                and provider_finished.get(key, False)
                and key not in clarification_pending,
                "source": json.loads(entry["payload"]),
                "keys": entry.get("dazedtl_sources"),
                "file": entry.get("dazedtl_file"),
                "lineFiles": entry.get("dazedtl_line_files"),
                "servedFiles": entry.get("dazedtl_files"),
                "response": results.get(key),
                "error": receipt.get("error"),
                "unused": receipt.get("unused"),
                "keptLines": receipt.get("keptLines"),
            }
        return
    rows = ledger_records(root) if records is None else records
    if rows is not None:
        for index, row in enumerate(rows):
            state = row["state"]
            if state == "prepared" and row["sources"] is None:
                state = "uncertain"
            yield {
                "index": index,
                "state": state,
                "source": source_values(row["params"]) or {},
                "keys": row["sources"],
                "file": row["filename"],
                "response": row["response"],
                "error": row["error"],
                "keptLines": kept_lines(row["kept_lines"])
                if row.get("kept_lines") and state == "validated"
                else None,
            }
        if rows:
            return
    plan_path = root / "plan.json"
    if (
        plan_path.exists()
        and job.get("mode") == "translate"
        and job.get("status")
        in {"running", "waiting", "interrupted", "stopped", "failed"}
    ):
        for row in read_json(plan_path).get("dazedtl_reserved_sources", []):
            yield {**row, "state": "uncertain"}


def strings(source):
    # Request lines are text; nothing else can match another request's lines.
    return [text for text in source.values() if isinstance(text, str)]


def earliest(lookups, filename, shared):
    """The first new request sharing a looked-up value, from a file that can
    hold this earlier request's lines: its own, or any shared file when it
    has none. New requests without a file can hold any."""
    best = None
    for index, values in lookups:
        for value in values:
            found = index.get(value)
            if not found:
                continue
            positions = (
                (found.get(filename), found.get(None))
                if filename
                else (
                    position
                    for name, position in found.items()
                    if name is None or name in shared
                )
            )
            for position in positions:
                if position is not None and (best is None or position < best):
                    best = position
    return best


def overlap(estimate_root, estimate_job, previous):
    current = list(requests(estimate_root, estimate_job))
    phase = estimate_job.get("logicalPhase")
    files = set(estimate_job.get("files", []))
    # Source identities compare when both requests carry them, otherwise
    # source text does. Index the first new request of each file holding a
    # value, so each earlier request is checked once instead of against all.
    keyed, texts, unkeyed = {}, {}, {}
    for position, row in enumerate(current):
        name = row["file"] or None
        for key in row["keys"] or []:
            keyed.setdefault(key, {}).setdefault(name, position)
        for text in strings(row["source"]):
            texts.setdefault(text, {}).setdefault(name, position)
            if not row["keys"]:
                unkeyed.setdefault(text, {}).setdefault(name, position)
    matches = []
    for root, job in previous:
        if (
            job.get("mode") not in {"batch", "translate", "speakers"}
            or job.get("logicalPhase") != phase
        ):
            continue
        shared = files.intersection(job.get("files", [])) - set(
            job.get("retiredFiles", [])
        )
        if not shared:
            continue
        rows = list(requests(root, job))
        for old in rows:
            if old["state"] not in {"submitted", "uncertain", "received"}:
                continue
            if old["file"] and old["file"] not in shared:
                continue
            sources = strings(old["source"])
            position = earliest(
                [(keyed, old["keys"]), (unkeyed, sources)]
                if old["keys"]
                else [(texts, sources)],
                old["file"],
                shared,
            )
            if position is not None:
                new = current[position]
                matches.append(
                    {
                        "run": job["id"],
                        "request": old["index"] + 1,
                        "state": old["state"],
                        "files": [new["file"]] if new["file"] else sorted(shared),
                    }
                )
        if (
            not rows
            and job.get("mode") == "translate"
            and job.get("status") in {"running", "waiting", "interrupted", "stopped"}
        ):
            pending_files = (
                shared.intersection(row["file"] for row in current)
                if current and all(row["file"] for row in current)
                else shared
            )
            if pending_files:
                matches.append(
                    {
                        "run": job["id"],
                        "state": "legacy_unknown",
                        "files": sorted(pending_files),
                    }
                )
    return matches
