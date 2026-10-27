"""The languages DazedTL translates between: each language's script, and for
a game's source language the patterns that tell text still in it, which
decide what a run sends, what Lines reads as left and what the census counts.
Settings, the engine and the app read them here.

A pair is supported when its source and target use different scripts, so a
value's letters tell whether it still needs translating. The source is one
of SOURCE_LANGUAGES; a target is free text that names a language one way
or another (`language`), and a name DazedTL doesn't know is refused, never
read as Latin script. Chinese shares a Japanese source's
kanji, so in a translation into it only kana tell Japanese left
(`shares_kanji`).

A Japanese source keeps each engine's own pattern exactly, by variant name:
merging them would change what existing runs send. An English source reads
Latin letters outside control codes and their arguments.
"""

import os
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import NamedTuple

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


class Language(NamedTuple):
    """A language as a pair names it: the script it is written in and its
    BCP 47 tag, which the app gives text in it so the system draws that
    language's forms, such as Japanese kanji over Chinese ones."""

    script: str
    tag: str


# The languages a pair can name, by English name: the script each is written
# in and its tag, with the other names a user may give it, its own name and
# its ISO 639 codes (`language`).
_LANGUAGES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "japanese": ("japanese", "ja", ("日本語", "ja", "jp", "jpn")),
    "chinese": (
        "chinese",
        "zh",
        (
            "中文", "汉语", "漢語", "华语", "華語", "普通话", "普通話", "国语",
            "國語", "粤语", "粵語", "mandarin", "cantonese", "zh", "zho", "chi",
        ),
    ),
    "korean": ("korean", "ko", ("한국어", "조선어", "ko", "kor")),
    "english": (LATIN, "en", ("en", "eng")),
    "spanish": (LATIN, "es", ("español", "castellano", "castilian", "es", "spa")),
    "portuguese": (LATIN, "pt", ("português", "pt", "por")),
    "french": (LATIN, "fr", ("français", "fr", "fra", "fre")),
    "german": (LATIN, "de", ("deutsch", "de", "deu", "ger")),
    "italian": (LATIN, "it", ("italiano", "it", "ita")),
    "dutch": (LATIN, "nl", ("nederlands", "flemish", "nl", "nld", "dut")),
    "polish": (LATIN, "pl", ("polski", "pl", "pol")),
    "czech": (LATIN, "cs", ("čeština", "cs", "ces", "cze")),
    "slovak": (LATIN, "sk", ("slovenčina", "sk", "slk")),
    "hungarian": (LATIN, "hu", ("magyar", "hu", "hun")),
    "romanian": (LATIN, "ro", ("română", "ro", "ron", "rum")),
    "croatian": (LATIN, "hr", ("hrvatski", "hr", "hrv")),
    "slovenian": (LATIN, "sl", ("slovene", "slovenščina", "sl", "slv")),
    "swedish": (LATIN, "sv", ("svenska", "sv", "swe")),
    "norwegian": (LATIN, "no", ("norsk", "bokmål", "nynorsk", "no", "nb", "nn", "nor")),
    "danish": (LATIN, "da", ("dansk", "da", "dan")),
    "finnish": (LATIN, "fi", ("suomi", "fi", "fin")),
    "icelandic": (LATIN, "is", ("íslenska", "is", "isl")),
    "estonian": (LATIN, "et", ("eesti", "et", "est")),
    "latvian": (LATIN, "lv", ("latviešu", "lv", "lav")),
    "lithuanian": (LATIN, "lt", ("lietuvių", "lt", "lit")),
    "turkish": (LATIN, "tr", ("türkçe", "tr", "tur")),
    "vietnamese": (LATIN, "vi", ("tiếng việt", "vi", "vie")),
    "indonesian": (LATIN, "id", ("bahasa indonesia", "id", "ind")),
    "malay": (LATIN, "ms", ("bahasa melayu", "ms", "msa", "may")),
    "filipino": (LATIN, "fil", ("tagalog", "fil", "tl", "tgl")),
    "catalan": (LATIN, "ca", ("català", "ca", "cat")),
    "galician": (LATIN, "gl", ("galego", "gl", "glg")),
    "basque": (LATIN, "eu", ("euskara", "eu", "eus")),
    "irish": (LATIN, "ga", ("gaeilge", "ga", "gle")),
    "welsh": (LATIN, "cy", ("cymraeg", "cy", "cym")),
    "albanian": (LATIN, "sq", ("shqip", "sq", "sqi")),
    "esperanto": (LATIN, "eo", ("eo", "epo")),
    "latin": (LATIN, "la", ("latina", "la", "lat")),
    "swahili": (LATIN, "sw", ("kiswahili", "sw", "swa")),
    "afrikaans": (LATIN, "af", ("af", "afr")),
    "russian": ("cyrillic", "ru", ("русский", "ru", "rus")),
    "ukrainian": ("cyrillic", "uk", ("українська", "uk", "ukr")),
    "belarusian": ("cyrillic", "be", ("беларуская", "be", "bel")),
    "bulgarian": ("cyrillic", "bg", ("български", "bg", "bul")),
    "serbian": ("cyrillic", "sr", ("српски", "sr", "srp")),
    "macedonian": ("cyrillic", "mk", ("македонски", "mk", "mkd")),
    "kazakh": ("cyrillic", "kk", ("қазақ", "kk", "kaz")),
    "mongolian": ("cyrillic", "mn", ("монгол", "mn", "mon")),
    "greek": ("greek", "el", ("ελληνικά", "el", "ell", "gre")),
    "arabic": ("arabic", "ar", ("العربية", "ar", "ara")),
    "persian": ("arabic", "fa", ("farsi", "فارسی", "fa", "fas", "per")),
    "urdu": ("arabic", "ur", ("اردو", "ur", "urd")),
    "hebrew": ("hebrew", "he", ("עברית", "he", "heb")),
    "thai": ("thai", "th", ("ไทย", "th", "tha")),
    "hindi": ("devanagari", "hi", ("हिन्दी", "हिंदी", "hi", "hin")),
    "bengali": ("bengali", "bn", ("bangla", "বাংলা", "bn", "ben")),
}
# Tags Chinese is written by, as a qualifier names the variety.
_CHINESE_TAGS = {
    "simplified": "zh-Hans", "hans": "zh-Hans", "简体": "zh-Hans",
    "簡體": "zh-Hans", "简": "zh-Hans", "mainland": "zh-Hans", "china": "zh-Hans",
    "prc": "zh-Hans", "singapore": "zh-Hans", "大陆": "zh-Hans", "大陸": "zh-Hans",
    "cn": "zh-Hans", "sg": "zh-Hans", "traditional": "zh-Hant", "hant": "zh-Hant",
    "繁體": "zh-Hant", "繁体": "zh-Hant", "繁": "zh-Hant", "taiwan": "zh-Hant",
    "taiwanese": "zh-Hant", "hong": "zh-Hant", "kong": "zh-Hant",
    "macau": "zh-Hant", "macao": "zh-Hant", "台灣": "zh-Hant", "台湾": "zh-Hant",
    "香港": "zh-Hant", "tw": "zh-Hant", "hk": "zh-Hant", "mo": "zh-Hant",
}
# Words a name may add beside its language outside brackets: the variety or
# the place it is written in, as in Simplified Chinese or Brazilian
# Portuguese, or its script, as in Serbian Latin.
_QUALIFIERS = frozenset(
    (
        *_CHINESE_TAGS,
        *(
            "brazilian european american latin mexican british australian "
            "canadian international standard modern cyrillic us uk"
        ).split(),
    )
)
_NAMES = {
    alias.casefold(): english
    for english, (_script, _tag, aliases) in _LANGUAGES.items()
    for alias in (english, *aliases)
}
# A qualifier in brackets, as in Portuguese (Brazil) or 中文（简体）.
_BRACKETS = re.compile(r"[(\[（【]([^)\]）】]*)[)\]）】]")
# What separates a name's words.
_SEPARATORS = re.compile(r"[\s,/·・_-]+")
# A BCP 47 tag: a language code and its region or script, such as zh-Hant.
_CODE = re.compile(r"([a-z]{2,3})(?:[-_][a-z0-9]{2,8})*")
# The names and qualifiers written without spaces, at which a run such as
# 简体中文 splits.
_CJK_NAMES = re.compile(
    "|".join(
        sorted(
            (re.escape(name) for name in (*_NAMES, *_QUALIFIERS) if not name.isascii()),
            key=len,
            reverse=True,
        )
    )
)

# Japanese text by each reader's own pattern. COMMON is the engines' shared
# LANGREGEX and the translator's default; MVMZ is RPG Maker MV/MZ's, which
# leaves out the voicing marks and full-width Latin; SRPG is SRPG Studio's;
# IMAGETEXT is image text's, COMMON spelled with literal half-width forms.
# The others are single readers' own: the census's runs and the letters a run
# must hold, plugin and Ruby script text, the desktop project's database
# records, game update text, the evaluation's segments,
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


@lru_cache(maxsize=64)
def language(name) -> Language | None:
    """The language *name* names, or None for a name DazedTL doesn't know,
    which a pair refuses (`pair_problem`). A name is the language's English
    name, its own or a code, such as Chinese, 中文 or zh-TW, with qualifiers
    in brackets, such as Portuguese (Brazil), or beside it from a short list,
    such as Simplified Chinese or Serbian Latin."""
    text = unicodedata.normalize("NFKC", str(name or "")).strip().casefold()
    qualifiers = _words(" ".join(_BRACKETS.findall(text)))
    base = _BRACKETS.sub(" ", text).strip()
    code = _CODE.fullmatch(base)
    if base in _NAMES:
        found = _NAMES[base]
    elif code and code[1] in _NAMES:
        found = _NAMES[code[1]]
        qualifiers += _SEPARATORS.split(base)[1:]
    else:
        words = _words(base)
        named = [word for word in words if word not in _QUALIFIERS]
        found = _NAMES.get(" ".join(named))
        if found is None:
            return None
        qualifiers += [word for word in words if word in _QUALIFIERS]
    return _language(found, qualifiers)


def _words(text: str) -> list[str]:
    """The words of *text*, a han or kana run split at the names and
    qualifiers written in it, such as 简体 and 中文."""
    found = []
    for word in _SEPARATORS.split(text):
        pieces = _CJK_NAMES.findall(word) if not word.isascii() else ()
        if word in _NAMES or "".join(pieces) != word:
            pieces = [word]
        found.extend(piece for piece in pieces if piece)
    return found


def _language(english: str, qualifiers: list[str]) -> Language:
    """The Language of *english* as *qualifiers* write it: Chinese tagged by
    its variety, and a language written in Cyrillic or Latin letters, such
    as Serbian, in the script they name."""
    script, tag, _aliases = _LANGUAGES[english]
    if english == "chinese":
        tag = next(
            (_CHINESE_TAGS[word] for word in qualifiers if word in _CHINESE_TAGS),
            tag,
        )
    if script == "cyrillic" and "latin" in qualifiers:
        script = LATIN
    return Language(script, tag)


def script(name) -> str:
    """The script the language *name* names is written in (`language`). A
    name DazedTL doesn't know, which Settings and Set up refuse, reads as
    Latin in a pair recorded before they did."""
    found = language(name)
    return found.script if found else LATIN


def tag(name) -> str | None:
    """The BCP 47 tag of the language *name* names, or None."""
    found = language(name)
    return found.tag if found else None


def target_uses_cjk(language) -> bool:
    """Whether a target language is Chinese or Japanese, which are written
    with full-width punctuation and without spaces between words."""
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
    whose languages share a script can't tell text left from translated,
    and a target DazedTL doesn't know can't be read for its script."""
    if language(target) is None:
        return (
            f"DazedTL doesn't know the language \"{str(target or '').strip()}\", "
            "so it can't tell which text is left to translate. Name it in "
            "English, such as Simplified Chinese, Spanish or Korean."
        )
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
