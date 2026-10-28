"""Small provider-specific pricing rules shared by batch workflows."""

from __future__ import annotations

import re
from datetime import UTC, datetime

# The version of the rules that price counted tokens: a Batch discount, a
# cache read or write multiple, the Live formula. Raise it with any change
# that prices the same counts differently. Every quote and estimate saved for
# later display or approval records the version it was priced under, and one
# priced under another version is priced again from its counts on its next
# view, or reads outdated when its counts can't be (translation/repricing).
# A change to what is counted, such as the output allowance, changes the
# counts themselves and raises the counting kind's own version instead.
# 1: every figure saved before figures recorded it. 2: OpenAI's per-model
# cache prices (2.48.0) and every rule before them.
PRICE_RULES_VERSION = 2


def received_at(created=None) -> str:
    """The UTC time a response arrived, as its usage records it: the
    provider's ``created`` Unix time when it gives one, else now."""
    if type(created) in (int, float) and created > 0:
        try:
            return datetime.fromtimestamp(created, UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return datetime.now(UTC).isoformat()


def time_priced_route(endpoint: str | None) -> str | None:
    """The route at ``endpoint`` whose Live price depends on when each
    response arrived, DeepSeek's own API, or None; see time_price_factor."""
    from dazedtl.settings.providers import own_api

    return "deepseek" if own_api("deepseek", endpoint) else None


def time_price_factor(route: str | None, received: str | None) -> float:
    """Usage's price at the time it arrived as a multiple of the list price,
    on a ``route`` from time_priced_route.

    DeepSeek's own API bills half outside its peak hours, 01:00-04:00 and
    06:00-10:00 UTC Monday to Friday
    (https://api-docs.deepseek.com/quick_start/pricing). Its Chinese public
    holidays are off-peak too but count as peak here, which errs high, as
    does usage recorded without a time, such as rows saved before times were.
    Every other route bills the same at any hour.
    """
    if route != "deepseek" or not isinstance(received, str):
        return 1.0
    try:
        when = datetime.fromisoformat(received)
    except ValueError:
        return 1.0
    if when.tzinfo is None:
        return 1.0
    when = when.astimezone(UTC)
    peak = when.weekday() < 5 and (1 <= when.hour < 4 or 6 <= when.hour < 10)
    return 1.0 if peak else 0.5


def joined_received_at(route: str | None, *times: str | None) -> str | None:
    """The time usage adding up several responses, such as a refused request
    and its clarification, is priced at: the last response's when they all
    arrived at the same price, otherwise none, which reads as peak."""
    if len({time_price_factor(route, when) for when in times}) != 1:
        return None
    return times[-1]


# An OpenAI model by its name, on OpenAI's API or any other host, with or
# without a host's "openai/" prefix: GPT models and the o-series reasoning
# models. The open-weight gpt-oss models are not OpenAI's to price.
_OPENAI_MODEL = re.compile(r"(?:^|/)(?:gpt-\d|chatgpt-|o\d(?:[-:]|$))")


def is_openai_model(model: str) -> bool:
    """Whether ``model`` names an OpenAI model, priced at OpenAI's cache
    prices wherever it runs (batch_providers.live_price_route)."""
    return bool(_OPENAI_MODEL.search(str(model or "").lower()))


def _openai_model_at_least(model: str, major: int, minor: int) -> bool:
    match = re.search(
        r"(?:^|/)gpt-(\d+)\.(\d+)(?:\D|$)",
        str(model or "").lower(),
    )
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (major, minor)


def cache_write_multiplier(provider: str, model: str,
                           cache_ttl: str = "1h") -> float:
    """Return cache-write price as a multiple of regular input pricing.

    Anthropic five-minute writes cost 1.25 times regular input, while one-hour
    writes cost twice regular input. OpenAI introduced separately billed cache
    writes for GPT-5.6 and later model families at 1.25 times regular input.
    """
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "anthropic":
        return 1.25 if str(cache_ttl).strip().lower() == "5m" else 2.0
    if normalized_provider == "openai" and _openai_model_at_least(model, 5, 6):
        return 1.25
    return 1.0


def batch_write_weight(provider: str, model: str, writes: float,
                       one_hour: float | None = None) -> float:
    """Return Batch cache writes as regular-input tokens.

    ``one_hour`` is how many of the writes used the one-hour cache, which
    Anthropic reports beside the total; the rest used the five-minute cache.
    Without it every write counts as one-hour, the only cache Claude Batches
    asked for before they moved to the five-minute one.
    """
    one_hour = writes if one_hour is None else min(writes, one_hour)
    return (
        one_hour * cache_write_multiplier(provider, model, "1h")
        + (writes - one_hour) * cache_write_multiplier(provider, model, "5m")
    )


# OpenAI's cached input as a multiple of standard input for the families
# that don't read at 0.1 times, the default
# (https://developers.openai.com/api/docs/pricing): GPT-4o, GPT-4o mini, o1
# and o3-mini at half, GPT-4.1, o3 and o4-mini at a quarter, GPT-6.1 Sol and
# Terra at a twentieth. Searched in order, so o3-mini is found before o3; an
# OpenRouter variant such as ":nitro" reads as its model.
_OPENAI_CACHE_READS = (
    (re.compile(r"(?:^|/)(?:gpt-4o|o1|o3-mini)(?:[-:]|$)"), 0.50),
    (re.compile(r"(?:^|/)(?:gpt-4\.1|o3|o4-mini)(?:[-:]|$)"), 0.25),
    (re.compile(r"(?:^|/)gpt-6\.1-(?:sol|terra)(?:[-:]|$)"), 0.05),
)


def cache_read_multiplier(provider: str, model: str) -> float:
    """Return cache-read price as a multiple of regular input pricing.

    Anthropic reads cost 0.05 times regular input on Claude Opus 5.5 and
    Sonnet 5.5 and 0.025 times on Claude Fable 5.1 and Mythos 5.1. Several
    OpenAI families read at their own multiple (_OPENAI_CACHE_READS). Kimi
    reads cost $0.16 of K2.6's $0.95 and $0.19 of K2.7 Code's $0.95
    (https://platform.kimi.ai/docs/pricing/chat). DeepSeek reads cost $0.006
    of Flash's $0.30 and $0.044 of V4 Pro's $1.32, off-peak too
    (https://api-docs.deepseek.com/quick_start/pricing). Every other route
    here, Kimi K3 and the other OpenAI models included, prices them at 0.1
    times.
    """
    normalized_provider = str(provider or "").strip().lower()
    name = str(model or "").lower()
    if normalized_provider == "openai":
        for family, multiplier in _OPENAI_CACHE_READS:
            if family.search(name):
                return multiplier
    if normalized_provider == "anthropic":
        if re.search(r"claude-(?:fable|mythos)-5-1(?:\D|$)", name):
            return 0.025
        if re.search(r"claude-(?:opus|sonnet)-5-5(?:\D|$)", name):
            return 0.05
    if normalized_provider == "kimi":
        if "kimi-k2.7-code" in name:
            return 0.20
        if "kimi-k2.6" in name:
            return 0.16 / 0.95
    if normalized_provider == "deepseek":
        if "deepseek-v4-pro" in name:
            return 0.044 / 1.32
        if "flash" in name:
            return 0.006 / 0.30
    return 0.10


def batch_price_factor(provider: str | None) -> float:
    """Return a Batch's price as a multiple of the same Live usage.

    Kimi's Batch API saves 40% (https://platform.kimi.ai/docs/guide/use-batch-api);
    every other Batch provider here halves the price.
    """
    return 0.60 if str(provider or "").strip().lower() == "kimi" else 0.50


def has_billed_cache_writes(provider: str, model: str) -> bool:
    """Return whether cache writes have a distinct price for this route."""
    return cache_write_multiplier(provider, model) != 1.0


def uncached_usage(counts: dict) -> dict:
    """A response's counts, whose ``prompt_tokens`` includes its cache reads
    and writes (batch_providers.openai_usage), as usage_cost reads them."""
    def count(key: str) -> int:
        value = counts.get(key, 0)
        return value if type(value) is int and value >= 0 else 0

    reads, writes = (
        count("cache_read_input_tokens"),
        count("cache_creation_input_tokens"),
    )
    return {
        "input_tokens": max(0, count("prompt_tokens") - reads - writes),
        "output_tokens": count("completion_tokens"),
        "cache_read_input_tokens": reads,
        "cache_creation_input_tokens": writes,
        "thinking_tokens": count("thinking_tokens"),
    }


def usage_cost(usage: dict, provider: str, model: str, input_rate: float,
               output_rate: float, factor: float = 1.0) -> float:
    """Price billed usage at per-token rates with the route's cache
    multipliers, then ``factor``: the Batch discount, or 1 for Live.

    ``usage`` holds uncached ``input_tokens``, ``output_tokens``, cache reads
    and writes as Anthropic names them, and ``thinking_tokens`` billed as
    output; see batch_write_weight for the one-hour writes beside them.
    """
    def count(key: str) -> float:
        return usage.get(key, 0) or 0

    raw = (
        count("cache_read_input_tokens") * input_rate
        * cache_read_multiplier(provider, model)
        + batch_write_weight(
            provider, model, count("cache_creation_input_tokens"),
            usage.get("cache_creation_1h_input_tokens"),
        ) * input_rate
        + count("input_tokens") * input_rate
        + (count("output_tokens") + count("thinking_tokens")) * output_rate
    )
    return raw * factor
