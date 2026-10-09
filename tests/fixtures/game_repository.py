"""Real Git journeys for a game's version save."""

import shutil
import sys
import threading
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util.len_git import setup_git
from util.len_translation import LenProject
from util.version_update.git_workflow import _run_git


def game(name):
    folder = temporary / name
    shutil.copytree(root / "tests/fixtures/mz-game", folder)
    return folder


def save(folder):
    return setup_git(LenProject(folder), version="1.0", current_is_untranslated=True)


raced = game("raced")
save(raced)

# A `git status` holds the index lock briefly; an index write waits for it.
lock = raced / ".git/index.lock"
lock.write_bytes(b"")
threading.Timer(0.2, lock.unlink).start()
_run_git(raced, "read-tree", "main")
print("ok")
