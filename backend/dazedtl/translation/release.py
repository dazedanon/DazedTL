"""Package destinations and publication checks shared by Guided release workers."""

import hashlib
import os
from pathlib import Path
import zipfile


def git_identity(status):
    keys = ("original_commit", "translation_commit")
    if any(not isinstance(status.get(key), str) or not status[key] for key in keys):
        raise ValueError("The original and translation commits are unavailable. Check version tracking before packaging.")
    return {key: status[key] for key in keys}


def destination(source, workspace, engine_source, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 10000 or "\0" in value:
        raise ValueError("Choose a release ZIP destination.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Choose an absolute release destination.")
    if path.suffix.lower() != ".zip":
        raise ValueError("Use a .zip archive name.")
    if path.is_symlink():
        raise ValueError("The release destination cannot be a symbolic link.")
    path = path.resolve()
    if any(path.is_relative_to(Path(root).resolve()) for root in (source, workspace, engine_source, Path(__file__).resolve().parents[3])):
        raise ValueError("Save the release outside the game, app workspace, and engine source.")
    if path.exists() and not path.is_file():
        raise ValueError("Choose an archive file, not an existing directory.")
    return path


def output_hash(path):
    path = Path(path)
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError("The release destination is not a regular file.")
    if not path.exists():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stamp(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("The saved release archive is unavailable.")
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def available(value):
    try:
        return stamp(value["path"]) == value["stamp"]
    except (OSError, ValueError, KeyError):
        return False


def publish(staged, output, expected, *, stopped=lambda: False):
    """Keep the previous ZIP until a complete archive is ready to replace it."""
    staged, output = Path(staged), Path(output)
    with zipfile.ZipFile(staged) as archive:
        if not archive.infolist() or archive.testzip() is not None:
            raise ValueError("The release ZIP could not be verified.")
    if stopped():
        raise InterruptedError("Package creation stopped. The previous release is unchanged.")
    if output_hash(output) != expected:
        raise ValueError("The destination changed while packaging. Choose the output again.")
    os.replace(staged, output)
    identity = stamp(output)
    return {"path": str(output), "size": identity[2], "stamp": identity}
