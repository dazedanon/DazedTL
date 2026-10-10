"""Real Git journeys for a game's repository: interrupted baselines, a held
index lock and the GameUpdate config a published patch carries."""

import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

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


# Tools the assistant installs in its work folder, such as a Python
# environment with symbolic links, are never part of the game's history.
tooled = game("tooled")
environment = tooled / ".dazedtl/len-method/work/.venv/bin"
environment.mkdir(parents=True)
try:
    (environment / "python").symlink_to(sys.executable)
except OSError:  # Windows without the symbolic link privilege
    pass
result = save(tooled)
assert result["configured"] and result["worktree_clean"], result

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

# GameUpdate: published repositories are patches players download, so the
# translation commit carries a working patch-config.txt that DazedTL writes
# from the saved defaults and the origin remote, never a placeholder.
from dazedtl.compatibility.translation import TranslationEngine
from desktop.backend.workflow_actions import action_guard
from util import gameupdate_config as updater
from util.game_settings import load_game_update, save_game_wrap_widths

defaults = {
    "forge": "gitlab",
    "host": "gitgud.io",
    "username": "dazed-translations",
    "branch": "main",
}
published = game("published")
(published / "gameupdate").mkdir()
(published / "gameupdate/patch.ps1").write_text("# GameUpdate fixture\n")
save(published)
config = published / updater.CONFIG
state = updater.reconcile(published, defaults)
assert state["state"] == "needs_repo" and not config.exists(), state
# An earlier version left a placeholder; it must never be published.
config.write_text("username=dazed-translations\nrepo=YOUR_PATCH_REPO\nbranch=main\n")
engine = TranslationEngine(temporary / "profile")
options = {
    "mode": "agent",
    "include_images": False,
    "instructions": "",
    "include_glossary_base": False,
    "install_forge": False,
}
manifest = {"files": {"data/System.json": {}}}


def checkpoint():
    engine.git_scope(published, options, manifest, None, False)
    engine.commit(published, "translation: fixture checkpoint")
    return git(published, "ls-files").split()


with engine.context():
    assert updater.CONFIG not in checkpoint()
    git(
        published,
        "remote",
        "add",
        "origin",
        "git@ssh.gitgud.io:dazed-translations/published.git",
    )
    save_game_wrap_widths(published, {"width": 64})
    guard = action_guard({"source": str(published)}, temporary / "workflow")
    state = updater.reconcile(published, defaults)
    assert state["state"] == "ready" and not state["committed"], state
    # The game's settings keep its repository beside the wrap widths; writing
    # it must not make saved QA, runs or reviews read Outdated.
    assert load_game_update(published)["repo"] == "published"
    assert action_guard({"source": str(published)}, temporary / "workflow") == guard
    save_game_wrap_widths(published, {"width": 70})
    assert action_guard({"source": str(published)}, temporary / "workflow") != guard
    assert config.read_text().splitlines()[2:] == [
        "forge=gitlab",
        "host=gitgud.io",
        "username=dazed-translations",
        "repo=published",
        "branch=main",
    ], config.read_text()
    assert updater.CONFIG in checkpoint()
    assert "!/gameupdate/patch-config.txt" in (published / ".gitignore").read_text()
    assert updater.status(published, defaults)["committed"]
    # A local patch ZIP is no verified public version, so it leaves the config out.
    packaged = engine.package(published, options, manifest, temporary / "deliveries")
    names = zipfile.ZipFile(packaged["path"]).namelist()
    assert "data/System.json" in names and updater.CONFIG not in names, names
    # DazedTL's own file follows Settings; a hand edit is reported, not overwritten.
    moved = {**defaults, "host": "gitlab.com"}
    assert updater.reconcile(published, moved)["state"] == "ready"
    assert "host=gitlab.com" in config.read_text()
    assert "remotes are on ssh.gitgud.io" in updater.status(published, moved)["remote"]
    config.write_text(config.read_text().replace("gitlab.com", "gitgud.io"))
    state = updater.reconcile(published, moved)
    assert state["state"] == "edited" and state["differences"] == ["host"], state
    assert "host=gitgud.io" in config.read_text()
    state = updater.reconcile(published, moved, "keep")
    assert state["state"] == "ready" and state["overrides"] == ["host"], state

# A working config DazedTL has not seen is the game's own: its values stay,
# including a forge and host other than Settings'.
mirrored = temporary / "mirrored"
(mirrored / "gameupdate").mkdir(parents=True)
(mirrored / "gameupdate/patch.ps1").write_text("# GameUpdate fixture\n")
git(mirrored, "init", "-q")
git(
    mirrored,
    "remote",
    "add",
    "origin",
    "https://git.dazedtl.dev/dazed-translations/mirrored",
)
own = "# Copied from the example\n forge=forgejo\n host=git.dazedtl.dev\nusername=dazed-translations\nrepo=mirrored\nbranch=main\n"
(mirrored / updater.CONFIG).write_text(own)
state = updater.reconcile(mirrored, defaults)
assert state["state"] == "ready" and state["overrides"] == ["forge", "host"], state
assert not state["remote"] and (mirrored / updater.CONFIG).read_text() == own, state
print("ok")
