"""The languages DazedTL translates between: each language's script, and for
a game's source language the patterns that tell text still in it, which
decide what a run sends, what Lines reads as left and what the census counts.
Settings, the engine and the app read them here.

A pair is supported when its source and target use different scripts, so a
value's letters tell whether it still needs translating. The source is one
of SOURCE_LANGUAGES; a target is free text, read as Latin script unless it
names a language written otherwise. Chinese shares a Japanese source's
kanji, so in a translation into it only kana tell Japanese left
(`shares_kanji`).

A Japanese source keeps each engine's own pattern exactly, by variant name:
merging them would change what existing runs send. An English source reads
Latin letters outside control codes and their arguments.
"""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar

from util.runtime_text import HALF_WIDTH_LETTERS, PROTECTED_PATTERNS

JAPANESE = "Japanese"
ENGLISH = "English"
# The languages a game's text can be written in, the default first.
SOURCE_LANGUAGES = (JAPANESE, ENGLISH)
DEFAULT_SOURCE = JAPANESE
# The environment variable that carries a run's source language into the
# engine, beside "language", its target.
SOURCE_ENV = "sourceLanguage"

LATIN = "latin"
# Scripts by language name, casefolded; any other language is Latin.
_SCRIPTS = {"japanese": "japanese", "chinese": "chinese", "korean": "korean"}

# Japanese text by each reader's own pattern. COMMON is the engines' shared
# LANGREGEX and the translator's default; MVMZ is RPG Maker MV/MZ's, which
# leaves out the voicing marks and full-width Latin; SRPG is SRPG Studio's;
# IMAGETEXT is image text's, COMMON spelled with literal half-width forms.
# The others are single readers' own: the census's runs and the letters a run
# must hold, plugin and Ruby script text, the desktop project's database
# records, speaker formats, game update text, the evaluation's segments,
# Wolf's string commands, the quoted strings of a plugin's disp_list and the
# release playtest's, a JavaScript pattern for what the game draws and its
# plugins' strings.
JAPANESE_PATTERNS = {
    "common": r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+",
    "mvmz": r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+",
    "srpg": r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+",
    "imagetext": r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ]+",
    "census_run": "[\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff60\uff61-\uff9f\uffe0-\uffee]+",
    "census_word": "[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]",
    "script": r"[\u3040-\u30ff\u3400-\u9fff]",
    "records": r"[ぁ-ゔァ-ヴ一-龠]",
    "speakers": r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]",
    "update_text": r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]",
    "evaluation": r"[一-龠々〆〤ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]",
    "wolf_strings": r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+",
    "disp_list": r'"([^"]*[一-龠ぁ-ゔァ-ヴー]+[^"]*)"',
    "playtest": "[ぁ-ゔァ-ヴ一-龠々〆〤]",
}
# Japanese letters, util/source_text's rule: 々〆〇, kana, kanji and
# half-width kana. The middle dot and long vowel mark (・ー), which English
# uses as bullets and dashes, are not letters, nor are the voicing marks
# (゛゜, ﾞﾟ and their combining forms): in Japanese one always follows a kana,
# which reads as a letter itself, and alone it is a symbol, such as the eyes
# of the kaomoji (ﾟдﾟ).
JAPANESE_LETTERS = (
    r"々-〇ぁ-ゖゝ-ヺㇰ-ㇿ"
    rf"㐀-䶿一-鿿豈-﫿{HALF_WIDTH_LETTERS}"
)
KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# Kana letters: hiragana, katakana and half-width katakana, which Japanese
# writes and Chinese does not.
KANA = re.compile(rf"[ぁ-ゖァ-ヺ{HALF_WIDTH_LETTERS}]")

# Latin letters: ASCII and the accented letters of Latin-1 and Latin
# Extended-A and B, without × and ÷.
LATIN_LETTERS = r"A-Za-zÀ-ÖØ-öø-ɏ"
# What holds Latin letters without being text: the control codes and
# placeholders util/runtime_text protects, with their arguments, markup tags
# such as <br> or <WordWrap> and {name} placeholders.
MARKUP = (
    "(?:"
    + "|".join(PROTECTED_PATTERNS)
    + r"|__PROTECTED_\d+__|</?[A-Za-z][\w-]*(?::[^<>\n]*)?>|\{[A-Za-z_]\w*\})"
)
# English text as a pattern the engines search a value with: a Latin letter
# outside markup. Searched from the start, each code is taken whole, so a
# letter of its name or argument never matches on its own.
ENGLISH_PATTERN = rf"^(?>{MARKUP}|[^{LATIN_LETTERS}])*+[{LATIN_LETTERS}]+"
# English text by the readers whose Japanese pattern captures it or that
# read no control codes: the quoted strings of a plugin's disp_list, and for
# the release playtest a word of two letters or more with a small one, since
# a translation keeps abbreviations such as HP in capitals. The others search
# with ENGLISH_PATTERN.
ENGLISH_PATTERNS = {
    "disp_list": rf'"([^"]*[{LATIN_LETTERS}][^"]*)"',
    "playtest": r"\b(?=[A-Za-z]*[a-z])[A-Za-z]{2,}",
}
# An English run, as the census counts text: from a letter, digit or opening
# parenthesis to the last letter, digit or closing mark before a break,
# through spaces and the punctuation of a sentence. Searched in text whose
# markup is taken out, it must hold a letter.
ENGLISH_RUN = (
    rf"[({LATIN_LETTERS}0-9]"
    rf"(?:[{LATIN_LETTERS}0-9 '’,.!?;:&%()/+*#~-]*[{LATIN_LETTERS}0-9.!?)])?"
)


def script(language) -> str:
    """The script *language* is written in; an unknown name reads as Latin."""
    return _SCRIPTS.get(str(language or "").strip().casefold(), LATIN)


def target_uses_cjk(language) -> bool:
    """Whether a target language is Chinese or Japanese, which are written
    with full-width punctuation."""
    return script(language) in {"chinese", "japanese"}


def shares_kanji(source=None, target=None) -> bool:
    """Whether a translation from *source* into *target*, the active pair
    by default, writes with the source's own letters: Japanese into Chinese,
    whose hanzi are kanji, so only kana read as Japanese left in it."""
    return (source or active_source()) == JAPANESE and script(
        target or active_target()
    ) == "chinese"


def source_language(value) -> str:
    """*value* as a supported source language, matched in any case."""
    for language in SOURCE_LANGUAGES:
        if str(value or "").strip().casefold() == language.casefold():
            return language
    raise ValueError(
        "Choose a source language DazedTL supports: "
        + ", ".join(SOURCE_LANGUAGES)
        + "."
    )


def pair_problem(source, target) -> str | None:
    """Why DazedTL can't translate *source* into *target*, or None: a pair
    whose languages share a script can't tell text left from translated."""
    if script(source) == script(target):
        return (
            f"DazedTL can't translate {source} into {str(target).strip()}: "
            "both are written in the same script, so it can't tell which "
            "text is left to translate. Choose a target written in another "
            "script."
        )
    return None


# The source and target languages work on one game reads in, in a process
# that serves several games, such as the app's (`reading`).
_READING: ContextVar[str | None] = ContextVar("source_language", default=None)
_TARGET: ContextVar[str | None] = ContextVar("target_language", default=None)


@contextmanager
def reading(language, target=None):
    """Reads text as written in the source *language*, and translated into
    *target* when given, within the block, in this thread or task."""
    token = _READING.set(source_language(language))
    named = str(target or "").strip()
    target_token = _TARGET.set(named) if named else None
    try:
        yield
    finally:
        if target_token is not None:
            _TARGET.reset(target_token)
        _READING.reset(token)


def active_source() -> str:
    """The source language of the work at hand: the one `reading` names, or
    the run's, which a run worker's environment carries; Japanese when
    neither is set."""
    value = _READING.get() or os.getenv(SOURCE_ENV)
    return source_language(value) if value else DEFAULT_SOURCE


def active_target() -> str:
    """The target language of the work at hand: the one `reading` names, or
    the run's ``language`` setting, which a run worker's environment
    carries; English when neither is set."""
    return _TARGET.get() or (os.getenv("language") or "").strip() or ENGLISH


def source_pattern(variant="common", language=None) -> str:
    """The pattern that finds text in the source *language*, the active
    source by default: a Japanese source's *variant*, each reader's own, or
    the English one."""
    language = language or active_source()
    if language == JAPANESE:
        return JAPANESE_PATTERNS[variant]
    return ENGLISH_PATTERNS.get(variant, ENGLISH_PATTERN)
