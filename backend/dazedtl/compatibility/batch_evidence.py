"""Retain approved Batch inspection evidence before native scratch cleanup."""

from pathlib import Path

from dazedtl.storage import write_json

from .process_view import saved

ARCHIVE = "dazedtl-batch-evidence.json"
# A queued request's fields naming the files it serves. Identical requests of
# several files share one queue entry, so two copies of one request can differ
# here, as each file that asked for it wrote its own.
ATTRIBUTION = frozenset(
    {"dazedtl_file", "dazedtl_sources", "dazedtl_line_files", "dazedtl_files"}
)


def served_files(entry):
    """The files a queued request's response is used in, first asker first."""
    return entry.get("dazedtl_files") or [entry.get("dazedtl_file")]


def joined(kept, entry):
    """`kept` serving the files of both copies of one queued request, or None
    when the two are different requests."""

    def request(value):
        return {key: item for key, item in value.items() if key not in ATTRIBUTION}

    if request(kept) != request(entry):
        return None
    files = list(dict.fromkeys([*served_files(kept), *served_files(entry)]))
    return kept if files == served_files(kept) else {**kept, "dazedtl_files": files}


def extends(retained, value):
    """Whether ``value`` is ``retained`` with fields added, as a response
    downloaded again records usage an older download did not."""
    return (
        isinstance(retained, dict)
        and isinstance(value, dict)
        and all(key in value and value[key] == item for key, item in retained.items())
    )


def merge(previous, current):
    result = dict(previous)
    for key, value in current.items():
        if key in result and result[key] != value and not extends(result[key], value):
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
    """Retains a Batch run's queue, results and state before the run clears them."""
    if plan.get("mode") != "batch" or plan.get("batch_link"):
        return

    def clear(native, *args, **kwargs):
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
        return native(*args, **kwargs)

    translation._clear_run_batch_queue.layer("batch-evidence", clear)
