"""Keeps a game's window title current (engine/util/window_title) where
DazedTL makes no write of its own to carry it: when Settings' translator
name changes, when the game opens or the window returns, as GameUpdate's
config follows Settings there, and as a release's review opens, before it
reads the game, such as after a game update registered a version."""

from pathlib import Path


def refresh(root, game_write):
    """Brings the title of the game at `root` up to date in a checkpoint of
    its own; `game_write(**options)` opens the game's write gateway, with its
    Guided workspace where it has one. A failure waits for the next one."""
    from util import window_title

    root = Path(root)
    try:
        changed = window_title.pending(root)
        if not changed:
            return
        # VX Ace writes Game.ini where it packs, which keeps the packing
        # receipt current in the game's Guided workspace.
        ace = (root / "ace_json").is_dir()
        with game_write(
            paths=["ace_json/System.json", *changed] if ace else changed,
            summary="Update the window title",
            stage="Release",
        ) as game:
            if ace:
                game.wrote("ace_json/System.json")
    except ValueError, OSError, RuntimeError:
        pass


class WindowTitle:
    def __init__(self, translation):
        self.translation = translation

    def sync(self, project_id):
        """`refresh` for a project, while nothing else changes the game."""
        if self.translation.game_update.busy(project_id):
            return
        try:
            _record, project = self.translation.project(project_id)
        except ValueError, OSError:
            return
        backend = self.translation.projects.get(project_id).get("backend_id")
        refresh(
            project.root,
            lambda **options: self.translation.settings.adapter.game_write(
                project.root, backend, **options
            ),
        )
