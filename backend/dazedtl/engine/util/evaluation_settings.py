"""Model-aware generation settings for reproducible evaluation candidates."""

from __future__ import annotations

from dazedtl.settings.effort import LABELS
from dazedtl.settings.effort import levels as effort_levels


DEFAULT_MAX_OUTPUT_TOKENS = 4096
MAX_OUTPUT_TOKEN_LIMIT = 128_000
SETTING_FIELDS = ("reasoning_effort", "effective_reasoning_effort", "max_output_tokens")
EFFORT_LABELS = {**LABELS, "provider_default": "Provider default"}


def reasoning_profile(candidate: dict) -> tuple[tuple[str, ...], str]:
    """Return the efforts a model takes (dazedtl/settings/effort, the one
    table runs read too) and the cheapest, which an "auto" choice resolves
    to. Unknown models keep provider defaults instead of inheriting another
    model's API contract."""
    levels = effort_levels(candidate.get("provider"), candidate.get("model"))
    return (levels, levels[0]) if levels else ((), "provider_default")


def generation_settings(candidate: dict) -> dict:
    """Validate settings and resolve an auto choice, retaining a saved resolution."""
    levels, default = reasoning_profile(candidate)
    choice = candidate.get("reasoning_effort", "auto")
    saved = "effective_reasoning_effort" in candidate
    # A saved candidate keeps the effort it ran with, which an earlier table
    # may have offered; requests still carry only levels the table holds.
    if saved:
        levels = tuple(EFFORT_LABELS)
    if choice != "auto" and choice not in levels:
        raise ValueError(f"{candidate.get('model')}: unsupported reasoning effort {choice!r}")
    effective = candidate.get("effective_reasoning_effort", default if choice == "auto" else choice)
    allowed = levels or ("provider_default",)
    if effective not in allowed or (choice != "auto" and effective != choice):
        raise ValueError(f"{candidate.get('model')}: saved reasoning settings do not match this model")
    limit = candidate.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_OUTPUT_TOKEN_LIMIT:
        raise ValueError(f"Output token limit must be a whole number from 1 to {MAX_OUTPUT_TOKEN_LIMIT:,}")
    return {
        "reasoning_effort": choice,
        "effective_reasoning_effort": effective,
        "max_output_tokens": limit,
    }


def candidate_label(candidate: dict) -> str:
    """Distinguish model/effort comparisons while preserving legacy result labels."""
    label = str(candidate.get("label") or candidate.get("model") or candidate.get("id") or "")
    if any(field in candidate for field in SETTING_FIELDS):
        settings = generation_settings(candidate)
        effort = EFFORT_LABELS[settings["effective_reasoning_effort"]]
        label += f" / {effort} / {settings['max_output_tokens']:,} tokens"
    return label
