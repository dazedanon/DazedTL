"""Text QA's pronoun rule: a he or she the English gives a character the
game's glossary gives the other gender.

Japanese drops pronouns and translation supplies them, so one can slip
against a character's gender. Each name the glossary gives a gender opens a
window that closes at the next mention of any glossary name, at the end of
its paragraph, or WINDOW characters on; the first pronoun of the other gender
after the name, inside that window, likely means that character (the
next-name window of Len's game-translation skill,
references/glossary-and-prompts.md). A pronoun for someone the glossary does
not name can fall in the window too, so a reviewer judges each one.

Text QA reads each scene as one document, and every other line as its own;
qa --check (translation/result_checks.py) reads an Assistant-led export the
same way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

from util.languages import tag
from util.rpgmaker_qa_glossary import genders

# The check's name, in deep review and in qa --check.
CHECK = "gender-pronoun"
# Characters after a name that its window reaches at most.
WINDOW = 180
OPPOSING = {
    "Female": ("he", "him", "his", "himself"),
    "Male": ("she", "her", "hers", "herself"),
}
_PRONOUNS = {
    gender: re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)
    for gender, words in OPPOSING.items()
}
# Paragraphs are separated by a blank line.
_PARAGRAPH = re.compile(r"\n[ \t]*\n")
# What may stand before a name that labels its row's speaker: control codes,
# a name window's \n< and an opening bracket.
_LABEL_START = re.compile(
    r"(?:\s|\\+[A-Za-z]+(?:\[[^\]\n]*\])?|\\+[{}.!|^><]|[\[【<(（])*"
)
# What follows that name: control codes, then a closing bracket or a colon.
_LABEL_END = re.compile(r"(?:\s|\\+[A-Za-z]+(?:\[[^\]\n]*\])?)*[\]】>)）:：]")


class Cast(NamedTuple):
    """The characters the glossary gives a gender, and their names as one
    pattern, longest first, so "Mina Ashford" is found before "Mina"."""

    genders: dict[str, str]
    pattern: re.Pattern[str] | None


class Slip(NamedTuple):
    """A pronoun of the other gender after a character's name: in which of a
    document's texts, whose name, the glossary's gender, and the pronoun."""

    index: int
    name: str
    gender: str
    pronoun: str


def cast(glossary_text: str | None, target: str) -> Cast:
    """The characters of a game's glossary the rule reads, for a translation
    into *target*: none unless it is English, whose pronouns it knows."""
    found = genders(glossary_text) if tag(target) == "en" else {}
    names = sorted(found, key=lambda name: (-len(name), name))
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(map(re.escape, names)) + r")(?:['’]s)?(?!\w)"
    ) if names else None
    return Cast(found, pattern)


def _label(paragraph: str, mention: re.Match[str]) -> bool:
    """Whether a name labels its row's speaker, as in "Ken: She's late." or
    \\n<Ken>, rather than naming someone in the text."""
    row = paragraph.rfind("\n", 0, mention.start()) + 1
    return bool(
        _LABEL_START.fullmatch(paragraph, row, mention.start())
        and _LABEL_END.match(paragraph, mention.end())
    )


def slips(texts: Iterable[str], characters: Cast) -> list[Slip]:
    """Each pronoun of the other gender inside a glossary name's window, in
    one document's *texts* in order, reported the first time each
    (character, pronoun) meets it."""
    found: list[Slip] = []
    if characters.pattern is None:
        return found
    seen: set[tuple[str, str]] = set()
    for index, text in enumerate(texts):
        for paragraph in _PARAGRAPH.split(str(text)):
            mentions = list(characters.pattern.finditer(paragraph))
            for position, mention in enumerate(mentions):
                if _label(paragraph, mention):
                    continue
                name = mention.group(1)
                gender = characters.genders[name]
                following = (
                    mentions[position + 1].start()
                    if position + 1 < len(mentions) else len(paragraph)
                )
                closes = min(following, mention.end() + WINDOW)
                pronoun = _PRONOUNS[gender].search(paragraph, mention.end())
                if pronoun is None or pronoun.start() >= closes:
                    continue
                key = (name, pronoun.group(1).casefold())
                if key not in seen:
                    seen.add(key)
                    found.append(Slip(index, name, gender, key[1]))
    return found


def note(slip: Slip) -> str:
    """What a reviewer reads of a slip."""
    return (
        f'The glossary gives {slip.name} as {slip.gender}, and "{slip.pronoun}" '
        "follows the name before any other name does."
    )
