"""Whether text still holds Japanese to translate: the one rule the RPG Maker
MV/MZ engine sends text by, the response check accepts a translation by,
Guided's run reuse answers a line by and Guided's line counts read a line as
left by (translation/file_lines.py), and that event-text tools such as custom
patterns and fitting, Text QA and the playtest share.

Japanese to translate is a Japanese letter (kana, kanji or half-width kana)
outside control codes and their arguments. Punctuation and brackets are not
letters: a translation keeps 【】 labels and 「」, and a game writes its own
English inside them, such as "【Saving beforehand is recommended】", so text
holding only those reads finished. A control code's argument, such as
\\SA[びっくり] or \\fn[和風], names a plugin's asset or setting, never text,
so a translation that keeps one reads finished too. Furigana is the exception:
its base is text the player reads, so \\rb[魔王,まおう] holds Japanese.

A value is read against the Japanese source it was translated from where one
is known (`japanese_left`): a lone kana or mark the source holds is part of a
symbol the translation keeps, such as a kaomoji's ﾉ or a censor mask's 〇,
and a value given back unchanged is all left. Without a source, every
Japanese letter is left (`holds_source`).
"""

import re
import unicodedata
from collections import Counter

from util.runtime_text import (
    HALF_WIDTH_LETTERS,
    without_control_codes,
    without_protected_codes,
)

# Japanese letters: 々〆〇, kana, kanji and half-width kana. The middle dot
# and long vowel mark (・ー), which English uses as bullets and dashes, are not
# letters, nor are the voicing marks (゛゜, ﾞﾟ and their combining forms):
# in Japanese one always follows a kana, which reads as a letter itself, and
# alone it is a symbol, such as the eyes of the kaomoji (ﾟдﾟ).
KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LETTERS = re.compile(
    r"[\u3005-\u3007\u3041-\u3096\u309d-\u30fa\u31f0-\u31ff"
    rf"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff{HALF_WIDTH_LETTERS}]"
)
_WORD = re.compile(LETTERS.pattern + "+")

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


def japanese_left(text, source=None) -> list[str]:
    """The Japanese *text* still holds, as runs of letters outside control
    codes, reading furigana as its base. Given the Japanese *source* it was
    translated from, a lone kana or mark that the source holds as often, never
    a kanji, is part of a symbol the translation keeps, such as the ﾉ and ゞ of
    a kaomoji or the 〇 of a censor mask (うん〇 -> sh〇t), so it is not left;
    asking again can only give it back. A value that gives back the source's
    letters and digits unchanged, such as え？ for え？, translated nothing and
    keeps no symbol: all its Japanese is left, as it is without a source."""
    if not isinstance(text, str):
        return []
    spoken = _spoken(text)
    runs = _WORD.findall(spoken)
    if not runs or not isinstance(source, str) or source == text:
        return runs
    source = _spoken(source)
    if _letters_and_digits(source) == _letters_and_digits(spoken):
        return runs
    kept = Counter(LETTERS.findall(source))
    found = []
    for run in runs:
        if len(run) == 1 and kept[run] > 0 and not KANJI.match(run):
            kept[run] -= 1
        else:
            found.append(run)
    return found


def holds_source(text) -> bool:
    """Whether *text* still holds Japanese, read without a source
    (`japanese_left`): the source itself, or a value whose source is
    unknown."""
    return bool(japanese_left(text))


def _spoken(text: str) -> str:
    """*text* as the player reads it: furigana as its base, without control
    codes, other protected codes or their placeholders in a request."""
    return without_control_codes(without_protected_codes(furigana_base(text)))


def _letters_and_digits(text: str) -> list[str]:
    """The letters and digits of *text* in compatibility form, so a full-width
    or half-width spelling reads the same."""
    return [
        char
        for char in unicodedata.normalize("NFKC", text)
        if unicodedata.category(char)[0] in "LN"
    ]
