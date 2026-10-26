"""Line wrapping for translated text: the width rule fits count by (`cells`)
and the rule each target breaks its lines by (`Words`).

A target written with spaces between words, such as English, breaks at its
spaces. Chinese and Japanese are written without them, so their text breaks
between characters by the Japanese line-break rules: no line starts with
closing punctuation, 。、ー, a small kana or the like, no line ends with an
opening bracket, and a control code, a half-width word such as HP and a run
of dots each stay whole. The target is the run's (the ``language``
environment variable) unless a caller names one.
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from util.languages import target_uses_cjk

# Wolf / RPG Maker inline codes that do not occupy visible box width.
_WOLF_INLINE_VISIBLE_STRIP = re.compile(
    r"[\\]+(?:"
    r"r\[[^\]]*\]|"
    r"c(?:self)?\[[^\]]*\]|"
    r"f\[[^\]]*\]|"
    r"[A-Za-z]+\[[^\]]*\]|"
    r"\^|"
    r"[ @<>\-]|"
    r"[A-Za-z]"
    r")"
)
_WOLF_CODE_PLACEHOLDER = re.compile(r"__WOLF_CODE_\d+__")
# The environment variable that carries a run's target language.
TARGET_ENV = "language"


def visible_text(text: str) -> str:
    """
    The characters of *text* a window draws, without inline control codes.

    Handles Wolf ``\\f[N]``, ``\\c[N]``, ruby ``\\r[...]``, and legacy RPG Maker
    color codes so wrap-width checks match in-game bulletin / message boxes.
    """
    if not text:
        return ""
    cleaned = _WOLF_INLINE_VISIBLE_STRIP.sub("", text)
    cleaned = _WOLF_CODE_PLACEHOLDER.sub("", cleaned)
    cleaned = re.sub(r"[\\]+[cC]\[\d+\]", "", cleaned)
    cleaned = re.sub(r"[\\]+[fF](?:\[\d+\])?", "", cleaned)
    cleaned = re.sub(r"[\\]+.", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@lru_cache(maxsize=1 << 12)
def cells(character: str) -> int:
    """The half-width cells *character* takes, the unit Line widths count in.
    Games draw text in Japanese fonts, which draw full-width characters, and
    ones of ambiguous width other than letters, full width: MV/MZ's and VX
    Ace's fonts draw ♥, … and ① so, which captures of Fuuma Chronicle
    confirmed, while accented, Greek and Cyrillic letters, such as é, stay
    half width (MV/MZ's M+ and VX Ace's VL Gothic draw them so). Other
    symbols, such as ❤ and ✓, are glyphs those fonts lack, which the game
    draws from a fallback font at least full width; Latin-1's, such as ©, the
    fonts draw half width. Combining marks and format characters, such as the
    emoji selector after ❤️, take no room of their own."""
    category = unicodedata.category(character)
    if category in ("Mn", "Me", "Cf"):
        return 0
    width = unicodedata.east_asian_width(character)
    if (
        width in "FW"
        or (width == "A" and not category.startswith("L"))
        or (width == "N" and category == "So" and ord(character) > 0xFF)
    ):
        return 2
    return 1


def text_cells(text: str) -> int:
    """The cells *text* takes, each character as :func:`cells` counts it."""
    return sum(cells(character) for character in text)


def breaks_characters(target=None) -> bool:
    """Whether text in *target*, the run's target language by default, breaks
    between characters: Chinese and Japanese, which are written without
    spaces. Any other target breaks at its spaces."""
    return target_uses_cjk(os.getenv(TARGET_ENV) if target is None else target)


def _get_visible_length(text: str) -> int:
    """The visible length of text, ignoring inline control codes (see
    :func:`visible_text`), in characters: what the engines other than RPG
    Maker have always counted text that breaks at its spaces in, so its
    lines stay as they were. RPG Maker counts every target in cells
    (util.rpgmaker_rewrap.visible_width)."""
    return len(visible_text(text))


def _visible_cells(text: str) -> int:
    """The visible width of text, ignoring inline control codes, in cells
    (see :func:`cells`): what text that breaks between characters is
    measured in."""
    return text_cells(visible_text(text))


def _measure(characters: bool):
    return _visible_cells if characters else _get_visible_length


def max_line_visible_length(text: str, target=None) -> int:
    """Longest visible line length in *text* (handles ``\\r`` / ``\\n``), as
    :func:`wrapText` measures text in *target*."""
    if not isinstance(text, str) or not text:
        return 0
    measure = _measure(breaks_characters(target))
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n") if normalized else [""]
    if not lines:
        return measure(normalized)
    return max(measure(line) for line in lines)


# ------------------------------------------------------------------- words

# Characters a line does not start with where they follow text directly: the
# Japanese line-start rules' closing brackets and quotes, full stops, commas
# and middle dots, iteration marks, the long vowel mark, small kana, ellipses,
# dashes and wave dashes and sentence marks; with them the marks that trail a
# word, such as ♪, ♥ and %, and the list marks, which start a line only
# after a space or a row break.
_NO_START = frozenset(
    "、。，．,.・：；:;？！?!‼⁇⁈⁉"
    ")]}）］｝〕〉》」』】〙〗〟’”｠»"
    "ゝゞヽヾ々〻ー‐゠–\u2014〜～~…‥―"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ"
    "ｧｨｩｪｫｬｭｮｯｰ"
    "%％♪♥♡❤★☆●◆◇■□※•゛゜"
)
# Characters a line does not end with: opening brackets and quotes.
_NO_END = frozenset("([{（［｛〔〈《「『【〘〖〝‘“｟«")
# A control code, taken whole: its letters with an argument in brackets or a
# name in angle brackets, as RPG Maker reads every letter of an escape, or a
# mark such as a wait (\.).
_CODE = re.compile(
    r"[\\]+(?:[A-Za-z_][A-Za-z0-9_]*(?:\[(?:[^\[\]]|\[[^\]]*\])*\]|<[^<>\n]*>)?"
    r"|[^\sA-Za-z0-9_])"
)
# Codes that go with the text before them: waits (\. \|), waiting for input
# (\!) and closing the window without it (\^). Other codes go with the text
# after them, such as a colour with the word it colours.
_TRAILING_CODE = re.compile(r"[\\]+[.|!^]")


@dataclass(frozen=True)
class Words:
    """Text as the pieces its lines break between, each with its width, and
    what is written between two pieces that share a line, with its width.

    Text that breaks at its spaces breaks between its words, written with one
    space between. Text that breaks between characters breaks between them
    (see :func:`_clusters`), or at a space or a row break it holds; a row
    break is written as nothing between full-width characters, as Japanese
    and Chinese are written, and as a space between half-width ones."""

    words: list[str]
    sizes: list[int]
    spaces: list[str]
    gaps: list[int]

    def line(self, start: int, end: int) -> str:
        """``words[start:end]`` written on one line."""
        return self.words[start] + "".join(
            self.spaces[index] + self.words[index] for index in range(start + 1, end)
        )

    def part(self, start: int, end: int) -> "Words":
        """``words[start:end]`` on their own."""
        return Words(
            self.words[start:end],
            self.sizes[start:end],
            [""] + self.spaces[start + 1 : end],
            [0] + self.gaps[start + 1 : end],
        )


def _words(text: str, measure, characters: bool, glue=None) -> Words:
    """*text* as the pieces its lines break between, each as wide as
    *measure* counts it; between characters when *characters*, where a piece
    the pattern *glue* matches at its start stays with the one before."""
    if not characters:
        words = text.split()
        joins = max(0, len(words) - 1)
        return Words(
            words,
            [measure(word) for word in words],
            [""] + [" "] * joins if words else [],
            [0] + [1] * joins if words else [],
        )
    words: list[str] = []
    spaces: list[str] = []
    before = ""
    for piece, first, last, space in _clusters(text):
        if words and space is None and (
            not first
            or first in _NO_START
            or before in _NO_END
            or (glue is not None and glue.match(piece))
        ):
            words[-1] += piece
        else:
            spaces.append(_written_space(space, before, first) if words else "")
            words.append(piece)
        before = last or before
    return Words(
        words,
        [measure(word) for word in words],
        spaces,
        [text_cells(space) for space in spaces],
    )


def _written_space(space: str | None, before: str, after: str) -> str:
    """What is written between two pieces on one line for the *space* the
    text held between them (None: none)."""
    if space is None:
        return ""
    if "\n" in space:
        wide = any(character and cells(character) == 2 for character in (before, after))
        return "" if wide else " "
    return space


def _clusters(text: str) -> list[list]:
    """What text that breaks between characters never breaks inside, in
    order: a character, or a run of half-width ones such as a Latin word, a
    number or "...", with the codes that go with it and the marks after it.
    Each is [its text, its first and last drawn character, the space before
    it or None]."""
    clusters: list[list] = []
    pending = ""
    space = None
    index, end = 0, len(text)
    while index < end:
        character = text[index]
        if character.isspace():
            stop = index + 1
            while stop < end and text[stop].isspace():
                stop += 1
            # Codes before a space go with the text before it.
            if pending and clusters and space is None:
                clusters[-1][0] += pending
                pending = ""
            space = (space or "") + text[index:stop]
            index = stop
            continue
        code = _CODE.match(text, index) if character == "\\" else None
        if code:
            if (
                _TRAILING_CODE.fullmatch(code.group())
                and clusters
                and space is None
                and not pending
            ):
                clusters[-1][0] += code.group()
            else:
                pending += code.group()
            index = code.end()
            continue
        size = cells(character)
        if not size:
            # A combining mark or a format character stays with what it
            # follows.
            if clusters and space is None and not pending:
                clusters[-1][0] += character
            else:
                pending += character
            index += 1
            continue
        stop = index + 1
        if size == 1:
            # A half-width run keeps its own combining marks, as in café.
            while (
                stop < end
                and not text[stop].isspace()
                and text[stop] != "\\"
                and cells(text[stop]) < 2
            ):
                stop += 1
        piece = text[index:stop]
        clusters.append([pending + piece, piece[0], piece[-1], space])
        pending, space = "", None
        index = stop
    if pending:
        if clusters:
            clusters[-1][0] += pending
        else:
            clusters.append([pending, "", "", None])
    return clusters


def measure_words(text: str, measure=None, target=None) -> Words:
    """*text* as the pieces its lines break between in *target* (see
    :class:`Words`), each as wide as *measure* counts it (by default as
    :func:`wrapText` counts text in *target*)."""
    characters = breaks_characters(target)
    return _words(text, measure or _measure(characters), characters)


def character_words(text: str, measure=None) -> Words:
    """*text* as the pieces its lines break between when it breaks between
    characters, whatever the target, such as Chinese or Japanese drawn into
    an image."""
    return _words(text, measure or _visible_cells, True)


def one_line(text: str, target=None) -> str:
    """*text*'s lines run together on one line, as text in *target* runs on:
    with a space between, or for text that breaks between characters nothing
    between full-width ones (see :class:`Words`)."""
    return _one_line(text, breaks_characters(target))


def _one_line(text: str, characters: bool) -> str:
    if not characters:
        return text.replace("\n", " ")
    words = _words(text, len, True)
    return words.line(0, len(words.words)) if words.words else ""


def _filled(words: Words, width: int) -> list[str]:
    """*words* on lines of *width*, filling each line in turn."""
    lines: list[str] = []
    start, length = 0, None
    for index, size in enumerate(words.sizes):
        if length is not None and length + words.gaps[index] + size > width:
            lines.append(words.line(start, index))
            start, length = index, size
        else:
            length = size if length is None else length + words.gaps[index] + size
    if words.words:
        lines.append(words.line(start, len(words.words)))
    return lines


def wrapText(text: str, width: int, target=None) -> str:
    """
    Wrap text to the specified width, preserving RPG Maker color codes.

    Args:
        text (str): The text to wrap
        width (int): The maximum number of characters per line
        target: The language of the text, the run's by default (see
            :func:`breaks_characters`)

    Returns:
        str: The wrapped text with lines separated by \n
    """
    if not text:
        return ""

    characters = breaks_characters(target)
    measure = _measure(characters)
    # Split on double newlines (\n\n or \\n\\n)
    segments = re.split(r'(?:\n\n|\\n\\n)', text)
    wrapped_segments = []
    for segment in segments:
        lines = _filled(_words(segment, measure, characters), width)
        wrapped_segments.append("\n".join(lines))
    # Rejoin with double newlines to preserve hard breaks
    return "\n\n".join(wrapped_segments)


def wrapLines(
    text: str, width: int, rows: int | None = None, measure=None, target=None
) -> str:
    """
    Wrap text whose line breaks are authored, such as a database note or
    description, keeping every line break.

    Only a line wider than *width* wraps, onto lines of its own. Blank lines
    stay as they are, including the full-width-space lines that plugins which
    skip an empty line need to draw an empty row.

    *rows* is the number of lines the source spends on a window of fixed
    height, such as a help window. When kept lines would need more rows than
    that and running them together needs fewer, the text flows instead.
    *measure* gives a word's visible width and *target* the text's
    language, as for :func:`wrapShaped`.
    """
    if not text:
        return ""
    characters = breaks_characters(target)
    measure = measure or _measure(characters)

    lines = []
    for line in text.split("\n"):
        if not line.strip() or _line_width(line, measure, characters) <= width:
            lines.append(line)
        else:
            lines.append(_wrapLine(line, width, measure, characters))
    kept = "\n".join(lines)
    if rows is None or kept.count("\n") < rows:
        return kept
    # A row past the window's last is cut off in game, so text that needs
    # more rows than the window shows flows together, a list's items too.
    # Its items and sentences still start a line where the rows allow it,
    # on as few lines as that takes; otherwise the lines run even.
    words = _words(text, measure, characters)
    flowed = None
    for count in range(rows_needed(words.sizes, width, words.gaps), rows + 1):
        lines = _sentence_lines(words, width, count, False, characters)
        if lines:
            flowed = "\n".join(lines)
            break
    flowed = flowed or _shaped(
        _one_line(text, characters), width, None, None, measure, characters
    )
    return flowed if flowed.count("\n") < kept.count("\n") else kept


def _line_width(line: str, measure, characters: bool) -> int:
    words = _words(line, measure, characters)
    return sum(words.sizes) + sum(words.gaps)


# Inline codes that may trail a word, such as a wait (\.) or a colour reset
# (\C[0]), and the closing marks that may follow its punctuation.
_TRAILING_CODES = re.compile(r"(?:\\+[A-Za-z]+\[[^\]]*\]|\\+[.|!^<>{}$])+$")
_LEADING_CODES = re.compile(r"^(?:\\+[A-Za-z]+\[[^\]]*\]|\\+[.|!^<>{}$])+")
_CLOSERS = "\"'”’)]）」』】＞*"
# A translated word that ends a sentence, and one that ends a clause; text
# that breaks between characters ends a sentence with 。 too.
_SENTENCE_END = re.compile(r"(?:[.!?…♪♥♡～~！？]|―)[" + re.escape(_CLOSERS) + r"]*$")
_FULL_STOP_END = re.compile(r"(?:[.!?…‥♪♥♡～~！？。]|―)[" + re.escape(_CLOSERS) + r"]*$")
_CLAUSE_END = re.compile(r"(?:[,;:、，]|—|–|--)[" + re.escape(_CLOSERS) + r"]*$")
# A line that starts a list item or a note starts on a line of its own.
ITEM_START = re.compile(r"^[・●◆◇■□※★☆•]")
# A source line that ends a sentence, and one that ends a clause: where the
# writer broke the line on purpose rather than to fit the window.
_SOURCE_SENTENCE_END = re.compile(r"[。！？!?…‥.♪♥♡～〜ー―」』）)】]$")
_SOURCE_CLAUSE_END = re.compile(r"[、，,]$")
_SOURCE_BLANK = " \t　"


def _word_end(word: str) -> str:
    return _TRAILING_CODES.sub("", word)


def _break_kind(words: list[str], end: int, characters: bool = False) -> str:
    """How a line break after ``words[end - 1]`` reads: after a sentence or
    before a list item, after a clause, or inside a sentence: between words,
    or for text that breaks between characters inside a word (see
    :func:`_phrase_break`)."""
    head = _LEADING_CODES.sub("", words[end]) if end < len(words) else ""
    if ITEM_START.match(head):
        return "sentence"
    tail = _word_end(words[end - 1])
    if (_FULL_STOP_END if characters else _SENTENCE_END).search(tail):
        return "sentence"
    if _CLAUSE_END.search(tail):
        return "clause"
    if characters and not _phrase_break(tail[-1:], head[:1]):
        return "character"
    return "word"


_HIRAGANA = re.compile(r"[ぁ-ゖー]")


def _phrase_break(before: str, after: str) -> bool:
    """Whether a break between the characters *before* and *after* falls
    between Japanese phrases, as a reader takes them in: after the kana that
    end a phrase, such as a particle, before a word in kanji, katakana or
    Latin letters, or around brackets. Elsewhere it splits a word, such as
    攻撃 or ポーション."""
    if not before or not after:
        return True
    if before in _NO_END or after in _NO_START or after in _NO_END or before in ")]}）］｝〕〉》」』】":
        return True
    return bool(_HIRAGANA.match(before)) and not _HIRAGANA.match(after)


def _source_segments(lines: list[str]) -> tuple[list[int], bool]:
    """The sizes of the source's deliberate lines, joining lines it broke
    only to fit the window, and whether it breaks after a clause."""
    sizes: list[int] = []
    clauses = False
    joined = False
    for index, line in enumerate(lines):
        text = line.strip(_SOURCE_BLANK)
        size = len(_LEADING_CODES.sub("", text))
        if joined:
            sizes[-1] += size
        else:
            sizes.append(size)
        following = lines[index + 1].strip(_SOURCE_BLANK) if index + 1 < len(lines) else ""
        end = _word_end(text)
        if _SOURCE_SENTENCE_END.search(end) or ITEM_START.match(_LEADING_CODES.sub("", following)):
            joined = False
        elif _SOURCE_CLAUSE_END.search(end):
            joined, clauses = False, True
        else:
            joined = True
    return sizes, clauses


_BREAK_COST = {"sentence": 0.0, "clause": 0.12, "word": 0.3, "character": 0.45}
# How much uneven lines cost against a break that reads worse.
EVEN_WEIGHT = 4.0


def rows_needed(sizes: list[int], width: int, gaps: list[int] | None = None) -> int:
    """The fewest rows words of *sizes* take within *width*, filling each
    row in turn, with *gaps* between them (one each by default)."""
    rows, line = 1, None
    for index, size in enumerate(sizes):
        if line is None:
            line = size
            continue
        gap = 1 if gaps is None else gaps[index]
        if line + gap + size > width:
            rows, line = rows + 1, size
        else:
            line += gap + size
    return rows


def _split(words: Words, back: list[list[int]], rows: int) -> list[str]:
    lines, end = [], len(words.words)
    for row in range(rows, 0, -1):
        start = back[row][end]
        lines.append(words.line(start, end))
        end = start
    return lines[::-1]


def _even_lines(words: Words, width: int, rows: int, characters: bool) -> list[str]:
    """*words* on exactly *rows* lines within *width*, as even in length as
    possible, breaking after sentences and clauses where that costs little."""
    sizes, gaps = words.sizes, words.gaps
    count = len(sizes)
    infinite = float("inf")
    best = [[infinite] * (count + 1) for _ in range(rows + 1)]
    back = [[0] * (count + 1) for _ in range(rows + 1)]
    best[0][0] = 0.0
    # The lines' length together, without the gaps their breaks take.
    joins = sum(gaps)
    even = (sum(sizes) + joins - (rows - 1) * (joins / (count - 1) if count > 1 else 0)) / rows
    for row in range(1, rows + 1):
        for end in range(1, count + 1):
            length = None
            for start in range(end, 0, -1):
                length = (
                    sizes[start - 1]
                    if length is None
                    else length + sizes[start - 1] + gaps[start]
                )
                if length > width and start < end:
                    break
                if best[row - 1][start - 1] == infinite:
                    continue
                cost = ((even - length) / width) ** 2 * EVEN_WEIGHT
                if end < count:
                    cost += _BREAK_COST[_break_kind(words.words, end, characters)]
                total = best[row - 1][start - 1] + cost
                if total < best[row][end]:
                    best[row][end] = total
                    back[row][end] = start - 1
    return _split(words, back, rows)


def _sentence_lines(
    words: Words,
    width: int,
    rows: int,
    clauses: bool,
    characters: bool,
    shares: list[float] | None = None,
) -> list[str] | None:
    """*words* on exactly *rows* lines within *width*, every break after a
    sentence (or a clause, when *clauses*) or before a list item. With
    *shares*, each line's share of the text as close to the source line's
    share as it can be; otherwise the widest line as narrow as it can be.
    None when the text has no such breaks."""
    sizes, gaps = words.sizes, words.gaps
    count = len(sizes)
    total = sum(sizes) + sum(gaps)
    infinite = (float("inf"), float("inf"))
    best = [[infinite] * (count + 1) for _ in range(rows + 1)]
    back = [[0] * (count + 1) for _ in range(rows + 1)]
    best[0][0] = (0.0, 0)
    allowed = {"sentence", "clause"} if clauses else {"sentence"}
    for row in range(1, rows + 1):
        for end in range(1, count + 1):
            if end < count and _break_kind(words.words, end, characters) not in allowed:
                continue
            length = None
            for start in range(end, 0, -1):
                length = (
                    sizes[start - 1]
                    if length is None
                    else length + sizes[start - 1] + gaps[start]
                )
                if length > width:
                    break
                previous = best[row - 1][start - 1]
                if previous == infinite:
                    continue
                drift = (length / total - shares[row - 1]) ** 2 if shares else 0.0
                score = (previous[0] + drift, max(previous[1], length))
                if score < best[row][end]:
                    best[row][end] = score
                    back[row][end] = start - 1
    if best[rows][count] == infinite:
        return None
    return _split(words, back, rows)


def _paged(
    words: Words, width: int, page_rows: int, characters: bool
) -> list[list[str]] | None:
    """*words* split into pages of at most *page_rows* rows, each page ending
    on a sentence: as few pages as possible, then as even as possible. None
    when the sentences do not allow it."""
    sizes, gaps = words.sizes, words.gaps
    count = len(sizes)
    infinite = (float("inf"), float("inf"))
    best = [infinite] * (count + 1)
    back = [0] * (count + 1)
    best[0] = (0, 0)
    for end in range(1, count + 1):
        if end < count and _break_kind(words.words, end, characters) != "sentence":
            continue
        for start in range(end - 1, -1, -1):
            if best[start] == infinite:
                continue
            rows = rows_needed(sizes[start:end], width, gaps[start:end])
            if rows > page_rows:
                break
            pages, spare = best[start]
            score = (pages + 1, spare + (page_rows - rows) ** 2)
            if score < best[end]:
                best[end] = score
                back[end] = start
    if best[count] == infinite:
        return None
    pages, end = [], count
    while end:
        start = back[end]
        part = words.part(start, end)
        pages.append(
            _even_lines(
                part, width, rows_needed(part.sizes, width, part.gaps), characters
            )
        )
        end = start
    return pages[::-1]


def wrapShaped(
    text: str,
    width: int,
    source: str | None = None,
    rows: int | None = None,
    measure=None,
    target=None,
    glue=None,
) -> str:
    """Wrap translated *text* to *width*, laid out like its *source* where the
    translation allows.

    Blank first rows stay: the text's own, or else the source's. Where the
    source breaks its lines after sentences, before list items or after
    clauses, the text breaks after its own sentences (and clauses, where the
    source breaks after one) on as many lines as the source has deliberate
    lines, each line's share of the text close to the source line's, when
    every line fits. Otherwise the text takes the fewest lines it needs, as
    even as possible, preferring breaks after sentences and clauses.

    *rows* is the rows one page of the window shows. Text that needs more
    starts each new page after a sentence where it can, filling the page
    before with empty rows, rather than wherever the window runs out.
    Paragraphs split by a blank line wrap separately. *measure* gives a
    word's visible width; it defaults to :func:`_get_visible_length`, or
    :func:`_visible_cells` for text that breaks between characters. *target*
    is the text's language, the run's by default: Chinese and Japanese break
    between characters (see :class:`Words`), any other at its spaces. For
    text that breaks between characters, a piece the pattern *glue* matches
    at its start never starts a line.

    Measured on six translated games against filling each line in turn (in
    parentheses), it matched the Japanese row count for 51-93% of messages
    (33-87%), broke after a sentence or clause at 42-77% of line breaks
    (9-14%), and left a short stray last line in 0-2% of multi-line messages
    (18-32%).
    """
    characters = breaks_characters(target)
    return _shaped(
        text, width, source, rows, measure or _measure(characters), characters, glue
    )


def _shaped(
    text: str,
    width: int,
    source: str | None,
    rows: int | None,
    measure,
    characters: bool,
    glue=None,
) -> str:
    width = int(width)
    if not text or not text.strip():
        return text or ""
    source_lines = (source or "").replace("\r\n", "\n").split("\n")
    # Text fitted again keeps the blank rows it starts with.
    lead = len(text) - len(text.lstrip("\n"))
    if not lead:
        while lead < len(source_lines) - 1 and not source_lines[lead].strip(_SOURCE_BLANK):
            lead += 1
    segments, clauses = _source_segments(
        [line for line in source_lines[lead:] if line.strip(_SOURCE_BLANK)]
    )
    page = None if rows is None else max(1, int(rows) - lead)
    paragraphs = re.split(r"\n[ \t]*\n|\\n\\n", text.strip("\n"))
    out: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        words = _words(paragraph, measure, characters, glue)
        if not words.words:
            continue
        needed = rows_needed(words.sizes, width, words.gaps)
        lines = None
        if len(paragraphs) == 1 and len(segments) > 1:
            shares = [size / sum(segments) for size in segments] if sum(segments) else None
            most = len(segments) if page is None else min(len(segments), page)
            for count in range(most, needed - 1, -1):
                lines = _sentence_lines(
                    words, width, count, clauses, characters,
                    shares if count == len(segments) else None,
                )
                if lines:
                    break
        lines = lines or _even_lines(words, width, needed, characters)
        if page is not None and len(lines) > page:
            pages = _paged(words, width, page, characters)
            if pages:
                lines = []
                for number, part in enumerate(pages):
                    if number:
                        lines += [""] * lead
                    lines += part
                    if number < len(pages) - 1:
                        lines += [""] * (page - len(part))
        if index:
            out.append("")
        out += lines
    return "\n" * lead + "\n".join(out)


def unpaged(text: str, rows: int) -> str:
    """Text :func:`wrapShaped` paged into windows of *rows* as it read the
    text before: without the empty rows it fills a page with. Other blank
    rows, such as a paragraph break, stay, unless one ends a page just as
    those rows would."""
    lines = text.split("\n")
    lead = 0
    while lead < len(lines) and not lines[lead].strip():
        lead += 1
    page = max(1, int(rows) - lead)
    kept = lines[:lead]
    shown = 0
    index = lead
    while index < len(lines):
        end = index
        while end < len(lines) and not lines[end].strip():
            end += 1
        if end == index:
            # A full page goes on to the next with no empty rows between.
            shown = 1 if shown == page else shown + 1
            kept.append(lines[index])
            index += 1
            continue
        # A page's empty rows fill it and add the blank rows each page
        # starts with; a paragraph starts its pages afresh.
        if not (end < len(lines) and 0 < shown and end - index == page - shown + lead):
            kept += lines[index:end]
        shown = 0
        index = end
    return "\n".join(kept)


def _wrapLine(line: str, width: int, measure, characters: bool) -> str:
    """One authored line too wide for *width*, on as few lines as it needs,
    evened out so its last line is not a stray word. The line's indent stays
    on its first line."""
    body = line.lstrip()
    return line[: len(line) - len(body)] + _shaped(
        body, width, None, None, measure, characters
    )


def wrapSGDesc(text: str, width: int, target=None) -> str:
    """Structured word-wrap for SG plugin description blocks.

    Unlike wrapText, this function understands the layout of SG info-box
    content:
      ◆ / ・ / • / ● lines are always kept on their own line as section
      headers; the body text immediately following is word-wrapped to
      *width*.  Paragraph breaks (\\n\\n) are preserved between sections.
    *target* is the text's language, as for :func:`wrapText`.
    """
    HEADER_CHARS = ("◆", "・", "•", "●")
    characters = breaks_characters(target)
    measure = _measure(characters)

    paragraphs = text.split("\n\n")
    wrapped_paragraphs = []
    for para in paragraphs:
        lines = para.split("\n")
        out_parts = []
        body_buf: list[str] = []

        def flush_body():
            if not body_buf:
                return
            out_parts.extend(_filled(_words("\n".join(body_buf), measure, characters), width))
            body_buf.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(HEADER_CHARS):
                flush_body()
                # Word-wrap the header line itself — the bullet stays on the
                # first wrapped line; continuation lines are plain body lines.
                out_parts.extend(_filled(_words(stripped, measure, characters), width))
            else:
                body_buf.append(stripped)
        flush_body()
        wrapped_paragraphs.append("\n".join(out_parts))

    return "\n\n".join(wrapped_paragraphs)
