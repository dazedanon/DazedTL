"""Git-backed game version updates with exact file-tree preservation.

This module deliberately knows nothing about RPG Maker or any other engine.
Official game folders become Git trees, official releases become commits on the
``original`` branch, and those commits are cherry-picked into the repository's
configured translated branch.
No game file is parsed or reconstructed.
"""

from __future__ import annotations

import os
import functools
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping, NamedTuple

import jsbeautifier

from util import system
from util.paths import (
    GAME_REPOSITORY_METADATA,
    ensure_game_tool_gitignore,
    game_tool_gitattributes_text,
    is_portable_game_file,
    staging_folder,
)
from util.playtest import fixes

from .json_merge import merge_json
from .script_merge import is_plugin_registry, merge_plugins, restore_lines


ORIGINAL_BRANCH = "original"
TRANSLATION_BRANCH = "main"
_LEGACY_TRANSLATION_BRANCH = "translation"
_TRANSLATION_BRANCH_CONFIG = "dazedtl.translationBranch"
_PRESERVE_GAME_FILES_CONFIG = "dazedtl.preserveGameFiles"
_PRESERVE_GAME_FILES_TRAILER = "DazedTL-Preserve-Game-Files: true"
VERSION_TRAILER = "DazedTL-Version"
# Whether an update commit came from a complete release or a patch copied over the game.
RELEASE_TRAILER = "DazedTL-Release"
# On an update commit, the commit of DazedTL's private record of the prepared
# release it was made from (dazedtl/compatibility/original_files.py), which
# counts as the game's original files only once this commit names it.
PREPARED_TRAILER = "DazedTL-Prepared"
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_TOOL_NAME = "DazedMTLTool"
_TOOL_EMAIL = "local@dazedmtl.invalid"
_ZERO_OID = "0" * 40
# DazedTL's own refs outside the branches, never pushed with them.
_PRIVATE_REFS = "refs/dazedtl/"
# Commands that take the index lock before they change anything, so one that
# found the lock held can run again. A `git status` holds it briefly while it
# refreshes the index, including the app's own polls; waiting here, rather
# than stopping the polls, lets them keep that refresh while workers write.
_INDEX_WRITERS = frozenset(
    {"add", "checkout", "checkout-index", "cherry-pick", "commit", "read-tree", "reset", "rm", "update-index"}
)
INDEX_LOCK_WAIT = 10.0
# Git names the lock file it found held in every language: "Unable to create '<path>/index.lock'".
_HELD_LOCK = re.compile(rb"'([^\n]*index\.lock)'")
_HELD_INDEX = (
    "Another Git process is using this repository. If none is running, "
    "delete the leftover .git/index.lock file in the game folder and try again."
)
# Git operations a checkout can be left in the middle of, by the file or
# folder Git keeps in its directory while one is under way.
PENDING_OPERATIONS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
    "BISECT_LOG",
)
_VERSION_LINE = re.compile(r"^DazedTL-Version:\s*(.+?)\s*$", re.MULTILINE)
_VERSION_HINT = re.compile(
    r"(?i)(?:\bversion\b|\bver\.?|\bv|update(?:d)?(?:\s+original)?\s+game\s+files\s+to)"
    r"[\s:._-]*(\d+(?:\.\d+)+)"
)
_IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".png_", ".rpgmvp", ".webp"}
)
_AUDIO_EXTENSIONS = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".m4a_",
        ".mid",
        ".midi",
        ".mp3",
        ".ogg",
        ".ogg_",
        ".opus",
        ".rpgmvm",
        ".rpgmvo",
        ".wav",
        ".wma",
    }
)
_VIDEO_EXTENSIONS = frozenset(
    {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".ogv", ".webm", ".webm_", ".wmv"}
)
_FONT_EXTENSIONS = frozenset({".eot", ".otf", ".ttf", ".woff", ".woff2"})
# Windows batch/registry scripts are CRLF-sensitive; keep their exact bytes.
_CRLF_SENSITIVE_EXTENSIONS = frozenset({".bat", ".cmd", ".reg"})
_ASSET_MANIFEST_FORMAT = 1
_ASSET_BASELINE_SOURCE_BOOTSTRAP = "bootstrap"
_ASSET_BASELINE_SOURCE_CURRENT_GAME = "current-game"
_ASSET_BASELINE_SOURCE_PREVIOUS_OFFICIAL = "previous-official"
_TOOL_RESOURCE_DIRECTORIES = frozenset(
    {
        ".agents",
        ".codex",
        ".dazedtl",
        "dazedtl_images",
        "dictionaries",
        "docs",
        "documentation",
        "gameupdate",
        "prompts",
        "skills",
    }
)
_LOCAL_ONLY_DIRECTORIES = frozenset(
    {
        ".dazedtl",
        ".venv",
        "venv",
        "__pycache__",
        "cache",
        "caches",
        "crash",
        "crashes",
        "log",
        "logs",
        "save",
        "saves",
        "screenshots",
        "temp",
        "tmp",
    }
)
_NON_GAME_RESOURCE_EXTENSIONS = frozenset(
    {".adoc", ".bdic", ".markdown", ".md", ".rst"}
)
_LOCAL_ONLY_FILENAMES = frozenset(
    {
        "cg.dat",
        "kabe3_save.dat",
        "kabe3_system.dat",
        "previous_patch_sha.txt",
        "psbpack.dat",
        "scene.dat",
    }
)
_TOOL_OWNED_ROOT_FILES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        "gameupdate.bat",
        "gameupdate_linux.sh",
        "patch-config.example.txt",
        "patch-config.txt",
        "readme.md",
        "uberwolfcli.exe",
        "uberwolfcli.license.txt",
    }
)


class GitWorkflowError(RuntimeError):
    """Raised when an exact Git workflow operation cannot complete safely."""


class UserFacingGitError(GitWorkflowError):
    """A Git failure worded for the user, with no path outside the game; the page shows it as written."""

    user_facing = True


@dataclass(frozen=True)
class RepositoryStatus:
    selected_root: Path
    repo_root: Path | None
    game_prefix: str
    current_branch: str | None
    original_exists: bool
    original_commit: str | None
    original_version: str | None
    translation_exists: bool
    translation_commit: str | None
    translation_version: str | None
    worktree_clean: bool
    pending_cherry_pick: bool
    git_available: bool = True
    asset_sync_pending: bool = False
    asset_manifest_available: bool = False
    asset_baseline_repair_needed: bool = False
    translation_branch: str | None = None
    applied_update_version: str | None = None
    # With assets pending, whether the update reached the translation, so
    # finishing copies its assets; otherwise cancelling restores the version
    # before it.
    asset_update_applied: bool = False
    # The PENDING_OPERATIONS under way, pending_cherry_pick's among them.
    pending_operations: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(
            self.repo_root
            and self.original_exists
            and self.translation_exists
            and self.current_branch == self.translation_branch
            and self.worktree_clean
            and not self.pending_cherry_pick
            and not self.asset_sync_pending
        )


@dataclass(frozen=True)
class Checkout:
    """What a write to a game needs of its repository, from three Git calls
    (`read_checkout`): where the repository is, the branch it is on, the
    branches it registers, the operations under way and its settings. An
    operation carries it (`carrying`) so its Git calls reuse it."""

    selected_root: Path
    repo: Path
    prefix: str
    # The PENDING_OPERATIONS' paths, the index's and the config file's, by name.
    git_paths: Mapping[str, Path]
    current_branch: str | None
    translation_branch: str | None
    original_commit: str | None
    translation_commit: str | None
    # The PENDING_OPERATIONS under way.
    pending_operations: tuple[str, ...]
    asset_sync_pending: bool
    # DazedTL's repository-local settings (`_settings`), None when Git could
    # not read them.
    settings: Mapping[str, str | None] | None
    # The config file as the settings were read, which tells whether they
    # still hold.
    config_stat: tuple[int, int, int] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.original_commit and self.translation_commit)

    @property
    def index(self) -> Path:
        return self.git_paths["index"]

    @functools.cached_property
    def preserve_game_files(self) -> bool:
        return _preserve_policy(self.repo, self.settings)

    def settings_hold(self) -> bool:
        """Whether the config file is as it was when the settings were read."""
        return self.config_stat is not None and self.config_stat == _stat(
            self.git_paths["config"]
        )


def _stat(path: Path) -> tuple[int, int, int] | None:
    try:
        value = path.stat()
    except OSError:
        return None
    return value.st_mtime_ns, value.st_size, value.st_ino


# The repository read the Git calls of an operation reuse (`carrying`).
_carried: ContextVar[Checkout | None] = ContextVar("carried_checkout", default=None)


@contextmanager
def carrying(checkout: Checkout | None) -> Iterator[None]:
    """Runs an operation whose Git calls reuse `checkout`, a read of its
    repository: its settings, such as whether it keeps game files as they
    are, while its config file is unchanged, and its index's path."""
    token = _carried.set(checkout)
    try:
        yield
    finally:
        _carried.reset(token)


@dataclass(frozen=True)
class BootstrapResult:
    repo_root: Path
    original_commit: str
    translation_commit: str
    version: str
    formatted_json_paths: tuple[str, ...] = ()
    json_warnings: tuple[str, ...] = ()
    ignored_paths: tuple[str, ...] = ()
    gitignore_installed: bool = False


@dataclass(frozen=True)
class UpdateResult:
    repo_root: Path
    original_commit: str
    translation_commit: str | None
    version: str
    official_won_paths: tuple[str, ...] = ()
    pending_conflicts: tuple[str, ...] = ()
    content_changed: bool = True
    already_present_paths: tuple[str, ...] = ()
    external_changes: tuple[UpdateExternalChange, ...] = ()

    @property
    def complete(self) -> bool:
        return self.translation_commit is not None and not self.pending_conflicts


@dataclass(frozen=True)
class UpdateFileChange:
    path: str
    change: str
    added_lines: int | None
    deleted_lines: int | None
    is_image: bool = False
    translation_changed: bool = False
    already_present: bool = False
    whole_file_replaced: bool = False
    result: str = ""


@dataclass(frozen=True)
class UpdateImageChange:
    path: str
    change: str
    tracked: bool
    warning: bool
    result: str


@dataclass(frozen=True)
class UpdateExternalChange:
    path: str
    change: str
    category: str
    already_present: bool
    size_bytes: int
    result: str


@dataclass(frozen=True)
class UpdatePreview:
    repo_root: Path
    source_root: Path
    version: str
    original_commit: str
    translation_commit: str
    proposed_tree: str
    added_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    overlapping_paths: tuple[str, ...]
    already_present_paths: tuple[str, ...]
    formatted_json_paths: tuple[str, ...]
    json_warnings: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    file_changes: tuple[UpdateFileChange, ...] = ()
    image_changes: tuple[UpdateImageChange, ...] = ()
    external_changes: tuple[UpdateExternalChange, ...] = ()
    proposed_asset_manifest: str = ""
    baseline_asset_manifest: str = ""
    asset_manifest_available: bool = True
    baseline_source_root: Path | None = None
    preserved_translation_asset_paths: tuple[str, ...] = ()
    patch_overlay: bool = False
    # The tree the update was compared from: the original branch's, or the
    # previous official folder's when one was given.
    baseline_tree: str = ""

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return self.added_paths + self.modified_paths + self.deleted_paths

    @property
    def translation_change_paths(self) -> tuple[str, ...]:
        already_present = set(self.already_present_paths)
        return tuple(path for path in self.changed_paths if path not in already_present)

    @property
    def content_change_expected(self) -> bool:
        return bool(
            self.translation_change_paths
            or any(not change.already_present for change in self.external_changes)
        )


@dataclass(frozen=True)
class _SourceFile:
    path: Path
    relative: str
    mode: str
    normalized_text: str | None = None
    json_warning: str | None = None


@dataclass(frozen=True)
class _TreeBuild:
    tree: str
    formatted_json_paths: tuple[str, ...]
    json_warnings: tuple[str, ...]
    ignored_paths: tuple[str, ...]


@dataclass(frozen=True)
class _AssetManifestEntry:
    sha256: str
    size: int
    mode: str


def _command_name(args: tuple[str, ...]) -> str:
    index = 0
    while index < len(args) - 1 and args[index] == "-c":
        index += 2
    return args[index] if index < len(args) else "command"


def _run_git(
    cwd: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 120,
    errors: str = "replace",
) -> subprocess.CompletedProcess[str]:
    """Runs Git and decodes its output with `errors`; "surrogateescape" keeps
    a file name that isn't UTF-8 as Python names it, for a caller that reads
    paths to write files by."""
    command = ["git", "-C", str(cwd), *args]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    # Feed Git stdin as raw UTF-8 bytes. On Windows, text-mode subprocess pipes
    # translate LF to CRLF, which corrupts hash-object --stdin blobs and can
    # embed trailing CR into update-index --index-info paths. A file name that
    # isn't UTF-8, as unzip leaves Shift-JIS names on Linux, reaches Python
    # with surrogateescape and goes to Git as its own bytes.
    input_bytes = None if input_text is None else input_text.encode("utf-8", "surrogateescape")
    deadline = None
    while True:
        try:
            raw = system.run(
                command,
                check=False,
                capture_output=True,
                input=input_bytes,
                env=process_env,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise UserFacingGitError("Git is not installed or is not available on PATH") from exc
        # The exceptions' own text is a Python command list; say which Git command,
        # after any -c settings in front of it.
        except subprocess.TimeoutExpired as exc:
            raise UserFacingGitError(f"git {_command_name(args)} did not finish within {timeout} seconds.") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            reason = getattr(exc, "strerror", None) or type(exc).__name__
            raise UserFacingGitError(f"git {_command_name(args)} could not run: {reason}") from exc
        held = _HELD_LOCK.search(raw.stderr) if raw.returncode and _command_name(args) in _INDEX_WRITERS else None
        if held is None:
            break
        deadline = deadline or index_lock_deadline(Path(os.fsdecode(held.group(1))))
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    result = subprocess.CompletedProcess(
        raw.args,
        raw.returncode,
        raw.stdout.decode("utf-8", errors=errors),
        raw.stderr.decode("utf-8", errors="replace"),
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitWorkflowError(detail)
    return result


def index_lock_deadline(lock: Path) -> float:
    """When waiting for the index lock at `lock` gives up: once it has been held for
    INDEX_LOCK_WAIT, by its age, which a Git process refreshing the index never
    reaches. A lock a crashed Git left fails at once, rather than after a wait in
    each Git command that meets it."""
    try:
        held = time.time() - lock.stat().st_mtime
    except OSError:
        held = 0.0
    return time.monotonic() + min(INDEX_LOCK_WAIT, max(0.0, INDEX_LOCK_WAIT - held))


def wait_for_index_lock(lock: Path) -> None:
    """Returns once no Git process holds the index lock at `lock`, refusing as
    `_open_index_lock` does once it has been held too long, for a write that
    must not start while its checkpoint would fail."""
    deadline = index_lock_deadline(lock)
    while lock.exists():
        if time.monotonic() >= deadline:
            raise UserFacingGitError(_HELD_INDEX)
        time.sleep(0.1)


def _open_index_lock(lock: Path):
    """Creates the index lock for writing, waiting like `_run_git` while another Git process holds it."""
    deadline = index_lock_deadline(lock)
    while True:
        try:
            return lock.open("xb")
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise UserFacingGitError(_HELD_INDEX) from None
            time.sleep(0.1)


def _require_matching_worktree(repo: Path, *, action: str) -> None:
    status = _run_git(repo, "status", "--porcelain=v1", "-z").stdout
    if not status:
        return
    entries = [entry for entry in status.split("\x00") if entry]
    preview = ", ".join(entries[:8])
    if len(entries) > 8:
        preview = f"{preview}, ... ({len(entries)} paths)"
    raise GitWorkflowError(
        f"{action}, but the translated worktree does not match it: {preview}"
    )


def _configure_exact_tree_repo(repo: Path) -> None:
    """Disable platform line-ending rewrites for exact game tree transport.

    Local Git config is not pushed, so clones and other machines may still have
    global ``core.autocrlf=true``. Re-apply on every workflow entry that touches
    the repository so later updates and conflict checkouts keep LF blobs exact.
    """
    _run_git(repo, "config", "core.autocrlf", "false")
    _run_git(repo, "config", "core.eol", "lf")


def _settings(repo: Path) -> dict[str, str | None] | None:
    """DazedTL's repository-local settings by their lowercase names, from one
    Git call: each one's last value, None for one set without a value; None
    when Git can't read them."""
    result = _run_git(
        repo, "config", "--local", "-z", "--get-regexp", r"^dazedtl\.", check=False
    )
    if result.returncode not in {0, 1}:
        return None
    settings: dict[str, str | None] = {}
    for entry in result.stdout.split("\0"):
        if entry:
            name, separator, value = entry.partition("\n")
            settings[name] = value if separator else None
    return settings


def _config_bool(value: str | None) -> bool | None:
    """A setting's value as Git reads a boolean, or None when it reads none."""
    if value is None:
        return True
    word = value.strip().casefold()
    if word in {"true", "yes", "on"}:
        return True
    if word in {"false", "no", "off", ""}:
        return False
    number = re.fullmatch(r"([-+]?\d+)[kmg]?", word)
    return bool(int(number.group(1))) if number else None


def _preserve_game_files(repo: Path) -> bool:
    """Len projects keep native encodings/layout and their reviewed ignore policy."""
    carried = _carried.get()
    if (
        carried is not None
        and repo in (carried.repo, carried.selected_root)
        and carried.settings_hold()
    ):
        return carried.preserve_game_files
    return _preserve_policy(repo, _settings(repo))


def _preserve_policy(repo: Path, settings: Mapping[str, str | None] | None) -> bool:
    """`_preserve_game_files` from the repository's `settings`."""
    name = _PRESERVE_GAME_FILES_CONFIG.casefold()
    if settings is None or name in settings:
        value = None if settings is None else _config_bool(settings[name])
        if value is None:
            raise GitWorkflowError("Invalid repository setting: " + _PRESERVE_GAME_FILES_CONFIG)
        return value
    # Repo-local settings do not travel with a clone. The original release
    # commit records this policy so later updates cannot silently normalize it.
    original = _run_git(repo, "log", "-1", "--format=%B", "refs/heads/original", check=False)
    if original.returncode == 0 and _PRESERVE_GAME_FILES_TRAILER in original.stdout.splitlines():
        return True
    # Adopting a pre-existing original records the policy on the translation
    # registration commit instead of rewriting that original's history.
    adopted = _run_git(repo, "log", "-1", "--format=%B", f"--grep=^{_PRESERVE_GAME_FILES_TRAILER}$", "HEAD", check=False)
    return adopted.returncode == 0 and _PRESERVE_GAME_FILES_TRAILER in adopted.stdout.splitlines()


def _ref_commits(repo: Path, *refs: str) -> dict[str, str]:
    """The commit of each branch in `refs` that has one, from one Git call."""
    result = _run_git(
        repo,
        "cat-file",
        "--batch-check=%(objectname)",
        input_text="".join(f"refs/heads/{ref}^{{commit}}\n" for ref in refs),
        check=False,
    )
    if result.returncode != 0:
        return {}
    lines = result.stdout.splitlines()
    if len(lines) != len(refs):
        raise GitWorkflowError("Git did not resolve every branch")
    # A name that resolves to no commit comes back as "<name> missing".
    return {ref: line for ref, line in zip(refs, lines) if " " not in line}


def _ref_commit(repo: Path, ref: str) -> str | None:
    return _ref_commits(repo, ref).get(ref)


def _validate_branch_name(repo: Path, branch: str, checked_out: str | None = None) -> str:
    """`branch`, refusing a name Git can't give a branch or the original
    branch's; `checked_out`, the branch HEAD is on, is one Git gave."""
    value = branch.strip()
    valid = value and (
        value == checked_out
        or _run_git(repo, "check-ref-format", "--branch", value, check=False).returncode == 0
    )
    if not valid:
        raise GitWorkflowError(f"The configured translated branch is invalid: {branch!r}")
    if value == ORIGINAL_BRANCH:
        raise GitWorkflowError("The original branch cannot also be the translated branch")
    return value


def _registered_translation_branch(
    repo: Path,
    settings: Mapping[str, str | None] | None = None,
    checked_out: str | None = None,
) -> str | None:
    """The translated branch the repository's `settings` register, read
    when not given; `checked_out` as for `_validate_branch_name`."""
    if settings is None:
        settings = _settings(repo) or {}
    configured = (settings.get(_TRANSLATION_BRANCH_CONFIG.casefold()) or "").strip()
    if configured:
        return _validate_branch_name(repo, configured, checked_out)
    return None


def _translation_branch(registered: str | None, commits: Mapping[str, str]) -> str | None:
    """The registered translated branch, or else the legacy one while
    `commits` (from _ref_commits) holds it."""
    if registered or _LEGACY_TRANSLATION_BRANCH not in commits:
        return registered
    return _LEGACY_TRANSLATION_BRANCH


def _configured_translation_branch(repo: Path) -> str | None:
    registered = _registered_translation_branch(repo)
    if registered:
        return registered
    return _translation_branch(None, _ref_commits(repo, _LEGACY_TRANSLATION_BRANCH))


def _set_translation_branch(repo: Path, branch: str) -> str:
    value = _validate_branch_name(repo, branch)
    _run_git(repo, "config", "--local", _TRANSLATION_BRANCH_CONFIG, value)
    return value


def _version_messages(repo: Path, ref: str) -> list[str]:
    """The messages of every commit on `ref` that records a version, newest
    first, from one Git call. Checkpoints record none, and a long run makes
    hundreds of them after the commit that does."""
    return _run_git(
        repo, "log", f"--grep=^{VERSION_TRAILER}:", "--format=%B%x00", ref
    ).stdout.split("\x00")


def _version_from_history(
    repo: Path, ref: str, commit: str | None, messages: list[str] | None = None
) -> str | None:
    """`messages` are _version_messages of `ref` when the caller has them."""
    if not commit:
        return None
    for message in _version_messages(repo, ref) if messages is None else messages:
        match = _VERSION_LINE.search(message)
        if match:
            return match.group(1).strip()

    tags = _run_git(repo, "tag", "--points-at", commit, check=False).stdout.splitlines()
    tagged = [tag.strip() for tag in tags if _VERSION_HINT.search(tag.strip())]
    if tagged:
        match = _VERSION_HINT.search(sorted(tagged)[-1])
        if match:
            return match.group(1)

    subject = _run_git(repo, "log", "-1", "--format=%s", ref).stdout.strip()
    match = _VERSION_HINT.search(subject)
    return match.group(1) if match else None


@dataclass(frozen=True)
class VersionRecord:
    version: str
    # When the version was recorded, as an ISO 8601 time.
    recorded: str
    # "setup" for the first version, "update" for each one after it.
    kind: str
    # "patch" or "complete" for updates that record it; "" before that.
    release: str
    commit: str


def version_history(game_root: str | Path) -> tuple[VersionRecord, ...]:
    """Every version the original branch recorded, newest first."""
    status = inspect_repository(Path(game_root).expanduser().resolve())
    if not status.repo_root or not status.original_commit:
        return ()
    log = _run_git(
        status.repo_root,
        "log",
        "--first-parent",
        "--format=%H%x00%cI%x00%B%x1e",
        ORIGINAL_BRANCH,
    ).stdout
    records = []
    for entry in log.split("\x1e"):
        parts = entry.strip("\n").split("\x00", 2)
        if len(parts) != 3:
            continue
        commit, recorded, message = parts
        subject = message.strip().splitlines()[0] if message.strip() else ""
        version = _VERSION_LINE.search(message)
        if not version:
            continue
        if subject.startswith("original: import clean game"):
            kind = "setup"
        elif subject.startswith("patch: "):
            kind = "update"
        else:
            # Metadata and normalization commits record no new version.
            continue
        release = re.search(rf"^{RELEASE_TRAILER}:\s*(patch|complete)\s*$", message, re.MULTILINE)
        records.append(
            VersionRecord(
                version.group(1).strip(),
                recorded,
                kind,
                release.group(1) if release else "",
                commit,
            )
        )
    return tuple(records)


def _applied_update_version(messages: list[str]) -> str | None:
    """Return the newest DazedTL patch version among a translated branch's
    _version_messages."""
    for message in messages:
        lines = message.strip().splitlines()
        if not lines or not lines[0].casefold().startswith("patch:"):
            continue
        match = _VERSION_LINE.search(message)
        if match:
            return match.group(1).strip()
    return None


class _Repository(NamedTuple):
    repo: Path
    # The selected folder's path in the repository.
    prefix: str
    # Repository-internal paths, as _git_paths resolves them, by name.
    paths: dict[str, Path]
    # The branch HEAD is on, None when it is detached or not asked for.
    branch: str | None = None


def game_prefix(repo: Path, selected: Path) -> str:
    """The path of the game folder `selected` in the repository at `repo`."""
    try:
        relative = selected.resolve().relative_to(repo)
    except ValueError as exc:
        raise GitWorkflowError("Selected game folder is outside its Git repository") from exc
    return "" if relative == Path(".") else relative.as_posix()


def _repository_for(selected: Path, *names: str, head: bool = False) -> _Repository | None:
    """The repository holding `selected` and the repository-internal paths
    `names`, with `head` the branch HEAD is on, from the same Git call; a
    branch with no commit yet takes a second."""
    arguments = [argument for name in names for argument in ("--git-path", name)]
    if head:
        # --verify -q fails a HEAD with no commit only once the rest is printed.
        arguments += ["--symbolic-full-name", "--verify", "-q", "HEAD"]
    result = _run_git(
        selected, "rev-parse", "--show-toplevel", "--path-format=absolute", *arguments, check=False
    )
    top, *lines = result.stdout.splitlines() or [""]
    unborn = head and result.returncode == 1 and len(lines) == len(names)
    if result.returncode != 0 and not unborn:
        return None
    symbolic = lines.pop() if head and not unborn else ""
    if len(lines) != len(names):
        raise GitWorkflowError("Git did not resolve every repository path")
    repo = Path(top.strip()).resolve()
    prefix = game_prefix(repo, selected)
    if unborn:
        symbolic = _run_git(repo, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    branch = symbolic.removeprefix("refs/heads/") if symbolic.startswith("refs/heads/") else None
    return _Repository(repo, prefix, dict(zip(names, map(Path, lines))), branch)


def _git_paths(repo: Path, *names: str) -> dict[str, Path]:
    """Resolve repository-internal paths with one Git call; each launch is costly on Windows."""
    arguments = [argument for name in names for argument in ("--git-path", name)]
    lines = _run_git(repo, "rev-parse", *arguments).stdout.splitlines()
    if len(lines) != len(names):
        raise GitWorkflowError("Git did not resolve every repository path")
    return {
        name: (path if path.is_absolute() else repo / path)
        for name, path in zip(names, map(Path, lines))
    }


def _cherry_pick_path(repo: Path) -> Path:
    return _git_paths(repo, "CHERRY_PICK_HEAD")["CHERRY_PICK_HEAD"]


def worktree_clean(repo: Path) -> bool:
    """Whether the working tree matches the index and HEAD, from one `git status`."""
    return not _run_git(repo, "status", "--porcelain=v1", "-z").stdout


def read_checkout(game_root: str | Path) -> Checkout | None:
    """What a write to the game at `game_root` needs of its repository, or
    None outside one. Each Git launch is costly on Windows, and the app reads
    this around every game write: it shares calls wherever one can answer
    more."""
    selected = Path(game_root).expanduser().resolve()
    found = (
        _repository_for(selected, *PENDING_OPERATIONS, "index", "config", head=True)
        if selected.is_dir()
        else None
    )
    if found is None:
        return None
    repo, prefix, paths, current_branch = found
    config_stat = _stat(paths["config"])
    settings = _settings(repo)
    registered = _registered_translation_branch(repo, settings or {}, current_branch)
    commits = _ref_commits(
        repo, ORIGINAL_BRANCH, registered or _LEGACY_TRANSLATION_BRANCH
    )
    translation_branch = _translation_branch(registered, commits)
    return Checkout(
        selected_root=selected,
        repo=repo,
        prefix=prefix,
        git_paths=paths,
        current_branch=current_branch,
        translation_branch=translation_branch,
        original_commit=commits.get(ORIGINAL_BRANCH),
        translation_commit=commits.get(translation_branch) if translation_branch else None,
        pending_operations=tuple(
            name for name in PENDING_OPERATIONS if paths[name].exists()
        ),
        asset_sync_pending=_asset_state_path(repo, prefix, "pending-assets").exists(),
        settings=settings,
        config_stat=config_stat,
    )


def inspect_repository(game_root: str | Path) -> RepositoryStatus:
    return read_repository(game_root)[0]


def read_repository(game_root: str | Path) -> tuple[RepositoryStatus, Checkout | None]:
    """The game's repository status, and the read of its checkout it was
    made from, which holds its settings too."""
    selected = Path(game_root).expanduser().resolve()
    if not selected.is_dir():
        return RepositoryStatus(
            selected, None, "", None, False, None, None, False, None, None, False, False
        ), None
    checkout = read_checkout(selected)
    if checkout is None:
        return RepositoryStatus(
            selected, None, "", None, False, None, None, False, None, None, True, False
        ), None
    repo, prefix = checkout.repo, checkout.prefix
    original_commit = checkout.original_commit
    translation_branch = checkout.translation_branch
    translation_commit = checkout.translation_commit
    original_version = _version_from_history(repo, ORIGINAL_BRANCH, original_commit)
    translation_ref = translation_branch or TRANSLATION_BRANCH
    translation_messages = (
        _version_messages(repo, translation_ref) if translation_commit else []
    )
    translation_version = _version_from_history(
        repo, translation_ref, translation_commit, translation_messages
    )
    asset_sync_pending = checkout.asset_sync_pending
    status = RepositoryStatus(
        selected_root=selected,
        repo_root=repo,
        game_prefix=prefix,
        current_branch=checkout.current_branch,
        original_exists=original_commit is not None,
        original_commit=original_commit,
        original_version=original_version,
        translation_exists=translation_commit is not None,
        translation_commit=translation_commit,
        translation_version=translation_version,
        worktree_clean=worktree_clean(repo),
        pending_cherry_pick="CHERRY_PICK_HEAD" in checkout.pending_operations,
        asset_sync_pending=asset_sync_pending,
        asset_manifest_available=_asset_state_path(
            repo, prefix, "official-assets"
        ).exists(),
        asset_baseline_repair_needed=_asset_manifest_needs_repair(repo, prefix),
        translation_branch=translation_branch,
        applied_update_version=_applied_update_version(translation_messages),
        asset_update_applied=asset_sync_pending
        and translation_version == original_version,
        pending_operations=checkout.pending_operations,
    )
    return status, checkout


def _validate_version(version: str) -> str:
    value = version.strip()
    if not value:
        raise GitWorkflowError("A version label is required")
    if "\n" in value or "\r" in value:
        raise GitWorkflowError("Version labels must fit on one line")
    return value


def _validate_source(source: str | Path, destination: Path) -> Path:
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise GitWorkflowError(f"Official game folder not found: {root}")
    # Same-folder bootstrap is allowed: Prepare uses the pre-translation Project
    # game as both the original baseline and the starting translated branch.
    if root != destination and (
        destination in root.parents or root in destination.parents
    ):
        raise GitWorkflowError(
            "Official and translated game folders cannot be nested"
        )
    return root


def _prepare_worktree_formatting(
    source: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Normalize JSON/text on disk before any Git init or baseline commit."""
    files = _source_files(source, format_json=True)
    _materialize_normalized_text(files)
    formatted = tuple(
        entry.relative for entry in files if entry.normalized_text is not None
    )
    warnings = tuple(entry.json_warning for entry in files if entry.json_warning)
    return formatted, warnings


def _normalize_newlines(text: str) -> str:
    """Force LF line endings so CRLF/CR noise cannot create false conflicts."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode_utf8_text(raw: bytes) -> str | None:
    """Decode UTF-8 text while preserving CR characters.

    ``Path.read_text()`` uses universal newlines and silently converts CRLF to
    LF, which made already-pretty JSON look unchanged and left CRLF blobs in
    Git. Decode from bytes instead so EOL differences are visible to
    normalization.
    """
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _canonical_json(source_text: str) -> str:
    duplicate_keys: set[str] = set()

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                duplicate_keys.add(key)
            result[key] = value
        return result

    def reject_constant(value: str):
        raise ValueError(f"non-standard numeric constant {value}")

    document = json.loads(
        source_text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    if duplicate_keys:
        names = ", ".join(sorted(duplicate_keys)[:5])
        raise ValueError(f"duplicate object key(s): {names}")
    canonical = json.dumps(document, indent=4, ensure_ascii=False, allow_nan=False)
    canonical.encode("utf-8")
    return _normalize_newlines(canonical)


def _canonical_plugins_js(source_text: str) -> str | None:
    """Use the same RPG Maker plugins.js formatting as the Prepare workflow."""
    if not re.search(r"\bvar\s+\$plugins\s*=", source_text):
        return None
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    return _normalize_newlines(jsbeautifier.beautify(source_text, options))


def _source_files(source: Path, *, format_json: bool) -> list[_SourceFile]:
    files: list[_SourceFile] = []
    for candidate in sorted(source.rglob("*"), key=lambda path: path.as_posix()):
        relative = candidate.relative_to(source)
        if relative.parts and relative.parts[0] == ".git":
            continue
        # DazedTL keeps only its glossary, settings and skill notes in Git;
        # its work, backups and tool environments there are never tracked.
        if relative.parts[:1] == (".dazedtl",) and not is_portable_game_file(
            relative.as_posix()
        ):
            continue
        if candidate.is_symlink():
            raise GitWorkflowError(
                f"Symbolic links are not supported in game trees: {relative.as_posix()}"
            )
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise GitWorkflowError(
                f"Unsupported filesystem entry in game tree: {relative.as_posix()}"
            )
        rel_text = relative.as_posix()
        if any(character in rel_text for character in ("\n", "\r", "\t")):
            raise GitWorkflowError(f"Unsupported control character in path: {rel_text!r}")
        executable_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        mode = "100755" if candidate.stat().st_mode & executable_bits else "100644"
        normalized_text = None
        warning = None
        # Native engine archives can be gigabytes. Raw tree collection only
        # needs paths/modes; Git and the asset hasher stream the bytes later.
        source_text = _decode_utf8_text(candidate.read_bytes()) if format_json else None
        if format_json and candidate.suffix.casefold() == ".json":
            if source_text is None:
                warning = f"{rel_text}: JSON formatting skipped (not valid UTF-8 text)"
            else:
                try:
                    canonical = _canonical_json(source_text)
                    if canonical != source_text:
                        normalized_text = canonical
                except Exception as exc:  # formatting is optional; preserve source bytes
                    warning = f"{rel_text}: JSON formatting skipped ({exc})"
        elif format_json and candidate.name.casefold() == "plugins.js":
            if source_text is None:
                warning = f"{rel_text}: plugins.js formatting skipped (not valid UTF-8 text)"
            else:
                try:
                    canonical = _canonical_plugins_js(source_text)
                    if canonical is not None and canonical != source_text:
                        normalized_text = canonical
                except Exception as exc:  # preserve source bytes and warn visibly
                    warning = f"{rel_text}: plugins.js formatting skipped ({exc})"
        elif (
            format_json
            and source_text is not None
            and candidate.suffix.casefold() not in _CRLF_SENSITIVE_EXTENSIONS
        ):
            canonical = _normalize_newlines(source_text)
            if canonical != source_text:
                normalized_text = canonical
        files.append(_SourceFile(candidate, rel_text, mode, normalized_text, warning))
    return files


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_entries(files: Iterable[_SourceFile]) -> dict[str, _AssetManifestEntry]:
    """Each asset's hash, size and mode, several files at once: a game holds
    thousands of assets, and one at a time each waits on the disk."""
    files = list(files)

    def entry(source: _SourceFile) -> _AssetManifestEntry:
        return _AssetManifestEntry(
            _hash_file(source.path), source.path.stat().st_size, source.mode
        )

    with ThreadPoolExecutor(8) as pool:
        return {
            source.relative: value
            for source, value in zip(files, pool.map(entry, files))
        }


@functools.lru_cache(maxsize=64)
def _git_common_dir(repo: Path) -> Path:
    """The common directory is a fixed property of a repository root; status checks ask for it repeatedly."""
    common_text = _run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common = Path(common_text)
    if not common.is_absolute():
        common = repo / common
    return common.resolve()


def _asset_state_path(repo: Path, game_prefix: str, name: str) -> Path:
    key = hashlib.sha256(game_prefix.encode("utf-8")).hexdigest()[:16]
    return _git_common_dir(repo) / "dazedtl" / "version-update" / f"{key}-{name}.json"


def _manifest_payload(
    manifest: Mapping[str, _AssetManifestEntry],
) -> dict[str, dict[str, str | int]]:
    return {
        path: {"sha256": entry.sha256, "size": entry.size, "mode": entry.mode}
        for path, entry in sorted(manifest.items())
    }


def _manifest_digest(manifest: Mapping[str, _AssetManifestEntry]) -> str:
    encoded = json.dumps(
        _manifest_payload(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
        system.replace(temporary_name, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        system.unlink(temporary_name, ignore_errors=True)
        raise


def _validate_manifest_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise GitWorkflowError(f"Asset manifest contains an unsafe path: {path!r}")
    if any(character in path for character in ("\n", "\r", "\t")):
        raise GitWorkflowError(f"Asset manifest contains an unsafe path: {path!r}")


def _load_asset_manifest(
    repo: Path, game_prefix: str
) -> dict[str, _AssetManifestEntry] | None:
    path = _asset_state_path(repo, game_prefix, "official-assets")
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("format") != _ASSET_MANIFEST_FORMAT:
            raise ValueError("unsupported format")
        raw_files = document["files"]
        if not isinstance(raw_files, dict):
            raise ValueError("files must be an object")
        manifest = {}
        for relative, raw in raw_files.items():
            if not isinstance(relative, str) or not isinstance(raw, dict):
                raise ValueError("invalid file entry")
            _validate_manifest_path(relative)
            sha256 = raw.get("sha256")
            size = raw.get("size")
            mode = raw.get("mode")
            if (
                not isinstance(sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or not isinstance(size, int)
                or size < 0
                or mode not in {"100644", "100755"}
            ):
                raise ValueError(f"invalid metadata for {relative}")
            manifest[relative] = _AssetManifestEntry(sha256, size, mode)
        return manifest
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise GitWorkflowError(f"Official asset manifest is invalid: {path}") from exc


def _load_asset_manifest_metadata(
    repo: Path, game_prefix: str
) -> dict[str, object]:
    path = _asset_state_path(repo, game_prefix, "official-assets")
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("format") != _ASSET_MANIFEST_FORMAT:
            return {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}

    metadata = {}
    source_kind = document.get("baseline_source_kind")
    if isinstance(source_kind, str) and source_kind:
        metadata["baseline_source_kind"] = source_kind
    has_unbased = document.get("has_unbased_tracked_assets")
    if isinstance(has_unbased, bool):
        metadata["has_unbased_tracked_assets"] = has_unbased
    return metadata


def _asset_manifest_needs_repair(repo: Path, game_prefix: str) -> bool:
    metadata = _load_asset_manifest_metadata(repo, game_prefix)
    return bool(
        metadata.get("baseline_source_kind") == _ASSET_BASELINE_SOURCE_CURRENT_GAME
        and metadata.get("has_unbased_tracked_assets") is True
    )


def _save_asset_manifest(
    repo: Path,
    game_prefix: str,
    version: str,
    original_commit: str,
    manifest: Mapping[str, _AssetManifestEntry],
    *,
    baseline_source_kind: str | None = None,
    has_unbased_tracked_assets: bool | None = None,
) -> None:
    document = {
        "format": _ASSET_MANIFEST_FORMAT,
        "version": version,
        "original_commit": original_commit,
        "files": _manifest_payload(manifest),
    }
    if baseline_source_kind is not None:
        document["baseline_source_kind"] = baseline_source_kind
    if has_unbased_tracked_assets is not None:
        document["has_unbased_tracked_assets"] = has_unbased_tracked_assets
    _write_json_atomic(
        _asset_state_path(repo, game_prefix, "official-assets"),
        document,
    )


def _save_pending_asset_plan(
    repo: Path,
    game_prefix: str,
    source: Path,
    version: str,
    original_commit: str,
    manifest_digest: str,
    *,
    preserved_translation_assets: tuple[str, ...] = (),
    patch_overlay: bool = False,
) -> None:
    _write_json_atomic(
        _asset_state_path(repo, game_prefix, "pending-assets"),
        {
            "format": _ASSET_MANIFEST_FORMAT,
            "source": str(source),
            "version": version,
            "original_commit": original_commit,
            "manifest_digest": manifest_digest,
            "preserved_translation_assets": tuple(preserved_translation_assets),
            "patch_overlay": patch_overlay,
        },
    )


def _load_pending_asset_plan(
    repo: Path, game_prefix: str
) -> dict[str, object] | None:
    path = _asset_state_path(repo, game_prefix, "pending-assets")
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        required = ("source", "version", "original_commit", "manifest_digest")
        if document.get("format") != _ASSET_MANIFEST_FORMAT or any(
            not isinstance(document.get(key), str) or not document[key]
            for key in required
        ):
            raise ValueError("invalid pending asset plan")
        if not re.fullmatch(r"[0-9a-f]{64}", document["manifest_digest"]):
            raise ValueError("invalid manifest digest")
        preserved_translation_assets = document.get("preserved_translation_assets", ())
        if any(
            not isinstance(path, str) or not path
            for path in preserved_translation_assets
        ):
            raise ValueError("invalid preserved translation assets")
        if not isinstance(preserved_translation_assets, list):
            raise ValueError("invalid preserved translation assets")
        patch_overlay = document.get("patch_overlay", False)
        if not isinstance(patch_overlay, bool):
            raise ValueError("invalid patch overlay setting")
        return {
            **{key: document[key] for key in required},
            "preserved_translation_assets": tuple(preserved_translation_assets),
            "patch_overlay": patch_overlay,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise GitWorkflowError(f"Pending asset update is invalid: {path}") from exc


def _clear_pending_asset_plan(repo: Path, game_prefix: str) -> None:
    system.unlink(_asset_state_path(repo, game_prefix, "pending-assets"), missing_ok=True)


def _cancel_pending_update(
    repo: Path, game_prefix: str, moved: str, previous: str
) -> None:
    """Put the original branch back from an update that never reached the
    translation, and drop the assets it left to copy."""
    if _ref_commit(repo, ORIGINAL_BRANCH) == moved:
        _run_git(
            repo, "update-ref", f"refs/heads/{ORIGINAL_BRANCH}", previous, moved
        )
    _clear_pending_asset_plan(repo, game_prefix)


def _ensure_local_excludes(repo: Path) -> None:
    """Keep removed legacy updater metadata out of the exact game branches."""
    exclude = _git_common_dir(repo) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text("utf-8", errors="replace") if exclude.exists() else ""
    rule = ".dazedtl/version_update/"
    if rule not in {line.strip() for line in existing.splitlines()}:
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{rule}\n")


def _install_game_gitignore(game_root: Path, *, preserve_game_files: bool = False) -> bool:
    """Keep the portable DazedTL settings rules in the game's .gitignore, and
    those settings out of the archives players download.

    Projects that preserve game files also get attributes that keep native
    payload bytes exact across clones. Project rules are never replaced.
    """
    attributes = game_root / ".gitattributes"
    if attributes.is_symlink() or (attributes.exists() and not attributes.is_file()):
        raise GitWorkflowError("The game .gitattributes must be a regular file")
    if attributes.exists():
        existing = attributes.read_bytes().decode("utf-8", errors="surrogateescape")
    elif preserve_game_files:
        # This travels with clones; repo-local core.autocrlf alone does not.
        existing = "# Preserve native game payload bytes across platforms.\n* -text\n"
    else:
        existing = ""
    updated = game_tool_gitattributes_text(existing)
    if not attributes.exists() or updated != existing:
        attributes.write_bytes(updated.encode("utf-8", errors="surrogateescape"))
    return ensure_game_tool_gitignore(game_root, baseline=True)


def _reject_original_checked_out_elsewhere(repo: Path) -> None:
    listing = _run_git(repo, "worktree", "list", "--porcelain").stdout
    for block in listing.strip().split("\n\n"):
        fields = dict(
            line.split(" ", 1)
            for line in block.splitlines()
            if " " in line
        )
        if fields.get("branch") == f"refs/heads/{ORIGINAL_BRANCH}":
            raise GitWorkflowError(
                "The original branch is checked out in another Git worktree. "
                "Close or switch that worktree before updating it."
            )


def _temporary_index() -> tuple[str, dict[str, str]]:
    descriptor, name = tempfile.mkstemp(prefix="dazedtl-git-index-")
    os.close(descriptor)
    system.unlink(name)
    return name, {"GIT_INDEX_FILE": name}


def _prefixed(prefix: str, relative: str) -> str:
    return f"{prefix}/{relative}" if prefix else relative


def _ignored_paths(
    repo: Path, files: list[_SourceFile], game_prefix: str
) -> set[str]:
    if not files:
        return set()
    virtual_paths = [_prefixed(game_prefix, entry.relative) for entry in files]
    result = _run_git(
        repo,
        "check-ignore",
        "--no-index",
        "-z",
        "--stdin",
        check=False,
        input_text="\x00".join(virtual_paths) + "\x00",
    )
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitWorkflowError(detail or "Could not evaluate Git ignore rules")
    ignored_virtual = {path for path in result.stdout.split("\x00") if path}
    return {
        entry.relative
        for entry, virtual in zip(files, virtual_paths)
        if virtual in ignored_virtual
    }


def _build_ignored_asset_manifest(
    source: Path, ignored_paths: Iterable[str]
) -> dict[str, _AssetManifestEntry]:
    ignored = set(ignored_paths)
    return _asset_entries(
        entry
        for entry in _source_files(source, format_json=False)
        if entry.relative in ignored
        and not _is_local_only_asset(entry.relative)
        and not _is_tool_owned_path(entry.relative)
    )


def _proposed_asset_manifest(
    source: Path,
    ignored_paths: Iterable[str],
    baseline: Mapping[str, _AssetManifestEntry] | None,
    *,
    patch_overlay: bool,
) -> dict[str, _AssetManifestEntry]:
    """Build the next asset manifest from a release folder or copy-over patch."""
    supplied = _build_ignored_asset_manifest(source, ignored_paths)
    if not patch_overlay:
        return supplied
    proposed = dict(baseline or {})
    proposed.update(supplied)
    return proposed


def _asset_manifest_for_source(
    repo: Path, source: Path, game_prefix: str
) -> dict[str, _AssetManifestEntry]:
    files = _source_files(source, format_json=False)
    ignored = _ignored_paths(repo, files, game_prefix)
    return _asset_entries(
        entry
        for entry in files
        if entry.relative in ignored
        and not _is_local_only_asset(entry.relative)
        and not _is_tool_owned_path(entry.relative)
    )


def _validate_official_asset_baseline(
    repo: Path,
    game: Path,
    source_value: str | Path,
    game_prefix: str,
    original_commit: str,
) -> tuple[Path, dict[str, _AssetManifestEntry], str]:
    source = _validate_source(source_value, game)
    build = _write_tree_from_folder(
        repo,
        source,
        game_prefix=game_prefix,
        base_commit=original_commit,
    )
    build = _preserve_tool_owned_paths(
        repo, build, original_commit, game_prefix
    )
    differences = _diff_status(repo, original_commit, build.tree, game_prefix)
    differences.pop(_prefixed(game_prefix, ".gitignore"), None)
    significant = {
        path: change
        for path, change in differences.items()
        if not _is_legacy_baseline_migration(path, change, game_prefix)
    }
    if significant:
        examples = ", ".join(
            f"{change} {_display_path(path, game_prefix)}"
            for path, change in sorted(significant.items())[:5]
        )
        if len(significant) > 5:
            examples += f", and {len(significant) - 5} more"
        raise GitWorkflowError(
            "The previous official folder does not match the registered original "
            "branch. Select the clean game folder for the currently registered version. "
            f"Mismatched tracked game files: {examples}."
        )
    return (
        source,
        _build_ignored_asset_manifest(source, build.ignored_paths),
        build.tree,
    )


def _is_legacy_baseline_migration(
    path: str, change: str, game_prefix: str
) -> bool:
    """Identify differences caused by old updater and ignore-rule layouts.

    Older projects sometimes committed the GameUpdate bundle on ``original``
    and added selected translated binary paths only after that branch was
    created.  A clean baseline legitimately removes the former and introduces
    pristine copies for the latter.  Modified or removed game assets are never
    accepted here because they can indicate a different official version.
    """
    relative = _display_path(path, game_prefix)
    if _is_tool_owned_path(relative):
        return True
    return change == "A" and _asset_category(relative) != "Other asset"


def _is_tool_owned_path(relative: str) -> bool:
    pure = PurePosixPath(relative)
    lowered = tuple(part.casefold() for part in pure.parts)
    return bool(
        (
            len(lowered) == 1
            and lowered[0] in _TOOL_OWNED_ROOT_FILES
        )
        or (
            lowered
            and lowered[0] in _TOOL_RESOURCE_DIRECTORIES
        )
    )


def _is_local_only_asset(path: str) -> bool:
    pure = PurePosixPath(path)
    lowered_parts = tuple(part.casefold() for part in pure.parts)
    if lowered_parts and lowered_parts[0] in _TOOL_RESOURCE_DIRECTORIES:
        return True
    if any(part in _LOCAL_ONLY_DIRECTORIES for part in lowered_parts[:-1]):
        return True
    if lowered_parts[:2] == ("wolf_json", "originals"):
        return True
    name = lowered_parts[-1]
    return bool(
        name in _LOCAL_ONLY_FILENAMES
        or name in {".env", ".api_key", "api_keys.json"}
        or name.startswith(".env.")
        or name.endswith(("_key.txt", "_keys.txt"))
        or name.startswith("save")
        or name.startswith("bsxscript_")
        or Path(name).suffix in _NON_GAME_RESOURCE_EXTENSIONS | {".log", ".tmp"}
    )


def _asset_category(path: str) -> str:
    extension = Path(path).suffix.casefold()
    if extension in _IMAGE_EXTENSIONS:
        return "Image"
    if extension in _AUDIO_EXTENSIONS:
        return "Audio"
    if extension in _VIDEO_EXTENSIONS:
        return "Video"
    if extension in _FONT_EXTENSIONS:
        return "Font"
    return "Other asset"


def _destination_matches(game: Path, path: str, entry: _AssetManifestEntry) -> bool:
    destination = game.joinpath(*PurePosixPath(path).parts)
    if destination.is_symlink():
        raise GitWorkflowError(f"Asset destination is a symbolic link: {path}")
    if not destination.exists():
        return False
    if not destination.is_file():
        raise GitWorkflowError(f"Asset destination is not a regular file: {path}")
    return destination.stat().st_size == entry.size and _hash_file(destination) == entry.sha256


def _external_asset_changes(
    game: Path,
    baseline: Mapping[str, _AssetManifestEntry] | None,
    proposed: Mapping[str, _AssetManifestEntry],
) -> tuple[UpdateExternalChange, ...]:
    changes = []
    if baseline is None:
        candidates = proposed.keys()
    else:
        candidates = {
            path
            for path in set(baseline) | set(proposed)
            if baseline.get(path) != proposed.get(path)
        }
    for path in sorted(candidates):
        _validate_manifest_path(path)
        old = baseline.get(path) if baseline is not None else None
        new = proposed.get(path)
        if new is None:
            change = "Removed"
            destination = game.joinpath(*PurePosixPath(path).parts)
            if destination.is_symlink():
                raise GitWorkflowError(f"Asset destination is a symbolic link: {path}")
            already_present = not destination.exists()
            size = old.size if old else 0
            result = (
                "Already absent; no removal needed"
                if already_present
                else "Will be removed outside Git"
            )
        else:
            already_present = _destination_matches(game, path, new)
            destination_exists = game.joinpath(*PurePosixPath(path).parts).exists()
            change = "Added" if old is None and not destination_exists else "Replaced"
            size = new.size
            result = (
                "Already present; no copy needed"
                if already_present
                else "Will be copied outside Git"
            )
            if baseline is None and already_present:
                continue
        changes.append(
            UpdateExternalChange(
                path=path,
                change=change,
                category=_asset_category(path),
                already_present=already_present,
                size_bytes=size,
                result=result,
            )
        )
    return tuple(changes)


def _asset_destination(game: Path, relative: str) -> Path:
    _validate_manifest_path(relative)
    pure = PurePosixPath(relative)
    current = game
    for part in pure.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GitWorkflowError(f"Asset destination crosses a symbolic link: {relative}")
        if current.exists() and not current.is_dir():
            raise GitWorkflowError(f"Asset destination parent is not a directory: {relative}")
    destination = game.joinpath(*pure.parts)
    if destination.is_symlink():
        raise GitWorkflowError(f"Asset destination is a symbolic link: {relative}")
    if destination.exists() and not destination.is_file():
        raise GitWorkflowError(f"Asset destination is not a regular file: {relative}")
    return destination


def _sync_external_assets(
    repo: Path,
    game: Path,
    source: Path,
    changes: tuple[UpdateExternalChange, ...],
    proposed: Mapping[str, _AssetManifestEntry],
) -> tuple[UpdateExternalChange, ...]:
    pending = tuple(change for change in changes if not change.already_present)
    if not pending:
        return ()
    state_dir = _asset_state_path(repo, "", "sync-stage").parent
    state_dir.mkdir(parents=True, exist_ok=True)
    with staging_folder(state_dir, "asset-sync-") as stage_root:
        staged: dict[str, Path] = {}
        backups: dict[str, Path | None] = {}
        destinations = {}
        for index, change in enumerate(pending):
            destination = _asset_destination(game, change.path)
            destinations[change.path] = destination
            if destination.exists():
                backup = stage_root / f"backup-{index}"
                shutil.copy2(destination, backup)
                backups[change.path] = backup
            else:
                backups[change.path] = None
            if change.change != "Removed":
                source_path = source.joinpath(*PurePosixPath(change.path).parts)
                if source_path.is_symlink() or not source_path.is_file():
                    raise GitWorkflowError(
                        f"Official asset is no longer a regular file: {change.path}"
                    )
                expected = proposed.get(change.path)
                if expected is None or not (
                    source_path.stat().st_size == expected.size
                    and _hash_file(source_path) == expected.sha256
                ):
                    raise GitWorkflowError(
                        f"Official asset changed during synchronization: {change.path}"
                    )
                staged_path = stage_root / f"new-{index}"
                shutil.copy2(source_path, staged_path)
                if not (
                    staged_path.stat().st_size == expected.size
                    and _hash_file(staged_path) == expected.sha256
                ):
                    raise GitWorkflowError(
                        f"Official asset could not be staged exactly: {change.path}"
                    )
                staged[change.path] = staged_path

        applied: list[str] = []
        try:
            for change in pending:
                destination = destinations[change.path]
                if change.change == "Removed":
                    if destination.exists():
                        system.unlink(destination)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    system.replace(staged[change.path], destination)
                applied.append(change.path)
        except Exception as exc:
            rollback_errors = []
            for relative in reversed(applied):
                destination = destinations[relative]
                backup = backups[relative]
                try:
                    if backup is None:
                        if destination.exists():
                            system.unlink(destination)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, destination)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{relative}: {rollback_exc}")
            detail = f"Could not synchronize official game assets: {exc}"
            if rollback_errors:
                detail += ". Rollback also failed for " + ", ".join(rollback_errors)
            raise GitWorkflowError(detail) from exc
    return pending


def _materialize_normalized_text(files: list[_SourceFile]) -> None:
    for entry in files:
        if entry.normalized_text is None:
            continue
        original_mode = entry.path.stat().st_mode
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{entry.path.name}.dazedformat-", dir=entry.path.parent
        )
        try:
            # Write bytes so platform text-mode newline translation cannot
            # reintroduce CRLF after we normalized to LF.
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(entry.normalized_text.encode("utf-8"))
            os.chmod(temporary_name, stat.S_IMODE(original_mode))
            system.replace(temporary_name, entry.path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            system.unlink(temporary_name, ignore_errors=True)
            raise


def _write_tree_from_folder(
    repo: Path,
    source: Path,
    *,
    game_prefix: str,
    base_commit: str | None,
    format_json: bool = True,
    materialize_json: bool = False,
    replace_game_tree: bool = True,
    include_tool_state: bool = True,
) -> _TreeBuild:
    preserve_native = _preserve_game_files(repo)
    discovered_files = _source_files(source, format_json=format_json and not preserve_native)
    if not include_tool_state:
        discovered_files = [entry for entry in discovered_files if not entry.relative.startswith(".dazedtl/")]
    for filename in ((".gitignore", ".gitattributes") if preserve_native else (".gitignore",)):
        managed = repo.joinpath(game_prefix, filename)
        if managed.is_file():
            discovered_files = [entry for entry in discovered_files if entry.relative != filename]
            discovered_files.append(_SourceFile(managed, filename, "100644"))
    discovered_files.sort(key=lambda entry: entry.relative)
    ignored = _ignored_paths(repo, discovered_files, game_prefix)
    files = [entry for entry in discovered_files if entry.relative not in ignored]
    if materialize_json:
        _materialize_normalized_text(files)
    index_name, index_env = _temporary_index()
    try:
        if base_commit:
            _run_git(repo, "read-tree", base_commit, env=index_env)
        else:
            _run_git(repo, "read-tree", "--empty", env=index_env)

        removals = []
        if replace_game_tree:
            existing = _run_git(repo, "ls-files", "-z", env=index_env).stdout.split("\x00")
            prefix_marker = f"{game_prefix}/" if game_prefix else ""
            removals = [
                path
                for path in existing
                if path
                and (
                    not game_prefix
                    or path == game_prefix
                    or path.startswith(prefix_marker)
                )
            ]
        index_lines = [f"0 {_ZERO_OID}\t{path}" for path in removals]

        raw_files = [entry for entry in files if entry.normalized_text is None]
        raw_hashes: dict[str, str] = {}
        if raw_files:
            absolute_paths = "\n".join(str(entry.path) for entry in raw_files) + "\n"
            hashes = _run_git(
                repo,
                "hash-object",
                "-w",
                "--no-filters",
                "--stdin-paths",
                input_text=absolute_paths,
                timeout=600,
            ).stdout.splitlines()
            if len(hashes) != len(raw_files):
                raise GitWorkflowError("Git did not hash every file in the selected game")
            raw_hashes = {
                entry.relative: blob for entry, blob in zip(raw_files, hashes)
            }
        for entry in files:
            if entry.normalized_text is None:
                blob = raw_hashes[entry.relative]
            else:
                blob = _run_git(
                    repo,
                    "hash-object",
                    "-w",
                    "--no-filters",
                    "--stdin",
                    input_text=entry.normalized_text,
                ).stdout.strip()
            index_lines.append(
                f"{entry.mode} {blob}\t{_prefixed(game_prefix, entry.relative)}"
            )

        if index_lines:
            _run_git(
                repo,
                "update-index",
                "--index-info",
                input_text="\n".join(index_lines) + "\n",
                env=index_env,
                timeout=600,
            )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        warnings = [
            entry.json_warning for entry in files if entry.json_warning is not None
        ]
        if not any(entry.path.name == ".gitignore" for entry in discovered_files):
            warnings.append(
                "No .gitignore was found in the selected game folder. Files not "
                "covered by repository or global exclude rules will be committed."
            )
        return _TreeBuild(
            tree=tree,
            formatted_json_paths=tuple(
                entry.relative for entry in files if entry.normalized_text is not None
            ),
            json_warnings=tuple(warnings),
            ignored_paths=tuple(sorted(ignored)),
        )
    finally:
        system.unlink(index_name, ignore_errors=True)


def _with_trailer(message: str, trailer: str) -> str:
    """The message with `trailer` in its trailer block, the last paragraph
    when it holds only `Key: value` lines, which Git reads as trailers."""
    body = message.rstrip()
    _, separator, last = body.rpartition("\n\n")
    joined = separator and all(re.match(r"[A-Za-z0-9-]+: ", line) for line in last.splitlines())
    return body + ("\n" if joined else "\n\n") + trailer


def _commit_tree(
    repo: Path,
    tree: str,
    message: str,
    parents: Iterable[str] = (),
) -> str:
    if _preserve_game_files(repo) and _PRESERVE_GAME_FILES_TRAILER not in message.splitlines():
        message = _with_trailer(message, _PRESERVE_GAME_FILES_TRAILER)
    args = [
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "commit-tree",
        tree,
    ]
    for parent in parents:
        args.extend(["-p", parent])
    args.extend(["-m", message])
    return _run_git(repo, *args).stdout.strip()


def _message(subject: str, version: str) -> str:
    return f"{subject}\n\n{VERSION_TRAILER}: {version}"


def _ensure_translation_branch(repo: Path, head: str, branch: str) -> None:
    translation = _ref_commit(repo, branch)
    current = _run_git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    current_name = current.stdout.strip()
    if translation and current_name != branch:
        raise GitWorkflowError(
            f"The translated branch {branch!r} exists but is not checked out. Switch to it first."
        )
    if not translation:
        _run_git(repo, "update-ref", f"refs/heads/{branch}", head)
        _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")


def unfinished_bootstrap(game_root: str | Path) -> bool:
    """Whether the game's repository holds only a baseline DazedTL began and never registered.

    A fresh bootstrap registers its translated branch last. Until then the
    repository holds no commits, or only DazedTL's original import with its
    translated start on top, and an index that is missing or equal to that
    start. Anything more, such as another ref, a remote or a staged change,
    can be someone's work, so that repository is not recognized.
    """
    found = _repository_for(Path(game_root).expanduser().resolve())
    if found is None or found.prefix or _configured_translation_branch(found.repo) is not None:
        return False
    repo = found.repo
    head = _run_git(repo, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    remotes = _run_git(repo, "config", "--local", "--get-regexp", r"^remote\.", check=False).stdout
    if head != f"refs/heads/{TRANSLATION_BRANCH}" or remotes.strip():
        return False
    listed = _run_git(repo, "for-each-ref", "--format=%(refname)%00%(objectname)").stdout
    # DazedTL's private refs, such as the record of the original game's files
    # the game-write gateway makes before the first write, are not branches.
    refs = {
        name: value
        for name, value in (line.split("\x00") for line in listed.splitlines())
        if not name.startswith(_PRIVATE_REFS)
    }
    original = refs.pop(f"refs/heads/{ORIGINAL_BRANCH}", None)
    translation = refs.pop(f"refs/heads/{TRANSLATION_BRANCH}", None)
    if refs or (translation and not original):
        return False
    tool = f"{_TOOL_NAME} <{_TOOL_EMAIL}>"
    for commit, parents, subjects in (
        (original, "", ("original: import clean game ",)),
        (translation, original, ("translation: start from original game ", "translation: record translated game ")),
    ):
        if not commit:
            continue
        fields = _run_git(repo, "log", "-1", "--format=%P%x00%an <%ae>%x00%cn <%ce>%x00%B", commit).stdout
        found_parents, author, committer, message = fields.split("\x00", 3)
        if (found_parents.strip(), author, committer) != (parents, tool, tool) or not (
            message.startswith(subjects) and _VERSION_LINE.search(message)
        ):
            return False
    if not _git_paths(repo, "index")["index"].exists():
        return True
    # Bootstrap writes the index only from its translated start.
    return bool(translation) and not _run_git(
        repo, "diff-index", "--cached", "--quiet", translation, check=False
    ).returncode


def bootstrap_repository(
    translated_game: str | Path,
    original_game: str | Path,
    version: str,
    *,
    preserve_game_files: bool = False,
) -> BootstrapResult:
    """Record official/translated baselines; optionally preserve native game bytes.

    The preservation setting is repository-local and also applies to later
    registration, update previews and official updates. Existing Workflow callers
    retain their normalized text.
    """
    translated = Path(translated_game).expanduser().resolve()
    if not translated.is_dir():
        raise GitWorkflowError(f"Translated game folder not found: {translated}")
    version = _validate_version(version)
    original = _validate_source(original_game, translated)
    found = _repository_for(translated)
    # A baseline that stopped before registering its branch is made again in
    # the same repository; the earlier attempt's commits stay in the reflog.
    restart = found is not None and unfinished_bootstrap(translated)
    if found is not None:
        preserve_game_files = preserve_game_files or _preserve_game_files(found.repo)

    if found is None or restart:
        if found is None and translated.joinpath(".git").exists():
            raise GitWorkflowError("The selected folder contains unusable Git metadata")
        # Format and validate on disk before creating any repository state.
        # The clean official folder is left untouched when it is a separate path;
        # same-folder Prepare bootstrap normalizes the single selected game once.
        if preserve_game_files:
            _source_files(original, format_json=False)
            if original != translated:
                _source_files(translated, format_json=False)
            preformatted, prewarnings = (), ()
        elif original == translated:
            preformatted, prewarnings = _prepare_worktree_formatting(translated)
        else:
            _source_files(original, format_json=True)
            preformatted, prewarnings = _prepare_worktree_formatting(translated)
        gitignore_installed = _install_game_gitignore(translated, preserve_game_files=preserve_game_files)
        if found is None:
            _run_git(translated, "init", "-b", TRANSLATION_BRANCH)
        repo, prefix = translated, ""
        translation_branch = TRANSLATION_BRANCH
        _configure_exact_tree_repo(repo)
        if preserve_game_files:
            _run_git(repo, "config", "--local", _PRESERVE_GAME_FILES_CONFIG, "true")
        _ensure_local_excludes(repo)
        original_tree = _write_tree_from_folder(
            repo, original, game_prefix=prefix, base_commit=None,
            include_tool_state=not preserve_game_files,
        )
        original_commit = _commit_tree(
            repo,
            original_tree.tree,
            _message(f"original: import clean game {version}", version),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
        )
        translation_tree = _write_tree_from_folder(
            repo,
            translated,
            game_prefix=prefix,
            base_commit=original_commit,
            format_json=True,
            materialize_json=False,
        )
        translation_commit = _commit_tree(
            repo,
            translation_tree.tree,
            _message(
                f"translation: start from original game {version}"
                if original == translated
                else f"translation: record translated game {version}",
                version,
            ),
            (original_commit,),
        )
        translation_tree = _TreeBuild(
            translation_tree.tree,
            tuple(dict.fromkeys((*preformatted, *translation_tree.formatted_json_paths))),
            tuple(dict.fromkeys((*prewarnings, *translation_tree.json_warnings))),
            translation_tree.ignored_paths,
        )
    else:
        repo, prefix = found.repo, found.prefix
        _configure_exact_tree_repo(repo)
        _ensure_local_excludes(repo)
        status = inspect_repository(translated)
        if status.pending_cherry_pick:
            raise GitWorkflowError("Finish or abort the pending cherry-pick first")
        if not status.worktree_clean:
            raise GitWorkflowError(
                "Commit or discard current Git changes before registering the original game"
            )
        if status.original_exists:
            raise GitWorkflowError("The original branch already exists")
        head = _run_git(repo, "rev-parse", "HEAD", check=False)
        if head.returncode != 0:
            raise GitWorkflowError(
                "Existing repositories must have at least one commit before reconciliation"
            )
        head_commit = head.stdout.strip()
        translation_branch = status.translation_branch or status.current_branch
        if not translation_branch or translation_branch == ORIGINAL_BRANCH:
            raise GitWorkflowError(
                "Check out the branch containing the translated game before reconciliation"
            )
        # Normalize the working translation tree before baseline commits.
        if preserve_game_files:
            _source_files(original, format_json=False)
            _source_files(translated, format_json=False)
            preformatted, prewarnings = (), ()
            _run_git(repo, "config", "--local", _PRESERVE_GAME_FILES_CONFIG, "true")
        else:
            preformatted, prewarnings = _prepare_worktree_formatting(translated)
        gitignore_installed = _install_game_gitignore(translated, preserve_game_files=preserve_game_files)
        _ensure_translation_branch(repo, head_commit, translation_branch)
        original_tree = _write_tree_from_folder(
            repo, original, game_prefix=prefix, base_commit=head_commit,
            include_tool_state=not preserve_game_files,
        )
        original_commit = _commit_tree(
            repo,
            original_tree.tree,
            _message(f"original: import clean game {version}", version),
            (head_commit,),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
        )
        translation_tree = _write_tree_from_folder(
            repo,
            translated,
            game_prefix=prefix,
            base_commit=head_commit,
            format_json=True,
            materialize_json=False,
        )
        translation_commit = _commit_tree(
            repo,
            translation_tree.tree,
            _message(f"translation: register original baseline {version}", version),
            (head_commit, original_commit),
        )
        translation_tree = _TreeBuild(
            translation_tree.tree,
            tuple(dict.fromkeys((*preformatted, *translation_tree.formatted_json_paths))),
            tuple(dict.fromkeys((*prewarnings, *translation_tree.json_warnings))),
            translation_tree.ignored_paths,
        )

    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{translation_branch}",
        translation_commit,
    )
    _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{translation_branch}")
    _run_git(repo, "read-tree", translation_commit)
    _require_matching_worktree(repo, action="Git baseline was created")
    official_assets = _build_ignored_asset_manifest(
        original, original_tree.ignored_paths
    )
    _save_asset_manifest(
        repo,
        prefix,
        version,
        original_commit,
        official_assets,
        baseline_source_kind=_ASSET_BASELINE_SOURCE_BOOTSTRAP,
        has_unbased_tracked_assets=False,
    )
    _set_translation_branch(repo, translation_branch)
    return BootstrapResult(
        repo,
        original_commit,
        translation_commit,
        version,
        translation_tree.formatted_json_paths,
        translation_tree.json_warnings,
        translation_tree.ignored_paths,
        gitignore_installed,
    )


def register_translation_branch(
    translated_game: str | Path,
    version: str | None = None,
    *,
    branch: str | None = None,
    replace: bool = False,
    preserve_game_files: bool = False,
) -> BootstrapResult:
    """Register an existing local branch as the translated game branch."""
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit:
        raise GitWorkflowError("The original branch must exist first")
    if status.translation_exists and not replace:
        raise GitWorkflowError("The translated branch is already registered")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before reconciliation")
    translation_branch = _validate_branch_name(
        status.repo_root, branch or status.current_branch or ""
    )
    if branch and _ref_commit(status.repo_root, translation_branch) is None:
        raise GitWorkflowError(f"The translated branch does not exist: {translation_branch}")
    if status.current_branch != translation_branch:
        _run_git(status.repo_root, "checkout", translation_branch)
    head = _run_git(status.repo_root, "rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        raise GitWorkflowError("The current translated branch has no commit to register")
    head_commit = head.stdout.strip()
    if head_commit == status.original_commit:
        raise GitWorkflowError(
            "The original branch itself is checked out. Select or commit the translated game state first."
        )
    resolved_version = _validate_version(version or status.original_version or "")
    _configure_exact_tree_repo(status.repo_root)
    if preserve_game_files:
        _run_git(status.repo_root, "config", "--local", _PRESERVE_GAME_FILES_CONFIG, "true")
    _ensure_local_excludes(status.repo_root)
    gitignore_installed = _install_game_gitignore(game, preserve_game_files=_preserve_game_files(status.repo_root))
    translation_tree = _write_tree_from_folder(
        status.repo_root,
        game,
        game_prefix=status.game_prefix,
        base_commit=head_commit,
        format_json=True,
        materialize_json=True,
    )
    current_tree = _run_git(
        status.repo_root, "rev-parse", f"{head_commit}^{{tree}}"
    ).stdout.strip()
    current_version = _version_from_history(
        status.repo_root, translation_branch, head_commit
    )
    if translation_tree.tree == current_tree and current_version == resolved_version:
        translation_commit = head_commit
    else:
        translation_commit = _commit_tree(
            status.repo_root,
            translation_tree.tree,
            _message(
                f"translation: register translated game {resolved_version}",
                resolved_version,
            ),
            (head_commit, status.original_commit),
        )
    _run_git(
        status.repo_root,
        "update-ref",
        f"refs/heads/{translation_branch}",
        translation_commit,
    )
    _run_git(
        status.repo_root,
        "symbolic-ref", "HEAD", f"refs/heads/{translation_branch}",
    )
    _run_git(status.repo_root, "read-tree", translation_commit)
    _set_translation_branch(status.repo_root, translation_branch)
    return BootstrapResult(
        status.repo_root,
        status.original_commit,
        translation_commit,
        resolved_version,
        translation_tree.formatted_json_paths,
        translation_tree.json_warnings,
        translation_tree.ignored_paths,
        gitignore_installed,
    )


def local_branch_names(game_root: str | Path) -> tuple[str, ...]:
    """Return safe local branch choices for translated-branch registration."""
    status = inspect_repository(game_root)
    if not status.repo_root:
        return ()
    output = _run_git(
        status.repo_root,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
    ).stdout
    branches = []
    for raw in output.splitlines():
        branch = raw.strip()
        if not branch or branch == ORIGINAL_BRANCH:
            continue
        branches.append(_validate_branch_name(status.repo_root, branch))
    return tuple(sorted(set(branches)))


def record_version_metadata(
    translated_game: str | Path, version: str
) -> BootstrapResult:
    """Repair a complete legacy branch layout that lacks version trailers.

    The file trees are reused exactly.  Only no-content commits are added to
    the two branch tips so subsequent repository inspection can identify the
    registered baseline version.
    """
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Both original and translated branches must exist")
    _configure_exact_tree_repo(status.repo_root)
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before reconciliation")
    resolved_version = _validate_version(version)
    repo = status.repo_root

    if status.current_branch != status.translation_branch:
        _run_git(repo, "checkout", status.translation_branch)
    _reject_original_checked_out_elsewhere(repo)

    original_commit = status.original_commit
    if not status.original_version:
        original_tree = _run_git(
            repo, "rev-parse", f"{original_commit}^{{tree}}"
        ).stdout.strip()
        original_commit = _commit_tree(
            repo,
            original_tree,
            _message(f"original: record version metadata {resolved_version}", resolved_version),
            (original_commit,),
        )
        _run_git(repo, "update-ref", f"refs/heads/{ORIGINAL_BRANCH}", original_commit)

    translation_commit = status.translation_commit
    if not status.translation_version:
        translation_tree = _run_git(
            repo, "rev-parse", f"{translation_commit}^{{tree}}"
        ).stdout.strip()
        translation_commit = _commit_tree(
            repo,
            translation_tree,
            _message(
                f"translation: record version metadata {resolved_version}",
                resolved_version,
            ),
            (translation_commit,),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{status.translation_branch}",
            translation_commit,
        )
        _run_git(repo, "reset", "--soft", translation_commit)

    return BootstrapResult(
        repo,
        original_commit,
        translation_commit,
        resolved_version,
    )


def checkout_translation_branch(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.translation_exists:
        raise GitWorkflowError("The translated branch is not registered")
    _configure_exact_tree_repo(status.repo_root)
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current changes before switching branches")
    _run_git(status.repo_root, "checkout", status.translation_branch)
    return inspect_repository(game)


def _validate_conflict_path(path: str, prefix: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise GitWorkflowError(f"Git reported an unsafe conflict path: {path!r}")
    if prefix and path != prefix and not path.startswith(f"{prefix}/"):
        raise GitWorkflowError(f"Update conflict escaped the selected game folder: {path}")


def conflict_paths(game_root: str | Path) -> tuple[str, ...]:
    selected = Path(game_root).expanduser().resolve()
    found = _repository_for(selected) if selected.is_dir() else None
    return _unmerged_paths(found.repo) if found else ()


def _unmerged_paths(repo: Path) -> tuple[str, ...]:
    """The paths a stopped cherry-pick left unmerged in `repo`."""
    output = _run_git(
        repo,
        "diff",
        "--name-only",
        "--diff-filter=U",
        "-z",
        check=False,
    ).stdout
    return tuple(path for path in output.split("\x00") if path)


def _resolve_conflicts_with_official(repo: Path, prefix: str) -> tuple[str, ...]:
    paths = _unmerged_paths(repo)
    for path in paths:
        _validate_conflict_path(path, prefix)
        stage_records = _run_git(
            repo, "ls-files", "-u", "-z", "--", path
        ).stdout.split("\x00")
        stages: dict[int, tuple[str, str]] = {}
        for record in stage_records:
            if not record:
                continue
            metadata, _recorded_path = record.split("\t", 1)
            mode, object_id, stage_text = metadata.split(" ")
            stages[int(stage_text)] = (mode, object_id)

        if 3 not in stages:
            _run_git(repo, "rm", "-f", "--", path)
            continue

        if all(stage in stages for stage in (1, 2, 3)):
            official_mode, official_object = stages[3]
            # Game data and plugin settings merge by value, so a translated
            # line next to a line the release inserted keeps its translation.
            merged_value = _merged_by_value(repo, path, stages[1][1], stages[2][1], official_object)
            if merged_value is not None:
                blob = _run_git(
                    repo, "hash-object", "-w", "--no-filters", "--stdin", input_text=merged_value
                ).stdout.strip()
                _run_git(
                    repo,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"{official_mode},{blob},{path}",
                )
                _run_git(repo, "checkout-index", "--force", "--", path)
                continue
            merged = _run_git(
                repo,
                *_merge_file(),
                "--object-id",
                "--theirs",
                stages[2][1],
                stages[1][1],
                official_object,
                check=False,
            )
            merged_object = merged.stdout.strip()
            if merged.returncode == 0 and re.fullmatch(
                r"[0-9a-f]{40,64}", merged_object
            ):
                merged_object = _restored_object(
                    repo, path, stages[1][1], stages[2][1], official_object, merged_object
                )
                _run_git(
                    repo,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"{official_mode},{merged_object},{path}",
                )
                _run_git(repo, "checkout-index", "--force", "--", path)
                continue

            detail = merged.stderr.strip() or merged.stdout.strip()
            if "binary" not in detail.casefold():
                raise GitWorkflowError(
                    f"Could not resolve text conflict in {path} by Git hunk: "
                    + (detail or "git merge-file returned no merged object")
                )

        # Add/add conflicts and binary files cannot be combined safely by line.
        # The official file wins as the explicit fallback for those cases.
        _run_git(repo, "checkout", "--theirs", "--", path)
        _run_git(repo, "add", "--", path)
    remaining = _unmerged_paths(repo)
    if remaining:
        raise GitWorkflowError(
            "Some conflicts could not be resolved with the official version: "
            + ", ".join(remaining)
        )
    return paths


def _finish_cherry_pick(repo: Path, original_commit: str) -> str:
    env = {"GIT_EDITOR": "true"}
    continued = _run_git(
        repo,
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "cherry-pick",
        "--continue",
        check=False,
        env=env,
    )
    if continued.returncode != 0:
        combined = f"{continued.stdout}\n{continued.stderr}".lower()
        if "empty" in combined:
            aborted = _run_git(repo, "cherry-pick", "--abort", check=False)
            recovery = ""
            if aborted.returncode != 0:
                recovery = (
                    " The cherry-pick could not be restored automatically; use the "
                    "recovery controls before continuing."
                )
            raise GitWorkflowError(
                "The official patch unexpectedly produced no translation changes. "
                "No version marker was created." + recovery
            )
        else:
            detail = continued.stderr.strip() or continued.stdout.strip()
            raise GitWorkflowError(detail or "Could not finish cherry-pick")
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _tree_entry(repo: Path, ref: str, path: str) -> str:
    return _run_git(repo, "ls-tree", "-z", ref, "--", path).stdout


def _already_present_patch_paths(
    repo: Path,
    original_parent: str,
    original_commit: str,
    translation_commit: str,
    game_prefix: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    changed = tuple(
        sorted(_diff_status(repo, original_parent, original_commit, game_prefix))
    )
    already_present = tuple(
        path
        for path in changed
        if _tree_entry(repo, original_commit, path)
        == _tree_entry(repo, translation_commit, path)
    )
    return changed, already_present


def _record_already_present_version(
    repo: Path,
    translation_branch: str,
    translation_commit: str,
    original_commit: str,
    version: str,
    paths: tuple[str, ...],
    game_prefix: str,
) -> UpdateResult:
    tree = _run_git(repo, "rev-parse", f"{translation_commit}^{{tree}}").stdout.strip()
    message = _message(
        f"translation: record already-present original game version {version}", version
    )
    marker = _commit_tree(repo, tree, message, (translation_commit,))
    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{translation_branch}",
        marker,
        translation_commit,
    )
    return UpdateResult(
        repo_root=repo,
        original_commit=original_commit,
        translation_commit=marker,
        version=version,
        content_changed=False,
        already_present_paths=tuple(
            _display_path(path, game_prefix) for path in paths
        ),
    )


def _cherry_pick(
    status: RepositoryStatus,
    original_commit: str,
    version: str,
    *,
    auto_resolve: bool,
) -> UpdateResult:
    """Brings `original_commit` into the translation; `status` is the one
    its entry point read, as only the original branch moved since."""
    if not status.repo_root:
        raise GitWorkflowError("The translated game is not in a Git repository")
    repo = status.repo_root
    if not status.translation_commit:
        raise GitWorkflowError("The translated branch has no commit to update")
    parent = _run_git(repo, "rev-parse", f"{original_commit}^").stdout.strip()
    changed, already_present = _already_present_patch_paths(
        repo,
        parent,
        original_commit,
        status.translation_commit,
        status.game_prefix,
    )
    if len(already_present) == len(changed):
        return _record_already_present_version(
            repo,
            status.translation_branch,
            status.translation_commit,
            original_commit,
            version,
            already_present,
            status.game_prefix,
        )
    picked = _run_git(
        repo,
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "cherry-pick",
        original_commit,
        check=False,
    )
    if picked.returncode == 0:
        return UpdateResult(
            repo, original_commit, _run_git(repo, "rev-parse", "HEAD").stdout.strip(), version
        )

    conflicts = _unmerged_paths(repo)
    if not conflicts:
        detail = picked.stderr.strip() or picked.stdout.strip()
        if "empty" in detail.lower():
            aborted = _run_git(repo, "cherry-pick", "--abort", check=False)
            recovery = ""
            if aborted.returncode != 0:
                recovery = (
                    " The cherry-pick could not be restored automatically; use the "
                    "recovery controls before continuing."
                )
            raise GitWorkflowError(
                "The official patch unexpectedly produced no translation changes. "
                "No version marker was created." + recovery
            )
        raise GitWorkflowError(detail or "Cherry-pick failed without file conflicts")
    if not auto_resolve:
        return UpdateResult(repo, original_commit, None, version, (), conflicts)
    won = _resolve_conflicts_with_official(repo, status.game_prefix)
    translation_commit = _finish_cherry_pick(repo, original_commit)
    return UpdateResult(repo, original_commit, translation_commit, version, won)


def _diff_status(
    repo: Path, left: str, right: str, game_prefix: str
) -> dict[str, str]:
    args = ["diff", "--name-status", "--no-renames", "-z", left, right]
    if game_prefix:
        args.extend(["--", game_prefix])
    tokens = [token for token in _run_git(repo, *args).stdout.split("\x00") if token]
    if len(tokens) % 2:
        raise GitWorkflowError("Git returned an invalid change preview")
    return {tokens[index + 1]: tokens[index] for index in range(0, len(tokens), 2)}


def _diff_numstat(
    repo: Path, left: str, right: str, game_prefix: str
) -> dict[str, tuple[int | None, int | None]]:
    args = ["diff", "--numstat", "--no-renames", "-z", left, right]
    if game_prefix:
        args.extend(["--", game_prefix])
    stats = {}
    for record in _run_git(repo, *args).stdout.split("\x00"):
        if not record:
            continue
        fields = record.split("\t", 2)
        if len(fields) != 3:
            raise GitWorkflowError("Git returned invalid line counts for the update preview")
        added, deleted, path = fields
        stats[path] = (
            None if added == "-" else int(added),
            None if deleted == "-" else int(deleted),
        )
    return stats


def _tree_files(
    repo: Path, ref: str, game_prefix: str, errors: str = "replace"
) -> dict[str, tuple[str, str]]:
    args = ["ls-tree", "-r", "-z", ref]
    if game_prefix:
        args.extend(["--", game_prefix])
    files = {}
    for record in _run_git(repo, *args, errors=errors).stdout.split("\x00"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, object_type, object_id = metadata.split()
        if object_type == "blob":
            files[path] = (mode, object_id)
    return files


def _preserve_tool_owned_paths(
    repo: Path,
    build: _TreeBuild,
    base_ref: str,
    game_prefix: str,
) -> _TreeBuild:
    """Keep updater infrastructure out of official game patches."""
    base_files = _tree_files(repo, base_ref, game_prefix)
    proposed_files = _tree_files(repo, build.tree, game_prefix)
    index_lines = []
    for path in sorted(set(base_files) | set(proposed_files)):
        if not _is_tool_owned_path(_display_path(path, game_prefix)):
            continue
        base = base_files.get(path)
        proposed = proposed_files.get(path)
        if base == proposed:
            continue
        if base is None:
            index_lines.append(f"0 {_ZERO_OID}\t{path}")
        else:
            mode, object_id = base
            index_lines.append(f"{mode} {object_id}\t{path}")

    if not index_lines:
        return build

    index_name, index_env = _temporary_index()
    try:
        _run_git(repo, "read-tree", build.tree, env=index_env)
        _run_git(
            repo,
            "update-index",
            "--index-info",
            input_text="\n".join(index_lines) + "\n",
            env=index_env,
        )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        return replace(build, tree=tree)
    finally:
        system.unlink(index_name, ignore_errors=True)


def _preserve_unbased_translation_assets(
    repo: Path,
    build: _TreeBuild,
    original_commit: str,
    translation_commit: str,
    game_prefix: str,
) -> tuple[_TreeBuild, tuple[str, ...]]:
    """Exclude translated assets that have no authoritative original blob.

    Without a previous clean folder, comparing a translated image to the new
    official image cannot prove that the official asset changed. Keeping the
    path absent from both the original baseline and proposed official tree
    preserves the translated worktree copy instead of overwriting it on an
    unsupported guess.
    """
    original_files = _tree_files(repo, original_commit, game_prefix)
    translated_files = _tree_files(repo, translation_commit, game_prefix)
    proposed_files = _tree_files(repo, build.tree, game_prefix)
    index_lines = []
    preserved = []
    for path in translated_files:
        relative = _display_path(path, game_prefix)
        if (
            path not in original_files
            and path in proposed_files
            and not _is_tool_owned_path(relative)
            and _asset_category(relative) != "Other asset"
        ):
            index_lines.append(f"0 {_ZERO_OID}\t{path}")
            preserved.append(relative)

    if not index_lines:
        return build, ()

    index_name, index_env = _temporary_index()
    try:
        _run_git(repo, "read-tree", build.tree, env=index_env)
        _run_git(
            repo,
            "update-index",
            "--index-info",
            input_text="\n".join(index_lines) + "\n",
            env=index_env,
        )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        return replace(build, tree=tree), tuple(sorted(preserved))
    finally:
        system.unlink(index_name, ignore_errors=True)


def original_lacks(game_root: str | Path) -> tuple[str, ...]:
    """The game files the translation branch holds that the original branch
    lacks, as game-relative paths: files a checkpoint let into the patch
    after its baseline, such as a VX Ace game's ace_json, and files the
    translation added. Repository metadata and DazedTL's portable files are
    each branch's own."""
    checkout = read_checkout(game_root)
    if checkout is None or not checkout.configured:
        return ()
    repo, prefix = checkout.repo, checkout.prefix
    original = _tree_files(repo, checkout.original_commit, prefix)
    translated = _tree_files(repo, checkout.translation_commit, prefix)
    lacking = (_display_path(path, prefix) for path in set(translated) - set(original))
    return tuple(
        sorted(
            path
            for path in lacking
            if path not in GAME_REPOSITORY_METADATA and not is_portable_game_file(path)
        )
    )


def hold_in_original(game_root: str | Path, files: Mapping[str, tuple[str, str]]) -> str | None:
    """Adds `files`, the original game's (mode, blob) of files the original
    branch lacks, to that branch as one commit of its version. An update
    compares the release and the translation with this branch, so a file it
    lacks reads as one the translation added, and the release's copy of it
    then replaces the translation's. Returns the commit, or None when the
    branch already holds them."""
    game = Path(game_root).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit:
        raise GitWorkflowError("Register the original branch before adding to it")
    repo, prefix = status.repo_root, status.game_prefix
    held = _tree_files(repo, status.original_commit, prefix)
    lines = [
        f"{mode} {blob}\t{_prefixed(prefix, path)}"
        for path, (mode, blob) in sorted(files.items())
        if _prefixed(prefix, path) not in held
    ]
    if not lines:
        return None
    _reject_original_checked_out_elsewhere(repo)
    index_name, index_env = _temporary_index()
    try:
        _run_git(repo, "read-tree", status.original_commit, env=index_env)
        _run_git(
            repo,
            "update-index",
            "--index-info",
            input_text="\n".join(lines) + "\n",
            env=index_env,
        )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
    finally:
        system.unlink(index_name, ignore_errors=True)
    commit = _commit_tree(
        repo,
        tree,
        _message(
            "original: hold the original files the translation's patch holds",
            status.original_version or "",
        ),
        (status.original_commit,),
    )
    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{ORIGINAL_BRANCH}",
        commit,
        status.original_commit,
    )
    return commit


def _replacement_outcome(
    repo: Path,
    path: str,
    official_change: str,
    translation_change: str | None,
    base: tuple[str, str] | None,
    translated: tuple[str, str] | None,
    official: tuple[str, str] | None,
    *,
    is_image: bool,
) -> tuple[bool, str]:
    if translation_change is None:
        if official_change == "A":
            return False, "New file"
        if official_change == "D":
            return False, "File removed"
        return False, "Image replaced" if is_image else "Official changes applied"

    if official_change == "D":
        return True, "Translated file removed"
    if official_change == "A" or translation_change == "D":
        noun = "image" if is_image else "file"
        return True, f"Translated {noun} replaced by official {noun}"

    if not base or not translated or not official:
        return True, "Translated file replaced by official file"
    if translated[1] == base[1]:
        return False, "Image replaced" if is_image else "Official changes applied"
    if translated[1] == official[1]:
        return False, "Official content already present; file metadata updated"
    merged = merged_file(repo, path, translated[1], base[1], official[1])
    if merged is None:
        noun = "image" if is_image else "binary file"
        return True, f"Translated {noun} replaced by official {noun}"
    if merged == _git_bytes(repo, "cat-file", "blob", official[1]).stdout:
        return True, "Entire translated file replaced by official content"
    return False, "Merged with translation edits"


def _git_bytes(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Runs Git for file content as bytes, which text decoding could alter."""
    try:
        return system.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitWorkflowError(f"git {_command_name(args)} could not run") from exc


@functools.cache
def _merge_file() -> tuple[str, ...]:
    """`git merge-file` with the histogram diff the cherry-pick's own merge uses.

    Git's default diff stops searching after a few hundred changed lines and
    pairs formatted JSON's repeated lines with the wrong commands, so the
    release won conflicts it never had and replaced translations it left
    unchanged. merge-file takes histogram from Git 2.44; an older Git keeps
    the default.
    """
    version = _run_git(Path(tempfile.gettempdir()), "--version").stdout
    match = re.match(r"git version (\d+)\.(\d+)", version)
    if match and (int(match[1]), int(match[2])) >= (2, 44):
        return ("merge-file", "--diff-algorithm=histogram")
    return ("merge-file",)


def _blob_bytes(repo: Path, *objects: str) -> list[bytes] | None:
    blobs = [_git_bytes(repo, "cat-file", "blob", identity) for identity in objects]
    return None if any(blob.returncode for blob in blobs) else [blob.stdout for blob in blobs]


def _merged_by_value(repo: Path, path: str, base: str, translated: str, official: str) -> str | None:
    """Game data or a plugin registry both sides changed, merged by value
    (see json_merge and script_merge)."""
    if path.casefold().endswith(".json"):
        merge = merge_json
    elif is_plugin_registry(path):
        merge = merge_plugins
    else:
        return None
    blobs = _blob_bytes(repo, base, translated, official)
    return None if blobs is None else merge(*blobs)


def _restored(repo: Path, path: str, base: str, translated: str, official: str, merged: bytes) -> bytes:
    """A script Git merged by line, with the translated lines the release left
    back in place (see script_merge), and the line loading the playtest's
    fixes back in a main.js whose hunk the release won."""
    if not path.casefold().endswith(".js"):
        return merged
    blobs = _blob_bytes(repo, base, translated, official)
    if blobs is None:
        return merged
    merged = restore_lines(*blobs, merged)
    if ("/" + path).endswith("/" + fixes.MAIN) and fixes.loads_fixes(blobs[1]):
        try:
            return fixes.with_loader(merged)
        except ValueError:
            # A release that sets plugins up otherwise; the checkpoint
            # refuses fixes main.js does not load.
            return merged
    return merged


def _restored_object(repo: Path, path: str, base: str, translated: str, official: str, merged: str) -> str:
    content = _blob_bytes(repo, merged)
    if content is None:
        return merged
    restored = _restored(repo, path, base, translated, official, content[0])
    if restored == content[0]:
        return merged
    return _run_git(
        repo, "hash-object", "-w", "--no-filters", "--stdin", input_text=restored.decode("utf-8")
    ).stdout.strip()


def merged_file(repo: Path, path: str, translated: str, base: str, official: str) -> bytes | None:
    """The file applying an update leaves where both the release and the
    translation changed it, or None when Git cannot merge it, such as an image.

    Applying cherry-picks the release: a clean line merge is what Git writes,
    and a conflicted file is resolved as `_resolve_conflicts_with_official`
    does: game data and plugin registries by value, anything else by hunk
    with the release winning, and then a script's translated lines the
    release left go back in.
    """
    clean = _git_bytes(repo, *_merge_file(), "-p", "--object-id", translated, base, official)
    if clean.returncode == 0:
        return clean.stdout
    merged = _merged_by_value(repo, path, base, translated, official)
    if merged is not None:
        return merged.encode("utf-8")
    theirs = _git_bytes(repo, *_merge_file(), "-p", "--object-id", "--theirs", translated, base, official)
    if theirs.returncode:
        return None
    return _restored(repo, path, base, translated, official, theirs.stdout)


def _display_path(path: str, game_prefix: str) -> str:
    prefix = f"{game_prefix}/" if game_prefix else ""
    return path[len(prefix) :] if prefix and path.startswith(prefix) else path


def _validate_patch_root_alignment(
    repo: Path,
    source: Path,
    original_commit: str,
    game_prefix: str,
) -> None:
    """Reject a patch that clearly belongs one directory above the selection."""
    if not game_prefix:
        return
    entries = _source_files(source, format_json=False)
    if not entries:
        return
    original_files = _tree_files(repo, original_commit, "")
    selected = PurePosixPath(game_prefix)
    parent_prefix = "" if str(selected.parent) == "." else selected.parent.as_posix()
    direct_matches = []
    intended_matches = []
    for entry in entries:
        direct = _prefixed(parent_prefix, entry.relative)
        intended = _prefixed(game_prefix, entry.relative)
        if direct in original_files:
            direct_matches.append(entry.relative)
        if intended in original_files:
            intended_matches.append(entry.relative)

    first_parts = {
        PurePosixPath(entry.relative).parts[0].casefold()
        for entry in entries
        if PurePosixPath(entry.relative).parts
    }
    repeats_selected_folder = selected.name.casefold() in first_parts
    strongly_shifted = (
        len(direct_matches) >= 3
        and len(direct_matches) >= max(1, len(intended_matches)) * 4
    )
    if not direct_matches or (not repeats_selected_folder and not strongly_shifted):
        return

    example = next(
        (
            path
            for path in direct_matches
            if PurePosixPath(path).parts[0].casefold() == selected.name.casefold()
        ),
        direct_matches[0],
    )
    raise GitWorkflowError(
        "The patch paths do not line up with the selected translated game folder. "
        f"For example, {example!r} already exists one folder above the selection, "
        "so applying here would create a duplicated folder path. Select the game "
        f"root instead: {repo.joinpath(*selected.parent.parts)}"
    )


def preview_official_update(
    translated_game: str | Path,
    new_official_game: str | Path,
    version: str,
    *,
    previous_official_game: str | Path | None = None,
    patch_overlay: bool = False,
) -> UpdatePreview:
    """Build a non-ref preview of a full release or copy-over patch tree."""
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Register both branches before previewing an update")
    _configure_exact_tree_repo(status.repo_root)
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before previewing"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before previewing")
    official = _validate_source(new_official_game, game)
    if patch_overlay:
        _validate_patch_root_alignment(
            status.repo_root,
            official,
            status.original_commit,
            status.game_prefix,
        )
    build = _write_tree_from_folder(
        status.repo_root,
        official,
        game_prefix=status.game_prefix,
        base_commit=status.original_commit,
        replace_game_tree=not patch_overlay,
    )
    build = _preserve_tool_owned_paths(
        status.repo_root,
        build,
        status.original_commit,
        status.game_prefix,
    )
    preserved_translation_assets = ()
    if previous_official_game is None and not patch_overlay:
        build, preserved_translation_assets = _preserve_unbased_translation_assets(
            status.repo_root,
            build,
            status.original_commit,
            status.translation_commit,
            status.game_prefix,
        )
    baseline_assets = _load_asset_manifest(status.repo_root, status.game_prefix)
    stored_asset_baseline = baseline_assets is not None
    baseline_source = None
    baseline_tree = _run_git(
        status.repo_root, "rev-parse", f"{status.original_commit}^{{tree}}"
    ).stdout.strip()
    if previous_official_game is not None:
        baseline_source, baseline_assets, baseline_tree = _validate_official_asset_baseline(
            status.repo_root,
            game,
            previous_official_game,
            status.game_prefix,
            status.original_commit,
        )
    elif baseline_assets is None:
        baseline_assets = _asset_manifest_for_source(
            status.repo_root,
            game,
            status.game_prefix,
        )
    proposed_assets = _proposed_asset_manifest(
        official,
        build.ignored_paths,
        baseline_assets,
        patch_overlay=patch_overlay,
    )
    external_changes = _external_asset_changes(
        game, baseline_assets, proposed_assets
    )
    if preserved_translation_assets:
        preserved_set = set(preserved_translation_assets)
        external_changes = tuple(
            change for change in external_changes if change.path not in preserved_set
        )
    official_changes = _diff_status(
        status.repo_root, baseline_tree, build.tree, status.game_prefix
    )
    translation_changes = _diff_status(
        status.repo_root,
        baseline_tree,
        status.translation_commit,
        status.game_prefix,
    )
    original_files = _tree_files(
        status.repo_root, baseline_tree, status.game_prefix
    )
    translated_files = _tree_files(
        status.repo_root, status.translation_commit, status.game_prefix
    )
    proposed_files = _tree_files(status.repo_root, build.tree, status.game_prefix)
    overlap = sorted(set(official_changes) & set(translation_changes))
    already_present = tuple(
        sorted(
            path
            for path in official_changes
            if proposed_files.get(path) == translated_files.get(path)
        )
    )
    line_stats = _diff_numstat(
        status.repo_root, baseline_tree, build.tree, status.game_prefix
    )
    file_changes = []
    for path in sorted(official_changes):
        display_path = _display_path(path, status.game_prefix)
        change_code = official_changes[path]
        is_image = Path(display_path).suffix.casefold() in _IMAGE_EXTENSIONS
        if path in already_present:
            whole_file_replaced = False
            result = "Already present; no game change"
        else:
            whole_file_replaced, result = _replacement_outcome(
                status.repo_root,
                path,
                change_code,
                translation_changes.get(path),
                original_files.get(path),
                translated_files.get(path),
                proposed_files.get(path),
                is_image=is_image,
            )
        added_lines, deleted_lines = line_stats.get(path, (None, None))
        file_changes.append(
            UpdateFileChange(
                path=display_path,
                change={"A": "Added", "D": "Removed"}.get(
                    change_code, "Modified"
                ),
                added_lines=added_lines,
                deleted_lines=deleted_lines,
                is_image=is_image,
                translation_changed=path in translation_changes,
                already_present=path in already_present,
                whole_file_replaced=whole_file_replaced,
                result=result,
            )
        )

    image_changes = []
    for tracked_change in file_changes:
        if not tracked_change.is_image or tracked_change.already_present:
            continue
        image_change = {
            "Added": "Added",
            "Removed": "Removed",
        }.get(tracked_change.change, "Replaced")
        warning = image_change in {"Removed", "Replaced"}
        if warning:
            result = (
                "⚠ Tracked translation image will be removed"
                if image_change == "Removed"
                else "⚠ Tracked translation image will be replaced"
            )
        else:
            result = "Tracked image will be added"
        image_changes.append(
            UpdateImageChange(
                path=tracked_change.path,
                change=image_change,
                tracked=True,
                warning=warning,
                result=result,
            )
        )
    image_changes.extend(
        UpdateImageChange(
            path=change.path,
            change=change.change,
            tracked=False,
            warning=False,
            result=change.result,
        )
        for change in external_changes
        if change.category == "Image"
    )

    def paths_for(code: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                _display_path(path, status.game_prefix)
                for path, change in official_changes.items()
                if change == code
            )
        )

    return UpdatePreview(
        repo_root=status.repo_root,
        source_root=official,
        version=version,
        original_commit=status.original_commit,
        translation_commit=status.translation_commit,
        proposed_tree=build.tree,
        added_paths=paths_for("A"),
        modified_paths=paths_for("M"),
        deleted_paths=paths_for("D"),
        overlapping_paths=tuple(
            _display_path(path, status.game_prefix) for path in overlap
        ),
        already_present_paths=tuple(
            _display_path(path, status.game_prefix) for path in already_present
        ),
        formatted_json_paths=build.formatted_json_paths,
        json_warnings=build.json_warnings,
        ignored_paths=build.ignored_paths,
        file_changes=tuple(file_changes),
        image_changes=tuple(image_changes),
        external_changes=external_changes,
        proposed_asset_manifest=_manifest_digest(proposed_assets),
        baseline_asset_manifest=_manifest_digest(baseline_assets),
        asset_manifest_available=stored_asset_baseline,
        baseline_source_root=baseline_source,
        preserved_translation_asset_paths=preserved_translation_assets,
        patch_overlay=patch_overlay,
        baseline_tree=baseline_tree,
    )


def _rebuilt_pending_asset_plan(
    status: RepositoryStatus, result: UpdateResult, release: str | Path | None
) -> dict[str, object]:
    """The asset plan the update saved, made again from the release the
    original branch is at and `release`, the folder it was applied from,
    for a record that can no longer be read."""
    assert status.repo_root
    damaged = "This game update's record of the assets it still has to copy is damaged"
    if release is None:
        raise GitWorkflowError(
            f"{damaged}, and DazedTL has no note of the release folder the "
            "update came from, so it can't copy them. Copy that release's "
            "files that are not in Git into the game yourself, or go back to "
            "the checkpoint before this update and apply it again."
        )
    folder = Path(release).expanduser()
    if not folder.is_dir():
        raise GitWorkflowError(
            f"{damaged}, and copying them needs the release folder the update "
            f"came from, {folder}, which is gone. Put that folder back, then "
            "finish the update again."
        )
    source = _validate_source(folder, status.selected_root)
    released = next(
        (
            record
            for record in version_history(status.selected_root)
            if record.kind == "update"
        ),
        None,
    )
    if (
        released is None
        or released.commit != result.original_commit
        or released.version != result.version
    ):
        raise GitWorkflowError(
            "The pending asset update does not match the registered original version"
        )
    repo, prefix = status.repo_root, status.game_prefix
    patch_overlay = released.release == "patch"
    proposed = dict(_load_asset_manifest(repo, prefix) or {}) if patch_overlay else {}
    proposed.update(_asset_manifest_for_source(repo, source, prefix))
    return {
        "source": str(source),
        "version": result.version,
        "original_commit": result.original_commit,
        "manifest_digest": _manifest_digest(proposed),
        # The assets an update keeps the translation's copy of are files Git
        # tracks, never among those copied outside it.
        "preserved_translation_assets": (),
        "patch_overlay": patch_overlay,
    }


def _complete_pending_asset_plan(
    status: RepositoryStatus, result: UpdateResult, release: str | Path | None = None
) -> UpdateResult:
    """Copies the assets of the update `result` brought into the
    translation; `status` is the one its entry point read, as the update
    moved only branches since."""
    game = status.selected_root
    if not status.repo_root:
        raise GitWorkflowError("The translated game is not in a Git repository")
    try:
        plan = _load_pending_asset_plan(status.repo_root, status.game_prefix)
    except GitWorkflowError as error:
        if isinstance(error.__cause__, OSError):
            # Unreadable for now is not damaged.
            raise
        plan = _rebuilt_pending_asset_plan(status, result, release)
    if plan is None:
        return result
    if (
        plan["original_commit"] != result.original_commit
        or plan["version"] != result.version
    ):
        raise GitWorkflowError(
            "The pending asset update does not match the registered original version"
        )
    source = _validate_source(plan["source"], game)
    baseline = _load_asset_manifest(status.repo_root, status.game_prefix)
    supplied = _asset_manifest_for_source(
        status.repo_root, source, status.game_prefix
    )
    if plan.get("patch_overlay", False):
        proposed = dict(baseline or {})
        proposed.update(supplied)
    else:
        proposed = supplied
    if _manifest_digest(proposed) != plan["manifest_digest"]:
        raise GitWorkflowError(
            "The official folder changed before its assets were synchronized. "
            "Restore that folder and finish the asset update."
        )
    preserved_translation_assets = plan.get("preserved_translation_assets", ())
    changes = tuple(
        change
        for change in _external_asset_changes(game, baseline, proposed)
        if change.path not in set(preserved_translation_assets)
    )
    applied = _sync_external_assets(
        status.repo_root, game, source, changes, proposed
    )
    existing_metadata = _load_asset_manifest_metadata(status.repo_root, status.game_prefix)
    _save_asset_manifest(
        status.repo_root,
        status.game_prefix,
        result.version,
        result.original_commit,
        proposed,
        baseline_source_kind=existing_metadata.get("baseline_source_kind")
        if isinstance(existing_metadata.get("baseline_source_kind"), str)
        else None,
        has_unbased_tracked_assets=existing_metadata.get("has_unbased_tracked_assets")
        if isinstance(existing_metadata.get("has_unbased_tracked_assets"), bool)
        else None,
    )
    _clear_pending_asset_plan(status.repo_root, status.game_prefix)
    return UpdateResult(
        repo_root=result.repo_root,
        original_commit=result.original_commit,
        translation_commit=result.translation_commit,
        version=result.version,
        official_won_paths=result.official_won_paths,
        pending_conflicts=result.pending_conflicts,
        content_changed=result.content_changed or bool(applied),
        already_present_paths=result.already_present_paths,
        external_changes=changes,
    )


def apply_official_update(
    translated_game: str | Path,
    new_official_game: str | Path,
    version: str,
    *,
    auto_resolve: bool = True,
    expected_tree: str | None = None,
    expected_original_commit: str | None = None,
    expected_translation_commit: str | None = None,
    expected_asset_manifest: str | None = None,
    previous_official_game: str | Path | None = None,
    expected_baseline_asset_manifest: str | None = None,
    patch_overlay: bool = False,
    prepared_record: str | None = None,
) -> UpdateResult:
    """Moves the original branch to the release and brings it into the
    translation. `prepared_record` names the record of the prepared release
    made before, which the update commit names in its trailer."""
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    if prepared_record is not None and not _OBJECT_ID.fullmatch(prepared_record):
        raise GitWorkflowError("The prepared release's record is not a commit ID")
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Register both branches before applying an update")
    _configure_exact_tree_repo(status.repo_root)
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before updating"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before updating")
    if expected_original_commit and status.original_commit != expected_original_commit:
        raise GitWorkflowError(
            "The original branch changed after preview. Run the preview again before applying."
        )
    if expected_translation_commit and status.translation_commit != expected_translation_commit:
        raise GitWorkflowError(
            "The translated branch changed after preview. Run the preview again before applying."
        )
    official = _validate_source(new_official_game, game)
    repo = status.repo_root
    if patch_overlay:
        _validate_patch_root_alignment(
            repo,
            official,
            status.original_commit,
            status.game_prefix,
        )
    _reject_original_checked_out_elsewhere(repo)
    new_tree = _write_tree_from_folder(
        repo,
        official,
        game_prefix=status.game_prefix,
        base_commit=status.original_commit,
        replace_game_tree=not patch_overlay,
    )
    new_tree = _preserve_tool_owned_paths(
        repo,
        new_tree,
        status.original_commit,
        status.game_prefix,
    )
    preserved_translation_assets = ()
    if previous_official_game is None and not patch_overlay:
        new_tree, preserved_translation_assets = (
            _preserve_unbased_translation_assets(
                repo,
                new_tree,
                status.original_commit,
                status.translation_commit,
                status.game_prefix,
            )
        )
    baseline_assets = _load_asset_manifest(repo, status.game_prefix)
    baseline_was_missing = baseline_assets is None
    baseline_metadata_kind = None
    baseline_metadata_has_unbased_assets = None
    existing_baseline_metadata = _load_asset_manifest_metadata(repo, status.game_prefix)
    existing_baseline_source = existing_baseline_metadata.get("baseline_source_kind")
    registered_tree = _run_git(
        repo, "rev-parse", f"{status.original_commit}^{{tree}}"
    ).stdout.strip()
    baseline_tree = registered_tree
    if baseline_assets is None:
        if previous_official_game is not None:
            baseline_source, baseline_assets, baseline_tree = (
                _validate_official_asset_baseline(
                    repo,
                    game,
                    previous_official_game,
                    status.game_prefix,
                    status.original_commit,
                )
            )
            baseline_metadata_kind = _ASSET_BASELINE_SOURCE_PREVIOUS_OFFICIAL
            baseline_metadata_has_unbased_assets = False
        else:
            baseline_metadata_kind = _ASSET_BASELINE_SOURCE_CURRENT_GAME
            baseline_metadata_has_unbased_assets = bool(preserved_translation_assets)
            baseline_assets = _asset_manifest_for_source(
                repo,
                game,
                status.game_prefix,
            )
    elif previous_official_game is not None:
        baseline_source, baseline_assets, baseline_tree = _validate_official_asset_baseline(
            repo,
            game,
            previous_official_game,
            status.game_prefix,
            status.original_commit,
        )
        baseline_metadata_kind = _ASSET_BASELINE_SOURCE_PREVIOUS_OFFICIAL
        baseline_metadata_has_unbased_assets = False
    elif existing_baseline_source == _ASSET_BASELINE_SOURCE_CURRENT_GAME:
        baseline_metadata_kind = _ASSET_BASELINE_SOURCE_CURRENT_GAME
        baseline_metadata_has_unbased_assets = bool(
            bool(existing_baseline_metadata.get("has_unbased_tracked_assets"))
            or preserved_translation_assets
        )
    elif existing_baseline_source == _ASSET_BASELINE_SOURCE_BOOTSTRAP:
        baseline_metadata_kind = _ASSET_BASELINE_SOURCE_CURRENT_GAME
        baseline_metadata_has_unbased_assets = bool(preserved_translation_assets)
    proposed_assets = _proposed_asset_manifest(
        official,
        new_tree.ignored_paths,
        baseline_assets,
        patch_overlay=patch_overlay,
    )
    proposed_asset_digest = _manifest_digest(proposed_assets)
    baseline_asset_digest = _manifest_digest(baseline_assets)
    if expected_tree is not None and new_tree.tree != expected_tree:
        raise GitWorkflowError(
            "The official folder changed after preview. Run the preview again before applying."
        )
    if (
        expected_asset_manifest is not None
        and proposed_asset_digest != expected_asset_manifest
    ):
        raise GitWorkflowError(
            "The official assets changed after preview. Run the preview again before applying."
        )
    if (
        expected_baseline_asset_manifest is not None
        and baseline_asset_digest != expected_baseline_asset_manifest
    ):
        raise GitWorkflowError(
            "The previous official assets changed after preview. Run the preview again "
            "before applying."
        )
    baseline_parent = status.original_commit
    if baseline_tree != registered_tree:
        baseline_version = status.original_version or "unknown"
        baseline_parent = _commit_tree(
            repo,
            baseline_tree,
            _message(
                f"original: normalize legacy baseline {baseline_version}",
                baseline_version,
            ),
            (status.original_commit,),
        )
    if new_tree.tree == baseline_tree:
        if status.original_version == version:
            raise GitWorkflowError("That official game version is already registered")
        subject = f"patch: record original game version {version}"
    else:
        subject = f"patch: update original game files to {version}"
    original_commit = _commit_tree(
        repo,
        new_tree.tree,
        _message(subject, version)
        + f"\n{RELEASE_TRAILER}: {'patch' if patch_overlay else 'complete'}"
        + (f"\n{PREPARED_TRAILER}: {prepared_record}" if prepared_record else ""),
        (baseline_parent,),
    )
    if baseline_was_missing:
        _save_asset_manifest(
            repo,
            status.game_prefix,
            status.original_version or "unknown",
            baseline_parent,
            baseline_assets,
            baseline_source_kind=baseline_metadata_kind,
            has_unbased_tracked_assets=baseline_metadata_has_unbased_assets,
        )
    elif baseline_metadata_kind is not None:
        _save_asset_manifest(
            repo,
            status.game_prefix,
            status.original_version or "unknown",
            baseline_parent,
            baseline_assets,
            baseline_source_kind=baseline_metadata_kind,
            has_unbased_tracked_assets=baseline_metadata_has_unbased_assets,
        )
    _save_pending_asset_plan(
        repo,
        status.game_prefix,
        official,
        version,
        original_commit,
        proposed_asset_digest,
        preserved_translation_assets=preserved_translation_assets,
        patch_overlay=patch_overlay,
    )
    try:
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
            status.original_commit,
        )
    except Exception:
        _clear_pending_asset_plan(repo, status.game_prefix)
        raise
    try:
        result = _cherry_pick(
            status, original_commit, version, auto_resolve=auto_resolve
        )
    except Exception:
        # A cherry-pick that failed without conflicts to resolve left the
        # translation as it was, so the original branch goes back with it.
        if (
            not _cherry_pick_path(repo).exists()
            and _ref_commit(repo, status.translation_branch)
            == status.translation_commit
        ):
            _cancel_pending_update(
                repo, status.game_prefix, original_commit, status.original_commit
            )
        raise
    return _complete_pending_asset_plan(status, result) if result.complete else result


def apply_registered_original(
    translated_game: str | Path,
    *,
    auto_resolve: bool = True,
    release: str | Path | None = None,
) -> UpdateResult:
    """Brings the original branch's release into the translation and copies
    its assets. `release`, the folder the update was applied from, rebuilds
    a pending asset record that can no longer be read."""
    return _apply_registered(
        inspect_repository(translated_game), auto_resolve=auto_resolve, release=release
    )


def _apply_registered(
    status: RepositoryStatus,
    *,
    auto_resolve: bool = True,
    release: str | Path | None = None,
) -> UpdateResult:
    """`apply_registered_original` on the status its entry point read."""
    if not status.repo_root or not status.original_commit or not status.original_version:
        raise GitWorkflowError("The original branch has no recorded version to apply")
    _configure_exact_tree_repo(status.repo_root)
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before updating"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before updating")
    if status.translation_version == status.original_version:
        if not status.asset_sync_pending:
            raise GitWorkflowError("The translated branch already has this original version")
        result = UpdateResult(
            status.repo_root,
            status.original_commit,
            status.translation_commit,
            status.original_version,
            content_changed=False,
        )
        return _complete_pending_asset_plan(status, result, release)
    result = _cherry_pick(
        status,
        status.original_commit,
        status.original_version,
        auto_resolve=auto_resolve,
    )
    return (
        _complete_pending_asset_plan(status, result, release)
        if result.complete
        else result
    )


def continue_with_official(
    translated_game: str | Path, release: str | Path | None = None
) -> UpdateResult:
    """Finishes a stopped update; `release` as for `apply_registered_original`."""
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if status.repo_root and not status.pending_cherry_pick and status.asset_update_applied:
        # The update stopped once the translation had it; its assets remain.
        return _apply_registered(status, release=release)
    if not status.repo_root or not status.pending_cherry_pick:
        raise GitWorkflowError("There is no pending cherry-pick to continue")
    _configure_exact_tree_repo(status.repo_root)
    original_commit = _run_git(
        status.repo_root, "rev-parse", "CHERRY_PICK_HEAD"
    ).stdout.strip()
    version = _version_from_history(status.repo_root, original_commit, original_commit) or "unknown"
    won = _resolve_conflicts_with_official(status.repo_root, status.game_prefix)
    translated_commit = _finish_cherry_pick(status.repo_root, original_commit)
    result = UpdateResult(
        status.repo_root, original_commit, translated_commit, version, won
    )
    return _complete_pending_asset_plan(status, result, release)


def abort_update(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    stopped_before_translation = (
        status.asset_sync_pending and not status.asset_update_applied
    )
    if not status.repo_root or not (
        status.pending_cherry_pick or stopped_before_translation
    ):
        raise GitWorkflowError("There is no pending update to cancel")
    repo = status.repo_root
    _configure_exact_tree_repo(repo)
    # The update being cancelled moved the original branch to its release and
    # left its assets to synchronize once applied; cancelling puts both back.
    try:
        plan = _load_pending_asset_plan(repo, status.game_prefix)
    except GitWorkflowError:
        # A damaged record only says what to copy, so cancelling goes by the
        # original branch's release, which the stopped update moved.
        plan = {"original_commit": status.original_commit}
    if status.pending_cherry_pick:
        picked = _run_git(repo, "rev-parse", "CHERRY_PICK_HEAD").stdout.strip()
        _run_git(repo, "cherry-pick", "--abort")
    else:
        picked = plan["original_commit"]
    if plan is not None and plan["original_commit"] == picked:
        _cancel_pending_update(
            repo,
            status.game_prefix,
            picked,
            _run_git(repo, "rev-parse", f"{picked}^").stdout.strip(),
        )
    return inspect_repository(game)
