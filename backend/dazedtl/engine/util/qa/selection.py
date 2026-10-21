"""Which lines QA reviews and how they are grouped: risk reasons, compact
items, scenes, motifs, lint items, screen items and number checks, and the
nearby context they print."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from util.paths import (
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
)
from util.rpgmaker_qa_manifest import _mechanical_evidence
from util import rpgmaker_qa_checks as checks
from util import rpgmaker_qa_glossary as glossary_rules
from util import rpgmaker_qa_lint as lint
from util.reference_games import reference_context
from util.qa.schema import (
    _canonical_bytes,
    _JAPANESE_ANCHOR_RE,
    LINT_ITEM_LIMIT,
    _sha256,
)
from util.qa.storage import _decisions, _read_json, _read_optional
from util.qa.records import _decode_pointer, _record_maps, _resolve_parts
from util.qa.fitting import _record_problems

if TYPE_CHECKING:
    from util.qa.ledger import _Reviewed


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

_MOTIF_GUIDANCE_RE = re.compile(
    r"(?:recurring|running|joke|wordplay|pun|catchphrase|humou?r|冗談|駄洒落|語呂)",
    re.IGNORECASE,
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
    """The lint game of a prepared task, as it was prepared, with the
    decisions its reviewers recorded since."""
    return _game(manifest, _read_json(root / "context.json"))._replace(decided=tuple(
        (str(entry["source"]), str(entry["translation"]))
        for entry in _decisions(root)
        if entry.get("source") and entry.get("translation")
    ))


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


def _command_number(identity: str) -> int | None:
    """The event command that holds an identity's line, if any."""
    filename, _, pointer = identity.split("@", 1)[0].partition("#")
    position = _scene_position({"file": filename, "source_pointer": pointer})
    return position[1] if position else None


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
