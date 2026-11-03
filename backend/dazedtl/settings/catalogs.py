"""The model catalog a connection check keeps for the presets whose own model
list prices each model, OpenRouter's (settings/openrouter) and OpenCode's
routes' (settings/opencode): which saved catalog counts, how a model's Live
defaults read from it, and the bounds both catalogs' values keep."""

import math
from datetime import UTC, datetime

# A catalog counts as current for a day after the check that loaded it.
STALE_SECONDS = 86400


def checked(connection):
    """The models a verified check loaded, none before one or after a failure."""
    verified = connection.get("check", {}).get("status") == "verified"
    return connection.get("catalog", {}) if verified else {}


def described(connection, model, row):
    """*model*'s Live defaults from its catalog *row*, its input and output
    rates and output limit, empty when the catalog doesn't hold it: dated by
    the check that loaded them and stale a day after it (STALE_SECONDS)."""
    stamp = connection.get("check", {}).get("checkedAt")
    try:
        stale = (
            not stamp
            or (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()
            > STALE_SECONDS
        )
    except ValueError, TypeError:
        stale = True
    return {
        "model": model,
        "inputRate": row.get("input"),
        "outputRate": row.get("output"),
        "maxOutputTokens": row.get("max_output"),
        "source": "catalog" if row else "unavailable",
        "updatedAt": stamp,
        "stale": stale,
    }


def positive_integer(value):
    return value if type(value) is int and 0 < value <= 9_007_199_254_740_991 else None


def amount(value):
    """A price in USD per million tokens, or None outside its bounds."""
    return (
        value
        if type(value) in (int, float)
        and math.isfinite(value)
        and 0 <= value <= 1_000_000
        else None
    )
