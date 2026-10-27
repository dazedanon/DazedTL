"""Small provider-specific pricing rules shared by batch workflows."""

from __future__ import annotations

import re


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


def cache_read_multiplier(provider: str, model: str) -> float:
    """Return cache-read price as a multiple of regular input pricing.

    Anthropic reads cost 0.05 times regular input on Claude Opus 5.5 and
    Sonnet 5.5 and 0.025 times on Claude Fable 5.1 and Mythos 5.1. Kimi
    reads cost $0.16 of K2.6's $0.95 and $0.19 of K2.7 Code's $0.95
    (https://platform.kimi.ai/docs/pricing/chat). Every other route here,
    Kimi K3 included, prices them at 0.1 times.
    """
    normalized_provider = str(provider or "").strip().lower()
    name = str(model or "").lower()
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
