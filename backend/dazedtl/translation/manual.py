"""Manual: the user's own tools extract a game's text into a translation
file and write the translations back, for any engine, and DazedTL
translates the file with the API runs Assistant-led uses, its glossary,
speakers, checks and approval included (docs/translation-contract.md,
Translation files).

Loading a file makes its lines the project's units, which estimates
organize into requests; translations the file already holds are imported
first, so only the lines without one are sent. The user's extractor
decides what is in scope, so no census is needed, and DazedTL writes the
game only to add or take out GameUpdate on the user's word (gameupdate), so
no Git baseline is either (project MANUAL). The project's translation file
comes back out with Export (exchange).
"""

import json
from pathlib import Path

from dazedtl.settings import language_pair
from dazedtl.storage import write_json

from . import translation_file
from .exchange import UnitLines, glossary_counts, units_file
from .files import JSON_LIMIT, evidence, project_path, read_json
from .jobs import now
from .project import MANUAL_UNITS

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
        stay the same keep their translations, and the game's glossary gains
        the terms of the file's it lacks."""
        project = self._project(project_id)
        self.translation.idle(project_id)
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
        # Estimates and exports read the units file back as JSON, as
        # write_json writes it, so its size is checked before anything.
        if (
            len(json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
            >= JSON_LIMIT
        ):
            raise ValueError(
                "That file holds more text than a Manual project keeps: its lines "
                "take more than 128 MB as JSON."
            )
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
        added, glossary = glossary_counts(root, value["glossary"])
        changed = not relative.is_file() or read_json(relative) != document
        if write or added or changed:
            # As an import does (Exchange.apply): what can refuse first, then
            # the runs that would send the lines again end, then the file's
            # translations are saved before its lines replace the units.
            store = self.translation.jobs.store
            store.check_settled(project_id)
            if added:
                self.translation.engine.glossary_add(
                    root, added, "Load the text file's glossary terms"
                )
            store.retire(project_id)
        if write:
            lines.save(write, Path(path).name)
        if changed:
            write_json(relative, document)
        loaded = {
            # What a Manual run's estimate read, so a run of another file
            # reads as one (Translation.job_views).
            "units_sha256": evidence(root, [MANUAL_UNITS])[MANUAL_UNITS],
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
        return {
            **summary,
            "name": loaded["name"],
            "sha256": value["sha256"],
            "glossary": glossary,
            "loaded": loaded,
        }

    def example(self, project_id, path):
        """Saves an example translation file at *path*, outside the game, in
        the project's language pair, for the user's own extractor to follow."""
        project = self._project(project_id)
        target = translation_file.destination(path, project.root)
        value = translation_file.example(
            language_pair.pair(self.translation.settings, project.root)
        )
        translation_file.write(target, value)
        json = target.suffix.lower() == ".json"
        return {
            "path": str(target),
            "lines": len(value["lines"]),
            "translated": sum(
                line["translation"] is not None for line in value["lines"]
            ),
            "glossary": len(value["glossary"]) if json else 0,
        }

    def gameupdate(self, project_id, install):
        """Copies GameUpdate into the game, or takes it out, at once: no
        assistant installs it in a Manual game, so the box on Options shows
        and sets the game's own. The game's config follows, so the GameUpdate
        panel below the box shows it at once."""
        project = self._project(project_id)
        if type(install) is not bool:
            raise ValueError("Choose whether the game has GameUpdate.")
        self.translation.idle(project_id)
        self.translation.engine.set_gameupdate(project.root, install)
        self.translation.game_update.sync(project_id)
        return self.translation.game_update.state(project_id)

    def estimate(self, project_id):
        """Starts the estimate of the loaded lines without a translation, as
        organize packs them, in the project's API mode
        (Translation.manual_mode)."""
        project = self._project(project_id)
        if not project_path(project.root, MANUAL_UNITS, exists=False).is_file():
            raise ValueError("Load your text file first.")
        units_file(project.root, MANUAL_UNITS)
        mode = self.translation.run_mode(project, "manual")
        return self.translation.organize_manual(project_id, MANUAL_UNITS, mode)
