"""OpenRouter's inline Batch transport behind the preserved engine boundary."""

import json
import math
import os
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from dazedtl.settings.openrouter import MAX_BYTES, MAX_REQUESTS, validate_policy
from dazedtl.settings.providers import openrouter_host
from dazedtl.storage import write_json
from dazedtl.translation.files import decode_json, digest, project_path, read_json
from dazedtl.translation.refusals import refusal_reason, refused

BASE_URL = "https://openrouter.ai/api/v1"
TERMINAL = {"completed", "failed", "expired", "cancelled"}
MAX_RESPONSE_BYTES = 64_000_000
_worker_policy = None
_worker_root = None
_worker_configured = False


class ResultsUnavailable(ValueError):
    """Terminal provider work lacks verifiable request results; never resend."""


class RequestError(RuntimeError):
    def __init__(self, status):
        # A server-side timeout can follow a successful create.
        self.status_code = None if status == 408 else status
        super().__init__(
            f"OpenRouter returned HTTP {status}. No automatic paid retry was made."
        )


def is_route(endpoint):
    return str(endpoint or "").rstrip("/") == BASE_URL


def count(value):
    return value if type(value) is int and value >= 0 else None


def amount(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def envelope(model, rows, routing=None):
    """The same ordered wire envelope is used for submission and inspection."""
    return {
        "endpoint": "/v1/chat/completions",
        "model": model,
        "completion_window": "24h",
        **({"provider": {"only": routing["only"]}} if routing else {}),
        "requests": rows,
    }


def normalize(batch, identity):
    if not isinstance(batch, dict) or batch.get("id") != identity:
        raise ValueError("OpenRouter returned a different or invalid Batch receipt.")
    status = batch.get("status")
    if not isinstance(status, str) or status not in TERMINAL | {
        "validating",
        "in_progress",
        "finalizing",
        "cancelling",
    }:
        raise ValueError(
            "OpenRouter returned an unknown Batch status. Its receipt was retained."
        )
    raw = batch.get("request_counts") or {}
    if not isinstance(raw, dict):
        raise ResultsUnavailable(
            "OpenRouter returned invalid Batch counts. Its receipt was retained."
        )
    total, completed, failed = (
        count(raw.get(key)) for key in ("total", "completed", "failed")
    )
    if (
        total is not None
        and completed is not None
        and failed is not None
        and completed + failed > total
    ):
        raise ResultsUnavailable(
            "OpenRouter returned conflicting Batch counts. Its receipt was retained."
        )
    remaining = (
        total - completed - failed
        if total is not None and completed is not None and failed is not None
        else None
    )
    counts = {
        "total": total,
        "succeeded": completed,
        "errored": failed,
        "processing": 0 if status in TERMINAL else remaining,
        "expired": remaining if status == "expired" else 0,
        "canceled": remaining if status == "cancelled" else 0,
    }
    error = batch.get("error")
    errors = [error] if isinstance(error, dict) else []
    return {
        "id": identity,
        "api_status": status,
        "ended": status in TERMINAL,
        "terminal_failure": status in TERMINAL - {"completed"},
        "counts": counts,
        "errors": errors,
        "output_file_id": None,
        "error_file_id": None,
        "raw": batch,
        "can_cancel": False,
        "results_available": isinstance(batch.get("results"), list),
    }


class Client:
    """One connection, no redirects/retries, with optional durable run receipts."""

    def __init__(
        self,
        api_key,
        *,
        api_url=BASE_URL,
        policy=None,
        receipt_root=None,
        transport=None,
    ):
        if not is_route(api_url):
            raise ValueError(
                "OpenRouter Batch requires its original official API endpoint."
            )
        if not api_key:
            raise ValueError("OpenRouter Batch requires an API key.")
        self.api_key = api_key
        self.policy = policy
        self.receipt_root = Path(receipt_root) if receipt_root is not None else None
        self.timeout = 45
        self.http = httpx.Client(
            base_url=BASE_URL + "/",
            follow_redirects=False,
            transport=transport,
            headers={
                "Authorization": "Bearer " + api_key,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            timeout=self.timeout,
        )
        self._terminal = {}

    def with_options(self, *, timeout=45, max_retries=0, **_kwargs):
        self.timeout = timeout
        return self

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def request(self, method, path, *, body=None):
        content = (
            json.dumps(
                body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
            if body is not None
            else None
        )
        byte_limit = min(MAX_BYTES, (self.policy or {}).get("max_bytes", MAX_BYTES))
        if content is not None and len(content) > byte_limit:
            raise ValueError(
                "This OpenRouter Batch exceeds the application's request-size limit."
            )
        start, data = time.monotonic(), bytearray()
        with self.http.stream(
            method,
            path,
            content=content,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        ) as response:
            if response.status_code == 410 and method == "GET":
                raise ResultsUnavailable(
                    "OpenRouter's retained results have expired. Saved local responses remain available; this Batch will not be resubmitted."
                )
            if response.status_code not in ({202} if method == "POST" else {200}):
                raise RequestError(response.status_code)
            for part in response.iter_bytes(65536):
                data.extend(part)
                if len(data) > MAX_RESPONSE_BYTES or time.monotonic() - start > 90:
                    raise ValueError(
                        "OpenRouter's Batch response exceeded its read limit. The submission will not be repeated."
                    )
        # Never persist a credential echoed by an upstream error.
        value = decode_json(bytes(data).replace(self.api_key.encode(), b"[redacted]"))
        if not isinstance(value, dict):
            raise ValueError("OpenRouter returned an invalid Batch response.")
        return value

    def archive(self, identity, value, kind):
        if self.receipt_root is None:
            return
        path = project_path(
            self.receipt_root,
            f"log/openrouter/{digest(identity)}-{kind}.json",
            exists=False,
        )
        if path.exists():
            old = read_json(path, limit=MAX_RESPONSE_BYTES)
            if old != value:
                # Preserve both observations for reconciliation; never overwrite
                # a previously retained response with conflicting provider data.
                path = path.with_name(path.stem + "-" + digest(value) + ".json")
        write_json(path, value)

    def submit(self, requests):
        if not requests or len(requests) > MAX_REQUESTS:
            raise ValueError(
                "Split OpenRouter work into nonempty Batches within the application's request limit."
            )
        model = requests[0].get("params", {}).get("model")
        policy = validate_policy(self.policy, model)
        if len(requests) > policy["max_requests"]:
            raise ValueError("This OpenRouter Batch exceeds its frozen request limit.")
        from util.batch_providers import _openai_batch_body

        rows, seen = [], set()
        routing = None
        for item in requests:
            custom = item.get("custom_id")
            if (
                not isinstance(custom, str)
                or not custom
                or len(custom) > 200
                or custom in seen
            ):
                raise ValueError(
                    "OpenRouter Batch request IDs must be unique nonempty strings."
                )
            body = _openai_batch_body("openrouter", item["params"])
            if (
                body.get("model") != model
                or body.get("stream")
                or not body.get("messages")
            ):
                raise ValueError(
                    "OpenRouter Batch requires one model and non-streaming Chat Completions requests."
                )
            host = body.pop("provider", None)
            if policy.get("structuredOutputs"):
                if host != {"only": policy["providers"], "allow_fallbacks": False}:
                    raise ValueError(
                        "This request differs from its frozen structured-output Batch endpoints."
                    )
                response_format = body.get("response_format", {})
                schema = response_format.get("json_schema", {})
                if (
                    response_format.get("type") != "json_schema"
                    or schema.get("strict") is not True
                    or not schema.get("schema")
                ):
                    raise ValueError(
                        "This OpenRouter Batch requires a strict translation schema."
                    )
                if (
                    rows
                    and model.startswith("google/")
                    and response_format != rows[0]["body"].get("response_format")
                ):
                    raise ValueError(
                        "Google Batch requests must use the same translation schema. Prepare separate Batches."
                    )
            elif host is not None:
                selected = host.get("only") if isinstance(host, dict) else None
                if (
                    not isinstance(selected, list)
                    or len(selected) != 1
                    or not openrouter_host(selected[0])
                    or host != {"only": selected, "allow_fallbacks": False}
                ):
                    raise ValueError(
                        "OpenRouter Batch requires one exclusive host or automatic routing."
                    )
            if rows and host != routing:
                raise ValueError(
                    "All requests in an OpenRouter Batch must use the same host."
                )
            if (
                not policy.get("structuredOutputs")
                and "host" in policy
                and (host.get("only", [""])[0] if host else "") != policy["host"]
            ):
                raise ValueError(
                    "This request's OpenRouter host differs from its frozen Batch policy."
                )
            routing = host
            if any(
                key in body
                for key in ("plugins", "tools", "modalities", "audio", "image_config")
            ):
                raise ValueError(
                    "This OpenRouter Batch contains unsupported translation parameters."
                )
            seen.add(custom)
            rows.append({"custom_id": custom, "body": body})
        # OpenRouter stream-parses this object: requests MUST follow the header.
        body = envelope(policy["model"], rows, routing)
        batch = self.request("POST", "batches", body=body)
        identity = batch.get("id")
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError(
                "OpenRouter accepted the submission without a usable Batch ID. Reconcile it before retrying."
            )
        self.archive(identity, batch, "submission")
        # The caller journals the returned ID before any later status validation.
        return {"id": identity, "transport": policy["transport"]}

    def retrieve(self, identity):
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("Choose a retained OpenRouter Batch ID.")
        if identity in self._terminal:
            return deepcopy(self._terminal[identity])
        if self.receipt_root is not None:
            path = project_path(
                self.receipt_root,
                f"log/openrouter/{digest(identity)}-accepted.json",
                exists=False,
            )
            if path.is_file():
                batch = read_json(path, limit=MAX_RESPONSE_BYTES)
                normalize(batch, identity)
                if isinstance(batch.get("results"), list):
                    self._terminal[identity] = batch
                    return deepcopy(batch)
        batch = self.request("GET", "batches/" + quote(identity, safe=""))
        # Keep malformed terminal evidence too; it cannot authorize consumption.
        if batch.get("status") in TERMINAL:
            self.archive(identity, batch, "results")
        normalize(batch, identity)
        if batch.get("status") in TERMINAL and isinstance(batch.get("results"), list):
            self._terminal[identity] = batch
        return batch

    def collect(self, identity, mapping):
        batch = self.retrieve(identity)
        status = normalize(batch, identity)
        if not status["ended"]:
            raise ValueError("OpenRouter is still processing this Batch.")
        if status["counts"]["total"] is not None and status["counts"]["total"] != len(
            mapping
        ):
            raise ResultsUnavailable(
                "OpenRouter's request count differs from this Batch's retained mapping."
            )
        rows = batch.get("results")
        if not isinstance(rows, list):
            counts = status["counts"]
            if counts["succeeded"] == 0 and counts["errored"] == counts["total"] == len(
                mapping
            ):
                return (
                    {},
                    [(key, "OpenRouter rejected this request.") for key in mapping],
                    usage(batch, []),
                )
            raise ResultsUnavailable(
                "OpenRouter ended this Batch without verifiable results. Inspect its saved receipt; no requests will be resubmitted automatically."
            )
        from util.batch_providers import _openai_result

        seen, results, errors, normalized = set(), {}, [], []
        for row in rows:
            custom = row.get("custom_id") if isinstance(row, dict) else None
            if not isinstance(custom, str) or custom not in mapping or custom in seen:
                raise ResultsUnavailable(
                    "OpenRouter returned duplicate or unrelated request IDs. Its responses were retained for reconciliation."
                )
            seen.add(custom)
            response, error = row.get("response"), row.get("error")
            if (
                bool(response) == bool(error)
                or response
                and (
                    not isinstance(response, dict)
                    or type(response.get("status_code")) is not int
                    or not 200 <= response["status_code"] < 600
                    or 300 <= response["status_code"] < 400
                    or not isinstance(response.get("body"), dict)
                )
            ):
                raise ResultsUnavailable(
                    "OpenRouter returned an incomplete or conflicting request result. Its response was retained."
                )
            try:
                result, error = _openai_result(row, "openrouter")
            except ValueError, TypeError, KeyError, OverflowError:
                raise ResultsUnavailable(
                    "OpenRouter returned an invalid request response. Its receipt was retained for inspection."
                ) from None
            if error:
                errors.append(
                    (
                        custom,
                        "OpenRouter returned an unsuccessful response. Inspect its retained receipt.",
                    )
                )
                continue
            assert result is not None  # Rows without an error carry a result.
            body = row.get("response", {}).get("body", {})
            if refused(body):
                result["refusal"] = refusal_reason(body) or True
            result["provider_response"] = body
            results[mapping[custom]] = result
            normalized.append(result)
        if seen != set(mapping):
            raise ResultsUnavailable(
                "OpenRouter's results do not cover every submitted request ID. The retained Batch will not be resubmitted."
            )
        self.archive(identity, batch, "accepted")
        return results, errors, usage(batch, normalized)


def usage(batch, results):
    keys = {
        "input_tokens": "prompt_tokens",
        "output_tokens": "completion_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
        "thinking_tokens": "thinking_tokens",
    }
    totals = {
        key: sum(row.get(source, 0) for row in results) for key, source in keys.items()
    }
    totals["input_tokens"] = max(
        0,
        totals["input_tokens"]
        - totals["cache_read_input_tokens"]
        - totals["cache_creation_input_tokens"],
    )
    reported = batch.get("usage") or {}
    if not isinstance(reported, dict):
        reported = {}
    if count(reported.get("prompt_tokens")) is not None:
        totals["input_tokens"] = max(
            0,
            reported["prompt_tokens"]
            - totals["cache_read_input_tokens"]
            - totals["cache_creation_input_tokens"],
        )
    if count(reported.get("completion_tokens")) is not None:
        totals["output_tokens"] = reported["completion_tokens"]
    charge = amount(reported.get("cost"))
    details = reported.get("cost_details")
    upstream = (
        amount(details.get("upstream_inference_cost"))
        if isinstance(details, dict)
        else None
    )
    if charge is not None:
        totals["openrouter_cost"] = charge
    if reported.get("is_byok") is True and upstream is not None:
        totals["upstream_inference_cost"] = upstream
    return totals


def detect(native, model="", api_url=None, api_provider=None):
    endpoint = os.getenv("api", "") if api_url is None else api_url
    protocol = (
        os.getenv("API_PROVIDER", "openai") if api_provider is None else api_provider
    )
    if protocol in {"openai", "openrouter"} and is_route(endpoint):
        return (
            "openrouter"
            if not _worker_configured or _worker_policy is not None
            else None
        )
    return native(model, api_url, api_provider)


def client(native, provider, *, api_key=None, api_url=None, max_retries=None):
    if provider == "openrouter":
        return Client(
            api_key if api_key is not None else os.getenv("key", ""),
            api_url=api_url or os.getenv("api", "") or BASE_URL,
            policy=_worker_policy,
            receipt_root=_worker_root,
        )
    return native(provider, api_key=api_key, api_url=api_url, max_retries=max_retries)


def limits(native, provider):
    if provider != "openrouter":
        return native(provider)
    return (
        (_worker_policy or {}).get("max_requests", MAX_REQUESTS),
        (_worker_policy or {}).get("max_bytes", MAX_BYTES) - 4096,
    )


def label(native, provider):
    return "OpenRouter" if provider == "openrouter" else native(provider)


def operation(name):
    def call(native, provider, *args, client=None, **kwargs):
        if provider != "openrouter":
            return native(provider, *args, client=client, **kwargs)
        if name == "cancel_batch":
            raise ValueError(
                "OpenRouter does not expose Batch cancellation. Submitted work continues at the provider."
            )
        from util import batch_providers

        # The provider's get_client layer returns this module's Client.
        owner: Any = (
            nullcontext(client)
            if client is not None
            else batch_providers.get_client(provider)
        )
        with owner as connection:
            if name == "submit_batch":
                return connection.submit(*args)
            if name == "retrieve_batch":
                return normalize(connection.retrieve(*args), args[0])
            return connection.collect(*args)

    return call


def install():
    """Adds OpenRouter as a Batch provider beside the engine's own providers."""
    from util import batch_providers as native
    from util import extensions

    extensions.layer(native.detect_batch_provider, "openrouter", detect)
    extensions.layer(native.get_client, "openrouter", client)
    extensions.layer(native.batch_limits, "openrouter", limits)
    extensions.layer(native.batch_provider_label, "openrouter", label)
    for name in ("submit_batch", "retrieve_batch", "download_results", "cancel_batch"):
        extensions.layer(getattr(native, name), "openrouter", operation(name))


def configure(policy, root):
    global _worker_policy, _worker_root, _worker_configured
    _worker_configured = True
    _worker_policy = policy
    _worker_root = Path(root) if policy is not None else None
