"""The text inside the script strings RPG Maker evaluates.

A translated text variable (code 122) keeps its text in a script operand:
MV/MZ evaluate a JavaScript template literal, VX Ace a Ruby double-quoted
string. Translation writes the operand with these escapes, and QA writes its
corrections with them, so neither can end the string early, interpolate in it
or lose a message code's backslash. An interpolation the game's own text
has, such as ``${$gameActors.actor(1).name()}``, keeps running.

The text is the string's inside as the script holds it: ``\\\\`` stands for
one backslash and ``\\n`` for a line break, except in the ``\\n[1]`` actor
name code and in name window codes such as ``\\n<name>`` or ``\\nc<name>``.
"""

from __future__ import annotations

import re

# What follows "\n" where it starts a \n[1] actor name or a name window code
# (\n<name>, \nc<name>, \nl<name>, \nr<name>), as rpgmaker_rewrap reads them.
NAME_CODE = r"\[|[a-zA-Z]?<"
# A line break in a string's text: "\n", except where it starts a name code,
# so no text is written with a break right before one (see
# rpgmaker_rewrap.wrap_script).
BREAK = re.compile(rf"\\n(?!{NAME_CODE})")
# A lone backslash before a letter, digit or underscore, such as a translated
# \C[2], which the script would read as an escape of its own.
_LONE_BACKSLASH = re.compile(r"(?<![\\])([\\]{1})(?=\w)")
# What would end MV/MZ's template literal early or interpolate in it: a
# backtick, "${" and a backslash ending the text. An escape the text already
# has, such as \\ or \`, stays as it is.
_TEMPLATE_SPECIAL = re.compile(r"(\\.)|\\|`|\$\{", re.S)
# In a Ruby string's text a backslash escapes the next character; a lone one
# before anything else, such as a translated \C[2], stands for itself.
_RUBY_ESCAPE = re.compile(rf'\\(n(?!{NAME_CODE})|[\\"#])?')
# What a Ruby double-quoted string escapes: a backslash, its delimiter, a line
# break and a "#" that would start interpolation.
_RUBY_SPECIAL = re.compile(r'[\\"\n]|#(?=[{$@])')
# What starts an interpolation in each kind of string, by its quote mark.
OPENERS = {"`": "${", '"': "#{"}
# A Ruby string also interpolates a global, instance or class variable
# written right after "#", such as #$gold.
_RUBY_VARIABLE = re.compile(r"#(?:\$|@@?)[A-Za-z_]\w*")
# An interpolation held as one character while the text around it is
# changed: a character of Unicode's private use area, which no game text
# needs.
HELD = re.compile("[\ue000-\uf8ff]")
_HELD_LIMIT = 0xF8FF - 0xE000


def keep_backslashes(text: str) -> str:
    """*text* with each lone backslash before a letter, digit or underscore
    doubled, so the value keeps it."""
    return _LONE_BACKSLASH.sub(r"\\\\", text)


def interpolations(text: str, quote: str) -> list[tuple[int, int]]:
    """Where *text*, a string's inside between *quote* marks, interpolates:
    from each ``${`` (``#{`` in Ruby) to its closing brace, and a Ruby
    variable such as ``#$gold``. An escaped opener, such as ``\\${``, is
    text."""
    opener = OPENERS[quote]
    spans, index = [], 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith(opener, index):
            depth, end = 0, index + len(opener) - 1
            while end < len(text):
                if text[end] == "\\":
                    end += 1
                elif text[end] == "{":
                    depth += 1
                elif text[end] == "}":
                    depth -= 1
                    if not depth:
                        break
                end += 1
            spans.append((index, min(end + 1, len(text))))
            index = end + 1
        elif quote == '"' and (variable := _RUBY_VARIABLE.match(text, index)):
            spans.append(variable.span())
            index = variable.end()
        else:
            index += 1
    return spans


def interpolated(quote: str, *texts: str) -> frozenset[str]:
    """The interpolations *texts*, strings' insides between *quote* marks,
    run: the game's own, which its translation keeps running."""
    return frozenset(
        text[start:end]
        for text in texts
        if text
        for start, end in interpolations(text, quote)
    )


def hold(
    text: str, quote: str, own: frozenset[str] | None = None
) -> tuple[str, list[str]]:
    """*text* with each interpolation held as one private-use character
    (see :data:`HELD`), and the interpolations held: every one, or only
    those in *own*. Text that already has such a character holds none."""
    spans = [
        (start, end)
        for start, end in interpolations(text, quote)
        if own is None or text[start:end] in own
    ]
    if HELD.search(text) or len(spans) > _HELD_LIMIT:
        return text, []
    kept = [text[start:end] for start, end in spans]
    for number, (start, end) in reversed(list(enumerate(spans))):
        text = text[:start] + chr(0xE000 + number) + text[end:]
    return text, kept


def release(text: str, kept: list[str]) -> str:
    """*text* with the interpolations :func:`hold` held put back."""
    if not kept:
        return text
    return HELD.sub(lambda mark: kept[ord(mark.group(0)) - 0xE000], text)


def template_text(text: str) -> str:
    """*text* as the inside of a JavaScript template literal: its line breaks
    as ``\\n``, and a backtick, ``${`` and a trailing backslash escaped."""
    text = text.replace("\n", "\\n")
    return _TEMPLATE_SPECIAL.sub(lambda match: match[1] or "\\" + match[0], text)


def ruby_value(text: str, line_break: str) -> str:
    """The value a Ruby string's text stands for, with *line_break* for each
    ``\\n`` break."""
    return _RUBY_ESCAPE.sub(
        lambda match: line_break if match[1] == "n" else match[1] or "\\", text
    )


def ruby_text(value: str) -> str:
    """*value* as the inside of a Ruby double-quoted string."""
    return _RUBY_SPECIAL.sub(
        lambda match: "\\n" if match[0] == "\n" else "\\" + match[0], value
    )


def escape(text: str, quote: str, own: frozenset[str] = frozenset()) -> str:
    """*text*, a string's inside, as translation writes it between *quote*
    marks, keeping its line breaks: MV/MZ's template literal between
    backticks, VX Ace's Ruby string between double quotes, whose escapes
    JavaScript reads alike. An interpolation in *own*, the game's own, keeps
    running; any other is text."""
    if quote not in OPENERS:
        raise ValueError(f"Translation writes no script string between {quote} marks")
    held, kept = hold(text, quote, own)
    if quote == "`":
        written = template_text(keep_backslashes(BREAK.sub("\n", held)))
    else:
        written = ruby_text(ruby_value(held, "\n"))
    return release(written, kept)
