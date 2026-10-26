"""Fails a test whose app code writes a game's own file outside the gateway.

Every write to a file of a game folder that Git tracks goes through
dazedtl.compatibility.game_write; see its docstring for why. This audit hook,
installed for the whole suite and its probe processes (tests/probe.py), raises
when code under backend/dazedtl, other than the engine's, writes such a file
while no gateway write to that game is open. A game folder is one holding a
game's data, plugins or VX Ace exports; DazedTL's own records under
`.dazedtl/` are exempt, apart from the glossary, settings and skills Git
tracks. It also raises when any code changes a file a record of the game's
original files holds inside a write that left the game unrecorded, as it
named only DazedTL's own files.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from dazedtl.compatibility import original_files
from dazedtl.compatibility.game_write import unrecorded, write_game, writing

APP = str(Path(__file__).resolve().parents[1] / "backend/dazedtl") + os.sep
ENGINE = APP + "engine" + os.sep
# Shared helpers whose callers are the writers.
HELPERS = (
    APP + "storage.py",
    APP + "system.py",
    APP + "translation" + os.sep + "files.py",
)
GAME = ("data", "www", "Data", "ace_json")
TRACKED = {".dazedtl/glossary.txt", ".dazedtl/settings.json"}
WRITES = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
TARGETS = {
    "os.rename": 1,
    "os.replace": 1,
    "shutil.copyfile": 1,
    "shutil.move": 1,
    "shutil.copytree": 1,
    "os.remove": 0,
    "os.mkdir": 0,
    "os.rmdir": 0,
    "os.chmod": 0,
    "os.truncate": 0,
    "shutil.rmtree": 0,
}
MOVES = {"os.rename", "os.replace", "shutil.move"}
# Writers that change a game's files without the gateway, each with why.
OUTSIDE = {
    # Start over of a game DazedTL never wrote to moves notes aside without
    # the gateway, which would record the game as it is as the original.
    "translation/start_over.py:_move": "Start over",
    # A restored backup or recorded original is a new copy of the game's
    # files, never the game itself.
    "translation/backups.py:_extract": "backups",
    "translation/backups.py:_copy": "backups",
    "translation/originals.py:_Saved.extract": "originals",
    "translation/originals.py:_Recorded.extract": "originals",
    "compatibility/original_files.py:write": "originals",
    # Save a copy writes a checkpoint's game into a new folder outside it.
    "compatibility/checkpoint_history.py:save_copy": "Checkpoints",
    # A game update keeps its own commits, and copies the release's files
    # outside the patch beside them.
    "compatibility/translation.py:TranslationEngine.version": "game updates",
}
# Whether each folder seen is shaped like a game.
_games = {}


def game_write(source, _native=None, **options):
    """A test backend's gateway, as the app's backend opens it."""
    return write_game(source, **options)


def _game(path):
    """The outermost folder above `path` shaped like a game, since DazedTL's
    records inside one, such as Plugin files' working copies, keep a game's
    layout too."""
    for parent in reversed(path.parents):
        known = _games.get(parent)
        if known is None:
            if not str(parent).startswith(_scratch):
                continue
            known = _games[parent] = (
                any((parent / name).is_dir() for name in GAME)
                or (parent / "js/plugins.js").is_file()
            )
        if known:
            return parent
    return None


def _shaped(path):
    """Forgets that a folder isn't a game once a write gives it a game's
    folder or plugins.js."""
    if path.name in GAME:
        _games.pop(path.parent, None)
    elif path.name == "plugins.js" and path.parent.name == "js":
        _games.pop(path.parent.parent, None)


def _target(event, args):
    if event == "open":
        path, mode, flags = args
        if isinstance(mode, str):
            return path if set(mode) & set("wax+") else None
        return path if isinstance(flags, int) and flags & WRITES else None
    index = TARGETS.get(event)
    return None if index is None or len(args) <= index else args[index]


def _writer():
    """The app function a write comes from: the innermost frame under
    backend/dazedtl outside the engine and the shared helpers, or None for a
    write test code makes, such as a fixture or a stand-in an app writer
    calls back."""
    frame = sys._getframe(2)
    while frame:
        name = frame.f_code.co_filename
        if name.startswith(_tests):
            return None
        if name.startswith(APP) and not name.startswith((ENGINE, *HELPERS)):
            return (
                name[len(APP) :].replace(os.sep, "/") + ":" + frame.f_code.co_qualname
            )
        frame = frame.f_back
    return None


def _removing():
    """Whether shutil.rmtree is removing a folder, which the check judges by
    the folder it removes: on Windows it makes read-only files writable and
    deletes each file by its full path."""
    frame = sys._getframe(2)
    while frame:
        code = frame.f_code
        if os.path.normcase(code.co_filename) == _shutil and (
            code.co_name == "rmtree" or code.co_name.startswith("_rmtree")
        ):
            return True
        frame = frame.f_back
    return False


def _unrecorded(event, args):
    """Raises when a write changes a file a record of the original game holds
    inside a gateway write that left the game unrecorded."""
    if not (roots := unrecorded.get()):
        return
    # A move changes the file it takes as well as the one it makes.
    taken = args[:1] if event in MOVES else ()
    for target in (_target(event, args), *taken):
        if not isinstance(target, (str, os.PathLike)):
            continue
        path = Path(os.path.abspath(os.fspath(target)))
        for parent in path.parents:
            if str(parent) not in roots:
                continue
            relative = path.relative_to(parent).as_posix()
            if original_files.held(relative) and not original_files.recorded(parent):
                raise RuntimeError(
                    f"{relative} changed inside a game write that named only"
                    " files no record of the original game holds."
                )


def _hook(event, args):
    if event != "open" and event not in TARGETS:
        return
    _unrecorded(event, args)
    path = _target(event, args)
    if not isinstance(path, (str, os.PathLike)):
        return
    path = os.path.abspath(os.fspath(path))
    if not path.startswith(_scratch):
        return
    if event != "shutil.rmtree" and _removing():
        return
    path = Path(path)
    _shaped(path)
    if not (writer := _writer()):
        return
    active = writing.get()
    root = _game(path)
    if root is None or any(str(parent) in active for parent in path.parents):
        return
    # A release staged for a game update is a copy of the new version in the
    # workspace's translation/projects/<project>/incoming, never the game.
    if root.parent.name == "incoming" and root.parents[2].name == "projects":
        return
    relative = path.relative_to(root).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        return
    if (
        relative == ".dazedtl"
        or relative.startswith(".dazedtl/")
        and not (
            relative in TRACKED
            or relative.startswith(".dazedtl/skills/")
            and relative.endswith(".md")
        )
    ):
        return
    if writer in OUTSIDE:
        return
    raise RuntimeError(
        f"{writer} wrote {relative} in a game folder outside the game-write "
        "gateway (dazedtl.compatibility.game_write)."
    )


_scratch = str(Path(tempfile.gettempdir()).resolve()) + os.sep
_shutil = os.path.normcase(shutil.__file__)
_tests = str(Path(__file__).resolve().parent) + os.sep


def install():
    sys.addaudithook(_hook)
