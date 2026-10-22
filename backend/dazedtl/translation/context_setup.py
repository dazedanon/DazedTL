"""Guidance file availability and optional measured layout recommendations."""

import json
import re
import uuid
from pathlib import Path

from dazedtl.storage import write_json

from .files import digest, project_path, read_json

REPORT = ".dazedtl/guided/context-findings.json"
CORE = ("glossary", "quirks", "game")
WIDTHS = ("width", "faceWidth", "listWidth", "noteWidth")
# The rows a message window shows, measured with the widths; a report or
# request from before it existed leaves the saved rows as they are.
ROWS = "messageRows"
# The speaker request a line width task records when no Names & glossary task
# was copied; such a request waits for widths, never for guidance files.
LAYOUT_REQUEST = "layout"


def retained_documents(source, documents, drafts):
    """Keep missing custom files addressable while their recovery drafts exist."""
    for name in drafts:
        if name.startswith("custom:") and name not in documents:
            path = project_path(
                source,
                ".dazedtl/skills/" + name.removeprefix("custom:") + ".md",
                exists=False,
            )
            documents[name] = {"text": "", "revision": digest(b""), "path": str(path)}
    return documents


def selected_document(path, position, documents):
    value = read_json(path) if path.exists() else {}
    name = value.get("name") if isinstance(value, dict) else None
    if name in documents:
        return name
    return (
        "quirks"
        if position.get("task") == "guidance" and "quirks" in documents
        else "glossary"
    )


def request(path, project_id, speaker_request, widths=None):
    previous = read_json(path) if path.exists() else {}
    if (
        previous.get("project_id") == project_id
        and previous.get("speaker_request_id") == speaker_request["request_id"]
        and (widths is None or previous.get("widths", widths) == widths)
    ):
        if widths is not None and "widths" not in previous:
            previous["widths"] = dict(widths)
            write_json(path, previous)
        return previous
    value = {
        "version": 1,
        "request_id": uuid.uuid4().hex,
        "project_id": project_id,
        "speaker_request_id": speaker_request["request_id"],
    }
    if widths is not None:
        value["widths"] = dict(widths)
    write_json(path, value)
    return value


def optional_record(path):
    try:
        value = read_json(path, limit=200_000)
        return value if isinstance(value, dict) else {}
    except OSError, ValueError:
        return {}


def inspect(
    request_path,
    review_path,
    native,
    project_id,
    documents,
    findings,
    scan,
    observed_digest,
    references=(),
):
    request_value = optional_record(request_path)
    reviews = optional_record(review_path)
    document_states = {}
    for name, document in documents.items():
        path = project_path(
            native["source"],
            Path(document["path"]).relative_to(native["source"]).as_posix(),
            exists=False,
        )
        # Keep the legacy response fields for older clients without retaining
        # document review, empty-choice or conflict state.
        document_states[name] = {
            "exists": path.is_file(),
            "reviewed": False,
            "needsReview": False,
            "intentionalEmpty": False,
        }
    from util.game_settings import default_wrap_widths

    complete = all(document_states.get(name, {}).get("exists") for name in CORE)
    receipt = native.get("guided_layout", {})
    applied = bool(
        receipt.get("applied")
        and native["widths"] == {**native["widths"], **receipt.get("widths", {})}
    )
    names_request = (
        bool(request_value)
        and request_value.get("speaker_request_id") != LAYOUT_REQUEST
    )
    result = {
        "status": "ready" if complete else "waiting" if names_request else "missing",
        "message": "Guidance files are saved in the game folder."
        if complete
        else "Save the glossary, style and game context files when needed.",
        "requestId": request_value.get("request_id"),
        "speakerReportId": findings.get("reportId"),
        "referencesSha256": digest(references),
        "scanSha256": ((scan.get("job") or {}).get("result") or {}).get(
            "artifact_sha256"
        )
        if scan.get("current")
        else None,
        "documents": document_states,
        "revisions": {name: doc["revision"] for name, doc in documents.items()},
        "layoutRevision": digest(native["widths"]),
        "layout": None,
        "layoutReportId": None,
        "layoutApplication": "applied" if applied else "none",
        "layoutMessage": "",
        "layoutUnmeasured": False,
        "layoutRejected": "",
        "layoutStatus": "saved"
        if applied
        or reviews.get("layout") == digest(native["widths"])
        or native["widths"] != default_wrap_widths(native.get("engine"))
        else "defaults",
    }
    if not request_value:
        return result
    path = project_path(native["source"], REPORT, exists=False)
    if not path.is_file() and not path.is_symlink():
        return result

    def rejected(message):
        # This task's report, but one the app cannot use; the assistant reads
        # why through the helper and saves it again.
        return {**result, "layoutRejected": message}

    try:
        report = read_json(path, limit=200_000)
    except OSError:
        # Read again on the next poll, such as while the file is replaced.
        return result
    except ValueError:
        return rejected(
            "Save the line width report as one JSON object of at most 200 KB."
        )
    if not isinstance(report, dict):
        return rejected("Save the line width report as one JSON object.")
    report_id = digest(
        {"request_id": report.get("request_id"), "layout": report.get("layout")}
    )
    consumed = receipt.get("reportId") == report_id
    if report.get("project_id") != project_id:
        return result
    if report.get("request_id") != request_value.get("request_id") and not consumed:
        # An earlier request's report; one saved since this request was made
        # names the wrong request.
        try:
            earlier = path.stat().st_mtime <= request_path.stat().st_mtime
        except OSError:
            return result
        return (
            result
            if earlier
            else rejected(
                "The line width report's request_id is not this task's requestId."
            )
        )
    if type(report.get("version")) is not int or report["version"] != 1:
        return rejected("Save the line width report with version 1.")
    if "layout" not in report:
        return rejected(
            "Include layout in the line width report: the measured values, or null when they could not be measured."
        )
    layout = report["layout"]
    if layout is None:
        # The assistant could not measure the windows; the widths stay.
        return {**result, "layoutUnmeasured": True}
    try:
        check_layout(layout, native["source"], consumed, observed_digest)
    except ValueError as exc:
        return rejected(str(exc))
    except TypeError, KeyError:
        return rejected("The line width report does not match its schema.")
    return {
        **result,
        "layout": layout,
        "layoutReportId": report_id,
        "layoutApplication": ("applied" if applied else "manual")
        if consumed
        else "pending",
    }


def check_layout(layout, source, consumed, observed_digest):
    """Raises with what is wrong with measured layout recommendations."""
    if (
        not isinstance(layout, dict)
        or set(layout) != {"widths", "reason", "evidence"}
        or not isinstance(layout["widths"], dict)
        or not set(WIDTHS) <= set(layout["widths"]) <= {*WIDTHS, ROWS}
    ):
        raise ValueError(
            "Layout recommendations need four widths, a reason and source evidence."
        )
    if (
        any(
            type(value) is not int
            or not (1 <= value <= 20 if key == ROWS else 20 <= value <= 300)
            for key, value in layout["widths"].items()
        )
        or layout["widths"]["faceWidth"] > layout["widths"]["width"]
    ):
        raise ValueError("Layout recommendations contain invalid character limits.")
    if (
        not isinstance(layout["reason"], str)
        or not 1 <= len(layout["reason"].strip()) <= 4000
        or not isinstance(layout["evidence"], list)
        or not 1 <= len(layout["evidence"]) <= 20
    ):
        raise ValueError(
            "Layout recommendations need a reason and inspected source evidence."
        )
    for ref in layout["evidence"]:
        if (
            not isinstance(ref, dict)
            or set(ref) != {"file", "sha256", "location"}
            or not isinstance(ref["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
            or not isinstance(ref["location"], str)
            or not 1 <= len(ref["location"].strip()) <= 1000
        ):
            raise ValueError("Layout evidence needs a source path, hash and location.")
        if (
            not isinstance(ref["file"], str)
            or len(ref["file"]) > 2000
            or any(part.startswith(".") for part in ref["file"].split("/"))
            or Path(ref["file"]).suffix.lower()
            not in {".json", ".js", ".rb", ".ini", ".ttf", ".otf"}
        ):
            raise ValueError(
                "Cite inspected game sources or fonts for layout recommendations."
            )
        # Applied widths keep their evidence as it was when they were saved.
        if consumed:
            continue
        try:
            current = observed_digest(project_path(source, ref["file"]))
        except OSError, ValueError:
            raise ValueError(
                f"Layout evidence {ref['file']} is not a readable file in the game."
            ) from None
        if current != ref["sha256"]:
            raise ValueError(
                f"Layout evidence {ref['file']} has a sha256 that does not match the file."
            )


def layout_update(native, setup, request_value):
    """Consume each measured result once and retain edits made after its baseline."""
    layout, report_id = setup.get("layout"), setup.get("layoutReportId")
    previous = native.get("guided_layout", {})
    if not layout or not report_id or previous.get("reportId") == report_id:
        return None
    same_request = previous.get("requestId") == setup["requestId"]
    current = native["widths"]
    baseline = {
        **current,
        **(
            previous.get("widths", current)
            if same_request
            else request_value.get("widths", current)
        ),
    }
    measured = {**current, **layout["widths"]}
    manual = bool(
        same_request
        and not previous.get("applied")
        or current != baseline
        and current != measured
    )
    return {
        "reportId": report_id,
        "requestId": setup["requestId"],
        "applied": not manual,
        "widths": dict(current if manual else measured),
    }


def rebase_layout_draft(native, value):
    """Late recovery writes may cross a layout-only revision without losing edits."""
    receipt = native.get("guided_layout", {})
    if (
        not isinstance(value, dict)
        or value.get("revision") != receipt.get("beforeRevision")
        or native["revision"] != receipt.get("revision")
        or receipt.get("revision") == receipt.get("beforeRevision")
    ):
        return value
    values = value["values"]
    widths = (
        native["widths"]
        if values["widths"] == receipt.get("beforeWidths")
        else values["widths"]
    )
    return {
        **value,
        "revision": native["revision"],
        "values": {**values, "widths": dict(widths)},
    }


def review(path, documents, native, name, revision, choice):
    if choice in {"empty", "review"} and name in documents:
        return {"saved": True}  # Older clients no longer need a document receipt.
    if choice != "layout" or name != "layout" or revision != digest(native["widths"]):
        raise ValueError(
            "Layout values changed. Review the current values before saving."
        )
    write_json(path, {"layout": revision})
    return {"saved": True}


def instructions(value, command, capture):
    return (
        f"""
## Save guidance and optional layout recommendations

Keep this investigation focused on speaker formats, reusable glossary/context, and measured UI layout.
Reuse verified current findings and inspect only the source needed to resolve missing or stale evidence.
For layout, prioritize System resolution/font settings and the relevant window/plugin code.
Inspect font metrics, window skins, portrait or other image dimensions only when they establish an actual
text area's geometry. Skip unrelated artwork, image inventories, broad OCR and image text translation;
those belong to the separate Images stage. Do not edit images here, and run the game only to confirm
the measured limits on screen as the layout analysis describes.

After the local speaker scan, finish the glossary, voice, game context and width investigation.
Keep the shared glossary's category headers and `source (translation)` entry format; character notes stay on that entry's line.
Do not convert it to a Markdown table or JSON. Preserve existing spellings unless the source justifies a correction.
Save glossary, style and game context through the existing portable document paths, plus any custom guidance
you investigated. An empty file is fine when there is nothing to add. Their presence in the game folder
completes guidance setup; no document hashes, completion report or review receipts are required.
Read `{command}` to confirm the saved files are available.

Do not execute translation, paid name translation or API submission as part of this setup task.
"""
        + layout_instructions(value, command, capture)
        + f"""
Save `{REPORT}` last, after every other step of this task, including the speaker slip reviews
and guidance files: the app shows this task as finished once that report is saved.
"""
    )


def layout_instructions(value, command, capture):
    example = {
        "version": 1,
        "request_id": value["request_id"],
        "project_id": value["project_id"],
        "layout": None,
    }
    # A width the game gives no reason to change keeps its current value.
    current = (
        f" The project's current limits are {json.dumps(value['widths'])}; report a width you keep at its current value."
        if value.get("widths")
        else ""
    )
    return f"""
## Save measured character limits

Atomically save measured layout recommendations to `{REPORT}` with these identity fields:

```json
{json.dumps(example, ensure_ascii=False, indent=2)}
```

Replace layout null with the measured values and their evidence:
{{"widths": {{"width": 60, "faceWidth": 50, "listWidth": 100, "noteWidth": 75, "messageRows": 4}},
"reason": "Actual measurement method, confidence, font and exceptions.",
"evidence": [{{"file": "js/rpg_windows.js", "sha256": "FINAL_FILE_HASH", "location": "Inspected window functions"}}]}}.
Those values are schema examples, not measurements.{current} `messageRows` is the rows one message window
shows before the game starts a new window. Use only measured values with source evidence, confirmed
on screen as the measurement steps describe, and say in `reason` what the captures showed or what
could not be seen; otherwise save the report with `layout` null and report the unresolved geometry.
For an RPG Maker MV/MZ game the app confirms them itself: write the candidate widths, such as
{{"width": 55, "faceWidth": 50, "listWidth": 70, "messageRows": 4}}, to a JSON file and run
`{capture} --layout FILE --wait 10`. It shows English exactly that wide in the game's message window
with and without a face and in its help window, and `layout.probes` gives each one's widest line,
the room the window gives it, its rows and its capture file; look at the captures. A probe `fits`
only with `layout.headroom` characters spare after its widest line, as fonts and fallback glyphs
draw differently on other computers; `spare` and `spareCharacters` give the margin and `suggested`
the most characters that keep it. Save widths whose probes fit, checking a `suggested` width again.
`layout.fallback` lists the characters of the game's text its font lacks, with how often each
appears, how many characters the fitter counts it as (`counted`) and how wide the game drew it
(`drawn`); keep more spare for one drawn wider than counted, and name them in `reason`. Note windows and
plugin windows still need your own check; measure `noteWidth` on the window that draws the note tags
the layout analysis names, not on other note text.
The app automatically saves verified widths as the project’s character limits; the user does not
need to accept them in Layout. Read `{command}` to confirm `layoutApplication` is `applied`.
If it shows `layoutRejected`, fix what it names and save the report again.
An active operation or pending option edits may defer the save. Later manual width edits are retained.
Do not change unrelated guidance, translate text or submit API work as part of remeasurement.
"""
