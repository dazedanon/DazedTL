"""Frozen public execution choices and worker-only credential resolution."""

from typing import NamedTuple

from dazedtl.translation.files import read_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

from . import effort, language_pair, opencode, openrouter, preferences, providers


def connection_summary(settings):
    """Expose only the saved selection; drafts and credentials stay private."""
    connection = settings._connection(settings._read())
    return {key: connection[key] for key in ("name", "model")} if connection else None


def batch_reasons(settings):
    """Why the active connection cannot run Batch, and why whether it can
    isn't read yet, such as after a failed check (openrouter.Unread), each
    "" otherwise. Both workflows keep Batch until they know it can't run,
    so both are "" while no connection with a key and a model is chosen,
    and the second shows beside the method choice and in place of a Batch
    figure while Batch waits and Live goes ahead (openrouter.UNREAD)."""
    if not (settings.connection_summary() or {}).get("model"):
        return "", ""
    defaults = settings.translation_defaults()
    if not defaults.get("model") or defaults.get("batch_supported"):
        return "", ""
    if not defaults.get("batch_looked_up", True):
        return "", defaults.get("batch_reason", "")
    return defaults.get("batch_reason") or "This connection can't run Batch.", ""


def batch_unavailable(settings):
    """Why the active connection cannot run Batch (``batch_reasons``)."""
    return batch_reasons(settings)[0]


def runnable_mode(settings, mode, live):
    """The method a saved `mode` runs in: Batch on a connection that cannot
    run it is Live, named `live` by the workflow. The saved choice stays, so
    a connection that runs Batch brings it back; the page reads drafts the
    same way (app/src/features/translation/runnableMode.ts)."""
    return live if mode == "batch" and batch_unavailable(settings) else mode


def _entries(options):
    return options["entriesPerRequest"] or preferences.DEFAULT_ENTRIES_PER_REQUEST


def entries_per_request(settings):
    """The active model's entries per request, or the default without a
    connection, so requests organized in any mode also fit a later API run."""
    connection = settings._connection(settings._read())
    return _entries(
        connection["model_options"].get(
            connection["model"], preferences.DEFAULT_OPTIONS
        )
        if connection
        else preferences.DEFAULT_OPTIONS
    )


# What a model's looked-up defaults decide, which a snapshot reading cached
# prices only may not know yet.
LOOKED_UP = ("rates", "maxOutputTokens", "openrouterBatch", openrouter.UNREAD)


class Choice(NamedTuple):
    """A saved connection and model other than the active ones, and the
    model options a comparison sends in place of its saved ones, such as a
    thinking effort (preferences.DEFAULT_OPTIONS keys)."""

    connection_id: str
    model: str
    options: dict | None = None


class _Frozen(NamedTuple):
    """What a new run freezes from the active connection, read once for both
    shapes it is saved in (``configuration`` and ``request_policy``)."""

    connection: dict
    entries: int
    max_output: int | None
    effort: dict
    rates: dict
    updated_at: str | None
    batch: dict | None
    # The request settings both shapes end with, in order.
    requests: dict


def _frozen(settings, mode, *, cached_only, unpriced, choice=None):
    """An OpenRouter Batch policy no lookup could read yet
    (openrouter.Unread) is frozen as not read yet in a Live mode, and a Batch
    refuses it before anything else is priced (openrouter.frozen).
    ``unpriced`` reads unknown rates instead of refusing, and leaves such a
    Batch's policy out. ``choice`` reads another saved connection and model
    than the active ones, with its own options over the model's saved
    ones (``Choice``), as a model comparison sends them."""
    state = settings._read()
    connection = settings._connection(state, choice.connection_id if choice else None)
    if choice and connection is None:
        raise ValueError("That connection is no longer in Settings.")
    model = choice.model if choice else (connection or {}).get("model", "")
    if not settings._configured(connection) or not model.strip():
        raise ValueError(
            "Choose a connection and model in Settings before preparing API requests."
        )
    # The preserved engine's route validation, before anything is priced.
    settings.adapter.validate_route(
        {
            "model": model,
            "API_PROVIDER": connection["protocol"],
            "api": providers.address(connection),
        }
    )
    providers.validate_model_name(model, providers.address(connection))
    selected = connection["model_options"].get(model, preferences.DEFAULT_OPTIONS)
    if choice and choice.options:
        selected = {**selected, **choice.options}
    custom = selected["pricing"] == "custom"
    batch = {}
    if connection["provider"] == "openrouter":
        try:
            batch = openrouter.frozen(
                connection, model, selected, required=mode == "batch"
            )
        except openrouter.Unread:
            if not unpriced:
                raise
    defaults = (
        settings.connection_defaults(
            connection, model, cached_only=cached_only or custom
        )
        if choice
        else settings.model_defaults(
            connection["id"], model, cached_only=cached_only or custom
        )
    )
    # Cached defaults are empty until the model's prices are first looked up.
    rates = {
        "input": selected["inputRate"] if custom else defaults.get("inputRate"),
        "output": selected["outputRate"] if custom else defaults.get("outputRate"),
        "source": "custom" if custom else defaults.get("source"),
    }
    # The route's own cache read price, where it lists one per model.
    read = opencode.cache_read_multiple(connection, model)
    if read is not None:
        rates["cache_read_multiple"] = read
    if (rates["input"] is None or rates["output"] is None) and not unpriced:
        raise ValueError(
            "No price is available for this model. Enter custom rates in Settings; use 0 for a free model."
        )
    max_output = preferences.output_allowance(
        selected.get("maxOutputTokens"), defaults.get("maxOutputTokens")
    )
    policy = batch.get("openrouterBatch")
    if policy and mode == "batch":
        max_output = preferences.output_allowance(max_output, policy.get("max_output"))
    requests = {}
    if connection["provider"] == "openrouter":
        requests["openrouterStructuredOutputs"] = openrouter.STRUCTURED_OUTPUTS
    # A Batch's policy not read yet stays out, so it reads as a price not
    # known rather than as no Batch (translation/repricing.priced).
    requests.update(batch)
    if (
        connection["provider"] == "openai"
        or selected.get("batchInputTokens") is not None
    ):
        requests["batchInputTokens"] = (
            preferences.batch_input_tokens(selected.get("batchInputTokens"))
            or preferences.DEFAULT_BATCH_INPUT_TOKENS
        )
    if connection["provider"] == "openrouter" and connection.get("openrouter_host"):
        requests["openrouterHost"] = connection["openrouter_host"]
    return _Frozen(
        connection=connection,
        entries=_entries(selected),
        max_output=max_output,
        effort=effort.frozen(
            connection["provider"], model, selected, effort.record(connection, model)
        ),
        rates=rates,
        updated_at=None if custom else defaults.get("updatedAt"),
        batch=policy,
        requests=requests,
    )


def configuration(
    settings, mode, *, cached_only=False, unpriced=False, pair=None, choice=None
):
    """The settings an estimate or an Assistant-led run freezes (``_frozen``),
    translating between the game's language *pair* (settings/language_pair),
    Japanese into Settings' target when none is given. ``unpriced`` returns
    them with unknown rates instead of refusing, for comparisons that read
    cached prices only."""
    languages = language_pair.frozen({}, pair or language_pair.default(settings))
    if mode == "agent":
        return {
            "mode": mode,
            **languages,
            "model": "",
            "connection_id": "",
            "entries_per_request": None,
        }
    read = _frozen(
        settings, mode, cached_only=cached_only, unpriced=unpriced, choice=choice
    )
    connection = read.connection
    rates = dict(read.rates)
    if read.batch:
        rates.update(batch_input=read.batch["input"], batch_output=read.batch["output"])
    return {
        "mode": mode,
        **languages,
        "model": choice.model if choice else connection["model"],
        "connection_id": connection["id"],
        "provider": connection["provider"],
        "protocol": connection["protocol"],
        "endpoint": providers.address(connection),
        "organization": connection["organization"],
        "generationParameters": preferences.GENERATION_PARAMETERS,
        "maxOutputTokens": read.max_output,
        **read.effort,
        "refusalRetry": REFUSAL_POLICY,
        "entries_per_request": read.entries,
        "rates": rates,
        **read.requests,
    }


def request_policy(settings, mode, choice=None):
    """The request policy a new Guided or image run's engine freezes into its
    plan: the settings ``configuration`` freezes (``_frozen``) with the
    policies only the engine reads."""
    read = _frozen(settings, mode, cached_only=False, unpriced=False, choice=choice)
    return {
        "version": 1,
        "model": choice.model if choice else read.connection["model"],
        "generationParameters": preferences.GENERATION_PARAMETERS,
        "maxOutputTokens": read.max_output,
        **read.effort,
        "refusalRetry": REFUSAL_POLICY,
        "stateGrouping": "compatible-states-v1",
        **preferences.FROZEN_POLICIES,
        **preferences.REPLY_POLICIES,
        "entriesPerRequest": read.entries,
        "inputRate": read.rates["input"],
        "outputRate": read.rates["output"],
        **(
            {"cacheReadMultiple": read.rates["cache_read_multiple"]}
            if "cache_read_multiple" in read.rates
            else {}
        ),
        "source": read.rates["source"],
        "updatedAt": read.updated_at,
        **read.requests,
    }


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
