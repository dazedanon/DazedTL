"""Bounded project files and portable, content-bound identities."""

import hashlib
import json
import os
import stat
import time
from pathlib import Path

from dazedtl.storage import write_json

# File times advance in ticks of milliseconds, so a file written twice within
# one tick can keep its stat signature. Caches keyed by signatures keep only
# files that have been still for longer than this.
SETTLED_NS = 2_000_000_000


def settled(*modified_ns):
    """Whether every one of these modification times is safely in the past."""
    return time.time_ns() - max(modified_ns) > SETTLED_NS


def digest(value):
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def decode_json(raw):
    return json.loads(
        raw.decode("utf-8-sig"),
        object_pairs_hook=unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("JSON numbers must be finite.")
        ),
    )


def read_json(path, *, limit: int | None = 128_000_000):
    """A regular JSON file of at most `limit` bytes; None reads any size."""
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or limit is not None
        and path.stat().st_size > limit
    ):
        raise ValueError("Choose a regular JSON file within the supported size limit.")
    return decode_json(path.read_bytes())


def project_path(root, relative, *, exists=True):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The selected game folder is unavailable.")
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Use a project-relative path with forward slashes.")
    child = Path(relative)
    if child.is_absolute() or any(
        part.casefold() in {"..", ".git"} for part in child.parts
    ):
        raise ValueError(
            "Files must stay inside the selected game and outside Git internals."
        )
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


class ObservedFiles:
    """One observation's look at project files.

    A poll asks the same questions of hundreds of game files: is each a
    regular file inside its folder, and what does it hold. Each folder is
    listed once per observation, and a listed file's digest is reused across
    observations while its listed stat signature holds, so routine polls
    neither resolve paths nor reread unchanged files. Whatever a listing
    cannot settle, such as a missing file, a link or a name in another case,
    gets project_path's own answer or error. Execution and explicit
    inspection keep project_path and fresh reads.
    """

    def __init__(self, digests):
        # Shared by every observation; bounded below. Paths are kept as
        # strings: a poll looks up thousands, and pathlib's own equality and
        # hashing would cost more than the listing saves.
        self.digests = digests
        self.roots, self.folders, self.listings = {}, {}, {}

    def listing(self, folder):
        """A folder's entries by name, or None when it cannot be listed."""
        key = os.fspath(folder)
        if key not in self.listings:
            try:
                with os.scandir(key) as entries:
                    self.listings[key] = {entry.name: entry for entry in entries}
            except OSError:
                self.listings[key] = None
        return self.listings[key]

    def entry(self, path):
        """A regular file's listing entry, or None for anything else."""
        folder, name = os.path.split(os.fspath(path))
        entries = self.listing(folder)
        entry = entries.get(name) if entries else None
        return (
            entry
            if entry is not None and entry.is_file(follow_symlinks=False)
            else None
        )

    def folder(self, root, relative):
        """project_path's checks for a game folder, once per observation."""
        key = (os.fspath(root), relative)
        if key not in self.folders:
            try:
                root = Path(root).resolve(strict=True)
                path = project_path(root, relative, exists=False) if relative else root
                self.folders[key] = path if path.is_dir() else None
            except ValueError, OSError:
                self.folders[key] = None
        return self.folders[key]

    def project_path(self, root, relative):
        """project_path(root, relative) for an existing file."""
        if isinstance(relative, str) and "\\" not in relative:
            parent, _, name = relative.rpartition("/")
            folder = self.folder(root, parent)
            if (
                folder is not None
                and name.casefold() not in {"", ".", "..", ".git"}
                and self.entry(os.path.join(folder, name)) is not None
            ):
                return folder / name
        return project_path(root, relative)

    def digest(self, path):
        """A file's content digest, read again only after its listed stat
        signature changes."""
        key = os.fspath(path)
        entry = self.entry(key)
        info = entry.stat(follow_symlinks=False) if entry else os.lstat(key)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Observed artifacts cannot be symbolic links.")
        signature = (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        cached = self.digests.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        with open(key, "rb") as stream:
            value = digest(stream.read())
        if settled(info.st_mtime_ns):
            if len(self.digests) > 20_000:
                self.digests.clear()
            self.digests[key] = (signature, value)
        return value


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
    if (
        not isinstance(expected, dict)
        or not expected
        or evidence(root, list(expected)) != expected
    ):
        raise ValueError(
            "Source or guidance changed. Compile and review a new request plan."
        )


def write_project_json(root, relative, value):
    path = project_path(root, relative, exists=False)
    write_json(path, value)
    return path
