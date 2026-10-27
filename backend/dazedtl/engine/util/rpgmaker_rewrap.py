"""Fit RPG Maker MV/MZ/Ace text to the game's windows.

Translation wraps the text it writes with these functions, and every later
write of translated text (Apply, QA corrections, new Line widths) fits again
the lines that no longer fit, so the game's text is measured and wrapped one
way throughout; new Line widths also lay out again a message fitted to a
narrower window (see :func:`fit_value`). Line widths count half-width cells
(see :func:`util.dazedwrap.cells`), and lines break as the target language
breaks them: English at its spaces, Chinese and Japanese between characters
(see :class:`util.dazedwrap.Words`). The target is the game's (see
:attr:`Layout.target`) or, while a run translates, the run's. On-screen
checks, such as QA's captures and the playtest, confirm what a count cannot
see.

Only known display fields are touched, and ``_original`` never is.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import groupby
from typing import Any, Iterator

from util import dazedwrap
from util.game_settings import (
    MESSAGE_ROWS_KEY,
    game_wrap_widths,
    load_language_pair,
    normalize_wrap_widths,
)
from util import rpgmaker_blocks as blocks
from util import rpgmaker_script_strings as script_strings
from util.rpgmaker_blocks import PER_LINE as _PER_LINE
from util.rpgmaker_blocks import spread
from util.rpgmaker_script_strings import BREAK
from util.source_text import words_left


LIST_FIELDS_BY_FILE = {
    "Actors.json": ("profile",),
    "Armors.json": ("description",),
    "Items.json": ("description",),
    "Skills.json": ("description",),
    "States.json": ("description",),
    "Weapons.json": ("description",),
}
# Help and status windows show two rows unless the source spends more.
HELP_ROWS = 2

# The note bodies the translation module wraps as player-facing prose; True
# marks the SG info box, whose bullet lines stay headers. Only the captured
# body is touched, so plugin tags stay exact.
_NOTE_BODY_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"<SG説明:\n?(.*?)>", re.DOTALL), True),
    (re.compile(r"<SG説明:.+?Client\s?:.+?\n\n(.*?)>", re.DOTALL), True),
    (re.compile(r"<sub_[123]:([^>]+)", re.DOTALL), False),
    (re.compile(r"<infowindow:(.*?)>", re.DOTALL), False),
    (re.compile(r"<dPlnText:(.*?)>", re.DOTALL), False),
    (re.compile(r"<ExtendDesc:(.*?)>", re.DOTALL), False),
    (re.compile(r"<ClassMessage>\n?(.*?)</ClassMessage>", re.DOTALL), False),
    (re.compile(r"<コメント:\n?(.*?)>", re.DOTALL), False),
)
# Those tags as the setup prompts name them: noteWidth is measured on the
# window that draws them, since no other note text is wrapped.
WRAPPED_NOTE_TAGS = (
    "<SG説明:...>",
    "<sub_1:...>",
    "<sub_2:...>",
    "<sub_3:...>",
    "<infowindow:...>",
    "<dPlnText:...>",
    "<ExtendDesc:...>",
    "<ClassMessage>...</ClassMessage>",
    "<コメント:...>",
)
# Plugin commands (357) whose text shows in a message window, and the fields
# translation wraps there. Text pictures and other free-floating text have
# no box to fit; on-screen checks see them.
MESSAGE_PLUGIN_TEXT = {
    "AdvExtentionllk": ("comment", "text"),
    "LL_GalgeChoiceWindow": ("messageText",),
}


# ---------------------------------------------------------------- measuring

# A name window code (\n<Name>, \nc<Name>, \k<Name>): the name shows in its
# own window, not on the message's line.
_NAME_WINDOW = re.compile(r"\\+[nNkK][a-zA-Z]?<[^<>\n]*>")
# Alignment codes (\ac, \ar, \al) draw nothing. A letter right after one makes
# a different code, as RPG Maker reads every letter of an escape.
_ALIGNMENT = re.compile(r"\\+a[clr](?![A-Za-z])", re.IGNORECASE)
# Codes that draw text or an icon in their place, and the characters each
# takes: an actor's name (\N[n], \P[n]), an icon (\I[n]), a variable (\V[n])
# and the currency unit (\G). Names and numbers vary, so these are generous;
# translation and every later fit count them the same way.
_EXPANDING = {
    re.compile(r"\\+[NnPp]\[\d+\]"): 8,
    re.compile(r"\\+[Ii]\[\d+\]"): 2,
    re.compile(r"\\+[Vv]\[\d+\]"): 3,
    re.compile(r"\\+[Gg](?![A-Za-z])"): 2,
}
# A marker some games put before a message for a plugin, not drawn.
_MARKER = re.compile(r"^_ABL")
# The line width such a message wraps to.
MARKED_WIDTH = 100


def drawn_text(text: str) -> str:
    """The characters *text* draws on one line of a window: name windows,
    alignment and other codes draw nothing there, while names, icons and
    variables stand in as the room they take."""
    text = _MARKER.sub("", _ALIGNMENT.sub("", _NAME_WINDOW.sub("", text)))
    for pattern, size in _EXPANDING.items():
        text = pattern.sub("x" * size, text)
    return dazedwrap.visible_text(text)


# Fitting measures each word of a game's text, whose words repeat.
@lru_cache(maxsize=1 << 16)
def visible_width(text: str) -> int:
    """The half-width cells *text* takes on one line of a window (see
    :func:`drawn_text`), each character as :func:`util.dazedwrap.cells`
    counts it."""
    return dazedwrap.text_cells(drawn_text(text))


def _rendered_lines(text: str) -> list[str]:
    """The lines *text* draws: stored ``\\n`` escapes and ``<br>`` break lines
    as newlines do."""
    rendered = str(text).replace("\r\n", "\n").replace("<br>", "\n")
    return BREAK.sub("\n", rendered).split("\n")


def widest_line(text: str) -> int:
    """The visible width of *text*'s widest line."""
    return max(visible_width(line) for line in _rendered_lines(text))


def over_width(text: str, width: int) -> bool:
    return widest_line(text) > int(width)


def untranslated(
    text: str, source: str | None = None, target: str | None = None
) -> bool:
    """Whether *text*, a value or a row of a message, still holds source
    text, which DazedTL never rewraps: read as a player reads it, against
    *source*, the whole value or message it was translated from, for a
    translation into *target*, the run's by default (util/source_text
    `words_left`), so a Latin source's abbreviation, such as HP, is no text
    left. Without a source every Japanese letter is left."""
    return bool(words_left(text, source, target=target))


def _translated(text: str, source: str | None = None, target: str | None = None) -> str:
    """A message's rows without the ones left untranslated, which keep their
    rows (see wrap_message), read against its *source*."""
    return "\n".join(
        row for row in _rendered_lines(text) if not untranslated(row, source, target)
    )


_SPEAKER_LINE = re.compile(
    r"^(?P<prefix>(?:\[[^\]\n]{1,100}\]|"
    r"(?:\\+[kKnN][wWcCrReE]?[\[<][^\]>\n]+[\]>]))\n)"
)


def rendered_rows(text: str) -> int:
    """The rows *text* takes in its window. A name window on a line of its
    own takes no row; a literal [Speaker] line does."""
    if not text:
        return 0
    body = text
    prefix = _SPEAKER_LINE.match(body)
    if prefix and not prefix.group("prefix").lstrip().startswith("["):
        body = body[len(prefix.group("prefix")) :]
    return len(re.split(r"\n|<br>", body))


# ------------------------------------------------------------------ wrapping

_LEADING_CODES = re.compile(r"^(?:\\+[A-Za-z]+\[[^\]\n]*\]|\\+[{}<>|.!^$])+")


def _source_body(source: str | None) -> str | None:
    """The part of a Japanese source that lays out a message's body: without
    a name window or a speaker line, and without codes in front."""
    if source is None:
        return None
    body = _NAME_WINDOW.sub("", str(source).replace("\r\n", "\n"))
    prefix = _SPEAKER_LINE.match(body)
    if prefix:
        body = body[len(prefix.group("prefix")) :]
    return "\n".join(_LEADING_CODES.sub("", line) for line in body.split("\n"))


# A row that starts a font size of its own (\{, \}, \FS[n]) starts new text,
# and a label row, such as 【Name】, stands alone.
_SIZE_START = re.compile(r"^\\+(?:[{}]|FS\[\d+\])", re.IGNORECASE)
_LABEL_ROW = re.compile(r"^\s*(?:【[^】\n]*】|\[[^\]\n]*\])\s*$")


@dataclass
class _Span:
    """Rows, or the commands that hold them, laid out together: text that
    flows, with the code it repeats on each row, or ones kept as they are."""

    start: int
    end: int
    flows: bool
    per_line: str = ""


def _row_kind(row: str, source: str | None = None, target: str | None = None):
    """How a row groups (see :func:`_spans`): None when blank, False when it
    is kept as it is, otherwise the code it repeats on each row and whether
    it sets the font size. A row is read against its message's *source*."""
    if not row.strip():
        return None
    if untranslated(row, source, target) or _LABEL_ROW.match(row):
        return False
    match = _PER_LINE.match(row)
    return (match.group(0) if match else "", bool(_SIZE_START.match(row)))


def _command_kind(text: str, source: str | None = None, target: str | None = None):
    """How a command holding some of a message's rows groups: as its first
    row that flows, or kept as it is when none does."""
    kinds = [_row_kind(row, source, target) for row in text.split("\n") if row.strip()]
    if not kinds:
        return None
    return next((kind for kind in kinds if kind), False)


def _spans(kinds: list) -> list[_Span]:
    """A message's rows, or commands, by their kind (see :func:`_row_kind`),
    in the spans wrapping keeps apart. Japanese left untranslated and labels
    keep their rows, and a row that changes the code repeated on each row,
    such as centring, or sets the font size starts a span of its own; blank
    rows go with the text around them."""
    spans: list[_Span] = []
    for index, kind in enumerate(kinds):
        current = spans[-1] if spans and spans[-1].flows else None
        if kind is False:
            spans.append(_Span(index, index + 1, False))
        elif kind is None:
            if current:
                current.end = index + 1
            else:
                spans.append(_Span(index, index + 1, True))
        else:
            per_line, sized = kind
            started = current is not None and any(kinds[current.start : current.end])
            if (
                current is None
                or (index and sized)
                or (started and per_line.strip() != current.per_line.strip())
            ):
                spans.append(_Span(index, index + 1, True, per_line))
            else:
                current.end = index + 1
                current.per_line = current.per_line or per_line
    return spans


def _flow(
    lines: list[str],
    per_line: str,
    width: int,
    source: str | None,
    rows: int | None,
    target: str | None,
) -> list[str]:
    """Rows of text in *target* wrapped to *width* (see
    :func:`dazedwrap.wrapShaped`), keeping their blank rows before and after,
    with the code they repeat on each row on each new row."""
    if per_line:
        lines = [_PER_LINE.sub("", line) for line in lines]
    content = [index for index, line in enumerate(lines) if line.strip()]
    if not content:
        return lines
    first, last = content[0], content[-1]
    wrapped = dazedwrap.wrapShaped(
        "\n" * first + "\n".join(lines[first : last + 1]),
        int(width),
        source,
        rows,
        measure=visible_width,
        target=target,
    ).split("\n") + [""] * (len(lines) - last - 1)
    if per_line:
        return [_repeated(per_line, line) if line.strip() else line for line in wrapped]
    return wrapped


def _item_row(row: str) -> bool:
    """Whether a row starts a list item, as wrapping reads one (see
    :data:`dazedwrap.ITEM_START`), after the codes its message repeats on
    each row."""
    return bool(dazedwrap.ITEM_START.match(_PER_LINE.sub("", row).lstrip()))


def _item_rows(rows: list[str]) -> int:
    return sum(map(_item_row, rows))


def _items(rows: list[str]) -> list[list[str]]:
    """Rows in groups that each start with a list item, the rows before the
    first item a group of their own."""
    groups: list[list[str]] = []
    for row in rows:
        if not groups or _item_row(row):
            groups.append([row])
        else:
            groups[-1].append(row)
    return groups


def _repeated(code: str, line: str) -> str:
    """*line* after the code its message repeats on each row. RPG Maker reads
    every letter after an escape as part of it, so a letter after a code such
    as ``\\ac`` takes a space between (``\\acWhat`` hides "What")."""
    if line[:1].isascii() and line[:1].isalpha() and re.search(r"\\[A-Za-z]+$", code):
        return code + " " + line
    return code + line


def _message(text: str, rows: int | None) -> tuple[str, list[str], int | None, bool]:
    """A message as :func:`wrap_message` lays it out: its speaker line, the
    rows of its body without blank rows at the end, the rows a page of its
    window shows below a [Speaker] line, and whether it breaks lines with
    ``<br>``."""
    prefix = ""
    body = text
    speaker = _SPEAKER_LINE.match(body)
    if speaker:
        prefix = speaker.group("prefix")
        body = body[len(prefix) :]
        if rows is not None and prefix.lstrip().startswith("["):
            rows = max(1, rows - 1)
    uses_br = "<br>" in body and "\n" not in body
    if uses_br:
        body = body.replace("<br>", "\n")
    lines = body.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return prefix, lines, rows, uses_br


def _unpaged(
    text: str, rows: int, source: str | None = None, target: str | None = None
) -> str:
    """A message :func:`wrap_message` paged into windows of *rows* as it read
    the message before, without the empty rows it fills a page with (see
    :func:`dazedwrap.unpaged`), and without blank rows at the end."""
    prefix, lines, page, uses_br = _message(text, rows)
    read: list[str] = []
    for span in _spans([_row_kind(line, source, target) for line in lines]):
        part = "\n".join(lines[span.start : span.end])
        read.append(dazedwrap.unpaged(part, page or rows) if span.flows else part)
    body = "\n".join(read)
    return prefix + (body.replace("\n", "<br>") if uses_br else body)


def wrap_message(
    text: str,
    width: int,
    *,
    source: str | None = None,
    rows: int | None = None,
    every: bool = False,
    target: str | None = None,
    original: str | None = None,
) -> str:
    """A message laid out for its window: the body wrapped to *width* like
    its *source* (see :func:`dazedwrap.wrapShaped`), paging after a sentence
    where it needs more than *rows*, its lines breaking as text in *target*,
    the run's target by default, breaks them. A speaker line stays first,
    ``<br>`` breaks stay ``<br>``, and codes translation repeats on each
    line, such as centring, are repeated on each new line. Blank rows at the
    end go: a message spread over several commands gets them back from
    :func:`spread`.

    Rows that keep a layout of their own (see :func:`_spans`) split the
    message: then each part wraps on its own, only where a row is wider
    than *width* (or every part that flows, with *every*), and without the
    source's layout, which no longer lines up with the rows. Rows are read
    against *original*, the source of the whole message when *text* is
    part of it, else *source* (see :func:`untranslated`)."""
    if not text or not text.strip():
        return text
    against = source if original is None else original
    prefix, lines, rows, uses_br = _message(text, rows)
    spans = _spans([_row_kind(line, against, target) for line in lines])
    if len(spans) == 1 and spans[0].flows:
        wrapped = _flow(
            lines, spans[0].per_line, width, _source_body(source), rows, target
        )
    else:
        wrapped = []
        for span in spans:
            part = lines[span.start : span.end]
            if span.flows and (every or any(visible_width(row) > width for row in part)):
                wrapped += _flow(part, span.per_line, width, None, rows, target)
            else:
                wrapped += part
    # A message window pages instead of cutting rows off, so a list keeps one
    # item a row where flowing ran items together: on Fuuma, a too-wide item
    # pulled the item above onto its row, which text QA's lint then flagged.
    if _item_rows(wrapped) < _item_rows(lines):
        wrapped = []
        for span in spans:
            part = lines[span.start : span.end]
            for item in _items(part) if span.flows else [part]:
                if span.flows and (
                    every or any(visible_width(row) > width for row in item)
                ):
                    wrapped += _flow(item, span.per_line, width, None, rows, target)
                else:
                    wrapped += item
    result = "\n".join(wrapped)
    if uses_br:
        result = result.replace("\n", "<br>")
    return prefix + result


# A list item inside a row: an item mark after a space, past the codes
# before it.
_INLINE_ITEM = re.compile(
    r" +(?=(?:" + _LEADING_CODES.pattern.lstrip("^") + r")?"
    + dazedwrap.ITEM_START.pattern.lstrip("^") + ")"
)


def wrap_help(
    text: str, width: int, *, source: str | None = None, target: str | None = None
) -> str:
    """A choice's help laid out for its window like its *source* (see
    :func:`wrap_message`). A translation of several rows comes back on one
    line, so a list the source gives a row an item gets those rows back, as a
    message's does, even when the window then needs more rows."""
    wrapped = wrap_message(text, width, source=source, target=target)
    items = _item_rows(str(source or "").split("\n"))
    if items < 2 or "\n" in text or _item_rows(wrapped.split("\n")) >= items:
        return wrapped
    return wrap_message(
        _INLINE_ITEM.sub("\n", text), width, source=source, target=target
    )


def wrap_text(text: str, width: int, target: str | None = None) -> str:
    """Text with no source layout to follow, such as a script's message,
    wrapped to *width* in even lines."""
    return dazedwrap.wrapShaped(
        text, int(width), measure=visible_width, target=target
    )


def help_rows(source: str | None) -> int:
    """The rows a help or status window shows: two, or as many as the
    source spends there."""
    return max(HELP_ROWS, str(source or "").count("\n") + 1)


def wrap_lines(
    text: str,
    width: int,
    rows: int | None = None,
    target: str | None = None,
) -> str:
    """Database text, whose line breaks are authored, fitted as the database
    pass fits it (see :func:`dazedwrap.wrapLines`): ``\\n`` breaks, or
    ``<br>`` in text without one."""
    if "<br>" in text and "\n" not in text:
        return dazedwrap.wrapLines(
            text.replace("<br>", "\n"), width, rows, measure=visible_width, target=target
        ).replace("\n", "<br>")
    return dazedwrap.wrapLines(text, width, rows, measure=visible_width, target=target)


def wrap_note(note: str, width: int, target: str | None = None) -> str:
    """A database note with each translated prose tag body wider than
    *width* fitted to it; the rest of the note, such as other tags or a
    body left in Japanese, stays exact."""
    return _replace_spans(
        note,
        [
            (start, end, _fit_note_body(body, width, structured, target))
            for start, end, body, structured in _note_bodies(note)
            if not untranslated(body) and over_width(body, width)
        ],
    )


def _fit_note_body(body: str, width: int, structured: bool, target: str | None) -> str:
    if structured:
        return dazedwrap.wrapSGDesc(body, width, target)
    return wrap_lines(body, width, target=target)


def _note_bodies(note: str) -> Iterator[tuple[int, int, str, bool]]:
    """Each known prose tag body in *note*: its span, text and whether it is
    an SG info box."""
    occupied: list[tuple[int, int]] = []
    for pattern, structured in _NOTE_BODY_PATTERNS:
        for match in pattern.finditer(note):
            start, end = match.span(1)
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            if match.group(1).strip():
                yield start, end, match.group(1), structured


def _replace_spans(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


# An interpolation in a text variable's text is counted as wide as a
# variable's value (\V[n]).
_HELD_WIDTH = 3


def _script_string(value: str) -> tuple[int, int] | None:
    """Where the text of a text variable's operand starts and ends: an
    operand that opens with one of the quote marks translation writes it in
    (MV/MZ's template literal or VX Ace's Ruby string), up to the last one
    of that kind."""
    first = len(value) - len(value.lstrip())
    if value[first : first + 1] not in script_strings.OPENERS:
        return None
    last = value.rfind(value[first])
    return (first + 1, last) if last > first else None


def _held(value: str) -> tuple[str, list[str], tuple[int, int]] | None:
    """A text variable's operand as the lines it shows, each interpolation
    held as one character, with the interpolations and where the text is in
    *value*; None when it holds no quoted text to fit."""
    span = _script_string(value)
    if span is None:
        return None
    body = value[span[0] : span[1]]
    if script_strings.HELD.search(body):
        return None
    body, kept = script_strings.hold(body, value[span[0] - 1])
    return BREAK.sub("\n", body), kept, span


def _script_width(text: str) -> int:
    """The width of a text variable's line, each interpolation as wide as a
    variable's value."""
    return visible_width(script_strings.HELD.sub("x" * _HELD_WIDTH, text))


# The space before a word that starts with "[" or "<", which a line break
# may not take: written as "\n", a break there would start a name code such
# as \n[1] or \n<name> (see rpgmaker_script_strings.BREAK). It is held as a
# character no game text has, outside the interpolations' private use area.
_BEFORE_NAME_CODE = re.compile(rf"(?<=\S)\s+(?={script_strings.NAME_CODE})")
_KEPT_SPACE = "\U000f0000"
# Text that breaks between characters keeps such a word, or the space held
# before it, on the line before.
_NAME_CODE_START = re.compile(rf"{_KEPT_SPACE}|{script_strings.NAME_CODE}")


def wrap_script(text: str, width: int, target: str | None = None) -> str:
    """A text variable's text with its interpolations held (see
    rpgmaker_script_strings.hold), wrapped to *width* in even lines as
    :func:`wrap_text` wraps text, each interpolation as wide as a
    variable's value, as later fits count it. No line starts with "[" or
    "<" after a word, which its break would make a name code."""
    wrapped = dazedwrap.wrapShaped(
        _BEFORE_NAME_CODE.sub(_KEPT_SPACE, text),
        int(width),
        measure=lambda word: _script_width(word.replace(_KEPT_SPACE, " ")),
        target=target,
        glue=_NAME_CODE_START,
    )
    return wrapped.replace(_KEPT_SPACE, " ")


def _script_text(value: str) -> str | None:
    """The lines a text variable's operand shows, or None (see _held)."""
    held = _held(value)
    return None if held is None else script_strings.HELD.sub("x" * _HELD_WIDTH, held[0])


def wrap_variable(value: str, width: int, target: str | None = None) -> str:
    """A text variable's operand (122), the text between its quote marks
    with ``\\n`` escapes as its line breaks, wrapped to *width* when a line
    is wider. Its script stays as it runs: an interpolation such as
    ``${...}`` is never broken, and name codes such as ``\\n[1]`` stay."""
    held = _held(value)
    if held is None or max(map(_script_width, held[0].split("\n"))) <= int(width):
        return value
    body, kept, (start, end) = held
    wrapped = script_strings.release(
        wrap_script(dazedwrap.one_line(body, target), width, target), kept
    )
    return value[:start] + wrapped.replace("\n", r"\n") + value[end:]


# --------------------------------------------------------------------- boxes


@dataclass(frozen=True)
class Layout:
    """A game's Line widths, and the language its text is translated into,
    whose lines break at spaces or between characters (see
    :func:`util.dazedwrap.breaks_characters`); None is the run's."""

    width: int
    face_width: int
    list_width: int
    note_width: int
    message_rows: int
    target: str | None = None

    @classmethod
    def from_widths(
        cls, widths: dict[str, Any] | None, target: str | None = None
    ) -> Layout:
        values = normalize_wrap_widths(widths or {})
        return cls(
            values["width"],
            values["faceWidth"],
            values["listWidth"],
            values["noteWidth"],
            values[MESSAGE_ROWS_KEY],
            target,
        )

    @classmethod
    def of_game(cls, root, widths: dict[str, Any] | None = None) -> Layout:
        """The Line widths the game at *root* is fitted to, its saved ones
        unless *widths* are given, and the target its language pair records
        (see util.game_settings.load_language_pair), or None, the run's, for a
        game without one or whose settings can't be read."""
        try:
            pair = load_language_pair(root)
        except (OSError, ValueError):
            pair = None
        return cls.from_widths(
            game_wrap_widths(root) if widths is None else widths,
            pair["target"] if pair else None,
        )


@dataclass(frozen=True)
class Box:
    """The window a value shows in: its line width, the rows it shows, and
    whether text that needs more rows goes on to a new page (a message) or
    is cut off (a window of fixed height). ``rows`` None is unlimited, as in
    scrolling text. ``kind`` names how the value wraps, ``area`` the Line
    widths entry its width comes from, and ``target`` the language its lines
    break as (see :class:`Layout`)."""

    width: int
    rows: int | None
    paged: bool
    kind: str  # "message", "scroll", "lines", "note" or "variable"
    area: str | None = None
    target: str | None = None


def message_box(layout: Layout, *, face: bool = False) -> Box:
    if face:
        return Box(
            layout.face_width, layout.message_rows, True, "message", "faceWidth",
            layout.target,
        )
    return Box(layout.width, layout.message_rows, True, "message", "width", layout.target)


def choice_help_box(layout: Layout, *, face: bool = False) -> Box:
    """A choice's help (MPP_ChoiceEX): comment lines (408) the message window
    shows while the choice is open, beside the face of the message before the
    choice (see :func:`util.rpgmaker_blocks.help_face`). Rows the window cannot show go on
    to a page the player never sees, so the help is never paged."""
    message = message_box(layout, face=face)
    return Box(message.width, message.rows, False, "message", message.area, layout.target)


def scrolling_box(layout: Layout) -> Box:
    """Scroll Text, whose rows the author lays out, often as a list such as
    credits: a row too wide wraps onto rows of its own."""
    return Box(layout.width, None, False, "scroll", "width", layout.target)


def help_box(layout: Layout, source: str | None, *, dialogue: bool = False) -> Box:
    """A help or status window: two rows, or as many as the source spends.
    A profile change (325) wraps to the dialogue width, as translation does."""
    if dialogue:
        return Box(layout.width, help_rows(source), False, "lines", "width", layout.target)
    return Box(
        layout.list_width, help_rows(source), False, "lines", "listWidth", layout.target
    )


def nickname_box(layout: Layout) -> Box:
    return Box(layout.list_width, 1, False, "lines", "listWidth", layout.target)


def note_box(layout: Layout) -> Box:
    """The plugin windows that draw a note's prose tags. Their heights vary,
    so only their width is known."""
    return Box(layout.note_width, None, False, "note", "noteWidth", layout.target)


def variable_box(layout: Layout) -> Box:
    """A text variable (122), whose script string translation wraps to the
    list width (see :func:`wrap_variable`)."""
    return Box(layout.list_width, None, False, "variable", "listWidth", layout.target)


def _rows(text: str) -> list[str]:
    """A message's rows that hold text, after its speaker line."""
    speaker = _SPEAKER_LINE.match(text)
    body = text[speaker.end("prefix") :] if speaker else text
    return [row for row in _rendered_lines(body) if row.strip()]


def _parted(message: str | None) -> bool:
    """Whether a message, or its Japanese, has blank rows between its text
    below its speaker."""
    rows = [row.strip() for row in _rendered_lines(_source_body(message) or "")]
    held = [at for at, row in enumerate(rows) if row]
    return bool(held) and "" in rows[held[0] : held[-1]]


def _widened(
    text: str, box: Box, source: str | None, original: str | None = None
) -> str:
    """A message that fits *box* laid out again at its width when the fitter
    laid it out for a narrower window and the wider one takes it on fewer
    rows; otherwise *text*. A layout is the fitter's when wrapping it again
    at that width leaves it as it is, so rows a translator or the game laid
    out stay, and the message reads as if fitted at the new width at once.

    A message the fitter paged is read first without the empty rows it
    filled a page with (see :func:`_unpaged`), unless it is laid out for
    this width already with them read as paragraph breaks, or its Japanese
    has blank rows between text, which are the author's. Only a narrower
    width the rows of a message without blank rows fill as few rows as they
    hold is tried: wrapping at one where they take fewer never gives them
    back. Blank rows at the end, such as a message's spare commands, are no
    part of the layout (see :func:`wrap_message`). Rows are read against
    *original* (see :func:`fit_value`)."""
    rows = box.rows if box.paged else None
    laid = text.split("\n")
    while laid and not laid[-1].strip():
        laid.pop()
    laid = "\n".join(laid)
    held = _rows(text)
    words = dazedwrap.measure_words("\n".join(held), visible_width, box.target)

    def needed(width: int) -> int:
        return dazedwrap.rows_needed(words.sizes, width, words.gaps)

    if len(held) < 2 or needed(box.width) >= len(held):
        return text
    readings = [laid]
    # Only a message of more rows than its window shows was paged.
    paged = rows is not None and rendered_rows(laid) > rows
    if rows is not None and paged and not _parted(source):
        unpaged = _unpaged(laid, rows, original, box.target)
        if unpaged != laid:
            readings.insert(0, unpaged)
    wider: dict[str, str] = {}
    for read in readings:
        wider[read] = wrap_message(
            read,
            box.width,
            source=source,
            rows=rows,
            every=True,
            target=box.target,
            original=original,
        )
        # Laid out for this width already, its blank rows read as paragraph
        # breaks or not.
        if wider[read] == laid:
            return text
    # Rows that flow on with no blank row between need as many at a width.
    flowing = not paged and not _parted(laid)
    for read in readings:
        if len(_rows(wider[read])) >= len(held):
            continue
        for width in range(widest_line(text), box.width):
            if flowing and needed(width) < len(held):
                break
            if (
                wrap_message(
                    read,
                    width,
                    source=source,
                    rows=rows,
                    every=True,
                    target=box.target,
                    original=original,
                )
                == laid
            ):
                return wider[read]
    return text


def fit_value(
    text: str,
    box: Box,
    *,
    source: str | None = None,
    resized: bool = False,
    original: str | None = None,
) -> str:
    """*text* as DazedTL writes it to *box*: unchanged when every line fits,
    otherwise wrapped again as translation wraps it there. *resized* says the
    text was fitted to other Line widths: a message the fitter laid out for a
    narrower window is laid out again (see :func:`_widened`). Its rows are
    read against *original*, the source of the whole message when *text* is
    part of it, else *source*, which it is laid out like (see
    :func:`untranslated`)."""
    if not isinstance(text, str) or not text.strip():
        return text
    if box.kind == "note":
        return wrap_note(text, box.width, box.target)
    if box.kind == "variable":
        return wrap_variable(text, box.width, box.target)
    against = source if original is None else original
    rows_apart = box.kind in ("message", "scroll")
    if not over_width(
        _translated(text, against, box.target) if rows_apart else text, box.width
    ):
        if resized and box.kind == "message":
            return _widened(text, box, source, against)
        return text
    if box.kind == "scroll":
        return "\n".join(
            row
            if untranslated(row, against, box.target)
            else wrap_lines(row, box.width, target=box.target)
            for row in text.split("\n")
        )
    if box.kind == "lines":
        return wrap_lines(text, box.width, box.rows, box.target)
    return wrap_message(
        text,
        box.width,
        source=source,
        rows=box.rows if box.paged else None,
        target=box.target,
        original=against,
    )


def misfit(text: str, box: Box, source: str | None = None) -> str | None:
    """Why *text*, as written, still does not fit *box*, or None, its rows
    read against *source* (see :func:`untranslated`). Counts only choose
    what to look at: text a fixed window cuts off even fitted goes to Text
    QA as a ``text-fit`` check, and QA's captures and the playtest confirm
    what the game shows."""
    if not isinstance(text, str) or not text.strip():
        return None
    if box.kind == "note":
        bodies = [
            body
            for _start, _end, body, _structured in _note_bodies(text)
            if not untranslated(body)
        ]
    elif box.kind == "variable":
        bodies = [_script_text(text) or ""]
    elif box.kind in ("message", "scroll"):
        bodies = [_translated(text, source, box.target)]
    else:
        bodies = [text]
    for body in bodies:
        widest = widest_line(body)
        if widest > box.width:
            return f"has a line {widest} characters wide; its line width is {box.width}"
        if box.rows and not box.paged and box.kind != "note":
            rows = rendered_rows(body)
            if rows > box.rows:
                return f"needs {rows} rows; its window shows {box.rows}"
    return None


def rows_misfit(text: str, box: Box, source: str | None = None) -> str | None:
    """Why *text* needs more rows than *box* shows, or None, whatever its
    lines' widths: the rows of a window showing several texts whose lines
    are measured where each is written, such as a choice's help in parts
    (see :func:`util.rpgmaker_blocks.shown`)."""
    if not isinstance(text, str) or not text.strip():
        return None
    return misfit(text, replace(box, width=widest_line(text)), source)


# ------------------------------------------------------------ whole documents


@dataclass
class FitReport:
    """What fitting a file changed, and what it could not fit."""

    changes: list[dict[str, Any]] = field(default_factory=list)
    misfits: list[dict[str, Any]] = field(default_factory=list)


def fit_run(
    texts: list[str],
    box: Box,
    source: str | None = None,
    *,
    resized: bool = False,
    original: str | None = None,
) -> list[str]:
    """A message whose rows are stored in several commands, one text per
    command as Assistant-led writes them, fitted to *box* over the same
    commands. Text between commands kept as they are, such as Japanese left
    untranslated (see :func:`_spans`), is laid out as one text over its own
    commands (see :func:`spread`); Scroll Text rows wrap in their own
    command. *source* is the Japanese of the whole message, which it is laid
    out like, and *original* what its rows are read against, *source* by
    default; *resized* is :func:`fit_value`'s.

    Fitting each command on its own would have pushed 353 of Fuuma
    Chronicle's 3,307 overflowing messages past its four-row window, against
    23 when fitted as one text."""
    against = source if original is None else original
    if box.kind == "scroll" or len(texts) == 1:
        return [
            fit_value(
                text,
                box,
                source=source if len(texts) == 1 else None,
                resized=resized,
                original=against,
            )
            for text in texts
        ]
    spans = _spans([_command_kind(text, against, box.target) for text in texts])
    fitted = list(texts)
    for span in spans:
        if not span.flows:
            continue
        joined = "\n".join(texts[span.start : span.end])
        text = fit_value(
            joined,
            box,
            source=source if len(spans) == 1 else None,
            resized=resized,
            original=against,
        )
        if text != joined:
            fitted[span.start : span.end] = spread(text, span.end - span.start)
    return fitted


@dataclass(frozen=True)
class _Slot:
    """One display value in a document: where it is, its box, its source and
    how to read and write it. A message (*run*, the parameters of the
    commands that hold its rows) reads as one text and is fitted over the
    same commands (see :func:`fit_run`). A choice's help is written over its
    comment's *rows* in *commands* as translation writes it (see
    :func:`util.rpgmaker_blocks.write_help`). *source* is what it is laid
    out like, and *original* what it was translated from, which it is read
    against (see :func:`untranslated`): the whole help when the value is a
    part of it. Both are what the game keeps in `_original`, None for a
    value never translated."""

    pointer: str
    box: Box
    source: str | None
    owner: Any
    key: Any
    run: tuple[list, ...] = ()
    commands: list | None = None
    rows: tuple[int, ...] = ()
    # The rows a window shows with this text and the rest of its block,
    # checked as one once all are written (see :func:`fit_document`).
    together: tuple[int, ...] | None = None
    original: str | None = None

    @property
    def against(self) -> str | None:
        return self.source if self.original is None else self.original

    def read(self):
        if self.run:
            return "\n".join(parameters[0] for parameters in self.run)
        return self.owner[self.key]

    def fitted(self, resized: bool = False) -> list[str]:
        """The value fitted to its box (see :func:`fit_value`): a text for
        each command of a message, otherwise the one text."""
        if self.run:
            return fit_run(
                [parameters[0] for parameters in self.run],
                self.box,
                self.source,
                resized=resized,
                original=self.against,
            )
        return [
            fit_value(
                self.owner[self.key],
                self.box,
                source=self.source,
                resized=resized,
                original=self.against,
            )
        ]

    def written(self, texts: list[str]) -> str:
        """The value *texts* leave once written: help without the rows it
        no longer needs, which move out of it."""
        lines = "\n".join(texts).split("\n")
        while self.rows and len(lines) > 1 and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)

    def write(self, texts: list[str]) -> None:
        if self.rows:
            blocks.write_help(self.commands, self.rows, self.written(texts).split("\n"))
        elif self.run:
            for parameters, value in zip(self.run, texts):
                parameters[0] = value
        else:
            self.owner[self.key] = texts[0]


def _original(node: dict, key: str | None = None) -> str | None:
    original = node.get("_original")
    if key is None:
        return original if isinstance(original, str) else None
    return original.get(key) if isinstance(original, dict) and isinstance(original.get(key), str) else None


def _slots(document, file_name: str, layout: Layout) -> Iterator[_Slot]:
    """Every display value DazedTL fits in *document*."""
    fields = LIST_FIELDS_BY_FILE.get(file_name, ())
    if fields and isinstance(document, list):
        for index, entry in enumerate(document):
            if not isinstance(entry, dict):
                continue
            for name in fields:
                if isinstance(entry.get(name), str):
                    # Without an `_original` it was never translated, and
                    # its window's rows are its own.
                    source = _original(entry, name)
                    yield _Slot(
                        f"/{index}/{name}",
                        help_box(layout, source or entry[name]),
                        source,
                        entry,
                        name,
                    )
    for owner, pointer in _note_owners(document):
        yield _Slot(f"{pointer}/note", note_box(layout), None, owner, "note")
    for commands, pointer in _command_lists(document):
        yield from _command_slots(commands, pointer, layout)


def _note_owners(node, pointer: str = ""):
    if isinstance(node, dict):
        if isinstance(node.get("note"), str):
            yield node, pointer
        for key, value in node.items():
            if key != "_original":
                yield from _note_owners(value, f"{pointer}/{_pointer_part(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _note_owners(value, f"{pointer}/{index}")


def _command_lists(node, pointer: str = ""):
    if isinstance(node, dict):
        commands = node.get("list")
        if isinstance(commands, list) and any(
            blocks.code(item) is not None for item in commands
        ):
            yield commands, f"{pointer}/list"
        for key, value in node.items():
            if key == "_original" or (key == "list" and commands is value):
                continue
            yield from _command_lists(value, f"{pointer}/{_pointer_part(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _command_lists(value, f"{pointer}/{index}")


def _command_slots(commands: list, pointer: str, layout: Layout) -> Iterator[_Slot]:
    slots: list[tuple[int, _Slot]] = []
    for block in blocks.blocks(commands):
        if block.kind in (blocks.MESSAGE, blocks.SCROLL):
            # A message is fitted as a whole, even when its rows are stored
            # one command each, as Assistant-led writes them.
            if block.kind == blocks.SCROLL:
                box = scrolling_box(layout)
            else:
                box = message_box(layout, face=block.face)
            parts = block.parts
        elif block.kind == blocks.HELP:
            # Translated choice help, fitted over its own rows as a message
            # is; other comments, which plugins may read as settings, stay.
            box = choice_help_box(layout, face=block.face)
            parts = tuple(part for part in block.parts if part.translated and part.rows)
        else:
            continue
        # The window shows a choice's help whole: the game's own rows, such
        # as a page number, and every part around them.
        together = block.rows if block.kind == blocks.HELP else None
        for part in parts:
            runs = [part.rows]
            if block.kind == blocks.HELP and part.on_head:
                # Assistant-led writes the comment's rows one by one: the
                # game's own keep their row, and the text around them is
                # fitted on its own. Translation records the rows it owns.
                kept = blocks.kept(commands, part)
                runs = [
                    tuple(rows)
                    for own, rows in groupby(part.rows, lambda at: at in kept)
                    if not own
                ]
            original = blocks.source(commands, part)
            source = original if len(runs) == 1 else None
            for rows in runs:
                first = rows[0]
                params = commands[first]["parameters"]
                shown = box
                if block.kind == blocks.MESSAGE and _MARKER.match(params[0]):
                    shown = replace(box, width=MARKED_WIDTH, area=None)
                run = tuple(commands[at]["parameters"] for at in rows)
                slots.append((first, _Slot(
                    f"{pointer}/{first}/parameters/0", shown, source, params, 0, run,
                    commands, rows if block.kind == blocks.HELP else (), together,
                    original,
                )))
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        code = blocks.code(command)
        params = command.get("parameters")
        if not isinstance(params, list) or not params:
            continue
        at = f"{pointer}/{index}/parameters"
        if (
            code == 122
            and len(params) > 4
            and isinstance(params[4], str)
            # Only text translation wrote: a script of the game's own is code.
            and _original(command) is not None
            and _script_string(params[4]) is not None
        ):
            slots.append((index, _Slot(
                f"{at}/4", variable_box(layout), None, params, 4,
                original=_original(command),
            )))
        elif code == 324 and len(params) > 1 and isinstance(params[1], str):
            slots.append((index, _Slot(
                f"{at}/1", nickname_box(layout), None, params, 1,
                original=_original(command),
            )))
        elif code == 325 and len(params) > 1 and isinstance(params[1], str):
            source = _original(command)
            slots.append((index, _Slot(
                f"{at}/1",
                help_box(layout, source or params[1], dialogue=True),
                source,
                params,
                1,
            )))
        elif code == 357 and len(params) > 3 and isinstance(params[3], dict):
            for key in MESSAGE_PLUGIN_TEXT.get(params[0], ()):
                if isinstance(params[3].get(key), str):
                    slots.append((index, _Slot(
                        f"{at}/3/{key}", message_box(layout), None, params[3], key
                    )))
    slots.sort(key=lambda item: item[0])
    for _index, slot in slots:
        yield slot


def _fitted_slots(document, file_name: str, layout: Layout, areas):
    """The translated values in *document* DazedTL fits, limited to boxes
    measured by the Line widths entries in *areas* when given."""
    for slot in _slots(document, file_name, layout):
        value = slot.read()
        if not isinstance(value, str):
            continue
        # A message keeps untranslated rows as they are (see wrap_message),
        # and a note its untranslated tags (see wrap_note).
        if slot.box.kind != "note" and (
            all(
                untranslated(row, slot.against, slot.box.target)
                for row in value.split("\n")
                if row.strip()
            )
            if slot.box.kind in ("message", "scroll")
            else untranslated(value, slot.against, slot.box.target)
        ):
            continue
        if areas is not None and slot.box.area not in areas:
            continue
        yield slot, value


def fit_document(
    document,
    file_name: str,
    layout: Layout,
    *,
    areas: set[str] | None = None,
    resized: bool = False,
) -> FitReport:
    """Fit *document* in place: each translated value that does not fit its
    box is wrapped again, as translation wraps it. *areas* limits fitting to
    boxes measured by those Line widths entries, such as the ones a change of
    widths moved, and *resized* says the text was fitted to other widths, so
    a message the fitter laid out narrower is laid out again (see
    :func:`fit_value`). Japanese left untranslated is never rewrapped. A
    message keeps its commands (see :func:`fit_run`)."""
    report = FitReport()
    fitted = list(_fitted_slots(document, file_name, layout, areas))
    # Text a window shows together is checked once, at its first value.
    checks: dict[tuple[int, ...], _Slot] = {}
    for slot, _value in fitted:
        if slot.together is not None:
            checks.setdefault(slot.together, slot)
    # Last first: writing help moves the rows after it (see _Slot).
    for slot, value in reversed(fitted):
        texts = slot.fitted(resized)
        written = "\n".join(texts)
        if written != value:
            slot.write(texts)
            written = slot.written(texts)
            report.changes.append(
                {"file": file_name, "pointer": slot.pointer, "before": value, "after": written}
            )
        if slot.together is None:
            reasons = [misfit(written, slot.box, slot.against)]
        else:
            # Each part's lines are measured where they are written, and the
            # window's rows once every part is: it shows them all, the game's
            # own rows too. Spare rows moved to the end show nothing.
            reasons = [misfit(written, replace(slot.box, rows=None), slot.against)]
            if checks[slot.together] is slot:
                reasons.append(
                    rows_misfit(
                        blocks.shown(slot.commands, slot.together),
                        slot.box,
                        slot.against,
                    )
                )
        for reason in filter(None, reasons):
            report.misfits.append({"file": file_name, "pointer": slot.pointer, "reason": reason})
    report.changes.reverse()
    report.misfits.reverse()
    return report


def drawn_characters(document, file_name: str) -> Counter[str]:
    """How often each character the windows draw appears in the display
    values of *document* DazedTL fits, Japanese or translated (see
    :func:`drawn_text`); note tags, which plugins read, are left out."""
    counts: Counter[str] = Counter()
    for slot in _slots(document, file_name, Layout.from_widths(None)):
        value = slot.read()
        if slot.box.kind != "note" and isinstance(value, str):
            for line in _rendered_lines(value):
                counts.update(drawn_text(line))
    return counts


def _pointer_part(value) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")
