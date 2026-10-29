"""Small provider-specific pricing rules shared by batch workflows."""

from __future__ import annotations

import re
from datetime import UTC, datetime

# The version of the rules that price a quote's or estimate's counted tokens:
# a Batch discount, a Batch's cache read or write multiple, the Live formula.
# Every quote and estimate saved for later display or approval records the
# version it was priced under (PRICE_RULES_VERSION). One priced under an
# older version than the one its route's rules last changed at
# (ROUTE_PRICE_RULES) is priced again from its counts on its next view, or
# reads outdated when its counts can't be (translation/repricing); one on a
# route a fix left alone stands.
# A figure's route is the Batch provider that priced it, by the one rule its
# worker and the views read it by (compatibility/openrouter_batch
# batch_route), "openrouter" for an OpenRouter Batch and None for settings
# without one. Its routes are Batch providers alone: a figure's Live price
# is its counts at its rates, which no route's rules touch, and every rule
# that prices its cache or discount follows its Batch provider. A fix to a
# Live price, such as a Live response's cache prices on its Live price route
# (batch_providers.live_price_route), changes no saved figure, only what a
# run's usage costs, so it names no route here.
# A change that prices the same counts differently takes the next version,
# setting each route it changes to it here, or EVERY_ROUTE_PRICE_RULES when
# it changes them all; PRICE_RULES_VERSION is the newest.
# A change to what is counted, such as the output allowance, changes the
# counts themselves and raises the counting kind's own version instead.
# 1: every figure saved before figures recorded it. 2: OpenAI's per-model
# cache prices (2.48.0) and every rule before them, on every route. 3, OpenAI:
# no cache reads in an OpenAI Batch on the models whose Batch doesn't cache
# (openai_batch_caches). 4, OpenAI: an OpenAI Batch that writes the cache but
# expects no reads shows its price with those writes
# (translation.openai_cache_prices). 5: no route's. A fix to Claude's Live
# cache reads in any host's form of its name (cache_read_multiplier) first
# named the route without a Batch, though it changed no saved figure's price;
# figures priced since record it, so the next fix takes 6.
EVERY_ROUTE_PRICE_RULES = 2
ROUTE_PRICE_RULES = {"openai": 4}
PRICE_RULES_VERSION = max(5, EVERY_ROUTE_PRICE_RULES, *ROUTE_PRICE_RULES.values())


def route_price_rules(route: str | None) -> int:
    """The price rules version at which ``route``'s rules last changed: a
    figure priced on it under that version or a later one is current."""
    return max(EVERY_ROUTE_PRICE_RULES, ROUTE_PRICE_RULES.get(route or None, 0))


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


# A Claude model by its name, on Anthropic's API or any other host: a name
# starting "claude-", in any dated or versioned form, alone or as another host
# names it: OpenRouter's "anthropic/" (or "~anthropic/" for its latest
# aliases), Bedrock's "anthropic." with or without a region, also inside an
# ARN, Vertex AI's "publishers/anthropic/models/" and LiteLLM's "vertex_ai/",
# behind a gateway's own prefix such as "bedrock/", or a Databricks
# endpoint's "databricks-", alone or behind LiteLLM's "databricks/". Another
# model's name holding a Claude family word, such as "magnum-opus-72b", or
# another owner's "claude-" model, such as "someone/claude-style-7b", is not
# Claude's.
_CLAUDE_MODEL = re.compile(
    r"(?:(?:[\w.:~-]+/)*(?:~?(?:[a-z-]+\.)?anthropic[./](?:models/)?|vertex_ai(?:_beta)?/)"
    r"|(?:databricks/)?databricks-)?"
    r"(claude-[a-z0-9].*)",
    re.DOTALL,
)


def claude_model_name(model: str) -> str | None:
    """The Claude name in ``model``, from "claude-" on in lower case, such as
    "claude-opus-5.5" in "anthropic/claude-opus-5.5"; None when ``model``
    names no Claude model."""
    match = _CLAUDE_MODEL.fullmatch(str(model or "").strip().lower())
    return match.group(1) if match else None


def claude_version_name(model: str) -> str | None:
    """The Claude name in ``model`` (claude_model_name) with its version
    written as Anthropic writes it, hyphens between the numbers, so
    OpenRouter's "anthropic/claude-opus-4.5" reads "claude-opus-4-5": the
    name a Claude model's per-token rates are found by."""
    name = claude_model_name(model)
    return None if name is None else re.sub(r"(?<=\d)\.(?=\d)", "-", name)


def is_claude_model(model: str) -> bool:
    """Whether ``model`` names a Claude model, priced at Anthropic's cache
    prices wherever it runs (batch_providers.live_price_route)."""
    return claude_model_name(model) is not None


def is_claude_native(model: str, address: str | None) -> bool:
    """Whether a Live request for ``model`` to ``address`` goes through
    Anthropic's own SDK: a Claude model with no address set, or one holding
    "anthropic", such as a proxy path. Any other address, OpenRouter's or a
    Custom host's, takes the OpenAI-compatible path even for Claude models.
    Batches need Anthropic's own API (batch_providers.detect_batch_provider)."""
    address = str(address or "").strip().lower()
    return is_claude_model(model) and (not address or "anthropic" in address)


def on_anthropic_api(address: str | None) -> bool:
    """Whether a native Claude request to ``address`` reaches Anthropic's own
    API: no address set, or one at its host (settings/providers own_api). A
    proxy path holding "anthropic", or another host whose name holds it, is
    sent Live natively but is not Anthropic's API."""
    from dazedtl.settings.providers import own_api

    return not str(address or "").strip() or own_api("anthropic", address)


def foreign_claude_name(model: str, address: str | None) -> bool:
    """Whether ``model`` names Claude other than by its own ID for a request
    to Anthropic's own API, which takes only Claude's own IDs ("claude-...",
    in lower case as its model list writes them) and answers any other name
    with not found: another host's form, such as OpenRouter's
    "anthropic/claude-opus-5.5" or Bedrock's "us.anthropic.claude-...", or
    the ID in capitals, such as "Claude-Opus-5". Settings refuses it before
    any request is sent (settings/providers validate_model_name)."""
    name = claude_model_name(model)
    return (
        name is not None
        and on_anthropic_api(address)
        and name != str(model).strip()
    )


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


# The OpenAI models whose Batch reads nothing from the prompt cache: OpenAI's
# pricing page (https://developers.openai.com/api/docs/pricing, read
# 2026-10-28) lists no Batch cached-input price ("-") for every model before
# GPT-5 (GPT-4.1, 4.1 mini and nano, GPT-4o, 4o mini and 2024-05-13, o1,
# o1-pro, o3, o3-pro, o3-mini, o4-mini, GPT-4 Turbo, GPT-4 and GPT-3.5 Turbo)
# and for the GPT-5 "-pro" models, which have no prompt cache at all. A probe
# Batch of 200 gpt-4.1-mini requests sharing a 4,818-token prefix reported
# no cached tokens on any. Every other model lists half its Live cached price.
_OPENAI_BATCH_NO_CACHE = re.compile(
    r"(?:^|/)(?:gpt-3\.5|gpt-4(?:o|\.\d+)?|o\d|gpt-\d+(?:\.\d+)?-pro)(?:[-:]|$)"
)


def openai_batch_caches(model: str) -> bool:
    """Whether an OpenAI Batch on ``model`` reads its shared prompts from the
    cache, as the same requests sent Live do; see _OPENAI_BATCH_NO_CACHE."""
    return not _OPENAI_BATCH_NO_CACHE.search(str(model or "").lower())


def cache_read_multiplier(provider: str, model: str) -> float:
    """Return cache-read price as a multiple of regular input pricing.

    Anthropic reads cost 0.05 times regular input on Claude Opus 5.5 and
    Sonnet 5.5 and 0.025 times on Claude Fable 5.1 and Mythos 5.1, in any
    host's form of their names (claude_version_name). Several
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
        claude = claude_version_name(model) or ""
        if re.match(r"claude-(?:fable|mythos)-5-1(?:\D|$)", claude):
            return 0.025
        if re.match(r"claude-(?:opus|sonnet)-5-5(?:\D|$)", claude):
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


def shown_batch_price(estimate: dict) -> str:
    """Which of a Batch estimate's prices it shows as its Batch cost: the
    cached price when it expects the prompt cache (``uses_prompt_cache``),
    else the price without one."""
    return (
        "batch_cached_cost"
        if estimate.get("uses_prompt_cache")
        else "batch_nocache_cost"
    )


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
