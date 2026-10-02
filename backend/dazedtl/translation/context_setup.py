"""Verified context investigation receipts and explicit review choices, separate from engine text."""
from pathlib import Path
import json
import re
import uuid

from dazedtl.storage import write_json
from .files import digest, project_path, read_json

REPORT = ".dazedtl/guided/context-findings.json"
CORE = ("glossary", "quirks", "game")
WIDTHS = ("width", "faceWidth", "listWidth", "noteWidth")
DEFAULT_WIDTHS = dict(zip(WIDTHS, (60, 50, 100, 75)))


def request(path, project_id, speaker_request):
    previous = read_json(path) if path.exists() else {}
    if previous.get("project_id") == project_id and previous.get("speaker_request_id") == speaker_request["request_id"]:
        return previous
    value = {"version": 1, "request_id": uuid.uuid4().hex, "project_id": project_id,
             "speaker_request_id": speaker_request["request_id"]}
    write_json(path, value)
    return value


def inspect(request_path, review_path, native, project_id, documents, findings, scan, observed_digest, references=()):
    request_value = read_json(request_path) if request_path.exists() else {}
    reviews = read_json(review_path) if review_path.exists() else {}
    document_states = {}
    for name, document in documents.items():
        path = project_path(native["source"], str(Path(document["path"]).relative_to(native["source"])), exists=False)
        choice = reviews.get("documents", {}).get(name, {})
        scope = digest({"engine_options": native.get("engine_options", {}), "phase1_comments": native.get("phase1_comments", False)})
        current = choice.get("revision") == document["revision"] and choice.get("scope") == scope
        document_states[name] = {"exists": path.is_file(), "reviewed": current and path.is_file(), "needsReview": bool(choice) and not current,
                                 "intentionalEmpty": current and path.is_file() and choice.get("choice") == "empty" and not document["text"].strip()}
    result = {"status": "waiting" if request_value else "missing", "message": "Waiting for the investigation's saved context results.",
              "requestId": request_value.get("request_id"), "speakerReportId": findings.get("reportId"),
              "referencesSha256": digest(references), "scanSha256": ((scan.get("job") or {}).get("result") or {}).get("artifact_sha256") if scan.get("current") else None,
              "documents": document_states, "revisions": {name: doc["revision"] for name, doc in documents.items()},
              "layoutRevision": digest(native["widths"]), "layout": None, "layoutStatus": "saved" if reviews.get("layout") == digest(native["widths"]) or native["widths"] != DEFAULT_WIDTHS else "defaults"}
    path = project_path(native["source"], REPORT, exists=False)
    if not request_value or not path.is_file():
        return result
    try:
        report = read_json(path, limit=200_000)
        if not isinstance(report, dict) or set(report) != {"version", "request_id", "project_id", "speaker_report_id", "scan_sha256", "references_sha256", "documents", "layout"}:
            raise ValueError("The context completion record is incomplete.")
        if type(report["version"]) is not int or report["version"] != 1 or report["request_id"] != request_value["request_id"] or report["project_id"] != project_id:
            raise ValueError("The completion record belongs to another investigation.")
        if report["references_sha256"] != result["referencesSha256"]:
            return {**result, "status": "stale", "message": "Reference translations changed. Refresh the affected context investigation."}
        rows = report["documents"]
        if not isinstance(rows, dict) or not set(CORE).issubset(rows) or set(rows) - set(documents):
            raise ValueError("Record glossary, quirks and game context, including any intentionally empty document.")
        for name, row in rows.items():
            if not isinstance(row, dict) or set(row) != {"revision", "status"} or row["status"] not in {"created", "updated", "unchanged", "intentionally_empty"}:
                raise ValueError("Each document needs its final revision and outcome.")
            if row["revision"] != documents[name]["revision"] or not document_states[name]["exists"]:
                return {**result, "status": "stale", "message": "Saved guidance changed or is missing. Refresh the affected investigation results."}
            if (row["status"] == "intentionally_empty") != (not documents[name]["text"].strip()):
                raise ValueError("Empty guidance needs an explicit intentionally_empty outcome.")
        layout = report["layout"]
        if layout is not None:
            if not isinstance(layout, dict) or set(layout) != {"widths", "reason", "evidence"} or not isinstance(layout["widths"], dict) or set(layout["widths"]) != set(WIDTHS):
                raise ValueError("Layout recommendations need four widths, a reason and source evidence.")
            if any(type(value) is not int or not 20 <= value <= 300 for value in layout["widths"].values()) or layout["widths"]["faceWidth"] > layout["widths"]["width"]:
                raise ValueError("Layout recommendations contain invalid character limits.")
            if not isinstance(layout["reason"], str) or not 1 <= len(layout["reason"].strip()) <= 4000 or not isinstance(layout["evidence"], list) or not 1 <= len(layout["evidence"]) <= 20:
                raise ValueError("Layout recommendations need a reason and inspected source evidence.")
            for ref in layout["evidence"]:
                if not isinstance(ref, dict) or set(ref) != {"file", "sha256", "location"} or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) or not isinstance(ref["location"], str) or not 1 <= len(ref["location"].strip()) <= 1000:
                    raise ValueError("Layout evidence needs a source path, hash and location.")
                if (not isinstance(ref["file"], str) or len(ref["file"]) > 2000
                        or any(part.startswith(".") for part in ref["file"].split("/"))
                        or Path(ref["file"]).suffix.lower() not in {".json", ".js", ".rb", ".ini", ".ttf", ".otf"}):
                    raise ValueError("Cite inspected game sources or fonts for layout recommendations.")
                if observed_digest(project_path(native["source"], ref["file"])) != ref["sha256"]:
                    return {**result, "status": "stale", "message": "Layout evidence changed. Refresh its recommendations before using them."}
        if findings["status"] not in {"ready", "applied"} or not scan["current"] or report["speaker_report_id"] != findings["reportId"] or report["scan_sha256"] != result["scanSha256"]:
            return {**result, "status": "stale", "message": "Name scan needs refreshing. Saved guidance is retained for review."}
        for name, row in rows.items():
            document_states[name]["intentionalEmpty"] |= row["status"] == "intentionally_empty"
        return {**result, "status": "ready", "message": "Current speaker scan and all saved context results verified.", "layout": layout}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {**result, "status": "invalid", "message": str(exc) if isinstance(exc, ValueError) else "Check the saved context completion record."}


def review(path, documents, native, name, revision, choice):
    value = read_json(path) if path.exists() else {}
    if choice == "layout":
        if name != "layout" or revision != digest(native["widths"]):
            raise ValueError("Layout values changed. Review the current values before continuing.")
        value["layout"] = revision
    else:
        if choice not in {"empty", "review"} or name not in documents or revision != documents[name]["revision"]:
            raise ValueError("Saved guidance changed. Reload before reviewing it.")
        if choice == "empty" and (documents[name]["text"].strip() or not Path(documents[name]["path"]).is_file()):
            raise ValueError("Save an empty guidance document before keeping it intentionally empty.")
        value.setdefault("documents", {})[name] = {"revision": revision, "choice": choice,
            "scope": digest({"engine_options": native.get("engine_options", {}), "phase1_comments": native.get("phase1_comments", False)})}
    write_json(path, value)
    return {"saved": True}


def instructions(value, command):
    example = {"version": 1, "request_id": value["request_id"], "project_id": value["project_id"],
               "speaker_report_id": "FINAL_SPEAKER_REPORT_ID", "scan_sha256": "FINAL_SCAN_SHA256", "references_sha256": "FINAL_REFERENCES_SHA256",
               "documents": {name: {"revision": "FINAL_DOCUMENT_REVISION", "status": "updated"} for name in CORE}, "layout": None}
    return f"""
## Save the complete investigation result

After the local speaker scan, finish the glossary, voice, game context and width investigation.
Keep the shared glossary's category headers and `source (translation)` entry format; character notes stay on that entry's line.
Do not convert it to a Markdown table or JSON. Preserve existing spellings unless the source justifies a correction.
Save guidance through the existing portable document paths. Read `{command}` for the final document revisions,
current speakerReportId, scanSha256 and referencesSha256. If any document is intentionally empty, save an empty file and record
`intentionally_empty`; otherwise record `created`, `updated` or `unchanged`. Include all three core documents
and any custom documents you investigated. An unchanged file still requires investigation, not mere existence.
Atomically save `{REPORT}` in the game with these exact identity fields and final values:

```json
{json.dumps(example, ensure_ascii=False, indent=2)}
```

If the first investigation produced measured width recommendations, replace layout null with
{{"widths": {{"width": 60, "faceWidth": 50, "listWidth": 100, "noteWidth": 75}},
"reason": "Actual measurement method, confidence, font and exceptions.",
"evidence": [{{"file": "js/rpg_windows.js", "sha256": "FINAL_FILE_HASH", "location": "Inspected window functions"}}]}}.
Those values are schema examples, not measurements. Use only measured values with source evidence;
otherwise keep layout null and explain unresolved geometry in the game-context document.
Read `{command}` again and resolve any stale or invalid result before reporting completion.
Do not execute translation, paid name translation, API submission, or playtesting as part of this setup task.
"""
