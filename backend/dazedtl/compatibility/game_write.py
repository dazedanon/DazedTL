"""The one way DazedTL changes a game's own files.

Every write to a file of the game folder that Git tracks, which is all of it
but DazedTL's records under `.dazedtl/` (other than its glossary, settings and
skills), runs inside `write_game`, which holds the rules such writes share:

- It refuses while the game's Git checkout can't take the change
  (`checkout_issue`): a file written during a game update's stopped merge
  leaves Versions unable to cancel the update, and one written off the
  translation branch misses the translation's version.
- A VX Ace game reads Data, never the `ace_json` DazedTL edits, so the
  `ace_json` files a write touched are packed into Data once it succeeds,
  saving the packing receipt Release checks when the game has a Guided
  workspace. The game reads nothing else while an RGSS archive sits beside
  Game.exe, so a write that packs refuses before writing anything then.

Writers change files through the `GameWrite` it yields, or run an engine tool
inside it and name what the tool wrote with `wrote`, or have the write find
what it changed in a folder with `watch`. The suite's write check
(tests/game_writes.py) fails a test whose app code writes a game file
anywhere else.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from dazedtl.system import unlink, write_bytes
from dazedtl.translation.files import digest, project_path

# The game folders a gateway is writing to in this context.
writing = ContextVar("game_writes", default=frozenset())


class GameWrite:
    """The game files one write changes."""

    def __init__(self, root, packs=False):
        self.root = Path(root).resolve()
        self.touched = []
        self.everything = False
        self.packs = packs
        self.watched = {}

    def put(self, relative, raw, mode=None):
        """Writes one game file whole, with `mode` when given, or takes it
        out for None. A file the write creates is readable by everyone, as
        the game's own files are."""
        target = project_path(self.root, relative, exists=False)
        if raw is None:
            unlink(target, missing_ok=True)
        else:
            write_bytes(target, raw, 0o644 if mode is None else mode)
            if mode is not None:
                target.chmod(mode)
        self.wrote(relative)

    def wrote(self, *relative):
        """Names files a tool run inside the write changed itself."""
        self.touched.extend(relative)

    def watch(self, folder):
        """Names the files a tool run inside the write changes in `folder`,
        a game folder, itself, by their content before and after, for a tool
        that rewrites only some of them, such as a formatter. Only a write
        that packs needs their names; with the packing receipt, it also packs
        what the receipt finds changed since."""
        if self.packs:
            base = (self.root / folder).resolve()
            self.watched[base] = self._contents(base)

    def _contents(self, base):
        if not base.is_relative_to(self.root):
            raise ValueError(f"{base} is outside the game folder.")
        return {
            path.relative_to(self.root).as_posix(): digest(path.read_bytes())
            for path in sorted(base.rglob("*") if base.is_dir() else ())
            if path.is_file()
        }

    def _settle(self):
        for folder, before in self.watched.items():
            after = self._contents(folder)
            changed = after.keys() | before.keys()
            self.wrote(*(n for n in sorted(changed) if before.get(n) != after.get(n)))

    def repack(self):
        """Packs every export whose Data is out of date, as Pack outside
        edits does, rather than only what this write touched."""
        self.everything = True


def _checkout(root):
    from util.len_git import git_status
    from util.len_translation import LenProject

    from dazedtl.translation.operations import checkout_issue

    # A game takes translation work only in a repository of its own; one
    # without, before version tracking is set up, has no checkout to keep.
    if not (root / ".git").exists():
        return
    status = git_status(LenProject(root))
    if status.get("configured") and (issue := checkout_issue(status)):
        raise ValueError(issue)


def _pack(native, folder, game, log):
    from util.ace import actions

    from dazedtl.translation.release import packing_target

    from .guided import pack_ace

    if game.everything:
        return pack_ace(native, folder, log)
    touched = [name for name in game.touched if name.startswith("ace_json/")]
    # A write that watched its exports lets the packing receipt find what
    # changed even when it changed nothing itself, such as a format run
    # again after one stopped before its pack.
    if not touched and (folder is None or not game.watched):
        return []
    if folder is None:
        # Without a Guided workspace, which keeps the packing receipt, a
        # write packs only what it touched.
        only = {packing_target(name) for name in touched}
        return actions.run(Path(native["source"]), "ace_pack", log, only=only)
    return pack_ace(native, folder, log, touched)


@contextmanager
def write_game(
    root,
    folder=None,
    *,
    log=lambda _line: None,
    paths=None,
    pack=True,
    subject="The text",
):
    """Checks, then yields the `GameWrite` for one write to the game at
    `root`, and packs it once the block succeeds.

    `folder` is the game's Guided workspace, which keeps the packing receipt;
    `paths` the files the write will change when known, so a write that packs
    none refuses no archive; `pack=False` leaves Data as it is, for tools that
    convert between Data and `ace_json`; `subject` names what was written when
    packing fails.
    """
    from .guided import ace_blocked

    root = Path(root).resolve()
    _checkout(root)
    # A VX Ace game's text DazedTL writes is always its ace_json.
    native = {"source": str(root), "data": str(root / "ace_json"), "engine": "ACE"}
    ace = pack and (root / "ace_json").is_dir()
    packs = ace and (
        paths is None or any(str(name).startswith("ace_json/") for name in paths)
    )
    if packs and (blocked := ace_blocked(root)):
        raise ValueError(blocked)
    game = GameWrite(root, packs=ace)
    token = writing.set(writing.get() | {str(root)})
    try:
        yield game
    finally:
        writing.reset(token)
    if not ace:
        return
    game._settle()
    token = writing.set(writing.get() | {str(root)})
    try:
        _pack(native, folder, game, log)
    except InterruptedError:
        # A stop, which the log raises, stays a stop.
        raise
    except (OSError, ValueError, KeyError) as error:
        if game.everything:
            raise
        raise ValueError(
            f"{subject} is in ace_json, but the game's data could not be "
            f"updated: {error} Pack outside edits, in Release, tries again."
        ) from error
    finally:
        writing.reset(token)
