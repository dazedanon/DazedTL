"""The supported preferences contract, independent of legacy engine settings."""

from copy import deepcopy
import math


DEFAULT_ENTRIES_PER_REQUEST = 50
DEFAULT_OUTPUT_TOKENS = 32_768
# Below the 500k Tier 1 Batch queue limit published for GPT-5.5 Pro;
# source and account-limit caveats live in docs/architecture.md.
DEFAULT_BATCH_INPUT_TOKENS = 400_000
GENERATION_PARAMETERS = "provider-defaults-v1"
CHOICE_COLLECTION = "event-choices-once-v1"
SPEAKER_CONTEXT = "event-speaker-context-v1"

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
            *(output_tokens(limit) for limit in limits if limit is not None),
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
