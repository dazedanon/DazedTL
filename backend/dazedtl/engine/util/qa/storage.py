"""A task folder's files: atomic writes, the task lock, reading the task
and its checkpoint, and the decisions and answers files."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from util import extensions, system
from util.freshness import Basis, compare
from util.qa.schema import (
    CHECKPOINT_SCHEMA,
    PREPARED_AT,
    QA_RULES_VERSION,
    TASK_SCHEMA,
    _canonical_bytes,
    _sha256,
)


def _rules_version(task: dict[str, Any]) -> int:
    """The QA rules version a task was prepared under. Tasks from before
    versions were kept name a hash of QA's code files instead and count as
    the first."""
    return int(task.get("rules_version", 1))


def _atomic_write_json(path: Path, value: Any) -> None:
    system.write_bytes(path, _canonical_bytes(value) + b"\n")


def _atomic_write_text(path: Path, value: str) -> None:
    system.write_text(path, value.rstrip() + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    # utf-8-sig: an assistant's shell may start a result file with a BOM.
    value = json.loads(system.read_bytes(path).decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _safe_task_root(output_root: str | Path, game_root: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    if root == game_root or game_root in root.parents:
        raise ValueError("QA task storage must be outside the selected game folder")
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def _task_lock(task_dir: Path, wait: bool = True):
    """Serialize cross-process checkpoint mutations for parallel helpers.

    Without *wait*, it yields whether it got the lock instead of waiting for
    another process to let go of it.
    """
    lock_path = task_dir / ".checkpoint.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(
                    handle.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1
                )
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
                )
        except OSError:
            if wait:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:80] or "game"


def game_tasks(output_root: Path, game_root: Path, key: str | None = None) -> Path:
    """The folder of *output_root* holding a game's tasks and baselines: the
    one named *key*, as the app names it for the project so a renamed game
    keeps them, else one named for the game folder."""
    if key is not None and _slug(key) != key:
        raise ValueError(f"Not a QA storage folder name: {key!r}")
    return output_root / (key or _slug(game_root.name))


def _read_optional(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "status": "missing", "sha256": "", "text": ""}
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        return {
            "path": str(resolved),
            "status": "missing",
            "sha256": "",
            "text": "",
        }
    raw = resolved.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {
            "path": str(resolved),
            "status": f"unreadable: {exc}",
            "sha256": _sha256(raw),
            "text": "",
        }
    return {
        "path": str(resolved),
        "status": "loaded" if text.strip() else "empty",
        "sha256": _sha256(raw),
        "text": text,
    }


# Observations a task left out when it was prepared, since an earlier review
# had judged them for the same text.
JUDGED_BEFORE = "judged_before"


def _observation_key(observation: dict[str, Any]) -> tuple[str, str]:
    """An observation is the same as another of the same line for the same
    reason; another reason, such as the playtest's beside a reviewer's, is
    evidence of its own."""
    return observation["identity"], observation["note"]


@extensions.point
def game_folder(task_dir: Path, task: dict[str, Any]) -> str:
    """Where the game a task reviews is now: where it was prepared, unless
    a host whose games can move layers where it keeps them."""
    return task["game_root"]


def located(task_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    """The task with its game and data folders where they are now; its
    digest still names the task as prepared (schema.task_sha256)."""
    if not isinstance(task.get("game_root"), str) or not isinstance(task.get("data_root"), str):
        return task
    game = str(game_folder(task_dir, task))
    if game == task["game_root"]:
        return task
    prepared, data = Path(task["game_root"]), Path(task["data_root"])
    if data.is_relative_to(prepared):
        data = Path(game) / data.relative_to(prepared)
    return {**task, "game_root": game, "data_root": str(data),
            PREPARED_AT: {"game_root": task["game_root"], "data_root": task["data_root"]}}


def task_json(task_dir: str | Path) -> dict[str, Any]:
    """A task folder's task, its game where it is now."""
    root = Path(task_dir).expanduser().resolve()
    return located(root, _read_json(root / "task.json"))


def read_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    """The task and its checkpoint for reading, or for applying a finished
    task's findings, whichever rules prepared it."""
    root = Path(task_dir).expanduser().resolve()
    task = task_json(root)
    checkpoint = _read_json(root / "checkpoint.json")
    if task.get("schema") != TASK_SCHEMA or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError(f"Unsupported or corrupt QA task: {root}")
    return root, task, checkpoint


def rules_changed(task: dict[str, Any], checkpoint: dict[str, Any]) -> bool:
    """Whether an update changed QA's rules while this task was in review, so
    it takes no more review and QA is prepared again. A finished task keeps
    its results through any update."""
    return _rules_moved(task) and checkpoint["stage"] != "complete"


def _rules_moved(task: dict[str, Any]) -> bool:
    """Whether QA's rules changed since this task was prepared."""
    return compare(Basis(_rules_version(task), {}), Basis(QA_RULES_VERSION, {})) is not None


def _load_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    """The task and its checkpoint for review work, which needs the rules
    version that made it."""
    root, task, checkpoint = read_task(task_dir)
    if _rules_moved(task):
        raise ValueError(
            "An update changed QA's rules after this task was prepared, so it "
            f"takes no more review; prepare QA again: {root}"
        )
    return root, task, checkpoint


# The user's answers to a task's questions, which its ledger reads: keep the
# line as it is, or use the reviewer's proposal.
ANSWERS_FILE = "answers.json"
ANSWERS_SCHEMA = "rpgmaker-qa-answers-v1"
ANSWERS = frozenset({"keep", "use"})


def answers(task_dir: str | Path) -> dict[str, str]:
    """The user's answer to each of a task's questions they answered."""
    try:
        document = _read_json(Path(task_dir).expanduser().resolve() / ANSWERS_FILE)
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("schema") != ANSWERS_SCHEMA:
        return {}
    saved = document.get("answers")
    if not isinstance(saved, dict):
        return {}
    return {
        str(question): choice for question, choice in saved.items() if choice in ANSWERS
    }


DECISIONS_FILE = "decisions.json"
DECISIONS_SCHEMA = "rpgmaker-qa-decisions-v1"


def _decisions(root: Path) -> list[dict[str, Any]]:
    """The decision log's current entries, the latest one per key, those
    carried from earlier tasks included."""
    path = root / DECISIONS_FILE
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for entry in _read_json(path).get("decisions") or []:
        latest[entry["key"]] = entry
    return sorted(latest.values(), key=lambda entry: entry["key"])
