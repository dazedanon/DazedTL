"""Deterministic lint for RPG Maker translations.

Each family finds one known mechanical defect and fixes it exactly, so the
screen reviewers can spend their attention on meaning and voice. Translation
applies the automatic families to each new line and QA accepts them without
review; QA proposes the other families' fixes, reviewed as a group. Fixers are
idempotent and run in a fixed order, so accepted fixes also apply on top of a
deep correction. Text identical to its source was never translated and gets
no fixes. Some families read the whole game, such as its quoted titles and
its glossary, from a `Game` made once per inventory.

Each family names the targets it reads (`targets`), one kind or several:
English, any target written in Latin script, any written without spaces
between words (Chinese, Japanese), or any target. The game's target, English
unless its pair says otherwise, decides which families run, so a Japanese
translation gets no English spacing or apostrophe fixes.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from collections.abc import Collection, Mapping
from typing import Any, NamedTuple

FAMILIES: dict[str, dict[str, str]] = {
    "lint:inline-speaker": {
        "category": "formatting",
        "description": "A colon follows the speaker name a line starts with, where the source has none.",
        "targets": "latin",
    },
    "lint:heart-spacing": {
        "category": "formatting",
        "description": "A new sentence starts right after ♥ with no space.",
        "targets": "latin",
    },
    "lint:stray-sokuon": {
        "category": "formatting",
        "description": "A stray letter after an ellipsis stands for the small っ.",
        "targets": "english",
    },
    "lint:dakuten-apostrophe": {
        "category": "formatting",
        "description": "An apostrophe left by a dakuten mark splits a real word.",
        "targets": "english",
    },
    "lint:merged-list": {
        "category": "formatting",
        "description": "List items that start separate lines in the source share one line.",
        "targets": "any",
    },
    "lint:quoted-title": {
        "category": "ui",
        "description": "A quoted title no longer matches the title it names.",
        "targets": "latin",
    },
    "lint:duplicated-label": {
        "category": "formatting",
        "description": "A bracketed label appears twice where the source has it once.",
        "targets": "latin",
    },
    "lint:level-tag-spacing": {
        "category": "formatting",
        "description": "A level tag or bracketed label touches the word or number beside it.",
        "targets": "latin",
    },
    "lint:glossary-term": {
        "category": "terminology",
        "description": "A glossary term is rendered another way than the glossary gives it.",
        "targets": "english unspaced",
    },
}
ORDER = tuple(FAMILIES)
# The target a game without a recorded language pair translates into.
DEFAULT_TARGET = "English"
# Families whose fix was right on every line it matched in released games and
# keeps the line's breaks and codes. The rest need a reviewer, the whole game,
# or a change of line structure; see docs/architecture.md.
AUTOMATIC = ("lint:inline-speaker", "lint:heart-spacing", "lint:stray-sokuon")

# A name a line starts with, a colon, and the quote that opens what follows,
# all on its first row.
_SPEAKER_COLON_RE = re.compile(r'^([^\s:："“][^:："“\n]{0,29}?)[ \t]*[:：][ \t]*(?=["“])')
_CLOSING_QUOTES = {'"': '"', "“": "”"}
_HEART_RE = re.compile(r"♥(?=[A-Za-z(])")
_SOKUON_SOURCE_RE = re.compile(r"[っッ]")
_STRAY_SOKUON_RE = re.compile(r"((?:…|\.\.\.)+)h+(?=[♥)\s!?…]|$)")
_DAKUTEN_SOURCE_RE = re.compile(r"[゛゙”]")
_SPLIT_WORD_RE = re.compile(r"\b([A-Za-z]+)'([A-Za-z]*)")
# Single quotes used as quotation marks: their closing mark follows a word.
_OPENING_QUOTE_RE = re.compile(r"(?:^|[\s(\[\"“])'[A-Za-z]")
# Letters of moans and interjections, which keep the apostrophe ("Oh'").
_INTERJECTION_RE = re.compile(r"[aeiouhnmgy]+", re.IGNORECASE)
# After a moan, an apostrophe marks its strain and w counts too ("Whoa'");
# inside a word, w would spare real words ("Wh'y").
_TRAILING_INTERJECTION_RE = re.compile(r"[aeiouhnmgyw]+", re.IGNORECASE)
_CONTRACTION_PREFIXES = frozenset(
    "i you he she it we they that there here who what where when why how let "
    "can don won isn aren wasn weren didn doesn haven hasn hadn couldn wouldn "
    "shouldn mustn ain".split()
)
_BULLET = "・"
_QUOTED_RE = re.compile(r'"([^"\n]{2,120})"|“([^”\n]{2,120})”')
_TITLE_SOURCE_RE = re.compile(r"[「『]([^」』\n]{2,80})[」』]")
# A line that is one quotation from start to end is speech, not a title.
_SPEECH_RE = re.compile(r"「[^「」]*」")
_LEVEL_TAG_RE = re.compile(r"(?<=[a-z])(?=(?:Lv|LV)\.?\s?\d)")
# A label right before a number. A code's bracket, as in \C[2]5 or _PUM[0]1,
# follows the code's name instead.
_LABEL_NUMBER_RE = re.compile(r"((?<![\\\w])\[[^\[\]\n]{1,40}\])(?=\d)")
_SOURCE_LABEL_NUMBER_RE = re.compile(
    r"(?:【[^】\n]{1,40}】|(?<![\\\w])\[[^\[\]\n]{1,40}\])\d"
)
_ENGLISH_LABEL_RE = re.compile(r"\[[^\]\n]{1,40}\]")
_SOURCE_LABEL_RE = re.compile(r"【[^】\n]{1,40}】|\[[^\]\n]{1,40}\]")
_DUPLICATED_LABEL_RE = re.compile(r"(\[[^\]\n]{1,40}\])\s*\1")


class Game(NamedTuple):
    """What families read from the whole game: each single-line Japanese
    text's English forms, which quoted titles must match, its glossary with
    the renderings its English holds, and the language it is translated
    into."""

    titles: Mapping[str, set[str]] = {}
    # An rpgmaker_qa_glossary.Glossary, or None for a text checked alone.
    glossary: Any = None
    # The (Japanese, English) renderings reviewers recorded as decisions,
    # which a glossary fix may not undo.
    decided: tuple[tuple[str, str], ...] = ()
    target: str = DEFAULT_TARGET


def applies(family: str, target: str) -> bool:
    """Whether a family checks a translation into *target*."""
    from util.languages import LATIN, english, script, target_uses_cjk

    reads = {
        "english": lambda: english(target),
        "latin": lambda: script(target) == LATIN,
        "unspaced": lambda: target_uses_cjk(target),
        "any": lambda: True,
    }
    return any(reads[kind]() for kind in FAMILIES[family]["targets"].split())


def _inline_speaker(source: str, text: str, game: Game) -> str:
    # A model writes Name「...」 as the script format Name: "..."; the game
    # shows the line as written, and Dazed's English keeps the source's
    # format, Name "...". A label before a title, as in Novel: "Royal Tomb"
    # or Its name: "Excalibur", keeps its colon.
    from util.speakers import SOURCE, inline_speaker

    match = _SPEAKER_COLON_RE.match(text)
    if (
        match is None
        or inline_speaker(source, SOURCE) is None
        or not _speaker_name(match.group(1))
        or not _opens_speech(text[match.end():])
    ):
        return text
    return f"{match.group(1)} {text[match.end():]}"


def _speaker_name(text: str) -> bool:
    """Whether *text* reads as a name: one to four words, each capitalized,
    with the codes that color it or stand for it."""
    from util.speakers import NAME_CODE_RE

    text = NAME_CODE_RE.sub("", text)
    if not text:
        return True
    words = text.split(" ")
    return (
        len(words) <= 4
        and not any(mark in text for mark in ",;!?")
        and all(word and (word[0].isupper() or word[0].isdigit()) for word in words)
    )


def _opens_speech(text: str) -> bool:
    """Whether the quotation *text* opens is speech: it runs past the text,
    as a message's speech goes on to its next row, or ends a sentence, which
    a title does not."""
    from util.target_text import SENTENCE_ENDS

    end = text.find(_CLOSING_QUOTES[text[0]], 1)
    if end == -1:
        return True
    quoted = text[1:end].rstrip()
    return bool(quoted) and quoted[-1] in SENTENCE_ENDS


def _heart_spacing(source: str, text: str, game: Game) -> str:
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


def _stray_sokuon(source: str, text: str, game: Game) -> str:
    if not _SOKUON_SOURCE_RE.search(source):
        return text
    return _STRAY_SOKUON_RE.sub(r"\1", text)


def _split_word(prefix: str, suffix: str) -> bool:
    """Whether an apostrophe inside or after this word is a dakuten leftover."""
    if _INTERJECTION_RE.fullmatch(prefix + suffix):
        return False
    before, after = prefix.casefold(), suffix.casefold()
    # 's, also as slurred speech writes it ("head'sh").
    if before in {"y", "o", "ma"} or after in {"s", "sh"}:
        return False
    if after == "t":
        return not before.endswith("n")
    if after in {"re", "ve", "ll", "d", "m"}:
        return before not in _CONTRACTION_PREFIXES
    if not after:
        # Dropped g ("goin'"), plural possessives ("girls'") and a moan's
        # strain ("Whoa'") end a word.
        return not (
            before.endswith("in")
            or before.endswith("s")
            or _TRAILING_INTERJECTION_RE.fullmatch(before)
        )
    return True


def _dakuten_apostrophe(source: str, text: str, game: Game) -> str:
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


def _merged_list(source: str, text: str, game: Game) -> str:
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
    # A head that already ends its row takes no blank row before the items.
    head = text[:first].rstrip(" \u3000\n")
    joined = re.sub(r"\s*\n\s*", " ", text[first:])
    items = [part.strip() for part in joined.split(_BULLET) if part.strip()]
    body = "\n".join(_BULLET + item for item in items)
    return (head + "\n" + body) if head else body


def _quoted_title(source: str, text: str, game: Game) -> str:
    spans = list(_QUOTED_RE.finditer(text))
    if len(spans) != 1:
        return text
    match = spans[0]
    group = 1 if match.group(1) else 2
    # A sentence's closing punctuation may sit inside the quote marks.
    quoted = match.group(group).rstrip(".,!?…")
    end = match.start(group) + len(quoted)
    named = set()
    if _SPEECH_RE.fullmatch(source.strip(" \u3000")):
        return text
    whole = source.strip(" \u3000「」『』")
    for piece in [*source.split("\n"), *_TITLE_SOURCE_RE.findall(source)]:
        key = piece.strip(" \u3000「」『』")
        # The line's own source is not a title it names.
        if key != whole:
            named |= game.titles.get(key, set())
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


def _duplicated_label(source: str, text: str, game: Game) -> str:
    if len(_ENGLISH_LABEL_RE.findall(text)) <= len(_SOURCE_LABEL_RE.findall(source)):
        return text
    return _DUPLICATED_LABEL_RE.sub(r"\1", text)


def _level_tag_spacing(source: str, text: str, game: Game) -> str:
    text = _LEVEL_TAG_RE.sub(" ", text)
    # A label followed by its number, as in 【噂Lv】3, reads "[Rumor Lv.] 3".
    if _SOURCE_LABEL_NUMBER_RE.search(source):
        return _LABEL_NUMBER_RE.sub(r"\1 ", text)
    return text


def _glossary_term(source: str, text: str, game: Game) -> str:
    if game.glossary is None:
        return text
    from util import rpgmaker_qa_glossary as glossary

    fixed = glossary.fix(source, text, game.glossary)
    # A decision reviewers recorded wins over the glossary row it disputes,
    # as Demon Lord for 魔王 over a row's Demon King's Kunai.
    if any(
        japanese in source and english in text and english not in fixed
        for japanese, english in game.decided
    ):
        return text
    return fixed


FIXERS = {
    "lint:inline-speaker": _inline_speaker,
    "lint:heart-spacing": _heart_spacing,
    "lint:stray-sokuon": _stray_sokuon,
    "lint:dakuten-apostrophe": _dakuten_apostrophe,
    "lint:merged-list": _merged_list,
    "lint:quoted-title": _quoted_title,
    "lint:duplicated-label": _duplicated_label,
    "lint:level-tag-spacing": _level_tag_spacing,
    "lint:glossary-term": _glossary_term,
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


def game(
    manifest: dict[str, Any], glossary_text: str, target: str = DEFAULT_TARGET
) -> Game:
    """What the families read from a whole inventory, its glossary and the
    language it is translated into. The glossary rules read English words or
    text written without spaces (rpgmaker_qa_glossary), so another target
    reads none."""
    from util import rpgmaker_qa_glossary as glossary

    if not applies("lint:glossary-term", target):
        glossary_text = ""
    return Game(
        title_map(manifest["clusters"]),
        glossary.build(glossary_text, manifest["records"], target),
        target=target,
    )


def note(family: str, source: str, live: str, game: Game) -> str:
    """Why one text's fix is right, for a family that says so line by line,
    as the glossary family names the terms it writes; otherwise ""."""
    if family != "lint:glossary-term" or game.glossary is None:
        return ""
    from util import rpgmaker_qa_glossary as glossary

    return " ".join(
        f'The glossary gives {term.source} as "{term.english}".'
        for term in glossary.fixed_terms(source, live, game.glossary)
    )


def compose(source: str, text: str, families: Collection[str], game: Game) -> str:
    """Apply the named families' fixes to a text, in the fixed family order."""
    if text == source:
        return text
    for family in ORDER:
        if family in families and applies(family, game.target):
            text = FIXERS[family](source, text, game)
    return text


def normalize(source: str, text: str, target: str = DEFAULT_TARGET) -> str:
    """A new translation of a source line into *target*, with the automatic
    families' fixes."""
    return compose(source, text, AUTOMATIC, Game(target=target))


def proposals(source: str, live: str, game: Game) -> dict[str, str]:
    """Each family's own fix of one text, for the families that change it."""
    found = {}
    if live == source:
        return found
    for family in ORDER:
        if not applies(family, game.target):
            continue
        fixed = FIXERS[family](source, live, game)
        if fixed != live:
            found[family] = fixed
    return found
