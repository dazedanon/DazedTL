"""Recoverable source and workspace snapshots outside both Git branches."""

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import uuid

from dazedtl.storage import write_json
from .files import read_json


def snapshot(source, destination, *, source_game=False, stopped=lambda: False, progress=lambda _count, _path: None):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Keep backup storage separate from the selected source.")
    destination.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    temporary = destination / ("." + identity)
    final = destination / identity
    temporary.mkdir()
    manifest = {"version": 1, "id": identity, "source": str(source), "kind": "source" if source_game else "workspace",
                "created": datetime.now(timezone.utc).isoformat(), "files": {}}
    try:
        for directory, names, files in os.walk(source, followlinks=False):
            relative = Path(directory).relative_to(source)
            if source_game and relative == Path("."):
                names[:] = [name for name in names if name not in {".git", ".dazedtl"}]
                files = [name for name in files if name != ".git"]
            for name in names + files:
                path = Path(directory) / name
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    raise ValueError("Backup stopped at a symbolic link or junction. Preserve that source explicitly before continuing.")
            for name in files:
                if stopped():
                    raise InterruptedError("Backup stopped before publication; the source was not changed.")
                path = Path(directory) / name
                relative_file = path.relative_to(source)
                output = temporary / "files" / relative_file
                output.parent.mkdir(parents=True, exist_ok=True)
                before = path.stat()
                shutil.copy2(path, output)
                with output.open("rb") as handle:
                    fingerprint = __import__("hashlib").file_digest(handle, "sha256").hexdigest()
                with path.open("rb") as handle:
                    current = __import__("hashlib").file_digest(handle, "sha256").hexdigest()
                after = path.stat()
                if fingerprint != current or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("A source file changed during backup. Retry after the other writer finishes.")
                manifest["files"][relative_file.as_posix()] = fingerprint
                progress(len(manifest["files"]), relative_file.as_posix())
        if not manifest["files"]:
            raise ValueError("There are no files to back up.")
        write_json(temporary / "manifest.json", manifest)
        temporary.rename(final)
        return {"id": identity, "path": str(final), "files": len(manifest["files"]), "kind": manifest["kind"]}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def manifest(directory, source=None):
    directory = Path(directory)
    value = read_json(directory / "manifest.json")
    if value.get("version") != 1 or source is not None and value.get("source") != str(Path(source).resolve()):
        raise ValueError("The backup belongs to another project.")
    return value
