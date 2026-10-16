"""Glossary terms a translation renders another way.

Each glossary row says how a Japanese term reads in English. Text translated
before a row was added or changed can render the term differently, as
"Kelsar Fort" for the glossary's Kelser Fortress. Text QA's inventory pairs
each translated line's Japanese, which the engine keeps in `_original`, with
the English the game shows, and a line whose Japanese holds a term its
English lacks is flagged.

Some terms are also ordinary words, such as 回復 for a skill named Heal, so
every flag is the user's to review. A proposal writes the term in place of
the words that render it, and nothing reaches the game without a choice.

This module is not one of Text QA's rule files, so changing it never makes a
prepared QA task outdated.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

# Players never read MapInfos.json names; a map shows its own display name.
UNSEEN_FILES = frozenset({"MapInfos.json"})
# A one-character term is too often part of other words.
TERM_MIN = 2
# Lines a scan keeps; a glossary row that matches more is better narrowed.
LINE_LIMIT = 1000
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

_KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆ヶ]")
# Katakana and its long vowel mark, without the middle dot that joins names.
_KATAKANA = re.compile(r"[\u30a1-\u30fa\u30fc-\u30ff\uff66-\uff9f]")
_JAPANESE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]"
)
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
# A word ending, and the endings the word may have without it, so
# "Warriors", "Accessories" and "blessed" meet Warrior, Accessory and Blessing.
_ENDINGS = (
    ("ies", ("y",)),
    ("ied", ("y",)),
    ("men", ("man",)),
    ("es", ("", "e")),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("s", ("",)),
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
    # What a proposal writes in place of a rendering; "" when the glossary
    # gives the Japanese more than one English.
    replacement: str
    # Base glossary rows only claim their span; their English is a hint.
    checked: bool


def glossary_rows(text: str) -> list[tuple[str, str, str, bool]]:
    """The glossary's rows as (Japanese, English, section, is_base), with
    each `source (translation)` pair of a line that lists several."""
    from util.vocab import BASE_SEPARATOR, split_glossary_row

    rows = []
    game, _separator, base = str(text or "").partition(BASE_SEPARATOR)
    for part, is_base in ((game, False), (base, True)):
        section = ""
        for raw in part.splitlines():
            line = raw.strip()
            if line.startswith("#"):
                section = line.lstrip("#").strip()
                continue
            while line:
                row = split_glossary_row(line)
                if row is None:
                    break
                source, english, rest = row
                rows.append((source, english, section, is_base))
                # "分身小町 (Komachi's Clone) / 小町２ (Komachi 2) - …"
                rest = rest.lstrip()
                line = rest[1:].strip() if rest[:1] in "/／" else ""
    return rows


def _fold(word: str) -> str:
    return unicodedata.normalize("NFKC", word).casefold().replace("’", "'")


def _words(text: str) -> list[tuple[str, int, int]]:
    """Each English word's folded form and span, skipping control codes and
    choice conditions."""
    masked = _CONDITION.sub(lambda match: " " * len(match.group()), text)
    return [
        (_fold(match.group("word")), match.start(), match.end())
        for match in _TOKEN.finditer(masked)
        if match.group("word")
    ]


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


def _forms(english: str) -> list[tuple[str, ...]]:
    """The word sequences that count as using a glossary English: each of
    its "/" alternatives and the parts of one that pairs a name with a
    title, as "Scissor, Bandit Leader", each also without a trailing "(…)"
    qualifier and a leading article."""
    texts = []
    for alternative in english.split("/"):
        texts.append(alternative)
        if "," in alternative:
            texts.extend(alternative.split(","))
    forms: list[tuple[str, ...]] = []
    for text in texts:
        for variant in (text, _QUALIFIER.sub("", text)):
            words = [word for word, _start, _end in _words(variant)]
            if len(words) > 1 and words[0] in ARTICLES:
                words = words[1:]
            if words and tuple(words) not in forms:
                forms.append(tuple(words))
    return forms


def terms(rows: Iterable[tuple[str, str, str, bool]]) -> list[Term]:
    """Every row's Japanese forms, longest first, so each claims its span
    before a shorter term inside it. A Japanese the game's glossary gives
    two English accepts either and has no proposal."""
    found: dict[str, Term] = {}
    for order, (source, english, section, is_base) in enumerate(rows):
        english = _undecorated(english)
        first = english.split("/")[0].strip()
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
                        forms=tuple(dict.fromkeys(earlier.forms + tuple(_forms(english)))),
                        replacement="",
                    )
                continue
            forms = tuple(_forms(english))
            found[alias] = Term(
                source=alias,
                english=english,
                section=section,
                order=order,
                forms=forms,
                # A qualifier the Japanese lacks is a note, as in Thora (Event).
                replacement=(
                    first if _QUALIFIER.search(alias) else _QUALIFIER.sub("", first)
                ),
                checked=(
                    not is_base
                    and len(alias) >= TERM_MIN
                    and bool(forms)
                    # Hiragana alone is grammar or an ordinary word, such as
                    # さん inside たくさん.
                    and bool(_KANJI.search(alias) or _KATAKANA.search(alias))
                    and _JAPANESE.search(english) is None
                ),
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
    its own script, as パン does in パンツ or 呪術 in 呪術師."""
    first, last = _script(text[start]), _script(text[end - 1])
    before = _script(text[start - 1]) if start else ""
    after = text[end] if end < len(text) else ""
    return bool(
        (first and before == first)
        or (last and after and _script(after) == last and after not in SUFFIXES)
    )


def _by_first(ordered: list[Term]) -> dict[str, list[tuple[int, Term]]]:
    """Each term under its first character, with its place in `ordered`, so
    a text is searched only for the terms that can start in it."""
    index: dict[str, list[tuple[int, Term]]] = defaultdict(list)
    for rank, term in enumerate(ordered):
        index[term.source[0]].append((rank, term))
    return index


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


def _bases(word: str) -> set[str]:
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
    return forms


def _meets(term_word: str, live_word: str, last: bool) -> bool:
    """Whether a live word is a term's word, in any number or tense or held
    long; a possessive counts only at the term's end, since Tarna's Academy
    is not the glossary's Tarna Academy."""
    term, term_owns = _possessive(term_word)
    live, live_owns = _possessive(live_word)
    if live_owns and not (term_owns or last):
        return False
    live = _HELD.sub(r"\1", live)
    return term == live or bool(_bases(term) & _bases(live))


def _content(words: Iterable[str]) -> list[str]:
    """Words without the ones a rendering may add or drop, such as "of"."""
    words = list(words)
    content = [word for word in words if word not in STOPWORDS]
    return content or words


def _uses(words: list[str], form: tuple[str, ...]) -> bool:
    """Whether a line's words hold a term form's words in order, with its
    words joined or split as in "break through" for Breakthrough, and any
    of the small words a rendering adds or drops."""
    form_words, words = _content(form), _content(words)
    count = len(form_words)
    for index in range(len(words) - count + 1):
        if all(
            _meets(form_words[offset], words[index + offset], offset == count - 1)
            for offset in range(count)
        ):
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


def uses_term(live: str, term: Term) -> bool:
    words = [word for word, _start, _end in _words(live)]
    return any(_uses(words, form) for form in term.forms)


def _likeness(term_word: str, live_word: str) -> float:
    if _meets(term_word, live_word, True):
        return 1.0
    term, live = _possessive(term_word)[0], _possessive(live_word)[0]
    if term == live:
        # Only a possessive differs, as in Tarna's Academy.
        return 0.9
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


@dataclass(frozen=True)
class _Line:
    live: str
    words: list[tuple[str, int, int]]
    # A rendering may cross a line break only where the fix is rewrapped.
    wraps: bool


def _rendering(line: _Line, term: Term, words_of: Corpus) -> tuple[int, int] | None:
    """The span of the words that most resemble the term, or None when no
    run of words resembles each of the term's words without adding others.

    A word that does not read as a name, as "Scene" beside Scenario or a
    sentence's "But" beside Butt, never renders a term alone; with another
    word of the term beside it, as in "Swamp of Ashes" for Ashen Swamp, a
    close likeness does. A capitalized term never replaces a word written in
    lower case, the ordinary word the term shares its writing with, as "pray"
    for Prayer.
    """
    live, words = line.live, line.words
    content = _content(term.forms[0])
    capitalized = term.replacement[:1].isupper()
    best: tuple[float, int, int] | None = None
    for first in range(len(words)):
        for last in range(first, min(len(words), first + len(term.forms[0]) + 2)):
            window = words[first : last + 1]
            if window[0][0] in STOPWORDS or window[-1][0] in STOPWORDS:
                continue
            start, end = window[0][1], window[-1][2]
            if re.search(_CODE, live[start:end]) or (
                "\n" in live[start:end] and not line.wraps
            ):
                continue
            if capitalized and not live[start].isupper():
                continue
            found = [word for word in window if word[0] not in STOPWORDS]
            if len(found) != len(content):
                continue
            # Each of the term's words takes the window word most like it.
            matched = []
            remaining = list(found)
            for word in content:
                match = max(remaining, key=lambda item: _likeness(word, item[0]))
                matched.append((match, _likeness(word, match[0])))
                remaining.remove(match)
            scores = [score for _match, score in matched]
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


def _is_name(record: dict[str, Any]) -> bool:
    """Whether a text names something, as a nameplate, an actor name or a
    database entry's name does, rather than saying something."""
    field = str((record.get("database_entity") or {}).get("field") or "")
    return (
        record.get("event_code") in NAME_CODES
        or record.get("classification") == "database"
        and (field.endswith("name") or record["file"] == "System.json")
    )


def _whole(record: dict[str, Any], line: _Line, term: Term) -> tuple[int, int] | None:
    """The span of every word when a name's Japanese is the term and nothing
    else, so its English is only the term's rendering. A message that says
    only the term, as 興奮…… does, may mean the ordinary word."""
    source = str(record["source"])
    if not _is_name(record) or _FRAME.sub("", source) != term.source or not line.words:
        return None
    start, end = line.words[0][1], line.words[-1][2]
    if "\n" in line.live[start:end] and not line.wraps:
        return None
    return start, end


def _learned(
    line: _Line, renderings: Iterable[str], taken: list[tuple[int, int, Term]]
) -> tuple[int, int] | None:
    """Where the line holds a rendering another line of the term was found
    with, such as a nameplate's "Sonko" in dialogue."""
    for rendering in sorted(renderings, key=len, reverse=True):
        pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, rendering.split())) + r"(?!\w)"
        for match in re.finditer(pattern, line.live):
            span = match.span()
            if ("\n" in match.group() and not line.wraps) or any(
                span[0] < end and start < span[1] for start, end, _term in taken
            ):
                continue
            return span
    return None


def _written(line: _Line, spans: list[tuple[int, int, Term]]) -> str | None:
    """The line with each term written over its rendering."""
    text = line.live
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
        text = text[:start] + replacement + text[end:]
    return text if text != line.live else None


def line_key(identity: str, live: str) -> str:
    """A flagged line's key: its inventory identity and the English it holds,
    so a choice made for one text never applies to another."""
    return hashlib.sha256(f"{identity}\0{live}".encode("utf-8")).hexdigest()[:16]


def check_records(
    records: Iterable[dict[str, Any]],
    ordered: list[Term],
    skip: Callable[[str, str], bool] = lambda _live, _source: False,
) -> tuple[int, list[dict[str, Any]]]:
    """How many translated lines were checked, and each one whose Japanese
    holds a term its English lacks, with the terms and a proposal.

    A proposal writes each term over its rendering: the whole English of a
    name that is only the term, the words most like the term, or a
    rendering another line of the term was found with. `skip` leaves out
    lines that hold no translation, given their English and Japanese.
    """
    records = [
        record
        for record in records
        if record["file"] not in UNSEEN_FILES
        and str(record["source"]) != str(record["live"])
        and str(record["live"]).strip()
        and not skip(str(record["live"]), str(record["source"]))
    ]
    words_of = corpus(str(record["live"]) for record in records)
    index = _by_first(ordered)
    found = []
    for record in records:
        source, live = str(record["source"]), str(record["live"])
        missing: list[tuple[Term, int, int]] = []
        for term, start, end in _hits(source, index):
            # A term the English still holds in Japanese is kept on purpose,
            # such as a plugin key in a note.
            if live.count(term.source) >= source.count(term.source):
                continue
            if not uses_term(live, term) and all(term != hit[0] for hit in missing):
                missing.append((term, start, end))
        if missing:
            line = _Line(
                live,
                _words(live),
                len(record["live_pointers"]) == 1
                and record["live_transform"] == "identity",
            )
            found.append((record, line, missing))
    renderings: dict[str, set[str]] = defaultdict(set)
    spans_by_line = []
    for record, line, missing in found:
        spans: list[tuple[int, int, Term]] = []
        for term, _start, _end in missing:
            if not term.replacement:
                continue
            span = _whole(record, line, term) or _rendering(
                line, term, words_of
            )
            if span and not any(span[0] < end and start < span[1] for start, end, _t in spans):
                spans.append((*span, term))
                rendering = line.live[span[0] : span[1]]
                if rendering[:1].isupper():
                    renderings[term.source].add(" ".join(rendering.split()))
        spans_by_line.append(spans)
    flagged = []
    for (record, line, missing), spans in zip(found, spans_by_line):
        for term, _start, _end in missing:
            if term.replacement and all(term != span[2] for span in spans):
                span = _learned(line, renderings[term.source], spans)
                if span:
                    spans.append((*span, term))
        flagged.append(
            {
                "key": line_key(record["identity"], line.live),
                "identity": record["identity"],
                "file": record["file"],
                "pointer": record["live_pointers"][0],
                "source": str(record["source"]),
                "live": line.live,
                "terms": [
                    {
                        "source": term.source,
                        "english": term.english,
                        "section": term.section,
                        "order": term.order,
                        "start": start,
                        "end": end,
                    }
                    for term, start, end in missing
                ],
                "proposal": _written(line, spans) if spans else None,
                # What fitting and checking a fix to its box needs.
                "record": {
                    key: record[key]
                    for key in (
                        "identity", "file", "source", "live", "event_code",
                        "live_pointers", "live_transform", "speaker",
                        "database_entity", "risky_context",
                    )
                    if key in record
                },
            }
        )
    return len(records), flagged


def fix_problems(
    record: dict[str, Any], text: str, layout: dict[str, Any]
) -> tuple[str, list[str]]:
    """A fix as DazedTL writes it, rewrapped to its box like a QA correction,
    and why it would fail to apply or break the line."""
    from util.rpgmaker_qa import _box, _fit, correction_problems

    box = _box(record, layout)
    problems = correction_problems(
        record["source"], record["live"], text, record.get("event_code"),
        record["live_pointers"], record["live_transform"], box=box,
    )
    return _fit(text, record["live"], box), problems


def scan(
    data_root: str | Path,
    glossary_text: str,
    layout: dict[str, Any],
    skip: Callable[[str, str], bool] = lambda _live, _source: False,
) -> dict[str, Any]:
    """Every translated line in the game's data whose Japanese holds a
    glossary term its English lacks, with a proposal that applies cleanly."""
    from util.rpgmaker_qa_manifest import build_manifest

    manifest = build_manifest(data_root, "release")
    checked, flagged = check_records(
        manifest["records"], terms(glossary_rows(glossary_text)), skip
    )
    for line in flagged:
        if line["proposal"]:
            fitted, problems = fix_problems(line["record"], line["proposal"], layout)
            line["proposal"] = None if problems else fitted
    return {
        "lines": checked,
        "flagged": len(flagged),
        "found": flagged[:LINE_LIMIT],
        "layout": layout,
    }


def apply_fixes(data_root: str | Path, fixes: list[dict[str, Any]]) -> list[str]:
    """Writes each fix's text over the English it was chosen for, in the
    data folder given, and returns the files it changed. A line that changed
    since stops the whole write."""
    from util.rpgmaker_qa import _operation_writes, _render_json_like, _set_pointer

    root = Path(data_root).resolve()
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fix in fixes:
        by_file[fix["record"]["file"]].append(fix)
    rendered = {}
    for name, rows in sorted(by_file.items()):
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe glossary fix target: {name}")
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        for fix in rows:
            record = fix["record"]
            operation = {
                "identity": record["identity"],
                "live_pointers": record["live_pointers"],
                "live_transform": record["live_transform"],
                "expected": record["live"],
                "replacement": fix["text"],
            }
            try:
                writes = _operation_writes(document, operation)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"A line in {name} changed since the glossary check; check again."
                ) from exc
            for pointer, value in writes:
                _set_pointer(document, pointer, value)
        rendered[path] = _render_json_like(raw, document)
    for path, raw in rendered.items():
        path.write_bytes(raw)
    return sorted(by_file)
