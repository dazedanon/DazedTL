"""How a saved quote or estimate reads: as saved, priced again, or outdated.

An estimate counts its requests' tokens once. A switch that leaves the text
of every request the same keeps those counts, so the estimate takes the new
model's prices at once instead of being estimated again: the same connection
and request settings, a model whose requests carry the same text, and a
provider that counts tokens the same way for every model. Claude counts with
each model's own tokenizer, so a Claude estimate is always estimated again.

A pricing fix (provider_costs.PRICE_RULES_VERSION) keeps the counts too, so a
figure priced under older rules than its route's (``route_rules``) is priced
again under today's on its next view, or reads outdated when its counts
can't be; a fix to another route's rules leaves it standing. ``read``
decides this for every saved figure a user approves or reads: an
Assistant-led quote waiting for approval, a Guided Translate estimate and a
whole-game estimate.
"""

from dataclasses import dataclass

from dazedtl.compatibility.request_text import request_text
from dazedtl.settings.execution import LOOKED_UP

from .files import digest

# What a model or mode switch changes in the frozen settings without
# changing the text of the requests built under them. The thinking effort,
# like the output allowance, changes what a reply may cost, not its text, and
# so does the frozen record of the model's effort levels it is judged by and
# the rule its refusal is read by.
PRICE_ONLY = frozenset(
    {
        "mode",
        "model",
        "rates",
        "maxOutputTokens",
        "thinkingEffort",
        "thinkingEffortListed",
        "thinkingEffortRefusals",
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


def known(configuration):
    """The settings without what a model's price lookup fills in."""
    return {key: item for key, item in configuration.items() if key not in LOOKED_UP}


def unknown_prices(before, after):
    """Whether ``after`` differs from ``before`` only by prices DazedTL hasn't
    looked up since it started, which a snapshot reads as unchanged rather
    than outdate every estimate on each restart."""
    return not priced(after) and known(before) == known(after)


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


def current_rules():
    """The price rules version figures are priced under today."""
    from util.provider_costs import PRICE_RULES_VERSION

    return PRICE_RULES_VERSION


def rules(figure):
    """The price rules version a saved quote or estimate was priced under;
    one saved before figures recorded it reads as version 1."""
    return (figure or {}).get("price_rules", 1)


def route_rules(*routes):
    """The price rules version a figure priced on ``routes`` needs to keep
    its price, the newest at which any of their rules changed: a figure's
    route is the Batch provider that priced it, None for none
    (provider_costs.route_price_rules). A Guided estimate and each task of a
    whole-game estimate record it as ``provider``, an Assistant-led quote as
    ``route`` (``quote_route``)."""
    from util.provider_costs import route_price_rules

    return max(route_price_rules(route) for route in routes or (None,))


def quote_route(quote, provider):
    """The route that priced an Assistant-led quote, the Batch provider it
    records as ``route``; one saved before quotes recorded it reads as
    ``provider``, the Batch provider of its run's current settings. A quote
    whose route is no longer its settings' is priced again on theirs
    (service.changed_since)."""
    return quote.get("route", provider)


@dataclass(frozen=True)
class Reading:
    """How a saved figure reads now: ``current`` while it stands as saved
    (``figure`` None) or priced again (``figure``, at ``settings``)."""

    current: bool
    settings: dict | None = None
    figure: object = None


OUTDATED = Reading(False)


def read(change, before, after, again):
    """How a figure priced with the settings ``before`` reads now.

    ``change`` is freshness.compare of its basis, with the price rules it was
    priced under, against the current one, with the price rules its route
    needs (``route_rules``); ``after`` the current settings;
    ``again(settings)`` its counts priced with ``settings`` under today's
    rules, None when they can't be. Unchanged, it stands as saved. When only
    what prices it changed and its requests keep their text, it is priced
    again: at the current settings when they changed, else at the ones it was
    priced with, whose prices a snapshot may not have looked up yet.
    Otherwise it reads outdated and is estimated again."""
    if change is None:
        return Reading(True)
    if not change.priced_only or not before:
        return OUTDATED
    settings = after if change.settings else before
    if not settings or not priced(settings) or not same_requests(before, settings):
        return OUTDATED
    figure = again(settings)
    return OUTDATED if figure is None else Reading(True, settings, figure)


def approval_token(token, configuration, route):
    """The approval of a quote priced again with these settings on ``route``
    under today's price rules: it takes a new token, so approving binds to
    the price shown. The token follows only the rules of its own route
    (``route_rules``), so a fix to another route's rules keeps it."""
    return digest(
        {"token": token, "configuration": configuration, "rules": route_rules(route)}
    )[:32]
