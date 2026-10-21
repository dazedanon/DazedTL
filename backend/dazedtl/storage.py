"""Atomic application state in an explicitly supplied user workspace."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

# The writers and folders moved to the platform layer; these names stay for
# their many callers.
from .system import new_folder, staging_folder, write_bytes, write_json

__all__ = [
    "WorkspaceError",
    "exclusive",
    "hold",
    "new_folder",
    "read_versioned_json",
    "staging_folder",
    "write_bytes",
    "write_json",
]


class WorkspaceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def read_versioned_json(path, default, upgrades, validate):
    """Upgrade in memory, retain the original bytes, then atomically replace.

    Each upgrade keyed by N accepts version N and returns a new document;
    this function advances its version to N+1.
    The caller must hold the workspace lock.
    """
    path = Path(path)
    if not path.exists():
        return deepcopy(default)
    original = path.read_bytes()
    try:
        value = json.loads(original)
    except (ValueError, UnicodeError) as exc:
        raise WorkspaceError(
            "workspace_invalid",
            "Saved workspace data is invalid. The file was left unchanged.",
        ) from exc
    version = value.get("version") if isinstance(value, dict) else None
    target = default["version"]
    if type(version) is not int or version < 1:
        raise WorkspaceError(
            "workspace_invalid",
            "Saved workspace data has an invalid version. The file was left unchanged.",
        )
    if version > target:
        raise WorkspaceError(
            "workspace_newer", "This workspace requires a newer application version."
        )
    if version == target:
        validate(value)
        return value
    if any(step not in upgrades for step in range(version, target)):
        raise WorkspaceError(
            "workspace_upgrade",
            "This app cannot upgrade the saved data format. The file was left unchanged.",
        )

    try:
        migrated = deepcopy(value)
        for step in range(version, target):
            migrated = upgrades[step](migrated)
            if not isinstance(migrated, dict):
                raise TypeError("An upgrade must return a document.")
            migrated["version"] = step + 1
        validate(migrated)
    except Exception as exc:
        raise WorkspaceError(
            "workspace_upgrade",
            "The workspace upgrade could not finish. The original file was left unchanged.",
        ) from exc

    backup = (
        path.parent
        / "backups"
        / f"{path.stem}.v{version}.{hashlib.sha256(original).hexdigest()[:16]}.json"
    )
    try:
        if backup.parent.is_symlink():
            raise OSError("The backup directory must belong to the workspace.")
        if backup.exists():
            if backup.is_symlink() or backup.read_bytes() != original:
                raise OSError("The existing backup does not match the source.")
        else:
            write_bytes(backup, original)
        if path.read_bytes() != original:
            raise OSError("The source changed during the upgrade.")
        write_json(path, migrated)
    except OSError as exc:
        raise WorkspaceError(
            "workspace_backup",
            "The workspace upgrade could not be saved safely. The original file was left unchanged.",
        ) from exc
    return migrated


def _try_lock(handle, path):
    """Takes an exclusive lock on an open file without waiting; False while
    another thread or process holds it. Closing the handle releases it."""
    try:
        if os.name == "nt":
            import msvcrt

            if not path.stat().st_size:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def hold(path):
    """An open handle holding an exclusive lock on path until it is closed,
    or None while another thread or process holds it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if _try_lock(handle, path):
        return handle
    handle.close()
    return None


class WorkspaceLock:
    def __init__(self, workspace):
        handle = hold(Path(workspace) / "workspace.lock")
        if handle is None:
            raise WorkspaceError(
                "workspace_locked",
                "This workspace is already open in another application instance.",
            )
        self.handle = handle

    def close(self):
        self.handle.close()


@contextmanager
def exclusive(path):
    """Holds an exclusive lock on path, waiting while another thread or
    process holds it."""
    while (handle := hold(path)) is None:
        time.sleep(0.05)
    with handle:
        yield
