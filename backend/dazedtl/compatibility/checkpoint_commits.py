"""Checkpoints: one commit on a game's translation branch for each change
DazedTL makes to the game, so the game's Git history is the one record of
its translation, and Git does every save and restore.

The game-write gateway ([game_write](game_write.py)) opens a checkpoint for
the outermost write to a game whose Git is set up and records it once the
write succeeds, after packing; a write that failed or stopped while writing
records nothing. One that wrote its files and then made no
checkpoint, as a failed checkpoint or pack or an ended process leaves it,
keeps the record it registered before writing, which names its change, and
the next checkpoint commits it under that name, marked with a
`DazedTL-Recovered` trailer (`_recover`). Opening one first records those,
then the changes made outside DazedTL since the last checkpoint as their own
(`outside_edits`), so a checkpoint holds only its write's change and no flow
waits for a clean worktree. Game updates keep their own commits and record
outside edits before they start.

A checkpoint commits every pending change Git sees in the patch, which is
the files the translation branch tracks or its .gitignore allows, and lets
the files its write names that the patch lacks into it (`grow_scope`). The
checkpoint of a DazedTL write lets in DazedTL's own runtime files the game
holds too (`dazedtl_files`), whichever write added them, since the
plugins.js loading Forge or the update check stops players' game at start
without them. A file outside the patch is the original game's, which the
`original` branch holds.

An assistant writes a game's text one file at a time, so the writes made
inside `in_phase` wait for one checkpoint of their phase instead of each
being one: a record in the Git folder names their files until `save` commits
the phase. Any other checkpoint first records the writes still waiting as
their phase's own. A waiting write leaves the edits made outside DazedTL to
the phase's checkpoint, since in an assistant's phase they are mostly its own.

Its message is one line, "<stage>: <summary>", then trailers naming the
action and the stage (`message`), so checkpoints group by stage without a
saved record. Every checkpoint has DazedTL's author, as all of DazedTL's
commits do.

Commits to one repository take turns through a lock in its Git folder, and
each write in progress registers the files it said it would change: another
checkpoint, or the outside-edits step, leaves those to it, and takes only its
own files while a write that said nothing runs. While the game's index
matches HEAD, as every checkpoint leaves it, the commit is built on a copy
of the index, which becomes the index under its lock while the index is
still as the status found it (`_on_index`); once the user staged changes,
it is built in a temporary index from HEAD's tree, so they stay as they are
(`_on_head`). Git commands that take the index lock wait for a leftover one
as `_run_git` does. A write refuses before it writes while the index lock is
held, and the game's index lock is taken before the branch moves, so one a
crashed Git left fails the write with nothing written or committed.

Each Git process is slow to start on Windows, so a checkpoint asks Git only
what it can't know: the write's read of the repository is carried through
it (`carrying`) and kept while the checkpoints leave what it read as it is
([game_write](game_write.py) `checkout`), and the tree and tracked files of
the commit it made last are kept for the next. A write's checkpoint then
costs a `git status` before the write, for the edits made outside DazedTL,
one after it and four Git calls that make the commit;
tests/test_git_launches.py holds each operation to its count.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

from dazedtl import system
from dazedtl.storage import exclusive, hold
from dazedtl.translation.git_status_cache import RepositoryStatusCache

if TYPE_CHECKING:
    from util.version_update.git_workflow import Checkout

ACTION_TRAILER = "DazedTL-Action"
STAGE_TRAILER = "DazedTL-Stage"
# The checkpoint a go back put the game back to.
TARGET_TRAILER = "DazedTL-Target"
# The action of a checkpoint holding changes made outside DazedTL.
OUTSIDE_EDITS = "outside_edits"
# A subject Git's one-line views show whole.
SUBJECT_LIMIT = 100


# Marks the checkpoint of a write committed after its write ended without one.
RECOVERED_TRAILER = "DazedTL-Recovered"
# The version of a write's record, which names its change so a write that
# ended without its checkpoint is committed under its own name; a record of
# another version is a write in progress's only.
WRITE_RECORD = 1


@dataclass(frozen=True)
class Change:
    """What one checkpoint records: a plain summary, the workflow stage it
    belongs to, and the action that made it."""

    summary: str
    stage: str | None = None
    action: str | None = None
    target: str | None = None
    recovered: bool = False


OUTSIDE = Change("Edits made outside DazedTL", None, OUTSIDE_EDITS)
# The action a worker runs, which names the checkpoints of its writes.
_running: ContextVar[Change | None] = ContextVar("checkpoint_change", default=None)
# The phase whose checkpoint the writes made in this context wait for.
_phase: ContextVar[Change | None] = ContextVar("checkpoint_phase", default=None)
# The record in the checkpoints folder of the writes waiting for their phase,
# JSON without the suffix that marks a write in progress's.
WAITING = "waiting.phase"


def for_action(name, label=None, stage=None):
    """The change an action makes, named by its row in the action registry,
    or by `label` and `stage` for an operation the registry doesn't hold.
    An Apply's own `label` names its tasks."""
    from dazedtl.actions import ACTIONS

    row = ACTIONS.get(name)
    if row and row.family == "apply" and label:
        return Change(label, row.stage, name)
    if row:
        return Change(row.label, row.stage, name)
    return Change(label or name, stage, name)


@contextmanager
def running(change):
    """Names the checkpoints of the writes made inside it."""
    token = _running.set(change)
    try:
        yield
    finally:
        _running.reset(token)


@contextmanager
def in_phase(change):
    """The writes made inside it wait for the checkpoint of the phase
    `change` names; None leaves each write its own."""
    token = _phase.set(change)
    try:
        yield
    finally:
        _phase.reset(token)


def current(action=None, summary=None, stage=None):
    """What a write's checkpoint records: its action's row, the action
    running around it, or its caller's summary."""
    if action:
        return for_action(action)
    return _running.get() or Change(summary or "Change game files", stage)


def message(change):
    """A checkpoint's commit message."""
    summary = " ".join(str(change.summary).split()) or "Change game files"
    subject = f"{change.stage}: {summary}" if change.stage else summary
    if len(subject) > SUBJECT_LIMIT:
        subject = subject[: SUBJECT_LIMIT - 1].rstrip() + "…"
    trailers = [f"{ACTION_TRAILER}: {change.action}"] if change.action else []
    if change.stage:
        trailers.append(f"{STAGE_TRAILER}: {change.stage}")
    if change.target:
        trailers.append(f"{TARGET_TRAILER}: {change.target}")
    if change.recovered:
        trailers.append(f"{RECOVERED_TRAILER}: true")
    return subject + ("\n\n" + "\n".join(trailers) if trailers else "")


def _folder(root):
    from util.version_update.git_workflow import _git_common_dir

    git = Path(root) / ".git"
    return (git if git.is_dir() else _git_common_dir(Path(root))) / (
        "dazedtl/checkpoints"
    )


def _record(path, value):
    """Writes one of the checkpoints folder's records, whose paths may hold a
    file name that isn't UTF-8, escaped so it reads back as it was."""
    system.write_text(path, json.dumps(value))


def _fields(change):
    return {
        "summary": change.summary,
        "stage": change.stage,
        "action": change.action,
        "target": change.target,
    }


class _Write:
    """A write in progress, registered before it writes with the files it
    said it would change and the change its checkpoint records; its lock,
    held while it runs, tells a live write from one whose process ended.

    A write that wrote its files but made no checkpoint, as a failed
    checkpoint or pack, a stop then or an ended process leaves it, keeps its
    record for the next checkpoint to commit (`_recover`). A write of a phase
    names no change, as the phase's checkpoint takes its files."""

    def __init__(self, folder, paths, change):
        self.folder = folder
        self.name = uuid.uuid4().hex
        self.handle = hold(folder / (self.name + ".lock"))
        self.value = {
            "version": WRITE_RECORD,
            "change": None if change is None else _fields(change),
            "paths": sorted(paths) if paths else None,
            "touched": [],
        }
        _record(folder / (self.name + ".json"), self.value)

    def close(self, touched=None):
        """Ends the write; `touched`, the files of a write that wrote them but
        made no checkpoint, keeps its record for the next checkpoint."""
        if touched is not None and self.value["change"] is not None:
            self.value["touched"] = sorted(set(_relative(touched)))
            _record(self.folder / (self.name + ".json"), self.value)
            if self.handle is not None:
                self.handle.close()
            return
        if self.handle is not None:
            self.handle.close()
        _forget(self.folder, self.name)


def _forget(folder, name):
    for suffix in (".json", ".lock"):
        system.unlink(folder / (name + suffix), missing_ok=True, ignore_errors=True)


def _writes(folder, own=None):
    """The records of the other writes, each with whether it is live: its
    process holds its lock."""
    for record in sorted(folder.glob("*.json")):
        name = record.stem
        if own is not None and name == own.name:
            continue
        handle = hold(folder / (name + ".lock"))
        if handle is not None:
            handle.close()
        try:
            value = json.loads(record.read_text(encoding="utf-8"))
        except OSError, ValueError:
            value = None
        yield name, handle is None, value if isinstance(value, dict) else {}


def _others(folder, own=None):
    """The files other writes in progress said they would change, or None
    while one of them said nothing."""
    claimed = set()
    for _name, live, value in _writes(folder, own):
        if not live:
            continue
        paths = value.get("paths")
        if not isinstance(paths, list):
            return None
        claimed.update(paths)
    return claimed


def _ended(value):
    """The change and files of a write that ended without its checkpoint,
    by its record, or None for a record that names none."""
    try:
        if value["version"] != WRITE_RECORD or value["change"] is None:
            return None
        change = Change(**value["change"], recovered=True)
        named = [*(value["paths"] or ()), *value["touched"]]
        return change, {str(path) for path in named}
    except KeyError, TypeError:
        return None


def _recover(root, folder, keep: AbstractSet[str] = frozenset()):
    """Commits each write that ended without its checkpoint as its own,
    under its name: the files it named or said it wrote, never edits made
    since. One that shares a file with `keep`, the files of the write
    recording its checkpoint, is left for that write's checkpoint to take,
    as the file now holds that write's change too. A record that names no
    change, or whose commit fails, is forgotten, its files left to the next
    checkpoint as pending changes, so no record stops every later write."""
    for name, live, value in _writes(folder):
        if live:
            continue
        ended = _ended(value)
        if ended and ended[1] & keep:
            continue
        try:
            if ended:
                _save(root, ended[0], ended[1], None)
        finally:
            _forget(folder, name)


def _relative(paths):
    for value in paths:
        path = PurePosixPath(str(value).replace("\\", "/"))
        if not path.is_absolute() and ".." not in path.parts and path.parts:
            yield path.as_posix()


def at(root):
    """The checkpoint the game is at and the tracked files changed since it,
    which the next checkpoint takes; None and none until its Git is set up."""
    from util.paths import game_git_set_up

    if not game_git_set_up(root):
        return None, frozenset()
    status = _status(root)
    if not status.head or status.head == "(initial)":
        return None, frozenset()
    return status.head, frozenset(status.paths - status.new)


# The files changed since a commit, which Git's metadata alone decides, for
# the few records polls compare.
_since = RepositoryStatusCache(stable=True)


def changed_since(root, commit):
    """The files the checkpoints since `commit` added, changed or removed,
    from its tree and the one the game is at, so a file an undo put back as
    it was is not among them. None when the game cannot tell, as without Git
    or with `commit` no longer in its history."""
    from util.paths import game_git_set_up

    def compute():
        if not game_git_set_up(root):
            return None
        found = _git(
            root,
            "diff-tree",
            "-r",
            "-z",
            "--no-renames",
            "--name-only",
            commit,
            "HEAD",
            check=False,
        )
        if found.returncode != 0:
            return None
        return frozenset(path for path in found.stdout.split("\0") if path)

    if len(_since.entries) >= 64:
        _since.clear()
    return _since.get((str(root), commit), root, compute)


def _git(root, *args, **options):
    """Runs Git in the game. Paths Git prints keep the bytes of a file name
    that isn't UTF-8, as Python names the file, so a restore writes the file
    it read."""
    from util.version_update.git_workflow import _run_git

    options.setdefault("errors", "surrogateescape")
    return _run_git(Path(root), *args, **options)


def _pending(root):
    """The files Git sees changed in the patch: tracked files changed or
    deleted, and new files the ignore rules let in."""
    return _status(root).paths


class _Status(NamedTuple):
    """What one `git status` says of the game."""

    # `_pending`, and the new files among them.
    paths: set[str]
    new: set[str]
    # The commit HEAD is at, "(initial)" on a branch with no commit yet.
    head: str | None
    # The game's index as Git left it (`_mark`) once it found the index
    # matching HEAD, so a commit can be built on it (`_on_index`); None
    # while the index holds staged changes or can't be read.
    index: tuple | None


def _status(root):
    """`_pending`, the commit HEAD is at and the new files among `_pending`,
    from one `git status`, and the index while it matches HEAD."""
    listing = _git(
        root,
        "status",
        "--porcelain=v2",
        "--branch",
        "--no-ahead-behind",
        "-z",
        "--no-renames",
        "--untracked-files=all",
        "--ignore-submodules=all",
    ).stdout
    # As soon as Git is done, so nothing can stage a change in between.
    index = _known_index(root)
    mark = None if index is None else _mark(index)
    paths, head, new, staged = set(), None, set(), False
    for entry in listing.split("\0"):
        # Each kind of entry has its own number of fields before the path.
        kind, _, rest = entry.partition(" ")
        if kind == "#" and rest.startswith("branch.oid "):
            head = rest.removeprefix("branch.oid ")
        elif kind in _PATH_FIELDS:
            path = entry.split(" ", _PATH_FIELDS[kind])[-1]
            paths.add(path)
            if kind == "?":
                new.add(path)
            # A changed entry's first status letter compares the index with
            # HEAD; an unmerged one is staged too.
            staged = staged or kind == "u" or (kind == "1" and rest[:1] != ".")
    # The status leaves out submodules, staged changes to them included.
    staged = staged or (Path(root) / ".gitmodules").exists()
    return _Status(paths, new, head, None if staged else mark)


# The fields before the path in each kind of `git status --porcelain=v2`
# entry: changed, unmerged and untracked.
_PATH_FIELDS = {"1": 8, "u": 10, "?": 1}
# The trees of the latest commits checkpoints made or started from, so the
# next checkpoint compares its tree with its parent's without asking Git; a
# commit's tree never changes.
_trees: dict[str, str] = {}


def _tree(root, commit, tree=None):
    """The tree of `commit`, which is `tree` when given, or the carried read
    of the repository's when it read that commit."""
    known = _trees.get(commit)
    if known is None:
        if tree is None:
            from util.version_update.git_workflow import _carried

            carried = _carried.get()
            if carried is not None and carried.translation_commit == commit:
                tree = carried.translation_tree
        known = tree or _git(root, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
        if len(_trees) >= 64:
            _trees.clear()
        _trees[commit] = known
    return known


# The files the game's index tracked at a commit while it matched HEAD
# there, which the next checkpoint at that commit reuses: a checkpoint built
# on the index knows what it changed (`_commit`).
_tracked_at: dict[str, tuple[str, frozenset[str]]] = {}


def _tracked(root, status):
    """The files the game's index tracks, by `status`, the game's
    `_status`."""
    known = _tracked_at.get(str(root))
    if status.index is not None and known is not None and known[0] == status.head:
        return known[1]
    files = frozenset(_git(root, "ls-files", "-z").stdout.split("\0")) - {""}
    if status.index is not None and status.head:
        _track(root, status.head, files)
    return files


def _track(root, commit, files):
    if len(_tracked_at) >= 16:
        _tracked_at.clear()
    _tracked_at[str(root)] = (commit, files)


def _mark(index):
    """The game's index file as it is, to tell whether it changed: its stat
    and its last bytes, which hold Git's checksum of the rest; None while it
    can't be read."""
    read = _read_index(index, whole=False)
    return None if read is None else read[0]


def _read_index(index, whole=True):
    """`_mark` of the game's index file and its bytes, all of them when
    `whole`, read through one handle so the two always belong together."""
    try:
        with open(index, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not whole:
                handle.seek(max(0, info.st_size - 64))
            raw = handle.read()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ino, raw[-64:]), raw


class _Moved(Exception):
    """The game's index changed since its status found it matching HEAD."""


def _commit(root, paths, change, status):
    """Commits `paths` as they are in the game on top of the commit HEAD is
    at by `status`, the game's `_status`, or None when that changes nothing.
    While the index matches HEAD, as every checkpoint leaves it unless the
    user staged changes, the commit is built on a copy of the index, which
    then becomes the game's (`_on_index`); otherwise it is built on HEAD's
    tree, so the user's staged changes stay as they are (`_on_head`)."""
    head = status.head
    if head is None or head == "(initial)":
        # Git fails a branch with no commit here, as it did before.
        head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    game_index, before = _index(root), _tree(root, head)
    listed = "".join(path + "\0" for path in sorted(paths))
    text = message(change)
    try:
        if status.index is None:
            raise _Moved
        made = _on_index(root, game_index, status.index, head, before, listed, text)
    except _Moved:
        _tracked_at.pop(str(root), None)
        made = _on_head(root, game_index, head, before, listed, text)
    else:
        known = _tracked_at.get(str(root))
        if made is not None and known is not None and known[0] == head:
            present = {path for path in paths if os.path.lexists(Path(root) / path)}
            _track(root, made[1], (known[1] - set(paths)) | present)
    if made is None:
        return None
    tree, commit = made
    _tree(root, commit, tree)
    return commit


def _on_head(root, game_index, head, before, listed, text):
    """Builds the commit of the `listed` files on `head`'s tree in a
    temporary index, then moves the branch (`_move`); returns its tree and
    commit, or None when it changes nothing."""
    from util.version_update.git_workflow import _commit_tree, _temporary_index

    index, environment = _temporary_index()
    try:
        _git(root, "read-tree", head, env=environment)
        _stage(root, environment, listed)
        tree = _git(root, "write-tree", env=environment).stdout.strip()
    finally:
        system.unlink(index, ignore_errors=True)
    if tree == before:
        return None
    commit = _commit_tree(Path(root), tree, text, (head,))
    _move(root, game_index, head, commit, text.splitlines()[0], listed)
    return tree, commit


def _stage(root, environment, listed):
    _git(
        root,
        "update-index",
        "--add",
        "--remove",
        "-z",
        "--stdin",
        env=environment,
        input_text=listed,
    )


def _on_index(root, game_index, mark, head, before, listed, text):
    """Builds the commit of the `listed` files on a copy of the game's index,
    which matched HEAD as `mark` found it, then makes the copy the game's
    index as the branch moves (`_install`), as `git commit` leaves it.
    Returns the commit's tree and commit, or None when it changes nothing;
    raises `_Moved` when the index changed since `mark`, before the copy or
    by the time the index lock is taken, for `_on_head` to build it instead,
    so nothing staged since the status joins the commit."""
    from util.version_update.git_workflow import (
        _commit_tree,
        _temporary_index,
        wait_for_index_lock,
    )

    # A lock a crashed Git left fails it before it builds anything.
    wait_for_index_lock(game_index.with_name(game_index.name + ".lock"))
    read = _read_index(game_index)
    if read is None or read[0] != mark:
        raise _Moved
    built, environment = _temporary_index()
    try:
        system.write_bytes(built, read[1])
        _stage(root, environment, listed)
        tree = _git(root, "write-tree", env=environment).stdout.strip()
        if tree == before:
            return None
        commit = _commit_tree(Path(root), tree, text, (head,))

        def index():
            if _mark(game_index) != mark:
                raise _Moved
            return Path(built).read_bytes()

        _install(root, game_index, head, commit, text.splitlines()[0], index)
    finally:
        system.unlink(built, ignore_errors=True)
    return tree, commit


def _move(root, game_index, head, commit, subject, listed):
    """Moves the branch from `head` to `commit`, and the game's index takes
    the `listed` files as committed, as `git commit` leaves it (`_install`)."""
    from util.version_update.git_workflow import _temporary_index

    staged, environment = _temporary_index()

    def index():
        if game_index.is_file():
            system.write_bytes(staged, game_index.read_bytes())
            _git(
                root,
                "reset",
                "-q",
                commit,
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                env={**environment, "GIT_LITERAL_PATHSPECS": "1"},
                input_text=listed,
            )
        else:
            _git(root, "read-tree", commit, env=environment)
        return Path(staged).read_bytes()

    try:
        _install(root, game_index, head, commit, subject, index)
    finally:
        system.unlink(staged, ignore_errors=True)


def _install(root, game_index, head, commit, subject, index):
    """Moves the branch from `head` to `commit` and makes `index()` the
    game's index. `index` runs under the index lock, taken first and waited
    for as `_run_git` waits: a lock a crashed Git left fails the write with
    nothing committed, and once the branch moved nothing fails it."""
    from util.version_update.git_workflow import _open_index_lock

    lock = game_index.with_name(game_index.name + ".lock")
    handle = _open_index_lock(lock)
    try:
        with handle:
            handle.write(index())
        # Moves the branch only if nothing else moved it since.
        _git(root, "update-ref", "-m", "checkpoint: " + subject, "HEAD", commit, head)
    except BaseException:
        system.unlink(lock, missing_ok=True, ignore_errors=True)
        raise
    try:
        system.replace(lock, game_index)
    except OSError:
        # The checkpoint stands; Git shows its files as staged until the
        # next checkpoint that takes them.
        system.unlink(lock, missing_ok=True, ignore_errors=True)


def _waiting(folder):
    """The phase the waiting writes belong to and their files, or None."""
    try:
        value = json.loads((folder / WAITING).read_text(encoding="utf-8"))
        return Change(**value["change"]), set(value["paths"])
    except FileNotFoundError:
        return None
    except OSError, ValueError, KeyError, TypeError:
        # A record that can't be read leaves its files to the next checkpoint
        # as pending changes.
        system.unlink(folder / WAITING, missing_ok=True, ignore_errors=True)
        return None


def _settle(root, folder, change=None):
    """Commits the writes waiting for their phase as its checkpoint, or,
    when they wait for `change`, returns their files for its checkpoint to
    take."""
    waiting = _waiting(folder)
    if waiting is None:
        return set()
    phase, paths = waiting
    if phase == change:
        return paths
    _save(root, phase, paths, None)
    system.unlink(folder / WAITING, missing_ok=True)
    return set()


def _wait(root, folder, change, paths):
    """Adds a write's files to the writes waiting for `change`'s checkpoint."""
    paths = set(_relative(paths)) | _settle(root, folder, change)
    _record(
        folder / WAITING,
        {
            "change": {
                "summary": change.summary,
                "stage": change.stage,
                "action": change.action,
            },
            "paths": sorted(paths),
        },
    )


def _save(root, change, named, claimed):
    """Commits the pending changes `claimed`, another write's, leaves out,
    or only the `named` ones while `claimed` is None, with the named files
    and DazedTL's own runtime files the patch lacks let into it."""
    return _saving(root, change, named, claimed)[0]


def _saving(root, change, named, claimed):
    """`_save`'s commit, and the commit HEAD is at once it is done."""
    from util.len_patch_scope import dazedtl_files, grow_scope

    named = set(_relative(named))
    status = _status(root)
    # DazedTL's own files are never edits made outside it.
    own = (
        set()
        if change is OUTSIDE
        else dazedtl_files(Path(root)).keys() - (claimed or set())
    )
    joined = set()
    # A new file that another rule lets in, as the Image Manager's .gitignore
    # section lets in an image it applied, still joins the patch's own rules,
    # which drop it from the inventory of the original's files Git leaves out.
    if outside := (named | own) - (status.paths - status.new):
        tracked = _tracked(root, status)
        added, rules = grow_scope(
            Path(root),
            tracked,
            [p for p in outside if p not in tracked and (Path(root) / p).is_file()],
        )
        joined = {*added, *rules}
        if rules:
            # New rules can let in files they hid, such as the portable
            # settings an old rule order kept out.
            status = _status(root)
    pending = status.paths
    chosen = joined | (pending & named if claimed is None else pending - claimed)
    commit = _commit(root, chosen, change, status) if chosen else None
    return commit, commit or (status.head if status.head != "(initial)" else None)


def save(root, change, named=()):
    """Records the pending changes in the patch, and the `named` files the
    patch lacks, as one checkpoint; for work committed outside a game write,
    such as an assistant's own edits and a phase's waiting writes. Writes
    waiting for another phase are its checkpoint first. Letting files in
    rewrites .gitignore, a write of the gateway's own."""
    from .game_write import writing

    folder = _folder(root)
    token = writing.set(writing.get() | {str(Path(root).resolve())})
    try:
        with exclusive(folder / "checkpoint.lock"):
            _recover(root, folder)
            waiting = _settle(root, folder, change)
            commit = _save(root, change, [*named, *waiting], _others(folder))
            system.unlink(folder / WAITING, missing_ok=True)
            return commit
    finally:
        writing.reset(token)


def outside_edits(root):
    """Records the writes waiting for their phase as its checkpoint, then the
    changes made in the patch outside DazedTL as their own, leaving the files
    of writes in progress to them."""
    folder = _folder(root)
    with exclusive(folder / "checkpoint.lock"):
        _recover(root, folder)
        _settle(root, folder)
        claimed = _others(folder)
        if claimed is not None:
            return _save(root, OUTSIDE, (), claimed)
    return None


def _index(root) -> Path:
    """The game's index file."""
    if (known := _known_index(root)) is not None:
        return known
    found = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "index")
    return Path(found.stdout.strip())


def _known_index(root) -> Path | None:
    """The game's index file when Git need not say where it is: as the
    carried read of the repository found it, or in the game's own .git
    folder."""
    from util.version_update.git_workflow import _carried

    carried = _carried.get()
    if carried is not None and carried.selected_root == Path(root).resolve():
        return carried.index
    git = Path(root) / ".git"
    return git / "index" if git.is_dir() else None


def recovered_text(root, relative):
    """The text of the file at `relative` before and after the latest
    checkpoint that changed it, None where there was no file, when that
    checkpoint is a context save (stage Context, no action) committed after
    it ended without its checkpoint and the file is as it left it; a run's or
    QA's change to it is another's, so otherwise None."""
    from util.paths import game_git_set_up

    if not game_git_set_up(root):
        return None

    def trailer(key):
        return f"%(trailers:key={key},valueonly,separator=)"

    found = _git(
        root,
        "log",
        "-1",
        "--format=%H %x00"
        + "%x00".join(
            trailer(key) for key in (RECOVERED_TRAILER, STAGE_TRAILER, ACTION_TRAILER)
        ),
        "--",
        relative,
    )
    commit, _, rest = found.stdout.strip().partition(" \0")
    mark, stage, action = (
        value.strip() for value in (rest.split("\0") + ["", "", ""])[:3]
    )
    if not commit or mark != "true" or stage != "Context" or action:
        return None
    if _git(root, "status", "--porcelain", "--", relative).stdout.strip():
        return None

    def text(revision):
        shown = _git(root, "show", f"{revision}:{relative}", check=False)
        return shown.stdout.removeprefix("﻿") if shown.returncode == 0 else None

    return text(commit + "^"), text(commit)


class Checkpoint:
    """The checkpoint of one write in progress, or, inside `in_phase`, its
    place among the writes waiting for their phase's.

    It refuses before the write while the game's index lock is held, waiting
    once as Git commands do, since the checkpoint would fail after it; the
    writes that ended without their checkpoint are then committed as their
    own, and the edits made outside DazedTL as theirs."""

    def __init__(
        self,
        root,
        paths: Iterable[str] | None,
        change: Change,
        checkout: Checkout | None = None,
    ):
        from util.version_update.git_workflow import carrying

        self.root = Path(root)
        self.folder = _folder(root)
        self.paths = list(_relative(paths or ()))
        self.phase = _phase.get()
        # The read of the repository the write checked, whose settings,
        # index path and branch tree its Git calls reuse.
        self.checkout = checkout
        # The commit HEAD was at once the edits made outside DazedTL were
        # saved, when that step ran.
        self.start: str | None = None
        with carrying(checkout):
            self._open(change)

    def _open(self, change):
        from util.version_update.git_workflow import wait_for_index_lock

        wait_for_index_lock(_index(self.root).with_name("index.lock"))
        with exclusive(self.folder / "checkpoint.lock"):
            if self.phase is None:
                _recover(self.root, self.folder)
            claimed = None if self.phase else _others(self.folder)
            self.write = _Write(self.folder, self.paths, None if self.phase else change)
            if self.phase is not None:
                return
            try:
                _settle(self.root, self.folder)
                if claimed is not None:
                    self.start = _saving(self.root, OUTSIDE, (), claimed)[1]
            except BaseException:
                self.write.close()
                raise

    def record(self, change, touched=()):
        """Commits the write's change once it succeeded, or adds it to the
        writes waiting for its phase; returns its commit, or None when it
        changed nothing or waits."""
        from util.version_update.git_workflow import carrying

        with carrying(self.checkout), exclusive(self.folder / "checkpoint.lock"):
            if self.phase is not None:
                return _wait(
                    self.root, self.folder, self.phase, [*self.paths, *touched]
                )
            # A write that named no files may have changed any, so the
            # writes that ended before it are left to its checkpoint.
            if mine := set(_relative([*self.paths, *touched])):
                _recover(self.root, self.folder, mine)
            return _save(
                self.root,
                change,
                [*self.paths, *touched],
                _others(self.folder, self.write),
            )

    def close(self, touched=None):
        """Ends the write; `touched`, the files of a write that wrote them
        but made no checkpoint, leaves it for the next checkpoint to commit
        under its name."""
        self.write.close(touched)
