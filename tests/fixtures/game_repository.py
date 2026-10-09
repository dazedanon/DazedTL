"""Real Git journeys for a game's version save: interrupted baselines and a held index lock."""

import shutil
import subprocess
import sys
import threading
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util.len_git import setup_git
from util.len_translation import LenProject
from util.version_update import GitWorkflowError
from util.version_update.git_workflow import _run_git


def git(game, *arguments):
    return subprocess.run(
        ["git", "-C", str(game), *arguments],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def game(name):
    folder = temporary / name
    shutil.copytree(root / "tests/fixtures/mz-game", folder)
    return folder


def save(folder):
    return setup_git(LenProject(folder), version="1.0", current_is_untranslated=True)


def refused(folder):
    data = {path: path.read_bytes() for path in folder.glob("data/*")}
    try:
        save(folder)
    except GitWorkflowError as error:
        assert "Review and checkpoint" in str(error), error
    else:
        raise AssertionError(f"{folder.name}: setup adopted someone else's repository")
    assert data == {path: path.read_bytes() for path in folder.glob("data/*")}


# A forced stop between git init and the first commit.
stopped = game("stopped")
git(stopped, "init", "-q", "-b", "main")
git(stopped, "config", "dazedtl.preserveGameFiles", "true")
result = save(stopped)
assert result["configured"] and result["worktree_clean"], result

# Baseline commits made, but the index write lost a race and the branch was
# never registered. The redo keeps the earlier commit in the reflog.
raced = game("raced")
first = save(raced)["translation_commit"]
(raced / ".git/index").unlink()
git(raced, "config", "--unset", "dazedtl.translationBranch")
result = save(raced)
assert result["configured"] and result["worktree_clean"], result
assert first in git(raced, "log", "-g", "--format=%H", "main").split()

# Repositories holding anyone else's work keep the refusal.
own = game("own")
git(own, "init", "-q", "-b", "main")
git(own, "add", "data/System.json")
refused(own)
player = ("-c", "user.name=Player", "-c", "user.email=player@example.invalid")
git(own, *player, "commit", "-qm", "Mine")
refused(own)

# A `git status` holds the index lock briefly; an index write waits for it.
lock = raced / ".git/index.lock"
lock.write_bytes(b"")
threading.Timer(0.2, lock.unlink).start()
_run_git(raced, "read-tree", "main")
print("ok")
