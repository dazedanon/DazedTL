"""Work a game folder keeps for another project, and the user's way on.

Plugin files and Images save their progress inside the game folder, bound to
the project that saved it. Projects are keyed by the game's path, so a moved or
copied game, a new profile or a reinstall opens the same folder as a new
project. Its saved work is then neither used nor discarded until the user
chooses: the feature takes it over after rechecking what it can, or starts over
with the saved files moved aside under a dated name.
"""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeIs

from dazedtl.translation.files import project_path

ARCHIVE = ".dazedtl/archived"
UNREADABLE = "This version of DazedTL can't read it; start over to set it aside."
INTERRUPTED = (
    "An Apply or Restore was interrupted while the other project wrote to the "
    "game, and only that project can check which files it changed. Finish it "
    "there, or start over."
)


class ForeignWorkError(ValueError):
    """Saved work belongs to another project or app version; nothing changed.

    The summary is what the feature's choice shows, including the binding the
    chosen recovery must repeat.
    """

    def __init__(self, message, summary):
        super().__init__(message)
        self.summary = summary


def owned(value, project_id) -> TypeIs[dict[str, Any]]:
    """Whether saved state is this project's, in the version this app reads."""
    return (
        isinstance(value, dict)
        and value.get("version") == 1
        and value.get("projectId") == project_id
    )


def readable(value) -> TypeIs[dict[str, Any]]:
    """Whether another project's saved state is in a version this app reads."""
    return (
        isinstance(value, dict)
        and value.get("version") == 1
        and isinstance(value.get("projectId"), str)
    )


def binding(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def summary(path):
    """The fields every feature's choice shares."""
    return {
        "binding": binding(path),
        "saved": datetime.fromtimestamp(Path(path).stat().st_mtime, UTC).isoformat(),
        "archive": ARCHIVE,
    }


def reviewed(path, summary, shown):
    """The saved work's bytes, when they are what the user was shown: a choice
    applies only to that work."""
    raw = Path(path).read_bytes()
    if shown != summary["binding"] or hashlib.sha256(raw).hexdigest() != shown:
        raise ValueError("The saved work changed since it was shown. Review it again.")
    return raw


def archive(root, relative, name):
    """Moves a work folder under ARCHIVE with a dated name, keeping every file."""
    source = project_path(root, relative, exists=False)
    if not source.is_dir():
        raise ValueError("The saved work folder is missing.")
    folder = project_path(root, ARCHIVE + "/" + name, exists=False).parent
    folder.mkdir(parents=True, exist_ok=True)
    stamp = name + "-" + datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    target = folder / stamp
    count = 1
    while target.exists():
        count += 1
        target = folder / (stamp + "-" + str(count))
    os.rename(source, target)
    return target.relative_to(Path(root).resolve()).as_posix()
