"""The workspace snapshot keeps opening when one project cannot be read."""

import subprocess
import unittest
from types import SimpleNamespace


class GitWorkflowError(RuntimeError):
    """Stands in for the engine's Git error, a RuntimeError."""


class SnapshotTests(unittest.TestCase):
    def test_a_project_whose_git_fails_is_unavailable_instead_of_closing_the_workspace(
        self,
    ):
        # A fresh Windows without Git, and later a broken game repository, made
        # every snapshot raise, so the workspace never opened and Settings >
        # Updates, the way out, stayed locked. The project must report the
        # reason in words and the rest must load.
        from dazedtl.api.server import Application

        timeout = subprocess.TimeoutExpired(["git", "cat-file", "blob", "abc"], 30)
        for error, shown in [
            (
                GitWorkflowError("Git is not installed or is not available on PATH"),
                "Git is not installed",
            ),
            (timeout, "A tool this project needs could not finish"),
        ]:

            def unreadable(_project_id, error=error):
                raise error

            project = {
                "id": "project",
                "name": "Game",
                "source": "/games/game",
                "engine": "MVMZ",
                "method": "guided",
                "available": True,
            }
            failures = []
            app = SimpleNamespace(
                state=lambda project=project: {
                    "project": project,
                    "recent": [],
                    "screen": "project",
                    "running": False,
                    "observing": False,
                    "provider_ready": True,
                },
                translation=SimpleNamespace(state=unreadable),
                images=SimpleNamespace(state=unreadable),
                plugins=SimpleNamespace(state=unreadable),
                assistant_tasks=SimpleNamespace(view=unreadable),
                failure=lambda failure, *_args, failures=failures: failures.append(
                    failure
                ),
            )
            app.unreadable = lambda failure, app=app: Application.unreadable(
                app, failure
            )
            snapshot = Application.snapshot(app)
            project_view = snapshot["application"]["project"]
            self.assertEqual(project_view["status"], "Project unavailable")
            self.assertIn(shown, project_view["detail"])
            self.assertNotIn("[", project_view["detail"])
            for key in ("translationError", "imagesError", "pluginsError"):
                self.assertIn(shown, snapshot[key])
            self.assertEqual(snapshot["assistantTasks"], [])
            # Tool failures keep their full detail for diagnostics.
            self.assertEqual(
                failures, [error] * 3 if error is timeout else [], repr(error)
            )
