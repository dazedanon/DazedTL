"""Whether text still holds Japanese to translate: the one rule the RPG Maker
MV/MZ engine sends text by and Guided's line counts read a line as left by
(translation/file_lines.py), and that event-text tools such as custom
patterns and fitting share.

Japanese to translate is a Japanese letter (kana, kanji or half-width kana)
outside control codes and their arguments. Punctuation and brackets are not
letters: a translation keeps 【】 labels and 「」, and a game writes its own
English inside them, such as "【Saving beforehand is recommended】", so text
holding only those reads finished. A control code's argument, such as
\\SA[びっくり] or \\fn[和風], names a plugin's asset or setting, never text,
so a translation that keeps one reads finished too.
"""

import re

from util.runtime_text import without_control_codes

# Japanese letters: 々〆〇, kana without the voicing mark ゛ and the middle dot
# and long vowel mark (・ー), which English uses as bullets and dashes, kanji
# and half-width kana.
LETTERS = re.compile(
    r"[々-〇぀-゚゜-ヺㇰ-ㇿ㐀-䶿"
    r"一-鿿豈-﫿ｦ-ﾟ]"
)


def holds_source(text) -> bool:
    """Whether *text* still holds Japanese letters outside control codes."""
    return isinstance(text, str) and bool(LETTERS.search(without_control_codes(text)))
