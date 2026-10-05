"""Resolve existing model rates in an isolated process without credentials."""

import json
import math
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


def catalog(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid pricing catalog.")
    keys = ("input_cost_per_token", "output_cost_per_token")
    return {
        name: {
            **{key: row[key] for key in keys},
            "max_output_tokens": output_limit(row.get("max_output_tokens")),
        }
        for name, row in value.items()
        if isinstance(name, str)
        and isinstance(row, dict)
        and all(
            type(row.get(key)) in (int, float)
            and math.isfinite(row[key])
            and 0 <= row[key] <= 1
            for key in keys
        )
    }


def output_limit(value):
    return value if type(value) is int and 0 < value <= 9_007_199_254_740_991 else None


def model_output_limit(prices, model):
    # Limits must come from this model, not the native price resolver's fuzzy
    # prefix fallback, which can price an alias using a different model family.
    name = str(model).strip().lower().removeprefix("models/")
    row = prices.get(name) or prices.get(name.rsplit("/", 1)[-1]) or {}
    return output_limit(row.get("max_output_tokens"))


def resolve(cache, model, online):
    from dazedtl.compatibility.runtime import activate

    activate()
    import util.translation as translation
    import httpx

    cache = Path(cache)
    cached = None
    if (
        cache.is_file()
        and not cache.is_symlink()
        and cache.stat().st_size <= 24_000_000
    ):
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if (
                type(cached.get("fetched_at")) not in (float, int)
                or not math.isfinite(cached["fetched_at"])
                or not 0 <= cached["fetched_at"] <= time.time() + 60
            ):
                cached = None
            else:
                cached["prices"] = catalog(cached.get("prices"))
        except (ValueError, OSError, AttributeError):
            cached = None
    now = time.time()
    if online and (
        cached is None
        or cached.get("version") != 2
        or now - cached["fetched_at"] > 86400
    ):
        try:
            started, data = time.monotonic(), bytearray()
            with httpx.Client(
                timeout=4, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream(
                    "GET",
                    translation._LITELLM_PRICING_URL,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_raw(65536):
                        data.extend(chunk)
                        if len(data) > 20_000_000 or time.monotonic() - started > 6:
                            raise ValueError("Pricing catalog exceeds its read limit.")
            prices = catalog(json.loads(data))
            cached = {"version": 2, "fetched_at": now, "prices": prices}
            from dazedtl.storage import write_json

            write_json(cache, cached)
        except (httpx.HTTPError, ValueError, OSError):
            pass
    translation._load_litellm_pricing = lambda: cached["prices"] if cached else None
    catalog_rate = translation._lookup_model_price(model)
    config = translation.getPricingConfig(model)
    valid_rates = all(
        type(config[key]) in (int, float)
        and math.isfinite(config[key])
        and config[key] >= 0
        for key in ("inputAPICost", "outputAPICost")
    )
    origin = (
        "catalog"
        if catalog_rate
        else "engine_default"
        if valid_rates
        else "unavailable"
    )
    return {
        "model": model,
        "inputRate": config["inputAPICost"] if valid_rates else None,
        "outputRate": config["outputAPICost"] if valid_rates else None,
        "maxOutputTokens": model_output_limit(cached["prices"], model)
        if cached
        else None,
        "source": origin,
        "updatedAt": datetime.fromtimestamp(
            cached["fetched_at"], timezone.utc
        ).isoformat()
        if catalog_rate
        else None,
        "stale": bool(
            catalog_rate
            and (cached.get("version") != 2 or now - cached["fetched_at"] > 86400)
        ),
    }


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    request = json.load(sys.stdin)
    # Imports and existing engine messages cannot pollute the response protocol.
    with redirect_stdout(sys.stderr):
        result = resolve(Path(sys.argv[1]), request["model"], request["online"])
    print(json.dumps(result, allow_nan=False))
