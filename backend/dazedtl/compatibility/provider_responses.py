"""Retain provider failure bodies and refusal metadata for inspection."""

import json
import re
from functools import wraps
from types import SimpleNamespace
from typing import Any, cast

from dazedtl.translation.refusals import refusal_reason, refused


def error_evidence(error, secret=""):
    """Read SDK response evidence, never exception strings or request headers."""
    from .process_view import clean_message

    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        if body is None:
            response = getattr(current, "response", None)
            try:
                body = response.text if response is not None else None
            except Exception:  # noqa: BLE001
                body = None  # An unread response must not trigger a network read.
        if body is not None or getattr(current, "status_code", None) is not None:
            break
        current = current.__cause__ or current.__context__
    current = current or error
    status = getattr(current, "status_code", None)
    detail = {"status": status}
    if body is not None:
        body = sanitized_body(body, secret)
        fields = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(fields, dict):
            detail.update(
                {
                    key: fields[key]
                    for key in ("message", "code", "param", "type")
                    if key in fields
                }
            )
        detail["body"] = body
    # Historical failure summaries use this field; the inspector retains the
    # full body separately, including nested OpenRouter metadata.raw errors.
    detail["message"] = clean_message(
        detail.get("message")
        or (
            f"Provider returned HTTP {status}."
            if status is not None
            else f"Provider request failed ({type(current).__name__})."
        ),
        secret,
    )
    return detail


def sanitized_body(body, secret=""):
    """Bound retained diagnostics and redact credentials inside nested JSON."""
    from .process_view import clean_message

    limit = 64_000
    sensitive = {
        "authorization",
        "proxyauthorization",
        "apikey",
        "xapikey",
        "key",
        "token",
        "accesstoken",
        "refreshtoken",
        "password",
        "secret",
        "cookie",
        "setcookie",
    }

    def clean(value, depth=0):
        if depth > 20:
            return "[nested response truncated]"
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError, RecursionError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(clean(parsed, depth + 1), ensure_ascii=False)
            return clean_message(value, secret, limit=None)
        if isinstance(value, dict):
            return {
                clean_message(key, secret): "[credential removed]"
                if re.sub(r"[^a-z]", "", key.lower()) in sensitive
                else clean(item, depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [clean(item, depth + 1) for item in value]
        return value

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError, RecursionError:
            pass
    result = clean(body)
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return text[:limit] + "\n[response truncated]" if len(text) > limit else result


def install():
    from util import batch_history, batch_providers

    if getattr(batch_providers._openai_result, "_dazedtl_refusals", False):
        return
    native = batch_providers._openai_result

    @wraps(native)
    def openai_result(row, *args, **kwargs):
        result, error = native(row, *args, **kwargs)
        if result is not None and refused(
            (row.get("response") or {}).get("body") or {}
        ):
            result["refusal"] = (
                refusal_reason((row.get("response") or {}).get("body") or {}) or True
            )
        return result, error

    cast(Any, openai_result)._dazedtl_refusals = True
    batch_providers._openai_result = openai_result
    anthropic_entry = batch_history._result_entry_from_message

    @wraps(anthropic_entry)
    def entry(message):
        result = anthropic_entry(message)
        if refused(message):
            result["refusal"] = True
        return result

    batch_history._result_entry_from_message = entry
    native_download = batch_providers._download_anthropic

    @wraps(native_download)
    def download(client, batch_id, custom_ids):
        rejected = set()

        def rows(identity):
            for row in client.messages.batches.results(identity):
                if row.result.type == "succeeded" and refused(row.result.message):
                    rejected.add(row.custom_id)
                yield row

        observed = SimpleNamespace(
            messages=SimpleNamespace(batches=SimpleNamespace(results=rows))
        )
        results, errors, usage = native_download(observed, batch_id, custom_ids)
        for custom in rejected:
            if custom in custom_ids and custom_ids[custom] in results:
                results[custom_ids[custom]]["refusal"] = True
        return results, errors, usage

    batch_providers._download_anthropic = download
