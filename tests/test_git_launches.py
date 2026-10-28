"""Checkpoint operations start no more Git processes than their budgets, and
what they keep of a repository between writes still sees it change.

Each Git process takes about 100 ms to start on a loaded Windows runner, and
Windows users pay that on every save: the checkpoint probe once launched Git
over a thousand times and timed Windows CI out. Linux counts the same
launches in a fraction of the time, so a change that adds one fails here.
"""

import os
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.compatibility import (
    checkpoint_commits,
    checkpoint_history,
    game_write,
    original_files,
)
from dazedtl.compatibility.checkpoint_commits import for_action, running
from dazedtl.compatibility.game_write import write_game
from util.len_git import git_status, setup_git
from util.len_translation import LenProject
from util.version_update import git_workflow

ROOT = Path(__file__).resolve().parents[1]
# Git processes each operation may start on a set-up MZ game that holds one
# of DazedTL's own runtime files, in this order; 2.40.2 started 38, 14, 12,
# 18, 9, 23, 24 and 6. Operations' workers start with nothing read.
BUDGETS = {
    "Set up in a new process": 35,
    "a write in a new process": 10,
    "a write after another": 6,
    "a write after an edit made outside DazedTL": 10,
    "the Checkpoints tab's read after a write": 2,
    "an undo in a new process": 16,
    "a go back in a new process": 17,
    "the version update status": 5,
}


def fresh():
    """Forgets what this process read of games' repositories, as a new
    worker process starts with nothing read."""
    game_write._statuses.clear()
    git_workflow._settings_read.clear()
    git_workflow._common_dirs.clear()
    checkpoint_commits._trees.clear()
    checkpoint_commits._tracked_at.clear()
    original_files._READ.clear()


@contextmanager
def launches(folder):
    """Counts the Git processes started in `folder`."""
    started = []
    original = subprocess.Popen

    class Counted(original):
        def __init__(self, arguments, *rest, **options):
            command = [str(part) for part in arguments]
            target = options.get("cwd") or ""
            if "-C" in command:
                target = command[command.index("-C") + 1]
            if Path(command[0]).stem == "git" and str(target).startswith(folder):
                started.append(command)
            super().__init__(arguments, *rest, **options)

    subprocess.Popen = Counted
    try:
        yield started
    finally:
        subprocess.Popen = original


def git(game, *arguments):
    return subprocess.run(
        ["git", "-C", str(game), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


@unittest.skipIf(os.name == "nt", "Linux counts the same launches in less time.")
class GitLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.game = Path(temporary.name) / "game"
        shutil.copytree(ROOT / "tests/fixtures/mz-game", self.game)
        (self.game / "GameUpdate.bat").write_bytes(b"@echo off\r\n")
        self.project = LenProject(self.game)
        self.counts = {}

    def count(self, name, operation, new_process=False):
        if new_process:
            fresh()
        with launches(str(self.game)) as started:
            value = operation()
        self.counts[name] = len(started)
        return value

    def write(self, raw, name="data/Map001.json"):
        with (
            running(for_action("export_selected")),
            write_game(self.game, paths=[name]) as written,
        ):
            written.put(name, raw)

    def set_up(self):
        return setup_git(self.project, version="1.0", current_is_untranslated=True)

    def test_checkpoint_operations_stay_within_their_git_launches(self):
        game, count, write = self.game, self.count, self.write
        count("Set up in a new process", self.set_up, True)
        count("a write in a new process", lambda: write(b'{"a": 1}'), True)
        count("a write after another", lambda: write(b"[null]", "data/Items.json"))
        (game / "data/System.json").write_bytes(b"{}")
        count("a write after an edit made outside DazedTL", lambda: write(b"{}"))
        view = count(
            "the Checkpoints tab's read after a write",
            lambda: game_write.checkout(game) and checkpoint_history.timeline(game),
        )
        newest, _, third, *_ = [
            row["commit"] for row in view["versions"][0]["checkpoints"]
        ]
        count(
            "an undo in a new process",
            lambda: checkpoint_history.undo(game, newest),
            True,
        )
        count(
            "a go back in a new process",
            lambda: checkpoint_history.go_back(game, third),
            True,
        )
        count("the version update status", lambda: git_status(self.project))
        self.assertEqual(
            {name: max(self.counts[name], budget) for name, budget in BUDGETS.items()},
            BUDGETS,
            self.counts,
        )

    def test_a_kept_read_still_sees_a_branch_switch_and_staged_changes(self):
        game = self.game
        self.set_up()
        git(game, "branch", "elsewhere")
        self.write(b'{"a": 1}')
        head = git(game, "rev-parse", "HEAD")
        # The read a write kept would let one onto another branch, which
        # misses the translation's version.
        git(game, "checkout", "-q", "elsewhere")
        with self.assertRaisesRegex(ValueError, "translation branch “main”"):
            self.write(b'{"a": 2}')
        git(game, "checkout", "-q", "main")
        self.assertEqual(git(game, "rev-parse", "HEAD"), head)
        self.assertEqual(git(game, "status", "--porcelain"), "")
        # A checkpoint built on the index would commit what the user staged,
        # which stays staged while another write in progress that named no
        # files leaves it to that write.
        (game / "data/Items.json").write_bytes(b'["staged"]')
        git(game, "add", "data/Items.json")
        other = checkpoint_commits._Write(checkpoint_commits._folder(game), None, None)
        try:
            self.write(b'{"a": 3}')
        finally:
            other.close()
        self.assertEqual(
            git(game, "diff-tree", "--name-only", "-r", "HEAD", "HEAD~1").split(),
            ["data/Map001.json"],
        )
        self.assertEqual(
            git(game, "diff", "--cached", "--name-only").split(), ["data/Items.json"]
        )


if __name__ == "__main__":
    unittest.main()
