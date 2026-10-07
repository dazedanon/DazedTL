"""Package destinations and publication checks shared by Guided release workers."""

import hashlib
import json
import os
import re
import sqlite3
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .files import evidence, project_path, read_json

_PRIVATE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".dazedtl",
    ".agents",
    ".codex",
    ".claude",
    ".cursor",
    ".aws",
    ".ssh",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "save",
    "saves",
    "savedata",
    "save_data",
    "log",
    "logs",
    "cache",
    "caches",
}
_WORK_DIRS = {"ace_json", "wolf_json", "translated", "files", "skills"}
_PRIVATE_FILES = {
    ".api_key",
    "api_keys.json",
    "credentials.json",
    ".netrc",
    ".npmrc",
    ".ds_store",
    "desktop.ini",
    "thumbs.db",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".pre-commit-config.yaml",
    "previous_patch_sha.txt",
    "patch2.ps1",
    "patch2.sh",
}
_WORK_FILES = {
    "agents.md",
    "claude.md",
    "todo.md",
    "requirements.txt",
    "translation_quirks.txt",
    "glossary.txt",
    "vocab.txt",
}
_TEMP_SUFFIXES = (
    ".log",
    ".tmp",
    ".temp",
    ".bak",
    ".backup",
    ".orig",
    ".rpgsave",
    ".sav",
    ".swp",
    ".swo",
    "~",
)
_UPDATER_CONFIG = "gameupdate/patch-config.txt"
_UPDATER_STATE = "gameupdate/previous_patch_sha.txt"


def exclusion(relative, *, directory=False):
    parts = Path(relative).parts
    lowered = [part.casefold() for part in parts]
    if any(part in _PRIVATE_DIRS for part in lowered):
        return "Private configuration, local state or tool cache"
    name = lowered[-1]
    if (
        name.startswith(".env")
        or name in _PRIVATE_FILES
        or re.search(r"(?:_keys?\.txt|\.pem|\.p12|\.pfx)$", name)
    ):
        return "Private or tool-generated file"
    if name.endswith(_TEMP_SUFFIXES):
        return "Save, log, backup or temporary file"
    if len(parts) == 1 and (
        directory and name in _WORK_DIRS or not directory and name in _WORK_FILES
    ):
        return "Translator workspace or guidance"
    return None


def inventory(source, updater_stamp=None):
    """The same inventory drives inspection, writing and freshness verification."""
    root = Path(source)
    files, omitted = {}, []
    for current, directories, names in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=lambda error: (_ for _ in ()).throw(error),
    ):
        base = Path(current)
        kept = []
        for name in sorted(directories):
            path = base / name
            relative = path.relative_to(root).as_posix()
            reason = (
                "Symbolic link"
                if (path.is_symlink() or getattr(path, "is_junction", lambda: False)())
                else exclusion(relative, directory=True)
            )
            if reason:
                omitted.append({"path": relative + "/", "reason": reason})
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            reason = (
                "Symbolic link"
                if (path.is_symlink() or getattr(path, "is_junction", lambda: False)())
                else exclusion(relative)
            )
            if relative.casefold() == _UPDATER_CONFIG and not updater_stamp:
                reason = (
                    "GameUpdate disabled in this local ZIP: no verified public version"
                )
            if reason:
                omitted.append({"path": relative, "reason": reason})
                continue
            stat = project_path(root, relative).stat()
            files[relative] = [
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ]
    return {"files": files, "exclusions": omitted, "updater_stamp": updater_stamp}


def write_archive(source, target, scope, log, *, prefix=True):
    if inventory(source, scope["updater_stamp"]) != scope:
        raise ValueError("The archive contents changed. Inspect and build again.")
    if not scope["files"]:
        raise ValueError("No runtime files are available to package.")
    stopped = getattr(log, "stopped", lambda: False)
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for index, relative in enumerate(sorted(scope["files"]), 1):
            if stopped():
                raise InterruptedError(
                    "Package creation stopped. The previous ZIP is unchanged."
                )
            log(f"{index}/{len(scope['files'])} · {relative}")
            name = (Path(source).name + "/" if prefix else "") + relative
            archive.write(project_path(source, relative), name)
        if scope["updater_stamp"]:
            archive.writestr(
                (Path(source).name + "/" if prefix else "") + _UPDATER_STATE,
                scope["updater_stamp"] + "\n",
            )
    if inventory(source, scope["updater_stamp"]) != scope:
        raise ValueError(
            "The game changed during packaging. Its partial archive was discarded."
        )


def runtime_asset(source, relative):
    """Explicit additions are player images/fonts, never arbitrary private files."""
    path = project_path(source, relative)
    lowered = relative.casefold().split("/")
    area = lowered[1:] if lowered[0] == "www" else lowered
    extensions = {
        "img": {".png", ".jpg", ".jpeg", ".webp", ".rpgmvp", ".png_", ".bmp"},
        "fonts": {".ttf", ".otf", ".woff", ".woff2"},
    }
    if (
        exclusion(relative)
        or len(area) < 2
        or area[0] not in extensions
        or path.suffix.casefold() not in extensions[area[0]]
    ):
        raise ValueError(
            "Add exact player image or font paths under img/ or fonts/ (including www/ layouts)."
        )
    return relative


def applied_assets(source):
    root = Path(source)
    location = root / ".dazedtl/image_manager/guided/inventory.sqlite3"
    if not location.is_file():
        return []
    index = project_path(root, location.relative_to(root).as_posix())
    paths = []
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as db:
        for (raw,) in db.execute("SELECT data FROM assets"):
            row = json.loads(raw)
            applied = row.get("applied") or {}
            if applied.get("runtimeHash"):
                relative = runtime_asset(root, row["runtime"])
                if evidence(root, [relative])[relative] != applied["runtimeHash"]:
                    raise ValueError(
                        "An applied image changed. Review or restore it in Images before packaging: "
                        + relative
                    )
                paths.append(relative)
    return sorted(set(paths))


def packing_inputs(native):
    root, data = Path(native["source"]), Path(native["data"])
    paths = sorted(path.relative_to(root).as_posix() for path in data.glob("*.json"))
    if not paths:
        raise ValueError("Ace JSON exports are missing. Extract them before packing.")
    return evidence(root, paths)


def unpacked(inputs, outputs):
    """JSON exports without a packed native file of the same name; the game
    and the converter match data file names without regard to case."""
    packed = {PurePosixPath(name).stem.casefold() for name in outputs}
    return [
        name for name in inputs if PurePosixPath(name).stem.casefold() not in packed
    ]


def packing_state(native, folder):
    if native["engine"] != "ACE":
        return {"required": False, "current": True, "message": ""}
    try:
        receipt = read_json(Path(folder) / "ace-packing.json")
        inputs = packing_inputs(native)
        current = (
            receipt.get("source") == native["source"]
            and not unpacked(inputs, receipt["outputs"])
            and receipt.get("inputs") == inputs
            and receipt.get("outputs")
            == evidence(native["source"], list(receipt["outputs"]))
        )
    except OSError, ValueError, KeyError, TypeError:
        current = False
    return {
        "required": True,
        "current": current,
        "message": "Native data matches the saved packing receipt."
        if current
        else "Pack the current Ace JSON before building. No matching native packing evidence is saved.",
    }


def git_identity(status):
    keys = ("original_commit", "translation_commit")
    if any(not isinstance(status.get(key), str) or not status[key] for key in keys):
        raise ValueError(
            "The original and translation commits are unavailable. Check version tracking before packaging."
        )
    return {key: status[key] for key in keys}


def destination(source, workspace, engine_source, value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 10000
        or "\0" in value
    ):
        raise ValueError("Choose a release ZIP destination.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Choose an absolute release destination.")
    if path.suffix.lower() != ".zip":
        raise ValueError("Use a .zip archive name.")
    if path.is_symlink():
        raise ValueError("The release destination cannot be a symbolic link.")
    path = path.resolve()
    if any(
        path.is_relative_to(Path(root).resolve())
        for root in (
            source,
            workspace,
            engine_source,
            Path(__file__).resolve().parents[3],
        )
    ):
        raise ValueError(
            "Save the release outside the game, app workspace, and engine source."
        )
    if path.exists() and not path.is_file():
        raise ValueError("Choose an archive file, not an existing directory.")
    return path


def output_hash(path):
    path = Path(path)
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError("The release destination is not a regular file.")
    if not path.exists():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stamp(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("The saved release archive is unavailable.")
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def available(value):
    try:
        return stamp(value["path"]) == value["stamp"]
    except OSError, ValueError, KeyError:
        return False


def input_stamps(source, paths):
    """Size and modification time of each runtime file an archive is built from.

    Device, inode and change time are left out: metadata updates such as a
    permission change alter them without changing the content.
    """
    root = Path(source)
    stamps = {}
    for path in paths:
        stat = project_path(root, path).stat()
        stamps[path] = [stat.st_size, stat.st_mtime_ns]
    return stamps


def current(value, source):
    """Whether a saved archive still matches the game's runtime files.

    None means the archive predates recorded inputs, so it cannot be compared.
    Images applied after the build also make it outdated.
    """
    if not available(value):
        return False
    inputs = value.get("inputs")
    if not isinstance(inputs, dict):
        return None
    try:
        return input_stamps(source, inputs) == inputs and set(
            applied_assets(source)
        ) <= set(inputs)
    except OSError, ValueError:
        return False


def publish(staged, output, expected, *, stopped=lambda: False):
    """Keep the previous ZIP until a complete archive is ready to replace it."""
    staged, output = Path(staged), Path(output)
    with zipfile.ZipFile(staged) as archive:
        if not archive.infolist() or archive.testzip() is not None:
            raise ValueError("The release ZIP could not be verified.")
    if stopped():
        raise InterruptedError(
            "Package creation stopped. The previous release is unchanged."
        )
    if output_hash(output) != expected:
        raise ValueError(
            "The destination changed while packaging. Choose the output again."
        )
    os.replace(staged, output)
    identity = stamp(output)
    return {
        "path": str(output),
        "size": identity[2],
        "stamp": identity,
        "saved": datetime.now(UTC).isoformat(),
    }
