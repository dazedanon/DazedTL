"""GameUpdate's ``gameupdate/patch-config.txt``: where players download the patch.

GameUpdate and the RPG Maker startup check read forge, host, username, repo and
branch from this one file. DazedTL writes it from the GameUpdate defaults in
Settings plus the game's own repository, which its ``.dazedtl/settings.json``
keeps (pre-filled from the ``origin`` remote under the configured owner). A
file that was edited after DazedTL wrote it is never overwritten silently: its
differing values are reported until the user keeps them or replaces them.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values

CONFIG = "gameupdate/patch-config.txt"
FIELDS = ("forge", "host", "username", "repo", "branch")
# Values a game can set for itself instead of following Settings.
OVERRIDES = ("forge", "host", "username", "branch")

# .env keys (engine settings)
ENV_FORGE = "gameUpdateForge"
ENV_HOST = "gameUpdateHost"
ENV_USERNAME = "gameUpdateUsername"
ENV_BRANCH = "gameUpdateBranch"

DEFAULT_FORGE = "gitlab"
DEFAULT_HOST = "gitgud.io"
DEFAULT_BRANCH = "main"

_FORGE_HOST_DEFAULTS = {
    "gitlab": "gitgud.io",
    "github": "github.com",
    "forgejo": "codeberg.org",
}
# GameUpdate's own aliases (patch.ps1, patch.sh, TranslationUpdateCheck.js).
_FORGE_ALIASES = {
    "": "gitlab",
    "gitlab": "gitlab",
    "gl": "gitlab",
    "gitgud": "gitlab",
    "github": "github",
    "gh": "github",
    "forgejo": "forgejo",
    "gitea": "forgejo",
    "fj": "forgejo",
    "codeberg": "forgejo",
}
_KEY_ALIASES = {"provider": "forge", "owner": "username", "org": "username"}
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?")
# patch.sh reads the file as shell, so owners and branches keep to path-like
# names; GitLab groups nest with slashes.
_PATH = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")


def forge_kind(raw: str | None) -> str | None:
    """GameUpdate's forge for a ``forge=`` value, or None when it rejects it."""
    return _FORGE_ALIASES.get((raw or "").strip().lower())


def normalize_forge(raw: str | None) -> str:
    return forge_kind(raw) or DEFAULT_FORGE


def default_host_for_forge(forge: str) -> str:
    return _FORGE_HOST_DEFAULTS.get(normalize_forge(forge), DEFAULT_HOST)


def normalize_host(raw: str | None) -> str:
    """A host as GameUpdate reads it: no scheme, path or spaces."""
    value = re.sub(r"\s", "", raw or "").lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    return value.split("/")[0]


def check_defaults(values: dict[str, str], *, owner_required=True) -> dict[str, str]:
    """Normalized forge, host, owner and branch, or a ValueError naming what to fix.

    Settings may leave the owner empty, which leaves GameUpdate unconfigured.
    """
    forge = forge_kind(values.get("forge"))
    if forge is None:
        raise ValueError("Choose GitLab, Forgejo or GitHub for GameUpdate.")
    host = normalize_host(values.get("host")) or default_host_for_forge(forge)
    username = (values.get("username") or "").strip().strip("/")
    branch = (values.get("branch") or "").strip()
    if not _HOST.fullmatch(host) or "." not in host.split(":")[0]:
        raise ValueError("Enter the GameUpdate host name, such as gitgud.io.")
    if (owner_required or username) and (not username or placeholder(username)):
        raise ValueError("Set the GameUpdate owner in Settings > GameUpdate.")
    if username and not _PATH.fullmatch(username):
        raise ValueError(
            "Use letters, numbers, dots, dashes and underscores for the GameUpdate owner."
        )
    if not _PATH.fullmatch(branch) or branch.startswith(".") or ".." in branch:
        raise ValueError("Enter the GameUpdate branch, such as main.")
    return {"forge": forge, "host": host, "username": username, "branch": branch}


def check(values: dict[str, str]) -> dict[str, str]:
    """Complete, normalized values, or a ValueError naming what to fix."""
    checked = check_defaults(values)
    return {**checked, "repo": check_repo(values.get("repo"))}


def placeholder(value: str) -> bool:
    return value.strip().upper().startswith("YOUR_")


def parse(text: str) -> dict[str, str]:
    """A config's keys as GameUpdate reads them: case-insensitive, with
    aliases, and a later line replacing an earlier one."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        key = _KEY_ALIASES.get(key, key)
        if key in FIELDS:
            values[key] = value.strip()
    return values


def file_values(text: str) -> dict[str, str] | None:
    """The values players get from a config, or None while it cannot work."""
    try:
        return check(parse(text))
    except ValueError:
        return None


def format_patch_config(values: dict[str, str]) -> str:
    """The compact file DazedTL writes; refuses incomplete values."""
    values = check(values)
    lines = [
        "# GameUpdate downloads the translation patch from this repository.",
        "# DazedTL writes this file from Settings > GameUpdate and the game's Project page.",
        *(f"{key}={values[key]}" for key in FIELDS),
        "",
    ]
    return "\n".join(lines)


def load_gameupdate_defaults(env_path: str | Path | None = None) -> dict[str, str]:
    """Return forge/host/username/branch from .env (with process env fallback)."""
    path = Path(env_path) if env_path is not None else Path(".env")
    file_vals = dotenv_values(path) if path.is_file() else {}

    def _get(key: str, default: str = "") -> str:
        raw = file_vals.get(key)
        if raw is None or str(raw).strip() == "":
            raw = os.getenv(key, default)
        return str(raw or default).strip()

    forge = normalize_forge(_get(ENV_FORGE, DEFAULT_FORGE))
    return {
        "forge": forge,
        "host": normalize_host(_get(ENV_HOST, "")) or default_host_for_forge(forge),
        "username": _get(ENV_USERNAME, ""),
        "branch": _get(ENV_BRANCH, DEFAULT_BRANCH) or DEFAULT_BRANCH,
    }


# ---------------------------------------------------------------- remotes


def _git(root: Path, *args: str):
    """A read that reports no result when Git cannot run, rather than failing."""
    from util.version_update import GitWorkflowError
    from util.version_update.git_workflow import _run_git

    try:
        return _run_git(root, *args, check=False, timeout=30)
    except GitWorkflowError:
        return subprocess.CompletedProcess(args, 1, "", "")


def remote_urls(game_root: str | Path) -> dict[str, list[str]]:
    """Each remote's fetch URL, then its push URLs, for a game that is its own
    repository."""
    root = Path(game_root)
    if not (root / ".git").exists():
        return {}
    listed = _git(root, "config", "--get-regexp", r"^remote\..+\.(url|pushurl)$")
    remotes: dict[str, list[str]] = {}
    for line in listed.stdout.splitlines():
        key, _, url = line.partition(" ")
        name, _, kind = key[len("remote.") :].rpartition(".")
        urls = remotes.setdefault(name, [])
        if url.strip():
            urls.insert(0 if kind == "url" else len(urls), url.strip())
    return remotes


def url_location(url: str) -> tuple[str, str]:
    """A remote URL's host and ``owner/repo`` path, for https and scp-style URLs."""
    url = url.strip()
    if "://" in url:
        rest = url.split("://", 1)[1]
        authority, _, path = rest.partition("/")
    else:
        authority, _, path = url.partition(":")
    host = authority.rsplit("@", 1)[-1].split(":")[0].lower()
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return host, path


def _site(host: str) -> str:
    """Hosts of one forge share a site: gitgud.io and ssh.gitgud.io, or
    git.dazedtl.dev and git-ssh.dazedtl.dev."""
    return ".".join(host.split(":")[0].split(".")[-2:])


def origin_repo(remotes: dict[str, list[str]], owner: str) -> str:
    """The repository name ``origin`` fetches from under ``owner``, or ""."""
    urls = remotes.get("origin") or []
    if not urls or not owner:
        return ""
    _host, path = url_location(urls[0])
    namespace, _, name = path.rpartition("/")
    if namespace.casefold() != owner.strip("/").casefold() or not _NAME.fullmatch(name):
        return ""
    return name


def remote_problem(values: dict[str, str], remotes: dict[str, list[str]]) -> str:
    """Why no remote is where players' GameUpdate downloads from, or ""."""
    locations = [url_location(url) for urls in remotes.values() for url in urls]
    if not locations:
        return ""
    target = f"{values['username']}/{values['repo']}"
    there = [path for host, path in locations if _site(host) == _site(values["host"])]
    if any(path.casefold() == target.casefold() for path in there):
        return ""
    if there:
        return (
            f"Players' GameUpdate downloads {values['host']}/{target}, "
            f"but this game's Git remote there is {there[0]}."
        )
    hosts = ", ".join(sorted({host for host, _path in locations if host}))
    return (
        f"Players' GameUpdate downloads from {values['host']}, "
        f"but this game's Git remotes are on {hosts}."
    )


def committed_values(game_root: str | Path, branch: str) -> dict[str, str] | None:
    """The working config's values in ``branch``'s commit, or None without one."""
    shown = _git(Path(game_root), "show", f"refs/heads/{branch}:{CONFIG}")
    return file_values(shown.stdout) if shown.returncode == 0 else None


# ------------------------------------------------------------------ state


def installed(game_root: str | Path) -> bool:
    folder = Path(game_root) / "gameupdate"
    return (folder / "patch.ps1").is_file() or (folder / "patch.sh").is_file()


def check_repo(repo: str | None) -> str:
    repo = (repo or "").strip()
    if not repo or placeholder(repo):
        raise ValueError("Enter the game's GameUpdate repository.")
    if not _NAME.fullmatch(repo) or repo.startswith("."):
        raise ValueError(
            "Use letters, numbers, dots, dashes and underscores for the repository name."
        )
    return repo


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(game_root: Path) -> tuple[bytes | None, dict[str, str] | None]:
    path = game_root / CONFIG
    if path.is_symlink() or not path.is_file():
        return None, None
    data = path.read_bytes()
    return data, file_values(data.decode("utf-8", errors="replace"))


def _merged(defaults: dict[str, str], saved: dict[str, str]) -> dict[str, str]:
    """Settings' values with the game's own in their place; no repository."""
    values = {key: defaults.get(key, "") for key in OVERRIDES}
    values.update({key: saved[key] for key in OVERRIDES if saved.get(key)})
    values["forge"] = normalize_forge(values["forge"])
    values["host"] = normalize_host(values["host"]) or default_host_for_forge(
        values["forge"]
    )
    values["username"] = values["username"].strip().strip("/")
    values["branch"] = values["branch"].strip()
    return values


def _own(found: dict[str, str], defaults: dict[str, str], data: bytes) -> dict:
    """A record keeping a working config: its repository and the values where
    it differs from Settings."""
    base = _merged(defaults, {})
    record = {key: found[key] for key in OVERRIDES if found[key] != base[key]}
    return {**record, "repo": found["repo"], "written": digest(data)}


def _evaluate(saved, defaults, data, found, suggested):
    """The state, the values DazedTL wants (None while incomplete) and the
    values to show."""
    if found and data is not None and not saved.get("written") and not saved.get("repo"):
        # A working config DazedTL has not seen before is the game's own.
        return "ready", found, found
    values = {**_merged(defaults, saved), "repo": saved.get("repo") or suggested}
    if not values["username"]:
        return "unconfigured", None, values
    if not values["repo"]:
        return "needs_repo", None, values
    try:
        wanted = check(values)
    except ValueError:
        return "unconfigured", None, values
    if found == wanted:
        return "ready", wanted, wanted
    if found is None or data is not None and saved.get("written") == digest(data):
        return "pending", wanted, wanted
    return "edited", wanted, wanted


_MESSAGES = {
    "unconfigured": "Set the GameUpdate owner in Settings > GameUpdate.",
    "needs_repo": "Enter the game's GameUpdate repository on the Project page.",
}


def _status(root: Path, defaults, saved, data, found, remotes) -> dict:
    present = installed(root)
    suggested = origin_repo(remotes, _merged(defaults, saved)["username"])
    result = {
        "installed": present,
        "repo": saved.get("repo", ""),
        "suggested": suggested,
        "overrides": [key for key in OVERRIDES if saved.get(key)],
        "file": found,
        "placeholder": data is not None and found is None,
        "differences": [],
        "committed": False,
        "remote": "",
    }
    if not present and data is None:
        return {**result, "state": "absent", "values": None, "message": ""}
    state, wanted, values = _evaluate(saved, defaults, data, found, suggested)
    if state == "edited":
        result["differences"] = [key for key in FIELDS if found[key] != wanted[key]]
    current = found or wanted
    if current:
        result["remote"] = remote_problem(current, remotes)
    if found and (root / ".git").exists():
        result["committed"] = committed_values(root, found["branch"]) == found
    return {**result, "state": state, "values": values, "message": _MESSAGES.get(state, "")}


def status(game_root: str | Path, defaults: dict[str, str]) -> dict:
    """Where the config stands; reads only.

    ``state`` is absent (no GameUpdate in the game), unconfigured (no owner in
    Settings), needs_repo, pending (DazedTL writes it next), edited (changed
    after DazedTL wrote it, values differ) or ready.
    """
    from util.game_settings import load_game_update

    root = Path(game_root)
    data, found = _read(root)
    return _status(root, defaults, load_game_update(root), data, found, remote_urls(root))


def _write(game_root: Path, values: dict[str, str]) -> str:
    """Atomically writes the compact config; returns the written bytes' digest."""
    folder = game_root / "gameupdate"
    for path in (folder, folder / "patch-config.txt"):
        if path.is_symlink():
            raise ValueError(f"GameUpdate's config cannot be written through a link: {path}")
    data = format_patch_config(values).encode("utf-8")
    folder.mkdir(exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".patch-config-", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, folder / "patch-config.txt")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest(data)


def reconcile(
    game_root: str | Path,
    defaults: dict[str, str],
    action: str = "sync",
    repo: str | None = None,
) -> dict:
    """Brings the config in line with the settings, then returns its status.

    ``sync`` adopts a working config DazedTL has not seen, writes one that is
    missing, a placeholder or outdated since DazedTL last wrote it, and leaves
    an edited one for the user. The user's choices: ``save`` a repository,
    ``keep`` an edited file's values for this game, ``replace`` them with
    DazedTL's, or follow Settings again with ``defaults``.
    """
    from util.game_settings import load_game_update, save_game_update

    if action not in {"sync", "save", "keep", "replace", "defaults"}:
        raise ValueError("Choose a GameUpdate action.")
    root = Path(game_root)
    saved = load_game_update(root)
    original = dict(saved)
    data, found = _read(root)
    remotes = remote_urls(root)
    if action == "save":
        saved["repo"] = check_repo(repo)
    elif action == "keep":
        if found is None or data is None:
            raise ValueError("GameUpdate's config has no complete values to keep.")
        saved = _own(found, defaults, data)
    elif action == "defaults":
        saved = {key: value for key, value in saved.items() if key not in OVERRIDES}
    suggested = origin_repo(remotes, _merged(defaults, saved)["username"])
    state, wanted, _values = _evaluate(saved, defaults, data, found, suggested)
    if found and data is not None and not saved.get("written") and not saved.get("repo"):
        saved = _own(found, defaults, data)
    elif wanted and found == wanted and data is not None:
        saved.update(repo=wanted["repo"], written=digest(data))
    elif wanted and installed(root) and (
        state == "pending" or action in {"save", "replace", "defaults"}
    ):
        saved.update(repo=wanted["repo"], written=_write(root, wanted))
    if saved != original:
        save_game_update(root, saved)
    data, found = _read(root)
    return _status(root, defaults, saved, data, found, remotes)
