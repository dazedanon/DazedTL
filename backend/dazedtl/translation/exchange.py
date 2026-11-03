"""A project's translation file (translation_file), whichever method
translates it: exporting its lines with their current translations, and
importing a file's translations back onto the same lines.

Each method names its lines its own way, and a line set gives the rest one
interface: its lines in play order with their current translations, why a
translation would not be kept, and how translations are saved. Assistant-led
and Manual name lines by their units' IDs and keep translations in the
accepted results, where an imported translation is a receipt of its own
(unit_results.save_import), so every later run and export reads it as a
run's; Guided names them by their place in the game's files (guided_lines).
The game's glossary travels with its lines, and an import only adds the terms
the glossary lacks.
"""

from pathlib import Path

from dazedtl.projects.store import working_method
from dazedtl.settings import language_pair

from . import organize, translation_file, unit_results
from .files import project_path, read_json
from .project import MANUAL_UNITS


class UnitLines:
    """The lines of a units file and their translations in the accepted
    results, which Assistant-led's assistant or a Manual project's own
    extractor wrote."""

    def __init__(self, store, project_id, root, units, pair, quotes):
        self.store, self.project_id, self.root = store, project_id, Path(root)
        self.units = units
        self.by_id = {unit["id"]: unit for unit in units}
        self.pair, self.quotes = pair, quotes

    def lines(self):
        """Each unit's fields with its current translation, or None."""
        found = unit_results.translations(
            self.store,
            self.project_id,
            self.root,
            self.units,
            self.pair["source"],
            self.pair["target"],
            self.quotes,
        )
        return [
            {
                "id": unit["id"],
                "scene": unit["scene"],
                "group": unit["group"],
                "kind": unit["kind"],
                "speaker": unit["speaker"],
                "source": unit["source"],
                "translation": found.get(unit["id"]),
                **({"field": unit["field"]} if unit["field"] else {}),
                **unit["constraints"],
            }
            for unit in self.units
        ]

    def problems(self, translations):
        return unit_results.import_problems(
            self.by_id, translations, self.pair["source"], self.pair["target"]
        )

    def idle(self):
        """Nothing beyond the Translation service's own check (idle)."""

    def save(self, translations, name):
        unit_results.save_import(
            self.root,
            self.by_id,
            translations,
            self.pair["source"],
            self.pair["target"],
            name,
        )


def units_file(root, relative):
    """The validated units of the units file at *relative* in the game."""
    return organize.units_input(read_json(project_path(root, relative)))


def assistant_units(store, project_id, root):
    """The units the assistant last organized: the units file of the newest
    run its organize compiled, or None before one."""
    for job in store.list(project_id):
        if job["kind"] != "translation":
            continue
        try:
            _job, plan = store.load(job["id"], project_id)
        except OSError, ValueError:
            continue
        relative = plan.get("input_path")
        if plan.get("method") or not relative or not organize.owns(relative):
            continue
        try:
            inputs = read_json(project_path(root, relative))["inputs"]
            return units_file(root, inputs[0])
        except OSError, ValueError, KeyError, IndexError, TypeError:
            return None
    return None


def glossary_entries(root):
    """The game glossary's entries, each a section, source, translation and
    note; the shipped base glossary and rows that aren't `source
    (translation)` stay out."""
    from util.vocab import read_game_vocab, split_glossary_row

    section = ""
    entries = []
    for row in read_game_vocab(root, create=False).splitlines():
        text = row.strip()
        if text.startswith("#"):
            section = text.lstrip("#").strip()
            continue
        parsed = split_glossary_row(text) if section else None
        if not parsed or not parsed[1]:
            continue
        source, translation, rest = parsed
        note = rest.strip().removeprefix("-").strip()
        entries.append(
            {
                "section": section,
                "source": source,
                "translation": translation,
                "note": note,
            }
        )
    return entries


def glossary_counts(root, entries):
    """What importing glossary *entries* adds: the terms whose sources no row
    of the game glossary covers, in any section or as a slash variant
    (util.vocab glossary_row_sources), by section, so an imported name never
    competes with one the game has, such as a character row outranking a
    speaker's; and how many it covers already, the same or not."""
    from util.vocab import glossary_row_sources

    held = {}
    for entry in glossary_entries(root):
        for source in glossary_row_sources(entry["source"], entry["section"]):
            held.setdefault(source, entry["translation"])
    added: dict[str, list] = {}
    counts = {"added": 0, "same": 0, "differs": 0}
    for entry in entries:
        sources = glossary_row_sources(entry["source"], entry["section"])
        known = {held[source] for source in sources if source in held}
        if not known:
            for source in sources:
                held[source] = entry["translation"]
            added.setdefault(entry["section"], []).append(
                (entry["source"], entry["translation"], entry["note"])
            )
            counts["added"] += 1
        elif known == {entry["translation"]}:
            counts["same"] += 1
        else:
            counts["differs"] += 1
    return added, counts


class Exchange:
    """Translation files for the projects the Translation service and
    Guided hold. *guided_lines* gives a Guided project's line set."""

    def __init__(self, translation, guided_lines):
        self.translation = translation
        self.guided_lines = guided_lines

    def _lines(self, project_id):
        record, project = self.translation.project(project_id)
        root = project.root
        settings = self.translation.settings
        pair = language_pair.pair(settings, root)
        # A game whose method was never chosen reads as Assistant-led's.
        method = working_method(record, True)
        if method == "guided":
            return (
                record,
                root,
                pair,
                self.guided_lines(project_id, pair, settings.convert_quotes()),
            )
        if method == "manual":
            if not project_path(root, MANUAL_UNITS, exists=False).is_file():
                raise ValueError("Load your text file first.")
            units = units_file(root, MANUAL_UNITS)
        else:
            units = assistant_units(self.translation.jobs.store, project_id, root)
            if units is None:
                raise ValueError(
                    "Your assistant hasn't organized the game's text yet, so there are no lines to export or import."
                )
        lines = UnitLines(
            self.translation.jobs.store,
            project_id,
            root,
            units,
            pair,
            settings.convert_quotes(),
        )
        return record, root, pair, lines

    def export(self, project_id, path):
        """Writes the project's lines with their current translations and
        the game glossary to *path*, outside the game, and says how many
        lines it holds and how many are translated."""
        record, root, pair, lines = self._lines(project_id)
        target = translation_file.destination(path, root)
        rows = lines.lines()
        glossary = glossary_entries(root)
        translation_file.write(
            target,
            translation_file.document(
                pair,
                rows,
                glossary if target.suffix.lower() == ".json" else (),
                {
                    "title": record.get("name") or root.name,
                    "engine": record.get("engine") or "",
                    "method": record.get("method"),
                },
            ),
        )
        return {
            "path": str(target),
            "lines": len(rows),
            "translated": sum(row["translation"] is not None for row in rows),
            "glossary": len(glossary) if target.suffix.lower() == ".json" else 0,
        }

    def _matched(self, project_id, path):
        _record, root, pair, lines = self._lines(project_id)
        value = translation_file.read(path)
        translation_file.check_languages(value["languages"], pair)
        current = {
            row["id"]: {"source": row["source"], "translation": row["translation"]}
            for row in lines.lines()
        }
        write, summary = translation_file.matched(
            value["lines"], current, lines.problems
        )
        added, glossary = glossary_counts(root, value["glossary"])
        return (
            root,
            lines,
            value,
            write,
            added,
            {
                **summary,
                "name": Path(path).name,
                "sha256": value["sha256"],
                "glossary": glossary,
            },
        )

    def preview(self, project_id, path):
        """What importing the translation file at *path* would change,
        without changing anything; its sha256 binds the import."""
        return self._matched(project_id, path)[-1]

    def apply(self, project_id, path, sha256):
        """Imports the translation file at *path*, the one its preview read
        (*sha256*): each line whose ID and source match takes its
        translation, and the glossary gains the terms it lacks."""
        self.translation.idle(project_id)
        root, lines, _value, write, added, summary = self._matched(project_id, path)
        if summary["sha256"] != sha256:
            raise ValueError(
                "The file changed after it was checked. Check it again before importing."
            )
        lines.idle()
        if write:
            lines.save(write, summary["name"])
        if added:
            self.translation.engine.glossary_add(root, added, "Import glossary terms")
        if write or added:
            # Requests read both, so no waiting estimate pays for lines the
            # file translated or replaces them with its reply.
            self.translation.jobs.store.retire_estimates(project_id)
        return summary
