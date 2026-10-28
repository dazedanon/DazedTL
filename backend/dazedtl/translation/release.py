"""Package destinations and publication checks shared by Guided release workers."""

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from stat import S_IFREG

from dazedtl import system
from dazedtl.actions import stopped_note
from dazedtl.freshness import Basis, Digests, compare

from .files import evidence, project_path, read_evidence, read_json

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
_ADDED = "Not part of the game or its translation"
_UPDATER_CONFIG = "gameupdate/patch-config.txt"
_UPDATER_STATE = "gameupdate/previous_patch_sha.txt"
UPDATER_OMITTED = "GameUpdate disabled in this local ZIP: no verified public version"
# Windows refuses these names, so extracting a ZIP that holds one fails there.
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|(?:com|lpt)[0-9¹²³])(?:\..*)?")
# Ace packing receipts from version 2 bind Game.ini, whose title packing
# writes, and from version 3 packing writes text variables translated as
# template literals as Ruby strings; earlier receipts need packing again.
PACKING_VERSION = 3


def _windows_unsafe(name):
    return (
        any(ord(char) < 32 or char in '<>:"\\|?*' for char in name)
        or name.endswith((" ", "."))
        or bool(_WINDOWS_DEVICE.fullmatch(name.casefold()))
    )


def exclusion(relative, *, directory=False):
    parts = Path(relative).parts
    lowered = [part.casefold() for part in parts]
    if any(_windows_unsafe(part) for part in parts):
        return "A name Windows can't use"
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
    if lowered[:2] == ["data", "backups"]:
        # Earlier Ace packing kept RV2JSON's copies of the original data here.
        return "Original data kept by Ace packing"
    if len(parts) == 1 and (
        directory and name in _WORK_DIRS or not directory and name in _WORK_FILES
    ):
        return "Translator workspace or guidance"
    return None


def _known_key(name):
    # A snapshot may spell a name in another case or Unicode form than the folder.
    return unicodedata.normalize("NFC", name).casefold()


def inventory(source, updater_stamp=None, known=None):
    """The same inventory drives inspection, writing and freshness verification.

    `known` names the files a clean ZIP may hold, the game's and its
    translation's. Anything else was added to the folder while working there,
    such as notes, downloads or a browser's cache, and stays out.
    """
    root = Path(source)
    files, omitted = {}, []
    if known is not None:
        known = sorted(known)
        keys = {_known_key(name) for name in known}
        folders = {
            parent.as_posix() for name in keys for parent in PurePosixPath(name).parents
        }
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
            if not reason and known is not None and _known_key(relative) not in folders:
                reason = _ADDED
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
                reason = UPDATER_OMITTED
            if not reason and known is not None and _known_key(relative) not in keys:
                reason = _ADDED
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
    return {
        "files": files,
        "exclusions": omitted,
        "updater_stamp": updater_stamp,
        "known": known,
    }


def public_version(source):
    """The one rule for GameUpdate's config in a release ZIP, a clean game
    ZIP or a patch ZIP, whichever workflow builds it: the config goes in only
    when the game's commit is the verified public version, the tip players
    update from, which the ZIP then stamps as the version they have. This is
    that commit, or None, and the ZIP leaves the config out, so a player's
    first update fetches the published patch."""
    from util.release_package import ReleasePackageError, _release_patch_sha

    try:
        return _release_patch_sha(Path(source))
    except ReleasePackageError:
        # Building a local ZIP never needs the version published.
        return None


def summary(files, exclusions, updater_stamp):
    """What a release ZIP's review says it holds, for either kind."""
    return {
        "included": len(files) + bool(updater_stamp),
        "excluded": len(exclusions),
        "exclusions": exclusions,
        "updater": "Verified public GameUpdate version included."
        if updater_stamp
        else "GameUpdate configuration is omitted until a matching public version is verified.",
        "generated": [_UPDATER_STATE] if updater_stamp else [],
    }


def patch_summary(files, omitted, updater_stamp, archive=None):
    """What a patch ZIP's review says it holds: its runtime `files`, the
    GameUpdate config it leaves out (`omitted`) and the encrypted game's
    `archive` it carries rebuilt, if any."""
    value = summary(
        files,
        [{"path": name, "reason": UPDATER_OMITTED} for name in omitted],
        updater_stamp,
    )
    if archive:
        value["updater"] += (
            f" This game came encrypted, so the patch carries {archive} rebuilt"
            " with the translation; GameUpdate cannot update it."
        )
        value["generated"].append(archive)
    return value


def player_permissions(info):
    """Gives an entry ordinary file permissions, whatever the game folder's
    are, such as the owner-only files a temporary-file write leaves. Only the
    central directory holds them, so this works after the entry is written."""
    executable = info.external_attr >> 16 & 0o111
    info.external_attr = (S_IFREG | (0o755 if executable else 0o644)) << 16 | (
        info.external_attr & 0xFFFF
    )


def game_folder(output, engine):
    """The folder a clean game ZIP holds the game in: the archive's own name,
    so players get the name the translator chose, not the source folder's.

    RGSS3's Game.exe finds its library through the ANSI code page, so on
    English Windows a VX Ace game won't start from a folder named in
    Japanese. Extracting the ZIP in Explorer makes a folder of the archive's
    name too, so an Ace archive's whole name must be ASCII.
    """
    name = Path(output).stem
    if _windows_unsafe(name):
        raise ValueError(
            "Windows can't use this archive name, and it becomes the game's folder in the ZIP."
        )
    if engine == "ACE" and not name.isascii():
        raise ValueError(
            "Use only English letters, numbers and symbols. This name becomes the game's folder, and a VX Ace game won't start on English Windows from a folder named in other characters."
        )
    return name


def destination_check(source, workspace, engine_source, output, kind, engine):
    """Whether a release ZIP may be written to `output`, without writing:
    the error and whether the archive name alone or the whole path is at
    fault, or empty ones."""
    try:
        path = destination(source, workspace, engine_source, output)
    except ValueError as exc:
        return {"error": str(exc), "field": "path"}
    if kind == "game":
        # The archive's name becomes the game's folder inside it.
        try:
            game_folder(path, engine)
        except ValueError as exc:
            return {"error": str(exc), "field": "name"}
    return {"error": "", "field": ""}


def archive_stem(name, engine):
    """What a game's release ZIPs are named before the translator names them,
    as in "<stem>-game.zip": the game folder's *name* wherever game_folder
    takes it, else its ASCII form, else a plain name, so a VX Ace game with
    a Japanese folder name still opens Release with a name it can build."""
    from util.ace.game_ini import ascii_title

    for stem in (name, ascii_title(name)):
        try:
            if stem:
                return game_folder(stem + ".zip", engine)
        except ValueError:
            pass
    return "translated"


def write_archive(source, target, scope, log, *, folder, stopped=None):
    if inventory(source, scope["updater_stamp"], scope["known"]) != scope:
        raise ValueError("The archive contents changed. Inspect and build again.")
    if not scope["files"]:
        raise ValueError("No runtime files are available to package.")
    stopped = stopped or getattr(log, "stopped", lambda: False)
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for index, relative in enumerate(sorted(scope["files"]), 1):
            if stopped():
                raise InterruptedError(stopped_note("release"))
            log(f"{index}/{len(scope['files'])} · {relative}")
            name = folder + "/" + relative
            archive.write(project_path(source, relative), name)
            player_permissions(archive.getinfo(name))
        if scope["updater_stamp"]:
            name = folder + "/" + _UPDATER_STATE
            archive.writestr(name, scope["updater_stamp"] + "\n")
            player_permissions(archive.getinfo(name))
    if inventory(source, scope["updater_stamp"], scope["known"]) != scope:
        raise ValueError(
            "The game changed during packaging. Its partial archive was discarded."
        )


def game_scope(source, known):
    """A clean game ZIP's inventory, with the public version it stamps."""
    return inventory(source, public_version(source), known)


def build_game(
    source, output, scope, expected, log, *, engine, inputs, check=None, stopped=None
):
    """Builds the clean game ZIP whose review read `scope` (game_scope) at
    `output`, which held the file of hash `expected` then. `check` runs
    again once the archive is written, before it replaces the destination,
    and `inputs` names the runtime files a later freshness check compares."""
    output = Path(output)
    folder = game_folder(output, engine)
    stopped = stopped or getattr(log, "stopped", lambda: False)
    if game_scope(source, scope["known"]) != scope:
        raise ValueError(
            "The package contents or public version changed. Build a new release preview."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with system.staging_folder(output.parent, ".dazedtl-release-") as temporary:
        staged = temporary / output.name
        write_archive(source, staged, scope, log, folder=folder, stopped=stopped)
        if check:
            check()
        if game_scope(source, scope["known"]) != scope:
            raise ValueError(
                "The game or public version changed during packaging. Its partial archive was discarded."
            )
        # Later checks compare only the runtime files translation work
        # changes, not the whole game. An applied image edited outside Images
        # still packages; that archive just cannot be compared later.
        try:
            built = basis(source, inputs())
        except ValueError:
            built = {"inputs": None}
        saved = publish(staged, output, expected, stopped=stopped)
    return {
        **saved,
        "kind": "game",
        **built,
        "files": len(scope["files"]) + bool(scope["updater_stamp"]),
        "excluded": len(scope["exclusions"]),
        "updater_stamp": bool(scope["updater_stamp"]),
    }


def runtime_asset(source, relative):
    """Explicit additions are player images/fonts, never arbitrary private files."""
    path = project_path(source, relative)
    lowered = relative.casefold().split("/")
    area = lowered[1:] if lowered[0] == "www" else lowered
    images = {".png", ".jpg", ".jpeg", ".webp", ".rpgmvp", ".png_", ".bmp"}
    extensions = {
        "img": images,
        # VX Ace keeps its images in Graphics and fonts in Fonts.
        "graphics": images,
        "fonts": {".ttf", ".otf", ".woff", ".woff2"},
    }
    if (
        exclusion(relative)
        or len(area) < 2
        or area[0] not in extensions
        or path.suffix.casefold() not in extensions[area[0]]
    ):
        raise ValueError(
            "Add exact player image or font paths under img/, Graphics/ or fonts/ (including www/ layouts)."
        )
    return relative


def applied_images(source):
    """Each image the Image Manager applied to the game: its path and the
    hash it was applied at, wherever its folder is."""
    root = Path(source)
    location = root / ".dazedtl/image_manager/guided/inventory.sqlite3"
    if not location.is_file():
        return {}
    index = project_path(root, location.relative_to(root).as_posix())
    found = {}
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as db:
        for (raw,) in db.execute("SELECT data FROM assets"):
            row = json.loads(raw)
            applied = row.get("applied") or {}
            if applied.get("runtimeHash"):
                found[row["runtime"]] = applied["runtimeHash"]
    return found


def applied_assets(source):
    """The applied images a Guided patch carries, each a player image under
    its engine's image folders and as it was applied."""
    root = Path(source)
    paths = []
    for name, applied in applied_images(root).items():
        relative = runtime_asset(root, name)
        if evidence(root, [relative])[relative] != applied:
            raise ValueError(
                "An applied image changed. Review or restore it in Images before packaging: "
                + relative
            )
        paths.append(relative)
    return sorted(set(paths))


def packing_paths(native):
    """The Ace exports packing reads: each data file's JSON and each script."""
    root, data = Path(native["source"]), Path(native["data"])
    found = [*data.glob("*.json"), *data.glob("scripts/*.rb")]
    return sorted(path.relative_to(root).as_posix() for path in found)


def packing_inputs(native):
    paths = packing_paths(native)
    if not any(path.endswith(".json") for path in paths):
        raise ValueError("Ace JSON exports are missing. Extract them before packing.")
    return evidence(Path(native["source"]), paths)


def packing_target(name):
    """The native data file an export packs into, by its case-folded name: a
    JSON file packs into the data file of its name and a script into
    Scripts; the game and the converter match names without regard to case."""
    path = PurePosixPath(name)
    return "scripts" if path.parent.name == "scripts" else path.stem.casefold()


def unpacked(inputs, outputs):
    """Exports without a packed native file."""
    packed = {PurePosixPath(name).stem.casefold() for name in outputs}
    return [name for name in inputs if packing_target(name) not in packed]


def output_target(name):
    """The export a native file the receipt names is packed from, as
    `packing_target` names it: Game.ini holds System's title."""
    path = PurePosixPath(name)
    return "system" if name.casefold() == "game.ini" else path.stem.casefold()


def packing_receipt(native, folder, inputs, restored=()):
    """The game's saved packing receipt, what changed in ``inputs``, its
    current exports, since it was saved, and the native files to pack again.

    The receipt is None when there is none, an older packing version saved
    it, or the native files it describes changed since, other than the
    `restored` ones a checkpoint restore wrote itself, which are packed
    again; the game's data is current while there is a receipt and nothing
    changed or is unpacked."""
    try:
        path = Path(folder) / "ace-packing.json"
        saved = read_json(path) if path.exists() else {}
        # Git and the file system may name a file in other letter cases.
        named = {name.casefold() for name in restored}
        restored = [name for name in saved["outputs"] if name.casefold() in named]
        kept = [name for name in saved["outputs"] if name not in restored]
        if not (
            isinstance(saved["inputs"], dict)
            and all(
                saved["outputs"][name] == value
                for name, value in (
                    evidence(native["source"], kept) if kept else {}
                ).items()
            )
        ):
            return None, None, None
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        return None, None, None
    change = compare(
        Basis(saved.get("version"), saved["inputs"]), Basis(PACKING_VERSION, inputs)
    )
    if change and change.version:
        return None, None, None
    # A removed export leaves nothing to pack.
    names = [
        *(change.added + change.changed if change else ()),
        *unpacked(inputs, saved["outputs"]),
    ]
    targets = {packing_target(name) for name in names}
    return saved, change, targets | set(map(output_target, restored))


def packing_state(native, folder):
    """Whether the game's native data holds its current ace_json, as the
    receipt every in-app write's packing saves shows. Writes outside the app,
    to ace_json or Data, leave it outdated."""
    if native["engine"] != "ACE":
        return {"required": False, "current": True, "message": ""}
    try:
        inputs = packing_inputs(native)
        receipt, change, targets = packing_receipt(native, folder, inputs)
        current = receipt is not None and not change and not targets
    except OSError, ValueError, KeyError, TypeError:
        current = False
    return {
        "required": True,
        "current": current,
        "message": "The game's data matches ace_json."
        if current
        else "The game's data is older than ace_json, such as after an edit outside DazedTL.",
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
    """Size, modification time and SHA-256 of each runtime file an archive is
    built from, which ``current`` compares.

    Device, inode and change time are left out: metadata updates such as a
    permission change alter them without changing the content.
    """
    root = Path(source)
    stamps = {}
    for path in paths:
        info, fingerprint = read_evidence(project_path(root, path))
        stamps[path] = [info.st_size, info.st_mtime_ns, fingerprint]
    return stamps


# Runtime files written again since a build are read to compare them; each
# is read again only once it changes.
_rewritten = Digests()


def _unchanged(root, path, saved):
    """Whether a runtime file holds what it held when an archive was built.

    Its size and time say so without reading it. A file written again with
    the same bytes, as a checkpoint restore that went back to the build's
    files writes it, keeps the archive current: its digest tells. An archive
    saved before digests were recorded cannot tell, so the file reads changed.
    """
    if not isinstance(saved, list) or len(saved) not in (2, 3):
        return False
    target = project_path(root, path)
    info = target.stat()
    size, modified, *fingerprint = saved
    if (info.st_size, info.st_mtime_ns) == (size, modified):
        return True
    return (
        bool(fingerprint)
        and info.st_size == size
        and fingerprint == [_rewritten.file(target, info)]
    )


def basis(source, paths):
    """What a later freshness check (`current`) compares an archive with:
    the checkpoint the game was at and the stamps of `paths`, the runtime
    files it was built from, and of the files changed since that checkpoint,
    which a later one takes in as they are."""
    from dazedtl.compatibility.checkpoint_commits import at

    try:
        checkpoint, pending = at(source)
    except RuntimeError:
        checkpoint, pending = None, frozenset()
    pending = [
        name
        for name in pending
        if _shipped(name) and project_path(source, name).is_file()
    ]
    return {
        "inputs": input_stamps(source, sorted({*paths, *pending})),
        "checkpoint": checkpoint,
    }


def _shipped(name):
    """Whether a release may hold the file at `name`, as `inventory` reads
    its folder."""
    top = PurePosixPath(name).parts
    return exclusion(name) is None and (
        len(top) == 1 or exclusion(top[0], directory=True) is None
    )


def current(value, source):
    """Whether a saved archive still matches the game's runtime files.

    None means the archive predates recorded inputs, so it cannot be compared.
    Images applied after the build also make it outdated, but for those
    decoded from the game's archives, which it never holds, as does a change
    its record was marked outdated by (operations.outdate_patch), and a
    checkpoint since its build that added, changed or removed another file a
    release may hold, as a game update adding maps does. A record without
    its checkpoint, or one Git can no longer read, is compared by its inputs
    alone.
    """
    from util.paths import decoded_image_files

    from dazedtl.compatibility.checkpoint_commits import changed_since

    if not available(value) or value.get("outdated"):
        return False
    inputs = value.get("inputs")
    if not isinstance(inputs, dict):
        return None
    try:
        applied = set(applied_images(source))
        if not all(
            _unchanged(source, path, saved) for path, saved in inputs.items()
        ) or not applied - decoded_image_files(source, applied) <= set(inputs):
            return False
    except OSError, ValueError:
        return False
    checkpoint = value.get("checkpoint")
    try:
        changed = changed_since(source, checkpoint) if checkpoint else None
    except RuntimeError:
        changed = None
    built = {_known_key(name) for name in inputs}
    return not any(
        _known_key(name) not in built and _shipped(name) for name in changed or ()
    )


def publish(staged, output, expected, *, stopped=lambda: False):
    """Keep the previous ZIP until a complete archive is ready to replace it."""
    staged, output = Path(staged), Path(output)
    with zipfile.ZipFile(staged) as archive:
        if not archive.infolist() or archive.testzip() is not None:
            raise ValueError("The release ZIP could not be verified.")
    if stopped():
        raise InterruptedError(stopped_note("release"))
    if output_hash(output) != expected:
        raise ValueError(
            "The destination changed while packaging. Choose the output again."
        )
    system.replace(staged, output)
    identity = stamp(output)
    return {
        "path": str(output),
        "size": identity[2],
        "stamp": identity,
        "saved": datetime.now(UTC).isoformat(),
    }
