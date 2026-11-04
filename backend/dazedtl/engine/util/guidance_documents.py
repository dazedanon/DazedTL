"""What each guidance document of a game is, defined once.

The glossary, the style and quirks, the game context and the custom skills
are what translation requests carry; the assistant notes, AGENTS.md at the
game's root, are what every assistant reads first and keeps, and no request
carries them. Every place that treats them differently reads the properties
here instead of a document's name: both methods' editors and their titles,
the save, the work an unsaved draft holds up, translation requests and how
checkpoints move each file. A new kind of document is a new definition.
"""

from dataclasses import dataclass

from util.paths import (
    GAME_METADATA_RELATIVE,
    GAME_NOTES_FILENAME,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILLS_RELATIVE,
    GLOSSARY_FILENAME,
    LEGACY_GAME_SKILLS_RELATIVE,
    LEGACY_QUIRKS_FILENAME,
    is_game_notes,
)

# The work an unsaved draft can hold up: handing a task to an assistant,
# which reads every document from its file, and the work that reads what
# translation requests carry, such as preparing, estimating, running,
# approving, and the operations Plugin files, Images and the project helper
# start.
HANDOFF = "handoff"
REQUEST_WORK = "work"

CUSTOM_PREFIX = "custom:"


@dataclass(frozen=True)
class Definition:
    """One guidance document.

    `path` is its file, relative to the game, and `legacy` the files earlier
    versions kept it in, which a save moves into `path`. `kind` is "core"
    for the documents Guidance needs, "optional" for one that may never
    exist, and "custom" for a skill the game adds. `requests` says whether
    translation requests carry it. `created` is "always" when Save creates
    its file even empty, which completes Guidance, or "with_text" when only
    text creates it. `checkpoints` is "move" when undo and Go back put its
    file back with the rest of the game, or "keep" when every checkpoint but
    its own, Go back and Start over leave it as it is. `holds_up` is the work
    an unsaved draft of it holds up. `any_case` matches its file name in any
    case, as assistants and Windows name it. A document requests don't
    carry says what it is for in `description`, with `help` on where it is
    kept, {file} naming its file, which the editors show in place of the
    file."""

    key: str
    path: str
    title: str
    kind: str
    requests: bool
    created: str
    checkpoints: str
    holds_up: frozenset[str]
    legacy: tuple[str, ...] = ()
    any_case: bool = False
    description: str = ""
    help: str = ""

    def matches(self, relative):
        """Whether a game-relative path is this document's file."""
        return is_game_notes(relative) if self.any_case else relative == self.path

    @property
    def skill(self):
        """Whether its file is a skill, which the former root skills folder
        held too."""
        return self.path.startswith(GAME_SKILLS_RELATIVE.as_posix() + "/")


def _guidance(key, path, title, legacy):
    return Definition(
        key=key,
        path=path,
        title=title,
        kind="core",
        requests=True,
        created="always",
        checkpoints="move",
        holds_up=frozenset({HANDOFF, REQUEST_WORK}),
        legacy=legacy,
    )


GLOSSARY = _guidance(
    "glossary",
    (GAME_METADATA_RELATIVE / GLOSSARY_FILENAME).as_posix(),
    "Glossary",
    (GLOSSARY_FILENAME,),
)
QUIRKS = _guidance(
    "quirks",
    GAME_QUIRKS_RELATIVE.as_posix(),
    "Style & quirks",
    (LEGACY_QUIRKS_FILENAME,),
)
GAME_CONTEXT = _guidance(
    "game",
    GAME_SKILL_RELATIVE.as_posix(),
    "Game context",
    ((LEGACY_GAME_SKILLS_RELATIVE / "translation.md").as_posix(),),
)
# Every assistant task edits them, with its own tools and in any encoding,
# so a draft of them holds up only handing a task to an assistant, which
# would read the file without it; they describe the game rather than a state
# of its translation, so translation checkpoints leave them.
ASSISTANT_NOTES = Definition(
    key="notes",
    path=GAME_NOTES_FILENAME,
    title="Assistant notes",
    kind="optional",
    requests=False,
    created="with_text",
    checkpoints="keep",
    holds_up=frozenset({HANDOFF}),
    any_case=True,
    description="Notes every assistant reads first and keeps current. Never sent"
    " with translation requests.",
    help="Saved as {file} in the game folder and kept in the game's Git, so they"
    " reach other computers and assistants, and anyone who can see the game's"
    " repository. Players' downloads leave them out.",
)
# In the editors' tab order; custom skills follow.
FIXED = (GLOSSARY, QUIRKS, GAME_CONTEXT, ASSISTANT_NOTES)


def custom(stem):
    """A custom skill the game adds, named `stem`."""
    return Definition(
        key=CUSTOM_PREFIX + stem,
        path=(GAME_SKILLS_RELATIVE / f"{stem}.md").as_posix(),
        title=f"Skill: {stem}",
        kind="custom",
        requests=True,
        created="with_text",
        checkpoints="move",
        holds_up=frozenset({HANDOFF, REQUEST_WORK}),
        legacy=((LEGACY_GAME_SKILLS_RELATIVE / f"{stem}.md").as_posix(),),
    )


def definition(key):
    """The definition of the document named `key`, or None for a name no
    document has."""
    for fixed in FIXED:
        if key == fixed.key:
            return fixed
    if not isinstance(key, str) or not key.startswith(CUSTOM_PREFIX):
        return None
    from util.skills import sanitize_custom_skill_stem

    stem = key.removeprefix(CUSTOM_PREFIX)
    try:
        return custom(stem) if stem and sanitize_custom_skill_stem(stem) == stem else None
    except ValueError:
        return None


def defined(key):
    """The definition of a document `key` names, such as one the reader
    listed; a name no document has is refused."""
    found = definition(key)
    if found is None:
        raise ValueError("Choose a guidance document below 1 MB.")
    return found


def kept_by_checkpoints(relative):
    """Whether a game-relative path is a document every checkpoint but its
    own, Go back and Start over leave as it is."""
    return any(
        fixed.checkpoints == "keep" and fixed.matches(relative) for fixed in FIXED
    )


def save_summary(keys):
    """The checkpoint name of a save of the documents `keys`, in both
    methods."""
    return "Save " + ", ".join(defined(key).title for key in keys)
