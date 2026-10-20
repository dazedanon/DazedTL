"""Real Git journeys for a game's repository: interrupted baselines, a held
index lock, original files read in one process and the GameUpdate config a
published patch carries."""

import hashlib
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch

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
from dazedtl.compatibility.guided import guard_context
from dazedtl.compatibility.observations import RunObservations
from dazedtl.compatibility.translation import TranslationEngine
from desktop.backend.workflow_actions import action_guard
from util import freshness
from util import gameupdate_config as updater
from util.game_settings import load_game_update, save_game_wrap_widths

defaults = {
    "forge": "gitlab",
    "host": "gitgud.io",
    "username": "dazed-translations",
    "branch": "main",
}
published = game("published")
# The game's own main.js, which loads the playtest's fixes once they exist.
(published / "js/main.js").write_text("PluginManager.setup($plugins);\n")
(published / "gameupdate").mkdir()
(published / "gameupdate/patch.ps1").write_text("# GameUpdate fixture\n")
save(published)
config = published / updater.CONFIG
state = updater.reconcile(published, defaults)
assert state["state"] == "needs_repo" and not config.exists(), state
# An earlier version left a placeholder; it must never be published.
config.write_text("username=dazed-translations\nrepo=YOUR_PATCH_REPO\nbranch=main\n")
engine = TranslationEngine(temporary / "profile")
# Every original file comes out of one Git process with its own bytes, which
# its blob ID hashes; a missing blob stops the read.
blobs = [
    row.split()[2] for row in git(published, "ls-tree", "-r", "original").splitlines()
]
read = dict(engine.original_blobs(published, blobs))
assert len(blobs) > 2 and set(read) == set(blobs), read.keys()
for blob, raw in read.items():
    assert hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest() == blob, blob
try:
    dict(engine.original_blobs(published, [blobs[0], "0" * 40, blobs[1]]))
except ValueError as error:
    assert "is not a saved file" in str(error), error
else:
    raise AssertionError("A missing original blob was read.")
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
    # A patch's plugins.js may not switch on a plugin neither the patch nor
    # players' game has, which stops their game at start: one the assistant
    # wrote, or DazedTL's TL Inspector, which no release has even when the
    # backup lists it. The game's own plugins need not join the patch, in any
    # letter case, including one with a save-like name that only the
    # backup's list holds.
    registry = published / "js/plugins.js"
    shipped = registry.read_bytes()
    # The untranslated plugins.js, as a checkpoint restores it from the backup.
    original = temporary / "published-original"
    (original / "js").mkdir(parents=True)
    (original / "js/plugins.js").write_bytes(shipped)
    added = [published / f"js/plugins/{name}.js" for name in ("Wrap", "TLInspector")]
    for path in added:
        path.write_text("// Plugin\n")
    # The game's own TitleMessage and SaveLayout, and a plugin switched off.
    loaded = ["TitleMessage", "SaveLayout", "Wrap", "TLInspector"]
    registry.write_text(
        "var $plugins = [\n"
        + "".join(f'{{"name":"{name}","status":true}},\n' for name in loaded)
        + '{"name":"Old","status":false}\n];\n'
    )
    scoped = {"files": {"data/System.json": {}, "js/plugins.js": {}}}
    backup = ["js/plugins/savelayout.js", "js/plugins/TLInspector.js"]
    try:
        engine.git_scope(published, options, scoped, str(original), True, backup)
    except GitWorkflowError as error:
        assert str(error).startswith(
            "js/plugins.js loads the plugins TLInspector and Wrap,"
        ), error
    else:
        raise AssertionError("A patch loaded plugins players lack.")
    for path in added:
        scoped["files"][path.relative_to(published).as_posix()] = {
            "original_sha256": None
        }
    engine.git_scope(published, options, scoped, str(original), True, backup)
    registry.write_bytes(shipped)
    for path in added:
        path.unlink()
    # With no backup, the original of the main.js loading the playtest's
    # fixes is the file without that line, as the game's asset record holds
    # it; a checkpoint then refused the fixes. Each goes to players only
    # with the other: fixes main.js no longer loads, as a game update can
    # leave it, and a main.js loading fixes the patch lacks are refused.
    from util.len_patch_scope import with_dazedtl_files
    from util.playtest import fixes

    main = published / fixes.MAIN
    game_main = main.read_bytes()
    (published / fixes.PLUGIN).write_text("// Fixes\n")
    main.write_bytes(fixes.with_loader(game_main))
    data = {"files": {"data/System.json": {}}}
    engine.git_scope(
        published, options, with_dazedtl_files(published, data), None, True
    )
    main.write_bytes(game_main)
    for scope, message in (
        (
            with_dazedtl_files(published, data),
            "js/main.js in the patch doesn't load them",
        ),
        ({"files": {**data["files"], fixes.MAIN: {}}}, None),
    ):
        if message is None:
            (published / fixes.PLUGIN).unlink()
            main.write_bytes(fixes.with_loader(game_main))
            message = "the patch has no js/plugins/DazedTL_Fixes.js"
        try:
            engine.git_scope(published, options, scope, None, True)
        except GitWorkflowError as error:
            assert message in str(error), error
        else:
            raise AssertionError(f"A checkpoint took {sorted(scope['files'])}.")
    main.write_bytes(game_main)
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
    # Guards reuse the digests of files that kept their stat signature, so a
    # data file rewritten at the same size must still read as changed.
    system = published / "data/System.json"
    with patch.object(freshness, "SETTLED_NS", -1):
        guard = action_guard({"source": str(published)}, temporary / "workflow")
        raw = system.read_bytes()
        system.write_bytes(raw[:-1] + (b" " if raw[-1:] != b" " else b"\n"))
        assert action_guard({"source": str(published)}, temporary / "workflow") != guard
    system.write_bytes(raw)

    # A poll's guard parts match the engine's, and follow a changed plugin.
    def shared():
        full = action_guard({"source": str(published)}, temporary / "workflow")
        return {
            key: value
            for key, value in full.items()
            if key not in {"data", "files", "translated", "variables"}
        }

    def polled():
        with observations.read():
            return guard_context({"source": str(published)}, observations.files())

    observations = RunObservations()
    plugin = published / "js/plugins/Polled.js"
    plugin.parent.mkdir(exist_ok=True)
    plugin.write_text("// first\n")
    (published / ".dazedtl/skills/notes").mkdir(parents=True)
    (published / ".dazedtl/skills/notes/style.md").write_text("Keep it short.\n")
    assert polled() == shared() and polled()["skills"], polled()
    plugin.write_text("// second\n")
    assert polled() == shared(), polled()
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
