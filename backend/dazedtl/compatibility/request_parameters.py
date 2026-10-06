"""Omit legacy generation overrides that the app's preferences do not expose."""

from inspect import signature

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
):

    output_tokens(max_output_tokens)
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
        ):
            builder.remove(LAYER)
            continue
        call_signature = signature(builder)

        def defaulted(native, *args, _name=name, _signature=call_signature, **kwargs):
            params = provider_defaults(native(*args, **kwargs), policy)
            params = completion_budget(params, max_output_tokens)
            if _name == "buildOpenAIRequest":
                if structured_outputs:
                    arguments = _signature.bind(*args, **kwargs).arguments
                    if (
                        arguments.get("formatType") == "json"
                        and arguments.get("numLines") is not None
                    ):
                        params = structured_output(
                            params,
                            translation.createTranslationSchema(arguments["numLines"]),
                            live=not batch,
                        )
                params = host_routing(params, openrouter_host)
                if structured_outputs and batch:
                    params = batch_routing(params, openrouter_batch)
            if record is not None:
                record(params)
            return params

        builder.layer(LAYER, defaulted)
