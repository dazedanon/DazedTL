"""RPG Maker helpers shared by manual runs: imported guidance."""

from __future__ import annotations

from pathlib import Path


def import_context(source: Path, destination: Path):
    """Copy portable guidance without invoking migration helpers on the game."""
    metadata = source / ".dazedtl"
    if metadata.is_symlink():
        raise ValueError("Project guidance cannot be imported through a symbolic link.")
    destination.mkdir(parents=True, exist_ok=True)
    candidates = [metadata / "glossary.txt", metadata / "settings.json"]
    if (metadata / "skills").is_symlink():
        raise ValueError("Project skills cannot be imported through a symbolic link.")
    candidates.extend((metadata / "skills").glob("*.md"))
    for path in candidates:
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("A project guidance file is not a regular file below 1 MB.")
        target = destination / path.relative_to(metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())

