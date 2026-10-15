"""Reusable recipes for edited images, and the validator command.

Every image an assistant edits names, in the project's resource manifest,
the command and hashed inputs that render it again and the regions its edit
was allowed to change. A later sibling then starts from a recipe instead of
being reverse-engineered from pixels, and the same declaration lets the app
check the edit's pixels when it reads the assistant's report. Assistants run
this module's command line on their request before reporting.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from dazedtl.storage import write_bytes
from dazedtl.translation.files import digest, project_path, read_json

from . import validation

RESOURCES = ".dazedtl/image_translation_resources"
MANIFEST = RESOURCES + "/manifest.json"
CHECK_KEYS = {"intermediate", "cleanup", "text", "protected", "clearance"}
REGIONS = ("cleanup", "text", "protected")


def _hash(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def manifest(root):
    """The manifest's recipes by image ID, and why none can be read."""
    try:
        path = project_path(root, MANIFEST, exists=False)
    except ValueError as exc:
        return None, str(exc)
    if not path.exists():
        return {}, ""
    try:
        value = read_json(path, limit=16_000_000)
    except ValueError:
        return None, "The resource manifest is not readable JSON."
    found = value.get("recipes", {}) if isinstance(value, dict) else None
    if not isinstance(found, dict):
        return None, "The resource manifest's recipes must map image IDs to recipes."
    return found, ""


def problem(entry):
    """What a recipe lacks, or an empty string."""
    if not isinstance(entry, dict):
        return "it must be an object"
    if not _hash(entry.get("output")):
        return "output must be the edited PNG's SHA-256"
    command = entry.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) for part in command)
        or not any("{output}" in part for part in command)
    ):
        return "command must be a list of arguments that writes {output}"
    inputs = entry.get("inputs")
    if (
        not isinstance(inputs, dict)
        or not inputs
        or any(
            not isinstance(path, str) or not _hash(value)
            for path, value in inputs.items()
        )
    ):
        return "inputs must map project-relative paths to SHA-256 hashes"
    declared = entry.get("check")
    if not isinstance(declared, dict) or not {"cleanup", "text"} & set(declared):
        return "check must declare its cleanup or text region"
    if set(declared) - CHECK_KEYS:
        return "check takes only " + ", ".join(sorted(CHECK_KEYS))
    if "intermediate" in declared and not isinstance(declared["intermediate"], str):
        return "check.intermediate must be a project-relative path"
    clearance = declared.get("clearance", 0)
    if type(clearance) is not int or not 0 <= clearance <= 512:
        return "check.clearance must be whole pixels"
    for name in REGIONS:
        if name in declared and not isinstance(declared[name], (str, list)):
            return f"check.{name} must be a mask path or [x, y, width, height] boxes"
    return ""


def _files(entry):
    """The project files a recipe's check reads."""
    declared = entry["check"]
    return [
        declared[name]
        for name in ("intermediate", *REGIONS)
        if isinstance(declared.get(name), str)
    ]


def _recipe(entry, image, file_hash):
    """Whether the recipe still reproduces this exact edit."""
    if entry is None:
        return "missing", "No reusable recipe is saved for this image."
    wrong = problem(entry)
    if wrong:
        return "invalid", f"Its recipe is incomplete: {wrong}."
    if entry["output"] != image["candidateHash"]:
        return "stale", "Its recipe renders an earlier edit, not this one."
    for path, expected in entry["inputs"].items():
        actual = file_hash(path)
        # Inputs in the resource folder are named from it, as recipes are.
        shown = path.removeprefix(RESOURCES + "/")
        if actual is None:
            return "stale", f"Its recipe input {shown} is missing."
        if actual != expected:
            return "stale", f"Its recipe input {shown} changed."
    hashes = set(entry["inputs"].values())
    if not hashes & image["originals"]:
        return "invalid", "Its recipe does not list the original it renders from."
    if not any(path.startswith(RESOURCES + "/") for path in entry["inputs"]):
        return (
            "invalid",
            "Its recipe does not list a renderer or layout from the resource folder.",
        )
    return "current", ""


def proof(root, image, entry, *, file_hash=None, cached=None):
    """The recipe and validation of one edited image.

    image holds the request's or inventory's id, frozen original path and
    hash, candidateHash, the candidate's bytes and the hashes that identify
    its original (frozen PNG, runtime source and backup). A cached proof with
    the same key keeps its validation instead of decoding the images again.
    """
    file_hash = file_hash or (lambda path: _project_hash(root, path))
    state, reason = _recipe(entry, image, file_hash)
    result: dict[str, Any] = {"recipe": {"state": state, "reason": reason}}
    if state in {"missing", "invalid"} and (entry is None or problem(entry)):
        result.update(key="", validation=None, ok=False, reason=reason)
        return result
    files = _files(entry)
    key = digest(
        {
            "entry": entry["check"],
            "candidate": image["candidateHash"],
            "original": image["frozenHash"],
            "files": {path: file_hash(path) for path in files},
        }
    )
    if cached and cached.get("key") == key and cached.get("validation"):
        checked = cached["validation"]
    else:
        try:
            checked = _validate(root, image, entry["check"])
        except Exception as exc:  # noqa: BLE001 - one unreadable image fails alone
            checked = {
                "ok": False,
                "checks": {},
                "failures": ["unreadable"],
                "summary": f"the images could not be checked ({exc})",
            }
    result.update(key=key, validation=checked)
    reasons = []
    if not checked["ok"]:
        # Said from the checks, so a kept validation reads as new ones do.
        summary = (
            validation.summary(checked) if checked["checks"] else checked["summary"]
        )
        reasons.append("Validation failed: " + summary + ".")
    if state != "current":
        reasons.append(reason)
    result.update(ok=not reasons, reason=" ".join(reasons))
    return result


def _project_hash(root, path):
    try:
        found = project_path(root, path, exists=False)
        return sha_bytes(found.read_bytes()) if found.is_file() else None
    except OSError, ValueError:
        return None


def _validate(root, image, declared):
    def read(path):
        return project_path(root, path).read_bytes()

    original = project_path(root, image["frozen"]).read_bytes()
    if sha_bytes(original) != image["frozenHash"]:
        raise ValueError("the preserved original changed")
    return run(original, image["candidate"], declared, read)


def run(original, candidate, declared, read):
    """Validates bytes against a recipe's check declaration; read(path)
    returns a declared file's bytes."""
    size = _size(original)
    masks, broken = {}, []
    for name in REGIONS:
        if name in declared:
            try:
                masks[name] = validation.region(declared[name], size, read)
            except (OSError, ValueError) as exc:
                broken.append(f"{name}: {exc}")
    intermediate = None
    if isinstance(declared.get("intermediate"), str):
        try:
            intermediate = read(declared["intermediate"])
        except OSError, ValueError:
            intermediate = b""
    result = validation.check(
        original,
        candidate,
        intermediate=intermediate,
        cleanup=masks.get("cleanup"),
        text=masks.get("text"),
        protected=masks.get("protected"),
        clearance=declared.get("clearance", 0),
    )
    if broken:
        result["checks"]["regions"] = {"ok": False, "detail": broken}
        result["failures"] = [*dict.fromkeys([*result["failures"], "regions"])]
        result["ok"] = False
    result["summary"] = validation.summary(result)
    return result


def reproduce(root, entry):
    """Runs the recipe's command into a temporary file and compares the
    result with the recorded output hash."""
    folder = project_path(root, RESOURCES + "/work/.reproduce", exists=False).parent
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reproduce-", dir=folder) as temporary:
        output = Path(temporary) / "output.png"
        command = [
            part.replace("{output}", str(output)).replace("{python}", sys.executable)
            for part in entry["command"]
        ]
        try:
            finished = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "reason": f"The recipe command did not run: {exc}"}
        if finished.returncode or not output.is_file():
            tail = (finished.stderr or finished.stdout).strip().splitlines()[-3:]
            return {
                "ok": False,
                "reason": "The recipe command failed: " + " ".join(tail),
            }
        actual = sha_bytes(output.read_bytes())
    if actual != entry["output"]:
        return {
            "ok": False,
            "reason": f"The recipe renders {actual}, not the recorded output.",
        }
    return {"ok": True, "reason": ""}


def _request_images(root, request, only):
    """The request's images to check, with each one's report status."""
    report = {}
    path = Path(request["report"])
    if path.is_file():
        saved = read_json(path, limit=48_000_000)
        for item in saved.get("assets", []) if isinstance(saved, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                report[item["id"]] = item.get("status", "")
    for asset in request["assets"]:
        if only and asset["id"] not in only:
            continue
        frozen = asset.get("frozen") or ""
        frozen_hash = asset.get("frozenHash") or (
            _project_hash(root, frozen) if frozen else None
        )
        yield asset, report.get(asset["id"], ""), frozen_hash


def _check_request(arguments):
    request = read_json(arguments.request, limit=48_000_000)
    root = Path(request["source"])
    found, unreadable = manifest(root)
    results = []
    for asset, status, frozen_hash in _request_images(
        root, request, set(arguments.asset)
    ):
        row = {"id": asset["id"], "status": status or "not reported"}
        results.append(row)
        if status in {"skipped", "needs_review", "error"}:
            row.update(ok=True, reason=f"Reported {status}; nothing to check.")
            continue
        try:
            _check_asset(root, asset, frozen_hash, found, unreadable, arguments, row)
        except (OSError, ValueError) as exc:
            row.update(ok=False, reason=str(exc))
    return {
        "request": request["id"],
        "ok": all(row["ok"] for row in results),
        "assets": results,
    }


def _check_asset(root, asset, frozen_hash, found, unreadable, arguments, row):
    """Checks one requested image as the app does when it reads the report."""
    candidate = project_path(root, asset["editable"]).read_bytes()
    candidate_hash = sha_bytes(candidate)
    row["candidateHash"] = candidate_hash
    if candidate_hash == frozen_hash:
        row.update(ok=True, reason="Unchanged from the original; nothing to check.")
        return
    if found is None:
        row.update(ok=False, reason=unreadable)
        return
    entry = found.get(asset["id"])
    image = {
        "id": asset["id"],
        "frozen": asset["frozen"],
        "frozenHash": frozen_hash,
        "candidateHash": candidate_hash,
        "candidate": candidate,
        "originals": {frozen_hash, asset["sourceHash"]},
    }
    checked = proof(root, image, entry)
    row.update(
        ok=checked["ok"],
        reason=checked["reason"],
        recipe=checked["recipe"],
        validation=checked["validation"],
    )
    if arguments.reproduce and entry is not None and not problem(entry):
        row["reproduced"] = reproduce(root, entry)
        row["ok"] = row["ok"] and row["reproduced"]["ok"]
    if arguments.diagnostics and entry is not None and checked["validation"]:
        row["diagnostics"] = _diagnose(
            root, asset, candidate, entry["check"], arguments.diagnostics
        )


def _check_recipes(arguments):
    """Whether each saved recipe can still render its image, such as a
    sibling's recipe about to be reused."""
    root = Path(arguments.folder)
    found, unreadable = manifest(root)
    if found is None:
        return {"ok": False, "error": unreadable}
    results = []
    for identity, entry in sorted(found.items()):
        if arguments.asset and identity not in arguments.asset:
            continue
        row = {"id": identity}
        results.append(row)
        wrong = problem(entry)
        if wrong:
            row.update(ok=False, reason=f"Its recipe is incomplete: {wrong}.")
            continue
        stale = [
            path
            for path, expected in entry["inputs"].items()
            if _project_hash(root, path) != expected
        ]
        row.update(
            ok=not stale,
            reason="Changed or missing inputs: " + ", ".join(stale) if stale else "",
        )
        if arguments.reproduce and not stale:
            row["reproduced"] = reproduce(root, entry)
            row["ok"] = row["reproduced"]["ok"]
    return {"ok": all(row["ok"] for row in results), "recipes": results}


def _diagnose(root, asset, candidate, declared, folder):
    original = project_path(root, asset["frozen"]).read_bytes()
    size = _size(original)

    def read(path):
        return project_path(root, path).read_bytes()

    allowed = None
    for name in ("cleanup", "text"):
        if name in declared:
            mask = validation.region(declared[name], size, read)
            allowed = mask if allowed is None else allowed | mask
    intermediate = (
        read(declared["intermediate"]) if "intermediate" in declared else None
    )
    return validation.diagnostics(
        original,
        candidate,
        folder,
        Path(asset["id"]).stem,
        intermediate=intermediate,
        regions=allowed,
    )


def _size(data):
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        return image.size


def _local_region(values, size):
    """A command-line region: mask files and x,y,width,height boxes, joined."""
    mask = None
    for value in values:
        if Path(value).is_file():
            part = validation.region(value, size, lambda path: Path(path).read_bytes())
        else:
            try:
                box = [int(number) for number in value.split(",")]
            except ValueError:
                raise ValueError(
                    f"{value} is neither a mask file nor x,y,width,height."
                ) from None
            part = validation.region([box], size, lambda path: b"")
        mask = part if mask is None else mask | part
    return mask


def _check_files(arguments):
    original = Path(arguments.original).read_bytes()
    candidate = Path(arguments.candidate).read_bytes()
    size = _size(original)
    regions = {name: _local_region(getattr(arguments, name), size) for name in REGIONS}
    intermediate = (
        Path(arguments.intermediate).read_bytes() if arguments.intermediate else None
    )
    result = validation.check(
        original,
        candidate,
        intermediate=intermediate,
        cleanup=regions["cleanup"],
        text=regions["text"],
        protected=regions["protected"],
        clearance=arguments.clearance,
    )
    result["summary"] = validation.summary(result)
    if arguments.diagnostics:
        allowed = [
            mask for mask in (regions["cleanup"], regions["text"]) if mask is not None
        ]
        result["diagnostics"] = validation.diagnostics(
            original,
            candidate,
            arguments.diagnostics,
            Path(arguments.candidate).stem,
            intermediate=intermediate,
            regions=allowed[0] | allowed[-1] if allowed else None,
        )
    return result


def _encode(arguments):
    data = validation.encode_like(
        Path(arguments.candidate).read_bytes(), Path(arguments.like).read_bytes()
    )
    write_bytes(Path(arguments.output), data)
    return {"ok": True, "output": arguments.output, "sha256": sha_bytes(data)}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="image_validate",
        description="Check edited game images against their originals and their recipes.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser(
        "request",
        help="check a DazedTL image request's edited images and their recipes, as the app does when it reads the report",
    )
    request.add_argument("request", help="the request JSON the task names")
    request.add_argument(
        "--asset", action="append", default=[], help="check only this image ID"
    )
    request.add_argument(
        "--reproduce",
        action="store_true",
        help="also run each recipe's command and compare its output hash",
    )
    request.add_argument("--diagnostics", help="write review composites to this folder")
    saved = commands.add_parser(
        "recipes",
        help="check that the game's saved recipes can still render their images",
    )
    saved.add_argument("folder", help="the game folder")
    saved.add_argument(
        "--asset", action="append", default=[], help="check only this image ID"
    )
    saved.add_argument(
        "--reproduce",
        action="store_true",
        help="also run each recipe and compare its output hash",
    )
    files = commands.add_parser(
        "files", help="check one edited PNG against its original"
    )
    files.add_argument("--original", required=True)
    files.add_argument("--candidate", required=True)
    files.add_argument(
        "--intermediate", help="the text-free PNG between cleanup and lettering"
    )
    for name in REGIONS:
        files.add_argument(
            "--" + name,
            action="append",
            default=[],
            help=f"{name} region: a mask PNG (nonzero pixels) or x,y,width,height; repeatable",
        )
    files.add_argument(
        "--clearance",
        type=int,
        default=0,
        help="pixels the text keeps from protected shapes",
    )
    files.add_argument("--diagnostics", help="write review composites to this folder")
    encode = commands.add_parser(
        "encode",
        help="re-encode an edited PNG with the original's header and metadata chunks",
    )
    encode.add_argument("candidate")
    encode.add_argument("--like", required=True, help="the original PNG")
    encode.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = {
            "request": _check_request,
            "recipes": _check_recipes,
            "files": _check_files,
            "encode": _encode,
        }[arguments.command](arguments)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
