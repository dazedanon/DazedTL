"""Apply model-specific cache rates to newly calculated native Batch quotes."""

import math
import re
from typing import cast


def sol(value):
    """Whether a quote prices GPT-6.1 Sol through OpenAI."""
    return value.get("provider") == "openai" and bool(
        re.fullmatch(
            r"(?:openai/)?gpt-6\.1-sol(?:-\d{4}-\d{2}-\d{2})?",
            str(value.get("model") or "").lower(),
        )
    )


def sol_cached_cost(value, input_rate, output_rate):
    """A GPT-6.1 Sol Batch quote's price with its expected cache hits, from
    its token counts and per-token rates, or None for counts that can't be
    priced. GPT-6.1 Sol reads cost 5% of uncached input, writes 125%; Batch
    halves input and output rates. It is computed from the counts rather
    than by subtracting a correction that could be applied twice on
    preparation."""
    counts = [
        value.get(key)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    ]
    if any(
        # bool is an int subclass but never a token count.
        not isinstance(count, (int, float))
        or isinstance(count, bool)
        or not math.isfinite(count)
        or count < 0
        for count in counts
    ):
        return None
    # Every count was checked above as a finite, non-negative number.
    inputs, outputs, reads, writes = cast(list[float], counts)
    regular = inputs - reads - writes
    if regular < 0:
        return None
    return (
        (regular + reads * 0.05 + writes * 1.25) * input_rate + outputs * output_rate
    ) * 0.5


def with_sol_cache(value, cost):
    """The quote with its expected-hits price replaced by ``cost``."""
    return {
        **value,
        "batch_cached_cost": cost,
        **(
            {
                "batch_cost": cost
                if value.get("uses_prompt_cache")
                else value["batch_nocache_cost"]
            }
            if "batch_cost" in value
            else {}
        ),
    }


def configure(translation, enabled):
    if not enabled:
        translation.estimateBatchCost.remove("cache-pricing")
        return

    def estimate(native, *args, **kwargs):
        value = native(*args, **kwargs)
        if not isinstance(value, dict) or not sol(value):
            return value
        rates = translation.getPricingConfig(value["model"])
        cost = sol_cached_cost(
            value, rates["inputAPICost"] / 1_000_000, rates["outputAPICost"] / 1_000_000
        )
        if cost is None:
            return value
        if cost != value.get("batch_cached_cost"):
            print(
                f"{kwargs.get('log_prefix', '[BATCH]')} updated prompt-caching estimate: ${cost:.4f}",
                flush=True,
            )
        return with_sol_cache(value, cost)

    translation.estimateBatchCost.layer("cache-pricing", estimate)
