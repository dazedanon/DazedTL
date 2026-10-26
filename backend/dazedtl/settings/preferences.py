"""The supported preferences contract, independent of legacy engine settings."""

import math
from copy import deepcopy
from typing import cast

DEFAULT_ENTRIES_PER_REQUEST = 50
DEFAULT_OUTPUT_TOKENS = 32_768
# The default Batch input-token allowance for new OpenAI runs, which a
# connection or model can override in batchInputTokens. It leaves 20% headroom
# below the 500k Tier 1 Batch queue limit published for GPT-5.5 Pro
# (https://developers.openai.com/api/docs/models/gpt-5.5-pro), which is lower
# than the published GPT-6 Astra and GPT-6 Luna limits. It is a conservative
# fallback, not an account quota: older models can have lower limits, GPT-6.1
# Sol's public page does not list its Batch limit, other pending jobs share the
# queue, and account usage outside the tracked Guided runs still needs headroom
# because the local estimate is not a provider quota lookup. The frozen value
# becomes the Guided Batch window's combined active-token allowance, which
# clarification batches reserve from before they record submission intent.
# Older runs keep their native default or saved sequential limit.
DEFAULT_BATCH_INPUT_TOKENS = 400_000
# The request policies below are frozen into each new API run before it is
# estimated, so a policy joins the estimate's identity and applies to Live and
# Batch alike. A run frozen without one keeps its original parameters, parser
# behavior and request identities. The event policies are implemented by the
# engine's modules/rpgmakermvmz.py, which holds each one's full rule.
# The native engine's implicit temperature, frequency penalty and reasoning
# effort are omitted (compatibility/request_parameters), since model
# preferences expose no explicit override for them; the provider's defaults
# apply, without guessing a model's capabilities.
GENERATION_PARAMETERS = "provider-defaults-v1"
# Built-in menu choices are requested only on the first event pass, keeping
# their scene context, so the write pass cannot queue a duplicate during
# preparation or consume and retry a rejected choice again.
CHOICE_COLLECTION = "event-choices-once-v1"
# Already-translated code 101 nameplates still give dialogue context, unnamed
# messages clear the preceding speaker, and an implicit [Name] nameplate must
# pass short-name plausibility checks, so bracketed tutorial prose gets normal
# text instructions. Adjacent text with its own retained original stays a
# separate translation unit.
SPEAKER_CONTEXT = "event-speaker-context-v1"
# A nameplate sharing its line with the text, such as 【Name】：text or
# Name「text, is sent only as the [Speaker]: prefix, so the model does not
# write it into the message a second time.
SAME_LINE_SPEAKERS = "event-same-line-speakers-v1"
# Small RPG Maker event pages of one file share a request, each page labelled,
# because each request otherwise repeats the full system prompt: a 970-map
# game's Maps & events estimate fell from 4,089 to 2,173 requests and from
# 23.5 to 14.0 million input tokens. A page of more than SHARED_PAGE_ENTRIES
# (10) message boxes and choices keeps a request of its own, so no other
# scene's speakers or subjects bleed into it, and its choice menus join that
# request in play order when the page fits one request. A packed reply of the
# wrong length writes none of its pages, which stay untranslated for a retry.
PAGE_PACKING = "event-pages-v1"
# Stretches left between translations an earlier run saved share requests up to
# the request size, each labelled with the lines before it and their earlier
# translations, so scattered leftovers do not each pay for a full prompt. Runs
# frozen without it, and a call with one stretch, send each stretch with its
# preceding source.
REUSE_STRETCHES = "shared-stretches-v1"
# A Batch's grouped map display names are identified by the maps they name, as
# a Live run identifies each map's name, and each translation is saved under
# every one of those maps, so either run reuses the other's whichever map a
# selection starts at; a name an older run saved under the first map is reused
# too. Runs frozen without it keep the first map's identities, so their Batch
# consume rebuilds the requests it collected.
MAP_NAME_IDENTITIES = "map-name-identities-v1"
# A skill's battle messages carry a note naming the actors that learn it and
# the enemies whose actions use it, and those names bring their glossary
# entries, so the model can choose pronouns for the battler. A skill granted
# any other way, such as by a plugin, has no users and its battler stays
# gender neutral, as does a state message's (_battle_users in the parser).
BATTLE_MESSAGE_USERS = "battle-message-users-v2"
# RPG Maker MV/MZ text still to translate is what engine util/source_text
# reads as Japanese, the rule Guided's line counts share, and finished labels
# and map names are not sent again. A run frozen without it reads Japanese by
# LANGREGEX and sends map names and labels on every pass.
SOURCE_TEXT = "source-letters-v3"
# Each source-text policy a saved run may hold, by the engine level it
# enables: v3 reads a value for the run's language pair, so a Chinese
# translation's hanzi read translated and only its kana left; v2 reads a
# value against the Japanese it was translated from, so a lone kana or mark
# the source holds, such as a kaomoji's ﾉ, reads translated, and the run
# reuses no saved line that rule reads as left; v1 reads every Japanese
# letter as left.
SOURCE_TEXT_LEVELS = {
    "source-letters-v1": 1,
    "source-letters-v2": 2,
    SOURCE_TEXT: 3,
}
# Each battle-message-users policy a saved run may hold, by the parser level it
# enables: v2 also treats a party of one actor as that actor.
BATTLE_MESSAGE_USERS_LEVELS = {
    "battle-message-users-v1": 1,
    BATTLE_MESSAGE_USERS: 2,
}

DEFAULT_OPTIONS = {
    "entriesPerRequest": None,
    "batchInputTokens": None,
    "pricing": "automatic",
    "inputRate": None,
    "outputRate": None,
}


def batch_input_tokens(value):
    if value is not None and (
        type(value) is not int or not 1 <= value <= 9_007_199_254_740_991
    ):
        raise ValueError(
            "Batch token allowance must be a positive whole number of input tokens."
        )
    return value


def output_tokens(value):
    if value is not None and (
        type(value) is not int or not 1 <= value <= 9_007_199_254_740_991
    ):
        raise ValueError("The output token allowance must be a positive whole number.")
    return value


def output_allowance(value=None, *limits):
    return min(
        [
            output_tokens(value) or DEFAULT_OUTPUT_TOKENS,
            # output_tokens returns valid limits unchanged and rejects others.
            *(cast(int, output_tokens(limit)) for limit in limits if limit is not None),
        ]
    )


def text(value, label, *, required=False):
    if (
        not isinstance(value, str)
        or len(value) > 2000
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"Enter a valid {label}.")
    if required and not value.strip():
        raise ValueError(f"Enter a {label}.")
    return value.strip()


def values(value, *, draft=False, connection=False):
    if not isinstance(value, dict) or set(value) != {"language", "model"}:
        raise ValueError("Unknown preference. Reopen Settings after updating the app.")
    return {
        "language": text(value["language"], "target language", required=not draft),
        "model": text(
            value["model"], "model ID", required=not draft and not connection
        ),
    }


def chosen(value, *, draft=False, connection=False):
    """The preferences Settings sends, with the source language new games
    start in (settings/language_pair), which the record keeps beside them:
    (values, source language)."""
    if not isinstance(value, dict) or "sourceLanguage" not in value:
        raise ValueError("Unknown preference. Reopen Settings after updating the app.")
    from . import language_pair

    rest = {key: item for key, item in value.items() if key != "sourceLanguage"}
    return (
        values(rest, draft=draft, connection=connection),
        language_pair.source_language(value["sourceLanguage"]),
    )


def options(value, *, draft=False):
    # Existing version-two preferences and recovery drafts can omit the override.
    optional = {
        "batchInputTokens",
        "maxOutputTokens",
        "batchPricing",
        "batchInputRate",
        "batchOutputRate",
    }
    if (
        not isinstance(value, dict)
        or not set(DEFAULT_OPTIONS).difference(optional).issubset(value)
        or set(value) - set(DEFAULT_OPTIONS) - optional
    ):
        raise ValueError("Invalid model options.")
    batch_input_tokens(value.get("batchInputTokens"))
    output_tokens(value.get("maxOutputTokens"))
    if value["pricing"] not in ("automatic", "custom"):
        raise ValueError("Choose automatic pricing or custom rates.")
    if value.get("batchPricing", "automatic") not in ("automatic", "custom"):
        raise ValueError("Choose automatic Batch pricing or custom Batch rates.")
    entries = value["entriesPerRequest"]
    if (
        entries is not None
        and not (draft and entries == "")
        and (type(entries) is not int or not 1 <= entries <= 100)
    ):
        raise ValueError("Entries per request must be a whole number from 1 to 100.")
    for name in ("inputRate", "outputRate", "batchInputRate", "batchOutputRate"):
        rate = value.get(name)
        custom = (
            value.get("batchPricing", "automatic") == "custom"
            if name.startswith("batch")
            else value["pricing"] == "custom"
        )
        if rate is None or draft and rate == "":
            if not draft and custom:
                raise ValueError(
                    "Enter both custom Batch rates; use 0 for a free model."
                    if name.startswith("batch")
                    else "Enter both custom rates; use 0 for a free model."
                )
        elif (
            type(rate) not in (int, float)
            or not math.isfinite(rate)
            or not 0 <= rate <= 1_000_000
        ):
            raise ValueError(
                "Rates must be finite, nonnegative amounts in USD per million tokens."
            )
        elif round(rate, 6) != rate:
            raise ValueError("Use at most six decimal places for estimate rates.")
    return {**DEFAULT_OPTIONS, **deepcopy(value)}


def model_options(value, *, draft=False):
    if not isinstance(value, dict) or len(value) > 1000:
        raise ValueError("Invalid saved model options.")
    result = {}
    for model, item in value.items():
        key = text(model, "model ID", required=True)
        if key != model:
            raise ValueError("Model IDs cannot have surrounding spaces.")
        try:
            result[key] = options(item, draft=draft)
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from exc
    return result


def upgrade_v1(value):
    """Retain legacy fields privately; new model choices start on automatic rates."""
    saved = deepcopy(value["values"])
    engines = value.pop("engines")
    draft = value["draft"]
    value["legacy"] = {"values": saved, "engines": engines, "draft": deepcopy(draft)}
    value["values"] = {key: saved[key] for key in ("language", "model")}
    value["model_options"] = {}
    for connection in value["connections"]:
        connection["model_options"] = {}
        # Retain a deliberate request-size override for the model it was used with.
        # The former global default of 30 now defers to the application default.
        if connection["model"].strip() and saved["batchsize"] != 30:
            connection["model_options"][connection["model"].strip()] = {
                **DEFAULT_OPTIONS,
                "entriesPerRequest": saved["batchsize"],
            }
    if not value["active"] and saved["batchsize"] != 30:
        value["model_options"][saved["model"].strip()] = {
            **DEFAULT_OPTIONS,
            "entriesPerRequest": saved["batchsize"],
        }
    value["draft"] = None
    if draft:
        profiles = {}
        for identity, model in draft["models"].items():
            connection = next(
                (item for item in value["connections"] if item["id"] == identity), None
            )
            profiles[identity] = {
                "model": model,
                "model_options": deepcopy(
                    connection["model_options"]
                    if connection
                    else value["model_options"]
                ),
            }
        value["draft"] = {
            "language": draft["values"].get("language", saved["language"]),
            "connections": profiles,
        }
    return value


def upgrade_v2(value):
    """Settings from before the source language was one: every game's text
    was Japanese."""
    from dazedtl.languages import DEFAULT_SOURCE

    value["sourceLanguage"] = DEFAULT_SOURCE
    return value
