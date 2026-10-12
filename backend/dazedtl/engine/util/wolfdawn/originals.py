"""Pristine binary snapshots for idempotent WolfDawn inject."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from util import wolfdawn
from util.paths import staging_folder

ProgressFn = Callable[[int, int, str], None]


def find_data_archives(game_root: Path, data_dir: Path) -> list[Path]:
    """Return split or monolithic data archives usable as a pristine baseline."""
    archives: list[Path] = []
    seen: set[Path] = set()
    for base in (game_root, data_dir):
        for archive in wolfdawn.list_archives(base, backups=True):
            resolved = archive.resolve()
            if resolved not in seen:
                seen.add(resolved)
                archives.append(archive)

    def preferred(stem: str) -> Path | None:
        candidates = [a for a in archives if wolfdawn.archive_stem(a).casefold() == stem]
        if not candidates:
            return None
        backups = [a for a in candidates if a.suffix.casefold() == ".bak"]
        return (backups or candidates)[0]

    basic = preferred("basicdata")
    maps = preferred("mapdata")
    monolithic = preferred("data")
    # A complete split pair is more specific. If only half of the pair exists,
    # prefer monolithic Data.wolf so the snapshot is not silently incomplete.
    if basic is not None and maps is not None:
        return [basic, maps]
    if monolithic is not None:
        return [monolithic]
    return [archive for archive in (basic, maps) if archive is not None]


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def pristine_path_for(
    live_path: Path,
    data_dir: Path,
    originals_dir: Path,
) -> Path:
    """Return the mirrored pristine path for a live file or directory."""
    try:
        relative = live_path.relative_to(data_dir)
    except ValueError:
        relative = Path(live_path.name)
    return originals_dir / relative


def preferred_extract_path(
    live_path: Path,
    data_dir: Path,
    originals_dir: Path,
) -> Path:
    """Prefer a pristine source path while retaining loose-data compatibility."""
    pristine = pristine_path_for(live_path, data_dir, originals_dir)
    return pristine if pristine.exists() else live_path


def rebuild_originals_from_archives(
    game_root: Path,
    originals_dir: Path,
    *,
    force: bool = False,
    log_fn: Callable[[str], None] | None = None,
    progress_fn: ProgressFn | None = None,
) -> bool:
    """Unpack ``BasicData`` / ``MapData`` archives into *originals_dir*.

    When *force* is true, the entire *originals_dir* tree is removed first so
    stale flat snapshots from an old extract cannot survive beside rebuilt data.
    """
    emit = log_fn or (lambda _msg: None)
    data_dir = game_root / "Data"
    archives = find_data_archives(game_root, data_dir)
    if not archives:
        emit("  ⚠ no Data/BasicData/MapData archives found to rebuild originals")
        return False

    emit("Rebuilding pristine originals from the game's archives…")
    originals_dir.parent.mkdir(parents=True, exist_ok=True)
    with staging_folder(originals_dir.parent, ".wolf-originals-") as temp_root:
        unpacked = temp_root / "unpacked"
        inputs: list[str] = []
        for arc in archives:
            if arc.suffix.casefold() == ".bak":
                staged = temp_root / arc.with_suffix("").name
                _link_or_copy(arc, staged)
                # wolf unpack reads a Wolf Pro game's key beside the archive.
                key = wolfdawn.pro_key_file(arc.parent)
                if key is not None and not (temp_root / key.name).exists():
                    _link_or_copy(key, temp_root / key.name)
                inputs.append(str(staged))
            else:
                inputs.append(str(arc))
        res = wolfdawn.unpack_all(
            inputs,
            str(unpacked),
            log_fn=log_fn,
            progress_fn=progress_fn,
            progress_total=len(inputs),
        )
        if not res.ok:
            emit(f"  ⚠ could not rebuild originals (unpack exit {res.returncode})")
            return False

        # Split archives unpack as ``unpacked/BasicData`` + ``unpacked/MapData``.
        # A monolithic Data.wolf unpacks one level deeper as ``unpacked/Data``.
        source = unpacked / "Data"
        if not source.is_dir() or not any(
            (source / name).exists() for name in ("BasicData", "MapData")
        ):
            source = unpacked
        if not any((source / name).exists() for name in ("BasicData", "MapData")):
            emit("  ⚠ rebuilt archive did not contain BasicData or MapData")
            return False

        if force:
            assembled = temp_root / "assembled"
            shutil.copytree(source, assembled)
            previous = temp_root / "previous"
            if originals_dir.exists():
                originals_dir.rename(previous)
            try:
                assembled.rename(originals_dir)
            except Exception:
                if previous.exists() and not originals_dir.exists():
                    previous.rename(originals_dir)
                raise
        else:
            shutil.copytree(source, originals_dir, dirs_exist_ok=True)
    return True


def names_inject_would_apply(
    names_json: Path,
    data_dir: Path,
    *,
    allow_code_drift: bool = False,
) -> int | None:
    """Return how many name changes wolf would apply (dry run), or None if unknown."""
    res = wolfdawn.names_inject(
        str(names_json),
        str(data_dir),
        dry_run=True,
        allow_code_drift=allow_code_drift,
        log_fn=None,
    )
    applied, _drifted = wolfdawn.parse_names_inject_counts(res.stdout, res.stderr)
    return applied
