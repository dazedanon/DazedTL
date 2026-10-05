"""Preserved fitting and QA validators, with app-owned runtime publication."""

import difflib
import shutil
import tempfile
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation import publication
from dazedtl.translation.files import decode_json, digest, project_path, read_json


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


def qa_state(plan):
    from util import rpgmaker_qa as qa

    pointer = Path(plan["folder"]) / (
        "text-qa-" + plan["options"].get("focus", "release") + ".json"
    )
    if not pointer.exists():
        return {
            "current": False,
            "status": {},
            "findings": [],
            "corrections": [],
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
    root, task, checkpoint = qa._load_task(task_path)
    if (
        task["game_root"] != plan["project"]["source"]
        or task["data_root"] != plan["project"]["data"]
    ):
        raise ValueError("The QA task belongs to another project.")
    current = saved["binding"] == binding(plan)
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    if document and (
        document.get("schema") != qa.FINDINGS_SCHEMA
        or document.get("task_sha256") != qa._sha256(qa._canonical_bytes(task))
    ):
        raise ValueError("Saved findings belong to another QA task.")
    findings = document.get("findings", []) + [
        {**row, "classification": "Uncertain - excluded from corrections"}
        for row in document.get("uncertain_playtests", [])
    ]
    corrections = []
    path = root / "correction-map.json"
    if path.exists() and checkpoint["stage"] == "complete":
        document = read_json(path)
        qa._validate_correction_map(document, task)
        corrections = document.get("operations", [])
    return {
        "current": current,
        "task": str(root),
        "status": qa.status(root),
        "findings": findings,
        "corrections": corrections,
        "message": "Saved results match current project text."
        if current
        else "Project text or source context changed. Prepare current QA before applying corrections.",
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
        handoff = (
            "This is optional DazedTL text QA. Follow the task README for immutable inventory, screen and deep discovery, findings and correction-map validation only. "
            "Do not run apply, editorial-apply, or any runtime publication command. Do not edit the game. "
            "Stop after discovery and correction-map preparation. The user selects corrections and reviews Apply in DazedTL. "
            "Never claim copying this task completes QA.\n\nTask: "
            + str(task)
            + "\nREADME: "
            + str(task / "README.md")
        )
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
    elif action == "qa_apply":
        from util import rpgmaker_qa as qa

        state = qa_state(plan)
        if not state["current"]:
            raise ValueError(state["message"])
        if options.get("task") != state["task"]:
            raise ValueError(
                "The QA task changed. Choose corrections from the current findings."
            )
        task_root, task, _checkpoint = qa._load_task(state["task"])
        chosen = options.get("findings")
        if (
            not isinstance(chosen, list)
            or not chosen
            or len(set(chosen)) != len(chosen)
            or any(not isinstance(value, str) for value in chosen)
        ):
            raise ValueError("Choose correction IDs to apply.")
        corrections = read_json(task_root / "correction-map.json")
        available = {row["finding_id"] for row in corrections["operations"]}
        if set(chosen) - available:
            raise ValueError("The chosen QA corrections changed. Refresh findings.")
        selected = {
            **corrections,
            "approved_finding_ids": sorted(chosen),
            "operations": [
                row for row in corrections["operations"] if row["finding_id"] in chosen
            ],
        }
        selected.pop("content_sha256", None)
        selected["content_sha256"] = qa._sha256(qa._canonical_bytes(selected))
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
            qa._apply_loaded_correction_map(
                staging,
                scratch_task,
                selected,
                read_json(task_root / "inventory.json"),
                dry_run_name="dry-run.json",
                regression_name="regression.json",
                nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
            )
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
        rows.append(
            {
                **row,
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
