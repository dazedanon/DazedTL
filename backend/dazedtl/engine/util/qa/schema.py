"""Schemas, the rules version and limits that several QA layers share, and
the basic helpers they all use: errors, timestamps, hashes and category
names."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

TASK_SCHEMA = "rpgmaker-qa-task-v3"
# The rules a task is reviewed under. Bump it only when a change makes reviews
# an earlier version saved wrong or unreadable: a task in review then prepares
# again, while a finished task keeps its results and applies as before. Any
# other change to DazedTL's code leaves saved QA work current, and the
# previous-release check (scripts/qa-upgrade.mjs) fails on one that breaks it
# without a bump. Tasks from before this version was kept, up to 2.24.0,
# count as version 1.
QA_RULES_VERSION = 1
CHECKPOINT_SCHEMA = "rpgmaker-qa-checkpoint-v3"
BUNDLE_SCHEMA = "rpgmaker-qa-bundle-v3"
SCREEN_RESULT_SCHEMA = "rpgmaker-qa-screen-result-v2"
DEEP_RESULT_SCHEMA = "rpgmaker-qa-deep-result-v4"
SWEEP_RESULT_SCHEMA = "rpgmaker-qa-sweep-result-v1"
# Stages whose bundles reviewers claim, in order.
REVIEW_STAGES = ("screen", "deep", "sweep", "editorial")
FINDINGS_SCHEMA = "rpgmaker-qa-findings-v5"
CORRECTION_MAP_SCHEMA = "rpgmaker-qa-correction-map-v1"
REGRESSION_SCHEMA = "rpgmaker-qa-regression-v1"
EDITORIAL_RESULT_SCHEMA = "rpgmaker-qa-editorial-result-v2"

DEFAULT_SCREEN_CHAR_BUDGET = 48_000
DEFAULT_SCREEN_ITEM_LIMIT = 160
DEFAULT_DEEP_CHAR_BUDGET = 56_000
DEFAULT_DEEP_ITEM_LIMIT = 24

# A reviewer that will not review an item says why in one line, without game text.
DECLINE_REASON_LIMIT = 300
# A review that changes or reports a line says what is wrong in one plain
# sentence the user reads on the Text QA page; `evidence` keeps the reasoning.
SUMMARY_LIMIT = 120

# Workers on one AI helper share its boundaries, so what one of them declined
# goes only to workers on another helper; a worker names its helper when it
# runs on a different one than the coordinator.
DEFAULT_HELPER = "default"

# Bundles that need no more review; a split bundle's items moved to new ones
# when a worker declined some of them before anyone reviewed it.
FINISHED_STATUSES = frozenset({"accepted", "set-aside", "split"})

FINDING_CATEGORIES = frozenset({
    "speaker",
    "meaning",
    "terminology",
    "fluency",
    "wordplay",
    "voice",
    "ui",
    "gameplay",
    "runtime",
    "formatting",
    "other",
})
EDITORIAL_JUDGMENT_CATEGORIES = frozenset({"fluency", "voice", "wordplay"})

# A battler-name fix may add that one %1 and no other runtime code, which is
# narrower than allowing the whole runtime-token-mismatch flag.
ADDED_BATTLER_NAME = "added-battler-name"

# Lint proposals per review item, so a decline sets aside few of them.
LINT_ITEM_LIMIT = 60

_QUOTED_VALUE_RE = re.compile(r"(['\"`])(.*)(\1)", re.DOTALL)

_JAPANESE_ANCHOR_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]{2,}")


class QAResultError(ValueError):
    """Raised when an AI-helper result violates its immutable bundle contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _normalize_category(value: Any) -> str:
    """Collapse reviewer-specific labels into a stable report taxonomy."""
    label = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    tokens = set(label.split("-"))
    if tokens & {"speaker", "nameplate", "face"}:
        return "speaker"
    if tokens & {"runtime", "control", "code"}:
        return "runtime"
    if "ui" in tokens:
        return "ui"
    if tokens & {"gameplay", "mechanics"}:
        return "gameplay"
    if tokens & {"wordplay", "comic", "timing", "pun"}:
        return "wordplay"
    if tokens & {"terminology", "consistency", "glossary", "name", "title"}:
        return "terminology"
    if tokens & {"voice", "tone", "characterization"}:
        return "voice"
    if tokens & {"formatting", "capitalization"}:
        return "formatting"
    if tokens & {"fluency", "grammar", "naturalness", "idiom", "agreement"}:
        return "fluency"
    if tokens & {
        "meaning", "accuracy", "context", "referent", "pronoun", "subject",
        "identity", "condition", "number", "modality", "action", "explicit",
    }:
        return "meaning"
    return "other"


def _normalize_family_key(value: Any) -> str:
    key = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return key[:200]
