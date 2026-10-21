"""The backups DazedTL saved before it kept a game's original files in Git.

They stay readable, so projects set up then keep their original
([originals](originals.py)) and scripts/backups.py can still restore them;
nothing writes new ones or removes old ones.
"""

import hashlib
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath

from dazedtl import system
from dazedtl.storage import staging_folder

from .files import digest, read_json

STORE_RELATIVE = ".dazedtl/backups/v2"
_ID = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"[0-9a-f]{64}")


class BackupMissing(ValueError):
    """No saved snapshot exists at any supported location."""


def _cancel(stopped):
    if stopped():
        raise InterruptedError(
            "Backup operation stopped; existing snapshots were retained."
        )


def _linked(path):
    """A symbolic link or junction, from one look at the path."""
    try:
        info = os.lstat(path)
    except OSError, ValueError:
        return False
    return stat.S_ISLNK(info.st_mode) or (
        sys.platform == "win32"
        and info.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    )


def _relative(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 for char in name)
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or PurePosixPath(name).is_absolute()
    ):
        raise ValueError("Backup entries must use safe relative file paths.")
    return name


def _child(root, name):
    """``name`` under ``root``, refusing a link at any step."""
    path = Path(root)
    _refuse_link(path)
    for part in _relative(name).split("/"):
        path /= part
        _refuse_link(path)
    return path


def _refuse_link(path):
    if _linked(path):
        raise ValueError("Backup operations cannot follow symbolic links or junctions.")


def store_path(game):
    return _child(Path(game).resolve(strict=True), STORE_RELATIVE)


def _store(root):
    root = Path(root)
    if _linked(root) or root.exists() and not root.is_dir():
        raise ValueError("Choose a regular backup store directory.")
    if read_json(_child(root, "store.json"), limit=4096) != {"version": 2}:
        raise ValueError("Unsupported backup store. Its contents were left unchanged.")
    return root


def _hash_file(path, stopped=lambda: False):
    if _linked(path) or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Backups support regular files only.")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            _cancel(stopped)
            value.update(block)
    return value.hexdigest()


def _object(root, fingerprint):
    if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
        raise ValueError("Invalid backup content hash.")
    return _child(root, "objects/" + fingerprint[:2] + "/" + fingerprint)


def _identity(value):
    return digest(
        {key: value[key] for key in ("kind", "files", "sizes", "modes", "directories")}
    )


def manifest(directory, source=None):
    directory = Path(directory)
    value = read_json(_child(directory, "manifest.json"))
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] not in {1, 2}
    ):
        raise ValueError("Unsupported backup manifest.")
    if (
        value.get("id") != directory.name
        or not _ID.fullmatch(directory.name)
        or value.get("kind") not in {"source", "workspace"}
    ):
        raise ValueError("Invalid backup identity or kind.")
    if (
        not isinstance(value.get("source"), str)
        or not value["source"]
        or not isinstance(value.get("created"), str)
    ):
        raise ValueError("Invalid backup provenance.")
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("The backup has no valid file inventory.")
    for name, fingerprint in files.items():
        _relative(name)
        if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
            raise ValueError("Invalid backup content hash.")
    if value["version"] == 1:
        if source is not None and value.get("source") != str(Path(source).resolve()):
            raise ValueError("The backup belongs to another project.")
    else:
        if directory.parent.name != "snapshots":
            raise ValueError("Choose a snapshot in its original backup store.")
        _store(directory.parent.parent)
        for key, maximum in (("sizes", None), ("modes", 0o777)):
            values = value.get(key)
            if (
                not isinstance(values, dict)
                or set(values) != set(files)
                or any(
                    type(item) is not int
                    or item < 0
                    or maximum is not None
                    and item > maximum
                    for item in values.values()
                )
            ):
                raise ValueError("Invalid backup file metadata.")
        directories = value.get("directories")
        if not isinstance(directories, list):
            raise ValueError("Invalid backup directory inventory.")
        for name in directories:
            _relative(name)
            if name in files:
                raise ValueError("A backup path cannot be both a file and a directory.")
        if len(set(directories)) != len(directories):
            raise ValueError("Duplicate backup directories.")
        if (
            value.get("fingerprint") != _identity(value)
            or value["fingerprint"][:32] != value["id"]
        ):
            raise ValueError(
                "The snapshot manifest changed. Its original content is required for recovery."
            )
    return value


def _stored_file(directory, value, name):
    return (
        _object(Path(directory).parent.parent, value["files"][name])
        if value["version"] == 2
        else _child(Path(directory), "files/" + name)
    )


def _available_objects(directory, value, stopped):
    """Check each object and shard once per observation, without retaining state."""
    root = _child(Path(directory).parent.parent, "objects")
    shards, objects = {}, {}
    for name, fingerprint in value["files"].items():
        _cancel(stopped)
        if fingerprint not in objects:
            prefix = fingerprint[:2]
            if prefix not in shards:
                shards[prefix] = _child(root, prefix)
            info = (shards[prefix] / fingerprint).lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(
                info, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(
                    "Backup content is missing or is no longer a regular file."
                )
            objects[fingerprint] = info.st_size
        if objects[fingerprint] != value["sizes"][name]:
            raise ValueError("Backup content has changed size.")


def verify(directory, *, source=None, full=True, stopped=lambda: False):
    value = manifest(directory, source)
    if not full and value["version"] == 2:
        _available_objects(directory, value, stopped)
        return value
    checked = set()
    for name, fingerprint in value["files"].items():
        _cancel(stopped)
        path = _stored_file(directory, value, name)
        if not path.is_file() or _linked(path):
            raise ValueError(
                "Backup content is missing or is no longer a regular file."
            )
        if value["version"] == 2 and path.stat().st_size != value["sizes"][name]:
            raise ValueError("Backup content has changed size.")
        if full and path not in checked and _hash_file(path, stopped) != fingerprint:
            raise ValueError("Backup content failed its integrity check.")
        checked.add(path)
    return value


def _extract(directory, value, target, names, stopped, progress):
    for index, name in enumerate(names, 1):
        _cancel(stopped)
        output = _child(target, name)
        output.parent.mkdir(parents=True, exist_ok=True)
        _copy(directory, value, name, output, stopped)
        progress(index, name)


def _copy(directory, value, name, output, stopped):
    """Writes one saved file to a new path, verified and synced to disk."""
    incoming = _stored_file(directory, value, name)
    if _linked(incoming) or not stat.S_ISREG(incoming.stat().st_mode):
        raise ValueError("Backup content is not a regular file.")
    copied = hashlib.sha256()
    with incoming.open("rb") as reader, output.open("xb") as writer:
        while block := reader.read(1024 * 1024):
            _cancel(stopped)
            copied.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    if copied.hexdigest() != value["files"][name]:
        raise ValueError(
            "Backup content failed its integrity check. No restore was published."
        )
    if _hash_file(output, stopped) != value["files"][name]:
        raise ValueError(
            "Restored content failed its integrity check. No restore was published."
        )
    mode = (
        value["modes"][name]
        if value["version"] == 2
        else stat.S_IMODE(incoming.stat().st_mode)
    )
    output.chmod(mode)


def peek(directory, name, size):
    """The first bytes of one saved file, such as an archive's index,
    without restoring a file that can be gigabytes."""
    value = manifest(directory)
    if name not in value["files"]:
        raise ValueError("The backup has no such file.")
    incoming = _stored_file(directory, value, name)
    if _linked(incoming) or not stat.S_ISREG(incoming.stat().st_mode):
        raise ValueError("Backup content is not a regular file.")
    with incoming.open("rb") as reader:
        return reader.read(size)


def restore(
    directory,
    destination,
    *,
    stopped=lambda: False,
    progress=lambda _count, _path: None,
):
    value = manifest(directory)
    target = Path(destination).expanduser().absolute()
    if _linked(target) or target.exists():
        raise ValueError(
            "Restore into a new directory; existing files are never overwritten."
        )
    parent = target.parent.resolve(strict=True)
    target = parent / target.name
    store = (
        Path(directory).parent.parent.resolve()
        if value["version"] == 2
        else Path(directory).resolve()
    )
    original = Path(value["source"]).resolve()
    roots = [store, original]
    if store.parts[-3:] == (".dazedtl", "backups", "v2"):
        roots.append(store.parents[2])
    if any(
        target.is_relative_to(root) or root.is_relative_to(target) for root in roots
    ):
        raise ValueError(
            "Restore into a separate directory outside the source and backup store."
        )
    with staging_folder(parent, ".dazedtl-restore-") as temporary:
        for name in value.get("directories", []):
            _child(temporary, name).mkdir(parents=True, exist_ok=True)
        _extract(directory, value, temporary, list(value["files"]), stopped, progress)
        _cancel(stopped)
        if target.exists() or _linked(target):
            raise ValueError(
                "The restore destination appeared during recovery. It was left unchanged."
            )
        system.rename(temporary, target)
    return {
        "path": str(target),
        "files": len(value["files"]),
        "kind": value["kind"],
        "id": value["id"],
        "restored": True,
    }


def lookup(game, legacy_root, identity):
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError("Choose a saved backup ID.")
    for path in (
        _child(store_path(game), "snapshots/" + identity),
        _child(legacy_root, identity),
        _child(legacy_root, "snapshots/" + identity),
    ):
        try:
            path.stat()
        except FileNotFoundError:
            continue
        return path
    raise BackupMissing("The backup is unavailable. Its files were not changed.")


def game_files(game, records=()):
    """Every file name the game's saved snapshots hold: its original, the
    prepared game, each update and each game backup, plus the snapshots
    `records` name in an older profile store. Unreadable snapshots add none.
    """
    folders = []
    root = store_path(game) / "snapshots"
    if not _linked(root) and root.is_dir():
        folders.extend(
            folder for folder in root.iterdir() if _ID.fullmatch(folder.name)
        )
    for record in records:
        try:
            folders.append(lookup(game, Path(record["path"]).parent, record["id"]))
        except OSError, ValueError, KeyError, TypeError:
            continue
    names = set()
    for folder in folders:
        try:
            value = manifest(folder)
        except OSError, ValueError, TypeError:
            continue
        if value["kind"] == "source":
            names.update(value["files"])
    return names


def catalog(game, legacy_root):
    rows, warnings = [], []
    for root in (store_path(game) / "snapshots", Path(legacy_root)):
        if not root.exists():
            continue
        if _linked(root) or not root.is_dir():
            warnings.append("A backup location is not a regular directory.")
            continue
        for folder in root.iterdir():
            if not _ID.fullmatch(folder.name):
                continue
            try:
                value = manifest(folder)
                rows.append(
                    {
                        "id": value["id"],
                        "kind": value["kind"],
                        "created": value.get("created", ""),
                        "files": len(value["files"]),
                        "version": value["version"],
                        "bytes_total": sum(value["sizes"].values())
                        if value["version"] == 2
                        else None,
                    }
                )
            except OSError, ValueError, TypeError:
                warnings.append(
                    "Backup "
                    + folder.name
                    + " could not be read; its files were retained."
                )
    return {
        "snapshots": sorted(rows, key=lambda row: row["created"], reverse=True),
        "warnings": warnings,
    }
