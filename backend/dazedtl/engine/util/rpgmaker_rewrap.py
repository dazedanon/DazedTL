"""Fit RPG Maker MV/MZ/Ace text to the game's windows.

Translation wraps the text it writes with these functions, and every later
write of translated text (Apply, QA corrections, new Line widths) fits again
the lines that no longer fit, so the game's text is measured and wrapped one
way throughout. Line widths count characters; on-screen checks, such as QA's
captures and the playtest, confirm what a count cannot see.

Only known display fields are touched, and ``_original`` never is.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterator

from util import dazedwrap
from util.game_settings import MESSAGE_ROWS_KEY, normalize_wrap_widths
from util import rpgmaker_script_strings as script_strings
from util.rpgmaker_script_strings import BREAK


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


def visible_width(text: str) -> int:
    """The characters *text* takes on one line of a window: name windows,
    alignment and other codes draw nothing there, while names, icons and
    variables take their room. A full-width character takes two, and so
    does a symbol East Asian fonts draw full width, such as ♥ or …: RPG
    Maker games draw text in Japanese fonts."""
    text = _MARKER.sub("", _ALIGNMENT.sub("", _NAME_WINDOW.sub("", text)))
    for pattern, size in _EXPANDING.items():
        text = pattern.sub("x" * size, text)
    drawn = dazedwrap.visible_text(text)
    return len(drawn) + sum(1 for character in drawn if _full_width(character))


def _full_width(character: str) -> bool:
    """Whether Japanese fonts draw *character* full width: a full-width
    character, or one of ambiguous width other than a letter. MV/MZ's and
    VX Ace's fonts draw ♥, … and ① full width, while accented, Greek and
    Cyrillic letters, such as é, stay half width."""
    width = unicodedata.east_asian_width(character)
    return width in "FW" or (
        width == "A" and not unicodedata.category(character).startswith("L")
    )


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


# Japanese the translation left as it is, which is never rewrapped: kana and
# kanji. English uses the middle dot and the long vowel mark (\u30fb, \u30fc) as
# bullets and dashes, so they alone do not make text Japanese.
_JAPANESE = re.compile(r"[\u3040-\u30fa\u30fd-\u30ff\u3400-\u9fff]")


def untranslated(text: str) -> bool:
    """Whether *text* still holds Japanese, which DazedTL never rewraps."""
    return bool(_JAPANESE.search(text))


def _translated(text: str) -> str:
    """A message's rows without the ones left in Japanese, which keep their
    rows (see wrap_message)."""
    return "\n".join(row for row in _rendered_lines(text) if not untranslated(row))


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

# Codes translation repeats on every line of a message: centring, instant
# lines and an indent.
_PER_LINE = re.compile(r"^(?:\\+a[clr](?![A-Za-z])|\\+>|\\+px\[\d+\])+ ?", re.IGNORECASE)
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


def _row_kind(row: str):
    """How a row groups (see :func:`_spans`): None when blank, False when it
    is kept as it is, otherwise the code it repeats on each row and whether
    it sets the font size."""
    if not row.strip():
        return None
    if untranslated(row) or _LABEL_ROW.match(row):
        return False
    match = _PER_LINE.match(row)
    return (match.group(0) if match else "", bool(_SIZE_START.match(row)))


def _command_kind(text: str):
    """How a command holding some of a message's rows groups: as its first
    row that flows, or kept as it is when none does."""
    kinds = [_row_kind(row) for row in text.split("\n") if row.strip()]
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
    lines: list[str], per_line: str, width: int, source: str | None, rows: int | None
) -> list[str]:
    """Rows of text wrapped to *width* (see :func:`dazedwrap.wrapShaped`),
    keeping their blank rows before and after, with the code they repeat on
    each row on each new row."""
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
    ).split("\n") + [""] * (len(lines) - last - 1)
    if per_line:
        return [_repeated(per_line, line) if line.strip() else line for line in wrapped]
    return wrapped


def _repeated(code: str, line: str) -> str:
    """*line* after the code its message repeats on each row. RPG Maker reads
    every letter after an escape as part of it, so a letter after a code such
    as ``\\ac`` takes a space between (``\\acWhat`` hides "What")."""
    if line[:1].isascii() and line[:1].isalpha() and re.search(r"\\[A-Za-z]+$", code):
        return code + " " + line
    return code + line


def wrap_message(
    text: str,
    width: int,
    *,
    source: str | None = None,
    rows: int | None = None,
) -> str:
    """A message laid out for its window: the body wrapped to *width* like
    its Japanese *source* (see :func:`dazedwrap.wrapShaped`), paging after a
    sentence where it needs more than *rows*. A speaker line stays first,
    ``<br>`` breaks stay ``<br>``, and codes translation repeats on each
    line, such as centring, are repeated on each new line. Blank rows at the
    end go: a message spread over several commands gets them back from
    :func:`spread`.

    Rows that keep a layout of their own (see :func:`_spans`) split the
    message: then each part wraps on its own, only where a row is wider
    than *width*, and without the source's layout, which no longer lines up
    with the rows."""
    if not text or not text.strip():
        return text
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
    spans = _spans([_row_kind(line) for line in lines])
    if len(spans) == 1 and spans[0].flows:
        wrapped = _flow(lines, spans[0].per_line, width, _source_body(source), rows)
    else:
        wrapped = []
        for span in spans:
            part = lines[span.start : span.end]
            if span.flows and any(visible_width(row) > width for row in part):
                wrapped += _flow(part, span.per_line, width, None, rows)
            else:
                wrapped += part
    result = "\n".join(wrapped)
    if uses_br:
        result = result.replace("\n", "<br>")
    return prefix + result


def wrap_text(text: str, width: int) -> str:
    """Text with no source layout to follow, such as a script's message,
    wrapped to *width* in even lines."""
    return dazedwrap.wrapShaped(text, int(width), measure=visible_width)


def help_rows(source: str | None) -> int:
    """The rows a help or status window shows: two, or as many as the
    source spends there."""
    return max(HELP_ROWS, str(source or "").count("\n") + 1)


def wrap_lines(
    text: str,
    width: int,
    rows: int | None = None,
) -> str:
    """Database text, whose line breaks are authored, fitted as the database
    pass fits it (see :func:`dazedwrap.wrapLines`): ``\\n`` breaks, or
    ``<br>`` in text without one."""
    if "<br>" in text and "\n" not in text:
        return dazedwrap.wrapLines(
            text.replace("<br>", "\n"), width, rows, measure=visible_width
        ).replace("\n", "<br>")
    return dazedwrap.wrapLines(text, width, rows, measure=visible_width)


def wrap_note(note: str, width: int) -> str:
    """A database note with each translated prose tag body wider than
    *width* fitted to it; the rest of the note, such as other tags or a
    body left in Japanese, stays exact."""
    return _replace_spans(
        note,
        [
            (start, end, _fit_note_body(body, width, structured))
            for start, end, body, structured in _note_bodies(note)
            if not untranslated(body) and over_width(body, width)
        ],
    )


def _fit_note_body(body: str, width: int, structured: bool) -> str:
    if structured:
        return dazedwrap.wrapSGDesc(body, width)
    return wrap_lines(body, width)


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


def wrap_script(text: str, width: int) -> str:
    """A text variable's text with its interpolations held (see
    rpgmaker_script_strings.hold), wrapped to *width* in even lines as
    :func:`wrap_text` wraps text, each interpolation as wide as a
    variable's value, as later fits count it."""
    return dazedwrap.wrapShaped(text, int(width), measure=_script_width)


def _script_text(value: str) -> str | None:
    """The lines a text variable's operand shows, or None (see _held)."""
    held = _held(value)
    return None if held is None else script_strings.HELD.sub("x" * _HELD_WIDTH, held[0])


def wrap_variable(value: str, width: int) -> str:
    """A text variable's operand (122), the text between its quote marks
    with ``\\n`` escapes as its line breaks, wrapped to *width* when a line
    is wider. Its script stays as it runs: an interpolation such as
    ``${...}`` is never broken, and name codes such as ``\\n[1]`` stay."""
    held = _held(value)
    if held is None or max(map(_script_width, held[0].split("\n"))) <= int(width):
        return value
    body, kept, (start, end) = held
    wrapped = dazedwrap.wrapShaped(
        body.replace("\n", " "), int(width), measure=_script_width
    )
    wrapped = script_strings.release(wrapped, kept)
    return value[:start] + wrapped.replace("\n", r"\n") + value[end:]


# --------------------------------------------------------------------- boxes


@dataclass(frozen=True)
class Layout:
    """A game's Line widths."""

    width: int
    face_width: int
    list_width: int
    note_width: int
    message_rows: int

    @classmethod
    def from_widths(cls, widths: dict[str, Any] | None) -> Layout:
        values = normalize_wrap_widths(widths or {})
        return cls(
            values["width"],
            values["faceWidth"],
            values["listWidth"],
            values["noteWidth"],
            values[MESSAGE_ROWS_KEY],
        )


@dataclass(frozen=True)
class Box:
    """The window a value shows in: its line width, the rows it shows, and
    whether text that needs more rows goes on to a new page (a message) or
    is cut off (a window of fixed height). ``rows`` None is unlimited, as in
    scrolling text. ``kind`` names how the value wraps, and ``area`` the Line
    widths entry its width comes from."""

    width: int
    rows: int | None
    paged: bool
    kind: str  # "message", "scroll", "lines", "note" or "variable"
    area: str | None = None


def message_box(layout: Layout, *, face: bool = False) -> Box:
    if face:
        return Box(layout.face_width, layout.message_rows, True, "message", "faceWidth")
    return Box(layout.width, layout.message_rows, True, "message", "width")


def scrolling_box(layout: Layout) -> Box:
    """Scroll Text, whose rows the author lays out, often as a list such as
    credits: a row too wide wraps onto rows of its own."""
    return Box(layout.width, None, False, "scroll", "width")


def help_box(layout: Layout, source: str | None, *, dialogue: bool = False) -> Box:
    """A help or status window: two rows, or as many as the source spends.
    A profile change (325) wraps to the dialogue width, as translation does."""
    if dialogue:
        return Box(layout.width, help_rows(source), False, "lines", "width")
    return Box(layout.list_width, help_rows(source), False, "lines", "listWidth")


def nickname_box(layout: Layout) -> Box:
    return Box(layout.list_width, 1, False, "lines", "listWidth")


def note_box(layout: Layout) -> Box:
    """The plugin windows that draw a note's prose tags. Their heights vary,
    so only their width is known."""
    return Box(layout.note_width, None, False, "note", "noteWidth")


def fit_value(
    text: str,
    box: Box,
    *,
    source: str | None = None,
) -> str:
    """*text* as DazedTL writes it to *box*: unchanged when every line fits,
    otherwise wrapped again as translation wraps it there."""
    if not isinstance(text, str) or not text.strip():
        return text
    if box.kind == "note":
        return wrap_note(text, box.width)
    if box.kind == "variable":
        return wrap_variable(text, box.width)
    rows_apart = box.kind in ("message", "scroll")
    if not over_width(_translated(text) if rows_apart else text, box.width):
        return text
    if box.kind == "scroll":
        return "\n".join(
            row if untranslated(row) else wrap_lines(row, box.width)
            for row in text.split("\n")
        )
    if box.kind == "lines":
        return wrap_lines(text, box.width, box.rows)
    return wrap_message(
        text, box.width, source=source, rows=box.rows if box.paged else None
    )


def misfit(text: str, box: Box) -> str | None:
    """Why *text*, as written, still does not fit *box*, or None."""
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
        bodies = [_translated(text)]
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


# ------------------------------------------------------------ whole documents


@dataclass
class FitReport:
    """What fitting a file changed, and what it could not fit."""

    changes: list[dict[str, Any]] = field(default_factory=list)
    misfits: list[dict[str, Any]] = field(default_factory=list)


def spread(text: str, count: int) -> list[str]:
    """A message's rows laid over the *count* commands that hold it, which
    the game shows one after another: a row each, the rows left over in the
    last command and empty commands when the text has fewer rows. No command
    is added or removed, so a saved game's place in an event stays valid and
    each command keeps its source."""
    rows = text.split("\n")
    rows += [""] * (count - len(rows))
    return rows[: count - 1] + ["\n".join(rows[count - 1 :])]


def fit_run(texts: list[str], box: Box, source: str | None = None) -> list[str]:
    """A message whose rows are stored in several commands, one text per
    command as Assistant-led writes them, fitted to *box* over the same
    commands. Text between commands kept as they are, such as Japanese left
    untranslated (see :func:`_spans`), is laid out as one text over its own
    commands (see :func:`spread`); Scroll Text rows wrap in their own
    command. *source* is the Japanese of the whole message."""
    if box.kind == "scroll" or len(texts) == 1:
        return [
            fit_value(text, box, source=source if len(texts) == 1 else None)
            for text in texts
        ]
    spans = _spans([_command_kind(text) for text in texts])
    fitted = list(texts)
    for span in spans:
        if not span.flows:
            continue
        joined = "\n".join(texts[span.start : span.end])
        text = fit_value(joined, box, source=source if len(spans) == 1 else None)
        if text != joined:
            fitted[span.start : span.end] = spread(text, span.end - span.start)
    return fitted


@dataclass(frozen=True)
class _Slot:
    """One display value in a document: where it is, its box, its source and
    how to read and write it. A message (*run*, the parameters of the
    commands that hold its rows) reads as one text and is fitted over the
    same commands (see :func:`fit_run`)."""

    pointer: str
    box: Box
    source: str | None
    owner: Any
    key: Any
    run: tuple[list, ...] = ()

    def read(self):
        if self.run:
            return "\n".join(parameters[0] for parameters in self.run)
        return self.owner[self.key]

    def fitted(self) -> list[str]:
        """The value fitted to its box: a text for each command of a message,
        otherwise the one text."""
        if self.run:
            return fit_run([parameters[0] for parameters in self.run], self.box, self.source)
        return [fit_value(self.owner[self.key], self.box, source=self.source)]

    def write(self, texts: list[str]) -> None:
        if self.run:
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
                    source = _original(entry, name) or entry[name]
                    yield _Slot(f"/{index}/{name}", help_box(layout, source), source, entry, name)
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
            isinstance(item, dict) and isinstance(item.get("code"), int) for item in commands
        ):
            yield commands, f"{pointer}/list"
        for key, value in node.items():
            if key == "_original" or (key == "list" and commands is value):
                continue
            yield from _command_lists(value, f"{pointer}/{_pointer_part(key)}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _command_lists(value, f"{pointer}/{index}")


def _has_face(command: dict) -> bool:
    params = command.get("parameters") or []
    return len(params) >= 4 and isinstance(params[0], str) and bool(params[0].strip())


def _text_command(command, code: int) -> bool:
    return (
        isinstance(command, dict)
        and command.get("code") == code
        and isinstance(command.get("parameters"), list)
        and bool(command["parameters"])
        and isinstance(command["parameters"][0], str)
    )


def _run_end(commands: list, start: int) -> int:
    """Where the message starting at *start* ends: the Show Text (401) or
    Scroll Text (405) commands after it that carry no source of their own,
    as translation, Len's writer and QA group them."""
    code = commands[start]["code"]
    end = start + 1
    while (
        end < len(commands)
        and _text_command(commands[end], code)
        and "_original" not in commands[end]
    ):
        end += 1
    return end


def _command_slots(commands: list, pointer: str, layout: Layout) -> Iterator[_Slot]:
    face = False
    # The end of the last message, whose commands it fitted.
    end = 0
    for index, command in enumerate(commands):
        if index < end or not isinstance(command, dict):
            continue
        code = command.get("code")
        params = command.get("parameters")
        # A Show Text with a face graphic narrows the lines that follow it.
        if code == 101:
            face = _has_face(command)
        elif code not in (401, 405, 0, -1):
            face = False
        if not isinstance(params, list) or not params:
            continue
        at = f"{pointer}/{index}/parameters"
        if code in (401, 405) and _text_command(command, code):
            # A message is fitted as a whole, even when its rows are stored
            # one command each, as Assistant-led writes them.
            end = _run_end(commands, index)
            run = tuple(item["parameters"] for item in commands[index:end])
            if code == 405:
                box = scrolling_box(layout)
            else:
                box = message_box(layout, face=face)
                if _MARKER.match(params[0]):
                    box = Box(MARKED_WIDTH, box.rows, True, "message")
            yield _Slot(f"{at}/0", box, _original(command), params, 0, run)
        elif (
            code == 122
            and len(params) > 4
            and isinstance(params[4], str)
            # Only text translation wrote: a script of the game's own is code.
            and _original(command) is not None
            and _script_string(params[4]) is not None
        ):
            box = Box(layout.list_width, None, False, "variable", "listWidth")
            yield _Slot(f"{at}/4", box, None, params, 4)
        elif code == 324 and len(params) > 1 and isinstance(params[1], str):
            yield _Slot(f"{at}/1", nickname_box(layout), None, params, 1)
        elif code == 325 and len(params) > 1 and isinstance(params[1], str):
            source = _original(command) or params[1]
            yield _Slot(f"{at}/1", help_box(layout, source, dialogue=True), source, params, 1)
        elif code == 357 and len(params) > 3 and isinstance(params[3], dict):
            for key in MESSAGE_PLUGIN_TEXT.get(params[0], ()):
                if isinstance(params[3].get(key), str):
                    yield _Slot(f"{at}/3/{key}", message_box(layout), None, params[3], key)


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
            all(untranslated(row) for row in value.split("\n") if row.strip())
            if slot.box.kind in ("message", "scroll")
            else untranslated(value)
        ):
            continue
        if areas is not None and slot.box.area not in areas:
            continue
        yield slot, value


def needs_fit(
    document, file_name: str, layout: Layout, *, areas: set[str] | None = None
) -> bool:
    """Whether any translated value in *document* does not fit its box."""
    return any(
        "\n".join(slot.fitted()) != value
        for slot, value in _fitted_slots(document, file_name, layout, areas)
    )


def fit_document(
    document,
    file_name: str,
    layout: Layout,
    *,
    areas: set[str] | None = None,
) -> FitReport:
    """Fit *document* in place: each translated value that does not fit its
    box is wrapped again, as translation wraps it. *areas* limits fitting to
    boxes measured by those Line widths entries, such as the ones a change of
    widths moved. Japanese left untranslated is never rewrapped. A message
    keeps its commands (see :func:`fit_run`)."""
    report = FitReport()
    for slot, value in list(_fitted_slots(document, file_name, layout, areas)):
        texts = slot.fitted()
        written = "\n".join(texts)
        if written != value:
            slot.write(texts)
            report.changes.append(
                {"file": file_name, "pointer": slot.pointer, "before": value, "after": written}
            )
        reason = misfit(written, slot.box)
        if reason:
            report.misfits.append({"file": file_name, "pointer": slot.pointer, "reason": reason})
    return report


def _pointer_part(value) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")
