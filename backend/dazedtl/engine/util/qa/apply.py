"""The user's decisions, correction maps, applying corrections to a game's
data, and the regression check after."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from util.paths import unlink_with_retry
from util.qa.fitting import (
    _disallowed_flags,
    _flag_details,
    _message_record,
    _operation_writes,
    _written,
)
from util.qa.ledger import REVIEWED_FILE
from util.qa.records import _changes, _set_pointer
from util.qa.schema import (
    CORRECTION_MAP_SCHEMA,
    REGRESSION_SCHEMA,
    _canonical_bytes,
    _sha256,
    _utc_now,
)
from util.qa.storage import (
    ANSWERS,
    ANSWERS_FILE,
    ANSWERS_SCHEMA,
    DECISIONS_FILE,
    DECISIONS_SCHEMA,
    _atomic_write_json,
    _decisions,
    _load_task,
    _read_json,
    _read_task,
    _task_lock,
    answers,
)
from util.rpgmaker_qa_manifest import _mechanical_evidence, build_manifest
from util.rpgmaker_qa_verify import verify_manifest


def answer(task_dir: str | Path, question: str, choice: str) -> dict[str, str]:
    """Record the user's answer to one of a task's questions. A kept line is
    judged as it is, so the task's ledger is derived again with it."""
    root = Path(task_dir).expanduser().resolve()
    if choice not in ANSWERS:
        raise ValueError("Keep the current text, or use the reviewer's proposal.")
    # The lock would make a folder that is not there.
    _read_task(root)
    with _task_lock(root):
        saved = {**answers(root), str(question): choice}
        _atomic_write_json(
            root / ANSWERS_FILE, {"schema": ANSWERS_SCHEMA, "answers": saved}
        )
        if (root / REVIEWED_FILE).is_file():
            unlink_with_retry(root / REVIEWED_FILE)
    return saved


def record_decision(
    task_dir: str | Path,
    key: str,
    choice: str,
    worker: str,
    source: str = "",
    translation: str = "",
) -> list[dict[str, Any]]:
    """Record a choice every reviewer follows, such as narration tense or a
    quoted label; with a source and translation it is also checked."""
    root = Path(task_dir).expanduser().resolve()
    key, choice = str(key).strip(), str(choice).strip()
    if not 0 < len(key) <= 120 or not 0 < len(choice) <= 500 or "\n" in key + choice:
        raise ValueError("A decision needs a one-line key and choice")
    if bool(source) != bool(translation):
        raise ValueError("A checked decision needs both its source and translation")
    with _task_lock(root):
        _load_task(root)
        path = root / DECISIONS_FILE
        document = (
            _read_json(path) if path.is_file()
            else {"schema": DECISIONS_SCHEMA, "decisions": []}
        )
        document["decisions"].append({
            "key": key,
            "choice": choice,
            "worker": str(worker or ""),
            "at": _utc_now(),
            **({"source": source, "translation": translation} if source else {}),
        })
        _atomic_write_json(path, document)
    return _decisions(root)


def correction_map(
    task_dir: str | Path,
    approved_finding_ids: Iterable[str],
    chosen_proposals: Iterable[str] = (),
    *,
    undo: bool = False,
) -> dict[str, Any]:
    """The checksummed operations that apply the approved findings, with the
    open questions whose proposal the user chose, or with `undo` put their
    lines back.

    It is built in memory for the app's apply, which runs it on disposable
    copies and publishes the result; no QA command writes the game itself.
    """
    # A finished task's findings apply under any rules version, since apply
    # checks them with the current rules.
    root, task, checkpoint = _read_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA review must be complete before its findings are applied")
    findings_doc = _read_json(root / "findings.json")
    approved = set(approved_finding_ids)
    selected = [item for item in findings_doc["findings"] if item["id"] in approved]
    if {item["id"] for item in selected} != approved:
        raise ValueError("One or more approved finding IDs do not exist")
    manifest_clusters = {
        cluster["representative"]: cluster
        for cluster in _read_json(root / "inventory.json")["clusters"]
    }
    questions = {
        row["id"]: row for row in findings_doc.get("uncertain_playtests") or []
    }
    for question_id in chosen_proposals:
        question = questions.get(question_id)
        if not question or not question.get("correction"):
            raise ValueError("A chosen proposal no longer exists")
        cluster = manifest_clusters[question_id]
        selected.append({
            "id": question_id,
            "source": question["source"],
            "current": question["current"],
            "correction": question["correction"],
            "target_identities": [
                identity for identity in cluster["identities"]
                if identity not in {
                    row["identity"] for row in findings_doc.get("not_reviewed") or []
                }
            ],
        })
    manifest = _read_json(root / "inventory.json")
    records = {record["identity"]: record for record in manifest["records"]}
    operations = []
    targets: dict[tuple[str, tuple[str, ...]], str] = {}
    for finding in selected:
        if finding.get("kind") == "show-text":
            operations.append({
                "finding_id": finding["id"],
                "kind": "show-text",
                "identity": finding["nameplate_identity"],
                "file": finding["file"],
                "pointer": finding["pointer"],
                "expected": finding["current_parameters"],
                "replacement": finding["parameters"],
                # Narration's header loses its name on purpose.
                "allowed_flags": ["empty-live"] if finding["parameters"][4] == "" else [],
            })
            continue
        # A scene correction's lines apply and undo together as one finding.
        for change in _changes(finding):
            for identity in change["identities"]:
                record = records[identity]
                target = (record["file"], tuple(record["live_pointers"]))
                previous = targets.get(target)
                if previous is not None and previous != change["correction"]:
                    raise ValueError(
                        f"Approved findings propose conflicting corrections for {identity}"
                    )
                if previous is not None:
                    continue
                targets[target] = change["correction"]
                # The replacement reads as it will once written, so undoing
                # it finds it there.
                replacement = _written(record, change["correction"], task["layout"])
                message = len(record["live_pointers"]) > 1 and _message_record(record)
                operations.append({
                    "finding_id": finding["id"],
                    "identity": identity,
                    "file": record["file"],
                    "live_pointers": record["live_pointers"],
                    "live_transform": record["live_transform"],
                    "expected": record["live"],
                    "replacement": replacement,
                    "allowed_flags": list(finding.get("allowed_flags") or []),
                    **({"message": True} if message else {}),
                })
    if undo:
        # Each operation puts back the text it replaced.
        for operation in operations:
            operation["expected"], operation["replacement"] = (
                operation["replacement"], operation["expected"]
            )
            operation["allowed_flags"] = []
    document = {
        "schema": CORRECTION_MAP_SCHEMA,
        "created_at": _utc_now(),
        "manifest_sha256": task["manifest_sha256"],
        "approved_finding_ids": sorted(approved | set(chosen_proposals)),
        **({"mode": "undo"} if undo else {}),
        "operations": operations,
    }
    document["content_sha256"] = _sha256(_canonical_bytes(document))
    return document


def _has_suspicious_length_ratio(source: Any, live: Any) -> bool:
    source_text = str(source or "")
    live_text = str(live or "")
    if len(source_text) < 8 or not live_text:
        return False
    ratio = len(live_text) / len(source_text)
    return ratio < 0.35 or ratio > 3.0


def _validate_correction_map(
    correction_map: dict[str, Any], task: dict[str, Any]
) -> None:
    if correction_map.get("schema") != CORRECTION_MAP_SCHEMA:
        raise ValueError("Correction map has an unsupported schema")
    checksum_value = dict(correction_map)
    claimed_checksum = checksum_value.pop("content_sha256", "")
    if claimed_checksum != _sha256(_canonical_bytes(checksum_value)):
        raise ValueError("Correction map checksum does not match its contents")
    if correction_map.get("manifest_sha256") != task["manifest_sha256"]:
        raise ValueError("Correction map does not match this QA inventory")


def _dry_run_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    report_name: str,
) -> dict[str, Any]:
    _validate_correction_map(correction_map, task)

    data_root = Path(task["data_root"]).resolve()
    inventory_records = {
        item["identity"]: item
        for item in _read_json(root / "inventory.json").get("records") or []
    }
    documents: dict[str, Any] = {}
    preview = []
    warnings = []
    pointer_targets: dict[tuple[str, str], str] = {}
    for operation in correction_map.get("operations") or []:
        filename = str(operation.get("file") or "")
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        if filename not in documents:
            documents[filename] = json.loads(path.read_text(encoding="utf-8-sig"))
        for pointer, replacement in _operation_writes(documents[filename], operation):
            target = (filename, pointer)
            previous = pointer_targets.get(target)
            overlapping = any(
                other_file == filename and (
                    other.startswith(pointer + "/") or pointer.startswith(other + "/")
                )
                for other_file, other in pointer_targets
            )
            if overlapping or previous is not None and previous != replacement:
                raise ValueError(f"Conflicting approved corrections target {filename}#{pointer}")
            pointer_targets[target] = replacement
        preview.append({
            "finding_id": operation["finding_id"],
            "identity": operation["identity"],
            "file": filename,
            "live_pointers": operation.get("live_pointers") or [operation["pointer"]],
            "expected": operation["expected"],
            "replacement": operation["replacement"],
        })
        if operation.get("kind") == "show-text":
            continue
        baseline = inventory_records.get(operation["identity"]) or {}
        baseline_flags = set(
            (baseline.get("mechanical") or {}).get("flags") or []
        )
        if (
            "suspicious-length-ratio" not in baseline_flags
            and _has_suspicious_length_ratio(
                baseline.get("source"), operation["replacement"]
            )
        ):
            warnings.append(
                "approved correction projects a non-blocking mechanical flag: "
                f"{operation['identity']} suspicious-length-ratio"
            )
    report = {
        "schema": "rpgmaker-qa-correction-dry-run-v1",
        "created_at": _utc_now(),
        "valid": True,
        "operation_count": len(preview),
        "file_count": len(documents),
        "warnings": warnings,
        "operations": preview,
    }
    _atomic_write_json(root / report_name, report)
    return report


def _render_json_like(raw: bytes, document: Any) -> bytes:
    """Render JSON using the file's existing BOM, indentation, and final newline."""
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = raw.decode("utf-8-sig")
    indent_match = re.search(r"\n([ \t]+)[\"\[\]{}]", decoded)
    indent: int | str | None
    if indent_match:
        token = indent_match.group(1)
        indent = token if "\t" in token else len(token)
    else:
        indent = None
    rendered = json.dumps(
        document,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )
    if decoded.endswith("\r\n"):
        rendered = rendered.replace("\n", "\r\n") + "\r\n"
    elif decoded.endswith("\n"):
        rendered += "\n"
    payload = rendered.encode("utf-8")
    return (b"\xef\xbb\xbf" + payload) if has_bom else payload


def _apply_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    before: dict[str, Any],
    *,
    dry_run_name: str,
    regression_name: str,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Apply one validated map atomically and roll back on regression failure."""
    _dry_run_loaded_correction_map(root, task, correction_map, dry_run_name)
    data_root = Path(task["data_root"]).resolve()
    by_file: dict[str, list[dict]] = defaultdict(list)
    for operation in correction_map["operations"]:
        by_file[operation["file"]].append(operation)
    originals: dict[Path, bytes] = {}
    rendered: dict[Path, bytes] = {}
    applied = 0
    for filename, operations in sorted(by_file.items()):
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        raw = path.read_bytes()
        originals[path] = raw
        document = json.loads(raw.decode("utf-8-sig"))
        for operation in operations:
            for pointer, replacement in _operation_writes(document, operation):
                _set_pointer(document, pointer, replacement)
            applied += 1
        rendered[path] = _render_json_like(raw, document)
    temporaries: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, raw in rendered.items():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".qa.tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            json.loads(temporary.read_text(encoding="utf-8-sig"))
            temporaries[path] = temporary
        for path, temporary in temporaries.items():
            temporary.replace(path)
            replaced.append(path)
    except Exception:
        for path in replaced:
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(originals[path])
            rollback.replace(path)
        raise
    finally:
        for temporary in temporaries.values():
            temporary.unlink(missing_ok=True)
    regression = _regression_check_loaded(
        task,
        before,
        correction_map,
        nonblocking_introduced_flags=nonblocking_introduced_flags,
    )
    if not regression["valid"]:
        for path, raw in originals.items():
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(raw)
            rollback.replace(path)
        regression["rolled_back"] = True
        _atomic_write_json(root / regression_name, regression)
        raise ValueError("QA regression failed; all game-file changes were rolled back")
    regression["applied_operations"] = applied
    _atomic_write_json(root / regression_name, regression)
    return regression


def _regression_check_loaded(
    task: dict[str, Any],
    before: dict[str, Any],
    corrections: dict[str, Any] | None,
    *,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    after = build_manifest(task["data_root"], task["focus"])
    validation = verify_manifest(task["data_root"], after)
    before_records = {item["identity"]: item for item in before["records"]}
    after_records = {item["identity"]: item for item in after["records"]}
    errors = list(validation.get("errors") or [])
    warnings = []
    if set(before_records) != set(after_records):
        errors.append("source identity coverage changed after corrections")
    for identity in sorted(set(before_records) & set(after_records)):
        if before_records[identity]["source_sha256"] != after_records[identity]["source_sha256"]:
            errors.append(f"preserved source changed: {identity}")
    if corrections is not None:
        for operation in corrections.get("operations") or []:
            header = operation.get("kind") == "show-text"
            if header and not operation["identity"]:
                # A header without a translated name has no record to check.
                continue
            record = after_records.get(operation["identity"])
            expected = operation["replacement"][4] if header else operation["replacement"]
            if record is None or record["live"] != expected:
                errors.append(f"approved correction is missing: {operation['identity']}")
                continue
            # The text QA reviewed, flagged by the current rules as the
            # correction is, whichever rules made its inventory.
            before_record = before_records.get(operation["identity"])
            before_flags = set(
                _mechanical_evidence(
                    before_record["source"],
                    before_record["live"],
                    before_record.get("event_code"),
                )["flags"]
                if before_record
                else ()
            )
            after_flags = set(record.get("mechanical", {}).get("flags") or [])
            introduced_flags = _disallowed_flags(
                after_flags - before_flags, operation.get("allowed_flags") or (),
                record["source"], record["live"],
            )
            warning_flags = sorted(
                introduced_flags & nonblocking_introduced_flags
            )
            blocking_flags = sorted(
                introduced_flags - nonblocking_introduced_flags
            )
            if warning_flags:
                warnings.append(
                    "approved correction introduced non-blocking mechanical flags: "
                    f"{operation['identity']} " + ", ".join(warning_flags)
                )
            if blocking_flags:
                errors.append(
                    "approved correction introduced mechanical flags: "
                    f"{operation['identity']} "
                    + _flag_details(blocking_flags, record["source"], record["live"])
                )
    return {
        "schema": REGRESSION_SCHEMA,
        "created_at": _utc_now(),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "before_manifest_sha256": before["content_sha256"],
        "after_manifest_sha256": after["content_sha256"],
        "records_checked": len(after_records),
    }
