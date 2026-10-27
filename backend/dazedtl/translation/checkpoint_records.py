"""What a project's records of applied work do when a checkpoint is undone
or gone back past: they follow the game's files.

Each feature's apply names, in its record, the checkpoint its write made.
Undoing a checkpoint, or going back past it, hands the checkpoints taken
out, newest first, to each feature, which takes out what it applied there
as made by the new checkpoint: text batches' receipts, which History, Text
QA and `applied-outputs.json` read ([publication](publication.py)), Plugin
files' applications ([plugins](../plugins/service.py)), and an Assistant-led
report's phases, whose checkpoints reopen their phase and every one after it
([progress_report](progress_report.py)). A restore is
a record too, so taking one out brings back what it restored. Images reads
whether an image is applied from its file, which it checks again once the
game's checkpoints move ([images](../images/service.py)). A Guided
project's Line widths are the game's settings: a restore that changes the
widths the game uses leaves them in the project's folder, which Guided takes
on its next look ([guided](guided.py)). Records from before applies named
their checkpoint stay as they are.

History's Undo, Plugin files' Recovery and the Checkpoints tab all undo
through `undo` or `go_back` here, so their records follow the same way;
Start over, which takes out every checkpoint, calls `follow` itself.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dazedtl.compatibility import checkpoint_history
from dazedtl.storage import write_json
from dazedtl.system import unlink
from dazedtl.translation.files import read_json

# The Line widths a restore gave the game, for its Guided project to take.
RESTORED_WIDTHS = "restored-line-widths.json"


@dataclass(frozen=True)
class Records:
    """Where one project's records of applied work are kept."""

    root: Path
    workspace: Path | None = None
    project_id: str | None = None
    # The Guided project's folder of text publications, when it has one,
    # which also keeps a VX Ace game's packing receipt.
    publications: Path | None = None
    # The translation engine, which republishes an Assistant-led report; an
    # undo of one feature's own checkpoint, never a phase's, passes none.
    engine: Any = None


def undoes(record):
    """Whether a record of applied work restores through Git: by undoing
    the checkpoint its write made, or, when the write made none because it
    stopped or failed after writing, by putting its files back as the
    checkpoint it started from had them. One from before records named them
    restores from the copies it saved; one restored since still reads as
    undone through Git."""
    return bool(record.get("commit") or record.get("parent"))


def publications(backend, project):
    """The folder of a project's text publications, or None without a
    Guided project."""
    native = project.get("backend_id")
    return Path(backend.workflows.root) / native if native else None


def _widths(root):
    """The Line widths the game uses, or None when its settings can't be
    read."""
    from util.game_settings import game_wrap_widths

    try:
        return game_wrap_widths(root)
    except OSError, ValueError:
        return None


def follow(records, undone, commit, widths=None):
    """Takes out what each feature applied in the checkpoints `undone`,
    newest first, as made by checkpoint `commit`; `widths` are the Line
    widths the game used before."""
    from dazedtl.plugins.service import follow as plugins

    from . import progress_report, publication

    if records.publications is not None and records.publications.is_dir():
        publication.follow(records.publications, records.root, undone, commit)
        restored = _widths(records.root)
        if restored is not None and restored != widths:
            write_json(
                records.publications / RESTORED_WIDTHS,
                {"version": 1, "widths": restored},
            )
    if records.workspace is not None and records.project_id:
        plugins(records.workspace, records.project_id, records.root, undone, commit)
        if records.engine is not None:
            progress_report.follow(
                records.workspace,
                records.project_id,
                records.engine,
                records.root,
                undone,
            )


def restored_widths(folder):
    """The Line widths a restore gave the game of the Guided project in
    `folder`, which it takes once, or None."""
    path = Path(folder) / RESTORED_WIDTHS
    try:
        saved = read_json(path) if path.is_file() else {}
    except OSError, ValueError:
        saved = {}
    widths = saved.get("widths") if saved.get("version") == 1 else None
    return widths if isinstance(widths, dict) else None


def took_widths(folder):
    """The Guided project in `folder` took the restored Line widths."""
    unlink(Path(folder) / RESTORED_WIDTHS, missing_ok=True)


def undo(records, commit, **options):
    """Undoes one checkpoint, as `checkpoint_history.undo` does, and the
    records follow."""
    widths = _widths(records.root)
    result = checkpoint_history.undo(
        records.root, commit, folder=records.publications, **options
    )
    follow(records, result["undone"], result["commit"], widths)
    return result


def go_back(records, commit, **options):
    """Goes back to a checkpoint, as `checkpoint_history.go_back` does, and
    the records of every checkpoint after it follow."""
    widths = _widths(records.root)
    result = checkpoint_history.go_back(
        records.root, commit, folder=records.publications, **options
    )
    follow(records, result["undone"], result["commit"], widths)
    return result
