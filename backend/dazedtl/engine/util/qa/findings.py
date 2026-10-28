"""The findings document drafted from a task's reviews."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from util import rpgmaker_blocks as blocks
from util.qa.advance import _not_reviewed
from util.qa.bundles import _screen_motif_map
from util.qa.pace import _not_translated_report
from util.qa.records import (
    _changes,
    _decode_pointer,
    _latest_deep_reviews,
    _record_maps,
    _resolve_parts,
    _result_declines,
)
from util.qa.schema import (
    ADDED_BATTLER_NAME,
    EDITORIAL_JUDGMENT_CATEGORIES,
    FINDINGS_SCHEMA,
    QAResultError,
    _canonical_bytes,
    _normalize_category,
    _normalize_family_key,
    _sha256,
    _utc_now,
)
from util.qa.scope import (
    _add_lint_findings,
    _add_sweep_findings,
    _declined_scope,
    _lint_decisions,
)
from util.qa.selection import (
    _cluster_by_identity,
    _lint_game,
    _scene_records,
    _scene_signature,
)
from util.qa.storage import _read_json, review_layout
from util.qa.validation import _scene_line, _simulate_apply

# The flags each correcting source fix may introduce.
SOURCE_FIX_ALLOWED_FLAGS = {
    "database-numbers": ("visible-number-mismatch",),
    "battler-name": (ADDED_BATTLER_NAME,),
}


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
    not_corrected = []
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
                "summary": review["summary"].strip(),
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
                "summary": review["summary"].strip(),
                "source": cluster["source"],
                "current": cluster["live"],
                "places": len(places),
            })
        elif review["disposition"] == "not-corrected" and places:
            not_corrected.append({
                "id": review["id"],
                "source": cluster["source"],
                "current": cluster["live"],
                "places": len(places),
                "summary": review["summary"].strip(),
                "evidence": review["evidence"],
                "reviewer": str(row.get("assigned_to") or ""),
            })
    layout = review_layout(task)
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
        # Defects reviewers found but could not correct within apply's
        # checks, reported without asking the user.
        "not_corrected": not_corrected,
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
    if commands[owner].get("code") == 401:
        owner = blocks.show_text(commands, owner)
    header = commands[owner] if owner is not None else {}
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
        "summary": review["summary"].strip(),
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
        "summary": review["summary"].strip(),
        "evidence": review["evidence"],
        "lines": lines,
        "target_identities": targets,
        "authors": [str(row.get("assigned_to") or "")],
        **(
            {"editorial_basis": review["editorial_basis"]}
            if category in EDITORIAL_JUDGMENT_CATEGORIES else {}
        ),
    }
