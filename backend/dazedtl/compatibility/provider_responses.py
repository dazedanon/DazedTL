"""Retain provider failure bodies and refusal metadata for inspection, and
read a provider's error the one way a run's messages show it."""

import ast
import json
import re
from types import SimpleNamespace

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
        fields = _fields(body)
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


def _fields(body):
    """The error fields of a provider's error *body*: the ``error`` object
    OpenAI-compatible and Anthropic bodies hold, else the body itself."""
    return body.get("error", body) if isinstance(body, dict) else body


def provider_error(detail):
    """How a provider's error *detail* (error_evidence) reads in a run's
    messages: its HTTP status and its own message, without the SDK's and the
    engine's wrapping; without a message, its code, such as a flagged prompt's
    content_filter. A Batch request's error carries no status."""
    fields = _fields(detail.get("body"))
    own = isinstance(fields, dict) and fields.get("message")
    text = detail["message"].strip() if own else ""
    code = detail.get("code")
    if not text and isinstance(code, str):
        text = code.strip()
    if text and not text.endswith((".", "!", "?")):
        text += "."
    status = detail.get("status")
    if status is None:
        return text or "The provider gave no reason."
    return f"HTTP {status} - {text}" if text else f"HTTP {status} with no reason given."


def stored_reason(text):
    """How a Batch request's error, as a fetch stores it (batch_providers: the
    provider's error object, failed response or error-file row as Python
    text), reads in a
    run's messages (provider_error); any other text, such as a refused
    effort's message or an Anthropic result's type, reads as it is."""
    text = str(text or "")
    try:
        value = ast.literal_eval(text) if text.lstrip().startswith("{") else None
    except ValueError, TypeError, SyntaxError, MemoryError, RecursionError:
        value = None  # Cut short at 500 characters, or not Python's text.
    if not isinstance(value, dict):
        return text
    if not value.get("error") and isinstance(value.get("response"), dict):
        # A row of OpenAI's error file, kept whole: its failed response.
        value = value["response"]
    status = value.get("status_code")
    status = status if type(status) is int else None
    body = value.get("body") if status is not None else value
    fields = _fields(body)
    if not isinstance(fields, dict):
        return text
    from .process_view import clean_message

    return provider_error(
        {
            "status": status,
            "code": fields.get("code"),
            "message": clean_message(fields.get("message")),
            "body": body,
        }
    )


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


def openai_result(native, row, *args, **kwargs):
    result, error = native(row, *args, **kwargs)
    body = (row.get("response") or {}).get("body") or {}
    if result is not None and refused(body):
        result["refusal"] = refusal_reason(body) or True
    return result, error


def anthropic_entry(native, message):
    result = native(message)
    if refused(message):
        result["refusal"] = True
    return result


def anthropic_download(native, client, batch_id, custom_ids):
    rejected = set()

    def rows(identity):
        for row in client.messages.batches.results(identity):
            if row.result.type == "succeeded" and refused(row.result.message):
                rejected.add(row.custom_id)
            yield row

    observed = SimpleNamespace(
        messages=SimpleNamespace(batches=SimpleNamespace(results=rows))
    )
    results, errors, usage = native(observed, batch_id, custom_ids)
    for custom in rejected:
        if custom in custom_ids and custom_ids[custom] in results:
            results[custom_ids[custom]]["refusal"] = True
    return results, errors, usage


def install():
    """Mark refused Batch results so collection can retry or review them."""
    from util import batch_history, batch_providers

    batch_providers._openai_result.layer("refusals", openai_result)
    batch_history._result_entry_from_message.layer("refusals", anthropic_entry)
    batch_providers._download_anthropic.layer("refusals", anthropic_download)
