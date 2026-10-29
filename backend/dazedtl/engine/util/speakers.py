"""Speaker utilities shared across engine modules.

One home for everything speaker-related so ``util/`` does not sprawl:

* **Prefix parsing** - the ``[Speaker]: line`` convention the shared prompt uses.
  Widely imported by the engine modules to add the tag to a request's line and
  strip it off translated text.
* **Inline speakers** - a dialogue line that starts with its speaker's name,
  which the RPG Maker MV/MZ parser reads with INLINE401SPEAKERS.
* **WOLF first-line reshaping** - WolfDawn bakes some speaker names into line 1
  of the source; these helpers reshape those lines into ``[Speaker]: line`` for
  translation and restore WOLF's native ``Speaker\nline`` layout afterwards.
* **Speakers in the plain engine modules** - finding a speaker by an engine's
  own syntax, translating its name once, and writing back only the name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import NamedTuple

from util.languages import ENGLISH, shares_kanji
from util.paths import DATA_DIR
from util.target_text import name_translated, title_case

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

SPEAKER_TAG_RE = re.compile(
    rf"^\[({SPEAKER_BRACKET_INNER})\]",
    re.IGNORECASE,
)

# Dialogue body after an optional [Speaker]: prefix (text.py lineTextRegex, etc.)
SPEAKER_PREFIX_OPTIONAL_RE = re.compile(
    rf"(?:{_PREFIX_PATTERN})?(.+)",
    re.IGNORECASE,
)


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


# A Japanese name a model put before a line it translated, as in ミカ：Hello
# or ミカ(Hello), and the closing parenthesis such a line ends with.
_ECHOED_NAME_RE = re.compile(r"^[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+\s*[\(（:]\s*")
_ECHOED_CLOSE_RE = re.compile(r"\s*[)）]\s*$")


def strip_echoed_speaker(text: str, language, speaker: str = "") -> str:
    """A translated line without the speaker a model echoed: a
    ``[Speaker]:`` prefix (strip_speaker_prefix, with the *speaker* the line
    was sent with), or else, for a target written in another script than
    Japanese, a leading Japanese name with ``(`` or ``:``. A Chinese or
    Japanese target writes such a word as text (util/target_text)."""
    from util.target_text import full_width

    stripped = strip_speaker_prefix(text, speaker)
    if stripped != text or full_width(language):
        return stripped
    echoed = _ECHOED_NAME_RE.match(text)
    if not echoed:
        return text
    return _ECHOED_CLOSE_RE.sub("", text[echoed.end():])


def extract_dialogue_after_speaker(text: str) -> str | None:
    """Return dialogue body after an optional ``[Speaker]:`` prefix, or ``None``."""
    if not text:
        return None
    m = SPEAKER_PREFIX_OPTIONAL_RE.match(text)
    return m.group(1) if m else None


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

# speaker_src values whose name is baked into line 1 of the source text.
FIRSTLINE_SRCS = ("literal_line1", "literal_line1_lowconf")

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


def parse_prefixed(text: str, speaker: str = ""):
    """Parse a translated ``[Speaker]: body`` string.

    Returns (speaker, body). ``speaker`` is ``None`` when the model did not emit a
    ``[Speaker]:`` prefix, in which case ``body`` is the whole string. The
    *speaker* the line was sent with is read whatever it holds, as
    strip_speaker_prefix reads it.
    """
    if not isinstance(text, str):
        return None, text
    end = _sent_label_end(text, speaker)
    if end is not None:
        return speaker, text[end:]
    m = SPEAKER_TAG_RE.match(text)
    if not m:
        return None, text
    return m.group(1).strip(), strip_speaker_prefix(text)


def restore_source(prefix: str, speaker: str, body: str) -> str:
    """Rebuild WOLF's native ``Speaker\nbody`` layout (with any window prefix)."""
    return f"{prefix}{speaker}\n{body}"


# ============================================================================
# Speakers in the plain engine modules
# ----------------------------------------------------------------------------
# A plain engine module (Text, Regex, Tyrano, Kirikiri, WOLF2, CSV, Lune and
# WOLF's wolf.py) finds a speaker by its engine's own syntax (find_speaker),
# translates the name through translate_speaker, writes back only the name
# (FoundSpeaker.written), sends the lines the speaker says as
# ``[Speaker]: line`` (to_prefixed) and takes that prefix off each reply line
# (strip_speaker_prefix with the speaker); Regex, CSV, WOLF2 and JSON send
# and write their lines through util/sent_lines, which does both. A speaker
# says only the lines its engine's syntax gives it, never lines after them
# that name no speaker. translate_speaker answers a name it translated, or a
# translation it gave, from its cache at no cost, so a module that walks its
# lines again to write the replies (Text, Tyrano, Kirikiri) finds the names
# its first walk wrote for free and needs no rule of its own for which walk
# translates.
# ============================================================================


class FoundSpeaker(NamedTuple):
    """A speaker's *name* in *line*, from *start* to *end*."""

    name: str
    line: str
    start: int
    end: int

    def written(self, translated: str) -> str:
        """The line with only the name replaced by *translated*: the rest of
        the line, such as a voice file named after the speaker, stays."""
        return self.line[: self.start] + translated + self.line[self.end :]


def find_speaker(syntax, line: str) -> FoundSpeaker | None:
    """The speaker *line* names in an engine's *syntax*, a pattern whose first
    group is the name, or None."""
    match = re.search(syntax, line)
    if match is None or match.group(1) is None:
        return None
    return FoundSpeaker(match.group(1), line, match.start(1), match.end(1))


def name_reply(reply: str, language) -> str:
    """A model's reply for a speaker name, as an engine writes it: its first
    line that holds anything, as the name is written on its own line or
    inside a tag, where more lines would add lines to the file and a model's
    later lines are a note or the name again; title-cased for a Latin target
    and without a stray ``Speaker: `` echo."""
    if "\n" in reply or "\r" in reply:
        reply = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    return title_case(reply, language).replace("'S", "'s").replace("Speaker: ", "")


# Names every engine writes alike, and the target language each needs (None:
# any)
_FIXED_NAMES = {"？？？": ("???", None), "ファイン": ("Fine", ENGLISH)}


def translate_speaker(speaker, names, language, translate):
    """A speaker name translated once per run: ``[translated, [in, out tokens]]``.

    *names* is the module's ``[original, translated]`` cache and gains each new
    name; *translate* is its ``translateAI``. A name the cache gave as a
    translation is answered as it is, at no cost, as a module finds it again
    where it wrote it. A reply is read by name_reply and asked for once more
    when it does not read as a translation.
    """
    if not speaker:
        return ["", [0, 0]]
    for original, translated in names:
        if speaker == original:
            return [translated, [0, 0]]
    if any(speaker == translated for _original, translated in names):
        return [speaker, [0, 0]]
    fixed, fixed_language = _FIXED_NAMES.get(speaker, (None, None))
    if fixed is not None and fixed_language in (None, language):
        names.append([speaker, fixed])
        return [fixed, [0, 0]]

    prompt = "Reply with the " + language + " translation of the NPC name."
    for _ in range(2):
        response = translate(speaker, prompt, False)
        response[0] = name_reply(response[0], language)
        if name_translated(response[0], language):
            break
    names.append([speaker, response[0]])
    return response
