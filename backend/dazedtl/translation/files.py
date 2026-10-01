"""Bounded project files and portable, content-bound identities."""

import hashlib
import json
from pathlib import Path

from dazedtl.storage import write_json


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def read_json(path, *, limit=128_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Choose a regular JSON file within the supported size limit.")
    return json.loads(path.read_bytes().decode("utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("JSON numbers must be finite.")))


def project_path(root, relative, *, exists=True):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The selected game folder is unavailable.")
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Use a project-relative path with forward slashes.")
    child = Path(relative)
    if child.is_absolute() or any(part.casefold() in {"..", ".git"} for part in child.parts):
        raise ValueError("Files must stay inside the selected game and outside Git internals.")
    path = root
    for part in child.parts:
        path /= part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Project operations cannot follow symbolic links.")
    if not path.resolve().is_relative_to(root) or path == root:
        raise ValueError("Choose a file inside the selected game.")
    if exists and not path.is_file():
        raise ValueError("The selected project file is missing.")
    return path


def evidence(root, paths):
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise ValueError("Supply unique source and guidance file paths.")
    result = {}
    for relative in paths:
        path = project_path(root, relative)
        before = path.stat()
        with path.open("rb") as stream:
            fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("A source file changed while it was being read.")
        result[relative] = fingerprint
    return result


def verify_evidence(root, expected):
    if not isinstance(expected, dict) or not expected or evidence(root, list(expected)) != expected:
        raise ValueError("Source or guidance changed. Compile and review a new request plan.")


def write_project_json(root, relative, value):
    path = project_path(root, relative, exists=False)
    write_json(path, value)
    return path
