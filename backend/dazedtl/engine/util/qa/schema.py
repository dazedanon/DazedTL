"""Schemas, the rules version and limits that several QA layers share, and
the basic helpers they all use: errors, timestamps, hashes and category
names."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from util import rpgmaker_blocks as blocks

TASK_SCHEMA = "rpgmaker-qa-task-v3"
# The rules a task is reviewed under. Bump it only when a change makes reviews
# an earlier version saved wrong or unreadable: a task in review then prepares
# again, while a finished task keeps its results and applies as before. Any
# other change to DazedTL's code leaves saved QA work current, and the
# previous-release check (scripts/qa-upgrade.mjs) fails on one that breaks it
# without a bump. Tasks from before this version was kept, up to 2.24.0,
# count as version 1. Version 2 reads Japanese left against each line's source
# in the game's language pair, so a Chinese translation's hanzi are no residue.
# Version 3 reads data, plugin settings and custom data that keep no source
# against the game's original files, so the never-translated report leaves
# out a Chinese translation of them. Version 4 sends a line whose censor masks
# (〇, ●) its source does not share, and a pronoun against a character's
# glossary gender, to deep review. Version 5 reads each text of a message or
# scrolling text as a record of its own (TEXT_RECORDS).
QA_RULES_VERSION = 5
# From this rules version an inventory reads a message's and scrolling text's
# texts as the engine sends them, a record each with its own source, where a
# writer laid one source over several, such as a name on a row of its own and
# its speech, so each is reviewed and its correction fitted on its own
# (read_texts). A task of an earlier version keeps reading, applying and
# comparing its game's text as it was made.
TEXT_RECORDS = 5
# How QA reads those texts: as the engine sends them where no engine settings
# read them, a speaker in any form the engine reads a text of its own, the
# reading Assistant-led's writer splits and fits by (util/len_originals
# READING), so QA's inventory never changes with a project's speaker settings.
TEXT_READING = blocks.EVERY_SPEAKER
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



def read_texts(document: Any, rules: int = QA_RULES_VERSION) -> Any:
    """A data file's *document* as QA's *rules* version reads it, in place:
    from TEXT_RECORDS, each text of a message or scrolling text keeps its own
    source on its first row, read by TEXT_READING (rpgmaker_blocks
    `keep_document_texts`), so one source laid over a name and its speech
    reads as two records. Earlier versions read it as it is. The inventory
    builder and its verifier read the game by it, and Apply keeps the texts
    it corrects so in the game (util/qa/fitting `keep_corrected_texts`)."""
    if rules >= TEXT_RECORDS:
        blocks.keep_document_texts(document, TEXT_READING)
    return document


# How a reviewer's text shows a line break: bundles, briefs and the context
# view write each as this mark (shown_text), and the text a reviewer writes
# back reads each as a line break (typed_text), so a correction copied from
# what they read keeps its breaks.
NEWLINE_MARK = "⏎"


def shown_text(value: Any) -> str:
    """*value* as a reviewer reads it, each line break as NEWLINE_MARK."""
    return str(value).replace("\n", NEWLINE_MARK)


def typed_text(value: Any, *held: Any) -> Any:
    """Text a reviewer wrote, such as a correction, as the game gets it: each
    NEWLINE_MARK a line break, the inverse of shown_text. When the line's own
    text, *held* (its source or current text), holds the mark itself, the
    reviewer read it there as text, so it stays as written."""
    if not isinstance(value, str) or any(
        NEWLINE_MARK in str(text) for text in held if isinstance(text, str)
    ):
        return value
    return value.replace(NEWLINE_MARK, "\n")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


# Where a task's game was when it was prepared, kept in a task read after
# the game moved (storage.located), so the task's digest stays the same.
PREPARED_AT = "prepared_at"


def task_sha256(task: dict[str, Any]) -> str:
    """The digest a task's checkpoint and findings name their task by, as
    it was prepared."""
    if PREPARED_AT in task:
        task = {**{key: value for key, value in task.items() if key != PREPARED_AT}, **task[PREPARED_AT]}
    return _sha256(_canonical_bytes(task))


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
