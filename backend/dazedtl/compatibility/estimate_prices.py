"""A Guided estimate priced again for another model of its connection.

An estimate's worker counts its requests once and prices them with the
engine's estimateBatchCost and DazedTL's pricing layers. When a model switch
keeps the text of every request (translation/repricing), those counts are
priced here with the new model's rates by the same formulas: the engine's
OpenAI cache prices, OpenRouter's own Batch rates and GPT-6.1 Sol's cache
rates. Claude counts with each model's own tokenizer, so a Claude estimate
is never priced again.
"""

from .batch_pricing import sol, sol_cached_cost, with_sol_cache
from .openrouter_pricing import batch_cost


def reprice(estimate, configuration):
    """``estimate`` priced with the model and rates of ``configuration``, or
    None when its counts can't be priced again."""
    from util.provider_costs import batch_price_factor
    from util.translation import openai_cache_prices, unestimatedThinking

    provider = estimate.get("provider")
    if (
        provider == "anthropic"
        or "input_tokens" not in estimate
        or "output_tokens" not in estimate
        or provider == "openai"
        and "cacheable_tokens" not in estimate
    ):
        return None
    model = configuration["model"]
    inputs, outputs = estimate["input_tokens"], estimate["output_tokens"]
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
        **estimate,
        "model": model,
        "live_cost": live,
        "batch_nocache_cost": nocache,
        "batch_cached_cost": nocache,
        "batch_max_cost": nocache,
        "unestimated_thinking_tokens": bool(router)
        or unestimatedThinking(provider, model),
    }
    if provider == "openai":
        writes, max_writes, cached, most = openai_cache_prices(
            inputs,
            outputs,
            estimate["cache_read_tokens"],
            estimate["cacheable_tokens"],
            model,
            in_rate,
            out_rate,
        )
        value.update(
            cache_write_tokens=writes,
            batch_cached_cost=cached,
            # Without billed writes, the cached prefixes estimateBatchCost
            # counted beside the rest of the input.
            cache_max_write_tokens=inputs - estimate["dynamic_tokens"]
            if max_writes is None
            else max_writes,
        )
        if most is not None:
            value["batch_max_cost"] = most
    if sol(value):
        cost = sol_cached_cost(value, in_rate, out_rate)
        if cost is not None:
            value = with_sol_cache(value, cost)
    # What a Translate estimate shows as its Batch price.
    value["batch_cost"] = (
        value["batch_cached_cost"]
        if value.get("uses_prompt_cache")
        else value["batch_nocache_cost"]
    )
    return value
