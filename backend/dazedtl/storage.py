"""Atomic application state in an explicitly supplied user workspace."""

import json
import os
from pathlib import Path
import tempfile
from copy import deepcopy
import hashlib


class WorkspaceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def write_json(path, value):
    write_bytes(
        path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".saving-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


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


class WorkspaceLock:
    def __init__(self, workspace):
        path = Path(workspace) / "workspace.lock"
        self.handle = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if not path.stat().st_size:
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise WorkspaceError(
                "workspace_locked",
                "This workspace is already open in another application instance.",
            ) from None

    def close(self):
        self.handle.close()
