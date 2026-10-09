"""Frozen public execution choices and worker-only credential resolution."""

from dazedtl.translation.files import read_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

from . import openrouter, preferences, providers


def connection_summary(settings):
    """Expose only the saved selection; drafts and credentials stay private."""
    connection = settings._connection(settings._read())
    return {key: connection[key] for key in ("name", "model")} if connection else None


def configuration(settings, mode, *, cached_only=False):
    state = settings._read()
    language = state["values"]["language"]
    if mode == "agent":
        return {
            "mode": mode,
            "language": language,
            "model": "",
            "connection_id": "",
            "entries_per_request": None,
        }
    connection = settings._connection(state)
    if not settings._configured(connection) or not connection["model"].strip():
        raise ValueError(
            "Choose a connection and model in Settings before preparing API requests."
        )
    selected = connection["model_options"].get(
        connection["model"], preferences.DEFAULT_OPTIONS
    )
    defaults = settings.model_defaults(
        connection["id"],
        connection["model"],
        cached_only=cached_only or selected["pricing"] == "custom",
    )
    input_rate = (
        selected["inputRate"]
        if selected["pricing"] == "custom"
        else defaults["inputRate"]
    )
    output_rate = (
        selected["outputRate"]
        if selected["pricing"] == "custom"
        else defaults["outputRate"]
    )
    if input_rate is None or output_rate is None:
        raise ValueError(
            "Model pricing is unknown. Set explicit rates in Settings before estimating."
        )
    value = {
        "mode": mode,
        "language": language,
        "model": connection["model"],
        "connection_id": connection["id"],
        "provider": connection["provider"],
        "protocol": connection["protocol"],
        "endpoint": providers.address(connection),
        "organization": connection["organization"],
        "generationParameters": preferences.GENERATION_PARAMETERS,
        "maxOutputTokens": preferences.output_allowance(
            selected.get("maxOutputTokens"), defaults.get("maxOutputTokens")
        ),
        "refusalRetry": REFUSAL_POLICY,
        "entries_per_request": selected["entriesPerRequest"]
        or preferences.DEFAULT_ENTRIES_PER_REQUEST,
        "rates": {
            "input": input_rate,
            "output": output_rate,
            "batch_factor": None,
            "source": "custom"
            if selected["pricing"] == "custom"
            else defaults["source"],
        },
    }
    if connection["provider"] == "openrouter":
        value["openrouterStructuredOutputs"] = openrouter.STRUCTURED_OUTPUTS
        policy = openrouter.policy(
            connection, connection["model"], selected, required=mode == "batch"
        )
        value["openrouterBatch"] = policy
        if policy:
            value["rates"].update(
                batch_input=policy["input"], batch_output=policy["output"]
            )
            if mode == "batch":
                value["maxOutputTokens"] = preferences.output_allowance(
                    value["maxOutputTokens"], policy.get("max_output")
                )
    if (
        connection["provider"] == "openai"
        or selected.get("batchInputTokens") is not None
    ):
        value["batchInputTokens"] = (
            preferences.batch_input_tokens(selected.get("batchInputTokens"))
            or preferences.DEFAULT_BATCH_INPUT_TOKENS
        )
    if connection["provider"] == "openrouter" and connection.get("openrouter_host"):
        value["openrouterHost"] = connection["openrouter_host"]
    # Keep the same route validation as the preserved engine before building requests.
    settings.adapter.validate_route(
        {
            "model": value["model"],
            "API_PROVIDER": value["protocol"],
            "api": value["endpoint"],
        }
    )
    return value


def worker_secret(workspace, frozen):
    value = read_json(workspace / "settings/settings.json", limit=8_000_000)
    if value.get("version") != 2:
        raise ValueError("Open this workspace in DazedTL before resuming the run.")
    connection = next(
        (
            item
            for item in value.get("connections", [])
            if item.get("id") == frozen["connection_id"]
        ),
        None,
    )
    if not connection:
        raise ValueError(
            "Restore the saved run's connection in Settings before resuming."
        )
    if (
        not isinstance(connection.get("secret"), str)
        or type(connection.get("keyless")) is not bool
    ):
        raise ValueError(
            "The saved connection's credential fields are invalid. Restore them in Settings."
        )
    expected = (
        frozen["provider"],
        providers.route(frozen["protocol"], frozen["endpoint"]),
        frozen["organization"],
    )
    actual = (
        connection["provider"],
        providers.route(connection["protocol"], providers.address(connection)),
        connection["organization"],
    )
    if actual != expected or not (connection["secret"] or connection["keyless"]):
        raise ValueError(
            "The saved run's connection changed. Restore its provider and endpoint before resuming."
        )
    return connection["secret"]
