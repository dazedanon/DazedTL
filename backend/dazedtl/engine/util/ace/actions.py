"""The Ace preparation actions a workflow runs on a game folder."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from . import rgssad, rv2json

ACTIONS = ("ace_decrypt", "ace_extract", "ace_pack")
# Where Set up keeps an encrypted game's original archive. The game reads
# its extracted files only while no archive sits beside Game.exe.
ORIGINALS = Path(".dazedtl/ace")


def original_archive(root: Path) -> Path | None:
    """The archive an encrypted game came with, once Set up set it aside."""
    folder = Path(root) / ORIGINALS
    found = rgssad.archives(folder) if folder.is_dir() else []
    return found[0] if found else None


def run(root: Path, action: str, log: Callable[[str], None] = print) -> list[Path]:
    """Extracts the encrypted archive (ace_decrypt), converts Data to ace_json
    (ace_extract, extracting an encrypted game first and setting its archive
    aside) or packs ace_json back into Data (ace_pack), and returns the native
    data files packing wrote.

    Packing updates Data in place without RV2JSON's Data/backups copies: the
    workflow already keeps the original, and a copy inside Data would ship
    with the game.
    """
    root = Path(root)
    if action == "ace_decrypt":
        archives = rgssad.archives(root)
        if not archives:
            raise ValueError("No Game.rgss archive needs extraction.")
        log("Extracting " + archives[0].name)
        rgssad.extract(archives[0], root, log=log)
    elif action == "ace_extract":
        archives = rgssad.archives(root)
        if archives:
            # Files already extracted are kept; missing ones are added.
            log("Extracting " + archives[0].name)
            rgssad.extract(archives[0], root, log=log)
        log("Converting Data to ace_json")
        rv2json.create(root, log=log)
        if archives:
            target = root / ORIGINALS / archives[0].name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(archives[0], target)
            log(
                f"Moved {archives[0].name} to {ORIGINALS.as_posix()}, so the game reads its extracted files"
            )
    elif action == "ace_pack":
        log("Packing ace_json into Data")
        return rv2json.update(root, skip_backup=True, log=log)
    else:
        raise ValueError("Unknown Ace action: " + action)
    return []


def patch_archive(root: Path, target: Path, tracked: Iterable[str]) -> str | None:
    """Rebuilds an encrypted game's archive with its current files at
    ``target`` and returns the archive's name, or None for a game that came
    unencrypted. Tracked files in the archive's folders are added to it, since
    the game reads those folders only from the archive."""
    original = original_archive(root)
    if original is None:
        return None
    _header, rows = rgssad.table(original)
    folders = {
        raw.decode("utf-8", "replace").split("\\")[0].casefold() for raw, _ in rows
    }
    extra = [
        name.replace("/", "\\")
        for name in sorted(tracked)
        if "/" in name and name.split("/")[0].casefold() in folders
    ]
    rgssad.rebuild(original, target, Path(root), extra=extra)
    return original.name
