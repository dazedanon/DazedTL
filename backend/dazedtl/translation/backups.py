"""Portable, immutable file snapshots; old full-copy backups remain readable."""

import hashlib
import os
import queue
import re
import shutil
import stat
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from dazedtl.storage import WorkspaceLock, staging_folder, write_json

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


def _child(root, name, folders=None):
    """``name`` under ``root``, refusing a link at any step. A snapshot passes
    ``folders`` to check each folder once rather than once per file; its
    final inventory walk would still find a link that appears later."""
    path = Path(root)
    _refuse_link(path, folders)
    *parents, leaf = _relative(name).split("/")
    for part in parents:
        path /= part
        _refuse_link(path, folders)
    path /= leaf
    _refuse_link(path)
    return path


def _refuse_link(path, folders=None):
    if folders is not None and path in folders:
        return
    if _linked(path):
        raise ValueError("Backup operations cannot follow symbolic links or junctions.")
    if folders is not None:
        folders.add(path)


def store_path(game):
    return _child(Path(game).resolve(strict=True), STORE_RELATIVE)


def _store(root, *, create=False):
    root = Path(root)
    if _linked(root) or root.exists() and not root.is_dir():
        raise ValueError("Choose a regular backup store directory.")
    marker = _child(root, "store.json")
    if not marker.exists() and create:
        if root.exists() and any(root.iterdir()):
            raise ValueError(
                "This backup directory contains unrecognized files. They were left unchanged."
            )
        root.mkdir(parents=True, exist_ok=True)
        write_json(marker, {"version": 2})
    if read_json(marker, limit=4096) != {"version": 2}:
        raise ValueError("Unsupported backup store. Its contents were left unchanged.")
    if create:
        for name in ("objects", "snapshots", "temporary"):
            _child(root, name).mkdir(exist_ok=True)
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


def _signature(path):
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        stat.S_IMODE(value.st_mode) & 0o777,
    )


def _inventory(source, source_game, stopped):
    files, directories = {}, []

    def failed(error):
        raise error

    for directory, names, entries in os.walk(source, followlinks=False, onerror=failed):
        _cancel(stopped)
        relative = Path(directory).relative_to(source)
        if relative == Path("."):
            excluded = (
                {".git", ".dazedtl"}
                if source_game
                else ({"backups"} if source.name == ".dazedtl" else set())
            )
            names[:] = [name for name in names if name not in excluded]
            entries = [name for name in entries if name not in excluded]
        for name in names + entries:
            path = Path(directory) / name
            entry = path.relative_to(source).as_posix()
            try:
                _relative(entry)
            except ValueError:
                # A stray file, such as a pager's "\x1bq", is easy to remove
                # once named.
                raise ValueError(
                    f"Backups can't keep the name {entry!r}."
                    " Rename it or move it out of the folder, then try again."
                ) from None
            if _linked(path):
                raise ValueError(
                    "Backup stopped at a symbolic link or junction. Preserve that source explicitly."
                )
        directories.extend(
            (Path(directory) / name).relative_to(source).as_posix() for name in names
        )
        for name in entries:
            path = Path(directory) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Backups support regular files only.")
            files[path.relative_to(source).as_posix()] = _signature(path)
    return files, sorted(directories)


def _object(root, fingerprint, folders=None):
    if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
        raise ValueError("Invalid backup content hash.")
    return _child(root, "objects/" + fingerprint[:2] + "/" + fingerprint, folders)


# Several files at once hide each file's waits for its creation and disk
# flush, which dominate a game of many small files, most of all on Windows.
_WORKERS = 8
# A file up to this size is read once and stored from memory; a larger one is
# hashed, then copied.
_BUFFERED = 16 * 1024 * 1024


class _Contents:
    """What one snapshot's threads stored, with each content hash stored or
    checked by one thread: Windows refuses to replace a file another thread
    is reading, as happens when a game holds two identical files. ``folders``
    holds the folders already checked for links."""

    def __init__(self):
        self.lock = threading.Lock()
        self.claims = {}
        self.created = {}
        self.folders = set()

    def claim(self, fingerprint):
        """True for the first thread with this content; later ones wait for it."""
        with self.lock:
            settled = self.claims.get(fingerprint)
            if settled is None:
                self.claims[fingerprint] = threading.Event()
                return True
        settled.wait()
        return False

    def settle(self, fingerprint):
        self.claims[fingerprint].set()


def _keep(root, source, name, signature, contents, stopped):
    """Stores one source file under its content hash and returns the hash."""
    _cancel(stopped)
    path = _child(source, name, contents.folders)
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Backups support regular files only.")
        # A read sized to the file: one sized to the limit allocates the
        # limit for every file, which costs Windows more than the reading.
        data = stream.read() if info.st_size <= _BUFFERED else None
    if data is None:
        fingerprint, size = _hash_file(path, stopped), info.st_size
    else:
        fingerprint, size = hashlib.sha256(data).hexdigest(), len(data)
    if contents.claim(fingerprint):
        try:
            _store_content(root, path, fingerprint, size, data, contents, stopped)
        finally:
            contents.settle(fingerprint)
    if _signature(path) != signature:
        raise ValueError(
            "A source file changed during backup. Retry when its writer finishes."
        )
    return fingerprint


def _store_content(root, path, fingerprint, size, data, contents, stopped):
    """Content the store holds is checked by size, as reading it back costs
    more than the backup: its file was synced before taking its name, and
    restores check its hash. New content is synced before taking its name."""
    output = _object(root, fingerprint, contents.folders)
    try:
        held = output.stat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(held.st_mode) or held.st_size != size:
            raise ValueError(
                "Stored backup content is damaged. Preserve the store and recover it from a trusted copy."
            )
        return
    temporary = _child(root, "temporary/" + uuid.uuid4().hex, contents.folders)
    try:
        with temporary.open("xb") as outgoing:
            if data is None:
                copied = hashlib.sha256()
                with path.open("rb") as incoming:
                    while block := incoming.read(1024 * 1024):
                        _cancel(stopped)
                        copied.update(block)
                        outgoing.write(block)
                if copied.hexdigest() != fingerprint:
                    raise ValueError(
                        "A source file changed during backup. Retry when its writer finishes."
                    )
            else:
                outgoing.write(data)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        output.parent.mkdir(exist_ok=True)
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    contents.created[output] = size


def _keep_all(root, source, names, signatures, contents, stopped, progress):
    """Stores every named file on several threads; each takes the next name
    when it finishes one. Returns each file's content hash."""
    queued, lock = iter(names), threading.Lock()
    stored, finished, failed = {}, queue.SimpleQueue(), threading.Event()

    def halted():
        return failed.is_set() or stopped()

    def work():
        try:
            while not failed.is_set():
                with lock:
                    name = next(queued, None)
                if name is None:
                    return
                stored[name] = _keep(
                    root, source, name, signatures[name], contents, halted
                )
                finished.put(name)
        except BaseException as error:  # noqa: BLE001 - the main thread raises it
            failed.set()
            finished.put(error)

    threads = [
        threading.Thread(target=work, name="backup", daemon=True)
        for _ in range(_WORKERS)
    ]
    for thread in threads:
        thread.start()
    try:
        for count in range(1, len(names) + 1):
            name = finished.get()
            if isinstance(name, BaseException):
                raise name
            progress(count, name)
    except BaseException:
        # Threads stop at their next block; the snapshot removes what they
        # stored.
        failed.set()
        raise
    finally:
        for thread in threads:
            thread.join()
    return stored


def _identity(value):
    return digest(
        {key: value[key] for key in ("kind", "files", "sizes", "modes", "directories")}
    )


def snapshot(
    source,
    destination,
    *,
    source_game=False,
    stopped=lambda: False,
    progress=lambda _count, _path: None,
):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if not source.is_dir():
        raise ValueError("Choose an existing directory to back up.")
    if destination.is_relative_to(source):
        permitted = source / (STORE_RELATIVE if source_game else "backups/v2")
        if destination != permitted or not source_game and source.name != ".dazedtl":
            raise ValueError(
                "Only the managed .dazedtl/backups/v2 store may be inside a snapshot source."
            )
        _child(source, destination.relative_to(source).as_posix())
    destination = destination.resolve()
    if destination.is_relative_to(source):
        permitted = source / (STORE_RELATIVE if source_game else "backups/v2")
        if destination != permitted or not source_game and source.name != ".dazedtl":
            raise ValueError(
                "Keep nested backups in the managed .dazedtl/backups/v2 store."
            )
    if source.is_relative_to(destination):
        raise ValueError("The snapshot source cannot be inside its backup store.")
    root = _store(destination, create=True)
    _child(root, "workspace.lock")
    lock = WorkspaceLock(root)
    contents, published = _Contents(), False
    try:
        before, directories = _inventory(source, source_game, stopped)
        if not before:
            raise ValueError("There are no files to back up.")
        value = {
            "version": 2,
            "source": str(source),
            "kind": "source" if source_game else "workspace",
            "created": datetime.now(UTC).isoformat(),
            "files": {},
            "sizes": {},
            "modes": {},
            "directories": directories,
        }
        names = sorted(before)
        stored = _keep_all(root, source, names, before, contents, stopped, progress)
        for name in names:
            value["files"][name] = stored[name]
            value["sizes"][name], value["modes"][name] = (
                before[name][2],
                before[name][5],
            )
        added = sum(contents.created.values())
        if _inventory(source, source_game, stopped) != (before, directories):
            raise ValueError(
                "The source inventory changed during backup. No snapshot was published."
            )
        _cancel(stopped)
        value["fingerprint"] = _identity(value)
        value["id"] = value["fingerprint"][:32]
        final = _child(root, "snapshots/" + value["id"])
        reused = final.exists()
        if reused:
            previous = manifest(final)
            if previous["fingerprint"] != value["fingerprint"]:
                raise ValueError(
                    "The existing snapshot identity is inconsistent; it was not replaced."
                )
            value = previous
        else:
            temporary = _child(root, "temporary/" + uuid.uuid4().hex)
            temporary.mkdir()
            try:
                write_json(temporary / "manifest.json", value)
                temporary.rename(final)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        published = True
        total = sum(value["sizes"].values())
        return {
            "id": value["id"],
            "path": str(final),
            "files": len(value["files"]),
            "kind": value["kind"],
            "version": 2,
            "bytes_total": total,
            "bytes_added": added,
            "bytes_reused": total - added,
            "reused_snapshot": reused,
        }
    finally:
        try:
            if not published:
                for path in contents.created:
                    path.unlink(missing_ok=True)
        finally:
            lock.close()


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


@contextmanager
def materialized(directory, *, files=None, stopped=lambda: False):
    """Supply verified normal files to engine tools without retaining another copy."""
    value = manifest(directory)
    names = (
        list(value["files"])
        if files is None
        else [name for name in files if name in value["files"]]
    )
    with tempfile.TemporaryDirectory(prefix="dazedtl-restore-") as temporary:
        target = Path(temporary)
        if files is None:
            for name in value.get("directories", []):
                _child(target, name).mkdir(parents=True, exist_ok=True)
        _extract(directory, value, target, names, stopped, lambda *_args: None)
        yield target, value


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
        temporary.rename(target)
    return {
        "path": str(target),
        "files": len(value["files"]),
        "kind": value["kind"],
        "id": value["id"],
        "restored": True,
    }


def reset(
    original,
    current,
    game,
    archive,
    *,
    keep=lambda _name: False,
    stopped=lambda: False,
    progress=lambda _count, _path: None,
):
    """Puts a game folder back to its ``original`` snapshot in place.

    ``current`` is a snapshot of the folder taken just before, so only the
    files that differ are written. Files the original lacks move into
    ``archive`` instead of being deleted, and ``keep`` names files left as
    they are, such as save games. Each file is written and synced beside its
    target before it replaces it, so an interruption leaves whole files, and
    running it again finishes the job.
    """
    root = Path(game).resolve(strict=True)
    before, after = manifest(original), manifest(current, root)
    if before["kind"] != "source" or after["kind"] != "source":
        raise ValueError("Only a game-file backup can put the game back.")
    verify(original, full=False, stopped=stopped)
    extras = sorted(
        name
        for name in after["files"]
        if name not in before["files"] and not keep(name)
    )
    changed = [
        name
        for name in before["files"]
        if not keep(name) and after["files"].get(name) != before["files"][name]
    ]
    count = 0
    for name in extras:
        _cancel(stopped)
        target = _child(archive, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _child(root, name).rename(target)
        except FileNotFoundError:
            continue
        count += 1
        progress(count, name)
    # Folders the original lacks go once empty; kept files hold theirs.
    for name in sorted(
        set(after["directories"]) - set(before["directories"]),
        key=lambda item: item.count("/"),
        reverse=True,
    ):
        path = _child(root, name)
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    for name in before["directories"]:
        _child(root, name).mkdir(parents=True, exist_ok=True)
    for name in changed:
        _cancel(stopped)
        target = _child(root, name)
        if target.is_dir():
            raise ValueError(
                f"{name} is a folder holding files kept in place. Move them, then try again."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".dazedtl-restore-" + uuid.uuid4().hex)
        try:
            _copy(original, before, name, temporary, stopped)
            try:
                temporary.replace(target)
            except PermissionError:
                # Windows refuses to replace a read-only file.
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
                temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        count += 1
        progress(count, name)
    return {"restored": len(changed), "set_aside": len(extras)}


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


def record_status(game, record, *, kind):
    """Inspect saved references without recreating stores or hashing every blob."""
    result = dict(record)
    try:
        location = lookup(game, Path(record["path"]).parent, record["id"])
        result["path"] = str(location)
        value = verify(location, source=game, full=False)
        if value["kind"] != kind:
            raise ValueError("The saved backup has the wrong content type.")
    except BackupMissing:
        # Its own message suits a refused restore; status callers prefix a title.
        result.update(available=False, issue="Its saved files could not be found.")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result.update(
            available=False,
            issue=str(exc)
            if isinstance(exc, ValueError)
            else "The saved backup could not be read.",
        )
    else:
        result.update(available=True, issue="")
    return result


def original(game):
    """The earliest game snapshot in the game's own store, where setup saves
    the original first. A project opened on a moved, copied or reinstalled
    game can take it over instead of saving its current files as the original.
    """
    root = store_path(game) / "snapshots"
    if _linked(root) or not root.is_dir():
        return None
    found = []
    for folder in root.iterdir():
        if not _ID.fullmatch(folder.name):
            continue
        try:
            value = manifest(folder)
        except OSError, ValueError, TypeError:
            continue
        if value["kind"] == "source" and value["version"] == 2:
            found.append((value["created"], str(folder), value))
    if not found:
        return None
    created, path, value = min(found)
    return {
        "id": value["id"],
        "path": path,
        "files": len(value["files"]),
        "kind": "source",
        "version": 2,
        "bytes_total": sum(value["sizes"].values()),
        "created": created,
    }


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
