"""Durable, same-provider Batch retries for confirmed refusals only."""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from copy import deepcopy
from typing import Any

from dazedtl.storage import write_json

from .files import digest, project_path, read_json
from .refusals import clarified, clarifies, refused


def outline(batch):
    """A clarification Batch without its payloads and responses."""
    return {
        **{
            key: batch[key]
            for key in ("id", "state", "api_status", "counts", "usage")
            if key in batch
        },
        "items": [
            {key: item[key] for key in ("key", "custom_id")} for item in batch["items"]
        ],
    }


def summary(record):
    return {
        "original_id": record["original_id"],
        "batches": [outline(batch) for batch in record["batches"]],
    }


def save(path, record):
    view = path.with_suffix(".summary.json")
    active = any(
        batch["state"] in {"pending", "sending", "submitted"}
        for batch in record["batches"]
    )
    # Publish protection before sending; publish completion only after its
    # authoritative receipt. Observers read this small derived view, not prompts.
    if active:
        write_json(view, summary(record))
    write_json(path, record)
    if not active:
        write_json(view, summary(record))


def journal(root, batch_id):
    return project_path(
        root, "log/clarifications/" + digest(batch_id) + ".json", exists=False
    )


def started(root, batch_id):
    """Whether the Batch's clarification journal exists; it then holds the
    Batch's responses, which need not be collected again."""
    return journal(root, batch_id).exists()


def load(path, batch_id, requests):
    """The saved journal, if it still belongs to this Batch and its requests."""
    # Records before version 2 held the params of every request in the Batch,
    # about 26 KB each, so a large Batch's record can exceed the usual cap.
    record = read_json(path, limit=None)
    if record.get("version") == 2:
        # The clarified payloads are the only requests the journal sends; the
        # original Batch's own payloads stay with its run.
        same = set(record["keys"]) == set(requests) and all(
            item["key"] in requests and clarifies(item["params"], requests[item["key"]])
            for batch in record["batches"]
            for item in batch["items"]
        )
    else:
        same = record["requests"] == requests
    if record["original_id"] != batch_id or not same:
        raise ValueError(
            "The saved clarification scope changed. Keep its provider receipts for recovery."
        )
    return record


def advance(
    root,
    batch_id,
    requests,
    responses,
    usage,
    provider,
    *,
    limits=(50_000, 200_000_000),
    input_tokens=lambda _: 0,
    commit: Callable[[], AbstractContextManager[Any]] = nullcontext,
    allow_submit=True,
    reserve=lambda _items: nullcontext(True),
):
    """Clarifies the original Batch's refused requests in Batches of their own.

    `responses` and `usage` are the original Batch's results; they may be None
    once its journal has started, which keeps them. Every outcome carries the
    Batch's responses and usage so far: the original ones while a
    clarification is unfinished, merged with the clarified ones once all end.
    """
    path = journal(root, batch_id)
    if path.exists():
        record = load(path, batch_id, requests)
    else:
        rejected = {
            key: value
            for key, value in responses.items()
            if key in requests and refused(value)
        }
        if not rejected:
            return {
                "ready": True,
                "responses": responses,
                "usage": usage,
                "batches": [],
            }
        chunks, items, size, tokens = [], [], 0, 0
        token_limit = limits[2] if len(limits) > 2 else None
        for key in rejected:
            params = clarified(requests[key])
            item = {
                "custom_id": "clarify-" + digest(key)[:32],
                "params": params,
                "key": key,
            }
            length = len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 1024
            count = input_tokens(params)
            if length > limits[1] or token_limit and count > token_limit:
                raise ValueError(
                    "The clarification exceeds the provider Batch limit. Review a smaller request."
                )
            if items and (
                len(items) >= limits[0]
                or size + length > limits[1]
                or token_limit
                and tokens + count > token_limit
            ):
                chunks.append({"state": "pending", "id": "", "items": items})
                items, size, tokens = [], 0, 0
            items.append(item)
            size += length
            tokens += count
        if items:
            chunks.append({"state": "pending", "id": "", "items": items})
        record = {
            "version": 2,
            "original_id": batch_id,
            "keys": list(requests),
            "original_responses": responses,
            "original_usage": usage,
            "batches": chunks,
        }
        with commit():
            save(path, record)

    def unfinished(**state):
        return {
            "ready": False,
            **state,
            "responses": record["original_responses"],
            "usage": record["original_usage"],
            "batches": record["batches"],
        }

    for batch in record["batches"]:
        if batch["state"] in {"complete", "failed"}:
            continue
        if batch["state"] == "sending":
            return unfinished(uncertain=True)
        if batch["state"] == "pending":
            if not allow_submit:
                batch["state"] = "failed"
                save(path, record)
                continue
            with reserve(batch["items"]) as available:
                if not available:
                    return unfinished(waiting_capacity=True)
                with commit():
                    batch["state"] = "sending"
                    save(path, record)
                try:
                    result = provider.submit(
                        [
                            {key: item[key] for key in ("custom_id", "params")}
                            for item in batch["items"]
                        ]
                    )
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    if type(status) is int and 400 <= status < 500:
                        batch["state"] = "failed"
                        save(path, record)
                        continue
                    raise
                # Retain returned IDs before releasing shared token capacity.
                batch.update(id=result["id"], state="submitted")
                save(path, record)
            return unfinished()
        status = provider.status(batch["id"])
        batch.update(api_status=status["api_status"], counts=status.get("counts") or {})
        if not status["ended"]:
            # The record holds every response of the original Batch, and a
            # clarification can wait for hours, so a poll that changes only
            # the provider's progress publishes just the summary.
            write_json(path.with_suffix(".summary.json"), summary(record))
            return unfinished()
        save(path, record)
        mapping = {item["custom_id"]: item["key"] for item in batch["items"]}
        collect = (
            provider.collect_terminal
            if status["terminal_failure"]
            else provider.collect
        )
        part, errors, used = collect(batch["id"], mapping)
        matched = set(part) | {mapping[key] for key in errors if key in mapping}
        if set(part) - set(mapping.values()) or matched != set(mapping.values()):
            return unfinished(uncertain=True)
        batch.update(state="complete", responses=part, usage=used)
        save(path, record)
    merged, total = (
        deepcopy(record["original_responses"]),
        dict(record["original_usage"]),
    )
    for batch in record["batches"]:
        for key, value in batch.get("responses", {}).items():
            original = merged[key]
            merged[key] = deepcopy(value)
            # Preserve per-request billed usage as well as the aggregate. This
            # also feeds the guided engine's existing file cost accounting.
            for name in set(original) | set(value):
                if name.endswith("tokens"):
                    merged[key][name] = (original.get(name) or 0) + (
                        value.get(name) or 0
                    )
        for key, value in batch.get("usage", {}).items():
            total[key] = total.get(key, 0) + (value or 0)
    return {
        "ready": True,
        "responses": merged,
        "usage": total,
        "batches": record["batches"],
    }
