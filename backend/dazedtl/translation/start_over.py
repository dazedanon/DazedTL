"""Start over: the game back to its original, the assistant's work set aside.

An Assistant-led project changes the game folder in many places: preparation,
Git baselines, the canary and injected translations, and the assistant's work
records under .dazedtl/len-method. Starting over puts the game files back to
the original saved before setup and moves everything else aside under a dated
folder, so the next starting prompt begins again from preparation. Nothing is
deleted: backups of the game and project files come first, and files the
original lacks are moved, not removed. Save games, the project's options and
Image Manager work stay, and the glossary and notes stay unless the user lets
them go.
"""

import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dazedtl.foreign_work import ARCHIVE

from . import backups
from .files import project_path
from .project import WORK

# Save games outlive any translation attempt, wherever the engine keeps them.
SAVE_FOLDERS = {"save", "saves", "savedata"}
SAVE_FILE = re.compile(r"save\d*\.(rvdata2|rvdata|rxdata|lsd)", re.IGNORECASE)


def save_game(name):
    """Whether a game-relative path is a save game, which starting over keeps."""
    *folders, filename = name.split("/")
    return any(part.lower() in SAVE_FOLDERS for part in folders) or bool(
        SAVE_FILE.fullmatch(filename)
    )


def _archive(root):
    folder = project_path(root, ARCHIVE, exists=False)
    stamp = "assistant-led-" + datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    target, count = folder / stamp, 1
    while target.exists():
        count += 1
        target = folder / f"{stamp}-{count}"
    target.mkdir(parents=True)
    return target


def _move(path, target):
    """Moves a file or folder aside. Windows refuses while another program,
    such as the Git status check, holds a file inside, so it retries briefly."""
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(20):
        try:
            os.rename(path, target)
            return
        except PermissionError:
            if attempt == 19:
                raise ValueError(
                    f"{path.name} is in use. Close programs using the game folder, "
                    "then start over again; what moved so far is in the archive."
                ) from None
            time.sleep(0.25)


def _shown(path):
    """Git hides its folder on Windows; the archived copy shows in Explorer
    like the rest of the attempt."""
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        attributes = kernel.GetFileAttributesW(str(path))
        hidden = 0x2  # FILE_ATTRIBUTE_HIDDEN
        if attributes != -1 and attributes & hidden:
            kernel.SetFileAttributesW(str(path), attributes & ~hidden)


def run(
    source, state, documents, keep_context, *, stopped, progress
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Starts the project over; returns its new lifecycle and a summary."""
    root = Path(source).resolve(strict=True)
    store = backups.store_path(root)
    original = None
    if state.get("source_backup"):
        record = state["source_backup"]
        original = backups.lookup(root, Path(record["path"]).parent, record["id"])
        backups.verify(original, full=False, stopped=stopped)
    renewed: dict[str, Any] = {"version": 1}
    if original:
        progress("Backing up the game as it is now.")
        renewed["source_backup"] = state["source_backup"]
        renewed["game_backup"] = backups.snapshot(
            root,
            store,
            source_game=True,
            stopped=stopped,
            progress=lambda count, path: progress(
                f"Backed up {count:,} game files · {path}"
            ),
        )
    if (root / ".dazedtl").is_dir():
        progress("Backing up the project files.")
        renewed["workspace_backup"] = backups.snapshot(
            root / ".dazedtl", store, stopped=stopped
        )
    archive = _archive(root)
    relative = archive.relative_to(root).as_posix()
    kept = set()
    for document in documents.values():
        path = Path(document["path"])
        if not path.is_file():
            continue
        name = path.resolve().relative_to(root).as_posix()
        if keep_context:
            kept.add(name)
        else:
            _move(path, archive / "context" / name)
    result: dict[str, Any] = {"archive": relative, "restored": 0, "set_aside": 0}
    if original:
        progress("Putting back the original game files.")
        result |= backups.reset(
            original,
            Path(renewed["game_backup"]["path"]),
            root,
            archive / "game-files",
            keep=lambda name: save_game(name) or name in kept,
            stopped=stopped,
            progress=lambda count, path: progress(f"Put back {count:,} files · {path}"),
        )
    git = root / ".git"
    if git.exists() or git.is_symlink():
        progress("Setting the Git history aside.")
        _move(git, archive / "git")
        _shown(archive / "git")
    work = project_path(root, WORK, exists=False)
    if work.is_dir():
        progress("Setting the assistant's work aside.")
        for child in sorted(work.iterdir()):
            # The project's options belong to the user, not to one attempt.
            if child.name != "workflow.json":
                _move(child, archive / "len-method" / child.name)
    renewed["started_over"] = {"at": datetime.now(UTC).isoformat(), "archive": relative}
    return renewed, result
