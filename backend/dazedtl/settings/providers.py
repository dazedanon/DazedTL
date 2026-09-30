"""Connection presets and explicit, non-generating access checks."""

from datetime import datetime, timezone
import json
import time
from urllib.parse import urlsplit

import httpx


PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "openai",
        "endpoint": "https://api.openai.com/v1",
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


def check(connection):
    """A bounded model-list request; no inference, retries, or redirects.

    https://developers.openai.com/api/reference/overview
    https://platform.claude.com/docs/en/api/models/list
    https://ai.google.dev/gemini-api/docs/openai#list-models
    https://docs.mistral.ai/api/endpoint/models
    """
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
    if connection.get("organization") and protocol == "openai":
        headers["OpenAI-Organization"] = connection["organization"]
    url = base + ("/v1/models?limit=250" if protocol == "anthropic" else "/models")

    def result(status, message, models=None):
        return {
            "check": {
                "status": status,
                "message": message,
                "checkedAt": datetime.now(timezone.utc).isoformat(),
            },
            "models": models,
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
                    if len(content) > 2_000_000 or time.monotonic() > deadline:
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
            }
        )[:250]
        official = any(
            route(protocol, base) == route(item["protocol"], item["endpoint"])
            for name, item in PROVIDERS.items()
            if name != "custom"
        )
        if official and not connection["keyless"]:
            return result(
                "verified",
                "Authentication verified. Model availability and usage limits can still vary.",
                models,
            )
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
    except httpx.TransportError:
        return result(
            "unavailable",
            "The server could not be reached securely. Check the address, network, and certificate.",
        )
    except (ValueError, UnicodeError):
        return result(
            "unsupported",
            "The key, address, or server response could not be used. Review the connection details.",
        )
