"""Glossary terms a translation renders another way.

Each glossary row says how a Japanese term reads in English. Text translated
before a row was added or changed can render the term differently, as
"Kelsar Fort" for the glossary's Kelser Fortress. Text QA's inventory pairs
each translated line's Japanese, which the engine keeps in `_original`, with
the English the game shows, and a line whose Japanese holds a term its
English lacks misses it.

A missed term is fixed only where its rendering is found: the whole English
of a name that is only the term, the words most like the term, or a
rendering another line of the term was found with. A line that names the
term another way, such as "you" for a character, or that means an ordinary
word written like a term, such as 回復 beside a skill named Heal, has no
rendering to replace. Text QA proposes each fix as its glossary lint family,
which a reviewer checks, so a term used as an ordinary word stays as it is.

The rules read Japanese terms and English words, so Text QA reads a glossary
for a game translated into English, or into a language written without spaces
between words (util/languages `target_uses_cjk`), Chinese or Japanese, whose
translation uses a term when it holds the term's text. Such a translation has
no words to find a rendering among, so only a name that is the term alone
gets a fix (rpgmaker_qa_lint `game`).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Iterable

from util.languages import KANA, KANJI, active_target, target_uses_cjk
from util.source_text import source_left

# Players never read MapInfos.json names; a map shows its own display name.
UNSEEN_FILES = frozenset({"MapInfos.json"})
# A one-character term is too often part of other words.
TERM_MIN = 2
# Event commands whose text is a name: Show Text's nameplate and the Change
# Name and Change Nickname commands.
NAME_CODES = frozenset({101, 320, 324})
# Kanji that follow a name without making a longer word, such as 様 in トーラ様.
SUFFIXES = frozenset("様殿君達氏")
# Words a term's English may hold, or a rendering may add, without them
# deciding whether the line names the term.
STOPWORDS = frozenset("a an and at by de for from in of on or the to with".split())
ARTICLES = frozenset({"a", "an", "the"})
# Two words alike enough that one may be the other's rendering, such as
# "Kelsar" for Kelser or "Fort" for Fortress.
SIMILAR = 0.6
# At least one word of a rendering is this alike, unless every word of it
# is written like a name.
ANCHOR = 0.8
# Texts and words whose matching a scan remembers: a large game's English
# repeats the same words across tens of thousands of lines.
MEMORY = 1 << 16
# Endings that make a word's people, adjective or noun, as "Shikinowan" and
# "villager" do of Shikinowa and Village; such a word uses the term.
DERIVED = ("n", "an", "ian", "ese", "ish", "ic", "r", "er", "ment", "ness")
# Words naming a person or people, so "Military Police" uses the glossary's
# Military Policeman and "townspeople" its Townsman.
PEOPLE = ("man", "men", "woman", "women", "person", "people", "folk", "folks")

_KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆ヶ]")
# Katakana and its long vowel mark, without the middle dot that joins names.
_KATAKANA = re.compile(r"[\u30a1-\u30fa\u30fc-\u30ff\uff66-\uff9f]")
_KATAKANA_NAME = re.compile(r"[\u30a1-\u30fa\u30fc-\u30ff\uff66-\uff9f]+")
# What joins the parts of a full name written without spaces.
_NAME_PARTS = re.compile(r"\s*[·・•]\s*")
# RPG Maker's control codes, which English words never include.
_CODE = r"\\+[A-Za-z]+\[[^\]]*\]|\\+[A-Za-z{}|.!><^$]"
_TOKEN = re.compile(rf"(?P<code>{_CODE})|(?P<word>[^\W_]+(?:['’][^\W_]+)*['’]?)")
# A choice plugin's condition, written straight after the text it shows, as
# in "Kelser Fortressif(s[119])".
_CONDITION = re.compile(r"(?:if|en)\((?:[^()]|\([^()]*\))*\)")
# A letter held three times or more, as in "Saaan" for サン～.
_HELD = re.compile(r"(\w)\1{2,}")
# Where a capital starts a sentence rather than a name.
_SENTENCE_END = frozenset(".!?。！？…\n")
_OPENING = frozenset(" \t\"'“‘「『(（【［[《〈―─—-▼■●◆★・")
# What a Japanese text may hold around a term that is the whole text, as in
# a nameplate "【トーラ】".
_FRAME = re.compile(rf"{_CODE}|[\s【】「」『』（）()［］\[\]〈〉《》・:：!！?？…～。、.,]")
_QUALIFIER = re.compile(r"\s*\([^()]*\)\s*$")
_ALIASES = re.compile(r"\s*[,、/／]\s*")
# What separates a glossary English's alternatives, as in "Lulu / Lulu-chan".
_ALTERNATIVES = re.compile(r"\s*[/;]\s*")
# The gender a character's line gives right after its names, as in
# "ミナ (Mina) - Female - The hero's sister."
_GENDER = re.compile(r"\s*-\s*(female|male)\b", re.IGNORECASE)
# The qualifier, alternatives and name and title parts of a rendering written
# without spaces, in full-width forms too, as in 爱丽丝（女仆） or 雪莉，盗贼首领.
_UNSPACED_QUALIFIER = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
_UNSPACED_ALTERNATIVES = re.compile(r"\s*[/;／；]\s*")
_UNSPACED_PARTS = re.compile(r"\s*[,，、]\s*")
# A word of romanized Japanese, syllable by syllable, as "Wakachi" or
# "Ishihiroi".
_ROMAJI = re.compile(
    r"(?:(?:[kgsztdnhbpmyrwfj]|sh|ch|ts|[kgnhbpmr]y)?[aiueo]|n(?![aiueoy])"
    r"|([kgstdpc])(?=\1))+"
)
# Letters and digits that continue a term written with them, as the Ａ of
# コア1Ａ does コア1.
_ALNUM = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]")
# A word ending, and the endings the word may have without it, so
# "Warriors", "Accessories" and "blessed" meet Warrior, Accessory and Blessing.
_ENDINGS = (
    ("ies", ("y",)),
    ("ves", ("f", "fe")),
    ("ied", ("y",)),
    ("men", ("man",)),
    ("es", ("", "e")),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("s", ("",)),
    # Succubi, incubi.
    ("i", ("us",)),
)


@dataclass(frozen=True)
class Term:
    """One Japanese form of a glossary row."""

    source: str
    english: str
    section: str
    order: int
    # The English word sequences that count as using the term.
    forms: tuple[tuple[str, ...], ...]
    # What a fix writes in place of a rendering; "" when the glossary gives
    # the Japanese more than one English.
    replacement: str
    # Base glossary rows only claim their span; their English is a hint.
    checked: bool
    # Whether the target writes words between spaces, which the forms are
    # then made of; a form of one written without is its whole text.
    spaced: bool = True
    # Whether the term written as it is in a translation is Japanese left,
    # kept on purpose, as a plugin key in a note is, rather than a rendering:
    # a Chinese target writes a kanji term's hanzi as its own text, and only
    # a term with kana reads as left there.
    kept_is_left: bool = True


def glossary_lines(
    text: str | None,
) -> list[tuple[tuple[tuple[str, str], ...], str, str, bool]]:
    """The glossary's lines as (pairs, line, section, is_base): each
    `source (translation)` pair of a line that lists several, and the whole
    line, which keeps the notes after them, such as a character's gender."""
    from util.vocab import BASE_SEPARATOR, split_glossary_row

    lines = []
    game, _separator, base = str(text or "").partition(BASE_SEPARATOR)
    for part, is_base in ((game, False), (base, True)):
        section = ""
        for raw in part.splitlines():
            whole = line = raw.strip()
            if line.startswith("#"):
                section = line.lstrip("#").strip()
                continue
            pairs = []
            while line:
                row = split_glossary_row(line)
                if row is None:
                    break
                source, english, rest = row
                pairs.append((source, english))
                # "分身小町 (Komachi's Clone) / 小町２ (Komachi 2) - …"
                rest = rest.lstrip()
                line = rest[1:].strip() if rest[:1] in "/／" else ""
            if pairs:
                lines.append((tuple(pairs), whole, section, is_base))
    return lines


def genders(text: str | None) -> dict[str, str]:
    """The gender, Female or Male, the game's glossary gives each character
    right after its names, by each English name its line lists, as
    "ミナ (Mina / Mina-chan) - Female - …" gives both names. Base rows name
    none of the game's characters, and a name lines give different genders
    has none."""
    found: dict[str, tuple[str, set[str]]] = {}
    for pairs, line, _section, is_base in glossary_lines(text):
        last = f"({pairs[-1][1]})"
        end = line.rfind(last)
        gender = None if is_base or end < 0 else _GENDER.match(line, end + len(last))
        if gender is None:
            continue
        for _source, english in pairs:
            for name in _ALTERNATIVES.split(_undecorated(english)):
                name = _QUALIFIER.sub("", name).strip()
                if len(name) >= TERM_MIN:
                    found.setdefault(name.casefold(), (name, set()))[1].add(
                        gender.group(1).capitalize()
                    )
    return {
        name: next(iter(given))
        for name, given in found.values()
        if len(given) == 1
    }


def glossary_rows(text: str) -> list[tuple[str, str, str, bool]]:
    """The glossary's rows as (Japanese, English, section, is_base), with
    each `source (translation)` pair of a line that lists several."""
    return [
        (source, english, section, is_base)
        for pairs, _line, section, is_base in glossary_lines(text)
        for source, english in pairs
    ]


def aliases(source: str) -> list[str]:
    """The Japanese forms a glossary row's source lists, such as 様 and さま."""
    return [alias for part in _ALIASES.split(source) if (alias := _undecorated(part))]


def mentions(text: str, source: str) -> bool:
    """Whether a Japanese text holds a glossary form as a word of its own,
    not inside a longer word of its script, as パン is in パンツ."""
    start = text.find(source)
    while start != -1:
        if not _inside_word(text, start, start + len(source)):
            return True
        start = text.find(source, start + 1)
    return False


def _fold(word: str) -> str:
    return unicodedata.normalize("NFKC", word).casefold().replace("’", "'")


@lru_cache(maxsize=MEMORY)
def _words(text: str) -> tuple[tuple[str, int, int], ...]:
    """Each English word's folded form and span, skipping control codes and
    choice conditions."""
    masked = _CONDITION.sub(lambda match: " " * len(match.group()), text)
    return tuple(
        (_fold(match.group("word")), match.start(), match.end())
        for match in _TOKEN.finditer(masked)
        if match.group("word")
    )


def _initial(text: str, index: int) -> bool:
    """Whether the character at index starts a sentence, so its capital
    says nothing about a name."""
    while index > 0 and text[index - 1] in _OPENING:
        index -= 1
    return index == 0 or text[index - 1] in _SENTENCE_END


def _undecorated(text: str) -> str:
    """A glossary text without its leading label marker, such as ▼."""
    index = 0
    while index < len(text) and (
        unicodedata.category(text[index]) == "So" or text[index] in "•‣⁃※"
    ):
        index += 1
    return text[index:].strip()


def _forms(english: str, source: str, spaced: bool = True) -> list[tuple[str, ...]]:
    """The word sequences that count as using a glossary English: each of
    its "/" alternatives and the parts of one that pairs a name with a
    title, as "Scissor, Bandit Leader", each also without a trailing "(…)"
    qualifier and a leading article. A katakana name the glossary gives a
    full English name, as ニーナ (Nena Evans), is also used by either name
    alone, since the Japanese says only one of them. A target written
    without spaces has each such text as one form, a full name's parts
    joined by a middle dot as in 妮娜·埃文斯."""
    forms: list[tuple[str, ...]] = []
    if not spaced:
        for alternative in _UNSPACED_ALTERNATIVES.split(english):
            for text in (alternative, *_UNSPACED_PARTS.split(alternative)):
                for variant in (text, _UNSPACED_QUALIFIER.sub("", text)):
                    variant = _fold(variant.strip())
                    parts = _NAME_PARTS.split(variant)
                    if not _KATAKANA_NAME.fullmatch(source) or len(parts) not in (2, 3):
                        parts = []
                    # A name's part of one letter is too often inside other
                    # words, as 李 is in 行李.
                    for found in (variant, *(p for p in parts if len(p) >= TERM_MIN)):
                        if found and (found,) not in forms:
                            forms.append((found,))
        return forms
    texts = []
    for alternative in _ALTERNATIVES.split(english):
        texts.append(alternative)
        if "," in alternative:
            texts.extend(alternative.split(","))
    for text in texts:
        for variant in (text, _QUALIFIER.sub("", text)):
            words = [word for word, _start, _end in _words(variant)]
            if len(words) > 1 and words[0] in ARTICLES:
                words = words[1:]
            if words and tuple(words) not in forms:
                forms.append(tuple(words))
    if _KATAKANA_NAME.fullmatch(source):
        for text in texts:
            spans = _words(_QUALIFIER.sub("", text))
            if len(spans) in (2, 3) and all(
                _QUALIFIER.sub("", text)[start].isupper() and word not in STOPWORDS
                for word, start, _end in spans
            ):
                for name in (spans[0][0], spans[-1][0]):
                    if (name,) not in forms:
                        forms.append((name,))
    return forms


def terms(
    rows: Iterable[tuple[str, str, str, bool]], target: str | None = None
) -> list[Term]:
    """Every row's Japanese forms, longest first, so each claims its span
    before a shorter term inside it. A Japanese the game's glossary gives
    two English accepts either and has no fix. *target* is the language
    the game is translated into, the active target by default."""
    target = target or active_target()
    spaced = not target_uses_cjk(target)
    alternatives, qualifier = (
        (_ALTERNATIVES, _QUALIFIER) if spaced
        else (_UNSPACED_ALTERNATIVES, _UNSPACED_QUALIFIER)
    )
    found: dict[str, Term] = {}
    for order, (source, english, section, is_base) in enumerate(rows):
        english = _undecorated(english)
        first = alternatives.split(english)[0].strip()
        for alias in _ALIASES.split(source):
            alias = _undecorated(alias)
            if not alias:
                continue
            earlier = found.get(alias)
            if earlier:
                if earlier.checked and not is_base and earlier.english != english:
                    found[alias] = replace(
                        earlier,
                        english=f"{earlier.english} / {english}",
                        forms=tuple(
                            dict.fromkeys(
                                earlier.forms + tuple(_forms(english, alias, spaced))
                            )
                        ),
                        replacement="",
                    )
                continue
            forms = tuple(_forms(english, alias, spaced))
            found[alias] = Term(
                source=alias,
                english=english,
                section=section,
                order=order,
                forms=forms,
                # A qualifier the Japanese lacks is a note, as in Thora (Event).
                replacement=(
                    first if qualifier.search(alias) else qualifier.sub("", first)
                ),
                checked=(
                    not is_base
                    and len(alias) >= TERM_MIN
                    and bool(forms)
                    # Hiragana alone is grammar or an ordinary word, such as
                    # さん inside たくさん.
                    and bool(_KANJI.search(alias) or _KATAKANA.search(alias))
                    # A target that still holds the Japanese it names, read
                    # in the game's pair, where a Chinese one's hanzi are its
                    # own, is no translation to check.
                    and not source_left(english, alias, target=target)
                    # A target written without spaces is checked against a
                    # rendering in its own letters, not one a glossary
                    # written for English still gives, as アリス (Alice).
                    and (spaced or bool(KANJI.search(english) or KANA.search(english)))
                ),
                spaced=spaced,
                kept_is_left=spaced or bool(source_left(alias, alias, target=target)),
            )
    return sorted(found.values(), key=lambda term: (-len(term.source), term.order))


def _script(char: str) -> str:
    if _KANJI.match(char):
        return "kanji"
    if _KATAKANA.match(char):
        return "katakana"
    return ""


def _inside_word(text: str, start: int, end: int) -> bool:
    """Whether a term found at text[start:end] continues a longer word of
    its own script, as パン does in パンツ or 呪術 in 呪術師, or a longer
    name written with letters and digits, as コア1 does in コア1Ａ."""
    first, last = _script(text[start]), _script(text[end - 1])
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return bool(
        (first and _script(before) == first)
        or (last and after and _script(after) == last and after not in SUFFIXES)
        or (_ALNUM.match(text[end - 1]) and _ALNUM.match(after))
        or (_ALNUM.match(text[start]) and _ALNUM.match(before))
    )


def _by_first(ordered: list[Term]) -> dict[str, list[tuple[int, Term]]]:
    """Each term under its first character, with its place in `ordered`, so
    a text is searched only for the terms that can start in it."""
    index: dict[str, list[tuple[int, Term]]] = defaultdict(list)
    for rank, term in enumerate(ordered):
        index[term.source[0]].append((rank, term))
    return dict(index)


def _hits(
    source: str, index: dict[str, list[tuple[int, Term]]]
) -> list[tuple[Term, int, int]]:
    """The terms in a Japanese text, each span claimed by the longest term
    that covers it, as 防御態勢 claims the 防御 inside it."""
    claimed = [False] * len(source)
    hits = []
    candidates = sorted(
        (entry for char in set(source) for entry in index.get(char, ())),
        key=lambda entry: entry[0],
    )
    for _rank, term in candidates:
        start = source.find(term.source)
        while start != -1:
            end = start + len(term.source)
            if not any(claimed[start:end]):
                claimed[start:end] = [True] * (end - start)
                if term.checked and not _inside_word(source, start, end):
                    hits.append((term, start, end))
            start = source.find(term.source, start + 1)
    return hits


def _possessive(word: str) -> tuple[str, bool]:
    if word.endswith("'s"):
        return word[:-2], True
    if word.endswith("'"):
        return word[:-1], True
    return word, False


@lru_cache(maxsize=MEMORY)
def _bases(word: str) -> frozenset[str]:
    """A word and the words it may be a plural or verb form of."""
    forms = {word}
    for ending, replacements in _ENDINGS:
        if not word.endswith(ending) or ending == "s" and word.endswith("ss"):
            continue
        stem = word[: -len(ending)]
        for replacement in replacements:
            if len(stem + replacement) >= 3:
                forms.add(stem + replacement)
        # "stopped" and "stopping" come from stop.
        if ending in {"ed", "ing"} and len(stem) > 3 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
    return frozenset(forms)


def _derived(term: str, live: str) -> bool:
    """Whether a live word is a term word's people, adjective or noun, as
    "Shikinowans" is of Shikinowa."""
    return len(term) >= 4 and any(
        base.startswith(term) and base[len(term) :] in DERIVED for base in _bases(live)
    )


def _people(term: str, live: str) -> bool:
    """Whether a live word names the people a term's word names a person of,
    or one of them, as "police" or "policemen" does of Policeman."""
    for ending in PEOPLE:
        stem = term[: -len(ending)]
        if not term.endswith(ending) or len(stem) < 3:
            continue
        stems = {stem, stem[:-1] if stem.endswith("s") else stem + "s"}
        return any(
            base in stems or base[: len(stem)] in stems and base[len(stem) :] in PEOPLE
            for base in _bases(live)
        )
    return False


@lru_cache(maxsize=MEMORY)
def _meets(term_word: str, live_word: str, last: bool) -> bool:
    """Whether a live word is a term's word, in any number or tense, held
    long, or as its people or adjective; a possessive counts only at the
    term's end, since Tarna's Academy is not the glossary's Tarna Academy."""
    term, term_owns = _possessive(term_word)
    live, live_owns = _possessive(live_word)
    if live_owns and not (term_owns or last):
        return False
    live = _HELD.sub(r"\1", live)
    return (
        term == live
        or bool(_bases(term) & _bases(live))
        or _derived(term, live)
        or _people(term, live)
        or _people(live, term)
    )


def _content(words: Iterable[str]) -> list[str]:
    """Words without the ones a rendering may add or drop, such as "of"."""
    words = list(words)
    content = [word for word in words if word not in STOPWORDS]
    return content or words


def _reordered(form_words: list[str], window: list[str]) -> bool:
    """Whether a run of words holds a term's words in another order, as
    "Lilith's Tower" does Tower of Lilith."""
    remaining = list(window)
    order = []
    for word in form_words:
        match = next(
            (index for index, live in enumerate(remaining)
             if live is not None and _meets(word, live, True)),
            None,
        )
        if match is None:
            return False
        order.append(match)
        remaining[match] = None
    return len(form_words) > 1 and order != sorted(order)


def _uses(words: list[str], form: tuple[str, ...]) -> bool:
    """Whether a line's words hold a term form's words in order, with its
    words joined or split as in "break through" for Breakthrough, and any
    of the small words a rendering adds or drops."""
    form_words, words = _content(form), _content(words)
    count = len(form_words)
    for index in range(len(words) - count + 1):
        window = words[index : index + count]
        if all(
            _meets(form_words[offset], window[offset], offset == count - 1)
            for offset in range(count)
        ) or _reordered(form_words, window):
            return True
    target = "".join(_possessive(word)[0] for word in form_words)
    for index in range(len(words)):
        joined = ""
        for word in words[index:]:
            joined += _possessive(word)[0]
            if _bases(joined) & _bases(target):
                return True
            if len(joined) >= len(target) + 3:
                break
    return False


@lru_cache(maxsize=MEMORY)
def uses_term(live: str, term: Term) -> bool:
    if not term.spaced:
        text = _fold(live)
        return any(form[0] in text for form in term.forms)
    words = [word for word, _start, _end in _words(live)]
    return any(_uses(words, form) for form in term.forms)


def _likeness(term_word: str, live_word: str) -> float:
    if _meets(term_word, live_word, True):
        return 1.0
    term, live = _possessive(term_word)[0], _possessive(live_word)[0]
    if term == live:
        # Only a possessive differs, as in Tarna's Academy.
        return 0.9
    # A rendering keeps a name's first sound, as "Kelsar" does Kelser's, so
    # "Riyuuya" never renders Yuuyami however many letters they share.
    if term[:1] != live[:1]:
        return 0.0
    ratio = difflib.SequenceMatcher(None, term, live).ratio()
    # A shortened word, as "Fort" for Fortress.
    short, long = sorted((term, live), key=len)
    if len(short) >= 4 and long.startswith(short):
        ratio = max(ratio, 0.75)
    return ratio


def _article(text: str) -> str:
    """The article a multi-word English starts with, folded, or ""."""
    first, _space, rest = text.partition(" ")
    return _fold(first) if rest and _fold(first) in ARTICLES else ""


def _with_article(live: str, start: int, term: Term) -> int:
    """Where a rendering starts once it takes the article the term's own
    English starts with, so "the Bitter Winter" becomes "The Bitter Winter
    of Fjall" rather than "the The Bitter Winter of Fjall"."""
    article = _article(term.replacement)
    before = live[:start].rstrip(" ")
    if article and _fold(before[-len(article) :]) == article and (
        len(before) == len(article) or not before[-len(article) - 1].isalnum()
    ):
        return len(before) - len(article)
    return start


@dataclass(frozen=True)
class Corpus:
    """How the game's own English writes its words: those it writes in lower
    case somewhere are ordinary words, and those it capitalizes inside a
    sentence are names."""

    ordinary: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()

    def named(self, live: str, word: str, position: int) -> bool:
        """Whether a word reads as a name: capitalized, never written in
        lower case, and inside a sentence or capitalized there elsewhere."""
        word = _possessive(word)[0]
        return (
            word not in self.ordinary
            and live[position].isupper()
            and (not _initial(live, position) or word in self.names)
        )


def corpus(texts: Iterable[str]) -> Corpus:
    ordinary, names = set(), set()
    for text in texts:
        for word, start, _end in _words(text):
            if text[start].islower():
                ordinary.add(_possessive(word)[0])
            elif text[start].isupper() and not _initial(text, start):
                names.add(_possessive(word)[0])
    return Corpus(frozenset(ordinary), frozenset(names))


def _rendering(
    live: str, words: list[tuple[str, int, int]], term: Term, words_of: Corpus
) -> tuple[int, int] | None:
    """The span of the words that most resemble the term, or None when no
    run of words resembles each of the term's words without adding others.

    A word that does not read as a name, as "Scene" beside Scenario or a
    sentence's "But" beside Butt, never renders a term alone; with another
    word of the term beside it, as in "Swamp of Ashes" for Ashen Swamp, a
    close likeness does. A capitalized term never replaces a word written in
    lower case, the ordinary word the term shares its writing with, as "pray"
    for Prayer.
    """
    content = _content(term.forms[0])
    capitalized = term.replacement[:1].isupper()
    # A term written as a title, every word capitalized, is rendered as
    # one too, so "the Fjall warriors'" is a phrase, not Warrior of Fjall.
    title = all(
        term.replacement[start].isupper()
        for word, start, _end in _words(term.replacement)
        if word not in STOPWORDS
    )
    best: tuple[float, int, int] | None = None
    for first in range(len(words)):
        for last in range(first, min(len(words), first + len(term.forms[0]) + 2)):
            window = words[first : last + 1]
            if window[0][0] in STOPWORDS or window[-1][0] in STOPWORDS:
                continue
            start, end = window[0][1], window[-1][2]
            if re.search(_CODE, live[start:end]) or live[start:end].count("\n") > 1:
                continue
            if capitalized and not live[start].isupper():
                continue
            found = [word for word in window if word[0] not in STOPWORDS]
            if len(found) != len(content) or (
                title and not all(live[start].isupper() for _word, start, _end in found)
            ):
                continue
            # Each of the term's words takes the window word most like it.
            matched = []
            remaining = list(found)
            for word in content:
                match = max(remaining, key=lambda item: _likeness(word, item[0]))
                matched.append((match, _likeness(word, match[0])))
                remaining.remove(match)
            scores = [score for _match, score in matched]
            # A word that only resembles the term's is no rendering when it
            # is an abbreviation, as "MN" beside Mana, or part of a
            # hyphenated word, as "Succu-Room" beside Succubus.
            if min(scores) < 1 and (
                any(
                    score < 1 and live[position:end].isupper() and end - position <= 3
                    for (_word, position, end), score in matched
                )
                or live[start - 1 : start] == "-"
                or live[end : end + 1] == "-"
            ):
                continue
            names = all(
                words_of.named(live, word, position)
                for (word, position, _end), _score in matched
            )
            if min(scores) < SIMILAR or not (
                names or len(content) > 1 and max(scores) >= ANCHOR
            ):
                continue
            score = sum(scores) / len(scores)
            if best is None or score > best[0]:
                best = (score, start, end)
    return (_with_article(live, best[1], term), best[2]) if best else None


def _romanized(
    live: str, words: list[tuple[str, int, int]], term: Term, glossary: Glossary
) -> tuple[int, int] | None:
    """The span of a name that keeps a word of the term and writes the rest
    in romanized Japanese, as "Wakachi Valley" does Dividing Valley or
    "Crag of Yomi" Underworld Crag; a romanized word the glossary gives as
    another term's English, as a character's name, is that term's."""
    content = _content(term.forms[0])
    if len(content) < 2:
        return None
    for first in range(len(words)):
        for last in range(first + 1, min(len(words), first + len(term.forms[0]) + 1)):
            window = words[first : last + 1]
            if window[0][0] in STOPWORDS or window[-1][0] in STOPWORDS:
                continue
            start, end = window[0][1], window[-1][2]
            if re.search(_CODE, live[start:end]) or live[start:end].count("\n") > 1:
                continue
            found = [word for word in window if word[0] not in STOPWORDS]
            kept = [
                word for word in found
                if any(_meets(own, word[0], True) for own in content)
            ]
            others = [word for word in found if word not in kept]
            # The name ends where the term's words do, so "Yotetsu in an
            # Oni's" is not taken without its "Hands".
            beside = [words[index][0] for index in (first - 1, last + 1) if 0 <= index < len(words)]
            if (
                any(_meets(own, word, True) for own in content for word in beside)
                or not 2 <= len(found) <= len(content)
                or not kept
                or not others
                or not all(live[position].isupper() for _word, position, _end in found)
            ):
                continue
            if all(
                len(word) >= 3
                and _ROMAJI.fullmatch(_possessive(word)[0])
                and _possessive(word)[0] not in glossary.known
                and glossary.corpus.named(live, word, position)
                for word, position, _end in others
            ):
                return _with_article(live, start, term), end
    return None


def is_name(record: dict[str, Any]) -> bool:
    """Whether a text names something, as a nameplate, an actor name or a
    database entry's name does, rather than saying something."""
    field = str((record.get("database_entity") or {}).get("field") or "")
    return (
        record.get("event_code") in NAME_CODES
        or record.get("classification") == "database"
        and (field.endswith("name") or record["file"] == "System.json")
    )


def _whole(
    source: str, live: str, words: list[tuple[str, int, int]], term: Term
) -> tuple[int, int] | None:
    """The span of every word when a name's Japanese is the term and nothing
    else, so its English is only the term's rendering, with any mark the
    term's English starts or ends with, as the + of "Mark+"."""
    if not words or _FRAME.sub("", source) != _FRAME.sub("", term.source):
        return None
    start, end = words[0][1], words[-1][2]
    if live[start:end].count("\n") > 1:
        return None
    head = re.match(r"[^\w\s]*", term.replacement).group()
    if head and live[:start].endswith(head):
        start -= len(head)
    tail = re.search(r"[^\w\s]*$", term.replacement).group()
    if tail and live[end:].startswith(tail):
        end += len(tail)
    return start, end


def _pattern(rendering: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<!\w)" + r"\s+".join(map(re.escape, rendering.split())) + r"(?!\w)"
    )


def _occurrences(
    live: str, renderings: Iterable[str], taken: list[tuple[int, int, Term]]
) -> list[tuple[int, int]]:
    """Every place the line holds one of the renderings outside the spans
    taken, longest rendering first."""
    found: list[tuple[int, int]] = []
    for rendering in sorted(renderings, key=lambda text: (-len(text), text)):
        for match in _pattern(rendering).finditer(live):
            span = match.span()
            if match.group().count("\n") > 1 or any(
                span[0] < end and start < span[1]
                for start, end in [*found, *((s, e) for s, e, _t in taken)]
            ):
                continue
            found.append(span)
    return found


def _replaced(text: str, start: int, end: int, replacement: str) -> str:
    """The text with a rendering replaced, keeping a line break it crossed
    between the same words where the replacement has as many, or before the
    replacement otherwise, so a line spread over several commands keeps its
    lines."""
    rendered = text[start:end]
    if "\n" not in rendered:
        return text[:start] + replacement + text[end:]
    before = len(rendered[: rendered.index("\n")].split())
    words = replacement.split(" ")
    if len(words) > 1:
        cut = min(max(before, 1), len(words) - 1)
        return (
            text[:start] + " ".join(words[:cut]) + "\n" + " ".join(words[cut:])
            + text[end:]
        )
    head = text[:start].rstrip(" ")
    if not head or head.endswith("\n"):
        return head + replacement + "\n" + text[end:].lstrip(" ")
    return head + "\n" + replacement + text[end:]


def _written(live: str, spans: list[tuple[int, int, Term]]) -> str:
    """The line with each term written over its rendering."""
    text = live
    for start, end, term in sorted(spans, key=lambda item: item[0], reverse=True):
        replacement = term.replacement
        # A name keeps its capital; a leading article or an ordinary word
        # takes the case of the text it replaces.
        if replacement[:1].islower() and text[start].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        elif _article(replacement) and text[start].islower():
            replacement = replacement[0].lower() + replacement[1:]
        # The rendering's possessive stays: "Kelsar Fort's gate".
        rendered = text[start:end]
        if _possessive(_fold(rendered))[1] and not _possessive(_fold(replacement))[1]:
            replacement += "'" if rendered.endswith("'") else rendered[-2:]
        text = _replaced(text, start, end, replacement)
    return text


@dataclass(frozen=True)
class Glossary:
    """A game's glossary terms with what its English says of them: the
    words it writes as names, the Japanese of its names, and each term's
    renderings found on its lines."""

    index: dict[str, list[tuple[int, Term]]] = field(default_factory=dict)
    corpus: Corpus = Corpus()
    # The Japanese and English of each nameplate, actor name and database
    # name, so a message with a name's Japanese is not taken for one.
    names: frozenset[tuple[str, str]] = frozenset()
    # Japanese texts only files players never read show.
    unseen: frozenset[str] = frozenset()
    renderings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Every word of the glossary's English.
    known: frozenset[str] = frozenset()
    # Each of the game's own texts that misses a term, fixed, so Text QA
    # reads its proposals without finding them again.
    fixed: dict[tuple[str, str], str] = field(default_factory=dict)


def _seen(record: dict[str, Any]) -> bool:
    return (
        record["file"] not in UNSEEN_FILES
        and str(record["source"]) != str(record["live"])
        and bool(str(record["live"]).strip())
    )


def missing(source: str, text: str, glossary: Glossary) -> list[tuple[Term, int, int]]:
    """Each glossary term a Japanese text holds that its English lacks, with
    its span in the Japanese. A term the English still holds in Japanese is
    kept on purpose, such as a plugin key in a note."""
    found: list[tuple[Term, int, int]] = []
    for term, start, end in _hits(source, glossary.index):
        if term.kept_is_left and text.count(term.source) >= source.count(term.source):
            continue
        if not uses_term(text, term) and all(term != hit[0] for hit in found):
            found.append((term, start, end))
    return found


def _spans(
    source: str, text: str, glossary: Glossary, learned: bool = True
) -> list[tuple[int, int, Term]]:
    """Where a text renders each glossary term it misses, every place it
    writes that rendering included."""
    if text == source or source in glossary.unseen:
        return []
    terms = [term for term, _start, _end in missing(source, text, glossary)]
    words = _words(text)
    spans: list[tuple[int, int, Term]] = []
    for term in terms:
        if not term.replacement:
            continue
        span = (
            ((source, text) in glossary.names and _whole(source, text, words, term))
            or term.spaced and (
                _rendering(text, words, term, glossary.corpus)
                or _romanized(text, words, term, glossary)
            )
        )
        if span and not any(span[0] < end and start < span[1] for start, end, _t in spans):
            spans.append((*span, term))
    for term in terms:
        if not term.replacement:
            continue
        own = {" ".join(text[start:end].split()) for start, end, t in spans if t == term}
        if not own and learned:
            own = set(glossary.renderings.get(term.source, ()))
        spans += [(*span, term) for span in _occurrences(text, own, spans)]
    return spans


def build(
    glossary_text: str, records: Iterable[dict[str, Any]], target: str | None = None
) -> Glossary:
    """A game's glossary context from its glossary file and the inventory
    records Text QA reads: the game's English words, the Japanese of its
    names, and the renderings each term was found with, so a nameplate's
    "Sonko" fixes dialogue too. *target* is the language the game is
    translated into, the active target by default."""
    ordered = terms(glossary_rows(glossary_text), target)
    if not any(term.checked for term in ordered):
        return Glossary()
    records = list(records)
    seen = [record for record in records if _seen(record)]
    names = frozenset(
        (str(record["source"]), str(record["live"])) for record in seen if is_name(record)
    )
    shown = {str(record["source"]) for record in seen}
    unseen = frozenset(
        str(record["source"]) for record in records
        if record["file"] in UNSEEN_FILES and str(record["source"]) not in shown
    )
    context = Glossary(
        index=_by_first(ordered),
        corpus=corpus(str(record["live"]) for record in seen),
        names=names,
        unseen=unseen,
        known=frozenset(
            word for term in ordered for form in term.forms for word in form
        ),
    )
    renderings: dict[str, set[str]] = defaultdict(set)
    lacking = []
    for source, live in sorted({(str(r["source"]), str(r["live"])) for r in seen}):
        if not missing(source, live, context):
            continue
        lacking.append((source, live))
        for start, end, term in _spans(source, live, context, learned=False):
            rendering = live[start:end]
            if rendering[:1].isupper():
                renderings[term.source].add(" ".join(rendering.split()))
    context = replace(
        context,
        renderings={
            source: tuple(sorted(found, key=lambda text: (-len(text), text)))
            for source, found in sorted(renderings.items())
        },
    )
    return replace(
        context,
        fixed={(source, live): _fixed(source, live, context) for source, live in lacking},
    )


def fixed_terms(source: str, text: str, glossary: Glossary) -> list[Term]:
    """The terms `fix` writes into a text, in the order it finds them."""
    return list(dict.fromkeys(term for _start, _end, term in _spans(source, text, glossary)))


def _fixed(source: str, text: str, glossary: Glossary) -> str:
    spans = _spans(source, text, glossary)
    return _written(text, spans) if spans else text


def fix(source: str, text: str, glossary: Glossary) -> str:
    """The text with each glossary term it misses written over its
    rendering, or the text itself when no rendering is found."""
    known = glossary.fixed.get((source, text))
    return _fixed(source, text, glossary) if known is None else known
