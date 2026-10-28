"""Transport-independent acceptance, submission journaling, and safe resume."""

import os
import time
from contextlib import nullcontext
from functools import partial

from dazedtl.compatibility.batch_window import (
    CHUNK_POLICY,
    RUN_POLICY,
    chunk_tokens,
    job_tokens,
    reserve_run,
)
from dazedtl.storage import write_json

from .batch_refusals import advance, outline, started
from .files import digest, read_json
from .organize import DELIVERED
from .refusals import (
    MESSAGE as REFUSAL_MESSAGE,
)
from .refusals import (
    POLICY as REFUSAL_POLICY,
)
from .refusals import (
    ClarifyOnce,
    refused,
)
from .requests import delivered_params, from_provider, provider_sources
from .results import Results, kept, left_lines

# A Batch collection accepts thousands of responses in one pass, and each save
# rewrites the whole record, so it saves at most this often and once at the
# end. Every response is saved before it is accepted, and recover() rebuilds
# acceptance from those files and the results, so an interrupted collection
# loses nothing and its provider job is only collected again.
SAVE_INTERVAL = 1.0
# An API run under this policy sends a provider payload that several of its
# requests share once, as Guided queues a scene two maps repeat once: their
# lines are the same text in the same order under the same keys, so the
# result the first of them saves answers the others line by line. The plan
# freezes the policy and each other request's first (askers), so earlier
# runs send every request.
SHARED_PAYLOADS = "shared-payloads-v1"
# The run record's message of the failed chunk after which a Batch run with
# several chunks in flight (CHUNK_POLICY) sends no further chunk; the run
# ends with it once the chunks sent before it ended, and a Resume of that
# failed run sends the rest, as it does for a run sending one at a time.
STOPPED_SENDING = "stopped_sending"


def askers(requests):
    """Each of the requests whose provider payload an earlier one of them
    also sends, by ID, with that earlier request's ID."""
    first, found = {}, {}
    for row in requests:
        sender = first.setdefault(digest(row["params"]), row)
        if sender is not row and list(sender["sources"].values()) == list(
            row["sources"].values()
        ):
            found[row["id"]] = sender["id"]
    return found


def kept_message(failing):
    """The note of an accepted request whose failing lines kept their source
    text (results.kept), naming each and why; empty when none did."""
    if not failing:
        return ""
    return "Kept in the original text, as no usable translation: " + "; ".join(
        f"{identity} ({reason})" for identity, reason in failing.items()
    )


class JobRetries:
    """Assistant-led's clarification journal: the run record's
    `refusal_retries`, the clarified payload sent for each request."""

    def __init__(self, job):
        self.job = job

    def __contains__(self, identity):
        return identity in self.job.get("refusal_retries", {})

    def record(self, identity, params):
        self.job.setdefault("refusal_retries", {})[identity] = params


class Runner:
    def __init__(
        self, store, identity, provider, validate_current, checkpoint=lambda: None
    ):
        self.store = store
        # A worker builds a runner for every poll; the record may have changed
        # since, the frozen plan cannot have.
        self.job, self.plan = store.load(identity, reuse=True)
        self.provider = provider
        self.validate_current = validate_current
        self.checkpoint = checkpoint
        self.results = Results(self.plan["source"])
        self.folder = store.folder(identity)
        self.requests = {row["id"]: row for row in self.plan["requests"]}
        # The request whose answer answers each request asking its payload
        # (askers), which is never sent itself.
        self.sender = (
            self.plan["askers"]
            if self.plan.get("shared_payloads") == SHARED_PAYLOADS
            else {}
        )
        self.askers = {}
        for asker, sender in self.sender.items():
            self.askers.setdefault(sender, []).append(asker)
        # The earlier lines each later part of a split scene quotes, whose
        # delivered translation a Live run sends with it (delivered).
        self.preceding = (
            self.plan["preceding"] if self.plan.get("delivered") == DELIVERED else {}
        )
        self.holders = None
        # The plan's OpenAI Batch token allowance, and whether its chunks
        # take a quarter of it each, several in flight, or, in runs frozen
        # before CHUNK_POLICY, all of it, one at a time.
        limits = self.plan.get("batch_limits") or []
        self.token_limit = limits[2] if len(limits) > 2 else None
        self.several = (
            bool(self.token_limit) and self.plan.get("batch_chunks") == CHUNK_POLICY
        )
        # Whether this pass checked the game before sending a chunk (submit).
        self.checked = False
        self.saved = time.monotonic()
        # Sums of request_usage, kept as rows change; see record_usage.
        self.request_totals = None

    def save(self, status=None, message=None):
        if status is not None:
            self.job["status"] = status
        if message is not None:
            self.job["message"] = message
        # A request asking the payload of one that ended without a result is
        # never sent in this run; the next organize sends it.
        for asker, sender in self.sender.items():
            if self.job["states"][asker]["state"] == "pending" and self.job["states"][
                sender
            ]["state"] in {"failed", "uncertain"}:
                self.job["states"][asker] = {
                    "state": "failed",
                    "message": f"Not sent: it asks what {sender} asks, which got no translation.",
                }
        self.store.save(self.job)
        self.saved = time.monotonic()

    def response_path(self, identity, *, original=False):
        suffix = (
            "-clarified"
            if not original and identity in self.job.get("refusal_retries", {})
            else ""
        )
        return self.folder / "responses" / (digest(identity) + suffix + ".json")

    def sources(self, identity):
        """The request's source lines under the keys its provider saw."""
        return provider_sources(self.requests[identity], self.plan["configuration"])

    def delivered(self, identity):
        """The translation this run delivered for the earlier lines a later
        part of a split scene quotes (organize.DELIVERED), in order, or None
        unless each has one, as Guided passes a Live chunk's English on only
        when every line of it was translated: each line is held by a request
        accepted before it, as the part before is, since Live sends its
        requests in plan order, and its receipt translates it."""
        quoted = self.preceding.get(identity)
        if not quoted:
            return None
        if self.holders is None:
            self.holders = {
                unit: row["id"]
                for row in self.plan["requests"]
                for unit in row["sources"]
            }
        receipts, lines = {}, []
        for unit in quoted:
            holder = self.holders.get(unit)
            if holder is None or self.job["states"][holder]["state"] != "accepted":
                return None
            if holder not in receipts:
                request = self.requests[holder]
                value = self.results.get(request)
                receipts[holder] = value and (
                    value["translations"],
                    left_lines(request, value),
                )
            saved = receipts[holder]
            if not saved or unit in saved[1] or not saved[0][unit].strip():
                return None
            lines.append(saved[0][unit])
        return lines

    def accept(self, identity, response):
        request = self.requests[identity]
        write_json(self.response_path(identity), response)
        self.record_usage(identity, response)
        try:
            if refused(response, self.sources(identity)):
                raise ValueError(REFUSAL_MESSAGE)
            # A line that fails the content check keeps its source text, as
            # Guided's Batch keeps it, so no retry pays for the lines that
            # passed.
            output, failing = kept(
                request,
                from_provider(request, self.plan["configuration"], response["text"]),
            )
            self.results.accept(
                request,
                output,
                {
                    "run_id": self.job["id"],
                    "mode": self.plan["configuration"]["mode"],
                    "model": self.plan["configuration"]["model"],
                },
            )
            self.job["states"][identity] = {
                "state": "accepted",
                "message": kept_message(failing),
            }
            self.answer(identity, output, failing)
        except ValueError as exc:
            self.job["states"][identity] = {"state": "failed", "message": str(exc)}
        # Each Live request is a paid call of its own.
        if (
            self.plan["configuration"]["mode"] != "batch"
            or time.monotonic() - self.saved >= SAVE_INTERVAL
        ):
            self.save()
        self.checkpoint()

    def answer(self, sender, output=None, failing=None):
        """Saves sender's translations, output or else its saved result, for
        each request asking its payload, line by line in order; failing names
        the lines sender kept in their source text (kept), which the askers
        keep too."""
        waiting = [
            asker
            for asker in self.askers.get(sender, ())
            if self.job["states"][asker]["state"] != "accepted"
        ]
        request = self.requests[sender]
        if waiting and output is None:
            output = (self.results.get(request) or {}).get("translations")
        if not output:
            return
        lines = list(request["sources"])
        for asker in waiting:
            row = self.requests[asker]
            try:
                # The asker's line at each position of the sender's.
                mapped = dict(zip(lines, row["sources"], strict=True))
                self.results.accept(
                    row,
                    {mapped[identity]: output[identity] for identity in lines},
                    {
                        "run_id": self.job["id"],
                        "mode": self.plan["configuration"]["mode"],
                        "model": self.plan["configuration"]["model"],
                    },
                )
                self.job["states"][asker] = {
                    "state": "accepted",
                    "message": kept_message(
                        {
                            mapped[identity]: reason
                            for identity, reason in (failing or {}).items()
                        }
                    ),
                }
            except ValueError as exc:
                self.job["states"][asker] = {"state": "failed", "message": str(exc)}

    @staticmethod
    def received(response):
        """A Live response with the UTC time it arrived, which prices its
        usage (provider_costs time_price_factor): the provider's ``created``
        when it gives one, else now."""
        from util.provider_costs import received_at

        response = dict(response)
        response["received_at"] = received_at(response.pop("created", None))
        return response

    def record_usage(self, identity, response):
        from util.provider_costs import joined_received_at, time_priced_route

        times = [response.get("received_at")]
        if identity in self.job.get("refusal_retries", {}):
            original = read_json(self.response_path(identity, original=True))
            times.insert(0, original.get("received_at"))
            response = {
                key: (response.get(key, 0) if type(response.get(key, 0)) is int else 0)
                + (original.get(key, 0) if type(original.get(key, 0)) is int else 0)
                for key in set(response) | set(original)
                if key.endswith("tokens")
            }

        def count(key):
            value = response.get(key, 0)
            return value if type(value) is int and value >= 0 else 0

        cached, created = (
            count("cache_read_input_tokens"),
            count("cache_creation_input_tokens"),
        )
        row = {
            "input_tokens": max(0, count("prompt_tokens") - cached - created),
            "output_tokens": count("completion_tokens"),
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": created,
            "thinking_tokens": count("thinking_tokens"),
        }
        rows = self.job.setdefault("request_usage", {})
        # Recovery records every saved response again, so summing all rows
        # each time would cost the square of a large run's requests.
        if self.request_totals is None:
            self.request_totals = {
                key: sum(other[key] for other in rows.values()) for key in row
            }
        previous = rows.get(identity, dict.fromkeys(row, 0))
        for key, value in row.items():
            self.request_totals[key] += value - previous[key]
        self.job["usage"] = dict(self.request_totals)
        # The time that prices the row (estimate_prices.usage_cost); a row
        # without one, as rows saved before they held one, reads as peak.
        when = joined_received_at(
            time_priced_route(self.plan["configuration"].get("endpoint")), *times
        )
        rows[identity] = {**row, "received_at": when} if when else row

    def recover(self):
        # A waiting Batch recovers on every poll, so the saved responses and
        # results are each listed once rather than looked up per request.
        try:
            with os.scandir(self.folder / "responses") as entries:
                responses = {entry.name for entry in entries if entry.is_file()}
        except FileNotFoundError:
            responses = set()
        accepted = self.results.saved()
        for identity, request in self.requests.items():
            path = self.response_path(identity)
            response = read_json(path) if path.name in responses else None
            if response is not None:
                self.record_usage(identity, response)
            fingerprint = request["fingerprint"]
            if fingerprint in accepted and self.results.get(
                request, accepted[fingerprint]
            ):
                # An accepted request keeps its note of the lines it kept.
                if self.job["states"][identity]["state"] != "accepted":
                    self.job["states"][identity] = {"state": "accepted", "message": ""}
            elif response is not None:
                self.accept(identity, response)
            elif self.job["states"][identity]["state"] == "sending":
                self.job["states"][identity] = {
                    "state": "uncertain",
                    "message": "The connection ended without a saved response. Check provider usage before explicitly retrying.",
                }
        # Requests asking a payload whose answer is saved, as an interruption
        # right after saving it leaves them.
        for sender in self.askers:
            self.answer(sender)
        if self.plan["configuration"]["mode"] == "batch":
            self.record_batch_usage()
        self.save()

    def record_batch_usage(self):
        receipts = [batch["usage"] for batch in self.job["batches"] if "usage" in batch]
        if receipts:
            self.job["usage"] = {
                key: sum(row.get(key, 0) for row in receipts)
                for key in set().union(*receipts)
            }

    def live(self):
        clarify = ClarifyOnce(
            self.plan["configuration"].get("refusalRetry"), JobRetries(self.job)
        )
        for identity, request in self.requests.items():
            state = self.job["states"][identity]["state"]
            # A request asking another's payload waits for its answer.
            if state != "pending" or identity in self.sender:
                continue
            if self.store.stopped(self.job["id"]):
                self.save("stopped", "Stopped at a saved request boundary.")
                return
            self.validate_current()
            params = request["params"]
            lines = self.delivered(identity)
            # Journaled with the send, so Inspect shows what was sent.
            if lines:
                self.job.setdefault("delivered", {})[identity] = lines
                params = delivered_params(params, lines, request["context"])
            else:
                self.job.get("delivered", {}).pop(identity, None)
            self.job["states"][identity] = {
                "state": "sending",
                "message": "Awaiting provider response.",
            }
            self.save("running", "Translating " + identity)
            try:
                response = self.received(self.provider.live(params))
            except Exception as exc:  # noqa: BLE001
                status = getattr(exc, "status_code", None)
                certain = type(status) is int and 400 <= status < 500
                self.job["states"][identity] = {
                    "state": "failed" if certain else "uncertain",
                    "message": "Provider rejected the request (HTTP "
                    + str(status)
                    + ")."
                    if certain
                    else "The request outcome is uncertain. It will not be sent again automatically.",
                }
                self.save(
                    "failed" if certain else "uncertain",
                    self.job["states"][identity]["message"],
                )
                return
            self.accept(identity, response)
            if refused(response, self.sources(identity)) and clarify.allowed(identity):
                if self.store.stopped(self.job["id"]):
                    self.save("stopped", "Stopped before the clarification retry.")
                    return
                self.validate_current()
                params = clarify.begin(identity, params)
                self.job["states"][identity] = {
                    "state": "sending",
                    "message": "Clarifying the translation context once.",
                }
                self.save("running", self.job["states"][identity]["message"])
                try:
                    response = self.received(self.provider.live(params))
                except Exception as exc:  # noqa: BLE001
                    status = getattr(exc, "status_code", None)
                    certain = type(status) is int and 400 <= status < 500
                    self.job["states"][identity] = {
                        "state": "failed" if certain else "uncertain",
                        "message": "The clarification retry failed. Review the saved request before further paid work.",
                    }
                    self.save(
                        "failed" if certain else "uncertain",
                        self.job["states"][identity]["message"],
                    )
                    return
                self.accept(identity, response)
        self.finish()

    def batch(self):
        if not self.job["batches"]:
            pending = [
                row
                for row in self.plan["requests"]
                if self.job["states"][row["id"]]["state"] == "pending"
                and row["id"] not in self.sender
            ]
            limit = self.plan["batch_limits"]
            import json

            chunks, chunk, size, tokens, counted = [], [], 0, 0, []
            schema = None
            same_schema = self.plan["configuration"].get(
                "openrouterStructuredOutputs"
            ) and self.plan["configuration"]["model"].startswith("google/")
            token_limit = self.token_limit
            # The most tokens a chunk packs (see several).
            packed = (
                (job_tokens(token_limit) if self.several else token_limit)
                if token_limit
                else 0
            )
            for index, row in enumerate(pending):
                item = {
                    "custom_id": "dtl-" + self.job["id"][:12] + "-" + str(index),
                    "request": row["id"],
                }
                length = (
                    len(json.dumps(row["params"], ensure_ascii=False).encode("utf-8"))
                    + 1024
                )
                # A plan frozen without counts (see compile_run) is counted
                # here, before anything is sent, so packing stays exact.
                request_tokens = (
                    row["input_tokens"]
                    if "input_tokens" in row
                    else self.provider.input_tokens(row["params"])
                    if token_limit
                    else 0
                )
                if length > limit[1] or token_limit and request_tokens > token_limit:
                    raise ValueError(
                        "A request exceeds the provider's Batch file limit. Split the scene with source context."
                    )
                if chunk and (
                    len(chunk) >= limit[0]
                    or size + length > limit[1]
                    or token_limit
                    and tokens + request_tokens > packed
                    or same_schema
                    and schema != row["params"].get("response_format")
                ):
                    chunks.append({"state": "pending", "id": "", "items": chunk})
                    counted.append(tokens)
                    chunk, size, tokens = [], 0, 0
                chunk.append(item)
                schema = row["params"].get("response_format")
                size += length
                tokens += request_tokens
            if chunk:
                chunks.append({"state": "pending", "id": "", "items": chunk})
                counted.append(tokens)
            if token_limit:
                # The window asks each chunk's tokens again; spare it counting.
                for row, known in zip(chunks, counted, strict=True):
                    chunk_tokens(self.job, row, None, None, known)
            self.job["batches"] = chunks
            self.save()
        # With several chunks in flight a pass goes on past one still
        # processing, and ends waiting with the last such chunk's message.
        waiting, held = None, False
        for chunk in self.job["batches"]:
            if chunk["state"] in {"complete", "canceled", "rejected"}:
                continue
            if self.store.stopped(self.job["id"]):
                self.save(
                    "stopped",
                    "Polling stopped. Saved provider jobs remain available for collection.",
                )
                return
            if chunk["state"] == "submitting" and not chunk["id"]:
                for item in chunk["items"]:
                    self.job["states"][item["request"]] = {
                        "state": "uncertain",
                        "message": "Attach the matching provider job before resuming.",
                    }
                self.save(
                    "uncertain",
                    "Submission may have succeeded; a provider job ID must be reconciled.",
                )
                return
            cancel = self.store.cancel_requested(self.job["id"])
            if cancel and not chunk["id"]:
                chunk["state"] = "canceled"
                for item in chunk["items"]:
                    self.job["states"][item["request"]] = {
                        "state": "failed",
                        "message": "Canceled before submission; no request was sent.",
                    }
                self.save()
                continue
            if not chunk["id"]:
                # Chunks are sent in order, so every later one is unsent too.
                if self.several and STOPPED_SENDING in self.job:
                    if chunk["state"] == "queued":
                        chunk["state"] = "pending"
                    break
                if held:
                    break
                if not self.submit(chunk):
                    if self.several and chunk["state"] in {"queued", "rejected"}:
                        if chunk["state"] == "queued":
                            waiting = self.job["message"]
                        break
                    return
            policy = self.plan["configuration"].get("refusalRetry") == REFUSAL_POLICY
            # A clarification journal starts only after this job ended, so a
            # cancellation then belongs to the clarification Batches.
            journaled = policy and started(self.folder, chunk["id"])
            if cancel and not journaled and not chunk.get("cancel_requested"):
                try:
                    self.provider.cancel(chunk["id"])
                except Exception as exc:  # noqa: BLE001
                    chunk["cancel_error"] = type(exc).__name__
                chunk["cancel_requested"] = True
                self.save()
            if journaled:
                # The clarification journal holds this job's responses, and a
                # clarification can wait for hours, so a poll does not
                # download the job's whole output again.
                responses = usage = None
            else:
                collected = self.collect(chunk, cancel)
                if collected is None:
                    # A canceled run submits nothing more, so the pass that
                    # collects its canceled job also settles the later chunks.
                    if cancel and chunk["state"] == "complete":
                        continue
                    if not self.several or chunk["state"] == "unmatched":
                        return
                    # Still processing, or a provider failure that halted
                    # further sends (halt).
                    if chunk["state"] != "complete":
                        waiting = self.job["message"]
                    continue
                responses, usage = collected
            # A canceled run starts no clarification but settles a started one.
            if journaled or policy and not cancel:
                from contextlib import contextmanager

                @contextmanager
                def retry_commit():
                    if self.store.stopped(self.job["id"]):
                        raise ValueError(
                            "Stopped before submitting a clarification Batch."
                        )
                    self.validate_current()
                    yield

                from dazedtl.compatibility.batch_window import (
                    reserve_run_clarification,
                )

                limits = self.plan["batch_limits"]
                count = getattr(self.provider, "input_tokens", lambda _: 0)
                if not journaled:
                    # The window reads this record, which must show its
                    # ended job before a clarification asks for room.
                    self.save()
                retried = advance(
                    self.folder,
                    chunk["id"],
                    {
                        item["request"]: self.requests[item["request"]]["params"]
                        for item in chunk["items"]
                    },
                    responses,
                    usage,
                    self.provider,
                    limits=limits,
                    input_tokens=count,
                    commit=retry_commit,
                    cancel=cancel,
                    reserve=partial(
                        reserve_run_clarification,
                        self.store.workspace,
                        self.plan["configuration"],
                        count=count,
                        limit=self.token_limit,
                    ),
                    sources={
                        item["request"]: self.sources(item["request"])
                        for item in chunk["items"]
                    },
                )
                # The journal keeps the clarified payloads and responses, and
                # this record is saved on every poll, so it keeps an outline.
                chunk["clarification_batches"] = [
                    outline(batch) for batch in retried["batches"]
                ]
                responses, usage = retried["responses"], retried["usage"]
                if not retried["ready"]:
                    usage_keys = set(usage).union(
                        *(batch.get("usage", {}) for batch in retried["batches"])
                    )
                    chunk["usage"] = {
                        key: usage.get(key, 0)
                        + sum(
                            batch.get("usage", {}).get(key, 0)
                            for batch in retried["batches"]
                        )
                        for key in usage_keys
                    }
                    # The first poll accepts the original responses; only those
                    # an interruption left queued are new later, and the final
                    # pass below accepts every response again.
                    for identity, response in responses.items():
                        state = self.job["states"][identity]["state"]
                        if state == "queued" and not refused(
                            response, self.sources(identity)
                        ):
                            self.accept(identity, response)
                    self.record_batch_usage()
                    self.save(
                        "uncertain" if retried.get("uncertain") else "waiting",
                        "Reconcile the clarification Batch submission."
                        if retried.get("uncertain")
                        else "Cancellation requested. Waiting for the provider's final status and any completed results."
                        if cancel
                        else "Waiting for available Batch token capacity."
                        if retried.get("waiting_capacity")
                        else "Waiting for the Batch clarification of refused requests.",
                    )
                    if not self.several or retried.get("uncertain"):
                        return
                    waiting = self.job["message"]
                    # Room frees for the clarification of sent work first.
                    held = held or bool(retried.get("waiting_capacity"))
                    continue
            # Only a started clarification leaves the provider job uncollected.
            assert responses is not None and usage is not None
            for item in chunk["items"]:
                identity = item["request"]
                if identity in responses:
                    self.accept(identity, responses[identity])
                elif self.job["states"][identity]["state"] != "accepted":
                    self.job["states"][identity] = {
                        "state": "failed",
                        "message": "No successful response was returned for this request.",
                    }
            chunk.update(state="complete", usage=usage)
            self.record_batch_usage()
            self.save()
            # A canceled run submits nothing more, so it settles every chunk.
            if not cancel and any(
                self.job["states"][item["request"]]["state"] == "failed"
                for item in chunk["items"]
            ):
                self.halt(
                    "Some returned translations failed validation. Later batches have not been submitted."
                )
                if not self.several:
                    return
        if self.several:
            halted = self.job.get(STOPPED_SENDING)
            canceled = self.store.cancel_requested(self.job["id"])
            if waiting:
                self.save(
                    "waiting",
                    halted + " Collecting the batches already sent."
                    if halted and not canceled
                    else waiting,
                )
                return
            if halted:
                del self.job[STOPPED_SENDING]
                if not canceled:
                    self.save("failed", halted)
                    return
        self.finish()

    def halt(self, message):
        """Sends no further chunk after a failed one: the run ends failed with
        `message`, or, with several chunks in flight, first collects the
        chunks sent before it (STOPPED_SENDING)."""
        if self.several:
            self.job.setdefault(STOPPED_SENDING, message)
            self.save()
        else:
            self.save("failed", message)

    def room(self, chunk):
        """Whether the provider's Batch window has room for the chunk now,
        held while it is sent; runs frozen before RUN_POLICY never wait."""
        limit = self.token_limit
        if self.plan.get("batch_window") != RUN_POLICY or not limit:
            return nullcontext(True)
        count = self.provider.input_tokens
        return reserve_run(
            self.store.workspace,
            self.plan["configuration"],
            chunk_tokens(self.job, chunk, lambda: self.requests, count),
            count,
            limit,
        )

    def submit(self, chunk):
        """Sends the unsent chunk once the window has room, and whether the
        pass goes on; a chunk without room stays queued, sending nothing."""
        with self.room(chunk) as available:
            pass
        if available:
            # Checking the game takes a while on a big one, so it runs
            # outside the window's lock, which other runs wait on, and once
            # for the chunks one pass sends.
            if not self.checked:
                self.validate_current()
                self.checked = True
            with self.room(chunk) as available:
                if available:
                    return self.send(chunk)
        chunk["state"] = "queued"
        self.save("waiting", "Waiting for available Batch token capacity.")
        return False

    def send(self, chunk):
        """Submits the chunk the window holds room for, and whether the pass
        goes on."""
        # Durable intent comes before the call, including each exact
        # correlation ID, and before the window's room is released.
        chunk["state"] = "submitting"
        for item in chunk["items"]:
            self.job["states"][item["request"]] = {
                "state": "queued",
                "message": "Submitting provider job.",
            }
        self.save("running", "Submitting a provider batch.")
        try:
            value = self.provider.submit(
                [
                    {
                        "custom_id": item["custom_id"],
                        "params": self.requests[item["request"]]["params"],
                    }
                    for item in chunk["items"]
                ]
            )
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "status_code", None)
            certain = type(code) is int and 400 <= code < 500
            for item in chunk["items"]:
                self.job["states"][item["request"]] = {
                    "state": "failed" if certain else "uncertain",
                    "message": "Provider rejected submission (HTTP " + str(code) + ")."
                    if certain
                    else "Submission outcome is uncertain; inspect the provider job list.",
                }
            if certain:
                chunk["state"] = "rejected"
                self.halt("Review the rejected submission.")
            else:
                self.save(
                    "uncertain",
                    "The provider submission must be reconciled before retrying.",
                )
            return False
        chunk.update(id=value["id"], state="submitted")
        self.save()
        return True

    def collect(self, chunk, cancel):
        """The ended provider job's responses and usage, or None when this
        pass ends with the job still processing, failed or unmatched."""
        status = self.provider.status(chunk["id"])
        chunk.update(api_status=status["api_status"], counts=status["counts"])
        if not status["ended"]:
            message = (
                "Provider batch is still processing."
                if not cancel
                else "Cancellation requested. Waiting for the provider's final status and any completed results."
            )
            if self.several:
                # A large record is saved once a pass, at its end (batch).
                self.job["message"] = message
            else:
                self.save("waiting", message)
            return None
        if status["terminal_failure"]:
            mapping = {item["custom_id"]: item["request"] for item in chunk["items"]}
            responses, errors, usage = self.provider.collect_terminal(
                chunk["id"], mapping
            )
            matched = set(responses) | {
                mapping[identity] for identity in errors if identity in mapping
            }
            if chunk.get("attached") and matched != set(mapping.values()):
                chunk["state"] = "unmatched"
                for item in chunk["items"]:
                    if item["request"] not in matched:
                        self.job["states"][item["request"]] = {
                            "state": "uncertain",
                            "message": "The attached terminal job did not verify this request ID.",
                        }
                for identity, response in responses.items():
                    self.accept(identity, response)
                self.save(
                    "uncertain",
                    "Verify the attached provider job before preparing any retry.",
                )
                return None
            for identity, response in responses.items():
                self.accept(identity, response)
            for item in chunk["items"]:
                if self.job["states"][item["request"]]["state"] != "accepted":
                    self.job["states"][item["request"]] = {
                        "state": "failed",
                        "message": "Provider job ended with "
                        + status["api_status"]
                        + ".",
                    }
            chunk.update(state="complete", usage=usage)
            if not cancel:
                self.halt(
                    "The provider batch failed. Review remaining work before paying for a retry."
                )
            return None
        mapping = {item["custom_id"]: item["request"] for item in chunk["items"]}
        responses, errors, usage = self.provider.collect(chunk["id"], mapping)
        known_errors = {mapping[identity] for identity in errors if identity in mapping}
        unmatched = set(mapping.values()) - set(responses) - known_errors
        if unmatched:
            for identity in unmatched:
                if self.job["states"][identity]["state"] != "accepted":
                    self.job["states"][identity] = {
                        "state": "uncertain",
                        "message": "The provider results did not identify this request. Reconcile the job; do not resubmit it.",
                    }
            for identity, response in responses.items():
                if identity in mapping.values():
                    self.accept(identity, response)
            chunk["state"] = "unmatched"
            self.save(
                "uncertain",
                "Returned request IDs are incomplete or belong to another job. Attach the matching job before proceeding.",
            )
            return None
        return responses, usage

    def finish(self):
        states = {row["state"] for row in self.job["states"].values()}
        if states <= {"accepted"}:
            self.save(
                "complete",
                "All requested translations are saved. Injection and runtime QA remain separate checkpoints.",
            )
        elif "uncertain" in states:
            self.save("uncertain", "Review unresolved requests before continuing.")
        else:
            self.save(
                "failed",
                "Canceled. Completed results are saved; review unresolved requests before continuing."
                if self.store.cancel_requested(self.job["id"])
                else "Review unresolved requests before continuing.",
            )

    def step(self, recover=True):
        """One pass of the run. Recovery rebuilds acceptance from the saved
        responses and results after an interruption; a worker that saved
        every change its earlier passes made can skip it."""
        if recover:
            self.recover()
        if any(row["state"] == "uncertain" for row in self.job["states"].values()):
            self.finish()
            return
        if self.plan["configuration"]["mode"] == "batch":
            self.batch()
        else:
            self.live()
