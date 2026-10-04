"""Guidance file availability and optional measured layout recommendations."""
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


def retained_documents(source, documents, drafts):
    """Keep missing custom files addressable while their recovery drafts exist."""
    for name in drafts:
        if name.startswith("custom:") and name not in documents:
            path = project_path(source, ".dazedtl/skills/" + name.removeprefix("custom:") + ".md", exists=False)
            documents[name] = {"text": "", "revision": digest(b""), "path": str(path)}
    return documents


def selected_document(path, position, documents):
    value = read_json(path) if path.exists() else {}
    name = value.get("name") if isinstance(value, dict) else None
    if name in documents:
        return name
    return "quirks" if position.get("task") == "guidance" and "quirks" in documents else "glossary"


def request(path, project_id, speaker_request, widths=None):
    previous = read_json(path) if path.exists() else {}
    if (previous.get("project_id") == project_id and previous.get("speaker_request_id") == speaker_request["request_id"]
            and (widths is None or previous.get("widths", widths) == widths)):
        if widths is not None and "widths" not in previous:
            previous["widths"] = dict(widths)
            write_json(path, previous)
        return previous
    value = {"version": 1, "request_id": uuid.uuid4().hex, "project_id": project_id,
             "speaker_request_id": speaker_request["request_id"]}
    if widths is not None:
        value["widths"] = dict(widths)
    write_json(path, value)
    return value


def optional_record(path):
    try:
        value = read_json(path, limit=200_000)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def inspect(request_path, review_path, native, project_id, documents, findings, scan, observed_digest, references=()):
    request_value = optional_record(request_path)
    reviews = optional_record(review_path)
    document_states = {}
    for name, document in documents.items():
        path = project_path(native["source"], str(Path(document["path"]).relative_to(native["source"])), exists=False)
        # Keep the legacy response fields for older clients without retaining
        # document review, empty-choice or conflict state.
        document_states[name] = {"exists": path.is_file(), "reviewed": False, "needsReview": False, "intentionalEmpty": False}
    complete = all(document_states.get(name, {}).get("exists") for name in CORE)
    receipt = native.get("guided_layout", {})
    applied = bool(receipt.get("applied") and native["widths"] == receipt.get("widths"))
    result = {"status": "ready" if complete else "waiting" if request_value else "missing",
              "message": "Guidance files are saved in the game folder." if complete else "Save the glossary, style and game context files when needed.",
              "requestId": request_value.get("request_id"), "speakerReportId": findings.get("reportId"),
              "referencesSha256": digest(references), "scanSha256": ((scan.get("job") or {}).get("result") or {}).get("artifact_sha256") if scan.get("current") else None,
              "documents": document_states, "revisions": {name: doc["revision"] for name, doc in documents.items()},
              "layoutRevision": digest(native["widths"]), "layout": None,
              "layoutReportId": None, "layoutApplication": "applied" if applied else "none", "layoutMessage": "",
              "layoutStatus": "saved" if applied or reviews.get("layout") == digest(native["widths"]) or native["widths"] != DEFAULT_WIDTHS else "defaults"}
    if not request_value:
        return result
    try:
        path = project_path(native["source"], REPORT)
        report = read_json(path, limit=200_000)
        report_id = digest({"request_id": report.get("request_id"), "layout": report.get("layout")}) if isinstance(report, dict) else None
        consumed = receipt.get("reportId") == report_id and report_id is not None
        if (not isinstance(report, dict) or type(report.get("version")) is not int or report["version"] != 1
                or report.get("request_id") != request_value.get("request_id") and not consumed or report.get("project_id") != project_id):
            return result
        layout = report.get("layout")
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
                if not consumed and observed_digest(project_path(native["source"], ref["file"])) != ref["sha256"]:
                    return result
        return {**result, "layout": layout, "layoutReportId": report_id if layout else None,
                "layoutApplication": ("applied" if applied else "manual") if consumed else "pending" if layout else result["layoutApplication"]}
    except (OSError, ValueError, TypeError, KeyError):
        return result


def layout_update(native, setup, request_value):
    """Consume each measured result once and retain edits made after its baseline."""
    layout, report_id = setup.get("layout"), setup.get("layoutReportId")
    previous = native.get("guided_layout", {})
    if not layout or not report_id or previous.get("reportId") == report_id:
        return None
    same_request = previous.get("requestId") == setup["requestId"]
    baseline = previous.get("widths", native["widths"]) if same_request else request_value.get("widths", native["widths"])
    manual = bool(same_request and not previous.get("applied") or native["widths"] != baseline and native["widths"] != layout["widths"])
    return {"reportId": report_id, "requestId": setup["requestId"], "applied": not manual,
            "widths": dict(native["widths"] if manual else layout["widths"])}


def rebase_layout_draft(native, value):
    """Late recovery writes may cross a layout-only revision without losing edits."""
    receipt = native.get("guided_layout", {})
    if (not isinstance(value, dict) or value.get("revision") != receipt.get("beforeRevision")
            or native["revision"] != receipt.get("revision") or receipt.get("revision") == receipt.get("beforeRevision")):
        return value
    values = value["values"]
    widths = native["widths"] if values["widths"] == receipt.get("beforeWidths") else values["widths"]
    return {**value, "revision": native["revision"], "values": {**values, "widths": dict(widths)}}


def review(path, documents, native, name, revision, choice):
    if choice in {"empty", "review"} and name in documents:
        return {"saved": True}  # Older clients no longer need a document receipt.
    if choice != "layout" or name != "layout" or revision != digest(native["widths"]):
        raise ValueError("Layout values changed. Review the current values before saving.")
    write_json(path, {"layout": revision})
    return {"saved": True}


def instructions(value, command):
    return f"""
## Save guidance and optional layout recommendations

Keep this investigation focused on speaker formats, reusable glossary/context, and measured UI layout.
Reuse verified current findings and inspect only the source needed to resolve missing or stale evidence.
For layout, prioritize System resolution/font settings and the relevant window/plugin code.
Inspect font metrics, window skins, portrait or other image dimensions only when they establish an actual
text area's geometry. Skip unrelated artwork, image inventories, broad OCR and image text translation;
those belong to the separate Images stage. Do not edit images or execute the game here.

After the local speaker scan, finish the glossary, voice, game context and width investigation.
Keep the shared glossary's category headers and `source (translation)` entry format; character notes stay on that entry's line.
Do not convert it to a Markdown table or JSON. Preserve existing spellings unless the source justifies a correction.
Save glossary, style and game context through the existing portable document paths, plus any custom guidance
you investigated. An empty file is fine when there is nothing to add. Their presence in the game folder
completes guidance setup; no document hashes, completion report or review receipts are required.
Read `{command}` to confirm the saved files are available.

Do not execute translation, paid name translation, API submission, or playtesting as part of this setup task.
""" + layout_instructions(value, command)


def layout_instructions(value, command):
    example = {"version": 1, "request_id": value["request_id"], "project_id": value["project_id"], "layout": None}
    return f"""
## Save measured character limits

Atomically save measured layout recommendations to `{REPORT}` with these identity fields:

```json
{json.dumps(example, ensure_ascii=False, indent=2)}
```

Replace layout null with the measured values and their evidence:
{{"widths": {{"width": 60, "faceWidth": 50, "listWidth": 100, "noteWidth": 75}},
"reason": "Actual measurement method, confidence, font and exceptions.",
"evidence": [{{"file": "js/rpg_windows.js", "sha256": "FINAL_FILE_HASH", "location": "Inspected window functions"}}]}}.
Those values are schema examples, not measurements. Use only measured values with source evidence;
otherwise omit the optional layout record and report the unresolved geometry.
The app automatically saves verified widths as the project’s character limits; the user does not
need to accept them in Layout. Read `{command}` to confirm `layoutApplication` is `applied`.
An active operation or pending option edits may defer the save. Later manual width edits are retained.
Do not change unrelated guidance, translate text, submit API work or execute the game as part of remeasurement.
"""
