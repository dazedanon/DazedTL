"""Manual: the user's own tools extract a game's text into a translation
file and write the translations back, for any engine, and DazedTL
translates the file with the API runs Assistant-led uses, its glossary,
speakers, checks and approval included (docs/translation-contract.md,
Translation files).

Loading a file makes its lines the project's units, which estimates
organize into requests; translations the file already holds are imported
first, so only the lines without one are sent. The user's extractor
decides what is in scope, so no census is needed, and DazedTL never writes
the game, so no Git baseline is either (project MANUAL). The project's
translation file comes back out with Export (exchange).
"""

from pathlib import Path

from dazedtl.settings import language_pair
from dazedtl.storage import write_json

from . import translation_file
from .exchange import MANUAL_UNITS, UnitLines, units_file
from .files import project_path, read_json
from .jobs import now

# What the user last loaded: the file's name, path and digest, when, and
# its counts, beside the units it became.
LOADED = ".dazedtl/manual/loaded.json"


def loaded(root):
    """The file the game at *root* last loaded, or None before one."""
    path = project_path(root, LOADED, exists=False)
    units = project_path(root, MANUAL_UNITS, exists=False)
    if not path.is_file() or not units.is_file():
        return None
    try:
        return read_json(path)
    except OSError, ValueError:
        return None


class Manual:
    def __init__(self, translation):
        self.translation = translation

    def _project(self, project_id):
        record, project = self.translation.project(project_id)
        if record.get("method") != "manual":
            raise ValueError("This game isn't translated Manually.")
        return project

    def load(self, project_id, path):
        """Makes the translation file at *path* the project's text: its lines
        become the units estimates organize, replacing any loaded before, and
        the translations it holds are imported. Lines whose ID and source
        stay the same keep their translations."""
        project = self._project(project_id)
        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        root = project.root
        pair = language_pair.pair(self.translation.settings, root)
        value = translation_file.read(path)
        translation_file.check_languages(value["languages"], pair)
        units = translation_file.units(value["lines"])
        relative = project_path(root, MANUAL_UNITS, exists=False)
        document = {
            "version": 1,
            "units": [
                {key: item for key, item in line.items() if key != "translation"}
                for line in value["lines"]
            ],
        }
        if not relative.is_file() or read_json(relative) != document:
            write_json(relative, document)
        lines = UnitLines(
            self.translation.jobs.store,
            project_id,
            root,
            units,
            pair,
            self.translation.settings.convert_quotes(),
        )
        current = {
            row["id"]: {"source": row["source"], "translation": row["translation"]}
            for row in lines.lines()
        }
        write, summary = translation_file.matched(
            value["lines"], current, lines.problems
        )
        if write:
            lines.save(write, Path(path).name)
        loaded = {
            "name": Path(path).name,
            "path": str(Path(path)),
            "sha256": value["sha256"],
            "loaded": now(),
            "lines": len(units),
            "scenes": len({unit["scene"] for unit in units}),
            # The file's translations the project now holds.
            "translations": summary["unchanged"]
            + summary["added"]
            + summary["replaced"],
        }
        write_json(project_path(root, LOADED, exists=False), loaded)
        return {**summary, "loaded": loaded}

    def estimate(self, project_id):
        """Starts the estimate of the loaded lines without a translation, as
        organize packs them, in the project's API mode
        (Translation.manual_mode)."""
        project = self._project(project_id)
        if not project_path(project.root, MANUAL_UNITS, exists=False).is_file():
            raise ValueError("Load your text file first.")
        units_file(project.root, MANUAL_UNITS)
        mode = self.translation.manual_mode(project)
        return self.translation.organize_manual(project_id, MANUAL_UNITS, mode)
