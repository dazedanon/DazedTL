"""Repository status reused across polls while Git's own metadata is unchanged."""

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

# Files Git rewrites for every ref, index, config or in-progress operation
# change; logs/HEAD records every checkout, commit and reset.
MARKERS = (
    "HEAD",
    "index",
    "packed-refs",
    "config",
    "logs/HEAD",
    "ORIG_HEAD",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
    "BISECT_LOG",
)
# Trees whose files change without touching a marker above.
TREES = ("refs", "dazedtl/version-update")


def repository_signature(root):
    """What changes when the repository's metadata changes, from a few stats."""
    git = Path(root) / ".git"
    try:
        head = git.stat()
    except OSError:
        return None
    if not git.is_dir():
        return (head.st_mtime_ns, head.st_size)
    parts = []
    for name in MARKERS:
        try:
            value = (git / name).stat()
            parts.append((name, value.st_mtime_ns, value.st_size))
        except OSError:
            parts.append((name, None, None))
    for tree in TREES:
        for folder, _directories, files in os.walk(git / tree):
            for name in files:
                try:
                    value = os.stat(os.path.join(folder, name))
                    parts.append((folder, name, value.st_mtime_ns, value.st_size))
                except OSError:
                    parts.append((folder, name, None, None))
    return tuple(parts)


class RepositoryStatusCache:
    """Reuses a status while its repository signature holds, for at most `ttl` seconds.

    Working-tree changes do not move the signature, so the window bounds how
    long a dirty or clean tree can be reported late. Failures are reused for
    the same window: each attempt costs the same process launches.
    """

    def __init__(self, ttl=5.0, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self.entries = {}

    def get[T](self, key, root, compute: Callable[[], T]) -> T:
        signature = repository_signature(root)
        now = self.clock()
        entry = self.entries.get(key)
        if not (entry and entry[0] == signature and now - entry[1] < self.ttl):
            try:
                entry = (signature, now, compute(), None)
            except Exception as exc:  # noqa: BLE001
                entry = (signature, now, None, exc)
            self.entries[key] = entry
        if entry[3] is not None:
            raise entry[3]
        return cast(T, entry[2])

    def clear(self):
        self.entries.clear()
