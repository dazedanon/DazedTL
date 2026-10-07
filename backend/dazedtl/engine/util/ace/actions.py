"""The Ace preparation actions a workflow runs on a game folder."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import rgssad, rv2json

ACTIONS = ("ace_decrypt", "ace_extract", "ace_pack")


def _has_native_data(root: Path) -> bool:
    try:
        folder = rv2json.data_dir(root)
    except rv2json.ConversionError:
        return False
    return any(path.suffix.lower() == ".rvdata2" for path in folder.iterdir())


def run(root: Path, action: str, log: Callable[[str], None] = print) -> list[Path]:
    """Extracts the encrypted archive (ace_decrypt), converts Data to ace_json
    (ace_extract, extracting an encrypted game first) or packs ace_json back
    into Data (ace_pack), and returns the native data files packing wrote.

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
        # An encrypted game is extracted first, so one action prepares it.
        archives = rgssad.archives(root)
        if archives and not _has_native_data(root):
            log("Extracting " + archives[0].name)
            rgssad.extract(archives[0], root, log=log)
        log("Converting Data to ace_json")
        rv2json.create(root, log=log)
    elif action == "ace_pack":
        log("Packing ace_json into Data")
        return rv2json.update(root, skip_backup=True, log=log)
    else:
        raise ValueError("Unknown Ace action: " + action)
    return []
