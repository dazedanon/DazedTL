"""Deterministic local tooling for AI-helper RPG Maker translation QA.

DazedTL owns inventory, compact bundles, checkpoints, context expansion,
result validation, finding propagation, correction maps, and regression.  The
AI helper only reviews immutable bundle files and writes the documented JSON
result shape; this module never calls a model provider.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from util.paths import (
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
    new_folder,
    replace_with_retry,
    unlink_with_retry,
)
from util.rpgmaker_qa_manifest import (
    QUOTED_TRANSFORMS,
    SCRIPT_STRINGS,
    _mechanical_evidence,
    build_manifest,
    resolve_pointer,
    write_manifest,
)
from util.rpgmaker_qa_verify import verify_manifest
from util import rpgmaker_qa_checks as checks
from util import rpgmaker_qa_glossary as glossary_rules
from util import rpgmaker_qa_lint as lint
from util.rpgmaker_header_check import check as check_headers
from util.rpgmaker_qa_preflight import (
    REASON as NOT_TRANSLATED_REASON,
    kept_digest,
    preflight,
    read_sources,
    with_kept,
)
from util.game_settings import load_game_wrap_widths, normalize_wrap_widths
from util.reference_games import reference_context
from util import rpgmaker_screens
from util.rpgmaker_screens import screen_of, shown_text
from util import rpgmaker_rewrap as rewrap
from util.rpgmaker_rewrap import rendered_rows, widest_line
from util import rpgmaker_script_strings as script_strings
from util.skills import rpgmaker_qa_skill_file, rpgmaker_qa_skill_parts


TASK_SCHEMA = "rpgmaker-qa-task-v3"
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
EDITORIAL_VERDICTS = frozenset({"accept", "revise", "withdraw"})
# Editorial rounds that only settle conflicting corrections, before those are
# left unverified.
EDITORIAL_CONFLICT_ROUNDS = 3

DEFAULT_SCREEN_CHAR_BUDGET = 48_000
DEFAULT_SCREEN_ITEM_LIMIT = 160
DEFAULT_DEEP_CHAR_BUDGET = 56_000
DEFAULT_DEEP_ITEM_LIMIT = 24
# Occurrences a deep item lists in full; its shapes still cover every one.
DEEP_LOCATOR_LIMIT = 12
# Ready deep items that open a deep bundle while screening continues.
EARLY_DEEP_BATCH = DEFAULT_DEEP_ITEM_LIMIT
# A bundle whose worker has not been seen this long, or three times a typical
# bundle's time when longer, has stalled; the next idle worker takes it.
STALL_MINIMUM_SECONDS = 20 * 60
# Workers seen this recently are active, and reviews in this much of QA's
# latest work measure how many bundles it reviews at once.
ACTIVE_WORKER_SECONDS = 30 * 60
# A worker's run reviews this many bundles, then a fresh run of it continues,
# which keeps each review's context small.
RUN_BUNDLES = 6
# QA's latest work reviews one bundle at a time while others wait when it held
# this many bundles and fewer than this many were in review at once.
ONE_AT_A_TIME_BUNDLES = 3
ONE_AT_A_TIME_BELOW = 1.5
# Seconds one review target takes, by stage, until the task has measured it.
DEFAULT_SECONDS_PER_ITEM = {"screen": 5.0, "deep": 60.0, "sweep": 4.0, "editorial": 30.0}

SCREEN_VERDICTS = frozenset({"suspect", "needs-context"})
MOTIF_DISPOSITIONS = frozenset({"preserved", "suspect", "uncertain-playtest"})
DEEP_DISPOSITIONS = frozenset({
    "clean", "actionable", "uncertain-playtest", "declined",
})
# A reviewer that will not review an item says why in one line, without game text.
DECLINE_REASON_LIMIT = 300
# Workers on one AI helper share its boundaries, so what one of them declined
# goes only to workers on another helper; a worker names its helper when it
# runs on a different one than the coordinator.
DEFAULT_HELPER = "default"
# Distinct helpers that must decline an item before it is set aside unreviewed.
DECLINES_TO_SET_ASIDE = 2
# Bundles that need no more review; a split bundle's items moved to new ones
# when a worker declined some of them before anyone reviewed it.
FINISHED_STATUSES = frozenset({"accepted", "set-aside", "split"})
# Another reviewer screens at least this share of each reviewer's scene and
# line targets again, starting with its first bundle.
SCREEN_CHECK_SHARE = 0.25
# A reviewer has every bundle checked once checks found at least this many
# problems it missed, and more than it found in the same lines.
SCREEN_CHECK_MISSES = 2
# An observation's reason, for a line outside the reviewer's own items, is one
# short line.
OBSERVATION_NOTE_LIMIT = 500
SEVERITIES = frozenset({"critical", "high", "medium"})
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
APPROVED_NONBLOCKING_MECHANICAL_FLAGS = frozenset({"suspicious-length-ratio"})
# Fixes for slips in the Japanese source itself: the Show Text header's face
# and name, a database field's number that its own entry contradicts, or an
# MZ battle message without the %1 that shows its battler's name.
SOURCE_FIX_KINDS = frozenset({"show-text", "database-numbers", "battler-name"})
# A battler-name fix may add that one %1 and no other runtime code, which is
# narrower than allowing the whole runtime-token-mismatch flag.
ADDED_BATTLER_NAME = "added-battler-name"
# The flags each correcting source fix may introduce.
SOURCE_FIX_ALLOWED_FLAGS = {
    "database-numbers": ("visible-number-mismatch",),
    "battler-name": (ADDED_BATTLER_NAME,),
}
# Every module whose rules shape bundles, flags, findings or the briefs.
_ENGINE_SOURCES = (
    "rpgmaker_qa.py", "rpgmaker_qa_manifest.py", "rpgmaker_qa_lint.py",
    "rpgmaker_qa_preflight.py", "rpgmaker_qa_reach.py", "rpgmaker_qa_checks.py",
    "rpgmaker_qa_glossary.py",
    "rpgmaker_header_check.py", "rpgmaker_rewrap.py", "dazedwrap.py",
    "rpgmaker_script_strings.py",
    "rpgmaker_screens/__init__.py", "rpgmaker_screens/capture.cjs",
    "rpgmaker_screens/harness.js", "rpgmaker_window/__init__.py",
    "rpgmaker_window/launcher.cjs", "rpgmaker_window/bridge.cjs",
    "skills/setup.py",
)
# Lint proposals per review item, so a decline sets aside few of them.
LINT_ITEM_LIMIT = 60

FORCED_DEEP_MECHANICAL_FLAGS = frozenset({
    "empty-live",
    "unchanged-source",
    "source-language-residue",
    "missing-center-alignment",
    "runtime-token-mismatch",
    "unsafe-bare-center-code",
    "visible-number-mismatch",
})
FORCED_DEEP_EVENT_CODES = frozenset({102})

_JP_RISK_CUES = {
    "negation": re.compile(
        r"(?:ない|なかった|ません|ませぬ|禁止|不可|[ぬず](?:[、。！？!?…\s]|$))"
    ),
    "condition": re.compile(r"(?:なら|れば|たら|場合|条件|限り|とき|時に)"),
    "quantity": re.compile(r"(?:\d|[０-９]|一|二|三|四|五|六|七|八|九|十|百|千|万)(?:人|個|回|日|年|枚|本|匹|体|つ)?"),
    "identity": re.compile(r"(?:彼|彼女|あいつ|こいつ|そいつ|父|母|兄|姉|弟|妹|夫|妻|先生|様|殿)"),
    "choice-or-order": re.compile(r"(?:選|決|必ず|先に|後で|前に|まで|以降|以前)"),
    "wordplay": re.compile(r"(?:駄洒落|冗談|笑|ふふ|はは|クク|語呂|謎|暗号)"),
}
_QUOTED_VALUE_RE = re.compile(r"(['\"`])(.*)(\1)", re.DOTALL)
_MOTIF_GUIDANCE_RE = re.compile(
    r"(?:recurring|running|joke|wordplay|pun|catchphrase|humou?r|冗談|駄洒落|語呂)",
    re.IGNORECASE,
)
_JAPANESE_ANCHOR_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]{2,}")
_CANONICAL_QUIRK_MAPPING_RE = re.compile(
    r"`([^`\n]+)`\s*→\s*\"([^\"\n]+)\""
)
_JAPANESE_FIELD_LABEL_RE = re.compile(r"【([^】\n]+)】")
_ENGLISH_FIELD_LABEL_RE = re.compile(
    r"\[([A-Za-z][A-Za-z0-9 /&'’-]{0,79})\]"
)
_EN_PRONOUN_RE = re.compile(
    r"\b(?:I|me|my|mine|myself|we|us|our|ours|ourselves|you|your|yours|yourself|"
    r"yourselves|he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b",
    re.IGNORECASE,
)
_EN_THIRD_PERSON_PRONOUN_RE = re.compile(
    r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b",
    re.IGNORECASE,
)


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


def _fixed_source_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _fixed_translation_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _consistency_conflicts(
    findings: list[dict[str, Any]],
    context: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    """Corrections that contradict each other or the project's fixed wording.

    Hard conflicts (quirk mappings, recorded decisions, structured labels) must
    be revised; a soft one, the same text corrected two ways, may stand when
    an editorial reviewer confirms the contexts differ.
    """
    conflicts: dict[str, list[dict[str, str]]] = defaultdict(list)
    findings = [finding for finding in findings if finding.get("kind") != "show-text"]
    quirks = str((context.get("quirks") or {}).get("text") or "")
    canonical: dict[str, set[str]] = defaultdict(set)
    for source, translation in _CANONICAL_QUIRK_MAPPING_RE.findall(quirks):
        source_parts = re.split(r"\s+/\s+", source)
        translation_parts = re.split(r"\s+/\s+", translation)
        mappings = (
            zip(source_parts, translation_parts, strict=True)
            if len(source_parts) > 1 and len(source_parts) == len(translation_parts)
            else ((source, translation),)
        )
        for mapped_source, mapped_translation in mappings:
            canonical[_fixed_source_key(mapped_source)].add(
                _fixed_translation_key(mapped_translation)
            )
    for finding in findings:
        for change in _changes(finding):
            expected = canonical.get(_fixed_source_key(change["source"])) or set()
            if len(expected) == 1 and _fixed_translation_key(
                change["correction"]
            ) not in expected:
                conflicts[finding["id"]].append({
                    "kind": "hard",
                    "key": "quirk:" + _fixed_source_key(change["source"]),
                    "message": "The translation quirks fix this text as "
                    f"{next(iter(expected))!r}.",
                })
            for decision in decisions:
                if (
                    decision.get("source")
                    and decision["source"] in str(change["source"])
                    and decision.get("translation") not in str(change["correction"])
                ):
                    conflicts[finding["id"]].append({
                        "kind": "hard",
                        "key": "decision:" + decision["key"],
                        "message": f"Decision {decision['key']!r} renders "
                        f"{decision['source']!r} as {decision['translation']!r}.",
                    })

    field_labels: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for finding in findings:
        for change in _changes(finding):
            source_labels = _JAPANESE_FIELD_LABEL_RE.findall(str(change["source"]))
            correction_labels = _ENGLISH_FIELD_LABEL_RE.findall(
                str(change["correction"])
            )
            if not source_labels or len(source_labels) != len(correction_labels):
                continue
            for source_label, correction_label in zip(
                source_labels, correction_labels, strict=True
            ):
                field_labels[source_label][correction_label].add(finding["id"])
    for source_label, translations in sorted(field_labels.items()):
        if len(translations) < 2:
            continue
        rendered = ", ".join(
            f"{translation!r} ({', '.join(sorted(ids))})"
            for translation, ids in sorted(translations.items())
        )
        for ids in translations.values():
            for finding_id in ids:
                conflicts[finding_id].append({
                    "kind": "hard",
                    "key": "label:" + source_label,
                    "message": f"The label 【{source_label}】 is corrected as {rendered}.",
                })

    # The same text corrected two ways; different translations of one source
    # may keep different corrections. A scene correction's lines are meant
    # for their scene, so only the lines it shares count, below.
    by_text: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding.get("kind") != "scene":
            by_text[(str(finding["source"]), str(finding["current"]))].append(finding)
    for text, members in sorted(by_text.items()):
        corrections = sorted({str(member["correction"]) for member in members})
        if len(corrections) < 2:
            continue
        signature = _sha256(_canonical_bytes(corrections))[:16]
        for member in members:
            conflicts[member["id"]].append({
                "kind": "soft",
                "key": "text:" + _sha256(_canonical_bytes(text))[:16],
                "signature": signature,
                "message": "The same text is corrected differently in "
                + ", ".join(sorted(other["id"] for other in members if other is not member))
                + "; keep the difference only when the contexts need it.",
            })

    # A scene correction replaces another correction of a line it changes,
    # so it keeps that fix when it still applies; two scene corrections
    # cannot share a line.
    owners: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for finding in findings:
        if finding.get("lint_only"):
            continue
        for change in _changes(finding):
            for identity in change["identities"]:
                owners[identity].append((finding, change))
    reported: set[tuple[str, str]] = set()
    for identity, found in sorted(owners.items()):
        scenes = [
            (finding, change) for finding, change in found
            if finding.get("kind") == "scene"
        ]
        for scene, line in scenes:
            for other, change in found:
                if other is scene or (scene["id"], other["id"]) in reported:
                    continue
                reported.add((scene["id"], other["id"]))
                if other.get("kind") == "scene":
                    conflicts[scene["id"]].append({
                        "kind": "hard",
                        "key": "scene-overlap:" + other["id"],
                        "message": f"{other['id']} also changes line #{line['command']} "
                        f"({line['current']!r}); leave each line to one scene correction.",
                    })
                    continue
                conflicts[scene["id"]].append({
                    "kind": "soft",
                    "key": "overlap:" + other["id"],
                    "signature": _sha256(_canonical_bytes(
                        [line["correction"], change["correction"]]
                    ))[:16],
                    "message": f"{other['id']} corrects line #{line['command']} "
                    f"({line['current']!r}) as {change['correction']!r}; this scene "
                    "correction replaces it there, so keep its fix if it still applies.",
                })
    return dict(conflicts)


def _simulate_apply(
    findings: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    layout: dict[str, Any],
) -> None:
    """Refuse findings whose corrections the post-apply regression would reject."""
    problems = []
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        for change in _changes(finding):
            for identity in change["identities"]:
                found = _record_problems(
                    records[identity],
                    change["correction"],
                    layout,
                    frozenset(finding.get("allowed_flags") or ()),
                )
                if found:
                    problems.append(
                        f"{finding['id']} at {identity}: " + "; ".join(found)
                    )
    if problems:
        raise QAResultError(
            "These corrections would block apply: " + " | ".join(problems[:20])
        )


def _validate_editorial_basis(review: dict[str, Any], identity: str) -> None:
    """Require subjective findings to prove a defect rather than state a preference."""
    category = _normalize_category(review.get("category"))
    basis = review.get("editorial_basis")
    if category not in EDITORIAL_JUDGMENT_CATEGORIES:
        if basis is not None:
            raise QAResultError(
                f"Objective review cannot have editorial_basis for {identity}"
            )
        return
    if not isinstance(basis, dict) or set(basis) != {
        "defect", "source_support", "not_preference"
    }:
        raise QAResultError(
            f"Subjective actionable review needs editorial_basis for {identity}"
        )
    if not str(basis.get("defect") or "").strip():
        raise QAResultError(f"Editorial basis has no concrete defect for {identity}")
    if not str(basis.get("source_support") or "").strip():
        raise QAResultError(f"Editorial basis has no source support for {identity}")
    if basis.get("not_preference") is not True:
        raise QAResultError(f"Editorial basis is only a preference for {identity}")


def task_layout(
    game_root: str | Path, fit: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The Line widths a task fits corrections to. The app passes its own;
    without them a task reads the game's saved widths."""
    fit = fit or {}
    return {
        "widths": normalize_wrap_widths(
            fit.get("widths") or load_game_wrap_widths(game_root)
        ),
    }


def _window(record: dict[str, Any], layout: dict[str, Any]) -> rewrap.Box | None:
    """The window a record's text shows in, as DazedTL fits text to it, or
    None when nothing known limits the text."""
    widths = rewrap.Layout.from_widths(layout["widths"])
    code = record.get("event_code")
    field = (record.get("database_entity") or {}).get("field")
    source = str(record.get("source") or "")
    if code == 401:
        face = str((record.get("speaker") or {}).get("face_name") or "").strip()
        return rewrap.message_box(widths, face=bool(face))
    if code == 405:
        return rewrap.scrolling_box(widths)
    if code == 324:
        return rewrap.nickname_box(widths)
    if code == 325:
        return rewrap.help_box(widths, source, dialogue=True)
    if code == 357:
        plugin = (record.get("risky_context") or {}).get("plugin_header")
        key = record["live_pointers"][0].rsplit("/", 1)[-1]
        if key in rewrap.MESSAGE_PLUGIN_TEXT.get(plugin, ()):
            return rewrap.message_box(widths)
        return None
    if code is None and field in rewrap.LIST_FIELDS_BY_FILE.get(record["file"], ()):
        return rewrap.help_box(widths, source)
    if code is None and field == "note":
        return rewrap.note_box(widths)
    return None


def _box(record: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any] | None:
    """The box a record's text shows in, by the task's Line widths: its width,
    the rows it shows, whether a message goes on to a new page after them, and
    whether DazedTL rewraps a correction to it. None when nothing limits the
    text."""
    window = _window(record, layout)
    if window is None:
        return None
    box: dict[str, Any] = {"width": window.width, "kind": window.kind}
    if window.rows:
        box["rows"] = window.rows
    if window.paged:
        box["pages"] = True
    # A message spread over several commands is fitted and spread over them
    # again (rpgmaker_rewrap.spread); other text spread over several commands,
    # such as a comment or a script, keeps its line structure.
    box["wraps"] = record["live_transform"] == "identity" and (
        len(record["live_pointers"]) == 1 or _message_code(record.get("event_code"))
    )
    return box


def _message_code(code: int | None) -> bool:
    """Whether a command holds a row of a message, which DazedTL fits as a
    whole however many commands hold its rows."""
    return code in (401, 405)


def _fit_window(box: dict[str, Any]) -> rewrap.Box:
    """The fitter's window for a box. A correction is never paged: one taller
    than its message window is refused instead."""
    rows = None if box.get("pages") else box.get("rows")
    return rewrap.Box(box["width"], rows, False, box.get("kind", "message"))


def _widens(correction: str, live: str, width: int) -> bool:
    """Whether a correction has a line wider than both its box and the current
    text."""
    return widest_line(correction) > max(width, widest_line(live))


def _fit(
    correction: str,
    live: str,
    box: dict[str, Any] | None,
    source: str | None = None,
    commands: int = 1,
) -> str:
    """A correction as DazedTL writes it: wrapped again, as translation wraps
    it, when a line does not fit its box, and as it reads once spread over
    the *commands* that hold the text."""
    if not box or not box.get("wraps"):
        return correction
    fitted = rewrap.fit_value(correction, _fit_window(box), source=source)
    return "\n".join(rewrap.spread(fitted, commands))


# The quote mark of each script string transform.
_SCRIPT_QUOTES = {transform: quote for quote, transform in SCRIPT_STRINGS.items()}


def _script_text(correction: str, transform: str) -> str:
    """A correction as DazedTL writes it into a script string: with the
    escapes translation writes there, so it can't end the string early or
    interpolate in it; other text as it is."""
    quote = _SCRIPT_QUOTES.get(transform)
    return script_strings.escape(correction, quote) if quote else correction


def _fitted(
    correction: str,
    live: str,
    targets: list[dict[str, Any]],
    layout: dict[str, Any],
) -> str:
    """One correction for every target it reaches, as DazedTL writes it when
    each target takes the same text: escaped into one kind of script string,
    or fitted to the narrowest box when each target takes a rewrapped
    value."""
    transforms = {target["live_transform"] for target in targets}
    if len(transforms) == 1 and transforms <= _SCRIPT_QUOTES.keys():
        return _script_text(correction, *transforms)
    boxes = [_box(target, layout) for target in targets]
    if not boxes or not all(box and box.get("wraps") for box in boxes):
        return correction
    narrowest = min(boxes, key=lambda box: box["width"])
    return _fit(correction, live, narrowest, targets[0].get("source"))


def _fit_corrections(
    findings: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    clusters: dict[str, dict[str, Any]],
    layout: dict[str, Any],
) -> None:
    """Write each correction and proposal as DazedTL applies it, so findings
    show the text the game gets."""
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        scene = finding.get("kind") == "scene"
        for change in finding["lines"] if scene else [finding]:
            identities = change["identities"] if scene else finding["target_identities"]
            change["correction"] = _fitted(
                change["correction"],
                change["current"],
                [records[identity] for identity in identities],
                layout,
            )
    for question in questions:
        if question.get("correction"):
            identities = clusters[question["id"]]["identities"]
            question["correction"] = _fitted(
                question["correction"],
                question["current"],
                [records[identity] for identity in identities],
                layout,
            )


def _record_problems(
    record: dict[str, Any],
    correction: str,
    layout: dict[str, Any],
    allowed: frozenset[str] = frozenset(),
) -> list[str]:
    """Why one correction of an inventory record would block apply."""
    return correction_problems(
        record["source"], record["live"], correction, record.get("event_code"),
        record["live_pointers"], record["live_transform"], allowed,
        box=_box(record, layout),
    )


def correction_problems(
    source: str,
    live: str,
    correction: str,
    event_code: int | None,
    live_pointers: list[str],
    live_transform: str,
    allowed: frozenset[str] = frozenset(),
    *,
    box: dict[str, Any] | None,
) -> list[str]:
    """Why applying one correction would fail or trip the post-apply regression.

    This simulates the apply step for one target: the line structure its
    pointers need, the rows its box shows, and the mechanical flags the
    regression treats as blocking. DazedTL writes the correction fitted to
    the box, which may not need more rows than the box shows or the current
    text uses; a correction it cannot rewrap may not have a line wider than
    both the box and the current text. Into a script string it writes the
    correction escaped as translation writes the string.
    """
    problems = []
    written = _script_text(
        _fit(correction, live, box, source, len(live_pointers)), live_transform
    )
    if written == live:
        problems.append("the correction matches the current text")
    lines = correction.split("\n")
    if live_transform == "quoted-string":
        # The text sits between quote marks in a script parameter whose
        # escapes are unknown, so a new kind of quote mark could end the
        # string early.
        if any(mark in correction and mark not in live for mark in "'\"`"):
            problems.append("adds a quote mark to a script string")
    elif (
        len(live_pointers) > 1 and not (box and box.get("wraps"))
        and len(lines) != len(live_pointers)
    ):
        problems.append(
            f"needs {len(live_pointers)} lines like the current text, "
            f"not {len(lines)}"
        )
    elif event_code in {101, 102} and "\n" in correction:
        problems.append("a name or choice cannot contain a line break")
    elif box and box.get("rows"):
        rows = rendered_rows(written)
        if rows > max(rendered_rows(live), box["rows"]):
            window = "a message window" if event_code == 401 else "its window"
            problems.append(f"needs {rows} rows; {window} shows {box['rows']}")
    if (
        box and box.get("width") and not box.get("wraps")
        and _widens(correction, live, box["width"])
    ):
        problems.append(
            f"has a line {widest_line(correction)} characters wide; its line "
            f"width is {box['width']}"
        )
    before = set(_mechanical_evidence(source, live, event_code)["flags"])
    after = set(_mechanical_evidence(source, written, event_code)["flags"])
    introduced = sorted(_disallowed_flags(
        after - before - APPROVED_NONBLOCKING_MECHANICAL_FLAGS, allowed,
        source, written,
    ))
    if introduced:
        problems.append("introduces " + ", ".join(introduced))
    return problems


def _adds_only_battler_name(source: str, text: str) -> bool:
    """Whether a text keeps its source's runtime codes and adds only the %1
    the source lacks."""
    evidence = _mechanical_evidence(source, text, None)
    source_tokens = Counter(evidence["source_runtime_tokens"])
    text_tokens = Counter(evidence["live_runtime_tokens"])
    return (
        "%1" not in source_tokens
        and text_tokens - source_tokens == Counter({"%1": 1})
        and not source_tokens - text_tokens
    )


def _disallowed_flags(
    introduced: set[str], allowed: Iterable[str], source: str, text: str
) -> set[str]:
    """The introduced flags no allowance covers; a battler-name allowance
    covers a runtime-token mismatch only from the one %1 it adds."""
    allowed = set(allowed)
    left = introduced - allowed
    if (
        ADDED_BATTLER_NAME in allowed
        and "runtime-token-mismatch" in left
        and _adds_only_battler_name(source, text)
    ):
        left.discard("runtime-token-mismatch")
    return left


def _engine_fingerprint() -> str:
    """Fingerprint the files that define QA's rules: the engine modules and
    the policy the README and briefs are made from.

    Only the files count, never this process's loaded values: the app keeps
    the code it started with while each QA worker loads the files as they are,
    so once the files change, both still agree on which rules are current.
    """
    files = {name: Path(__file__).parent / name for name in _ENGINE_SOURCES}
    files["policy"] = rpgmaker_qa_skill_file()
    return _sha256(_canonical_bytes({
        name: _sha256(path.read_bytes()) for name, path in files.items()
    }))


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    # utf-8-sig: an assistant's shell may start a result file with a BOM.
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _safe_task_root(output_root: str | Path, game_root: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    if root == game_root or game_root in root.parents:
        raise ValueError("QA task storage must be outside the selected game folder")
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def _task_lock(task_dir: Path, wait: bool = True):
    """Serialize cross-process checkpoint mutations for parallel helpers.

    Without *wait*, it yields whether it got the lock instead of waiting for
    another process to let go of it.
    """
    lock_path = task_dir / ".checkpoint.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(
                    handle.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1
                )
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
                )
        except OSError:
            if wait:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:80] or "game"


def _read_optional(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "status": "missing", "sha256": "", "text": ""}
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        return {
            "path": str(resolved),
            "status": "missing",
            "sha256": "",
            "text": "",
        }
    raw = resolved.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {
            "path": str(resolved),
            "status": f"unreadable: {exc}",
            "sha256": _sha256(raw),
            "text": "",
        }
    return {
        "path": str(resolved),
        "status": "loaded" if text.strip() else "empty",
        "sha256": _sha256(raw),
        "text": text,
    }


def _context_pack(
    game_root: Path, current_sources: Iterable[str] = ()
) -> dict[str, Any]:
    skills_dir = game_root / GAME_SKILLS_RELATIVE
    reserved = {name.casefold() for name in GAME_SKILL_RESERVED_NAMES}
    overlay_paths = []
    if skills_dir.is_dir() and not skills_dir.is_symlink():
        for path in sorted(skills_dir.glob("*.md"), key=lambda item: item.name.casefold()):
            if path.name.casefold() in reserved:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Unsafe custom QA context path: {path}")
            overlay_paths.append(path)
    glossary = _read_optional(game_root / GAME_GLOSSARY_RELATIVE)
    quirks = _read_optional(game_root / GAME_QUIRKS_RELATIVE)
    game = _read_optional(game_root / GAME_SKILL_RELATIVE)
    overlays = [_read_optional(path) for path in overlay_paths]
    pack = {
        "schema": "rpgmaker-qa-context-v2",
        "glossary": glossary,
        "quirks": quirks,
        "game": game,
        "overlays": overlays,
        "reference_translations": reference_context(game_root, current_sources),
    }
    pack["content_sha256"] = _sha256(_canonical_bytes(pack))
    return pack


def _record_maps(manifest: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    records = {record["identity"]: record for record in manifest["records"]}
    clusters = {cluster["representative"]: cluster for cluster in manifest["clusters"]}
    return records, clusters


def _semantic_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Hash inventory semantics while excluding recomputable detector evidence."""
    projection = {
        key: value for key, value in manifest.items() if key != "content_sha256"
    }
    projection["records"] = [
        {key: value for key, value in record.items() if key != "mechanical"}
        for record in manifest.get("records") or []
    ]
    return _sha256(_canonical_bytes(projection))


def _risk_reasons(
    cluster: dict[str, Any], records: dict[str, dict], glossary: glossary_rules.Glossary
) -> tuple[list[str], list[list[str]]]:
    members = [records[identity] for identity in cluster["identities"]]
    reasons: set[str] = set()
    for record in members:
        reasons.update(record.get("mechanical", {}).get("flags") or [])
        if record.get("event_code") == 102:
            reasons.add("choice")
        if record.get("classification") == "risky-codes":
            reasons.add("runtime-sensitive")
    source = str(cluster["source"])
    if len(source.strip()) <= 4:
        reasons.add("short-ambiguous")
    for label, pattern in _JP_RISK_CUES.items():
        if pattern.search(source):
            reasons.add(label)
    # The glossary terms the English lacks; a term it uses needs no word.
    hits = [
        [term.source, term.english]
        for term, _start, _end in glossary_rules.missing(source, str(cluster["live"]), glossary)
    ] if source not in glossary.unseen else []
    if hits:
        reasons.add("glossary")
    facets = {
        (
            record.get("file"),
            record.get("event_code"),
            (record.get("speaker") or {}).get("display_name", ""),
            record.get("display_shape"),
        )
        for record in members
    }
    if len(facets) > 1:
        reasons.add("multiple-contexts")
    return sorted(reasons), hits


def _compact_items(manifest: dict[str, Any], context: dict[str, Any]) -> list[dict]:
    records, clusters = _record_maps(manifest)
    glossary = _game(manifest, context).glossary
    live_by_source: dict[str, set[str]] = defaultdict(set)
    for cluster in manifest["clusters"]:
        live_by_source[str(cluster["source"])].add(str(cluster["live"]))
    items = []
    for ordinal, representative in enumerate(manifest["review_sequence"], start=1):
        cluster = clusters[representative]
        reasons, hits = _risk_reasons(cluster, records, glossary)
        alternatives = sorted(
            live for live in live_by_source[str(cluster["source"])]
            if live != str(cluster["live"])
        )
        if alternatives:
            reasons = sorted({*reasons, "inconsistent-source"})
        reference_rows = list(
            ((context.get("reference_translations") or {}).get("matches") or {}).get(
                str(cluster["source"]), []
            )
        )
        if reference_rows and any(
            str(row.get("translation") or "") != str(cluster["live"])
            for row in reference_rows
        ):
            reasons = sorted({*reasons, "reference-difference"})
        member_records = [records[identity] for identity in cluster["identities"]]
        speakers = sorted({
            str((record.get("speaker") or {}).get("display_name") or "")
            for record in member_records
            if str((record.get("speaker") or {}).get("display_name") or "")
        })
        item = {
            "ordinal": ordinal,
            "id": representative,
            "occurrences": len(cluster["identities"]),
            "context_facets": len({
                (
                    record.get("file"), record.get("event_code"),
                    (record.get("speaker") or {}).get("display_name", ""),
                    record.get("display_shape"),
                )
                for record in member_records
            }),
            "risk": reasons,
            "glossary": hits,
            "event_codes": sorted({
                int(record["event_code"])
                for record in member_records if record.get("event_code") is not None
            }),
            "speakers": speakers[:8],
            "display_shapes": sorted({
                str(record.get("display_shape") or "") for record in member_records
            }),
            "source": cluster["source"],
            "translation": cluster["live"],
        }
        if reference_rows:
            item["reference_translations"] = reference_rows
        if alternatives:
            item["same_source_alternatives"] = alternatives[:20]
        items.append(item)
    return items


def _cluster_by_identity(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        identity: cluster["representative"]
        for cluster in manifest["clusters"]
        for identity in cluster["identities"]
    }


def _scene_position(record: dict[str, Any]) -> tuple[str, int] | None:
    """Return the owning command-list ID and command index for a dialogue record."""
    parts = _decode_pointer(str(record.get("source_pointer") or ""))
    list_positions = [index for index, part in enumerate(parts[:-1]) if part == "list"]
    if not list_positions:
        return None
    list_pos = list_positions[-1]
    try:
        command_index = int(parts[list_pos + 1])
    except (ValueError, IndexError):
        return None
    list_pointer = "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1")
        for part in parts[: list_pos + 1]
    )
    return f"{record['file']}#{list_pointer}", command_index


def _scene_records(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Each command list's dialogue records in command order: the scenes
    screening reads, and the lines a scene correction numbers."""
    scenes: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for record in manifest["records"]:
        if record.get("classification") != "dialogue":
            continue
        position = _scene_position(record)
        if position is None:
            continue
        scene_id, command_index = position
        scenes[scene_id].append((command_index, record))
    return {
        scene_id: [
            record for _index, record in sorted(
                positioned, key=lambda item: (item[0], item[1]["source_pointer"])
            )
        ]
        for scene_id, positioned in scenes.items()
    }


def _scene_signature(records: list[dict[str, Any]]) -> str:
    content = [{
        "source": record["source"],
        "translation": record["live"],
        "speaker": (record.get("speaker") or {}).get("display_name", ""),
        "event_code": record.get("event_code"),
        "display_shape": record.get("display_shape"),
        "choice_context": record.get("choice_context"),
    } for record in records]
    return _sha256(_canonical_bytes(content))


def _pronoun_context_requirements(
    groups: list[dict[str, Any]], compact: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], set[str]]:
    """Return narrowly scoped repeated-scene targets that need local context."""
    groups_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    speakers_by_cluster: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        for cluster_id in group["clusters"]:
            groups_by_cluster[cluster_id].append(group)
            speakers_by_cluster[cluster_id].update(
                group["cluster_speakers"].get(cluster_id, set())
            )

    requirements: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cluster_id, contexts in groups_by_cluster.items():
        if len(contexts) < 2:
            continue
        translation = str(compact[cluster_id]["translation"])
        if _EN_THIRD_PERSON_PRONOUN_RE.search(translation):
            for group in contexts:
                requirements[(group["signature"], cluster_id)].add(
                    "repeated-third-person-context"
                )

        speakers = speakers_by_cluster[cluster_id]
        if len(speakers) < 2 or not _EN_PRONOUN_RE.search(translation):
            continue
        for speaker in sorted(speakers):
            candidates = [
                group for group in contexts
                if speaker in group["cluster_speakers"].get(cluster_id, set())
            ]
            if not candidates:
                continue
            chosen = min(candidates, key=lambda group: group["scene_id"])
            requirements[(chosen["signature"], cluster_id)].add(
                "cross-speaker-pronoun-context"
            )
    return requirements


def _scene_groups(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every dialogue command list as a scene, identical scenes as copies of
    one group, and each line's cluster."""
    cluster_ids = _cluster_by_identity(manifest)
    equivalent: dict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for scene_id, ordered in _scene_records(manifest).items():
        equivalent[_scene_signature(ordered)].append((scene_id, ordered))

    groups = []
    for signature, copies in equivalent.items():
        copies.sort(key=lambda item: item[0])
        scene_id, representative_records = copies[0]
        cluster_speakers: dict[str, set[str]] = defaultdict(set)
        for record in representative_records:
            speaker = str((record.get("speaker") or {}).get("display_name") or "")
            if speaker:
                cluster_speakers[cluster_ids[record["identity"]]].add(speaker)
        groups.append({
            "signature": signature,
            "scene_id": scene_id,
            "copies": copies,
            "records": representative_records,
            "clusters": {cluster_ids[record["identity"]] for record in representative_records},
            "cluster_speakers": cluster_speakers,
        })
    return groups, cluster_ids


def _scene_item(
    group: dict[str, Any],
    targets: set[str],
    compact: dict[str, dict[str, Any]],
    lint_fixes: dict[str, dict[str, Any]],
    cluster_ids: dict[str, str],
    *,
    item_id: str = "",
    context_expansion: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """One scene as a screen item, with the index of its lines' clusters: a
    target cluster's first line carries an `id`, every other line a
    `context_id`."""
    signature = group["signature"]
    emitted_clusters: set[str] = set()
    lines = []
    screen_index: dict[str, dict[str, str]] = {}
    for position, record in enumerate(group["records"]):
        cluster_id = cluster_ids[record["identity"]]
        line = {
            "source": record["source"],
            "translation": record["live"],
        }
        speaker = str((record.get("speaker") or {}).get("display_name") or "")
        if speaker:
            line["speaker"] = speaker
        if record.get("event_code") != 401:
            line["event_code"] = record.get("event_code")
        if cluster_id in lint_fixes:
            line["lint"] = lint_fixes[cluster_id]
        if cluster_id in targets and cluster_id not in emitted_clusters:
            emitted_clusters.add(cluster_id)
            cluster_item = compact[cluster_id]
            review_id = "scene-target-" + _sha256(
                f"{signature}\0{position}\0{cluster_id}"
            )[:20]
            line["id"] = review_id
            if cluster_item["risk"]:
                line["risk"] = cluster_item["risk"]
            if cluster_item["glossary"]:
                line["glossary"] = cluster_item["glossary"]
            if cluster_item.get("same_source_alternatives"):
                line["same_source_alternatives"] = cluster_item[
                    "same_source_alternatives"
                ]
            if cluster_item.get("reference_translations"):
                line["reference_translations"] = cluster_item[
                    "reference_translations"
                ]
            if record.get("choice_context"):
                line["choice_context"] = record["choice_context"]
            expansion = sorted((context_expansion or {}).get(cluster_id, set()))
            if expansion:
                line["context_expansion"] = expansion
            screen_index[review_id] = {
                "cluster_id": cluster_id,
                "representative_identity": record["identity"],
            }
        else:
            context_id = "scene-context-" + _sha256(
                f"{signature}\0{position}\0{cluster_id}\0context"
            )[:20]
            line["context_id"] = context_id
            screen_index[context_id] = {
                "cluster_id": cluster_id,
                "representative_identity": record["identity"],
            }
        lines.append(line)
    if emitted_clusters != targets:
        raise ValueError("Scene target assignment lost a dialogue cluster")
    return {
        "kind": "scene",
        "id": item_id or "scene-" + signature[:20],
        "scene_id": group["scene_id"],
        **(
            {"scene_copies": [copy_id for copy_id, _records in group["copies"]]}
            if len(group["copies"]) > 1 else {}
        ),
        "scene_occurrences": len(group["copies"]),
        "target_count": len(targets),
        "line_count": len(lines),
        "lines": lines,
    }, screen_index


def _scene_items(
    manifest: dict[str, Any],
    compact: dict[str, dict[str, Any]],
    lint_fixes: dict[str, dict[str, Any]],
    reviewed: _Reviewed | None = None,
) -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, str]]]:
    """Build indivisible scenes that cover each dialogue cluster exactly once;
    a line reviewed earlier is no target, so only scenes with another line
    are read, where it shows as context."""
    groups, cluster_ids = _scene_groups(manifest)

    def earlier(cluster_id: str) -> bool:
        item = compact[cluster_id]
        return bool(reviewed) and reviewed.line(item["source"], item["translation"])

    uncovered = {
        cluster_id
        for group in groups for cluster_id in group["clusters"]
        if not earlier(cluster_id)
    }
    selected_by_signature: dict[str, dict[str, Any]] = {}
    while uncovered:
        candidates = [
            (len(group["clusters"] & uncovered), group["scene_id"], group)
            for group in groups
            if group["clusters"] & uncovered
        ]
        _coverage, _scene_id, chosen = min(
            candidates, key=lambda item: (-item[0], item[1])
        )
        chosen = dict(chosen)
        chosen["targets"] = chosen["clusters"] & uncovered
        chosen["context_expansion"] = defaultdict(set)
        selected_by_signature[chosen["signature"]] = chosen
        uncovered.difference_update(chosen["targets"])

    groups_by_signature = {group["signature"]: group for group in groups}
    for (signature, cluster_id), reasons in _pronoun_context_requirements(
        groups, compact
    ).items():
        if earlier(cluster_id) and reviewed.scene(
            "scene-" + signature[:20],
            (
                (record["source"], record["live"])
                for record in groups_by_signature[signature]["records"]
            ),
        ):
            continue
        selected = selected_by_signature.get(signature)
        if selected is None:
            selected = dict(groups_by_signature[signature])
            selected["targets"] = set()
            selected["context_expansion"] = defaultdict(set)
            selected_by_signature[signature] = selected
        selected["targets"].add(cluster_id)
        selected["context_expansion"][cluster_id].update(reasons)

    selected = sorted(
        selected_by_signature.values(), key=lambda group: group["scene_id"]
    )

    items = []
    screen_index: dict[str, dict[str, str]] = {}
    for group in selected:
        item, item_index = _scene_item(
            group, set(group["targets"]), compact, lint_fixes, cluster_ids,
            context_expansion=group["context_expansion"],
        )
        items.append(item)
        screen_index.update(item_index)
    items.sort(key=lambda item: _sha256("scene-screen-v1\0" + item["id"]))
    return items, {
        index_item["cluster_id"] for index_item in screen_index.values()
    }, screen_index


def _motif_seeds(quirks_text: str) -> list[dict[str, Any]]:
    seeds = []
    for raw in str(quirks_text or "").splitlines():
        guidance = raw.strip().lstrip("-* ").strip()
        if not guidance or not _MOTIF_GUIDANCE_RE.search(guidance):
            continue
        anchors = sorted(set(_JAPANESE_ANCHOR_RE.findall(guidance)))
        if not anchors:
            continue
        seeds.append({
            "id": "motif-" + _sha256(guidance)[:20],
            "guidance": guidance,
            "anchors": anchors,
        })
    return seeds


def _motif_items(
    manifest: dict[str, Any], context: dict[str, Any], compact: dict[str, dict[str, Any]],
    data_root: Path, reviewed: _Reviewed | None = None,
) -> list[dict[str, Any]]:
    """Each recurring joke's translations as one family; variants reviewed in
    the family earlier are listed beside the others instead of read again."""
    records, clusters = _record_maps(manifest)
    document_cache: dict[str, Any] = {}
    items = []
    for seed in _motif_seeds(context["quirks"]["text"]):
        matching = [
            cluster for cluster in manifest["clusters"]
            if any(anchor in str(cluster["source"]) for anchor in seed["anchors"])
        ]
        if len(matching) < 2:
            continue
        earlier = [
            cluster for cluster in matching
            if reviewed and reviewed.variant(seed["id"], cluster["source"], cluster["live"])
        ]
        if len(earlier) == len(matching):
            continue
        variants = []
        for cluster in matching:
            if cluster in earlier:
                continue
            cluster_id = cluster["representative"]
            representative = records[cluster["identities"][0]]
            item = compact[cluster_id]
            variants.append({
                "id": cluster_id,
                "representative_identity": representative["identity"],
                "occurrences": len(cluster["identities"]),
                "source": cluster["source"],
                "translation": cluster["live"],
                "speakers": item["speakers"],
                "risk": item["risk"],
                "nearby_commands": _nearby_commands(
                    data_root, representative, document_cache
                ),
            } | (
                {"reference_translations": item["reference_translations"]}
                if item.get("reference_translations") else {}
            ))
        variants.sort(key=lambda item: (item["source"], item["translation"], item["id"]))
        items.append({
            "kind": "motif-family",
            "id": seed["id"],
            "guidance": seed["guidance"],
            "anchors": seed["anchors"],
            **({"reviewed_variants": [
                {"source": cluster["source"], "translation": cluster["live"]}
                for cluster in sorted(
                    earlier, key=lambda cluster: (cluster["source"], cluster["live"])
                )
            ]} if earlier else {}),
            # Each variant is a target, so a declined one moves on its own.
            "target_count": len(variants),
            "variant_count": len(variants),
            "variants": variants,
            "exclusive_bundle": True,
        })
    return items


# The lint families' reading of the last task's game, which one command may
# need several times: a large game's glossary takes a second or two to read.
_LINT_GAMES: dict[tuple[str, str], lint.Game] = {}


def _game(manifest: dict[str, Any], context: dict[str, Any]) -> lint.Game:
    """What the lint families and screen hints read from the whole game: an
    inventory and the glossary its task's context holds."""
    key = (manifest["content_sha256"], context["content_sha256"])
    if key not in _LINT_GAMES:
        _LINT_GAMES.clear()
        _LINT_GAMES[key] = lint.game(manifest, context["glossary"]["text"])
    return _LINT_GAMES[key]


def _lint_game(root: Path, manifest: dict[str, Any]) -> lint.Game:
    """The lint game of a prepared task, as it was prepared."""
    return _game(manifest, _read_json(root / "context.json"))


def _lint_items(
    manifest: dict[str, Any],
    layout: dict[str, Any],
    game: lint.Game,
    reviewed: _Reviewed | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Each reviewed lint family's proposals as review items, and every line's
    fixes, the automatic families' included.

    A proposal the post-apply regression would reject is left out, and so is
    one a reviewer rejected earlier for the same text. Proposals are grouped
    by scene and split into small items, so a declined item sets aside only
    that part of a family.
    """
    records, _clusters = _record_maps(manifest)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fixes: dict[str, dict[str, Any]] = {}
    for cluster in manifest["clusters"]:
        members = [records[identity] for identity in cluster["identities"]]
        found = {
            family: proposed
            for family, proposed in lint.proposals(
                cluster["source"], cluster["live"], game
            ).items()
            if not any(
                _record_problems(record, proposed, layout) for record in members
            ) and not (
                reviewed and family not in lint.AUTOMATIC and reviewed.lint_rejected(
                    cluster["source"], cluster["live"], proposed
                )
            )
        }
        if not found:
            continue
        cluster_id = cluster["representative"]
        fixes[cluster_id] = {
            "families": sorted(found, key=lint.ORDER.index),
            "proposed": lint.compose(cluster["source"], cluster["live"], found, game),
        }
        position = _scene_position(members[0])
        speaker = str((members[0].get("speaker") or {}).get("display_name") or "")
        for family, proposed in found.items():
            if family in lint.AUTOMATIC:
                continue
            by_family[family].append({
                "id": "lint-" + _sha256(f"{family}\0{cluster_id}")[:16],
                "cluster_id": cluster_id,
                "occurrences": len(members),
                "scene": position[0] if position else members[0]["file"],
                **({"speaker": speaker} if speaker else {}),
                "source": cluster["source"],
                "current": cluster["live"],
                "proposed": proposed,
                **(
                    {"note": note}
                    if (note := lint.note(family, cluster["source"], cluster["live"], game))
                    else {}
                ),
            })
    items = []
    for family in lint.ORDER:
        proposals = sorted(
            by_family.get(family) or [],
            key=lambda row: (row["scene"], row["cluster_id"]),
        )
        for start in range(0, len(proposals), LINT_ITEM_LIMIT):
            chunk = proposals[start : start + LINT_ITEM_LIMIT]
            items.append({
                "kind": "lint-family",
                "id": "lint-family-" + _sha256(
                    family + "\0" + "\0".join(row["id"] for row in chunk)
                )[:20],
                "family": family,
                "description": lint.FAMILIES[family]["description"],
                "target_count": len(chunk),
                "proposals": chunk,
            })
    return items, fixes


def _screen_items(
    manifest: dict[str, Any],
    context: dict[str, Any],
    data_root: Path,
    lint_fixes: dict[str, dict[str, Any]],
    reviewed: _Reviewed | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    compact_items = _compact_items(manifest, context)
    compact = {item["id"]: item for item in compact_items}
    items: list[dict[str, Any]] = []
    covered_dialogue: set[str] = set()
    screen_index: dict[str, dict[str, str]] = {}
    if manifest["focus"] in {"dialogue", "release"}:
        scenes, covered_dialogue, screen_index = _scene_items(
            manifest, compact, lint_fixes, reviewed
        )
        items.extend(scenes)

    clusters = {
        cluster["representative"]: cluster for cluster in manifest["clusters"]
    }
    member_records = {
        record["identity"]: record for record in manifest["records"]
    }
    for item in compact_items:
        if reviewed and reviewed.line(item["source"], item["translation"]):
            continue
        cluster = clusters[item["id"]]
        has_non_scene_member = any(
            member_records[identity].get("classification") != "dialogue"
            or _scene_position(member_records[identity]) is None
            for identity in cluster["identities"]
        )
        if (
            manifest["focus"] not in {"dialogue", "release"}
            or item["id"] not in covered_dialogue
            or (manifest["focus"] == "release" and has_non_scene_member)
        ):
            item = {**item, "kind": "cluster", "target_count": 1}
            if item["id"] in lint_fixes:
                item["lint"] = lint_fixes[item["id"]]
            items.append(item)

    if manifest["focus"] in {"dialogue", "release"}:
        items.extend(_motif_items(manifest, context, compact, data_root, reviewed))

    # Preserve deterministic load balancing while assigning exact coverage ordinals.
    items.sort(key=lambda item: _sha256("rpgmaker-qa-screen-v3\0" + item["id"]))
    ordinal = 1
    for item in items:
        item["ordinal"] = ordinal
        if item["kind"] == "scene":
            for line in item["lines"]:
                if "id" in line:
                    line["ordinal"] = ordinal
                    ordinal += 1
        elif item["kind"] == "motif-family":
            ordinal += 1
        else:
            ordinal += 1
    return items, screen_index


# Source numbers in ordinal or idiom contexts (第1層, 1番目, 3日目, 一番) read as
# words in English; kanji numerals are words already.
_ORDINAL_OR_IDIOM_NUMBER_RE = re.compile(
    r"第\s*(\d+)|(\d+)\s*(?:番|回目|人目|日目|度目|階)"
)
_KANJI_DIGITS = {
    "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
    "八": 8, "九": 9,
}
_KANJI_NUMBER_RE = re.compile(r"[〇一二三四五六七八九十百千]+")


def _kanji_value(text: str) -> int | None:
    total, current = 0, 0
    for char in text:
        if char in _KANJI_DIGITS:
            current = current * 10 + _KANJI_DIGITS[char]
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            total += (current or 1) * unit
            current = 0
    value = total + current
    return value or None


def _number_defect(source: str, live: str) -> bool:
    """Whether a number mismatch can be a translation defect worth deep review.

    A number the English adds or changes always is. A source number missing
    from the English is only when it is not an ordinal or idiom, not a small
    count English writes as a word ("three", "once"), and not a word already.
    """
    evidence = _mechanical_evidence(source, live, None)
    visible = unicodedata.normalize("NFKC", source)
    idioms = Counter(
        number.lstrip("0") or "0"
        for match in _ORDINAL_OR_IDIOM_NUMBER_RE.finditer(visible)
        for number in match.groups() if number
    )
    kanji = Counter(
        str(value) for match in _KANJI_NUMBER_RE.finditer(source)
        if (value := _kanji_value(match.group(0))) is not None
    )
    source_numbers = Counter(evidence["source_visible_numbers"])
    live_numbers = Counter(evidence["live_visible_numbers"])
    if live_numbers - source_numbers - kanji - idioms:
        return True
    missing = source_numbers - live_numbers - idioms
    return any(
        not (number.isdigit() and int(number) <= 10) for number in missing
    )


def _forced_deep_reasons(item: dict[str, Any]) -> list[str]:
    """Return only high-confidence reasons that override a clean screen receipt.

    Number and runtime-token flags force deep review only when they can be a
    defect: a changed number, or a source code the English lost.
    """
    source, live = str(item["source"]), str(item["translation"])
    evidence = _mechanical_evidence(source, live, None)
    reasons = {
        reason for reason in item.get("risk") or []
        if reason in FORCED_DEEP_MECHANICAL_FLAGS
        and not (
            reason == "visible-number-mismatch" and not _number_defect(source, live)
        )
        and not (
            reason == "runtime-token-mismatch"
            and not Counter(evidence["source_runtime_tokens"])
            - Counter(evidence["live_runtime_tokens"])
        )
    }
    if set(item.get("event_codes") or []) & FORCED_DEEP_EVENT_CODES:
        reasons.add("choice-context")
    return sorted(reasons)


def _database_checks(
    manifest: dict[str, Any], data_root: Path
) -> dict[str, list[dict[str, str]]]:
    """Database text that deterministic checks send to deep review, by cluster."""
    return checks.database_checks(manifest, checks.runtime(data_root))


# Captures of the game's interface screens, and those taken again with a
# finding's corrections in place, under the task's folder. Each capture is a
# round in a folder of its own, which the record beside them names with the
# plugin files it ran with, so a reused task captures again once they change.
INTERFACE_FOLDER = "interface"
CAPTURE_RECORD = "capture.json"
CAPTURE_SCHEMA = "rpgmaker-qa-capture-v1"
# The places one interface-fit check names before counting the rest.
INTERFACE_PLACES_LISTED = 3
_ENEMY_LETTER_RE = re.compile(r"\s?[A-ZＡ-Ｚ]$")
# Who notes the lines a capture taken again finds squeezed.
RECAPTURE_OBSERVER = "interface"


def _capture_record(root: Path) -> dict[str, Any] | None:
    path = root / INTERFACE_FOLDER / CAPTURE_RECORD
    return _read_json(path) if path.is_file() else None


def interface_capture(task_dir: str | Path) -> dict[str, Any] | None:
    """A task's latest interface capture: its round, its folder and what it
    found; None for a task prepared without one."""
    root = Path(task_dir)
    record = _capture_record(root)
    if record:
        return {
            "round": record["round"],
            "folder": root / INTERFACE_FOLDER / record["folder"],
            "summary": record["summary"],
        }
    # A task from before captures kept a record has its one capture in the
    # folder itself.
    found = _read_json(root / "task.json").get("interface")
    if not found:
        return None
    return {
        "round": 1,
        "folder": root / INTERFACE_FOLDER,
        "summary": found,
    }


def _capture_folder(root: Path) -> Path:
    found = interface_capture(root)
    return found["folder"] if found else root / INTERFACE_FOLDER


def _capture_round(
    data: Path,
    root: Path,
    number: int,
    manifest: dict[str, Any],
    progress: Callable[[str], None] | None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Capture the interface screens as round *number* of the task in *root*:
    its record, unsaved, and where each cluster's text shows squeezed."""
    plugins = rpgmaker_screens.plugins_sha256(data)
    name = f"round-{number}"
    staging = new_folder(root / INTERFACE_FOLDER, f".{name}.")
    try:
        summary = _capture_interface(data, staging, progress)
        # A round an interrupted prepare left behind is in no record.
        shutil.rmtree(root / INTERFACE_FOLDER / name, ignore_errors=True)
        staging.rename(root / INTERFACE_FOLDER / name)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    places, outside = _interface_places(root / INTERFACE_FOLDER / name, manifest)
    record = {
        "schema": CAPTURE_SCHEMA,
        "round": number,
        "folder": name,
        "captured_at": _utc_now(),
        # A capture that failed is of no plugin files, so the next prepare
        # tries again.
        "plugins_sha256": None if summary.get("error") else plugins,
        "summary": summary | {"squeezed": len(places), "outside": len(outside)},
    }
    return record, places


def _save_capture_record(root: Path, record: dict[str, Any]) -> None:
    path = root / INTERFACE_FOLDER / CAPTURE_RECORD
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_canonical_bytes(record) + b"\n")
    # The app's polls read the record; Windows can't replace a file while
    # one does.
    replace_with_retry(temporary, path)


def _recapture(
    root: Path,
    data: Path,
    manifest: dict[str, Any],
    progress: Callable[[str], None] | None,
) -> None:
    """Capture a reused task's interface screens again once the plugin files
    they ran with changed, keeping its review. Lines the new capture finds
    squeezed go to deep review as observations; a complete task goes back to
    deep review for them, as for an observation made after deep review.

    A reused task always holds the text it reviewed, since applying its
    corrections changes the inventory and so the task, so no correction of
    it is in the game when its findings are made again."""
    previous = _capture_record(root)
    if previous is None or previous.get(
        "plugins_sha256"
    ) == rpgmaker_screens.plugins_sha256(data):
        return
    record, places = _capture_round(
        data, root, previous["round"] + 1, manifest, progress
    )
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        complete = checkpoint["stage"] == "complete"
        candidates = checkpoint["deep"].get("candidate_reasons") or {}
        observed = {row["cluster_id"] for row in checkpoint.get("observations") or []}
        fresh = sorted(
            cluster_id for cluster_id in places
            if "interface-fit" not in (candidates.get(cluster_id) or {}).get("reasons", [])
            and cluster_id not in observed
        )
        # Deep items read the squeezed places from the latest capture.
        _save_capture_record(root, record)
        if fresh:
            # A cluster is named by its representative line.
            _note_observations(
                checkpoint,
                [
                    {
                        "identity": cluster_id,
                        "cluster_id": cluster_id,
                        "categories": ["ui"],
                        "note": "The game draws this text with too little room on a "
                        "screen captured again after its plugin files changed.",
                    }
                    for cluster_id in fresh
                ],
                checkpoint["stage"],
                RECAPTURE_OBSERVER,
            )
            checkpoint["updated_at"] = _utc_now()
            _atomic_write_json(root / "checkpoint.json", checkpoint)
            if complete:
                _follow_up(root, checkpoint)
            else:
                _issue_new_evidence(root, checkpoint)
    if complete:
        # Review bundles name the captures they were made with; a follow-up
        # round's name only the latest.
        for folder in (root / INTERFACE_FOLDER).glob("round-*"):
            if folder.name != record["folder"]:
                shutil.rmtree(folder, ignore_errors=True)


def _capture_interface(
    data: Path, folder: Path, progress: Callable[[str], None] | None
) -> dict[str, Any]:
    """Capture the game's interface screens into *folder*; how many, and why
    none or some could not be."""
    try:
        listing = rpgmaker_screens.capture(data, folder, progress=progress)
    except rpgmaker_screens.WindowUnavailable as error:
        return {"captured": 0, "error": str(error)}
    return {
        "captured": len(listing["screens"]),
        **({"skipped": listing["skipped"]} if listing["skipped"] else {}),
        **(
            {"error": "; ".join(listing["errors"][:3])}
            if not listing["screens"] and listing["errors"]
            else {}
        ),
    }


def _interface_places(
    folder: Path, manifest: dict[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Where each cluster's text shows squeezed or cut off in the captures in
    *folder*, and that text the inventory holds no line of, such as a
    plugin's."""
    listing_path = folder / "screens.json"
    if not listing_path.is_file():
        return {}, []
    listing = _read_json(listing_path)
    cluster_of = _cluster_by_identity(manifest)
    by_text: dict[str, set[str]] = defaultdict(set)
    for record in manifest["records"]:
        shown = shown_text(record["live"])
        if shown and "\n" not in shown:
            by_text[shown].add(cluster_of[record["identity"]])
    places: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outside: dict[str, dict[str, Any]] = {}
    for screen in listing["screens"]:
        for label in screen.get("labels") or []:
            if not (label.get("squeezed") or label.get("clipped")):
                continue
            place = {
                "title": screen["title"],
                "capture": str(folder / screen["file"]),
                **{key: label[key] for key in ("squeezed", "clipped") if key in label},
            }
            # A battle names repeated enemies with a letter, such as "Slime Ａ".
            clusters = by_text.get(shown_text(label["text"])) or by_text.get(
                _ENEMY_LETTER_RE.sub("", shown_text(label["text"]))
            )
            if not clusters:
                outside.setdefault(label["text"], {"text": label["text"], **place})
            for cluster_id in sorted(clusters or ()):
                if place["capture"] not in {
                    earlier["capture"] for earlier in places[cluster_id]
                }:
                    places[cluster_id].append(place)
    return dict(places), list(outside.values())


def _place_text(place: dict[str, Any]) -> str:
    how = (
        "cut off" if place.get("clipped")
        else f"squeezed to {round(place['squeezed'] * 100)}% of the width it needs"
    )
    return f"{place['title']}: {how}, {place['capture']}"


def _fit_checks(
    manifest: dict[str, Any], layout: dict[str, Any]
) -> dict[str, list[dict[str, str]]]:
    """Text in a window of fixed height, such as a help window, that needs
    more rows than the window shows even wrapped to the Line widths, by
    cluster; DazedTL cannot fit it, so a reviewer shortens it."""
    cluster_of = {
        identity: cluster["representative"]
        for cluster in manifest["clusters"]
        for identity in cluster["identities"]
    }
    found: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in manifest["records"]:
        window = _window(record, layout)
        live = str(record.get("live") or "")
        if (
            window is None or window.paged or not window.rows or window.kind == "note"
            or not live.strip() or rewrap.untranslated(live)
        ):
            continue
        box = _box(record, layout)
        written = _fit(live, live, box, str(record.get("source") or ""))
        reason = rewrap.misfit(written, window)
        if reason:
            entry = {
                "check": "text-fit",
                "note": f"Wrapped to the game's Line widths, this text {reason}.",
            }
            if entry not in found[cluster_of[record["identity"]]]:
                found[cluster_of[record["identity"]]].append(entry)
    return dict(found)


def _interface_checks(
    folder: Path, manifest: dict[str, Any]
) -> dict[str, list[dict[str, str]]]:
    """Text the game squeezes or cuts off on a captured screen, by cluster,
    naming the captures that show it."""
    places, _outside = _interface_places(folder, manifest)
    checked = {}
    for cluster_id, found in places.items():
        listed = "; ".join(_place_text(place) for place in found[:INTERFACE_PLACES_LISTED])
        more = len(found) - INTERFACE_PLACES_LISTED
        checked[cluster_id] = [{
            "check": "interface-fit",
            "note": "The game draws this text with too little room. "
            + listed + (f"; and {more} more" if more > 0 else ""),
        }]
    return checked


def _interface_after(
    root: Path,
    task: dict[str, Any],
    manifest: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Captures of the screens that squeezed or cut off a finding's text, taken
    again with the corrections in place, by finding."""
    folder = _capture_folder(root)
    places, _outside = _interface_places(folder, manifest)
    if not places:
        return {}
    records, _clusters = _record_maps(manifest)
    cluster_of = _cluster_by_identity(manifest)
    data_root = Path(task["data_root"])
    shown_on: dict[str, list[dict[str, Any]]] = {}
    documents: dict[str, Any] = {}
    choices: dict[str, dict[str, Any]] = {}
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        for change in _changes(finding):
            touched = [
                identity for identity in change["identities"]
                if cluster_of.get(identity) in places
            ]
            if not touched:
                continue
            shown_on[finding["id"]] = places[cluster_of[touched[0]]]
            for identity in change["identities"]:
                record = records[identity]
                if record["file"] not in documents:
                    documents[record["file"]] = json.loads(
                        (data_root / record["file"]).read_text(encoding="utf-8-sig")
                    )
                operation = {
                    "identity": identity,
                    "live_pointers": record["live_pointers"],
                    "live_transform": record["live_transform"],
                    "expected": record["live"],
                    "replacement": _script_text(
                        change["correction"], record["live_transform"]
                    ),
                }
                try:
                    for pointer, value in _operation_writes(
                        documents[record["file"]], operation
                    ):
                        _set_pointer(documents[record["file"]], pointer, value)
                except ValueError:
                    continue
                if record.get("event_code") == 102:
                    command = record["live_pointers"][0].split("/parameters/")[0]
                    choices[f"{record['file']}#{command}"] = {
                        "file": record["file"], "command": command,
                    }
    if not shown_on:
        return {}
    rounds = sorted(folder.glob("after-*"))
    out = folder / f"after-{len(rounds) + 1}"
    overlay = {}
    for name, document in documents.items():
        path = out / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        # By its path under the game's web folder, which holds the data folder.
        overlay[f"{data_root.resolve().name}/{name}"] = path
    choice_sets = []
    for key, where in choices.items():
        params = resolve_pointer(documents[where["file"]], where["command"] + "/parameters")
        choice_sets.append({
            "key": key,
            "choices": params[0],
            **{
                name: params[index]
                for index, name in enumerate(
                    ("cancelType", "defaultType", "positionType", "background"), start=1
                )
                if index < len(params)
            },
        })
    screens = sorted({
        screen_of(place["capture"])
        for found in shown_on.values() for place in found
    } - {""})
    try:
        listing = rpgmaker_screens.capture(
            data_root, out, overlay=overlay, screens=screens,
            choices=choice_sets, all_choices=True,
        )
    except rpgmaker_screens.WindowUnavailable as error:
        return {finding_id: [{"error": str(error)}] for finding_id in shown_on}
    after: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        if finding["id"] not in shown_on:
            continue
        texts = {shown_text(change["correction"]) for change in _changes(finding)}
        titles = {place["title"] for place in shown_on[finding["id"]]}
        found = []
        for screen in listing["screens"]:
            labels = [
                label for label in screen.get("labels") or []
                if shown_text(label["text"]) in texts
            ]
            if labels and (screen["title"] in titles or screen["name"].startswith("choices")):
                worst = min(labels, key=lambda label: label.get("squeezed", 1))
                found.append({
                    "title": screen["title"],
                    "capture": str(out / screen["file"]),
                    **{key: worst[key] for key in ("squeezed", "clipped") if key in worst},
                })
        after[finding["id"]] = found or [{
            "error": "The corrected text did not show on the screens captured again.",
        }]
    return after


def _header_flags(data: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """The header check's likely Show Text slips, each beside the first line of
    its box the inventory holds, or none when the box was never translated."""
    result = check_headers(data)
    records = {
        (record["file"], record["source_pointer"]): record["identity"]
        for record in manifest["records"]
    }
    for flag in result["flags"]:
        flag["identity"] = next((
            records[(flag["file"], line + "/_original")] for line in flag["lines"]
            if (flag["file"], line + "/_original") in records
        ), "")
    return result


def _candidate(reasons: Iterable[str], identities: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "reasons": sorted(set(reasons)),
        "context_identities": sorted(set(identity for identity in identities if identity)),
    }


def _merge_candidate(
    candidates: dict[str, dict[str, Any]], cluster_id: str,
    reasons: Iterable[str], identities: Iterable[str] = (),
) -> None:
    existing = candidates.get(cluster_id) or _candidate(())
    candidates[cluster_id] = _candidate(
        [*(existing.get("reasons") or []), *reasons],
        [*(existing.get("context_identities") or []), *identities],
    )


def _bundle_items(
    items: list[dict], *, stage: str, char_budget: int, item_limit: int,
    first: int = 1, screen_index: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    if char_budget < 2_000 or item_limit < 1:
        raise ValueError("QA bundle limits are too small")
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for item in items:
        size = len(_canonical_bytes(item))
        if item.get("exclusive_bundle"):
            if current:
                groups.append(current)
                current, current_chars = [], 0
            groups.append([item])
            continue
        if current and (len(current) >= item_limit or current_chars + size > char_budget):
            groups.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += size
    if current:
        groups.append(current)
    return [
        _make_bundle(
            stage, f"{stage}-{index:04d}", group, _own_index(group, screen_index)
        )
        for index, group in enumerate(groups, start=first)
    ]


def _own_index(
    items: list[dict], screen_index: dict[str, dict[str, str]] | None
) -> dict[str, Any]:
    """A follow-up bundle's own screen index, for lines the task's index,
    made before any review, does not hold."""
    entries = {
        target: screen_index[target]
        for item in items for target in _item_targets(item)
        if target in (screen_index or {})
    }
    return {"screen_index": entries} if entries else {}


def _target_entry(
    screen_index: dict[str, dict[str, str]], bundle: dict[str, Any], target: str
) -> dict[str, str]:
    """The cluster and representative line a screen target or context ID names."""
    return (
        (bundle.get("screen_index") or {}).get(target)
        or screen_index.get(target)
        or {}
    )


def _make_bundle(
    stage: str, bundle_id: str, group: list[dict], extra: dict | None = None
) -> dict:
    ordinals = []
    for item in group:
        if item.get("kind") == "scene":
            ordinals.extend(
                line["ordinal"] for line in item["lines"] if "id" in line
            )
        else:
            ordinals.append(item["ordinal"])
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "stage": stage,
        "bundle_id": bundle_id,
        "ordinal_start": min(ordinals),
        "ordinal_end": max(ordinals),
        "item_count": sum(int(item.get("target_count", 1)) for item in group),
        "review_unit_count": len(group),
        "scene_count": sum(item.get("kind") == "scene" for item in group),
        "motif_count": sum(
            item.get("kind") == "motif-family" for item in group
        ),
        "items": group,
        **(extra or {}),
    }
    bundle["content_sha256"] = _sha256(_canonical_bytes(bundle))
    return bundle


def _target_shape(locator: dict[str, Any]) -> dict[str, Any]:
    """The line structure and box of one place an item's text shows."""
    return {
        "event_code": locator.get("event_code"),
        "pointers": len(locator["live_pointers"]),
        "transform": locator.get("live_transform", "identity"),
        **({"box": locator["box"]} if locator.get("box") else {}),
    }


def _shape_problems(
    item: dict[str, Any],
    correction: str,
    shape: dict[str, Any],
    allowed: frozenset[str] = frozenset(),
) -> list[str]:
    """Why a correction of a bundle item would block apply at one shape."""
    return correction_problems(
        str(item["source"]),
        str(item["translation"]),
        correction,
        shape["event_code"],
        ["/"] * shape["pointers"],
        shape["transform"],
        allowed,
        box=shape.get("box"),
    )


def _compact_deep_item(
    item: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """A deep item without its scenes and motif reviews, which its bundle
    prints once, and with long occurrence lists capped."""
    item = dict(item)
    scenes = item.pop("screen_scene_contexts", None) or []
    motifs = item.pop("motif_contexts", None) or []
    locators = item["locators"]
    item["occurrences"] = len(locators)
    shapes = {
        json.dumps(shape): shape for shape in map(_target_shape, locators)
    }
    item["target_shapes"] = [shapes[key] for key in sorted(shapes)]
    if len(locators) > DEEP_LOCATOR_LIMIT:
        first = set(item.get("screen_context_identities") or [])
        kept = sorted(locators, key=lambda row: row["identity"] not in first)
        kept = kept[:DEEP_LOCATOR_LIMIT]
        item["locators"] = kept
        item["identities"] = [locator["identity"] for locator in kept]
    if scenes:
        # The scene shows the lines around it; windows would repeat them.
        item.pop("nearby_commands", None)
        item.pop("suspect_contexts", None)
    return item, scenes, motifs


def _compact_scene(scene: dict[str, Any], marks: dict[str, list[str]]) -> dict:
    """A scene as deep review reads it: each line's text and speaker, and the
    items whose screen evidence names it."""
    lines = []
    for line in scene["lines"]:
        compact = {"source": line["source"], "translation": line["translation"]}
        for key in ("speaker", "event_code", "command"):
            if key in line:
                compact[key] = line[key]
        named = marks.get(line.get("id") or line.get("context_id") or "")
        if named:
            compact["items"] = sorted(set(named))
        lines.append(compact)
    return {"scene_id": scene["scene_id"], "lines": lines}


def _bundle_deep(items: list[dict], first: int = 1) -> list[dict]:
    """Deep bundles grouped by scene, each scene and motif review printed once."""
    prepared = [_compact_deep_item(item) for item in items]
    order = {item["id"]: index for index, (item, _scenes, _motifs) in enumerate(prepared)}

    def scene_key(entry):
        item, scenes, _motifs = entry
        first = scenes[0]["scene_id"] if scenes else str(
            (item["locators"] or [{}])[0].get("file") or ""
        )
        return first, order[item["id"]]

    prepared.sort(key=scene_key)
    groups: list[list[tuple]] = []
    current: list[tuple] = []
    size = 0
    seen: set[str] = set()
    for entry in prepared:
        item, scenes, motifs = entry
        new = [scene for scene in scenes if scene["scene_id"] not in seen] + [
            motif for motif in motifs if motif["id"] not in seen
        ]
        extra = len(_canonical_bytes(item)) + len(_canonical_bytes(new))
        if current and (
            len(current) >= DEFAULT_DEEP_ITEM_LIMIT
            or size + extra > DEFAULT_DEEP_CHAR_BUDGET
        ):
            groups.append(current)
            current, size, seen = [], 0, set()
            extra = len(_canonical_bytes(item)) + len(_canonical_bytes(scenes + motifs))
        current.append(entry)
        size += extra
        seen |= {scene["scene_id"] for scene in scenes} | {motif["id"] for motif in motifs}
    if current:
        groups.append(current)
    bundles = []
    for index, group in enumerate(groups, start=first):
        scenes: dict[str, dict] = {}
        keys: dict[str, str] = {}
        motifs: dict[str, dict] = {}
        members = []
        # The scene lines each item's screen evidence names.
        marks: dict[str, list[str]] = defaultdict(list)
        for item, _scenes, _motifs in group:
            for evidence in item.get("screen_evidence") or []:
                marks[evidence["target_id"]].append(item["id"])
        for item, item_scenes, item_motifs in group:
            item = dict(item)
            for scene in item_scenes:
                if scene["scene_id"] not in keys:
                    keys[scene["scene_id"]] = f"S{len(keys) + 1}"
                    scenes[keys[scene["scene_id"]]] = _compact_scene(scene, marks)
            if item_scenes:
                item["scenes"] = [keys[scene["scene_id"]] for scene in item_scenes]
            for motif in item_motifs:
                motifs.setdefault(motif["id"], motif)
            if item_motifs:
                item["motifs"] = [motif["id"] for motif in item_motifs]
            members.append(item)
        bundles.append(_make_bundle(
            "deep", f"deep-{index:04d}", members,
            {
                **({"scenes": scenes} if scenes else {}),
                **({"motifs": motifs} if motifs else {}),
            },
        ))
    return bundles


# A family item's own review units, which a reviewer may decline one by one.
_UNIT_LISTS = {
    "lint-family": "proposals", "sweep-family": "candidates", "motif-family": "variants",
}


def _units(item: dict[str, Any]) -> list[dict[str, Any]]:
    """A family item's proposals, candidates or variants; nothing for others."""
    key = _UNIT_LISTS.get(item.get("kind") or "")
    return item[key] if key else []


def _family_part(
    item: dict[str, Any], units: list[dict[str, Any]], part_id: str = ""
) -> dict[str, Any]:
    """The family item holding only these units; a declined part has an ID of
    its own and names the family it came from."""
    part = {**item, _UNIT_LISTS[item["kind"]]: units, "target_count": len(units)}
    if item["kind"] == "motif-family":
        part["variant_count"] = len(units)
    if part_id:
        part["id"] = part_id
        part["part_of"] = item.get("part_of") or item["id"]
    return part


def _partition(
    bundle: dict[str, Any], reasons: dict[str, str], number: int = 0
) -> tuple[list[dict], list[dict]]:
    """The bundle's items split into what was declined and what remains.

    A family with some of its units declined splits in two, and its declined
    part is numbered after the bundle that will hold it.
    """
    declined, remaining = [], []
    for item in bundle["items"]:
        units = _units(item)
        chosen = [unit for unit in units if unit["id"] in reasons]
        if item["id"] in reasons or units and len(chosen) == len(units):
            declined.append(item)
        elif chosen:
            family = item.get("part_of") or item["id"]
            declined.append(_family_part(item, chosen, f"{family}-d{number}"))
            remaining.append(_family_part(
                item, [unit for unit in units if unit["id"] not in reasons]
            ))
        else:
            remaining.append(item)
    return declined, remaining


def _result_declines(result: dict[str, Any]) -> set[str]:
    """The items and units an accepted result declined."""
    return {entry["id"] for entry in result.get("declined") or []}


def _shared_context(bundle: dict[str, Any], items: list[dict]) -> dict[str, Any]:
    """What a bundle made of some of another's items keeps from it: the scenes
    and motif reviews a deep bundle prints once that these items name, and a
    follow-up's own screen index for their lines."""
    shared = _own_index(items, bundle.get("screen_index"))
    for key in ("scenes", "motifs"):
        named = {name for item in items for name in item.get(key) or []}
        if named:
            shared[key] = {
                name: value for name, value in bundle[key].items() if name in named
            }
    return shared


def _add_row(
    root: Path,
    checkpoint: dict[str, Any],
    stage: str,
    bundle: dict[str, Any],
    fields: dict[str, Any],
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a bundle made from another's items and add its checkpoint row,
    after `after` or last."""
    path = root / "bundles" / stage / f"{bundle['bundle_id']}.json"
    _atomic_write_json(path, bundle)
    row = {
        "id": bundle["bundle_id"],
        "path": str(path),
        "sha256": bundle["content_sha256"],
        "item_count": bundle["item_count"],
        "status": "pending",
        "assigned_to": "",
        "result_path": "",
        **fields,
        # The authors of its judgment corrections still cannot confirm them.
        **(
            {"authors": sorted({
                author for item in bundle["items"] for author in item["authors"]
            })}
            if stage == "editorial" else {}
        ),
    }
    rows = checkpoint[stage]["bundles"]
    rows.insert(rows.index(after) + 1 if after else len(rows), row)
    return row


def _next_number(checkpoint: dict[str, Any], stage: str, origin: str) -> int:
    return 1 + sum(
        other.get("origin") == origin for other in checkpoint[stage]["bundles"]
    )


def _split_declined(
    root: Path,
    checkpoint: dict[str, Any],
    stage: str,
    row: dict[str, Any],
    bundle: dict[str, Any],
    reasons: dict[str, str],
    worker: str = "",
) -> tuple[dict[str, Any], list[dict]]:
    """Move declined items into their own bundle for a reviewer on another helper.

    Returns that bundle's row and the items that remain. After enough
    distinct helpers declined the same items, they are set aside unreviewed
    instead. The worker that declined is the bundle's holder unless named.
    """
    worker = worker or str(row.get("assigned_to") or "") or "unnamed reviewer"
    helper = _helper_of(checkpoint, worker)
    declined_helpers = sorted({*(row.get("declined_helpers") or []), helper})
    origin = row.get("origin") or row["id"]
    number = _next_number(checkpoint, stage, origin)
    items, remaining = _partition(bundle, reasons, number)
    split = _make_bundle(
        stage, f"{origin}-d{number}", items, _shared_context(bundle, items)
    )
    return _add_row(root, checkpoint, stage, split, {
        "status": (
            "set-aside"
            if len(declined_helpers) >= DECLINES_TO_SET_ASIDE else "pending"
        ),
        "origin": origin,
        **({"follow_up": True} if row.get("follow_up") else {}),
        "declined_by": sorted({*(row.get("declined_by") or []), worker}),
        "declined_helpers": declined_helpers,
        "declines": [
            *(row.get("declines") or []),
            {"worker": worker, "helper": helper, "reasons": reasons},
        ],
        **({"round": row.get("round")} if stage == "editorial" else {}),
    }), remaining


def _checkable(bundle: dict[str, Any], declined: Iterable[str]) -> list[dict[str, Any]]:
    """The scenes and lines a screen result reviewed, which a check repeats;
    lint and motif families are group reviews and are not repeated."""
    declined = set(declined)
    return [
        item for item in bundle["items"]
        if item.get("kind") in {"scene", "cluster"} and item["id"] not in declined
    ]


def _check_row(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """A second screen of one accepted bundle's reviewed lines, for another reviewer."""
    bundle = _read_json(Path(row["path"]))
    result = _read_json(Path(row["result_path"]))
    items = _checkable(bundle, _declined_items(bundle, result))
    check = _make_bundle(
        "screen", f"{row['id']}-c1", items, _own_index(items, bundle.get("screen_index"))
    )
    path = root / "bundles" / "screen" / f"{check['bundle_id']}.json"
    _atomic_write_json(path, check)
    return {
        "id": check["bundle_id"],
        "path": str(path),
        "sha256": check["content_sha256"],
        "item_count": check["item_count"],
        "status": "pending",
        "assigned_to": "",
        "result_path": "",
        "check_of": row["id"],
        # Anyone but the reviewer that screened these lines may check them; a
        # reviewer that declined them can decline them again.
        "independent_of": [str(row.get("assigned_to") or "")],
    }


def _issue_checks(root: Path, checkpoint: dict[str, Any]) -> int:
    """Open checks until each reviewer has its share of targets checked, its
    earliest bundles first; an escalated reviewer has every bundle checked.

    An accepted check counts the targets it compared, so lines its reviewer
    declined send another bundle to be checked. Returns how many opened.
    """
    rows = checkpoint["screen"]["bundles"]
    escalated = set((checkpoint["screen"].get("checks") or {}).get("escalated") or [])
    checks = {row["check_of"]: row for row in rows if row.get("check_of")}
    by_worker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["status"] == "accepted" and row.get("checkable"):
            by_worker[str(row.get("assigned_to") or "")].append(row)
    opened = 0
    for worker, accepted in sorted(by_worker.items()):
        share = 1.0 if worker in escalated else SCREEN_CHECK_SHARE
        total = sum(row["checkable"] for row in accepted)
        done = sum(
            checks[row["id"]]["compared"]
            if checks[row["id"]]["status"] == "accepted" else row["checkable"]
            for row in accepted if row["id"] in checks
        )
        for row in sorted(accepted, key=lambda row: row["accepted_at"]):
            if done >= share * total:
                break
            if row["id"] not in checks:
                rows.append(_check_row(root, row))
                done += row["checkable"]
                opened += 1
    return opened


def _record_check(
    checkpoint: dict[str, Any], row: dict[str, Any], bundle: dict, result: dict,
    declined: dict[str, str],
) -> None:
    """Compare a check with the screen it repeats, in the lines both reviewed.

    Each reviewer is tallied with what it found and what the other found that
    it did not; one that missed enough, and more than it found, is escalated.
    """
    _stage, original_row = _bundle_row(checkpoint, row["check_of"])
    original = _read_json(Path(original_row["result_path"]))
    reviewed = [item for item in bundle["items"] if item["id"] not in declined]
    row["compared"] = sum(int(item.get("target_count", 1)) for item in reviewed)
    compared = {target for item in reviewed for target in _item_targets(item)}
    first = {exception["id"] for exception in original["exceptions"]} & compared
    second = {exception["id"] for exception in result["exceptions"]}
    state = checkpoint["screen"].setdefault(
        "checks", {"added": 0, "escalated": [], "reviewers": {}}
    )
    state["added"] += len(second - first)
    for worker, found, missed in (
        (str(original_row.get("assigned_to") or ""), first, second - first),
        (str(row.get("assigned_to") or ""), second, first - second),
    ):
        tally = state["reviewers"].setdefault(worker, {"found": 0, "missed": 0})
        tally["found"] += len(found)
        tally["missed"] += len(missed)
        if (
            tally["missed"] >= SCREEN_CHECK_MISSES
            and tally["missed"] > tally["found"]
            and worker not in state["escalated"]
        ):
            state["escalated"].append(worker)


def _check_counts(screen: dict[str, Any]) -> dict[str, Any]:
    """Second screens in targets: compared, opened and expected in all, the
    problems only a check found, and the reviewers checked in full."""
    rows = [row for row in screen["bundles"] if row.get("check_of")]
    state = screen.get("checks") or {}
    total = sum(int(row["item_count"]) for row in rows)
    set_aside = sum(
        int(row["item_count"]) for row in screen["bundles"]
        if row["status"] == "set-aside"
    )
    unscreened = max(
        0, int(screen["total_items"]) - int(screen["accepted_items"]) - set_aside
    )
    return {
        "accepted": sum(
            int(row.get("compared", 0)) for row in rows if row["status"] == "accepted"
        ),
        "total": total,
        "projected": total + math.ceil(SCREEN_CHECK_SHARE * unscreened),
        "added": int(state.get("added", 0)),
        "escalated": sorted(state.get("escalated") or []),
    }


def _write_bundles(
    task_dir: Path, bundles: list[dict], *, recorded_root: Path | None = None
) -> list[dict]:
    summaries = []
    stage = bundles[0]["stage"] if bundles else "screen"
    folder = task_dir / "bundles" / stage
    folder.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        path = folder / f"{bundle['bundle_id']}.json"
        _atomic_write_json(path, bundle)
        recorded_path = (recorded_root or task_dir) / "bundles" / stage / path.name
        summaries.append({
            "id": bundle["bundle_id"],
            "path": str(recorded_path),
            "sha256": bundle["content_sha256"],
            "item_count": bundle["item_count"],
            "status": "pending",
            "assigned_to": "",
            "result_path": "",
        })
    return summaries


def shell_argument(value: str | Path) -> str:
    """Quote a handoff argument for PowerShell on Windows, sh elsewhere."""
    text = str(value)
    return "'" + text.replace("'", "''") + "'" if os.name == 'nt' else shlex.quote(text)


def runtime_command(script: str | Path) -> str:
    """Use the running managed interpreter, even with no Python on PATH.

    Windows pipes use the ANSI code page, which cannot hold Japanese game text,
    so Python writes UTF-8 and PowerShell decodes it; the app's
    dazedtl.translation.helper_command follows the same form.
    """
    prefix = '[Console]::OutputEncoding = [Text.Encoding]::UTF8; & ' if os.name == 'nt' else ''
    return prefix + shell_argument(sys.executable) + ' -X utf8 ' + shell_argument(script)


# Each brief's sections besides the policy, commands and result formats; a
# worker reviews whichever bundle next gives it.
_BRIEF_SECTIONS = {
    "screen": ("Screen reviewer",),
    "deep": ("Deep reviewer",),
    "group": ("Group reviewer",),
    "editorial": ("Editorial reviewer",),
    "worker": (
        "Worker", "Screen reviewer", "Deep reviewer", "Group reviewer", "Editorial reviewer",
    ),
}
QA_ROLES = tuple(_BRIEF_SECTIONS)
_SKILL_SECTION_RE = re.compile(r"^## (.+)$", re.M)


def _skill_sections(focus: str) -> tuple[str, dict[str, str], str]:
    """The QA policy's introduction, its sections by title, and the focus."""
    common, selected = rpgmaker_qa_skill_parts(focus)
    starts = list(_SKILL_SECTION_RE.finditer(common))
    intro = common[: starts[0].start()].strip() if starts else common
    sections = {
        match.group(1).strip(): common[
            match.end() : starts[index + 1].start() if index + 1 < len(starts) else None
        ].strip()
        for index, match in enumerate(starts)
    }
    return intro, sections, selected


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _skill_values(task_dir: Path, task: dict[str, Any]) -> dict[str, str]:
    return {
        "CLI": runtime_command(
            Path(__file__).resolve().parents[1] / "scripts" / "rpgmaker_qa.py"
        ),
        "TASK": shell_argument(task_dir),
        "CONTEXT": str(task_dir / "context.json"),
        "RECEIPTS": str(
            Path(task["game_root"]) / ".dazedtl" / "qa-receipts" / task_dir.name
        ),
        "CATEGORIES": ", ".join(sorted(FINDING_CATEGORIES)),
        "SCREEN_SCHEMA": SCREEN_RESULT_SCHEMA,
        "DEEP_SCHEMA": DEEP_RESULT_SCHEMA,
        "SWEEP_SCHEMA": SWEEP_RESULT_SCHEMA,
        "EDITORIAL_SCHEMA": EDITORIAL_RESULT_SCHEMA,
    }


def _task_instructions(task_dir: Path, task: dict[str, Any]) -> str:
    """The task README: the QA policy with every role's brief, for this task."""
    intro, sections, focus = _skill_sections(task["focus"])
    body = "\n\n".join(
        f"## {title}\n\n{text}" for title, text in sections.items() if title != "Handoff"
    )
    return _fill(
        f"# Text QA task\n\nTask: `{task_dir}`\n\n{focus}\n\n{intro}\n\n{body}\n",
        _skill_values(task_dir, task),
    )


def brief(task_dir: str | Path, role: str, worker: str = "") -> str:
    """One reviewer's brief: the policy, its role, the commands, and the
    game's guidance and decisions, so a reviewer reads no other context.

    A named *worker* starts a run with it, whose bundles `accept_text` counts.
    """
    if role not in QA_ROLES:
        raise ValueError("Choose a role: " + ", ".join(QA_ROLES))
    if worker:
        root = Path(task_dir).expanduser().resolve()
        with _task_lock(root):
            _root, _task, checkpoint = _load_task(root)
            _register_worker(checkpoint, worker, None)
            checkpoint["workers"][worker]["run_started"] = _utc_now()
            _atomic_write_json(root / "checkpoint.json", checkpoint)
    root, task, _checkpoint = _load_task(task_dir)
    _intro, sections, focus = _skill_sections(task["focus"])
    parts = [focus] + [
        f"## {name}\n\n{sections[name]}"
        for name in ("Policy", *_BRIEF_SECTIONS[role], "Commands", "Result formats")
    ]
    # The game's own text is appended after filling, so it is never read as
    # a placeholder.
    return "\n\n".join(
        [_fill("\n\n".join(parts), _skill_values(root, task)), *_game_guidance(root)]
    ) + "\n"


def _decision_line(decision: dict[str, Any]) -> str:
    wording = (
        f" ({decision['source']} = {decision['translation']})"
        if decision.get("source") else ""
    )
    return f"- {decision['key']}: {decision['choice']}{wording}"


def _game_guidance(root: Path) -> list[str]:
    """The task context's game notes, translation quirks, custom guidance and
    the decisions recorded so far; bundles carry the glossary entries they use."""
    context = _read_json(root / "context.json")
    documents = [
        ("Game notes", context.get("game")),
        ("Translation quirks", context.get("quirks")),
        *(
            (f"Game guidance: {Path(str(overlay.get('path') or '')).stem}", overlay)
            for overlay in context.get("overlays") or []
        ),
    ]
    parts = [
        f"## {title}\n\n{text}"
        for title, document in documents
        if (text := str((document or {}).get("text") or "").strip())
    ]
    if decisions := _decisions(root):
        parts.append("## Decisions\n\n" + "\n".join(map(_decision_line, decisions)))
    return parts


def handoff_text(task_dir: str | Path, helper: str) -> str:
    """The copied task: the policy's handoff for this task and helper."""
    root, task, _checkpoint = _load_task(task_dir)
    _intro, sections, _focus = _skill_sections(task["focus"])
    return _fill(
        sections["Handoff"],
        {
            "GAME": Path(task["game_root"]).name,
            "README": str(root / "README.md"),
            "HELPER": helper,
        },
    ) + "\n"


# Earlier reviews. A finished task's reviews still stand for text that has not
# changed since, and a version the user says was checked before DazedTL counts
# as reviewed as it was then; a new task reads such lines only as context.
REVIEWED_SCHEMA = "rpgmaker-qa-reviewed-v1"
REVIEWED_FILE = "reviewed.json"
BASELINE_FOLDER = "baselines"


def _pair_key(source: Any, translation: Any) -> str:
    return _sha256(f"{source}\0{translation}")[:32]


def _guidance_lines(context: dict[str, Any]) -> dict[str, list[str]]:
    """Each glossary entry and translation quirk, with the Japanese terms it
    governs; a quirk without Japanese governs no line in particular."""
    lines = {
        line: terms
        for terms, _english, line in _glossary_entries(
            (context.get("glossary") or {}).get("text")
        )
    }
    for raw in str((context.get("quirks") or {}).get("text") or "").splitlines():
        line = raw.strip()
        if terms := _quirk_terms(line):
            lines[line] = terms
    return lines


_QUOTED_RE = re.compile(r"`([^`\n]+)`")
_NAMED_JAPANESE_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]*[一-龠々ァ-ヴ][一-龠々〆〤ぁ-ゔァ-ヴー]*")


def _quirk_terms(line: str) -> list[str]:
    """The Japanese a quirk governs: its quoted Japanese, each alternative
    apart, or else its words with kanji or katakana, never bare kana that
    common words share."""
    quoted = [
        part.strip()
        for span in _QUOTED_RE.findall(line)
        for part in span.split(" / ")
        if _JAPANESE_ANCHOR_RE.search(part)
    ]
    if quoted:
        return sorted(set(quoted))
    return sorted({
        word for word in _NAMED_JAPANESE_RE.findall(line) if len(word) >= 2
    })


def _task_ledger(root: Path) -> dict[str, Any] | None:
    """What a complete task reviewed and left standing, kept in its folder:
    lines screened or deep-reviewed, minus any whose finding still waits to be
    applied or whose review was declined, plus the corrections editorial
    confirmed."""
    cached = root / REVIEWED_FILE
    try:
        ledger = _read_json(cached)
        if ledger.get("schema") == REVIEWED_SCHEMA:
            return ledger
    except (OSError, ValueError):
        pass
    try:
        _root, _task, checkpoint = _read_task(root)
        if checkpoint["stage"] != "complete":
            return None
        ledger = _derive_ledger(root, checkpoint)
    except (OSError, ValueError, KeyError, TypeError):
        # A task whose files moved or broke is no review to build on.
        return None
    try:
        _atomic_write_json(cached, ledger)
    except OSError:
        pass
    return ledger


def _derive_ledger(root: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    report = _read_json(root / "findings.json")
    context = _read_json(root / "context.json")
    reviewed: set[str] = set()
    scenes: set[str] = set()
    variants: set[str] = set()
    rejected: set[str] = set()
    cleared: dict[str, set[str]] = defaultdict(set)
    observed: set[str] = set()
    unsettled: set[str] = set()
    for row in checkpoint["screen"]["bundles"]:
        if row["status"] != "accepted" or row.get("check_of"):
            continue
        bundle = _read_json(Path(row["path"]))
        result = _read_json(Path(row["result_path"]))
        declined = _result_declines(result)
        motifs = {review["id"]: review for review in result.get("motif_reviews") or []}
        lints = {review["id"]: review for review in result.get("lint_reviews") or []}
        for item in bundle["items"]:
            if item["id"] in declined:
                continue
            kind = item.get("kind")
            if kind == "scene":
                scenes.add(item["id"])
                reviewed.update(
                    _pair_key(line["source"], line["translation"])
                    for line in item["lines"] if "id" in line
                )
            elif kind == "cluster":
                reviewed.add(_pair_key(item["source"], item["translation"]))
            elif kind == "motif-family" and (
                motifs.get(item["id"]) or {}
            ).get("disposition") == "preserved":
                variants.update(
                    _pair_key(item["id"], _pair_key(variant["source"], variant["translation"]))
                    for variant in item["variants"] if variant["id"] not in declined
                )
            elif kind == "lint-family" and item["id"] in lints:
                rejected.update(
                    _sha256(
                        f"{proposal['source']}\0{proposal['current']}\0{proposal['proposed']}"
                    )[:32]
                    for proposal in item["proposals"]
                    if proposal["id"] in set(lints[item["id"]]["rejected"]) - declined
                )
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] != "accepted":
            continue
        items = {item["id"]: item for item in _read_json(Path(row["path"]))["items"]}
        for review in _read_json(Path(row["result_path"]))["reviews"]:
            item = items[review["id"]]
            pair = _pair_key(item["source"], item["translation"])
            if review["disposition"] == "declined":
                unsettled.add(pair)
                continue
            if review["disposition"] == "clean":
                reviewed.add(pair)
                cleared[pair].update(item.get("deep_reasons") or [])
            observed.update(
                _sha256(f"{pair}\0{evidence['note']}")[:32]
                for evidence in item.get("screen_evidence") or []
                if evidence.get("verdict") == "observation"
            )
    for finding in report.get("findings") or []:
        for change in _changes(finding):
            unsettled.add(_pair_key(change["source"], change["current"]))
            # Editorial confirmed the correction, which passed every check.
            corrected = _pair_key(change["source"], change["correction"])
            reviewed.add(corrected)
            cleared[corrected].add("*")
    for row in [
        *(report.get("uncertain_playtests") or []), *(report.get("not_reviewed") or []),
    ]:
        unsettled.add(_pair_key(row.get("source"), row.get("current")))
    return {
        "schema": REVIEWED_SCHEMA,
        "origin": f"task {root.name}",
        "pairs": sorted(reviewed - unsettled),
        "scenes": sorted(scenes),
        "variants": sorted(variants),
        "lint_rejected": sorted(rejected),
        "cleared": {
            pair: sorted(reasons) for pair, reasons in sorted(cleared.items())
            if pair not in unsettled
        },
        "observed": sorted(observed),
        "guidance": _guidance_lines(context),
    }


def _baseline_commit(game: Path, since: str) -> tuple[Path, str, str]:
    """The repository and commit whose translation a since-scope treats as
    reviewed: before the update that brought version *since*, or *since* as
    a Git revision; and how to name it."""
    from util.version_update.git_workflow import (
        _VERSION_LINE, GitWorkflowError, _run_git,
    )

    try:
        repo = Path(
            _run_git(game, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        log = _run_git(
            repo, "log", "--first-parent", "--format=%H%x00%B%x1e", "HEAD"
        ).stdout
    except GitWorkflowError as exc:
        raise ValueError(
            "QA can take earlier text as checked only in a game saved in Git: "
            f"{exc}"
        ) from exc
    for entry in log.split("\x1e"):
        commit, _, message = entry.strip("\n").partition("\x00")
        version = _VERSION_LINE.search(message)
        if (
            message.strip().startswith("patch:")
            and version and version.group(1).strip() == since.strip()
        ):
            parent = _run_git(repo, "rev-parse", f"{commit}^").stdout.strip()
            return repo, parent, f"before the {since.strip()} update"
    resolved = _run_git(
        repo, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}", check=False
    )
    if resolved.returncode != 0 or not resolved.stdout.strip():
        raise ValueError(
            f"{since} is neither a version this game was updated to nor a Git revision"
        )
    commit = resolved.stdout.strip()
    return repo, commit, f"as of {commit[:12]}"


def _baseline_ledger(
    storage: Path, game: Path, data: Path, focus: str, since: str
) -> dict[str, Any]:
    """Every line of the game as it was translated at the baseline, which the
    user says was reviewed before, as a ledger kept with the game's tasks."""
    import io
    import subprocess
    import tarfile

    from util.version_update.git_workflow import _run_git

    repo, commit, label = _baseline_commit(game, since)
    path = storage / BASELINE_FOLDER / f"{commit}.json"
    try:
        ledger = _read_json(path)
        if ledger.get("schema") == REVIEWED_SCHEMA:
            return ledger
    except (OSError, ValueError):
        pass
    relative = data.relative_to(repo).as_posix()
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", commit, "--", relative],
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        raise ValueError(
            f"Git could not read the game's data at {commit[:12]}: "
            + archive.stderr.decode("utf-8", "replace").strip()
        )
    with tempfile.TemporaryDirectory(prefix="dazedtl-qa-baseline-") as temporary:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(temporary, filter="data")
        manifest = build_manifest(Path(temporary) / relative, focus)
    guidance = {}
    for name, relative_path in (
        ("glossary", GAME_GLOSSARY_RELATIVE), ("quirks", GAME_QUIRKS_RELATIVE),
    ):
        pointer = (game / relative_path).relative_to(repo).as_posix()
        shown = _run_git(repo, "show", f"{commit}:{pointer}", check=False)
        guidance[name] = {"text": shown.stdout if shown.returncode == 0 else ""}
    groups, _cluster_ids = _scene_groups(manifest)
    ledger = {
        "schema": REVIEWED_SCHEMA,
        "origin": f"since {since.strip()}",
        "commit": commit,
        "label": label,
        "everything": True,
        "pairs": sorted({
            _pair_key(cluster["source"], cluster["live"])
            for cluster in manifest["clusters"]
        }),
        "scenes": sorted("scene-" + group["signature"][:20] for group in groups),
        "guidance": _guidance_lines(guidance),
    }
    _atomic_write_json(path, ledger)
    return ledger


_KANA_RE = re.compile(r"[ぁ-ゔァ-ヴー]+")
_LINE_PUNCTUATION_RE = re.compile(r"[\s。、！？!?…‥―〜~・「」『』]+")


class _Terms:
    """Changed guidance terms found in a line's Japanese. A word of two kana
    or fewer, such as a pun on なる, governs only a line that is that word, or
    it would reopen every line sharing common kana."""

    def __init__(self, terms: set[str]):
        whole = {
            bare for term in terms
            if _KANA_RE.fullmatch(bare := _LINE_PUNCTUATION_RE.sub("", term))
            and len(bare) <= 2
        }
        inside = sorted(
            (term for term in terms if _LINE_PUNCTUATION_RE.sub("", term) not in whole),
            key=lambda term: (-len(term), term),
        )
        self.whole = whole
        self.inside = re.compile("|".join(map(re.escape, inside))) if inside else None

    def search(self, source: str) -> bool:
        return bool(self.inside and self.inside.search(source)) or (
            _LINE_PUNCTUATION_RE.sub("", source) in self.whole
        )


def _terms_pattern(terms: set[str]) -> _Terms | None:
    return _Terms(terms) if terms else None


class _Reviewed:
    """What earlier tasks and baselines reviewed that still stands for this
    task's guidance: a ledger's line no longer counts once a glossary entry
    or quirk whose Japanese it holds changed since that review."""

    def __init__(self, ledgers: list[dict[str, Any]], context: dict[str, Any]):
        guidance = _guidance_lines(context)
        self.ledgers = []
        for ledger in ledgers:
            before = ledger.get("guidance") or {}
            changed = {
                term for line in before.keys() ^ guidance.keys()
                for term in before.get(line) or guidance.get(line) or []
            }
            self.ledgers.append((
                ledger,
                {key: set(ledger.get(key) or []) for key in (
                    "pairs", "scenes", "variants", "lint_rejected", "observed",
                )},
                _terms_pattern(changed),
            ))
        self.origins = [ledger["origin"] for ledger in ledgers]

    def __bool__(self) -> bool:
        return bool(self.ledgers)

    def _standing(self, source: str) -> list[tuple[dict, dict[str, set[str]]]]:
        return [
            (ledger, sets) for ledger, sets, changed in self.ledgers
            if changed is None or not changed.search(source)
        ]

    def line(self, source: Any, translation: Any) -> bool:
        key = _pair_key(source, translation)
        return any(key in sets["pairs"] for _ledger, sets in self._standing(str(source)))

    def scene(self, scene_id: str, lines: Iterable[tuple[Any, Any]]) -> bool:
        """Whether a scene with this text was screened, or holds only text
        reviewed before, such as corrections editorial confirmed; changed
        guidance reopens the lines it governs, not the scene's other lines."""
        if any(scene_id in sets["scenes"] for _ledger, sets, _changed in self.ledgers):
            return True
        return all(
            any(_pair_key(source, translation) in sets["pairs"] for _l, sets, _c in self.ledgers)
            for source, translation in lines
        )

    def cleared(self, source: Any, translation: Any, reasons: Iterable[str]) -> bool:
        """Whether deep review already settled every one of these reasons for
        the line, so they send it to deep review no more. Squeezed text and
        text too long for its window are always looked at again, since a
        capture or new Line widths can change what fits."""
        reasons = set(reasons)
        if reasons & {"interface-fit", "text-fit"}:
            return False
        key = _pair_key(source, translation)
        settled: set[str] = set()
        for ledger, sets in self._standing(str(source)):
            if ledger.get("everything") and key in sets["pairs"]:
                return True
            settled.update((ledger.get("cleared") or {}).get(key) or [])
        return bool(reasons) and ("*" in settled or reasons <= settled)

    def variant(self, family: str, source: Any, translation: Any) -> bool:
        pair = _pair_key(source, translation)
        key = _pair_key(family, pair)
        return any(
            key in sets["variants"] or ledger.get("everything") and pair in sets["pairs"]
            for ledger, sets in self._standing(str(source))
        )

    def lint_rejected(self, source: Any, current: Any, proposed: Any) -> bool:
        pair = _pair_key(source, current)
        key = _sha256(f"{source}\0{current}\0{proposed}")[:32]
        return any(
            key in sets["lint_rejected"]
            or ledger.get("everything") and pair in sets["pairs"]
            for ledger, sets in self._standing(str(source))
        )

    def observed(self, source: Any, translation: Any, note: str) -> bool:
        key = _sha256(f"{_pair_key(source, translation)}\0{note}")[:32]
        return any(key in sets["observed"] for _ledger, sets in self._standing(str(source)))


def _earlier_reviews(games: Path, context: dict[str, Any]) -> _Reviewed:
    """The reviews a new task builds on: every complete task of this game and
    every baseline the user named."""
    ledgers = [
        ledger
        for path in sorted(games.glob(f"*/*/{REVIEWED_FILE}"))
        if (ledger := _task_ledger(path.parent))
    ]
    seen = {path.parent for path in games.glob(f"*/*/{REVIEWED_FILE}")}
    ledgers += [
        ledger
        for task in sorted(games.glob("*/*/task.json"))
        if task.parent not in seen and (ledger := _task_ledger(task.parent))
    ]
    for path in sorted((games / BASELINE_FOLDER).glob("*.json")):
        try:
            ledger = _read_json(path)
        except (OSError, ValueError):
            continue
        if ledger.get("schema") == REVIEWED_SCHEMA:
            ledgers.append(ledger)
    return _Reviewed(ledgers, context)


def prepare_task(
    game_root: str | Path,
    data_root: str | Path,
    focus: str,
    output_root: str | Path,
    *,
    screen_char_budget: int = DEFAULT_SCREEN_CHAR_BUDGET,
    screen_item_limit: int = DEFAULT_SCREEN_ITEM_LIMIT,
    fit: dict[str, Any] | None = None,
    interface: bool = False,
    progress: Callable[[str], None] | None = None,
    observations: Iterable[dict[str, Any]] = (),
    observer: str = "playtest",
    kept: Iterable[dict[str, Any]] = (),
    since: str | None = None,
    earlier: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Create or reuse one immutable QA task and its exhaustive screen bundles.

    A new task builds on [earlier reviews](#earlier-reviews): lines a complete
    task of this game reviewed, unchanged since and with the same glossary
    entries and quirks, are read only as context, and so are lines unchanged
    since a baseline the user named once with *since*, a version this game was
    updated to or a Git revision, whose earlier text was checked before. A
    baseline stays in effect for the game's later tasks. *earlier* False
    reviews everything.

    *fit* holds the Line widths the task fits corrections to; a task already
    prepared keeps the ones it was made with.
    With *interface*, the game's interface screens are captured, and text the
    game squeezes or cuts off on them goes to deep review with its captures;
    *progress* hears which screen the capture is on. A task prepared again
    captures them again once the game's plugin files changed since, keeping
    its review.

    Observations made outside QA, such as the release playtest's findings in
    translated text, start in its checkpoint, so deep review takes their lines;
    a task with different observations is another task, and one a line the
    inventory lacks is left out.

    *kept* names the plugin settings the plugin task keeps in Japanese on
    purpose, which the never-translated report leaves out. A task prepared
    again keeps its review, but reads that report again, since plugin
    settings, custom data files and the plugin task's decisions change it
    without changing the inventory.
    """
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if not game.is_dir() or not data.is_dir() or game not in data.parents:
        raise ValueError("The QA data folder must be inside the selected game folder")
    storage = _safe_task_root(output_root, game)
    layout = task_layout(game, fit)
    manifest = build_manifest(data, focus)
    validation = verify_manifest(data, manifest)
    if not validation["valid"]:
        raise ValueError("QA inventory validation failed: " + "; ".join(validation["errors"]))
    context = _context_pack(
        game, (str(record.get("source") or "") for record in manifest["records"])
    )
    engine_fingerprint = _engine_fingerprint()
    screen_configuration = {
        "char_budget": int(screen_char_budget),
        "item_limit": int(screen_item_limit),
    }
    observed = []
    for entry in observations:
        try:
            (observation,) = _read_observations([entry], manifest)
        except QAResultError:
            continue
        if all(row["identity"] != observation["identity"] for row in observed):
            observed.append(observation)
    games = storage / _slug(game.name)
    if since and earlier:
        _baseline_ledger(games, game, data, focus, since)
    baselines = sorted(
        path.stem for path in (games / BASELINE_FOLDER).glob("*.json")
    ) if earlier else []
    # A baseline is the user's scope, so a task under another is another task;
    # tasks finished since leave a prepared task as it is.
    task_key = _sha256(
        f"{TASK_SCHEMA}\0{engine_fingerprint}\0{focus}\0"
        f"{manifest['content_sha256']}\0{context['content_sha256']}\0"
        f"{_sha256(_canonical_bytes(screen_configuration))}"
        + (f"\0{_sha256(_canonical_bytes(observed))}" if observed else "")
        + (f"\0baselines:{','.join(baselines)}" if baselines else "")
        + ("" if earlier else "\0everything")
    )[:16]
    task_parent = games / focus
    task_parent.mkdir(parents=True, exist_ok=True)
    task_dir = task_parent / task_key
    with _task_lock(task_parent):
        existing = task_dir / "task.json"
        if existing.is_file():
            task = _read_json(existing)
            if task.get("schema") != TASK_SCHEMA:
                raise ValueError(f"Existing QA task has an unsupported schema: {task_dir}")
            report = preflight(data, manifest, kept)
            with _task_lock(task_dir):
                _write_report(task_dir, report)
            if interface:
                _recapture(task_dir, data, manifest, progress)
            return task_dir, status(task_dir)

        staging = new_folder(task_parent, f".{task_key}.")
        try:
            write_manifest(manifest, staging / "inventory.json")
            _atomic_write_json(staging / "inventory-validation.json", validation)
            # Japanese never translated is reported, never silently skipped.
            _atomic_write_json(staging / "preflight.json", preflight(data, manifest, kept))
            _atomic_write_json(staging / "context.json", context)
            reviewed = (
                _earlier_reviews(games, context) if earlier else _Reviewed([], context)
            )
            _records, clusters_by_id = _record_maps(manifest)

            def settled(cluster_id: str, reasons: list[str]) -> bool:
                cluster = clusters_by_id[cluster_id]
                return bool(reviewed) and reviewed.cleared(
                    cluster["source"], cluster["live"], reasons
                )

            compact_items = _compact_items(manifest, context)
            forced_candidates = {
                item["id"]: _candidate(forced_reasons)
                for item in compact_items
                if (forced_reasons := _forced_deep_reasons(item))
                and not settled(item["id"], forced_reasons)
            }
            for cluster_id, failed in _database_checks(manifest, data).items():
                reasons = [entry["check"] for entry in failed]
                if not settled(cluster_id, reasons):
                    _merge_candidate(forced_candidates, cluster_id, reasons)
            # Text too long for its window even wrapped goes to a reviewer to
            # shorten.
            for cluster_id in _fit_checks(manifest, layout):
                if not settled(cluster_id, ["text-fit"]):
                    _merge_candidate(forced_candidates, cluster_id, ["text-fit"])
            if interface:
                (staging / INTERFACE_FOLDER).mkdir()
                capture, places = _capture_round(data, staging, 1, manifest, progress)
                _save_capture_record(staging, capture)
                for cluster_id in places:
                    _merge_candidate(forced_candidates, cluster_id, ["interface-fit"])
            # A likely slip in a line's Show Text header goes to deep review,
            # where a reviewer fixes the header or says why it is right.
            headers = _header_flags(data, manifest)
            _atomic_write_json(staging / "header-check.json", headers)
            clusters = _cluster_by_identity(manifest)
            for flag in headers["flags"]:
                if flag["identity"] and not settled(
                    clusters[flag["identity"]], ["show-text-header"]
                ):
                    _merge_candidate(
                        forced_candidates, clusters[flag["identity"]],
                        ["show-text-header"], [flag["identity"]],
                    )
            lint_items, lint_fixes = _lint_items(
                manifest, layout, _game(manifest, context), reviewed
            )
            items, screen_index = _screen_items(
                manifest, context, data, lint_fixes, reviewed
            )
            screen_index_document = {
                "schema": "rpgmaker-qa-screen-index-v1",
                "targets": screen_index,
            }
            screen_index_document["content_sha256"] = _sha256(
                _canonical_bytes(screen_index_document)
            )
            _atomic_write_json(staging / "screen-index.json", screen_index_document)
            # Lint families come first, in bundles of their own.
            ordinal = max(
                [item["ordinal"] for item in items if "ordinal" in item]
                + [
                    line["ordinal"] for item in items
                    for line in item.get("lines") or [] if "ordinal" in line
                ]
                + [0]
            )
            for ordinal, item in enumerate(lint_items, start=ordinal + 1):
                item["ordinal"] = ordinal
            bundles = _bundle_items(
                lint_items,
                stage="screen",
                char_budget=screen_char_budget,
                item_limit=screen_item_limit,
            )
            bundles += _bundle_items(
                items,
                stage="screen",
                char_budget=screen_char_budget,
                item_limit=screen_item_limit,
                first=len(bundles) + 1,
            )
            items += lint_items
            _atomic_write_json(
                staging / "screen-targets.json", _screen_targets(items, bundles)
            )
            bundle_summaries = _write_bundles(
                staging, bundles, recorded_root=task_dir
            )
            task = {
                "schema": TASK_SCHEMA,
                "created_at": _utc_now(),
                "game_root": str(game),
                "data_root": str(data),
                "focus": focus,
                "engine_fingerprint": engine_fingerprint,
                "screen_configuration": screen_configuration,
                "layout": layout,
                "manifest_sha256": manifest["content_sha256"],
                "context_sha256": context["content_sha256"],
                "screen_index_sha256": screen_index_document["content_sha256"],
                "counts": manifest["counts"],
            }
            if reviewed:
                # Lines as the task counts them: every place a text shows.
                task["reviewed_before"] = {
                    "lines": sum(
                        len(cluster["identities"])
                        for cluster in manifest["clusters"]
                        if reviewed.line(cluster["source"], cluster["live"])
                    ),
                    "from": reviewed.origins,
                }
            checkpoint = {
                "schema": CHECKPOINT_SCHEMA,
                "task_sha256": _sha256(_canonical_bytes(task)),
                "updated_at": _utc_now(),
                "stage": "screen",
                "screen": {
                    "total_items": sum(
                        int(item.get("target_count", 1)) for item in items
                    ),
                    "accepted_items": 0,
                    "exception_ids": [],
                    "motif_total": sum(
                        item.get("kind") == "motif-family" for item in items
                    ),
                    "motif_accepted": 0,
                    "lint_total": sum(
                        item["target_count"] for item in lint_items
                    ),
                    "lint_accepted": 0,
                    "bundles": bundle_summaries,
                },
                "deep": {
                    "total_items": 0,
                    "accepted_items": 0,
                    "projected_items": len(forced_candidates),
                    "candidate_reasons": forced_candidates,
                    "bundles": [],
                },
                "sweep": {"total_items": 0, "accepted_items": 0, "bundles": []},
                "editorial": {
                    "total_items": 0, "accepted_items": 0, "bundles": [], "round": 0,
                },
                "findings_file": "",
            }
            # An observation deep review already judged for the same text is
            # not asked again.
            _note_observations(checkpoint, [
                observation for observation in observed
                if not (reviewed and reviewed.observed(
                    clusters_by_id[observation["cluster_id"]]["source"],
                    clusters_by_id[observation["cluster_id"]]["live"],
                    observation["note"],
                ))
            ], "screen", observer)
            _atomic_write_json(staging / "task.json", task)
            _atomic_write_json(staging / "checkpoint.json", checkpoint)
            _atomic_write_text(
                staging / "README.md", _task_instructions(task_dir, task)
            )
            staging.replace(task_dir)
        except Exception:
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise
    return task_dir, status(task_dir)


def _read_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    """The task and its checkpoint for reading, whichever rules prepared it."""
    root = Path(task_dir).expanduser().resolve()
    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    if task.get("schema") != TASK_SCHEMA or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError(f"Unsupported or corrupt QA task: {root}")
    return root, task, checkpoint


def _load_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    """The task and its checkpoint for work, which needs the rules that made it."""
    root, task, checkpoint = _read_task(task_dir)
    if task.get("engine_fingerprint") != _engine_fingerprint():
        raise ValueError(
            f"QA rules changed after this task was prepared; create a fresh task: {root}"
        )
    return root, task, checkpoint


def _reviewed_seconds(rows: list[dict[str, Any]]) -> list[tuple[float, int]]:
    """Each accepted bundle's review time and target count."""
    return [
        (
            (
                datetime.fromisoformat(row["accepted_at"])
                - datetime.fromisoformat(row["assigned_at"])
            ).total_seconds(),
            int(row["item_count"]),
        )
        for row in rows
        if row["status"] == "accepted"
        and row.get("assigned_at")
        and row.get("accepted_at")
        and int(row["item_count"])
    ]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    )


def _seconds_per_item(checkpoint: dict[str, Any], stage: str) -> float:
    timed = _reviewed_seconds(checkpoint.get(stage, {}).get("bundles", []))
    if not timed:
        return DEFAULT_SECONDS_PER_ITEM[stage]
    return _median([seconds / count for seconds, count in timed])


def _stall_after(checkpoint: dict[str, Any], stage: str) -> float:
    timed = _reviewed_seconds(checkpoint.get(stage, {}).get("bundles", []))
    typical = _median([seconds for seconds, _count in timed]) if timed else 0.0
    return max(STALL_MINIMUM_SECONDS, 3 * typical)


def _stalled(checkpoint: dict[str, Any], stage: str, row: dict[str, Any]) -> bool:
    if row["status"] != "assigned" or not row.get("assigned_at"):
        return False
    seen = (checkpoint.get("workers") or {}).get(row.get("assigned_to") or "", {})
    last = max(
        datetime.fromisoformat(row["assigned_at"]),
        datetime.fromisoformat(seen.get("last_seen") or row["assigned_at"]),
    )
    idle = (datetime.now(timezone.utc) - last).total_seconds()
    return idle > _stall_after(checkpoint, stage)


def _pace(checkpoint: dict[str, Any], now: datetime) -> tuple[float, int]:
    """How many bundles QA reviewed at once in its latest work, on average,
    and how many bundles that work held.

    Reviewers are counted by the bundles they held, not the names they used:
    one session taking turns under two names reviews one bundle at a time.
    The window ends at the latest review, so a pause leaves the pace as QA
    last worked; idle time between bundles inside it slows the pace, as it
    slows QA.
    """
    spans = []
    for stage in REVIEW_STAGES:
        for row in (checkpoint.get(stage) or {}).get("bundles", []):
            if not row.get("assigned_at"):
                continue
            if row["status"] == "accepted" and row.get("accepted_at"):
                end = datetime.fromisoformat(row["accepted_at"])
            elif row["status"] == "assigned" and not _stalled(checkpoint, stage, row):
                end = now
            else:
                continue
            spans.append((datetime.fromisoformat(row["assigned_at"]), end))
    if not spans:
        return 0.0, 0
    latest = max(end for _start, end in spans)
    recent = [
        span for span in spans
        if span[1] > latest - timedelta(seconds=ACTIVE_WORKER_SECONDS)
    ]
    start = max(
        latest - timedelta(seconds=ACTIVE_WORKER_SECONDS),
        min(begin for begin, _end in recent),
    )
    window = (latest - start).total_seconds()
    reviewing = sum((end - max(begin, start)).total_seconds() for begin, end in recent)
    return (reviewing / window if window > 0 else 1.0), len(recent)


def _estimate(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """The work left by stage and the engine's estimate of its time."""
    now = datetime.now(timezone.utc)
    active = sorted(
        name for name, worker in (checkpoint.get("workers") or {}).items()
        if worker.get("last_seen")
        and (now - datetime.fromisoformat(worker["last_seen"])).total_seconds()
        <= ACTIVE_WORKER_SECONDS
    )
    remaining = {}
    for stage in REVIEW_STAGES:
        state = checkpoint.get(stage) or {}
        total = int(state.get("total_items", 0))
        if stage == "deep":
            total = max(total, int(state.get("projected_items", 0)))
        set_aside = sum(
            row["item_count"] for row in state.get("bundles", [])
            if row["status"] == "set-aside"
        )
        remaining[stage] = max(0, total - int(state.get("accepted_items", 0)) - set_aside)
        if stage == "screen":
            checks = _check_counts(state)
            remaining[stage] += checks["projected"] - checks["accepted"]
    seconds = sum(
        remaining[stage] * _seconds_per_item(checkpoint, stage) for stage in remaining
    )
    measured = any(
        _reviewed_seconds((checkpoint.get(stage) or {}).get("bundles", []))
        for stage in REVIEW_STAGES
    )
    at_once, recent = _pace(checkpoint, now)
    waiting = any(
        row["status"] == "pending" and not row.get("declined_by")
        for stage in REVIEW_STAGES
        for row in (checkpoint.get(stage) or {}).get("bundles", [])
    )
    return {
        "remaining": remaining,
        "workers": active,
        "in_review_at_once": round(at_once, 1),
        # Bundles waited while reviewers took them one after another.
        "one_at_a_time": waiting
        and recent >= ONE_AT_A_TIME_BUNDLES
        and at_once < ONE_AT_A_TIME_BELOW,
        "eta_seconds": round(seconds / (at_once or 1)) if measured else None,
    }


def _stage_metrics(stage: dict[str, Any], *, active: bool) -> dict[str, Any]:
    # A split bundle's items are in the bundles made from it.
    bundles = [row for row in stage["bundles"] if row["status"] != "split"]
    assigned = [row for row in bundles if row["status"] == "assigned"]
    accepted = [row for row in bundles if row["status"] == "accepted"]
    starts = [
        datetime.fromisoformat(row["assigned_at"])
        for row in bundles if row.get("assigned_at")
    ]
    elapsed_seconds = 0.0
    if starts:
        if active:
            end = datetime.now(timezone.utc)
        else:
            accepted_times = [
                datetime.fromisoformat(row["accepted_at"])
                for row in accepted if row.get("accepted_at")
            ]
            end = max(accepted_times) if accepted_times else min(starts)
        elapsed_seconds = max(0.0, (end - min(starts)).total_seconds())
    accepted_items = int(stage["accepted_items"])
    items_per_minute = (
        accepted_items / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    )
    remaining = max(0, int(stage["total_items"]) - accepted_items)
    eta_seconds = remaining / (items_per_minute / 60) if items_per_minute else None
    return {
        "bundles_accepted": len(accepted),
        "bundles_assigned": len(assigned),
        "bundles_pending": sum(row["status"] == "pending" for row in bundles),
        "bundles_total": len(bundles),
        "assigned_workers": sorted({
            str(row.get("assigned_to") or "") for row in assigned
            if str(row.get("assigned_to") or "")
        }),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "items_per_minute": round(items_per_minute, 1),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
    }


def status(task_dir: str | Path) -> dict[str, Any]:
    # A task an update made unusable still reports where it stood.
    root, task, checkpoint = _read_task(task_dir)
    screen = checkpoint["screen"]
    deep = checkpoint["deep"]
    return {
        "task": str(root),
        "focus": task["focus"],
        "engine_fingerprint": task["engine_fingerprint"],
        "rules_changed": task["engine_fingerprint"] != _engine_fingerprint(),
        "stage": checkpoint["stage"],
        "mechanical": {
            "checked": task["counts"]["records"],
            "total": task["counts"]["records"],
            "unresolved": task["counts"]["unresolved"],
        },
        "not_translated": _not_translated(root),
        # Lines earlier QA reviewed, unchanged since, which this task reads
        # only as context.
        **(
            {"reviewed_before": task["reviewed_before"]}
            if task.get("reviewed_before") else {}
        ),
        **(
            {"interface": captured["summary"]}
            if (captured := interface_capture(root))
            else {}
        ),
        "screen": {
            "accepted": screen["accepted_items"],
            "total": screen["total_items"],
            "exceptions": len(screen.get("exception_ids") or []),
            "motif_families": {
                "accepted": int(screen.get("motif_accepted", 0)),
                "total": int(screen.get("motif_total", 0)),
            },
            "lint": {
                "accepted": int(screen.get("lint_accepted", 0)),
                "total": int(screen.get("lint_total", 0)),
                "declined": _declined_lint(screen),
            },
            # Second screens add no coverage, so they are counted apart.
            "checks": _check_counts(screen),
            **_stage_metrics(screen, active=checkpoint["stage"] == "screen"),
        },
        "deep": {
            "accepted": deep["accepted_items"],
            "total": deep["total_items"],
            "projected": deep.get("projected_items", deep["total_items"]),
            **_stage_metrics(deep, active=checkpoint["stage"] == "deep"),
        },
        "sweep": {
            "accepted": checkpoint.get("sweep", {}).get("accepted_items", 0),
            "total": checkpoint.get("sweep", {}).get("total_items", 0),
            **_stage_metrics(
                checkpoint.get("sweep") or {
                    "bundles": [], "accepted_items": 0, "total_items": 0,
                },
                active=checkpoint["stage"] == "sweep",
            ),
        },
        "editorial": {
            "accepted": checkpoint.get("editorial", {}).get("accepted_items", 0),
            "total": checkpoint.get("editorial", {}).get("total_items", 0),
            "round": checkpoint.get("editorial", {}).get("round", 0),
            **_stage_metrics(
                checkpoint.get("editorial") or {
                    "bundles": [], "accepted_items": 0, "total_items": 0,
                },
                active=checkpoint["stage"] == "editorial",
            ),
        },
        "decisions": len(_decisions(root)),
        "observations": len(checkpoint.get("observations") or []),
        "estimate": _estimate(checkpoint),
        "declined": _declined_counts(checkpoint),
        "findings_file": checkpoint.get("findings_file") or "",
    }


# Each task's never-translated counts and the plugin decisions they follow,
# kept while its preflight.json is unchanged: the app reads them every poll.
_REPORTS: dict[Path, tuple[tuple[int, int, int], dict[str, Any]]] = {}


def _report_summary(root: Path) -> dict[str, Any]:
    path = root / "preflight.json"
    try:
        stat = path.stat()
    except FileNotFoundError:
        # A task from before the preflight.
        return {"total": 0, "may_show": 0, "kept_sha256": None}
    signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    cached = _REPORTS.get(path)
    if cached and cached[0] == signature:
        return cached[1]
    report = _read_json(path)
    summary = {**_counted(report), "kept_sha256": report.get("kept_sha256")}
    _REPORTS[path] = (signature, summary)
    return summary


def _counted(report: dict[str, Any]) -> dict[str, int]:
    """A report's never-translated text, and what players may see of it; one
    from before reach was read counts it all as what players may see."""
    total = sum(report["counts"].values())
    return {"total": total, "may_show": report.get("may_show", total)}


def _not_translated(root: Path) -> dict[str, int]:
    """Japanese never translated, which QA did not review: all of it, and
    what players may see, as the task's preflight.json reports it now."""
    summary = _report_summary(root)
    return {"total": summary["total"], "may_show": summary["may_show"]}


def _not_translated_report(report: dict[str, Any]) -> dict[str, Any]:
    """Never a passing count: Japanese no reviewer read, by file and plugin,
    with whether players can reach it; preflight.json lists its text."""
    return {
        "reason": NOT_TRANSLATED_REASON,
        **_counted(report),
        "sources": [
            {key: value for key, value in source.items() if key != "texts"}
            for source in read_sources(report)
        ],
    }


def _write_report(root: Path, report: dict[str, Any]) -> None:
    """Saves the never-translated report a task holds now, its findings' copy
    first; the caller holds the task's lock."""
    path = root / "preflight.json"
    if path.is_file() and _read_json(path) == report:
        return
    findings = root / "findings.json"
    if findings.is_file():
        document = _read_json(findings)
        document["not_translated"] = _not_translated_report(report)
        if "coverage" in document:
            document["coverage"]["not_translated"] = _counted(report)
        _atomic_write_json(findings, document)
    _atomic_write_json(path, report)


def refresh_kept(task_dir: str | Path, kept: Iterable[dict[str, Any]]) -> None:
    """Has a task's never-translated report follow the plugin task's
    decisions, which change without changing the game's files, from the
    plugin settings the report recorded.

    Polls call it, so it costs a file check while the decisions are those
    the report followed, and leaves the work to a later call while another
    process holds the task. A report from before it recorded the settings
    waits for the task to be prepared again.
    """
    root = Path(task_dir).expanduser().resolve()
    kept = list(kept)
    recorded = _report_summary(root)["kept_sha256"]
    if recorded is None or recorded == kept_digest(kept):
        return
    with _task_lock(root, wait=False) as locked:
        if not locked:
            return
        report = with_kept(_read_json(root / "preflight.json"), kept)
        if report is None:
            return
        try:
            _write_report(root, report)
        except OSError:
            # Windows can't replace a file another program is reading; a
            # later poll writes it.
            pass


def _declined_lint(screen: dict[str, Any]) -> int:
    """Lint proposals declined and not reviewed since, which lint review no
    longer waits for."""
    if int(screen.get("lint_accepted", 0)) >= int(screen.get("lint_total", 0)):
        return 0
    return sum(
        item["target_count"]
        for row in screen["bundles"]
        if row.get("declined_by")
        and row["status"] in {"pending", "assigned", "set-aside"}
        for item in _read_json(Path(row["path"]))["items"]
        if item.get("kind") == "lint-family"
    )


def _declined_counts(checkpoint: dict[str, Any]) -> dict[str, int]:
    rows = [
        row for stage in REVIEW_STAGES
        for row in checkpoint.get(stage, {}).get("bundles", [])
        if row.get("declined_by")
    ]
    return {
        "waiting": sum(
            row["item_count"] for row in rows
            if row["status"] in {"pending", "assigned"}
        ),
        "set_aside": sum(
            row["item_count"] for row in rows if row["status"] == "set-aside"
        ),
    }


def _helper_of(checkpoint: dict[str, Any], worker: str) -> str:
    return str(
        ((checkpoint.get("workers") or {}).get(worker) or {}).get("helper")
        or DEFAULT_HELPER
    )


def _register_worker(
    checkpoint: dict[str, Any], worker: str, helper: str | None
) -> str:
    """Record the worker as seen and return its helper, which it keeps."""
    record = checkpoint.setdefault("workers", {}).setdefault(
        worker, {"bundles": 0, "seconds": 0.0}
    )
    named = " ".join(str(helper or "").split()).casefold()
    if len(named) > 60:
        raise ValueError("A helper name is one short line")
    if named and record.get("helper", named) != named:
        raise ValueError(
            f"{worker} runs on the {record['helper']} helper; give a worker on "
            "another helper a name of its own"
        )
    record["helper"] = record.get("helper") or named or DEFAULT_HELPER
    record["last_seen"] = _utc_now()
    return record["helper"]


def next_bundle(
    task_dir: str | Path,
    worker: str,
    bundle_id: str | None = None,
    *,
    helper: str | None = None,
    skip_declined: bool = False,
) -> dict[str, Any] | None:
    """Assign the worker its next bundle, or the named one.

    A worker never receives a bundle a worker on its helper declined; a worker
    on another helper can claim that bundle. With `skip_declined`, declined
    bundles nobody else took are set aside when their stage is otherwise
    reviewed, as advance and finalize would with it.
    """
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "worker")
    with _task_lock(root):
        for _transition in range(8):
            row, moved = _next_unlocked(root, worker, bundle_id, helper, skip_declined)
            if row is not None or not moved:
                return row
        return None


def claim(
    task_dir: str | Path,
    worker: str,
    bundle_id: str | None = None,
    *,
    helper: str | None = None,
    skip_declined: bool = False,
) -> str:
    """What a worker reads when it asks for a bundle: the bundle as text, with
    the decisions recorded since its last bundle, or why none waits for it."""
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "worker")
    row = next_bundle(
        root, worker, bundle_id, helper=helper, skip_declined=skip_declined
    )
    if row is None:
        return _no_bundle(root, worker)
    with _task_lock(root):
        _root, _task, checkpoint = _load_task(root)
        record = checkpoint["workers"][worker]
        seen = str(record.get("decisions_seen") or "")
        newer = [entry for entry in _decisions(root) if str(entry["at"]) > seen]
        if newer:
            record["decisions_seen"] = max(str(entry["at"]) for entry in newer)
            _atomic_write_json(root / "checkpoint.json", checkpoint)
    text = render_bundle(root, row["id"])
    if newer:
        text += "\n## DECISIONS recorded since your last bundle\n" + "\n".join(
            map(_decision_line, newer)
        ) + "\n"
    return text


def _no_bundle(root: Path, worker: str) -> str:
    state = status(root)
    stage = state["stage"]
    if stage not in REVIEW_STAGES:
        return f"No bundle for {worker}: QA is {stage}.\n"
    metrics = state[stage]
    return (
        f"No bundle for {worker} now: the {stage} stage has "
        f"{metrics['bundles_pending']} waiting for another reviewer and "
        f"{metrics['bundles_assigned']} in review.\n"
    )


def accept_text(
    task_dir: str | Path,
    result_path: str | Path,
    *,
    worker: str = "",
    then_next: bool = False,
) -> str:
    """Accept a result and say so in one line; with *then_next*, also claim
    and print the worker's next bundle, so each bundle costs one round."""
    root = Path(task_dir).expanduser().resolve()
    accept_result(root, result_path)
    bundle_id = str(_read_json(Path(result_path).expanduser().resolve())["bundle_id"])
    text = f"Accepted {bundle_id}.\n"
    if not then_next:
        return text
    _root, _task, checkpoint = _read_task(root)
    worker = worker or str(_bundle_row(checkpoint, bundle_id)[1].get("assigned_to") or "")
    if not worker:
        return text + "Name your worker to claim the next bundle.\n"
    started = str((checkpoint.get("workers") or {}).get(worker, {}).get("run_started") or "")
    reviewed = sum(
        row["status"] == "accepted" and row.get("assigned_to") == worker
        and str(row.get("accepted_at") or "") >= started
        for stage in REVIEW_STAGES for row in checkpoint[stage]["bundles"]
    )
    if started and reviewed >= RUN_BUNDLES:
        return text + (
            f"This run has reviewed {reviewed} bundles: stop now and end with your "
            "one-line report; a fresh run continues.\n"
        )
    return text + "\n" + claim(root, worker)


def _stage_finished(
    checkpoint: dict[str, Any], stages: list[str], skip_declined: bool = False
) -> bool:
    return all(
        row["status"] in FINISHED_STATUSES
        or skip_declined and row["status"] == "pending" and row.get("declined_by")
        for stage in stages for row in checkpoint[stage]["bundles"]
    )


def _next_unlocked(
    root: Path,
    worker: str,
    bundle_id: str | None,
    helper: str | None = None,
    skip_declined: bool = False,
) -> tuple[dict[str, Any] | None, bool]:
    """One assignment attempt; True when it moved QA to its next stage instead."""
    root, task, checkpoint = _load_task(root)
    helper = _register_worker(checkpoint, worker, helper)
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    stage = checkpoint["stage"]
    if stage not in REVIEW_STAGES:
        if bundle_id:
            raise ValueError(f"No bundle can be claimed in the {stage} stage")
        return None, False
    if stage == "screen" and _stage_finished(checkpoint, ["screen"]):
        # Screening ended while early deep bundles wait: deep review is the
        # stage now, as advance would make it.
        _advance_unlocked(root)
        return None, True
    # Deep bundles open while screening continues; screening comes first.
    stages = ["screen", "deep"] if stage == "screen" else [stage]
    bundles = [row for name in stages for row in checkpoint[name]["bundles"]]
    if bundle_id:
        claimed_stage, pending = _bundle_row(checkpoint, bundle_id)
        if claimed_stage not in stages:
            raise ValueError(f"{bundle_id} belongs to the {claimed_stage} stage")
        if pending["status"] == "assigned" and pending.get("assigned_to") == worker:
            return copy.deepcopy(pending), False
        if pending["status"] != "pending":
            raise ValueError(f"{bundle_id} is {pending['status']}, not waiting")
        if helper in (pending.get("declined_helpers") or []):
            raise ValueError(
                f"{worker} runs on the {helper} helper, which declined {bundle_id}; "
                "only a worker on another helper can claim it"
            )
        if worker in (pending.get("authors") or []):
            raise ValueError(
                f"{worker} wrote corrections in {bundle_id}; an independent "
                "reviewer must confirm them"
            )
        if worker in (pending.get("independent_of") or []):
            raise ValueError(
                f"{worker} screened the lines {bundle_id} checks; an independent "
                "reviewer must check them"
            )
    else:
        for row in bundles:
            if row["status"] == "assigned" and row.get("assigned_to") == worker:
                return copy.deepcopy(row), False
        eligible = [
            (name, row) for name in stages for row in checkpoint[name]["bundles"]
            if helper not in (row.get("declined_helpers") or [])
            and worker not in (row.get("authors") or [])
            and worker not in (row.get("independent_of") or [])
        ]
        pending = next(
            (row for _name, row in eligible if row["status"] == "pending"), None
        )
        stalled = next(
            (row for name, row in eligible if _stalled(checkpoint, name, row)),
            None,
        )
        if pending is None and stalled is not None:
            # Its worker stopped answering; the first result accepted counts.
            pending = stalled
            pending["reassigned_from"] = pending.get("assigned_to") or ""
        if pending is None:
            if not _stage_finished(checkpoint, [stage], skip_declined):
                return None, False
            # Every bundle of the stage is reviewed: move QA on, as advance
            # and finalize would.
            if stage == "screen":
                _advance_unlocked(root, skip_declined)
            else:
                _finalize_unlocked(root, skip_declined)
            after = _read_json(root / "checkpoint.json")
            # QA moved to another stage, or opened more bundles of this one.
            return None, after["stage"] != stage or (
                after["stage"] in REVIEW_STAGES
                and not _stage_finished(after, [after["stage"]])
            )
    pending["status"] = "assigned"
    pending["assigned_to"] = worker
    pending["assigned_at"] = _utc_now()
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return copy.deepcopy(pending), False


def decline_items(
    task_dir: str | Path,
    worker: str,
    bundle_id: str,
    declined: list[dict[str, str]],
    *,
    helper: str | None = None,
) -> dict[str, Any]:
    """Decline items of a bundle that no other worker holds, without
    reviewing the rest, as a coordinator does for items it read.

    The declined items move to a bundle of their own, as a result's declines
    do, and the rest to a new bundle in the same place and with the same
    holder, so the next reviewer never sees what was declined.
    """
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "").strip()
    if not worker:
        raise ValueError("Name the worker that declines")
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        helper = _register_worker(checkpoint, worker, helper)
        stage, row = _bundle_row(checkpoint, bundle_id)
        holder = str(row.get("assigned_to") or "")
        if row["status"] == "assigned" and holder != worker:
            raise ValueError(
                f"{holder} holds {bundle_id} and declines items in its result"
            )
        if row["status"] not in {"pending", "assigned"}:
            raise ValueError(
                f"{bundle_id} is {row['status']}; only a waiting bundle's items "
                "can be declined"
            )
        if row.get("check_of"):
            raise ValueError(
                f"{bundle_id} checks lines screened already; its reviewer declines "
                "items in its result"
            )
        if helper in (row.get("declined_helpers") or []):
            raise ValueError(f"A worker on the {helper} helper declined {bundle_id}")
        bundle = _read_json(Path(row["path"]))
        reasons = _declined_items(bundle, {"declined": declined})
        if not reasons:
            raise ValueError("Name each item to decline with a one-line reason")
        split, remaining = _split_declined(
            root, checkpoint, stage, row, bundle, reasons, worker
        )
        remainder = None
        if remaining:
            origin = row.get("origin") or row["id"]
            rest = _make_bundle(
                stage,
                f"{origin}-r{_next_number(checkpoint, stage, origin)}",
                remaining,
                _shared_context(bundle, remaining),
            )
            remainder = _add_row(root, checkpoint, stage, rest, {
                **{
                    key: row[key]
                    for key in (
                        "status", "assigned_to", "assigned_at", "follow_up",
                        "declined_by", "declined_helpers", "declines", "round",
                    )
                    if key in row
                },
                "origin": origin,
            }, after=row)
        row["status"] = "split"
        row["remainder"] = remainder["id"] if remainder else ""
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return {
            "declined": copy.deepcopy(split),
            "remainder": copy.deepcopy(remainder),
        }


def _split_notice(row: dict[str, Any]) -> str:
    return f"{row['id']} was split when a worker declined some of its items; " + (
        f"review {row['remainder']} instead" if row.get("remainder")
        else "every item was declined"
    )


def release_bundle(task_dir: str | Path, bundle_id: str) -> dict[str, Any]:
    """Return one unfinished assignment to the queue without changing coverage."""
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        _stage, row = _bundle_row(checkpoint, bundle_id)
        if row["status"] == "accepted":
            raise ValueError("An accepted QA bundle cannot be released")
        if row["status"] != "assigned":
            raise ValueError("Only an assigned QA bundle can be released")
        row["status"] = "pending"
        row["assigned_to"] = ""
        row.pop("assigned_at", None)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def _bundle_row(checkpoint: dict, bundle_id: str) -> tuple[str, dict]:
    for stage in REVIEW_STAGES:
        for row in checkpoint.get(stage, {}).get("bundles", []):
            if row["id"] == bundle_id:
                return stage, row
    raise QAResultError(f"Unknown bundle id {bundle_id!r}")


def _load_screen_index(root: Path, task: dict[str, Any]) -> dict[str, dict[str, str]]:
    document = _read_json(root / "screen-index.json")
    checksum_value = dict(document)
    claimed = checksum_value.pop("content_sha256", "")
    if (
        document.get("schema") != "rpgmaker-qa-screen-index-v1"
        or claimed != _sha256(_canonical_bytes(checksum_value))
        or claimed != task.get("screen_index_sha256")
    ):
        raise QAResultError("Screen target index checksum is invalid")
    targets = document.get("targets")
    if not isinstance(targets, dict):
        raise QAResultError("Screen target index is invalid")
    return targets


def _screen_target_map(
    bundle: dict[str, Any], screen_index: dict[str, dict[str, str]] | None = None
) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for item in bundle["items"]:
        if item.get("kind") == "scene":
            candidates = [
                {**line, "id": line.get("id") or line["context_id"]}
                for line in item["lines"]
                if "id" in line or "context_id" in line
            ]
        elif item.get("kind") == "cluster":
            candidates = [{**item, "cluster_id": item["id"]}]
        else:
            continue
        for target in candidates:
            identity = target["id"]
            if identity in targets:
                raise QAResultError(f"Duplicate screen target {identity!r}")
            targets[identity] = {
                **target,
                **_target_entry(screen_index or {}, bundle, identity),
            }
    return targets


def _screen_motif_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item for item in bundle["items"]
        if item.get("kind") == "motif-family"
    }


def _declined_items(bundle: dict, result: dict) -> dict[str, str]:
    """The bundle items a reviewer declined, with the one-line reason for each.

    A family's single proposal, candidate or variant may be declined by its
    own ID, and the rest of the family is reviewed as usual.
    """
    declined = result.get("declined", [])
    if not isinstance(declined, list):
        raise QAResultError("Declined items must be a list")
    items = {item["id"] for item in bundle["items"]}
    families = {
        unit["id"]: item["id"] for item in bundle["items"] for unit in _units(item)
    }
    reasons: dict[str, str] = {}
    for entry in declined:
        identity = str((entry or {}).get("id") or "") if isinstance(entry, dict) else ""
        reason = str(entry.get("reason") or "").strip() if isinstance(entry, dict) else ""
        if identity not in items and identity not in families or identity in reasons:
            raise QAResultError(f"Invalid or duplicate declined item {identity!r}")
        if not reason or "\n" in reason or len(reason) > DECLINE_REASON_LIMIT:
            raise QAResultError(
                f"A declined item needs a one-line reason of at most "
                f"{DECLINE_REASON_LIMIT} characters: {identity}"
            )
        reasons[identity] = reason
    for identity in reasons:
        if families.get(identity) in reasons:
            raise QAResultError(
                f"Decline {families[identity]} or some of its units, not both"
            )
    return reasons


def _require_reviews(
    result: str, kind: str, reviewed: list[str], expected: Iterable[str]
) -> None:
    """Every assigned family reviewed once, naming the ones that are not; a
    family whose every unit was declined is declined, not reviewed."""
    expected = set(expected)
    problems = [
        f"{label} {', '.join(sorted(ids))}"
        for label, ids in (
            ("missing", expected - set(reviewed)),
            ("not assigned or declined", set(reviewed) - expected),
            ("repeated", {identity for identity in reviewed if reviewed.count(identity) > 1}),
        )
        if ids
    ]
    if problems:
        raise QAResultError(
            f"{result} must review every assigned {kind} exactly once: "
            + "; ".join(problems)
        )


def _item_targets(item: dict[str, Any]) -> set[str]:
    """The screen target and context IDs one bundle item holds."""
    if item.get("kind") == "scene":
        return {
            line.get("id") or line["context_id"]
            for line in item["lines"]
            if "id" in line or "context_id" in line
        }
    return {item["id"]}


def _encode_pointer(parts: Iterable[str]) -> str:
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)


def _line_names(manifest: dict[str, Any]) -> dict[str, set[str]]:
    """Every shorter name an observation may give a line: its identity without
    the checksum, its event command or database entry, and where its English
    lives, such as `Map007.json#/events/14/pages/2/list/217` or
    `States.json#/42/message1`."""
    names: dict[str, set[str]] = defaultdict(set)
    for record in manifest["records"]:
        identity, prefix = record["identity"], record["file"] + "#"
        names[prefix + record["source_pointer"]].add(identity)
        parts = _decode_pointer(record["source_pointer"])
        if "_original" in parts:
            names[prefix + _encode_pointer(parts[: parts.index("_original")])].add(identity)
        for pointer in record["live_pointers"]:
            names[prefix + pointer].add(identity)
    return names


def _resolve_line(
    records: dict[str, dict[str, Any]], names: dict[str, set[str]], text: Any
) -> str:
    """The inventory identity an observation names."""
    text = str(text or "").strip()
    if text in records:
        return text
    found = sorted(names.get(text.split("@", 1)[0], ()))
    if len(found) == 1:
        return found[0]
    if found:
        raise QAResultError(
            f"{text} holds {len(found)} lines; name one of: "
            + ", ".join(identity.split("@", 1)[0] for identity in found[:6])
        )
    raise QAResultError(f"{text!r} names no line of this task's inventory")


def _own_lines(
    stage: str,
    bundle: dict[str, Any],
    screen_index: dict[str, dict[str, str]],
    clusters: dict[str, dict[str, Any]],
) -> set[str]:
    """The lines a bundle gives its reviewer to judge in place, which an
    observation cannot name."""
    own: set[str] = set()
    for item in bundle["items"]:
        if stage == "screen" and item.get("kind") == "scene":
            own |= {
                _target_entry(screen_index, bundle, line["id"])["representative_identity"]
                for line in item["lines"] if "id" in line
            }
        elif stage == "screen" and item.get("kind") == "cluster":
            own |= set(clusters[item["id"]]["identities"])
        elif stage == "deep":
            own |= set(item.get("identities") or [])
        elif stage == "sweep":
            own |= {
                identity for candidate in item["candidates"]
                for identity in candidate["identities"]
            }
        elif stage == "editorial":
            own |= {target["identity"] for target in item.get("targets") or []}
    return own


def _read_observations(
    entries: Any,
    manifest: dict[str, Any],
    own: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Validate observations: each names one inventory line outside the
    reviewer's own items, with categories and a short concrete reason."""
    if not isinstance(entries, list):
        raise QAResultError("Observations must be a list")
    records, _clusters = _record_maps(manifest)
    names = _line_names(manifest)
    cluster_ids = _cluster_by_identity(manifest)
    observations = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise QAResultError("An observation must be an object")
        identity = _resolve_line(records, names, entry.get("identity"))
        if identity in own:
            raise QAResultError(
                f"{identity} is one of this bundle's own lines; judge it in this "
                "result instead of observing it"
            )
        if any(observation["identity"] == identity for observation in observations):
            raise QAResultError(f"Duplicate observation of {identity}")
        categories = entry.get("categories")
        if not isinstance(categories, list) or not categories or not all(
            isinstance(value, str) and value.strip() for value in categories
        ):
            raise QAResultError(f"An observation needs its categories: {identity}")
        note = str(entry.get("note") or "").strip()
        if not note or "\n" in note or len(note) > OBSERVATION_NOTE_LIMIT:
            raise QAResultError(
                f"An observation needs a one-line reason of at most "
                f"{OBSERVATION_NOTE_LIMIT} characters: {identity}"
            )
        observations.append({
            "identity": identity,
            "cluster_id": cluster_ids[identity],
            "categories": [value.strip() for value in categories],
            "note": note,
        })
    return observations


def _validate_screen_result(bundle: dict, result: dict) -> None:
    if result.get("schema") != SCREEN_RESULT_SCHEMA:
        raise QAResultError("Screen result has the wrong schema")
    if result.get("reviewed_all") is not True:
        raise QAResultError("Screen result must confirm reviewed_all=true")
    # Declined items and units are left out of what the result must review.
    remaining = {"items": _partition(bundle, _declined_items(bundle, result))[1]}
    allowed = set(_screen_target_map(remaining))
    seen: set[str] = set()
    exceptions = result.get("exceptions")
    if not isinstance(exceptions, list):
        raise QAResultError("Screen result exceptions must be a list")
    for item in exceptions:
        if not isinstance(item, dict):
            raise QAResultError("Screen exception must be an object")
        identity = str(item.get("id") or "")
        if identity not in allowed or identity in seen:
            raise QAResultError(f"Invalid or duplicate screen identity {identity!r}")
        seen.add(identity)
        if item.get("verdict") not in SCREEN_VERDICTS:
            raise QAResultError(f"Invalid screen verdict for {identity}")
        categories = item.get("categories")
        if not isinstance(categories, list) or not all(
            isinstance(value, str) and value.strip() for value in categories
        ):
            raise QAResultError(f"Screen categories are invalid for {identity}")
        if not str(item.get("note") or "").strip():
            raise QAResultError(f"Screen exception has no reason for {identity}")

    expected_motifs = _screen_motif_map(remaining)
    motif_reviews = result.get("motif_reviews")
    if not isinstance(motif_reviews, list):
        raise QAResultError("Screen result motif_reviews must be a list")
    actual_motifs = [
        str(item.get("id") or "") for item in motif_reviews
        if isinstance(item, dict)
    ]
    _require_reviews("Screen result", "motif", actual_motifs, expected_motifs)
    for review in motif_reviews:
        motif_id = review["id"]
        disposition = review.get("disposition")
        if disposition not in MOTIF_DISPOSITIONS:
            raise QAResultError(f"Invalid motif disposition for {motif_id}")
        if not str(review.get("note") or "").strip():
            raise QAResultError(f"Motif review has no evidence for {motif_id}")
        suspect_ids = review.get("suspect_ids")
        if not isinstance(suspect_ids, list):
            raise QAResultError(f"Motif suspect_ids are invalid for {motif_id}")
        allowed_variants = {
            variant["id"] for variant in expected_motifs[motif_id]["variants"]
        }
        if len(suspect_ids) != len(set(suspect_ids)) or not set(
            suspect_ids
        ).issubset(allowed_variants):
            raise QAResultError(f"Motif suspect_ids are invalid for {motif_id}")
        if disposition == "preserved" and suspect_ids:
            raise QAResultError(f"Preserved motif cannot name suspects for {motif_id}")
        if disposition != "preserved" and not suspect_ids:
            raise QAResultError(f"Non-clean motif must name suspects for {motif_id}")

    expected_lint = {
        item["id"]: item for item in remaining["items"]
        if item.get("kind") == "lint-family"
    }
    lint_reviews = result.get("lint_reviews", [])
    if not isinstance(lint_reviews, list) or not all(
        isinstance(review, dict) for review in lint_reviews
    ):
        raise QAResultError("Screen result lint_reviews must be a list of objects")
    _require_reviews(
        "Screen result",
        "lint family",
        [str(review.get("id") or "") for review in lint_reviews],
        expected_lint,
    )
    for review in lint_reviews:
        rejected = review.get("rejected")
        allowed = {row["id"] for row in expected_lint[review["id"]]["proposals"]}
        if (
            not isinstance(rejected, list)
            or len(rejected) != len(set(rejected))
            or not set(rejected) <= allowed
        ):
            raise QAResultError(f"Lint rejections are invalid for {review['id']}")
        if rejected and not str(review.get("note") or "").strip():
            raise QAResultError(
                f"A lint review that rejects proposals needs a note: {review['id']}"
            )


def _validate_show_text_fix(review: dict[str, Any], item: dict[str, Any]) -> None:
    """A Show Text fix names one occurrence and the header it should have."""
    identity = review["id"]
    fix = review["source_fix"]
    if set(fix) != {"kind", "face_name", "face_index", "name"}:
        raise QAResultError(
            f"A Show Text fix is {{kind, face_name, face_index, name}}: {identity}"
        )
    if (
        not isinstance(fix["face_name"], str)
        or not isinstance(fix["name"], str)
        or type(fix["face_index"]) is not int
        or not 0 <= fix["face_index"] <= 7
        or any(len(fix[key]) > 100 or "\n" in fix[key] for key in ("face_name", "name"))
    ):
        raise QAResultError(f"The Show Text fix's face or name is invalid: {identity}")
    if review.get("correction") is not None:
        raise QAResultError(
            f"A Show Text fix keeps the line's text; leave correction null: {identity}"
        )
    if _normalize_category(review.get("category")) != "speaker":
        raise QAResultError(f"A Show Text fix uses the speaker category: {identity}")
    targets = review.get("apply_identities") or []
    locators = {locator["identity"]: locator for locator in item.get("locators") or []}
    if len(targets) != 1 or locators.get(targets[0], {}).get("event_code") not in {101, 401}:
        raise QAResultError(
            f"A Show Text fix names exactly one message occurrence in "
            f"apply_identities: {identity}"
        )


def _number_values(value: Any) -> set[str]:
    """Every number a database entry holds, as the visible-number check writes them."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {str(int(value)) if float(value).is_integer() else str(value)}
    if isinstance(value, list):
        return set().union(*(_number_values(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(
            _number_values(item) for key, item in value.items()
            if key not in {"id", "_original"}
        )) if value else set()
    return set()


def _database_number_allowance(
    review: dict[str, Any], item: dict[str, Any]
) -> frozenset[str]:
    """A database text may change a number only to one its own entry holds."""
    identity = review["id"]
    targets = set(review.get("apply_identities") or [])
    if not targets:
        raise QAResultError(
            f"A database number fix names the entries it changes in apply_identities: "
            f"{identity}"
        )
    for locator in item.get("locators") or []:
        if locator["identity"] not in targets:
            continue
        values = locator.get("database_values")
        if values is None:
            raise QAResultError(
                f"A database number fix needs a database field: {identity}"
            )
        evidence = _mechanical_evidence(
            str(item["source"]), str(review["correction"]), locator.get("event_code")
        )
        added = Counter(evidence["live_visible_numbers"]) - Counter(
            evidence["source_visible_numbers"]
        )
        if not added or any(
            number.lstrip("+") not in values for number in added
        ):
            raise QAResultError(
                f"A database number fix must change a number to one its entry "
                f"holds ({', '.join(sorted(values)[:12])}): {identity}"
            )
    return frozenset({"visible-number-mismatch"})


def _battler_name_allowance(
    review: dict[str, Any], item: dict[str, Any]
) -> frozenset[str]:
    """An MZ battle message the battler-name check found may gain the one %1
    its source lacks, where RPG Maker writes the battler's name."""
    identity = review["id"]
    if not any(
        entry.get("source_fix") == "battler-name" for entry in item.get("checks") or []
    ):
        raise QAResultError(
            f"A battler-name fix is for an MZ battle message whose battler-name "
            f"check offers it: {identity}"
        )
    for target in review.get("apply_identities") or item["identities"]:
        file, pointer = target.split("#", 1)
        field = pointer.rsplit("@", 1)[0].rsplit("/", 1)[-1]
        if field not in checks.BATTLE_MESSAGES["MZ"].get(file, ()):
            raise QAResultError(
                f"A battler-name fix changes only battle messages; name them in "
                f"apply_identities: {identity}"
            )
    if not _adds_only_battler_name(str(item["source"]), str(review["correction"])):
        raise QAResultError(
            f"A battler-name fix adds the one %1 its source lacks and changes no "
            f"other code: {identity}"
        )
    return frozenset({ADDED_BATTLER_NAME})


def _validate_sweep_rule(review: dict[str, Any], item: dict[str, Any]) -> None:
    """A sweep rule must reproduce its review's correction exactly."""
    identity = review["id"]
    rule = review["sweep"]
    if (
        not isinstance(rule, dict)
        or not {"find", "replace"} <= set(rule)
        or set(rule) - {"find", "replace", "source_has"}
        or not all(isinstance(value, str) for value in rule.values())
    ):
        raise QAResultError(
            f"A sweep rule is {{find, replace, optional source_has}}: {identity}"
        )
    find, replace = rule["find"], rule["replace"]
    source_has = rule.get("source_has", "")
    if not 0 < len(find) <= 200 or len(replace) > 200 or find == replace:
        raise QAResultError(f"A sweep rule needs a short, real change: {identity}")
    if len(source_has) > 100 or source_has not in str(item["source"]):
        raise QAResultError(
            f"A sweep rule's source_has must appear in the source: {identity}"
        )
    if not str(review.get("family_key") or "").strip():
        raise QAResultError(f"A sweep rule needs the family_key it fixes: {identity}")
    if str(item["translation"]).replace(find, replace) != review["correction"]:
        raise QAResultError(
            f"Applying the sweep rule to the current text must give the "
            f"correction exactly: {identity}"
        )


def _validate_sweep_result(bundle: dict, result: dict) -> None:
    if result.get("schema") != SWEEP_RESULT_SCHEMA:
        raise QAResultError("Sweep result has the wrong schema")
    expected = {
        item["id"]: item
        for item in _partition(bundle, _declined_items(bundle, result))[1]
    }
    reviews = result.get("reviews")
    if not isinstance(reviews, list) or not all(
        isinstance(review, dict) for review in reviews
    ):
        raise QAResultError("Sweep result reviews must be a list of objects")
    _require_reviews(
        "Sweep result", "family", [str(review.get("id") or "") for review in reviews],
        expected,
    )
    for review in reviews:
        rejected = review.get("rejected")
        allowed = {row["id"] for row in expected[review["id"]]["candidates"]}
        if (
            not isinstance(rejected, list)
            or len(rejected) != len(set(rejected))
            or not set(rejected) <= allowed
        ):
            raise QAResultError(f"Sweep rejections are invalid for {review['id']}")
        if rejected and not str(review.get("note") or "").strip():
            raise QAResultError(
                f"A sweep review that rejects candidates needs a note: {review['id']}"
            )


def _scene_check(
    root: Path, checkpoint: dict[str, Any], bundle: dict, result: dict
) -> dict[str, Any]:
    """What a scene correction is checked against: each scene's records and
    each line's cluster, and what reviewers declined, this result's declines
    included."""
    manifest = _read_json(root / "inventory.json")
    _records, clusters = _record_maps(manifest)
    declined = _declined_scope(root, checkpoint, manifest, waiting=True)
    identities = set(declined["identities"])
    scenes = set(declined["context_scenes"])
    items = {item["id"]: item for item in bundle["items"]}
    for review in result["reviews"]:
        if (
            not isinstance(review, dict)
            or review.get("disposition") != "declined"
            or review.get("id") not in items
        ):
            continue
        identities |= set(clusters[review["id"]]["identities"])
        scenes |= {
            bundle["scenes"][key]["scene_id"]
            for key in items[review["id"]].get("scenes") or []
        }
    return {
        "scenes": _scene_records(manifest),
        "clusters": _cluster_by_identity(manifest),
        "declined_identities": identities,
        "declined_scenes": scenes,
        "layout": _read_json(root / "task.json")["layout"],
    }


def _scene_line(
    records: list[dict[str, Any]], command: Any, current: Any
) -> dict[str, Any] | None:
    """The one line of a scene that the event command holds with this current
    text; a command can hold several lines, such as a choice's options."""
    found = [
        record for record in records
        if (_scene_position(record) or ("", None))[1] == command
        and record["live"] == current
    ]
    return found[0] if len(found) == 1 else None


def _validate_scene_correction(
    review: dict[str, Any], item: dict[str, Any], bundle: dict,
    check: dict[str, Any] | None,
) -> None:
    """A scene correction changes two or more lines of one of the item's
    scenes, each named by its event command and exact current text, the
    item's own line among them, each passing apply's checks."""
    identity = review["id"]
    scene = review["scene_correction"]
    if (
        not isinstance(scene, dict)
        or set(scene) != {"scene", "lines"}
        or not isinstance(scene["lines"], list)
    ):
        raise QAResultError(f"A scene correction is {{scene, lines}}: {identity}")
    if any(
        review.get(key)
        for key in ("correction", "apply_identities", "sweep", "source_fix")
    ):
        raise QAResultError(
            f"A scene correction replaces correction, apply_identities, sweep and "
            f"source_fix; leave them empty: {identity}"
        )
    key = scene["scene"]
    if not isinstance(key, str) or key not in (item.get("scenes") or []):
        raise QAResultError(
            f"A scene correction names one of the item's scenes, not {key!r}: {identity}"
        )
    if check is None:
        raise QAResultError(f"A scene correction needs the task to check it: {identity}")
    shown = bundle["scenes"][key]
    if shown["scene_id"] in check["declined_scenes"]:
        raise QAResultError(
            f"A reviewer declined part of scene {key}, so no scene correction may "
            f"change it: {identity}"
        )
    if len(scene["lines"]) < 2:
        raise QAResultError(
            f"A scene correction changes two or more lines; correct one line with "
            f"correction: {identity}"
        )
    records = check["scenes"].get(shown["scene_id"]) or []
    targets: set[str] = set()
    own = False
    for entry in scene["lines"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"command", "current", "correction"}
            or type(entry["command"]) is not int
        ):
            raise QAResultError(
                f"A scene correction's line is {{command, current, correction}}: "
                f"{identity}"
            )
        command, current = entry["command"], entry["current"]
        shows = any(
            line.get("command") == command and line["translation"] == current
            for line in shown["lines"]
        )
        record = _scene_line(records, command, current) if shows else None
        if record is None:
            raise QAResultError(
                f"Scene {key} shows no single line #{command} with the current text "
                f"given; check the command number and text: {identity}"
            )
        if record["identity"] in targets:
            raise QAResultError(
                f"A scene correction names line #{command} twice: {identity}"
            )
        targets.add(record["identity"])
        correction = entry["correction"]
        if not isinstance(correction, str) or not correction.strip():
            raise QAResultError(
                f"Line #{command} of the scene correction has no correction: {identity}"
            )
        if record["identity"] in check["declined_identities"]:
            raise QAResultError(
                f"A reviewer declined line #{command} of scene {key}, so no "
                f"correction may change it: {identity}"
            )
        problems = _record_problems(record, correction, check["layout"])
        if problems:
            raise QAResultError(
                f"Line #{command} of the scene correction for {identity} would block "
                "apply: " + "; ".join(problems)
            )
        own = own or check["clusters"][record["identity"]] == identity
    if not own:
        raise QAResultError(
            f"A scene correction changes the item's own line in scene {key}: {identity}"
        )


def _validate_correction(
    review: dict[str, Any], item: dict[str, Any], kind: str | None
) -> None:
    """An item's correction passes apply's checks at every occurrence it
    reaches."""
    identity = review["id"]
    correction = review.get("correction")
    if not isinstance(correction, str) or not correction.strip():
        raise QAResultError(f"Actionable review has no correction for {identity}")
    if kind == "database-numbers":
        allowed = _database_number_allowance(review, item)
    elif kind == "battler-name":
        allowed = _battler_name_allowance(review, item)
    else:
        allowed = frozenset()
    # Every occurrence the correction reaches, by its line structure; a
    # capped item lists only some of them.
    chosen = set(review.get("apply_identities") or [])
    shapes = [
        _target_shape(locator)
        for locator in item.get("locators") or []
        if locator["identity"] in chosen
    ] if chosen else item.get("target_shapes") or []
    for shape in shapes:
        problems = _shape_problems(item, correction, shape, allowed)
        if problems:
            raise QAResultError(
                f"The correction for {identity} would block apply: "
                + "; ".join(problems)
            )


def _validate_deep_result(
    bundle: dict, result: dict, scene_check: dict[str, Any] | None = None
) -> None:
    if result.get("schema") != DEEP_RESULT_SCHEMA:
        raise QAResultError("Deep result has the wrong schema")
    expected = {item["id"] for item in bundle["items"]}
    reviews = result.get("reviews")
    if not isinstance(reviews, list):
        raise QAResultError("Deep result reviews must be a list")
    actual = [str(item.get("id") or "") for item in reviews if isinstance(item, dict)]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise QAResultError("Deep result must contain every assigned identity exactly once")
    bundle_items = {item["id"]: item for item in bundle["items"]}
    for review in reviews:
        identity = review["id"]
        disposition = review.get("disposition")
        if disposition not in DEEP_DISPOSITIONS:
            raise QAResultError(f"Invalid deep disposition for {identity}")
        if disposition == "declined":
            reason = str(review.get("reason") or "").strip()
            if not reason or "\n" in reason or len(reason) > DECLINE_REASON_LIMIT:
                raise QAResultError(
                    f"A declined item needs a one-line reason of at most "
                    f"{DECLINE_REASON_LIMIT} characters: {identity}"
                )
            if any(
                review.get(key) for key in (
                    "severity", "category", "family_key", "motif_ids",
                    "evidence", "correction", "apply_identities",
                    "editorial_basis", "scene_correction",
                )
            ):
                raise QAResultError(
                    f"A declined item carries only its reason: {identity}"
                )
            continue
        if disposition == "actionable":
            if review.get("severity") not in SEVERITIES:
                raise QAResultError(f"Actionable review has invalid severity for {identity}")
            if _normalize_category(review.get("category")) not in FINDING_CATEGORIES:
                raise QAResultError(f"Actionable review has invalid category for {identity}")
            if not str(review.get("evidence") or "").strip():
                raise QAResultError(f"Actionable review has no evidence for {identity}")
            _validate_editorial_basis(review, identity)
            item = bundle_items[identity]
            source_fix = review.get("source_fix")
            kind = source_fix.get("kind") if isinstance(source_fix, dict) else None
            if source_fix is not None and kind not in SOURCE_FIX_KINDS:
                raise QAResultError(f"Unknown source fix for {identity}")
            if review.get("scene_correction") is not None:
                _validate_scene_correction(review, item, bundle, scene_check)
            elif kind == "show-text":
                _validate_show_text_fix(review, item)
                continue
            else:
                _validate_correction(review, item, kind)
        elif review.get("scene_correction") is not None:
            raise QAResultError(f"Only an actionable review can correct a scene: {identity}")
        elif review.get("source_fix") is not None:
            raise QAResultError(f"Only an actionable review can fix the source: {identity}")
        elif review.get("severity") not in {None, ""}:
            raise QAResultError(f"Non-actionable review cannot have severity for {identity}")
        elif review.get("editorial_basis") is not None:
            raise QAResultError(
                f"Non-actionable review cannot have editorial_basis for {identity}"
            )
        if review.get("sweep") is not None:
            if disposition != "actionable":
                raise QAResultError(
                    f"Only an actionable review can carry a sweep rule: {identity}"
                )
            _validate_sweep_rule(review, bundle_items[identity])
        if (
            disposition == "clean"
            and bundle_items[identity].get("screen_evidence")
            and not str(review.get("evidence") or "").strip()
        ):
            raise QAResultError(
                f"Clean review must rebut preserved screen evidence for {identity}"
            )
        if disposition == "uncertain-playtest" and not str(
            review.get("evidence") or ""
        ).strip():
            raise QAResultError(f"Uncertain review has no playtest reason for {identity}")
        if disposition == "uncertain-playtest" and review.get("correction") is not None:
            # A proposal the user may choose instead of the current text.
            proposal = review["correction"]
            item = bundle_items[identity]
            if not isinstance(proposal, str) or not proposal.strip():
                raise QAResultError(f"A question's proposal must be text: {identity}")
            for shape in item.get("target_shapes") or []:
                problems = _shape_problems(item, proposal, shape)
                if problems:
                    raise QAResultError(
                        f"The proposal for {identity} would block apply: "
                        + "; ".join(problems)
                    )
        elif disposition == "clean" and review.get("correction") is not None:
            raise QAResultError(f"A clean review has no correction: {identity}")
        family_key = review.get("family_key")
        if not isinstance(family_key, str):
            raise QAResultError(f"Review has invalid family_key for {identity}")
        if disposition != "actionable" and family_key.strip():
            raise QAResultError(f"Non-actionable review cannot have family_key for {identity}")
        apply_ids = review.get("apply_identities") or []
        allowed_ids = set(bundle_items[identity].get("identities") or [])
        if not isinstance(apply_ids, list) or not set(apply_ids).issubset(allowed_ids):
            raise QAResultError(f"Invalid apply_identities for {identity}")
        motif_ids = review.get("motif_ids") or []
        allowed_motif_ids = set(bundle_items[identity].get("motifs") or [])
        if (
            not isinstance(motif_ids, list)
            or len(motif_ids) != len(set(motif_ids))
            or not set(motif_ids).issubset(allowed_motif_ids)
        ):
            raise QAResultError(f"Invalid motif_ids for {identity}")
        if motif_ids and disposition == "clean":
            raise QAResultError(f"Clean review cannot attribute a motif for {identity}")
        if (
            motif_ids
            and disposition == "actionable"
            and _normalize_category(review.get("category")) != "wordplay"
        ):
            raise QAResultError(
                f"Motif-attributed actionable review must use wordplay for {identity}"
            )


def accept_result(task_dir: str | Path, result_path: str | Path) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, task, checkpoint = _load_task(root)
        result = _read_json(Path(result_path).expanduser().resolve())
        bundle_id = str(result.get("bundle_id") or "")
        stage, row = _bundle_row(checkpoint, bundle_id)
        if row["status"] == "split":
            raise QAResultError(_split_notice(row))
        bundle = _read_json(Path(row["path"]))
        if result.get("bundle_sha256") != row["sha256"]:
            raise QAResultError("Result does not match the immutable bundle checksum")
        if stage == "screen":
            _validate_screen_result(bundle, result)
        elif stage == "sweep":
            _validate_sweep_result(bundle, result)
        elif stage == "editorial":
            _validate_editorial_result(bundle, result, str(row.get("assigned_to") or ""))
        else:
            reviews = result.get("reviews")
            _validate_deep_result(
                bundle,
                result,
                _scene_check(root, checkpoint, bundle, result)
                if isinstance(reviews, list) and any(
                    isinstance(review, dict) and review.get("scene_correction") is not None
                    for review in reviews
                )
                else None,
            )
        observations = []
        if result.get("observations", []) != []:
            manifest = _read_json(root / "inventory.json")
            observations = _read_observations(
                result["observations"],
                manifest,
                _own_lines(
                    stage,
                    bundle,
                    _load_screen_index(root, task) if stage == "screen" else {},
                    _record_maps(manifest)[1],
                ),
            )
        canonical_path = root / "results" / stage / f"{bundle_id}.json"
        if row["status"] == "accepted" and canonical_path.is_file():
            if _read_json(canonical_path) != result:
                raise QAResultError("An accepted bundle result cannot be replaced")
            return status(root)
        if row["status"] == "set-aside":
            raise QAResultError(
                f"{bundle_id} was set aside after reviewers declined it"
            )
        check = bool(row.get("check_of"))
        if check and row["status"] != "assigned":
            raise QAResultError(
                f"Claim {bundle_id} with next before submitting it, so the check "
                "records its own reviewer"
            )
        _atomic_write_json(canonical_path, result)
        declined = (
            _declined_items(bundle, result)
            if stage in {"screen", "sweep", "editorial"}
            else {
                review["id"]: review["reason"]
                for review in result["reviews"]
                if review["disposition"] == "declined"
            }
        )
        # The checked lines were screened already, so a check's declines
        # leave coverage as it is.
        moved, remaining = 0, bundle["items"]
        if declined and not check:
            split, remaining = _split_declined(
                root, checkpoint, stage, row, bundle, declined
            )
            moved = split["item_count"]
        _note_observations(
            checkpoint, observations, stage, str(row.get("assigned_to") or ""), bundle_id
        )
        if stage == "screen":
            exception_ids = checkpoint["screen"].setdefault("exception_ids", [])
            candidate_reasons = checkpoint["deep"].setdefault(
                "candidate_reasons", {}
            )
            screen_targets = _screen_target_map(
                bundle, _load_screen_index(root, task)
            )
            # Whatever either screen reports goes to deep review.
            for exception in result["exceptions"]:
                review_id = exception["id"]
                target = screen_targets[review_id]
                cluster_id = target.get("cluster_id") or review_id
                if not check:
                    exception_ids.append(review_id)
                _merge_candidate(
                    candidate_reasons,
                    cluster_id,
                    [f"screen-{exception['verdict']}"],
                    [target.get("representative_identity", "")],
                )
            motifs = _screen_motif_map(bundle)
            for review in result["motif_reviews"]:
                if review["disposition"] == "preserved":
                    continue
                motif = motifs[review["id"]]
                variants = {variant["id"]: variant for variant in motif["variants"]}
                for cluster_id in review["suspect_ids"]:
                    variant = variants[cluster_id]
                    _merge_candidate(
                        candidate_reasons,
                        cluster_id,
                        [f"motif-{review['disposition']}"],
                        [variant["representative_identity"]],
                    )
            # A motif family counts once; its declined parts do not again.
            checkpoint["screen"]["motif_accepted"] = int(
                checkpoint["screen"].get("motif_accepted", 0)
            ) + sum(
                not motifs[review["id"]].get("part_of")
                for review in result["motif_reviews"]
            )
            checkpoint["screen"]["lint_accepted"] = int(
                checkpoint["screen"].get("lint_accepted", 0)
            ) + sum(
                item["target_count"] for item in remaining
                if item.get("kind") == "lint-family"
            )
            checkpoint["deep"]["projected_items"] = len(
                set(candidate_reasons)
                | {
                    observation["cluster_id"]
                    for observation in checkpoint.get("observations") or []
                }
            )
            if check:
                _record_check(checkpoint, row, bundle, result, declined)
            else:
                row["checkable"] = sum(
                    int(item.get("target_count", 1))
                    for item in _checkable(bundle, declined)
                )
        if not check:
            checkpoint[stage]["accepted_items"] += int(row["item_count"]) - moved
        row["status"] = "accepted"
        row["result_path"] = str(canonical_path)
        row["accepted_at"] = _utc_now()
        if stage == "screen":
            _issue_checks(root, checkpoint)
        worker = checkpoint.setdefault("workers", {}).setdefault(
            str(row.get("assigned_to") or ""), {"bundles": 0, "seconds": 0.0}
        )
        worker["bundles"] += 1
        if row.get("assigned_at"):
            worker["seconds"] += (
                datetime.fromisoformat(row["accepted_at"])
                - datetime.fromisoformat(row["assigned_at"])
            ).total_seconds()
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        if stage == "screen" or observations:
            _issue_new_evidence(root, checkpoint)
    return status(root)


def _note_observations(
    checkpoint: dict[str, Any],
    observations: list[dict[str, Any]],
    stage: str,
    worker: str,
    bundle_id: str = "",
) -> None:
    checkpoint.setdefault("observations", []).extend(
        {
            **observation,
            "stage": stage,
            "worker": worker,
            **({"bundle": bundle_id} if bundle_id else {}),
            "at": _utc_now(),
        }
        for observation in observations
    )


def _issue_new_evidence(root: Path, checkpoint: dict[str, Any]) -> None:
    """Open deep items for new evidence while QA still takes them: in early
    batches while screening continues and at once during deep review. Later
    stages leave it for a follow-up deep round."""
    stage = checkpoint["stage"]
    if stage in {"screen", "deep"} and _issue_deep(
        root, checkpoint, final=stage == "deep"
    ):
        _atomic_write_json(root / "checkpoint.json", checkpoint)


def record_observation(
    task_dir: str | Path,
    worker: str,
    identity: str,
    categories: Iterable[str],
    note: str,
) -> dict[str, Any]:
    """Send a line to deep review with a reviewer's reason, such as a defect
    a reviewer reported outside its own bundle."""
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        if checkpoint["stage"] == "complete":
            raise ValueError("QA is complete; run QA again to review more text")
        (observation,) = _read_observations(
            [{"identity": identity, "categories": list(categories), "note": note}],
            _read_json(root / "inventory.json"),
        )
        _note_observations(checkpoint, [observation], checkpoint["stage"], str(worker or ""))
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        _issue_new_evidence(root, checkpoint)
    return observation


def observed_names(task_dir: str | Path) -> set[str]:
    """The lines a task already observes, under every name an observation
    may give them, such as `States.json#/42/message1`."""
    root = Path(task_dir).expanduser().resolve()
    _root, _task, checkpoint = _read_task(root)
    recorded = {row["identity"] for row in checkpoint.get("observations") or []}
    if not recorded:
        return set()
    names = _line_names(_read_json(root / "inventory.json"))
    return recorded | {name for name, lines in names.items() if lines & recorded}


# Commands the context view leaves out: flow, waits, sound and picture moves.
_CONTEXT_QUIET_CODES = frozenset({
    0, 221, 222, 223, 224, 225, 230, 231, 232, 235, 241, 245, 246, 249, 250,
    404, 412,
})
_CONTEXT_TEXT_CODES = frozenset({
    101, 102, 108, 122, 320, 324, 355, 357, 401, 402, 405, 408, 655,
})


def _context_text(value: Any) -> str:
    return "∅" if value is None else str(value).replace("\n", "⏎")


def context_view(
    task_dir: str | Path, locator: str, radius: int = 12, worker: str = ""
) -> str:
    """Read-only game text around a locator, with Japanese and current English.

    The locator is an inventory identity or a command list such as
    `Map001.json#/events/1/pages/0/list`. Scenes a reviewer declined stay out,
    except for the worker whose assigned bundle prints them.
    """
    root, task, checkpoint = _load_task(task_dir)
    data_root = Path(task["data_root"]).resolve()
    filename, _, pointer = locator.split("@", 1)[0].partition("#")
    path = (data_root / filename).resolve()
    if data_root not in path.parents or not path.is_file() or path.suffix != ".json":
        raise ValueError(f"Unknown game data file: {filename}")
    parts = _decode_pointer(pointer)
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if "list" not in parts:
        node = _resolve_parts(
            document, parts[: parts.index("_original")] if "_original" in parts else parts
        )
        return json.dumps(node, ensure_ascii=False, indent=1)[:6000]
    list_index = len(parts) - 1 - parts[::-1].index("list")
    scene = f"{filename}#/" + "/".join(
        part.replace("~", "~0").replace("/", "~1") for part in parts[: list_index + 1]
    )
    declined = _declined_scope(
        root, checkpoint, _read_json(root / "inventory.json"), waiting=True
    )
    if scene in declined["context_scenes"] and scene not in _assigned_scenes(
        checkpoint, worker
    ):
        raise ValueError(
            "A reviewer declined this scene, so context shows it only to the worker "
            "whose assigned bundle prints it, with --worker <name>."
        )
    commands = _resolve_parts(document, parts[: list_index + 1])
    if list_index + 1 < len(parts):
        center = int(parts[list_index + 1])
        start = max(0, center - radius)
        end = min(len(commands), center + radius + 1)
    else:
        center, start, end = None, 0, len(commands)
    lines = [f"{scene} commands {start}-{end - 1} of {len(commands)}"]
    for index in range(start, end):
        command = commands[index]
        code = command.get("code")
        if code in _CONTEXT_QUIET_CODES:
            continue
        mark = ">>" if index == center else "  "
        parameters = command.get("parameters")
        if code in _CONTEXT_TEXT_CODES:
            shown = [
                value for value in parameters if isinstance(value, (str, list))
            ] if isinstance(parameters, list) else parameters
            lines.append(
                f"{mark}#{index} c{code}: JP="
                + _context_text(json.dumps(command.get("_original"), ensure_ascii=False))
                + " EN=" + _context_text(json.dumps(shown, ensure_ascii=False))
            )
        else:
            lines.append(
                f"{mark}#{index} c{code}: "
                + _context_text(json.dumps(parameters, ensure_ascii=False))[:200]
            )
    return "\n".join(lines)


# Event commands whose text a rendered context shows; others print as data.
_RENDERED_TEXT_CODES = frozenset({
    101, 102, 108, 122, 320, 324, 355, 357, 401, 402, 405, 408, 655,
})


def _render_commands(commands: list[dict], indent: str) -> list[str]:
    out = []
    for command in commands or []:
        code = command.get("code")
        if code in _CONTEXT_QUIET_CODES:
            continue
        parameters = command.get("parameters")
        if code in _RENDERED_TEXT_CODES:
            shown = [
                value for value in parameters if isinstance(value, (str, list))
            ] if isinstance(parameters, list) else parameters
            out.append(
                f"{indent}#{command.get('index')} c{code}: JP="
                + _context_text(json.dumps(command.get("original"), ensure_ascii=False))
                + " EN=" + _context_text(json.dumps(shown, ensure_ascii=False))
            )
        else:
            out.append(
                f"{indent}#{command.get('index')} c{code}: "
                + _context_text(json.dumps(parameters, ensure_ascii=False))[:160]
            )
    return out


def _render_hints(entry: dict, indent: str) -> list[str]:
    out = [
        indent + f"check {failed['check']}: " + _context_text(failed["note"])
        for failed in entry.get("checks") or []
    ]
    if entry.get("glossary"):
        out.append(indent + "glossary: " + "; ".join(f"{a}={b}" for a, b in entry["glossary"]))
    for alternative in entry.get("same_source_alternatives") or []:
        out.append(indent + "same JP elsewhere: " + _context_text(alternative))
    for row in entry.get("reference_translations") or []:
        out.append(indent + "reference: " + _context_text(row.get("translation")))
    if entry.get("lint"):
        out.append(
            indent + "lint (" + ", ".join(entry["lint"]["families"]) + "): "
            + _context_text(entry["lint"]["proposed"])
        )
    return out


def _command_number(identity: str) -> int | None:
    """The event command that holds an identity's line, if any."""
    filename, _, pointer = identity.split("@", 1)[0].partition("#")
    position = _scene_position({"file": filename, "source_pointer": pointer})
    return position[1] if position else None


def _render_line(line: dict, mark: str) -> list[str]:
    """One scene line, numbered by the event command that holds it, so an
    observation can name it as the scene's command list and that number."""
    number = f"#{line['command']}" if line.get("command") is not None else ""
    speaker = f"<{line['speaker']}> " if line.get("speaker") else ""
    code = f" c{line['event_code']}" if line.get("event_code") else ""
    out = [
        f"{number:>5} {mark}{code} JP: {speaker}{_context_text(line['source'])}",
        f"{'':>5}   EN: {_context_text(line['translation'])}",
    ]
    if line.get("risk"):
        out.append(f"{'':>5}   risk: " + ",".join(line["risk"]))
    if line.get("context_expansion"):
        out.append(f"{'':>5}   repeated in: " + ",".join(line["context_expansion"]))
    if line.get("choice_context"):
        labels = " | ".join(
            f"{branch['index']}:{branch['label']}"
            for branch in line["choice_context"].get("branches", [])
        )
        out.append(f"{'':>5}   choices: {labels}")
    return out + _render_hints(line, "        ")


def _render_screen_item(
    item: dict, screen_index: dict[str, dict[str, str]]
) -> list[str]:
    kind = item.get("kind")
    if kind == "scene":
        out = [
            f"### SCENE {item['id']} {item['scene_id']} "
            f"({item['line_count']} lines, {item['target_count']} targets)"
        ]
        for line in item["lines"]:
            mark = f"[T {line['id']}]" if "id" in line else "[ctx]"
            entry = screen_index[line.get("id") or line["context_id"]]
            out += _render_line(
                {**line, "command": _command_number(entry["representative_identity"])},
                mark,
            )
        return out
    if kind == "cluster":
        meta = [f"occ={item.get('occurrences', 1)}"]
        if item.get("display_shapes"):
            meta.append("shape=" + ",".join(item["display_shapes"]))
        if item.get("speakers"):
            meta.append("speakers=" + ",".join(item["speakers"]))
        out = [f"### CLUSTER {item['id']} " + " ".join(meta)]
        if item.get("risk"):
            out.append("  risk: " + ",".join(item["risk"]))
        out += [
            "  JP: " + _context_text(item["source"]),
            "  EN: " + _context_text(item["translation"]),
        ]
        return out + _render_hints(item, "  ")
    if kind == "motif-family":
        out = [
            f"### MOTIF {item['id']} ({item['variant_count']} variants)",
            "  anchors: " + ", ".join(item["anchors"]),
            "  guidance: " + _context_text(item["guidance"]),
        ]
        for variant in item["variants"]:
            out += [
                f"  - VARIANT {variant['id']} occ={variant['occurrences']}",
                "    JP: " + _context_text(variant["source"]),
                "    EN: " + _context_text(variant["translation"]),
            ] + _render_commands(variant.get("nearby_commands"), "      ")
        if item.get("reviewed_variants"):
            out.append("  reviewed in this family before, for comparison:")
            out += [
                "  - " + _context_text(variant["source"])
                + " || " + _context_text(variant["translation"])
                for variant in item["reviewed_variants"]
            ]
        return out
    if kind == "lint-family":
        out = [f"### LINT {item['id']} {item['family']}: {item['description']}"]
        for proposal in item["proposals"]:
            speaker = f" <{proposal['speaker']}>" if proposal.get("speaker") else ""
            # The line, which an observation may name, in its scene.
            line = proposal["cluster_id"].split("@", 1)[0]
            out += [
                f"  {proposal['id']} {line}{speaker}",
                "    JP:  " + _context_text(proposal["source"]),
                "    EN:  " + _context_text(proposal["current"]),
                "    FIX: " + _context_text(proposal["proposed"]),
            ] + (["    WHY: " + proposal["note"]] if proposal.get("note") else [])
        return out
    return ["### " + json.dumps(item, ensure_ascii=False)]


def _render_boxes(places: list[dict] | None) -> list[str]:
    """The boxes an item's text shows in, such as 50 chars x 4 rows."""
    shown = []
    for place in places or []:
        box = place.get("box") or {}
        size = " x ".join(
            f"{box[key]} {unit}"
            for key, unit in (("width", "chars"), ("rows", "rows"))
            if box.get(key)
        )
        text = size + (", rewrapped" if box.get("wraps") else "")
        if size and text not in shown:
            shown.append(text)
    return ["  box: " + " | ".join(shown)] if shown else []


def _render_deep(bundle: dict) -> list[str]:
    out = []
    numbers = {item["id"]: number for number, item in enumerate(bundle["items"], 1)}
    for number, item in enumerate(bundle["items"], 1):
        out += [
            "",
            f"### ITEM {number} {item['id']}",
            "  deep_reasons: " + ", ".join(item.get("deep_reasons") or []),
        ]
        meta = []
        for key, label in (("risk", "risk"), ("display_shapes", "shape"),
                           ("event_codes", "codes"), ("speakers", "speakers")):
            if item.get(key):
                meta.append(f"{label}=" + ",".join(map(str, item[key])))
        listed = len(item.get("locators") or [])
        meta.append(
            f"occurrences={item.get('occurrences', listed)}"
            + (f" (listing {listed})" if item.get("occurrences", listed) != listed else "")
        )
        out.append("  " + " ".join(meta))
        out += [
            "  JP: " + _context_text(item["source"]),
            "  EN: " + _context_text(item["translation"]),
        ] + _render_boxes(item.get("target_shapes")) + _render_hints(item, "  ")
        for evidence in item.get("screen_evidence") or []:
            source = (
                "observed at " + evidence["identity"].split("@", 1)[0]
                if evidence["verdict"] == "observation"
                else f"screen [{evidence['verdict']}]"
            )
            out.append(
                f"  {source} ({','.join(evidence['categories'])}): "
                + _context_text(evidence["note"])
            )
        prior = item.get("prior_review")
        if prior:
            out.append(
                f"  earlier deep review [{prior['disposition']}]: "
                + _context_text(prior.get("evidence"))
                + (f" -> {_context_text(prior['correction'])}" if prior.get("correction") else "")
            )
        if item.get("scenes"):
            out.append("  scenes: " + ", ".join(item["scenes"]))
        if item.get("motifs"):
            out.append("  motifs: " + ", ".join(item["motifs"]))
        for locator in item.get("locators") or []:
            if len(item.get("locators") or []) == 1 and locator["identity"] == item["id"]:
                break
            extra = []
            speaker = (locator.get("speaker") or {}).get("display_name")
            if speaker:
                extra.append(f"speaker={speaker}")
            if locator.get("database_entity"):
                extra.append("entity=" + json.dumps(locator["database_entity"], ensure_ascii=False))
            if locator.get("database_values"):
                extra.append("values=" + ",".join(locator["database_values"]))
            out.append(f"  - {locator['identity']} " + " ".join(extra))
        if item.get("nearby_commands"):
            out.append("  nearby:")
            out += _render_commands(item["nearby_commands"], "    ")
        for context in item.get("suspect_contexts") or []:
            out.append(f"  around {context['identity']}:")
            out += _render_commands(context["nearby_commands"], "    ")
    for key, scene in (bundle.get("scenes") or {}).items():
        out += ["", f"## SCENE {key} {scene['scene_id']} ({len(scene['lines'])} lines)"]
        for line in scene["lines"]:
            named = [str(numbers[item]) for item in line.get("items") or [] if item in numbers]
            mark = (">>ITEM " + ",".join(named)) if named else "  "
            out += _render_line(line, mark)
    for motif_id, motif in (bundle.get("motifs") or {}).items():
        out += [
            "",
            f"## MOTIF {motif_id} {motif.get('disposition', '')}",
            "  guidance: " + _context_text(motif.get("guidance")),
            "  screen note: " + _context_text(motif.get("note")),
        ]
        for variant in motif.get("variants") or []:
            out.append(
                "  - " + _context_text(variant.get("source"))
                + " || " + _context_text(variant.get("translation"))
            )
    return out


def _render_group(item: dict) -> list[str]:
    rule = item["rule"]
    out = [
        f"### SWEEP {item['id']} {item['family_key']}: "
        f"{rule['find']!r} -> {rule['replace']!r}"
        + (f" where the source has {rule['source_has']!r}" if rule.get("source_has") else ""),
        "  accepted: JP " + _context_text(item["example"]["source"]),
        "            EN " + _context_text(item["example"]["current"]),
        "           FIX " + _context_text(item["example"]["correction"]),
        "        reason " + _context_text(item["example"]["evidence"]),
    ]
    for candidate in item["candidates"]:
        speaker = f" <{candidate['speaker']}>" if candidate.get("speaker") else ""
        out += [
            f"  {candidate['id']} {candidate['scene']}{speaker}",
            "    JP:  " + _context_text(candidate["source"]),
            "    EN:  " + _context_text(candidate["current"]),
            "    FIX: " + _context_text(candidate["proposed"]),
        ]
    return out


def _render_editorial(item: dict) -> list[str]:
    finding = item["finding"]
    scene = finding.get("kind") == "scene"
    out = [
        f"### FINDING {item['id']} [{finding['severity']} {finding['category']}] "
        f"{finding.get('family_key', '')} occurrences={item['occurrences']}"
        + (f" SCENE CORRECTION of {len(finding['lines'])} lines" if scene else ""),
    ]
    if not scene:
        out += [
            "  JP:  " + _context_text(finding["source"]),
            "  EN:  " + _context_text(finding["current"]),
            "  FIX: " + _context_text(finding["correction"]),
        ]
    out += _render_boxes(item.get("targets"))
    out.append("  evidence: " + _context_text(finding["evidence"]))
    basis = finding.get("editorial_basis")
    if basis:
        out += [
            "  defect: " + _context_text(basis["defect"]),
            "  support: " + _context_text(basis["source_support"]),
        ]
    for conflict in item.get("conflicts") or []:
        out.append(f"  CONFLICT ({conflict['kind']}): " + conflict["message"])
    for place in item.get("after") or []:
        if "error" in place:
            out.append("  corrected screen: " + place["error"])
        elif place.get("clipped") or place.get("squeezed"):
            out.append("  corrected screen, still too long: " + _place_text(place))
        else:
            out.append(f"  corrected screen, fits: {place['title']}: {place['capture']}")
    if not scene:
        return out + _render_commands(item.get("nearby_commands"), "    ")
    # The whole scene, each changed line marked with its correction.
    fixes = {line["position"]: line["correction"] for line in finding["lines"]}
    out.append(f"  scene {finding['scene_id']} ({len(item['scene'])} lines):")
    for position, line in enumerate(item["scene"]):
        out += _render_line(line, ">>FIX" if position in fixes else "  ")
        if position in fixes:
            out.append(f"{'':>5}   FIX: {_context_text(fixes[position])}")
    return out


def render_bundle(task_dir: str | Path, bundle_id: str) -> str:
    """A bundle as compact text: what a reviewer reads instead of its JSON."""
    root, task, checkpoint = _load_task(task_dir)
    stage, row = _bundle_row(checkpoint, bundle_id)
    if row["status"] == "split":
        raise ValueError(_split_notice(row))
    bundle = _read_json(Path(row["path"]))
    # A follow-up or check bundle carries the index entries the task's lacks.
    screen_index = (
        {**_load_screen_index(root, task), **(bundle.get("screen_index") or {})}
        if stage == "screen" else {}
    )
    out = [
        f"BUNDLE {bundle_id} ({stage}, {bundle['item_count']} targets, "
        f"sha256 {bundle['content_sha256']}). Newlines show as ⏎."
    ]
    if stage == "deep":
        out += _render_deep(bundle)
    else:
        for item in bundle["items"]:
            out.append("")
            if stage == "screen":
                out += _render_screen_item(item, screen_index)
            elif stage == "sweep":
                out += _render_group(item)
            else:
                out += _render_editorial(item)
    out += _glossary_section(root, bundle)
    return "\n".join(out) + "\n"


def _glossary_entries(text: str) -> list[tuple[list[str], list[str], str]]:
    """Each glossary line's Japanese forms, its English and the whole line,
    whose notes, such as a character's gender, stay with it."""
    return [
        (
            [alias for source, _english in pairs for alias in glossary_rules.aliases(source)],
            [english for _source, english in pairs],
            line,
        )
        for pairs, line, _section, _is_base in glossary_rules.glossary_lines(text)
    ]


def _bundle_wording(value: Any, japanese: list[str], names: set[str]) -> None:
    """Collect a bundle's Japanese and the speaker names it shows."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source", "original"}:
                japanese.append(
                    item if isinstance(item, str)
                    else json.dumps(item, ensure_ascii=False)
                )
            elif key == "speaker":
                name = item.get("display_name") if isinstance(item, dict) else item
                if name:
                    names.add(str(name))
            elif key == "speakers" and isinstance(item, list):
                names.update(str(name) for name in item if name)
            else:
                _bundle_wording(item, japanese, names)
    elif isinstance(value, list):
        for item in value:
            _bundle_wording(item, japanese, names)


def _glossary_section(root: Path, bundle: dict[str, Any]) -> list[str]:
    """The glossary entries whose Japanese a bundle holds, or whose English
    names one of its speakers, so a reviewer needs no other glossary."""
    japanese: list[str] = []
    names: set[str] = set()
    _bundle_wording(bundle, japanese, names)
    text = "\n".join(japanese)
    glossary = (_read_json(root / "context.json").get("glossary") or {}).get("text")
    used = [
        line for terms, english, line in _glossary_entries(glossary)
        if names.intersection(english)
        or any(glossary_rules.mentions(text, term) for term in terms)
    ]
    return ["", "## GLOSSARY entries for this bundle's text", *used] if used else []


def _decode_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer {pointer!r}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _resolve_parts(value: Any, parts: Iterable[str]) -> Any:
    current = value
    for part in parts:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _entry_numbers(data_root: Path, record: dict, cache: dict[str, Any]) -> set[str]:
    """The numbers of the database entry that holds a record."""
    parts = _decode_pointer(record["source_pointer"])
    if "_original" not in parts:
        return set()
    filename = record["file"]
    if filename not in cache:
        cache[filename] = json.loads((data_root / filename).read_text(encoding="utf-8-sig"))
    return _number_values(_resolve_parts(cache[filename], parts[: parts.index("_original")]))


def _nearby_commands(data_root: Path, record: dict, cache: dict[str, Any]) -> list[dict]:
    parts = _decode_pointer(record["source_pointer"])
    list_positions = [index for index, part in enumerate(parts[:-1]) if part == "list"]
    if not list_positions:
        return []
    list_pos = list_positions[-1]
    try:
        command_index = int(parts[list_pos + 1])
    except (ValueError, IndexError):
        return []
    filename = record["file"]
    if filename not in cache:
        cache[filename] = json.loads((data_root / filename).read_text(encoding="utf-8-sig"))
    commands = _resolve_parts(cache[filename], parts[: list_pos + 1])
    if not isinstance(commands, list):
        return []
    compact = []
    for index in range(max(0, command_index - 3), min(len(commands), command_index + 4)):
        command = commands[index]
        if not isinstance(command, dict):
            continue
        compact.append({
            "index": index,
            "code": command.get("code"),
            "indent": command.get("indent"),
            "parameters": command.get("parameters"),
            "original": command.get("_original"),
        })
    return compact


def _deep_basis(
    root: Path,
    checkpoint: dict[str, Any],
    manifest: dict[str, Any],
    declined: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """What deep items are made from: each candidate's reasons, with the
    accepted screen rationale, full scenes and motif adjudication behind it.

    An observation is screen evidence too, except on a line reviewers
    declined, which stays out of deep review.
    """
    screen_index = _load_screen_index(root, _read_json(root / "task.json"))
    records, _clusters = _record_maps(manifest)
    candidates = copy.deepcopy(checkpoint["deep"].get("candidate_reasons") or {})
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scenes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    motifs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Every screened scene by its command list, and by each of its copies',
    # with the cluster of each of its lines.
    screened: dict[str, dict[str, Any]] = {}
    line_clusters: dict[str, str] = {}

    for row in checkpoint["screen"]["bundles"]:
        if row.get("status") != "accepted" or not row.get("result_path"):
            continue
        bundle = _read_json(Path(row["path"]))
        result = _read_json(Path(row["result_path"]))
        target_scenes: dict[str, dict[str, Any]] = {}
        motif_items = _screen_motif_map(bundle)
        for item in bundle["items"]:
            if item.get("kind") != "scene":
                continue
            scene = {
                "scene_id": item["scene_id"],
                "line_count": item["line_count"],
                "lines": [
                    {
                        **line,
                        "command": _command_number(
                            _target_entry(
                                screen_index, bundle, line.get("id") or line["context_id"]
                            )["representative_identity"]
                        ),
                    }
                    for line in item["lines"]
                ],
            }
            for copy_id in item.get("scene_copies") or [item["scene_id"]]:
                screened[copy_id] = scene
            for line in item["lines"]:
                target_id = line.get("id") or line.get("context_id")
                if target_id:
                    target_scenes[target_id] = scene
                    line_clusters[target_id] = str(
                        _target_entry(screen_index, bundle, target_id).get("cluster_id")
                        or ""
                    )

        for exception in result["exceptions"]:
            target_id = exception["id"]
            target = _target_entry(screen_index, bundle, target_id)
            cluster_id = target.get("cluster_id") or target_id
            evidence[cluster_id].append({
                "target_id": target_id,
                "verdict": exception["verdict"],
                "categories": list(exception["categories"]),
                "note": exception["note"],
            })
            scene = target_scenes.get(target_id)
            if scene:
                scenes[cluster_id][scene["scene_id"]] = scene

        # A declined variant was not judged with the rest.
        declines = _result_declines(result)
        for review in result["motif_reviews"]:
            motif = motif_items[review["id"]]
            variants = [
                variant for variant in motif["variants"]
                if variant["id"] not in declines
            ]
            context = {
                "id": motif["id"],
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": len(variants),
                "variants": variants,
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
            }
            for variant in variants:
                motifs[variant["id"]].append(context)

    for observation in checkpoint.get("observations") or []:
        identity, cluster_id = observation["identity"], observation["cluster_id"]
        if identity in declined["identities"]:
            continue
        _merge_candidate(candidates, cluster_id, ["observation"], [identity])
        position = _scene_position(records[identity])
        scene = screened.get(position[0]) if position else None
        # The scene line the observation names, which its deep item marks.
        target_id = next((
            line_id
            for line in (scene or {}).get("lines") or []
            if (line_id := line.get("id") or line.get("context_id"))
            and line_clusters.get(line_id) == cluster_id
        ), "")
        evidence[cluster_id].append({
            "target_id": target_id or identity,
            "verdict": "observation",
            "identity": identity,
            "categories": list(observation["categories"]),
            "note": observation["note"],
        })
        if scene and target_id:
            scenes[cluster_id][scene["scene_id"]] = scene

    _reopen_disputed_preserved_motifs(candidates, evidence, motifs)
    return {
        "candidates": candidates,
        "evidence": dict(evidence),
        "scenes": {key: list(value.values()) for key, value in scenes.items()},
        "motifs": dict(motifs),
    }


def _reopen_disputed_preserved_motifs(
    candidate_reasons: dict[str, dict[str, Any]],
    screen_evidence: dict[str, list[dict[str, Any]]],
    motif_contexts: dict[str, list[dict[str, Any]]],
) -> None:
    """Deep-review a whole preserved motif when scene evidence disputes its wordplay."""
    disputed = {
        motif["id"]
        for cluster_id, evidence_rows in screen_evidence.items()
        if cluster_id in candidate_reasons
        and any(
            _normalize_category(category) == "wordplay"
            for evidence in evidence_rows
            for category in evidence.get("categories") or []
        )
        for motif in motif_contexts.get(cluster_id) or []
        if motif.get("disposition") == "preserved"
    }
    if not disputed:
        return

    for cluster_id, contexts in motif_contexts.items():
        for motif in contexts:
            if motif.get("id") not in disputed:
                continue
            variant = next(
                (
                    item for item in motif.get("variants") or []
                    if item.get("id") == cluster_id
                ),
                {},
            )
            _merge_candidate(
                candidate_reasons,
                cluster_id,
                ["motif-scene-contradiction"],
                [str(variant.get("representative_identity") or "")],
            )
            break


def _motif_translation_roster(context: dict[str, Any]) -> dict[str, Any]:
    """Keep family-wide comparison evidence without repeating every context window."""
    return {
        key: value for key, value in context.items() if key != "variants"
    } | {
        "variants": [
            {
                key: variant[key]
                for key in ("source", "translation")
                if key in variant
            }
            for variant in context.get("variants") or []
        ]
    }


def _screen_target_rows(
    root: Path, checkpoint: dict[str, Any], screen_index: dict[str, dict[str, str]]
) -> dict[str, tuple[str, str]]:
    """Each screen target ID with its cluster and the bundle that offers it:
    the task's own, or the latest follow-up that targets a set-aside line
    again."""
    targets = {
        target: ((screen_index.get(target) or {}).get("cluster_id") or target, bundle_id)
        for target, bundle_id in _read_json(root / "screen-targets.json")["targets"].items()
    }
    for row in checkpoint["screen"]["bundles"]:
        if not row.get("follow_up"):
            continue
        bundle = _read_json(Path(row["path"]))
        for item in bundle["items"]:
            for line in item["lines"]:
                if "id" in line:
                    targets[line["id"]] = (
                        _target_entry(screen_index, bundle, line["id"])["cluster_id"],
                        row["id"],
                    )
    return targets


def _read_scenes(checkpoint: dict[str, Any]) -> set[str]:
    """Scenes a screen reviewer read: those of scene items whose latest
    bundle, after any decline moved them, was accepted."""
    latest: dict[tuple[str, str], tuple[str, list[str]]] = {}
    for row in checkpoint["screen"]["bundles"]:
        origin = row.get("origin") or row["id"]
        for item in _read_json(Path(row["path"]))["items"]:
            if item.get("kind") == "scene":
                latest[(origin, item["id"])] = (
                    row["status"], item.get("scene_copies") or [item["scene_id"]]
                )
    return {
        scene
        for status, copies in latest.values() if status == "accepted"
        for scene in copies
    }


def _declined_scope(
    root: Path,
    checkpoint: dict[str, Any],
    manifest: dict[str, Any],
    *,
    waiting: bool = False,
) -> dict[str, Any]:
    """What reviewers declined: set aside, and with `waiting` also still offered.

    `declined_scenes` are the scenes of declined screen items, `scenes` those
    no screen reviewer read, and `context_scenes` adds the scenes of declined
    deep items. A cluster stays screened while another target covers it, such
    as a follow-up's: `unscreened` are the clusters every screen target of
    which was declined, `clusters` adds those deep review declined, and
    `identities` are the lines no correction may target: those clusters' and
    every line of a scene no screen reviewer read.
    """
    task = _read_json(root / "task.json")
    screen_index = _load_screen_index(root, task)
    records, clusters = _record_maps(manifest)
    statuses = {"set-aside", "pending", "assigned"} if waiting else {"set-aside"}
    declined_scenes: set[str] = set()
    context_scenes: set[str] = set()
    declined_targets: dict[str, str] = {}
    unreviewed: set[str] = set()
    # Clusters an accepted deep review judged, read once a deep decline needs them.
    judged: set[str] | None = None
    items = []
    for stage in REVIEW_STAGES:
        for row in checkpoint.get(stage, {}).get("bundles", []):
            if row["status"] not in statuses or not row.get("declined_by"):
                continue
            bundle = _read_json(Path(row["path"]))
            for item in bundle["items"]:
                kind = item.get("kind") or stage
                units = [unit["id"] for unit in _units(item)]
                # A family part was declined unit by unit, and later whole.
                keys = {item["id"], *units}
                if stage in {"sweep", "editorial"}:
                    # Lines were reviewed; only these fixes are left out.
                    pass
                elif stage == "deep":
                    if judged is None:
                        judged = set(_latest_deep_reviews(checkpoint))
                    # A declined follow-up leaves the earlier deep review standing.
                    if item["id"] not in judged:
                        unreviewed.add(item["id"])
                    context_scenes |= {
                        bundle["scenes"][key]["scene_id"]
                        for key in item.get("scenes") or []
                    }
                elif kind == "scene":
                    copies = set(item.get("scene_copies") or [item["scene_id"]])
                    declined_scenes |= copies
                    context_scenes |= copies
                    declined_targets.update({
                        line["id"]: _target_entry(
                            screen_index, bundle, line["id"]
                        )["cluster_id"]
                        for line in item["lines"] if "id" in line
                    })
                elif kind == "cluster":
                    declined_targets[item["id"]] = item["id"]
                items.append({
                    "stage": stage,
                    "id": item["id"],
                    "kind": "deep" if stage == "deep" else kind,
                    **(
                        {"part_of": item["part_of"], "units": units}
                        if item.get("part_of") else {}
                    ),
                    "set_aside": row["status"] == "set-aside",
                    # One reason a decline, however many units it named.
                    "reasons": [
                        reason
                        for decline in row.get("declines") or []
                        for reason in dict.fromkeys(
                            reason for key, reason in decline["reasons"].items()
                            if key in keys
                        )
                    ],
                    "declined_by": row["declined_by"],
                })
    offered: dict[str, set[str]] = defaultdict(set)
    if declined_targets:
        for target, (cluster_id, _bundle) in _screen_target_rows(
            root, checkpoint, screen_index
        ).items():
            offered[cluster_id].add(target)
    unscreened = {
        cluster_id for cluster_id in set(declined_targets.values())
        if offered[cluster_id].issubset(declined_targets)
    }
    unreviewed |= unscreened
    # Only a follow-up shows a scene twice, so only then may another reviewer
    # have read a declined scene.
    scenes = declined_scenes - (
        _read_scenes(checkpoint)
        if declined_scenes
        and any(row.get("follow_up") for row in checkpoint["screen"]["bundles"])
        else set()
    )
    identities = {
        identity
        for cluster_id in unreviewed if cluster_id in clusters
        for identity in clusters[cluster_id]["identities"]
    } | {
        record["identity"]
        for record in records.values()
        if (position := _scene_position(record)) and position[0] in scenes
    }
    return {
        "scenes": scenes,
        "declined_scenes": declined_scenes,
        "context_scenes": context_scenes,
        "unscreened": unscreened,
        "clusters": unreviewed,
        "identities": identities,
        "items": items,
    }


def _printed_scenes(bundle: dict[str, Any]) -> set[str]:
    """The scenes a bundle prints whole: its scene items, with their copies, and
    the scenes a deep bundle prints once."""
    scenes = {scene["scene_id"] for scene in (bundle.get("scenes") or {}).values()}
    for item in bundle["items"]:
        if item.get("kind") == "scene":
            scenes |= set(item.get("scene_copies") or [item["scene_id"]])
    return scenes


def _assigned_scenes(checkpoint: dict[str, Any], worker: str) -> set[str]:
    """The scenes the worker's assigned bundles print, which its context may show
    even after a reviewer declined them: the bundle already shows their text."""
    if not worker:
        return set()
    return {
        scene
        for stage in REVIEW_STAGES
        for row in checkpoint.get(stage, {}).get("bundles", [])
        if row["status"] == "assigned" and row.get("assigned_to") == worker
        for scene in _printed_scenes(_read_json(Path(row["path"])))
    }


def _open_follow_ups(
    root: Path, task: dict[str, Any], checkpoint: dict[str, Any]
) -> int:
    """Target set-aside lines again in scenes no reviewer declined.

    A cluster whose every screen target was set aside gets a target in another
    scene that shows it, chosen as screening chose its scenes, in follow-up
    screen bundles. A line only declined scenes show stays set aside. Returns
    how many targets opened.
    """
    manifest = _read_json(root / "inventory.json")
    declined = _declined_scope(root, checkpoint, manifest)
    if not declined["unscreened"]:
        return 0
    groups, cluster_ids = _scene_groups(manifest)
    candidates = [
        group for group in groups
        if group["clusters"] & declined["unscreened"]
        and not {copy_id for copy_id, _records in group["copies"]}
        & declined["declined_scenes"]
    ]
    uncovered = declined["unscreened"] & set().union(
        *(group["clusters"] for group in candidates)
    )
    chosen = []
    while uncovered:
        group = min(
            (group for group in candidates if group["clusters"] & uncovered),
            key=lambda group: (-len(group["clusters"] & uncovered), group["scene_id"]),
        )
        chosen.append((group, group["clusters"] & uncovered))
        uncovered -= group["clusters"]
    if not chosen:
        return 0
    compact = {
        item["id"]: item
        for item in _compact_items(manifest, _read_json(root / "context.json"))
    }
    _lint, lint_fixes = _lint_items(manifest, task["layout"], _lint_game(root, manifest))
    screen = checkpoint["screen"]
    # Ordinals continue past every target the task has offered.
    ordinal = int(screen["total_items"])
    items = []
    screen_index: dict[str, dict[str, str]] = {}
    for group, targets in sorted(chosen, key=lambda entry: entry[0]["scene_id"]):
        item, item_index = _scene_item(
            group, targets, compact, lint_fixes, cluster_ids,
            item_id="scene-" + _sha256(
                "follow-up\0" + group["signature"] + "\0" + "\0".join(sorted(targets))
            )[:20],
        )
        item["ordinal"] = ordinal + 1
        for line in item["lines"]:
            if "id" in line:
                ordinal += 1
                line["ordinal"] = ordinal
        items.append(item)
        screen_index.update(item_index)
    configuration = task.get("screen_configuration") or {}
    rows = _write_bundles(root, _bundle_items(
        items,
        stage="screen",
        char_budget=int(configuration.get("char_budget", DEFAULT_SCREEN_CHAR_BUDGET)),
        item_limit=int(configuration.get("item_limit", DEFAULT_SCREEN_ITEM_LIMIT)),
        first=1 + sum(
            not row.get("origin") and not row.get("check_of")
            for row in screen["bundles"]
        ),
        screen_index=screen_index,
    ))
    for row in rows:
        row["follow_up"] = True
    screen["bundles"] += rows
    opened = sum(item["target_count"] for item in items)
    screen["total_items"] = int(screen["total_items"]) + opened
    return opened


def _lint_decisions(
    checkpoint: dict[str, Any],
    declined: dict[str, Any],
    manifest: dict[str, Any],
    layout: dict[str, Any],
    game: lint.Game,
) -> dict[str, dict[str, Any]]:
    """The lint families accepted for each cluster, with reviewers' notes:
    the automatic families wherever they fix a line, which needs no reviewer,
    and the others where reviewers accepted them."""
    accepted: dict[str, dict[str, Any]] = {}
    for cluster_id, fixes in _lint_items(manifest, layout, game)[1].items():
        automatic = {family for family in fixes["families"] if family in lint.AUTOMATIC}
        if automatic:
            accepted[cluster_id] = {"families": automatic, "notes": []}
    for row in checkpoint["screen"]["bundles"]:
        if row["status"] != "accepted":
            continue
        result = _read_json(Path(row["result_path"]))
        reviews = {review["id"]: review for review in result.get("lint_reviews") or []}
        if not reviews:
            continue
        # Declined proposals were not judged; rejected ones were.
        declines = _result_declines(result)
        for item in _read_json(Path(row["path"]))["items"]:
            review = reviews.get(item["id"])
            if item.get("kind") != "lint-family" or review is None:
                continue
            left_out = set(review["rejected"]) | declines
            # A note beside rejected proposals says why they were rejected,
            # so it stays off the accepted ones.
            note = "" if review["rejected"] else str(review.get("note") or "").strip()
            for proposal in item["proposals"]:
                cluster_id = proposal["cluster_id"]
                if proposal["id"] in left_out or cluster_id in declined["clusters"]:
                    continue
                entry = accepted.setdefault(
                    cluster_id, {"families": set(), "notes": []}
                )
                entry["families"].add(item["family"])
                if note:
                    entry["notes"].append(note)
    return accepted


def _add_sweep_findings(
    findings: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    records: dict[str, dict[str, Any]],
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Accepted sweep candidates as findings, one per line, rules combined.

    Returns candidates left out because their combined rules would block apply.
    """
    by_cluster: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)
    for row in checkpoint.get("sweep", {}).get("bundles", []):
        if row["status"] != "accepted":
            continue
        result = _read_json(Path(row["result_path"]))
        reviews = {review["id"]: review for review in result["reviews"]}
        declines = _result_declines(result)
        for item in _read_json(Path(row["path"]))["items"]:
            review = reviews.get(item["id"])
            if review is None:
                continue
            left_out = set(review["rejected"]) | declines
            for candidate in item["candidates"]:
                if candidate["id"] not in left_out:
                    by_cluster[candidate["cluster_id"]].append((
                        {**item, "reviewer": str(row.get("assigned_to") or "")},
                        candidate,
                        str(review.get("note") or "").strip(),
                    ))
    # A line a follow-up deep review corrected keeps that correction.
    corrected = {
        finding["cluster_id"] for finding in findings if finding.get("kind") != "show-text"
    }
    dropped = []
    for cluster_id, accepted in sorted(by_cluster.items()):
        if cluster_id in corrected:
            continue
        accepted.sort(key=lambda entry: entry[0]["family_key"])
        item, candidate, note = accepted[0]
        correction = candidate["current"]
        for family, _candidate, _note in accepted:
            correction = correction.replace(
                family["rule"]["find"], family["rule"]["replace"]
            )
        targets = sorted(
            set.intersection(*(set(entry[1]["identities"]) for entry in accepted))
        )
        problems = sorted({
            problem
            for identity in targets
            for problem in _record_problems(records[identity], correction, layout)
        })
        if problems or not targets:
            dropped.append({"cluster_id": cluster_id, "problems": problems})
            continue
        findings.append({
            "id": "",
            "cluster_id": cluster_id,
            "severity": item["severity"],
            "category": item["category"],
            "family_key": item["family_key"],
            "evidence": (
                "Same problem as an accepted correction: "
                + item["example"]["evidence"]
                + (" Sweep reviewer: " + note if note else "")
            ),
            "source": candidate["source"],
            "current": candidate["current"],
            "correction": correction,
            "target_identities": targets,
            "sweep_families": sorted({entry[0]["family_key"] for entry in accepted}),
            "authors": sorted({
                author
                for entry in accepted
                for author in (entry[0].get("author", ""), entry[0]["reviewer"])
            }),
        })
    return dropped


def _add_lint_findings(
    findings: list[dict[str, Any]],
    accepted: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    declined: dict[str, Any],
    layout: dict[str, Any],
    game: lint.Game,
) -> list[dict[str, Any]]:
    """Mark reviewer corrections with their lines' accepted lint fixes, which
    compose after the editorial pass, and add the rest as findings.

    A scene correction's lines take their own clusters' fixes; the findings
    added here still cover those lines, should editorial withdraw it.
    Returns the fixes left out because the fixed text would block apply.
    """
    records, clusters = _record_maps(manifest)
    by_cluster = {
        finding["cluster_id"]: finding for finding in findings
        if finding.get("kind") not in {"show-text", "scene"}
    }
    for finding in findings:
        if finding.get("kind") != "scene":
            continue
        for line in finding["lines"]:
            if line["cluster_id"] in accepted:
                line["lint_families"] = sorted(
                    accepted[line["cluster_id"]]["families"], key=lint.ORDER.index
                )
    dropped = []
    for cluster_id, decision in sorted(accepted.items()):
        families = sorted(decision["families"], key=lint.ORDER.index)
        cluster = clusters[cluster_id]
        finding = by_cluster.get(cluster_id)
        if finding:
            finding["lint_families"] = families
        remaining = [
            identity for identity in cluster["identities"]
            if not finding or identity not in finding["target_identities"]
        ]
        # Automatic fixes need no reviewer, so they reach declined lines too.
        parts = [
            (families, [
                identity for identity in remaining
                if identity not in declined["identities"]
            ]),
            ([family for family in families if family in lint.AUTOMATIC], [
                identity for identity in remaining
                if identity in declined["identities"]
            ]),
        ]
        for part, targets in parts:
            if not part or not targets:
                continue
            composed = lint.compose(cluster["source"], cluster["live"], part, game)
            if composed == cluster["live"]:
                continue
            problems = [
                problem
                for identity in targets
                for problem in _record_problems(records[identity], composed, layout)
            ]
            if problems:
                dropped.append({
                    "cluster_id": cluster_id,
                    "families": part,
                    "problems": sorted(set(problems)),
                })
                continue
            reviewed = any(family not in lint.AUTOMATIC for family in part)
            findings.append({
                "id": "",
                "cluster_id": cluster_id,
                "severity": "medium",
                "category": next(
                    (
                        lint.FAMILIES[family]["category"] for family in part
                        if lint.FAMILIES[family]["category"] != "formatting"
                    ),
                    "formatting",
                ),
                "family_key": part[0],
                "evidence": " ".join(
                    lint.note(family, cluster["source"], cluster["live"], game)
                    or lint.FAMILIES[family]["description"]
                    for family in part
                ) + "".join(
                    " Reviewer: " + note for note in decision["notes"][:2] if reviewed
                ),
                "source": cluster["source"],
                "current": cluster["live"],
                "correction": composed,
                "target_identities": targets,
                "lint_families": part,
                "lint_only": True,
            })
    return dropped


def _not_reviewed(
    scope: dict[str, Any], records: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """The lines no reviewer judged, for the optional queue the user can read."""
    return [
        {
            "identity": identity,
            "file": records[identity]["file"],
            "source": records[identity]["source"],
            "current": records[identity]["live"],
        }
        for identity in sorted(scope["identities"])
    ]


def _deep_items(
    root: Path,
    checkpoint: dict[str, Any],
    manifest: dict[str, Any],
    declined: dict[str, Any],
    basis: dict[str, dict[str, Any]],
    only: set[str],
    prior: dict[str, dict[str, Any]],
) -> list[dict]:
    """Deep items for the `only` candidates of the basis; a cluster reviewed
    before carries that `prior_review` to reconcile with newer evidence."""
    context = _read_json(root / "context.json")
    task = _read_json(root / "task.json")
    records, clusters = _record_maps(manifest)
    game = _lint_game(root, manifest)
    lint_accepted = _lint_decisions(checkpoint, declined, manifest, task["layout"], game)
    compact = {item["id"]: item for item in _compact_items(manifest, context)}
    by_source: dict[str, list[dict]] = defaultdict(list)
    for cluster in manifest["clusters"]:
        by_source[cluster["source"]].append(cluster)
    data_root = Path(task["data_root"])
    failed_checks = _database_checks(manifest, data_root)
    for cluster_id, found in [
        *_fit_checks(manifest, task["layout"]).items(),
        *_interface_checks(_capture_folder(root), manifest).items(),
    ]:
        failed_checks[cluster_id] = [*failed_checks.get(cluster_id, []), *found]
    document_cache: dict[str, Any] = {}
    candidate_reasons = basis["candidates"]
    screen_evidence, screen_scenes = basis["evidence"], basis["scenes"]
    motif_contexts = basis["motifs"]
    # The header check read the game's files when the task was made, before
    # any apply could change them.
    header_notes: dict[str, list[str]] = defaultdict(list)
    if (root / "header-check.json").is_file():
        for flag in _read_json(root / "header-check.json")["flags"]:
            header_notes[flag["identity"]].append(flag["evidence"])
    items = []
    for identity in manifest["review_sequence"]:
        # Lines in scenes a reviewer declined stay out of deep review.
        if (
            identity not in candidate_reasons
            or identity in declined["clusters"]
            or identity not in only
        ):
            continue
        cluster = clusters[identity]
        member_records = [
            records[item] for item in cluster["identities"]
            if item not in declined["identities"]
        ]
        if not member_records:
            continue
        candidate = candidate_reasons[identity]
        context_identities = [
            item for item in candidate.get("context_identities") or []
            if item in records and item in cluster["identities"]
            and item not in declined["identities"]
        ]
        representative = (
            records[context_identities[0]] if context_identities else member_records[0]
        )
        alternatives = sorted({
            other["live"] for other in by_source[cluster["source"]]
            if other["live"] != cluster["live"]
        })
        item = {
            **compact[identity],
            "deep_reasons": list(candidate.get("reasons") or []),
            "identities": [record["identity"] for record in member_records],
            "screen_context_identities": context_identities,
            "locators": [{
                "identity": record["identity"],
                "file": record["file"],
                "source_pointer": record["source_pointer"],
                "live_pointers": record["live_pointers"],
                "live_transform": record["live_transform"],
                "event_code": record.get("event_code"),
                "speaker": record.get("speaker"),
                "database_entity": record.get("database_entity"),
                "choice_context": record.get("choice_context"),
                **(
                    {"box": box}
                    if (box := _box(record, task["layout"])) else {}
                ),
                **(
                    {"database_values": sorted(
                        _entry_numbers(data_root, record, document_cache)
                    )}
                    if record.get("classification") == "database" else {}
                ),
            } for record in member_records],
            "nearby_commands": _nearby_commands(data_root, representative, document_cache),
            "suspect_contexts": [{
                "identity": context_identity,
                "nearby_commands": _nearby_commands(
                    data_root, records[context_identity], document_cache
                ),
            } for context_identity in context_identities[:4]],
            "same_source_alternatives": alternatives[:20],
        }
        if screen_evidence.get(identity):
            item["screen_evidence"] = screen_evidence[identity]
        failed = [*failed_checks.get(identity, []), *(
            {"check": "show-text-header", "note": note}
            for record in member_records
            for note in header_notes.get(record["identity"], [])
        )]
        if failed:
            item["checks"] = failed
        if identity in lint_accepted:
            families = sorted(lint_accepted[identity]["families"], key=lint.ORDER.index)
            item["lint"] = {
                "families": families,
                "proposed": lint.compose(
                    cluster["source"], cluster["live"], families, game
                ),
            }
        scenes = [
            scene for scene in screen_scenes.get(identity) or []
            if scene["scene_id"] not in declined["scenes"]
        ]
        if scenes:
            item["screen_scene_contexts"] = scenes
        if motif_contexts.get(identity):
            contexts = motif_contexts[identity]
            if "motif-scene-contradiction" in item["deep_reasons"]:
                contexts = [_motif_translation_roster(value) for value in contexts]
            item["motif_contexts"] = contexts
        if identity in prior:
            item["prior_review"] = prior[identity]
        items.append(item)
    return items


def _screen_targets(items: list[dict[str, Any]], bundles: list[dict]) -> dict:
    """Which screen bundle targets each cluster, and which review its motifs."""
    targets: dict[str, str] = {}
    motifs: dict[str, list[str]] = defaultdict(list)
    for bundle in bundles:
        for item in bundle["items"]:
            if item.get("kind") == "scene":
                for line in item["lines"]:
                    if "id" in line:
                        targets[line["id"]] = bundle["bundle_id"]
            elif item.get("kind") == "cluster":
                targets[item["id"]] = bundle["bundle_id"]
            elif item.get("kind") == "motif-family":
                for variant in item["variants"]:
                    motifs[variant["id"]].append(bundle["bundle_id"])
    return {"targets": targets, "motifs": dict(motifs)}


def _latest_deep_reviews(
    checkpoint: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Each cluster's latest accepted deep review, with its item and row; a
    later review saw everything the earlier one did."""
    latest = {}
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] != "accepted":
            continue
        items = {item["id"]: item for item in _read_json(Path(row["path"]))["items"]}
        for review in _read_json(Path(row["result_path"]))["reviews"]:
            if review["disposition"] != "declined":
                latest[review["id"]] = (review, items[review["id"]], row)
    return latest


def _issue_deep(root: Path, checkpoint: dict[str, Any], final: bool) -> int:
    """Open deep bundles for candidates whose screen evidence is complete.

    While screening continues, a batch opens once enough clusters are ready:
    their target bundle, its check and motif reviews are accepted. When
    screening ends, and again whenever QA would leave deep review or new
    observations wait, every remaining candidate opens, and a cluster whose
    evidence grew after its deep review opens again with that review beside
    it. Returns how many items opened.
    """
    deep = checkpoint["deep"]
    issued = deep.setdefault("issued", {})
    rows = deep.setdefault("bundles", [])
    open_clusters = {
        item["id"]
        for row in rows if row["status"] in {"pending", "assigned"}
        for item in _read_json(Path(row["path"]))["items"]
    }
    if not final:
        candidates = set(deep.get("candidate_reasons") or {}) | {
            observation["cluster_id"]
            for observation in checkpoint.get("observations") or []
        }
        index = _read_json(root / "screen-targets.json")
        screen_rows = {row["id"]: row for row in checkpoint["screen"]["bundles"]}
        statuses = {}
        for key, row in screen_rows.items():
            # A split bundle's targets are reviewed in the bundle that remained.
            while row["status"] == "split" and row.get("remainder"):
                row = screen_rows[row["remainder"]]
            statuses[key] = row["status"]
        # Bundles whose lines await a check: the checked bundle, which a
        # follow-up's targets name, and the bundle it split from, which the
        # task's targets name.
        unchecked = {
            name
            for row in screen_rows.values()
            if row.get("check_of") and row["status"] != "accepted"
            for name in (row["check_of"], screen_rows[row["check_of"]].get("origin"))
            if name
        }
        screen_index = _load_screen_index(root, _read_json(root / "task.json"))
        cluster_bundle = {
            cluster_id: bundle
            for cluster_id, bundle in _screen_target_rows(
                root, checkpoint, screen_index
            ).values()
        }
        ready = {
            cluster_id for cluster_id in candidates
            if cluster_id not in issued
            and statuses.get(cluster_bundle.get(cluster_id, "")) == "accepted"
            and cluster_bundle.get(cluster_id, "") not in unchecked
            and all(
                statuses.get(bundle) == "accepted"
                for bundle in index["motifs"].get(cluster_id, [])
            )
        }
        if len(ready) < EARLY_DEEP_BATCH:
            return 0
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    manifest = _read_json(root / "inventory.json")
    declined = _declined_scope(root, checkpoint, manifest, waiting=not final)
    basis = _deep_basis(root, checkpoint, manifest, declined)
    candidates, evidence = basis["candidates"], basis["evidence"]
    scenes, motifs = basis["scenes"], basis["motifs"]
    if final:
        ready = set(candidates)
        # The observations this round has considered.
        deep["observed"] = len(checkpoint.get("observations") or [])

    def signature(cluster_id):
        return _sha256(_canonical_bytes([
            sorted(candidates[cluster_id]["reasons"]),
            evidence.get(cluster_id) or [],
            sorted(scene["scene_id"] for scene in scenes.get(cluster_id) or []),
            [
                [motif["id"], motif.get("disposition"), motif.get("suspect_ids")]
                for motif in motifs.get(cluster_id) or []
            ],
        ]))[:20]

    fresh = {
        cluster_id for cluster_id in ready & set(candidates)
        if cluster_id not in declined["clusters"]
        and cluster_id not in open_clusters
        and issued.get(cluster_id) != signature(cluster_id)
    }
    if not fresh:
        return 0
    latest = _latest_deep_reviews(checkpoint)
    prior = {
        cluster_id: {
            key: review.get(key)
            for key in ("disposition", "severity", "category", "evidence", "correction")
        }
        for cluster_id, (review, _item, _row) in latest.items()
        if cluster_id in fresh
    }
    items = _deep_items(root, checkpoint, manifest, declined, basis, fresh, prior)
    if not items:
        return 0
    bundles = _bundle_deep(items, first=len(rows) + 1)
    rows += _write_bundles(root, bundles)
    for item in items:
        issued[item["id"]] = signature(item["id"])
    deep["total_items"] = int(deep.get("total_items", 0)) + len(items)
    deep["projected_items"] = max(len(candidates), deep["total_items"])
    return len(items)


def _settle_declined(
    checkpoint: dict[str, Any], stage: str, skip_declined: bool
) -> None:
    """Require a finished stage; declined bundles nobody else took are set aside
    only on request."""
    rows = checkpoint[stage]["bundles"]
    waiting = [
        row for row in rows
        if row["status"] == "pending" and row.get("declined_by")
    ]
    checks = [
        row["id"] for row in rows
        if row.get("check_of") and row["status"] in {"pending", "assigned"}
    ]
    if checks:
        raise ValueError(
            f"{len(checks)} check bundle(s) wait for a reviewer that did not "
            f"screen their lines ({', '.join(checks)}): claim each with next "
            "under another worker name"
        )
    if any(
        row["status"] not in FINISHED_STATUSES and row not in waiting
        for row in rows
    ):
        raise ValueError(f"Every {stage} bundle must be accepted first")
    if waiting and not skip_declined:
        raise ValueError(
            f"{len(waiting)} declined {stage} bundle(s) wait for a reviewer on "
            f"another helper ({', '.join(row['id'] for row in waiting)}): such a "
            "worker claims each with next --bundle ID --helper NAME, or use "
            "--skip-declined to report them as not reviewed"
        )
    for row in waiting:
        row["status"] = "set-aside"
        row["skipped"] = True


def _sweep_items(
    checkpoint: dict[str, Any],
    manifest: dict[str, Any],
    declined: dict[str, Any],
    offered: set[str],
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every other line an accepted family's sweep rule changes, for group
    review, leaving out the candidates an earlier sweep `offered`."""
    records, _clusters = _record_maps(manifest)
    corrected: set[str] = set()
    families: dict[str, dict[str, Any]] = {}
    for review, item, row in _latest_deep_reviews(checkpoint).values():
        if review["disposition"] != "actionable":
            continue
        corrected.add(review["id"])
        if not review.get("sweep"):
            continue
        family_key = _normalize_family_key(review["family_key"])
        shapes = sorted(item.get("display_shapes") or [])
        key = _sha256(_canonical_bytes([family_key, review["sweep"], shapes]))[:20]
        families.setdefault(key, {
            "family_key": family_key,
            "rule": review["sweep"],
            "shapes": shapes,
            "example": {
                "source": item["source"],
                "current": item["translation"],
                "correction": review["correction"],
                "evidence": review["evidence"],
            },
            "category": _normalize_category(review.get("category")),
            "severity": review["severity"],
            "author": str(row.get("assigned_to") or ""),
        })
    items = []
    for key, family in sorted(families.items()):
        find, replace = family["rule"]["find"], family["rule"]["replace"]
        source_has = family["rule"].get("source_has", "")
        candidates = []
        for cluster in manifest["clusters"]:
            cluster_id = cluster["representative"]
            candidate_id = "sweep-" + _sha256(f"{key}\0{cluster_id}")[:16]
            if (
                cluster_id in corrected
                or cluster_id in declined["clusters"]
                or candidate_id in offered
                or find not in cluster["live"]
                or source_has not in cluster["source"]
            ):
                continue
            members = [
                records[identity] for identity in cluster["identities"]
                if identity not in declined["identities"]
                and (
                    not family["shapes"]
                    or records[identity].get("display_shape") in family["shapes"]
                )
            ]
            proposed = cluster["live"].replace(find, replace)
            if not members or any(
                _record_problems(record, proposed, layout) for record in members
            ):
                continue
            position = _scene_position(members[0])
            speaker = str((members[0].get("speaker") or {}).get("display_name") or "")
            candidates.append({
                "id": candidate_id,
                "cluster_id": cluster_id,
                "identities": [record["identity"] for record in members],
                "scene": position[0] if position else members[0]["file"],
                **({"speaker": speaker} if speaker else {}),
                "source": cluster["source"],
                "current": cluster["live"],
                "proposed": proposed,
            })
        candidates.sort(key=lambda row: (row["scene"], row["cluster_id"]))
        for start in range(0, len(candidates), LINT_ITEM_LIMIT):
            chunk = candidates[start : start + LINT_ITEM_LIMIT]
            items.append({
                "kind": "sweep-family",
                "id": "sweep-family-" + _sha256(
                    key + "\0" + "\0".join(row["id"] for row in chunk)
                )[:20],
                "ordinal": len(items) + 1,
                "family_key": family["family_key"],
                "rule": family["rule"],
                "category": family["category"],
                "severity": family["severity"],
                "example": family["example"],
                "author": family["author"],
                "target_count": len(chunk),
                "candidates": chunk,
            })
    return items


def _advance_unlocked(
    task_dir: str | Path, skip_declined: bool = False
) -> dict[str, Any]:
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] == "deep":
        _settle_declined(checkpoint, "deep", skip_declined)
        if _issue_deep(root, checkpoint, final=True):
            # Evidence that grew during deep review, such as an observation,
            # opens more of it first.
            checkpoint["updated_at"] = _utc_now()
            _atomic_write_json(root / "checkpoint.json", checkpoint)
            return status(root)
        manifest = _read_json(root / "inventory.json")
        sweep = checkpoint.setdefault(
            "sweep", {"total_items": 0, "accepted_items": 0, "bundles": []}
        )
        # A follow-up deep round adds only the lines no sweep offered yet.
        offered = {
            candidate["id"]
            for row in sweep["bundles"]
            for item in _read_json(Path(row["path"]))["items"]
            for candidate in item["candidates"]
        }
        items = _sweep_items(
            checkpoint,
            manifest,
            _declined_scope(root, checkpoint, manifest),
            offered,
            task["layout"],
        )
        bundles = _bundle_items(
            items,
            stage="sweep",
            char_budget=DEFAULT_DEEP_CHAR_BUDGET,
            item_limit=DEFAULT_DEEP_ITEM_LIMIT,
            first=len(sweep["bundles"]) + 1,
        ) if items else []
        sweep["bundles"] += _write_bundles(root, bundles) if bundles else []
        sweep["total_items"] += sum(item["target_count"] for item in items)
        checkpoint["stage"] = "sweep" if bundles else "ready-finalize"
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return status(root)
    if checkpoint["stage"] != "screen":
        return status(root)
    _settle_declined(checkpoint, "screen", skip_declined)
    if _open_follow_ups(root, task, checkpoint):
        # Screening goes on while set-aside lines wait in other scenes.
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return status(root)
    _issue_deep(root, checkpoint, final=True)
    checkpoint["deep"]["projected_items"] = checkpoint["deep"]["total_items"]
    checkpoint["stage"] = "deep" if checkpoint["deep"]["bundles"] else "ready-finalize"
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def advance(task_dir: str | Path, skip_declined: bool = False) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        return _advance_unlocked(root, skip_declined)


def rebuild_deep_from_screen(
    source_task_dir: str | Path, output_root: str | Path | None = None
) -> tuple[Path, dict[str, Any]]:
    """Create a current task by replaying immutable receipts from a completed screen."""
    source = Path(source_task_dir).expanduser().resolve()
    source_task = _read_json(source / "task.json")
    source_checkpoint = _read_json(source / "checkpoint.json")
    if (
        source_task.get("schema") != TASK_SCHEMA
        or source_checkpoint.get("schema") != CHECKPOINT_SCHEMA
        or source_checkpoint.get("task_sha256")
        != _sha256(_canonical_bytes(source_task))
    ):
        raise ValueError(f"Unsupported or corrupt source QA task: {source}")
    source_rows = source_checkpoint["screen"]["bundles"]
    if (
        not source_rows
        or any(row.get("status") != "accepted" for row in source_rows)
        or source_checkpoint["screen"]["accepted_items"]
        != source_checkpoint["screen"]["total_items"]
    ):
        raise ValueError("The source task must have a fully accepted screen stage")

    reusable_results: dict[str, Path] = {}
    reusable_summaries: dict[str, tuple[str, int]] = {}
    for row in source_rows:
        bundle_path = source / "bundles" / "screen" / f"{row['id']}.json"
        result_path = source / "results" / "screen" / f"{row['id']}.json"
        bundle = _read_json(bundle_path)
        checksum_value = dict(bundle)
        claimed = checksum_value.pop("content_sha256", "")
        if (
            bundle.get("schema") != BUNDLE_SCHEMA
            or bundle.get("stage") != "screen"
            or bundle.get("bundle_id") != row["id"]
            or claimed != row.get("sha256")
            or claimed != _sha256(_canonical_bytes(checksum_value))
        ):
            raise ValueError(f"Source screen bundle checksum is invalid: {row['id']}")
        result = _read_json(result_path)
        if result.get("bundle_sha256") != claimed:
            raise ValueError(f"Source screen result checksum is invalid: {row['id']}")
        _validate_screen_result(bundle, result)
        reusable_results[row["id"]] = result_path
        if not row.get("check_of"):
            reusable_summaries[row["id"]] = (claimed, int(row["item_count"]))

    destination_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else source.parents[2]
    )
    rebuilt, _state = prepare_task(
        source_task["game_root"],
        source_task["data_root"],
        source_task["focus"],
        destination_root,
        screen_char_budget=int(
            (source_task.get("screen_configuration") or {}).get(
                "char_budget", DEFAULT_SCREEN_CHAR_BUDGET
            )
        ),
        screen_item_limit=int(
            (source_task.get("screen_configuration") or {}).get(
                "item_limit", DEFAULT_SCREEN_ITEM_LIMIT
            )
        ),
        fit=source_task.get("layout"),
    )
    if rebuilt == source:
        raise ValueError("The source task already uses the current QA rules")
    _rebuilt_root, rebuilt_task, rebuilt_checkpoint = _load_task(rebuilt)
    for key in ("manifest_sha256", "context_sha256"):
        if rebuilt_task.get(key) != source_task.get(key):
            raise ValueError(f"Cannot reuse screening after {key} changed")
    rebuilt_summaries = {
        row["id"]: (row["sha256"], int(row["item_count"]))
        for row in rebuilt_checkpoint["screen"]["bundles"]
        if not row.get("check_of")
    }
    if rebuilt_summaries != reusable_summaries:
        raise ValueError("Current screen bundles differ; screening cannot be reused")

    if rebuilt_checkpoint["stage"] == "screen":
        # Accepted in their order under the same reviewers, the results open
        # the same checks, which take their own results in turn.
        for source_row in sorted(source_rows, key=lambda row: row.get("accepted_at") or ""):
            with _task_lock(rebuilt):
                _rebuilt_root, _task, checkpoint = _load_task(rebuilt)
                try:
                    _stage, row = _bundle_row(checkpoint, source_row["id"])
                except QAResultError as error:
                    raise ValueError(
                        "Current screen checks differ; screening cannot be reused"
                    ) from error
                if row["sha256"] != source_row["sha256"]:
                    raise ValueError(
                        "Current screen checks differ; screening cannot be reused"
                    )
                if row["status"] != "accepted":
                    row["status"] = "assigned"
                    row["assigned_to"] = str(source_row.get("assigned_to") or "")
                    _atomic_write_json(rebuilt / "checkpoint.json", checkpoint)
            accept_result(rebuilt, reusable_results[source_row["id"]])
        if _stage_finished(_read_task(rebuilt)[2], ["screen"]):
            return rebuilt, advance(rebuilt)
    return rebuilt, status(rebuilt)


def _draft_document(
    root: Path, task: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    """Findings from deep review, the sweep and lint, before the editorial pass."""
    manifest = _read_json(root / "inventory.json")
    records, clusters = _record_maps(manifest)
    declined = _declined_scope(root, checkpoint, manifest)
    faces = _face_names(Path(task["data_root"]))
    findings = []
    uncertain = []
    motif_families = []
    scene_dropped = []
    scenes: dict[str, Any] | None = None
    deep_dispositions: dict[str, str] = {}
    deep_motif_attributions: dict[str, set[str] | None] = {}
    for row in checkpoint["screen"]["bundles"]:
        if row["status"] != "accepted":
            continue
        bundle = _read_json(Path(row["path"]))
        motifs = _screen_motif_map(bundle)
        if not motifs:
            continue
        result = _read_json(Path(row["result_path"]))
        declines = _result_declines(result)
        for review in result["motif_reviews"]:
            motif = motifs[review["id"]]
            variant_ids = [
                variant["id"] for variant in motif["variants"]
                if variant["id"] not in declines
            ]
            motif_families.append({
                "id": review["id"],
                **({"part_of": motif["part_of"]} if motif.get("part_of") else {}),
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": len(variant_ids),
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
                "screen_review": {
                    "disposition": review["disposition"],
                    "note": review["note"],
                    "suspect_ids": review["suspect_ids"],
                },
                "_variant_ids": variant_ids,
            })
    for review, _item, row in _latest_deep_reviews(checkpoint).values():
        deep_dispositions[review["id"]] = review["disposition"]
        deep_motif_attributions[review["id"]] = (
            set(review.get("motif_ids") or [])
            if "motif_ids" in review
            else None
        )
        kind = (review.get("source_fix") or {}).get("kind")
        cluster = clusters[review["id"]]
        # A follow-up review that reviewers declined leaves the lines unreviewed.
        places = [
            identity for identity in cluster["identities"]
            if identity not in declined["identities"]
        ]
        if review["disposition"] == "actionable" and kind == "show-text":
            if review["apply_identities"][0] not in declined["identities"]:
                findings.append(_show_text_finding(
                    review, records, task, faces, row, declined
                ))
        elif review["disposition"] == "actionable" and review.get("scene_correction"):
            if scenes is None:
                scenes = _scene_index(manifest)
            finding = _scene_finding(review, row, scenes, declined)
            if "reason" in finding:
                scene_dropped.append(finding)
            else:
                findings.append(finding)
        elif review["disposition"] == "actionable":
            target_ids = [
                identity
                for identity in review.get("apply_identities") or cluster["identities"]
                if identity not in declined["identities"]
            ]
            if not target_ids:
                continue
            findings.append({
                "id": "",
                "cluster_id": review["id"],
                "severity": review["severity"],
                "category": _normalize_category(review.get("category")),
                "family_key": _normalize_family_key(review.get("family_key")),
                "evidence": review["evidence"],
                "source": cluster["source"],
                "current": cluster["live"],
                "correction": review["correction"],
                "target_identities": target_ids,
                "authors": [str(row.get("assigned_to") or "")],
                **(
                    {
                        "source_fix": kind,
                        "allowed_flags": list(SOURCE_FIX_ALLOWED_FLAGS[kind]),
                    }
                    if kind in SOURCE_FIX_ALLOWED_FLAGS else {}
                ),
                **(
                    {"editorial_basis": review["editorial_basis"]}
                    if _normalize_category(review.get("category"))
                    in EDITORIAL_JUDGMENT_CATEGORIES
                    else {}
                ),
            })
        elif review["disposition"] == "uncertain-playtest" and places:
            uncertain.append({
                **review,
                "source": cluster["source"],
                "current": cluster["live"],
                "places": len(places),
            })
    layout = task["layout"]
    sweep_dropped = _add_sweep_findings(findings, checkpoint, records, layout)
    game = _lint_game(root, manifest)
    _add_lint_findings(
        findings,
        _lint_decisions(checkpoint, declined, manifest, layout, game),
        manifest,
        declined,
        layout,
        game,
    )
    findings.sort(key=lambda item: (
        {"critical": 0, "high": 1, "medium": 2}[item["severity"]],
        item["cluster_id"],
        bool(item.get("lint_only")),
    ))
    _number_findings(checkpoint, findings)
    _simulate_apply(findings, records, layout)
    finding_by_cluster = {
        item["cluster_id"]: item for item in findings
        if not item.get("lint_only") and not item.get("sweep_families")
    }
    uncertain_ids = {item["id"] for item in uncertain}
    for motif in motif_families:
        variant_ids = set(motif.pop("_variant_ids"))
        screen_review = motif["screen_review"]
        screen_suspects = set(screen_review["suspect_ids"])
        actionable_variants = sorted(
            cluster_id
            for cluster_id in variant_ids & set(finding_by_cluster)
            if (
                motif["id"] in deep_motif_attributions[cluster_id]
                if deep_motif_attributions.get(cluster_id) is not None
                else (
                    cluster_id in screen_suspects
                    and finding_by_cluster[cluster_id]["category"] == "wordplay"
                )
            )
        )
        uncertain_variants = sorted(
            cluster_id
            for cluster_id in variant_ids & uncertain_ids
            if (
                motif["id"] in deep_motif_attributions[cluster_id]
                if deep_motif_attributions.get(cluster_id) is not None
                else cluster_id in screen_suspects
            )
        )
        finding_ids = [finding_by_cluster[item]["id"] for item in actionable_variants]
        cleared_screen_suspects = sorted(
            item for item in screen_suspects
            if deep_dispositions.get(item) == "clean"
        )
        if actionable_variants:
            motif["disposition"] = "suspect"
            motif["suspect_ids"] = sorted(
                screen_suspects | set(actionable_variants) | set(uncertain_variants)
            )
            motif["note"] = (
                "Deep review superseded the screen receipt: "
                f"{len(actionable_variants)} variant(s) are actionable; "
                f"see {', '.join(finding_ids)}."
            )
        elif uncertain_variants:
            motif["disposition"] = "uncertain-playtest"
            motif["suspect_ids"] = sorted(screen_suspects | set(uncertain_variants))
            motif["note"] = (
                "Deep review superseded the screen receipt: "
                f"{len(uncertain_variants)} variant(s) require playtesting."
            )
        elif screen_suspects and len(cleared_screen_suspects) == len(screen_suspects):
            motif["disposition"] = "preserved"
            motif["suspect_ids"] = []
            motif["note"] = (
                "Deep review cleared every variant suspected by the screen receipt."
            )
        motif["deep_reconciliation"] = {
            "actionable_variant_ids": actionable_variants,
            "uncertain_variant_ids": uncertain_variants,
            "cleared_screen_suspect_ids": cleared_screen_suspects,
            "finding_ids": finding_ids,
        }
    return {
        "schema": FINDINGS_SCHEMA,
        "created_at": _utc_now(),
        "task_sha256": checkpoint["task_sha256"],
        "focus": task["focus"],
        "findings": findings,
        "uncertain_playtests": uncertain,
        "motif_families": sorted(motif_families, key=lambda item: item["id"]),
        # A coverage gap, never a review someone must attest: what reviewers
        # declined and the lines nobody judged.
        "declined": declined["items"],
        "not_reviewed": _not_reviewed(declined, records),
        "sweep_dropped": sweep_dropped,
        "scene_dropped": scene_dropped,
        "not_translated": _not_translated_report(
            _read_json(root / "preflight.json")
        ),
    }


def _number_findings(
    checkpoint: dict[str, Any], findings: list[dict[str, Any]]
) -> None:
    """Give each finding the ID an identical finding had in an earlier draft,
    so editorial verdicts keep applying after a follow-up deep round, or the
    next unused one."""
    ids = checkpoint.setdefault("finding_ids", {})
    used = max((int(value.split("-")[1]) for value in ids.values()), default=0)
    seen: Counter[str] = Counter()
    for finding in findings:
        key = _sha256(_canonical_bytes([
            finding["cluster_id"],
            finding.get("kind") or "",
            bool(finding.get("lint_only")),
            finding.get("sweep_families") or [],
            [
                [change["source"], change["current"], change["correction"]]
                for change in _changes(finding)
            ],
            finding["target_identities"],
            finding.get("parameters"),
        ]))[:24]
        seen[key] += 1
        key = f"{key}:{seen[key]}"
        if key not in ids:
            used += 1
            ids[key] = f"QA-{used:04d}"
        finding["id"] = ids[key]


def _face_names(data_root: Path) -> set[str]:
    """Face images the game's own Show Text headers use."""
    faces: set[str] = set()
    for path in data_root.glob("*.json"):
        if not (path.name.startswith(("Map", "CommonEvents", "Troops"))):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        stack = [document]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                parameters = value.get("parameters")
                if (
                    value.get("code") == 101 and isinstance(parameters, list)
                    and parameters and isinstance(parameters[0], str)
                ):
                    faces.add(parameters[0])
                stack.extend(child for key, child in value.items() if key != "_original")
            elif isinstance(value, list):
                stack.extend(value)
    return faces


def _show_text_finding(
    review: dict[str, Any],
    records: dict[str, dict[str, Any]],
    task: dict[str, Any],
    faces: set[str],
    row: dict[str, Any],
    declined: dict[str, Any],
) -> dict[str, Any]:
    """A Show Text header fix: the face and name of the message's own header."""
    identity = review["apply_identities"][0]
    if identity in declined["identities"]:
        raise QAResultError(f"A Show Text fix targets a declined line: {review['id']}")
    record = records[identity]
    fix = review["source_fix"]
    parts = _decode_pointer(record["source_pointer"])
    list_index = len(parts) - 1 - parts[::-1].index("list")
    document = json.loads(
        (Path(task["data_root"]) / record["file"]).read_text(encoding="utf-8-sig")
    )
    commands = _resolve_parts(document, parts[: list_index + 1])
    owner = int(parts[list_index + 1])
    while commands[owner].get("code") == 401 and owner > 0:
        owner -= 1
    header = commands[owner]
    parameters = header.get("parameters")
    if header.get("code") != 101 or not isinstance(parameters, list) or len(parameters) < 5:
        raise QAResultError(f"No Show Text header owns this message: {review['id']}")
    if fix["face_name"] and fix["face_name"] not in faces:
        raise QAResultError(
            f"The Show Text fix names a face the game never shows: {review['id']}"
        )
    replacement = list(parameters)
    replacement[0], replacement[1], replacement[4] = (
        fix["face_name"], fix["face_index"], fix["name"]
    )
    pointer = "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1")
        for part in [*parts[: list_index + 1], str(owner), "parameters"]
    )
    nameplate = next((
        other["identity"] for other in records.values()
        if other["file"] == record["file"]
        and other["source_pointer"].startswith(pointer.rsplit("/", 1)[0] + "/_original")
    ), "")

    def header_text(values: list) -> str:
        face = f"{values[0]} {values[1]}" if values[0] else "no face"
        return f"{values[4] or '(no name)'} · {face}"

    return {
        "id": "",
        "kind": "show-text",
        "cluster_id": review["id"],
        "severity": review["severity"],
        "category": "speaker",
        "family_key": _normalize_family_key(review.get("family_key")),
        "evidence": review["evidence"],
        "source": record["source"],
        "current": header_text(parameters),
        "correction": header_text(replacement),
        "file": record["file"],
        "pointer": pointer,
        "current_parameters": parameters,
        "parameters": replacement,
        "line_identity": identity,
        "nameplate_identity": nameplate,
        "target_identities": [],
        "authors": [str(row.get("assigned_to") or "")],
    }


def _scene_index(manifest: dict[str, Any]) -> dict[str, Any]:
    """Scenes' records, which scenes are copies of each other, and each
    line's cluster: what a scene correction's finding is made from."""
    records = _scene_records(manifest)
    copies: dict[str, list[str]] = defaultdict(list)
    for scene_id, rows in sorted(records.items()):
        copies[_scene_signature(rows)].append(scene_id)
    return {
        "records": records,
        "copies": {
            scene_id: same for same in copies.values() for scene_id in same
        },
        "clusters": _cluster_by_identity(manifest),
    }


def _scene_finding(
    review: dict[str, Any],
    row: dict[str, Any],
    scenes: dict[str, Any],
    declined: dict[str, Any],
) -> dict[str, Any]:
    """A scene correction as one finding: each line it changes, in that scene
    and in every copy of it. A line reviewers declined since its deep review
    leaves the whole correction out, with the reason."""
    bundle = _read_json(Path(row["path"]))
    shown = bundle["scenes"][review["scene_correction"]["scene"]]
    scene_id = shown["scene_id"]
    ordered = scenes["records"][scene_id]
    copies = scenes["copies"][scene_id]
    positions = {
        record["identity"]: position for position, record in enumerate(ordered)
    }
    lines = []
    for entry in review["scene_correction"]["lines"]:
        record = _scene_line(ordered, entry["command"], entry["current"])
        if record is None:
            raise ValueError(f"Scene {scene_id} no longer matches its deep review")
        position = positions[record["identity"]]
        lines.append({
            "position": position,
            "command": entry["command"],
            "cluster_id": scenes["clusters"][record["identity"]],
            "source": record["source"],
            "current": record["live"],
            "correction": entry["correction"],
            # The same line in every copy of the scene.
            "identities": [
                scenes["records"][other][position]["identity"] for other in copies
            ],
        })
    # In scene order; the position also tells editorial which line it is.
    lines.sort(key=lambda line: line["position"])
    targets = [identity for line in lines for identity in line["identities"]]
    if set(copies) & declined["context_scenes"] or set(targets) & declined["identities"]:
        return {
            "cluster_id": review["id"],
            "scene_id": scene_id,
            "reason": "Reviewers declined part of this scene after its deep review.",
        }
    category = _normalize_category(review.get("category"))
    return {
        "id": "",
        "kind": "scene",
        "cluster_id": review["id"],
        "scene_id": scene_id,
        "severity": review["severity"],
        "category": category,
        "family_key": _normalize_family_key(review.get("family_key")),
        "evidence": review["evidence"],
        "lines": lines,
        "target_identities": targets,
        "authors": [str(row.get("assigned_to") or "")],
        **(
            {"editorial_basis": review["editorial_basis"]}
            if category in EDITORIAL_JUDGMENT_CATEGORIES else {}
        ),
    }


def _changes(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """The text a finding changes, line by line: a scene correction's lines,
    or one correction of every line it targets."""
    if finding.get("kind") == "scene":
        return finding["lines"]
    return [{
        "source": finding["source"],
        "current": finding["current"],
        "correction": finding["correction"],
        "identities": finding["target_identities"],
    }]


def _finding_families(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding["family_key"]:
            members_by_key[finding["family_key"]].append(finding)
    families = []
    for family_key, members in sorted(members_by_key.items()):
        if len(members) < 2:
            continue
        families.append({
            "id": f"QAF-{len(families) + 1:04d}",
            "family_key": family_key,
            "severity": min(
                (item["severity"] for item in members),
                key={"critical": 0, "high": 1, "medium": 2}.__getitem__,
            ),
            "categories": sorted({item["category"] for item in members}),
            "finding_ids": [item["id"] for item in members],
            "affected_occurrences": sum(
                len(item["target_identities"]) for item in members
            ),
        })
    return families


def _needs_editorial(finding: dict[str, Any]) -> bool:
    """Reviewer-written corrections get the editorial pass; group-reviewed
    mechanical fixes only when a conflict names them."""
    return not finding.get("lint_only") and (
        not finding.get("sweep_families")
        or finding["category"] in EDITORIAL_JUDGMENT_CATEGORIES
    )


def _editorial_target(record: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any]:
    """One place an editorial finding changes, with the box it shows in."""
    return {
        "identity": record["identity"],
        "event_code": record.get("event_code"),
        "live_pointers": record["live_pointers"],
        "live_transform": record["live_transform"],
        **({"box": box} if (box := _box(record, layout)) else {}),
    }


def _editorial_items(
    root: Path,
    checkpoint: dict[str, Any],
    findings: list[dict[str, Any]],
    conflicts: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    """One editorial item per finding to confirm, with its nearby game text,
    or a scene correction's whole scene."""
    task = _read_json(root / "task.json")
    manifest = _read_json(root / "inventory.json")
    records, _clusters = _record_maps(manifest)
    scenes = (
        _scene_records(manifest)
        if any(finding.get("kind") == "scene" for finding in findings) else {}
    )
    data_root = Path(task["data_root"])
    nearby: dict[str, list[dict]] = {}
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] == "accepted":
            for item in _read_json(Path(row["path"]))["items"]:
                nearby[item["id"]] = item.get("nearby_commands") or []
    cache: dict[str, Any] = {}
    # Text the game had too little room for, shown again corrected.
    after = _interface_after(root, task, manifest, [
        finding for finding in findings
        if finding["id"] in conflicts or _needs_editorial(finding)
    ])
    items = []
    for finding in findings:
        if finding["id"] not in conflicts and not _needs_editorial(finding):
            continue
        judgment = finding["category"] in EDITORIAL_JUDGMENT_CATEGORIES
        corrected = {"after": after[finding["id"]]} if finding["id"] in after else {}
        if finding.get("kind") == "scene":
            items.append({
                "kind": "editorial",
                "id": finding["id"],
                "ordinal": len(items) + 1,
                "finding": {
                    key: finding[key]
                    for key in (
                        "severity", "category", "family_key", "evidence",
                        "editorial_basis", "kind", "scene_id",
                    )
                    if key in finding
                } | {
                    "lines": [
                        {
                            key: line[key]
                            for key in (
                                "position", "command", "source", "current", "correction",
                            )
                        }
                        for line in finding["lines"]
                    ],
                },
                "occurrences": len(finding["target_identities"]),
                "targets": [{
                    "position": line["position"],
                    **_editorial_target(records[identity], task["layout"]),
                } for line in finding["lines"] for identity in line["identities"]],
                "scene": [{
                    "command": (_scene_position(record) or ("", None))[1],
                    "source": record["source"],
                    "translation": record["live"],
                    **(
                        {"speaker": record["speaker"]["display_name"]}
                        if (record.get("speaker") or {}).get("display_name") else {}
                    ),
                    **(
                        {"event_code": record.get("event_code")}
                        if record.get("event_code") != 401 else {}
                    ),
                } for record in scenes[finding["scene_id"]]],
                **({"conflicts": conflicts[finding["id"]]} if finding["id"] in conflicts else {}),
                **corrected,
                "authors": sorted(set(finding.get("authors") or []) - {""}) if judgment else [],
            })
            continue
        targets = [records[identity] for identity in finding["target_identities"]]
        items.append({
            "kind": "editorial",
            "id": finding["id"],
            "ordinal": len(items) + 1,
            "finding": {
                key: finding[key]
                for key in (
                    "severity", "category", "family_key", "evidence", "source",
                    "current", "correction", "editorial_basis", "sweep_families",
                    "kind", "current_parameters", "parameters", "allowed_flags",
                )
                if key in finding
            },
            "occurrences": len(targets),
            "targets": [
                _editorial_target(record, task["layout"]) for record in targets
            ],
            "nearby_commands": nearby.get(finding["cluster_id"])
            or _nearby_commands(
                data_root,
                targets[0] if targets else records[finding["line_identity"]],
                cache,
            ),
            **({"conflicts": conflicts[finding["id"]]} if finding["id"] in conflicts else {}),
            **corrected,
            # The authors of a judgment correction cannot confirm it.
            "authors": sorted(set(finding.get("authors") or []) - {""}) if judgment else [],
        })
    return items


def _open_editorial_round(
    root: Path,
    checkpoint: dict[str, Any],
    findings: list[dict[str, Any]],
    conflicts: dict[str, list[dict[str, str]]],
) -> bool:
    """Add one editorial round's bundles; False when nothing needs it."""
    items = _editorial_items(root, checkpoint, findings, conflicts)
    if not items:
        return False
    editorial = checkpoint.setdefault(
        "editorial", {"total_items": 0, "accepted_items": 0, "bundles": [], "round": 0}
    )
    editorial["round"] = int(editorial.get("round", 0)) + 1
    first = len(editorial["bundles"]) + 1
    judged = [item for item in items if item["authors"]]
    rest = [item for item in items if not item["authors"]]
    bundles = []
    for group in (judged, rest):
        if group:
            bundles += _bundle_items(
                group,
                stage="editorial",
                char_budget=DEFAULT_DEEP_CHAR_BUDGET,
                item_limit=DEFAULT_DEEP_ITEM_LIMIT,
                first=first + len(bundles),
            )
    rows = _write_bundles(root, bundles)
    for row, bundle in zip(rows, bundles, strict=True):
        row["round"] = editorial["round"]
        row["authors"] = sorted({
            author for item in bundle["items"] for author in item["authors"]
        })
    editorial["bundles"] += rows
    editorial["total_items"] += sum(row["item_count"] for row in rows)
    checkpoint["stage"] = "editorial"
    return True


def _scene_revision(
    lines: list[dict[str, Any]], replacements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """A scene correction's lines after an editorial revision: a line named
    by its command and current text takes its replacement, and one put back
    to its current text is left out."""
    revised = {
        (row["command"], row["current"]): row["replacement"] for row in replacements
    }
    lines = [
        {
            **line,
            "correction": revised.get(
                (line["command"], line["current"]), line["correction"]
            ),
        }
        for line in lines
    ]
    return [line for line in lines if line["correction"] != line["current"]]


def _validate_scene_revision(review: dict[str, Any], item: dict[str, Any]) -> None:
    """Revised lines are lines the correction changes, named by command and
    current text, each passing apply's checks, and at least one line still
    changes."""
    identity = review["id"]
    finding = item["finding"]
    replacements = review.get("replacements")
    if (
        review.get("replacement") is not None
        or not isinstance(replacements, list)
        or not replacements
        or not all(
            isinstance(row, dict)
            and set(row) == {"command", "current", "replacement"}
            and type(row["command"]) is int
            and isinstance(row["current"], str)
            and isinstance(row["replacement"], str)
            and row["replacement"].strip()
            for row in replacements
        )
    ):
        raise QAResultError(
            f"A scene correction is revised with replacements, each "
            f"{{command, current, replacement}}: {identity}"
        )
    lines = {(line["command"], line["current"]): line for line in finding["lines"]}
    named = [(row["command"], row["current"]) for row in replacements]
    if len(set(named)) != len(named):
        raise QAResultError(f"A revision names a line twice: {identity}")
    for command, current in named:
        if (command, current) not in lines:
            raise QAResultError(
                f"Line #{command} with the current text given is not a line of "
                f"{identity}; check the command number and text"
            )
    if not _scene_revision(finding["lines"], replacements):
        raise QAResultError(
            f"A revision leaves every line as it is; withdraw the correction "
            f"instead: {identity}"
        )
    for row in replacements:
        line = lines[(row["command"], row["current"])]
        if row["replacement"] == line["current"]:
            continue
        for target in item["targets"]:
            if target["position"] != line["position"]:
                continue
            problems = correction_problems(
                line["source"], line["current"], row["replacement"],
                target["event_code"], target["live_pointers"], target["live_transform"],
                box=target.get("box"),
            )
            if problems:
                raise QAResultError(
                    f"The revision of line #{row['command']} of {identity} would "
                    "block apply: " + "; ".join(problems)
                )


def _validate_editorial_result(bundle: dict, result: dict, worker: str) -> None:
    if result.get("schema") != EDITORIAL_RESULT_SCHEMA:
        raise QAResultError("Editorial result has the wrong schema")
    declined = _declined_items(bundle, result)
    expected = {
        item["id"]: item for item in bundle["items"] if item["id"] not in declined
    }
    reviews = result.get("reviews")
    if not isinstance(reviews, list) or not all(
        isinstance(review, dict) for review in reviews
    ):
        raise QAResultError("Editorial result reviews must be a list of objects")
    reviewed = [str(review.get("id") or "") for review in reviews]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(expected):
        raise QAResultError("Editorial result must review every assigned finding once")
    for review in reviews:
        identity = review["id"]
        item = expected[identity]
        verdict = review.get("verdict")
        if verdict not in EDITORIAL_VERDICTS:
            raise QAResultError(f"Invalid editorial verdict for {identity}")
        if worker in item["authors"]:
            raise QAResultError(
                f"An independent reviewer must confirm {identity}, not its author"
            )
        note = str(review.get("note") or "").strip()
        if not note and (verdict != "accept" or item.get("conflicts")):
            raise QAResultError(f"Editorial review needs a note for {identity}")
        replacement = review.get("replacement")
        if verdict != "revise":
            if replacement is not None or review.get("replacements") is not None:
                raise QAResultError(f"Only a revision has a replacement: {identity}")
            continue
        finding = item["finding"]
        if finding.get("kind") == "show-text":
            raise QAResultError(
                f"A Show Text fix is accepted or withdrawn, not revised: {identity}"
            )
        if finding.get("kind") == "scene":
            _validate_scene_revision(review, item)
            continue
        if review.get("replacements") is not None:
            raise QAResultError(
                f"Only a scene correction is revised line by line: {identity}"
            )
        if not isinstance(replacement, str) or not replacement.strip():
            raise QAResultError(f"A revision needs its replacement text: {identity}")
        for target in item["targets"]:
            problems = correction_problems(
                finding["source"], finding["current"], replacement,
                target["event_code"], target["live_pointers"], target["live_transform"],
                frozenset(finding.get("allowed_flags") or ()),
                box=target.get("box"),
            )
            if problems:
                raise QAResultError(
                    f"The revision of {identity} would block apply: "
                    + "; ".join(problems)
                )


def _compose_lint(
    findings: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    game: lint.Game,
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply accepted lint fixes on top of final corrections, a scene
    correction's line by line; returns those left out because the combined
    text would block apply."""
    dropped = []
    for finding in findings:
        if finding.get("lint_only"):
            continue
        scene = finding.get("kind") == "scene"
        for change in finding["lines"] if scene else [finding]:
            families = change.get("lint_families")
            if not families:
                continue
            composed = lint.compose(
                change["source"], change["correction"], families, game
            )
            problems = sorted({
                problem
                for identity in (
                    change["identities"] if scene else finding["target_identities"]
                )
                for problem in _record_problems(
                    records[identity], composed, layout,
                    frozenset(finding.get("allowed_flags") or ()),
                )
            })
            if problems:
                dropped.append({
                    "id": finding["id"],
                    **({"command": change["command"]} if scene else {}),
                    "families": families,
                    "problems": problems,
                })
            else:
                change["correction"] = composed
    return dropped


def _supersede(
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A confirmed scene correction replaces other corrections of its lines,
    which editorial saw as conflicts; returns the findings left and which
    reviewer corrections it replaced where."""
    covered = {
        identity: finding["id"]
        for finding in findings if finding.get("kind") == "scene"
        for identity in finding["target_identities"]
    }
    kept, superseded = [], []
    for finding in findings:
        replaced = [
            identity for identity in finding["target_identities"] if identity in covered
        ]
        if finding.get("kind") == "scene" or not replaced:
            kept.append(finding)
            continue
        targets = [
            identity for identity in finding["target_identities"]
            if identity not in covered
        ]
        if targets:
            kept.append({**finding, "target_identities": targets})
        # A lint fix is not lost: it composes into the scene correction's line.
        if not finding.get("lint_only"):
            superseded.append({
                "id": finding["id"],
                "by": sorted({covered[identity] for identity in replaced}),
                "places": len(replaced),
            })
    return kept, superseded


def _complete_editorial(
    root: Path, task: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    """Apply editorial verdicts, then open a round for the findings no
    editorial reviewer has judged, such as a follow-up deep round's, or for
    conflicts, or finish."""
    draft = _read_json(root / "draft-findings.json")
    manifest = _read_json(root / "inventory.json")
    records, clusters = _record_maps(manifest)
    layout = task["layout"]
    game = _lint_game(root, manifest)
    editorial = checkpoint.setdefault(
        "editorial", {"total_items": 0, "accepted_items": 0, "bundles": [], "round": 0}
    )
    # Each finding's verdicts in round order; a later round judged the text
    # the earlier ones left.
    verdicts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    shown: dict[str, dict[str, Any]] = {}
    set_aside: set[str] = set()
    for row in editorial["bundles"]:
        items = _read_json(Path(row["path"]))["items"]
        if row["status"] == "set-aside":
            set_aside |= {item["id"] for item in items}
            continue
        if row["status"] != "accepted":
            continue
        for review in _read_json(Path(row["result_path"]))["reviews"]:
            verdicts[review["id"]].append(
                {**review, "reviewer": row.get("assigned_to") or ""}
            )
        shown.update({item["id"]: item for item in items})
    acks = editorial.setdefault("acks", {})
    for identity, item in shown.items():
        if verdicts[identity] and verdicts[identity][-1]["verdict"] == "accept":
            for conflict in item.get("conflicts") or []:
                if conflict["kind"] == "soft":
                    acks[f"{conflict['key']}:{identity}"] = conflict["signature"]
    final, withdrawn, unverified, remnants = [], [], [], []
    unjudged: set[str] = set()
    for finding in draft["findings"]:
        identity = finding["id"]
        history = verdicts.get(identity) or []
        verdict = history[-1] if history else None
        if identity in set_aside and verdict is None:
            unverified.append({"id": identity, "reason": "declined by editorial reviewers"})
            continue
        if verdict is None and _needs_editorial(finding):
            unjudged.add(identity)
        if verdict and verdict["verdict"] == "withdraw":
            withdrawn.append({
                "id": identity, "note": verdict["note"], "reviewer": verdict["reviewer"],
            })
            if finding.get("lint_families"):
                # The line still gets the mechanical fixes it was given.
                remnants.append({
                    **{key: finding[key] for key in (
                        "cluster_id", "source", "current", "target_identities",
                        "lint_families",
                    )},
                    "id": "",
                    "severity": "medium",
                    "category": "formatting",
                    "family_key": finding["lint_families"][0],
                    "evidence": " ".join(
                        lint.FAMILIES[family]["description"]
                        for family in finding["lint_families"]
                    ),
                    "correction": finding["current"],
                    "lint_only": True,
                })
                final.append(remnants[-1])
            continue
        finding = dict(finding)
        for earlier in history:
            if earlier["verdict"] != "revise":
                continue
            # A later round names only the scene lines it changes again.
            if finding.get("kind") == "scene":
                finding["lines"] = _scene_revision(
                    finding["lines"], earlier["replacements"]
                )
            else:
                finding["correction"] = earlier["replacement"]
        if finding.get("kind") == "scene":
            finding["target_identities"] = [
                target for line in finding["lines"] for target in line["identities"]
            ]
        if verdict:
            finding["editorial"] = {
                "verdict": verdict["verdict"],
                "note": str(verdict.get("note") or ""),
                "reviewer": verdict["reviewer"],
            }
        final.append(finding)
    _number_findings(checkpoint, remnants)
    lint_dropped = []
    for finding in remnants:
        composed = lint.compose(
            finding["source"], finding["current"], finding["lint_families"], game
        )
        problems = sorted({
            problem
            for identity in finding["target_identities"]
            for problem in _record_problems(records[identity], composed, layout)
        })
        if problems:
            lint_dropped.append({
                "id": finding["id"], "families": finding["lint_families"],
                "problems": problems,
            })
        else:
            finding["correction"] = composed
    lint_dropped += _compose_lint(final, records, game, layout)
    final = [
        finding for finding in final
        if any(change["correction"] != change["current"] for change in _changes(finding))
    ]
    conflicts = _consistency_conflicts(
        final, _read_json(root / "context.json"), _decisions(root)
    )
    open_conflicts = {
        identity: [
            conflict for conflict in found
            if conflict["kind"] == "hard"
            or acks.get(f"{conflict['key']}:{identity}") != conflict.get("signature")
        ]
        for identity, found in conflicts.items()
    }
    open_conflicts = {key: value for key, value in open_conflicts.items() if value}
    unjudged &= {finding["id"] for finding in final}
    conflict_rounds = int(editorial.get("conflict_rounds", 0))
    if unjudged or open_conflicts and conflict_rounds < EDITORIAL_CONFLICT_ROUNDS:
        if not unjudged:
            editorial["conflict_rounds"] = conflict_rounds + 1
        _open_editorial_round(
            root,
            checkpoint,
            [
                finding for finding in final
                if finding["id"] in unjudged or finding["id"] in open_conflicts
            ],
            open_conflicts,
        )
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return checkpoint
    for finding in final:
        if finding["id"] in open_conflicts:
            unverified.append({
                "id": finding["id"],
                "reason": "conflicting corrections stayed unresolved: "
                + "; ".join(conflict["message"] for conflict in open_conflicts[finding["id"]]),
            })
    final = [finding for finding in final if finding["id"] not in open_conflicts]
    final, superseded = _supersede(final)
    questions = copy.deepcopy(draft.get("uncertain_playtests") or [])
    _fit_corrections(final, questions, records, clusters, layout)
    _simulate_apply(final, records, layout)
    document = {
        **draft,
        "created_at": _utc_now(),
        "findings": final,
        "uncertain_playtests": questions,
        "finding_families": _finding_families(final),
        "withdrawn": withdrawn,
        "unverified": unverified,
        "superseded": superseded,
        "lint_dropped": lint_dropped,
        "editorial_rounds": int(editorial.get("round", 0)),
        # Plugin files' decisions may have changed the report since the draft.
        "not_translated": _not_translated_report(
            _read_json(root / "preflight.json")
        ),
    }
    findings_path = root / "findings.json"
    checkpoint["stage"] = "complete"
    checkpoint["findings_file"] = str(findings_path)
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    document["coverage"] = status(root)
    _atomic_write_json(findings_path, document)
    return checkpoint


def _finalize_unlocked(
    task_dir: str | Path, skip_declined: bool = False
) -> dict[str, Any]:
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] == "screen":
        raise ValueError("Advance the completed screen stage first")
    if checkpoint["stage"] == "deep":
        state = _advance_unlocked(root, skip_declined)
        if state["stage"] != "ready-finalize":
            # Reviewers check more deep items or the family sweep first.
            return state
        root, task, checkpoint = _load_task(root)
    stage = checkpoint["stage"]
    if stage in {"sweep", "ready-finalize", "editorial"}:
        if stage != "ready-finalize":
            _settle_declined(checkpoint, stage, skip_declined)
        if _follow_up(root, checkpoint):
            return status(root)
        if stage != "editorial":
            # Findings are made, or made again after a follow-up deep round.
            _atomic_write_json(
                root / "draft-findings.json", _draft_document(root, task, checkpoint)
            )
        _complete_editorial(root, task, checkpoint)
    return status(root)


def _follow_up(root: Path, checkpoint: dict[str, Any]) -> bool:
    """Return QA to deep review for observations made after its last deep
    round; a complete task's findings are made again once that round ends."""
    observations = len(checkpoint.get("observations") or [])
    if observations <= int(checkpoint["deep"].get("observed", 0)):
        return False
    if not _issue_deep(root, checkpoint, final=True):
        return False
    checkpoint["stage"] = "deep"
    checkpoint["findings_file"] = ""
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    # Nothing applies findings of a task in review, and later tasks build on
    # its reviews only once it is complete again; the app's polls read these
    # files, and Windows can't remove a file while one does.
    for name in ("findings.json", REVIEWED_FILE):
        if (root / name).is_file():
            unlink_with_retry(root / name)
    return True


def _decisions(root: Path) -> list[dict[str, Any]]:
    """The decision log's current entries, the latest one per key."""
    path = root / "decisions.json"
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for entry in _read_json(path).get("decisions") or []:
        latest[entry["key"]] = entry
    return sorted(latest.values(), key=lambda entry: entry["key"])


def record_decision(
    task_dir: str | Path,
    key: str,
    choice: str,
    worker: str,
    source: str = "",
    translation: str = "",
) -> list[dict[str, Any]]:
    """Record a choice every reviewer follows, such as narration tense or a
    quoted label; with a source and translation it is also checked."""
    root = Path(task_dir).expanduser().resolve()
    key, choice = str(key).strip(), str(choice).strip()
    if not 0 < len(key) <= 120 or not 0 < len(choice) <= 500 or "\n" in key + choice:
        raise ValueError("A decision needs a one-line key and choice")
    if bool(source) != bool(translation):
        raise ValueError("A checked decision needs both its source and translation")
    with _task_lock(root):
        _load_task(root)
        path = root / "decisions.json"
        document = (
            _read_json(path) if path.is_file()
            else {"schema": "rpgmaker-qa-decisions-v1", "decisions": []}
        )
        document["decisions"].append({
            "key": key,
            "choice": choice,
            "worker": str(worker or ""),
            "at": _utc_now(),
            **({"source": source, "translation": translation} if source else {}),
        })
        _atomic_write_json(path, document)
    return _decisions(root)


def finalize(task_dir: str | Path, skip_declined: bool = False) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        return _finalize_unlocked(root, skip_declined)


def _set_pointer(document: Any, pointer: str, value: str) -> None:
    parts = _decode_pointer(pointer)
    if not parts:
        raise ValueError("Refusing to replace an entire JSON document")
    parent = _resolve_parts(document, parts[:-1])
    key = parts[-1]
    if isinstance(parent, list):
        parent[int(key)] = value
    else:
        parent[key] = value


def correction_map(
    task_dir: str | Path,
    approved_finding_ids: Iterable[str],
    chosen_proposals: Iterable[str] = (),
    *,
    undo: bool = False,
) -> dict[str, Any]:
    """The checksummed operations that apply the approved findings, with the
    open questions whose proposal the user chose, or with `undo` put their
    lines back.

    It is built in memory for the app's apply, which runs it on disposable
    copies and publishes the result; no QA command writes the game itself.
    """
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA review must be complete before its findings are applied")
    findings_doc = _read_json(root / "findings.json")
    approved = set(approved_finding_ids)
    selected = [item for item in findings_doc["findings"] if item["id"] in approved]
    if {item["id"] for item in selected} != approved:
        raise ValueError("One or more approved finding IDs do not exist")
    manifest_clusters = {
        cluster["representative"]: cluster
        for cluster in _read_json(root / "inventory.json")["clusters"]
    }
    questions = {
        row["id"]: row for row in findings_doc.get("uncertain_playtests") or []
    }
    for question_id in chosen_proposals:
        question = questions.get(question_id)
        if not question or not question.get("correction"):
            raise ValueError("A chosen proposal no longer exists")
        cluster = manifest_clusters[question_id]
        selected.append({
            "id": question_id,
            "source": question["source"],
            "current": question["current"],
            "correction": question["correction"],
            "target_identities": [
                identity for identity in cluster["identities"]
                if identity not in {
                    row["identity"] for row in findings_doc.get("not_reviewed") or []
                }
            ],
        })
    manifest = _read_json(root / "inventory.json")
    records = {record["identity"]: record for record in manifest["records"]}
    operations = []
    targets: dict[tuple[str, tuple[str, ...]], str] = {}
    for finding in selected:
        if finding.get("kind") == "show-text":
            operations.append({
                "finding_id": finding["id"],
                "kind": "show-text",
                "identity": finding["nameplate_identity"],
                "file": finding["file"],
                "pointer": finding["pointer"],
                "expected": finding["current_parameters"],
                "replacement": finding["parameters"],
                # Narration's header loses its name on purpose.
                "allowed_flags": ["empty-live"] if finding["parameters"][4] == "" else [],
            })
            continue
        # A scene correction's lines apply and undo together as one finding.
        for change in _changes(finding):
            for identity in change["identities"]:
                record = records[identity]
                target = (record["file"], tuple(record["live_pointers"]))
                previous = targets.get(target)
                if previous is not None and previous != change["correction"]:
                    raise ValueError(
                        f"Approved findings propose conflicting corrections for {identity}"
                    )
                if previous is not None:
                    continue
                targets[target] = change["correction"]
                # A correction that reaches only one kind of script string is
                # stored escaped, which escaping again keeps; one that reaches
                # other text too is escaped here for each script string.
                replacement = _script_text(
                    change["correction"], record["live_transform"]
                )
                # A message's rows are spread over the commands that hold
                # them; the replacement reads as it will once written, so
                # undoing it finds it there.
                message = len(record["live_pointers"]) > 1 and _message_code(
                    record.get("event_code")
                )
                if message:
                    replacement = "\n".join(
                        rewrap.spread(replacement, len(record["live_pointers"]))
                    )
                operations.append({
                    "finding_id": finding["id"],
                    "identity": identity,
                    "file": record["file"],
                    "live_pointers": record["live_pointers"],
                    "live_transform": record["live_transform"],
                    "expected": record["live"],
                    "replacement": replacement,
                    "allowed_flags": list(finding.get("allowed_flags") or []),
                    **({"message": True} if message else {}),
                })
    if undo:
        # Each operation puts back the text it replaced.
        for operation in operations:
            operation["expected"], operation["replacement"] = (
                operation["replacement"], operation["expected"]
            )
            operation["allowed_flags"] = []
    document = {
        "schema": CORRECTION_MAP_SCHEMA,
        "created_at": _utc_now(),
        "manifest_sha256": task["manifest_sha256"],
        "approved_finding_ids": sorted(approved | set(chosen_proposals)),
        **({"mode": "undo"} if undo else {}),
        "operations": operations,
    }
    document["content_sha256"] = _sha256(_canonical_bytes(document))
    return document


def _operation_writes(document: Any, operation: dict) -> list[tuple[str, Any]]:
    """The pointers one operation writes, after checking it still finds the
    value it was approved against."""
    if operation.get("kind") == "show-text":
        if resolve_pointer(document, operation["pointer"]) != operation["expected"]:
            raise ValueError(
                f"Expected Show Text header changed for {operation['finding_id']}; rebuild QA"
            )
        return [(operation["pointer"], operation["replacement"])]
    values = _operation_values(document, operation)
    current = "\n".join(values)
    if operation["live_transform"] in QUOTED_TRANSFORMS:
        match = _QUOTED_VALUE_RE.search(current)
        current = match.group(2) if match else current
    if current != operation["expected"]:
        raise ValueError(
            f"Expected value changed for {operation['identity']}; rebuild QA"
        )
    return list(zip(operation["live_pointers"], _operation_replacements(values, operation)))


def _operation_values(document: Any, operation: dict) -> list[str]:
    return [resolve_pointer(document, pointer) for pointer in operation["live_pointers"]]


def _operation_replacements(values: list[str], operation: dict) -> list[str]:
    replacement = operation["replacement"]
    transform = operation["live_transform"]
    if transform in QUOTED_TRANSFORMS:
        if len(values) != 1:
            raise ValueError("Quoted-string operation has multiple live pointers")
        match = _QUOTED_VALUE_RE.search(values[0])
        if not match:
            raise ValueError("Quoted-string live value no longer contains a quoted value")
        return [values[0][: match.start(2)] + replacement + values[0][match.end(2) :]]
    if len(values) == 1:
        return [replacement]
    if operation.get("message"):
        return rewrap.spread(replacement, len(values))
    lines = replacement.split("\n")
    if len(lines) != len(values):
        raise ValueError(
            f"Replacement for {operation['identity']} must have {len(values)} lines"
        )
    return lines


def _has_suspicious_length_ratio(source: Any, live: Any) -> bool:
    source_text = str(source or "")
    live_text = str(live or "")
    if len(source_text) < 8 or not live_text:
        return False
    ratio = len(live_text) / len(source_text)
    return ratio < 0.35 or ratio > 3.0


def _validate_correction_map(
    correction_map: dict[str, Any], task: dict[str, Any]
) -> None:
    if correction_map.get("schema") != CORRECTION_MAP_SCHEMA:
        raise ValueError("Correction map has an unsupported schema")
    checksum_value = dict(correction_map)
    claimed_checksum = checksum_value.pop("content_sha256", "")
    if claimed_checksum != _sha256(_canonical_bytes(checksum_value)):
        raise ValueError("Correction map checksum does not match its contents")
    if correction_map.get("manifest_sha256") != task["manifest_sha256"]:
        raise ValueError("Correction map does not match this QA inventory")


def _dry_run_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    report_name: str,
) -> dict[str, Any]:
    _validate_correction_map(correction_map, task)

    data_root = Path(task["data_root"]).resolve()
    inventory_records = {
        item["identity"]: item
        for item in _read_json(root / "inventory.json").get("records") or []
    }
    documents: dict[str, Any] = {}
    preview = []
    warnings = []
    pointer_targets: dict[tuple[str, str], str] = {}
    for operation in correction_map.get("operations") or []:
        filename = str(operation.get("file") or "")
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        if filename not in documents:
            documents[filename] = json.loads(path.read_text(encoding="utf-8-sig"))
        for pointer, replacement in _operation_writes(documents[filename], operation):
            target = (filename, pointer)
            previous = pointer_targets.get(target)
            overlapping = any(
                other_file == filename and (
                    other.startswith(pointer + "/") or pointer.startswith(other + "/")
                )
                for other_file, other in pointer_targets
            )
            if overlapping or previous is not None and previous != replacement:
                raise ValueError(f"Conflicting approved corrections target {filename}#{pointer}")
            pointer_targets[target] = replacement
        preview.append({
            "finding_id": operation["finding_id"],
            "identity": operation["identity"],
            "file": filename,
            "live_pointers": operation.get("live_pointers") or [operation["pointer"]],
            "expected": operation["expected"],
            "replacement": operation["replacement"],
        })
        if operation.get("kind") == "show-text":
            continue
        baseline = inventory_records.get(operation["identity"]) or {}
        baseline_flags = set(
            (baseline.get("mechanical") or {}).get("flags") or []
        )
        if (
            "suspicious-length-ratio" not in baseline_flags
            and _has_suspicious_length_ratio(
                baseline.get("source"), operation["replacement"]
            )
        ):
            warnings.append(
                "approved correction projects a non-blocking mechanical flag: "
                f"{operation['identity']} suspicious-length-ratio"
            )
    report = {
        "schema": "rpgmaker-qa-correction-dry-run-v1",
        "created_at": _utc_now(),
        "valid": True,
        "operation_count": len(preview),
        "file_count": len(documents),
        "warnings": warnings,
        "operations": preview,
    }
    _atomic_write_json(root / report_name, report)
    return report


def _render_json_like(raw: bytes, document: Any) -> bytes:
    """Render JSON using the file's existing BOM, indentation, and final newline."""
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = raw.decode("utf-8-sig")
    indent_match = re.search(r"\n([ \t]+)[\"\[\]{}]", decoded)
    indent: int | str | None
    if indent_match:
        token = indent_match.group(1)
        indent = token if "\t" in token else len(token)
    else:
        indent = None
    rendered = json.dumps(
        document,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )
    if decoded.endswith("\r\n"):
        rendered = rendered.replace("\n", "\r\n") + "\r\n"
    elif decoded.endswith("\n"):
        rendered += "\n"
    payload = rendered.encode("utf-8")
    return (b"\xef\xbb\xbf" + payload) if has_bom else payload


def _apply_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    before: dict[str, Any],
    *,
    dry_run_name: str,
    regression_name: str,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Apply one validated map atomically and roll back on regression failure."""
    _dry_run_loaded_correction_map(root, task, correction_map, dry_run_name)
    data_root = Path(task["data_root"]).resolve()
    by_file: dict[str, list[dict]] = defaultdict(list)
    for operation in correction_map["operations"]:
        by_file[operation["file"]].append(operation)
    originals: dict[Path, bytes] = {}
    rendered: dict[Path, bytes] = {}
    applied = 0
    for filename, operations in sorted(by_file.items()):
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        raw = path.read_bytes()
        originals[path] = raw
        document = json.loads(raw.decode("utf-8-sig"))
        for operation in operations:
            for pointer, replacement in _operation_writes(document, operation):
                _set_pointer(document, pointer, replacement)
            applied += 1
        rendered[path] = _render_json_like(raw, document)
    temporaries: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, raw in rendered.items():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".qa.tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            json.loads(temporary.read_text(encoding="utf-8-sig"))
            temporaries[path] = temporary
        for path, temporary in temporaries.items():
            temporary.replace(path)
            replaced.append(path)
    except Exception:
        for path in replaced:
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(originals[path])
            rollback.replace(path)
        raise
    finally:
        for temporary in temporaries.values():
            temporary.unlink(missing_ok=True)
    regression = _regression_check_loaded(
        task,
        before,
        correction_map,
        nonblocking_introduced_flags=nonblocking_introduced_flags,
    )
    if not regression["valid"]:
        for path, raw in originals.items():
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(raw)
            rollback.replace(path)
        regression["rolled_back"] = True
        _atomic_write_json(root / regression_name, regression)
        raise ValueError("QA regression failed; all game-file changes were rolled back")
    regression["applied_operations"] = applied
    _atomic_write_json(root / regression_name, regression)
    return regression


def _regression_check_loaded(
    task: dict[str, Any],
    before: dict[str, Any],
    corrections: dict[str, Any] | None,
    *,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    after = build_manifest(task["data_root"], task["focus"])
    validation = verify_manifest(task["data_root"], after)
    before_records = {item["identity"]: item for item in before["records"]}
    after_records = {item["identity"]: item for item in after["records"]}
    errors = list(validation.get("errors") or [])
    warnings = []
    if set(before_records) != set(after_records):
        errors.append("source identity coverage changed after corrections")
    for identity in sorted(set(before_records) & set(after_records)):
        if before_records[identity]["source_sha256"] != after_records[identity]["source_sha256"]:
            errors.append(f"preserved source changed: {identity}")
    if corrections is not None:
        for operation in corrections.get("operations") or []:
            header = operation.get("kind") == "show-text"
            if header and not operation["identity"]:
                # A header without a translated name has no record to check.
                continue
            record = after_records.get(operation["identity"])
            expected = operation["replacement"][4] if header else operation["replacement"]
            if record is None or record["live"] != expected:
                errors.append(f"approved correction is missing: {operation['identity']}")
                continue
            before_record = before_records.get(operation["identity"], {})
            before_flags = set(
                before_record.get("mechanical", {}).get("flags") or []
            )
            after_flags = set(record.get("mechanical", {}).get("flags") or [])
            introduced_flags = _disallowed_flags(
                after_flags - before_flags, operation.get("allowed_flags") or (),
                record["source"], record["live"],
            )
            warning_flags = sorted(
                introduced_flags & nonblocking_introduced_flags
            )
            blocking_flags = sorted(
                introduced_flags - nonblocking_introduced_flags
            )
            if warning_flags:
                warnings.append(
                    "approved correction introduced non-blocking mechanical flags: "
                    f"{operation['identity']} " + ", ".join(warning_flags)
                )
            if blocking_flags:
                errors.append(
                    "approved correction introduced mechanical flags: "
                    f"{operation['identity']} " + ", ".join(blocking_flags)
                )
    return {
        "schema": REGRESSION_SCHEMA,
        "created_at": _utc_now(),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "before_manifest_sha256": before["content_sha256"],
        "after_manifest_sha256": after["content_sha256"],
        "records_checked": len(after_records),
    }


def find_latest_task(
    output_root: str | Path, game_root: str | Path, focus: str
) -> Path | None:
    base = Path(output_root).expanduser().resolve() / _slug(Path(game_root).name) / focus
    if not base.is_dir():
        return None
    tasks = [path for path in base.iterdir() if (path / "task.json").is_file()]
    return max(tasks, key=lambda path: path.stat().st_mtime) if tasks else None


