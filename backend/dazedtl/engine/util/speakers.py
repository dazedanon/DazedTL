"""Speaker utilities shared across engine modules.

One home for everything speaker-related so ``util/`` does not sprawl:

* **Prefix parsing** - the ``[Speaker]: line`` convention the shared prompt uses,
  to add the tag to a request's line and strip it off translated text.
* **Inline speakers** - a dialogue line that starts with its speaker's name,
  which the RPG Maker MV/MZ parser reads with INLINE401SPEAKERS.
* **MV/MZ message speakers** - the speaker a message's first row names, on a
  row of its own or in front of the speech.
* **WOLF first-line reshaping** - WolfDawn bakes some speaker names into line 1
  of the source; these helpers split those lines for the WOLF tools.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import NamedTuple

from util.languages import shares_kanji
from util.source_text import holds_source
from util.paths import DATA_DIR

# ============================================================================
# [Speaker]: prefix parsing
# ----------------------------------------------------------------------------
# Handles RPG Maker control codes inside speaker brackets, e.g.
# ``[\\C[10]Hp Drink\\C[0]]: dialogue`` where inner ``[10]`` must not end the
# match early.
# ============================================================================

# Inner text of [Speaker] - allows \C[n], \c[n], \i[n], \n[actorId], etc.
# The control-code branch (\X[...]) keeps the inner [..] from ending the bracket early.
SPEAKER_BRACKET_INNER = r"(?:\\[A-Za-z]+\[[^\]]*\]|[^\]\n])+"

# A bare [Speaker]: / [Speaker]| / [Speaker]： prefix.
_PREFIX_PATTERN = rf"^\[{SPEAKER_BRACKET_INNER}\]\s*[|:：]\s*"
SPEAKER_PREFIX_RE = re.compile(_PREFIX_PATTERN, re.IGNORECASE)


# A names pass translates the speakers of many files together, so its requests
# belong to no game file. Run records keep them under this name instead, which
# the app's run inspector (compatibility/process_view.py) reads back.
NAMES_FILE = "speakers"

# Kana a speaker's name translated into a target that shares the source's
# kanji must not hold: the long vowel mark and half-width voicing marks
# included, which util/languages KANA leaves out as no letters of their own.
_NAME_KANA = re.compile(r"[ぁ-ゖァ-ヺー\uFF66-\uFF9F]")


def speaker_translated(
    source: str,
    translated: str,
    target: str,
    left: Callable[[str], bool],
    mixed: bool = False,
) -> bool:
    """Whether *translated* reads as the speaker name *source* translated
    into *target*. A target that shares the source's kanji, such as Japanese
    into Simplified Chinese, writes the name in them, so only kana is left.
    Another target, Japanese included, has a source in another script: the
    name must differ from its source and hold no text *left* reads as the
    source's, unless *mixed* and it holds Latin letters, as WOLF's localized
    names such as ``EN_セルリア`` do."""
    normalized = str(translated or "").strip()
    if not normalized:
        return False
    if shares_kanji(target=target):
        return _NAME_KANA.search(normalized) is None
    if normalized.casefold() == str(source or "").strip().casefold():
        return False
    return not left(normalized) or (
        mixed and re.search(r"[A-Za-z]", normalized) is not None
    )


def to_prefixed(speaker: str, body: str) -> str:
    """The ``[Speaker]: body`` line a request sends, or *body* alone when
    there is no *speaker*."""
    return f"[{speaker}]: {body}" if speaker else body


# What follows the bracketed name in a prefix
_PREFIX_SEPARATOR_RE = re.compile(r"\s*[|:：]\s*")


def _sent_label_end(text: str, speaker: str) -> int | None:
    """Where the ``[speaker]:`` label to_prefixed sent *speaker* with ends in
    *text*, or None when *text* does not start with it."""
    sent = f"[{speaker}]"
    if not speaker or not text.startswith(sent):
        return None
    separator = _PREFIX_SEPARATOR_RE.match(text, len(sent))
    return separator.end() if separator else None


def strip_speaker_prefix(text: str, speaker: str = "") -> str:
    """Remove a leading ``[Speaker]:`` / ``[Speaker]|`` / ``[Speaker]：`` prefix.

    *speaker*, the name the request's line was sent with (to_prefixed), is
    removed whatever it holds, such as a ``]`` that ends a name for the
    pattern; any other bracketed name as the pattern reads it."""
    if not text:
        return text
    end = _sent_label_end(text, speaker)
    if end is not None:
        return text[end:]
    return SPEAKER_PREFIX_RE.sub("", text, count=1)


# ============================================================================
# Inline speakers
# ----------------------------------------------------------------------------
# A dialogue line that starts with its speaker's name, then the speech. A
# Japanese game writes the source form, Name「dialogue, at times with a colon
# or a space before the quote. A line an inline re-export wrote back, or a
# game already in English, holds a written-back form: Name: "dialogue" (or “),
# Name (dialogue, or [Name] dialogue. The MV/MZ parser (INLINE401SPEAKERS)
# reads every form (ANY). Lint reads the source form with no colon (SOURCE),
# Name「dialogue or Name"dialogue as a Latin-script target's requests send it
# (util/target_text.corner_quotes), to keep a translation in that format.
# ============================================================================

ANY = "any"
SOURCE = "source"

# The name: up to 20 characters with no space, quote, sentence mark, code
# backslash, ASCII colon or bracket. A full-width colon stays in the name, as
# ミカ：「 has always read ミカ：.
_INLINE_NAME_EXCLUDES = r'\s「」。、！？…\\\n“”"(:\[\]'
_INLINE_NAME = rf"[^{_INLINE_NAME_EXCLUDES}]{{1,20}}"
_INLINE_SEPARATOR = r"[:：]?\s*"
# A code with a number, such as \C[2] or \N[1], before, after or as a name.
_NAME_CODE = r"\\+[A-Za-z]+\[\d+\]"
NAME_CODE_RE = re.compile(_NAME_CODE)
_INLINE_FORMS = {
    ANY: re.compile(
        rf"^(?:\[([^\]]{{1,30}})\]\s*"
        rf'|({_INLINE_NAME}){_INLINE_SEPARATOR}(?=[「“"(]))'
    ),
    # Codes may color the name or stand for it, as in \C[2]ミカ\C[0]「 or
    # \N[2]「. An ASCII quote that ends its row closes speech from the rows
    # before.
    SOURCE: re.compile(
        rf"^((?:{_NAME_CODE})*[^{_INLINE_NAME_EXCLUDES}：]{{1,20}}(?:{_NAME_CODE})*"
        rf"|(?:{_NAME_CODE})*\\+[NnPp]\[\d+\](?:{_NAME_CODE})*)"
        rf'\s*(?=「|"(?!\s*(?:\n|$)))'
    ),
}


class InlineSpeaker(NamedTuple):
    name: str
    # The name and what separates it from the speech, as the line has them.
    prefix: str
    speech: str


def inline_speaker(text: str, form: str = ANY) -> InlineSpeaker | None:
    """The speaker *text* starts with in the inline *form*, ANY or SOURCE,
    or None."""
    match = _INLINE_FORMS[form].match(text)
    if not match:
        return None
    name = next(group for group in match.groups() if group is not None)
    return InlineSpeaker(name.strip(), text[: match.end()], text[match.end():])


# ============================================================================
# MV/MZ message speakers
# ----------------------------------------------------------------------------
# The MV/MZ parser reads a message's speaker from its first row: a nameplate
# on a row of its own, with the speech on the rows after it, or a name in
# front of the speech on the same row. Guided's translation file names its
# lines by the same reading (translation/file_lines `nameplated`).
# ============================================================================

# Codes such as \c[1], \n[2], \F[tt07] or \FF[\w[3]].
MARKUP_RE = re.compile(r"[\\]+[A-Za-z]+\[(?:[^\[\]]|\[[^\]]*\])*\]")
# Actor and variable codes that are the speaker, such as \n[1] or \v[7].
_VARIABLE_NAME_RE = re.compile(r"[\\]+[nNvV]\[\d+\]")


def display_name(name: str) -> str:
    """Return the visible speaker nameplate with RPG Maker control codes removed.

    FIRSTLINESPEAKERS (and some colour/plugin wrappers) leave trailing or
    leading codes on the 401 name line, e.g. ``Tsubaki\\F[tt07]`` or
    ``メア\\F[tme01]\\FF[tl05]\\AA[F]\\FH[ON]``.  Glossary lookup and the
    ``[Speaker]:`` transport prefix need only the name; the written-back 401
    parameter keeps the codes via ``_replace_speaker_in_param``.

    Code-only nameplates such as ``\\v[007]\\AA[N]`` keep the variable/actor
    code (``\\v[007]``) and drop presentation plugins (``\\AA``, ``\\FH``, …).
    """
    raw = str(name or "")
    if not raw:
        return raw
    clean = MARKUP_RE.sub("", raw).strip()
    if clean:
        return clean
    vars_only = "".join(_VARIABLE_NAME_RE.findall(raw))
    return vars_only if vars_only else raw.strip()


def plausible_speaker(name: str) -> bool:
    """Return True only if *name* looks like a character name rather than dialogue or junk.

    Called during SPEAKER_PARSE_MODE to filter false positives before they
    enter SPEAKER_COLLECTED.  Heuristics (applied after stripping markup):
      • 1–20 characters long
      • Contains at least one Japanese letter (util/source_text)
      • No sentence-ending / mid-sentence punctuation (。！？…、)
      • No dialogue-opening quotes (「"（)
      • No newlines, underscores, slashes, or dots
      • No brace/plugin markup or decorative symbols
      • No clause-like particle/verb fragments scraped from prose
    """
    # Use the stripped form so trailing plugin codes (\F[tt07], etc.) do not
    # poison length / character checks. Pure control-code nameplates stay empty.
    clean = MARKUP_RE.sub("", str(name or "")).strip()
    if not clean:
        return False
    if len(clean) > 20:
        return False
    # Must have at least one Japanese letter
    if not holds_source(clean):
        return False
    # Reject sentence-like strings
    if re.search(r"[。！？…、]", clean):
        return False
    # Reject dialogue openers / structural characters
    if re.search(r"[「」""\n\r_/\\.]", clean):
        return False
    # Reject plugin placeholders and decorative junk ({{name}}, hearts, etc.)
    if re.search(r"[{}<>=★☆※♥♡\\]", clean):
        return False
    # Reject clause fragments that FIRSTLINESPEAKERS sometimes mis-detects.
    # Do not ban bare は/が/へ/を - those appear inside real names (はるか, かがやき).
    if re.search(r"しながら|すると|になった|した時|する時", clean):
        return False
    return True


def standalone_speaker(name: str, holds: Callable[[str], bool] = holds_source) -> bool:
    """Whether a [Name] row names a speaker, *holds* saying whether text
    holds source text.

    Re-exported [Name] lines are implicit nameplates, unlike explicit 101
    fields. Apply discovery's prose rejection before routing them to the
    short-name prompt. Keep resolved runtime names and short Latin labels."""
    display = display_name(name)
    if re.fullmatch(r"\\[nNvV]\[\d+\]", display):
        return True
    if holds(display):
        return plausible_speaker(display)
    return bool(
        len(display) <= 40
        and len(display.split()) <= 4
        and re.fullmatch(r"[^\W\d_][\w '\u2019\-]*", display)
    )


_CODE_NAMEPLATE = re.compile(r"(.*?)[\\]+m\[\d+?\][\\]+z\[\d+?\]")
# A name between colour codes, such as \C[2]【アリス】\C[0].
COLOURED_NAME_RE = re.compile(
    r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$"
)
_BRACKETED_SPEECH = re.compile(r"^\s*【([^】]+)】(.+)", re.DOTALL)
# A row that ends with 】 or with codes such as \n[2] or \FF[\w[3]].
_BRACKETS_END = re.compile(r"(】\s*|(?:[\\]+[A-Za-z]+(?:\[(?:[^\[\]]|\[[^\]]*\])*\])+\s*)$)")
_COLON_NAME = re.compile(r"(.+)：$")
_BRACKETED_ROW = re.compile(rf"^\[({SPEAKER_BRACKET_INNER})\]\s*$", re.IGNORECASE)
_SAME_LINE = re.compile(r"^\s*【([^】]+)】(?:\s*[：:])?(.+)", re.DOTALL)
# Codes the speech after a first-line name may open with.
_SPEECH_CODES = re.compile(r"^((?:[\\]+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+)")
_SPEECH_FORMAT = re.compile(r"(^[\\]+[\W]+?)")
_SPEECH_OPENERS = ("「", '"', "(", "（", "*", "[")


class MessageSpeakers(NamedTuple):
    """The speakers a message's first row names, as the row writes them."""

    names: tuple[str, ...]
    # The name in front of the speech, in an inline form (INLINE401SPEAKERS).
    inline: InlineSpeaker | None
    # 【Name】 with the speech after it on the same row.
    same_line: re.Match | None
    # The row holds only the names; the speech starts on the next row.
    own_line: bool


def message_speakers(
    line: str,
    following: str | None,
    *,
    first_line: bool,
    inline: bool,
    code_nameplates: bool,
    standalone: Callable[[str], bool] | None,
) -> MessageSpeakers | None:
    """The speakers *line*, the first row of a message or of scrolling text,
    names as the MV/MZ parser reads them, or None. *following* is the next
    command's text when that command is another of the text's rows (401 or
    405, or one translation emptied, with no text), else None. *first_line*
    reads a short row before speech as its speaker (FIRSTLINESPEAKERS) and
    *inline* a name in front of the speech (INLINE401SPEAKERS).
    *code_nameplates* reads a Name\\m[N]\\z[N] row as a nameplate only when
    a name comes before the codes, and *standalone*, when given, decides
    which [Name] rows name a speaker; the run's policy sets both."""
    names: list[str] = []
    found_inline = None
    match = _CODE_NAMEPLATE.search(line)
    if match and (match.group(1).strip() or not code_nameplates):
        names.append(match.group(1))
        if "\\c" in names[0]:
            names = COLOURED_NAME_RE.findall(names[0])
    # Brackets, one name or more, such as 【A】【B】
    if not names:
        bracketed = _BRACKETED_SPEECH.match(line)
        if bracketed:
            names = [bracketed.group(1).strip()]
        elif re.match(r"^\s*【", line) and _BRACKETS_END.search(line):
            names = [name.strip() for name in re.findall(r"【(.*?)】", line)]
    if not names:
        names = COLOURED_NAME_RE.findall(line)
    if not names:
        names = _COLON_NAME.findall(line)
    if not names:
        row = _BRACKETED_ROW.match(line)
        if row and (standalone is None or standalone(row.group(1))):
            names = [row.group(1).strip()]
    if not names and inline:
        found_inline = inline_speaker(line)
        if found_inline:
            names = [found_inline.name]
    if not names and first_line and len(line) < 40 and following:
        speech = following.strip()
        codes = _SPEECH_CODES.search(speech)
        format_code = _SPEECH_FORMAT.search(speech)
        if codes is not None:
            speech = speech.replace(codes.group(1), "")
        if format_code is not None:
            speech = speech.replace(format_code.group(1), "")
        if speech and speech[0] in _SPEECH_OPENERS:
            names = re.findall(r".+", line)
    if not names:
        return None
    same_line = _SAME_LINE.match(line)
    alone = len(names) == 1
    return MessageSpeakers(
        tuple(names),
        found_inline,
        same_line,
        following is not None
        and not (found_inline and alone)
        and not (same_line and alone),
    )


# ============================================================================
# WOLF (WolfDawn) first-line speaker reshaping
# ----------------------------------------------------------------------------
# WolfDawn attributes a speaker to every extracted line (``speaker`` /
# ``speaker_src`` fields). For the two "first-line" formats the speaker name is
# baked into line 1 of the ``source`` text, e.g.::
#
#     "市民\nおぉっ！来た！帰ってきたぞ！"        speaker_src = literal_line1_lowconf
#     "セルリア\nほーら、ローザも手を振って。"    speaker_src = literal_line1
#
# When translating we resolve the nameplate to English first (vocab /
# ``getSpeaker``), reshape into ``[Speaker]: body`` with that English tag, and
# on write-back restore WOLF's native ``Speaker\nbody`` layout using the
# pre-resolved name so a model that echoes Japanese cannot poison ``text``.
#
# WolfDawn does the detection, so there is nothing to configure for the reliable
# format: ``literal_line1`` is a real nameplate (a face window precedes the line),
# always reshaped, no toggle. Only ``literal_line1_lowconf`` is a heuristic guess
# (short line 1, no face window) that can occasionally be wrong; whether to trust
# it is a per-game call, so it is the single configurable format
# (``data/wolf_speakers.json``), recommended by the workflow's speaker-format AI
# prompt rather than guessed by hand.
# ============================================================================

# Reliable nameplate - always reshaped, not user-configurable.
ALWAYS_ON_SRCS = ("literal_line1",)

# Heuristic guess - reshaping is gated by config (per-game, AI-recommended).
CONFIGURABLE_SRCS = ("literal_line1_lowconf",)

# Default: also reshape the low-confidence guess. WolfDawn already gates it (short
# line 1, no control codes, no sentence punctuation), so it is safe enough on by
# default; the speaker-format prompt can advise turning it off for a given game.
DEFAULT_CONFIG = {
    "literal_line1_lowconf": True,
}

CONFIG_PATH = DATA_DIR / "wolf_speakers.json"

# Optional leading window-option prefix (``@<option>\n``) that WolfDawn keeps in
# the raw source; preserved verbatim so the reshaped/restored text still matches.
_WINDOW_PREFIX_RE = re.compile(r"^@[^\n]*\n")


def load_config() -> dict:
    """Return the WOLF speaker-format config, filling in defaults for missing keys."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = bool(data[key])
    except Exception:
        pass
    return cfg


def save_config(config: dict) -> None:
    """Persist the WOLF speaker-format config (only known keys are written)."""
    out = {key: bool(config.get(key, DEFAULT_CONFIG[key])) for key in DEFAULT_CONFIG}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(out, indent=4), encoding="utf-8", newline="\n")


def is_firstline_enabled(speaker_src: str, config: dict | None = None) -> bool:
    """True if *speaker_src* is a first-line format that should be reshaped.

    The reliable nameplate (``literal_line1``) is always on; the low-confidence
    guess is gated by *config* (per-game, AI-recommended).
    """
    if speaker_src in ALWAYS_ON_SRCS:
        return True
    if speaker_src not in CONFIGURABLE_SRCS:
        return False
    cfg = config if config is not None else DEFAULT_CONFIG
    return bool(cfg.get(speaker_src, DEFAULT_CONFIG.get(speaker_src, False)))


def split_window_prefix(text: str) -> tuple[str, str]:
    """Split a leading ``@<option>\\n`` window prefix off *text*.

    Returns ``(prefix, rest)`` where ``prefix`` is ``""`` when there is no such
    prefix. The prefix is preserved verbatim so wrapping/reshaping stays
    byte-faithful for WolfDawn's inject drift-guard.
    """
    if not isinstance(text, str):
        return "", text
    m = _WINDOW_PREFIX_RE.match(text)
    if not m:
        return "", text
    return m.group(0), text[m.end():]


def split_source(source: str, speaker_src: str, config: dict | None = None):
    """Split a first-line-speaker source into (prefix, speaker, body).

    Returns ``None`` when the line is not an enabled first-line-speaker format or
    cannot be split (no body after the name).
    """
    if not isinstance(source, str) or not is_firstline_enabled(speaker_src, config):
        return None
    prefix, rest = split_window_prefix(source)
    if "\n" not in rest:
        return None
    line1, body = rest.split("\n", 1)
    if not line1.strip():
        return None
    return prefix, line1, body
