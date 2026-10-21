"""Accepting reviewers' results and observations, and the lines a task
observed, corrected or held."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from util.qa.bundles import (
    _checkable,
    _declined_items,
    _issue_checks,
    _load_screen_index,
    _merge_candidate,
    _record_check,
    _screen_motif_map,
    _screen_target_map,
    _split_declined,
)
from util.qa.editorial import _validate_editorial_result
from util.qa.ledger import _pair_key, _task_ledger
from util.qa.pace import status
from util.qa.records import _bundle_row, _record_maps, _split_notice
from util.qa.reopen import _issue_new_evidence, _note_observations
from util.qa.schema import _QUOTED_VALUE_RE, QAResultError, _sha256, _utc_now
from util.qa.storage import (
    JUDGED_BEFORE,
    _atomic_write_json,
    _load_task,
    _observation_key,
    _read_json,
    _task_lock,
    read_task,
)
from util.qa.validation import (
    _line_names,
    _own_lines,
    _read_observations,
    _scene_check,
    _validate_deep_result,
    _validate_screen_result,
    _validate_sweep_result,
)
from util.rpgmaker_qa_manifest import QUOTED_TRANSFORMS, resolve_pointer


def accept_result(task_dir: str | Path, result_path: str | Path) -> dict[str, Any]:
    return _accept(task_dir, _read_json(Path(result_path).expanduser().resolve()))


def _accept(task_dir: str | Path, result: dict[str, Any]) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, task, checkpoint = _load_task(root)
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
        # The same reason for the same line is already evidence.
        if _observation_key(observation) in {
            _observation_key(row) for row in checkpoint.get("observations") or []
        }:
            return observation
        _note_observations(checkpoint, [observation], checkpoint["stage"], str(worker or ""))
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        _issue_new_evidence(root, checkpoint)
    return observation


class _TaskLines:
    """A task's inventory as lines named from outside it: every name of each
    line, and where each line's English lives in the game."""

    def __init__(self, manifest: dict[str, Any]):
        self.names = _line_names(manifest)
        self.lines = {
            record["identity"]: (
                record["file"],
                record["live_pointers"],
                record["live_transform"],
                record["live"],
            )
            for record in manifest["records"]
        }
        self.files = {row["path"]: row["sha256"] for row in manifest["files"]}
        # Each cluster's text, as the task's ledger keys it.
        self.pairs = {
            cluster["representative"]: _pair_key(cluster["source"], cluster["live"])
            for cluster in manifest["clusters"]
        }

    def identities(self, name: str) -> set[str]:
        """The lines a name holds: an identity, or a shorter name."""
        if name in self.lines:
            return {name}
        return self.names.get(name.split("@", 1)[0], set())


# The app asks after the same task on every poll, and a task's inventory
# never changes, so its lines are read once.
_TASK_LINES: dict[Path, tuple[tuple[int, int], _TaskLines]] = {}
# Lines whose English changed since their task's inventory, by task, data
# file and that file's SHA-256.
_CHANGED: dict[tuple[Path, str, str], dict[str, bool]] = {}


def _task_lines(root: Path) -> _TaskLines:
    path = root / "inventory.json"
    info = path.stat()
    key = (info.st_mtime_ns, info.st_size)
    saved = _TASK_LINES.get(root)
    if not saved or saved[0] != key:
        if len(_TASK_LINES) >= 4:
            _TASK_LINES.clear()
        saved = _TASK_LINES[root] = (key, _TaskLines(_read_json(path)))
    return saved[1]


def observed_lines(
    task_dir: str | Path, judged: bool = False
) -> dict[str, set[str]]:
    """The lines a task already observes, under every name an observation
    may give them, such as `States.json#/42/message1`, each with the reasons
    it was observed for; with *judged*, those it left out instead, since an
    earlier review had judged them for the same text."""
    root = Path(task_dir).expanduser().resolve()
    _root, _task, checkpoint = read_task(root)
    notes: dict[str, set[str]] = defaultdict(set)
    for row in checkpoint.get(JUDGED_BEFORE if judged else "observations") or []:
        notes[row["identity"]].add(row["note"])
    return _named(root, notes)


def _named(root: Path, notes: dict[str, set[str]]) -> dict[str, set[str]]:
    """Reasons by line identity, under every name of each line too."""
    if not notes:
        return {}
    found = {identity: set(held) for identity, held in notes.items()}
    for name, lines in _task_lines(root).names.items():
        if held := lines & notes.keys():
            found.setdefault(name, set()).update(*(notes[line] for line in held))
    return found


def corrected_lines(
    task_dir: str | Path, hashes: dict[str, str]
) -> dict[str, set[str]]:
    """The lines a complete task observes and its deep review corrected,
    under every name, with the reasons, once the game's text changed since:
    a line that still holds the text the task reviewed never got that
    correction, and preparing QA again makes a task that takes it back.
    *hashes* holds each data file's SHA-256 by its path in the data folder;
    while the game's data is as the task read it, preparing again resumes
    this task, so none counts."""
    root = Path(task_dir).expanduser().resolve()
    lines = _task_lines(root)
    if all(hashes.get(path, digest) == digest for path, digest in lines.files.items()):
        return {}
    ledger = _task_ledger(root)
    corrected = set((ledger or {}).get("corrected") or [])
    if not corrected:
        return {}
    _root, _task, checkpoint = read_task(root)
    notes: dict[str, set[str]] = defaultdict(set)
    for row in checkpoint.get("observations") or []:
        pair = lines.pairs.get(row.get("cluster_id"))
        if pair and _sha256(f"{pair}\0{row['note']}")[:32] in corrected:
            notes[row["identity"]].add(row["note"])
    return _named(root, notes)


def observed_names(task_dir: str | Path) -> set[str]:
    """The lines a task already observes, under every name an observation
    may give them."""
    return set(observed_lines(task_dir))


def held_names(task_dir: str | Path, names: Iterable[str]) -> set[str]:
    """Of these names of lines, such as the playtest's findings, those that
    name one line of the task's inventory, which QA can take."""
    lines = _task_lines(Path(task_dir).expanduser().resolve())
    return {name for name in names if len(lines.identities(name)) == 1}


def changed_names(
    task_dir: str | Path, names: Iterable[str], hashes: dict[str, str] | None = None
) -> set[str]:
    """Of these names of lines the task's inventory holds, those whose English
    in the game is no longer the text the task reviewed, as once one of its
    corrections is in. *hashes*, each data file's SHA-256 by its path in the
    game's data folder, spares reading a file still as the inventory read it."""
    root = Path(task_dir).expanduser().resolve()
    lines = _task_lines(root)
    data = Path(_read_json(root / "task.json")["data_root"])
    documents: dict[str, Any] = {}

    def changed(identity: str) -> bool:
        file, pointers, transform, reviewed = lines.lines[identity]
        digest = (hashes or {}).get(file)
        if digest is not None and digest == lines.files.get(file):
            return False
        if digest is None:
            try:
                digest = _sha256((data / file).read_bytes())
            except OSError:
                return True
        cached = _CHANGED.setdefault((root, file, digest), {})
        if identity not in cached:
            if file not in documents:
                try:
                    documents[file] = json.loads(
                        (data / file).read_text(encoding="utf-8-sig")
                    )
                except (OSError, ValueError):
                    documents[file] = None
            try:
                current = "\n".join(
                    resolve_pointer(documents[file], pointer) for pointer in pointers
                )
                if transform in QUOTED_TRANSFORMS:
                    match = _QUOTED_VALUE_RE.search(current)
                    current = match.group(2) if match else current
                cached[identity] = current != reviewed
            except (KeyError, IndexError, TypeError, ValueError):
                cached[identity] = True
        return cached[identity]

    if len(_CHANGED) >= 64:
        _CHANGED.clear()
    return {
        name for name in names
        if any(changed(identity) for identity in lines.identities(name))
    }
