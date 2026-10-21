"""Validation of the reviewers' screen, sweep and deep results."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from util.rpgmaker_qa_manifest import _mechanical_evidence
from util import rpgmaker_qa_checks as checks
from util.qa.schema import (
    ADDED_BATTLER_NAME,
    _canonical_bytes,
    DECLINE_REASON_LIMIT,
    DEEP_RESULT_SCHEMA,
    EDITORIAL_JUDGMENT_CATEGORIES,
    FINDING_CATEGORIES,
    _normalize_category,
    QAResultError,
    SCREEN_RESULT_SCHEMA,
    _sha256,
    SUMMARY_LIMIT,
    SWEEP_RESULT_SCHEMA,
)
from util.qa.storage import _read_json
from util.qa.records import _changes, _decode_pointer, _record_maps
from util.qa.fitting import _adds_only_battler_name, _record_problems
from util.qa.selection import _cluster_by_identity, _scene_position, _scene_records
from util.qa.bundles import (
    _declined_items,
    _partition,
    _screen_motif_map,
    _screen_target_map,
    _shape_problems,
    _target_entry,
    _target_shape,
)
from util.qa.scope import _declined_scope


SCREEN_VERDICTS = frozenset({"suspect", "needs-context"})
MOTIF_DISPOSITIONS = frozenset({"preserved", "suspect", "uncertain-playtest"})
# A question offers the user a proposal; a defect no correction can fix within
# apply's checks is reported as not corrected instead, which asks nobody.
DEEP_DISPOSITIONS = frozenset({
    "clean", "actionable", "uncertain-playtest", "not-corrected", "declined",
})

_SUMMARY_CODE_RE = re.compile(r"\\[A-Za-z{}<>|.!^$]|\.json\b|#/")
SUMMARY_DISPOSITIONS = frozenset({"actionable", "uncertain-playtest", "not-corrected"})

# An observation's reason, for a line outside the reviewer's own items, is one
# short line.
OBSERVATION_NOTE_LIMIT = 500
SEVERITIES = frozenset({"critical", "high", "medium"})

# Fixes for slips in the Japanese source itself: the Show Text header's face
# and name, a database field's number that its own entry contradicts, or an
# MZ battle message without the %1 that shows its battler's name.
SOURCE_FIX_KINDS = frozenset({"show-text", "database-numbers", "battler-name"})

_CANONICAL_QUIRK_MAPPING_RE = re.compile(
    r"`([^`\n]+)`\s*→\s*\"([^\"\n]+)\""
)
_JAPANESE_FIELD_LABEL_RE = re.compile(r"【([^】\n]+)】")
_ENGLISH_FIELD_LABEL_RE = re.compile(
    r"\[([A-Za-z][A-Za-z0-9 /&'’-]{0,79})\]"
)


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


def _validate_summary(review: dict[str, Any], identity: str) -> None:
    """Require the one plain sentence the user reads for a reviewed line."""
    summary = review.get("summary")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or "\n" in summary
        or len(summary.strip()) > SUMMARY_LIMIT
        or _SUMMARY_CODE_RE.search(summary)
    ):
        raise QAResultError(
            f"A review needs a summary: one plain sentence of at most "
            f"{SUMMARY_LIMIT} characters saying what a player would see wrong, "
            f"without control codes or file pointers: {identity}"
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
        if disposition in SUMMARY_DISPOSITIONS:
            _validate_summary(review, identity)
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
        if disposition == "not-corrected" and not str(
            review.get("evidence") or ""
        ).strip():
            raise QAResultError(
                f"A line not corrected needs the reason in evidence: {identity}"
            )
        if disposition == "not-corrected" and review.get("correction") is not None:
            raise QAResultError(f"A line not corrected has no correction: {identity}")
        if disposition == "uncertain-playtest":
            # A proposal the user may choose instead of the current text: a
            # question without one would only ask the user to keep the line.
            proposal = review.get("correction")
            item = bundle_items[identity]
            if proposal is None:
                raise QAResultError(
                    f"A question needs a correction the user may choose: {identity}. "
                    "Propose the fix, or when no correction passes apply's checks, "
                    "give disposition not-corrected with the reason in evidence."
                )
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
