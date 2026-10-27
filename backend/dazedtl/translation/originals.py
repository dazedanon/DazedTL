"""Where a project reads the original game's files.

A game's original files are recorded in its own Git repository
([original_files](../compatibility/original_files.py)). A project set up
before that keeps reading the backups it saved then, through the records its
`lifecycle.json` still holds, which DazedTL no longer writes:

- `found`, the game before DazedTL changed it, which plugin lookups, release
  file lists and Start over read: an old project's `source_backup` while it
  is readable, else the Git record.
- `prepared`, the game as its current version's baseline was made, which
  the census, checkpoint sources and packaging read: the Git record the
  `original` branch's tip holds (`original_files.prepared_record`), else an
  old `prepared_source`, else `found`.

Each is an `Original` with the same reads, so no reader knows which kind it
has.
"""

from __future__ import annotations

import hashlib
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from dazedtl import system
from dazedtl.compatibility import original_files

from . import backups


class Original:
    """One saved state of the game's files. `files` maps each file to an
    identity of its content, which another state's identity of the same
    content equals; `id` names the state for saved work keyed on it."""

    id: str
    files: dict[str, str]

    def peek(self, name, size):
        raise NotImplementedError

    def extract(self, names, target, stopped=lambda: False):
        """Writes `names` under `target`, a new or empty folder."""
        raise NotImplementedError

    def identify(self, root, names, stopped=lambda: False):
        """The content identities of files of the game at `root`."""
        raise NotImplementedError

    def blobs(self, root, names, stopped=lambda: False):
        """The (mode, blob) of each of `names`, kept in the game's Git at
        `root`."""
        names = [name for name in names if name in self.files]
        with self.materialized(names, stopped) as folder:
            kept = original_files.identities(root, folder, names, stopped, keep=True)
            return {
                name: (
                    "100755"
                    if (Path(folder) / name).stat().st_mode & stat.S_IXUSR
                    else "100644",
                    blob,
                )
                for name, blob in kept.items()
            }

    @contextmanager
    def materialized(self, files=None, stopped=lambda: False):
        """The saved files, or those of `files` it holds, as normal files in
        a temporary folder, for engine tools."""
        names = (
            list(self.files)
            if files is None
            else [name for name in files if name in self.files]
        )
        with original_files.temporary("dazedtl-originals-") as target:
            self.extract(names, target, stopped)
            yield target


class _Recorded(Original):
    def __init__(self, root, commit):
        self.root = Path(root)
        self.id = commit
        self.entries = original_files.files(root, commit)
        self.files = {name: row[1] for name, row in self.entries.items()}

    def peek(self, name, size):
        return original_files.peek(self.root, self.entries[name][1], size)

    def blobs(self, root, names, stopped=lambda: False):
        # The record's blobs are the game's own Git objects already.
        return {name: self.entries[name][:2] for name in names if name in self.entries}

    def extract(self, names, target, stopped=lambda: False):
        original_files.write(
            self.root,
            [(self.entries[n][1], n, self.entries[n][2]) for n in names],
            target,
            stopped,
        )
        for name in names:
            if self.entries[name][0] == "100755":
                path = Path(target) / name
                path.chmod(path.stat().st_mode | 0o111)

    def identify(self, root, names, stopped=lambda: False):
        return original_files.identities(self.root, Path(root), names, stopped)


class _Saved(Original):
    """A snapshot in an old backup store."""

    def __init__(self, location, value):
        self.location = location
        self.value = value
        self.id = value["id"]
        self.files = value["files"]

    def peek(self, name, size):
        return backups.peek(self.location, name, size)

    def extract(self, names, target, stopped=lambda: False):
        for name in names:
            output = Path(target) / name
            output.parent.mkdir(parents=True, exist_ok=True)
            backups._copy(self.location, self.value, name, output, stopped)

    def identify(self, root, names, stopped=lambda: False):
        result = {}
        for name in names:
            path = Path(root) / name
            if path.is_file():
                result[name] = backups._hash_file(path, stopped)
        return result


def _saved(workspace, project_id, root, record):
    """An old backup record's snapshot, or None once it can't be read."""
    if not isinstance(record, dict):
        return None
    try:
        # A record names its snapshot's folder; the profile's old store
        # holds the ones that don't.
        store = (
            Path(record["path"]).parent
            if record.get("path")
            else Path(workspace) / "backups" / project_id
        )
        location = backups.lookup(root, store, record["id"])
        value = backups.verify(location, full=False)
    except OSError, ValueError, KeyError, TypeError:
        return None
    return _Saved(location, value) if value["kind"] == "source" else None


def _lifecycle(workspace, project_id, state):
    if state is not None:
        return state
    from .operations import lifecycle

    return lifecycle(workspace, project_id)


def _record(root, row):
    return _Recorded(root, row.commit) if row else None


def found(workspace, project_id, root, state=None):
    """The game as DazedTL found it, or None."""
    root = Path(root)
    state = _lifecycle(workspace, project_id, state)
    return _saved(workspace, project_id, root, state.get("source_backup")) or (
        _record(root, original_files.found_record(root))
    )


def _current_version(root):
    from util.version_update.git_workflow import ORIGINAL_BRANCH

    from dazedtl.compatibility.checkpoint_commits import _git

    log = _git(root, "log", "-1", "--format=%B", ORIGINAL_BRANCH, "--", check=False)
    if log.returncode:
        return None
    return original_files._trailer(log.stdout, original_files.VERSION_TRAILER)


def recorded_now(root):
    """The Git record of the game as its current version is, the one a
    patch for the next version is laid over: its prepared record, else the
    game as found; None without either."""
    root = Path(root)
    row = original_files.prepared_record(root) or original_files.found_record(root)
    return row.commit if row else None


def stage(
    root,
    names,
    current,
    target,
    *,
    data=None,
    plugins=False,
    stopped=lambda: False,
):
    """Writes under `target`, laid out as the game is (`data/<name>`,
    `js/plugins.js`; engine util/original_values), the recorded original of
    each data file of `names`, such as Map001.json, whose copy in the folder
    `current` differs from it, and with `plugins` the original plugin list
    where the game's differs. `data` is the game's data folder, else the
    record's `data` or `www/data`. Writes nothing for a game whose original
    files are not recorded, or not yet; returns whether they are."""
    root = Path(root)
    commit = recorded_now(root) if original_files.recorded(root) else None
    if commit is None:
        return False
    entries = original_files.files(root, commit)
    if data is not None:
        folder = Path(data).resolve().relative_to(root.resolve()).as_posix()
        prefix = "" if folder == "." else folder.removesuffix("data")
    else:
        prefix = next(
            (
                prefix
                for prefix in ("", "www/")
                if any(f"{prefix}data/{name}" in entries for name in names)
            ),
            "",
        )
    wanted = [
        (f"{prefix}data/{name}", Path(current) / name, f"data/{name}") for name in names
    ]
    if plugins:
        wanted.append(
            (f"{prefix}js/plugins.js", root / prefix / "js/plugins.js", "js/plugins.js")
        )
    rows = []
    for name, path, staged in wanted:
        if name not in entries:
            continue
        _mode, blob, size = entries[name]
        if _blob(path, len(blob)) != blob:
            rows.append((blob, staged, size))
    original_files.write(root, rows, target, stopped)
    return True


@contextmanager
def staged(root, data, folder, prefix):
    """The game's recorded original data and plugin files that differ from
    the game's (:func:`stage`), staged in a folder under `folder` named from
    `prefix` and removed afterwards, as engine util/original_values reads
    them: the source of text that keeps none, for a never-translated list.
    None for a game whose originals are not recorded."""
    from util.original_values import Originals

    root, data = Path(root), Path(data)
    with system.staging_folder(folder, prefix) as target:
        names = [path.name for path in data.glob("*.json")]
        recorded = stage(root, names, data, target, data=data, plugins=True)
        yield Originals(target) if recorded else None


def _blob(path, length):
    """The Git blob ID of the file at `path` in a repository whose IDs are
    `length` hex digits long, or None without the file."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256 if length == 64 else hashlib.sha1
    return digest(b"blob %d\0" % len(raw) + raw).hexdigest()


def under_patch(
    workspace,
    project_id,
    root,
    state=None,
    *,
    stopped=lambda: False,
    progress=lambda _message: None,
):
    """The record a patch for the next version is laid over: `recorded_now`,
    or, for a game set up before Git kept its original files, the backup of
    its current version it saved then, recorded in Git first, so the next
    version's record holds every file and going back or undoing reads the
    files the patch added or changed outside the translation's patch from
    it; None without either."""
    root = Path(root)
    if over := recorded_now(root):
        return over
    backup = saved(workspace, project_id, root, state)
    if backup is None:
        return None
    progress("Recording the current version's original files in Git.")
    # Beside the game's Git objects, not in a temporary folder that may be
    # held in memory, since it holds the whole game.
    parent = original_files._folder(root)
    parent.mkdir(parents=True, exist_ok=True)
    with system.staging_folder(parent, "originals-") as folder:
        backup.extract(list(backup.files), folder, stopped)
        return original_files.record(
            root,
            original_files.PREPARED,
            _current_version(root) or "",
            folder=folder,
            stopped=stopped,
            progress=progress,
        )


def prepared(workspace, project_id, root, state=None, *, or_found=True):
    """The game as its current version's baseline was made, else, unless
    `or_found` is false, as DazedTL found it; or None."""
    root = Path(root)
    state = _lifecycle(workspace, project_id, state)
    recorded = None
    if original_files.recorded(root):
        recorded = _record(root, original_files.prepared_record(root))
    return (
        recorded
        or _saved(workspace, project_id, root, state.get("prepared_source"))
        or (found(workspace, project_id, root, state) if or_found else None)
    )


def hold_in_original(workspace, project_id, root, state=None, stopped=lambda: False):
    """Gives the `original` branch the original of each file the translation
    branch holds that it lacks, such as the ace_json a VX Ace game's
    checkpoints let into the patch, from the game as its current version's
    baseline was made, so a game update merges the translation of those
    files instead of replacing it with the release's
    (`git_workflow.hold_in_original`). Returns the commit, or None."""
    from util.version_update.git_workflow import hold_in_original as hold
    from util.version_update.git_workflow import original_lacks

    root = Path(root)
    lacking = original_lacks(root)
    original = (
        prepared(workspace, project_id, root, state, or_found=False)
        if lacking
        else None
    )
    if original is None:
        return None
    files = original.blobs(root, lacking, stopped)
    return hold(root, files) if files else None


def saved(workspace, project_id, root, state=None):
    """The backup of the game's current version a project set up before Git
    kept its original files saved then, which going back and undoing read
    for files outside the patch; None for a game Git keeps the original of,
    or when the backup can't be read."""
    root = Path(root)
    if original_files.recorded(root):
        return None
    try:
        return prepared(workspace, project_id, root, state)
    except OSError, ValueError:
        return None


MISSING = (
    "DazedTL has no record of this game's original files, and its backup from"
    " before checkpoints can't be read. Put the original game back in its"
    " folder and set it up again."
)


def require(workspace, project_id, root, state=None):
    """`found`, refusing without it."""
    original = found(workspace, project_id, root, state)
    if original is None:
        raise ValueError(MISSING)
    return original


def available(workspace, project_id, root, state=None):
    """Whether the game's original files are recorded, without reading
    them, for polls: a Git record or an old backup record."""
    state = _lifecycle(workspace, project_id, state)
    return original_files.recorded(root) or bool(state.get("source_backup"))


def by_id(workspace, project_id, root, identity, state=None):
    """The saved state an assistant named: a Git record's commit or an old
    backup's ID."""
    for row in original_files.records(root):
        if row.commit == identity:
            return _Recorded(root, row.commit)
    try:
        location = backups.lookup(
            root, Path(workspace) / "backups" / project_id, identity
        )
        value = backups.verify(location, full=False)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("No saved original has that ID.") from error
    return _Saved(location, value)


def game_names(workspace, project_id, root, state=None):
    """Every file name the game's records and old backups hold: its
    original, the prepared game and each update."""
    root = Path(root)
    state = _lifecycle(workspace, project_id, state)
    names = set()
    for row in original_files.records(root):
        names.update(original_files.files(root, row.commit))
    names |= backups.game_files(
        root,
        [
            state[key]
            for key in ("source_backup", "prepared_source", "game_backup")
            if state.get(key)
        ],
    )
    return names


def reset(
    original,
    root,
    archive,
    *,
    keep=lambda _name: False,
    stopped=lambda: False,
    progress=lambda _count, _path: None,
):
    """Puts a game folder back to `original` in place.

    Only files that differ are written. Files the original lacks move into
    `archive` instead of being deleted, and `keep` names files left as they
    are, such as save games. Each file is written beside its target before
    it replaces it, so an interruption leaves whole files, and running it
    again finishes the job.
    """
    root = Path(root).resolve(strict=True)
    current = original_files.inventory(root, stopped)
    extras = sorted(n for n in current if n not in original.files and not keep(n))
    candidates = [n for n in original.files if not keep(n)]
    present = original.identify(root, [n for n in candidates if n in current], stopped)
    changed = [n for n in candidates if present.get(n) != original.files[n]]
    count = 0
    emptied = set()
    for name in extras:
        if stopped():
            raise InterruptedError("Stopped before every original file was put back.")
        target = Path(archive) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            system.rename(root / name, target)
        except FileNotFoundError:
            continue
        emptied.update(
            parent.as_posix() for parent in PurePosixPath(name).parents if parent.parts
        )
        count += 1
        progress(count, name)
    # Folders left empty by files set aside go; other folders stay.
    for name in sorted(emptied, key=lambda item: item.count("/"), reverse=True):
        path = root / name
        if path.is_dir() and not any(path.iterdir()):
            system.rmdir(path)
    if not changed:
        return {"restored": 0, "set_aside": len(extras)}
    with system.staging_folder(
        root, ".dazedtl-restore-" + uuid.uuid4().hex[:8]
    ) as staged:
        original.extract(changed, staged, stopped)
        for name in changed:
            if stopped():
                raise InterruptedError(
                    "Stopped before every original file was put back."
                )
            target = root / name
            if target.is_dir():
                raise ValueError(
                    f"{name} is a folder holding files kept in place. Move them, then try again."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            # Windows refuses to replace a read-only file.
            if target.exists() and not target.stat().st_mode & stat.S_IWRITE:
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
            system.replace(staged / name, target)
            count += 1
            progress(count, name)
    return {"restored": len(changed), "set_aside": len(extras)}
