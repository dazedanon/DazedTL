"""A game's original files, recorded in the background.

Recording a big game takes minutes, and the backend answers one request at a
time, so no request records one: the [gateway](game_write.py) refuses a
request's write that would change a file a record holds until the record
exists. DazedTL starts the record when it opens a game whose Git is not set
up, in a worker process of its own, and a refused write starts it again
after a stop or a failure, so recording needs no step of its own. The worker
holds the record's lock ([original_files](original_files.py)
`ensure_found`), so a write outside a request, in an operation's worker,
waits for it and then finds the record. It stops at Stop or when DazedTL
closes, between chunks of files; a stopped record keeps nothing.
"""

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from dazedtl import system

from . import original_files


class RecordPending(ValueError):
    """A request's write that waits for the record of the game's original
    files, which the page shows with the record's progress."""


@dataclass
class _Record:
    process: system.Process
    message: str = "Recording the original game files in Git."
    error: str = ""
    stopping: bool = False
    follower: threading.Thread = field(init=False)


# The records this backend started, by game folder; a finished one keeps
# how it ended until the game is recorded again.
_records: dict[str, _Record] = {}
_lock = threading.Lock()


def _alive(record):
    return record is not None and record.process.poll() is None


def start(root):
    """Starts recording the game at `root` unless it is recorded already or
    a record of it runs."""
    root = Path(root).resolve()
    with _lock:
        if _alive(_records.get(str(root))) or original_files.recorded(root):
            return
        process = system.popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("original_worker.py")),
                str(root),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            group=True,
        )
        record = _records[str(root)] = _Record(process)
        record.follower = threading.Thread(
            target=_follow, args=(root, record), daemon=True
        )
        record.follower.start()


def _follow(root, record):
    assert record.process.stdout is not None
    for line in record.process.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        with _lock:
            if "message" in event:
                record.message = str(event["message"])[:1000]
            if "error" in event:
                record.error = str(event["error"])[:2000]
    record.process.wait()
    with _lock:
        if record.process.returncode and not record.error and not record.stopping:
            record.error = "The record ended before it finished."
    if original_files.recorded(root):
        from dazedtl.projects import location

        # The repository may be new; it names its project from now on.
        location.adopt(root)


def view(root):
    """The record of the game at `root` this backend started: whether it
    runs, its progress, and that it stopped or why it failed; None without
    one, or once one finished."""
    root = Path(root).resolve()
    with _lock:
        record = _records.get(str(root))
        if record is None:
            return None
        running = _alive(record)
        if not running and (
            original_files.recorded(root) or not (record.error or record.stopping)
        ):
            return None
        return {
            "running": running,
            "message": ("Stopping…" if record.stopping else record.message)
            if running
            else "",
            "error": "" if running or record.stopping else record.error,
            "stopped": not running and record.stopping,
        }


def refusal(root):
    """The refusal of a request's write to the game at `root` that waits for
    the record of its original files, which this starts again after a stop
    or a failure."""
    root = Path(root).resolve()
    with _lock:
        record = _records.get(str(root))
        running = _alive(record)
        error = "" if running or record is None or record.stopping else record.error
    if not running:
        start(root)
    waiting = (
        "DazedTL is recording the game's original files, which it keeps"
        " before it changes any of them. Try again once that finishes."
    )
    if error:
        return RecordPending(
            f"The game's original files weren't recorded: {error} {waiting}"
        )
    return RecordPending(waiting)


def stop(root):
    """Asks the record of the game at `root` to stop between chunks of files."""
    root = Path(root).resolve()
    with _lock:
        record = _records.get(str(root))
        if record is None or not _alive(record):
            raise ValueError("The original game files are no longer being recorded.")
        record.stopping = True
        _ask_stop(record)


def _ask_stop(record):
    try:
        assert record.process.stdin is not None
        record.process.stdin.write("stop\n")
        record.process.stdin.flush()
    except OSError:
        pass


def close(timeout=4):
    """Stops every record as DazedTL closes."""
    with _lock:
        records = [record for record in _records.values() if _alive(record)]
        for record in records:
            record.stopping = True
            _ask_stop(record)
    for record in records:
        try:
            record.process.wait(timeout)
        except subprocess.TimeoutExpired:
            # The whole tree, or a Git command the worker waits on outlives it.
            system.stop_tree(record.process, force=True)
