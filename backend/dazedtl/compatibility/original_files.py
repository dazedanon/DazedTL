"""The original game's files, kept in the game's own Git repository.

The `original` branch holds only the files a patch can change, and it is
published with the translation, so the whole game as DazedTL found it is
kept under a private ref instead, `refs/dazedtl/originals`, which no branch
push sends. Each of its commits holds every file of a game folder but `.git`
and `.dazedtl`, in native bytes, and says which kind of record it is in a
`DazedTL-Original` trailer:

- `found`: the game before DazedTL first changes it. The game-write gateway
  records it before the first write to a game whose Git is not set up, so
  even the Git repository may start with it.
- `prepared`: the game as its Git baseline is made, after preparation, and
  the prepared release a game update brings in, with its version.
- `update`: a new official release as the user chose it, before it is laid
  out as the game.

Nothing is ever removed from the ref, so a game's records keep every version
DazedTL saw; identical files are one Git object. Saved backups from before
these records stay readable through [originals](../translation/originals.py),
which picks the record each reader needs.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from dazedtl import system
from dazedtl.storage import exclusive

from .checkpoint_commits import _git

REF = "refs/dazedtl/originals"
KIND_TRAILER = "DazedTL-Original"
VERSION_TRAILER = "DazedTL-Version"
FOUND, PREPARED, UPDATE = "found", "prepared", "update"
_SUBJECTS = {
    FOUND: "Original game files as DazedTL found them",
    PREPARED: "Original game files as prepared",
    UPDATE: "Official release files",
}
# Files hashed by one Git process, so progress and a stop come between them.
_CHUNK = 2000
# Blobs at least this large are written by a Git process of their own rather
# than read into memory with others.
_LARGE = 32 * 1024 * 1024
# The game's folders no record holds: Git's and DazedTL's own.
_OWN = frozenset({".git", ".dazedtl"})


@dataclass(frozen=True)
class Record:
    commit: str
    kind: str
    version: str


def _folder(root):
    from .checkpoint_commits import _folder as checkpoints

    return checkpoints(root).parent


def _trailer(message, key):
    for line in message.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip()
    return ""


# A record never changes once made, so what was read of one is kept by its
# commit, and a game's list of records by the tip of its ref.
_READ: dict[tuple[str, str, str], Any] = {}


def _kept(key, read):
    if key not in _READ:
        if len(_READ) > 64:
            _READ.clear()
        _READ[key] = read()
    return _READ[key]


def _tip(root):
    """The commit the ref names, read from the Git folder without a Git
    process, or "" without one."""
    git = Path(root) / ".git"
    try:
        return (git / REF).read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        packed = (git / "packed-refs").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in packed.splitlines():
        if line.endswith(" " + REF):
            return line.split(" ", 1)[0]
    return ""


def records(root) -> list[Record]:
    """The game's records, oldest first; none without a repository."""
    root = Path(root)
    if not (root / ".git").is_dir():
        return []
    tip = _tip(root)
    if not tip:
        return []
    return list(_kept((str(root), "records", tip), lambda: _records(root)))


def _records(root):
    log = _git(root, "log", "--first-parent", "--format=%H%x1f%B%x1e", REF).stdout
    rows = []
    for entry in log.split("\x1e"):
        if "\x1f" not in entry:
            continue
        commit, message = entry.strip("\n").split("\x1f", 1)
        rows.append(
            Record(
                commit,
                _trailer(message, KIND_TRAILER),
                _trailer(message, VERSION_TRAILER),
            )
        )
    return rows[::-1]


def chosen(root, kind, version=None):
    """The record a reader of `kind` takes: the oldest `found`, the game as
    DazedTL first found it, or the newest record of another kind, of
    `version` when given; None without one."""
    rows = [row for row in records(root) if row.kind == kind]
    if version is not None:
        rows = [row for row in rows if row.version == version]
    if not rows:
        return None
    return rows[0] if kind == FOUND else rows[-1]


def recorded(root):
    """Whether the game has its original files recorded, from one look at
    its Git folder, for polls."""
    return (Path(root) / ".git").is_dir() and bool(_tip(root))


def _relative(name):
    if any(ord(char) < 32 for char in name) or "\\" in name:
        raise ValueError(
            f"Git can't keep the file name {name!r}."
            " Rename it or move it out of the folder, then try again."
        )
    return name


def held(relative):
    """Whether a record holds the file at `relative` in the game folder:
    every file but those in `.git` and `.dazedtl`."""
    parts = PurePosixPath(str(relative).replace("\\", "/")).parts
    return not parts or parts[0] not in _OWN


def has_files(folder):
    """Whether `folder` holds a file a record holds, from as much of a walk
    as finds the first, for requests."""
    for directory, names, entries in os.walk(folder):
        if Path(directory) == Path(folder):
            names[:] = [name for name in names if held(name)]
            entries = [name for name in entries if held(name)]
        if entries:
            return True
    return False


def inventory(folder, stopped=lambda: False):
    """Every file of `folder` a record holds, with what says it changed:
    size, modification time and mode."""

    def failed(error):
        raise error

    files = {}
    for directory, names, entries in os.walk(folder, onerror=failed):
        if stopped():
            raise InterruptedError("Stopped before the original files were recorded.")
        here = Path(directory)
        if here == folder:
            names[:] = [name for name in names if held(name)]
            entries = [name for name in entries if held(name)]
        for name in names + entries:
            path = here / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                os.name == "nt"
                and info.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
            ):
                raise ValueError(
                    f"{path.relative_to(folder).as_posix()} is a symbolic link"
                    " or junction, which DazedTL can't keep as an original file."
                )
        for name in entries:
            path = here / name
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("DazedTL keeps regular files only.")
            relative = _relative(path.relative_to(folder).as_posix())
            executable = os.name != "nt" and bool(info.st_mode & stat.S_IXUSR)
            files[relative] = (info.st_size, info.st_mtime_ns, executable)
    return files


def _repository(root):
    """The game's own repository, made when the game has none; its Git
    baseline configures it later. Files are kept with `--no-filters`, so no
    setting changes their bytes."""
    from util.version_update.git_workflow import TRANSLATION_BRANCH

    if not (root / ".git").exists():
        _git(root, "init", "-q", "-b", TRANSLATION_BRANCH)


def record(
    root,
    kind,
    version="",
    *,
    folder=None,
    over=None,
    stopped=lambda: False,
    progress=lambda _message: None,
):
    """Records every file of `folder`, the game itself by default, as the
    game's newest record of `kind`, and returns its commit; with `over`, a
    record the folder's files are laid over, as a patch is over the game. A
    folder that changes while it is read records nothing."""
    from util.version_update.git_workflow import _temporary_index

    root = Path(root).resolve(strict=True)
    folder = root if folder is None else Path(folder).resolve(strict=True)
    if kind not in _SUBJECTS:
        raise ValueError("Unknown kind of original record.")
    _repository(root)
    before = inventory(folder, stopped)
    if not before:
        raise ValueError("There are no game files to record.")
    names = sorted(before)
    blobs = []
    for start in range(0, len(names), _CHUNK):
        if stopped():
            raise InterruptedError("Stopped before the original files were recorded.")
        chunk = names[start : start + _CHUNK]
        listed = "".join(str(folder / name) + "\n" for name in chunk)
        hashed = _git(
            root,
            "hash-object",
            "-w",
            "--no-filters",
            "--stdin-paths",
            input_text=listed,
            timeout=3600,
        ).stdout.split()
        if len(hashed) != len(chunk):
            raise ValueError("Git did not keep every original file.")
        blobs.extend(hashed)
        progress(
            f"Recorded {start + len(chunk):,} original file"
            f"{'' if start + len(chunk) == 1 else 's'} in Git · {chunk[-1]}"
        )
    if inventory(folder, stopped) != before:
        raise ValueError(
            "The game's files changed while DazedTL recorded them. Try again"
            " once nothing else is changing them."
        )
    lines = "".join(
        f"{'100755' if before[name][2] else '100644'} {blob}\t{name}\0"
        for name, blob in zip(names, blobs)
    )
    index, environment = _temporary_index()
    try:
        if over:
            _git(root, "read-tree", over, env=environment)
        _git(
            root,
            "update-index",
            "--add",
            "-z",
            "--index-info",
            env=environment,
            input_text=lines,
        )
        tree = _git(root, "write-tree", env=environment).stdout.strip()
    finally:
        system.unlink(index, ignore_errors=True)
    trailers = [f"{KIND_TRAILER}: {kind}"]
    if version:
        trailers.append(f"{VERSION_TRAILER}: {version}")
    text = (
        _SUBJECTS[kind]
        + (f" ({version})" if version else "")
        + "\n\n"
        + "\n".join(trailers)
    )
    from util.version_update.git_workflow import _TOOL_EMAIL, _TOOL_NAME

    with exclusive(_folder(root) / "originals.lock"):
        parent = _tip(root)
        commit = _git(
            root,
            "-c",
            f"user.name={_TOOL_NAME}",
            "-c",
            f"user.email={_TOOL_EMAIL}",
            "commit-tree",
            tree,
            *(("-p", parent) if parent else ()),
            input_text=text,
        ).stdout.strip()
        _git(
            root,
            "update-ref",
            "-m",
            "originals: " + text.splitlines()[0],
            REF,
            commit,
            parent or "0" * 40,
        )
    return commit


def ensure_found(root, log=lambda _message: None, stopped=lambda: False):
    """Records the game as found unless it has a record already, as the
    [background record](original_record.py) does when DazedTL opens the game
    and the game-write gateway outside a request before writing to a game
    whose Git is not set up. Only one record of a game runs at a time; one
    that starts while another runs waits for it, then finds its record."""
    root = Path(root).resolve(strict=True)
    if recorded(root):
        return None
    _repository(root)
    with exclusive(_folder(root) / "found.lock"):
        # A folder with no files yet has none to keep.
        if recorded(root) or not inventory(root, stopped):
            return None
        log("Recording the original game files in Git.")
        return record(root, FOUND, stopped=stopped, progress=log)


def files(root, commit) -> dict[str, tuple[str, str, int]]:
    """A record's files: path to (mode, blob, size)."""
    return dict(_kept((str(root), "files", commit), lambda: _files(root, commit)))


def _files(root, commit):
    listing = _git(root, "ls-tree", "-r", "-z", "-l", commit).stdout
    result = {}
    for entry in listing.split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        mode, kind, blob, size = metadata.split()
        if kind == "blob":
            result[path] = (mode, blob, int(size))
    return result


def peek(root, blob, size):
    """The first `size` bytes of one blob, such as an archive's index."""
    with system.popen(
        ["git", "-C", str(root), "cat-file", "blob", blob],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        assert process.stdout is not None
        data = process.stdout.read(size)
        process.kill()
    return data


# Readers such as plugin scans take the same few original files again and
# again; a blob's bytes never change, so small ones are kept in memory.
_BLOBS: dict[str, bytes] = {}
_BLOB_LIMIT = 256 * 1024
_BLOBS_LIMIT = 16 * 1024 * 1024
_held = [0]


def _keep_blob(blob, raw):
    if len(raw) > _BLOB_LIMIT or blob in _BLOBS:
        return
    if _held[0] + len(raw) > _BLOBS_LIMIT:
        _BLOBS.clear()
        _held[0] = 0
    _BLOBS[blob] = raw
    _held[0] += len(raw)


def write(root, entries: Iterable[tuple[str, str, int]], target, stopped):
    """Writes blobs to files: each entry is (blob, path under `target`, size).
    Small blobs are read a few at a time, large ones streamed one by one."""
    from .checkpoint_history import _blob_contents

    target = Path(target)
    small, large = {}, []
    for blob, path, size in entries:
        if size >= _LARGE:
            large.append((blob, path))
        else:
            small.setdefault(blob, []).append(path)
    kept = {blob: _BLOBS[blob] for blob in small if blob in _BLOBS}
    read = _blob_contents(root, [blob for blob in small if blob not in kept])
    for blob, raw in [*kept.items(), *read]:
        if stopped():
            raise InterruptedError("Stopped before every original file was written.")
        _keep_blob(blob, raw)
        for path in small[blob]:
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            system.write_bytes(destination, raw)
    for blob, path in large:
        if stopped():
            raise InterruptedError("Stopped before every original file was written.")
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".dazedtl-part")
        try:
            with temporary.open("wb") as handle:
                system.run(
                    ["git", "-C", str(root), "cat-file", "blob", blob],
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            system.replace(temporary, destination)
        finally:
            system.unlink(temporary, missing_ok=True, ignore_errors=True)


def identities(root, folder, names, stopped=lambda: False, *, keep=False):
    """The blob each file of `folder` named in `names` would be, kept in the
    game's Git only with `keep`."""
    names = list(names)
    result = {}
    for start in range(0, len(names), _CHUNK):
        if stopped():
            raise InterruptedError("Stopped before the game's files were compared.")
        chunk = names[start : start + _CHUNK]
        listed = "".join(str(Path(folder) / name) + "\n" for name in chunk)
        hashed = _git(
            root,
            "hash-object",
            *(["-w"] if keep else []),
            "--no-filters",
            "--stdin-paths",
            input_text=listed,
            timeout=3600,
        ).stdout.split()
        result.update(zip(chunk, hashed))
    return result


@contextmanager
def temporary(prefix):
    """A temporary folder outside the game, removed afterwards."""
    with system.staging_folder(tempfile.gettempdir(), prefix) as folder:
        yield Path(folder)
