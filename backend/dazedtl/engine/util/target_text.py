"""How a translation's text is written for its target language: the cleanup
every reply goes through, the punctuation a run writes for text it never
sends, and how a translated name is capitalized. Each rule is defined here
once and reads the target's script (util/languages).

A target written with Latin letters, such as English, is written as it always
was: Japanese punctuation a model or a game leaves takes a Latin form (。 a
period, 【】 square brackets, corner brackets ASCII quotes when convertQuotes
is on), the small っ and ッ that mark a stop are left out, other small kana
in a line holding no full-size kana or kanji are written as the Latin letters
they sound, typographic apostrophes and dialogue tildes take the forms
Japanese fonts draw well, a long vowel mark run after a kana letter repeats
the letter, and names are title-cased.

Chinese and Japanese are written with full-width punctuation, so a
translation into them keeps 。、「」【】, the small っ, quotes and tildes as
the model wrote them: only a reply's scaffolding (a "Translation:" label,
code fences) and runaway repetition are cleaned, and text the run never sends
stays exactly as the game wrote it.
"""

import re
from functools import lru_cache

from util.languages import JAPANESE_LETTERS, LATIN, script, target_uses_cjk
from util.runtime_text import PROTECTED_PATTERNS, split_protected_codes


def full_width(language) -> bool:
    """Whether a translation into *language* is written with full-width
    punctuation (Chinese, Japanese), which it keeps as written."""
    return target_uses_cjk(language)


def convert_corner_brackets(text, enabled=True):
    """Replace Japanese quotation marks with ASCII double quotes when enabled."""
    if not enabled or not isinstance(text, str):
        return text
    return (
        text.replace("「", '"')
        .replace("」", '"')
        .replace("『", '"')
        .replace("』", '"')
        .replace("〝", '"')
        .replace("〞", '"')
        .replace("〟", '"')
    )


def corner_quotes(text, language, enabled=True):
    """*text* with corner brackets as ASCII quotes when *enabled* and the
    target writes Latin punctuation; a full-width target keeps 「」."""
    return convert_corner_brackets(text, enabled and not full_width(language))


# The full stop 。 in a Latin-script translation. Its writers have kept three
# rules, and each keeps its own, so Japanese to English output stays as it
# was: every 。 a period (PERIOD, the reply cleanup), left out after a mark
# that ends a sentence and otherwise a period (AFTER_SENTENCE, text the run
# never sends, english_punctuation), or left out after "..." and otherwise
# kept (AFTER_ELLIPSIS, MV/MZ messages as their parser writes them).
PERIOD = "period"
AFTER_SENTENCE = "sentence"
AFTER_ELLIPSIS = "ellipsis"
_FULL_STOPS_AFTER_ELLIPSIS = re.compile(r"\.\.\.(。)+")
# Marks that already end a sentence, so a full stop after one adds nothing.
SENTENCE_ENDS = frozenset(".…‥!?♪♡♥～〜~")


def full_stops(text, language, rule):
    """*text* with each 。 written by *rule*, PERIOD or AFTER_ELLIPSIS, for a
    Latin-script *language*; a full-width target keeps them.
    english_punctuation writes AFTER_SENTENCE, which reads the marks around
    the codes it keeps."""
    if full_width(language) or not isinstance(text, str):
        return text
    if rule == PERIOD:
        return text.replace("。", ".")
    if rule == AFTER_ELLIPSIS:
        return _FULL_STOPS_AFTER_ELLIPSIS.sub("...", text)
    raise ValueError(f"No full stop rule named {rule!r}.")


# Japanese punctuation a game writes around text with no Japanese letters,
# such as ・・・・・。 or ？, and the English a translation writes for it. A
# middle dot alone stays: English uses it as a bullet.
_ENGLISH_MARKS = str.maketrans({"！": "!", "？": "?", "（": "(", "）": ")"})
_MIDDLE_DOTS = re.compile(r"・(?: ?・)+")
_JAPANESE_COMMA = re.compile(r"、(?=[^\s\"')」』])")


def english_punctuation(text, quotes=True):
    """Text that holds no Japanese letters with the Japanese punctuation
    around it in English: dotted ellipses (・・・) as periods, ！？（） and 、
    as ASCII, 。 as a period unless the sentence already ends, and corner
    brackets as quotes when *quotes* is on (convert_corner_brackets). Codes
    keep their arguments exactly."""
    parts = split_protected_codes(text)
    last = ""
    for index in range(0, len(parts), 2):
        run = _MIDDLE_DOTS.sub(lambda dots: dots[0].replace("・", "."), parts[index])
        run = convert_corner_brackets(run.translate(_ENGLISH_MARKS), quotes)
        run = _JAPANESE_COMMA.sub(", ", run).replace("、", ",")
        written = []
        for char in run:
            if char == "。":
                if last in SENTENCE_ENDS:
                    continue
                char = "."
            written.append(char)
            if not char.isspace():
                last = char
        parts[index] = "".join(written)
    return "".join(parts)


# The one definition of what a translation writes for text that holds no
# source letters, such as ・・・・・。, ？ or 「……」, which a run never sends.
# A full-width target keeps it exactly as the game wrote it. For a Latin
# target its writers have always differed, and each keeps its own form, so
# Japanese to English output stays as it was:
# - ROWS: a parser writing message, scroll and choice rows it never sends
#   (MV/MZ), and an Assistant-led run writing the lines no request sends
#   (translation/results unsent_line): every mark in its English form
#   (english_punctuation).
# - SKIPPED: translate() handing back a value it skips: the reply cleanup
#   (clean_reply), so ・・・ and ！？ stay full-width, 。 is always a period,
#   【】 become [] and the small っ is left out.
# - BRACKETS: translate() handing back a value of ellipses and long vowel
#   marks alone, such as 「………」: its corner brackets only.
# Corner brackets become quotes in ROWS and BRACKETS by *quotes*
# (convertQuotes), and in SKIPPED only when *quotes* is on, as translate()
# asks for a batch's lines but not for a value sent alone.
ROWS = "rows"
SKIPPED = "skipped"
BRACKETS = "brackets"


def unsent_text(text, language, form, quotes=True):
    """*text*, which holds no source letters, as a translation into
    *language* writes it, in the writer's *form* (ROWS, SKIPPED, BRACKETS)."""
    if not isinstance(text, str) or full_width(language):
        return text
    if form == ROWS:
        return english_punctuation(text, quotes)
    if form == SKIPPED:
        return convert_corner_brackets(clean_reply(text, language), quotes)
    if form == BRACKETS:
        return convert_corner_brackets(text, quotes)
    raise ValueError(f"No unsent text form named {form!r}.")


_DIALOGUE_TYPOGRAPHY_RE = re.compile(
    # Leave runtime tokens, URLs, paths and inline code byte-for-byte intact.
    r"(?P<protected>" + "|".join(PROTECTED_PATTERNS) +
    r'|\b[\w+.-]+://[^\s"<>]+|\bwww\.[^\s"<>]+'
    r'|(?:[A-Za-z]:[\\/]|(?<!\w)~[\\/]|\.{0,2}/)[^\s"<>]+'
    r'|`[^`\r\n]+`)'
    r"|(?P<apostrophe>[‘’‛ʼ＇])"
    # A drawn-out word ending, not an approximation, range or bitwise operator.
    r"|(?<=[^\W\d_])(?P<tail>[~〜]+)"
    r"(?:(?=__PROTECTED_\d+__)|(?![\w~〜]|\.[A-Za-z0-9]))"
)


def normalize_dialogue_typography(text, language=None):
    """Use font-safe apostrophes and centered dialogue tildes in decoded
    prose of a Latin-script target; *language* None reads as English, the
    default target. A full-width target keeps its marks."""
    if (
        not isinstance(text, str)
        or full_width(language)
        or not any(char in text for char in "~〜‘’‛ʼ＇")
    ):
        return text
    return _DIALOGUE_TYPOGRAPHY_RE.sub(
        lambda match: (
            match.group("protected")
            or ("'" if match.group("apostrophe") else "～" * len(match.group("tail")))
        ),
        text,
    )


# Typographic quotes a reply's JSON may hold, as ASCII apostrophes, so a
# model that writes “ for " in a value leaves the JSON readable.
_REPLY_QUOTES = {
    0x201C: "'",  # “ left double quotation mark
    0x201D: "'",  # ” right double quotation mark
    0xFF02: "'",  # ＂ fullwidth quotation mark
    0x2018: "'",  # ‘ left single quotation mark
    0x2019: "'",  # ’ right single quotation mark
    0x201B: "'",  # ‛ single high-reversed-9 quotation mark
    0x02BC: "'",  # ʼ modifier letter apostrophe
    0xFF07: "'",  # ＇ fullwidth apostrophe
}


def reply_quotes(text, language):
    """A reply's typographic quotes as ASCII apostrophes for a Latin-script
    target; a full-width target keeps them."""
    return text if full_width(language) else text.translate(_REPLY_QUOTES)


# Reply scaffolding every target leaves out: code fences around the JSON.
_FENCES = ("```json", "```")
_RUNAWAY = re.compile(r"(.)\s*\1(?:\s*\1){" + str(20 - 1) + r",}")


def _without_label(text, language):
    """*text* without a reply's "Translation:" label, which every target
    leaves out."""
    for label in (f"{language} Translation: ", "Translation: "):
        text = text.replace(label, "")
    return text


# Marks a Latin-script translation writes in another form: an em dash as the
# horizontal bar Japanese fonts draw, 【】 as square brackets and é as e.
_LATIN_MARKS = (("—", "―"), ("】", "]"), ("【", "["), ("é", "e"))


def _without_stops(text):
    """*text* with the small っ and ッ that mark a stop left out."""
    return text.replace("っ", "").replace("ッ", "")


def _latin_marks(text, language):
    """*text* with the small っ and ッ that mark a stop left out, 。 a period
    and _LATIN_MARKS in their Latin forms."""
    text = _without_stops(text)
    text = full_stops(text, language, PERIOD)
    for mark, latin_form in _LATIN_MARKS:
        text = text.replace(mark, latin_form)
    return text


# Small kana a model leaves in a moan as a dragged-out vowel, such as
# milk゛ぅぅぅ♡, as the Latin letters they sound (Len's game-translation
# skill, sfx-onomatopoeia.md), and the small ｯ, っ and ッ that mark a stop
# left out, as the cleanup always leaves out っ and ッ (_latin_marks), where
# Len's skill writes a hyphen after a letter.
_SMALL_KANA = str.maketrans(
    {
        **dict(zip("ぁぃぅぇぉ", "aiueo")),
        **dict(zip("ァィゥェォ", "aiueo")),
        **dict(zip("ｧｨｩｪｫ", "aiueo")),
        **dict(zip("ゃゅょ", ("ya", "yu", "yo"))),
        **dict(zip("ャュョ", ("ya", "yu", "yo"))),
        **dict(zip("ｬｭｮ", ("ya", "yu", "yo"))),
        "ゎ": "wa",
        "ヮ": "wa",
        "ｯ": "",
        "っ": "",
        "ッ": "",
    }
)
_SMALL_KANA_LETTERS = "".join(map(chr, _SMALL_KANA))
_SMALL_KANA_LETTER = re.compile(f"[{_SMALL_KANA_LETTERS}]")
# A Japanese letter other than a small kana: a full-size kana or a kanji.
_FULL_SIZE = re.compile(f"(?![{_SMALL_KANA_LETTERS}])[{JAPANESE_LETTERS}]")


def _line_stranded_kana(parts, language):
    """The runs of one translated line split around its codes (_runs), with
    their small kana as Latin letters (_SMALL_KANA) for a Latin-script
    *language*, unless the line's text holds a full-size kana or kanji: that
    is a real miss, which goes back to the model rather than be papered
    over. The ideographic space stays, a pause between gasps."""
    text = "".join(parts[0::2])
    if (
        script(language) == LATIN
        and _SMALL_KANA_LETTER.search(text)
        and not _FULL_SIZE.search(text)
    ):
        parts[0::2] = [part.translate(_SMALL_KANA) for part in parts[0::2]]
    return parts


def stranded_kana(line, language):
    """One translated *line* of a reply with its stranded small kana as
    Latin letters (_line_stranded_kana); Guided sends codes masked, so the
    line is all text."""
    if not isinstance(line, str):
        return line
    return _line_stranded_kana([line], language)[0]


def kana_written(text, language, protected=()):
    """One line of a translation into *language* with only the kana the
    reply cleanup writes otherwise changed, as translated_line writes them:
    for a target written without full-width punctuation the small っ and ッ
    left out, and for a Latin-script one its stranded small kana as Latin
    letters. Codes and the literal *protected* tokens keep their spelling.
    The content check reads a line that never went through clean_reply so."""
    if not isinstance(text, str) or full_width(language):
        return text
    parts = _runs(text, protected)
    parts[0::2] = map(_without_stops, parts[0::2])
    return "".join(_line_stranded_kana(parts, language))


def _settled(text, language, latin):
    """*text* with font-safe apostrophes and tildes for a Latin target, a
    character repeated more than 20 times cut to 20, and a long vowel mark
    run after a kana repeating it for a Latin target."""
    if latin:
        # Japanese fonts may give smart apostrophes fullwidth advances and
        # raise ~. Normalize prose before engine-specific line wrapping
        # measures the output.
        text = normalize_dialogue_typography(text, language)

    # Remove Repeating Characters
    text = _RUNAWAY.sub(lambda match: match.group(0).replace(" ", "")[:20], text)

    # Elongate Long Dashes (Since GPT Ignores them...)
    return elongate_characters(text) if latin else text


def clean_reply(text, language):
    """A reply cleaned for the target *language*: without its "Translation:"
    label and code fences, and a character repeated more than 20 times cut
    to 20. For a Latin-script target its marks also take Latin forms: the
    small っ and ッ that mark a stop are left out, 。 is a period, an em dash
    the horizontal bar Japanese fonts draw, 【】 square brackets and é plain
    e; apostrophes and tildes are made font-safe and a long vowel mark run
    after a kana repeats it. 「 and 」 stay, since quotes would break the JSON
    before it is read; they become quotes per line once it is, and its
    lines' stranded small kana are repaired once it is read
    (stranded_kana)."""
    latin = not full_width(language)
    text = _without_label(text, language)
    if latin:
        text = _latin_marks(text, language)
    for fence in _FENCES:
        text = text.replace(fence, "")
    return _settled(text, language, latin)


def _runs(text, protected):
    """*text* split around its codes (util/runtime_text PROTECTED_PATTERNS)
    and the literal *protected* tokens: the text between them at even
    indexes, each code or token at the odd index after it."""
    tokens = tuple(sorted({token for token in protected if token}, key=len, reverse=True))
    if not tokens:
        return split_protected_codes(text)
    parts, start = [], 0
    for match in _token_pattern(tokens).finditer(text):
        parts += [text[start : match.start()], match.group()]
        start = match.end()
    return parts + [text[start:]]


@lru_cache(maxsize=4096)
def _token_pattern(tokens):
    """The pattern _runs splits text with: the literal *tokens*, longest
    first, then the codes."""
    return re.compile("|".join([*map(re.escape, tokens), *PROTECTED_PATTERNS]))


def translated_line(text, language, quotes=True, protected=()):
    """One line of a translation into *language* as Guided writes every line
    of a reply: cleaned as clean_reply cleans the reply, apart from the code
    fences around a reply, then with typographic quotes as apostrophes (reply_quotes) and
    corner brackets as quotes when *quotes* (corner_quotes, convertQuotes).
    Codes and the literal *protected* tokens keep their spelling, as Guided
    sends codes masked, so the reply never holds them, and the line's small
    kana are repaired by its text around them (_line_stranded_kana)."""
    if not isinstance(text, str):
        return text
    latin = not full_width(language)
    parts = _runs(text, protected)
    for index in range(0, len(parts), 2):
        run = _without_label(parts[index], language)
        if latin:
            run = _latin_marks(run, language)
        parts[index] = _settled(run, language, latin)
    _line_stranded_kana(parts, language)
    for index in range(0, len(parts), 2):
        run = reply_quotes(parts[index], language)
        parts[index] = corner_quotes(run, language, quotes)
    return "".join(parts)


def elongate_characters(text):
    """Replace ー sequences with elongated characters"""
    # Define a pattern to match one character followed by two or more ー characters.
    # The lookbehind is restricted to non-ー Japanese/CJK characters so that:
    #   - standalone ー separators (e.g. "ーーーーーーーーーー") are left untouched
    #   - ー sequences preceded by a JSON quote or other non-Japanese char are not corrupted
    pattern = r"(?<=([぀-ゟ゠-・ヽ-ヿ一-鿯｡-ﾟ]))ー{2,}"

    # Define a replacement function that elongates the captured character
    def repl(match):
        char = match.group(1)  # The character before the ー sequence
        count = len(match.group(0)) - 1  # Number of ー characters
        return char * count  # Replace ー sequence with the character repeated

    # Use re.sub() to replace the pattern in the text
    return re.sub(pattern, repl, text)


def title_case(name, language):
    """A translated name capitalized for a Latin-script *language*, word by
    word (str.title); a name in another script stays as written."""
    if not isinstance(name, str) or script(language) != LATIN:
        return name
    return name.title()


_LATIN_NAME = re.compile(r"([a-zA-Z？?])")


def name_translated(name, language) -> bool:
    """Whether a reply for a name reads as a translation into *language*: a
    Latin-script name holds a letter or a question mark, as ？？？ for an
    unknown speaker; a name in another script holds anything at all."""
    if script(language) == LATIN:
        return _LATIN_NAME.search(name) is not None
    return bool(str(name).strip())
