"""Apply model-specific cache rates to newly calculated native Batch quotes."""

import math
import re
from typing import cast


def configure(translation, enabled):
    if not enabled:
        translation.estimateBatchCost.remove("cache-pricing")
        return

    def estimate(native, *args, **kwargs):
        value = native(*args, **kwargs)
        if not isinstance(value, dict) or value.get("provider") != "openai":
            return value
        model = str(value.get("model") or "")
        if not re.fullmatch(
            r"(?:openai/)?gpt-6\.1-sol(?:-\d{4}-\d{2}-\d{2})?", model.lower()
        ):
            return value
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
            return value
        # Every count was checked above as a finite, non-negative number.
        inputs, outputs, reads, writes = cast(list[float], counts)
        regular = inputs - reads - writes
        if regular < 0:
            return value
        rates = translation.getPricingConfig(model)
        input_rate, output_rate = (
            rates["inputAPICost"] / 1_000_000,
            rates["outputAPICost"] / 1_000_000,
        )
        # GPT-6.1 Sol reads cost 5% of uncached input, writes 125%; Batch
        # halves input and output rates. Recompute from counts rather than
        # subtracting a correction that could be applied twice on preparation.
        cost = (
            (regular + reads * 0.05 + writes * 1.25) * input_rate
            + outputs * output_rate
        ) * 0.5
        if cost != value.get("batch_cached_cost"):
            print(
                f"{kwargs.get('log_prefix', '[BATCH]')} updated prompt-caching estimate: ${cost:.4f}",
                flush=True,
            )
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

    translation.estimateBatchCost.layer("cache-pricing", estimate)
