"""Stage an explicit Len patch and align its untranslated backup without checking out branches."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import subprocess
import tempfile
from collections.abc import Collection, Iterable
from itertools import chain
from pathlib import Path, PurePosixPath
from typing import Any

from util.gameupdate_config import CONFIG, file_values
from util.len_git import git_status
from util.len_translation import LenProject, _write_atomic
from util.paths import (
    GAME_REPOSITORY_METADATA, LEN_PATCH_GITIGNORE_BEGIN, LEN_PATCH_GITIGNORE_END, PROJECT_ROOT,
    game_tool_gitattributes_text, is_portable_game_file, normalize_game_tool_gitignore_text,
    portable_game_files, without_gitignore_section,
)
from util.playtest.fixes import MAIN as FIXES_MAIN
from util.playtest.fixes import NAME as FIXES_PLUGIN
from util.playtest.fixes import PLUGIN as FIXES_FILE
from util.playtest.fixes import loads_fixes, without_loader
from util.playtest.fixes import patch_files as fixes_files
from util.project_preparation import (
    GAMEUPDATE_COPY_SKIP_NAMES, RPG_GAMEUPDATE_COPY_SKIP_NAMES, rpgmaker_layout,
)
from util.version_update import GitWorkflowError
from util.version_update.git_workflow import (
    _AssetManifestEntry, _asset_state_path, _commit_tree, _hash_file,
    _is_local_only_asset, _is_tool_owned_path, _load_asset_manifest,
    _load_asset_manifest_metadata, _message, _open_index_lock, _reject_original_checked_out_elsewhere,
    _run_git, _save_asset_manifest, _temporary_index, _tree_files, _write_json_atomic,
)
from util import system

_BEGIN = LEN_PATCH_GITIGNORE_BEGIN
_END = LEN_PATCH_GITIGNORE_END
_METADATA = set(GAME_REPOSITORY_METADATA)
# DazedTL writes these rules into every patch; the rest of the metadata is the game's.
_RULES = (".gitignore", ".gitattributes")
_PLUGIN_REGISTRIES = ("js/plugins.js", "www/js/plugins.js")


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or PurePosixPath(value).as_posix() != value:
        raise GitWorkflowError(f"Use an exact game-relative file path: {value!r}")
    parts = value.split("/")
    if (value.startswith("/") or any(p.casefold() in {".", "..", ".git", ".dazedtl", ".agents", ".codex"} for p in parts)
            or any(c in value for c in "\\\x00\r\n\t:")
            or any(p.casefold() in {"save", "saves", "logs", "cache", "__pycache__", "node_modules", ".venv", "venv"} for p in parts[:-1])
            or any(p == ".env" or p.startswith(".env.") for p in parts)
            or parts[-1] in {".api_key", "api_keys.json", "previous_patch_sha.txt"}
            or parts[-1].endswith(("_key.txt", "_keys.txt", ".log", ".tmp"))):
        raise GitWorkflowError(f"Local state or unsafe path cannot enter the patch: {value!r}")
    return value


def repository_files(root: Path) -> set[str]:
    """The repository metadata a patch keeps: DazedTL's rule files and the
    game's own metadata it holds."""
    return {p for p in _METADATA if (root / p).exists()} | set(_RULES)


def updater_config(root: Path) -> bool:
    """Whether the game holds a GameUpdate config players' updates can use."""
    path = root / CONFIG
    return (
        not path.is_symlink()
        and path.is_file()
        and file_values(path.read_text(encoding="utf-8", errors="replace")) is not None
    )


def _held(root: Path, relative: str) -> bool:
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            return False
    return path.is_file()


def setup_files(root: Path) -> list[str]:
    """The runtime files of DazedTL's own that Set up installed in the game:
    GameUpdate's launchers and scripts, and the MV/MZ plugins for the update
    check and Forge, which the game stops at boot without once its plugins.js
    loads them."""
    from util.forge.config import PLUGIN_BY_ENGINE
    from util.translation_update_check.installer import PLUGIN_NAME

    template = PROJECT_ROOT / "gameupdate"
    skip = RPG_GAMEUPDATE_COPY_SKIP_NAMES if rpgmaker_layout(root) else GAMEUPDATE_COPY_SKIP_NAMES
    names = [f"{web}js/plugins/{name}.js" for web in ("www/", "")
             for name in (PLUGIN_NAME, *PLUGIN_BY_ENGINE.values())]
    for path in template.rglob("*"):
        relative = path.relative_to(template)
        # The installation README is repository metadata, handled separately.
        if path.is_file() and not skip & set(relative.parts) and relative.as_posix() not in _METADATA:
            names.append(relative.as_posix())
    return sorted(name for name in names if _held(root, name))


def dazedtl_files(root: Path) -> dict[str, dict]:
    """The patch-manifest rows of DazedTL's own runtime files the game holds,
    which every patch carries whichever method wrote its manifest: Set up's
    files and the playtest's fixes with the main.js that loads them."""
    return {**{name: {} for name in setup_files(root)}, **fixes_files(root)}


def with_dazedtl_files(root: Path, document: Any) -> Any:
    """A runtime patch manifest, a list of paths or an object with `files`,
    with DazedTL's own files in it; their rows are DazedTL's, since DazedTL
    writes those files."""
    rows = dazedtl_files(root)
    if not rows:
        return document
    if isinstance(document, list):
        return {"files": {**{path: {} for path in document}, **rows}}
    files = document.get("files") if isinstance(document, dict) else None
    if isinstance(files, list):
        files = {path: {} for path in files}
    if not isinstance(files, dict):
        return document
    return {**document, "files": {**files, **rows}}


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _plugin_refusal(root: Path, scope: Collection[str], original: Iterable[str],
                    original_game: Path | None) -> str | None:
    """Why a patch's plugins.js may not go to players: it switches on plugins
    whose file neither the patch nor the original game holds, so their game
    stops at start. `original` names the original game's files, and
    `original_game` is a folder of them. Paths match in any letter case, as
    Windows loads them, and DazedTL's own plugins never count as the original
    game's: Git set up on a prepared game records them, but no release has
    them."""
    from util.forge.config import PLUGIN_BY_ENGINE
    from util.rpgmaker_plugin_registry import PluginRegistryError, plugin_entries
    from util.tl_inspector.installer import PLUGIN_NAME as INSPECTOR
    from util.translation_update_check.installer import PLUGIN_NAME

    registries = [registry for registry in _PLUGIN_REGISTRIES if registry in scope]
    if not registries:
        return None
    own = {name.casefold() for name in (PLUGIN_NAME, INSPECTOR, FIXES_PLUGIN, *PLUGIN_BY_ENGINE.values())}
    patch = {path.casefold() for path in scope}
    known = {path.casefold() for path in original}
    for registry in registries:
        try:
            entries = plugin_entries((root / registry).read_text(encoding="utf-8-sig", errors="replace"))
        except PluginRegistryError:
            # The playtest reports a list the game can't read as a crash.
            continue
        folder = registry.removesuffix("plugins.js") + "plugins/"
        missing = {}
        for entry in entries:
            name = entry.get("name")
            if not entry.get("status") or not isinstance(name, str) or not name:
                continue
            # The game asks for the plugin by URL, which takes either slash.
            path = posixpath.normpath(folder + name.replace("\\", "/") + ".js")
            if path.startswith("../") or path.casefold() in patch:
                continue
            if name.casefold() in own or not (
                    path.casefold() in known or (original_game is not None and _held(original_game, path))):
                missing[name] = path
        if missing:
            plural = "s" if len(missing) > 1 else ""
            return (f"{registry} loads the plugin{plural} {_listed(sorted(missing))}, whose file{plural} "
                    "neither the patch nor the original game has, so players' game would stop at start. "
                    f"Add {_listed(sorted(missing.values()))} to the patch manifest.")
    return None


def _fixes_refusal(root: Path, scope: Collection[str]) -> str | None:
    """Why a patch's main.js and the playtest's fixes may not go to players
    together: a main.js that loads fixes the patch lacks stops their game at
    start, and fixes no main.js loads, as a game update's merge can leave
    the release's main.js, let the problems they fix come back."""
    for web in ("www/", ""):
        main, plugin = web + FIXES_MAIN, web + FIXES_FILE
        loads = main in scope and _held(root, main) and loads_fixes((root / main).read_bytes())
        if loads and plugin not in scope:
            return (f"{main} loads the playtest's fixes, but the patch has no {plugin}, so players' "
                    f"game would stop at start. Apply the fixes again, or take their line out of {main}.")
        if plugin in scope and not loads:
            return (f"{plugin} holds the playtest's fixes, but {main} in the patch doesn't load them, "
                    "as a game update can leave it, so the problems they fix would come back. "
                    f"Apply the fixes again, which loads them, or take {plugin} out of the game.")
    return None


def patch_refusal(root: Path, scope: Collection[str], original_names: Collection[str] = ()) -> str | None:
    """Why the patch's files `scope` may not go to players, as the plugin
    and fixes checks find, with the original game's files from the
    `original` branch, its ignored-asset inventory and `original_names`."""
    repo = Path(root)
    originals = _tree_files(repo, "original", "")
    assets = _load_asset_manifest(repo, "") or {}
    return (_plugin_refusal(repo, scope, chain(originals, assets, original_names), None)
            or _fixes_refusal(repo, scope))


def _file(root: Path, relative: str) -> Path:
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise GitWorkflowError(f"Patch/source paths cannot traverse symlinks: {relative}")
    if not path.is_file():
        raise GitWorkflowError(f"Required file is missing: {path}")
    return path


def patch_manifest(document: object) -> dict[str, dict]:
    """Accept a complete file list or a release manifest with optional bound hashes."""
    raw = document.get("files") if isinstance(document, dict) else document
    if isinstance(raw, list):
        if not all(isinstance(p, str) for p in raw) or len(set(raw)) != len(raw):
            raise GitWorkflowError("Patch files must be unique path strings")
        raw = {p: {} for p in raw}
    if not isinstance(raw, dict):
        raise GitWorkflowError("Supply a file list or an object containing files")
    result = {}
    for relative, row in raw.items():
        _path(relative)
        if relative in _METADATA or not isinstance(row, dict):
            raise GitWorkflowError("List runtime patch files only; repository metadata is handled separately")
        for key in ("sha256", "original_sha256"):
            if key in row and not (key == "original_sha256" and row[key] is None):
                if not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                    raise GitWorkflowError(f"Invalid {key} for {relative}")
        result[relative] = row
    return result


def _escape(path: str) -> str:
    return "".join("\\" + c if c in "*?[]! " else c for c in path)


def scope_ignore(existing: str, paths: set[str]) -> str:
    """Place exact-path rules after the project's rules, followed only by the
    portable-settings allowlist they would otherwise override."""
    if existing.count(_BEGIN) != existing.count(_END) or existing.count(_BEGIN) > 1:
        raise GitWorkflowError("The Len patch .gitignore block is incomplete or duplicated")
    if _BEGIN in existing:
        start, end = existing.index(_BEGIN), existing.index(_END)
        if end < start:
            raise GitWorkflowError("The Len patch .gitignore block is out of order")
        existing = without_gitignore_section(existing, start, end + len(_END))
    directories = {p[:i] for p in paths for i, c in enumerate(p) if c == "/"}
    lines = [_BEGIN, "# Only reviewed runtime patch files and repository metadata belong in Git.", "/*"]
    for directory in sorted(directories, key=lambda p: (p.count("/"), p)):
        lines.extend(["!/" + _escape(directory) + "/", "/" + _escape(directory) + "/*"])
    lines.extend("!/" + _escape(p) for p in sorted(paths))
    lines.append(_END)
    return normalize_game_tool_gitignore_text(existing.rstrip() + "\n\n" + "\n".join(lines) + "\n")


def grow_scope(repo: Path, tracked: Collection[str], added: Iterable[str]) -> tuple[list[str], list[str]]:
    """Lets `added`, files a patch-scoped translation branch lacks, into its
    patch: the .gitignore patch block allows them besides what Git tracks,
    and the inventory of the original's files Git leaves out drops them.
    Returns the files let in and the rule files changed, .gitattributes too
    when it lacks a rule keeping DazedTL's own files, such as ace_json, out
    of players' downloads; a branch without a patch block, which every file
    can join, lets in none."""
    ignore = repo / ".gitignore"
    text = ignore.read_text(encoding="utf-8", errors="surrogateescape") if ignore.is_file() else ""
    if _BEGIN not in text:
        return [], []
    accepted = []
    for relative in added:
        try:
            accepted.append(_path(relative))
        except GitWorkflowError:
            continue
    accepted = sorted(p for p in set(accepted) if not is_portable_game_file(p) and p not in _METADATA)
    if not accepted:
        return [], []
    scope = {p for p in tracked if not is_portable_game_file(p)} | set(accepted) | repository_files(repo)
    updated = scope_ignore(text, scope)
    rules = []
    if updated != text:
        _write_atomic(ignore, updated)
        rules.append(".gitignore")
    attributes = repo / ".gitattributes"
    existing = attributes.read_text(encoding="utf-8", errors="surrogateescape") if attributes.is_file() else ""
    if (kept := game_tool_gitattributes_text(existing)) != existing:
        _write_atomic(attributes, kept)
        rules.append(".gitattributes")
    inventory = _asset_state_path(repo, "", "official-assets")
    if inventory.is_file():
        document = json.loads(inventory.read_text(encoding="utf-8"))
        files = document.get("files")
        if isinstance(files, dict) and files.keys() & set(accepted):
            document["files"] = {p: row for p, row in files.items() if p not in accepted}
            _write_json_atomic(inventory, document)
    return accepted, rules


def _blob_metadata(repo: Path, objects: set[str]) -> dict[str, tuple[str, int]]:
    """Stream a single cat-file batch, including large native assets."""
    result = {}
    if not objects:
        return result
    with tempfile.TemporaryFile() as requests:
        requests.write(("\n".join(sorted(objects)) + "\n").encode("ascii"))
        requests.seek(0)
        with system.popen(["git", "-C", str(repo), "cat-file", "--batch"],
                              stdin=requests, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            for _ in objects:
                header = process.stdout.readline().decode("ascii").split()
                if len(header) != 3 or header[1] != "blob":
                    raise GitWorkflowError("Cannot read original source blob")
                oid, _, length = header
                size = remaining = int(length)
                digest = hashlib.sha256()
                while remaining:
                    data = process.stdout.read(min(remaining, 1024 * 1024))
                    if not data:
                        raise GitWorkflowError("Incomplete original source blob")
                    digest.update(data)
                    remaining -= len(data)
                if process.stdout.read(1) != b"\n":
                    raise GitWorkflowError("Invalid original source blob boundary")
                result[oid] = (digest.hexdigest(), size)
            if process.wait() != 0:
                raise GitWorkflowError("Cannot inspect original source objects")
    return result


def _hash_paths(repo: Path, files: dict[str, Path], *, write: bool) -> dict[str, tuple[str, str]]:
    if not files:
        return {}
    args = ["hash-object", "--no-filters", "--stdin-paths"]
    if write:
        args.append("-w")
    # Git's stdin-paths accepts C-quoted names, including spaces and quote marks.
    hashes = _run_git(repo, *args, input_text="".join(json.dumps(str(p), ensure_ascii=False) + "\n" for p in files.values()), timeout=600).stdout.splitlines()
    if len(hashes) != len(files):
        raise GitWorkflowError("Git did not hash every selected file")
    return {name: ("100755" if path.stat().st_mode & 0o111 else "100644", oid)
            for (name, path), oid in zip(files.items(), hashes)}


def _tree(repo: Path, entries: dict[str, tuple[str, str]], index: dict[str, str]) -> str:
    _run_git(repo, "read-tree", "--empty", env=index)
    if entries:
        _run_git(repo, "update-index", "-z", "--index-info", env=index,
                 input_text="".join(f"{mode} {oid}\t{name}\0" for name, (mode, oid) in sorted(entries.items())))
    return _run_git(repo, "write-tree", env=index).stdout.strip()


def sync_patch_scope(project: LenProject, document: object, *, original_game: Path | None = None,
                     original_names: Collection[str] = (), dry_run: bool = False) -> dict:
    """Stage only reviewed files; append an original scope commit, retaining all local files.

    A list is the COMPLETE patch, not just this batch's changes. Hash-bound release
    manifests also verify that the reviewed English bytes are in the actual game root.
    `original_names` lists all of the untranslated game's files when
    `original_game` holds only the patch's, as a restored backup does.
    """
    with system.staging_folder(tempfile.gettempdir(), "dazedtl-original-") as derived:
        return _sync_patch_scope(project, document, original_game, original_names, dry_run, derived)


def _sync_patch_scope(project: LenProject, document: object, original_game: Path | None,
                      original_names: Collection[str], dry_run: bool, derived: Path) -> dict:
    selected = patch_manifest(document)
    state = git_status(project)
    repo = project.game_root
    if state["repo_root"] != str(repo) or not state["configured"]:
        raise GitWorkflowError("Run Len git-setup in this game repository first")
    if state["current_branch"] != state["translation_branch"] or state["current_branch"] == "original":
        raise GitWorkflowError("Check out the registered translation branch before synchronizing patch files")
    if state["pending_operations"] or state["asset_sync_pending"]:
        raise GitWorkflowError("Finish the pending Git or version update first")
    if not state["preserve_game_files"]:
        raise GitWorkflowError("Patch scoping requires a native-byte Len repository")
    _reject_original_checked_out_elsewhere(repo)
    if _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise GitWorkflowError("Review and commit existing staged changes first; patch scoping will not overwrite them")
    if not state["original_version"]:
        raise GitWorkflowError("Record the original release version with git-setup first")
    original_ref = state["original_commit"]
    head = state["translation_commit"]
    originals = _tree_files(repo, original_ref, "")
    # The patch only grows: every DazedTL change is a checkpoint that lets
    # the files it wrote in, so a manifest naming fewer keeps the rest.
    metadata_names = repository_files(repo)
    for name in _tree_files(repo, head, ""):
        if name not in selected and name not in metadata_names and not is_portable_game_file(name):
            selected[name] = {} if name in originals else {"original_sha256": None}
    if updater_config(repo) and CONFIG not in selected:
        # A working GameUpdate config joins every patch, so the published
        # translation tells players' GameUpdate where to download it from.
        selected[CONFIG] = {} if CONFIG in originals else {"original_sha256": None}
    assets = _load_asset_manifest(repo, "")
    asset_metadata = _load_asset_manifest_metadata(repo, "")
    metadata = repository_files(repo)
    # The game's glossary, settings and skills follow the translation in Git,
    # never the untranslated original.
    portable = set(portable_game_files(repo))
    files = {p: _file(repo, p) for p in chain(selected, portable)}
    files.update({p: _file(repo, p) for p in metadata if p not in _RULES})
    before_rules = {}
    for name in _RULES:
        if (repo / name).exists() or (repo / name).is_symlink():
            _file(repo, name)
        before_rules[name] = (repo / name).read_bytes() if (repo / name).exists() else None
    before_text = {name: (raw or b"").decode("utf-8", errors="surrogateescape") for name, raw in before_rules.items()}
    rules = {".gitignore": scope_ignore(before_text[".gitignore"], set(selected) | metadata),
             ".gitattributes": game_tool_gitattributes_text(before_text[".gitattributes"])}
    source = original_game.expanduser().resolve() if original_game is not None else None
    if source is not None and (source == repo or not source.is_dir()):
        raise GitWorkflowError("Use a separate, matching untranslated backup as the original")
    # Players keep the original game's plugins; Git's inventory of them leaves
    # out names that look local, such as a plugin called Save..., which the
    # backup's list holds.
    refusal = (_plugin_refusal(repo, selected, chain(originals, assets or (), original_names), source)
               or _fixes_refusal(repo, selected))
    if refusal:
        raise GitWorkflowError(refusal)
    # Existing Git originals are authoritative; a supplied backup must match them.
    original_files = {}
    # Set up's files keep the prepared untranslated game's copy as their
    # original, like the plugins.js loading them; a game set up after its Git
    # baseline, or one without a prepared backup, has none, and only the
    # translation adds them.
    installed = set(setup_files(repo))
    # The main.js loading the playtest's fixes is the game's with one line of
    # DazedTL's added; without a backup or Git copy, that line taken out is
    # its original.
    loaders = {name for name, row in fixes_files(repo).items() if "original_sha256" not in row}
    for relative, row in selected.items():
        if "sha256" in row and _hash_file(files[relative]) != row["sha256"]:
            raise GitWorkflowError(f"Reviewed patch bytes are not installed in the game root: {relative}")
        if source is not None and ((source / relative).exists() or (source / relative).is_symlink()):
            original_files[relative] = _file(source, relative)
        elif (relative in loaders and relative not in originals
              and (raw := without_loader(files[relative].read_bytes())) is not None):
            original_files[relative] = derived / relative
            original_files[relative].parent.mkdir(parents=True, exist_ok=True)
            original_files[relative].write_bytes(raw)
        elif (relative not in originals and relative not in installed
              and not ("original_sha256" in row and row["original_sha256"] is None)):
            raise GitWorkflowError(f"Supply the matching untranslated original, or declare a translation-only addition with original_sha256: null: {relative}")
    source_entries = _hash_paths(repo, original_files, write=not dry_run)
    payload_entries = _hash_paths(repo, files, write=not dry_run)
    for name, entry in source_entries.items():
        if name in originals and originals[name] != entry:
            raise GitWorkflowError(f"The supplied original differs from the registered release: {name}")
    if any(originals[p][0] not in {"100644", "100755"} for p in selected if p in originals):
        raise GitWorkflowError("Original patch files must be regular files")
    original_payload = {p: originals[p] if p in originals else source_entries[p]
                        for p in selected if p in originals or p in source_entries}
    digests = _blob_metadata(repo, {v[1] for k, v in originals.items()
                                  if k in selected or (k not in metadata and not _is_tool_owned_path(k) and not _is_local_only_asset(k))})
    for name, row in selected.items():
        old = original_payload.get(name)
        source_digest = (_hash_file(original_files[name]) if name in original_files
                         else digests[old[1]][0] if old else None)
        if "original_sha256" in row and source_digest != row["original_sha256"]:
            raise GitWorkflowError(f"Original source hash disagrees with the reviewed manifest: {name}")
        # The ignored-asset backup lists Set up's files when Git was set up
        # on the prepared game, but they were never the release's.
        added = source_digest is None and name in installed
        if (not added and name not in originals and assets is not None and name in assets
                and source_digest != assets[name].sha256):
            raise GitWorkflowError(f"Original source disagrees with the registered ignored-asset backup: {name}")
    old_tracked = set(_tree_files(repo, head, ""))
    result = {"dry_run": dry_run, "translation_branch": state["translation_branch"],
              "patch_files": len(selected), "original_files": len(original_payload),
              "translation_only_files": sorted(set(selected) - set(original_payload)),
              "untrack": sorted(old_tracked - set(selected) - metadata - portable),
              "original_commit": original_ref, "main_committed": False,
              "local_files_deleted": False}
    if dry_run:
        return result
    # Keep the official updater's ignored-asset inventory aligned when paths leave Git.
    if assets is not None:
        assets = {p: row for p, row in assets.items() if p not in selected}
        for name, (mode, oid) in originals.items():
            if name not in selected and name not in metadata and not _is_tool_owned_path(name) and not _is_local_only_asset(name):
                digest, size = digests[oid]
                assets[name] = _AssetManifestEntry(digest, size, mode)
    index_name, index_env = _temporary_index()
    original_index, original_env = _temporary_index()
    index_path = Path(_run_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
    lock = index_path.with_name(index_path.name + ".lock")
    asset_path = _asset_state_path(repo, "", "official-assets")
    before_assets = asset_path.read_bytes() if asset_path.exists() else None
    new_original = original_ref
    acquired = False
    applied_rules = []
    rules_written = False
    moved_original = False
    try:
        for name, text in rules.items():
            oid = _run_git(repo, "hash-object", "-w", "--no-filters", "--stdin", input_text=text).stdout.strip()
            payload_entries[name] = ("100644", oid)
        original_payload.update({p: payload_entries[p] for p in metadata})
        main_tree = _tree(repo, payload_entries, index_env)
        source_tree = _tree(repo, original_payload, original_env)
        if source_tree != _run_git(repo, "rev-parse", f"{original_ref}^{{tree}}").stdout.strip():
            new_original = _commit_tree(repo, source_tree, _message("original: align patch file scope", state["original_version"]), (original_ref,))
        with _open_index_lock(lock) as handle:
            acquired = True
            handle.write(Path(index_name).read_bytes())
        if (_run_git(repo, "rev-parse", "HEAD").stdout.strip() != head
                or _run_git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() != state["current_branch"]
                or (asset_path.read_bytes() if asset_path.exists() else None) != before_assets
                or _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
                or any(((repo / n).read_bytes() if (repo / n).exists() else None) != b for n, b in before_rules.items())
                or _hash_paths(repo, files, write=False) != {p: v for p, v in payload_entries.items() if p not in _RULES}
                or _hash_paths(repo, original_files, write=False) != source_entries):
            raise GitWorkflowError("The game, source, index or branch changed during patch review; retry after reviewing those changes")
        for name, text in rules.items():
            if text.encode("utf-8", errors="surrogateescape") != before_rules[name]:
                applied_rules.append(name)
                _write_atomic(repo / name, text)
        rules_written = True
        # The allowlist never hides a removed skill, which leaves Git with the commit.
        checks = {p for p in old_tracked if not is_portable_game_file(p)} | set(payload_entries)
        ignored = _run_git(repo, "check-ignore", "--no-index", "-z", "--stdin", check=False,
                           input_text="\0".join(sorted(checks)) + "\0")
        if ignored.returncode not in {0, 1}:
            raise GitWorkflowError("Cannot verify the patch ignore rules")
        hidden = set(ignored.stdout.split("\0")) - {""}
        visible_new = set(_run_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")) - {""}
        if (checks - hidden) != set(payload_entries) or visible_new - set(payload_entries):
            raise GitWorkflowError("Nested or global ignore rules conflict with the exact patch file list; review those rules first")
        _run_git(repo, "update-ref", "refs/heads/original", new_original, original_ref)
        moved_original = new_original != original_ref
        if assets is not None:
            _save_asset_manifest(repo, "", state["original_version"], new_original, assets,
                                 baseline_source_kind=asset_metadata.get("baseline_source_kind", "bootstrap"),
                                 has_unbased_tracked_assets=bool(asset_metadata.get("has_unbased_tracked_assets", False)))
        system.replace(lock, index_path)
        acquired = False
        result.update({"original_commit": new_original, "staged_tree": main_tree})
        return result
    except Exception:
        if moved_original:
            _run_git(repo, "update-ref", "refs/heads/original", original_ref, new_original)
        for name in applied_rules:
            if before_rules[name] is None:
                system.unlink(repo / name)
            else:
                _write_atomic(repo / name, before_text[name])
        if rules_written:
            if before_assets is None:
                system.unlink(asset_path, missing_ok=True)
            else:
                asset_path.write_bytes(before_assets)
        raise
    finally:
        if acquired:
            system.unlink(lock, missing_ok=True)
        system.unlink(index_name, ignore_errors=True)
        system.unlink(original_index, ignore_errors=True)
