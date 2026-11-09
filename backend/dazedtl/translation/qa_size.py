"""How much of a game Text QA's review reads, for the usage note both methods
show before a review starts: the lines each focus takes and the scenes its
dialogue plays in.

A focus takes the lines of its classification (rpgmaker_qa_manifest: event
dialogue, risky event codes or database entries), and the full game text
takes every line; its scenes are the event command lists that hold dialogue,
as QA's screening reads them (qa/selection). Guided counts the lines of Text
QA's own inventory of the game's translated text. An Assistant-led project
counts its census of the original game's text instead, which its assistant
saves before translating, so its Options can show the count before the game
holds any translation. The assistant's usage itself is not measured, so the
note calls the count an estimate.

Counting a big game takes seconds, which no request may wait for: a look at
one that large counts it in a thread and reads as counting until it ends.
A count holds while the sizes and times of the files it read are unchanged.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from .files import read_json

FOCUSES = ("release", "database", "dialogue", "risky-codes")
# The focuses whose review reads scenes, which only dialogue plays in.
SCENES = ("release", "dialogue")
# A look counts files totaling at most this many bytes itself.
INLINE_BYTES = 2_000_000
# A census row's event code, as its field names it ("list/*[code=401]").
_CODE = re.compile(r"\[code=(\d+)")

_lock = threading.Lock()
# Each count by what it read: the signature it holds for, and its value.
_counts: dict[str, tuple[Any, Any]] = {}
_counting: set[str] = set()


def of_game(data_root) -> dict[str, Any]:
    """The review's size from Text QA's inventory of the game's data folder,
    which holds only translated lines."""
    root = Path(data_root)
    try:
        files = sorted(root.rglob("*.json"))
        signature = [
            (path.relative_to(root).as_posix(), *_stamp(path)) for path in files
        ]
    except OSError:
        return {"counting": False, "focuses": None}
    return _look(
        "game:" + str(root),
        signature,
        sum(row[1] for row in signature),
        lambda: count(_inventory_rows(root)),
    )


def of_census(path) -> dict[str, Any]:
    """The review's size from an Assistant-led project's saved census, or
    none before its assistant runs one."""
    path = Path(path)
    try:
        stamp = _stamp(path)
    except OSError:
        return {"counting": False, "focuses": None}
    return _look(
        "census:" + str(path),
        stamp,
        stamp[0],
        lambda: count(census_rows(read_json(path, limit=None))),
    )


def count(rows: Iterable[tuple[str, str | None]]) -> dict[str, Any] | None:
    """Each focus's lines and scenes from *rows* of a line's classification
    and the command list it plays in; None when no line counts."""
    lines: Counter[str] = Counter()
    scenes: set[str] = set()
    for classification, scene in rows:
        lines[classification] += 1
        if classification == "dialogue" and scene:
            scenes.add(scene)
    total = sum(lines.values())
    if not total:
        return None
    return {
        focus: {
            "lines": total if focus == "release" else lines[focus],
            "scenes": len(scenes) if focus in SCENES else 0,
        }
        for focus in FOCUSES
    }


def census_rows(census) -> list[tuple[str, str | None]]:
    """The rows of a census's RPG Maker data lines, which Text QA reads; its
    scripts and plugins it does not."""
    from util.rpgmaker_qa_manifest import classification_of

    rows = []
    for entry in census.get("entries") or []:
        kind = str(entry.get("kind") or "")
        if not kind.startswith(("rpgmaker:", "rgss:")) or kind == "rgss:scripts":
            continue
        code = _CODE.search(str(entry.get("field") or ""))
        # VX Ace's Map001.rvdata2 holds what its JSON form Map001.json does.
        name = PurePosixPath(str(entry["file"])).stem + ".json"
        classification = classification_of(name, int(code[1]) if code else None)
        parts = str(entry.get("location") or "").split("/")
        listed = [index for index, part in enumerate(parts) if part == "list"]
        scene = (
            str(entry["file"]) + "#" + "/".join(parts[: listed[-1] + 1])
            if listed
            else None
        )
        rows.append((classification, scene))
    return rows


def _inventory_rows(root: Path) -> list[tuple[str, str | None]]:
    from util.qa.selection import scene_position
    from util.rpgmaker_qa_manifest import build_manifest

    rows = []
    for record in build_manifest(root, "release")["records"]:
        position = scene_position(record)
        rows.append((record["classification"], position[0] if position else None))
    return rows


def _stamp(path: Path) -> tuple[int, int]:
    found = path.stat()
    return found.st_size, found.st_mtime_ns


def _look(name: str, signature, size: int, read: Callable[[], Any]):
    """read()'s count for *name* while *signature* holds; a count of more
    than INLINE_BYTES runs in a thread, reading as counting until it ends."""
    with _lock:
        saved = _counts.get(name)
        if saved is not None and saved[0] == signature:
            return {"counting": False, "focuses": saved[1]}
        if name in _counting:
            return {"counting": True, "focuses": None}
        _counting.add(name)

    def work():
        try:
            value = read()
        except Exception:  # noqa: BLE001
            # A file the count can't read leaves the note without one.
            value = None
        with _lock:
            _counts[name] = (signature, value)
            _counting.discard(name)
        return value

    if size <= INLINE_BYTES:
        return {"counting": False, "focuses": work()}
    threading.Thread(target=work, name="qa-size", daemon=True).start()
    return {"counting": True, "focuses": None}
