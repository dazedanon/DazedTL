"""The editorial round, which judges proposed corrections, and finishing a
task with its findings."""

from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

from util import rpgmaker_qa_lint as lint
from util.qa.advance import _advance_unlocked, _settle_declined
from util.qa.bundles import _bundle_items, _declined_items, _write_bundles
from util.qa.findings import _draft_document, _number_findings
from util.qa.fitting import (
    _box,
    _fit_corrections,
    _record_problems,
    correction_problems,
)
from util.qa.interface import _interface_after
from util.qa.pace import _not_translated_report, status
from util.qa.records import _changes, _finding_families, _record_maps
from util.qa.reopen import _follow_up
from util.qa.schema import (
    DEFAULT_DEEP_CHAR_BUDGET,
    DEFAULT_DEEP_ITEM_LIMIT,
    EDITORIAL_JUDGMENT_CATEGORIES,
    EDITORIAL_RESULT_SCHEMA,
    QAResultError,
    _utc_now,
)
from util.qa.selection import (
    _lint_game,
    _nearby_commands,
    _scene_position,
    _scene_records,
)
from util.qa.storage import (
    _atomic_write_json,
    _decisions,
    _load_task,
    _read_json,
    _task_lock,
    task_json,
)
from util.qa.validation import _consistency_conflicts, _simulate_apply

EDITORIAL_VERDICTS = frozenset({"accept", "revise", "withdraw"})
# Editorial rounds that only settle conflicting corrections, before those are
# left unverified.
EDITORIAL_CONFLICT_ROUNDS = 3


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
    task = task_json(root)
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
    by its command and current text takes its replacement, on which only
    the automatic lint families compose again (see _judged_findings); one
    put back to its current text is left out."""
    revised = {
        (row["command"], row["current"]): row["replacement"] for row in replacements
    }
    lines = [dict(line) for line in lines]
    for line in lines:
        key = (line["command"], line["current"])
        if key in revised:
            line["correction"] = revised[key]
            _keep_automatic_lint(line)
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


class _Judged(NamedTuple):
    """The draft's findings after editorial's verdicts."""

    # The findings that stand, as reviewers revised them, with lint remnants.
    final: list[dict[str, Any]]
    withdrawn: list[dict[str, Any]]
    unverified: list[dict[str, Any]]
    # The lint remnants still to compose; each is in final too.
    remnants: list[dict[str, Any]]
    # The findings no editorial reviewer has judged yet.
    unjudged: set[str]


def _judged_findings(
    findings: list[dict[str, Any]],
    verdicts: dict[str, list[dict[str, Any]]],
    set_aside: set[str],
    checkpoint: dict[str, Any],
) -> _Judged:
    """Each draft finding after its editorial verdicts, in round order.

    A withdrawn finding leaves its line the lint fixes it was given, as a
    remnant a conflict may show editorial; a verdict on the remnant counts
    like any other, so a withdrawn one stays withdrawn. A revision replaces
    a correction the reviewer saw with its lint fixes in it, so only the
    automatic families, which are always right, compose on it again.
    """
    final, withdrawn, unverified, remnants = [], [], [], []
    unjudged: set[str] = set()
    for finding in findings:
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
                    "summary": (summary := " ".join(
                        lint.FAMILIES[family]["description"]
                        for family in finding["lint_families"]
                    )),
                    "evidence": summary,
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
                _keep_automatic_lint(finding)
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
    composing, gone = [], set()
    for remnant in remnants:
        verdict = (verdicts.get(remnant["id"]) or [None])[-1]
        if verdict and verdict["verdict"] == "withdraw":
            withdrawn.append({
                "id": remnant["id"], "note": verdict["note"],
                "reviewer": verdict["reviewer"],
            })
            gone.add(remnant["id"])
        elif verdict and verdict["verdict"] == "revise":
            remnant["correction"] = verdict["replacement"]
        else:
            composing.append(remnant)
    final = [finding for finding in final if finding["id"] not in gone]
    return _Judged(final, withdrawn, unverified, composing, unjudged)


def _keep_automatic_lint(change: dict[str, Any]) -> None:
    """Drop the reviewed lint families of a change a reviewer revised."""
    families = [
        family for family in change.pop("lint_families", None) or []
        if family in lint.AUTOMATIC
    ]
    if families:
        change["lint_families"] = families


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
    judged = _judged_findings(draft["findings"], verdicts, set_aside, checkpoint)
    final, withdrawn, unverified, remnants, unjudged = judged
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
    not_corrected = copy.deepcopy(draft.get("not_corrected") or [])
    _fit_corrections(final, questions + not_corrected, records, clusters, layout)
    _simulate_apply(final, records, layout)
    document = {
        **draft,
        "created_at": _utc_now(),
        "findings": final,
        "uncertain_playtests": questions,
        "not_corrected": not_corrected,
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


def finalize(task_dir: str | Path, skip_declined: bool = False) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        return _finalize_unlocked(root, skip_declined)
