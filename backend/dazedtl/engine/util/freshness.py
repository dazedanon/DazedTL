"""Whether saved work is still current: the one rule.

Saved work - an estimate, a prepared Batch, a request plan, a speaker scan,
event text findings, a Plugin files or Images task, a Text QA task, a VX Ace
packing receipt - records the Basis it was made from:

- ``version``: an explicit constant of its kind. Raise it when DazedTL starts
  producing different work from the same inputs; the work then reads outdated
  once.
- ``inputs``: a digest per input the work read, such as game files, guidance
  files or a report, by name.
- ``settings``: a digest of only the settings that change the work.
- ``shape``: the same settings without the ones that only set a price, for
  kinds whose saved counts can be repriced after a model switch.
- ``prices``: for a priced figure, such as a quote or an estimate, the price
  rules version it was priced under (provider_costs.PRICE_RULES_VERSION).

``compare(saved, current)`` is None while the work is current, otherwise the
Change naming what differs. A Change that is ``priced_only`` leaves the work's
counts current and only its price not, which translation/repricing prices
again where it can. Code changes alone never outdate saved work: never
digest DazedTL's or the engine's source files into a basis, raise the kind's
version instead.

Each kind reads its own saved records into a Basis, including records an
older release saved in another form: when the old digest is what that release
would have saved for the current work, the record reads as the current basis,
so an upgrade alone never outdates saved work. A record whose inputs cannot be
named reads with ``inputs`` None and compares as changed.

File digests are reused by stat ``signature`` only once the file has been still
for longer than one clock tick (``settled``): a file written twice within one
tick keeps its size and times, so a younger file is read again every time.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Mapping

from util import system

# File times advance in ticks of milliseconds, so a file written twice within
# one tick can keep its stat signature. Caches keyed by signatures keep only
# files that have been still for longer than this.
SETTLED_NS = 2_000_000_000


def settled(*modified_ns: int) -> bool:
    """Whether every one of these modification times is safely in the past."""
    return time.time_ns() - max(modified_ns) > SETTLED_NS


def signature(info: os.stat_result) -> tuple:
    """A file's stat signature: it changes whenever the file is replaced or
    written, except twice within one clock tick (see ``settled``)."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def signature_settled(stamp: tuple | None) -> bool:
    """Whether the file a ``signature`` describes has settled; a missing
    file (None) has nothing left to change."""
    return stamp is None or settled(stamp[3])


class Digests:
    """Values by key, reused while the key's stat signature holds.

    Every poll checks every saved run's outputs, so the files one poll needs
    grow with the run history. Dropping all entries, or the oldest, once a
    long history outgrew a fixed bound reread every output on every poll; only
    entries no read has used for a while are dropped.
    """

    IDLE_SECONDS = 120

    def __init__(self, limit: int = 20_000):
        self.limit = limit
        self.entries: dict = {}
        # How many entries the last prune kept: pruning again waits until the
        # cache doubles, so a large working set is not scanned on every insert.
        self.kept = 0
        self.lock = threading.Lock()

    def get(self, key, stamp):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None or entry[0] != stamp:
                return None
            entry[2] = time.monotonic()
            return entry[1]

    def put(self, key, stamp, value):
        now = time.monotonic()
        with self.lock:
            self.entries[key] = [stamp, value, now]
            if len(self.entries) > max(self.limit, 2 * self.kept):
                self.entries = {
                    name: entry
                    for name, entry in self.entries.items()
                    if now - entry[2] < self.IDLE_SECONDS
                }
                self.kept = len(self.entries)

    def remember(self, key, info: os.stat_result, read):
        """``read()``'s value for the file ``info`` describes, reused while its
        signature holds and kept only once the file has settled."""
        stamp = signature(info)
        cached = self.get(key, stamp)
        if cached is not None:
            return cached
        value = read()
        if settled(info.st_mtime_ns):
            self.put(key, stamp, value)
        return value

    def file(self, path, info: os.stat_result | None = None) -> str:
        """A regular file's SHA-256, read again only after it changed.

        ``info`` is the file's own lstat result when the caller has it.
        """
        key = os.fspath(path)

        def read():
            with system.open_read(key) as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()

        return self.remember(key, info or os.lstat(key), read)


@dataclass(frozen=True)
class Basis:
    """What a piece of saved work was made from; see the module docstring."""

    version: object
    inputs: Mapping[str, object] | None = None
    settings: object = None
    shape: object = None
    prices: object = None

    def record(self) -> dict:
        """The basis as saved JSON."""
        value = {"version": self.version, "inputs": dict(self.inputs or {})}
        if self.settings is not None:
            value["settings"] = self.settings
        if self.shape is not None:
            value["shape"] = self.shape
        if self.prices is not None:
            value["prices"] = self.prices
        return value

    @classmethod
    def read(cls, value) -> Basis | None:
        """A basis saved by ``record``, or None for anything else."""
        if not isinstance(value, dict) or not isinstance(value.get("inputs"), dict):
            return None
        return cls(
            version=value.get("version"),
            inputs=value["inputs"],
            settings=value.get("settings"),
            shape=value.get("shape"),
            prices=value.get("prices"),
        )


@dataclass(frozen=True)
class Change:
    """What differs between a saved basis and the current one."""

    missing: bool = False
    version: bool = False
    settings: bool = False
    # The settings changed more than what prices the work.
    reshaped: bool = False
    # It was priced under other price rules.
    prices: bool = False
    added: tuple = ()
    removed: tuple = ()
    changed: tuple = ()
    # An older record names no inputs, so only "something changed" is known.
    unnamed: bool = False

    @property
    def inputs(self) -> tuple:
        """Every input name that was added, removed or changed."""
        return self.added + self.removed + self.changed

    @property
    def priced_only(self) -> bool:
        """Whether only what prices the work changed, its price rules or
        settings that keep its shape, so its counts still hold."""
        return not (
            self.missing or self.version or self.unnamed or self.reshaped or self.inputs
        )

    @property
    def rules_only(self) -> bool:
        """Whether only the price rules the work was priced under changed."""
        return self.priced_only and not self.settings


def compare(
    saved: Basis | None, current: Basis, *, prices_unknown: bool = False
) -> Change | None:
    """None while work saved on ``saved`` is current, else what changed.

    ``prices_unknown`` is true when the settings differ only in prices that are
    not known at the moment (``translation/repricing.py``); with an unchanged
    shape the settings then still count as the same.
    """
    if saved is None:
        return Change(missing=True)
    if saved.version != current.version:
        return Change(version=True)
    same_shape = saved.shape is not None and saved.shape == current.shape
    if saved.inputs is None:
        return Change(unnamed=True)
    old, new = dict(saved.inputs), dict(current.inputs or {})
    settings = saved.settings != current.settings and not (
        same_shape and prices_unknown
    )
    change = Change(
        settings=settings,
        reshaped=settings and not same_shape,
        prices=saved.prices != current.prices,
        added=tuple(sorted(set(new) - set(old))),
        removed=tuple(sorted(set(old) - set(new))),
        changed=tuple(sorted(name for name in old.keys() & new.keys() if old[name] != new[name])),
    )
    return change if change.settings or change.prices or change.inputs else None
