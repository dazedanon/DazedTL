"""Public-release checks: the ZIP destination name and the GameUpdate version stamp.

Clean release ZIPs are built by ``dazedtl.translation.release``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class ReleasePackageError(RuntimeError):
    """Raised when a safe public-release archive cannot be produced."""


_PATCH_CONFIG_PATH = Path("gameupdate/patch-config.txt")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)


def normalize_release_zip_path(output_path: str | Path) -> Path:
    output = Path(output_path).expanduser()
    if output.suffix.casefold() != ".zip":
        output = output.with_name(output.name + ".zip")
    return output.resolve()


def _configured_patch_branch(root: Path) -> str | None:
    """Return the configured public patch branch, or None without a valid repo."""
    config_path = root / _PATCH_CONFIG_PATH
    if not config_path.is_file():
        return None
    try:
        values: dict[str, str] = {}
        for raw_line in config_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().casefold()
            if key in {"owner", "org"}:
                key = "username"
            values[key] = value.strip()
    except (OSError, UnicodeError):
        return None

    username = values.get("username", "")
    repo = values.get("repo", "")
    branch = values.get("branch", "")
    if not username or not repo or not branch:
        return None
    if username.upper().startswith("YOUR_") or repo.upper().startswith("YOUR_"):
        return None
    return branch


def _release_patch_sha(root: Path) -> str | None:
    """Identify the exact clean Git commit represented by a patchable release."""
    branch = _configured_patch_branch(root)
    if branch is None:
        return None

    def run_git(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return subprocess.CompletedProcess(args, 1, "", "")

    repo = run_git("rev-parse", "--show-toplevel")
    if repo.returncode != 0:
        return None

    current_branch = run_git("branch", "--show-current")
    current = current_branch.stdout.strip()
    if current_branch.returncode != 0 or current != branch:
        raise ReleasePackageError(
            "The GameUpdate branch is configured as "
            f"{branch!r}, but the release source is on {current or 'a detached HEAD'!r}."
        )

    status = run_git("status", "--porcelain", "--untracked-files=all", "--", ".")
    if status.returncode != 0:
        raise ReleasePackageError("Could not verify that the release source is clean")
    if status.stdout.strip():
        raise ReleasePackageError(
            "Commit the game changes before building a public release so its "
            "translation version can be identified exactly."
        )

    head = run_git("rev-parse", "HEAD")
    sha = head.stdout.strip()
    if head.returncode != 0 or not _GIT_SHA_RE.fullmatch(sha):
        raise ReleasePackageError("Could not identify the release source Git commit")

    upstream = run_git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    upstream_name = upstream.stdout.strip()
    if upstream.returncode != 0 or not upstream_name:
        raise ReleasePackageError(
            "The release branch must track the configured public branch before "
            "its translation version can be stamped."
        )
    if upstream_name != branch and not upstream_name.endswith("/" + branch):
        raise ReleasePackageError(
            f"The tracked branch {upstream_name!r} does not match the configured "
            f"GameUpdate branch {branch!r}."
        )
    upstream_head = run_git("rev-parse", "@{upstream}")
    if upstream_head.returncode != 0 or upstream_head.stdout.strip().lower() != sha.lower():
        raise ReleasePackageError(
            "Push the release commit to its tracked public branch before building "
            "the ZIP. This prevents players from receiving an unverifiable version marker."
        )
    return sha.lower()
