"""Repository status reused across polls while Git's own metadata is unchanged."""

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from dazedtl.freshness import signature

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


def file_signature(path):
    """A file's stat signature, or None while it is missing."""
    try:
        return signature(os.stat(path))
    except OSError:
        return None


def repository_signature(root, *, index=True):
    """What changes when the repository's metadata changes, from a few stats.
    Without `index`, what changes with refs, HEAD, config, logs and operations
    under way: `git status` rewrites the index for about a second after a
    write, which it reports no change by."""
    git = Path(root) / ".git"
    try:
        head = git.stat()
    except OSError:
        return None
    if not git.is_dir():
        return (head.st_mtime_ns, head.st_size)
    parts = []
    for name in MARKERS:
        if name == "index" and not index:
            continue
        try:
            value = (git / name).stat()
            parts.append((name, value.st_mtime_ns, value.st_size))
        except OSError:
            parts.append((name, None, None))
    for tree in TREES:
        parts.extend(_files(git / tree))
    return tuple(parts)


def metadata_signature(root):
    """`repository_signature` without the index."""
    return repository_signature(root, index=False)


def checkout_signature(root):
    """What a read of a game's checkout depends on (engine `read_checkout`),
    from a few file reads: the branch HEAD is on, the repository's settings,
    which branches there are, the operations under way and game updates'
    records. A checkpoint moves its branch and rewrites the index, neither
    of which the read depends on but for the branch being there, so a game's
    writes reuse one read; a branch switch rewrites HEAD. None without a
    .git folder of the game's own, whose metadata Git keeps elsewhere."""
    from util.version_update.git_workflow import PENDING_OPERATIONS

    git = Path(root) / ".git"
    if not git.is_dir():
        return None

    def content(name):
        try:
            return (git / name).read_bytes()
        except OSError:
            return None

    branches = sorted(entry[:2] for entry in _files(git / "refs/heads"))
    updates = sorted(_files(git / "dazedtl/version-update"), key=lambda e: e[:2])
    return (
        content("HEAD"),
        content("config"),
        file_signature(git / "packed-refs"),
        tuple(branches),
        tuple((git / name).exists() for name in PENDING_OPERATIONS),
        tuple(updates),
    )


def _files(tree):
    """Each file under `tree` with its stat signature, as a walk finds them."""
    found = []
    for folder, _directories, files in os.walk(tree):
        for name in files:
            try:
                value = os.stat(os.path.join(folder, name))
                found.append((folder, name, value.st_mtime_ns, value.st_size))
            except OSError:
                found.append((folder, name, None, None))
    return found


class RepositoryStatusCache:
    """Reuses a status while its repository signature holds, for at most `ttl` seconds.

    Working-tree changes do not move the signature, so the window bounds how
    long a dirty or clean tree can be reported late. A `stable` status, which
    Git's metadata alone decides, is reused for as long as the signature
    holds, unless the root has no .git of its own to sign. Failures are reused
    for the window only: each attempt costs the same process launches.
    `signer` signs what the status reads of the repository, by default all
    of Git's metadata; it returns None when it can't sign the root.
    """

    def __init__(
        self,
        ttl=5.0,
        clock=time.monotonic,
        *,
        stable=False,
        signer: Callable[[Path], object] = repository_signature,
    ):
        self.ttl = ttl
        self.clock = clock
        self.stable = stable
        self.signer = signer
        self.entries = {}

    def get[T](self, key, root, compute: Callable[[], T], extra=()) -> T:
        """`extra` adds what else the status reads, such as files Git ignores."""
        signature = (self.signer(Path(root)), extra)
        now = self.clock()
        entry = self.entries.get(key)
        lasting = (
            self.stable
            and signature[0] is not None
            and (entry is None or entry[3] is None)
        )
        if not (
            entry and entry[0] == signature and (lasting or now - entry[1] < self.ttl)
        ):
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
