import re

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


def _get_visible_length(text: str) -> int:
    """The visible length of text, ignoring inline control codes (see
    :func:`visible_text`)."""
    return len(visible_text(text))


def visible_word_wrap_end_index(text: str, width: int) -> int:
    """Return index into *text* after the last word that fits *width* visible chars.

    Uses the same word-wrapping rules as :func:`wrapText`. Wolf ``\\c[]`` /
    ``\\f[]`` codes do not count toward *width*.
    """
    if not text or width <= 0:
        return len(text)
    if _get_visible_length(text) <= width:
        return len(text)
    words = text.split()
    if not words:
        return len(text)
    current_len = 0
    kept = 0
    pos = 0
    fit_end = 0
    for word in words:
        wl = _get_visible_length(word)
        gap = 1 if kept > 0 else 0
        if current_len + gap + wl <= width:
            idx = text.find(word, pos)
            if idx < 0:
                break
            pos = idx + len(word)
            fit_end = pos
            kept += 1
            current_len += gap + wl
        else:
            break
    if kept == 0 and words:
        idx = text.find(words[0], 0)
        fit_end = (idx + len(words[0])) if idx >= 0 else len(text)
    return fit_end


def max_line_visible_length(text: str) -> int:
    """Longest visible line length in *text* (handles ``\\r`` / ``\\n``)."""
    if not isinstance(text, str) or not text:
        return 0
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n") if normalized else [""]
    if not lines:
        return _get_visible_length(normalized)
    return max(_get_visible_length(line) for line in lines)

def wrapText(text: str, width: int) -> str:
    """
    Wrap text to the specified width, preserving RPG Maker color codes.
    
    Args:
        text (str): The text to wrap
        width (int): The maximum number of characters per line
    
    Returns:
        str: The wrapped text with lines separated by \n
    """
    if not text:
        return ""

    # Split on double newlines (\n\n or \\n\\n)
    import re
    segments = re.split(r'(?:\n\n|\\n\\n)', text)
    wrapped_segments = []
    for segment in segments:
        words = segment.split()
        lines = []
        current_line = []
        current_length = 0
        for word in words:
            word_length = _get_visible_length(word)
            if current_length + word_length + len(current_line) <= width:
                current_line.append(word)
                current_length += word_length
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_length
        if current_line:
            lines.append(" ".join(current_line))
        wrapped_segments.append("\n".join(lines))
    # Rejoin with double newlines to preserve hard breaks
    return "\n\n".join(wrapped_segments)


def wrapLines(text: str, width: int, rows: int | None = None, measure=None) -> str:
    """
    Wrap text whose line breaks are authored, such as a database note or
    description, keeping every line break.

    Only a line wider than *width* wraps, onto lines of its own. Blank lines
    stay as they are, including the full-width-space lines that plugins which
    skip an empty line need to draw an empty row.

    *rows* is the number of lines the source spends on a window of fixed
    height, such as a help window. When kept lines would need more rows than
    that and running them together needs fewer, the text flows instead.
    *measure* gives a word's visible width, as for :func:`wrapShaped`.
    """
    if not text:
        return ""
    measure = measure or _get_visible_length

    lines = []
    for line in text.split("\n"):
        if not line.strip() or _line_width(line, measure) <= width:
            lines.append(line)
        else:
            lines.append(_wrapLine(line, width, measure))
    kept = "\n".join(lines)
    if rows is None or kept.count("\n") < rows:
        return kept
    # A row past the window's last is cut off in game, so text that needs
    # more rows than the window shows flows together, a list's items too:
    # its items still start a line where they can.
    flowed = wrapShaped(text.replace("\n", " "), width, measure=measure)
    return flowed if flowed.count("\n") < kept.count("\n") else kept


def _line_width(line: str, measure) -> int:
    words = line.split()
    return sum(measure(word) for word in words) + max(0, len(words) - 1)


# Inline codes that may trail a word, such as a wait (\.) or a colour reset
# (\C[0]), and the closing marks that may follow its punctuation.
_TRAILING_CODES = re.compile(r"(?:\\+[A-Za-z]+\[[^\]]*\]|\\+[.|!^<>{}$])+$")
_LEADING_CODES = re.compile(r"^(?:\\+[A-Za-z]+\[[^\]]*\]|\\+[.|!^<>{}$])+")
_CLOSERS = "\"'”’)]）」』】＞*"
# A translated word that ends a sentence, and one that ends a clause.
_SENTENCE_END = re.compile(r"(?:[.!?…♪♥♡～~！？]|―)[" + re.escape(_CLOSERS) + r"]*$")
_CLAUSE_END = re.compile(r"(?:[,;:、，]|—|–|--)[" + re.escape(_CLOSERS) + r"]*$")
# A line that starts a list item or a note starts on a line of its own.
_ITEM_START = re.compile(r"^[・●◆◇■□※★☆•]")
# A source line that ends a sentence, and one that ends a clause: where the
# writer broke the line on purpose rather than to fit the window.
_SOURCE_SENTENCE_END = re.compile(r"[。！？!?…‥.♪♥♡～〜ー―」』）)】]$")
_SOURCE_CLAUSE_END = re.compile(r"[、，,]$")
_SOURCE_BLANK = " \t　"


def _word_end(word: str) -> str:
    return _TRAILING_CODES.sub("", word)


def _break_kind(words: list[str], end: int) -> str:
    """How a line break after ``words[end - 1]`` reads: after a sentence or
    before a list item, after a clause, or inside a sentence."""
    if end < len(words) and _ITEM_START.match(_LEADING_CODES.sub("", words[end])):
        return "sentence"
    tail = _word_end(words[end - 1])
    if _SENTENCE_END.search(tail):
        return "sentence"
    if _CLAUSE_END.search(tail):
        return "clause"
    return "word"


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
        if _SOURCE_SENTENCE_END.search(end) or _ITEM_START.match(_LEADING_CODES.sub("", following)):
            joined = False
        elif _SOURCE_CLAUSE_END.search(end):
            joined, clauses = False, True
        else:
            joined = True
    return sizes, clauses


_BREAK_COST = {"sentence": 0.0, "clause": 0.12, "word": 0.3}
# How much uneven lines cost against a break that reads worse.
EVEN_WEIGHT = 4.0


def _rows_needed(sizes: list[int], width: int) -> int:
    rows, line = 1, -1
    for size in sizes:
        if line >= 0 and line + 1 + size > width:
            rows, line = rows + 1, size
        else:
            line += 1 + size
    return rows


def _split(words: list[str], back: list[list[int]], rows: int) -> list[str]:
    lines, end = [], len(words)
    for row in range(rows, 0, -1):
        start = back[row][end]
        lines.append(" ".join(words[start:end]))
        end = start
    return lines[::-1]


def _even_lines(words: list[str], sizes: list[int], width: int, rows: int) -> list[str]:
    """*words* on exactly *rows* lines within *width*, as even in length as
    possible, breaking after sentences and clauses where that costs little."""
    count = len(words)
    infinite = float("inf")
    best = [[infinite] * (count + 1) for _ in range(rows + 1)]
    back = [[0] * (count + 1) for _ in range(rows + 1)]
    best[0][0] = 0.0
    even = (sum(sizes) + count - rows) / rows
    for row in range(1, rows + 1):
        for end in range(1, count + 1):
            length = -1
            for start in range(end, 0, -1):
                length += sizes[start - 1] + 1
                if length > width and start < end:
                    break
                if best[row - 1][start - 1] == infinite:
                    continue
                cost = ((even - length) / width) ** 2 * EVEN_WEIGHT
                if end < count:
                    cost += _BREAK_COST[_break_kind(words, end)]
                total = best[row - 1][start - 1] + cost
                if total < best[row][end]:
                    best[row][end] = total
                    back[row][end] = start - 1
    return _split(words, back, rows)


def _sentence_lines(
    words: list[str],
    sizes: list[int],
    width: int,
    rows: int,
    clauses: bool,
    shares: list[float] | None = None,
) -> list[str] | None:
    """*words* on exactly *rows* lines within *width*, every break after a
    sentence (or a clause, when *clauses*) or before a list item. With
    *shares*, each line's share of the text as close to the source line's
    share as it can be; otherwise the widest line as narrow as it can be.
    None when the text has no such breaks."""
    count = len(words)
    total = sum(sizes) + count - 1
    infinite = (float("inf"), float("inf"))
    best = [[infinite] * (count + 1) for _ in range(rows + 1)]
    back = [[0] * (count + 1) for _ in range(rows + 1)]
    best[0][0] = (0.0, 0)
    allowed = {"sentence", "clause"} if clauses else {"sentence"}
    for row in range(1, rows + 1):
        for end in range(1, count + 1):
            if end < count and _break_kind(words, end) not in allowed:
                continue
            length = -1
            for start in range(end, 0, -1):
                length += sizes[start - 1] + 1
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
    words: list[str], sizes: list[int], width: int, page_rows: int
) -> list[list[str]] | None:
    """*words* split into pages of at most *page_rows* rows, each page ending
    on a sentence: as few pages as possible, then as even as possible. None
    when the sentences do not allow it."""
    count = len(words)
    infinite = (float("inf"), float("inf"))
    best = [infinite] * (count + 1)
    back = [0] * (count + 1)
    best[0] = (0, 0)
    for end in range(1, count + 1):
        if end < count and _break_kind(words, end) != "sentence":
            continue
        for start in range(end - 1, -1, -1):
            if best[start] == infinite:
                continue
            rows = _rows_needed(sizes[start:end], width)
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
        pages.append(
            _even_lines(
                words[start:end], sizes[start:end], width,
                _rows_needed(sizes[start:end], width),
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
    word's visible width; it defaults to :func:`_get_visible_length`.
    """
    measure = measure or _get_visible_length
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
        words = paragraph.split()
        if not words:
            continue
        sizes = [measure(word) for word in words]
        needed = _rows_needed(sizes, width)
        lines = None
        if len(paragraphs) == 1 and len(segments) > 1:
            shares = [size / sum(segments) for size in segments] if sum(segments) else None
            most = len(segments) if page is None else min(len(segments), page)
            for count in range(most, needed - 1, -1):
                lines = _sentence_lines(
                    words, sizes, width, count, clauses,
                    shares if count == len(segments) else None,
                )
                if lines:
                    break
        lines = lines or _even_lines(words, sizes, width, needed)
        if page is not None and len(lines) > page:
            pages = _paged(words, sizes, width, page)
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


def _wrapLine(line: str, width: int, measure=None) -> str:
    """One authored line too wide for *width*, on as few lines as it needs,
    evened out so its last line is not a stray word. The line's indent stays
    on its first line."""
    body = line.lstrip()
    return line[: len(line) - len(body)] + wrapShaped(body, width, measure=measure)


def wrapSGDesc(text: str, width: int) -> str:
    """Structured word-wrap for SG plugin description blocks.

    Unlike wrapText, this function understands the layout of SG info-box
    content:
      ◆ / ・ / • / ● lines are always kept on their own line as section
      headers; the body text immediately following is word-wrapped to
      *width*.  Paragraph breaks (\\n\\n) are preserved between sections.
    """
    HEADER_CHARS = ("◆", "・", "•", "●")

    paragraphs = text.split("\n\n")
    wrapped_paragraphs = []
    for para in paragraphs:
        lines = para.split("\n")
        out_parts = []
        body_buf: list[str] = []

        def flush_body():
            if not body_buf:
                return
            words = " ".join(body_buf).split()
            cur_line: list[str] = []
            cur_len = 0
            for word in words:
                wl = _get_visible_length(word)
                if cur_len + wl + len(cur_line) <= width:
                    cur_line.append(word)
                    cur_len += wl
                else:
                    if cur_line:
                        out_parts.append(" ".join(cur_line))
                    cur_line = [word]
                    cur_len = wl
            if cur_line:
                out_parts.append(" ".join(cur_line))
            body_buf.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(HEADER_CHARS):
                flush_body()
                # Word-wrap the header line itself — the bullet stays on the
                # first wrapped line; continuation lines are plain body lines.
                words = stripped.split()
                cur_line: list[str] = []
                cur_len = 0
                for word in words:
                    wl = _get_visible_length(word)
                    if cur_len + wl + len(cur_line) <= width:
                        cur_line.append(word)
                        cur_len += wl
                    else:
                        if cur_line:
                            out_parts.append(" ".join(cur_line))
                        cur_line = [word]
                        cur_len = wl
                if cur_line:
                    out_parts.append(" ".join(cur_line))
            else:
                body_buf.append(stripped)
        flush_body()
        wrapped_paragraphs.append("\n".join(out_parts))

    return "\n\n".join(wrapped_paragraphs)