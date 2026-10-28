"""Actor names in place of RPG Maker's name codes, for both methods.

A request that shows the model ``\\N[1]`` makes it write ungrammatical
English around the code and leaves it no way to tell the actor's gender, so
both methods show the actor's English name instead (substitute) and put the
code back in the reply (restore). Guided resolves names from Actors.json,
with a real given name for a blank, player-named slot (fallback_name), else
from the glossary's "actor ID n" rows (glossary_actors); Assistant-led from
those rows alone. A ``\\V[n]`` shows a name when a Control Variables script
(code 122) sets the variable to an actor's name (scan_variable_actors).
"""

import re
from collections.abc import Callable

from util.vocab import split_glossary_row

ACTOR_CODE = re.compile(r"\\n\[(\d+)\]", re.IGNORECASE)
# Game-variable nameplates (\v[X]) often mirror an actor name via code-122 script.
VARIABLE_CODE = re.compile(r"\\v\[(\d+)\]", re.IGNORECASE)
_ACTOR_NAME_SCRIPT = re.compile(
    r"\$gameActors\.actor\s*\(\s*(\d+)\s*\)\.name\s*\(\s*\)",
    re.IGNORECASE,
)
_GLOSSARY_ACTOR = re.compile(r"\s*-\s*.*?\bactor\s+ID\s+(\d+)\b", re.IGNORECASE)
# Blank Actors.json slots are usually player-entered names. Substitute a real
# given name for the model, then restore the original \n[ID] / \v[ID] code.
# Distinct names are assigned per empty actor ID for the run (Alex first).
FALLBACK_NAMES = (
    "Alex",
    "Blake",
    "Casey",
    "Drew",
    "Eden",
    "Finley",
    "Harper",
    "Jordan",
    "Kai",
    "Logan",
    "Morgan",
    "Quinn",
    "Riley",
    "Skyler",
    "Taylor",
)


def glossary_actors(glossary: str) -> dict[int, str]:
    """Actor ID -> English name from the glossary rows whose notes name the
    actor's ID, such as ``ミカ (Mika) - Female, actor ID 1``."""
    found: dict[int, str] = {}
    for line in glossary.splitlines():
        row = split_glossary_row(line)
        match = row and _GLOSSARY_ACTOR.match(row[2])
        if match and row[1]:
            found[int(match.group(1))] = row[1]
    return found


def scan_variable_actors(data, into: dict) -> None:
    """Collect code-122 script assignments of ``$gameActors.actor(N).name()``
    in one map or CommonEvents.json document into *into*, variable ID ->
    actor ID; a variable keeps the first actor found."""

    def _scan_list(lst):
        for cmd in lst or []:
            if not isinstance(cmd, dict) or cmd.get("code") != 122:
                continue
            params = cmd.get("parameters") or []
            if len(params) < 5:
                continue
            # [startId, endId, operationType, operandType, operand]
            try:
                start_id = int(params[0])
                end_id = int(params[1])
                operand_type = params[3]
                operand = params[4]
            except (TypeError, ValueError):
                continue
            if operand_type != 4 or not isinstance(operand, str):
                continue
            match = _ACTOR_NAME_SCRIPT.search(operand)
            if not match:
                continue
            actor_id = int(match.group(1))
            for var_id in range(start_id, end_id + 1):
                into.setdefault(var_id, actor_id)

    if isinstance(data, list):
        # CommonEvents.json / Troops-style top-level list
        for entry in data:
            if isinstance(entry, dict):
                _scan_list(entry.get("list"))
        return
    if not isinstance(data, dict):
        return
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        for page in ev.get("pages") or []:
            if isinstance(page, dict):
                _scan_list(page.get("list"))
    _scan_list(data.get("list"))


def fallback_name(actor_id: int, reserved: set[str], assigned: dict[int, str]) -> str:
    """A real given name for a blank, player-named actor slot.

    The first empty actor ID gets ``Alex`` unless *reserved* (the names
    Actors.json uses) or another empty slot holds it; later IDs get the next
    free roster entry. *assigned* keeps each ID's name stable for the run.
    """
    aid = int(actor_id)
    cached = assigned.get(aid)
    if cached:
        return cached

    reserved_cf = {str(n).casefold() for n in (reserved or ()) if n}
    reserved_cf |= {n.casefold() for n in assigned.values()}

    for candidate in FALLBACK_NAMES:
        if candidate.casefold() not in reserved_cf:
            assigned[aid] = candidate
            return candidate

    uniquified = f"Alex{aid}"
    assigned[aid] = uniquified
    return uniquified


NameOf = Callable[[int], str | None]


def substitute(
    text: str,
    actor_name: NameOf,
    variable_name: NameOf | None = None,
    *,
    speaker_tag: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Replace ``\\n[ID]`` with ``actor_name(ID)`` and ``\\v[ID]`` with
    ``variable_name(ID)`` for the model, leaving a code whose name is None.

    Returns ``(substituted_text, reverse_map)`` where *reverse_map* maps the
    exact display name back to the original control code for restore. With
    *speaker_tag*, the pattern of a speaker label's inside, a leading
    ``[Speaker]:`` label shows names too but restores none.
    """

    variable_name = variable_name or (lambda _identity: None)
    reverse_map: dict[str, str] = {}

    def _spaced_name(chunk: str, match: re.Match, name: str) -> str:
        # Keep substituted names from fusing into one restore-breaking token.
        # Cases: literal "Player" + \n[4], or adjacent \n[3]\n[4] where actor 3
        # is named Player and 4 falls back to Alex (one-pass re.sub does not
        # see the first replacement as the previous character).
        if match.start() > 0:
            prev = chunk[match.start() - 1]
            if prev.isascii() and prev.isalnum():
                return f" {name}"
            if re.search(r"\\[nNvV]\[\d+\]$", chunk[: match.start()]):
                return f" {name}"
        return name

    def _display(name_of: NameOf) -> Callable[[re.Match], str]:
        def display(m: re.Match) -> str:
            name = name_of(int(m.group(1)))
            return name if name else m.group(0)

        return display

    def _repl(m: re.Match, chunk: str, name_of: NameOf) -> str:
        name = name_of(int(m.group(1)))
        if not name:
            return m.group(0)
        # Prefer restoring the original \n[X] / \v[X] form used in this string.
        reverse_map[name] = m.group(0)
        return _spaced_name(chunk, m, name)

    def _body(chunk: str) -> str:
        chunk = ACTOR_CODE.sub(lambda m: _repl(m, chunk, actor_name), chunk)
        return VARIABLE_CODE.sub(lambda m: _repl(m, chunk, variable_name), chunk)

    tag_match = (
        None
        if speaker_tag is None
        else re.match(
            rf"^(?P<open>\s*\[)(?P<speaker>{speaker_tag})(?P<close>\]\s*[|:：]\s*)",
            text,
            re.IGNORECASE,
        )
    )
    if tag_match:
        speaker = ACTOR_CODE.sub(_display(actor_name), tag_match.group("speaker"))
        speaker = VARIABLE_CODE.sub(_display(variable_name), speaker)
        body = _body(text[tag_match.end() :])
        return (
            f"{tag_match.group('open')}{speaker}{tag_match.group('close')}{body}",
            reverse_map,
        )
    return _body(text), reverse_map


def restore(
    text: str, reverse_map: dict[str, str], missing: dict[str, int] | None = None
) -> str:
    """Restore substituted actor display names to their original control codes.

    Handles both spaced forms (``Player Alex``) and fused forms the model
    sometimes emits (``PlayerAlex``) by first splitting a name glued to a
    preceding Latin/digit run, then applying normal word-boundary restore.
    With *missing*, each name restores at most that many of its occurrences,
    the codes the text lacks, so a name the reply also writes as a word, or
    beside a code it kept, stays a word; its whole-word occurrences restore
    first, so a name inside another word is restored only for a code still
    missing.
    """
    if not isinstance(text, str) or not reverse_map:
        return text
    names = "|".join(re.escape(n) for n in sorted(reverse_map, key=len, reverse=True))
    left = None if missing is None else dict(missing)

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if left is not None:
            if left.get(name, 0) < 1:
                return name
            left[name] -= 1
        return reverse_map[name]

    # PlayerAlex -> Player\n[4] (when Alex is the fallback / second code)
    glued = re.compile(rf"(?<=[A-Za-z0-9])({names})(?![A-Za-z0-9])")
    bounded = re.compile(rf"(?<!\w)({names})(?!\w)")
    if left is not None:
        text = bounded.sub(_replace, text)
        return glued.sub(_replace, text)
    text = glued.sub(_replace, text)
    return bounded.sub(_replace, text)


def shown(
    text: str, actors: dict[int, str], variables: dict[int, int]
) -> tuple[str, dict[str, str]] | None:
    """An Assistant-led line with each name code whose actor *actors* names
    (by actor ID; *variables* maps a variable ID to its actor) shown as the
    name, with the names' codes, or None to send the line as it is: one
    with no such code, or one that would show one name for two spellings of
    codes, which a restore could not tell apart."""
    spellings: dict[str, set[str]] = {}

    def actor(identity: int) -> str | None:
        return actors.get(identity)

    def variable(identity: int) -> str | None:
        actor_id = variables.get(identity)
        return None if actor_id is None else actors.get(actor_id)

    for pattern, name_of in ((ACTOR_CODE, actor), (VARIABLE_CODE, variable)):
        for match in pattern.finditer(text):
            name = name_of(int(match.group(1)))
            if name:
                spellings.setdefault(name, set()).add(match.group(0))
    if not spellings or any(len(codes) > 1 for codes in spellings.values()):
        return None
    return substitute(text, actor, variable)
