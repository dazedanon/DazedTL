"""Bounded project files and portable, content-bound identities."""

import hashlib
import json
import os
import stat
from pathlib import Path

from dazedtl import system
from dazedtl.storage import write_json


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
    return decode_json(system.read_bytes(path))


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


def live_path(root, relative, *, exists=True):
    """project_path for a file other processes replace, such as a running
    run's job.json or its translated outputs. It checks the folder holding
    the file and the file's own name but never resolves the file: on Windows,
    resolving a file replaced meanwhile keeps a \\?\\ prefix that no longer
    lies inside root."""
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Use a project-relative path with forward slashes.")
    parent, _, name = relative.rpartition("/")
    if name.casefold() in {"", ".", "..", ".git"}:
        raise ValueError("Choose a file inside the selected game.")
    if parent:
        folder = project_path(root, parent, exists=False)
    else:
        folder = Path(root).resolve(strict=True)
        if not folder.is_dir():
            raise ValueError("The selected game folder is unavailable.")
    path = folder / name
    if Path(relative).anchor or path.parent != folder:
        # A rooted path, or a drive-relative name such as C:x on Windows,
        # would leave the folder.
        raise ValueError(
            "Files must stay inside the selected game and outside Git internals."
        )
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Project operations cannot follow symbolic links.")
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
        # A Digests shared by every observation. Paths are kept as strings: a
        # poll looks up thousands, and pathlib's own equality and hashing
        # would cost more than the listing saves.
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

    def digests_in(self, root, names):
        """digest(project_path(root, name)) for each name, settled from one
        listing of root: a poll compares every saved run's outputs, and
        looking each one up on its own took seconds on Windows."""
        folder = self.folder(root, "")
        entries = (self.listing(folder) if folder is not None else None) or {}
        result = {}
        for name in names:
            entry = entries.get(name) if "/" not in name and "\\" not in name else None
            if (
                folder is not None
                and entry is not None
                and entry.is_file(follow_symlinks=False)
                and name.casefold() not in {".", "..", ".git"}
            ):
                result[name] = self._digest(os.path.join(folder, name), entry)
            else:
                result[name] = self.digest(self.project_path(root, name))
        return result

    def digest(self, path):
        """A file's content digest, read again only after its listed stat
        signature changes."""
        key = os.fspath(path)
        return self._digest(key, self.entry(key))

    def _digest(self, key, entry):
        info = entry.stat(follow_symlinks=False) if entry else os.lstat(key)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Observed artifacts cannot be symbolic links.")
        return self.digests.file(key, info)


def evidence(root, paths):
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise ValueError("Supply unique source and guidance file paths.")
    return {
        relative: read_evidence(project_path(root, relative))[1] for relative in paths
    }


def read_evidence(path):
    """A file's stat and SHA-256 from one read; refuses a file that changed
    while it was read."""
    before = path.stat()
    with system.open_read(path) as stream:
        fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("A source file changed while it was being read.")
    return after, fingerprint


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
