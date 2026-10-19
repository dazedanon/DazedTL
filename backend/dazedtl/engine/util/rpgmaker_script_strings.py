"""The text inside the script strings RPG Maker evaluates.

A translated text variable (code 122) keeps its text in a script operand:
MV/MZ evaluate a JavaScript template literal, VX Ace a Ruby double-quoted
string. Translation writes the operand with these escapes, and QA writes its
corrections with them, so neither can end the string early, interpolate in it
or lose a message code's backslash.

The text is the string's inside as the script holds it: ``\\\\`` stands for
one backslash and ``\\n`` for a line break, except in the ``\\n[1]`` and
``\\n<name>`` name codes.
"""

from __future__ import annotations

import re

# A line break in a string's text: "\n", except where it starts a \n[1] actor
# name or \n<name> name window code, as rpgmaker_rewrap reads it.
BREAK = re.compile(r"\\n(?![\[<])")
# A lone backslash before a letter, digit or underscore, such as a translated
# \C[2], which the script would read as an escape of its own.
_LONE_BACKSLASH = re.compile(r"(?<![\\])([\\]{1})(?=\w)")
# What would end MV/MZ's template literal early or interpolate in it: a
# backtick, "${" and a backslash ending the text. An escape the text already
# has, such as \\ or \`, stays as it is.
_TEMPLATE_SPECIAL = re.compile(r"(\\.)|\\|`|\$\{", re.S)
# In a Ruby string's text a backslash escapes the next character; a lone one
# before anything else, such as a translated \C[2], stands for itself.
_RUBY_ESCAPE = re.compile(r'\\(n(?![\[<])|[\\"#])?')
# What a Ruby double-quoted string escapes: a backslash, its delimiter, a line
# break and a "#" that would start interpolation.
_RUBY_SPECIAL = re.compile(r'[\\"\n]|#(?=[{$@])')


def keep_backslashes(text: str) -> str:
    """*text* with each lone backslash before a letter, digit or underscore
    doubled, so the value keeps it."""
    return _LONE_BACKSLASH.sub(r"\\\\", text)


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


def escape(text: str, quote: str) -> str:
    """*text*, a string's inside, as translation writes it between *quote*
    marks, keeping its line breaks: MV/MZ's template literal between
    backticks, VX Ace's Ruby string between double quotes, whose escapes
    JavaScript reads alike."""
    if quote == "`":
        return template_text(keep_backslashes(BREAK.sub("\n", text)))
    if quote == '"':
        return ruby_text(ruby_value(text, "\n"))
    raise ValueError(f"Translation writes no script string between {quote} marks")
