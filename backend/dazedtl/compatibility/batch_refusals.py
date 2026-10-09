"""Bridge guided Batch collection to the bounded clarification journal."""

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any

from dazedtl.storage import write_json
from dazedtl.translation.batch_refusals import advance
from dazedtl.translation.files import project_path, read_json
from dazedtl.translation.refusals import POLICY, refused

RESULTS = "dazedtl-clarified-results.json"


def records(root, *, details=False):
    folder = Path(root) / "log/clarifications"
    if not folder.exists():
        return []
    if folder.is_symlink():
        raise ValueError("Clarification receipts must stay inside the run.")
    from .process_view import saved

    if details:
        return [
            read_json(path)
            for path in sorted(folder.glob("*.json"))
            if not path.name.endswith(".summary.json")
        ]
    return [
        saved(root, "clarifications/" + path.name)
        for path in sorted(folder.glob("*.summary.json"))
    ]


def effective_results(root, previous, current):
    from .batch_evidence import merge
    from .process_view import saved

    receipt = saved(root, RESULTS)
    if not receipt:
        return merge(previous, current)
    original, effective = receipt["original"], receipt["results"]
    extra = {}
    for source in (previous, current):
        for key, value in source.items():
            if key in original:
                if value != original[key] and value != effective.get(key):
                    raise ValueError(
                        "Batch results conflict with the retained clarification receipts."
                    )
            else:
                extra = merge(extra, {key: value})
    return merge(effective, extra)


def advance_guided(
    root,
    plan,
    resolve,
    *,
    commit: Callable[[], AbstractContextManager[Any]] = nullcontext,
    connection=None,
    allow_submit=True,
):
    from . import batch_control
    from .process_view import batch_results, queue, saved

    if (plan.get("dazedtl_request_policy") or {}).get("refusalRetry") != POLICY:
        return {"ready": True, "batches": []}
    completed = saved(root, RESULTS)
    results = batch_results(root)
    if completed and set(results) == set(completed["results"]):
        # Repair a crash after publishing the receipt but before replacing the
        # native consume file; this operation cannot submit provider work.
        with commit():
            write_json(
                project_path(root, "log/batch_results.json", exists=False),
                completed["results"],
            )
        return {"ready": True, "batches": []}
    # More original chunks can arrive after an interrupted run's first chunk
    # was already clarified. Reuse its journal, and clarify only the new rows.
    if completed:
        results = {**results, **completed["original"]}
    queued = queue(root)
    history = saved(root, "batch_history.json").get("batches", [])
    output, pending = deepcopy(results), []
    for batch in history:
        mapping = batch.get("custom_ids") or {}
        part = {key: results[key] for key in mapping.values() if key in results}
        if not any(refused(value) for value in part.values()):
            continue
        # A canceled/failed provider job is not authorization for more work.
        if batch.get("api_status") not in {"completed", "ended"}:
            continue
        if any(key not in queued for key in mapping.values()):
            raise ValueError(
                "The original Batch payloads are unavailable for clarification."
            )
        connect = connection or (
            lambda batch, resolve: batch_control.connection(
                batch, resolve, receipt_root=root
            )
        )
        with connect(batch, resolve) as provider:
            from util.batch_providers import batch_limits

            from .batch_window import reserve_clarification

            state = saved(root, "batch_state.json")
            limit = (
                state.get("batch_token_allowance")
                or state.get("sequential_token_limit")
                or (
                    (plan.get("dazedtl_request_policy") or {}).get("batchInputTokens")
                    if batch["provider"] == "openai"
                    else None
                )
            )
            limits = batch_limits(batch["provider"])
            if batch["provider"] == "openrouter":
                from dazedtl.settings.openrouter import validate_policy

                frozen = (plan.get("dazedtl_request_policy") or {}).get(
                    "openrouterBatch"
                )
                validate_policy(frozen, plan["settings"]["model"])
                assert frozen is not None  # validate_policy rejects missing policies.
                limits = (frozen["max_requests"], frozen["max_bytes"] - 4096)
            result = advance(
                root,
                batch["id"],
                {key: queued[key]["params"] for key in mapping.values()},
                part,
                batch.get("usage") or {},
                provider,
                limits=(*limits, limit),
                input_tokens=provider.input_tokens,
                commit=commit,
                allow_submit=allow_submit,
                reserve=partial(
                    reserve_clarification,
                    root,
                    plan,
                    count=provider.input_tokens,
                    limit=limit,
                ),
            )
        pending.extend(result["batches"])
        if not result["ready"]:
            return {**result, "batches": pending}
        output.update(result["responses"])
    if pending:
        # Refusal prose must not pass the native JSON/string validators.
        for value in output.values():
            if refused(value):
                value.update(text="", refusal=True)
        with commit():
            write_json(
                project_path(root, "log/" + RESULTS, exists=False),
                {"original": results, "results": output},
            )
            write_json(
                project_path(root, "log/batch_results.json", exists=False), output
            )
    return {"ready": True, "batches": pending}


LAYER = "refusals"


def install_worker(root, plan):
    if (
        plan.get("mode") != "batch"
        or (plan.get("dazedtl_request_policy") or {}).get("refusalRetry") != POLICY
    ):
        return
    from util.translation_task import TranslationTask

    from .provider_responses import install

    install()
    from util import translation

    from .batch_control import TranslationProvider

    def result(native, *args, **kwargs):
        value = native(*args, **kwargs)
        return {**value, "text": ""} if refused(value) else value

    translation.require_batch_result.layer(LAYER, result)

    def files(native, task, matching_files, estimate_only, batch_phase=None):
        if batch_phase == "consume":
            from contextlib import contextmanager

            @contextmanager
            def active():
                if task.should_stop:
                    raise InterruptedError("Stopped before Batch clarification.")
                yield

            # Use the original run's pinned connection, exactly as native fetch.
            from util.batch_history import client_for_batch

            from .translation import google_batch_client

            @contextmanager
            def connection(batch, _resolve):
                provider = object.__new__(TranslationProvider)
                provider.provider = batch["provider"]
                provider.client = client_for_batch(
                    batch["id"],
                    batch["provider"],
                    str(batch.get("key_name") or ""),
                    str(batch.get("endpoint") or ""),
                ).with_options(max_retries=0, timeout=45)
                provider.google = (
                    google_batch_client(provider.client.api_key)
                    if batch["provider"] == "gemini"
                    else None
                )
                try:
                    yield provider
                finally:
                    provider.client.close()
                    if provider.google:
                        provider.google.close()

            # Pass the worker connection factory explicitly; no global SDK or
            # connection mutation while other file threads may be active.
            while not task.should_stop:
                outcome = advance_guided(
                    root, plan, None, commit=active, connection=connection
                )
                if outcome["ready"]:
                    translation._batch_results = None
                    break
                if outcome.get("uncertain"):
                    raise ValueError(
                        "The clarification Batch needs provider reconciliation before resuming."
                    )
                task._emit_batch_phase(
                    "poll_capacity"
                    if outcome.get("waiting_capacity")
                    else "poll_status",
                    [
                        {
                            "id": batch["id"],
                            "api_status": batch.get("api_status", "validating"),
                            "counts": batch.get("counts", {}),
                            "request_count": len(batch["items"]),
                        }
                        for batch in outcome["batches"]
                        if batch["id"]
                    ],
                )
                for _ in range(300):
                    if task.should_stop:
                        return "Stopped"
                    time.sleep(0.1)
            if task.should_stop:
                return "Stopped"
        return native(task, matching_files, estimate_only, batch_phase=batch_phase)

    TranslationTask._run_files.layer(LAYER, files)
