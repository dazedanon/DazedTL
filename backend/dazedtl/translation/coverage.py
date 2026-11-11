"""Proves a runtime hook shows English for every exported line: DazedTL writes
each line as the game shows it, every placeholder the game fills filled with
a value no line holds, the game's own self-test looks each one up through the
hook's store and gate, and its answers decide whether the patch packages.

A whole-string key a game fills before showing it, as Labyrinth City Asylum
filled `報酬{0}ゴールドをもらった。` with string.Format, misses once filled
while its unfilled lookup hits; the filled probe is what tells them apart.
"""

import re
import unicodedata
from itertools import count

from util.languages import UNTRANSLATED_TEXT

# A .NET composite format item, {index[,alignment][:format]}, which the code
# fills before the text reaches the screen; doubled braces are literal ones.
FORMAT_ITEM = re.compile(r"(?<!\{)\{(\d+)(?:,(-?\d+))?(?::([^{}]*))?\}(?!\})")
# Markup a text component reads as it is, never a value the code fills in:
# a rich-text tag such as <color=red> and a backslash code such as \C[2].
MARKUP = re.compile(r"<[^<>]+>|\\.*", re.DOTALL)
UNTRANSLATED = re.compile(UNTRANSLATED_TEXT)
# The fewest digits a filled value has, which keeps every value from holding
# another and leaves a thousands separator out of most formats.
FIRST_VALUE = 101


def probes(units):
    """One probe per unit, by unit ID: its speaker, the text the game shows
    (`text`), each placeholder filled, and the values the English must hold
    (`values`). *units* are the export's rows, each with its `id`, `source`,
    `speaker`, optional `translation` and protected `tokens`. A placeholder is
    a format item of the source, or a token that is no markup; repeated, it
    takes the same value, and no unit's source or translation holds one."""
    units = list(units)
    # A value is digits, so only a run of digits can hold one; full-width
    # digits read as the ASCII ones they show.
    runs = [
        run
        for unit in units
        for key in ("source", "translation")
        if isinstance(unit.get(key), str)
        for run in DIGITS.findall(unicodedata.normalize("NFKC", unit[key]))
    ]
    free = _Free(runs)
    return {
        unit["id"]: {"speaker": unit.get("speaker"), **_filled(unit, free)}
        for unit in units
    }


DIGITS = re.compile(r"\d+", re.ASCII)


class _Free:
    """The values no run of digits in *runs* holds, from FIRST_VALUE up,
    found as a probe first needs them."""

    def __init__(self, runs):
        self.runs = runs
        self.values = []
        self.candidates = map(str, count(FIRST_VALUE))

    def __getitem__(self, index):
        while len(self.values) <= index:
            value = next(self.candidates)
            if not any(value in run for run in self.runs if len(run) >= len(value)):
                self.values.append(value)
        return self.values[index]


def _filled(unit, free):
    values = {}
    shown = []

    def value(key):
        if key not in values:
            values[key] = free[len(values)]
        return values[key]

    def item(match):
        index, alignment, spec = match.groups()
        text = _formatted(value(("item", index)), spec)
        shown.append(text)
        width = int(alignment or 0)
        return text.rjust(width) if width > 0 else text.ljust(-width)

    text = FORMAT_ITEM.sub(item, unit["source"])
    for token in dict.fromkeys(unit.get("tokens") or ()):
        if FORMAT_ITEM.fullmatch(token) or MARKUP.fullmatch(token) or token not in text:
            continue
        shown.append(value(("token", token)))
        text = text.replace(token, shown[-1])
    return {"text": text, "values": list(dict.fromkeys(shown))}


def _formatted(value, spec):
    """*value*, a whole number's digits, as .NET shows it by a standard
    numeric format *spec* (D, F, N or X, with an optional precision); any
    other spec shows the digits as they are."""
    kind, digits = (spec[0].upper(), spec[1:]) if spec else ("", "")
    if not digits.isdigit() and digits:
        return value
    number = int(value)
    if kind == "D":
        return value.zfill(int(digits or 0))
    if kind == "F":
        return f"{number:.{int(digits or 2)}f}"
    if kind == "N":
        return f"{number:,.{int(digits or 2)}f}"
    if kind == "X":
        return format(number, spec[0]).zfill(int(digits or 0))
    return value


def problem(probe, shown):
    """Why the game's answer *shown* for *probe* is no clean English, in the
    assistant's terms, or None: no English (a miss), a carriage return, text
    still untranslated by the skill's class, or a filled value it drops."""
    if shown is None:
        return "the game finds no English for it"
    if "\r" in shown:
        return "its English holds a carriage return"
    if marks := UNTRANSLATED.findall(shown):
        return "its English still shows " + "".join(dict.fromkeys(marks))
    if lost := [value for value in probe["values"] if value not in shown]:
        return "its English drops the value the game fills in (" + ", ".join(lost) + ")"
    return None
