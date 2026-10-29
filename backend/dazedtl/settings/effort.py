"""Thinking effort: which efforts a model takes, what its provider uses when
none is sent, and how a choice is written into a request.

Settings, runs of both methods and the legacy evaluation all read this one
table. A request carries an effort only when its provider, its exact model ID
and the level are a row here, or of the provider's own model list where the
connection check keeps one (``LISTED``, ``profile``), or a level a check on
the connection passed for a model neither describes (``CHECKED``); every
other request sends nothing, exactly as runs did before the choice existed,
so no run sends a level its provider does not document or accept; a run
whose provider refuses its level anyway stops with one message
(``rejection``). The table is checked where a choice is saved
(settings/store), where a run freezes it (settings/execution and the Guided
request policy) and where a request is built (``apply``).

Rows were read on 2026-10-28 from each provider's own reference:
- Anthropic: platform.claude.com/docs/en/build-with-claude/effort and
  .../extended-thinking (adaptive ``thinking`` plus ``output_config.effort``).
- OpenAI: developers.openai.com/api/docs/models/<model> (``reasoning_effort``).
- Gemini: ai.google.dev/gemini-api/docs/openai and .../thinking
  (``reasoning_effort`` on the OpenAI-compatible endpoint, each model's own
  thinking levels only).
- DeepSeek: api-docs.deepseek.com/api/create-chat-completion and
  .../guides/thinking_mode.
- Kimi: platform.kimi.ai/docs/api/chat.
- Mistral: docs.mistral.ai/capabilities/reasoning.
- OpenRouter: openrouter.ai/docs/use-cases/reasoning-tokens and its public
  model list (``reasoning.supported_efforts`` and ``default_effort``).
Custom and local servers send a level only once a check passed it, since
DazedTL cannot know what they accept. scripts/effort_check.py sends each row
of the table to its provider, so the rows stay true as providers change; each
row keeps the date it last confirmed them.

The engine builders' own efforts (``buildOpenAIRequest`` in
engine/util/translation.py: "low" for GPT-6 Astra, "none" for other GPT-6 and
GPT-5.6, "minimal" for older GPT-5) belong to runs frozen without a request
policy (before 2026-10-03); they still send them, byte for byte, because
``request_parameters.provider_defaults`` leaves those runs alone.
"""

import json
import re
from typing import NotRequired, TypedDict

# Every level any provider takes, cheapest first.
LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
LABELS = {
    "none": "Off",
    "minimal": "Minimal",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
    "max": "Maximum",
}

_TO_XHIGH = ("low", "medium", "high", "xhigh")
_FULL = (*_TO_XHIGH, "max")
_OFF_FULL = ("none", *_FULL)
_OLD_CLAUDE = ("none", "low", "medium", "high", "max")
_GPT5 = ("none", *_TO_XHIGH)
_LMH = ("low", "medium", "high")
_MLMH = ("minimal", *_LMH)

# provider -> exact model ID -> (levels it takes, the level its provider
# uses when none is sent, or None when its docs don't say, and the date
# scripts/effort_check.py last saw the provider accept every level, or None
# until it has).
_NATIVE = {
    # Opus 5.5, Fable and Mythos always think. Opus 5, Sonnet 5.5 and Haiku
    # 5.5 turn thinking off only at effort high or below, which their
    # defaults are, so "Off" turns thinking off with no level. Omitting thinking on Opus
    # 4.8/4.7/4.6 and Sonnet 4.6 means no thinking. Haiku 4.5 and older
    # take a thinking budget, not an effort.
    "anthropic": {
        "claude-opus-5-5": (_FULL, "medium", "2026-10-29"),
        "claude-opus-5": (_OFF_FULL, "high", "2026-10-29"),
        "claude-opus-4-8": (_OFF_FULL, "none", "2026-10-29"),
        "claude-opus-4-7": (_OFF_FULL, "none", "2026-10-29"),
        "claude-opus-4-6": (_OLD_CLAUDE, "none", "2026-10-29"),
        "claude-sonnet-5-5": (_OFF_FULL, "high", "2026-10-29"),
        "claude-sonnet-5": (_OFF_FULL, "high", "2026-10-29"),
        "claude-sonnet-4-6": (_OLD_CLAUDE, "none", "2026-10-29"),
        "claude-haiku-5-5": (_OFF_FULL, "medium", "2026-10-29"),
        "claude-fable-5-1": (_FULL, "high", "2026-10-29"),
        "claude-fable-5": (_FULL, "high", "2026-10-29"),
        "claude-mythos-5-1": (_FULL, "high", None),
        "claude-mythos-5": (_FULL, "high", None),
    },
    # GPT-4.x and other models without reasoning take none. GPT-6.x and
    # GPT-5.6 refuse "max" (scripts/effort_check.py, 2026-10-29).
    "openai": {
        "gpt-6.1-sol": (_TO_XHIGH, "medium", "2026-10-29"),
        "gpt-6.1-terra": (_GPT5, "medium", "2026-10-29"),
        "gpt-6-astra": (_TO_XHIGH, None, "2026-10-29"),
        "gpt-6-sol": (_GPT5, "medium", "2026-10-29"),
        "gpt-6-luna": (_GPT5, "medium", "2026-10-29"),
        "gpt-5.6-sol": (_GPT5, "medium", "2026-10-29"),
        "gpt-5.6-terra": (_GPT5, "medium", "2026-10-29"),
        "gpt-5.6-luna": (_GPT5, "medium", "2026-10-29"),
        "gpt-5.5": (_GPT5, "medium", "2026-10-29"),
        "gpt-5.4": (_GPT5, "none", "2026-10-29"),
        "gpt-5.2": (_GPT5, "none", "2026-10-29"),
        "gpt-5.1": (("none", *_LMH), "none", "2026-10-29"),
        "gpt-5": (_MLMH, None, "2026-10-29"),
    },
    # Only levels each model's own thinking levels hold, since the
    # endpoint's mapping of the others is not documented. Thinking can be
    # turned off only on the 2.5 Flash models.
    "gemini": {
        "gemini-4-argon": (_LMH, "medium", None),
        "gemini-3.8-flash": (_LMH, "medium", None),
        "gemini-3.6-flash": (_MLMH, "medium", None),
        "gemini-3.5-flash-lite": (_MLMH, "minimal", None),
        "gemini-3.1-pro-preview": (_LMH, "high", None),
        "gemini-3-pro-preview": (("low", "high"), "high", None),
        "gemini-3-flash-preview": (_MLMH, "high", None),
        "gemini-2.5-pro": (_LMH, None, None),
        "gemini-2.5-flash": (("none", *_LMH), None, None),
        "gemini-2.5-flash-lite": (("none", *_LMH), "none", None),
    },
    # Its other levels are mapped to these four, so only these are offered.
    "deepseek": {
        "deepseek-flash": (("none", "low", "high", "max"), "high", None),
        "deepseek-v4-pro": (("none", "low", "high", "max"), "high", None),
        "deepseek-v4-flash": (("none", "low", "high", "max"), "high", None),
    },
    # The K3 series always thinks; K2.6 only turns thinking on or off, and
    # K2.7 Code only thinks.
    "kimi": {
        "kimi-k3": (("low", "high", "max"), "max", "2026-10-29"),
        "kimi-k3.1-pro": (("low", "high", "max"), "max", "2026-10-29"),
        "kimi-k3.1-pro-highspeed": (("low", "high", "max"), "max", "2026-10-29"),
        "kimi-k2.6": (("none",), None, "2026-10-29"),
    },
    # The docs name only these levels for these models.
    "mistral": {
        "mistral-small-latest": (("none", "high"), None, None),
        "mistral-medium-3-5": (("none", "high"), None, None),
        "mistral-large-4-0": (("none", "high"), None, None),
        "zai-glm-5-3": (("low", "high", "max"), None, None),
    },
}

# OpenRouter maps a level a model does not list to the nearest one it
# lists, silently, so a routed model offers only the levels both its own
# provider's row and OpenRouter's model list hold. Each row is the routed
# model's own (provider, model), then OpenRouter's supported_efforts and the
# level OpenRouter applies when none is sent ("none" where its list says
# reasoning is off by default), read from its public model list, then the
# date scripts/effort_check.py last confirmed the row. The default
# shown is the one both sources agree on, or the only one stated. Every
# OpenRouter endpoint of these models that takes structured outputs also
# takes `reasoning`, so `provider.require_parameters` routes as before.
_OPENROUTER = {
    "anthropic/claude-opus-5.5": (
        "anthropic",
        "claude-opus-5-5",
        _FULL,
        "high",
        "2026-10-29",
    ),
    "anthropic/claude-opus-5": (
        "anthropic",
        "claude-opus-5",
        _OFF_FULL,
        "high",
        "2026-10-29",
    ),
    "anthropic/claude-opus-4.8": (
        "anthropic",
        "claude-opus-4-8",
        _OFF_FULL,
        "none",
        "2026-10-29",
    ),
    "anthropic/claude-opus-4.7": (
        "anthropic",
        "claude-opus-4-7",
        _OFF_FULL,
        "none",
        "2026-10-29",
    ),
    "anthropic/claude-opus-4.6": (
        "anthropic",
        "claude-opus-4-6",
        _OLD_CLAUDE,
        "none",
        "2026-10-29",
    ),
    "anthropic/claude-sonnet-5.5": (
        "anthropic",
        "claude-sonnet-5-5",
        _FULL,
        "high",
        "2026-10-29",
    ),
    "anthropic/claude-sonnet-5": (
        "anthropic",
        "claude-sonnet-5",
        _OFF_FULL,
        "high",
        "2026-10-29",
    ),
    "anthropic/claude-sonnet-4.6": (
        "anthropic",
        "claude-sonnet-4-6",
        _OLD_CLAUDE,
        "medium",
        "2026-10-29",
    ),
    "anthropic/claude-haiku-5.5": (
        "anthropic",
        "claude-haiku-5-5",
        _OFF_FULL,
        "medium",
        "2026-10-29",
    ),
    "anthropic/claude-fable-5.1": (
        "anthropic",
        "claude-fable-5-1",
        _FULL,
        "high",
        "2026-10-29",
    ),
    "anthropic/claude-fable-5": (
        "anthropic",
        "claude-fable-5",
        _FULL,
        "high",
        "2026-10-29",
    ),
    "openai/gpt-6.1-sol": ("openai", "gpt-6.1-sol", _FULL, "medium", "2026-10-29"),
    "openai/gpt-6.1-terra": (
        "openai",
        "gpt-6.1-terra",
        _OFF_FULL,
        "medium",
        "2026-10-29",
    ),
    "openai/gpt-6-astra": ("openai", "gpt-6-astra", _FULL, "medium", "2026-10-29"),
    "openai/gpt-6-sol": ("openai", "gpt-6-sol", _OFF_FULL, "medium", "2026-10-29"),
    "openai/gpt-6-luna": ("openai", "gpt-6-luna", _OFF_FULL, "medium", "2026-10-29"),
    "openai/gpt-5.6-sol": ("openai", "gpt-5.6-sol", _OFF_FULL, "medium", "2026-10-29"),
    "openai/gpt-5.6-terra": (
        "openai",
        "gpt-5.6-terra",
        _OFF_FULL,
        "medium",
        "2026-10-29",
    ),
    "openai/gpt-5.6-luna": (
        "openai",
        "gpt-5.6-luna",
        _OFF_FULL,
        "medium",
        "2026-10-29",
    ),
    "openai/gpt-5.5": ("openai", "gpt-5.5", _GPT5, "medium", "2026-10-29"),
    "openai/gpt-5.4": ("openai", "gpt-5.4", _GPT5, "none", "2026-10-29"),
    "openai/gpt-5.2": ("openai", "gpt-5.2", _GPT5, "medium", "2026-10-29"),
    "openai/gpt-5.1": ("openai", "gpt-5.1", ("none", *_LMH), "none", "2026-10-29"),
    "openai/gpt-5": ("openai", "gpt-5", _MLMH, "medium", "2026-10-29"),
    "google/gemini-4-argon": ("gemini", "gemini-4-argon", _LMH, "medium", "2026-10-29"),
    "google/gemini-3.8-flash": (
        "gemini",
        "gemini-3.8-flash",
        _LMH,
        "medium",
        "2026-10-29",
    ),
    "google/gemini-3.6-flash": (
        "gemini",
        "gemini-3.6-flash",
        _MLMH,
        "medium",
        "2026-10-29",
    ),
    "google/gemini-3.5-flash-lite": (
        "gemini",
        "gemini-3.5-flash-lite",
        _MLMH,
        "minimal",
        "2026-10-29",
    ),
    "google/gemini-3.1-pro-preview": (
        "gemini",
        "gemini-3.1-pro-preview",
        _LMH,
        "medium",
        "2026-10-29",
    ),
    "google/gemini-3-flash-preview": (
        "gemini",
        "gemini-3-flash-preview",
        ("none", *_MLMH),
        "medium",
        "2026-10-29",
    ),
    "moonshotai/kimi-k3": (
        "kimi",
        "kimi-k3",
        ("none", "low", "high", "max"),
        "max",
        "2026-10-29",
    ),
    "moonshotai/kimi-k3.1-pro": (
        "kimi",
        "kimi-k3.1-pro",
        ("none", "low", "high", "max"),
        "max",
        "2026-10-29",
    ),
    "deepseek/deepseek-v4-pro": (
        "deepseek",
        "deepseek-v4-pro",
        ("none", "high", "xhigh"),
        "high",
        "2026-10-29",
    ),
    "deepseek/deepseek-v4-flash": (
        "deepseek",
        "deepseek-v4-flash",
        ("none", "high", "xhigh"),
        "high",
        "2026-10-29",
    ),
    "mistralai/mistral-large-4-0": (
        "mistral",
        "mistral-large-4-0",
        ("none", "high"),
        "high",
        "2026-10-29",
    ),
    "mistralai/mistral-medium-3-5": (
        "mistral",
        "mistral-medium-3-5",
        ("none", "high"),
        "high",
        "2026-10-29",
    ),
}


def _routed(model):
    own_provider, own_model, listed, listed_default = _OPENROUTER[model][:4]
    levels, own_default = _NATIVE[own_provider][own_model][:2]
    default = (
        own_default
        if listed_default in (own_default, None)
        else listed_default
        if own_default is None
        else None
    )
    return tuple(level for level in levels if level in listed), default


def table():
    """Each row of the notes, for scripts/effort_check.py: (provider, model
    ID, the levels it takes, its provider default, the date the script last
    confirmed it or None)."""
    for provider, models in _NATIVE.items():
        for model, row in models.items():
            notes = _notes(provider, model)
            yield provider, model, notes["levels"], notes["default"], row[2]
    for model, row in _OPENROUTER.items():
        notes = _notes("openrouter", model)
        yield "openrouter", model, notes["levels"], notes["default"], row[4]


def model_id(model):
    """The ID the table knows a model by: Gemini's optional `models/` prefix
    left out, in lower case; nothing else is matched loosely."""
    return str(model or "").strip().lower().removeprefix("models/")


# The providers whose own model list, which the connection check downloads,
# says which efforts each model takes: Anthropic's GET /v1/models
# (`capabilities.effort` and `capabilities.thinking.types`) and OpenRouter's
# GET /models/user (`reasoning`). The lists of OpenAI, Gemini, DeepSeek, Kimi
# and Mistral say nothing about effort, so their models keep the notes above.
LISTED = {"anthropic": "Anthropic", "openrouter": "OpenRouter"}
# A connection keeps at most as many records as its OpenRouter catalog.
MAX_LISTED = 2000
_OFF = (None, "disabled", "between_tools")


def _record(levels=(), default=None, off=None, adaptive=False):
    """How one model takes an effort: the levels it takes, the level its
    provider uses when none is sent (None: unknown), the `thinking` type that
    turns Claude's thinking off and whether a level turns Claude's adaptive
    thinking on."""
    return {
        "levels": [level for level in LEVELS if level in levels],
        "default": default,
        "off": off,
        "adaptive": adaptive,
    }


def _supported(value):
    return isinstance(value, dict) and value.get("supported") is True


def anthropic_record(row):
    """The record one row of Anthropic's model list gives, or None where the
    row doesn't say, which leaves the model to the notes. `disabled` is listed
    as unsupported exactly where sending it is refused, as on Opus 5.5;
    Sonnet 5.5 turns thinking off with `between_tools` instead. The list
    names no default level."""
    capabilities = row.get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    effort = capabilities.get("effort")
    thinking = capabilities.get("thinking")
    types = thinking.get("types") if isinstance(thinking, dict) else None
    if not isinstance(effort, dict) or type(effort.get("supported")) is not bool:
        return None
    if not effort["supported"]:
        return _record()
    if not isinstance(types, dict):
        return None
    off = (
        "disabled"
        if _supported(types.get("disabled"))
        else "between_tools"
        if _supported(types.get("between_tools"))
        else None
    )
    return _record(
        [level for level in _FULL if _supported(effort.get(level))]
        + (["none"] if off else []),
        off=off,
        adaptive=_supported(types.get("adaptive")),
    )


def openrouter_record(row):
    """The record one row of OpenRouter's model list gives, or None where the
    row doesn't say. OpenRouter maps a level a model doesn't list to the
    nearest one it lists, so only listed levels are offered; a `mandatory`
    model refuses "none", and a null `supported_efforts` has no allowlist,
    which leaves the model to the notes. A model whose list shows no
    `reasoning` parameter takes no effort."""
    parameters = row.get("supported_parameters")
    if isinstance(parameters, list) and "reasoning" not in parameters:
        return None if "reasoning_effort" in parameters else _record()
    reasoning = row.get("reasoning")
    if not isinstance(reasoning, dict):
        return None
    efforts = reasoning.get("supported_efforts")
    if not isinstance(efforts, list):
        return None
    offered = [
        level
        for level in efforts
        if not (level == "none" and reasoning.get("mandatory") is True)
    ]
    named = reasoning.get("default_effort")
    return _record(
        offered,
        "none"
        if reasoning.get("default_enabled") is False
        else named
        if isinstance(named, str) and named in LEVELS
        else None,
    )


def model_list(provider, rows):
    """{model ID: record} from the rows of *provider*'s model list, for each
    model whose row says which efforts it takes; empty for a provider whose
    list doesn't."""
    read = {"anthropic": anthropic_record, "openrouter": openrouter_record}.get(
        provider
    )
    result = {}
    if read is None:
        return result
    for row in rows:
        model = row.get("id") if isinstance(row, dict) else None
        # Runs name a model by its own ID, never its `:batch` listing.
        if (
            not isinstance(model, str)
            or not 0 < len(model) <= 200
            or any(ord(char) < 32 for char in model)
            or model.endswith(":batch")
        ):
            continue
        value = read(row)
        if value is not None:
            result[model_id(model)] = value
        if len(result) >= MAX_LISTED:
            break
    return result


def valid(value):
    """A saved or frozen record, which must be one this module made."""
    if (
        not isinstance(value, dict)
        or set(value) != {"levels", "default", "off", "adaptive"}
        or not isinstance(value["levels"], list)
        or value["levels"] != [level for level in LEVELS if level in value["levels"]]
        or not (value["default"] is None or value["default"] in LEVELS)
        or value["off"] not in _OFF
        or type(value["adaptive"]) is not bool
    ):
        raise ValueError("This model's saved thinking efforts are invalid.")
    return value


def valid_list(value):
    """A connection's saved records, by model ID."""
    if not isinstance(value, dict) or len(value) > MAX_LISTED:
        raise ValueError("This connection's saved thinking efforts are invalid.")
    for model, item in value.items():
        if not isinstance(model, str) or not 0 < len(model) <= 200:
            raise ValueError("This connection's saved thinking efforts are invalid.")
        valid(item)
    return value


def kept(connection):
    """Whether *connection*'s last check read its provider's model list
    for efforts: never for a connection checked before records were kept,
    or one whose provider's list names no effort."""
    return (
        bool(connection)
        and connection.get("provider") in LISTED
        and "efforts" in connection
    )


# Providers that take the OpenAI-compatible `reasoning_effort`, where a model
# the notes don't hold, and every model of a custom or local server, may send
# a level once a check on its connection passed it (settings/providers
# check_effort, on the user's click in Settings). Anthropic's and
# OpenRouter's own model lists say which efforts their models take, and
# OpenRouter maps a level a model doesn't list to another without saying so,
# so a check there would prove nothing.
CHECKED = frozenset({"openai", "gemini", "mistral", "kimi", "deepseek", "custom"})
# A connection keeps checks for at most this many models.
MAX_CHECKED = 200


def checkable(provider, model):
    """Whether *model* on *provider* takes a level only once a check on its
    connection passed it."""
    return (
        provider in CHECKED
        and bool(model_id(model))
        and not _notes(provider, model)["levels"]
    )


def trial(level):
    """The record a check of *level* sends it with, as a run would once the
    check passed."""
    return _record([level])


def valid_checks(value):
    """A connection's saved checks: by model ID, each level's outcome."""
    invalid = ValueError("This connection's saved effort checks are invalid.")
    if not isinstance(value, dict) or len(value) > MAX_CHECKED:
        raise invalid
    for model, levels in value.items():
        if (
            not isinstance(model, str)
            or not 0 < len(model) <= 200
            or not isinstance(levels, dict)
            or not levels
        ):
            raise invalid
        for level, item in levels.items():
            if (
                level not in LEVELS
                or not isinstance(item, dict)
                or set(item) != {"passed", "message", "checkedAt"}
                or type(item["passed"]) is not bool
                or not isinstance(item["message"], str)
                or len(item["message"]) > 1000
                or not isinstance(item["checkedAt"], str)
            ):
                raise invalid
    return value


def keep_check(checks, model, level, passed, message, checked_at):
    """*checks* with one check's outcome saved, dropping the model checked
    longest ago once more than MAX_CHECKED are kept."""
    checks = {key: dict(value) for key, value in checks.items()}
    key = model_id(model)
    checks[key] = {
        **checks.pop(key, {}),
        level: {"passed": passed, "message": message, "checkedAt": checked_at},
    }
    while len(checks) > MAX_CHECKED:
        oldest = min(
            checks,
            key=lambda item: max(entry["checkedAt"] for entry in checks[item].values()),
        )
        del checks[oldest]
    return checks


def record(connection, model):
    """*model*'s record from *connection*, or None: its provider's model list
    as the last connection check read it (None for a connection checked
    before records were kept, a provider whose list names no effort, or a
    model its list doesn't describe), or the levels checks on this
    connection passed for a model nothing else describes."""
    if not connection:
        return None
    provider = connection.get("provider")
    if provider in LISTED:
        return connection["efforts"].get(model_id(model)) if kept(connection) else None
    if not checkable(provider, model):
        return None
    saved = connection.get("effort_checks", {}).get(model_id(model), {})
    passed = [level for level, item in saved.items() if item["passed"]]
    return _record(passed) if passed else None


def _notes(provider, model):
    model = model_id(model)
    if provider == "openrouter":
        levels, default = _routed(model) if model in _OPENROUTER else ((), None)
    else:
        levels, default = _NATIVE.get(provider, {}).get(model, ((), None))[:2]
    claude = provider == "anthropic" and bool(levels)
    return _record(
        levels,
        default,
        # Sonnet 5.5 refuses "disabled"; it turns thinking off with
        # "between_tools", which takes no other field.
        ("between_tools" if model == "claude-sonnet-5-5" else "disabled")
        if claude and "none" in levels
        else None,
        claude,
    )


def profile(provider, model, listed=None):
    """How *model* on *provider*, a connection's identity (settings/providers
    PROVIDERS), takes an effort, as a record. *listed* is the model's record
    from its provider's own model list, or from checks on its connection
    for a model nothing else describes (``record``), which decides the
    levels; without one, DazedTL's notes above decide. Levels never mix the
    two sources; the default the notes name stands in where the list names
    none, as Anthropic's never does. A model none knows takes no level and
    its default is unknown."""
    notes = _notes(provider, model)
    if listed is None or not (provider in LISTED or checkable(provider, model)):
        return notes
    return {
        **listed,
        "levels": list(listed["levels"]),
        "default": listed["default"] or notes["default"],
    }


def levels(provider, model, listed=None):
    return tuple(profile(provider, model, listed)["levels"])


def takes(provider, model, level, listed=None):
    """Whether a request to *model* on *provider* may carry *level*."""
    return level in levels(provider, model, listed)


def checked(level):
    """A saved or frozen level, which must be one of LEVELS or None."""
    if level is not None and level not in LEVELS:
        raise ValueError("Choose a thinking effort from the list.")
    return level


def chosen(provider, model, level, listed=None):
    """The level a new run freezes for a saved choice: the choice while the
    model takes it, else None, which leaves the effort to the provider."""
    return (
        level if level is not None and takes(provider, model, level, listed) else None
    )


def frozen(provider, model, options, listed=None):
    """What a new run freezes for a model's saved options, beside its other
    request settings: nothing when it sends no effort and the notes describe
    it, so runs that send none keep the settings, and estimates, they had
    before the choice existed. The model list's record is frozen too when it,
    not the notes, decides what the run sends or the default its review
    names, so a later check never changes a frozen run. An effort is frozen
    with the rule its refusal is read by (``REFUSALS``)."""
    level = chosen(provider, model, options.get("thinkingEffort"), listed)
    value = (
        {}
        if level is None
        else {"thinkingEffort": level, "thinkingEffortRefusals": REFUSALS}
    )
    notes = _notes(provider, model)
    resolved = profile(provider, model, listed)
    if resolved != notes and (
        level is not None or resolved["default"] != notes["default"]
    ):
        # The list's record with the default the notes fill in, so a later
        # version's notes never rename what a frozen run's review names.
        value["thinkingEffortListed"] = resolved
    return value


def label(level):
    return LABELS[level]


def summary(provider, model, level, listed=None):
    """What a run sends, as the run summary names it: "Low", or
    "Provider default (Medium)" when it sends none."""
    if level is not None:
        return label(level)
    default = profile(provider, model, listed)["default"]
    return "Provider default" + (f" ({label(default)})" if default else "")


class Choices(TypedDict):
    # As api/contracts/settings ThinkingEffort.
    options: list[dict]
    source: NotRequired[str]


def describe(provider, model, listed=None, read=False) -> Choices:
    """The choices Settings offers for a model: the provider default first,
    then each level the model takes, and a line saying where those come
    from and how to refresh them. *read* is ``kept`` for the connection."""
    resolved = profile(provider, model, listed)
    value: Choices = {
        "options": [
            {"value": None, "label": summary(provider, model, None, listed)},
            *({"value": level, "label": label(level)} for level in resolved["levels"]),
        ]
    }
    name = LISTED.get(provider)
    if listed is not None and name:
        value["source"] = (
            f"These levels come from {name}'s model list as of your last "
            "connection check. Check the connection again in API connections "
            "to refresh them."
        )
    elif listed is not None and checkable(provider, model):
        value["source"] = "These levels passed a check on this connection."
    elif resolved["levels"]:
        value["source"] = "These levels come from DazedTL's built-in list" + (
            ", which DazedTL updates keep current."
            if not name
            else f", since {name}'s model list doesn't describe this model."
            if read
            else f". Check the connection in API connections to read {name}'s "
            "model list instead."
        )
    return value


def flat(params):
    """The JSON body an OpenAI-compatible client sends for *params*: the
    fields of its extra_body merged in at the top."""
    return {
        **{key: value for key, value in params.items() if key != "extra_body"},
        **(params.get("extra_body") or {}),
    }


def sent(provider, model, level):
    """The fields a check of *level* adds to its request, as runs add them
    once it passed, as JSON text such as `"reasoning_effort": "low"`."""
    return json.dumps(flat(apply({}, provider, model, level, trial(level))))[1:-1]


def unsampled(params):
    """Reasoning models refuse sampling settings beside an effort; Gemini,
    and a model whose thinking is off, take them."""
    for field in ("temperature", "top_p", "frequency_penalty"):
        params.pop(field, None)


def apply(params, provider, model, level, listed=None):
    """*params* with *level* written in when the model takes it (``profile``)
    and unchanged otherwise, so an unknown level never reaches a provider."""
    resolved = profile(provider, model, listed)
    if level is None or level not in resolved["levels"]:
        return params
    params = dict(params)
    if provider == "anthropic":
        if level == "none":
            if resolved["off"] is None:
                return params
            params["thinking"] = {"type": resolved["off"]}
        else:
            # A model without adaptive thinking takes the effort alone.
            if resolved["adaptive"]:
                params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {
                **params.get("output_config", {}),
                "effort": level,
            }
            unsampled(params)
        return params
    extra = dict(params.get("extra_body") or {})
    if provider == "openrouter":
        extra["reasoning"] = {"effort": level}
        unsampled(params)
    elif level == "none" and provider in ("deepseek", "kimi"):
        # Both turn thinking off with their `thinking` field.
        extra["thinking"] = {"type": "disabled"}
    else:
        params["reasoning_effort"] = level
        if provider != "gemini":
            unsampled(params)
        else:
            # A thinking budget beside reasoning_effort is refused.
            inner = {**extra.get("extra_body", {})}
            google = {
                key: value
                for key, value in inner.get("google", {}).items()
                if key != "thinking_config"
            }
            inner = {key: value for key, value in inner.items() if key != "google"}
            if google:
                inner["google"] = google
            extra = {key: value for key, value in extra.items() if key != "extra_body"}
            if inner:
                extra["extra_body"] = inner
    if extra:
        params["extra_body"] = extra
    else:
        params.pop("extra_body", None)
    return params


# Models that think when no effort is sent, for those whose default level
# the table does not name: billed as output an estimate cannot predict.
# Claude Opus, Sonnet and Haiku 5 and up, Fable and Mythos think when a
# request omits ``thinking``; matched from the start of the Claude name
# (provider_costs.claude_model_name), in any host's form.
_CLAUDE_THINKS_BY_DEFAULT = re.compile(
    r"claude-(?:(?:opus|sonnet|haiku)-(?:[5-9]|[1-9]\d)\b|fable|mythos)"
)
_THINKS_BY_DEFAULT = re.compile(
    # Kimi K3 always thinks; K2.6 and K2.7 Code think unless told not to.
    r"kimi-k(?:3|2\.[67])"
    # DeepSeek's Flash and V4 models think unless told not to; its reasoner
    # always does.
    r"|deepseek-(?:flash|v4|reasoner)",
    re.IGNORECASE,
)


def thinks(provider, model, level=None, listed=None):
    """Whether requests at *level* (None: the provider's default) make the
    model think, billing tokens an estimate leaves out. *provider* is the
    engine's Batch provider name, which is the connection's identity for
    every provider the table holds."""
    resolved = profile(provider, model, listed)
    if level is None or level not in resolved["levels"]:
        level = resolved["default"]
    elif provider == "anthropic" and not resolved["adaptive"]:
        # Sent alone, the effort turns no thinking on.
        return False
    if level is not None:
        return level != "none"
    from util.provider_costs import claude_model_name

    normalized = model_id(model)
    claude = claude_model_name(normalized)
    if claude is not None:
        return bool(_CLAUDE_THINKS_BY_DEFAULT.match(claude))
    return (provider == "gemini" and normalized.startswith("gemini-3")) or bool(
        _THINKS_BY_DEFAULT.search(normalized)
    )


# How a run reads its provider's refusal of its thinking effort, frozen
# beside the effort it sends (``frozen``): by ``refuses``, the rule Check an
# effort reads a server's reply by too. A run frozen before it reads one as
# it did when approved (``rejected``).
REFUSALS = "effort-refusals-v1"
# What a refusal of the effort says: it names the effort or how thinking is
# turned on or off, or that the model doesn't take reasoning or thinking, or
# only works with it ...
_REFUSED = re.compile(
    r"effort|thinking[._ ]type|between_tools"
    r"|\b(?:reasoning|thinking)\b[^.]*\b(?:not supported|unsupported|not available"
    r"|unrecognized|unknown|not allowed|not permitted|extra|invalid|disabled"
    r"|adaptive|mandatory|cannot be)"
    r"|\b(?:not support|doesn't support|don't support|unsupported|unrecognized"
    r"|unknown|only (?:works|supports?)|requires?)\b[^.]*\b(?:reasoning|thinking)\b",
    re.IGNORECASE,
)
# ... once another limit that mentions them, such as a thinking budget or
# reasoning tokens running out, is left out. Other errors that mention
# reasoning or thinking, such as a missing thinking block in a reply sent
# back, are no refusal of the level.
_LIMIT = re.compile(
    r"(?:reasoning|thinking)[._ -]?(?:budget\w*|tokens?)\b|budget_tokens",
    re.IGNORECASE,
)
# A Batch row's error or an engine's wrapped one names its status in its
# text, or the refusal by its type.
_STATUS = re.compile(r"\b(?:400|422)\b|invalid_request", re.IGNORECASE)
# Runs frozen before REFUSALS: an HTTP 400 naming the effort field itself or
# how thinking is turned on or off.
_EARLIER_REFUSAL = re.compile(
    r"effort|thinking[._ ]type|between_tools|thinking[^.]*\b(?:disabled|adaptive)\b",
    re.IGNORECASE,
)
_EARLIER_STATUS = re.compile(r"\b400\b|invalid_request", re.IGNORECASE)


# An HTTP 400 that says the reply reached its output cap before it finished,
# as OpenAI answers a check whose reasoning outruns CHECK_TOKENS
# (settings/providers): the server took the request, its effort included.
_CAPPED = re.compile(
    r"\bmax_tokens or model output limit was reached\b",
    re.IGNORECASE,
)


def capped(status, text):
    """Whether a provider's HTTP 400 *text* says the reply reached its output
    cap, which shows the server took the request and its effort; Check an
    effort reads it as accepted, and it never refuses the effort
    (``refuses``)."""
    return status == 400 and bool(_CAPPED.search(text))


def refuses(status, text):
    """Whether a provider's error refused a request for its thinking effort:
    HTTP 400 or 422, which providers don't bill, whose *text* refuses the
    effort, reasoning or thinking itself (``_REFUSED``). With *status* None,
    *text* names it, as a Batch row's error does."""
    refused = status in (400, 422) if status is not None else bool(_STATUS.search(text))
    return (
        refused
        and not capped(status, text)
        and bool(_REFUSED.search(_LIMIT.sub(" ", text)))
    )


def rejected(error, level, rule=None):
    """Whether a run that sends *level* got *error* as its provider's refusal
    of it, by the refusal *rule* the run froze (``REFUSALS``); a run frozen
    without one counts only an HTTP 400 naming the effort field itself or
    how thinking is turned on or off, as it did when approved."""
    if level is None:
        return False
    status = getattr(error, "status_code", None)
    status = status if type(status) is int else None
    text = str(error)
    if rule == REFUSALS:
        return refuses(status, text)
    return (status == 400 or bool(_EARLIER_STATUS.search(text))) and bool(
        _EARLIER_REFUSAL.search(text)
    )


def rejection(model, level):
    """The one message a run stops with when its provider refuses its
    effort; a refused request is not billed."""
    return (
        f"{model} refused thinking effort {label(level)}. Choose another "
        "Thinking effort for this model in Settings, under Advanced model options, "
        "then start the run again. Refused requests are not billed."
    )
