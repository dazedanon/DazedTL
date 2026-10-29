"""Public application views; legacy worker records never cross the UI boundary."""

import errno
import os
from pathlib import Path

from dazedtl.api.contracts import ContractViolation
from dazedtl.api.contracts.runs import RunEstimate
from dazedtl.compatibility.original_record import RecordPending

ESTIMATE_FIELDS = RunEstimate.__required_keys__ | RunEstimate.__optional_keys__


def pick(value, names):
    return {name: value[name] for name in names if name in value}


def project(value):
    if value is None:
        return None
    value = {
        **value,
        "method": value.get("method")
        if value.get("method") in {"guided", "len"}
        else None,
    }
    return pick(
        value,
        (
            "id",
            "name",
            "source",
            "engine",
            "engine_label",
            "method",
            "phase",
            "available",
            "status",
            "detail",
            "operation",
            "originals",
            "next_label",
            "languages",
        ),
    )


def application(value):
    return {
        "project": project(value["project"]),
        "recent": [project(item) for item in value["recent"]],
        "screen": value["screen"],
        "running": value["running"],
        "observing": value["observing"],
        "provider_ready": value["provider_ready"],
    }


def documents(value):
    return {
        name: pick(document, ("text", "revision", "path"))
        for name, document in value.items()
    }


def job(value):
    if value is None:
        return None
    result = pick(
        value,
        (
            "id",
            "status",
            "workerStatus",
            "message",
            "label",
            "mode",
            "phase",
            "model",
            "files",
            "progress",
            "itemProgress",
            "log",
            "estimate",
            "outputs",
            "outputsAvailable",
            "availableOutputs",
            "changedOutputs",
            "partialOutputs",
            "retiredFiles",
            "eventTextReview",
            "approval",
            "action",
            "result",
            "created",
            "updated",
            "logicalPhase",
            "scopeComplete",
            "appliedOutputs",
            "process",
            "preparationMode",
            "nothingToTranslate",
            "temporary",
            "nameTranslation",
            "repeatSubmission",
        ),
    )
    result.setdefault("log", [])
    if result.get("estimate"):
        # Runs saved by earlier versions keep estimate fields since removed.
        result["estimate"] = pick(result["estimate"], ESTIMATE_FIELDS)
    return result


def guided(value, project_id):
    native = value["project"]
    return {
        "projectId": project_id,
        "source": native["source"],
        "engine": native["engine"],
        "dataPath": native["data"],
        "encrypted": native["encrypted"],
        "hasPlugins": bool(native["plugins"]),
        "acePacking": value["ace_packing"],
        "step": value["step"],
        "task": value["task"],
        "positions": value["positions"],
        "contextDocument": value["context_document"],
        "form": value["form"],
        "preparation": value["preparation"],
        "preferences": value["preferences"],
        "optionsDraft": value["options_draft"],
        "speakerSetup": value["speaker_setup"],
        "speakerScan": speaker_scan(value["speaker_scan"]),
        "contextSetup": value["context_setup"],
        "eventText": value["event_text"],
        "fullEstimate": full_estimate(value["full_estimate"]),
        "engineSchema": value["engine_schema"],
        "files": [
            pick(item, ("name", "title", "default", "size", "group"))
            for item in native["files"]
        ],
        "selection": native["selected"],
        "importedFiles": native["imported"],
        "collectionError": native.get("collection_error", ""),
        "operations": [job(item) for item in value["jobs"]],
        "run": job(value["manual_job"]),
        "runs": [job(item) for item in value["runs"]],
        "activeJobId": value["active"] or None,
        "phase": value["phase"],
        "phaseFiles": value["phase_files"],
        "estimates": {
            phase: {"job": job(quote["job"]), "current": quote["current"]}
            for phase, quote in value["estimates"].items()
        },
        "phaseRuns": {phase: job(run) for phase, run in value["phase_runs"].items()},
        "comparisons": value["comparisons"],
        "sourceStatus": value["source_status"],
        "readiness": value["readiness"],
        "documents": documents(value["documents"]),
        "drafts": documents(value.get("draft", {}).get("documents", {})),
        "tools": value["tools"],
        "artifacts": value["artifacts"],
        "references": [
            pick(item, ("id", "title")) for item in value.get("references", [])
        ],
        "referenceFolders": value.get("reference_folders", []),
        "provider": {
            "model": value["provider"]["model"],
            "connection": value["provider"]["connection"],
            "defaultMode": value["provider"]["default_mode"],
            "batchUnavailable": value["provider"]["batch_unavailable"],
            "batchUnread": value["provider"]["batch_unread"],
            "ready": value["provider"]["credential_ready"],
            "enabled": value["allow_providers"],
        },
    }


def speaker_scan(value):
    return {**value, "job": job(value["job"])}


def full_estimate(value):
    attempt = value["job"]
    status = (
        "none"
        if attempt is None
        else {"running": "working", "complete": "complete", "stopped": "stopped"}.get(
            attempt["status"], "failed"
        )
    )
    progress = (attempt or {}).get("activity")
    return {
        "status": status,
        "message": attempt["message"] if attempt else "",
        "started": attempt["created"] if attempt else None,
        # Earlier versions saved no activity; a finished attempt has none.
        "progress": progress
        if status == "working" and isinstance(progress, dict)
        else None,
        "stopping": bool((attempt or {}).get("stopping")) and status == "working",
        "result": pick(value["result"], ("model", "batchSupported", "tasks"))
        if value["result"]
        else None,
        "finished": value["finished"],
        "took": value["took"],
        "current": value["current"],
    }


def settings(value):
    return pick(
        value,
        (
            "revision",
            "values",
            "modelOptions",
            "defaultEntriesPerRequest",
            "defaultOutputTokens",
            "defaultBatchInputTokens",
            "draft",
            "activeConnectionId",
            "connections",
            "providers",
            "checksEnabled",
            "gameUpdate",
        ),
    )


def openrouter_hosts(value):
    return [pick(host, ("slug", "name")) for host in value]


def image_action(value):
    # A copied task also reports its request and report files, which the
    # assistant reads from the task text.
    return pick(value, ("state", "result", "text", "requestId", "preview", "message"))


def preview(value):
    return pick(
        value,
        (
            "token",
            "action",
            "label",
            "destination",
            "files",
            "paths",
            "options",
            "confirmation",
            "publication",
            "additions",
            "package",
            "overwrite",
            "game_version",
            "estimate",
            "run",
        ),
    )


_REASONS = {
    errno.EACCES: "it is read-only or not allowed to change",
    errno.EPERM: "it is read-only or not allowed to change",
    errno.EROFS: "the location is read-only",
    errno.ENOSPC: "the disk is full",
    errno.ENOENT: "it no longer exists",
    errno.EBUSY: "another program is using it",
    errno.ETXTBSY: "another program is using it",
    errno.ENAMETOOLONG: "the path is too long",
}


def _shown_file(path, roots):
    """The file as the user knows it: relative to its game or profile folder,
    and nothing at all when it lies elsewhere."""
    try:
        file = Path(os.fsdecode(path))
    except TypeError, ValueError:
        return None
    for root in roots:
        try:
            return file.relative_to(root).as_posix()
        except ValueError:
            continue
    return None


def _storage(exc, roots):
    reason = _REASONS.get(exc.errno)
    if reason is None and getattr(exc, "winerror", None) in {5, 32, 33}:
        reason = "it is read-only or another program is using it"
    file = _shown_file(exc.filename, roots) if exc.filename else None
    if file and reason:
        return f"Could not write {file}: {reason}."
    if file:
        return f"Could not write {file}."
    if reason:
        return f"A file operation failed: {reason}."
    return "The file operation could not finish."


def error(exc, roots=()):
    """The page's version of a failure. `roots` are the game and profile
    folders whose files may be named; no message names a path outside them."""
    if isinstance(exc, ContractViolation):
        # Only raised when development checks are on; show which field drifted.
        return {"code": "internal", "message": str(exc)}
    if isinstance(exc, FileNotFoundError) and not exc.filename:
        return {"code": "not_found", "message": str(exc)}
    if isinstance(exc, RecordPending):
        return {"code": "recording", "message": str(exc)}
    # `user_facing` marks errors worded for the user (Git workflow errors).
    if isinstance(exc, ValueError) or getattr(exc, "user_facing", False):
        return {"code": "validation", "message": str(exc)}
    if isinstance(exc, OSError):
        return {"code": "storage", "message": _storage(exc, roots)}
    return {"code": "internal", "message": "The operation could not finish."}
