"""Stage advancement: issuing deep and sweep rounds once a stage finishes."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from util import rpgmaker_qa_lint as lint
from util.qa.schema import (
    _canonical_bytes,
    DEFAULT_DEEP_CHAR_BUDGET,
    DEFAULT_DEEP_ITEM_LIMIT,
    FINISHED_STATUSES,
    LINT_ITEM_LIMIT,
    _normalize_category,
    _normalize_family_key,
    _sha256,
    _utc_now,
)
from util.qa.storage import _atomic_write_json, _load_task, _read_json, _task_lock
from util.qa.records import _latest_deep_reviews, _record_maps
from util.qa.fitting import _box, _record_problems
from util.qa.selection import (
    _compact_items,
    _database_checks,
    _entry_numbers,
    _lint_game,
    _nearby_commands,
    _scene_position,
)
from util.qa.interface import _capture_folder, _fit_checks, _interface_checks
from util.qa.bundles import (
    _bundle_deep,
    _bundle_items,
    _load_screen_index,
    _write_bundles,
)
from util.qa.scope import (
    _declined_scope,
    _deep_basis,
    _lint_decisions,
    _motif_translation_roster,
    _open_follow_ups,
    _screen_target_rows,
)
from util.qa.pace import status


# Ready deep items that open a deep bundle while screening continues.
EARLY_DEEP_BATCH = DEFAULT_DEEP_ITEM_LIMIT


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
                "summary": review["summary"].strip(),
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
