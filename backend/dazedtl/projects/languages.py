"""Each project's language pair as the app shows and keeps it
(settings/language_pair): the pair its game translates between, recorded
when the app opens the game, which Set up can change until the game has
work, and which a game with work keeps whatever Settings' defaults name
later."""

from pathlib import Path

from dazedtl.compatibility.original_files import recorded
from dazedtl.languages import load_language_pair, tag, target_uses_cjk
from dazedtl.settings import language_pair, preferences

# Writing a record goes through the game write gateway, which may refuse.
REFUSALS = (OSError, ValueError, RuntimeError)


class ProjectLanguages:
    def __init__(self, projects, settings, *, holds, has_work):
        self.projects = projects
        self.settings = settings
        self.holds = holds
        self.has_work = has_work

    def view(self, project):
        """The pair the project's game translates between, or None while its
        folder or settings can't be read."""
        try:
            pair = language_pair.pair(self.settings, project["source"])
        except REFUSALS:
            return None
        return {
            "source": pair["source"],
            "target": pair["target"],
            "characters": target_uses_cjk(pair["target"]),
            "sourceTag": tag(pair["source"]),
            "targetTag": tag(pair["target"]),
        }

    def keep(self, project):
        """Records the pair of a game set up before pairs were recorded, as
        the app opens it. A refused write leaves it for the next opening;
        until then the game reads the same pair (language_pair.pair)."""
        if not self.unrecorded(project):
            return
        try:
            language_pair.keep(self.settings, project["source"])
        except REFUSALS:
            pass

    def keep_every(self):
        """Records the pair of every game set up before pairs were recorded,
        before Settings' default pair changes, so its work keeps its pair. A
        game whose folder is unavailable reads Settings' target until the
        app opens it again and records it."""
        for project in self.projects.data["projects"]:
            if not self.unrecorded(project):
                continue
            try:
                language_pair.keep(self.settings, project["source"])
            except REFUSALS as error:
                raise ValueError(
                    f"{project['name']}'s languages could not be recorded, so the "
                    f"defaults stay as they are: {error}"
                ) from error

    def unrecorded(self, project):
        """Whether the project's game is there without a recorded pair, set
        up, which records its original files, or with work from before that
        record existed."""
        try:
            if not self.holds(project) or load_language_pair(project["source"]):
                return False
        except REFUSALS:
            return False
        return recorded(project["source"]) or self.has_work(project)

    def locked(self, project):
        """Why the game's pair can't change any more, or "" while it can: a
        game with work keeps the pair all its saved runs mean. It reads every
        saved run, so Set up asks as its dialog opens, never in a snapshot."""
        if not self.has_work(project):
            return ""
        current = language_pair.pair(self.settings, project["source"])
        return (
            f"This game already has work translating {current['source']} into "
            f"{current['target']}, so its languages can't change; every saved "
            "run would mean something else. Open a fresh copy of the game as a "
            "new project to translate it another way."
        )

    def change(self, project_id, source, target):
        """Set up's choice of the game's pair, refused once it is locked."""
        project = self.projects.get(project_id)
        if not self.holds(project):
            raise ValueError("Find the game folder before changing its languages.")
        root = Path(project["source"])
        current = language_pair.pair(self.settings, root)
        chosen = {
            "source": language_pair.source_language(source),
            "target": preferences.text(target, "target language", required=True),
        }
        if chosen == current:
            if load_language_pair(root) is None:
                language_pair.choose(root, chosen["source"], chosen["target"])
            return
        refusal = self.locked(project)
        if refusal:
            raise ValueError(refusal)
        language_pair.choose(root, chosen["source"], chosen["target"])
