"""Omit legacy generation overrides that the app's preferences do not expose."""

from functools import partial
from inspect import signature

from dazedtl.settings import effort
from dazedtl.settings.preferences import GENERATION_PARAMETERS, output_tokens
from dazedtl.settings.providers import openrouter_host as validate_host


def provider_defaults(params, policy):
    if policy is None:
        return params
    if policy != GENERATION_PARAMETERS:
        raise ValueError("This run's saved generation parameter policy is unsupported.")
    # These values come from native defaults, not explicit model preferences.
    # Omission delegates to the provider without guessing a model's capabilities.
    return {
        key: value
        for key, value in params.items()
        if key not in {"temperature", "frequency_penalty", "reasoning_effort"}
    }


def thinking(params, configuration, provider):
    """*params* with the thinking effort a run froze (settings/effort), which
    replaces the provider default the policy above leaves; a run frozen
    without one sends exactly what it sent before."""
    return effort.apply(
        params, provider, configuration["model"], configuration.get("thinkingEffort")
    )


def refusal(translation, level, native, *args, **kwargs):
    """A Guided Live request, which stops the run with one plain message
    when the provider refuses the run's thinking effort: every later request
    carries the same effort, and sending it without one would change what
    the user chose."""
    try:
        return native(*args, **kwargs)
    except Exception as error:
        if effort.rejected(error, level):
            model = kwargs.get("model") or (args[5] if len(args) > 5 else "")
            raise translation.RunRefusedError(effort.rejection(model, level)) from error
        raise


def host_routing(params, host):
    host = validate_host(host)
    if not host:
        return params
    return {
        **params,
        "extra_body": {
            **params.get("extra_body", {}),
            "provider": {
                **params.get("extra_body", {}).get("provider", {}),
                "only": [host],
                "allow_fallbacks": False,
            },
        },
    }


def structured_output(params, schema, *, name="translation_response", live=True):
    params = {
        **params,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
    }
    if live:
        params["extra_body"] = {
            **params.get("extra_body", {}),
            "provider": {
                **params.get("extra_body", {}).get("provider", {}),
                "require_parameters": True,
            },
        }
    return params


def batch_routing(params, policy):
    if not policy or not policy.get("structuredOutputs"):
        raise ValueError(
            "Check this connection to verify structured-output Batch endpoints before preparing work."
        )
    from dazedtl.settings.openrouter import validate_policy

    validate_policy(policy, params["model"])
    return {
        **params,
        "extra_body": {
            **params.get("extra_body", {}),
            "provider": {"only": list(policy["providers"]), "allow_fallbacks": False},
        },
    }


def completion_budget(params, allowance):
    if output_tokens(allowance) is None:
        return params
    key = "max_completion_tokens" if "max_completion_tokens" in params else "max_tokens"
    return {**params, key: allowance}


LAYER = "request-parameters"
EFFORT_LAYER = "thinking-effort"


def named_effort(provider, level, native, *args, **kwargs):
    value = native(*args, **kwargs)
    if not isinstance(value, dict) or not value.get("model"):
        return value
    return {**value, "thinking_effort": effort.summary(provider, value["model"], level)}


def configure_builders(
    translation,
    policy,
    record=None,
    *,
    openrouter_host="",
    max_output_tokens=None,
    structured_outputs=False,
    batch=False,
    openrouter_batch=None,
    provider=None,
    thinking_effort=None,
):
    """Layers the run's frozen request policy over the engine's builders.
    *provider* is the connection's identity (settings/providers), which
    decides how *thinking_effort* is written."""
    output_tokens(max_output_tokens)
    effort.checked(thinking_effort)
    # Each estimate names the effort the run sends, for its review.
    for point in (translation.estimateCostComparison, translation.estimateBatchCost):
        if policy is None:
            point.remove(EFFORT_LAYER)
        else:
            point.layer(EFFORT_LAYER, partial(named_effort, provider, thinking_effort))
    if thinking_effort is None:
        translation.unestimatedThinking.remove(LAYER)
        translation.translateText.remove(LAYER)
    else:
        translation.translateText.layer(
            LAYER, partial(refusal, translation, thinking_effort)
        )
        # The estimate's note on unpredicted thinking follows the effort.
        translation.unestimatedThinking.layer(
            LAYER,
            lambda _native, _provider, model: effort.thinks(
                provider, model, thinking_effort
            ),
        )
    if max_output_tokens is None:
        translation._translation_completion_limit.remove(LAYER)
    else:
        # Mistral also calls this helper after building its SDK payload.
        # The policy belongs to one isolated worker, including file workers.
        translation._translation_completion_limit.layer(
            LAYER, lambda _native, *_args, **_kwargs: max_output_tokens
        )
    for name in ("buildOpenAIRequest", "buildClaudeRequest"):
        builder = getattr(translation, name)
        if (
            policy is None
            and not openrouter_host
            and max_output_tokens is None
            and not structured_outputs
            and thinking_effort is None
        ):
            builder.remove(LAYER)
            continue
        call_signature = signature(builder)

        def defaulted(native, *args, _name=name, _signature=call_signature, **kwargs):
            params = provider_defaults(native(*args, **kwargs), policy)
            params = completion_budget(params, max_output_tokens)
            if thinking_effort is not None:
                params = effort.apply(
                    params, provider, params["model"], thinking_effort
                )
            if _name == "buildOpenAIRequest":
                # A Batch run translates new speaker names Live before any
                # Batch phase starts; OpenRouter's Live route refuses the
                # Batch endpoint pin.
                queued = batch and translation.get_batch_phase() is not None
                if structured_outputs:
                    arguments = _signature.bind(*args, **kwargs).arguments
                    if (
                        arguments.get("formatType") == "json"
                        and arguments.get("numLines") is not None
                    ):
                        params = structured_output(
                            params,
                            translation.createTranslationSchema(arguments["numLines"]),
                            live=not queued,
                        )
                params = host_routing(params, openrouter_host)
                if structured_outputs and queued:
                    params = batch_routing(params, openrouter_batch)
            if record is not None:
                record(params)
            return params

        builder.layer(LAYER, defaulted)
