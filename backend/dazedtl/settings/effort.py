"""Thinking effort: which efforts a model takes, what its provider uses when
none is sent, and how a choice is written into a request.

Settings, runs of both methods and the legacy evaluation all read this one
table. A request carries an effort only when its provider, its exact model ID
and the level are a row here; every other request sends nothing, exactly as
runs did before the choice existed, so no run sends a level its provider
does not document; a run whose provider refuses its level anyway stops with
one message (``rejection``). The table is checked where a choice is saved
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
Custom and local servers send nothing: DazedTL cannot know what they accept.

The engine builders' own efforts (``buildOpenAIRequest`` in
engine/util/translation.py: "low" for GPT-6 Astra, "none" for other GPT-6 and
GPT-5.6, "minimal" for older GPT-5) belong to runs frozen without a request
policy (before 2026-10-03); they still send them, byte for byte, because
``request_parameters.provider_defaults`` leaves those runs alone.
"""

import re

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

_FULL = ("low", "medium", "high", "xhigh", "max")
_OFF_FULL = ("none", *_FULL)
_OLD_CLAUDE = ("none", "low", "medium", "high", "max")
_GPT5 = ("none", "low", "medium", "high", "xhigh")
_LMH = ("low", "medium", "high")
_MLMH = ("minimal", *_LMH)

# provider -> exact model ID -> (levels it takes, the level its provider
# uses when none is sent, or None when its docs don't say).
_NATIVE = {
    # Opus 5.5, Fable and Mythos always think. Opus 5, Sonnet 5.5 and Haiku
    # 5.5 turn thinking off only at effort high or below, which their
    # defaults are, so "Off" turns thinking off with no level. Omitting thinking on Opus
    # 4.8/4.7/4.6 and Sonnet 4.6 means no thinking. Haiku 4.5 and older
    # take a thinking budget, not an effort.
    "anthropic": {
        "claude-opus-5-5": (_FULL, "medium"),
        "claude-opus-5": (_OFF_FULL, "high"),
        "claude-opus-4-8": (_OFF_FULL, "none"),
        "claude-opus-4-7": (_OFF_FULL, "none"),
        "claude-opus-4-6": (_OLD_CLAUDE, "none"),
        "claude-sonnet-5-5": (_OFF_FULL, "high"),
        "claude-sonnet-5": (_OFF_FULL, "high"),
        "claude-sonnet-4-6": (_OLD_CLAUDE, "none"),
        "claude-haiku-5-5": (_OFF_FULL, "medium"),
        "claude-fable-5-1": (_FULL, "high"),
        "claude-fable-5": (_FULL, "high"),
        "claude-mythos-5-1": (_FULL, "high"),
        "claude-mythos-5": (_FULL, "high"),
    },
    # GPT-4.x and other models without reasoning take none.
    "openai": {
        "gpt-6.1-sol": (_FULL, "medium"),
        "gpt-6.1-terra": (_OFF_FULL, "medium"),
        "gpt-6-astra": (_FULL, None),
        "gpt-6-sol": (_OFF_FULL, "medium"),
        "gpt-6-luna": (_OFF_FULL, "medium"),
        "gpt-5.6-sol": (_OFF_FULL, "medium"),
        "gpt-5.6-terra": (_OFF_FULL, "medium"),
        "gpt-5.6-luna": (_OFF_FULL, "medium"),
        "gpt-5.5": (_GPT5, "medium"),
        "gpt-5.4": (_GPT5, "none"),
        "gpt-5.2": (_GPT5, "none"),
        "gpt-5.1": (("none", *_LMH), "none"),
        "gpt-5": (_MLMH, None),
    },
    # Only levels each model's own thinking levels hold, since the
    # endpoint's mapping of the others is not documented. Thinking can be
    # turned off only on the 2.5 Flash models.
    "gemini": {
        "gemini-4-argon": (_LMH, "medium"),
        "gemini-3.8-flash": (_LMH, "medium"),
        "gemini-3.6-flash": (_MLMH, "medium"),
        "gemini-3.5-flash-lite": (_MLMH, "minimal"),
        "gemini-3.1-pro-preview": (_LMH, "high"),
        "gemini-3-pro-preview": (("low", "high"), "high"),
        "gemini-3-flash-preview": (_MLMH, "high"),
        "gemini-2.5-pro": (_LMH, None),
        "gemini-2.5-flash": (("none", *_LMH), None),
        "gemini-2.5-flash-lite": (("none", *_LMH), "none"),
    },
    # Its other levels are mapped to these four, so only these are offered.
    "deepseek": {
        "deepseek-flash": (("none", "low", "high", "max"), "high"),
        "deepseek-v4-pro": (("none", "low", "high", "max"), "high"),
        "deepseek-v4-flash": (("none", "low", "high", "max"), "high"),
    },
    # The K3 series always thinks; K2.6 only turns thinking on or off, and
    # K2.7 Code only thinks.
    "kimi": {
        "kimi-k3": (("low", "high", "max"), "max"),
        "kimi-k3.1-pro": (("low", "high", "max"), "max"),
        "kimi-k3.1-pro-highspeed": (("low", "high", "max"), "max"),
        "kimi-k2.6": (("none",), None),
    },
    # The docs name only these levels for these models.
    "mistral": {
        "mistral-small-latest": (("none", "high"), None),
        "mistral-medium-3-5": (("none", "high"), None),
        "mistral-large-4-0": (("none", "high"), None),
        "zai-glm-5-3": (("low", "high", "max"), None),
    },
}

# OpenRouter maps a level a model does not list to the nearest one it
# lists, silently, so a routed model offers only the levels both its own
# provider's row and OpenRouter's model list hold. Each row is the routed
# model's own (provider, model), then OpenRouter's supported_efforts and the
# level OpenRouter applies when none is sent ("none" where its list says
# reasoning is off by default), read from its public model list. The default
# shown is the one both sources agree on, or the only one stated. Every
# OpenRouter endpoint of these models that takes structured outputs also
# takes `reasoning`, so `provider.require_parameters` routes as before.
_OPENROUTER = {
    "anthropic/claude-opus-5.5": ("anthropic", "claude-opus-5-5", _FULL, "high"),
    "anthropic/claude-opus-5": ("anthropic", "claude-opus-5", _OFF_FULL, "high"),
    "anthropic/claude-opus-4.8": ("anthropic", "claude-opus-4-8", _OFF_FULL, "none"),
    "anthropic/claude-opus-4.7": ("anthropic", "claude-opus-4-7", _OFF_FULL, "none"),
    "anthropic/claude-opus-4.6": ("anthropic", "claude-opus-4-6", _OLD_CLAUDE, "none"),
    "anthropic/claude-sonnet-5.5": ("anthropic", "claude-sonnet-5-5", _FULL, "high"),
    "anthropic/claude-sonnet-5": ("anthropic", "claude-sonnet-5", _OFF_FULL, "high"),
    "anthropic/claude-sonnet-4.6": (
        "anthropic",
        "claude-sonnet-4-6",
        _OLD_CLAUDE,
        "medium",
    ),
    "anthropic/claude-haiku-5.5": (
        "anthropic",
        "claude-haiku-5-5",
        _OFF_FULL,
        "medium",
    ),
    "anthropic/claude-fable-5.1": ("anthropic", "claude-fable-5-1", _FULL, "high"),
    "anthropic/claude-fable-5": ("anthropic", "claude-fable-5", _FULL, "high"),
    "openai/gpt-6.1-sol": ("openai", "gpt-6.1-sol", _FULL, "medium"),
    "openai/gpt-6.1-terra": ("openai", "gpt-6.1-terra", _OFF_FULL, "medium"),
    "openai/gpt-6-astra": ("openai", "gpt-6-astra", _FULL, "medium"),
    "openai/gpt-6-sol": ("openai", "gpt-6-sol", _OFF_FULL, "medium"),
    "openai/gpt-6-luna": ("openai", "gpt-6-luna", _OFF_FULL, "medium"),
    "openai/gpt-5.6-sol": ("openai", "gpt-5.6-sol", _OFF_FULL, "medium"),
    "openai/gpt-5.6-terra": ("openai", "gpt-5.6-terra", _OFF_FULL, "medium"),
    "openai/gpt-5.6-luna": ("openai", "gpt-5.6-luna", _OFF_FULL, "medium"),
    "openai/gpt-5.5": ("openai", "gpt-5.5", _GPT5, "medium"),
    "openai/gpt-5.4": ("openai", "gpt-5.4", _GPT5, "none"),
    "openai/gpt-5.2": ("openai", "gpt-5.2", _GPT5, "medium"),
    "openai/gpt-5.1": ("openai", "gpt-5.1", ("none", *_LMH), "none"),
    "openai/gpt-5": ("openai", "gpt-5", _MLMH, "medium"),
    "google/gemini-4-argon": ("gemini", "gemini-4-argon", _LMH, "medium"),
    "google/gemini-3.8-flash": ("gemini", "gemini-3.8-flash", _LMH, "medium"),
    "google/gemini-3.6-flash": ("gemini", "gemini-3.6-flash", _MLMH, "medium"),
    "google/gemini-3.5-flash-lite": (
        "gemini",
        "gemini-3.5-flash-lite",
        _MLMH,
        "minimal",
    ),
    "google/gemini-3.1-pro-preview": (
        "gemini",
        "gemini-3.1-pro-preview",
        _LMH,
        "medium",
    ),
    "google/gemini-3-flash-preview": (
        "gemini",
        "gemini-3-flash-preview",
        ("none", *_MLMH),
        "medium",
    ),
    "moonshotai/kimi-k3": ("kimi", "kimi-k3", ("none", "low", "high", "max"), "max"),
    "moonshotai/kimi-k3.1-pro": (
        "kimi",
        "kimi-k3.1-pro",
        ("none", "low", "high", "max"),
        "max",
    ),
    "deepseek/deepseek-v4-pro": (
        "deepseek",
        "deepseek-v4-pro",
        ("none", "high", "xhigh"),
        "high",
    ),
    "deepseek/deepseek-v4-flash": (
        "deepseek",
        "deepseek-v4-flash",
        ("none", "high", "xhigh"),
        "high",
    ),
    "mistralai/mistral-large-4-0": (
        "mistral",
        "mistral-large-4-0",
        ("none", "high"),
        "high",
    ),
    "mistralai/mistral-medium-3-5": (
        "mistral",
        "mistral-medium-3-5",
        ("none", "high"),
        "high",
    ),
}


def _routed(model):
    own_provider, own_model, listed, listed_default = _OPENROUTER[model]
    levels, own_default = _NATIVE[own_provider][own_model]
    default = (
        own_default
        if listed_default in (own_default, None)
        else listed_default
        if own_default is None
        else None
    )
    return tuple(level for level in levels if level in listed), default


def model_id(model):
    """The ID the table knows a model by: Gemini's optional `models/` prefix
    left out, in lower case; nothing else is matched loosely."""
    return str(model or "").strip().lower().removeprefix("models/")


def profile(provider, model):
    """(levels, provider default) for a connection's provider identity
    (settings/providers PROVIDERS) and model: no levels for a model or
    provider the table doesn't know, whose default is unknown too."""
    model = model_id(model)
    if provider == "openrouter":
        return _routed(model) if model in _OPENROUTER else ((), None)
    return _NATIVE.get(provider, {}).get(model, ((), None))


def levels(provider, model):
    return profile(provider, model)[0]


def takes(provider, model, level):
    """Whether a request to *model* on *provider* may carry *level*."""
    return level in levels(provider, model)


def checked(level):
    """A saved or frozen level, which must be one of LEVELS or None."""
    if level is not None and level not in LEVELS:
        raise ValueError("Choose a thinking effort from the list.")
    return level


def chosen(provider, model, level):
    """The level a new run freezes for a saved choice: the choice while the
    model takes it, else None, which leaves the effort to the provider."""
    return level if level is not None and takes(provider, model, level) else None


def frozen(provider, model, options):
    """What a new run freezes for a model's saved options, beside its other
    request settings: nothing when it sends no effort, so runs that send none
    keep the settings, and estimates, they had before the choice existed."""
    level = chosen(provider, model, options.get("thinkingEffort"))
    return {} if level is None else {"thinkingEffort": level}


def label(level):
    return LABELS[level]


def summary(provider, model, level):
    """What a run sends, as the run summary names it: "Low", or
    "Provider default (Medium)" when it sends none."""
    if level is not None:
        return label(level)
    default = profile(provider, model)[1]
    return "Provider default" + (f" ({label(default)})" if default else "")


def describe(provider, model):
    """The choices Settings offers for a model: the provider default first,
    then each level the model takes."""
    return {
        "options": [
            {"value": None, "label": summary(provider, model, None)},
            *(
                {"value": level, "label": label(level)}
                for level in levels(provider, model)
            ),
        ]
    }


def unsampled(params):
    """Reasoning models refuse sampling settings beside an effort; Gemini,
    and a model whose thinking is off, take them."""
    for field in ("temperature", "top_p", "frequency_penalty"):
        params.pop(field, None)


def apply(params, provider, model, level):
    """*params* with *level* written in when it is a row of the table, and
    unchanged otherwise, so an unknown level never reaches a provider."""
    if level is None or not takes(provider, model, level):
        return params
    params = dict(params)
    if provider == "anthropic":
        if level == "none":
            # Sonnet 5.5 refuses "disabled"; it turns thinking off with
            # "between_tools", which takes no other field.
            params["thinking"] = {
                "type": "between_tools"
                if model_id(model) == "claude-sonnet-5-5"
                else "disabled"
            }
        else:
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
_THINKS_BY_DEFAULT = re.compile(
    # Claude Opus, Sonnet and Haiku 5 and up, Fable and Mythos think when a
    # request omits ``thinking``.
    r"claude-(?:(?:opus|sonnet|haiku)-(?:[5-9]|[1-9]\d)\b|fable|mythos)"
    # Kimi K3 always thinks; K2.6 and K2.7 Code think unless told not to.
    r"|kimi-k(?:3|2\.[67])"
    # DeepSeek's Flash and V4 models think unless told not to; its reasoner
    # always does.
    r"|deepseek-(?:flash|v4|reasoner)",
    re.IGNORECASE,
)


def thinks(provider, model, level=None):
    """Whether requests at *level* (None: the provider's default) make the
    model think, billing tokens an estimate leaves out. *provider* is the
    engine's Batch provider name, which is the connection's identity for
    every provider the table holds."""
    if level is None or not takes(provider, model, level):
        level = profile(provider, model)[1]
    if level is not None:
        return level != "none"
    normalized = model_id(model)
    return (provider == "gemini" and normalized.startswith("gemini-3")) or bool(
        _THINKS_BY_DEFAULT.search(normalized)
    )


# The effort field itself, not another limit that mentions thinking, such
# as a thinking budget or reasoning tokens running out.
_REJECTION = re.compile(
    r"effort|thinking[._ ]type|between_tools|thinking[^.]*\b(?:disabled|adaptive)\b",
    re.IGNORECASE,
)
# A Batch row names the refusal by its type rather than its status.
_BAD_REQUEST = re.compile(r"\b400\b|invalid_request", re.IGNORECASE)


def rejected(error, level):
    """Whether a provider refused a request (HTTP 400) for its effort: the
    run sent one and the refusal names the effort or how thinking is
    turned on or off."""
    if level is None:
        return False
    status = getattr(error, "status_code", None)
    text = str(error)
    return (status == 400 or bool(_BAD_REQUEST.search(text))) and bool(
        _REJECTION.search(text)
    )


def rejection(model, level):
    """The one message a run stops with when its provider refuses its
    effort; a refused request is not billed."""
    return (
        f"{model} refused thinking effort {label(level)}. Choose another "
        "Thinking effort for this model in Settings, under Model options, "
        "then start the run again. Refused requests are not billed."
    )
