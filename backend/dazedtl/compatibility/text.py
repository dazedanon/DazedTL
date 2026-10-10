"""Preserved fitting and QA validators, with app-owned runtime publication."""

import difflib
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation import publication
from dazedtl.translation.files import decode_json, digest, project_path, read_json

# Where each QA stage stands for the page's activity line.
ACTIVITY_STAGES = ("screen", "deep", "sweep", "editorial")


def _finding_kind(row):
    """How a finding came to be, for the audit log's grouping."""
    if row.get("kind") == "show-text" or row.get("source_fix"):
        return "source"
    if row.get("lint_only"):
        return "lint"
    if row.get("sweep_families"):
        return "sweep"
    return "review"


def _task_record(folder, name, task):
    path = Path(folder) / name
    return (read_json(path) if path.exists() else {}).get(task)


def binding(plan):
    guard = {
        key: value
        for key, value in plan["guard"].items()
        if key not in {"files", "translated", "variables"}
    }
    index = Path(plan["folder"]) / "source-inputs.json"
    return {
        "source": plan["project"]["source"],
        "project": plan["project_id"],
        "guard": guard,
        "source_inputs": digest(index.read_bytes()) if index.exists() else None,
    }


def qa_handoff(task, helper="project.py qa"):
    """The text a coding assistant receives for one prepared QA task, from
    the QA policy that also makes its README."""
    from util import rpgmaker_qa as qa

    return qa.handoff_text(task, helper)


def qa_state(plan):
    from util import rpgmaker_qa as qa

    pointer = Path(plan["folder"]) / (
        "text-qa-" + plan["options"].get("focus", "release") + ".json"
    )
    if not pointer.exists():
        return {
            "current": False,
            "applied": False,
            "status": {},
            "findings": [],
            "questions": [],
            "message": "No QA task prepared for this focus.",
        }
    saved = read_json(pointer)
    storage = Path(plan["folder"]) / "text-qa"
    task_path = project_path(
        storage, (Path(saved["task"]).relative_to(storage) / "task.json").as_posix()
    ).parent
    immutable = saved.get("immutable", {})
    if set(immutable) != {
        "task.json",
        "inventory.json",
        "context.json",
        "screen-index.json",
    } or any(
        digest(project_path(task_path, name).read_bytes()) != expected
        for name, expected in immutable.items()
    ):
        raise ValueError(
            "The immutable QA task evidence changed. Prepare current QA before using these reports."
        )
    # A task from before an update still shows what it found and applied,
    # though only a task prepared with the current rules can continue.
    root, task, _checkpoint = qa._read_task(task_path)
    if (
        task["game_root"] != plan["project"]["source"]
        or task["data_root"] != plan["project"]["data"]
    ):
        raise ValueError("The QA task belongs to another project.")
    rules_changed = task["engine_fingerprint"] != qa._engine_fingerprint()
    current = saved["binding"] == binding(plan) and not rules_changed
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    if document and (
        document.get("schema") != qa.FINDINGS_SCHEMA
        or document.get("task_sha256") != qa._sha256(qa._canonical_bytes(task))
    ):
        raise ValueError("Saved findings belong to another QA task.")
    # Batches applied or undone from this task, oldest first; a restored one
    # counts for neither. Records saved before batches named their task count
    # when made after it was prepared.
    prepared = datetime.fromisoformat(task["created_at"]).timestamp()
    rows = [
        row
        for row in publication.history(plan["folder"])
        if row["kind"] in {"qa_apply", "qa_undo"}
        and row["state"] == "complete"
        and (row["task"] == str(root) if "task" in row else row["created"] >= prepared)
    ]
    every = [row["id"] for row in document.get("findings", [])]
    applied_ids, undone_ids = set(), set()
    for row in sorted(rows, key=lambda row: row["created"]):
        named = set(row.get("findings") or every)
        if row["kind"] == "qa_apply":
            applied_ids |= named
            undone_ids -= named
        else:
            undone_ids |= named
    applied = any(row["kind"] == "qa_apply" for row in rows)

    def finding_state(identity):
        return (
            "undone"
            if identity in undone_ids
            else "applied"
            if identity in applied_ids
            else ""
        )

    findings = []
    for row in document.get("findings", []):
        targets = row.get("target_identities") or []
        files = sorted(
            {identity.split("#", 1)[0] for identity in targets}
            or ({row["file"]} if row.get("file") else set())
        )
        findings.append(
            {
                "id": row["id"],
                "source": row["source"],
                "current": row["current"],
                "correction": row["correction"],
                "category": row["category"],
                "severity": row["severity"],
                "family": row.get("family_key") or "",
                "kind": _finding_kind(row),
                "places": max(1, len(targets)),
                "files": files,
                "reason": row.get("evidence") or "",
                **(
                    {"editorial": row["editorial"]["note"]}
                    if (row.get("editorial") or {}).get("note")
                    else {}
                ),
                **(
                    {"state": finding_state(row["id"])}
                    if finding_state(row["id"])
                    else {}
                ),
            }
        )
    choices = _task_record(plan["folder"], "text-qa-choices.json", str(root)) or {}
    questions = [
        {
            "id": row["id"],
            "source": row.get("source", ""),
            "current": row.get("current", ""),
            "reason": row.get("evidence") or "",
            "places": int(row.get("places") or 1),
            **({"proposal": row["correction"]} if row.get("correction") else {}),
            **({"choice": choices[row["id"]]} if row["id"] in choices else {}),
            **({"state": finding_state(row["id"])} if finding_state(row["id"]) else {}),
        }
        for row in document.get("uncertain_playtests", [])
    ]
    engine_status = qa.status(root)
    stage = engine_status.get("stage", "")
    reviewed = set(
        _task_record(plan["folder"], "text-qa-reviewed.json", str(root)) or []
    )
    unreviewed = [
        row
        for row in document.get("not_reviewed", [])
        if row["identity"] not in reviewed
    ]
    activity = {}
    if stage in ACTIVITY_STAGES:
        counts = engine_status[stage]
        total = (
            max(counts["total"], counts.get("projected", 0))
            if stage == "deep"
            else counts["total"]
        )
        lint = engine_status["screen"]["lint"]
        if stage == "screen" and lint["accepted"] < lint["total"]:
            # Lint families lead the screen bundles; the line names them.
            stage, counts, total = "lint", lint, lint["total"]
        activity = {
            "stage": stage,
            "done": counts["accepted"],
            "total": total,
            **(
                {"eta_seconds": int(engine_status["estimate"]["eta_seconds"])}
                if engine_status["estimate"]["eta_seconds"] is not None
                else {}
            ),
        }
    return {
        "current": current,
        "applied": applied,
        "task": str(root),
        "status": engine_status,
        "findings": findings,
        "questions": questions,
        **(
            {
                "coverage": {
                    "lines": int((task.get("counts") or {}).get("records", 0)),
                    "not_reviewed": len(unreviewed),
                    "preflight": sum((task.get("preflight") or {}).values()),
                }
            }
            if document
            else {}
        ),
        **({"activity": activity} if activity else {}),
        **({"rules_changed": True} if rules_changed else {}),
        "message": "Saved results match current project text."
        if current
        else "An update changed QA's rules after this task was prepared."
        if rules_changed
        else "The game text changed since this QA task was prepared.",
    }


def qa_report(plan):
    """What QA could not cover: lines no reviewer judged, with whether the user
    reviewed them, and Japanese QA cannot correct."""
    from util import rpgmaker_qa as qa

    state = qa_state(plan)
    if not state.get("task"):
        raise ValueError("Prepare text QA first.")
    root = Path(state["task"])
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    reviewed = set(
        _task_record(plan["folder"], "text-qa-reviewed.json", str(root)) or []
    )
    preflight = qa._read_json(root / "preflight.json")
    return {
        "not_reviewed": [
            {**row, "reviewed": row["identity"] in reviewed}
            for row in document.get("not_reviewed", [])
        ],
        "preflight": [
            {key: row[key] for key in ("file", "pointer", "kind", "text")}
            for name in ("untranslated", "custom_data", "plugin_parameters")
            for row in preflight.get(name, [])
        ],
        "preflight_total": sum(preflight.get("counts", {}).values()),
    }


def run_qa(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util import rpgmaker_qa as qa

    validate_plan(plan)
    folder = Path(plan["folder"])
    if plan["action"] == "qa_prepare":
        task, _state = qa.prepare_task(
            plan["project"]["source"],
            plan["project"]["data"],
            plan["options"]["focus"],
            folder / "text-qa",
        )
        manifest = qa.build_manifest(plan["project"]["data"], plan["options"]["focus"])
        descriptor = read_json(task / "task.json")
        if (
            descriptor["manifest_sha256"] != manifest["content_sha256"]
            or read_json(task / "inventory.json") != manifest
        ):
            raise ValueError(
                "The cached QA inventory changed. Retain it for investigation and prepare a fresh task."
            )
        immutable = {
            name: digest(project_path(task, name).read_bytes())
            for name in (
                "task.json",
                "inventory.json",
                "context.json",
                "screen-index.json",
            )
        }
        write_json(
            folder / ("text-qa-" + plan["options"]["focus"] + ".json"),
            {"task": str(task), "binding": binding(plan), "immutable": immutable},
        )
        handoff = qa_handoff(task)
    else:
        handoff = None
    result = qa_state(plan)
    if handoff:
        result["handoff"] = handoff
    log(result["message"])
    return result


def prepare_publication(plan):
    from desktop.backend.workflow_actions import validate_plan

    validate_plan(plan)
    root, data, folder = (
        Path(plan["project"]["source"]),
        Path(plan["project"]["data"]),
        Path(plan["folder"]),
    )
    action, options = plan["action"], plan["options"]
    prefix = data.relative_to(root)
    candidates, outputs, restored = {}, {}, None
    if action == "export_selected":
        saved = plan.get("run_output")
        output_folder = Path(saved["folder"]) if saved else folder
        for name in options["files"]:
            output = project_path(output_folder, "translated/" + name).read_bytes()
            if saved and digest(output) != saved["outputs"].get(name):
                raise ValueError("Saved Batch output changed. Review this Batch again.")
            # Parse the same bytes that will be frozen for publication.
            if len(output) > 128_000_000:
                raise ValueError(
                    "Choose a JSON output within the supported size limit."
                )
            decode_json(output)
            candidates[(prefix / name).as_posix()] = output
            outputs[name] = digest(output)
    elif action == "runtime_restore":
        candidates, restored = publication.restore_candidates(
            folder, root, options["publication"]
        )
    elif action == "rewrap_apply":
        from util.rpgmaker_rewrap import (
            RewrapOptions,
            parse_event_codes,
            rewrap_directory,
        )

        widths = options["widths"]
        settings = RewrapOptions(
            widths["width"],
            widths["faceWidth"],
            widths["listWidth"],
            widths["noteWidth"],
            categories=frozenset(options["categories"]),
            event_codes=parse_event_codes(options["codes"]),
            max_protected_rows=options["max_rows"] if options["protect_rows"] else 0,
            skip_protected_overflow=options["protect_rows"],
            only_over_limit=options["over_limit"],
        )
        with tempfile.TemporaryDirectory(dir=folder, prefix="fitting-") as temporary:
            staging = Path(temporary)
            for name in options["files"]:
                shutil.copyfile(
                    project_path(root, (prefix / name).as_posix()), staging / name
                )
            report = rewrap_directory(
                staging, settings, file_names=options["files"], apply=True
            )
            if report.errors:
                raise ValueError("; ".join(report.errors))
            for name in options["files"]:
                raw = (staging / name).read_bytes()
                if raw != (data / name).read_bytes():
                    candidates[(prefix / name).as_posix()] = raw
        if not candidates:
            raise ValueError(
                "No fitting edits are eligible. Protected row overflows were skipped; review the text or fitting settings and scan again."
            )
    elif action in {"qa_apply", "qa_undo"}:
        from util import rpgmaker_qa as qa

        state = qa_state(plan)
        if action == "qa_apply" and not state["current"]:
            raise ValueError(state["message"])
        if options.get("task") != state["task"]:
            raise ValueError(
                "The QA task changed. Choose corrections from the current findings."
            )
        if state.get("rules_changed"):
            raise ValueError(
                "An update changed QA's rules after these corrections were applied, so "
                "Undo is no longer available. Run QA again to check the text."
            )
        task_root, task, _checkpoint = qa._load_task(state["task"])
        chosen = options.get("findings", [])
        proposals = options.get("proposals", [])
        if (
            not isinstance(chosen, list)
            or not isinstance(proposals, list)
            or not chosen + proposals
            or len(set(chosen + proposals)) != len(chosen + proposals)
            or any(not isinstance(value, str) for value in chosen + proposals)
        ):
            raise ValueError("Choose the corrections to apply or undo.")
        states = {row["id"]: row.get("state", "") for row in state["findings"]}
        wanted = "applied" if action == "qa_undo" else ""
        if any(states.get(value, "missing") != wanted for value in chosen + proposals):
            raise ValueError(
                "Only applied corrections can be undone."
                if action == "qa_undo"
                else "The chosen QA corrections changed. Refresh findings."
            )
        try:
            selected = qa.correction_map(
                task_root, chosen, proposals, undo=action == "qa_undo"
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        with tempfile.TemporaryDirectory(
            dir=folder, prefix="qa-candidates-"
        ) as temporary:
            staging = Path(temporary)
            scratch = staging / "data"
            scratch.mkdir()
            for path in data.glob("*.json"):
                shutil.copyfile(
                    project_path(root, path.relative_to(root).as_posix()),
                    scratch / path.name,
                )
            write_json(
                staging / "inventory.json", read_json(task_root / "inventory.json")
            )
            scratch_task = {**task, "data_root": str(scratch)}
            try:
                qa._apply_loaded_correction_map(
                    staging,
                    scratch_task,
                    selected,
                    read_json(task_root / "inventory.json"),
                    dry_run_name="dry-run.json",
                    regression_name="regression.json",
                    nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
                )
            except ValueError as exc:
                if action == "qa_undo" and "Expected" in str(exc):
                    raise ValueError(
                        "A line changed in the game since QA corrected it, so the "
                        "correction can't be undone here. Use History or edit it."
                    ) from exc
                raise
            for name in {row["file"] for row in selected["operations"]}:
                candidates[(prefix / name).as_posix()] = project_path(
                    scratch, name
                ).read_bytes()
    else:
        raise ValueError("Unknown text publication.")
    frozen = publication.freeze(
        folder,
        root,
        candidates,
        action,
        outputs=outputs,
        restore=restored,
        overwrite=action == "export_selected",
        task=options["task"] if action in {"qa_apply", "qa_undo"} else None,
        findings=options.get("findings", []) + options.get("proposals", [])
        if action in {"qa_apply", "qa_undo"}
        else None,
    )
    if action == "export_selected":
        plan["overwrite_runtime"] = True
    plan["publication"] = frozen
    previous = (
        read_json(folder / "applied-outputs.json").get("files", {})
        if (folder / "applied-outputs.json").exists()
        else {}
    )
    rows = []
    for row in frozen["files"]:
        name = Path(row["path"]).name
        raw = project_path(root, row["path"]).read_bytes()
        candidate = (
            folder / "text-publications" / frozen["id"] / f"{row['index']}.after"
        ).read_bytes()
        lines = difflib.unified_diff(
            raw.decode("utf-8-sig").splitlines(),
            candidate.decode("utf-8-sig").splitlines(),
            fromfile="Current runtime",
            tofile="Reviewed replacement",
            lineterm="",
            n=2,
        )
        diff, length, truncated = [], 0, False
        for line in lines:
            length += len(line) + 1
            if length > 16000:
                truncated = True
                break
            diff.append(line)
        # The frozen row's index and mode stay internal to publication.
        rows.append(
            {
                **{key: row[key] for key in ("path", "before", "after", "size")},
                "destination": str(root / row["path"]),
                "later_edits": action == "export_selected"
                and name in previous
                and digest(raw) != previous[name],
                "diff": "\n".join(diff),
                "truncated": truncated,
                "before_text": raw.decode("utf-8-sig")[:16000],
                "after_text": candidate.decode("utf-8-sig")[:16000],
            }
        )
    return {
        "publication": rows,
        "paths": [row["path"] for row in rows],
        "files": len(rows),
    }


def run_publication(plan, log):
    validate_publication(plan)
    result = publication.publish(
        plan["folder"], plan["project"]["source"], plan["publication"], log
    )
    return {**result, "ace_packing_required": plan["project"]["engine"] == "ACE"}


def validate_publication(plan):
    from desktop.backend.workflow_actions import action_guard, validate_plan

    if plan.get("overwrite_runtime") and plan.get("action") == "export_selected":
        current = action_guard(plan["project"], plan["folder"])
        if {key: value for key, value in current.items() if key != "data"} != {
            key: value for key, value in plan["guard"].items() if key != "data"
        }:
            raise ValueError(
                "The saved output, destination or settings changed. Review Apply again."
            )
    else:
        validate_plan(plan)
