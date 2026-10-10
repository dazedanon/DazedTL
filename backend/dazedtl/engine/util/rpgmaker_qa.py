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
import os
import re
import shlex
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from util.paths import (
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
)
from util.rpgmaker_qa_manifest import (
    _mechanical_evidence,
    build_manifest,
    resolve_pointer,
    write_manifest,
)
from util.rpgmaker_qa_verify import verify_manifest
from util import rpgmaker_qa_lint as lint
from util.rpgmaker_qa_preflight import preflight
from util.reference_games import reference_context
from util.skills import rpgmaker_qa_skill_parts


TASK_SCHEMA = "rpgmaker-qa-task-v3"
CHECKPOINT_SCHEMA = "rpgmaker-qa-checkpoint-v3"
BUNDLE_SCHEMA = "rpgmaker-qa-bundle-v3"
SCREEN_RESULT_SCHEMA = "rpgmaker-qa-screen-result-v2"
DEEP_RESULT_SCHEMA = "rpgmaker-qa-deep-result-v3"
SWEEP_RESULT_SCHEMA = "rpgmaker-qa-sweep-result-v1"
# Stages whose bundles reviewers claim, in order.
REVIEW_STAGES = ("screen", "deep", "sweep", "editorial")
FINDINGS_SCHEMA = "rpgmaker-qa-findings-v5"
CORRECTION_MAP_SCHEMA = "rpgmaker-qa-correction-map-v1"
REGRESSION_SCHEMA = "rpgmaker-qa-regression-v1"
EDITORIAL_RESULT_SCHEMA = "rpgmaker-qa-editorial-result-v1"
EDITORIAL_VERDICTS = frozenset({"accept", "revise", "withdraw"})
# Editorial rounds for conflicting corrections before they are left unverified.
EDITORIAL_ROUND_LIMIT = 4

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
# Workers seen this recently count toward the estimate.
ACTIVE_WORKER_SECONDS = 30 * 60
# Seconds one review target takes, by stage, until the task has measured it.
DEFAULT_SECONDS_PER_ITEM = {"screen": 5.0, "deep": 60.0, "sweep": 4.0, "editorial": 30.0}

SCREEN_VERDICTS = frozenset({"suspect", "needs-context"})
MOTIF_DISPOSITIONS = frozenset({"preserved", "suspect", "uncertain-playtest"})
DEEP_DISPOSITIONS = frozenset({
    "clean", "actionable", "uncertain-playtest", "declined",
})
# A reviewer that will not review an item says why in one line, without game text.
DECLINE_REASON_LIMIT = 300
# Distinct reviewers that must decline an item before it is set aside unreviewed.
DECLINES_TO_SET_ASIDE = 2
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
# A Show Text window shows four rows; a correction may not need more than the
# current text already uses.
MESSAGE_WINDOW_LINES = 4
# Fixes for slips in the Japanese source itself: the Show Text header's face
# and name, or a database field's number that its own entry contradicts.
SOURCE_FIX_KINDS = frozenset({"show-text", "database-numbers"})
# Every module whose rules shape bundles, flags or findings.
_ENGINE_SOURCES = (
    "rpgmaker_qa.py", "rpgmaker_qa_manifest.py", "rpgmaker_qa_lint.py",
    "rpgmaker_qa_preflight.py",
)
# Lint proposals per review item, so a decline sets aside few of them.
LINT_ITEM_LIMIT = 60

QA_POLICY_VERSION = "rpgmaker-qa-scene-motif-editorial-reference-v13"
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
_GLOSSARY_PAIR_RE = re.compile(r"^(.+?)\s+\((.+)\)\s*$")
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
        expected = canonical.get(_fixed_source_key(finding.get("source"))) or set()
        if len(expected) == 1 and _fixed_translation_key(
            finding.get("correction")
        ) not in expected:
            conflicts[finding["id"]].append({
                "kind": "hard",
                "key": "quirk:" + _fixed_source_key(finding["source"]),
                "message": "The translation quirks fix this text as "
                f"{next(iter(expected))!r}.",
            })
        for decision in decisions:
            if (
                decision.get("source")
                and decision["source"] in str(finding["source"])
                and decision.get("translation") not in str(finding["correction"])
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
        source_labels = _JAPANESE_FIELD_LABEL_RE.findall(str(finding["source"]))
        correction_labels = _ENGLISH_FIELD_LABEL_RE.findall(str(finding["correction"]))
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
    # may keep different corrections.
    by_text: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
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
    return dict(conflicts)


def _simulate_apply(
    findings: list[dict[str, Any]], records: dict[str, dict[str, Any]]
) -> None:
    """Refuse findings whose corrections the post-apply regression would reject."""
    problems = []
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        for identity in finding["target_identities"]:
            record = records[identity]
            found = correction_problems(
                record["source"],
                record["live"],
                finding["correction"],
                record.get("event_code"),
                record["live_pointers"],
                record["live_transform"],
                frozenset(finding.get("allowed_flags") or ()),
            )
            if found:
                problems.append(f"{finding['id']} at {identity}: " + "; ".join(found))
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


def correction_problems(
    source: str,
    live: str,
    correction: str,
    event_code: int | None,
    live_pointers: list[str],
    live_transform: str,
    allowed: frozenset[str] = frozenset(),
) -> list[str]:
    """Why applying one correction would fail or trip the post-apply regression.

    This simulates the apply step for one target: the line structure its
    pointers need and the mechanical flags the regression treats as blocking.
    """
    problems = []
    if correction == live:
        problems.append("the correction matches the current text")
    lines = correction.split("\n")
    current_lines = live.split("\n")
    if live_transform == "quoted-string":
        # The text sits between quote marks in a script parameter, so a new
        # kind of quote mark could end the string early.
        if any(mark in correction and mark not in live for mark in "'\"`"):
            problems.append("adds a quote mark to a script string")
    elif len(live_pointers) > 1 and len(lines) != len(live_pointers):
        problems.append(
            f"needs {len(live_pointers)} lines like the current text, "
            f"not {len(lines)}"
        )
    elif (
        event_code == 401
        and len(lines) > max(len(current_lines), MESSAGE_WINDOW_LINES)
    ):
        problems.append(
            f"needs {len(lines)} lines; a message window shows "
            f"{MESSAGE_WINDOW_LINES}"
        )
    elif event_code in {101, 102} and "\n" in correction:
        problems.append("a name or choice cannot contain a line break")
    before = set(_mechanical_evidence(source, live, event_code)["flags"])
    after = set(_mechanical_evidence(source, correction, event_code)["flags"])
    introduced = sorted(
        after - before - APPROVED_NONBLOCKING_MECHANICAL_FLAGS - allowed
    )
    if introduced:
        problems.append("introduces " + ", ".join(introduced))
    return problems


def _engine_fingerprint() -> str:
    """Fingerprint every rule/configuration that affects reusable QA evidence."""
    contract = {
        "policy": QA_POLICY_VERSION,
        "engine_source_sha256": _sha256(b"".join(
            (Path(__file__).with_name(name)).read_bytes() for name in _ENGINE_SOURCES
        )),
        "schemas": {
            "task": TASK_SCHEMA,
            "checkpoint": CHECKPOINT_SCHEMA,
            "bundle": BUNDLE_SCHEMA,
            "screen_result": SCREEN_RESULT_SCHEMA,
            "deep_result": DEEP_RESULT_SCHEMA,
            "findings": FINDINGS_SCHEMA,
        },
        "bundle_limits": {
            "screen_chars": DEFAULT_SCREEN_CHAR_BUDGET,
            "screen_items": DEFAULT_SCREEN_ITEM_LIMIT,
            "deep_chars": DEFAULT_DEEP_CHAR_BUDGET,
            "deep_items": DEFAULT_DEEP_ITEM_LIMIT,
        },
        "forced_deep_mechanical_flags": sorted(FORCED_DEEP_MECHANICAL_FLAGS),
        "forced_deep_event_codes": sorted(FORCED_DEEP_EVENT_CODES),
        "risk_cues": {
            label: pattern.pattern for label, pattern in sorted(_JP_RISK_CUES.items())
        },
        # The policy the README and briefs are made from.
        "policy_sha256": _sha256("\n".join(
            "\n".join(rpgmaker_qa_skill_parts(focus))
            for focus in ("database", "risky-codes", "dialogue", "release")
        )),
        "screen_inconsistent_source_evidence": True,
    }
    return _sha256(_canonical_bytes(contract))


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
    value = json.loads(path.read_text(encoding="utf-8"))
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
def _task_lock(task_dir: Path):
    """Serialize cross-process checkpoint mutations for parallel helpers."""
    lock_path = task_dir / ".checkpoint.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
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


def _glossary_pairs(text: str) -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _GLOSSARY_PAIR_RE.match(line)
        if match:
            source, target = match.group(1).strip(), match.group(2).strip()
            if source and target:
                pairs[source] = target
    return sorted(pairs.items(), key=lambda item: (-len(item[0]), item[0]))


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
    cluster: dict[str, Any], records: dict[str, dict], glossary: list[tuple[str, str]]
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
    hits = [[src, dst] for src, dst in glossary if src in source]
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
    glossary = _glossary_pairs(context["glossary"]["text"])
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


def _scene_items(
    manifest: dict[str, Any],
    compact: dict[str, dict[str, Any]],
    lint_fixes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, str]]]:
    """Build indivisible scenes that cover each dialogue cluster exactly once."""
    cluster_ids = _cluster_by_identity(manifest)
    scenes: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for record in manifest["records"]:
        if record.get("classification") != "dialogue":
            continue
        position = _scene_position(record)
        if position is None:
            continue
        scene_id, command_index = position
        scenes[scene_id].append((command_index, record))

    equivalent: dict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for scene_id, positioned in scenes.items():
        ordered = [
            record for _index, record in sorted(
                positioned, key=lambda item: (item[0], item[1]["source_pointer"])
            )
        ]
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

    uncovered = set().union(*(group["clusters"] for group in groups)) if groups else set()
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
        signature = group["signature"]
        target_clusters = set(group["targets"])
        emitted_clusters: set[str] = set()
        lines = []
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
            if cluster_id in target_clusters and cluster_id not in emitted_clusters:
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
                context_expansion = sorted(
                    group["context_expansion"].get(cluster_id, set())
                )
                if context_expansion:
                    line["context_expansion"] = context_expansion
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
        if emitted_clusters != target_clusters:
            raise ValueError("Scene target assignment lost a dialogue cluster")
        items.append({
            "kind": "scene",
            "id": "scene-" + group["signature"][:20],
            "scene_id": group["scene_id"],
            **(
                {"scene_copies": [copy_id for copy_id, _records in group["copies"]]}
                if len(group["copies"]) > 1 else {}
            ),
            "scene_occurrences": len(group["copies"]),
            "target_count": len(target_clusters),
            "line_count": len(lines),
            "lines": lines,
        })
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
    data_root: Path,
) -> list[dict[str, Any]]:
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
        variants = []
        for cluster in matching:
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
            "target_count": 1,
            "variant_count": len(variants),
            "variants": variants,
            "exclusive_bundle": True,
        })
    return items


def _lint_items(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Each lint family's proposals as review items, and every line's fixes.

    A proposal the post-apply regression would reject is left out. Proposals
    are grouped by scene and split into small items, so a declined item sets
    aside only that part of a family.
    """
    records, _clusters = _record_maps(manifest)
    titles = lint.title_map(manifest["clusters"])
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fixes: dict[str, dict[str, Any]] = {}
    for cluster in manifest["clusters"]:
        members = [records[identity] for identity in cluster["identities"]]
        found = {
            family: proposed
            for family, proposed in lint.proposals(
                cluster["source"], cluster["live"], titles
            ).items()
            if not any(
                correction_problems(
                    record["source"], record["live"], proposed,
                    record.get("event_code"), record["live_pointers"],
                    record["live_transform"],
                )
                for record in members
            )
        }
        if not found:
            continue
        cluster_id = cluster["representative"]
        fixes[cluster_id] = {
            "families": sorted(found, key=lint.ORDER.index),
            "proposed": lint.compose(cluster["source"], cluster["live"], found, titles),
        }
        position = _scene_position(members[0])
        speaker = str((members[0].get("speaker") or {}).get("display_name") or "")
        for family, proposed in found.items():
            by_family[family].append({
                "id": "lint-" + _sha256(f"{family}\0{cluster_id}")[:16],
                "cluster_id": cluster_id,
                "occurrences": len(members),
                "scene": position[0] if position else members[0]["file"],
                **({"speaker": speaker} if speaker else {}),
                "source": cluster["source"],
                "current": cluster["live"],
                "proposed": proposed,
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
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    compact_items = _compact_items(manifest, context)
    compact = {item["id"]: item for item in compact_items}
    items: list[dict[str, Any]] = []
    covered_dialogue: set[str] = set()
    screen_index: dict[str, dict[str, str]] = {}
    if manifest["focus"] in {"dialogue", "release"}:
        scenes, covered_dialogue, screen_index = _scene_items(
            manifest, compact, lint_fixes
        )
        items.extend(scenes)

    clusters = {
        cluster["representative"]: cluster for cluster in manifest["clusters"]
    }
    member_records = {
        record["identity"]: record for record in manifest["records"]
    }
    for item in compact_items:
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
        items.extend(_motif_items(manifest, context, compact, data_root))

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
    first: int = 1,
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
        _make_bundle(stage, f"{stage}-{index:04d}", group)
        for index, group in enumerate(groups, start=first)
    ]


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
    item["target_shapes"] = [
        dict(shape) for shape in sorted({
            (
                ("event_code", locator.get("event_code")),
                ("pointers", len(locator["live_pointers"])),
                ("transform", locator.get("live_transform", "identity")),
            )
            for locator in locators
        }, key=lambda shape: json.dumps(shape))
    ]
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
        for key in ("speaker", "event_code"):
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


def _split_declined(
    root: Path,
    checkpoint: dict[str, Any],
    stage: str,
    row: dict[str, Any],
    bundle: dict[str, Any],
    reasons: dict[str, str],
) -> int:
    """Move declined items into their own bundle for another reviewer.

    Returns how many targets moved. After enough distinct reviewers declined
    the same items, they are set aside unreviewed instead.
    """
    items = [item for item in bundle["items"] if item["id"] in reasons]
    worker = str(row.get("assigned_to") or "") or "unnamed reviewer"
    declined_by = sorted({*(row.get("declined_by") or []), worker})
    origin = row.get("origin") or row["id"]
    number = 1 + sum(
        other.get("origin") == origin for other in checkpoint[stage]["bundles"]
    )
    split = _make_bundle(stage, f"{origin}-d{number}", items)
    path = root / "bundles" / stage / f"{split['bundle_id']}.json"
    _atomic_write_json(path, split)
    checkpoint[stage]["bundles"].append({
        "id": split["bundle_id"],
        "path": str(path),
        "sha256": split["content_sha256"],
        "item_count": split["item_count"],
        "status": (
            "set-aside" if len(declined_by) >= DECLINES_TO_SET_ASIDE else "pending"
        ),
        "assigned_to": "",
        "result_path": "",
        "origin": origin,
        "declined_by": declined_by,
        "declines": [
            *(row.get("declines") or []),
            {"worker": worker, "reasons": reasons},
        ],
    })
    return split["item_count"]


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


QA_ROLES = ("screen", "deep", "group", "editorial")
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


def brief(task_dir: str | Path, role: str) -> str:
    """One reviewer's fixed brief: the policy, its role and the commands."""
    if role not in QA_ROLES:
        raise ValueError("Choose a role: " + ", ".join(QA_ROLES))
    root, task, _checkpoint = _load_task(task_dir)
    _intro, sections, focus = _skill_sections(task["focus"])
    title = {"screen": "Screen reviewer", "deep": "Deep reviewer",
             "group": "Group reviewer", "editorial": "Editorial reviewer"}[role]
    parts = [focus] + [
        f"## {name}\n\n{sections[name]}"
        for name in ("Policy", title, "Commands", "Result formats")
    ]
    return _fill("\n\n".join(parts) + "\n", _skill_values(root, task))


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


def prepare_task(
    game_root: str | Path,
    data_root: str | Path,
    focus: str,
    output_root: str | Path,
    *,
    screen_char_budget: int = DEFAULT_SCREEN_CHAR_BUDGET,
    screen_item_limit: int = DEFAULT_SCREEN_ITEM_LIMIT,
) -> tuple[Path, dict[str, Any]]:
    """Create or reuse one immutable QA task and its exhaustive screen bundles."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if not game.is_dir() or not data.is_dir() or game not in data.parents:
        raise ValueError("The QA data folder must be inside the selected game folder")
    storage = _safe_task_root(output_root, game)
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
    task_key = _sha256(
        f"{TASK_SCHEMA}\0{engine_fingerprint}\0{focus}\0"
        f"{manifest['content_sha256']}\0{context['content_sha256']}\0"
        f"{_sha256(_canonical_bytes(screen_configuration))}"
    )[:16]
    task_parent = storage / _slug(game.name) / focus
    task_parent.mkdir(parents=True, exist_ok=True)
    task_dir = task_parent / task_key
    with _task_lock(task_parent):
        existing = task_dir / "task.json"
        if existing.is_file():
            task = _read_json(existing)
            if task.get("schema") != TASK_SCHEMA:
                raise ValueError(f"Existing QA task has an unsupported schema: {task_dir}")
            return task_dir, status(task_dir)

        staging = Path(tempfile.mkdtemp(prefix=f".{task_key}.", dir=task_parent))
        try:
            write_manifest(manifest, staging / "inventory.json")
            _atomic_write_json(staging / "inventory-validation.json", validation)
            # Japanese QA cannot correct is reported, never silently skipped.
            reach = preflight(data, manifest)
            _atomic_write_json(staging / "preflight.json", reach)
            _atomic_write_json(staging / "context.json", context)
            compact_items = _compact_items(manifest, context)
            forced_candidates = {
                item["id"]: _candidate(forced_reasons)
                for item in compact_items
                if (forced_reasons := _forced_deep_reasons(item))
            }
            lint_items, lint_fixes = _lint_items(manifest)
            items, screen_index = _screen_items(manifest, context, data, lint_fixes)
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
                "manifest_sha256": manifest["content_sha256"],
                "context_sha256": context["content_sha256"],
                "screen_index_sha256": screen_index_document["content_sha256"],
                "counts": manifest["counts"],
                "preflight": reach["counts"],
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


def _load_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    root = Path(task_dir).expanduser().resolve()
    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    if task.get("schema") != TASK_SCHEMA or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError(f"Unsupported or corrupt QA task: {root}")
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
    seconds = sum(
        remaining[stage] * _seconds_per_item(checkpoint, stage) for stage in remaining
    )
    measured = any(
        _reviewed_seconds((checkpoint.get(stage) or {}).get("bundles", []))
        for stage in REVIEW_STAGES
    )
    return {
        "remaining": remaining,
        "workers": active,
        "eta_seconds": round(seconds / max(1, len(active))) if measured else None,
    }


def _stage_metrics(stage: dict[str, Any], *, active: bool) -> dict[str, Any]:
    bundles = stage["bundles"]
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
    root, task, checkpoint = _load_task(task_dir)
    screen = checkpoint["screen"]
    deep = checkpoint["deep"]
    return {
        "task": str(root),
        "focus": task["focus"],
        "engine_fingerprint": task["engine_fingerprint"],
        "stage": checkpoint["stage"],
        "mechanical": {
            "checked": task["counts"]["records"],
            "total": task["counts"]["records"],
            "unresolved": task["counts"]["unresolved"],
        },
        "preflight": task.get("preflight") or {},
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
            },
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
        "estimate": _estimate(checkpoint),
        "declined": _declined_counts(checkpoint),
        "findings_file": checkpoint.get("findings_file") or "",
    }


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


def next_bundle(
    task_dir: str | Path, worker: str, bundle_id: str | None = None
) -> dict[str, Any] | None:
    """Assign the worker its next bundle, or the named one.

    A worker never receives a bundle it declined; another reviewer can claim
    that bundle by its ID.
    """
    root = Path(task_dir).expanduser().resolve()
    worker = str(worker or "worker")
    with _task_lock(root):
        for _transition in range(8):
            row, moved = _next_unlocked(root, worker, bundle_id)
            if row is not None or not moved:
                return row
        return None


def _stage_finished(checkpoint: dict[str, Any], stages: list[str]) -> bool:
    return all(
        row["status"] in {"accepted", "set-aside"}
        for stage in stages for row in checkpoint[stage]["bundles"]
    )


def _next_unlocked(
    root: Path, worker: str, bundle_id: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """One assignment attempt; True when it moved QA to its next stage instead."""
    root, task, checkpoint = _load_task(root)
    workers = checkpoint.setdefault("workers", {})
    workers.setdefault(worker, {"bundles": 0, "seconds": 0.0})["last_seen"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    stage = checkpoint["stage"]
    if stage not in REVIEW_STAGES:
        if bundle_id:
            raise ValueError(f"No bundle can be claimed in the {stage} stage")
        return None, False
    # Deep bundles open while screening continues; screening comes first.
    stages = ["screen", "deep"] if stage == "screen" else [stage]
    bundles = [row for name in stages for row in checkpoint[name]["bundles"]]
    if bundle_id:
        claimed_stage, pending = _bundle_row(checkpoint, bundle_id)
        if claimed_stage not in stages:
            raise ValueError(f"{bundle_id} belongs to the {claimed_stage} stage")
        if pending["status"] == "assigned" and pending.get("assigned_to") == worker:
            return copy.deepcopy(pending)
        if pending["status"] != "pending":
            raise ValueError(f"{bundle_id} is {pending['status']}, not waiting")
        if worker in (pending.get("declined_by") or []):
            raise ValueError(
                f"{worker} declined {bundle_id}; another reviewer must claim it"
            )
        if worker in (pending.get("authors") or []):
            raise ValueError(
                f"{worker} wrote corrections in {bundle_id}; an independent "
                "reviewer must confirm them"
            )
    else:
        for row in bundles:
            if row["status"] == "assigned" and row.get("assigned_to") == worker:
                return copy.deepcopy(row), False
        eligible = [
            (name, row) for name in stages for row in checkpoint[name]["bundles"]
            if worker not in (row.get("declined_by") or [])
            and worker not in (row.get("authors") or [])
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
            if not _stage_finished(checkpoint, [stage]):
                return None, False
            # Every bundle of the stage is reviewed: move QA on, as advance
            # and finalize would.
            before = stage
            if stage == "screen":
                _advance_unlocked(root)
            else:
                _finalize_unlocked(root)
            return None, _read_json(root / "checkpoint.json")["stage"] != before or (
                stage == "editorial"
                and not _stage_finished(_read_json(root / "checkpoint.json"), ["editorial"])
            )
    pending["status"] = "assigned"
    pending["assigned_to"] = worker
    pending["assigned_at"] = _utc_now()
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return copy.deepcopy(pending), False


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
                **((screen_index or {}).get(identity) or {}),
            }
    return targets


def _screen_motif_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item for item in bundle["items"]
        if item.get("kind") == "motif-family"
    }


def _declined_items(bundle: dict, result: dict) -> dict[str, str]:
    """The bundle items a reviewer declined, with the one-line reason for each."""
    declined = result.get("declined", [])
    if not isinstance(declined, list):
        raise QAResultError("Declined items must be a list")
    items = {item["id"] for item in bundle["items"]}
    reasons: dict[str, str] = {}
    for entry in declined:
        identity = str((entry or {}).get("id") or "") if isinstance(entry, dict) else ""
        reason = str(entry.get("reason") or "").strip() if isinstance(entry, dict) else ""
        if identity not in items or identity in reasons:
            raise QAResultError(f"Invalid or duplicate declined item {identity!r}")
        if not reason or "\n" in reason or len(reason) > DECLINE_REASON_LIMIT:
            raise QAResultError(
                f"A declined item needs a one-line reason of at most "
                f"{DECLINE_REASON_LIMIT} characters: {identity}"
            )
        reasons[identity] = reason
    return reasons


def _item_targets(item: dict[str, Any]) -> set[str]:
    """The screen target and context IDs one bundle item holds."""
    if item.get("kind") == "scene":
        return {
            line.get("id") or line["context_id"]
            for line in item["lines"]
            if "id" in line or "context_id" in line
        }
    return {item["id"]}


def _validate_screen_result(bundle: dict, result: dict) -> None:
    if result.get("schema") != SCREEN_RESULT_SCHEMA:
        raise QAResultError("Screen result has the wrong schema")
    if result.get("reviewed_all") is not True:
        raise QAResultError("Screen result must confirm reviewed_all=true")
    declined = _declined_items(bundle, result)
    allowed = set(_screen_target_map(bundle)) - {
        target
        for item in bundle["items"]
        if item["id"] in declined
        for target in _item_targets(item)
    }
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

    expected_motifs = {
        key: value for key, value in _screen_motif_map(bundle).items()
        if key not in declined
    }
    motif_reviews = result.get("motif_reviews")
    if not isinstance(motif_reviews, list):
        raise QAResultError("Screen result motif_reviews must be a list")
    actual_motifs = [
        str(item.get("id") or "") for item in motif_reviews
        if isinstance(item, dict)
    ]
    if len(actual_motifs) != len(set(actual_motifs)) or set(actual_motifs) != set(
        expected_motifs
    ):
        raise QAResultError("Screen result must review every assigned motif exactly once")
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
        item["id"]: item for item in bundle["items"]
        if item.get("kind") == "lint-family" and item["id"] not in declined
    }
    lint_reviews = result.get("lint_reviews", [])
    if not isinstance(lint_reviews, list) or not all(
        isinstance(review, dict) for review in lint_reviews
    ):
        raise QAResultError("Screen result lint_reviews must be a list of objects")
    reviewed = [str(review.get("id") or "") for review in lint_reviews]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(expected_lint):
        raise QAResultError(
            "Screen result must review every assigned lint family exactly once"
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
    declined = _declined_items(bundle, result)
    expected = {
        item["id"]: item for item in bundle["items"] if item["id"] not in declined
    }
    reviews = result.get("reviews")
    if not isinstance(reviews, list) or not all(
        isinstance(review, dict) for review in reviews
    ):
        raise QAResultError("Sweep result reviews must be a list of objects")
    reviewed = [str(review.get("id") or "") for review in reviews]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(expected):
        raise QAResultError("Sweep result must review every assigned family exactly once")
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


def _validate_deep_result(bundle: dict, result: dict) -> None:
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
                    "editorial_basis",
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
            if kind == "show-text":
                _validate_show_text_fix(review, item)
                continue
            correction = review.get("correction")
            if not isinstance(correction, str) or not correction.strip():
                raise QAResultError(f"Actionable review has no correction for {identity}")
            allowed = (
                _database_number_allowance(review, item)
                if kind == "database-numbers" else frozenset()
            )
            # Every occurrence the correction reaches, by its line structure;
            # a capped item lists only some of them.
            chosen = set(review.get("apply_identities") or [])
            shapes = [
                {
                    "event_code": locator.get("event_code"),
                    "pointers": len(locator["live_pointers"]),
                    "transform": locator.get("live_transform", "identity"),
                }
                for locator in item.get("locators") or []
                if locator["identity"] in chosen
            ] if chosen else item.get("target_shapes") or []
            for shape in shapes:
                problems = correction_problems(
                    str(item["source"]),
                    str(item["translation"]),
                    correction,
                    shape["event_code"],
                    ["/"] * shape["pointers"],
                    shape["transform"],
                    allowed,
                )
                if problems:
                    raise QAResultError(
                        f"The correction for {identity} would block apply: "
                        + "; ".join(problems)
                    )
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
                problems = correction_problems(
                    str(item["source"]), str(item["translation"]), proposal,
                    shape["event_code"], ["/"] * shape["pointers"], shape["transform"],
                )
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
            _validate_deep_result(bundle, result)
        canonical_path = root / "results" / stage / f"{bundle_id}.json"
        if row["status"] == "accepted" and canonical_path.is_file():
            if _read_json(canonical_path) != result:
                raise QAResultError("An accepted bundle result cannot be replaced")
            return status(root)
        if row["status"] == "set-aside":
            raise QAResultError(
                f"{bundle_id} was set aside after reviewers declined it"
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
        moved = (
            _split_declined(root, checkpoint, stage, row, bundle, declined)
            if declined else 0
        )
        if stage == "screen":
            exception_ids = checkpoint["screen"].setdefault("exception_ids", [])
            candidate_reasons = checkpoint["deep"].setdefault(
                "candidate_reasons", {}
            )
            screen_targets = _screen_target_map(
                bundle, _load_screen_index(root, task)
            )
            for exception in result["exceptions"]:
                review_id = exception["id"]
                target = screen_targets[review_id]
                cluster_id = target.get("cluster_id") or review_id
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
            checkpoint["screen"]["motif_accepted"] = int(
                checkpoint["screen"].get("motif_accepted", 0)
            ) + len(result["motif_reviews"])
            checkpoint["screen"]["lint_accepted"] = int(
                checkpoint["screen"].get("lint_accepted", 0)
            ) + sum(
                item["target_count"] for item in bundle["items"]
                if item.get("kind") == "lint-family" and item["id"] not in declined
            )
            checkpoint["deep"]["projected_items"] = len(candidate_reasons)
        checkpoint[stage]["accepted_items"] += int(row["item_count"]) - moved
        row["status"] = "accepted"
        row["result_path"] = str(canonical_path)
        row["accepted_at"] = _utc_now()
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
        if stage == "screen" and checkpoint["stage"] == "screen":
            if _issue_deep(root, checkpoint, final=False):
                _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


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


def context_view(task_dir: str | Path, locator: str, radius: int = 12) -> str:
    """Read-only game text around a locator, with Japanese and current English.

    The locator is an inventory identity or a command list such as
    `Map001.json#/events/1/pages/0/list`. Scenes a reviewer declined stay out.
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
    if scene in declined["context_scenes"]:
        raise ValueError("A reviewer declined this scene, so it is left out of context.")
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
    out = []
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


def _render_line(number: int, line: dict, mark: str) -> list[str]:
    speaker = f"<{line['speaker']}> " if line.get("speaker") else ""
    code = f" c{line['event_code']}" if line.get("event_code") else ""
    out = [
        f"{number:>4} {mark}{code} JP: {speaker}{_context_text(line['source'])}",
        f"{'':>4}   EN: {_context_text(line['translation'])}",
    ]
    if line.get("risk"):
        out.append(f"{'':>4}   risk: " + ",".join(line["risk"]))
    if line.get("context_expansion"):
        out.append(f"{'':>4}   repeated in: " + ",".join(line["context_expansion"]))
    if line.get("choice_context"):
        labels = " | ".join(
            f"{branch['index']}:{branch['label']}"
            for branch in line["choice_context"].get("branches", [])
        )
        out.append(f"{'':>4}   choices: {labels}")
    return out + _render_hints(line, "       ")


def _render_screen_item(item: dict) -> list[str]:
    kind = item.get("kind")
    if kind == "scene":
        out = [
            f"### SCENE {item['id']} {item['scene_id']} "
            f"({item['line_count']} lines, {item['target_count']} targets)"
        ]
        for number, line in enumerate(item["lines"], 1):
            mark = f"[T {line['id']}]" if "id" in line else "[ctx]"
            out += _render_line(number, line, mark)
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
        return out
    if kind == "lint-family":
        out = [f"### LINT {item['id']} {item['family']}: {item['description']}"]
        for proposal in item["proposals"]:
            speaker = f" <{proposal['speaker']}>" if proposal.get("speaker") else ""
            out += [
                f"  {proposal['id']} {proposal['scene']}{speaker}",
                "    JP:  " + _context_text(proposal["source"]),
                "    EN:  " + _context_text(proposal["current"]),
                "    FIX: " + _context_text(proposal["proposed"]),
            ]
        return out
    return ["### " + json.dumps(item, ensure_ascii=False)]


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
        ] + _render_hints(item, "  ")
        for evidence in item.get("screen_evidence") or []:
            out.append(
                f"  screen [{evidence['verdict']}] ({','.join(evidence['categories'])}): "
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
        for number, line in enumerate(scene["lines"], 1):
            named = [str(numbers[item]) for item in line.get("items") or [] if item in numbers]
            mark = (">>ITEM " + ",".join(named)) if named else "  "
            out += _render_line(number, line, mark)
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
    out = [
        f"### FINDING {item['id']} [{finding['severity']} {finding['category']}] "
        f"{finding.get('family_key', '')} occurrences={item['occurrences']}",
        "  JP:  " + _context_text(finding["source"]),
        "  EN:  " + _context_text(finding["current"]),
        "  FIX: " + _context_text(finding["correction"]),
        "  evidence: " + _context_text(finding["evidence"]),
    ]
    basis = finding.get("editorial_basis")
    if basis:
        out += [
            "  defect: " + _context_text(basis["defect"]),
            "  support: " + _context_text(basis["source_support"]),
        ]
    for conflict in item.get("conflicts") or []:
        out.append(f"  CONFLICT ({conflict['kind']}): " + conflict["message"])
    return out + _render_commands(item.get("nearby_commands"), "    ")


def render_bundle(task_dir: str | Path, bundle_id: str) -> str:
    """A bundle as compact text: what a reviewer reads instead of its JSON."""
    _root, _task, checkpoint = _load_task(task_dir)
    stage, row = _bundle_row(checkpoint, bundle_id)
    bundle = _read_json(Path(row["path"]))
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
                out += _render_screen_item(item)
            elif stage == "sweep":
                out += _render_group(item)
            else:
                out += _render_editorial(item)
    return "\n".join(out) + "\n"


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


def _screen_handoff_context(
    root: Path,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """Recover accepted screen rationale, full scenes, and motif adjudication."""
    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    screen_index = _load_screen_index(root, task)
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scenes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    motifs: dict[str, list[dict[str, Any]]] = defaultdict(list)

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
                "lines": item["lines"],
            }
            for line in item["lines"]:
                target_id = line.get("id") or line.get("context_id")
                if target_id:
                    target_scenes[target_id] = scene

        for exception in result["exceptions"]:
            target_id = exception["id"]
            target = screen_index.get(target_id) or {}
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

        for review in result["motif_reviews"]:
            motif = motif_items[review["id"]]
            context = {
                "id": motif["id"],
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": motif["variant_count"],
                "variants": motif["variants"],
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
            }
            for variant in motif["variants"]:
                motifs[variant["id"]].append(context)

    return (
        {key: value for key, value in evidence.items()},
        {key: list(value.values()) for key, value in scenes.items()},
        {key: value for key, value in motifs.items()},
    )


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


def _declined_scope(
    root: Path,
    checkpoint: dict[str, Any],
    manifest: dict[str, Any],
    *,
    waiting: bool = False,
) -> dict[str, Any]:
    """What reviewers declined: set aside, and with `waiting` also still offered.

    `scenes` are scenes no screen reviewer read, `context_scenes` adds those of
    declined deep items, and `identities` are the lines no reviewer judged,
    which no correction may target.
    """
    task = _read_json(root / "task.json")
    screen_index = _load_screen_index(root, task)
    records, clusters = _record_maps(manifest)
    statuses = {"set-aside", "pending", "assigned"} if waiting else {"set-aside"}
    scenes: set[str] = set()
    context_scenes: set[str] = set()
    unreviewed: set[str] = set()
    items = []
    for stage in REVIEW_STAGES:
        for row in checkpoint.get(stage, {}).get("bundles", []):
            if row["status"] not in statuses or not row.get("declined_by"):
                continue
            reasons: dict[str, list[str]] = defaultdict(list)
            for decline in row.get("declines") or []:
                for item_id, reason in decline["reasons"].items():
                    reasons[item_id].append(reason)
            for item in _read_json(Path(row["path"]))["items"]:
                kind = item.get("kind") or stage
                if stage in {"sweep", "editorial"}:
                    # Lines were reviewed; only these fixes are left out.
                    pass
                elif kind == "scene":
                    copies = set(item.get("scene_copies") or [item["scene_id"]])
                    scenes |= copies
                    context_scenes |= copies
                    unreviewed |= {
                        screen_index[line["id"]]["cluster_id"]
                        for line in item["lines"] if "id" in line
                    }
                elif kind in {"cluster", "deep"} or stage == "deep":
                    unreviewed.add(item["id"])
                    context_scenes |= {
                        scene["scene_id"]
                        for scene in item.get("screen_scene_contexts") or []
                    }
                items.append({
                    "stage": stage,
                    "id": item["id"],
                    "kind": "deep" if stage == "deep" else kind,
                    "set_aside": row["status"] == "set-aside",
                    "reasons": reasons.get(item["id"], []),
                })
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
        "context_scenes": context_scenes,
        "clusters": unreviewed,
        "identities": identities,
        "items": items,
    }


def _lint_decisions(
    checkpoint: dict[str, Any], declined: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """The lint families reviewers accepted for each cluster, with their notes."""
    accepted: dict[str, dict[str, Any]] = {}
    for row in checkpoint["screen"]["bundles"]:
        if row["status"] != "accepted":
            continue
        result = _read_json(Path(row["result_path"]))
        reviews = {review["id"]: review for review in result.get("lint_reviews") or []}
        if not reviews:
            continue
        for item in _read_json(Path(row["path"]))["items"]:
            review = reviews.get(item["id"])
            if item.get("kind") != "lint-family" or review is None:
                continue
            rejected = set(review["rejected"])
            for proposal in item["proposals"]:
                cluster_id = proposal["cluster_id"]
                if proposal["id"] in rejected or cluster_id in declined["clusters"]:
                    continue
                entry = accepted.setdefault(
                    cluster_id, {"families": set(), "notes": []}
                )
                entry["families"].add(item["family"])
                if str(review.get("note") or "").strip():
                    entry["notes"].append(str(review["note"]).strip())
    return accepted


def _add_sweep_findings(
    findings: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Accepted sweep candidates as findings, one per line, rules combined.

    Returns candidates left out because their combined rules would block apply.
    """
    by_cluster: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)
    for row in checkpoint.get("sweep", {}).get("bundles", []):
        if row["status"] != "accepted":
            continue
        reviews = {
            review["id"]: review
            for review in _read_json(Path(row["result_path"]))["reviews"]
        }
        for item in _read_json(Path(row["path"]))["items"]:
            review = reviews.get(item["id"])
            if review is None:
                continue
            for candidate in item["candidates"]:
                if candidate["id"] not in review["rejected"]:
                    by_cluster[candidate["cluster_id"]].append((
                        {**item, "reviewer": str(row.get("assigned_to") or "")},
                        candidate,
                        str(review.get("note") or "").strip(),
                    ))
    dropped = []
    for cluster_id, accepted in sorted(by_cluster.items()):
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
            for problem in correction_problems(
                records[identity]["source"], records[identity]["live"],
                correction, records[identity].get("event_code"),
                records[identity]["live_pointers"], records[identity]["live_transform"],
            )
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
) -> list[dict[str, Any]]:
    """Mark reviewer corrections with their lines' accepted lint fixes, which
    compose after the editorial pass, and add the rest as findings.

    Returns the fixes left out because the fixed text would block apply.
    """
    records, clusters = _record_maps(manifest)
    titles = lint.title_map(manifest["clusters"])
    by_cluster = {
        finding["cluster_id"]: finding for finding in findings
        if finding.get("kind") != "show-text"
    }
    dropped = []
    for cluster_id, decision in sorted(accepted.items()):
        families = sorted(decision["families"], key=lint.ORDER.index)
        cluster = clusters[cluster_id]
        reviewable = [
            identity for identity in cluster["identities"]
            if identity not in declined["identities"]
        ]
        finding = by_cluster.get(cluster_id)
        parts = []
        if finding:
            parts.append((finding["correction"], finding["target_identities"], finding))
        remaining = [
            identity for identity in reviewable
            if not finding or identity not in finding["target_identities"]
        ]
        if remaining:
            parts.append((cluster["live"], remaining, None))
        for base, targets, owner in parts:
            if owner:
                owner["lint_families"] = families
                continue
            composed = lint.compose(cluster["source"], base, families, titles)
            if composed == base:
                continue
            problems = [
                problem
                for identity in targets
                for problem in correction_problems(
                    records[identity]["source"], records[identity]["live"],
                    composed, records[identity].get("event_code"),
                    records[identity]["live_pointers"],
                    records[identity]["live_transform"],
                )
            ]
            if problems:
                dropped.append({
                    "cluster_id": cluster_id,
                    "families": families,
                    "problems": sorted(set(problems)),
                })
                continue
            findings.append({
                "id": "",
                "cluster_id": cluster_id,
                "severity": "medium",
                "category": (
                    "ui" if families == ["lint:quoted-title"] else "formatting"
                ),
                "family_key": families[0],
                "evidence": " ".join(
                    lint.FAMILIES[family]["description"] for family in families
                ) + "".join(" Reviewer: " + note for note in decision["notes"][:2]),
                "source": cluster["source"],
                "current": cluster["live"],
                "correction": composed,
                "target_identities": targets,
                "lint_families": families,
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
    candidate_reasons: dict[str, dict[str, Any]],
    only: set[str] | None = None,
    prior: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
    """Deep items for the candidates, or for `only` those; a cluster reviewed
    before carries that `prior_review` to reconcile with newer evidence."""
    manifest = _read_json(root / "inventory.json")
    context = _read_json(root / "context.json")
    records, clusters = _record_maps(manifest)
    checkpoint = _read_json(root / "checkpoint.json")
    declined = _declined_scope(root, checkpoint, manifest)
    lint_accepted = _lint_decisions(checkpoint, declined)
    titles = lint.title_map(manifest["clusters"])
    compact = {item["id"]: item for item in _compact_items(manifest, context)}
    by_source: dict[str, list[dict]] = defaultdict(list)
    for cluster in manifest["clusters"]:
        by_source[cluster["source"]].append(cluster)
    data_root = Path(_read_json(root / "task.json")["data_root"])
    document_cache: dict[str, Any] = {}
    screen_evidence, screen_scenes, motif_contexts = _screen_handoff_context(root)
    _reopen_disputed_preserved_motifs(
        candidate_reasons, screen_evidence, motif_contexts
    )
    items = []
    for identity in manifest["review_sequence"]:
        # Lines in scenes a reviewer declined stay out of deep review.
        if (
            identity not in candidate_reasons
            or identity in declined["clusters"]
            or only is not None and identity not in only
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
        if identity in lint_accepted:
            families = sorted(lint_accepted[identity]["families"], key=lint.ORDER.index)
            item["lint"] = {
                "families": families,
                "proposed": lint.compose(
                    cluster["source"], cluster["live"], families, titles
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
        if prior and identity in prior:
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
    their target bundle and motif reviews are accepted. When screening ends,
    every remaining candidate opens, and a cluster whose evidence grew after
    its deep review opens again with that review beside it. Returns how many
    items opened.
    """
    deep = checkpoint["deep"]
    candidates = deep.setdefault("candidate_reasons", {})
    issued = deep.setdefault("issued", {})
    rows = deep.setdefault("bundles", [])
    open_clusters = {
        item["id"]
        for row in rows if row["status"] in {"pending", "assigned"}
        for item in _read_json(Path(row["path"]))["items"]
    }
    if final:
        ready = set(candidates)
    else:
        index = _read_json(root / "screen-targets.json")
        statuses = {row["id"]: row["status"] for row in checkpoint["screen"]["bundles"]}
        screen_index = _load_screen_index(root, _read_json(root / "task.json"))
        cluster_bundle = {
            screen_index[target]["cluster_id"] if target in screen_index else target: bundle
            for target, bundle in index["targets"].items()
        }
        ready = {
            cluster_id for cluster_id in candidates
            if cluster_id not in issued
            and statuses.get(cluster_bundle.get(cluster_id, "")) == "accepted"
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
    evidence, scenes, motifs = _screen_handoff_context(root)
    _reopen_disputed_preserved_motifs(candidates, evidence, motifs)
    if final:
        ready = set(candidates)

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
        cluster_id for cluster_id in ready
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
    items = _deep_items(root, candidates, only=fresh, prior=prior)
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
    if any(
        row["status"] not in {"accepted", "set-aside"} and row not in waiting
        for row in rows
    ):
        raise ValueError(f"Every {stage} bundle must be accepted first")
    if waiting and not skip_declined:
        raise ValueError(
            f"{len(waiting)} declined {stage} bundle(s) wait for another reviewer "
            f"({', '.join(row['id'] for row in waiting)}): claim each with next "
            "--bundle ID under a different worker name, or use --skip-declined "
            "to report them as not reviewed"
        )
    for row in waiting:
        row["status"] = "set-aside"
        row["skipped"] = True


def _sweep_items(
    checkpoint: dict[str, Any], manifest: dict[str, Any], declined: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every other line an accepted family's sweep rule changes, for group review."""
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
            if (
                cluster_id in corrected
                or cluster_id in declined["clusters"]
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
                correction_problems(
                    record["source"], record["live"], proposed,
                    record.get("event_code"), record["live_pointers"],
                    record["live_transform"],
                )
                for record in members
            ):
                continue
            position = _scene_position(members[0])
            speaker = str((members[0].get("speaker") or {}).get("display_name") or "")
            candidates.append({
                "id": "sweep-" + _sha256(f"{key}\0{cluster_id}")[:16],
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
    root, _task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] == "deep":
        _settle_declined(checkpoint, "deep", skip_declined)
        manifest = _read_json(root / "inventory.json")
        items = _sweep_items(
            checkpoint, manifest, _declined_scope(root, checkpoint, manifest)
        )
        bundles = _bundle_items(
            items,
            stage="sweep",
            char_budget=DEFAULT_DEEP_CHAR_BUDGET,
            item_limit=DEFAULT_DEEP_ITEM_LIMIT,
        ) if items else []
        checkpoint["sweep"] = {
            "total_items": sum(item["target_count"] for item in items),
            "accepted_items": 0,
            "bundles": _write_bundles(root, bundles) if bundles else [],
        }
        checkpoint["stage"] = "sweep" if bundles else "ready-finalize"
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return status(root)
    if checkpoint["stage"] != "screen":
        return status(root)
    _settle_declined(checkpoint, "screen", skip_declined)
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
    }
    if rebuilt_summaries != reusable_summaries:
        raise ValueError("Current screen bundles differ; screening cannot be reused")

    if rebuilt_checkpoint["stage"] == "screen":
        for bundle_id in sorted(reusable_results):
            accept_result(rebuilt, reusable_results[bundle_id])
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
        for review in result["motif_reviews"]:
            motif = motifs[review["id"]]
            motif_families.append({
                "id": review["id"],
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": len(motif["variants"]),
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
                "screen_review": {
                    "disposition": review["disposition"],
                    "note": review["note"],
                    "suspect_ids": review["suspect_ids"],
                },
                "_variant_ids": [variant["id"] for variant in motif["variants"]],
            })
    for review, _item, row in _latest_deep_reviews(checkpoint).values():
        deep_dispositions[review["id"]] = review["disposition"]
        deep_motif_attributions[review["id"]] = (
            set(review.get("motif_ids") or [])
            if "motif_ids" in review
            else None
        )
        kind = (review.get("source_fix") or {}).get("kind")
        if review["disposition"] == "actionable" and kind == "show-text":
            findings.append(_show_text_finding(
                review, records, task, faces, row, declined
            ))
        elif review["disposition"] == "actionable":
            cluster = clusters[review["id"]]
            target_ids = [
                identity
                for identity in review.get("apply_identities") or cluster["identities"]
                if identity not in declined["identities"]
            ]
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
                    {"source_fix": kind, "allowed_flags": ["visible-number-mismatch"]}
                    if kind == "database-numbers" else {}
                ),
                **(
                    {"editorial_basis": review["editorial_basis"]}
                    if _normalize_category(review.get("category"))
                    in EDITORIAL_JUDGMENT_CATEGORIES
                    else {}
                ),
            })
        elif review["disposition"] == "uncertain-playtest":
            cluster = clusters[review["id"]]
            uncertain.append({
                **review,
                "source": cluster["source"],
                "current": cluster["live"],
                "places": len([
                    identity for identity in cluster["identities"]
                    if identity not in declined["identities"]
                ]),
            })
    sweep_dropped = _add_sweep_findings(findings, checkpoint, records)
    _add_lint_findings(
        findings, _lint_decisions(checkpoint, declined), manifest, declined
    )
    findings.sort(key=lambda item: (
        {"critical": 0, "high": 1, "medium": 2}[item["severity"]],
        item["cluster_id"],
        bool(item.get("lint_only")),
    ))
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"QA-{index:04d}"
    _simulate_apply(findings, records)
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
        "preflight": _read_json(root / "preflight.json"),
    }


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


def _editorial_items(
    root: Path,
    checkpoint: dict[str, Any],
    findings: list[dict[str, Any]],
    conflicts: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    """One editorial item per finding to confirm, with its nearby game text."""
    task = _read_json(root / "task.json")
    records, _clusters = _record_maps(_read_json(root / "inventory.json"))
    data_root = Path(task["data_root"])
    nearby: dict[str, list[dict]] = {}
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] == "accepted":
            for item in _read_json(Path(row["path"]))["items"]:
                nearby[item["id"]] = item.get("nearby_commands") or []
    cache: dict[str, Any] = {}
    items = []
    for finding in findings:
        if finding["id"] not in conflicts and not _needs_editorial(finding):
            continue
        targets = [records[identity] for identity in finding["target_identities"]]
        judgment = finding["category"] in EDITORIAL_JUDGMENT_CATEGORIES
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
            "targets": [{
                "identity": record["identity"],
                "event_code": record.get("event_code"),
                "live_pointers": record["live_pointers"],
                "live_transform": record["live_transform"],
            } for record in targets],
            "nearby_commands": nearby.get(finding["cluster_id"])
            or _nearby_commands(
                data_root,
                targets[0] if targets else records[finding["line_identity"]],
                cache,
            ),
            **({"conflicts": conflicts[finding["id"]]} if finding["id"] in conflicts else {}),
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
            if replacement is not None:
                raise QAResultError(f"Only a revision has a replacement: {identity}")
            continue
        finding = item["finding"]
        if finding.get("kind") == "show-text":
            raise QAResultError(
                f"A Show Text fix is accepted or withdrawn, not revised: {identity}"
            )
        if not isinstance(replacement, str) or not replacement.strip():
            raise QAResultError(f"A revision needs its replacement text: {identity}")
        for target in item["targets"]:
            problems = correction_problems(
                finding["source"], finding["current"], replacement,
                target["event_code"], target["live_pointers"], target["live_transform"],
                frozenset(finding.get("allowed_flags") or ()),
            )
            if problems:
                raise QAResultError(
                    f"The revision of {identity} would block apply: "
                    + "; ".join(problems)
                )


def _compose_lint(
    findings: list[dict[str, Any]], records: dict[str, dict[str, Any]], titles: dict
) -> list[dict[str, Any]]:
    """Apply accepted lint fixes on top of final corrections; returns those
    left out because the combined text would block apply."""
    dropped = []
    for finding in findings:
        families = finding.get("lint_families")
        if not families or finding.get("lint_only"):
            continue
        composed = lint.compose(
            finding["source"], finding["correction"], families, titles
        )
        problems = sorted({
            problem
            for identity in finding["target_identities"]
            for problem in correction_problems(
                records[identity]["source"], records[identity]["live"], composed,
                records[identity].get("event_code"), records[identity]["live_pointers"],
                records[identity]["live_transform"],
            )
        })
        if problems:
            dropped.append({"id": finding["id"], "families": families, "problems": problems})
        else:
            finding["correction"] = composed
    return dropped


def _complete_editorial(
    root: Path, task: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    """Apply editorial verdicts, then finish or open another round for conflicts."""
    draft = _read_json(root / "draft-findings.json")
    manifest = _read_json(root / "inventory.json")
    records, _clusters = _record_maps(manifest)
    titles = lint.title_map(manifest["clusters"])
    editorial = checkpoint.get("editorial") or {"bundles": []}
    verdicts: dict[str, dict[str, Any]] = {}
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
            verdicts[review["id"]] = {**review, "reviewer": row.get("assigned_to") or ""}
        shown.update({item["id"]: item for item in items})
    acks = editorial.setdefault("acks", {})
    for identity, item in shown.items():
        if verdicts.get(identity, {}).get("verdict") == "accept":
            for conflict in item.get("conflicts") or []:
                if conflict["kind"] == "soft":
                    acks[f"{conflict['key']}:{identity}"] = conflict["signature"]
    final, withdrawn, unverified = [], [], []
    for finding in draft["findings"]:
        identity = finding["id"]
        verdict = verdicts.get(identity)
        if identity in set_aside and verdict is None:
            unverified.append({"id": identity, "reason": "declined by editorial reviewers"})
            continue
        if verdict is None and _needs_editorial(finding):
            raise ValueError(f"{identity} has no editorial review yet")
        if verdict and verdict["verdict"] == "withdraw":
            withdrawn.append({
                "id": identity, "note": verdict["note"], "reviewer": verdict["reviewer"],
            })
            if finding.get("lint_families"):
                # The line still gets the mechanical fixes it was given.
                final.append({
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
            continue
        finding = dict(finding)
        if verdict:
            if verdict["verdict"] == "revise":
                finding["correction"] = verdict["replacement"]
            finding["editorial"] = {
                "verdict": verdict["verdict"],
                "note": str(verdict.get("note") or ""),
                "reviewer": verdict["reviewer"],
            }
        final.append(finding)
    numbers = [int(row["id"].split("-")[1]) for row in draft["findings"]]
    lint_dropped = []
    for finding in final:
        if finding["id"]:
            continue
        numbers.append(max(numbers, default=0) + 1)
        finding["id"] = f"QA-{numbers[-1]:04d}"
        composed = lint.compose(
            finding["source"], finding["current"], finding["lint_families"], titles
        )
        problems = sorted({
            problem
            for identity in finding["target_identities"]
            for problem in correction_problems(
                records[identity]["source"], records[identity]["live"], composed,
                records[identity].get("event_code"), records[identity]["live_pointers"],
                records[identity]["live_transform"],
            )
        })
        if problems:
            lint_dropped.append({
                "id": finding["id"], "families": finding["lint_families"],
                "problems": problems,
            })
        else:
            finding["correction"] = composed
    lint_dropped += _compose_lint(final, records, titles)
    final = [finding for finding in final if finding["correction"] != finding["current"]]
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
    if open_conflicts and int(editorial.get("round", 0)) < EDITORIAL_ROUND_LIMIT:
        _open_editorial_round(
            root,
            checkpoint,
            [finding for finding in final if finding["id"] in open_conflicts],
            open_conflicts,
        )
        return checkpoint
    for finding in final:
        if finding["id"] in open_conflicts:
            unverified.append({
                "id": finding["id"],
                "reason": "conflicting corrections stayed unresolved: "
                + "; ".join(conflict["message"] for conflict in open_conflicts[finding["id"]]),
            })
    final = [finding for finding in final if finding["id"] not in open_conflicts]
    _simulate_apply(final, records)
    document = {
        **draft,
        "created_at": _utc_now(),
        "findings": final,
        "finding_families": _finding_families(final),
        "withdrawn": withdrawn,
        "unverified": unverified,
        "lint_dropped": lint_dropped,
        "editorial_rounds": int(editorial.get("round", 0)),
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
        if state["stage"] == "sweep":
            # Reviewers check the family sweep before findings are made.
            return state
        root, task, checkpoint = _load_task(root)
    if checkpoint["stage"] in {"sweep", "ready-finalize"}:
        if checkpoint["stage"] == "sweep":
            _settle_declined(checkpoint, "sweep", skip_declined)
        draft = _draft_document(root, task, checkpoint)
        _atomic_write_json(root / "draft-findings.json", draft)
        conflicts = _consistency_conflicts(
            draft["findings"], _read_json(root / "context.json"), _decisions(root)
        )
        if not _open_editorial_round(root, checkpoint, draft["findings"], conflicts):
            checkpoint["editorial"] = checkpoint.get("editorial") or {
                "total_items": 0, "accepted_items": 0, "bundles": [], "round": 0,
            }
            _complete_editorial(root, task, checkpoint)
            return status(root)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return status(root)
    if checkpoint["stage"] == "editorial":
        _settle_declined(checkpoint, "editorial", skip_declined)
        _complete_editorial(root, task, checkpoint)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


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
        for identity in finding["target_identities"]:
            record = records[identity]
            target = (record["file"], tuple(record["live_pointers"]))
            previous = targets.get(target)
            if previous is not None and previous != finding["correction"]:
                raise ValueError(
                    f"Approved findings propose conflicting corrections for {identity}"
                )
            if previous is not None:
                continue
            targets[target] = finding["correction"]
            operations.append({
                "finding_id": finding["id"],
                "identity": identity,
                "file": record["file"],
                "live_pointers": record["live_pointers"],
                "live_transform": record["live_transform"],
                "expected": record["live"],
                "replacement": finding["correction"],
                "allowed_flags": list(finding.get("allowed_flags") or []),
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
    if operation["live_transform"] == "quoted-string":
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
    if transform == "quoted-string":
        if len(values) != 1:
            raise ValueError("Quoted-string operation has multiple live pointers")
        match = _QUOTED_VALUE_RE.search(values[0])
        if not match:
            raise ValueError("Quoted-string live value no longer contains a quoted value")
        return [values[0][: match.start(2)] + replacement + values[0][match.end(2) :]]
    if len(values) == 1:
        return [replacement]
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
            introduced_flags = after_flags - before_flags - set(
                operation.get("allowed_flags") or ()
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


