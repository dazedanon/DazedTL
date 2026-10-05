"""Use frozen absolute Batch rates without changing native parser accounting."""

import sys
from functools import wraps


def batch_cost(policy, regular, output, reads=0, writes=0):
    read_rate = policy.get("cache_read")
    write_rate = policy.get("cache_write")
    return (
        regular * policy["input"]
        + output * policy["output"]
        + reads * (policy["input"] if read_rate is None else read_rate)
        + writes * (policy["input"] if write_rate is None else write_rate)
    ) / 1_000_000


def configure(translation, policy):
    # Repeated prepare calls must restore, not stack, the accounting adapter.
    names = ("estimateCostComparison", "translateAI", "calculateCost")
    originals = {}
    for name in names:
        function = getattr(translation, name, None)
        if function is None:
            continue
        if getattr(function, "_dazedtl_openrouter_pricing", False):
            function = function.__wrapped__
        originals[name] = function
        setattr(translation, name, function)

    def parser_aliases():
        # Parsers import helpers by value during native prepare. Update those
        # exact aliases as well, so file totals cannot retain the old discount.
        for name, module in tuple(sys.modules.items()):
            if name.startswith("modules.") and module is not None:
                for alias, source in (
                    ("calculateCost", "calculateCost"),
                    ("sharedtranslateAI", "translateAI"),
                    ("translateAI", "translateAI"),
                ):
                    current = getattr(module, alias, None)
                    if current is not None and (
                        current is originals.get(source)
                        or getattr(current, "_dazedtl_openrouter_pricing", False)
                    ):
                        setattr(module, alias, getattr(translation, source))

    if policy is None:
        parser_aliases()
        return

    def wrap(name, function):
        if name not in originals:
            return
        decorated = wraps(originals[name])(function)
        decorated._dazedtl_openrouter_pricing = True
        setattr(translation, name, decorated)

    def comparison(*args, **kwargs):
        value = originals["estimateCostComparison"](*args, **kwargs)
        if (
            value.get("provider") == "openrouter"
            and value.get("model") == policy["model"]
        ):
            value = {
                **value,
                "batch_cost": batch_cost(
                    policy, value["input_tokens"], value["output_tokens"]
                ),
                "unestimated_thinking_tokens": True,
            }
        return value

    def counters():
        return tuple(
            getattr(translation._thread_local, "file_batch_" + name, 0)
            for name in ("regular", "output", "read", "write")
        )

    def native_cost(model, values):
        regular, output, reads, writes = values
        pricing = translation.getPricingConfig(model)
        multiplier = translation.cache_write_multiplier("openrouter", model)
        return (
            (
                (regular + reads * 0.1 + writes * multiplier) * pricing["inputAPICost"]
                + output * pricing["outputAPICost"]
            )
            * 0.5
            / 1_000_000
        )

    def translate(*args, **kwargs):
        before = counters()
        value = originals["translateAI"](*args, **kwargs)
        if translation.get_batch_phase() == "consume":
            delta = tuple(after - old for after, old in zip(counters(), before))
            # Native translateAI charges the same token deltas at half of the
            # Live rate. Correct that accumulator while keeping its guards,
            # caching, validation, and per-file token counters unchanged.
            native_charged = (
                delta[0] > 0
                or delta[1] > 0
                or any(
                    name in policy["model"].lower()
                    for name in ("claude", "sonnet", "haiku", "opus")
                )
            )
            correction = batch_cost(policy, *delta) - (
                native_cost(policy["model"], delta) if native_charged else 0
            )
            with translation._global_accurate_cost_lock:
                translation._global_accurate_cost += correction
        return value

    def calculate(input_tokens, output_tokens, model):
        values = counters()
        per_file = getattr(
            translation._thread_local, "file_cost_window_active", False
        ) or getattr(translation._thread_local, "file_cost_ready", False)
        value = originals["calculateCost"](input_tokens, output_tokens, model)
        if (
            model == policy["model"]
            and translation.get_batch_phase() == "consume"
            and per_file
        ):
            value += batch_cost(policy, *values) - native_cost(model, values)
        return value

    wrap("estimateCostComparison", comparison)
    wrap("translateAI", translate)
    wrap("calculateCost", calculate)
    parser_aliases()

    from util import batch_history

    if not getattr(batch_history._price_usage, "_dazedtl_openrouter_pricing", False):
        original = batch_history._price_usage

        @wraps(original)
        def price(usage, model, provider="anthropic"):
            # Provider-reported charges remain separate in usage. A BYOK fee
            # must never be presented as the total cost of inference.
            return (
                None if provider == "openrouter" else original(usage, model, provider)
            )

        price._dazedtl_openrouter_pricing = True
        batch_history._price_usage = price
