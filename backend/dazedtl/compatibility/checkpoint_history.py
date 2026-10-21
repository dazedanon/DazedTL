"""A game's checkpoints as the Checkpoints tab lists them, and what can be
done with one: go back to it, undo it, or save a copy of the game as of it.

The checkpoints are the translation branch's first-parent commits
([checkpoint_commits](checkpoint_commits.py)), read with the files each
changed in one `git log`. A commit whose `DazedTL-Version` trailer names a
version the older commits did not starts that game version: the setup's
import or a game update. Its other bookkeeping commits, which carry the same
version, and commits that change nothing are not listed.

What a file is at a checkpoint (`_Game.wanted`): its content in the
checkpoint's tree. A file the patch did not hold then is the original game's,
so it takes the `original` branch's bytes for that version. A file neither
holds did not exist then and goes, unless the original branch holds only the
patch too, when its earlier bytes are unknown and it stays as it is.

Going back and undoing write through the game-write gateway, which first
records the edits made outside DazedTL as their own checkpoint and then makes
the change one more checkpoint, so either can be undone in turn; VX Ace's
`ace_json` is packed into Data there. Both stay within the current game
version: going back across a game update would mix two versions' files, so
an earlier version's checkpoint is only saved as a copy.

A checkpoint undoes on its own once every file it changed is still as it
left it (`blocker`); otherwise the newest later checkpoint that changed one
of them names what to undo first. A checkpoint that undid another put the
file back, so undoing in turn never loops.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dazedtl import system

from .checkpoint_commits import (
    ACTION_TRAILER,
    OUTSIDE,
    OUTSIDE_EDITS,
    STAGE_TRAILER,
    WAITING,
    Change,
    _folder,
    _git,
    _pending,
    running,
)

VERSION_TRAILER = "DazedTL-Version"
RELEASE_TRAILER = "DazedTL-Release"
ORIGINAL = "original"
BACK = "checkpoint_back"
UNDO = "checkpoint_undo"
COPY = "checkpoint_copy"
# The files a row names before "and N more".
NAMED = 3
# Blobs read from Git at once, which bounds the memory a copy of big images
# takes.
BLOB_CHUNK = 16
_LINK = "120000"
# The patch's scope only grows, so going back and undoing leave the rule
# files that set it as they are.
_RULES = frozenset({".gitignore", ".gitattributes"})


def _trailer(message, key):
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", message, re.MULTILINE)
    return match.group(1) if match else None


@dataclass
class Entry:
    """One first-parent commit and the files it changed: path to (old mode,
    new mode, old blob, new blob, status)."""

    commit: str
    time: str
    message: str
    changes: dict[str, tuple[str, str, str, str, str]] = field(default_factory=dict)
    # Filled in by `_annotate`, oldest first.
    version: str | None = None
    boundary: bool = False
    listed: bool = False

    @property
    def subject(self):
        return self.message.strip().splitlines()[0] if self.message.strip() else ""

    @property
    def action(self):
        return _trailer(self.message, ACTION_TRAILER)

    @property
    def stage(self):
        return _trailer(self.message, STAGE_TRAILER)

    @property
    def title(self):
        if self.boundary:
            if self.subject.startswith("patch:"):
                return f"Updated the game to {self.version}"
            return f"Set up the game at version {self.version}"
        stage, subject = self.stage, self.subject
        if stage and subject.startswith(stage + ": "):
            return subject[len(stage) + 2 :]
        return subject

    @property
    def group(self):
        """The stage the view groups it under."""
        if self.boundary:
            return "Game update" if self.subject.startswith("patch:") else "Set up"
        if self.stage:
            return self.stage
        if self.action == OUTSIDE_EDITS:
            return "Outside DazedTL"
        if self.action in {BACK, UNDO}:
            return "Checkpoints"
        return "Other changes"


def _log(root):
    """Every first-parent commit on the checked-out branch, newest first."""
    output = _git(
        root,
        "log",
        "--first-parent",
        "--root",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        "--diff-merges=first-parent",
        "--format=%x1e%H%x1f%cI%x1f%B%x1f",
    ).stdout
    entries = []
    for record in output.split("\x1e")[1:]:
        commit, time, message, rest = record.split("\x1f", 3)
        entry = Entry(commit, time, message)
        fields = rest.lstrip("\0\n").split("\0")
        for meta, path in zip(fields[::2], fields[1::2]):
            match meta.lstrip(":").split():
                case [old_mode, new_mode, old_blob, new_blob, status]:
                    entry.changes[path] = (
                        old_mode,
                        new_mode,
                        old_blob,
                        new_blob,
                        status,
                    )
        entries.append(entry)
    _annotate(entries)
    return entries


def _annotate(entries):
    version = None
    for entry in reversed(entries):
        tag = _trailer(entry.message, VERSION_TRAILER)
        entry.boundary = tag is not None and tag != version
        version = tag or version
        entry.version = version
        entry.listed = entry.boundary or (tag is None and bool(entry.changes))


def _current_span(entries):
    """The entries of the current game version, newest first."""
    for index, entry in enumerate(entries):
        if entry.boundary:
            return entries[: index + 1]
    return entries


def _blockers(entries):
    """For each entry of the current version, the newest later entry it must
    wait for and the files they share, or None; one pass over the changes."""
    newest = {}
    result = {}
    for index, entry in enumerate(entries):
        differing = {
            path
            for path, change in entry.changes.items()
            if path in newest and newest[path][1] != change[3]
        }
        if differing:
            later = min(newest[path][0] for path in differing)
            shared = sorted(differing & set(entries[later].changes))
            result[entry.commit] = (entries[later], shared)
        else:
            result[entry.commit] = None
        for path, change in entry.changes.items():
            newest.setdefault(path, (index, change[3]))
    return result


def _blocker_view(found):
    if found is None:
        return None
    later, files = found
    return {"commit": later.commit, "title": later.title, "files": files}


def _outside_view(entry, outside):
    """The edits made outside DazedTL to a checkpoint's files, which become
    the later checkpoint its undo waits for once DazedTL next changes the
    game; no commit names them yet."""
    files = sorted(set(entry.changes) & set(outside))
    if not files:
        return None
    return {"commit": "", "title": OUTSIDE.summary, "files": files}


def blocker(root, commit):
    """The later checkpoint to undo before this one, as {commit, title,
    files}, or None when it undoes on its own; the one rule the Checkpoints
    tab, its undo and History's restores read."""
    entries = _log(root)
    index = _index(entries, commit)
    return _blocker_view(_blockers(entries[: index + 1])[commit])


def _index(entries, commit):
    for index, entry in enumerate(entries):
        if entry.commit == commit:
            return index
    raise ValueError("That checkpoint is no longer in the game's history.")


def _waiting(root):
    """The files an assistant's phase wrote that wait for its checkpoint."""
    try:
        record = (_folder(root) / WAITING).read_text(encoding="utf-8")
        return set(json.loads(record)["paths"])
    except OSError, ValueError, KeyError, TypeError:
        return set()


def edited_outside(root):
    """The files in the patch edited outside DazedTL since the last
    checkpoint, which become their own before DazedTL's next change."""
    return sorted(_pending(root) - _waiting(root))


def timeline(root):
    """The Checkpoints tab's view: the game's versions, newest first, each
    with its listed checkpoints, newest first, and the edits made outside
    DazedTL waiting for a checkpoint."""
    root = Path(root)
    entries = _log(root)
    current = _current_span(entries)
    blockers = _blockers(current)
    outside = edited_outside(root)
    versions = []
    head = next((entry for entry in entries if entry.listed), None)
    for entry in entries:
        if not entry.listed:
            continue
        if not versions or versions[-1]["version"] != entry.version:
            versions.append(
                {
                    "version": entry.version or "",
                    "current": not versions,
                    "checkpoints": [],
                }
            )
        names = sorted(entry.changes)
        in_current = entry.commit in blockers
        versions[-1]["checkpoints"].append(
            {
                "commit": entry.commit,
                "title": entry.title,
                "group": entry.group,
                "time": entry.time,
                "files": len(names),
                "names": names[:NAMED],
                "kind": (
                    ("update" if entry.subject.startswith("patch:") else "setup")
                    if entry.boundary
                    else "change"
                ),
                "release": _trailer(entry.message, RELEASE_TRAILER) or "",
                "current": entry is head,
                # Go back and undo stay within the current game version, and
                # a version's first checkpoint only goes back.
                "restorable": in_current,
                "blocker": (
                    _blocker_view(blockers[entry.commit])
                    or _outside_view(entry, outside)
                    if in_current and not entry.boundary
                    else None
                ),
            }
        )
    store = root / ".dazedtl" / "backups"
    return {
        "version": versions[0]["version"] if versions else "",
        "outside": outside,
        "versions": versions,
        "backups": str(store) if store.is_dir() and any(store.iterdir()) else None,
    }


def changes(root, commit):
    """What one checkpoint changed, as a game update's comparison shows a
    release's: each file and, for game text, its lines before and after."""
    from util.version_update.text_changes import checkpoint_text

    entries = _log(root)
    entry = entries[_index(entries, commit)]
    labels = {"A": "Added", "D": "Removed", "M": "Changed", "T": "Changed"}
    text = checkpoint_text(
        Path(root),
        {path: (change[2], change[3]) for path, change in entry.changes.items()},
    )
    return {
        "title": entry.title,
        "group": entry.group,
        "time": entry.time,
        "file_changes": [
            {
                "path": path,
                "change": labels.get(change[4][:1], "Changed"),
                # Its lines show beside it from `text`.
                "result": "",
            }
            for path, change in sorted(entry.changes.items())
        ],
        "text": text,
    }


class _Game:
    """The files of a game as of one of its checkpoints, against the game
    as it is now."""

    def __init__(self, root, target):
        self.root = root
        tip = _git(root, "rev-parse", "--verify", "-q", ORIGINAL, check=False)
        self.original_tip = tip.stdout.strip() if tip.returncode == 0 else ""
        self.original = self._original(target.version)
        # The original branch made from the patch alone, as an Assistant-led
        # baseline is, can't say what a file outside it was.
        from util.paths import LEN_PATCH_GITIGNORE_BEGIN

        rules = (
            _git(
                root, "cat-file", "-p", self.original_tip + ":.gitignore", check=False
            ).stdout
            if self.original_tip
            else ""
        )
        self.complete = (
            bool(self.original_tip) and LEN_PATCH_GITIGNORE_BEGIN not in rules
        )

    def _original(self, version):
        """The original game's files at `version`: the branch's tip while it
        is the newest version, else its newest commit recording it."""
        from util.version_update.git_workflow import _tree_files

        if not self.original_tip:
            return {}
        commit = self.original_tip
        log = _git(
            self.root, "log", "--first-parent", "--format=%H%x1f%B%x1e", ORIGINAL
        ).stdout
        newest = None
        for record in log.split("\x1e"):
            if "\x1f" not in record:
                continue
            identity, message = record.strip("\n").split("\x1f", 1)
            recorded = _trailer(message, VERSION_TRAILER)
            if recorded is None:
                continue
            newest = newest or recorded
            if recorded == version:
                # Commits after the version's own, such as a completed
                # original, belong to it while no newer version followed.
                commit = self.original_tip if recorded == newest else identity
                break
        return _tree_files(self.root, commit, "")

    def wanted(self, path, tree):
        """The (mode, blob) the file has as of the target, None when it
        didn't exist then, or "keep" when that can't be known."""
        if path in tree:
            return tree[path]
        if path in self.original:
            return self.original[path]
        return None if self.complete else "keep"

    def tree(self, commit):
        from util.version_update.git_workflow import _tree_files

        return _tree_files(self.root, commit, "")


def _diff(root, older, newer):
    """The files that differ between two commits' trees."""
    output = _git(
        root, "diff-tree", "-r", "-z", "--no-renames", "--name-only", older, newer
    ).stdout
    return {path for path in output.split("\0") if path}


def _blob_contents(root, blobs):
    """Each blob's bytes, read in chunks of one Git process each."""
    from util.version_update.text_changes import _blobs

    unique = list(dict.fromkeys(blobs))
    for start in range(0, len(unique), BLOB_CHUNK):
        chunk = unique[start : start + BLOB_CHUNK]
        read = _blobs(Path(root), chunk)
        for blob in chunk:
            if blob not in read:
                raise ValueError("Git could not read a file of that checkpoint.")
            yield blob, read[blob]


def _apply(game, root, plan, stopped):
    """Writes `plan`, path to (mode, blob) or None to remove, through the
    gateway's write."""
    removals = [path for path, value in plan.items() if value is None]
    writes = {path: value for path, value in plan.items() if value is not None}
    if any(mode == _LINK for mode, _blob in writes.values()):
        raise ValueError("That checkpoint holds a symbolic link DazedTL can't restore.")
    by_blob = {}
    for path, (mode, blob) in writes.items():
        by_blob.setdefault(blob, []).append((path, mode))
    for blob, raw in _blob_contents(root, by_blob):
        if stopped():
            raise InterruptedError("Stopped before every file was restored.")
        for path, mode in by_blob[blob]:
            game.put(path, raw, 0o755 if mode == "100755" else None)
    for path in removals:
        game.put(path, None)
    return len(plan)


def _quoted(title):
    """A title in quotes, single ones inside a title already quoting another."""
    return f"‘{title}’" if "“" in title else f"“{title}”"


def _restorable(entries, commit):
    index = _index(entries, commit)
    if index >= len(_current_span(entries)):
        raise ValueError(
            "That checkpoint is from an earlier game version. Save a copy to use it."
        )
    return index


def go_back(root, commit, stopped=lambda: False, log=lambda _line: None):
    """Puts the game's files back as they were at `commit`, as one checkpoint."""
    from .game_write import write_game

    root = Path(root).resolve()
    entries = _log(root)
    target = entries[_restorable(entries, commit)]
    change = Change(f"Went back to {_quoted(target.title)}", None, BACK)
    with running(change), write_game(root, log=log) as game:
        # The gateway recorded the edits made outside DazedTL first.
        entries = _log(root)
        target = entries[_restorable(entries, commit)]
        state = _Game(root, target)
        tree = state.tree(commit)
        plan = {}
        for path in _diff(root, commit, "HEAD") - _RULES:
            wanted = state.wanted(path, tree)
            if wanted != "keep":
                plan[path] = wanted
        written = _apply(game, root, plan, stopped)
    return {"files": written, "commit": _head(root)}


def undo(root, commit, stopped=lambda: False, log=lambda _line: None):
    """Takes out one checkpoint's change, as one checkpoint of its own."""
    from .game_write import write_game

    root = Path(root).resolve()
    entries = _log(root)
    index = _restorable(entries, commit)
    target = entries[index]
    if target.boundary:
        raise ValueError(
            "A game version's first checkpoint can't be undone; go back to it instead."
        )
    change = Change(f"Undid {_quoted(target.title)}", None, UNDO)
    with running(change), write_game(root, log=log) as game:
        entries = _log(root)
        index = _restorable(entries, commit)
        target = entries[index]
        found = _blockers(entries[: index + 1])[commit]
        if found is not None:
            later, files = found
            raise ValueError(
                f"Undo the later {_quoted(later.title)} first; it also changed "
                f"{_names(files)}."
            )
        state = _Game(root, target)
        parent = entries[index + 1].commit if index + 1 < len(entries) else None
        before = state.tree(parent) if parent else {}
        plan = {}
        for path in set(target.changes) - _RULES:
            wanted = state.wanted(path, before)
            if wanted != "keep":
                plan[path] = wanted
        written = _apply(game, root, plan, stopped)
    return {"files": written, "commit": _head(root)}


def _names(files):
    shown = [Path(name).name for name in files[:NAMED]]
    more = len(files) - len(shown)
    if more:
        return ", ".join(shown) + f" and {more} more"
    return " and ".join(shown) if len(shown) == 2 else ", ".join(shown)


def _head(root):
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def copy_folder(root, parent, version, entry_time):
    """A new folder in `parent` named for the game, its version and the
    checkpoint's time, never one inside the game or holding it."""
    root = Path(root).resolve()
    parent = Path(parent).expanduser()
    if not parent.is_absolute() or not parent.is_dir():
        raise ValueError("Choose an existing folder for the copy.")
    parent = parent.resolve()
    if parent.is_relative_to(root):
        raise ValueError("Choose a folder outside the game for the copy.")
    moment = datetime.fromisoformat(entry_time).astimezone()
    label = f"{root.name} ({version + ', ' if version else ''}{moment:%Y-%m-%d %H.%M})"
    candidate, number = parent / label, 1
    while candidate.exists():
        number += 1
        candidate = parent / f"{label} {number}"
    return candidate


def save_copy(
    root, commit, parent, stopped=lambda: False, progress=lambda _message: None
):
    """Writes the game as of `commit`, the original game with the
    translation, into a new folder in `parent`; the game stays as it is."""
    root = Path(root).resolve()
    entries = _log(root)
    target = entries[_index(entries, commit)]
    folder = copy_folder(root, parent, target.version, target.time)
    state = _Game(root, target)
    tree = state.tree(commit)
    # Edits made outside DazedTL are not in any checkpoint yet.
    changed = _diff(root, commit, "HEAD") | _pending(root)
    # Files outside the patch that a later game update changed.
    if state.original_tip:
        newest = state._original(None)
        changed |= {
            path
            for path in set(state.original) | set(newest)
            if state.original.get(path) != newest.get(path) and path not in tree
        }
    plan = {}
    for path in changed | {p for p in tree if p.startswith(".dazedtl/")}:
        wanted = state.wanted(path, tree)
        if wanted != "keep":
            plan[path] = wanted
    folder.mkdir()
    try:
        count = 0
        for directory, folders, files in os.walk(root):
            here = Path(directory)
            if here == root:
                folders[:] = [
                    name for name in folders if name not in {".git", ".dazedtl"}
                ]
            relative = here.relative_to(root)
            for name in files:
                if stopped():
                    raise InterruptedError("Stopped before the copy was finished.")
                path = (relative / name).as_posix()
                source = here / name
                if path in plan or source.is_symlink():
                    continue
                target_path = folder / relative / name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_path)
                count += 1
                if count % 500 == 0:
                    progress(f"Copied {count:,} files · {path}")
        writes = {path: value for path, value in plan.items() if value is not None}
        by_blob = {}
        for path, (mode, blob) in writes.items():
            if mode != _LINK:
                by_blob.setdefault(blob, []).append((path, mode))
        for blob, raw in _blob_contents(root, by_blob):
            if stopped():
                raise InterruptedError("Stopped before the copy was finished.")
            for path, mode in by_blob[blob]:
                destination = folder / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                system.write_bytes(
                    destination, raw, 0o755 if mode == "100755" else 0o644
                )
                count += 1
    except BaseException:
        system.remove_tree(folder, ignore_errors=True)
        raise
    return {"folder": str(folder), "files": count}
