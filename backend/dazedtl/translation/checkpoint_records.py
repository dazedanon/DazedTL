"""What a project's records of applied work do when a checkpoint is undone
or gone back past: they follow the game's files.

Each feature's apply names, in its record, the checkpoint its write made.
Undoing a checkpoint, or going back past it, hands the checkpoints taken
out, newest first, to each feature, which takes out what it applied there
as made by the new checkpoint: text batches' receipts, which History, Text
QA and `applied-outputs.json` read ([publication](publication.py)), and
Plugin files' applications ([plugins](../plugins/service.py)). A restore is
a record too, so taking one out brings back what it restored. Images reads
whether an image is applied from its file, which it checks again once the
game's checkpoints move ([images](../images/service.py)). Records from
before applies named their checkpoint stay as they are.

History's Undo, Plugin files' Recovery and the Checkpoints tab all undo
through `undo` or `go_back` here, so their records follow the same way.
"""

from dataclasses import dataclass
from pathlib import Path

from dazedtl.compatibility import checkpoint_history


@dataclass(frozen=True)
class Records:
    """Where one project's records of applied work are kept."""

    root: Path
    workspace: Path | None = None
    project_id: str | None = None
    # The Guided project's folder of text publications, when it has one.
    publications: Path | None = None


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


def follow(records, undone, commit):
    """Takes out what each feature applied in the checkpoints `undone`,
    newest first, as made by checkpoint `commit`."""
    from dazedtl.plugins.service import follow as plugins

    from . import publication

    if records.publications is not None and records.publications.is_dir():
        publication.follow(records.publications, records.root, undone, commit)
    if records.workspace is not None and records.project_id:
        plugins(records.workspace, records.project_id, records.root, undone, commit)


def undo(records, commit, **options):
    """Undoes one checkpoint, as `checkpoint_history.undo` does, and the
    records follow."""
    result = checkpoint_history.undo(records.root, commit, **options)
    follow(records, result["undone"], result["commit"])
    return result


def go_back(records, commit, **options):
    """Goes back to a checkpoint, as `checkpoint_history.go_back` does, and
    the records of every checkpoint after it follow."""
    result = checkpoint_history.go_back(records.root, commit, **options)
    follow(records, result["undone"], result["commit"])
    return result
