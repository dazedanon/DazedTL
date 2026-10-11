"""The setup assistant's decisions on the speaker scan's likely header slips.

The assistant checks each flagged Show Text header in its scene and writes one
review per flag: a fix with the header it should have, or keep with a reason.
Applying checks the report against the scan and the game's current files,
writes only the fixed headers' face and nameplate, and records every decision
so the Speaker slips list shows what was fixed and why the rest stays.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_bytes, write_json

from .files import decode_json, digest, project_path, read_json

REPORT = ".dazedtl/guided/header-review.json"
RECORD = ".dazedtl/guided/header-fixes.json"
_EVENT_FILE_RE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")


def _key(flag):
    """A flag's box as the scan saw it, which a later scan keeps until it changes."""
    return digest(
        [
            flag["file"],
            flag["pointer"],
            flag["face_name"],
            flag["face_index"],
            flag["name"],
            flag["text"],
        ]
    )


def _header(command):
    parameters = command["parameters"]
    return {
        "face_name": parameters[0],
        "face_index": parameters[1],
        "name": parameters[4],
    }


def _parts(pointer):
    return tuple(
        part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]
    )


def _command(document, pointer):
    value = document
    for part in _parts(pointer):
        value = value[int(part)] if isinstance(value, list) else value[part]
    if (
        not isinstance(value, dict)
        or value.get("code") != 101
        or not isinstance(value.get("parameters"), list)
        or len(value["parameters"]) < 5
    ):
        raise ValueError(f"No Show Text header is at {pointer}.")
    return value


def _faces(data):
    """Faces the game's own Show Text headers show."""
    faces = set()
    for path in data.glob("*.json"):
        if not _EVENT_FILE_RE.fullmatch(path.name):
            continue
        try:
            stack = [json.loads(path.read_bytes().decode("utf-8-sig"))]
        except OSError, UnicodeDecodeError, ValueError:
            continue
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                parameters = value.get("parameters")
                if (
                    value.get("code") == 101
                    and isinstance(parameters, list)
                    and parameters
                    and isinstance(parameters[0], str)
                ):
                    faces.add(parameters[0])
                stack.extend(
                    child for key, child in value.items() if key != "_original"
                )
            elif isinstance(value, list):
                stack.extend(value)
    return faces


def _spans(text, pointers):
    """Where each pointer's value sits in JSON text, in one pass that parses
    only the values on the way to them."""
    targets = {_parts(pointer): pointer for pointer in pointers}
    ancestors = {target[:depth] for target in targets for depth in range(len(target))}
    decoder = json.JSONDecoder()
    spans = {}

    def space(index):
        while text[index] in " \t\r\n":
            index += 1
        return index

    def walk(index, path):
        index = space(index)
        if path not in ancestors or text[index] not in "[{":
            end = decoder.raw_decode(text, index)[1]
            if path in targets:
                spans[targets[path]] = (index, end)
            return end
        closing = "]" if text[index] == "[" else "}"
        index = space(index + 1)
        position = 0
        while text[index] != closing:
            part = str(position)
            if closing == "}":
                part, index = decoder.raw_decode(text, index)
                index = space(index) + 1
            index = space(walk(index, (*path, part)))
            if text[index] == ",":
                index = space(index + 1)
            position += 1
        return index + 1

    walk(0, ())
    return spans


def _spliced(raw, document, values):
    """The file with only these pointers' values replaced, so its layout,
    escapes, line endings and byte order mark stay as they were."""
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom) :].decode("utf-8")
    spans = _spans(text, values)
    for pointer, (start, end) in sorted(
        spans.items(), key=lambda item: item[1][0], reverse=True
    ):
        text = (
            text[:start] + json.dumps(values[pointer], ensure_ascii=False) + text[end:]
        )
    if len(spans) != len(values) or decode_json(text.encode("utf-8")) != document:
        raise ValueError("A header could not be written in place; scan again.")
    return bom + text.encode("utf-8")


def _reviews(report, flags, faces):
    """The report's review for every flag, checked."""
    if (
        not isinstance(report, dict)
        or set(report) != {"version", "reviews"}
        or report["version"] != 1
        or not isinstance(report["reviews"], list)
    ):
        raise ValueError(
            f"Write {REPORT} as {{version: 1, reviews: [...]}}, one review per flag."
        )
    reviews = {}
    for review in report["reviews"]:
        fields = {"file", "pointer", "decision", "reason"}
        if isinstance(review, dict) and review.get("decision") == "fix":
            fields |= {"face_name", "face_index", "name"}
        if not isinstance(review, dict) or set(review) != fields:
            raise ValueError(
                "Each review is {file, pointer, decision, reason}, and a fix also "
                "names face_name, face_index and name."
            )
        place = (review["file"], review["pointer"])
        if place not in flags or place in reviews:
            raise ValueError(
                f"Review each flag of the current scan once: {review['file']} "
                f"{review['pointer']} is not one, or is reviewed twice."
            )
        reason = review["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
            raise ValueError(f"Give a one-line reason for {review['pointer']}.")
        if review["decision"] == "fix":
            after = {key: review[key] for key in ("face_name", "face_index", "name")}
            if (
                not isinstance(after["face_name"], str)
                or not isinstance(after["name"], str)
                or type(after["face_index"]) is not int
                or not 0 <= after["face_index"] <= 7
                or len(after["name"]) > 100
                or "\n" in after["name"]
            ):
                raise ValueError(f"The fix for {review['pointer']} is invalid.")
            if after["face_name"] and after["face_name"] not in faces:
                raise ValueError(
                    f"The fix for {review['pointer']} names a face the game never shows."
                )
            if after == {
                key: flags[place][key] for key in ("face_name", "face_index", "name")
            }:
                raise ValueError(
                    f"The fix for {review['pointer']} keeps the header as it is; "
                    "review it as keep instead."
                )
        elif review["decision"] != "keep":
            raise ValueError("A review's decision is fix or keep.")
        reviews[place] = review
    missing = sorted(set(flags) - set(reviews))
    if missing:
        raise ValueError(
            "Review every flag of the current scan; missing: "
            + ", ".join(f"{file} {pointer}" for file, pointer in missing[:5])
        )
    return reviews


def apply(source, data, headers):
    """Fix the headers the assistant's report fixes and record every decision."""
    source, data = Path(source), Path(data)
    report = read_json(project_path(source, REPORT), limit=2_000_000)
    flags = {(flag["file"], flag["pointer"]): flag for flag in headers["flags"]}
    if headers["total"] > len(flags):
        raise ValueError(
            "The scan found more flags than it lists, too many to review; "
            "leave the headers to release QA."
        )
    reviews = _reviews(report, flags, _faces(data))
    relative = data.relative_to(source).as_posix()
    fixed, kept, writes = [], [], {}
    for place, review in sorted(reviews.items()):
        flag = flags[place]
        if review["decision"] == "keep":
            kept.append({"key": _key(flag), "reason": review["reason"].strip()})
            continue
        path = project_path(source, f"{relative}/{flag['file']}")
        if path not in writes:
            raw = path.read_bytes()
            writes[path] = (raw, decode_json(raw), {})
        command = _command(writes[path][1], flag["pointer"])
        before = _header(command)
        if isinstance(command.get("_original"), str) or before != {
            key: flag[key] for key in ("face_name", "face_index", "name")
        }:
            raise ValueError(
                f"The header at {flag['file']} {flag['pointer']} changed or was "
                "translated since the scan; scan again."
            )
        after = {key: review[key] for key in ("face_name", "face_index", "name")}
        for index, key in ((0, "face_name"), (1, "face_index"), (4, "name")):
            command["parameters"][index] = after[key]
            writes[path][2][f"{flag['pointer']}/parameters/{index}"] = after[key]
        fixed.append(
            {
                "kind": flag["kind"],
                "file": flag["file"],
                "pointer": flag["pointer"],
                "text": flag["text"],
                "evidence": flag["evidence"],
                "before": before,
                "after": after,
                "reason": review["reason"].strip(),
            }
        )
    # Every file is checked before any is written.
    payloads = {
        path: _spliced(raw, document, values)
        for path, (raw, document, values) in writes.items()
    }
    for path, payload in payloads.items():
        write_bytes(path, payload)
    # Fixes stay listed after a later scan stops flagging them; keeps
    # describe the latest review.
    earlier = recorded(source)
    record = {
        "version": 1,
        "report": digest(report),
        "applied": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixed": [*(earlier["fixed"] if earlier else []), *fixed],
        "kept": kept,
    }
    write_json(project_path(source, RECORD, exists=False), record)
    return record


def recorded(source):
    """The applied decisions, or None before any or when the record is unusable."""
    try:
        record = read_json(project_path(source, RECORD), limit=2_000_000)
    except OSError, ValueError:
        return None
    if (
        not isinstance(record, dict)
        or record.get("version") != 1
        or not isinstance(record.get("fixed"), list)
        or not isinstance(record.get("kept"), list)
    ):
        return None
    return record


def view(headers, record):
    """The scan's flags beside the assistant's decisions, as the sheet lists them."""
    if not isinstance(headers, dict):
        return None
    kept = {item["key"]: item["reason"] for item in (record or {}).get("kept", [])}
    fixes = {
        (item["file"], item["pointer"]): item
        for item in (record or {}).get("fixed", [])
    }
    rows = []
    for flag in headers["flags"]:
        fix = fixes.pop((flag["file"], flag["pointer"]), None)
        if fix and fix["before"] != {
            key: flag[key] for key in ("face_name", "face_index", "name")
        }:
            fix = None
        rows.append(_row(flag, flag["evidence"], fix, kept.get(_key(flag), "")))
    # Fixed headers a later scan no longer flags.
    rows += [
        _row({**fix, **fix["before"]}, fix["evidence"], fix, "")
        for fix in fixes.values()
    ]
    # In the game's order: by file, then event, page and command.
    rows.sort(
        key=lambda row: (
            row["file"],
            [
                (0, int(part), "") if part.isdigit() else (1, 0, part)
                for part in row["pointer"].split("/")[1:]
            ],
        )
    )
    return {
        "total": headers["total"],
        "fixed": sum(row["decision"] == "fixed" for row in rows),
        "kept": sum(row["decision"] == "kept" for row in rows),
        "flags": rows,
    }


def _row(flag, evidence, fix, kept):
    return {
        "kind": flag["kind"],
        "file": flag["file"],
        "pointer": flag["pointer"],
        "faceName": flag["face_name"],
        "faceIndex": flag["face_index"],
        "name": flag["name"],
        "text": flag["text"],
        "evidence": evidence,
        "decision": "fixed" if fix else "kept" if kept else None,
        "reason": fix["reason"] if fix else kept,
        "fixedTo": {
            "faceName": fix["after"]["face_name"],
            "faceIndex": fix["after"]["face_index"],
            "name": fix["after"]["name"],
        }
        if fix
        else None,
    }
