"""Whether text still holds source text to translate: the one rule the RPG Maker
MV/MZ engine sends text by, the response check accepts a translation by,
Guided's run reuse answers a line by and Guided's line counts read a line as
left by (translation/file_lines.py), and that event-text tools such as custom
patterns and fitting, Text QA and the playtest share.

The source language is the run's (util/languages), Japanese by default.
Japanese to translate is a Japanese letter (kana, kanji or half-width kana)
outside control codes and their arguments. Punctuation and brackets are not
letters: a translation keeps 【】 labels and 「」, and a game writes its own
English inside them, such as "【Saving beforehand is recommended】", so text
holding only those reads finished. A control code's argument, such as
\\SA[びっくり] or \\fn[和風], names a plugin's asset or setting, never text,
so a translation that keeps one reads finished too. Furigana is the exception:
its base is text the player reads, so \\rb[魔王,まおう] holds Japanese.

English to translate is a Latin letter outside control codes, markup tags
such as <br> and {name} placeholders.

A value is read against the source it was translated from where one is known
(`source_left`): a lone kana, mark or letter the source holds is part of a
symbol the translation keeps, such as a kaomoji's ﾉ or a censor mask's 〇,
as is an abbreviation a Latin source writes in capitals, such as HP, and a
value given back unchanged is all left. Read against its source, a
translation into a language that shares the source's kanji, Japanese into
Chinese, holds Japanese left only where it holds kana. Without a source,
every letter of the source language is left (`holds_source`): the value may
be text never translated. A message's row is read against the whole
message's source (`row_left`), and what a player reads as left drops a
Latin source's abbreviations (`words_left`).
"""

import re
import unicodedata
from collections import Counter
from functools import lru_cache

from util import languages
from util.languages import ENGLISH, JAPANESE, KANJI
from util.runtime_text import without_control_codes, without_protected_codes

# Japanese letters (util/languages JAPANESE_LETTERS).
LETTERS = re.compile(f"[{languages.JAPANESE_LETTERS}]")
_LETTERS = {JAPANESE: LETTERS, ENGLISH: re.compile(f"[{languages.LATIN_LETTERS}]")}
_WORDS = {
    language: re.compile(letters.pattern + "+") for language, letters in _LETTERS.items()
}
_MARKUP = re.compile(languages.MARKUP)


def letters(language=None) -> re.Pattern[str]:
    """The pattern of one letter of the source *language*, the active
    source by default."""
    return _LETTERS[language or languages.active_source()]

# Furigana: a ruby code \r[base,reading] or \rb[base,reading], in any case and
# with any run of slashes, and a curly {base|reading} print the reading above
# the base.
RUBY = re.compile(r"[\\]+[rR][bB]?\[(.*?),.*?\]")
CURLY_RUBY = re.compile(r"\{([^|{}]+)\|[^|{}]+?\}")


def furigana_base(text: str) -> str:
    """*text* with each furigana replaced by its base, the text the engine
    sends for translation."""
    if "\\" in text:
        text = RUBY.sub(r"\1", text)
    return CURLY_RUBY.sub(r"\1", text) if "{" in text else text


def source_left(text, source=None, language=None, target=None) -> list[str]:
    """The source text *text* still holds, as runs of letters of the source
    *language* (the active source by default) outside control codes, reading
    furigana as its base. Given the *source* it was translated from, a lone
    kana, mark or letter that the source holds as often, never a kanji, is
    part of a symbol the translation keeps, such as the ﾉ and ゞ of a kaomoji
    or the 〇 of a censor mask (うん〇 -> sh〇t), so it is not left; asking
    again can only give it back. So is an abbreviation in capitals that a
    Latin source holds as often, such as the HP of HPを50回復する for
    Restores 50 HP. A value that gives back the source's letters
    and digits unchanged, such as え？ for え？, translated nothing and keeps no
    symbol: all its source text is left, as it is without a source.

    A translation into *target*, the active target by default, that shares
    the source's kanji (util/languages `shares_kanji`: Japanese into Chinese)
    holds Japanese left only in runs with kana: its hanzi are its own text,
    and a name such as 魔王 is written the same in both. Without a source a
    value may be text never translated, so every letter is left."""
    if not isinstance(text, str):
        return []
    language = language or languages.active_source()
    spoken = _spoken(text, language)
    runs = _WORDS[language].findall(spoken)
    if not runs or not isinstance(source, str):
        return runs
    found = _left(runs, spoken, source, language)
    if languages.shares_kanji(language, target):
        return [run for run in found if languages.KANA.search(run)]
    return found


def row_left(row, source=None, language=None, target=None) -> list[str]:
    """`source_left` for one row of a message read against the *source* of
    the whole message: a row that gives back one of its rows unchanged
    translated nothing, as a value that gives back its source does."""
    if isinstance(row, str) and isinstance(source, str) and row != source:
        language = language or languages.active_source()
        letters = tuple(_letters_and_digits(_spoken(row, language)))
        if letters and letters in _rows_letters(source, language):
            source = row
    return source_left(row, source, language, target)


# Fitting reads each row of a message against its source, at each width it
# tries.
@lru_cache(maxsize=4096)
def _rows_letters(source: str, language: str) -> frozenset[tuple[str, ...]]:
    """The letters and digits of each row of *source*."""
    return frozenset(
        tuple(_letters_and_digits(_spoken(part, language)))
        for part in source.split("\n")
    )


def holds_source(text, language=None) -> bool:
    """Whether *text* still holds text in the source *language*, read
    without a source (`source_left`): the source itself, or a value whose
    source is unknown."""
    return bool(source_left(text, language=language))


# A word a player reads in a Latin source (util/languages, the playtest's
# pattern): an abbreviation a game keeps in capitals, such as HP or the
# currency unit G, reads the same in any language.
_WORD = re.compile(languages.source_pattern("playtest", ENGLISH))


def words_left(text, source=None, language=None, target=None) -> list[str]:
    """The source text a player reads as left in *text*, a value or a row of
    a message read against the *source* of the whole message (`row_left`):
    for a Latin source only its words, so a value of abbreviations, such as
    HP or the currency unit G, reads finished. Fitting, Text QA's
    never-translated report and the playtest read text left by it."""
    language = language or languages.active_source()
    found = row_left(text, source, language, target)
    if language == JAPANESE:
        return found
    return [run for run in found if _WORD.search(run)]


def _left(runs: list[str], spoken: str, source: str, language: str) -> list[str]:
    """The *runs* of *spoken*, a value read as the player reads it, that
    *source* does not keep (`source_left`)."""
    source = _spoken(source, language)
    if _letters_and_digits(source) == _letters_and_digits(spoken):
        return runs
    kept = Counter(_LETTERS[language].findall(source))
    # Abbreviations a Latin source holds, such as HP or NPC, which a
    # translation into another script keeps as written.
    abbreviations = Counter(
        word for word in _WORDS[language].findall(source)
        if language != JAPANESE and word.isupper()
    )
    found = []
    for run in runs:
        if len(run) == 1 and kept[run] > 0 and not KANJI.match(run):
            kept[run] -= 1
        elif abbreviations[run] > 0:
            abbreviations[run] -= 1
        else:
            found.append(run)
    return found


def _spoken(text: str, language: str) -> str:
    """*text* as the player reads it: furigana as its base, without control
    codes, other protected codes or their placeholders in a request, and
    for a Latin source without markup tags and {name} placeholders."""
    text = without_control_codes(without_protected_codes(furigana_base(text)))
    return _MARKUP.sub("", text) if language != JAPANESE else text


def _letters_and_digits(text: str) -> list[str]:
    """The letters and digits of *text* in compatibility form, so a full-width
    or half-width spelling reads the same."""
    return [
        char
        for char in unicodedata.normalize("NFKC", text)
        if unicodedata.category(char)[0] in "LN"
    ]
