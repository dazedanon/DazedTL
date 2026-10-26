"""A failure reaches the page with the file and reason, or Git's own wording, and nothing private."""

import errno
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/dazedtl/engine"))

from dazedtl.api.views import error
from util.version_update import GitWorkflowError, git_workflow


class ErrorMappingTests(unittest.TestCase):
    def test_a_file_failure_names_its_game_file_and_reason(self):
        # A read-only glossary read "The file operation could not finish."
        game = Path("/games/Hero")
        denied = PermissionError(
            errno.EACCES, "Denied", str(game / ".dazedtl/glossary.txt")
        )
        shown = error(denied, [game])
        self.assertEqual(shown["code"], "storage")
        self.assertIn(".dazedtl/glossary.txt", shown["message"])
        self.assertIn("read-only", shown["message"])
        self.assertNotIn("/games", shown["message"])

    def test_a_file_outside_the_game_and_profile_is_not_named(self):
        elsewhere = PermissionError(errno.EACCES, "Denied", "/home/someone/secret.txt")
        self.assertNotIn("secret", error(elsewhere, [Path("/games/Hero")])["message"])
        self.assertNotIn("secret", error(elsewhere)["message"])

    def test_git_messages_for_the_user_pass_and_other_faults_stay_generic(self):
        # A leftover .git/index.lock read "The operation could not finish."
        lock = git_workflow.UserFacingGitError(
            "Another Git process is using this repository."
        )
        self.assertEqual(error(lock)["message"], str(lock))
        private = GitWorkflowError("fatal: /home/someone/repo is bad")
        self.assertEqual(error(private)["code"], "internal")
        self.assertNotIn("someone", error(private)["message"])
