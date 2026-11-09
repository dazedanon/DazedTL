"""The text blocks players read in an RPG Maker MV/MZ event command list.

Every part of DazedTL that reads or writes event text works out its blocks
here: translation, fitting, Text QA's inventory, verifier and never-translated
report, Assistant-led's writer and the playtest. A block is what one window
shows at once:

- a message: Show Text (101) and its text rows (401)
- scrolling text: Show Scrolling Text (105) and its rows (405)
- a choice list (102)
- a choice's help: a comment (108) right after a choice branch (402), whose
  rows (408) MPP_ChoiceEX shows in the message window while the choice is
  open; the comment's first line is its marker, such as 選択肢ヘルプ
- any other comment (108 and its 408 rows), which players read only when a
  plugin shows the comments under its marker

Translation writes a block's text in parts. A part's anchor is the command
that keeps the Japanese it was translated from, in ``_original``, and the
part owns the rows its text was written over. Rows a block holds outside its
translated parts are the game's own, translated or not. A writer that lays a
part's text over rows it chose records how many beside ``_original``, under
``_rows`` (:func:`record_rows`), and every reader takes a part's rows from
that record; text written before its writer recorded them is read by its
shape (see :func:`owned`). Assistant-led keeps a comment's Japanese, marker
included, on the comment (108) itself.

The engine sends a message's or scrolling text's rows in texts (see
:func:`texts`), and translation writes each text over its rows, keeping its
source on its first, and so does every writer that lays one source over
several texts (:func:`keep_texts`); data an earlier writer laid so keeps its
shape until written again. Every copy of a game names its lines by the texts
of the game's own rows (:func:`sent_texts`). A row after a message's translation
holding Japanese its source doesn't is the game's own, left untranslated,
wherever it stands (:func:`uncovered`), and so is a row past those its source
has lines for, or past those its writer recorded: the translation's part
ends before it (:func:`owned`), for every reader.

Commands the engine empties when it writes a message's translation over its
rows (code -1, no parameters) are left out until it writes the list back.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Sequence

from util import target_text
from util.speakers import (
    MessageSpeakers,
    display_name,
    message_speakers,
    plausible_speaker,
    standalone_speaker,
    to_prefixed,
)
from util.source_text import holds_source, source_left

# The number of rows a part's text was written over, kept on its anchor beside
# `_original` (record_rows). Notes are not game data: whatever copies or
# compares commands treats both as the translation's. A game may follow a
# translation's rows with its own, such as "(1/3)", a blank spacer, or a row
# after a name a run translated alone holding no Japanese, such as ……, and
# no reading of their text tells them apart, so a writer that lays a part's
# text over rows it chose records them: a run (from event-left-rows-v3), a
# translation file import, Assistant-led's writer over rows never translated
# and comment translation. One that writes a translation again over the rows
# it holds, as fitting, Text QA's corrections, Assistant-led's writer and a
# refusal note's restore do, keeps the record as it is: rows it read by their
# shape are no fact it can record. Game updates carry the count with the
# translation.
ROWS = "_rows"
# The data files whose events hold command lists: maps, common events and
# troops.
EVENT_FILE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")
NOTES = frozenset({"_original", ROWS})

MESSAGE = "message"
SCROLL = "scroll"
CHOICE = "choice"
HELP = "help"
COMMENT = "comment"

# A block's first command, and the code of its rows.
HEAD_ROWS = {101: 401, 105: 405, 108: 408}
_HEADS = {head: (kind, HEAD_ROWS[head]) for head, kind in ((101, MESSAGE), (105, SCROLL), (108, COMMENT))}
# A part's anchor's code, and the code of the rows it owns.
ROW_CODES = {401: 401, 405: 405, 408: 408, 108: 408}

# Codes translation repeats at the start of every row of a message: centring,
# instant lines and an indent.
PER_LINE = re.compile(r"^(?:\\+a[clr](?![A-Za-z])|\\+>|\\+px\[\d+\])+ ?", re.IGNORECASE)


def is_command_list(value: Any) -> bool:
    """Whether a data file's value is an event command list."""
    return isinstance(value, list) and any(
        isinstance(item, dict) and "code" in item for item in value
    )


def command_lists(document: Any, path: tuple = ()) -> Iterator[tuple[tuple, list]]:
    """Every event command list in a data file, by the path to it."""
    if isinstance(document, list):
        if is_command_list(document):
            yield path, document
            return
        for index, child in enumerate(document):
            yield from command_lists(child, path + (index,))
    elif isinstance(document, dict):
        for key, child in document.items():
            if key != "_original":
                yield from command_lists(child, path + (key,))


def code(command: Any) -> int | None:
    """A command's code, or None for one it cannot read, such as a malformed
    command whose code is no number, which no block holds."""
    value = command.get("code") if isinstance(command, dict) else None
    return value if type(value) is int else None


def emptied(command: Any) -> bool:
    """A command the engine emptied when it wrote a translation over its
    rows, removed when it writes the list back."""
    return code(command) == -1 and not command.get("parameters")


def text(command: Any) -> str:
    """A text row's text, or "" for one holding none."""
    parameters = command.get("parameters") if isinstance(command, dict) else None
    if isinstance(parameters, list) and parameters and isinstance(parameters[0], str):
        return parameters[0]
    return ""


def _text_row(command: Any, row_code: int) -> bool:
    parameters = command.get("parameters") if isinstance(command, dict) else None
    return (
        code(command) == row_code
        and isinstance(parameters, list)
        and bool(parameters)
        and isinstance(parameters[0], str)
    )


def has_face(command: Any) -> bool:
    """Whether a Show Text (101) shows a face graphic."""
    parameters = command.get("parameters") if isinstance(command, dict) else None
    return (
        isinstance(parameters, list)
        and len(parameters) >= 4
        and isinstance(parameters[0], str)
        and bool(parameters[0].strip())
    )


@dataclass(frozen=True)
class Part:
    """Text written as one over some of a block's rows: a translation, from
    its anchor, or rows never translated (``anchor`` None). Assistant-led's
    comment translations are anchored on the comment (108) before ``rows``."""

    anchor: int | None
    rows: tuple[int, ...]

    @property
    def translated(self) -> bool:
        return self.anchor is not None

    @property
    def on_head(self) -> bool:
        """Whether the anchor is the block's comment (108), which keeps the
        Japanese of its marker and rows together."""
        return self.anchor is not None and self.anchor not in self.rows

    @property
    def commands(self) -> tuple[int, ...]:
        """Every command holding the part's text, the anchor first: the text
        its `_original` was translated from lives in these."""
        return ((self.anchor,) if self.on_head else ()) + self.rows


@dataclass(frozen=True)
class Block:
    """One window's text: its kind, its first command (``head``; the choice
    itself for a choice list), its text rows, its parts in order, whether it
    shows beside a face graphic, and a comment's marker."""

    kind: str
    head: int | None
    rows: tuple[int, ...]
    parts: tuple[Part, ...]
    face: bool = False
    marker: str = ""

    def shown(self, markers: frozenset[str] | set[str]) -> bool:
        """Whether players read it: a comment only under a marker a plugin
        shows."""
        return self.kind not in (HELP, COMMENT) or self.marker in markers

    @property
    def start(self) -> int:
        """The index of its first command."""
        return self.head if self.head is not None else self.rows[0]

    @property
    def end(self) -> int:
        """The index after its last command."""
        return (self.rows[-1] if self.rows else self.start) + 1

    def part(self, index: int) -> Part | None:
        """The part holding the command at *index*, its anchor or a row."""
        return next((part for part in self.parts if index in part.commands), None)


def marker(command: Any) -> str:
    """A comment's (108) first line as the game wrote it."""
    original = command.get("_original") if isinstance(command, dict) else None
    if isinstance(original, str) and original.strip():
        return original.split("\n", 1)[0].strip()
    return text(command).strip()


class Choice(NamedTuple):
    """One choice of a choice list (102) as the engine sends it: its *label*,
    with the plugin condition clauses around it, such as MPP_ChoiceEX's
    ``if(s[1])`` and ``en(v[3]<=50)``, which the engine keeps out of the
    request and puts back around the label's translation as the game has
    them."""

    prefix: str
    label: str
    suffix: str

    def written(self, label: str) -> str:
        """*label* with this choice's clauses around it."""
        return self.prefix + label + self.suffix

    def restored(self, value: str) -> str:
        """*value*, a translation of the choice this splits, with the clauses
        of each side it lacks put back, which a translation file import left
        out before it kept them. A side is lacking when *value* has no clause
        there and holds none of its clauses anywhere, so a translation keeping
        them, or holding a condition of its own there, stays."""
        held = set(conditions(value))
        found = split_choice(value)

        def lacking(clauses: str, there: str) -> bool:
            return bool(clauses) and not there and not held & set(conditions(clauses))

        return (
            (self.prefix if lacking(self.prefix, found.prefix) else "")
            + value
            + (self.suffix if lacking(self.suffix, found.suffix) else "")
        )


_CONDITION = re.compile(r"(?:if|en)\(")
# A condition as MPP_ChoiceEX reads one: anywhere in a choice's text.
_READ_CONDITION = re.compile(r"(?:if|en)\(.+?\)")


def conditions(value: str) -> list[str]:
    """The condition clauses a choice plugin reads anywhere in a choice's
    *value*, as MPP_ChoiceEX does, a word such as "Open(door)" included, in
    order."""
    return _READ_CONDITION.findall(value)


def split_choice(value: str) -> Choice:
    """A choice's *value* split into its label and condition clauses: a
    leading lowercase ``if(...)``/``en(...)`` clause, and trailing ones,
    attached to the label or after whitespace, with nested calls such as
    ``if($gameSwitches.value(1))``. An unbalanced clause, or trailing text
    mixed with clauses, stays in the label, so no text players read is taken
    out of it."""
    end = _condition_end(value, 0)
    prefix, label = (value[:end], value[end:]) if end is not None else ("", value)
    for found in _CONDITION.finditer(label):
        start = found.start()
        while start > 0 and label[start - 1].isspace():
            start -= 1
        cursor = found.start()
        while (end := _condition_end(label, cursor)) is not None:
            cursor = end
            while cursor < len(label) and label[cursor].isspace():
                cursor += 1
            if cursor == len(label):
                return Choice(prefix, label[:start], label[start:])
    return Choice(prefix, label, "")


def restore_conditions(document: Any, places: Iterable[tuple] | None = None) -> list[tuple]:
    """Put back, in place, the condition clauses each choice of *document*
    lacks of those its source (`_original`) holds (`Choice.restored`), only
    at *places* when given, and return the places it changed, each a choice
    by its command list's path, its command and its index; a choice left in
    its source, or whose clauses are as the source has them, stays as it
    is."""
    only = None if places is None else set(places)
    changed = []
    for path, commands in command_lists(document):
        for at, command in enumerate(commands):
            if code(command) != 102:
                continue
            parameters, sources = command.get("parameters"), command.get("_original")
            if not isinstance(parameters, list) or not isinstance(sources, list):
                continue
            choices = parameters[0] if parameters else None
            if not isinstance(choices, list):
                continue
            for index, (value, source) in enumerate(zip(choices, sources)):
                place = (path, at, index)
                if only is not None and place not in only:
                    continue
                if not isinstance(value, str) or not isinstance(source, str):
                    continue
                restored = split_choice(source).restored(value)
                if restored != value:
                    choices[index] = restored
                    changed.append(place)
    return changed


# Bytes a data file holds a condition clause in, which reading it for one
# needs (see lacking_conditions).
_RAW_CONDITION = re.compile(rb"(?:if|en)\(")


def lacking_conditions(raw: bytes) -> frozenset[tuple]:
    """The places of the choices in a data file's *raw* bytes that lack
    condition clauses their sources hold, which `restore_conditions` puts
    back; none for a file that does not decode."""
    if not _RAW_CONDITION.search(raw):
        return frozenset()
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return frozenset()
    return frozenset(restore_conditions(document))


def _condition_end(value: str, start: int) -> int | None:
    """The end of a balanced ``if(...)``/``en(...)`` clause at *start*."""
    if not value.startswith(("if(", "en("), start):
        return None
    depth = 0
    for index in range(start + 2, len(value)):
        if value[index] == "(":
            depth += 1
        elif value[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def source(commands: list, part: Part) -> str | None:
    """The Japanese a translated part's rows were translated from: a comment
    anchored on its 108 keeps its marker as the first line."""
    if part.anchor is None:
        return None
    original = commands[part.anchor].get("_original")
    if not isinstance(original, str):
        return None
    if part.on_head:
        return original.split("\n", 1)[1] if "\n" in original else ""
    return original


def kept(commands: list, part: Part) -> tuple[int, ...]:
    """The rows of a translated part that hold one of the rows of the
    Japanese it was translated from as the game wrote it: the game's own,
    though the part holds them, such as a page number "(1/3)" Assistant-led
    left as it was when it wrote a comment's rows one by one."""
    original = source(commands, part)
    if original is None:
        return ()
    theirs = {line for line in original.split("\n") if line.strip()}
    return tuple(at for at in part.rows if text(commands[at]) in theirs)


def recorded(command: Any) -> int | None:
    """The rows a part's anchor records it owns, or None."""
    rows = command.get(ROWS) if isinstance(command, dict) else None
    return rows if isinstance(rows, int) and not isinstance(rows, bool) and rows > 0 else None


def record_rows(command: dict, rows: int) -> None:
    """Record on *command*, the first row a writer laid a part's text over,
    the *rows* it laid it over (ROWS), past emptied commands, beside the
    source it keeps: :func:`owned` reads a part's rows from it. A command
    keeping no source anchors no part and records none."""
    if "_original" in command:
        command[ROWS] = rows
    else:
        command.pop(ROWS, None)


def following(commands: list, start: int, row_code: int):
    """The indexes of the rows (*row_code*) after *start*, past emptied
    commands: a block's text rows after its first command, or a script's
    lines (655) after its first (355)."""
    at = start + 1
    while at < len(commands):
        command = commands[at]
        if emptied(command):
            at += 1
            continue
        if not _text_row(command, row_code):
            return
        yield at
        at += 1


def run(commands: list, start: int, row_code: int) -> tuple[int, ...]:
    """The text rows after *start* up to the next translation, such as the
    rows Assistant-led's write of a comment or a script owns."""
    rows = []
    for at in following(commands, start, row_code):
        if "_original" in commands[at]:
            break
        rows.append(at)
    return tuple(rows)


def uncovered(value: str, source: str) -> bool:
    """Whether a message's or scrolling text's row reading *value*, after
    the first of a translation of *source*, holds text that translation
    never covered: Japanese left in it, read against *source* as the engine
    reads it (util/source_text `source_left`), that no word of *source*
    holds. Such a row is the game's own, left untranslated, such as the
    speech after a nameplate a run translated alone, under other speaker
    settings or with the speech's request refused. A writer laying the
    translation over its rows leaves none, though a row may keep a word of
    the source, such as a name; a row of the game's own whose Japanese the
    source holds reads as the translation's too."""
    theirs = source_left(source)
    return any(
        not any(run in word for word in theirs) for run in source_left(value, source)
    )


def _translation(command: Any) -> str | None:
    """The source a message's or scrolling text's row keeps of a translation
    written from it, as the engine reads one (rpgmakermvmz
    `_scalar_original`): a string holding text, or None."""
    source = command.get("_original") if isinstance(command, dict) else None
    return source if isinstance(source, str) and source.strip() else None


def owned(
    commands: list,
    anchor: int,
    *,
    original: list | None = None,
    help_block: bool | None = None,
    by_lines: bool = True,
) -> tuple[int, ...]:
    """The text rows the translation anchored at *anchor* owns, in order; a
    comment (108) anchor owns the rows after it.

    A message's or scrolling text's translation owns none from a row it
    never covered (:func:`uncovered`), the game's own, left untranslated,
    whatever its anchor records, such as a row a game update's release
    changed under the record, which Git merges by line. Otherwise the rows
    its anchor records its writer laid it over (``_rows``, see
    :func:`record_rows`). Text written before its writer recorded them is
    read by its shape:
    - a message owns its rows up to the next translation, but no more than
      its source has lines (*by_lines*): a run writes a message's text on
      its first row, and a writer laying it over the rows one by one, as
      Assistant-led's does, keeps a source line for each, so the rows after
      them are the game's own, such as a punctuation-only row after a name a
      run translated alone, or one in English. Runs frozen before
      event-left-rows-v2 read it without (rpgmakermvmz LEFT_ROWS)
    - scrolling text owns its rows up to the next translation: a run lays
      its text over every row it joined, blank ones its source leaves out
      included, so their count is not its source's; rows never translated
      run up to the next translation too
    - a comment anchored on its 108, as Assistant-led writes them, owns its
      rows up to the next translation
    - choice help translated before translation recorded its rows owns the
      rows after it the game's original file did not have there (*original*,
      the original's command list), or without one the rows up to the next
      translation that hold no Japanese and are not blank: translation never
      wrote a blank row or left Japanese in one it added
    - other comment rows own their rows up to the next translation."""
    command = commands[anchor]
    row_code = ROW_CODES.get(code(command))
    if row_code is None:
        return ()
    head = code(command) == 108
    rows = [] if head else [anchor]
    count = recorded(command)
    source = _translation(command) if row_code != 408 else None
    if count is None and source is not None and row_code == 401 and by_lines:
        count = source.count("\n") + 1
    for at in following(commands, anchor, row_code):
        if (
            "_original" in commands[at]
            or (count is not None and len(rows) >= count)
            or (source is not None and uncovered(text(commands[at]), source))
        ):
            break
        rows.append(at)
    if count is not None or head or row_code != 408:
        return tuple(rows)
    if help_block is None:
        help_block = help_branch(commands, anchor) is not None
    if not help_block:
        return tuple(rows)
    if original is not None:
        aligned = _aligned(commands, anchor, original)
        if aligned is not None:
            return aligned
    kept = [anchor]
    for at in rows[1:]:
        value = text(commands[at])
        if not value.strip() or holds_source(value):
            break
        kept.append(at)
    return tuple(kept)


def _comment_ordinal(commands: list, head: int) -> int:
    return sum(1 for command in commands[:head] if code(command) == 108)


def _aligned(commands: list, anchor: int, original: list) -> tuple[int, ...] | None:
    """The rows a choice help translation at *anchor* owns, read against the
    original game file's command list. Walking the help's rows beside the
    original's: a translation uses up the rows its Japanese came from, a row
    the same as the original's next is the game's own, and any other row is
    one the translation added. None when the two do not line up."""
    head = anchor - 1
    while head >= 0 and (code(commands[head]) == 408 or emptied(commands[head])):
        head -= 1
    if head < 0 or code(commands[head]) != 108:
        return None
    ordinal = _comment_ordinal(commands, head)
    heads = [at for at, command in enumerate(original) if code(command) == 108]
    if ordinal >= len(heads):
        return None
    theirs = [text(original[at]) for at in following(original, heads[ordinal], 408)]
    position = 0
    owner: list[int] | None = None
    owners: dict[int, list[int]] = {}
    for at in following(commands, head, 408):
        command = commands[at]
        if "_original" in command:
            wanted = _lines(command["_original"])
            used: list[str] = []
            while position < len(theirs) and _lines("\n".join(used)) != wanted:
                used.append(theirs[position])
                position += 1
            if not wanted or _lines("\n".join(used)) != wanted:
                return None
            owner = owners[at] = [at]
        elif position < len(theirs) and text(command) == theirs[position]:
            position += 1
            owner = None
        elif owner is not None:
            owner.append(at)
        else:
            return None
    return tuple(owners[anchor]) if anchor in owners else None


def _lines(value: Any) -> list[str]:
    """A text's rows that hold something."""
    return [line for line in value.split("\n") if line.strip()] if isinstance(value, str) else []


def help_branch(commands: list, index: int) -> int | None:
    """The choice branch (402) whose help the comment holding the command at
    *index* (its 108 or a 408 row) is, or None: MPP_ChoiceEX reads a
    choice's help from the comment right after its branch, under a marker,
    which a comment without a first line never has."""
    at = index
    if code(commands[at]) != 108:
        at -= 1
        while at >= 0 and (code(commands[at]) == 408 or emptied(commands[at])):
            at -= 1
    if (
        at < 1
        or code(commands[at]) != 108
        or code(commands[at - 1]) != 402
        or not marker(commands[at])
    ):
        return None
    return at - 1


def show_text(commands: list, index: int) -> int | None:
    """The Show Text (101) of the message holding the command at *index*,
    its 101 or a row (401), or of the message a choice (102) at *index*
    shows with; None for rows without their Show Text."""
    if code(commands[index]) == 101:
        return index
    if code(commands[index]) not in (401, 102):
        return None
    at = index - 1
    while at >= 0 and (code(commands[at]) == 401 or emptied(commands[at])):
        at -= 1
    return at if at >= 0 and code(commands[at]) == 101 else None


def help_face(commands: list, index: int) -> bool:
    """Whether the choice help holding the command at *index* shows beside a
    face. MPP_ChoiceEX draws the help in the message window, which keeps the
    face of the Show Text (101) the choice follows; a choice right after
    another's end (404) joins that one and shows with its message."""
    at = help_branch(commands, index)
    if at is None:
        return False
    indent = commands[at].get("indent")
    while True:
        while at >= 0 and not (code(commands[at]) == 102 and commands[at].get("indent") == indent):
            at -= 1
        choice = at
        at -= 1
        while at >= 0 and emptied(commands[at]):
            at -= 1
        if at < 0:
            return False
        if code(commands[at]) != 404 or commands[at].get("indent") != indent:
            break
    head = show_text(commands, choice)
    return head is not None and has_face(commands[head])


def _parts(
    commands: list, rows: tuple[int, ...], head: int | None, original: list | None, help_block: bool
) -> tuple[Part, ...]:
    parts: list[Part] = []
    taken: set[int] = set()
    if head is not None and code(commands[head]) == 108 and "_original" in commands[head]:
        mine = owned(commands, head, original=original, help_block=help_block)
        parts.append(Part(head, mine))
        taken.update(mine)
    loose: list[int] = []
    for at in rows:
        if at in taken:
            continue
        if "_original" in commands[at]:
            if loose:
                parts.append(Part(None, tuple(loose)))
                loose = []
            mine = owned(commands, at, original=original, help_block=help_block)
            parts.append(Part(at, mine))
            taken.update(mine)
        else:
            loose.append(at)
    if loose:
        parts.append(Part(None, tuple(loose)))
    return tuple(parts)


def _block(commands: list, index: int, face: bool, original: list | None) -> Block | None:
    """The block starting at *index*, or None; *face* is whether rows
    without their Show Text show beside a face."""
    command = commands[index]
    command_code = code(command)
    parameters = command.get("parameters") if isinstance(command, dict) else None
    if command_code == 102:
        if not (isinstance(parameters, list) and parameters and isinstance(parameters[0], list)):
            return None
        part = Part(index if "_original" in command else None, (index,))
        return Block(CHOICE, index, (index,), (part,), face)
    if command_code in _HEADS:
        kind, row_code = _HEADS[command_code]
        head: int | None = index
        rows = tuple(following(commands, index, row_code))
    elif command_code in (401, 405) and _text_row(command, command_code):
        # Rows without their first command, as hand-made lists have.
        kind, row_code, head = (MESSAGE if command_code == 401 else SCROLL), command_code, None
        rows = (index, *following(commands, index, command_code))
    else:
        return None
    if command_code == 101:
        face = has_face(command)
    name, help_block = "", False
    if kind == COMMENT:
        name = marker(command)
        help_block = help_branch(commands, index) is not None
        kind = HELP if help_block else COMMENT
    shown_face = face if kind == MESSAGE else help_face(commands, index) if help_block else False
    return Block(
        kind, head, rows, _parts(commands, rows, head, original, help_block), shown_face, name
    )


def blocks(commands: list, *, original: list | None = None) -> Iterator[Block]:
    """Each block in an event command list, in order. *original* is the same
    list in the game's original file, which reads choice help translated
    before translation recorded its rows (see :func:`owned`)."""
    index = 0
    face = False
    while index < len(commands):
        command_code = code(commands[index])
        if command_code == 101:
            face = has_face(commands[index])
        block = _block(commands, index, face, original)
        if block is None:
            # A face shows beside the rows of its own message only.
            if command_code not in (0, -1, 401, 405):
                face = False
            index += 1
            continue
        yield block
        index = block.end


def block_at(commands: list, index: int, *, original: list | None = None) -> Block | None:
    """The block holding the command at *index*, or None."""
    if not 0 <= index < len(commands):
        return None
    row_code = code(commands[index])
    start = index
    if row_code in (401, 405, 408):
        while start > 0 and (code(commands[start - 1]) == row_code or emptied(commands[start - 1])):
            start -= 1
        head_code = next(head for head, rows in HEAD_ROWS.items() if rows == row_code)
        if start > 0 and code(commands[start - 1]) == head_code:
            start -= 1
    # Whether rows without their Show Text follow one with a face.
    face, at = False, start - 1
    while at >= 0 and code(commands[at]) in (0, -1, 401, 405):
        at -= 1
    if at >= 0 and code(commands[at]) == 101:
        face = has_face(commands[at])
    while True:
        block = _block(commands, start, face, original)
        if block is None:
            return None
        if index == block.head or index in block.rows:
            return block
        if not block.rows or block.rows[-1] < index:
            # A row that is no text row starts the rest of the rows over.
            start = (block.rows[-1] if block.rows else start) + 1
            while start < index and not _text_row(commands[start], row_code):
                start += 1
            if start > index:
                return None
            continue
        return None


def part_rows(commands: list, anchor: int, *, original: list | None = None) -> tuple[int, ...]:
    """Every command holding the text of the translation anchored at
    *anchor*, the anchor first (see :func:`owned`)."""
    rows = owned(commands, anchor, original=original)
    return ((anchor,) if code(commands[anchor]) == 108 else ()) + rows


# ----------------------------------------------- the texts the engine sends

# A row that opens with a code taking an argument, such as \SE[1] or \F[tt07],
# other than the colour, icon, name, key and variable codes (\C \I \N \K \V),
# which are part of the text.
_OPENING_CODE = re.compile(r"^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])")
# The commands a message's or scrolling text's text joins over: its rows and
# the ones translation emptied.
TEXT_CODES = (401, 405, -1)


def opens_text(row: Any) -> bool:
    """Whether a message or scrolling text row starts a text of its own: one
    opening with a code such as \\SE[1] (see _OPENING_CODE)."""
    return _OPENING_CODE.match(str(row)) is not None


def _opening(row: str) -> str:
    """The code a row opens a text of its own with (:func:`opens_text`), or
    "" for none."""
    found = _OPENING_CODE.match(row)
    return found.group(1).strip() if found else ""


def joins(commands: list, at: int, codes: tuple[int, ...] = TEXT_CODES) -> bool:
    """Whether the command after *at* joins the text of the one at *at* in
    what the engine sends: a command of *codes*, both holding parameters, the
    later opening no text of its own (:func:`opens_text`)."""
    if at + 1 >= len(commands):
        return False
    current, following = commands[at], commands[at + 1]
    return (
        following.get("code") in codes
        and bool(current.get("parameters"))
        and bool(following.get("parameters"))
        and not opens_text(following["parameters"][0])
    )


def text_end(
    commands: list,
    start: int,
    codes: tuple[int, ...] = TEXT_CODES,
    stop: Callable[[int], bool] | None = None,
    *,
    left: bool = False,
    by_lines: bool = True,
    reading: Reading | None = None,
) -> int:
    """The last command whose text joins the one at *start* (:func:`joins`),
    before any command *stop* names by its index and, with *left*, past no
    row of the translation whose source *start* keeps (:func:`owned`, read
    *by_lines*), so the game's own rows after it, such as rows left
    untranslated, are texts of their own. Given the *reading* too, every row
    that translation's text was written over joins it, as :func:`sent_texts`
    reads them (:func:`_written_over`), one opening with a code included: a
    fit may move a code to a row's start."""
    rows: frozenset[int] | None = None
    over: frozenset[int] = frozenset()
    kept = _translation(commands[start]) if left else None
    if kept is not None:
        mine = owned(commands, start, by_lines=by_lines)
        rows = frozenset(mine)
        if reading is not None:
            written = _written_over(commands, Part(start, mine), kept.split("\n"), reading)
            over = frozenset(mine[:written])
    end = start
    while (
        (joins(commands, end, codes) or end + 1 in over)
        and not (stop is not None and stop(end + 1))
        and not (rows is not None and end + 1 not in rows)
    ):
        end += 1
    return end


class NextText(NamedTuple):
    """The text the engine sends from a row (:func:`next_text`)."""

    # The speakers the row names (util/speakers `message_speakers`), or None.
    speakers: MessageSpeakers | None
    # The row of a nameplate the row is, sent apart from the text after it.
    name: int | None
    # The rows sent as one text, after the nameplate if any.
    rows: tuple[int, ...]


def next_text(
    commands: list,
    start: int,
    line: str,
    speakers: Callable[[str, str | None], MessageSpeakers | None],
    stop: Callable[[int], bool] | None = None,
    *,
    left: bool = False,
    by_lines: bool = True,
    reading: Reading | None = None,
) -> NextText:
    """The text the MV/MZ engine sends from the message or scrolling text row
    at *start*, whose text it reads as *line*: the speakers *speakers* reads
    there, given the next command's text when that command is another of the
    text's rows (TEXT_CODES) and None otherwise; a nameplate on that row,
    which goes alone, and the rows after it, past emptied commands; and the
    rows joined to the first (:func:`text_end`), up to any *stop* names and,
    with *left*, the game's own after the first's translation (read
    *by_lines*), and given the *reading*, every row it was written over."""
    following = None
    if start + 1 < len(commands) and commands[start + 1].get("code") in TEXT_CODES:
        parameters = commands[start + 1].get("parameters") or []
        following = parameters[0] if parameters else ""
    found = speakers(line, following)
    name, first = None, start
    if found is not None and found.own_line:
        name, first = start, start + 1
        while commands[first]["code"] == -1:
            first += 1
    end = text_end(commands, first, stop=stop, left=left, by_lines=by_lines, reading=reading)
    return NextText(found, name, tuple(range(first, end + 1)))


@dataclass(frozen=True)
class Reading:
    """How the engine reads a game's messages: a short row before speech as
    its speaker (*first_line*, FIRSTLINESPEAKERS), a name in front of the
    speech (*inline*, INLINE401SPEAKERS), and whether it skips text holding
    no source text (*skip_translated*, IGNORETLTEXT), with a run policy's
    reading of nameplates (util/speakers `message_speakers`): by default the
    newest, which a run's frozen CODE_NAMEPLATES and SPEAKER_CONTEXT set
    (*code_nameplates*, and *standalone* deciding which [Name] rows name a
    speaker, or None for every one). *named* reads a short row before speech
    as its speaker only when it reads as a name (util/speakers
    `plausible_speaker`)."""

    first_line: bool = False
    inline: bool = False
    skip_translated: bool = True
    named: bool = False
    code_nameplates: bool = True
    standalone: Callable[[str], bool] | None = standalone_speaker

    @classmethod
    def of(cls, options: dict | None) -> Reading:
        """The reading of a project's MV/MZ engine *options*, each left out
        at the engine's default."""
        options = options or {}
        return cls(
            bool(options.get("FIRSTLINESPEAKERS", False)),
            bool(options.get("INLINE401SPEAKERS", False)),
            bool(options.get("IGNORETLTEXT", True)),
        )

    def speakers(self, line: str, following: str | None) -> MessageSpeakers | None:
        """The speakers a row names (see :func:`next_text`)."""

        def read(first_line: bool) -> MessageSpeakers | None:
            return message_speakers(
                line,
                following,
                first_line=first_line,
                inline=self.inline,
                code_nameplates=self.code_nameplates,
                standalone=self.standalone,
            )

        if not self.named:
            return read(self.first_line)
        # A short row before speech is read last, when no other form is.
        found = read(False)
        if found is None and self.first_line:
            found = read(True)
            if found is not None and not plausible_speaker(found.names[0]):
                return None
        return found

    def sends(self, value: str) -> bool:
        """Whether the engine sends rows never translated that read *value*."""
        return bool(value.strip()) and (not self.skip_translated or holds_source(value))


# The reading of text no engine settings read, such as Assistant-led's and
# Text QA's: a speaker in any form the engine reads, a short row before speech
# that reads as a name included, is a text of its own, as the game's rows lay
# it out.
EVERY_SPEAKER = Reading(first_line=True, inline=True, named=True)


class Text(NamedTuple):
    """A text the engine sends of some rows (:func:`texts`): their indexes;
    for a nameplate on a row of its own, sent apart from the speech after
    it, the speaker it names, "" for any other text; whether the engine
    reads it at all, False for rows it skips as holding nothing it sends,
    which leave a speaker named before them to the text after them; and the
    speakers the engine reads on its first row (util/speakers
    `message_speakers`), or None: a nameplate's (`own_line`), or a name
    sharing that row with the text, never for the speech after a
    nameplate."""

    rows: tuple[int, ...]
    name: str = ""
    sent: bool = True
    speakers: MessageSpeakers | None = None

    @property
    def nameplate(self) -> bool:
        """Whether it is a nameplate on a row of its own, sent apart from the
        speech after it, its name "" too where the row names none, such as
        【】."""
        return self.speakers is not None and self.speakers.own_line


def texts(rows: Sequence[str], reading: Reading, starts: Iterable[int] = ()) -> tuple[Text, ...]:
    """The texts the engine sends of a message's or scrolling text's *rows*,
    as the game wrote them, read by *reading*: from each row, the rows that
    join it (:func:`text_end`) are skipped while they hold nothing it sends
    (Reading.sends), and otherwise sent from there (:func:`next_text`). A row
    in *starts* starts a text whatever the rows before it hold, as the first
    row of a translation does."""
    commands = [{"code": 401, "parameters": [row]} for row in rows]
    apart = frozenset(starts).__contains__
    found: list[Text] = []
    at = 0
    while at < len(rows):
        end = text_end(commands, at)
        if not reading.sends("\n".join(rows[at : end + 1])):
            skipped = [at]
            for later in range(at + 1, end + 1):
                if apart(later):
                    found.append(Text(tuple(skipped), sent=False))
                    skipped = []
                skipped.append(later)
            found.append(Text(tuple(skipped), sent=False))
            at = end + 1
            continue
        sent = next_text(commands, at, rows[at], reading.speakers, apart)
        if sent.name is not None:
            found.append(
                Text((sent.name,), display_name(sent.speakers.names[0]), speakers=sent.speakers)
            )
            found.append(Text(sent.rows))
        else:
            found.append(Text(sent.rows, speakers=sent.speakers))
        at = sent.rows[-1] + 1
    return tuple(found)


def text_source(rows: Sequence[str], shown: Sequence[str] | None = None) -> str:
    """The text the engine sends of a text's *rows*, and keeps as its source:
    the first row, then each later row that holds text, a line each. *shown*
    is what each row shows now, where the row's text is its source; a later
    row that shows nothing is left out."""
    seen = rows if shown is None else shown
    return "\n".join([*rows[:1], *(row for row, now in zip(rows[1:], seen[1:]) if now.strip())])


class SentText(NamedTuple):
    """A text the engine sends of a message or scrolling text, in a copy of
    the game (:func:`sent_texts`): the rows holding it, the Japanese
    translation keeps for it as the engine sends it (:func:`text_source`),
    None for rows never translated, the speaker a nameplate names and
    whether the engine reads it (see :class:`Text`), the lines of the
    Japanese the copy keeps that are its own, as its writer kept them, and
    the speakers the engine reads on its first line (see :class:`Text`)."""

    rows: tuple[int, ...]
    source: str | None
    name: str = ""
    sent: bool = True
    kept: str | None = None
    speakers: MessageSpeakers | None = None

    @property
    def nameplate(self) -> bool:
        """Whether it is a nameplate on a row of its own (see
        :attr:`Text.nameplate`), which the engine sends to its speaker step
        apart from the text after it."""
        return self.speakers is not None and self.speakers.own_line


def _written_over(commands: list, part: Part, lines: list[str], reading: Reading) -> int:
    """How many of a translated *part*'s rows its text was written over, the
    Japanese of its source's *lines*: all of them where its writer recorded
    them (ROWS). Text written before its writer recorded them is read by its
    shape. A run writes a message's text on its first row and lays scrolling
    text over its own rows, so the rows after them are the game's own, left
    untranslated: all of them after a nameplate, else from a row that opens
    a text of its own (:func:`opens_text`). A writer laying text over the
    rows one by one, as Assistant-led's does, keeps a source line for each
    row, and fitting may move a code to the start of one; in that shape the
    game's own start only at a row opening with a code its source doesn't
    hold. A row left untranslated, holding Japanese its source doesn't, ends
    the part itself (:func:`owned`), as does a message's row past those its
    source has lines for, so only scrolling text has rows after a nameplate."""
    rows = part.rows
    if len(rows) == 1 or recorded(commands[part.anchor]) is not None:
        return len(rows)
    values = [text(commands[at]) for at in rows]
    if len(lines) == 1:
        found = reading.speakers(lines[0], values[1])
        if found is not None and found.own_line:
            return 1
    whole = "\n".join(lines)
    for at in range(1, len(rows)):
        if not opens_text(values[at]):
            continue
        if len(rows) != len(lines):
            if not (at < len(lines) and opens_text(lines[at])):
                return at
        elif _opening(values[at]) not in whole:
            return at
    return len(rows)


def _lined_up(commands: list, rows: tuple[int, ...], lines: list[str], read: list[Text]) -> bool:
    """Whether text laid over *rows* one by one follows the *read* texts of
    its source's *lines*, a row each: each text whose source holds text holds
    text on its rows, and each opening with a code opens with it on its first
    row. A text written whole on the first row, with the others left empty,
    does not, so the name its first row holds may come with the speech; nor
    does one an import laid out without the source's blank rows, which moved
    each later row up."""
    return len(rows) == len(lines) and all(
        any(text(commands[rows[at]]).strip() for at in each.rows)
        and _opening(text(commands[rows[each.rows[0]]])) == _opening(lines[each.rows[0]])
        for each in read
        if any(lines[at].strip() for at in each.rows)
    )


def sent_texts(commands: list, block: Block, reading: Reading) -> tuple[SentText, ...]:
    """The texts the engine sends of a message or scrolling text *block*,
    read by *reading*, as the game's own rows hold them (:func:`texts`),
    wherever *commands* holds them: never translated, written by a run, a
    text a part each (see :func:`_written_over`), or by a writer that kept
    one source over several texts and laid the text over their rows one by
    one, such as Assistant-led's or a translation file import before each
    text kept its own (:func:`keep_texts`), which splits where its source's
    texts part while the rows line up (:func:`_lined_up`)."""
    # Each part's rows, and the Japanese of the rows its text was written
    # over, None for rows never translated, which are their own.
    segments: list[tuple[tuple[int, ...], list[str] | None]] = []
    for part in block.parts:
        kept = source(commands, part) if part.translated else None
        if kept is None:
            segments.append((part.rows, None))
            continue
        lines = kept.split("\n")
        own = _written_over(commands, part, lines, reading)
        segments.append((part.rows[:own], lines))
        if own < len(part.rows):
            segments.append((part.rows[own:], None))
    # The game's own rows, each segment's in turn: a segment's texts start at
    # its first.
    original: list[str] = []
    owners: list[tuple[int, int]] = []
    starts: list[int] = []
    for number, (rows, lines) in enumerate(segments):
        starts.append(len(original))
        theirs = [text(commands[at]) for at in rows] if lines is None else lines
        original += theirs
        owners += [(number, at) for at in range(len(theirs))]
    read: list[list[Text]] = [[] for _segment in segments]
    for each in texts(original, reading, starts):
        number = owners[each.rows[0]][0]
        read[number].append(each._replace(rows=tuple(owners[at][1] for at in each.rows)))
    found: list[SentText] = []
    for (rows, lines), mine in zip(segments, read):
        if lines is None or (len(mine) > 1 and _lined_up(commands, rows, lines, mine)):
            for each in mine:
                own = None if lines is None else [lines[at] for at in each.rows]
                found.append(
                    SentText(
                        tuple(rows[at] for at in each.rows),
                        None if own is None else text_source(own),
                        each.name,
                        each.sent,
                        None if own is None else "\n".join(own),
                        each.speakers,
                    )
                )
        else:
            # One text: a nameplate written with its speech names no speaker
            # on a row of its own there, while a name sharing the first line
            # with the text still names one.
            if len(mine) == 1:
                (only,) = mine
            else:
                first = mine[0] if mine else Text(rows)
                only = Text(rows, speakers=None if first.nameplate else first.speakers)
            found.append(
                SentText(
                    rows,
                    text_source(lines),
                    only.name,
                    only.sent,
                    "\n".join(lines),
                    only.speakers,
                )
            )
    return tuple(found)


def keep_sources(
    commands: list, block: Block, reading: Reading, part: Part | None = None
) -> None:
    """Keep each translated text of a message or scrolling text *block*, or
    of its *part* when given, its own Japanese on its first row, with the
    rows it covers (ROWS), as :func:`sent_texts` reads them, where a writer
    kept one source over it and others: so a text written after keeps the
    texts around it apart. A text whose first row keeps its Japanese already
    is left as its writer kept it. A text of blank rows, such as a blank
    first row before a row opening with \\SE[1], keeps no source: its rows
    are the game's own, which hold nothing to translate, and an empty source
    is one Text QA can't read."""
    for each in sent_texts(commands, block, reading):
        if part is not None and each.rows[0] not in part.rows:
            continue
        first = commands[each.rows[0]]
        if each.kept is None or first.get("_original") == each.kept:
            continue
        if not each.kept.strip():
            for note in NOTES:
                first.pop(note, None)
            continue
        first["_original"] = each.kept
        record_rows(first, len(each.rows))


def keep_texts(commands: list, reading: Reading, rows: Iterable[int] | None = None) -> None:
    """Keep each translated text of every message and scrolling text in an
    event command list its own source (:func:`keep_sources`), as
    :func:`sent_texts` reads them by *reading*, or only of the blocks holding
    a row of *rows*: Assistant-led's writer leaves no source laid over
    several texts, and Text QA reads each text as a record of its own."""
    wanted = None if rows is None else frozenset(rows)
    for block in list(blocks(commands)):
        if block.kind not in (MESSAGE, SCROLL):
            continue
        if wanted is None or not wanted.isdisjoint(block.rows):
            keep_sources(commands, block, reading)


def keep_document_texts(document: Any, reading: Reading) -> None:
    """:func:`keep_texts` over every event command list in a data file, in
    place."""
    for _path, commands in command_lists(document):
        keep_texts(commands, reading)


def keep_sent_sources(
    commands: list, anchor: int, reading: Reading, *, opened_only: bool = False
) -> None:
    """Keep each text of the message's or scrolling text's translation
    anchored at *anchor* its own Japanese, as :func:`sent_texts` reads them
    by *reading* (:func:`keep_sources`): a writer laying one source over a
    message's rows one by one, as Assistant-led's did, keeps it over every
    text there, such as a name on a row of its own and its speech, or a row
    opening a text of its own with a code such as \\SE[1] (:func:`opens_text`).
    A run reading the text from the anchor would read that whole source as
    the anchor's row, a name's speech as a second name, and send the rows
    after it apart, the speech's English as its text, or the whole source
    for the rows before a code row and that row's own text after. With
    *opened_only*, as runs frozen at event-left-rows-v4 do, only where a row
    of it after the first opens a text of its own. Runs frozen at v4 and v5
    keep sources so; later runs read every text from :func:`sent_texts` and
    keep the whole block's sources before writing (rpgmakermvmz
    `_keep_block_sources`)."""
    block = block_at(commands, anchor)
    part = block.part(anchor) if block is not None else None
    if (
        block is None
        or part is None
        or part.anchor != anchor
        or len(part.rows) < 2
        or _translation(commands[anchor]) is None
        or (opened_only and not any(opens_text(text(commands[at])) for at in part.rows[1:]))
    ):
        return
    keep_sources(commands, block, reading, part)


def spread(value: str, count: int) -> list[str]:
    """A text's rows laid over the *count* commands that hold it, which the
    game shows one after another: a row each, the rows left over in the
    last command and empty commands when the text has fewer rows. No command
    is added or removed, so a saved game's place in an event stays valid and
    each command keeps its source."""
    rows = value.split("\n")
    rows += [""] * (count - len(rows))
    return rows[: count - 1] + ["\n".join(rows[count - 1 :])]


def message_entry(text: str, speaker: str, *, unwrap: bool = True) -> str | None:
    """The line Guided translation sends for a message's *text* and its
    *speaker*'s name, or None for none: unwrapped onto one line unless
    *unwrap* is false, and headed by the speaker as ``[Name]: ``."""
    if unwrap:
        text = text.replace("\n", " ")
    text = text.replace("\\px[200]", "")
    if not text:
        return None
    return to_prefixed(speaker, text)


# The codes at the start of a message's text that Guided translation keeps
# out of what it sends and writes back in front of the translation: a run of
# presentation codes with an argument, such as \F[1] or \SE[...], but never
# the colour, name, icon, key and variable codes (\C \N \I \K \V), which are
# part of the text; then a bare escape; then an _ABL marker.
LEAD_CODES = re.compile(r"^((?:[\\]+[^cCnNiIkKvV{}]+?\[[\d\w\W]+?\]?\])+)")
LEAD_ESCAPES = re.compile(r"^(\\mn\\tmn|\\tmn|\\mn|\\vc)")
LEAD_MARKER = "_ABL"
# An MV name window's tag in a message's text, such as \n<Ellen>, which
# Guided translation sends as the speaker and writes back in front of the
# translation: group 1 the tag, group 2 the name.
NAMETAG = re.compile(
    r"([\\]+[kKnN][wWcCrRrEe]?[\[<](?:[\\]*\w\[\d+\])?(.*?)(?:[\\]*\w\[\d+\])?[>])"
)


def message_lead(text: str) -> int:
    """How many characters at the start of a message's *text* are the codes
    Guided translation keeps out of what it sends: a NAMETAG wherever it
    stands among LEAD_CODES, LEAD_ESCAPES and LEAD_MARKER, which follow in
    that order."""
    rest = text
    named = False
    for pattern in (LEAD_CODES, LEAD_ESCAPES, None):
        if not named and (tag := NAMETAG.match(rest)):
            rest = rest[tag.end() :]
            named = True
        found = pattern.search(rest) if pattern else None
        if found:
            rest = rest[found.end() :]
    rest = rest.removeprefix(LEAD_MARKER)
    return len(text) - len(rest)


_SENTENCE_GAP = re.compile(r"([!?])([A-Z])")
# A run of pause codes (\. \! \| \^) and what comes right before it: a
# code, such as \C[2] or \{, or a character that is neither a space nor a
# backslash.
_PAUSE_RUN = re.compile(
    r"(\\(?:[A-Za-z]+(?:\[[^\]\n]*\]|<[^>\n]*>)?|[{}<>$])|[^\s\\])((?:\\[.!|^])+)"
)
# The codes that show a word or an icon: actor, variable and party member
# names, icons and the currency unit.
_SHOWN_CODE = re.compile(r"\\(?:[NnVvPpIi]\[|[Gg]$)")


def _pause_spacing(found: re.Match) -> str:
    """One space before a pause run after a word or a code that shows one,
    none after a code that shows nothing, such as a colour."""
    before, run = found.groups()
    if before.startswith("\\") and not _SHOWN_CODE.match(before):
        return found.group(0)
    return f"{before} {run}"


def written_message(text: str, language) -> str:
    """A message's or scrolling text's translation (401, 405) as both methods
    write it into *language*, without the codes in front of it
    (message_lead): 。 left out after "...", and for a Latin-script target
    a space after ! or ? before a capital, since Japanese sets none after
    ！ and ？ and a model leaves it out too, one space before a whole run of
    pause codes (\\. \\! \\| \\^) after a word (_pause_spacing), so none comes
    inside the run, and "- " closed up to "-". Writing it again changes
    nothing."""
    text = target_text.full_stops(text, language, target_text.AFTER_ELLIPSIS)
    if target_text.full_width(language):
        return text
    text = _SENTENCE_GAP.sub(r"\1 \2", text)
    text = _PAUSE_RUN.sub(_pause_spacing, text)
    return text.replace("- ", "-")


# The text rows written_rows writes: a message's and scrolling text's.
MESSAGE_ROWS = (HEAD_ROWS[101], HEAD_ROWS[105])


def written_rows(rows: list[str], language) -> list[str]:
    """A translated message's or scrolling text's rows as written_message
    writes them, the codes in front of the first row kept as they are, as
    Guided translation never sends them."""
    written = []
    for index, row in enumerate(rows):
        lead = message_lead(row) if index == 0 else 0
        written.append(row[:lead] + written_message(row[lead:], language))
    return written


def write_text(
    commands: list,
    rows: tuple[int, ...],
    value: str,
    *,
    joined: bool = True,
    record: bool,
) -> None:
    """Write a part's text, *value*, over the text *rows* that hold it, whose
    first keeps its source, and with *record*, as a writer that chose those
    rows does, record the rows it now holds (:func:`record_rows`); each
    caller says which it is. Joined, as translation writes a message, the first
    row holds the text and the others are emptied, which the engine leaves
    out when it writes the list back. Otherwise the text is laid over the
    rows by :func:`spread`, adding and removing none, as a list written as it
    stands needs. Text the translation left untranslated
    (util.translation.reply_to_write) is not written, so its rows stay as
    the game has them. Without *record*, as runs frozen before
    event-left-rows-v3 write and as a refusal note's restore writes the
    source back over the rows its translation holds, a joined text drops its
    record and laid text keeps one only where it had one."""
    first = commands[rows[0]]
    if joined:
        first["parameters"] = [value]
        for at in rows[1:]:
            commands[at]["code"] = -1
            commands[at]["parameters"] = []
    else:
        for at, row in zip(rows, spread(value, len(rows))):
            commands[at]["parameters"] = [row]
    if record:
        record_rows(first, 1 if joined else len(rows))
    elif joined:
        first.pop(ROWS, None)
    elif ROWS in first:
        first[ROWS] = len(rows)


def write_help(commands: list, rows: tuple[int, ...], lines: list[str]) -> int:
    """Write a comment's text, *lines*, over the *rows* that hold it without
    adding or removing a command, and record on the first, when it keeps the
    Japanese, how many rows it holds. Rows it no longer needs move past the
    game's own rows after it, such as a page number, to the end of the
    comment or the next translation, where an empty row shows nothing, so
    the comment reads as the text lays out. A translation keeps its place:
    Text QA and saved notes know it by it. Returns the rows it holds."""
    used = min(len(rows), max(1, len(lines)))
    for at, value in zip(rows, spread("\n".join(lines), used)):
        commands[at]["parameters"] = [value]
    for at in rows[used:]:
        commands[at]["parameters"] = [""]
    record_rows(commands[rows[0]], used)
    spare = rows[used:]
    later = run(commands, rows[-1], 408)
    if spare and any(text(commands[at]).strip() for at in later):
        span = range(spare[0], later[-1] + 1)
        commands[span.start : span.stop] = [commands[at] for at in span if at not in spare] + [
            commands[at] for at in spare
        ]
    return used


def shown(commands: list, rows: Iterable[int]) -> str:
    """The text a window shows of a block's *rows*, such as a choice's help
    whole: the game's own rows and every part, while empty rows moved to the
    end (see :func:`write_help`) show nothing."""
    return "\n".join(text(commands[at]) for at in rows).rstrip("\n")


def help_layout(commands: list, anchor: int) -> dict[str, list] | None:
    """The comment a choice's help translation at *anchor* shows in, as
    plain data a check can keep beside the translation: the text of each of
    its rows, the ones the translation owns (``part``) and the ones a later
    or earlier translation starts at (``translated``). None for other text."""
    block = block_at(commands, anchor)
    if block is None or block.kind != HELP or anchor not in block.rows:
        return None
    place = {at: number for number, at in enumerate(block.rows)}
    return {
        "rows": [text(commands[at]) for at in block.rows],
        "part": [place[at] for at in owned(commands, anchor)],
        "translated": [
            place[at] for at in block.rows if at != anchor and "_original" in commands[at]
        ],
    }


def help_shown(layout: dict[str, list], lines: list[str] | None = None) -> str:
    """The text a choice's help window shows (see :func:`shown`) from its
    :func:`help_layout`, once *lines* are written over the translation's rows
    as :func:`write_help` writes them, or as it is without *lines*."""
    commands = [{"code": 408, "parameters": [row]} for row in layout["rows"]]
    for at in layout["translated"]:
        commands[at]["_original"] = ""
    if lines is not None:
        write_help(commands, tuple(layout["part"]), lines)
    return shown(commands, range(len(commands)))


def row_codes(value: str, tokens: re.Pattern) -> tuple[list[tuple[str, ...]], Counter]:
    """*value*'s runtime codes (*tokens*) with the ones each row starts with
    counted once for a run of rows that start with the same ones: the
    row-start codes of each run in order, and the other codes."""
    runs: list[tuple[str, ...]] = []
    others: Counter = Counter()
    for row in re.split(r"\n|<br>", value):
        if not row.strip():
            continue
        match = PER_LINE.match(row)
        start = tuple(tokens.findall(match.group(0))) if match else ()
        if not runs or runs[-1] != start:
            runs.append(start)
        others.update(tokens.findall(row[match.end() :] if match else row))
    return runs, others
