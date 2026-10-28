"""Prompt text that follows a run's language pair (util/languages).

The base translation rules, data/skills/system.md, are a template on the
run's source and target, and the request headings and assistant briefs name
the languages from here, so everything a run sends reads the same pair.
Japanese to English renders exactly as it read before the languages became a
setting, so the requests, estimates and caches made before stay current.

The template's syntax, each control on a line of its own:

    {{source}}, {{target}}          the languages' names, anywhere in a line
    {{#source X}} ... {{/source}}   kept only when the source is X
    {{^source X}} ... {{/source}}   kept when the source is not X
    {{#target X}}, {{^target X}} and {{/target}} the same on the target
    {{! ... }}                      a comment
    {{! end }}                      the template's end: what follows, such
                                    as a game's own guidance, is kept as it is

A Japanese source's rules then name the target in place of English, as
every run did before the languages became a setting, game guidance and a
profile's own copy of system.md included. Text without controls renders as
it is otherwise, and rendered text renders as itself.
"""

import os
import re
from functools import lru_cache

from util.languages import ENGLISH, JAPANESE, SOURCE_ENV, SOURCE_LANGUAGES, active_source

_CONTROL = re.compile(r"\{\{([#^/])(source|target)(?: ([^{}]+))?\}\}")
_COMMENT = re.compile(r"\{\{!.*\}\}")
_END = "{{! end }}"

# The headings of a request's parts, which the app reads saved requests by.
INSTRUCTIONS_HEADING = "Request Instructions:"
GLOSSARY_HEADING = "Here are glossary entries"
SFX_HEADING = "Japanese SFX reference"


def run_language(value=None) -> str:
    """A run's target as the engine names it: *value*, or the run's
    ``language`` setting, capitalized."""
    return (value or os.getenv("language", "english")).capitalize()


def _same(language, name) -> bool:
    return str(language).strip().casefold() == name.strip().casefold()


def render(text: str, source=None, target=None) -> str:
    """*text*, a template on the languages, for translating *source*, the
    active source by default, into *target*, the run's by default."""
    return _render(text, source or active_source(), target or run_language())


# A run renders the same rules for each of its requests.
@lru_cache(maxsize=32)
def _render(text: str, source: str, target: str) -> str:
    values = {"source": source, "target": target}
    kept, out = [], []
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if body == _END:
            out.extend(lines[index + 1 :])
            break
        if _COMMENT.fullmatch(body):
            continue
        control = _CONTROL.fullmatch(body)
        if control is None:
            if all(keep for _field, keep in kept):
                out.append(
                    line.replace("{{source}}", source).replace("{{target}}", target)
                )
            continue
        kind, field, name = control.groups()
        if kind == "/":
            if not kept or kept[-1][0] != field or name:
                raise ValueError(f"The prompt template closes {body} out of turn.")
            kept.pop()
            continue
        if not name:
            raise ValueError(f"The prompt template's {body} names no language.")
        kept.append((field, _same(values[field], name) == (kind == "#")))
    if kept:
        raise ValueError("The prompt template leaves a part open.")
    result = "".join(out)
    return result.replace(ENGLISH, target) if source == JAPANESE else result


def render_for_run(raw: bytes, settings: dict) -> bytes:
    """A template file's bytes, *raw*, rendered for a run with the engine
    *settings*, which name its target and any source but Japanese, keeping
    the file's line endings."""
    source = settings.get(SOURCE_ENV) or JAPANESE
    target = run_language(settings.get("language"))
    return render(raw.decode("utf-8"), source, target).encode("utf-8")


def source_context_heading(source=None) -> str:
    """The heading of a request's preceding source lines, which the app
    finds them by."""
    return f"Preceding {source or active_source()} Source Context"


def source_context_note(source=None) -> str:
    """The heading and note before a request's preceding source lines."""
    source = source or active_source()
    return (
        f"{source_context_heading(source)} (untranslated):\n"
        f"Use these lines only to understand the scene. Do not copy {source} "
        "spellings from them or treat them as approved terminology; the "
        "glossary is authoritative."
    )


def delivered_note(source=None, target=None) -> str:
    """The heading and note before the translation already delivered for a
    request's preceding source lines."""
    source = source or active_source()
    target = target or run_language()
    return (
        f"Preceding {target} Translation (already delivered):\n"
        f"The {target} for the same preceding lines, in order. Where the scene "
        "continues, keep its narration tense, forms of address, and voice; do "
        f"not repeat or revise it. The {source} source and the glossary stay "
        "authoritative."
    )


def delivered_block(lines, source=None, target=None) -> str:
    """The block a later Live request of a split scene sends after its
    preceding source lines, holding the translation already delivered for
    them, one line after another; both methods send it."""
    return delivered_note(source, target) + "\n```\n" + "\n".join(lines) + "\n```"


def request_headings() -> dict:
    """The headings the app reads a saved request's parts by: its matched
    glossary and SFX reference, its preceding source lines in any source
    language, and its own instructions."""
    return {
        "glossary": GLOSSARY_HEADING,
        "sfx": SFX_HEADING,
        "sourceContext": [source_context_heading(language) for language in SOURCE_LANGUAGES],
        "instructions": INSTRUCTIONS_HEADING,
    }


def pair_note(source, target) -> str:
    """What an assistant brief adds for a pair other than Japanese into
    English, the pair the skills and briefs are written for; "" for it."""
    english_target = _same(target, ENGLISH)
    if source == JAPANESE and english_target:
        return ""
    parts = [
        f"Languages: this game's text is in {source}; translate it into {target}.",
        "Len's skills and references are written for a Japanese game translated "
        f"into English: where they name the languages, read Japanese as {source} "
        f"and English as {target}.",
    ]
    if source != JAPANESE:
        parts.append(
            "Their guidance on Japanese itself, such as honorifics, kana, dropped "
            "pronouns, particles, the SFX dictionary and the base glossary, does "
            "not apply."
        )
    if not english_target:
        parts.append(
            "Their rules for English text, such as contractions and the ASCII "
            "apostrophe, do not apply; write as "
            f"{target} games are written."
        )
    return " ".join(parts) + "\n\n"
