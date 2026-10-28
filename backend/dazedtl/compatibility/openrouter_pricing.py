"""Price an OpenRouter Batch at its policy's frozen absolute rates."""

LAYER = "openrouter-pricing"


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
    """Every Batch price of the run, its estimate, file lines and TOTAL,
    comes from the policy's frozen rates."""
    points = (translation.estimateCostComparison, translation.batch_usage_cost)
    if policy is None:
        for point in points:
            point.remove(LAYER)
        return

    def comparison(native, *args, **kwargs):
        value = native(*args, **kwargs)
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

    def price(native, usage, model, provider):
        # The policy's absolute rates already hold the Batch discount, so they
        # replace the engine's Live rates instead of being halved again.
        if provider != "openrouter" or model != policy["model"]:
            return native(usage, model, provider)

        def count(key):
            return usage.get(key, 0) or 0

        return batch_cost(
            policy,
            count("input_tokens"),
            count("output_tokens") + count("thinking_tokens"),
            count("cache_read_input_tokens"),
            count("cache_creation_input_tokens"),
        )

    for point, layer in zip(points, (comparison, price), strict=True):
        point.layer(LAYER, layer)
    from util import batch_history

    batch_history._price_usage.layer("openrouter", price_usage)


def price_usage(native, usage, model, provider="anthropic"):
    # Provider-reported charges remain separate in usage. A BYOK fee must never
    # be presented as the total cost of inference.
    return None if provider == "openrouter" else native(usage, model, provider)
