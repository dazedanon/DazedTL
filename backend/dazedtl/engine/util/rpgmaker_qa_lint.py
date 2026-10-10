"""Deterministic lint for RPG Maker translation QA.

Each family finds one known mechanical defect and fixes it exactly, so the
screen reviewers can spend their attention on meaning and voice. A family's
proposals are reviewed as a group; fixers are idempotent and run in a fixed
order, so the fixes a reviewer accepted also apply on top of a deep correction.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any

FAMILIES: dict[str, dict[str, str]] = {
    "lint:heart-spacing": {
        "category": "formatting",
        "description": "A new sentence starts right after ♥ with no space.",
    },
    "lint:stray-sokuon": {
        "category": "formatting",
        "description": "A stray letter after an ellipsis stands for the small っ.",
    },
    "lint:dakuten-apostrophe": {
        "category": "formatting",
        "description": "An apostrophe left by a dakuten mark splits a real word.",
    },
    "lint:merged-list": {
        "category": "formatting",
        "description": "List items that start separate lines in the source share one line.",
    },
    "lint:quoted-title": {
        "category": "ui",
        "description": "A quoted title no longer matches the title it names.",
    },
    "lint:duplicated-label": {
        "category": "formatting",
        "description": "A bracketed label appears twice where the source has it once.",
    },
    "lint:level-tag-spacing": {
        "category": "formatting",
        "description": "A level tag or bracketed label touches the word or number beside it.",
    },
}
ORDER = tuple(FAMILIES)

_HEART_RE = re.compile(r"♥(?=[A-Za-z(])")
_SOKUON_SOURCE_RE = re.compile(r"[っッ]")
_STRAY_SOKUON_RE = re.compile(r"((?:…|\.\.\.)+)h+(?=[♥)\s!?…]|$)")
_DAKUTEN_SOURCE_RE = re.compile(r"[゛゙”]")
_SPLIT_WORD_RE = re.compile(r"\b([A-Za-z]+)'([A-Za-z]*)")
# Single quotes used as quotation marks: their closing mark follows a word.
_OPENING_QUOTE_RE = re.compile(r"(?:^|[\s(\[\"“])'[A-Za-z]")
# Letters of moans and interjections, which keep the apostrophe ("Oh'").
_INTERJECTION_RE = re.compile(r"[aeiouhnmgy]+", re.IGNORECASE)
_CONTRACTION_PREFIXES = frozenset(
    "i you he she it we they that there here who what where when why how let "
    "can don won isn aren wasn weren didn doesn haven hasn hadn couldn wouldn "
    "shouldn mustn ain".split()
)
_BULLET = "・"
_QUOTED_RE = re.compile(r'"([^"\n]{2,120})"|“([^”\n]{2,120})”')
_TITLE_SOURCE_RE = re.compile(r"[「『]([^」』\n]{2,80})[」』]")
_LEVEL_TAG_RE = re.compile(r"(?<=[a-z])(?=(?:Lv|LV)\.?\s?\d)")
_LABEL_NUMBER_RE = re.compile(r"\](?=\d)")
_SOURCE_LABEL_NUMBER_RE = re.compile(r"[】\]]\d")
_ENGLISH_LABEL_RE = re.compile(r"\[[^\]\n]{1,40}\]")
_SOURCE_LABEL_RE = re.compile(r"【[^】\n]{1,40}】|\[[^\]\n]{1,40}\]")
_DUPLICATED_LABEL_RE = re.compile(r"(\[[^\]\n]{1,40}\])\s*\1")


def _heart_spacing(source: str, text: str, titles: dict) -> str:
    quotes = 0
    out = []
    for index, char in enumerate(text):
        out.append(char)
        if char == '"':
            quotes += 1
        if char != "♥" or index + 1 >= len(text):
            continue
        following = text[index + 1]
        # An opening quote after ♥ starts a sentence; a closing one ends it.
        if _HEART_RE.match(text, index) or (following == '"' and quotes % 2 == 0):
            out.append(" ")
    return "".join(out)


def _stray_sokuon(source: str, text: str, titles: dict) -> str:
    if not _SOKUON_SOURCE_RE.search(source):
        return text
    return _STRAY_SOKUON_RE.sub(r"\1", text)


def _split_word(prefix: str, suffix: str) -> bool:
    """Whether an apostrophe inside or after this word is a dakuten leftover."""
    if _INTERJECTION_RE.fullmatch(prefix + suffix):
        return False
    before, after = prefix.casefold(), suffix.casefold()
    if before in {"y", "o", "ma"} or after == "s":
        return False
    if after == "t":
        return not before.endswith("n")
    if after in {"re", "ve", "ll", "d", "m"}:
        return before not in _CONTRACTION_PREFIXES
    if not after:
        # Dropped g ("goin'") and plural possessives ("girls'") end a word.
        return not (before.endswith("in") or before.endswith("s"))
    return True


def _dakuten_apostrophe(source: str, text: str, titles: dict) -> str:
    if not _DAKUTEN_SOURCE_RE.search(source):
        return text

    quoting = bool(_OPENING_QUOTE_RE.search(text))

    def fix(match: re.Match) -> str:
        prefix, suffix = match.groups()
        if quoting and not suffix:
            return match.group(0)
        return prefix + suffix if _split_word(prefix, suffix) else match.group(0)

    previous = None
    while previous != text:
        previous, text = text, _SPLIT_WORD_RE.sub(fix, text)
    return text


def _merged_list(source: str, text: str, titles: dict) -> str:
    source_items = [
        line for line in source.split("\n") if line.strip(" \u3000").startswith(_BULLET)
    ]
    if len(source_items) < 2 or text.count(_BULLET) != len(source_items):
        return text
    starts = [
        line for line in text.split("\n") if line.strip(" \u3000").startswith(_BULLET)
    ]
    if len(starts) >= len(source_items):
        return text
    first = text.index(_BULLET)
    head = text[:first].rstrip(" \u3000")
    joined = re.sub(r"\s*\n\s*", " ", text[first:])
    items = [part.strip() for part in joined.split(_BULLET) if part.strip()]
    body = "\n".join(_BULLET + item for item in items)
    return (head + "\n" + body) if head else body


def _quoted_title(source: str, text: str, titles: dict) -> str:
    spans = list(_QUOTED_RE.finditer(text))
    if len(spans) != 1:
        return text
    match = spans[0]
    group = 1 if match.group(1) else 2
    # A sentence's closing punctuation may sit inside the quote marks.
    quoted = match.group(group).rstrip(".,!?…")
    end = match.start(group) + len(quoted)
    named = set()
    whole = source.strip(" \u3000")
    for piece in [*source.split("\n"), *_TITLE_SOURCE_RE.findall(source)]:
        key = piece.strip(" \u3000「」『』")
        # The line's own source is not a title it names.
        if key != whole:
            named |= titles.get(key, set())
    if quoted in named:
        return text
    # The source line the quote stands for is the title it resembles.
    similar = {
        title
        for title in named
        if difflib.SequenceMatcher(None, quoted.casefold(), title.casefold()).ratio()
        >= 0.6
    }
    if len(similar) != 1:
        return text
    title = next(iter(similar))
    return text[: match.start(group)] + title + text[end:]


def _duplicated_label(source: str, text: str, titles: dict) -> str:
    if len(_ENGLISH_LABEL_RE.findall(text)) <= len(_SOURCE_LABEL_RE.findall(source)):
        return text
    return _DUPLICATED_LABEL_RE.sub(r"\1", text)


def _level_tag_spacing(source: str, text: str, titles: dict) -> str:
    text = _LEVEL_TAG_RE.sub(" ", text)
    # A label followed by its number, as in 【噂Lv】3, reads "[Rumor Lv.] 3".
    if _SOURCE_LABEL_NUMBER_RE.search(source):
        return _LABEL_NUMBER_RE.sub("] ", text)
    return text


FIXERS = {
    "lint:heart-spacing": _heart_spacing,
    "lint:stray-sokuon": _stray_sokuon,
    "lint:dakuten-apostrophe": _dakuten_apostrophe,
    "lint:merged-list": _merged_list,
    "lint:quoted-title": _quoted_title,
    "lint:duplicated-label": _duplicated_label,
    "lint:level-tag-spacing": _level_tag_spacing,
}


def title_map(clusters: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Single-line Japanese texts and every English form each one has.

    A quoted title in another line must match the one title its source names.
    """
    titles: dict[str, set[str]] = defaultdict(set)
    for cluster in clusters:
        source = str(cluster["source"]).strip(" \u3000")
        live = str(cluster["live"]).strip()
        title = live.strip('"“”')
        # A title is one line of its own, not a sentence that quotes one.
        if (
            "\n" in source
            or "\n" in live
            or len(source) < 2
            or any(mark in title for mark in '"“”・')
        ):
            continue
        titles[source].add(title)
    return titles


def compose(source: str, text: str, families: list[str] | set[str], titles: dict) -> str:
    """Apply the named families' fixes to a text, in the fixed family order."""
    for family in ORDER:
        if family in families:
            text = FIXERS[family](source, text, titles)
    return text


def proposals(source: str, live: str, titles: dict) -> dict[str, str]:
    """Each family's own fix of one text, for the families that change it."""
    found = {}
    for family in ORDER:
        fixed = FIXERS[family](source, live, titles)
        if fixed != live:
            found[family] = fixed
    return found
