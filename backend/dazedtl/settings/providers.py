"""Connection presets and explicit, non-generating access checks."""

from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import quote, urlsplit

import httpx


PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "openai",
        "endpoint": "https://api.openai.com/v1",
    },
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "openai",
        "endpoint": "https://openrouter.ai/api/v1",
    },
    "anthropic": {
        "label": "Anthropic",
        "protocol": "anthropic",
        "endpoint": "https://api.anthropic.com",
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
            url.port
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
    if value and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*", value):
        raise ValueError("Choose a valid OpenRouter host.")
    return value


def openrouter_hosts(model=""):
    """Read model-specific hosts (or the legacy public catalog), without credentials."""
    if (not isinstance(model, str) or len(model) > 200
            or model and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*", model)):
        raise ValueError("Choose a valid OpenRouter model in Preferences before loading its hosts.")
    path = "/models/" + quote(model, safe="/") + "/endpoints" if model else "/providers"
    try:
        deadline = time.monotonic() + 8
        with httpx.Client(timeout=httpx.Timeout(3, connect=3), follow_redirects=False) as client:
            with client.stream("GET", PROVIDERS["openrouter"]["endpoint"] + path,
                               headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_raw(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > 1_000_000 or time.monotonic() > deadline:
                        raise ValueError("OpenRouter's host list was too large or took too long. Try again.")
        data = json.loads(content).get("data")
        if model and (not isinstance(data, dict) or data.get("id") != model):
            raise ValueError
        rows = data.get("endpoints") if model else data
        if not isinstance(rows, list) or len(rows) > 512:
            raise ValueError
        hosts = {}
        for row in rows:
            slug = openrouter_host(row["tag"].split("/")[0] if model else row["slug"])
            name = row["provider_name"] if model else row["name"]
            if not slug or not isinstance(name, str) or not 0 < len(name.strip()) <= 200 or any(ord(char) < 32 for char in name):
                raise ValueError
            hosts[slug] = {"slug": slug, "name": name.strip()}
        return sorted(hosts.values(), key=lambda host: (host["name"].casefold(), host["slug"]))
    except httpx.HTTPError:
        raise ValueError("OpenRouter's host list could not be loaded. Check your connection and try again.") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("OpenRouter returned an unavailable or invalid host list. Try again later.") from None


def check(connection):
    """A bounded model-list request; no inference, retries, or redirects.

    https://developers.openai.com/api/reference/overview
    https://platform.claude.com/docs/en/api/models/list
    https://ai.google.dev/gemini-api/docs/openai#list-models
    https://docs.mistral.ai/api/endpoint/models
    https://openrouter.ai/docs/api/api-reference/models/list-models-filtered-by-user-provider-preferences-privacy-settings-and-guardrails
    """
    protocol = connection["protocol"]
    base = route(protocol, address(connection))[1]
    openrouter = infer_provider(protocol, base) == "openrouter"
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if not connection["keyless"]:
        if protocol == "anthropic":
            headers.update(
                {"x-api-key": connection["secret"], "anthropic-version": "2023-06-01"}
            )
        else:
            headers["Authorization"] = "Bearer " + connection["secret"]
    if connection.get("organization") and protocol == "openai" and not openrouter:
        headers["OpenAI-Organization"] = connection["organization"]
    # OpenRouter's public catalog cannot verify a key. Its account-filtered
    # list requires authentication and defaults to text-output models.
    url = base + ("/models/user" if openrouter else
                  "/v1/models?limit=250" if protocol == "anthropic" else "/models")
    byte_limit = 8_000_000 if openrouter else 2_000_000
    model_limit = 2000 if openrouter else 250

    def result(status, message, models=None, catalog=None):
        return {
            "check": {
                "status": status,
                "message": message,
                "checkedAt": datetime.now(timezone.utc).isoformat(),
            },
            "models": models,
            **({"catalog": catalog} if catalog is not None else {}),
        }

    try:
        deadline = time.monotonic() + 8
        with httpx.Client(
            timeout=httpx.Timeout(3, connect=3), follow_redirects=False
        ) as client:
            with client.stream("GET", url, headers=headers) as response:
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
        return result(
            "unavailable",
            "The server could not be reached securely. Check the address, network, and certificate.",
        )
    except (ValueError, UnicodeError):
        return result(
            "unsupported",
            "The key, address, or server response could not be used. Review the connection details.",
        )
