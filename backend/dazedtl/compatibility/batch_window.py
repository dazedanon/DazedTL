"""Fill shared OpenAI Batch capacity without changing approved requests."""

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import time

from dazedtl.storage import WorkspaceError, WorkspaceLock, write_json
from dazedtl.translation.files import digest, project_path
from .batch_continuation import JOURNAL, validate_submission_records
from .batch_control import TERMINAL
from .process_view import queue, saved


def scope(plan):
    return (
        plan.get("key_name"),
        plan.get("settings", {}).get("api", "").rstrip("/"),
        plan.get("settings", {}).get("model"),
    )


@contextmanager
def capacity_lock(root, identity):
    # Separate from the app lock: private workers share this connection/model
    # budget without holding the UI/API lock during uploads.
    folder = project_path(
        root.parents[2],
        "batch-capacity/" + digest(identity) + "/workspace.lock",
        exists=False,
    ).parent
    folder.mkdir(parents=True, exist_ok=True)
    try:
        lock = WorkspaceLock(folder)
    except WorkspaceError:
        yield False
        return
    try:
        yield True
    finally:
        lock.close()


def chunks(requests, submitted, tokens, available, target, limits):
    """Pack available capacity, preserving each request's original custom ID."""
    result, current, used, size = [], [], 0, 0
    for index, (key, entry) in enumerate(requests.items()):
        if key in submitted or tokens[key] > available:
            continue
        length = (
            len(json.dumps(entry["params"], ensure_ascii=False).encode("utf-8")) + 128
        )
        if length > limits[1]:
            raise ValueError(
                "An approved request exceeds the provider Batch file limit."
            )
        if current and (
            len(current) >= limits[0]
            or size + length > limits[1]
            or used + tokens[key] > target
        ):
            result.append((current, used))
            current, used, size = [], 0, 0
        current.append(
            {"custom_id": f"req-{index:06d}", "params": entry["params"], "key": key}
        )
        used += tokens[key]
        available -= tokens[key]
        size += length
    if current:
        result.append((current, used))
    return result


def active_tokens(root, identity, count, allowance):
    """Count known pending jobs and uncertain creates on the same connection.

    Partial request progress cannot release a Batch's tokens. Older receipts
    without token estimates are counted from their retained exact payloads.
    """
    used, seen = 0, set()
    for folder in root.parent.iterdir():
        if not folder.is_dir() or folder.is_symlink():
            continue
        state = saved(folder, "batch_state.json")
        history = saved(folder, "batch_history.json").get("batches", [])
        matching = [
            row
            for row in history
            if (
                row.get("key_name"),
                str(row.get("endpoint", "")).rstrip("/"),
                row.get("model"),
            )
            == identity
        ]
        # A just-returned job can precede its native history checkpoint.
        journal = saved(folder, JOURNAL).get("intent") or {}
        receipt = journal.get("receipt") or {}
        route = matching[0] if matching else state
        journal_matches = (
            bool(journal)
            and (
                receipt.get("key_name")
                or journal.get("key_name")
                or route.get("key_name"),
                str(
                    receipt.get("endpoint")
                    or journal.get("endpoint")
                    or route.get("endpoint")
                    or ""
                ).rstrip("/"),
                receipt.get("model") or journal.get("model") or route.get("model"),
            )
            == identity
        )
        if not matching and not journal_matches:
            continue
        active = {row["id"]: row for row in matching}
        if journal_matches and receipt and receipt["id"] not in active:
            active[receipt["id"]] = receipt
        manifests = {row["id"]: row for row in state.get("batches", [])}
        requests = None
        for batch_id, row in active.items():
            terminal = (
                row.get("api_status") in TERMINAL
                or not row.get("api_status")
                and row.get("status")
                in {"consumed", "fetched", "ended", "failed", "canceled", "expired"}
            )
            if batch_id in seen or terminal:
                continue
            seen.add(batch_id)
            estimate = row.get(
                "estimated_input_tokens",
                manifests.get(batch_id, {}).get("estimated_input_tokens"),
            )
            if type(estimate) is not int or estimate < 0:
                requests = requests if requests is not None else queue(folder)
                keys = set((row.get("custom_ids") or {}).values())
                if not keys or not keys.issubset(requests):
                    return allowance  # Unknown paid work never becomes free capacity.
                estimate = sum(count(requests[key]["params"]) for key in keys)
            used += estimate
        if journal_matches and not receipt:
            estimate = journal.get("estimated_input_tokens")
            if type(estimate) is not int or estimate < 0:
                return allowance
            used += estimate
        # Clarifications share the same provider quota, including creates whose
        # returned ID has not yet been recorded.
        for path in (folder / "log/clarifications").glob("*.summary.json"):
            summary = saved(folder, "clarifications/" + path.name)
            if summary.get("original_id") not in {row["id"] for row in matching}:
                continue
            pending = [
                row
                for row in summary.get("batches", [])
                if row.get("state") in {"sending", "submitted"}
                and row.get("api_status") not in TERMINAL
            ]
            if not pending:
                continue
            detail = saved(
                folder, "clarifications/" + path.name.replace(".summary.json", ".json")
            )
            detailed = {
                (
                    row.get("id"),
                    tuple(item["key"] for item in row.get("items", [])),
                ): row
                for row in detail.get("batches", [])
            }
            for row in pending:
                if row.get("id") and row["id"] in seen:
                    continue
                items = detailed.get(
                    (
                        row.get("id"),
                        tuple(item["key"] for item in row.get("items", [])),
                    ),
                    {},
                ).get("items")
                if not items or any("params" not in item for item in items):
                    return allowance
                used += sum(count(item["params"]) for item in items)
                if row.get("id"):
                    seen.add(row["id"])
    return used


@contextmanager
def reserve_clarification(root, plan, items, count, limit):
    if (
        plan.get("batch_link")
        or urlsplit(plan.get("settings", {}).get("api", "")).hostname
        != "api.openai.com"
        or not limit
    ):
        yield True
        return
    root = Path(root)
    with capacity_lock(root, scope(plan)) as acquired:
        if not acquired:
            yield False
            return
        used = active_tokens(root, scope(plan), count, limit)
        yield sum(count(item["params"]) for item in items) <= max(0, limit - used)


class BatchWindow:
    def __init__(self, root, plan, translation, providers, approve, recover, record):
        self.root, self.plan = Path(root), plan
        self.translation, self.providers = translation, providers
        self.approve, self.recover, self.record = approve, recover, record
        self.tokens = {}

    def count(self, params):
        key = digest(params)
        if key not in self.tokens:
            self.tokens[key] = self.translation._estimate_openai_batch_input_tokens(
                params
            )
        return self.tokens[key]

    def fill(self, task):
        with capacity_lock(self.root, scope(self.plan)) as acquired:
            if not acquired:
                return 0
            with self.translation._batch_submit_lock():
                self.recover()
                self.approve()
                validate_submission_records(self.root)
                requests = queue(self.root)
                if any(
                    not self.translation._batch_entry_context_is_current(entry)
                    for entry in requests.values()
                ):
                    raise ValueError(
                        "The approved Batch queue uses an unsupported request context. Its requests were retained."
                    )
                state = dict(saved(self.root, "batch_state.json"))
                batches = list(state.get("batches") or [])
                for batch in [
                    *batches,
                    *saved(self.root, "batch_history.json").get("batches", []),
                ]:
                    if (
                        batch.get("key_name")
                        and batch["key_name"] != self.plan["key_name"]
                        or batch.get("endpoint")
                        and batch["endpoint"].rstrip("/")
                        != state["endpoint"].rstrip("/")
                        or batch.get("provider")
                        and batch["provider"] != "openai"
                        or batch.get("model")
                        and batch["model"] != state["model"]
                    ):
                        raise ValueError(
                            "The saved Batch connection differs from its approved provider receipts."
                        )
                submitted = {
                    key
                    for batch in batches
                    for key in batch.get("custom_ids", {}).values()
                }
                if submitted == set(requests):
                    if state.get("status") != "submitted":
                        write_json(
                            project_path(self.root, "log/batch_state.json"),
                            {**state, "status": "submitted"},
                        )
                    return 0
                limit = (
                    state.get("batch_token_allowance")
                    or (self.plan.get("dazedtl_request_policy") or {}).get(
                        "batchInputTokens"
                    )
                    or state.get("sequential_token_limit")
                    or self.translation._openai_batch_token_limit()
                )
                if type(limit) is not int or limit <= 0:
                    raise ValueError("The saved Batch token allowance is invalid.")
                costs = {
                    key: self.count(entry["params"]) for key, entry in requests.items()
                }
                if any(
                    cost > limit for key, cost in costs.items() if key not in submitted
                ):
                    raise ValueError(
                        "An approved request exceeds the Batch token allowance. Increase the allowance or prepare smaller requests."
                    )
                available = max(
                    0,
                    limit
                    - active_tokens(self.root, scope(self.plan), self.count, limit),
                )
                # Keep several independently completing jobs in the window;
                # one straggler should not retain the entire token allowance.
                target = min(
                    max(1, limit // 4),
                    self.translation.OPENAI_BATCH_SEQUENTIAL_ENQUEUED_TOKEN_LIMIT,
                )
                pending = chunks(
                    requests,
                    submitted,
                    costs,
                    available,
                    target,
                    self.providers.batch_limits("openai"),
                )
                sent = 0
                for part, tokens in pending:
                    job = self.translation._read_batch_file(
                        self.root / "job.json", strict=True
                    )
                    if (
                        task.should_stop
                        or job.get("dazedtl_batch_stopped")
                        or job.get("dazedtl_batch_cancellations")
                    ):
                        break
                    payloads = [
                        {key: item[key] for key in ("custom_id", "params")}
                        for item in part
                    ]
                    result = self.providers.submit_batch(
                        "openai", payloads, _dazedtl_input_tokens=tokens
                    )
                    info = {
                        **result,
                        "custom_ids": {item["custom_id"]: item["key"] for item in part},
                        "provider": "openai",
                        "model": state["model"],
                        "run_id": state["run_id"],
                        "key_name": self.plan["key_name"],
                        "endpoint": state["endpoint"],
                        "cache_key_version": state.get("cache_key_version"),
                        "estimated_input_tokens": tokens,
                    }
                    batches.append(info)
                    submitted.update(info["custom_ids"].values())
                    state.update(
                        status="submitted"
                        if len(submitted) == len(requests)
                        else "partially_submitted",
                        batches=batches,
                        request_count=len(submitted),
                        queued_request_count=len(requests),
                        batch_token_allowance=limit,
                        cost_estimate=state.get("cost_estimate") or job.get("estimate"),
                    )
                    if sum(costs.values()) > limit:
                        state.setdefault("sequential_token_limit", limit)
                    write_json(project_path(self.root, "log/batch_state.json"), state)
                    self.record(
                        [info],
                        model=state["model"],
                        provider="openai",
                        file_set=state["file_set"],
                        cost_estimate=state.get("cost_estimate"),
                        key_name=self.plan["key_name"],
                        endpoint=state["endpoint"],
                    )
                    task.emit_log(
                        f"[BATCH] Submitted {len(part)} requests ({tokens:,} estimated input tokens); capacity remaining {available - tokens:,}."
                    )
                    available -= tokens
                    sent += len(part)
                return sent


def install_worker(
    root, plan, translation, providers, task_type, approve, recover, record
):
    if urlsplit(plan.get("settings", {}).get("api", "")).hostname != "api.openai.com":
        return
    window = BatchWindow(root, plan, translation, providers, approve, recover, record)
    native = getattr(
        task_type._run_batch_poll_fetch,
        "_dazedtl_native",
        task_type._run_batch_poll_fetch,
    )

    def poll(task):
        interval = int(os.getenv("batchPollInterval", "60") or 60)
        while not task.should_stop:
            state = saved(root, "batch_state.json")
            ended, statuses = (
                translation.checkTranslationBatchStatuses(print_status=False)
                if state.get("batches")
                else (True, [])
            )
            if statuses:
                task._emit_batch_phase("poll_status", statuses)
            failures = translation.failedTranslationBatchStatuses(statuses)
            if failures:
                task.emit_log(
                    "[BATCH] Provider failure: "
                    + translation.formatTranslationBatchFailures(failures)
                )
                return False
            if window.fill(task):
                continue
            state = saved(root, "batch_state.json")
            submitted = {
                key
                for batch in state.get("batches", [])
                for key in batch.get("custom_ids", {}).values()
            }
            remaining = set(queue(root)) - submitted
            if ended and state.get("status") == "submitted" and not remaining:
                return task._emit_batch_output(translation.fetchTranslationBatches)
            if ended and remaining:
                task._emit_batch_phase("poll_capacity", statuses)
                task.status_signal.emit("Waiting for available Batch token capacity.")
            for _ in range(interval * 10):
                if task.should_stop:
                    return None
                time.sleep(0.1)
        return None

    poll._dazedtl_native = native
    task_type._run_batch_poll_fetch = poll
