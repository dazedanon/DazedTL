"""Public application views; legacy worker records never cross the UI boundary."""

from dazedtl.api.contracts import ContractViolation
from dazedtl.api.contracts.runs import RunEstimate

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
            "next_label",
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
        "aceAvailable": value["ace_available"],
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
            "batchSupported": value["provider"]["batch_supported"],
            "batchReason": value["provider"].get("batch_reason", ""),
            "ready": value["provider"]["credential_ready"],
            "enabled": value["allow_providers"],
        },
    }


def speaker_scan(value):
    return {**value, "job": job(value["job"])}


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
        ),
    )


def openrouter_hosts(value):
    return [pick(host, ("slug", "name")) for host in value]


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
            "rewrap",
            "publication",
            "additions",
            "package",
            "overwrite",
            "game_version",
            "estimate",
            "run",
        ),
    )


def error(exc):
    if isinstance(exc, ContractViolation):
        # Only raised when development checks are on; show which field drifted.
        return {"code": "internal", "message": str(exc)}
    if isinstance(exc, FileNotFoundError):
        return {"code": "not_found", "message": str(exc)}
    if isinstance(exc, ValueError):
        return {"code": "validation", "message": str(exc)}
    if isinstance(exc, OSError):
        return {"code": "storage", "message": "The file operation could not finish."}
    return {"code": "internal", "message": "The operation could not finish."}
