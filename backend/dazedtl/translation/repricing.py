"""Pricing a saved estimate again after a model or translation mode switch.

An estimate counts its requests' tokens once. A switch that leaves the text
of every request the same keeps those counts, so the estimate takes the new
model's prices at once instead of being estimated again: the same connection
and request settings, a model whose requests carry the same text, and a
provider that counts tokens the same way for every model. Claude counts with
each model's own tokenizer, so a Claude estimate is always estimated again.
"""

from dazedtl.compatibility.request_text import request_text

from .files import digest

# What a model or mode switch changes in the frozen settings without
# changing the text of the requests built under them.
PRICE_ONLY = frozenset(
    {
        "mode",
        "model",
        "rates",
        "maxOutputTokens",
        "openrouterBatch",
        "batchInputTokens",
    }
)
API_MODES = {"batch", "live", "translate"}


def unpriced(configuration):
    """The settings that shape requests: everything but what a switch prices."""
    value = {key: item for key, item in configuration.items() if key not in PRICE_ONLY}
    if "engine_settings" in value:
        value["engine_settings"] = {
            key: item
            for key, item in value["engine_settings"].items()
            if key != "model"
        }
    return value


def priced(configuration):
    """Whether these settings know their model's prices."""
    rates = configuration.get("rates") or {}
    return rates.get("input") is not None and rates.get("output") is not None


def same_requests(before, after):
    """Whether requests built under ``after`` carry the text of those built
    under ``before``, so an estimate of them keeps its token counts."""
    return (
        before.get("mode") in API_MODES
        and after.get("mode") in API_MODES
        and "anthropic" not in (before.get("protocol"), after.get("protocol"))
        and unpriced(before) == unpriced(after)
        and request_text(before) == request_text(after)
    )


def approval_token(token, configuration):
    """The approval of a quote priced with these settings: a quote priced
    again takes a new token, so approving binds to the price shown."""
    return digest({"token": token, "configuration": configuration})[:32]
