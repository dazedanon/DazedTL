"""Checked OpenRouter catalog metadata and immutable Batch execution policy.

The authenticated connection check owns account eligibility. Model selection
resolves compatible Batch endpoints; estimate preparation can resolve Live prices.
Observations only read cached metadata.
"""

import json
import math
import time
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from typing import NamedTuple, cast
from urllib.parse import quote

import httpx

from .preferences import text

TRANSPORT = "openrouter-batch-v1"
STRUCTURED_OUTPUTS = "json-schema-v1"
# Local split points, not claims about an account's provider quota. Keeping
# requests small also bounds the inline response downloaded by GET /batches/id.
MAX_REQUESTS = 1000
MAX_BYTES = 10_000_000


def rate(value):
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        return None
    try:
        amount = float(Decimal(str(value)) * 1_000_000)
    except ValueError, OverflowError, DecimalException:
        return None
    return amount if math.isfinite(amount) and 0 <= amount <= 1_000_000 else None


def catalog(rows):
    """Keep only bounded fields needed for text translation and cost review."""
    result = {}
    for row in rows:
        model = row.get("id")
        if (
            not isinstance(model, str)
            or not 0 < len(model) <= 200
            or any(ord(c) < 32 for c in model)
        ):
            continue
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        architecture = (
            row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
        )
        top = (
            row.get("top_provider") if isinstance(row.get("top_provider"), dict) else {}
        )
        parameters = (
            row.get("supported_parameters")
            if isinstance(row.get("supported_parameters"), list)
            else []
        )
        modalities = [
            architecture.get(key) for key in ("input_modalities", "output_modalities")
        ]
        result[model] = {
            "input": rate(pricing.get("prompt")),
            "output": rate(pricing.get("completion")),
            "cache_read": rate(pricing.get("input_cache_read")),
            "cache_write": rate(pricing.get("input_cache_write")),
            "text": all(
                isinstance(values, list) and "text" in values for values in modalities
            ),
            "json": "response_format" in parameters,
            "context": positive_integer(row.get("context_length")),
            "max_output": positive_integer(top.get("max_completion_tokens")),
        }
        if len(result) >= 2000:
            break
    return result


def positive_integer(value):
    return value if type(value) is int and 0 < value <= 9_007_199_254_740_991 else None


def endpoint_output_limit(rows):
    limits = [
        positive_integer(row.get("max_completion_tokens"))
        for row in rows
        if isinstance(row, dict)
    ]
    return min((limit for limit in limits if limit is not None), default=None)


def validate_catalog(value):
    if not isinstance(value, dict) or len(value) > 2000:
        raise ValueError("Invalid OpenRouter catalog.")
    for model, row in value.items():
        text(model, "model ID", required=True)
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "input",
                "output",
                "cache_read",
                "cache_write",
                "text",
                "json",
                "context",
                "max_output",
            }
            or any(type(row[key]) is not bool for key in ("text", "json"))
            or any(
                row[key] is not None and positive_integer(row[key]) is None
                for key in ("context", "max_output")
            )
            or any(
                row[key] is not None
                and (
                    type(row[key]) not in (int, float)
                    or not math.isfinite(row[key])
                    or not 0 <= row[key] <= 1_000_000
                )
                for key in ("input", "output", "cache_read", "cache_write")
            )
        ):
            raise ValueError("Invalid OpenRouter catalog entry.")


def _catalog(connection):
    """The models a verified check loaded, none before one or after a failure."""
    checked = connection.get("check", {})
    return connection.get("catalog", {}) if checked.get("status") == "verified" else {}


class Batch(NamedTuple):
    """Whether a model runs Batch on a connection (``batch``): its Batch
    rates when it does, why not when it doesn't, whether that answer was
    looked up, and whether it waits on an endpoint read for its model and
    host (settings/store.batch_lookup)."""

    supported: bool
    rates: dict
    reason: str
    looked_up: bool
    endpoints_due: bool = False


def batch(connection, model):
    """Whether ``model`` runs Batch on this connection (``Batch``). A check
    that failed or hasn't run, or an endpoint read not made for this model
    and host or that failed, leaves it not looked up, unlike a model checked
    to have no Batch."""
    known = _catalog(connection)
    row = known.get(model + ":batch", {}) if ":" not in model else {}
    if not known:
        return Batch(
            False, {}, "Check this connection to load Batch availability.", False
        )
    if ":" in model:
        return Batch(False, {}, "Choose the base model ID for Batch.", True)
    if not (row.get("text") and row.get("json")):
        return Batch(
            False,
            row,
            "This model has no compatible text Batch endpoint for this account.",
            True,
        )
    endpoints = connection.get("batch_endpoints", {})
    if (
        endpoints.get("model") != model
        or endpoints.get("host") != connection.get("openrouter_host", "")
        or "providers" not in endpoints
    ):
        return Batch(
            False,
            {},
            "Batch support has not been checked for this model and host. Save preferences to check automatically.",
            False,
            True,
        )
    if endpoints.get("error"):
        return Batch(False, {}, endpoints["error"], False, True)
    if not endpoints.get("rates") or not endpoints.get("providers"):
        return Batch(
            False,
            {},
            "No selected Batch endpoint supports this model's required structured outputs.",
            True,
        )
    return Batch(True, {**row, **endpoints["rates"]}, "", True)


def describe(connection, model):
    model = text(model, "model ID", required=True)
    checked = connection.get("check", {})
    live = _catalog(connection).get(model, {})
    available = batch(connection, model)
    host = connection.get("openrouter_host", "")
    # Model-wide prices do not establish a selected host's Live rates. The
    # public resolver supplies those separately, without inferring eligibility.
    if host:
        live = {}
    stamp = checked.get("checkedAt")
    try:
        stale = (
            not stamp
            or (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()
            > 86400
        )
    except ValueError, TypeError:
        stale = True
    return {
        "model": model,
        "inputRate": live.get("input"),
        "outputRate": live.get("output"),
        "maxOutputTokens": live.get("max_output"),
        "source": "catalog" if live else "unavailable",
        "updatedAt": stamp,
        "stale": stale,
        "batchSupported": available.supported,
        "batchReason": available.reason,
        "batchInputRate": available.rates.get("input"),
        "batchOutputRate": available.rates.get("output"),
    }


def live_prices(model, host=""):
    """Resolve public prices for an explicit lookup; no key or inference call."""
    from .providers import openrouter_host

    host = openrouter_host(host)
    model = text(model, "OpenRouter model ID", required=True)
    path = (
        "/models/" + quote(model, safe="/") + "/endpoints"
        if host
        else "/model/" + quote(model, safe="/")
    )
    try:
        started, content = time.monotonic(), bytearray()
        with (
            httpx.Client(timeout=3, follow_redirects=False) as client,
            client.stream(
                "GET",
                "https://openrouter.ai/api/v1" + path,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response,
        ):
            response.raise_for_status()
            for part in response.iter_bytes(65536):
                content.extend(part)
                if len(content) > 2_000_000 or time.monotonic() - started > 6:
                    raise ValueError(
                        "OpenRouter's price response exceeded its read limit."
                    )
        payload = json.loads(content)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("id") != model:
            raise ValueError("OpenRouter returned prices for a different model.")
        if host:
            rows = data.get("endpoints")
            if not isinstance(rows, list):
                raise ValueError("OpenRouter returned invalid host prices.")
            endpoints = [
                row
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("tag"), str)
                and (row["tag"] == host or row["tag"].startswith(host + "/"))
            ]
            prices = [row.get("pricing") for row in endpoints]
            output_limit = endpoint_output_limit(endpoints)
        else:
            prices = [data.get("pricing")]
            top = data.get("top_provider")
            output_limit = (
                positive_integer(top.get("max_completion_tokens"))
                if isinstance(top, dict)
                else None
            )
        rates = [
            {
                key: rate(row.get(field))
                for key, field in (
                    ("inputRate", "prompt"),
                    ("outputRate", "completion"),
                )
            }
            for row in prices
            if isinstance(row, dict)
        ]
        if not rates or any(value is None for row in rates for value in row.values()):
            raise ValueError(
                "No complete OpenRouter price is available for this model and host. Choose another host or enter custom Live rates."
            )
        return {
            "model": model,
            "host": host,
            **{
                # Missing rates were rejected above.
                key: max(cast(float, row[key]) for row in rates)
                for key in ("inputRate", "outputRate")
            },
            "maxOutputTokens": output_limit,
            "source": "catalog",
            "updatedAt": datetime.now(UTC).isoformat(),
            "stale": False,
        }
    except httpx.HTTPError:
        raise ValueError(
            "OpenRouter's automatic prices could not be loaded. Try again, or enter custom Live rates."
        ) from None


def _endpoint_rows(model, secret):
    from .providers import PROVIDERS

    # The preset's address, which test scenarios point at their stand-in.
    url = (
        PROVIDERS["openrouter"]["endpoint"].rstrip("/")
        + "/models/"
        + quote(model + ":batch", safe="/:")
        + "/endpoints"
    )
    with (
        httpx.Client(timeout=3, follow_redirects=False) as client,
        client.stream(
            "GET",
            url,
            headers={
                "Authorization": "Bearer " + secret,
                "Accept-Encoding": "identity",
            },
        ) as response,
    ):
        if response.status_code == 404:
            return []
        response.raise_for_status()
        started, content = time.monotonic(), bytearray()
        for part in response.iter_bytes(65536):
            content.extend(part)
            if len(content) > 2_000_000 or time.monotonic() - started > 5:
                raise ValueError(
                    "OpenRouter endpoint metadata exceeded its read limit."
                )
    payload = json.loads(content)
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("id") != model + ":batch"
        or not isinstance(data.get("endpoints"), list)
    ):
        raise ValueError("OpenRouter returned invalid Batch endpoint metadata.")
    return data["endpoints"]


def check_endpoints(connection, known):
    """Verify Batch separately; an endpoint outage cannot revoke a valid key."""
    from .providers import openrouter_host

    model, host = connection.get("model", ""), connection.get("openrouter_host", "")
    if not model or model + ":batch" not in known:
        return {}
    unavailable = {
        "model": model,
        "host": host,
        "rates": None,
        "providers": [],
        "error": "Could not verify Batch structured-output support. Check the connection again.",
    }
    try:
        rows = _endpoint_rows(model, connection["secret"])
    except httpx.HTTPError, ValueError, UnicodeError:
        return unavailable
    selected_endpoints, eligible, unsupported = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            return unavailable
        tag = row.get("tag", "")
        parameters = row.get("supported_parameters")
        if (
            isinstance(tag, str)
            and tag
            and (not host or tag == host or tag.startswith(host + "/"))
        ):
            try:
                if openrouter_host(tag) != tag:
                    return unavailable
            except ValueError:
                return unavailable
            if not isinstance(parameters, list) or not {
                "response_format",
                "structured_outputs",
            }.issubset(parameters):
                unsupported.add(tag)
                continue
            eligible.add(tag)
            selected_endpoints.append(row)
    # A base provider slug also includes its endpoint variants. Do not let a
    # supported base endpoint admit an incompatible variant through `only`.
    eligible = {
        tag
        for tag in eligible
        if not any(other == tag or other.startswith(tag + "/") for other in unsupported)
    }
    if len(eligible) > 200:
        return unavailable
    selected_endpoints = [row for row in selected_endpoints if row["tag"] in eligible]
    matches = []
    for row in selected_endpoints:
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        matches.append(
            {
                key: rate(pricing.get(field))
                for key, field in (
                    ("input", "prompt"),
                    ("output", "completion"),
                    ("cache_read", "input_cache_read"),
                    ("cache_write", "input_cache_write"),
                )
            }
        )
    # A host slug can match several endpoints. Keep conservative rates across
    # that set. Missing prices remain unknown instead of becoming zero.
    rates = (
        {
            key: max(row[key] for row in matches)
            if all(row[key] is not None for row in matches)
            else None
            for key in ("input", "output", "cache_read", "cache_write")
        }
        if matches
        else None
    )
    return {
        "model": model,
        "host": host,
        "rates": rates,
        "max_output": endpoint_output_limit(selected_endpoints),
        "providers": sorted(eligible),
    }


def validate_endpoints(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid OpenRouter endpoint metadata.")
    if not value:
        return
    from .providers import openrouter_host

    text(value.get("model"), "model ID", required=True)
    openrouter_host(value.get("host"))
    if "providers" in value:
        validate_structured_providers(value["providers"], allow_empty=True)
    if "error" in value:
        text(value["error"], "Batch endpoint feedback")
    if (
        value.get("max_output") is not None
        and positive_integer(value["max_output"]) is None
    ):
        raise ValueError("Invalid OpenRouter Batch output limit.")
    rates = value.get("rates")
    if rates is not None and (
        not isinstance(rates, dict)
        or set(rates) != {"input", "output", "cache_read", "cache_write"}
        or any(
            amount is not None
            and (
                type(amount) not in (int, float)
                or not math.isfinite(amount)
                or not 0 <= amount <= 1_000_000
            )
            for amount in rates.values()
        )
    ):
        raise ValueError("Invalid OpenRouter endpoint prices.")


class Unread(ValueError):
    """A Batch policy no lookup could read yet (``batch`` not ``looked_up``),
    as before a connection's first check, after a failed one or before its
    model's Batch endpoints are read: whether the model runs Batch, and at
    what price, is not known, which is neither no Batch nor Batch. A Batch
    run or estimate refuses it (``frozen``), so Batch work, estimates and
    approvals wait for the lookup; a Batch read with unknown prices leaves
    the policy out (settings/execution.configuration), which a saved figure
    reads as a price not known (translation/repricing.priced); and a chosen
    Batch stays Batch meanwhile (execution.batch_reasons). Live freezes it
    as not read yet (``UNREAD``) and goes ahead."""

    @classmethod
    def of(cls, available):
        """The refusal for ``available`` (``Batch``), saying what reads it."""
        return cls(
            "Batch can't be estimated or started until this connection loads "
            "whether the model runs Batch, such as after its check failed; "
            "Live works meanwhile. " + available.reason
        )


# The key Live work and estimates freeze true beside no Batch policy while
# no lookup could read the policy (``Unread``). They go ahead at their Live
# price on no Batch route, with no Batch price; once a lookup reads the
# policy, a view prices their figures' Batch on its route and keeps their
# Live price current (translation/repricing). Settings and run records saved
# before it hold a policy or none, which read as before, and every reader of
# the policy, an older release's included, reads none.
UNREAD = "openrouterBatchUnread"


def policy(connection, model, options, *, required=False):
    """The Batch policy a run or an estimate on ``model`` is sent on, None
    for a model looked up to run no Batch, which ``required`` refuses;
    raises Unread while no lookup could read it."""
    available = batch(connection, model)
    if not available.looked_up:
        raise Unread.of(available)
    if not available.supported:
        if required:
            raise ValueError(available.reason)
        return None
    row = dict(available.rates)
    if connection["batch_endpoints"].get("max_output") is not None:
        row["max_output"] = connection["batch_endpoints"]["max_output"]
    custom = options.get("batchPricing", "automatic") == "custom"
    inputs = options.get("batchInputRate") if custom else row["input"]
    outputs = options.get("batchOutputRate") if custom else row["output"]
    if inputs is None or outputs is None:
        if required:
            raise ValueError(
                "OpenRouter Batch pricing is unavailable. Enter both Batch rates in Advanced model options."
            )
        return None
    return {
        "transport": TRANSPORT,
        "model": model,
        "host": connection.get("openrouter_host", ""),
        "input": inputs,
        "output": outputs,
        "structuredOutputs": STRUCTURED_OUTPUTS,
        "providers": list(connection["batch_endpoints"]["providers"]),
        "cache_read": None if custom else row["cache_read"],
        "cache_write": None if custom else row["cache_write"],
        "source": "custom" if custom else "catalog",
        "updatedAt": connection.get("check", {}).get("checkedAt"),
        "max_requests": MAX_REQUESTS,
        "max_bytes": MAX_BYTES,
        "context": row["context"],
        "max_output": row["max_output"],
    }


def frozen(connection, model, options, *, required=False):
    """The OpenRouter Batch settings a run or an estimate on ``model``
    freezes: its ``openrouterBatch`` policy (``policy``), or while no lookup
    could read it, which ``required``, as a Batch reads it, refuses
    (Unread), none with ``UNREAD`` true beside it."""
    try:
        return {
            "openrouterBatch": policy(connection, model, options, required=required)
        }
    except Unread:
        if required:
            raise
        return {"openrouterBatch": None, UNREAD: True}


def validate_policy(value, model):
    if (
        not isinstance(value, dict)
        or value.get("transport") != TRANSPORT
        or value.get("model") != model
        or any(
            type(value.get(key)) not in (int, float)
            or not math.isfinite(value[key])
            or not 0 <= value[key] <= 1_000_000
            for key in ("input", "output")
        )
        or any(
            value.get(key) is not None
            and (
                type(value[key]) not in (int, float)
                or not math.isfinite(value[key])
                or not 0 <= value[key] <= 1_000_000
            )
            for key in ("cache_read", "cache_write")
        )
        or any(
            positive_integer(value.get(key)) is None
            for key in ("max_requests", "max_bytes")
        )
        or value["max_requests"] > MAX_REQUESTS
        or value["max_bytes"] > MAX_BYTES
    ):
        raise ValueError(
            "This run's frozen OpenRouter Batch policy is invalid or unsupported."
        )
    from .providers import openrouter_host

    openrouter_host(value.get("host", ""))
    if "structuredOutputs" in value or "providers" in value:
        if value.get("structuredOutputs") != STRUCTURED_OUTPUTS:
            raise ValueError(
                "This run's frozen OpenRouter structured-output policy is unsupported."
            )
        validate_structured_providers(value.get("providers"))
        host = value.get("host", "")
        if host and any(
            tag != host and not tag.startswith(host + "/") for tag in value["providers"]
        ):
            raise ValueError(
                "This run's structured-output endpoints differ from its selected host."
            )
    return value


def validate_structured_providers(value, *, allow_empty=False):
    from .providers import openrouter_host

    if (
        not isinstance(value, list)
        or len(value) > 200
        or not value
        and not allow_empty
        or any(
            not isinstance(tag, str) or not tag or openrouter_host(tag) != tag
            for tag in value
        )
        or len(set(value)) != len(value)
    ):
        raise ValueError("Invalid OpenRouter structured-output endpoints.")
