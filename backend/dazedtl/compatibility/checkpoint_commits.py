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
own files while a write that said nothing runs. The commit is built in a
temporary index, so the user's staged changes stay as they are, and Git
commands that take the index lock wait for a leftover one as `_run_git` does.
A write refuses before it writes while the index lock is held, and the
game's index lock is taken before the branch moves (`_move`), so one a
crashed Git left fails the write with nothing written or committed.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dazedtl import system
from dazedtl.storage import exclusive, hold

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
    listing = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--no-renames",
        "--untracked-files=all",
        "--ignore-submodules=all",
    ).stdout
    return {entry[3:] for entry in listing.split("\0") if len(entry) > 3}


def _commit(root, paths, change):
    """Commits `paths` as they are in the game on top of HEAD, or None when
    that changes nothing."""
    from util.version_update.git_workflow import _commit_tree, _temporary_index

    found = _git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "index",
        "HEAD",
        "HEAD^{tree}",
    ).stdout.splitlines()
    game_index, head, before = Path(found[0]), found[1], found[2]
    listed = "".join(path + "\0" for path in sorted(paths))
    index, environment = _temporary_index()
    try:
        _git(root, "read-tree", head, env=environment)
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
        tree = _git(root, "write-tree", env=environment).stdout.strip()
    finally:
        system.unlink(index, ignore_errors=True)
    if tree == before:
        return None
    text = message(change)
    commit = _commit_tree(Path(root), tree, text, (head,))
    _move(root, game_index, head, commit, text.splitlines()[0], listed)
    return commit


def _move(root, game_index, head, commit, subject, listed):
    """Moves the branch from `head` to `commit`, and the game's index takes
    the `listed` files as committed, as `git commit` leaves it. The new index
    is made under the index lock, taken first and waited for as `_run_git`
    waits: a lock a crashed Git left fails the write with nothing committed,
    and once the branch moved nothing fails it."""
    from util.version_update.git_workflow import _open_index_lock, _temporary_index

    lock = game_index.with_name(game_index.name + ".lock")
    staged, environment = _temporary_index()
    try:
        handle = _open_index_lock(lock)
        try:
            with handle:
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
                handle.write(Path(staged).read_bytes())
            # Moves the branch only if nothing else moved it since.
            _git(
                root, "update-ref", "-m", "checkpoint: " + subject, "HEAD", commit, head
            )
        except BaseException:
            system.unlink(lock, missing_ok=True, ignore_errors=True)
            raise
        try:
            system.replace(lock, game_index)
        except OSError:
            # The checkpoint stands; Git shows its files as staged until the
            # next checkpoint that takes them.
            system.unlink(lock, missing_ok=True, ignore_errors=True)
    finally:
        system.unlink(staged, ignore_errors=True)


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
    from util.len_patch_scope import dazedtl_files, grow_scope

    named = set(_relative(named))
    pending = _pending(root)
    # DazedTL's own files are never edits made outside it.
    own = (
        set()
        if change is OUTSIDE
        else dazedtl_files(Path(root)).keys() - (claimed or set())
    )
    joined = set()
    if outside := (named | own) - pending:
        tracked = set(_git(root, "ls-files", "-z").stdout.split("\0")) - {""}
        added, rules = grow_scope(
            Path(root),
            tracked,
            [p for p in outside if p not in tracked and (Path(root) / p).is_file()],
        )
        joined = {*added, *rules}
        if rules:
            # New rules can let in files they hid, such as the portable
            # settings an old rule order kept out.
            pending = _pending(root)
    chosen = joined | (pending & named if claimed is None else pending - claimed)
    return _commit(root, chosen, change) if chosen else None


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


def _index(root):
    """The game's index file."""
    git = Path(root) / ".git"
    if git.is_dir():
        return git / "index"
    found = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "index")
    return Path(found.stdout.strip())


def recovered_text(root, relative):
    """The text of the file at `relative` before and after the latest
    checkpoint that changed it, None where there was no file, when that
    checkpoint is a write committed after it ended without one and the file
    is as it left it; otherwise None."""
    from util.paths import game_git_set_up

    if not game_git_set_up(root):
        return None
    marker = f"%(trailers:key={RECOVERED_TRAILER},valueonly,separator=)"
    found = _git(root, "log", "-1", f"--format=%H %x00{marker}", "--", relative)
    commit, _, mark = found.stdout.strip().partition(" \0")
    if not commit or mark.strip() != "true":
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

    def __init__(self, root, paths: Iterable[str] | None, change: Change):
        from util.version_update.git_workflow import wait_for_index_lock

        self.root = Path(root)
        self.folder = _folder(root)
        self.paths = list(_relative(paths or ()))
        self.phase = _phase.get()
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
                    _save(self.root, OUTSIDE, (), claimed)
            except BaseException:
                self.write.close()
                raise

    def record(self, change, touched=()):
        """Commits the write's change once it succeeded, or adds it to the
        writes waiting for its phase; returns its commit, or None when it
        changed nothing or waits."""
        with exclusive(self.folder / "checkpoint.lock"):
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
