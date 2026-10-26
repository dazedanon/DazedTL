"""A game's language pair: the source language its text is written in and
the target its runs translate into (util/languages).

Set up records Settings' pair in the game's `.dazedtl/settings.json`, and
every run on the game reads it from there. A game without a recorded pair
translates Japanese into the target Settings name, as every game did before
the source became a setting; Set up leaves such a pair unrecorded, since
writing it would change the game settings saved translation work is bound
to.
"""

# Imported when used: test stand-ins for the engine's util package may be
# in place when settings are first imported.


def source_language(value):
    """*value* as a supported source language (util/languages)."""
    from dazedtl.languages import source_language

    return source_language(value)


def problem(source, target):
    """Why DazedTL can't translate *source* into *target*, or None."""
    from dazedtl.languages import pair_problem

    return pair_problem(source, target)


def default(settings):
    """The pair of a game without one: Japanese into Settings' target."""
    from dazedtl.languages import DEFAULT_SOURCE

    return {"source": DEFAULT_SOURCE, "target": settings.language()}


def pair(settings, root):
    """The language pair runs on the game at *root* translate between."""
    from dazedtl.languages import load_language_pair

    return load_language_pair(root) or default(settings)


def record(settings, root):
    """Records Settings' pair in the game at *root* when it has none and
    Settings' source is not the default, as Set up starts."""
    from util.game_settings import save_language_pair

    from dazedtl.compatibility.game_write import write_game
    from dazedtl.languages import DEFAULT_SOURCE, load_language_pair

    source = settings.source_language()
    if source == DEFAULT_SOURCE or load_language_pair(root) is not None:
        return
    target = settings.language()
    refused = problem(source, target)
    if refused:
        raise ValueError(refused)
    with write_game(
        root, pack=False, summary="Record the game's languages", stage="Set up"
    ):
        save_language_pair(root, source, target)


def frozen(value, language_pair):
    """*value*, a run's settings, with the pair's target as its language and
    a source other than Japanese named, so a Japanese source's runs freeze
    what they froze before the source became a setting. Settings and the
    game's settings refuse a pair whose languages share a script."""
    from dazedtl.languages import JAPANESE, SOURCE_ENV

    value = {**value, "language": language_pair["target"]}
    if language_pair["source"] != JAPANESE:
        value[SOURCE_ENV] = language_pair["source"]
    return value


def run_source(value):
    """The source language a run's frozen settings name."""
    from dazedtl.languages import JAPANESE, SOURCE_ENV

    return (value or {}).get(SOURCE_ENV, JAPANESE)
