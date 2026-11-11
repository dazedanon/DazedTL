"""Keeps a game's window title current (engine/util/window_title) where
DazedTL makes no write of its own to carry it: when Settings' translator
name changes, and when the game opens or the window returns, as
GameUpdate's config follows Settings there."""

from pathlib import Path


class WindowTitle:
    def __init__(self, translation):
        self.translation = translation

    def sync(self, project_id):
        """Brings the game's title up to date in a checkpoint of its own
        while nothing else changes the game; a failure waits for the next
        sync."""
        from util import window_title

        if self.translation.game_update.busy(project_id):
            return
        try:
            _record, project = self.translation.project(project_id)
            root = Path(project.root)
            changed = window_title.pending(root)
            if not changed:
                return
            # VX Ace writes Game.ini where it packs System, which keeps
            # the packing receipt current in the game's Guided workspace.
            ace = (root / "ace_json").is_dir()
            with self.translation.settings.adapter.game_write(
                root,
                self.translation.projects.get(project_id).get("backend_id"),
                paths=["ace_json/System.json", *changed] if ace else changed,
                summary="Update the window title",
                stage="Release",
            ) as game:
                if ace:
                    game.wrote("ace_json/System.json")
        except ValueError, OSError, RuntimeError:
            pass
