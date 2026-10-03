"""Omit legacy generation overrides that the app's preferences do not expose."""

from functools import wraps

from dazedtl.settings.preferences import GENERATION_PARAMETERS


def provider_defaults(params, policy):
    if policy is None:
        return params
    if policy != GENERATION_PARAMETERS:
        raise ValueError("This run's saved generation parameter policy is unsupported.")
    # These values come from native defaults, not explicit model preferences.
    # Omission delegates to the provider without guessing a model's capabilities.
    return {key: value for key, value in params.items()
            if key not in {"temperature", "frequency_penalty", "reasoning_effort"}}


def configure_builders(translation, policy, record=None):
    for name in ("buildOpenAIRequest", "buildClaudeRequest"):
        builder = getattr(translation, name)
        if getattr(builder, "_dazedtl_provider_defaults", False):
            builder = builder.__wrapped__
        if policy is not None:
            @wraps(builder)
            def defaulted(*args, _builder=builder, **kwargs):
                params = provider_defaults(_builder(*args, **kwargs), policy)
                if record is not None:
                    record(params)
                return params
            defaulted._dazedtl_provider_defaults = True
            builder = defaulted
        setattr(translation, name, builder)
