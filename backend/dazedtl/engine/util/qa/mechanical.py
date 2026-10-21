"""Text QA's mechanical rule: the flags, runtime codes and visible numbers a
line's text gives before any reviewer reads it.

The inventory builder (util/rpgmaker_qa_manifest.py) records this evidence,
its verifier (util/rpgmaker_qa_verify.py) recomputes it, and QA's checks read
it again, all from this one definition. They call it as mechanical.evidence,
so a test that stands in for a changed rule patches it here once.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from util import rpgmaker_blocks as blocks
from util.source_text import holds_source

_RUNTIME_TOKEN_RE = re.compile(
    r"\\(?:[A-Za-z]+\[[^\]\r\n]*\]|[{}.!|^><])"
    # A name window code such as \n<Alice> or \nc<Alice>, counted without its
    # name, which translation changes.
    r"|\\n[A-Za-z]?<(?=[^<>\r\n]*>)"
    r"|__PROTECTED_\d+__"
    r"|%(?:\d+\$)?[-+#0]*(?:\d+|\*)?(?:\.\d+)?[A-Za-z]"
    # RPG Maker's numbered placeholders, as in "%1 uses %2!".
    r"|%\d+"
)
_UNSAFE_BARE_CENTER_RE = re.compile(
    r"\\(?:ac|cl)(?=[A-Za-z])", re.IGNORECASE
)
_CENTER_ALIGNMENT_RE = re.compile(r"\\ac", re.IGNORECASE)
# A stat or currency abbreviation beside a number is its unit, which English
# may move ("TP24増加" is "Increases TP by 24"); other letters beside digits
# make an identifier such as EV024, which shows no number.
_NUMBER_UNIT = r"(?:[HMST]P|EXP|ATK|DEF|MAT|MDF|AGI|LUK|L[Vv]|G)"
_VISIBLE_NUMBER_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{_NUMBER_UNIT}(?=\d))?([-+]?\d+(?:[.,]\d+)?)"
    rf"{_NUMBER_UNIT}?(?![A-Za-z0-9_])"
)
_CARDINALS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty",
)
_ORDINALS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
    "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
    "nineteenth", "twentieth",
)
_NUMBER_WORDS = {
    **{word: str(value) for value, word in enumerate(_CARDINALS, start=1)},
    **{word: str(value) for value, word in enumerate(_ORDINALS, start=1)},
    **{
        word: str(value)
        for word, value in (
            ("thirty", 30), ("forty", 40), ("fifty", 50), ("sixty", 60),
            ("seventy", 70), ("eighty", 80), ("ninety", 90), ("hundred", 100),
            ("thousand", 1000),
        )
    },
}
# English number words and ordinals stand for a source number (第1層 as "First
# Stratum", 3体 as "three"), so they may match one; an unmatched one ("wait a
# second", "this one") is prose.
_ORDINAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:(\d+)(?:st|nd|rd|th)|("
    + "|".join(_NUMBER_WORDS)
    + r"))(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})+$")


def _number(text: str) -> str:
    """A visible number as written, without a plus sign or thousands commas."""
    text = text.lstrip("+")
    return text.replace(",", "") if _THOUSANDS_RE.match(text) else text


def _numbers_match(source_numbers: list[str], live: str) -> bool:
    """Whether the live text shows the source's numbers in order.

    Every plain number in the live text must match the next source number;
    an ordinal may match one or be skipped.
    """
    tokens = [
        (match.start(1), _number(match.group(1)), False)
        for match in _VISIBLE_NUMBER_RE.finditer(live)
    ]
    for match in _ORDINAL_RE.finditer(live):
        digits, word = match.groups()
        value = digits or _NUMBER_WORDS[word.casefold()]
        tokens.append((match.start(), value, True))
    tokens.sort()
    # matched[j]: the first j source numbers are matched by the tokens so far.
    matched = [True] + [False] * len(source_numbers)
    for _start, value, optional in tokens:
        following = [False] * len(matched)
        for count, reachable in enumerate(matched):
            if not reachable:
                continue
            if optional:
                following[count] = True
            if count < len(source_numbers) and source_numbers[count] == value:
                following[count + 1] = True
        matched = following
    return matched[-1]


def row_codes(text: str):
    """*text*'s runtime codes counted per row (see rpgmaker_blocks.row_codes)."""
    return blocks.row_codes(text, _RUNTIME_TOKEN_RE)


def _runtime_tokens_match(source: str, live: str) -> bool:
    """Whether *live* keeps *source*'s runtime codes. A row wrapping adds may
    repeat the codes its row starts with; any other change still counts."""
    if Counter(_RUNTIME_TOKEN_RE.findall(source)) == Counter(
        _RUNTIME_TOKEN_RE.findall(live)
    ):
        return True
    return row_codes(source) == row_codes(live)


def evidence(source: str, live: str, code: int | None) -> dict[str, Any]:
    """The flags, runtime codes and visible numbers of a line's source and
    live text."""
    source_tokens = _RUNTIME_TOKEN_RE.findall(source)
    live_tokens = _RUNTIME_TOKEN_RE.findall(live)
    source_visible = unicodedata.normalize(
        "NFKC", _RUNTIME_TOKEN_RE.sub(" ", source)
    )
    live_visible = unicodedata.normalize(
        "NFKC", _RUNTIME_TOKEN_RE.sub(" ", live)
    )
    source_numbers = [_number(n) for n in _VISIBLE_NUMBER_RE.findall(source_visible)]
    live_numbers = [_number(n) for n in _VISIBLE_NUMBER_RE.findall(live_visible)]
    flags = []
    if not live.strip():
        flags.append("empty-live")
    if source == live:
        flags.append("unchanged-source")
    if holds_source(live):
        flags.append("source-language-residue")
    if not _runtime_tokens_match(source, live):
        flags.append("runtime-token-mismatch")
    live_lines = [line for line in live.splitlines() if line.strip()]
    safe_centered_live = bool(live_lines) and all(
        re.match(r"^\s*\\ac(?=[^A-Za-z]|$)", line, re.IGNORECASE)
        for line in live_lines
    )
    if code == 401 and _CENTER_ALIGNMENT_RE.search(source) and not safe_centered_live:
        flags.append("missing-center-alignment")
    if _UNSAFE_BARE_CENTER_RE.search(live):
        flags.append("unsafe-bare-center-code")
    if source_numbers != live_numbers and not _numbers_match(
        source_numbers, live_visible
    ):
        flags.append("visible-number-mismatch")
    if len(source) >= 8 and len(live) >= 1:
        ratio = len(live) / len(source)
        if ratio < 0.35 or ratio > 3.0:
            flags.append("suspicious-length-ratio")
    return {
        "flags": flags,
        "source_runtime_tokens": source_tokens,
        "live_runtime_tokens": live_tokens,
        "source_visible_numbers": source_numbers,
        "live_visible_numbers": live_numbers,
    }
