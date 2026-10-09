"""Check for and apply WolfDawn ``wolf`` binary updates (maintainer-only upstream fetch).

End users receive prebuilt binaries under ``util/wolfdawn/bin/<platform>/`` via
DazedTL updates. Maintainers refresh them with ``--refresh-all`` or ``--force``,
which record the upstream commit each platform was built from in the committed
``.wolf_version.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

from util.wolfdawn import (
    WolfDawnError,
    _latest_release_asset,
    _platform_dir,
    bundled_binary_path,
    download_wolf_binary,
)
from util.wolfdawn.build_tools import (
    build_and_install_platforms,
    upstream_commit,
)

_PKG_ROOT = Path(__file__).resolve().parent
VERSION_FILE = _PKG_ROOT / ".wolf_version.json"
BUNDLED_PLATFORMS: tuple[str, ...] = ("linux", "windows")


def _load_versions() -> dict:
    if not VERSION_FILE.is_file():
        return {}
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_versions(data: dict) -> None:
    VERSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _refresh_from_release(platform: str, log_fn=print) -> str | None:
    asset = _latest_release_asset(platform)
    if not asset:
        return None
    tag, _ = asset
    try:
        download_wolf_binary(platform=platform, log_fn=log_fn)
    except WolfDawnError as exc:
        _log(f"Warning: release download failed for {platform} ({exc}).", log_fn)
        return None
    return tag


def refresh_wolfdawn_binary(
    platform: str | None = None,
    *,
    platforms: Sequence[str] | None = None,
    log_fn=print,
) -> bool:
    """Rebuild WolfDawn binaries from upstream source.

    A release download only fills a missing binary: the newest release can be
    older than the bundled build, so it never replaces one.
    """
    targets = tuple(platforms or (platform or _platform_dir(),))
    try:
        upstream = upstream_commit()
    except Exception as exc:
        _log(f"ERROR: could not contact WolfDawn upstream ({exc})", log_fn)
        return False

    _log(f"Upstream WolfDawn commit: {upstream[:12]}", log_fn)
    source_results = build_and_install_platforms(
        tuple(p for p in targets if p in BUNDLED_PLATFORMS),
        log_fn=log_fn,
    )

    ok = True
    versions = _load_versions()
    platform_versions = versions.get("platforms")
    if not isinstance(platform_versions, dict):
        platform_versions = {}
    versions = {"platforms": platform_versions}

    for plat in targets:
        if source_results.get(plat):
            platform_versions[plat] = upstream
            _log(f"WolfDawn updated from source ({plat}, {upstream[:12]})", log_fn)
            continue

        if bundled_binary_path(plat).is_file():
            _log(
                f"ERROR: could not build WolfDawn for '{plat}' from source; kept the "
                "bundled binary. Building needs cargo, plus x86_64-w64-mingw32-gcc "
                "for Windows on Linux.",
                log_fn,
            )
            ok = False
            continue

        tag = _refresh_from_release(plat, log_fn=log_fn)
        if tag:
            platform_versions[plat] = tag
            _log(f"WolfDawn installed from release ({plat}, {tag})", log_fn)
            continue

        _log(f"ERROR: no WolfDawn binary available for '{plat}'.", log_fn)
        ok = False

    _save_versions(versions)
    return ok


def ensure_wolfdawn_binary(force: bool = False, log_fn=print) -> bool:
    """Ensure the bundled ``wolf`` binary is present (no upstream fetch by default)."""
    platform = _platform_dir()
    bundled = bundled_binary_path(platform)

    if force:
        if refresh_wolfdawn_binary(platforms=BUNDLED_PLATFORMS, log_fn=log_fn):
            return bundled_binary_path(platform).is_file()
        if bundled.is_file():
            _log("Warning: WolfDawn update failed; using bundled copy.", log_fn)
            return True
        _log("ERROR: WolfDawn update failed.", log_fn)
        return False

    if bundled.is_file():
        return True
    _log(
        f"ERROR: no bundled WolfDawn binary for '{platform}' at {bundled}. "
        "Update DazedTL to receive a prebuilt wolf binary.",
        log_fn,
    )
    return False


def main() -> int:
    if "--refresh-all" in sys.argv:
        return 0 if refresh_wolfdawn_binary(platforms=BUNDLED_PLATFORMS) else 1
    force = "--force" in sys.argv or "-f" in sys.argv
    return 0 if ensure_wolfdawn_binary(force=force) else 1


if __name__ == "__main__":
    raise SystemExit(main())
