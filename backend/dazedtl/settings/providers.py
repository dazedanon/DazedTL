"""Connection presets and explicit, non-generating access checks."""

import ipaddress
import json
import os
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx

from . import effort

# A preset declares its transport protocol independently of its identity. Kimi,
# DeepSeek and OpenRouter keep OpenAI's Live request formats under their own
# identity, so Kimi's Batches carry its eligible models and price factor (engine
# batch_providers and provider_costs), DeepSeek gets JSON mode instead of strict
# schemas, and OpenRouter has its own Batch transport
# (compatibility/openrouter_batch.py).
PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "openai",
        # Test scenarios point OpenAI at a local stand-in to run Batch offline;
        # see "Test scenarios" in docs/development.md.
        "endpoint": os.environ.get("DAZEDTL_TEST_OPENAI_ENDPOINT")
        or "https://api.openai.com/v1",
    },
    # Test scenarios check these presets against the stand-in's model lists.
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "openai",
        "endpoint": os.environ.get("DAZEDTL_TEST_OPENROUTER_ENDPOINT")
        or "https://openrouter.ai/api/v1",
    },
    "anthropic": {
        "label": "Anthropic",
        "protocol": "anthropic",
        "endpoint": os.environ.get("DAZEDTL_TEST_ANTHROPIC_ENDPOINT")
        or "https://api.anthropic.com",
    },
    "gemini": {
        "label": "Google Gemini",
        "protocol": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
    },
    "mistral": {
        "label": "Mistral",
        "protocol": "mistral",
        "endpoint": "https://api.mistral.ai/v1",
    },
    "kimi": {
        "label": "Kimi",
        "protocol": "openai",
        "endpoint": "https://api.moonshot.ai/v1",
    },
    "deepseek": {
        "label": "DeepSeek",
        "protocol": "openai",
        "endpoint": "https://api.deepseek.com",
    },
    "custom": {"label": "Custom / local", "protocol": "openai", "endpoint": ""},
}
PROTOCOLS = {"openai", "anthropic", "gemini", "mistral"}


def endpoint(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("Enter a valid server URL.")
    value = value.strip()
    if value:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname
                and not (url.username or url.password or url.query or url.fragment)
            )
            _ = url.port  # Raises ValueError for an invalid port.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "Use an HTTP or HTTPS base URL without a query, fragment, or embedded credentials."
            )
    return value


def address(connection):
    return connection["endpoint"] or PROVIDERS.get(connection["provider"], {}).get(
        "endpoint", ""
    )


def validate_model_name(model, endpoint):
    """Refuses a Claude name in another host's form for Anthropic's own API
    (provider_costs.foreign_claude_name), where every request, Live or Batch,
    would fail with not found: when Settings saves it, and before a run
    starts or resumes with it."""
    from util.provider_costs import foreign_claude_name

    if foreign_claude_name(model, endpoint):
        raise ValueError(
            "Anthropic's API takes Claude's own model IDs, such as claude-opus-5-5, "
            f"not another host's name for one, such as {str(model).strip()}. "
            "Enter Anthropic's ID for this model in Settings, or use that host's connection."
        )


# The host only a provider's own API serves, unlike others that serve its models.
OWN_HOSTS = {
    "openai": "api.openai.com",
    "kimi": "api.moonshot.ai",
    "deepseek": "api.deepseek.com",
}


def own_api(identity, endpoint):
    """Whether `endpoint` is the provider `identity`'s own API: OpenAI's, whose
    Batches share one enqueued-token window; Kimi's, with its own Batches; or
    DeepSeek's, with its own output ceiling and JSON mode. The one rule the app
    and the engine ask; in test scenarios the OpenAI preset's stand-in, which
    DAZEDTL_TEST_OPENAI_ENDPOINT names, counts as OpenAI's."""
    value = str(endpoint or "").strip().rstrip("/")
    stand_in = os.environ.get("DAZEDTL_TEST_OPENAI_ENDPOINT", "").strip().rstrip("/")
    try:
        hostname = urlsplit(value).hostname
    except ValueError:
        hostname = None
    return hostname == OWN_HOSTS[identity] or (
        identity == "openai" and bool(stand_in) and value == stand_in
    )


def completion_field(protocol, endpoint):
    """Whether an OpenAI-protocol request names its reply limit
    `max_completion_tokens`: on OpenAI's own API (its address when none is
    set) and Kimi's, which documents it and deprecates `max_tokens`; every
    other server takes `max_tokens`. *protocol* is the engine's API_PROVIDER
    or Batch provider name. https://platform.kimi.ai/docs/api/chat"""
    endpoint = str(endpoint or "").strip()
    protocol = str(protocol or "").strip()
    if protocol == "kimi":
        return True
    return protocol == "openai" and (
        not endpoint or own_api("openai", endpoint) or own_api("kimi", endpoint)
    )


def local(endpoint):
    """Whether *endpoint* is a server on this computer, which bills nothing.
    A server elsewhere on the network may be a gateway to a paid provider.
    The one rule Settings and the legacy evaluation's budget ask."""
    try:
        host = urlsplit(str(endpoint or "").strip()).hostname or ""
    except ValueError:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        value = ipaddress.ip_address(host)
    except ValueError:
        return False
    return value.is_loopback or value.is_unspecified


def response_format(protocol, endpoint, model, schema, name, *, batch=False):
    """The structured output an OpenAI-protocol request on this route asks
    for: JSON mode where the route has no strict schemas, otherwise a strict
    `schema`. The one rule Guided and Assistant-led request builders and the
    Batch transport call. DeepSeek's JSON mode has no strict schemas on any
    host, and Gemini's Batch files take JSON mode only; a server that rejects
    a schema still gets JSON mode from the senders' fallbacks (engine
    translateText and callMistral, batch_providers.execute_live_request)."""
    json_mode = (
        "deepseek" in str(model or "").lower()
        or own_api("deepseek", endpoint)
        or (batch and protocol == "gemini")
    )
    if json_mode:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def route(protocol, url):
    value = url.rstrip("/")
    if protocol == "anthropic" and value == "https://api.anthropic.com/v1":
        value = "https://api.anthropic.com"
    return protocol, value


def infer_provider(protocol, url):
    """Recognize explicit provider routes; never infer from a secret or its name."""
    for identity, definition in PROVIDERS.items():
        if identity != "custom" and route(protocol, url) == route(
            definition["protocol"], definition["endpoint"]
        ):
            return identity
    return "custom" if url and protocol in {"openai", "gemini", "mistral"} else None


def unchecked():
    return {"status": "not_checked", "message": "Saved, not checked", "checkedAt": None}


def openrouter_host(value):
    """An empty host preserves automatic routing; otherwise use a provider slug."""
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("Choose a valid OpenRouter host.")
    value = value.strip().lower()
    if value and not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*", value
    ):
        raise ValueError("Choose a valid OpenRouter host.")
    return value


def openrouter_hosts(model=""):
    """Read model-specific hosts (or the legacy public catalog), without credentials."""
    if (
        not isinstance(model, str)
        or len(model) > 200
        or model
        and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*", model
        )
    ):
        raise ValueError(
            "Choose a valid OpenRouter model in Preferences before loading its hosts."
        )
    path = "/models/" + quote(model, safe="/") + "/endpoints" if model else "/providers"
    try:
        deadline = time.monotonic() + 8
        with (
            httpx.Client(
                timeout=httpx.Timeout(3, connect=3), follow_redirects=False
            ) as client,
            client.stream(
                "GET",
                PROVIDERS["openrouter"]["endpoint"] + path,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response,
        ):
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_raw(chunk_size=65536):
                content.extend(chunk)
                if len(content) > 1_000_000 or time.monotonic() > deadline:
                    raise ValueError(
                        "OpenRouter's host list was too large or took too long. Try again."
                    )
        data = json.loads(content).get("data")
        if model and (not isinstance(data, dict) or data.get("id") != model):
            raise ValueError
        rows = data.get("endpoints") if model else data
        if not isinstance(rows, list) or len(rows) > 512:
            raise ValueError
        hosts = {}
        for row in rows:
            # An endpoint tag is "host/variant"; variants collapse to the host.
            slug = openrouter_host(row["tag"].split("/")[0] if model else row["slug"])
            name = row["provider_name"] if model else row["name"]
            if (
                not slug
                or not isinstance(name, str)
                or not 0 < len(name.strip()) <= 200
                or any(ord(char) < 32 for char in name)
            ):
                raise ValueError
            hosts[slug] = {"slug": slug, "name": name.strip()}
        return sorted(
            hosts.values(), key=lambda host: (host["name"].casefold(), host["slug"])
        )
    except httpx.HTTPError:
        raise ValueError(
            "OpenRouter's host list could not be loaded. Check your connection and try again."
        ) from None
    except ValueError, TypeError, KeyError, AttributeError:
        raise ValueError(
            "OpenRouter returned an unavailable or invalid host list. Try again later."
        ) from None


def _headers(connection):
    """The headers that reach *connection*'s server as its key allows: its
    key, Anthropic's API version, and an OpenAI organization where the
    route is not OpenRouter's."""
    protocol = connection["protocol"]
    base = route(protocol, address(connection))[1]
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if not connection["keyless"]:
        if protocol == "anthropic":
            headers.update(
                {"x-api-key": connection["secret"], "anthropic-version": "2023-06-01"}
            )
        else:
            headers["Authorization"] = "Bearer " + connection["secret"]
    if (
        connection.get("organization")
        and protocol == "openai"
        and infer_provider(protocol, base) != "openrouter"
    ):
        headers["OpenAI-Organization"] = connection["organization"]
    return headers


def check(connection):
    """A bounded model-list request; no inference, retries, or redirects.

    https://developers.openai.com/api/reference/overview
    https://platform.claude.com/docs/en/api/models/list
    https://ai.google.dev/gemini-api/docs/openai#list-models
    https://docs.mistral.ai/api/endpoint/models
    https://api-docs.deepseek.com/api/list-models
    https://openrouter.ai/docs/api/api-reference/models/list-models-filtered-by-user-provider-preferences-privacy-settings-and-guardrails
    """
    protocol = connection["protocol"]
    base = route(protocol, address(connection))[1]
    openrouter = infer_provider(protocol, base) == "openrouter"
    headers = _headers(connection)
    # OpenRouter's public catalog cannot verify a key. Its account-filtered
    # list requires authentication and defaults to text-output models.
    url = base + (
        "/models/user"
        if openrouter
        else "/v1/models?limit=250"
        if protocol == "anthropic"
        else "/models"
    )
    byte_limit = 8_000_000 if openrouter else 2_000_000
    model_limit = 2000 if openrouter else 250

    def result(status, message, models=None, catalog=None):
        return {
            "check": {
                "status": status,
                "message": message,
                "checkedAt": datetime.now(UTC).isoformat(),
            },
            "models": models,
            **({"catalog": catalog} if catalog is not None else {}),
        }

    try:
        deadline = time.monotonic() + 8
        with (
            httpx.Client(
                timeout=httpx.Timeout(3, connect=3), follow_redirects=False
            ) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            status = response.status_code
            if status == 400:
                return result(
                    "failed",
                    "The provider rejected the connection details. Check the API key and server URL.",
                )
            if status == 401:
                return result(
                    "failed",
                    "Authentication was rejected. Check the API key and provider.",
                )
            if status == 403:
                return result(
                    "unavailable",
                    "Model-list access was refused. This key may have restricted permissions.",
                )
            if status == 429:
                return result(
                    "unavailable",
                    "The provider is rate limiting requests. Try checking again later.",
                )
            if status in {301, 302, 303, 307, 308, 404, 405}:
                return result(
                    "unsupported",
                    "This address does not expose the expected model list. Check the server's base URL.",
                )
            if status != 200:
                return result(
                    "unavailable",
                    f"The provider returned HTTP {status}. The connection was saved, but could not be verified.",
                )
            content = bytearray()
            for chunk in response.iter_raw(chunk_size=65536):
                content.extend(chunk)
                if len(content) > byte_limit or time.monotonic() > deadline:
                    return result(
                        "unavailable",
                        "The model list was too large or took too long. Try again later.",
                    )
        payload = json.loads(content)
        rows = (
            payload.get("data")
            if isinstance(payload, dict)
            else payload
            if protocol == "mistral"
            else None
        )
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("id"), str)
            for row in rows
        ):
            return result(
                "unsupported",
                "The server replied with an unsupported model list. Check the provider and base URL.",
            )
        models = sorted(
            {
                row["id"]
                for row in rows
                if 0 < len(row["id"]) <= 200
                and not any(ord(char) < 32 for char in row["id"])
                and not (openrouter and row["id"].endswith(":batch"))
            }
        )[:model_limit]
        official = any(
            route(protocol, base) == route(item["protocol"], item["endpoint"])
            for name, item in PROVIDERS.items()
            if name != "custom"
        )
        if official and not connection["keyless"]:
            from .openrouter import catalog, check_endpoints

            known = catalog(rows) if openrouter else None
            value = result(
                "verified",
                "Authentication verified. Model availability and usage limits can still vary.",
                models,
                known,
            )
            if openrouter:
                value["batch_endpoints"] = check_endpoints(connection, known)
            # Which efforts each model takes, where the list says (EF2).
            identity = infer_provider(protocol, base)
            if identity in effort.LISTED:
                value["efforts"] = effort.model_list(identity, rows)
            return value
        return result(
            "reachable",
            "Server reached. This check does not prove that a custom server enforces API-key authentication.",
            models,
        )
    except httpx.TimeoutException:
        return result(
            "unavailable",
            "The connection timed out. Check the server address and network, then try again.",
        )
    except httpx.HTTPError:
        # Plain HTTP servers, often local ones, have no certificate to check.
        return result(
            "unavailable",
            "The server could not be reached. Check the address, network, and certificate."
            if url.startswith("https:")
            else "The server could not be reached. Check the address and network.",
        )
    except ValueError, UnicodeError:
        return result(
            "unsupported",
            "The key, address, or server response could not be used. Review the connection details.",
        )


# A check of a thinking effort: one short request whose reply, thinking
# included, stops at CHECK_TOKENS, so it costs a fraction of a cent.
CHECK_PROMPT = "Reply with OK."
CHECK_TOKENS = 16
# Every other backend request waits behind a check, so each step of it is
# bounded and the whole ends before the backend counts as stalled
# (api/server REQUEST_STALL_SECONDS).
CHECK_TIMEOUT = httpx.Timeout(10, connect=4)
CHECK_SECONDS = 20


def effort_request(connection, model, level, listed=None):
    """The URL, headers and JSON body of the one short request that checks
    *level* for *connection*'s *model*, the effort written in as runs write
    it (settings/effort apply, with *listed*); with no level it sends none,
    as a run that leaves the effort to the provider."""
    protocol = connection["protocol"]
    identity = connection["provider"]
    base = route(protocol, address(connection))[1]
    headers = {**_headers(connection), "Content-Type": "application/json"}
    messages = [{"role": "user", "content": CHECK_PROMPT}]
    if protocol == "anthropic":
        url = base + "/v1/messages"
        params = {"model": model, "max_tokens": CHECK_TOKENS, "messages": messages}
    else:
        url = base + "/chat/completions"
        limit = (
            "max_completion_tokens"
            if completion_field(protocol, base)
            else "max_tokens"
        )
        params = {"model": model, "messages": messages, limit: CHECK_TOKENS}
    if level is not None:
        params = effort.apply(params, identity, model, level, listed)
    return url, headers, effort.flat(params)


def _reason(payload, text, secret):
    """A refusal's reason in plain words: the message its error body carries,
    else its text, on one short line that never holds the key. Gemini's
    OpenAI-compatible endpoint wraps its error body in a list."""
    if isinstance(payload, list) and payload:
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    reason = (
        error.get("message")
        if isinstance(error, dict)
        else error
        if isinstance(error, str)
        else payload.get("message")
        if isinstance(payload, dict) and isinstance(payload.get("message"), str)
        else detail
        if isinstance(detail, str)
        else detail[0].get("msg")
        if isinstance(detail, list) and detail and isinstance(detail[0], dict)
        else text
    )
    reason = " ".join(
        "".join(char for char in str(reason or "") if char.isprintable()).split()
    )
    if secret and len(secret) >= 8:
        reason = reason.replace(secret, "[key]")
    reason = reason.rstrip(".") or "the server gave no reason"
    return reason if len(reason) <= 300 else reason[:299].rstrip() + "…"


def _thinking(protocol, payload):
    """Whether a reply shows the model thought, and the reasoning tokens it
    reports, or (None, None) when it doesn't say."""
    if protocol == "anthropic":
        return any(
            isinstance(block, dict)
            and block.get("type") in ("thinking", "redacted_thinking")
            for block in payload["content"]
        ), None
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    details = usage.get("completion_tokens_details")
    tokens = (details if isinstance(details, dict) else {}).get(
        "reasoning_tokens", usage.get("reasoning_tokens")
    )
    if type(tokens) is not int or tokens < 0:
        tokens = None
    choice = payload["choices"][0] if payload["choices"] else None
    message = choice.get("message") if isinstance(choice, dict) else None
    reasoned = isinstance(message, dict) and any(
        isinstance(message.get(key), str) and message[key].strip()
        for key in ("reasoning_content", "reasoning")
    )
    if reasoned or tokens:
        return True, tokens
    return (False, 0) if tokens == 0 else (None, None)


def _applied(payload):
    """The effort a reply says its provider applied, where it names one."""
    reasoning = payload.get("reasoning")
    value = (
        reasoning.get("effort")
        if isinstance(reasoning, dict)
        else payload.get("reasoning_effort")
    )
    return value if value in effort.LEVELS else None


def check_effort(connection, model, level, listed=None):
    """Sends the one short request that checks whether *connection*'s server
    takes *level* for *model* (``effort_request``): one attempt with no
    retries or redirects, sent only on the user's click in Settings or by
    the maintainer's scripts/effort_check.py. Its outcome is "accepted",
    with what the reply shows of the model's thinking; "refused", with the
    server's reason (HTTP 400 or 422, which providers don't bill); or
    "failed" when it can say neither, such as an unreachable server or a
    rejected key."""
    protocol = connection["protocol"]
    url, headers, body = effort_request(connection, model, level, listed)

    def failed(message):
        return {"status": "failed", "message": message}

    content = bytearray()
    try:
        deadline = time.monotonic() + CHECK_SECONDS
        with (
            httpx.Client(timeout=CHECK_TIMEOUT, follow_redirects=False) as client,
            client.stream(
                "POST", url, headers=headers, content=json.dumps(body).encode()
            ) as response,
        ):
            status = response.status_code
            for chunk in response.iter_bytes(chunk_size=65536):
                content.extend(chunk)
                if len(content) > 1_000_000 or time.monotonic() > deadline:
                    return failed(
                        "The server's reply was too large or took too long. Check again later."
                    )
    except httpx.TimeoutException:
        return failed(
            "The server didn't answer in time. If it was loading the model, check again once it has."
        )
    except httpx.HTTPError:
        return failed("The server could not be reached. Check the address and network.")
    text = content.decode("utf-8", "replace")
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if status in (400, 422):
        reason = _reason(payload, text, connection.get("secret", ""))
        # A refusal that doesn't name the effort, such as an unknown model,
        # says nothing about the level, so it saves nothing either; runs read
        # a refusal by the same rule (settings/effort).
        if not effort.refuses(status, reason):
            return failed(
                f"The server refused the request for another reason: {reason}."
            )
        return {"status": "refused", "message": f"Refused: {reason}."}
    if status != 200:
        return failed(
            "Authentication was rejected. Check the API key."
            if status == 401
            else "Access was refused. This key may not be allowed to use this model."
            if status == 403
            else "The server doesn't serve this model at this address. Check the model ID and server URL."
            if status == 404
            else "The server is rate limiting requests. Try again later."
            if status == 429
            else "The server redirected the request. Check the server's base URL."
            if 300 <= status < 400
            else f"The server returned HTTP {status}. Try again later."
        )
    if not isinstance(payload, dict) or not isinstance(
        payload.get("content" if protocol == "anthropic" else "choices"), list
    ):
        return failed("The server's reply could not be read as a chat reply.")
    thought, tokens = _thinking(protocol, payload)
    counted = f" ({tokens:,} reasoning tokens)" if tokens else ""
    return {
        "status": "accepted",
        "message": "Accepted. The reply doesn't say whether the model thought, so DazedTL can't tell whether the server uses the effort."
        if thought is None
        else f"Accepted, but the model still thought{counted}."
        if thought and level == "none"
        else f"Accepted, and the model thought{counted}."
        if thought
        else "Accepted, and the model didn't think."
        if level == "none"
        else "Accepted. The model didn't think about this short request.",
        "thought": thought,
        "applied": _applied(payload),
    }
