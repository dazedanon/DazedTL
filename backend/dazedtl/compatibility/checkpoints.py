"""Verified incremental JSON outputs and native-reader resume, without game writes."""

import io
import os
import threading
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import (
    Digests,
    decode_json,
    digest,
    project_path,
    read_json,
)

INDEX = "log/dazedtl-checkpoints.json"


def can_collect_outputs(job):
    """Batch collection writes scratch JSON; only consumption translates it.

    Keep explicit completed-file receipts and unknown legacy phases readable.
    """
    return (
        job.get("mode") != "batch"
        or bool(job.get("completed"))
        or job.get("phase")
        not in {
            "preparing",
            "collect",
            "collect_done",
            "submit",
            "poll",
            "polling",
            "poll_status",
            "failed",
            "canceled",
        }
    )


# Every snapshot checks every saved run's outputs; a bounded cache smaller
# than a long history's outputs missed on every one and parsed them all again,
# seconds per snapshot.
_DIGESTS = Digests()


def _json_digest(path, signature):
    cached = _DIGESTS.get(path, signature)
    if cached is not None:
        return cached
    raw = Path(path).read_bytes()
    if not isinstance(decode_json(raw), (dict, list)):
        raise ValueError("A progress checkpoint must contain game JSON.")
    value = digest(raw)
    _DIGESTS.put(path, signature, value)
    return value


def _index(root):
    """The run's checkpoint receipts, or None before its first checkpoint."""
    path = project_path(root, INDEX, exists=False)
    if not path.exists():
        return None
    record = read_json(path)
    if record.get("version") != 1 or record.get("plan_hash") != digest(
        (root / "plan.json").read_bytes()
    ):
        raise ValueError("Progress checkpoints do not match this saved run.")
    return record


def outputs(root, plan):
    root = Path(root)
    record = _index(root)
    if record is None:
        return {}
    allowed = {row["name"] for row in plan["files"]}
    # Snapshots check every run's outputs several times; one listing settles
    # each regular file, where resolving every path took most of a snapshot.
    # Anything the listing cannot settle gets project_path's answer or error.
    folder = project_path(root, "translated", exists=False)
    try:
        with os.scandir(folder) as entries:
            listed = {entry.name: entry for entry in entries}
    except OSError:
        listed = {}
    result = {}
    for name, expected in record.get("files", {}).items():
        if name not in allowed:
            raise ValueError("A progress checkpoint is outside this run’s file scope.")
        entry = listed.get(name)
        if entry is not None and entry.is_file(follow_symlinks=False):
            output = folder / name
            stat = entry.stat(follow_symlinks=False)
        else:
            output = project_path(root, "translated/" + name)
            stat = output.stat()
        actual = _json_digest(
            str(output), (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        )
        if actual == expected:
            result[name] = expected
        # A later atomic write can precede its receipt; only matching bytes count.
    return result


LAYER = "checkpoints"


def install(module, root, plan):
    if module is None or plan.get("mode") not in {"translate", "batch"}:
        return
    root = Path(root).resolve()
    names = {row["name"] for row in plan["files"]}
    plan_hash = digest((root / "plan.json").read_bytes())
    lock = threading.Lock()

    def save(native, data, filename, *args, **kwargs):
        saved = native(data, filename, *args, **kwargs)
        if saved and filename in names:
            path = project_path(root, "translated/" + filename)
            raw = path.read_bytes()
            if not isinstance(decode_json(raw), (dict, list)):
                raise ValueError("The engine checkpoint is not game JSON.")
            with lock:
                index = project_path(root, INDEX, exists=False)
                record = (
                    read_json(index)
                    if index.exists()
                    else {"version": 1, "plan_hash": plan_hash, "files": {}}
                )
                if record.get("plan_hash") != plan_hash:
                    raise ValueError("The checkpoint owner changed.")
                record["files"][filename] = digest(raw)
                write_json(index, record)
        return saved

    def opening(native, file, *args, **kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        # Batch consume must keep its exact frozen request grouping. It already
        # reuses provider receipts; only Live reads partially translated inputs.
        if (
            plan.get("mode") == "translate"
            and mode in {"r", "rt"}
            and isinstance(file, (str, Path))
        ):
            path = Path(file).resolve()
            if path.parent == root / "files" and path.name in names:
                # Only the reopened file's receipt matters: checking every
                # saved output made each file's start slower as a run went on.
                expected = ((_index(root) or {}).get("files") or {}).get(path.name)
                output = root / "translated" / path.name
                if expected and output.is_file():
                    raw = project_path(root, "translated/" + path.name).read_bytes()
                    if digest(raw) == expected and isinstance(
                        decode_json(raw), (dict, list)
                    ):
                        stream = io.StringIO(
                            raw.decode(kwargs.get("encoding") or "utf-8-sig")
                        )
                        stream.name = str(path)
                        return stream
        return native(file, *args, **kwargs)

    module.saveProgress.layer(LAYER, save)
    module.open.layer(LAYER, opening)
