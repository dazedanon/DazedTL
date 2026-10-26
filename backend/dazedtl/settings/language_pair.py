"""A game's language pair: the source language its text is written in and
the target its runs translate into (util/languages).

Settings name the pair new games start with. Set up records it in the
game's `.dazedtl/settings.json`, where the user can change it until the game
has work, and every run on the game reads it from there. A game set up
before pairs were recorded translates Japanese into the target Settings
name (`default`), as every game did before the source became a setting; the
app records that pair when it opens the game and before Settings' defaults
change (`keep`, projects/languages), so a later change to the defaults
leaves it as it was. A Japanese source's record is left out of the settings
saved work binds (util/game_settings.binding_bytes), so recording it never
makes that work read Outdated.
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
    """The pair of a game set up before pairs were recorded: Japanese into
    Settings' target."""
    from dazedtl.languages import DEFAULT_SOURCE

    return {"source": DEFAULT_SOURCE, "target": settings.language()}


def pair(settings, root):
    """The language pair runs on the game at *root* translate between: its
    own, or for a game without one, `default` once it is set up, which
    recorded its original files, else the pair Set up will record,
    Settings'."""
    from dazedtl.compatibility.original_files import recorded
    from dazedtl.languages import load_language_pair

    found = load_language_pair(root)
    if found:
        return found
    if recorded(root):
        return default(settings)
    return {"source": settings.source_language(), "target": settings.language()}


def record(settings, root):
    """Records Settings' pair in the game at *root* when it has none, as Set
    up starts."""
    from dazedtl.languages import load_language_pair

    if load_language_pair(root) is None:
        choose(root, settings.source_language(), settings.language())


def keep(settings, root):
    """Records `default` in a game without a pair, set up before pairs were
    recorded, so its work keeps translating that pair whatever Settings name
    later; True when it wrote the record."""
    from dazedtl.languages import load_language_pair

    if load_language_pair(root) is not None:
        return False
    pair = default(settings)
    choose(root, pair["source"], pair["target"])
    return True


def choose(root, source, target):
    """Records *source* into *target* as the pair of the game at *root*."""
    from util.game_settings import save_language_pair

    from dazedtl.compatibility.game_write import write_game

    source = source_language(source)
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
