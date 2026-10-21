"""What deep review covers: the screen's basis for it, declined scope,
scenes, follow-ups, and the sweep and lint findings it adds."""

from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path
from typing import Any

from util import rpgmaker_qa_lint as lint
from util.qa.bundles import (
    _bundle_items,
    _load_screen_index,
    _merge_candidate,
    _screen_motif_map,
    _target_entry,
    _units,
    _write_bundles,
)
from util.qa.fitting import _record_problems
from util.qa.records import _latest_deep_reviews, _record_maps, _result_declines
from util.qa.schema import (
    DEFAULT_SCREEN_CHAR_BUDGET,
    DEFAULT_SCREEN_ITEM_LIMIT,
    REVIEW_STAGES,
    _normalize_category,
    _sha256,
)
from util.qa.selection import (
    _command_number,
    _compact_items,
    _lint_game,
    _lint_items,
    _scene_groups,
    _scene_item,
    _scene_position,
)
from util.qa.storage import _read_json


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
            "summary": item["example"]["summary"],
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
            summary = " ".join(
                lint.note(family, cluster["source"], cluster["live"], game)
                or lint.FAMILIES[family]["description"]
                for family in part
            )
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
                "summary": summary,
                "evidence": summary + "".join(
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
