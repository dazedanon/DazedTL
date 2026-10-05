"""Retain approved Batch inspection evidence before native scratch cleanup."""

from functools import wraps
from pathlib import Path

from dazedtl.storage import write_json
from .process_view import saved

ARCHIVE = "dazedtl-batch-evidence.json"


def merge(previous, current):
    result = dict(previous)
    for key, value in current.items():
        if key in result and result[key] != value:
            raise ValueError(
                "Batch evidence conflicts with an already retained request or response."
            )
        result[key] = value
    return result


def preserve(root, requests, results, state):
    old = saved(root, ARCHIVE)
    history = saved(root, "batch_history.json").get("batches", [])
    # Never turn an unapproved preparation into retained run history.
    if not any(batch.get("custom_ids") for batch in history):
        return
    from .batch_refusals import RESULTS, effective_results

    clarified = saved(root, RESULTS)
    if clarified:
        effective_results(root, old.get("results", {}), results)
        # The archive owns original provider bodies; the clarification journal
        # supplies their effective replacements. Native cleanup may see either.
        results = {
            key: clarified["original"].get(key, value) for key, value in results.items()
        }
    value = {
        "version": 1,
        "requests": merge(old.get("requests", {}), requests),
        "results": merge(old.get("results", {}), results),
    }
    if not value["requests"]:
        return
    manifests = {
        batch["id"]: batch for batch in old.get("state", {}).get("batches", [])
    }
    manifests.update({batch["id"]: batch for batch in state.get("batches", [])})
    value["state"] = {
        **old.get("state", {}),
        **state,
        "batches": list(manifests.values()),
    }
    target = Path(root) / "log" / ARCHIVE
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("Retained Batch evidence must stay inside its run.")
    if value != old:
        write_json(target, value)


def install(translation, root, plan):
    if (
        plan.get("mode") != "batch"
        or plan.get("batch_link")
        or not hasattr(translation, "_clear_batch_queue_storage")
    ):
        return
    original = getattr(
        translation._clear_batch_queue_storage,
        "_dazedtl_native",
        translation._clear_batch_queue_storage,
    )

    @wraps(original)
    def clear(*args, **kwargs):
        if (
            kwargs.get("queue_file", translation.BATCH_QUEUE_FILE)
            == translation.BATCH_QUEUE_FILE
        ):
            preserve(
                root,
                translation._read_batch_queue(
                    strict=True, queue_file=translation.BATCH_QUEUE_FILE
                ),
                translation._read_batch_file(
                    translation.BATCH_RESULTS_FILE, strict=True
                ),
                translation._read_batch_file(translation.BATCH_STATE_FILE, strict=True),
            )
        return original(*args, **kwargs)

    clear._dazedtl_native = original
    translation._clear_batch_queue_storage = clear
