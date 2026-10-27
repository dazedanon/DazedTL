"""Values the Guided workspace derives from a game's files, kept in the profile.

Opening a big game counted every file's lines and read every selected event
file's built-in handlers again, which took seconds while every other request
waited. Each value here is a function of the bytes it was read from and the
inputs its key names, so it holds while those do, and a Store keeps it in
the project's Guided folder across restarts. A section names its own
version, which its owner raises when its code derives something else from
the same inputs (file_lines COUNT_VERSION, event_text MATCH_VERSION,
guided_runs LITERALS_VERSION for comparison literals); a
store of another format, or a section of another version, reads empty. The
store is a cache: deleting it only makes the next look read the files again.

A look that would read many files, such as the first at a big game or after
a Batch rewrote most of them, hands them to reader processes
([derived_worker](derived_worker.py)) and shows them as still being read
(`reading`), so the request returns at once; the next look finds what they
saved. Execution and explicit inspection read for themselves.

A run keeps its refusal verdicts the same way, in a Store beside its ledger
that each read of the ledger loads again (compatibility/process_view).
"""

import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from dazedtl import system

from .files import read_json

FORMAT = 1
NAME = "derived.json"
# A look reads files totaling at most this many bytes itself; reading more
# takes longer than a poll should wait, so readers take them.
INLINE_BYTES = 8_000_000
# Reader processes for one store at a time.
READERS = 4
# A reader saves what it read after this many values, so a stop keeps most.
SAVE_EVERY = 200

_stores: dict[str, Store] = {}
_lock = threading.Lock()


def key(*parts):
    """A section key: its parts as compact JSON."""
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def size(path):
    """A file's size in bytes, 0 when it cannot be read."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def store(folder):
    """The store of a project's Guided folder, read once per backend."""
    path = os.fspath(Path(folder) / NAME)
    with _lock:
        if path not in _stores:
            _stores[path] = Store(path)
        return _stores[path]


def close():
    """Stops every reader as DazedTL closes; what they saved stays."""
    with _lock:
        stores = list(_stores.values())
    for item in stores:
        item.stop()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        # One save writes at a time, so an older one cannot land last.
        self.saving = threading.Lock()
        self.sections: dict[str, dict] = self._load()
        # The sections this backend used, by kind ("lines" of "lines/2").
        self.used: dict[str, str] = {}
        self.changed = False
        # Keys readers are reading, and those a reader failed to read, which
        # looks then read themselves.
        self.reading: set[tuple[str, str]] = set()
        self.failed: set[tuple[str, str]] = set()
        self.processes: list = []

    def _load(self):
        try:
            value = read_json(self.path, limit=None)
        except OSError, ValueError:
            return {}
        if not isinstance(value, dict) or value.get("format") != FORMAT:
            return {}
        sections = value.get("sections")
        return {
            name: entries
            for name, entries in (
                sections if isinstance(sections, dict) else {}
            ).items()
            if isinstance(entries, dict)
        }

    def _use(self, section):
        # Under the lock.
        self.used[section.partition("/")[0]] = section
        return self.sections.get(section, {})

    def get(self, section, name, default: Any = None) -> Any:
        with self.lock:
            return self._use(section).get(name, default)

    def has(self, section, name):
        with self.lock:
            return name in self._use(section)

    def put(self, section, name, value):
        with self.lock:
            self._use(section)
            entries = self.sections.setdefault(section, {})
            if entries.get(name, self) != value:
                entries[name] = value
                self.changed = True

    def keep(self, section, names):
        """Drops the section's values outside `names`, the ones a whole look
        used, once they outnumber them: files change with every run."""
        with self.lock:
            entries = self.sections.get(section, {})
            if len(entries) > 2 * len(names) + 64:
                self.sections[section] = {
                    name: value for name, value in entries.items() if name in names
                }
                self.changed = True

    def save(self):
        with self.saving:
            with self.lock:
                # A folder Start over removed stays removed.
                if not self.changed or not self.path.parent.is_dir():
                    return
                # A kind's sections of other versions are left behind.
                self.sections = {
                    name: entries
                    for name, entries in self.sections.items()
                    if self.used.get(name.partition("/")[0], name) == name
                }
                raw = json.dumps(
                    {"format": FORMAT, "sections": self.sections},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.changed = False
            # Beside the store and never creating its folder, which Start over
            # may remove meanwhile.
            temporary = self.path.with_name(f".{NAME}.{secrets.token_hex(4)}.tmp")
            try:
                with open(temporary, "xb") as stream:
                    stream.write(raw)
                system.replace(temporary, self.path)
            except OSError:
                system.unlink(temporary, missing_ok=True, ignore_errors=True)
                with self.lock:
                    self.changed = True  # The next look saves again.

    def defer(self, section, missing, size, task):
        """Hands values a look misses to readers when reading them would hold
        it too long; returns the names it handed. `missing` maps each name
        to its key in `section`, `size(name)` gives the bytes it reads and
        `task(name, size)` its reader task. A value a reader failed stays
        with the look."""
        with self.lock:
            readable = [
                name
                for name, key in missing.items()
                if (section, key) not in self.failed
            ]
        sizes = {name: size(name) for name in readable}
        if sum(sizes.values()) <= INLINE_BYTES:
            return []
        self.read([task(name, sizes[name]) for name in readable])
        return readable

    def pending(self, section, name):
        """Whether a reader is reading the value now."""
        with self.lock:
            return (section, name) in self.reading

    def fail(self, section, name):
        """Notes a value no reader can read in this backend, such as an
        original Git cannot give, so looks stop asking for it."""
        with self.lock:
            self.failed.add((section, name))

    def readable(self, section, name):
        """Whether the value may be read: none failed it."""
        with self.lock:
            return (section, name) not in self.failed

    def read(self, tasks):
        """Starts readers for `tasks` no reader reads yet. Each task is a
        dict with its "section", "key", "size" in bytes and what
        derived_worker needs to read it."""
        with self.lock:
            tasks = [
                task
                for task in tasks
                if (task["section"], task["key"]) not in self.reading
            ]
            if not tasks:
                return
            self.reading.update((task["section"], task["key"]) for task in tasks)
            # The biggest first, each to the reader with the least so far.
            count = max(1, min(READERS, (os.cpu_count() or 2) // 2, len(tasks)))
            shares: list[list] = [[] for _ in range(count)]
            sizes = [0] * count
            for task in sorted(tasks, key=lambda task: -task["size"]):
                least = sizes.index(min(sizes))
                shares[least].append(task)
                sizes[least] += task["size"]
        for share in shares:
            self._start(share)

    def _start(self, tasks):
        try:
            process = system.popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(Path(__file__).with_name("derived_worker.py")),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                group=True,
            )
        except OSError:
            self._finish(tasks, set())
            return
        with self.lock:
            self.processes.append(process)
        threading.Thread(
            target=self._follow, args=(process, tasks), daemon=True
        ).start()

    def _follow(self, process, tasks):
        done = set()
        try:
            assert process.stdin is not None and process.stdout is not None
            # The tasks fit the pipe's buffer only in part; the reader reads
            # them all before it answers, so writing cannot wait on reading.
            process.stdin.write(json.dumps(tasks, ensure_ascii=False))
            process.stdin.close()
            for line in process.stdout:
                try:
                    value = json.loads(line)
                    section, name = value["section"], value["key"]
                except ValueError, KeyError, TypeError:
                    continue
                self.put(section, name, value["value"])
                done.add((section, name))
                if len(done) % SAVE_EVERY == 0:
                    self.save()
        except OSError, ValueError:
            pass  # A stopped reader; its keys are read again.
        finally:
            if process.stdout is not None:
                process.stdout.close()
            process.wait()
            self.save()
            self._finish(tasks, done, process)

    def _finish(self, tasks, done, process=None):
        with self.lock:
            for task in tasks:
                name = (task["section"], task["key"])
                self.reading.discard(name)
                # A value a reader skipped, such as a file it could not
                # read, is read by the next look itself.
                if name not in done:
                    self.failed.add(name)
            if process in self.processes:
                self.processes.remove(process)

    def stop(self):
        with self.lock:
            processes = list(self.processes)
        for process in processes:
            if process.poll() is None:
                system.stop_tree(process, force=True)


def run(tasks, emit):
    """Reads each task's value, as a reader process does, and gives `emit`
    its section, key and value; a value it cannot read is left out."""
    from dazedtl.compatibility import git_blobs

    # Original files Git reads for many tasks at once, by game folder: an
    # event file's built-in handlers, and the display name of a map whose
    # translated name keeps no source.
    originals: dict[str, dict[str, list]] = {}
    for task in tasks:
        if task["kind"] == "hits" and task.get("blob"):
            originals.setdefault(task["source"], {}).setdefault(
                task["blob"], []
            ).append(task)
            continue
        try:
            value = _read(task, git_blobs)
        except OSError, ValueError, Unread:
            continue  # The backend reads it again, and reports what fails.
        emit(task["section"], task["key"], value)
        names = task.get("names")
        if value and "mapName" in value and names:
            named = {**task, "kind": "name", "section": task["names_section"]}
            originals.setdefault(task["source"], {}).setdefault(names[0], []).append(
                {**named, "key": names[0], "ace": names[1]}
            )
    for source, rows in originals.items():
        try:
            for blob, raw in git_blobs.original_blobs(source, list(rows)):
                for task in rows[blob]:
                    if task["kind"] != "hits":
                        from .guided_inputs import display_name

                        emit(task["section"], blob, display_name(raw, task["ace"]))
                        continue
                    try:
                        emit(task["section"], task["key"], _hits(raw, task))
                    except ValueError:
                        continue
        except OSError, ValueError:
            continue  # Git failed; the backend reads what is left itself.


def _hits(raw, task):
    from .event_text import builtin_hits

    return builtin_hits(raw, task["builtins"])


class Unread(Exception):
    """An input a value needs that could not be read, such as an original
    Git did not give; the value is left to the look, which keeps none."""


def current(path, expected):
    """A file's bytes, while they are still those of digest `expected`,
    which a value read from them is kept under."""
    from .files import digest

    raw = Path(path).read_bytes()
    if digest(raw) != expected:
        raise Unread
    return raw


def _read(task, git_blobs):
    if task["kind"] == "hits":
        return _hits(current(task["path"], task["digest"]), task)
    from dazedtl.languages import reading

    from .file_lines import read_counts
    from .files import decode_json

    source, blob = task["source"], task.get("original")

    def original():
        try:
            return decode_json(git_blobs.original_bytes(source, blob))
        except OSError, ValueError:
            raise Unread from None

    raw = current(task["path"], task["digest"])
    with reading(*task["pair"]):
        return read_counts(
            task["name"],
            raw,
            task["phase"],
            frozenset(task["markers"] or ()),
            blob,
            original if blob else lambda: None,
        )
