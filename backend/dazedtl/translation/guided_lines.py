"""A Guided project's lines for its translation file (translation/exchange):
each text the engine sends as one (file_lines `sent`), in its file's newest
working copy, named by its file and its place in the game's original file.
Guided writes a translated message over fewer commands than the original
holds, so naming a line by its original place keeps its ID whether or not
the copy is translated, and two people's copies of one game version share
their IDs while their speaker settings match.

An ID is `<file>#<JSON pointer>` into the original file: a value's own, and
for an event text block its first command's, such as a message's window,
with `/parameters/4` after it for the message's name box and `~<n>` for its
later parts. A message's or scrolling text's parts are the texts the engine
sends of the game's own rows, read by the project's speaker settings
(rpgmaker_blocks `sent_texts`): a row opening with a code such as \\SE[1]
starts one, and a nameplate on a row of its own is one and names the speaker
of the speech after it. A command the original doesn't hold at a place, such
as one a game update added, keeps its pointer into the copy.

Importing writes into each file's working copy, as a run's output does
(guided_inputs), and records each changed value's source as Guided does,
each text's on its first row, so Translate's Apply puts the translations in
the game as one checkpoint, fitted to the Line widths. Choice help and note
labels are left out of an import: their rows and sources follow rules of
their own.
"""

import copy
from collections import defaultdict

from dazedtl import system
from dazedtl.compatibility.text import engine_json, imported_document
from dazedtl.languages import reading_game

from . import comment_text, file_lines
from .files import decode_json
from .results import game_line

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

    def __init__(self, guided, project_id, pair, quotes):
        self.guided = guided
        _project, self.native = guided.record(project_id)
        self.pair, self.quotes = pair, quotes
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
        self.variables = self.inputs.drawn_variables(self.files)
        from util.rpgmaker_blocks import Reading

        self.reading = Reading.of(self.native["engine_options"])
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
                raw = system.read_bytes(self.inputs.newest(name))
                document = decode_json(raw)
                # A copy translation never touched keeps the original's
                # places, so only a translated one reads the original's.
                original = (
                    self.inputs.original_document(name)
                    if b'"_original"' in raw
                    else None
                )
                places = _Places(document, original)

                def read_original(value=original):
                    return value

                notes = file_lines.note_pointers(document, read_original)
                for line in file_lines.read(
                    name,
                    document,
                    phase,
                    self.markers,
                    read_original,
                    self.variables,
                    self.reading,
                ):
                    # A block names its texts by the command it starts at.
                    head = (
                        places.of(line.start)
                        if line.kind in {"message", "scroll", "help"} and line.start
                        else None
                    )
                    named = head is not None
                    block = (name, line.start) if line.kind in _KINDS else None
                    speaker = None
                    part = 0
                    for index, ((text, source), paths) in enumerate(
                        zip(line.sent(), line.places(), strict=True)
                    ):
                        shown = file_lines.shown(text, source)
                        name_box = named and file_lines.name_box(paths)
                        nameplate = bool(line.names and line.names[index])
                        said = None
                        if nameplate:
                            speaker = line.names[index]
                        elif not name_box and (not line.read or line.read[index]):
                            # A name box's or nameplate's speaker says the
                            # next text the engine reads alone, as it sends
                            # them; rows it skips leave it to the one after.
                            said, speaker = speaker, None
                        if not holds_source(shown):
                            continue
                        if head is not None and name_box:
                            identity = _pointer((*head, "parameters", 4))
                            speaker = shown
                        elif head is not None:
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
                            if name_box or nameplate
                            else "dialogue"
                            if said
                            else "unknown"
                            if line.kind == "message"
                            else _KINDS.get(line.kind, "ui")
                        )
                        listed = places.of(line.start[:-1]) if line.start else None
                        found[f"{name}#{identity}"] = {
                            "id": f"{name}#{identity}",
                            "scene": name + ("#" + _pointer(listed) if listed else ""),
                            "group": name,
                            "kind": kind,
                            "speaker": said
                            if kind in {"dialogue", "unknown"}
                            else None,
                            "source": shown,
                            "translation": text if translated else None,
                            "file": name,
                            "paths": paths,
                            "line": line.kind,
                            "name_box": name_box,
                            # A message's or scrolling text's text keeps its
                            # source on its first row, as a run writes it.
                            "start": (paths[0], shown)
                            if block is not None and not name_box
                            else None,
                            "block": block,
                            "kept": source is not None,
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

    def idle(self):
        """Refuses while a run or tool operation is working on the game."""
        self.guided.idle()

    def save(self, translations, _name):
        """Writes *translations* into their files' working copies, each file
        whole, as Guided writes a reply's lines (results.game_line)."""
        from util import rpgmaker_blocks as blocks

        units = self._units()
        kept = defaultdict(list)
        for unit in units.values():
            if unit["kept"] and unit["block"] is not None:
                kept[unit["block"]].append(unit)
        by_file = defaultdict(list)
        for identity, text in translations.items():
            unit = units[identity]
            by_file[unit["file"]].append(
                (
                    unit,
                    game_line(unit["source"], text, self.pair["target"], self.quotes),
                )
            )
        written = {}
        with reading_game(self.native["source"]):
            for name, rows in by_file.items():
                before = decode_json(system.read_bytes(self.inputs.newest(name)))
                # Each text written of a message or scrolling text keeps its
                # source on its first row, as a run writes the texts it
                # sends, and so does every text a writer kept one source over
                # with it, which an export reads apart (rpgmaker_blocks
                # `sent_texts`): Apply fits each on its own.
                touched = {unit["block"] for unit, _text in rows}
                marks = [unit for unit, _text in rows] + [
                    unit for block in touched for unit in kept.get(block, ())
                ]
                for unit in marks:
                    if unit["start"] is not None:
                        path, source = unit["start"]
                        command = _parent(before, path[:-1])
                        command["_original"] = source
                        # The rows it lays the text over, the game's own after.
                        command[blocks.ROWS] = len(unit["paths"])
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
