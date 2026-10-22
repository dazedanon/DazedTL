"""Start over: the game back to its original, the assistant's work set aside.

An Assistant-led project changes the game folder in many places: preparation,
the canary and injected translations, and the assistant's work records under
.dazedtl/len-method and the playtest's fixes under .dazedtl/playtest.
Starting over is one checkpoint that puts every file the patch holds back as
the original game's current version has it, so the attempt stays in the
game's Git history and the record of its original files stays too; the next
starting prompt begins again from preparation, which finds Git set up. Files
outside the patch go back to the original recorded before setup
([originals](originals.py)), and what Git does not keep moves aside under a
dated folder: the assistant's work, the playtest's fixes, and files the
original lacks. Nothing is deleted. Save games, the project's options,
settings and skills and Image Manager work stay, and the glossary and notes
stay unless the user lets them go.
"""

import re
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dazedtl import system
from dazedtl.foreign_work import ARCHIVE

from . import originals
from .files import project_path
from .project import WORK

# The assistant's working copy of the playtest's fixes.
PLAYTEST = ".dazedtl/playtest"
# Save games outlive any translation attempt, wherever the engine keeps them.
SAVE_FOLDERS = {"save", "saves", "savedata"}
SAVE_FILE = re.compile(r"save\d*\.(rvdata2|rvdata|rxdata|lsd)", re.IGNORECASE)


def save_game(name):
    """Whether a game-relative path is a save game, which starting over keeps."""
    *folders, filename = name.split("/")
    return any(part.lower() in SAVE_FOLDERS for part in folders) or bool(
        SAVE_FILE.fullmatch(filename)
    )


def _archive(root):
    folder = project_path(root, ARCHIVE, exists=False)
    stamp = "assistant-led-" + datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    target, count = folder / stamp, 1
    while target.exists():
        count += 1
        target = folder / f"{stamp}-{count}"
    target.mkdir(parents=True)
    return target


def _move(path, target):
    """Moves a file or folder aside, to a path nothing holds yet. Windows
    refuses while another program, such as the Git status check, holds a
    file inside, which the platform layer waits out briefly."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        system.replace(path, target)
    except PermissionError:
        raise ValueError(
            f"{path.name} is in use. Close programs using the game folder, "
            "then start over again; what moved so far is in the archive."
        ) from None


# The lifecycle records a game keeps through Start over while its Git stays:
# its original files and version history. The rest belonged to the attempt.
KEPT = (
    "source_backup",
    "prepared_source",
    "game_backup",
    "git",
    "preparation",
    "version_update",
)


def run(
    workspace,
    project_id,
    source,
    state,
    documents,
    keep_context,
    *,
    configured,
    stopped,
    progress,
    publications=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Starts the project over: back to the original game as a checkpoint
    when its Git is `configured`, else to the game as DazedTL found it, or
    with the game's files as they are without either; returns its new
    lifecycle and a summary. `publications` is the project's Guided folder
    of text publications, when it has one."""
    from dazedtl.compatibility import checkpoint_history
    from dazedtl.compatibility.checkpoint_commits import Change, running
    from dazedtl.compatibility.game_write import write_game

    from . import checkpoint_records

    root = Path(source).resolve(strict=True)
    renewed: dict[str, Any] = {"version": 1}
    # A backup from before original files were kept in Git stays the
    # project's original, as does the Git record.
    for key in KEPT if configured else ("source_backup",):
        if state.get(key):
            renewed[key] = state[key]
    original = (
        originals.prepared(workspace, project_id, root, state)
        if configured
        else originals.found(workspace, project_id, root, state)
    )
    archive = _archive(root)
    result: dict[str, Any] = {
        "archive": archive.relative_to(root).as_posix(),
        "original": original is not None,
        "restored": 0,
        "set_aside": 0,
    }
    change = Change(
        "Started over from the original game", "Assistant-led", "start_over"
    )
    # A game DazedTL never wrote to has no original to put back, and a write
    # through the gateway would record it, as it is now, as the original.
    writing = (
        write_game(root, log=progress, pack=False)
        if configured or original is not None
        else nullcontext()
    )
    with running(change), writing as game:
        kept = set()
        for document in documents.values():
            path = Path(document["path"])
            if not path.is_file():
                continue
            name = path.resolve().relative_to(root).as_posix()
            if keep_context:
                kept.add(name)
            else:
                _move(path, archive / "context" / name)

        def keep(name):
            return save_game(name) or name in kept

        tracked, undone = set(), []
        if configured:
            progress("Putting back the original game files.")
            restored = checkpoint_history.to_original(
                game,
                keep,
                stopped,
                originals.saved(workspace, project_id, root, state),
            )
            result["restored"], undone = restored["files"], restored["undone"]
            tracked = checkpoint_history.tracked(root)
        if original:
            # Files outside the patch, which Git doesn't keep.
            put = originals.reset(
                original,
                root,
                archive / "game-files",
                keep=lambda name: keep(name) or name in tracked,
                stopped=stopped,
                progress=lambda count, path: progress(
                    f"Put back {count:,} file{'' if count == 1 else 's'} · {path}"
                ),
            )
            result["restored"] += put["restored"]
            result["set_aside"] = put["set_aside"]
        work = project_path(root, WORK, exists=False)
        if work.is_dir():
            progress("Setting the assistant's work aside.")
            for child in sorted(work.iterdir()):
                # The project's options belong to the user, not to one attempt.
                if child.name != "workflow.json":
                    _move(child, archive / "len-method" / child.name)
        # The playtest's fixes were written for this attempt's translation;
        # the next one starts from an empty fixes plugin.
        fixes = project_path(root, PLAYTEST, exists=False)
        if fixes.is_dir():
            _move(fixes, archive / "playtest")
    # Every checkpoint is taken out, so the records of what each feature
    # applied follow, as an undo's do, and nothing reads as in the game.
    checkpoint = game.checkpoint if game is not None else None
    if undone and checkpoint:
        checkpoint_records.follow(
            checkpoint_records.Records(
                root,
                Path(workspace),
                project_id,
                Path(publications) if publications else None,
            ),
            undone,
            checkpoint,
        )
    if not any(archive.iterdir()):
        system.rmdir(archive)
        result["archive"] = ""
    renewed["started_over"] = {
        "at": datetime.now(UTC).isoformat(),
        "archive": result["archive"],
    }
    return renewed, result
