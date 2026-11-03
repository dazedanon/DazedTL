"""A Guided project's lines for its translation file (translation/exchange):
each text the engine sends as one (file_lines `sent`), in its file's newest
working copy, named by its file and its place in the game's original file.
Guided writes a translated message over fewer commands than the original
holds, so naming a line by its original place keeps its ID whether or not
the copy is translated, and two people's copies of one game version share
their IDs.

An ID is `<file>#<JSON pointer>` into the original file: a value's own, and
for an event text block its first command's, such as a message's window,
with `/parameters/4` after it for the message's name box and `~<n>` for its
later parts. A command the original doesn't hold at a place, such as one a
game update added, keeps its pointer into the copy.

Importing writes into each file's working copy, as a run's output does
(guided_inputs), and records each changed value's source as Guided does,
so Translate's Apply puts the translations in the game as one checkpoint,
fitted to the Line widths. Choice help and note labels are left out of an
import: their rows and sources follow rules of their own.
"""

import copy
from collections import defaultdict

from dazedtl import system
from dazedtl.compatibility.text import engine_json, imported_document
from dazedtl.languages import reading_game

from . import comment_text, file_lines
from .files import decode_json

# The kind each line is read as, beside its speaker (organize KINDS).
_KINDS = {"message": "dialogue", "scroll": "narration"}
# Lines whose rows or sources an import leaves alone.
_KEPT = {"help": "Choice help", "label": "Note labels"}


def _pointer(path):
    from util.rpgmaker_qa_preflight import pointer

    return pointer(path)


def _is_commands(value):
    return isinstance(value, list) and any(
        isinstance(item, dict) and "code" in item for item in value
    )


class _Places:
    """Paths into a working copy mapped to the same places in the original
    file (util/original_values `commands`), each command list paired once."""

    def __init__(self, document, original):
        self.document, self.original = document, original
        self.pairs = {}

    def of(self, path):
        """*path*'s place in the original, or *path* where the original
        holds no such place."""
        if self.original is None:
            return tuple(path)
        from util.original_values import at, commands

        node, theirs, found = self.document, self.original, []
        for part in path:
            other = part
            if _is_commands(node) and isinstance(theirs, list):
                if id(node) not in self.pairs:
                    self.pairs[id(node)] = (node, dict(commands(node, theirs)))
                other = self.pairs[id(node)][1].get(part)
                if other is None:
                    return tuple(path)
            found.append(other)
            node, theirs = at(node, (part,)), at(theirs, (other,))
            if theirs is None:
                return tuple(path)
        return tuple(found)


class GuidedLines:
    """The lines of a Guided project's game data files (file_lines)."""

    def __init__(self, guided, project_id, pair):
        self.guided = guided
        _project, self.native = guided.record(project_id)
        self.pair = pair
        self.inputs = guided.inputs(self.native)
        database = set(guided.backend.phase_files(self.native, "database"))
        self.files = {
            name: "database" if name in database else "dialogue"
            for name in sorted(guided.supported_files(self.native))
        }
        self.markers = (
            comment_text.markers(self.native["source"])
            if self.native["phase1_comments"]
            else frozenset()
        )
        self._found = None

    def _units(self):
        """Each sent text: its ID, kind, scene, speaker, source, translation
        or None, file and the paths it covers, by ID, in file order."""
        if self._found is not None:
            return self._found
        from util.source_text import holds_source, source_left

        found = {}
        with reading_game(self.native["source"]):
            for name, phase in self.files.items():
                document = decode_json(system.read_bytes(self.inputs.newest(name)))
                original = self.inputs.original_document(name)
                places = _Places(document, original)

                def read_original(value=original):
                    return value

                notes = file_lines.note_pointers(document, read_original)
                for line in file_lines.read(
                    name, document, phase, self.markers, read_original
                ):
                    named = line.kind in {"message", "scroll", "help"} and line.start
                    head = places.of(line.start) if named else None
                    speaker = None
                    part = 0
                    for (text, source), paths in zip(
                        line.sent(), line.places(), strict=True
                    ):
                        shown = source if source and source.strip() else text
                        name_box = named and paths[0][-2:] == ("parameters", 4)
                        if not holds_source(shown):
                            continue
                        if name_box:
                            identity = _pointer((*head, "parameters", 4))
                            speaker = shown
                        elif named:
                            identity = _pointer(head) + (f"~{part}" if part else "")
                            part += 1
                        else:
                            identity = _pointer(places.of(paths[0]))
                        noted = any(_pointer(path) in notes for path in paths)
                        translated = (
                            bool(source and source.strip())
                            and not noted
                            and bool(text.strip())
                            and not source_left(text, source)
                        )
                        kind = (
                            "ui"
                            if name_box
                            else _KINDS.get(line.kind, "ui")
                            if line.kind != "message" or speaker
                            else "unknown"
                        )
                        listed = places.of(line.start[:-1]) if line.start else None
                        found[f"{name}#{identity}"] = {
                            "id": f"{name}#{identity}",
                            "scene": name + ("#" + _pointer(listed) if listed else ""),
                            "group": name,
                            "kind": kind,
                            "speaker": speaker
                            if kind in {"dialogue", "unknown"}
                            else None,
                            "source": shown,
                            "translation": text if translated else None,
                            "file": name,
                            "paths": paths,
                            "line": line.kind,
                            "name_box": name_box,
                        }
        self._found = found
        return found

    def lines(self):
        return [
            {
                key: value[key]
                for key in (
                    "id",
                    "scene",
                    "group",
                    "kind",
                    "speaker",
                    "source",
                    "translation",
                )
            }
            for value in self._units().values()
        ]

    def problems(self, translations):
        from .unit_results import import_problems

        units = self._units()
        problems = {
            identity: f"{_KEPT[units[identity]['line']]} can't be imported into Guided steps yet."
            for identity in translations
            if units[identity]["line"] in _KEPT
        }
        checked = {
            identity: text
            for identity, text in translations.items()
            if identity not in problems
        }
        problems.update(
            import_problems(
                {
                    identity: {"source": units[identity]["source"], "constraints": {}}
                    for identity in checked
                },
                checked,
                self.pair["source"],
                self.pair["target"],
            )
        )
        return problems

    def save(self, translations, _name):
        """Writes *translations* into their files' working copies, each file
        whole, once no run or tool operation is working on the game."""
        from util import rpgmaker_blocks as blocks

        self.guided.idle()
        units = self._units()
        by_file = defaultdict(list)
        for identity, text in translations.items():
            by_file[units[identity]["file"]].append((units[identity], text))
        written = {}
        with reading_game(self.native["source"]):
            for name, rows in by_file.items():
                before = decode_json(system.read_bytes(self.inputs.newest(name)))
                staged = copy.deepcopy(before)
                for unit, text in rows:
                    paths = unit["paths"]
                    if unit["name_box"]:
                        holder = _parent(staged, paths[0])
                        value = holder[paths[0][-1]]
                        current = file_lines.speaker_name(value)
                        holder[paths[0][-1]] = (
                            value.replace(current, text, 1) if current else text
                        )
                    elif len(paths) > 1 or unit["line"] in _KINDS:
                        for path, row in zip(
                            paths, blocks.spread(text, len(paths)), strict=True
                        ):
                            _parent(staged, path)[path[-1]] = row
                    else:
                        _parent(staged, paths[0])[paths[0][-1]] = text
                written[name] = engine_json(
                    imported_document(before, staged, name, self.pair["target"])
                )
        prepared = [name for name in written if not self.inputs.saved("files", name)]
        if prepared:
            self.inputs.prepare(prepared)
        for name, raw in written.items():
            system.write_bytes(self.inputs.path("translated", name), raw)
        self._found = None


def _parent(document, path):
    for part in path[:-1]:
        document = document[part]
    return document
