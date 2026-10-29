"""Frozen public execution choices and worker-only credential resolution."""

from dazedtl.translation.files import read_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

from . import effort, language_pair, openrouter, preferences, providers


def connection_summary(settings):
    """Expose only the saved selection; drafts and credentials stay private."""
    connection = settings._connection(settings._read())
    return {key: connection[key] for key in ("name", "model")} if connection else None


def batch_unavailable(settings):
    """Why the active connection cannot run Batch, or "" when it can or no
    connection with a key and a model is chosen yet, as both workflows keep
    Batch until the user picks one."""
    if not (settings.connection_summary() or {}).get("model"):
        return ""
    defaults = settings.translation_defaults()
    if not defaults.get("model") or defaults.get("batch_supported"):
        return ""
    return defaults.get("batch_reason") or "This connection can't run Batch."


def runnable_mode(settings, mode, live):
    """The method a saved `mode` runs in: Batch on a connection that cannot
    run it is Live, named `live` by the workflow. The saved choice stays, so
    a connection that runs Batch brings it back; the page reads drafts the
    same way (app/src/features/translation/runnableMode.ts)."""
    return live if mode == "batch" and batch_unavailable(settings) else mode


def entries_per_request(settings):
    """The active model's entries per request, or the default without a
    connection, so requests organized in any mode also fit a later API run."""
    connection = settings._connection(settings._read())
    selected = (
        connection["model_options"].get(
            connection["model"], preferences.DEFAULT_OPTIONS
        )
        if connection
        else preferences.DEFAULT_OPTIONS
    )
    return selected["entriesPerRequest"] or preferences.DEFAULT_ENTRIES_PER_REQUEST


# What a model's looked-up defaults decide, which a snapshot reading cached
# prices only may not know yet.
LOOKED_UP = ("rates", "maxOutputTokens", "openrouterBatch")


def configuration(settings, mode, *, cached_only=False, unpriced=False, pair=None):
    """The settings a run freezes, translating between the game's language
    *pair* (settings/language_pair), Japanese into Settings' target when
    none is given. ``unpriced`` returns them with unknown rates instead of
    refusing, and leaves out an OpenRouter Batch policy not looked up yet,
    for comparisons that read cached prices only."""
    state = settings._read()
    languages = language_pair.frozen({}, pair or language_pair.default(settings))
    if mode == "agent":
        return {
            "mode": mode,
            **languages,
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
    # Cached defaults are empty until the model's prices are first looked up.
    input_rate = (
        selected["inputRate"]
        if selected["pricing"] == "custom"
        else defaults.get("inputRate")
    )
    output_rate = (
        selected["outputRate"]
        if selected["pricing"] == "custom"
        else defaults.get("outputRate")
    )
    if (input_rate is None or output_rate is None) and not unpriced:
        raise ValueError(
            "Model pricing is unknown. Set explicit rates in Settings before estimating."
        )
    value = {
        "mode": mode,
        **languages,
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
        **effort.frozen(
            connection["provider"],
            connection["model"],
            selected,
            effort.record(connection, connection["model"]),
        ),
        "refusalRetry": REFUSAL_POLICY,
        "entries_per_request": entries_per_request(settings),
        "rates": {
            "input": input_rate,
            "output": output_rate,
            "source": "custom"
            if selected["pricing"] == "custom"
            else defaults.get("source"),
        },
    }
    if connection["provider"] == "openrouter":
        value["openrouterStructuredOutputs"] = openrouter.STRUCTURED_OUTPUTS
    # Read with unknown rates, the settings leave the Batch policy out while
    # Batch availability isn't looked up, as after a failed check, so it reads
    # as not known rather than as no Batch (translation/repricing.priced).
    if connection["provider"] == "openrouter" and not (
        unpriced and not openrouter.batch_looked_up(connection, connection["model"])
    ):
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
    providers.validate_model_name(value["model"], value["endpoint"])
    return value


def saved_connections(workspace):
    """The connections Settings saved, read without the app's settings store
    by a worker or a reader outside it."""
    value = read_json(workspace / "settings/settings.json", limit=8_000_000)
    if value.get("version") != 3:
        raise ValueError("Open this workspace in DazedTL before resuming the run.")
    return [item for item in value.get("connections", []) if isinstance(item, dict)]


def worker_secret(workspace, frozen):
    connection = next(
        (
            item
            for item in saved_connections(workspace)
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


def connection_names(workspace):
    """Each saved connection's runtime name by its ID, none when Settings
    cannot be read: Guided plans name a connection by runtime name,
    Assistant-led configurations by ID."""
    try:
        connections = saved_connections(workspace)
    except OSError, ValueError:
        return {}
    return {item.get("id"): item.get("runtime_name") for item in connections}
