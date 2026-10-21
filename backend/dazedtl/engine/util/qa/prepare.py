"""Preparing a task: task keys and folders, reuse of earlier tasks, and the
inventory and bundles a new task starts with."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from util import system
from util.freshness import Basis, compare
from util.paths import new_folder
from util.rpgmaker_qa_manifest import QUOTED_TRANSFORMS, build_manifest, write_manifest
from util.rpgmaker_qa_verify import verify_manifest
from util.rpgmaker_qa_preflight import preflight
from util.qa.schema import (
    _canonical_bytes,
    CHECKPOINT_SCHEMA,
    DEFAULT_SCREEN_CHAR_BUDGET,
    DEFAULT_SCREEN_ITEM_LIMIT,
    QA_RULES_VERSION,
    QAResultError,
    _sha256,
    TASK_SCHEMA,
    _utc_now,
)
from util.qa.storage import (
    _atomic_write_json,
    _atomic_write_text,
    _decisions,
    DECISIONS_FILE,
    DECISIONS_SCHEMA,
    JUDGED_BEFORE,
    _observation_key,
    _read_json,
    _rules_version,
    _safe_task_root,
    _slug,
    _task_lock,
)
from util.qa.records import _record_maps
from util.qa.fitting import task_layout
from util.qa.selection import (
    _cluster_by_identity,
    _compact_items,
    _context_pack,
    _database_checks,
    _forced_deep_reasons,
    _lint_game,
    _lint_items,
    _screen_items,
)
from util.qa.interface import (
    _capture_round,
    _fit_checks,
    INTERFACE_FOLDER,
    _save_capture_record,
)
from util.qa.ledger import (
    BASELINE_FOLDER,
    _baseline_ledger,
    _Reviewed,
    REVIEWED_SCHEMA,
    _task_ledger,
)
from util.qa.bundles import (
    _bundle_items,
    _candidate,
    _header_flags,
    _merge_candidate,
    _regrouped,
    _write_bundles,
)
from util.qa.validation import _read_observations
from util.qa.pace import status, _write_report
from util.qa.advance import _screen_targets
from util.qa.reopen import _note_observations, _observe_again, _recapture
from util.qa.briefs import _task_instructions


# A task's folder is named by its key; the app sets aside a task it can't
# trust under another name, and a task being prepared has a staging name.
_TASK_FOLDER_RE = re.compile(r"[0-9a-f]{16}")
# Beside a focus's tasks, the scope the user named last: the key of a review
# of every line, or none once a `since` named earlier text checked.
SCOPE_FILE = "scope.json"
# Beside a focus's tasks, the key of the one preparing QA returned last; the
# others are replaced, and a helper still holding one's path is sent on.
CURRENT_FILE = "current.json"


def replaced_by(task_dir: str | Path) -> Path | None:
    """The task preparing QA again made current in this one's place, or None
    while this one is current, or none is recorded or it is gone, as when the
    app set it aside."""
    root = Path(task_dir).expanduser().resolve()
    try:
        key = str(_read_json(root.parent / CURRENT_FILE).get("task") or "")
    except (OSError, ValueError, AttributeError):
        return None
    current = root.parent / key
    if (
        key == root.name
        or not _TASK_FOLDER_RE.fullmatch(key)
        or not (current / "task.json").is_file()
    ):
        return None
    return current


def require_current(task_dir: str | Path) -> None:
    """Refuses work on a task a newer one replaced, naming the newer one, so
    a helper can't review, report or finish the wrong task."""
    if current := replaced_by(task_dir):
        raise ValueError(
            "QA was prepared again, and a newer task replaced this one; run "
            f"this command with --task {current} and follow {current / 'README.md'}"
        )


def _task_basis(
    rules: str,
    focus: str,
    inventory: str,
    context: str,
    screen_configuration: dict[str, Any],
) -> str:
    """What names a task: its rules, focus, inventory and context hashes and
    how its screen is packed."""
    return (
        f"{TASK_SCHEMA}\0{rules}\0{focus}\0{inventory}\0{context}\0"
        f"{_sha256(_canonical_bytes(screen_configuration))}"
    )


def _task_keys(basis: str, baselines: list[str]) -> tuple[str, str]:
    """The keys of a task reviewing every line and of one building on earlier
    reviews and *baselines*."""
    return (
        _sha256(basis + "\0everything")[:16],
        _sha256(
            basis + (f"\0baselines:{','.join(baselines)}" if baselines else "")
        )[:16],
    )


def _fingerprinted_tasks(
    task_parent: Path,
    manifest: dict[str, Any],
    context: dict[str, Any],
    screen_configuration: dict[str, Any],
    baselines: list[str],
) -> dict[str, str]:
    """Tasks of these inputs that 2.24.0 and earlier made, by scope:
    "everything" or "scoped", the one prepared last of each.

    Those versions put a hash of QA's code files in a task's key, with the
    hash of its whole inventory. Each task's key made again from what its
    task.json recorded says which scope it has, here under *baselines*, and
    its inventory must hold the same text.
    """
    try:
        current = str(_read_json(task_parent / CURRENT_FILE).get("task") or "")
    except (OSError, ValueError, AttributeError):
        current = ""
    found: dict[str, list[tuple[bool, str, str]]] = {}
    text = None
    for path in task_parent.iterdir():
        if not _TASK_FOLDER_RE.fullmatch(path.name):
            continue
        try:
            task = _read_json(path / "task.json")
            fingerprint = task.get("engine_fingerprint")
            if (
                task.get("schema") != TASK_SCHEMA
                or not isinstance(fingerprint, str)
                or "rules_version" in task
                or task.get("focus") != manifest["focus"]
                or task.get("context_sha256") != context["content_sha256"]
                or task.get("screen_configuration") != screen_configuration
                or (task.get("counts") or {}).get("records")
                != manifest["counts"]["records"]
            ):
                continue
            everything, scoped = _task_keys(
                _task_basis(
                    fingerprint,
                    task["focus"],
                    task["manifest_sha256"],
                    task["context_sha256"],
                    task["screen_configuration"],
                ),
                baselines,
            )
            scope = {everything: "everything", scoped: "scoped"}.get(path.name)
            if scope is None:
                continue
            text = text or _inventory_text(manifest)
            if _inventory_text(_read_json(path / "inventory.json")) != text:
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        found.setdefault(scope, []).append(
            (path.name == current, str(task.get("created_at") or ""), path.name)
        )
    return {scope: max(tasks)[2] for scope, tasks in found.items()}


def _last_scope(path: Path) -> str | None:
    """The review of every line the user chose last, "" once they named
    another scope, or None before either."""
    try:
        return str(_read_json(path).get("everything") or "")
    except (OSError, ValueError, AttributeError):
        return None


def _earlier_reviews(
    games: Path,
    context: dict[str, Any],
    layout: dict[str, Any],
    origins: set[str] | None = None,
) -> _Reviewed:
    """The reviews a new task builds on: every complete task of this game and
    every baseline the user named, or only those *origins* names, each task's
    with the decisions its reviewers recorded."""
    ledgers = [
        {**ledger, "decisions": _decisions(task.parent)}
        for task in sorted(games.glob("*/*/task.json"))
        if _TASK_FOLDER_RE.fullmatch(task.parent.name)
        and (origins is None or f"task {task.parent.name}" in origins)
        and (ledger := _task_ledger(task.parent))
    ]
    for path in sorted((games / BASELINE_FOLDER).glob("*.json")):
        try:
            ledger = _read_json(path)
        except (OSError, ValueError):
            continue
        if ledger.get("schema") == REVIEWED_SCHEMA and (
            origins is None or ledger.get("origin") in origins
        ):
            ledgers.append(ledger)
    return _Reviewed(ledgers, context, layout)


def _baseline_origin(path: Path) -> str | None:
    try:
        return _read_json(path).get("origin")
    except (OSError, ValueError):
        return None


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
    origins: Iterable[str] | None = None,
    screen_groups: list[list[str]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create or reuse one immutable QA task and its exhaustive screen bundles.

    A new task builds on [earlier reviews](#earlier-reviews): lines a complete
    task of this game reviewed, unchanged since and with the same glossary
    entries and quirks, are read only as context, and so are lines unchanged
    since a baseline the user named once with *since*, a version this game was
    updated to or a Git revision, whose earlier text was checked before. A
    baseline stays in effect for the game's later tasks. *earlier* False
    reviews everything, and preparing again without a new *since* goes on
    with that review while the text is the same. *origins* limits the earlier
    reviews to those a task names as its `reviewed_before`, as a task rebuilt
    from another reads what that one read.

    *fit* holds the Line widths the task fits corrections to; a task already
    prepared keeps the ones it was made with.
    With *interface*, the game's interface screens are captured, and text the
    game squeezes or cuts off on them goes to deep review with its captures;
    *progress* hears which screen the capture is on. A task prepared again
    captures them again once the game's plugin files changed since, keeping
    its review.

    Observations made outside QA, such as the release playtest's findings in
    translated text, start in its checkpoint, so deep review takes their lines;
    one a line the inventory lacks is left out. A task prepared again keeps
    the observations it holds and takes those of lines it does not observe
    yet, at once while it reviews and in a follow-up deep round once
    complete.

    *kept* names the plugin settings the plugin task keeps in Japanese on
    purpose, which the never-translated report leaves out. A task prepared
    again keeps its review, but reads that report again, since plugin
    settings, custom data files and the plugin task's decisions change it
    without changing the inventory.

    *screen_groups*, the items of each screen bundle another task made, packs
    a new task's screen the same way when it holds the same items, so that
    task's screening carries over (see rebuild_deep_from_screen) even where
    the items' hints changed their size.
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
        # A line may hold several problems, each its own reason to review it.
        if all(_observation_key(row) != _observation_key(observation) for row in observed):
            observed.append(observation)
    games = storage / _slug(game.name)
    if since and earlier:
        _baseline_ledger(games, game, data, focus, since)
    if origins is not None:
        origins = set(origins)
    baselines = sorted(
        path.stem for path in (games / BASELINE_FOLDER).glob("*.json")
        if origins is None or _baseline_origin(path) in origins
    ) if earlier else []
    # A task is named by what it reviews and the rules version, never by
    # DazedTL's code: the text its inventory holds rather than what QA derives
    # from it. A baseline is the user's scope, so a task under another is
    # another task; tasks finished since leave a prepared task as it is, and
    # so do observations, which join its review.
    full_review, task_key = _task_keys(
        _task_basis(
            f"rules:{QA_RULES_VERSION}",
            focus,
            _sha256(_canonical_bytes(_inventory_text(manifest))),
            context["content_sha256"],
            screen_configuration,
        ),
        baselines,
    )
    task_parent = games / focus
    task_parent.mkdir(parents=True, exist_ok=True)
    with _task_lock(task_parent):
        # A task an earlier version made of the same inputs goes on.
        if QA_RULES_VERSION == 1 and not all(
            (task_parent / key / "task.json").is_file()
            for key in (full_review, task_key)
        ):
            fingerprinted = _fingerprinted_tasks(
                task_parent, manifest, context, screen_configuration, baselines
            )
            if not (task_parent / full_review / "task.json").is_file():
                full_review = fingerprinted.get("everything", full_review)
            if not (task_parent / task_key / "task.json").is_file():
                task_key = fingerprinted.get("scoped", task_key)
        if not earlier:
            task_key = full_review
        # The scope the user named last goes on while the text is the same: a
        # review of every line, until a `since` names earlier text checked.
        scope = task_parent / SCOPE_FILE
        if not earlier or since:
            _atomic_write_json(scope, {"everything": "" if earlier else full_review})
        elif (task_parent / full_review / "task.json").is_file() and _last_scope(
            scope
        ) in {None, full_review}:
            task_key = full_review
        task_dir = task_parent / task_key
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
            if observed:
                _observe_again(task_dir, observed, observer)
            _atomic_write_json(task_parent / CURRENT_FILE, {"task": task_key})
            return task_dir, status(task_dir)

        staging = new_folder(task_parent, f".{task_key}.")
        try:
            write_manifest(manifest, staging / "inventory.json")
            _atomic_write_json(staging / "inventory-validation.json", validation)
            # Japanese never translated is reported, never silently skipped.
            _atomic_write_json(staging / "preflight.json", preflight(data, manifest, kept))
            _atomic_write_json(staging / "context.json", context)
            reviewed = (
                _earlier_reviews(games, context, layout, origins)
                if earlier else _Reviewed([], context, layout)
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
            # Choices earlier QA of this game settled stay settled: reviewers
            # follow them, and no glossary fix undoes a decided rendering.
            if carried := reviewed.decisions():
                _atomic_write_json(
                    staging / DECISIONS_FILE,
                    {"schema": DECISIONS_SCHEMA, "decisions": carried},
                )
            lint_items, lint_fixes = _lint_items(
                manifest, layout, _lint_game(staging, manifest), reviewed
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
            if screen_groups is not None:
                bundles = _regrouped(bundles, screen_groups)
            items += lint_items
            _atomic_write_json(
                staging / "screen-targets.json", _screen_targets(items, bundles)
            )
            bundle_summaries = _write_bundles(
                staging, bundles, recorded_root=task_dir
            )
            # An observation deep review already judged for the same text is
            # not asked again; the task keeps it apart, so it reads as
            # reviewed and preparing again does not take it either.
            judged = [
                observation for observation in observed
                if reviewed and reviewed.observed(
                    clusters_by_id[observation["cluster_id"]]["source"],
                    clusters_by_id[observation["cluster_id"]]["live"],
                    observation["note"],
                )
            ]
            asked = {
                observation["cluster_id"] for observation in observed
                if observation not in judged
            }
            task = {
                "schema": TASK_SCHEMA,
                "created_at": _utc_now(),
                "game_root": str(game),
                "data_root": str(data),
                "focus": focus,
                "rules_version": QA_RULES_VERSION,
                "screen_configuration": screen_configuration,
                "layout": layout,
                "manifest_sha256": manifest["content_sha256"],
                "context_sha256": context["content_sha256"],
                "screen_index_sha256": screen_index_document["content_sha256"],
                "counts": manifest["counts"],
            }
            if reviewed:
                # Lines as the task counts them: every place a text shows. A
                # line an observation sends to deep review is this task's to
                # check.
                task["reviewed_before"] = {
                    "lines": sum(
                        len(cluster["identities"])
                        for cluster in manifest["clusters"]
                        if reviewed.line(cluster["source"], cluster["live"])
                        and cluster["representative"] not in asked
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
            _note_observations(checkpoint, [
                observation for observation in observed if observation not in judged
            ], "screen", observer)
            if judged:
                checkpoint[JUDGED_BEFORE] = [
                    {key: observation[key] for key in ("identity", "note")}
                    for observation in judged
                ]
            _atomic_write_json(staging / "task.json", task)
            _atomic_write_json(staging / "checkpoint.json", checkpoint)
            _atomic_write_text(
                staging / "README.md", _task_instructions(task_dir, task)
            )
            system.replace(staging, task_dir)
        except Exception:
            if staging.is_dir() and not staging.is_symlink():
                system.remove_tree(staging)
            raise
        _atomic_write_json(task_parent / CURRENT_FILE, {"task": task_key})
    return task_dir, status(task_dir)


def inventory_matches(task_dir: str | Path, manifest: dict[str, Any]) -> bool:
    """Whether a prepared task's inventory is the one it was prepared with
    and holds the text of *manifest*, read from the game now, whichever
    version made it."""
    root = Path(task_dir)
    task = _read_json(root / "task.json")
    inventory = _read_json(root / "inventory.json")
    claimed = inventory.pop("content_sha256", None)

    def text(value: dict[str, Any]) -> str:
        return _sha256(_canonical_bytes(_inventory_text(value)))

    return claimed == _sha256(_canonical_bytes(inventory)) and not compare(
        Basis(_rules_version(task), {"inventory": task.get("manifest_sha256"), "text": text(inventory)}),
        Basis(_rules_version(task), {"inventory": claimed, "text": text(manifest)}),
    )


def _inventory_text(manifest: dict[str, Any]) -> dict[str, Any]:
    """The text an inventory holds and where it lives: each line's Japanese,
    English and places, and whether its English is a script string's inside.
    Not what QA derives from them, which an update may derive otherwise, such
    as mechanical evidence or the transform naming a text variable's quote
    marks, nor the hashes of the extractor's source and of what it made."""
    return {
        "focus": manifest.get("focus"),
        "records": [
            {
                "identity": record["identity"],
                "live": record["live"],
                "live_pointers": record["live_pointers"],
                "event_code": record.get("event_code"),
                "quoted": record["live_transform"] in QUOTED_TRANSFORMS,
            }
            for record in manifest["records"]
        ],
        "unresolved": [
            (entry.get("file"), entry.get("source_pointer"))
            for entry in manifest.get("unresolved") or []
        ],
    }


def find_latest_task(
    output_root: str | Path, game_root: str | Path, focus: str
) -> Path | None:
    base = Path(output_root).expanduser().resolve() / _slug(Path(game_root).name) / focus
    if not base.is_dir():
        return None
    tasks = [path for path in base.iterdir() if (path / "task.json").is_file()]
    return max(tasks, key=lambda path: path.stat().st_mtime) if tasks else None
