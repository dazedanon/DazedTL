"""Fill shared OpenAI Batch capacity without changing approved requests."""

import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from stat import S_ISREG

from dazedtl.freshness import Digests
from dazedtl.settings.providers import own_api
from dazedtl.storage import WorkspaceError, WorkspaceLock, write_json
from dazedtl.translation.files import digest, live_path, project_path, read_json

from .batch_continuation import (
    JOURNAL,
    refused_create,
    validate_submission_records,
)
from .batch_control import TERMINAL
from .process_view import queue, saved


def scope(plan):
    return (
        plan.get("key_name"),
        plan.get("settings", {}).get("api", "").rstrip("/"),
        plan.get("settings", {}).get("model"),
    )


def run_scope(workspace, configuration, names=None):
    """The connection an Assistant-led run's frozen configuration sends
    with, named the way scope() names a Guided plan's; `names` are the saved
    connections' runtime names by ID, read from Settings when not given."""
    from dazedtl.settings.execution import connection_names

    if names is None:
        names = connection_names(Path(workspace))
    return (
        names.get(configuration.get("connection_id")),
        str(configuration.get("endpoint", "")).rstrip("/"),
        configuration.get("model"),
    )


def workspace_of(root):
    """The app workspace holding a Guided run folder, engine/manual/jobs/<run>."""
    return Path(root).parents[3]


@contextmanager
def capacity_lock(workspace, identity):
    # Separate from the app lock: private workers share this connection/model
    # budget without holding the UI/API lock during uploads.
    engine = Path(workspace) / "engine"
    engine.mkdir(exist_ok=True)
    folder = project_path(
        engine,
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


def active_tokens(workspace, identity, count, allowance):
    """Count known pending jobs and uncertain creates on the same connection,
    Guided's and Assistant-led's, which share the provider's window.

    Partial request progress cannot release a Batch's tokens. Older receipts
    without token estimates are counted from their retained exact payloads.
    """
    seen = set()
    used = guided_tokens(
        Path(workspace) / "engine/manual/jobs", identity, count, allowance, seen
    )
    if used >= allowance:
        return used
    return used + run_tokens(workspace, identity, count, allowance, seen)


def guided_tokens(jobs, identity, count, allowance, seen):
    """active_tokens of the Guided runs in the folder `jobs`."""
    if not jobs.is_dir():
        return 0
    used = 0
    for folder in jobs.iterdir():
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
        if journal_matches and not receipt and not refused_create(journal):
            estimate = journal.get("estimated_input_tokens")
            if type(estimate) is not int or estimate < 0:
                return allowance
            used += estimate
        # Clarifications share the same provider quota, including creates whose
        # returned ID has not yet been recorded.
        pending = clarification_tokens(
            folder, {row["id"] for row in matching}, count, seen
        )
        if pending is None:
            return allowance
        used += pending
    return used


def clarification_tokens(folder, originals, count, seen):
    """The tokens of the run folder's sent, unfinished clarification Batches
    of the provider jobs `originals`, or None when a payload is unknown."""
    used = 0
    for path in (folder / "log/clarifications").glob("*.summary.json"):
        summary = saved(folder, "clarifications/" + path.name)
        if summary.get("original_id") not in originals:
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
                return None
            used += sum(count(item["params"]) for item in items)
            if row.get("id"):
                seen.add(row["id"])
    return used


# The longest an OpenAI Batch runs before it expires. A polled run saves its
# record every pass, so one unsaved for longer has no job left at the provider.
COMPLETION_WINDOW = timedelta(hours=25)

# Each chunk's input tokens by its run's plan and first custom ID: the plans
# of large games are slow to read, and an approved plan never changes.
_chunk_tokens = {}

# Assistant-led Batch runs frozen with this policy send each chunk only once
# the window has room for it (Runner.batch); runs frozen before it send each
# chunk as soon as the one before it finished.
RUN_POLICY = "enqueued-tokens-v1"

# Assistant-led Batch runs frozen with this policy pack each chunk to at most
# job_tokens of the allowance and send the next while the window has room,
# so several are in flight; runs frozen before it pack a chunk up to the
# whole allowance and send the next once the one before it ended.
CHUNK_POLICY = "quarter-jobs-v1"


def job_tokens(allowance):
    """The most input tokens one provider job packs of the window's Batch
    token `allowance`, Guided's and Assistant-led's alike: a quarter, so
    several independently completing jobs share the window and one slow
    request cannot hold all of it, and at most the engine's default
    allowance. A request bigger than this still goes alone in a job."""
    from util.translation import OPENAI_BATCH_SEQUENTIAL_ENQUEUED_TOKEN_LIMIT

    return min(max(1, allowance // 4), OPENAI_BATCH_SEQUENTIAL_ENQUEUED_TOKEN_LIMIT)


def chunk_tokens(job, chunk, requests, count, known=None):
    """The input tokens of an Assistant-led run's chunk: `known` when its
    packing counted them, else counted from `requests()`, the run's plan
    requests by ID, read only when this process has not counted it yet."""
    key = (job.get("plan_sha256"), chunk["items"][0]["custom_id"])
    if known is not None:
        _chunk_tokens[key] = known
    if key not in _chunk_tokens:
        rows = requests()
        # Counted as Runner.batch packs them: a plan's own counts first.
        _chunk_tokens[key] = sum(
            row["input_tokens"] if "input_tokens" in row else count(row["params"])
            for row in (rows[item["request"]] for item in chunk["items"])
        )
    return _chunk_tokens[key]


# What the window read of each Assistant-led run record, by path: a long
# history holds many large records, and only a running run's changes.
_records = Digests()


def run_record(path, info):
    """What the window counts of the Assistant-led run record at `path`,
    whose stat result is `info`: when it was saved, the connection its
    configuration names, its plan's digest, its chunks sent and not yet
    ended, and every provider job ID it holds; or () for a record that sends
    no Batch or that no run can read, since no worker can send from it."""

    def read():
        try:
            job = read_json(path)
            updated = datetime.fromisoformat(job["updated"])
            configuration = job.get("configuration") or {}
            if configuration.get("mode") != "batch":
                return ()
            chunks = job.get("batches") or []
            return (
                updated,
                {
                    key: configuration.get(key)
                    for key in ("connection_id", "endpoint", "model")
                },
                {"plan_sha256": job.get("plan_sha256")},
                [
                    chunk
                    for chunk in chunks
                    if chunk.get("state") in {"submitting", "submitted"}
                    and chunk.get("api_status") not in TERMINAL
                ],
                {chunk["id"] for chunk in chunks if chunk.get("id")},
            )
        except AttributeError, KeyError, TypeError, ValueError:
            return ()

    return _records.remember(str(path), info, read)


def requests_of(store, folder, job):
    """The requests of the run's frozen plan, by ID."""
    return {row["id"]: row for row in store.plan(folder, job)["requests"]}


def run_tokens(workspace, identity, count, allowance, seen):
    """active_tokens of the Assistant-led runs: their provider jobs sent and
    not yet ended, including a create whose returned ID was not recorded,
    and their clarification Batches."""
    from dazedtl.settings.execution import connection_names
    from dazedtl.translation.jobs import RunStore

    runs = Path(workspace) / "translation/runs"
    if not runs.is_dir():
        return 0
    store, used = RunStore(workspace), 0
    names = connection_names(Path(workspace))
    oldest = datetime.now(UTC) - COMPLETION_WINDOW
    for folder in runs.iterdir():
        path = folder / "job.json"
        try:
            info = path.stat()
        except OSError:
            continue
        if folder.is_symlink() or not S_ISREG(info.st_mode):
            continue
        record = run_record(path, info)
        if not record:
            continue
        updated, configuration, job, chunks, ids = record
        if updated < oldest or run_scope(workspace, configuration, names) != identity:
            continue
        for chunk in chunks:
            if chunk.get("id") and chunk["id"] in seen:
                continue
            try:
                used += chunk_tokens(
                    job,
                    chunk,
                    partial(requests_of, store, folder, job),
                    count,
                )
            except KeyError, ValueError:
                return allowance  # Unknown paid work never becomes free capacity.
            if chunk.get("id"):
                seen.add(chunk["id"])
        pending = clarification_tokens(folder, ids, count, seen)
        if pending is None:
            return allowance
        used += pending
    return used


@contextmanager
def reserve(workspace, identity, needed, count, limit):
    """Whether `needed` more input tokens fit the connection's window now,
    held while they are sent so another worker cannot take the same room."""
    with capacity_lock(workspace, identity) as acquired:
        if not acquired:
            yield False
            return
        used = active_tokens(workspace, identity, count, limit)
        yield needed <= max(0, limit - used)


@contextmanager
def reserve_clarification(root, plan, items, count, limit):
    """reserve for a Guided run's clarification Batch."""
    if (
        plan.get("batch_link")
        or not own_api("openai", plan.get("settings", {}).get("api", ""))
        or not limit
    ):
        yield True
        return
    with reserve(
        workspace_of(root),
        scope(plan),
        sum(count(item["params"]) for item in items),
        count,
        limit,
    ) as available:
        yield available


@contextmanager
def reserve_run(workspace, configuration, needed, count, limit):
    """reserve for `needed` input tokens of an Assistant-led run; `limit` is
    its frozen plan's Batch token allowance, which the plan holds only for
    OpenAI's own API (TranslationEngine.batch_limits)."""
    if not limit:
        yield True
        return
    with reserve(
        workspace, run_scope(workspace, configuration), needed, count, limit
    ) as available:
        yield available


def reserve_run_clarification(workspace, configuration, items, count, limit):
    """reserve_run for an Assistant-led run's clarification Batch."""
    return reserve_run(
        workspace,
        configuration,
        sum(count(item["params"]) for item in items) if limit else 0,
        count,
        limit,
    )


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
        with capacity_lock(workspace_of(self.root), scope(self.plan)) as acquired:
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
                            live_path(self.root, "log/batch_state.json"),
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
                    - active_tokens(
                        workspace_of(self.root), scope(self.plan), self.count, limit
                    ),
                )
                pending = chunks(
                    requests,
                    submitted,
                    costs,
                    available,
                    job_tokens(limit),
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
                    write_json(live_path(self.root, "log/batch_state.json"), state)
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
    root, plan, translation, providers, task_type, approve, recover, record, attempt
):
    if not own_api("openai", plan.get("settings", {}).get("api", "")):
        return
    window = BatchWindow(root, plan, translation, providers, approve, recover, record)

    def poll(_native, task):
        # Replaces native polling: the window submits more work as capacity frees.
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
            with attempt():
                sent = window.fill(task)
            if sent:
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

    task_type._run_batch_poll_fetch.layer("batch-window", poll)
