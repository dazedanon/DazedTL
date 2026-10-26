"""The languages DazedTL translates between, defined once in the bundled
engine's ``util/languages.py`` so run workers follow it without importing
the app; this module makes it importable from the app, with the game's own
source language."""

import sys
from pathlib import Path

from dazedtl.compatibility.runtime import ENGINE_ROOT

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from util.languages import (
    DEFAULT_SOURCE,
    ENGLISH,
    ENGLISH_RUN,
    JAPANESE,
    LATIN_LETTERS,
    MARKUP,
    SOURCE_ENV,
    SOURCE_LANGUAGES,
    active_source,
    active_target,
    language,
    pair_problem,
    reading,
    script,
    source_language,
    source_pattern,
    tag,
    target_uses_cjk,
)
from util.prompt_pair import pair_note, request_headings

__all__ = [
    "DEFAULT_SOURCE",
    "ENGLISH",
    "ENGLISH_RUN",
    "JAPANESE",
    "LATIN_LETTERS",
    "MARKUP",
    "SOURCE_ENV",
    "SOURCE_LANGUAGES",
    "active_source",
    "active_target",
    "game_source",
    "language",
    "load_language_pair",
    "pair_note",
    "pair_problem",
    "read_source",
    "reading",
    "reading_game",
    "request_headings",
    "script",
    "source_language",
    "source_pattern",
    "tag",
    "target_uses_cjk",
]


def load_language_pair(root: str | Path) -> dict[str, str] | None:
    """The language pair recorded in the game at *root* (util/game_settings)."""
    from util.game_settings import load_language_pair

    return load_language_pair(root)


def game_source(root: str | Path) -> str:
    """The source language of the game at *root* (util/game_settings)."""
    from util.game_settings import game_source_language

    return game_source_language(root)


def read_source(root: str | Path) -> str:
    """The language to read the text of the game at *root* in: its source
    language, or Japanese, the source of every game set up before the
    source became a setting, when its settings can't be read; its run start
    reports that problem."""
    try:
        return game_source(root)
    except OSError, ValueError:
        return DEFAULT_SOURCE


def reading_game(root: str | Path):
    """Reads text in the language of the game at *root* (`read_source`),
    translated into the target its pair records, within the block; a game
    without a pair, or whose settings can't be read, reads for the run's
    target."""
    try:
        pair = load_language_pair(root)
    except OSError, ValueError:
        pair = None
    return reading(read_source(root), pair["target"] if pair else None)
