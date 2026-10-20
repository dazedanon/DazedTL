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
translated parts are the game's own, translated or not. Translation records
how many rows a choice help or comment part owns beside ``_original``, under
``_rows``; text translated before it did is read by its shape (see
:func:`owned`). Assistant-led keeps a comment's Japanese, marker included, on
the comment (108) itself.

Commands the engine empties when it writes a message's translation over its
rows (code -1, no parameters) are left out until it writes the list back.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterator

# The number of rows a part's text owns, kept on its anchor beside
# `_original`. Notes are not game data: whatever copies or compares commands
# treats both as the translation's.
ROWS = "_rows"
NOTES = frozenset({"_original", ROWS})

MESSAGE = "message"
SCROLL = "scroll"
CHOICE = "choice"
HELP = "help"
COMMENT = "comment"

# A block's first command, and the code of its rows.
_HEADS = {101: (MESSAGE, 401), 105: (SCROLL, 405), 108: (COMMENT, 408)}
# A part's anchor's code, and the code of the rows it owns.
ROW_CODES = {401: 401, 405: 405, 408: 408, 108: 408}

# Japanese that DazedTL never rewraps; ・ and ー alone are not Japanese.
_JAPANESE = re.compile(r"[\u3040-\u30fa\u30fd-\u30ff\u3400-\u9fff]")

# Codes translation repeats at the start of every row of a message: centring,
# instant lines and an indent.
PER_LINE = re.compile(r"^(?:\\+a[clr](?![A-Za-z])|\\+>|\\+px\[\d+\])+ ?", re.IGNORECASE)


def command_lists(document: Any, path: tuple = ()) -> Iterator[tuple[tuple, list]]:
    """Every event command list in a data file, by the path to it."""
    if isinstance(document, list):
        if any(isinstance(item, dict) and "code" in item for item in document):
            yield path, document
            return
        for index, child in enumerate(document):
            yield from command_lists(child, path + (index,))
    elif isinstance(document, dict):
        for key, child in document.items():
            if key != "_original":
                yield from command_lists(child, path + (key,))


def japanese(text: Any) -> bool:
    """Whether *text* still holds Japanese."""
    return isinstance(text, str) and bool(_JAPANESE.search(text))


def code(command: Any) -> int | None:
    return command.get("code") if isinstance(command, dict) else None


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

    def part(self, index: int) -> Part | None:
        """The part holding the command at *index*, its anchor or a row."""
        return next((part for part in self.parts if index in part.commands), None)


def marker(command: Any) -> str:
    """A comment's (108) first line as the game wrote it."""
    original = command.get("_original") if isinstance(command, dict) else None
    if isinstance(original, str) and original.strip():
        return original.split("\n", 1)[0].strip()
    return text(command).strip()


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


def recorded(command: Any) -> int | None:
    """The rows a part's anchor records it owns, or None."""
    rows = command.get(ROWS) if isinstance(command, dict) else None
    return rows if isinstance(rows, int) and not isinstance(rows, bool) and rows > 0 else None


def _following(commands: list, start: int, row_code: int):
    """The indexes of the text rows after *start*, past emptied commands."""
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
    """The text rows after *start* up to the next translation: what a
    message's translation and Assistant-led's write own."""
    rows = []
    for at in _following(commands, start, row_code):
        if "_original" in commands[at]:
            break
        rows.append(at)
    return tuple(rows)


def owned(
    commands: list,
    anchor: int,
    *,
    original: list | None = None,
    help_block: bool | None = None,
) -> tuple[int, ...]:
    """The text rows the translation anchored at *anchor* owns, in order; a
    comment (108) anchor owns the rows after it.

    The rows its anchor records (``_rows``). Without that record:
    - a message, scrolling text, or comment anchored on its 108 (as
      Assistant-led writes them) owns its rows up to the next translation
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
    for at in _following(commands, anchor, row_code):
        if "_original" in commands[at] or (count is not None and len(rows) >= count):
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
        if not value.strip() or japanese(value):
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
    theirs = [text(original[at]) for at in _following(original, heads[ordinal], 408)]
    position = 0
    owner: list[int] | None = None
    owners: dict[int, list[int]] = {}
    for at in _following(commands, head, 408):
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
        at -= 1
        while at >= 0 and emptied(commands[at]):
            at -= 1
        if at < 0:
            return False
        if code(commands[at]) != 404 or commands[at].get("indent") != indent:
            break
    while at >= 0 and (code(commands[at]) == 401 or emptied(commands[at])):
        at -= 1
    return at >= 0 and code(commands[at]) == 101 and has_face(commands[at])


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
        rows = tuple(_following(commands, index, row_code))
    elif command_code in (401, 405) and _text_row(command, command_code):
        # Rows without their first command, as hand-made lists have.
        kind, row_code, head = (MESSAGE if command_code == 401 else SCROLL), command_code, None
        rows = (index, *_following(commands, index, command_code))
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
        index = max(block.rows[-1] if block.rows else index, index) + 1


def block_at(commands: list, index: int, *, original: list | None = None) -> Block | None:
    """The block holding the command at *index*, or None."""
    if not 0 <= index < len(commands):
        return None
    row_code = code(commands[index])
    start = index
    if row_code in (401, 405, 408):
        while start > 0 and (code(commands[start - 1]) == row_code or emptied(commands[start - 1])):
            start -= 1
        head_code = {401: 101, 405: 105, 408: 108}[row_code]
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


def spread(value: str, count: int) -> list[str]:
    """A text's rows laid over the *count* commands that hold it, which the
    game shows one after another: a row each, the rows left over in the
    last command and empty commands when the text has fewer rows. No command
    is added or removed, so a saved game's place in an event stays valid and
    each command keeps its source."""
    rows = value.split("\n")
    rows += [""] * (count - len(rows))
    return rows[: count - 1] + ["\n".join(rows[count - 1 :])]


def untranslated(reply: Any, sent: Any) -> bool:
    """Whether a reply leaves its text untranslated: text the translation
    left untranslated or refused comes back as it was sent."""
    return reply == sent


def write_text(commands: list, rows: tuple[int, ...], value: str, *, joined: bool = True) -> None:
    """Write a part's text, *value*, over the text *rows* that hold it.
    Joined, as translation writes a message, the first row holds the text
    and the others are emptied, which the engine leaves out when it writes
    the list back. Otherwise the text is laid over the rows by :func:`spread`,
    adding and removing none, as a list written as it stands needs. Text the
    translation did not translate (see :func:`untranslated`) is not written,
    so its rows stay as the game has them."""
    if joined:
        commands[rows[0]]["parameters"] = [value]
        for at in rows[1:]:
            commands[at]["code"] = -1
            commands[at]["parameters"] = []
        return
    for at, row in zip(rows, spread(value, len(rows))):
        commands[at]["parameters"] = [row]


def write_help(commands: list, block: Block, rows: tuple[int, ...], lines: list[str]) -> int:
    """Write a comment's translation, *lines*, over the *rows* it owns
    without adding or removing a command, and record on the first, which
    keeps its Japanese, how many rows it holds. Rows it no longer needs move
    to the end of the comment, where an empty row shows nothing, so the
    comment reads as the translation lays out. Returns the rows it holds."""
    used = min(len(rows), max(1, len(lines)))
    for at, value in zip(rows, spread("\n".join(lines), used)):
        commands[at]["parameters"] = [value]
    for at in rows[used:]:
        commands[at]["parameters"] = [""]
    if "_original" in commands[rows[0]]:
        commands[rows[0]][ROWS] = used
    else:
        commands[rows[0]].pop(ROWS, None)
    spare = rows[used:]
    later = [at for at in block.rows if at > rows[-1]]
    if spare and any(text(commands[at]).strip() for at in later):
        # The spare rows go past the comment's later rows; every command
        # stays in the list.
        span = range(spare[0], later[-1] + 1)
        commands[span.start : span.stop] = [commands[at] for at in span if at not in spare] + [
            commands[at] for at in spare
        ]
    return used


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
