"""The model catalog of OpenCode's routes (settings/providers OPENCODE), as
their connection check keeps it, and the Live rates a model on them is
estimated and frozen at.

Each route's model list (GET /inference/go/v1/models for Go and
/inference/v1/models for pay-as-you-go, settings/providers check) prices
each model in USD per million tokens, the listed price, with any
multipliers on top: on Go, DeepSeek's models cost twice their listed price
in DeepSeek's peak hours, as on DeepSeek's own API, and a model may cost
more from a date on. Go bills a subscription's usage at these prices against
its allowance (https://opencode.ai/v2/docs/console/go/), and pay-as-you-go
bills the Console balance at its own, which carry no multipliers. The list
says which thinking efforts each model takes too, which settings/effort
reads from it.
"""

import math
from datetime import UTC, datetime, timedelta

from .catalogs import amount, checked, described, positive_integer
from .preferences import text

# The connection check keeps at most this many models of a list.
MAX_MODELS = 250
# A model keeps at most this many date multipliers.
MAX_DATED = 8
_KEYS = {
    "input",
    "output",
    "cache_read",
    "context",
    "max_output",
    "json",
    "peak",
    "dated",
}


def _factor(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and 0 < value <= 100
        else None
    )


def _day(value):
    """An ISO date such as "2026-12-01", or None for anything else."""
    try:
        return value if len(value) == 10 and datetime.fromisoformat(value) else None
    except TypeError, ValueError:
        return None


def _window(when):
    """The days a date multiplier's condition *when* holds, as (from, until),
    from inclusive and until exclusive, either None when open; None when the
    condition is not dates alone."""
    if not isinstance(when, dict) or set(when) != {"date"}:
        return None
    bounds = when["date"]
    if (
        not isinstance(bounds, dict)
        or not bounds
        or not set(bounds) <= {"gte", "gt", "lt", "lte"}
        or any(_day(value) is None for value in bounds.values())
    ):
        return None

    def after(day):
        return (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()

    start = bounds.get("gte") or (after(bounds["gt"]) if "gt" in bounds else None)
    end = bounds.get("lt") or (after(bounds["lte"]) if "lte" in bounds else None)
    return start, end


def _multipliers(cost):
    """The multipliers DazedTL prices a model with: the factor its price may
    take at any hour, its peak (None when none raises it), and the date
    multipliers. An hour-of-day multiplier, such as DeepSeek's peak hours,
    counts at its peak, and so does one whose condition DazedTL doesn't read,
    so estimates err high; one that lowers the price counts only by date.
    Several such multipliers count at the largest, since a condition split
    into several entries, such as one per peak window, would otherwise count
    more than once."""
    peak, dated = None, []
    items = cost.get("multipliers")
    for item in items if isinstance(items, list) else ():
        factor = _factor(item.get("factor")) if isinstance(item, dict) else None
        if factor is None:
            continue
        window = _window(item.get("when"))
        if window is not None:
            if len(dated) < MAX_DATED:
                dated.append({"from": window[0], "until": window[1], "factor": factor})
        elif factor > 1:
            peak = max(peak or 1, factor)
    return peak, dated


def _object(value, key):
    item = value.get(key) if isinstance(value, dict) else None
    return item if isinstance(item, dict) else {}


def paid(rows):
    """*rows* without the free models, whose input and output both list at
    no cost, such as "deepseek-v4.1-flash-free": OpenCode serves them only
    to its own app and answers any other client with HTTP 429
    (FreeUsageLimitError, retry after hours), so a Guided run would retry
    each file in vain. They are left out of the check's models and catalog;
    a free model's ID typed in Preferences is still sent."""

    def price(row, kind):
        cost = _object(_object(_object(row, "cost"), "text"), kind)
        return amount(cost.get("price"))

    return [row for row in rows if not price(row, "input") == price(row, "output") == 0]


def catalog(rows):
    """{model ID: what DazedTL keeps of its row}, bounded: its listed input,
    output and cache read prices, its context and output limits, whether it
    takes structured outputs, and its price multipliers (_multipliers).
    Context-length price overrides apply only far above a translation
    request's size, so they are left out."""
    result = {}
    for row in rows:
        model = row.get("id")
        if (
            not isinstance(model, str)
            or not 0 < len(model) <= 200
            or any(ord(c) < 32 for c in model)
        ):
            continue
        cost = _object(row, "cost")
        prices = _object(cost, "text")
        inputs = _object(prices, "input")
        limit = _object(row, "limit")
        peak, dated = _multipliers(cost)
        result[model] = {
            "input": amount(inputs.get("price")),
            "output": amount(_object(prices, "output").get("price")),
            "cache_read": amount(_object(inputs, "cache").get("read")),
            "context": positive_integer(limit.get("context")),
            "max_output": positive_integer(limit.get("output")),
            "json": _object(row, "capabilities").get("structured_output") is True,
            "peak": peak,
            "dated": dated,
        }
        if len(result) >= MAX_MODELS:
            break
    return result


def validate_catalog(value):
    if not isinstance(value, dict) or len(value) > MAX_MODELS:
        raise ValueError("Invalid OpenCode catalog.")
    for model, row in value.items():
        text(model, "model ID", required=True)
        if (
            not isinstance(row, dict)
            or set(row) != _KEYS
            or type(row["json"]) is not bool
            or any(
                row[key] is not None and positive_integer(row[key]) is None
                for key in ("context", "max_output")
            )
            or any(
                row[key] is not None and amount(row[key]) is None
                for key in ("input", "output", "cache_read")
            )
            or row["peak"] is not None
            and (_factor(row["peak"]) is None or row["peak"] <= 1)
            or not isinstance(row["dated"], list)
            or len(row["dated"]) > MAX_DATED
            or any(
                not isinstance(item, dict)
                or set(item) != {"from", "until", "factor"}
                or _factor(item["factor"]) is None
                or any(
                    item[key] is not None and _day(item[key]) is None
                    for key in ("from", "until")
                )
                for item in row["dated"]
            )
        ):
            raise ValueError("Invalid OpenCode catalog entry.")


def factor(row, now=None, peak=None):
    """What *row*'s listed prices are multiplied by for an estimate made
    *now*: *peak*, or else its own (_multipliers), and each date multiplier
    in effect on that day."""
    today = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
    value = peak or row["peak"] or 1
    for item in row["dated"]:
        if (item["from"] is None or item["from"] <= today) and (
            item["until"] is None or today < item["until"]
        ):
            value *= item["factor"]
    return value


def describe(connection, model, now=None):
    """*model*'s Live defaults on a connection to one of OpenCode's routes,
    from the catalog its last verified check kept (settings/catalogs): its
    listed rates times factor. A model billed as on DeepSeek's own API, a
    DeepSeek model on Go (providers deepseek_route), takes DeepSeek's peak
    factor, not its row's, since its
    usage records at DeepSeek's off-peak multiple of the frozen rate outside
    DeepSeek's peak hours (engine provider_costs time_price_factor)."""
    from util.provider_costs import DEEPSEEK_OFF_PEAK

    from .providers import address, deepseek_route

    model = text(model, "model ID", required=True)
    row = checked(connection).get(model)
    if not row:
        return described(connection, model, {})
    deepseek = deepseek_route(model, address(connection))
    multiple = factor(row, now, 1 / DEEPSEEK_OFF_PEAK if deepseek else None)
    return described(
        connection,
        model,
        {
            "input": None if row["input"] is None else row["input"] * multiple,
            "output": None if row["output"] is None else row["output"] * multiple,
            "max_output": row["max_output"],
        },
    )


def cache_read_multiple(connection, model):
    """What a Live cache read of *model* on *connection* costs as a multiple
    of its input price, on one of OpenCode's routes: its catalog row's cache
    read price over its input price (catalog). Each route lists it per model,
    from 0.02 for DeepSeek V4.1 Flash to 1 for GPT-5.5 Pro, where the
    engine's rules by provider (provider_costs cache_read_multiplier) would
    read most at 0.1. None off OpenCode's routes, for a model the catalog
    doesn't price, and for a model billed as on DeepSeek's own API, a
    DeepSeek model on Go (providers deepseek_route), which reads at
    DeepSeek's own cache prices. Each run freezes it beside its rates
    (settings/execution), and both methods' recorded spend reads it
    (provider_costs usage_cost)."""
    from .providers import OPENCODE, address, deepseek_route

    if connection.get("provider") not in OPENCODE or deepseek_route(
        model, address(connection)
    ):
        return None
    row = checked(connection).get(model) or {}
    if not row.get("input") or row.get("cache_read") is None:
        return None
    return row["cache_read"] / row["input"]
