"""Whether text still holds Japanese to translate: the one rule the RPG Maker
MV/MZ engine sends text by and Guided's line counts read a line as left by
(translation/file_lines.py), and that event-text tools such as custom
patterns and fitting, Text QA and the playtest share.

Japanese to translate is a Japanese letter (kana, kanji or half-width kana)
outside control codes and their arguments. Punctuation and brackets are not
letters: a translation keeps 【】 labels and 「」, and a game writes its own
English inside them, such as "【Saving beforehand is recommended】", so text
holding only those reads finished. A control code's argument, such as
\\SA[びっくり] or \\fn[和風], names a plugin's asset or setting, never text,
so a translation that keeps one reads finished too. Furigana is the exception:
its base is text the player reads, so \\rb[魔王,まおう] holds Japanese.
"""

import re
from collections import Counter

from util.runtime_text import without_control_codes

# Japanese letters: 々〆〇, kana, kanji and half-width kana. The middle dot
# and long vowel mark (・ー), which English uses as bullets and dashes, are not
# letters, nor are the voicing marks (゛゜, ﾞﾟ and their combining forms):
# in Japanese one always follows a kana, which reads as a letter itself, and
# alone it is a symbol, such as the eyes of the kaomoji (ﾟдﾟ).
KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LETTERS = re.compile(
    r"[\u3005-\u3007\u3041-\u3096\u309d-\u30fa\u31f0-\u31ff"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9d]"
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


def holds_source(text) -> bool:
    """Whether *text* still holds Japanese letters outside control codes,
    reading furigana as its base."""
    return isinstance(text, str) and bool(
        LETTERS.search(without_control_codes(furigana_base(text)))
    )


def left_in(source: str, translation: str) -> list[str]:
    """The Japanese a *translation* of *source* still holds, as runs of
    letters (holds_source's rule). A lone kana or mark that the source holds
    as often, never a kanji, is part of a symbol the translation keeps, such as
    the ﾉ and ゞ of a kaomoji or the 〇 of a censor mask (うん〇 -> sh〇t), so
    it is not left; asking again can only give it back."""
    kept = Counter(LETTERS.findall(without_control_codes(furigana_base(source))))
    left = []
    for run in _WORD.findall(without_control_codes(furigana_base(translation))):
        if len(run) == 1 and kept[run] > 0 and not KANJI.match(run):
            kept[run] -= 1
        else:
            left.append(run)
    return left
