"""Each game's GameUpdate config, kept in step with Settings and the game's
own repository for both methods' Project page.

The engine owns the file and its rules; this decides when they run: on
opening a game, on returning to the window, after Settings change, before
saving a translation version or building a release, and on the user's own
choices.
"""

ACTIONS = {"save", "keep", "replace", "defaults"}
# The engine's status of a game without GameUpdate.
ABSENT = {
    "state": "absent",
    "message": "",
    "repo": "",
    "suggested": "",
    "values": None,
    "file": None,
    "placeholder": False,
    "differences": [],
    "overrides": [],
    "committed": False,
    "remote": "",
}


def _public(values):
    if values is None:
        return None
    return {
        "forge": values["forge"],
        "host": values["host"],
        "owner": values["username"],
        "repo": values["repo"],
        "branch": values["branch"],
    }


def _field(name):
    return "owner" if name == "username" else name


def view(status):
    """The engine's status in the API's words."""
    return {
        "state": status["state"],
        "message": status["message"],
        "repo": status["repo"],
        "suggested": status["suggested"],
        "values": _public(status["values"]),
        "file": _public(status["file"]),
        "placeholder": status["placeholder"],
        "differences": [_field(name) for name in status["differences"]],
        "overrides": [_field(name) for name in status["overrides"]],
        "committed": status["committed"],
        "remote": status["remote"],
    }


class GameUpdate:
    def __init__(self, translation):
        self.translation = translation

    def defaults(self):
        return self.translation.settings.game_update()

    def busy(self, project_id):
        """Whether an operation is changing the game or its Git history."""
        return (
            self.translation.jobs.running(project_id, "operation")
            or self.translation.settings.adapter.running()
        )

    def _root(self, project_id):
        _record, project = self.translation.project(project_id)
        return project.root

    def state(self, project_id):
        try:
            return view(
                self.translation.engine.game_update(
                    self._root(project_id), self.defaults()
                )
            )
        except (ValueError, OSError, RuntimeError) as exc:
            return view({**ABSENT, "state": "unavailable", "message": str(exc)})

    def sync(self, project_id):
        """Writes a missing, placeholder or outdated config while nothing else
        changes the game; a failure waits for the next sync and shows in the
        Project page's status."""
        if self.busy(project_id):
            return
        try:
            self.translation.engine.game_update(
                self._root(project_id), self.defaults(), "sync"
            )
        except ValueError, OSError, RuntimeError:
            pass

    def act(self, project_id, action, repo=None):
        """The user's choice on the Project page."""
        if action not in ACTIONS:
            raise ValueError("Choose a GameUpdate action.")
        if action == "save" and not isinstance(repo, str):
            raise ValueError("Enter the game's GameUpdate repository.")
        if self.busy(project_id):
            raise ValueError(
                "Wait for the current operation to finish before changing GameUpdate."
            )
        return view(
            self.translation.engine.game_update(
                self._root(project_id), self.defaults(), action, repo
            )
        )

    def require_ready(self, project_id):
        """Refuses a release while GameUpdate is set up but cannot be written."""
        self.sync(project_id)
        current = self.state(project_id)
        if current["state"] == "needs_repo":
            raise ValueError(
                "Enter the GameUpdate repository on the Project page's Game updates tab before building."
            )
        if current["state"] == "pending":
            raise ValueError(
                "GameUpdate's config could not be written. Check the Project page's Game updates tab."
            )
