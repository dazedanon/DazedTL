"""Fit RPG Maker MV/MZ/Ace text to the game's windows.

Translation wraps the text it writes with these functions, and every later
write of translated text (Apply, QA corrections, new Line widths) fits again
the lines that no longer fit, so the game's text is measured and wrapped one
way throughout. Line widths count characters; on-screen checks, such as QA's
captures and the playtest, confirm what a count cannot see.

Only known display fields are touched, and ``_original`` never is.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterator

from util import dazedwrap
from util.game_settings import MESSAGE_ROWS_KEY, normalize_wrap_widths


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
    variables take their room. A full-width character, and one East Asian
    fonts draw full width such as ♥ or …, takes two: RPG Maker games draw
    text in Japanese fonts."""
    text = _MARKER.sub("", _ALIGNMENT.sub("", _NAME_WINDOW.sub("", text)))
    for pattern, size in _EXPANDING.items():
        text = pattern.sub("x" * size, text)
    drawn = dazedwrap.visible_text(text)
    return len(drawn) + sum(
        1 for character in drawn if unicodedata.east_asian_width(character) in "FWA"
    )


def _rendered_lines(text: str) -> list[str]:
    """The lines *text* draws: stored ``\\n`` escapes and ``<br>`` break lines
    as newlines do."""
    rendered = str(text).replace("\r\n", "\n").replace("<br>", "\n")
    return re.sub(r"\\n(?![\[<])", "\n", rendered).split("\n")


def widest_line(text: str) -> int:
    """The visible width of *text*'s widest line."""
    return max(visible_width(line) for line in _rendered_lines(text))


def over_width(text: str, width: int) -> bool:
    return widest_line(text) > int(width)


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
    line, such as centring, are repeated on each new line."""
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
    per_line = ""
    if all(_PER_LINE.match(line) for line in lines if line.strip()):
        per_line = _PER_LINE.match(next(line for line in lines if line.strip())).group(0)
        body = "\n".join(_PER_LINE.sub("", line) for line in lines)
    wrapped = dazedwrap.wrapShaped(
        body,
        int(width),
        _source_body(source),
        rows,
        measure=visible_width,
    )
    if per_line:
        wrapped = "\n".join(
            per_line + line if line.strip() else line for line in wrapped.split("\n")
        )
    if uses_br:
        wrapped = wrapped.replace("\n", "<br>")
    return prefix + wrapped


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
    """A database note with each known prose tag body wider than *width*
    fitted to it; the rest of the note stays exact."""
    return _replace_spans(
        note,
        [
            (start, end, _fit_note_body(body, width, structured))
            for start, end, body, structured in _note_bodies(note)
            if over_width(body, width)
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


def wrap_backtick(value: str, width: int) -> str:
    """A text variable's script value (122), `text` with ``\\n`` escapes as
    its line breaks, wrapped to *width*; name codes such as ``\\n[1]`` stay."""
    first, last = value.find("`"), value.rfind("`")
    if first < 0 or last <= first:
        return value
    body = re.sub(r"\\n(?![\[<])", " ", value[first + 1 : last])
    wrapped = wrap_text(body, width).replace("\n", r"\n")
    return value[: first + 1] + wrapped + value[last:]


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
    kind: str  # "message", "lines", "note" or "variable"
    area: str | None = None


def message_box(layout: Layout, *, face: bool = False) -> Box:
    if face:
        return Box(layout.face_width, layout.message_rows, True, "message", "faceWidth")
    return Box(layout.width, layout.message_rows, True, "message", "width")


def scrolling_box(layout: Layout) -> Box:
    return Box(layout.width, None, False, "message", "width")


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
    if not over_width(text, box.width):
        return text
    if box.kind == "variable":
        return wrap_backtick(text, box.width)
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
        bodies = [body for _start, _end, body, _structured in _note_bodies(text)]
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


@dataclass(frozen=True)
class _Slot:
    """One display value in a document: where it is, its box, its source and
    how to read and write it."""

    pointer: str
    box: Box
    source: str | None
    owner: Any
    key: Any

    def read(self):
        return self.owner[self.key]

    def write(self, value) -> None:
        self.owner[self.key] = value


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


def _command_slots(commands: list, pointer: str, layout: Layout) -> Iterator[_Slot]:
    face = False
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
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
        if code == 401 and isinstance(params[0], str):
            # Each 401 is wrapped on its own, as translation joins and wraps
            # the lines of a message up to a command it keeps separate.
            box = message_box(layout, face=face)
            if _MARKER.match(params[0]):
                box = Box(MARKED_WIDTH, box.rows, True, "message")
            yield _Slot(f"{at}/0", box, _original(command), params, 0)
        elif code == 405 and isinstance(params[0], str):
            yield _Slot(f"{at}/0", scrolling_box(layout), _original(command), params, 0)
        elif code == 122 and len(params) > 4 and isinstance(params[4], str) and "`" in params[4]:
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


# Japanese the translation left as it is, which is never rewrapped.
_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def untranslated(text: str) -> bool:
    """Whether *text* still holds Japanese, which DazedTL never rewraps."""
    return bool(_JAPANESE.search(text))


def _fitted_slots(document, file_name: str, layout: Layout, areas):
    """The translated values in *document* DazedTL fits, limited to boxes
    measured by the Line widths entries in *areas* when given."""
    for slot in _slots(document, file_name, layout):
        value = slot.read()
        if not isinstance(value, str) or untranslated(value):
            continue
        if areas is not None and slot.box.area not in areas:
            continue
        yield slot, value


def needs_fit(
    document, file_name: str, layout: Layout, *, areas: set[str] | None = None
) -> bool:
    """Whether any translated value in *document* does not fit its box."""
    return any(
        fit_value(value, slot.box, source=slot.source) != value
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
    widths moved. Japanese left untranslated is never rewrapped. Scrolling
    text (405) that wraps onto more lines is split into commands of its own,
    as translation writes it."""
    report = FitReport()
    scrolling = False
    for slot, value in list(_fitted_slots(document, file_name, layout, areas)):
        fitted = fit_value(value, slot.box, source=slot.source)
        if fitted != value:
            report.changes.append(
                {"file": file_name, "pointer": slot.pointer, "before": value, "after": fitted}
            )
            scrolling |= slot.box.kind == "message" and slot.box.rows is None
            slot.write(fitted)
        reason = misfit(fitted, slot.box)
        if reason:
            report.misfits.append({"file": file_name, "pointer": slot.pointer, "reason": reason})
    if scrolling:
        _split_scrolling(document)
    return report


def _split_scrolling(document) -> None:
    """Scrolling text keeps one line per 405 command, as translation writes it."""
    for commands, _pointer in _command_lists(document):
        index = 0
        while index < len(commands):
            command = commands[index]
            if (
                isinstance(command, dict)
                and command.get("code") == 405
                and isinstance((command.get("parameters") or [None])[0], str)
                and "\n" in command["parameters"][0]
            ):
                lines = command["parameters"][0].split("\n")
                command["parameters"][0] = lines[0]
                for offset, line in enumerate(lines[1:], start=1):
                    added = copy.deepcopy(command)
                    added.pop("_original", None)
                    added["parameters"] = [line]
                    commands.insert(index + offset, added)
                index += len(lines)
            else:
                index += 1


def _pointer_part(value) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")
