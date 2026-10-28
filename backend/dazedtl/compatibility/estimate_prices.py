"""What counted tokens cost, for Guided and Assistant-led alike.

A Guided estimate's worker counts its requests once and prices them with the
engine's estimateBatchCost and DazedTL's pricing layers. ``prices`` applies
the same formulas to counts at the model and rates of a configuration: the
engine's Claude and OpenAI cache prices and OpenRouter's own Batch rates.
Guided prices an estimate again with it after a
model switch that keeps the text of every request (translation/repricing),
and every Assistant-led quote is priced with it (translation/requests), so
both methods quote the same work alike. ``usage_cost`` prices what a run
recorded as Guided's receipts do, a Live run's requests at the price of the
time each arrived. Estimates stay at the standard price.
"""

from .openrouter_pricing import batch_cost


def output_tokens(source_tokens):
    """The output an estimate allows a request whose source text counts
    ``source_tokens``."""
    from util.translation import output_allowance

    return output_allowance(source_tokens)


def prices(counts, configuration, provider, cache=None):
    """What ``counts`` cost at the model and rates of ``configuration``, Live
    and as a Batch of ``provider``, the engine's Batch provider name.

    ``counts`` holds ``input_tokens`` and ``output_tokens``; an OpenAI Batch
    also needs ``cache_read_tokens`` and ``cacheable_tokens``, as
    estimateBatchCost counts them. ``cache`` is what Claude's cached
    instructions cost (util/claude_tokens.Cache). A cached Batch is a range,
    from ``batch_cached_cost`` with every expected cache hit to
    ``batch_max_cost`` with none; ``batch_cost`` is the price a Translate
    estimate shows.
    """
    from util.provider_costs import PRICE_RULES_VERSION, batch_price_factor
    from util.translation import claude_cache_prices, openai_cache_prices

    from dazedtl.settings.effort import summary, thinks

    model = configuration["model"]
    inputs, outputs = counts["input_tokens"], counts["output_tokens"]
    rates = configuration["rates"]
    in_rate, out_rate = rates["input"] / 1_000_000, rates["output"] / 1_000_000
    # As estimateCostComparison prices it, so the figures match to the cent.
    live = (inputs * rates["input"] + outputs * rates["output"]) / 1_000_000
    router = configuration.get("openrouterBatch") if provider == "openrouter" else None
    nocache = (
        batch_cost(router, inputs, outputs)
        if router
        else live * batch_price_factor(provider)
    )
    value = {
        "model": model,
        "provider": provider,
        # The rules these prices follow (translation/repricing).
        "price_rules": PRICE_RULES_VERSION,
        "live_cost": live,
        "batch_nocache_cost": nocache,
        "batch_cached_cost": nocache,
        "batch_max_cost": nocache,
        "uses_prompt_cache": False,
        # Which cache the cached price expects, as estimateBatchCost names it.
        "cache_kind": None,
        # Any model a Batch routes may think, unless the run froze an effort.
        "unestimated_thinking_tokens": bool(router)
        and configuration.get("thinkingEffort") is None
        or thinks(
            configuration.get("provider") or provider,
            model,
            configuration.get("thinkingEffort"),
        ),
        # The effort the run sends, which a price after an effort change names.
        "thinking_effort": summary(
            configuration.get("provider") or provider,
            model,
            configuration.get("thinkingEffort"),
        ),
    }
    if provider == "anthropic" and cache is not None and cache.writes:
        # Approximate input leaves out the reply schema the cache key holds.
        dynamic = max(0, inputs - cache.cached)
        cached, most = claude_cache_prices(cache, dynamic, outputs, in_rate, out_rate)
        value.update(
            cache_write_tokens=cache.writes,
            cache_read_tokens=cache.reads,
            cache_max_write_tokens=cache.cached,
            batch_cached_cost=cached,
            batch_max_cost=most,
            uses_prompt_cache=True,
            cache_kind="explicit",
        )
    elif provider == "openai":
        # The reads stay as counted, so the estimate is priced again for
        # another model from them; the hits are what this model's Batch reads.
        reads = min(inputs, counts["cache_read_tokens"])
        hits, writes, max_writes, cached, most = openai_cache_prices(
            inputs,
            outputs,
            reads,
            counts["cacheable_tokens"],
            model,
            in_rate,
            out_rate,
            nocache,
        )
        value.update(
            cache_read_tokens=reads,
            cache_write_tokens=writes,
            batch_cached_cost=cached,
            # Without billed writes, the cached prefixes estimateBatchCost
            # counted beside the rest of the input.
            cache_max_write_tokens=inputs - counts.get("dynamic_tokens", inputs)
            if max_writes is None
            else max_writes,
            uses_prompt_cache=bool(hits),
            cache_kind="automatic" if hits else None,
        )
        if most is not None:
            value["batch_max_cost"] = most
    value["batch_cost"] = (
        value["batch_cached_cost"]
        if value["uses_prompt_cache"]
        else value["batch_nocache_cost"]
    )
    return value


def reprice(estimate, configuration):
    """``estimate`` priced with the model and rates of ``configuration``, or
    None when its counts can't be priced again. Claude counts with each
    model's own tokenizer, so a Claude estimate is never priced again."""
    provider = estimate.get("provider")
    if (
        provider == "anthropic"
        or "input_tokens" not in estimate
        or "output_tokens" not in estimate
        or provider == "openai"
        and "cacheable_tokens" not in estimate
    ):
        return None
    return {**estimate, **prices(estimate, configuration, provider)}


def usage_cost(usage, configuration, provider, rows=None):
    """What a run's recorded ``usage`` cost at the rates it froze, as
    Guided's receipts price it; None when the provider reports its own
    charge, as OpenRouter's Batch does, or the rates are unknown.

    A Batch is priced at its Batch ``provider``'s cache prices, a Live run at
    those of its route as Guided prices Live responses
    (batch_providers.live_price_route). On a route priced by the time
    (provider_costs time_priced_route), a Live run's ``rows``, each request's
    usage and the time it arrived, whose sum is ``usage``, are priced one by
    one at that time's price."""
    from util.batch_providers import live_price_route
    from util.provider_costs import (
        batch_price_factor,
        time_price_factor,
        time_priced_route,
    )
    from util.provider_costs import usage_cost as cost

    rates = configuration.get("rates") or {}
    batch = configuration.get("mode") == "batch"
    if (
        rates.get("input") is None
        or rates.get("output") is None
        or batch
        and provider == "openrouter"
    ):
        return None
    route = (
        provider or configuration.get("provider", "")
        if batch
        else live_price_route(
            configuration["model"],
            configuration.get("endpoint") or "",
            configuration.get("protocol") or "",
        )
    )

    def price(counts, factor):
        return cost(
            # Assistant-led requests cache their instructions for five
            # minutes, which Live usage doesn't say beside its writes.
            {"cache_creation_1h_input_tokens": 0, **counts},
            route,
            configuration["model"],
            rates["input"] / 1_000_000,
            rates["output"] / 1_000_000,
            factor,
        )

    if batch:
        return price(usage, batch_price_factor(provider))
    timed = time_priced_route(configuration.get("endpoint"))
    if timed and rows:
        return sum(
            price(row, time_price_factor(timed, row.get("received_at"))) for row in rows
        )
    return price(usage, 1.0)
