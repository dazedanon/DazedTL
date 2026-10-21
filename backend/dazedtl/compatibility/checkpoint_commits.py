"""Checkpoints: one commit on a game's translation branch for each change
DazedTL makes to the game, so the game's Git history is the one record of
its translation, and Git does every save and restore.

The game-write gateway ([game_write](game_write.py)) opens a checkpoint for
the outermost write to a game whose Git is set up and records it once the
write succeeds, after packing; a failed or stopped write records nothing.
Opening one first records the changes made outside DazedTL since the last
checkpoint as their own (`outside_edits`), so a checkpoint holds only its
write's change and no flow waits for a clean worktree. Game updates keep
their own commits and record outside edits before they start.

A checkpoint commits every pending change Git sees in the patch, which is
the files the translation branch tracks or its .gitignore allows, and lets
the files its write names that the patch lacks into it (`grow_scope`). A
file outside the patch is the original game's, which the `original` branch
holds.

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
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dazedtl import system
from dazedtl.storage import exclusive, hold

ACTION_TRAILER = "DazedTL-Action"
STAGE_TRAILER = "DazedTL-Stage"
# The action of a checkpoint holding changes made outside DazedTL.
OUTSIDE_EDITS = "outside_edits"
# A subject Git's one-line views show whole.
SUBJECT_LIMIT = 100


@dataclass(frozen=True)
class Change:
    """What one checkpoint records: a plain summary, the workflow stage it
    belongs to, and the action that made it."""

    summary: str
    stage: str | None = None
    action: str | None = None


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
    or by `label` and `stage` for an operation the registry doesn't hold."""
    from dazedtl.actions import ACTIONS

    row = ACTIONS.get(name)
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
    return subject + ("\n\n" + "\n".join(trailers) if trailers else "")


def _folder(root):
    from util.version_update.git_workflow import _git_common_dir

    git = Path(root) / ".git"
    return (git if git.is_dir() else _git_common_dir(Path(root))) / (
        "dazedtl/checkpoints"
    )


class _Write:
    """A write in progress, registered with the files it said it would change;
    its lock, held while it runs, tells a live write from one whose process
    ended."""

    def __init__(self, folder, paths):
        self.folder = folder
        self.name = uuid.uuid4().hex
        self.handle = hold(folder / (self.name + ".lock"))
        system.write_json(
            folder / (self.name + ".json"),
            {"paths": sorted(paths) if paths else None},
        )

    def close(self):
        if self.handle is not None:
            self.handle.close()
        _forget(self.folder, self.name)


def _forget(folder, name):
    for suffix in (".json", ".lock"):
        system.unlink(folder / (name + suffix), missing_ok=True, ignore_errors=True)


def _others(folder, own=None):
    """The files other writes in progress said they would change, or None
    while one of them said nothing."""
    claimed = set()
    for record in sorted(folder.glob("*.json")):
        name = record.stem
        if own is not None and name == own.name:
            continue
        handle = hold(folder / (name + ".lock"))
        if handle is not None:
            # Its process ended without closing it.
            handle.close()
            _forget(folder, name)
            continue
        try:
            paths = json.loads(record.read_text(encoding="utf-8"))["paths"]
        except OSError, ValueError, KeyError, TypeError:
            paths = None
        if not isinstance(paths, list):
            return None
        claimed.update(paths)
    return claimed


def _relative(paths):
    for value in paths:
        path = PurePosixPath(str(value).replace("\\", "/"))
        if not path.is_absolute() and ".." not in path.parts and path.parts:
            yield path.as_posix()


def _git(root, *args, **options):
    from util.version_update.git_workflow import _run_git

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

    head, before = _git(root, "rev-parse", "HEAD", "HEAD^{tree}").stdout.split()
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
    # Moves the branch only if nothing else moved it since.
    _git(
        root,
        "update-ref",
        "-m",
        "checkpoint: " + text.splitlines()[0],
        "HEAD",
        commit,
        head,
    )
    # The game's index takes what was committed, as `git commit` leaves it.
    _git(
        root,
        "reset",
        "-q",
        "--pathspec-from-file=-",
        "--pathspec-file-nul",
        env={"GIT_LITERAL_PATHSPECS": "1"},
        input_text=listed,
    )
    return commit


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
    system.write_json(
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
    the patch lacks let into it."""
    from util.len_patch_scope import grow_scope

    named = set(_relative(named))
    pending = _pending(root)
    joined = set()
    if outside := named - pending:
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
        _settle(root, folder)
        claimed = _others(folder)
        if claimed is not None:
            return _save(root, OUTSIDE, (), claimed)
    return None


class Checkpoint:
    """The checkpoint of one write in progress, or, inside `in_phase`, its
    place among the writes waiting for their phase's."""

    def __init__(self, root, paths: Iterable[str] | None):
        self.root = Path(root)
        self.folder = _folder(root)
        self.paths = list(_relative(paths or ()))
        self.phase = _phase.get()
        with exclusive(self.folder / "checkpoint.lock"):
            claimed = _others(self.folder)
            self.write = _Write(self.folder, self.paths)
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
        writes waiting for its phase."""
        with exclusive(self.folder / "checkpoint.lock"):
            if self.phase is not None:
                return _wait(
                    self.root, self.folder, self.phase, [*self.paths, *touched]
                )
            return _save(
                self.root,
                change,
                [*self.paths, *touched],
                _others(self.folder, self.write),
            )

    def close(self):
        self.write.close()
