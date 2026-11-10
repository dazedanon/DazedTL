"""Accepted translations by unit, which organize keeps: a line keeps its
translation while its unit ID and source text stay the same, whichever
request answered it, so an organize after a guidance change, an extractor
fix, a game update or a packing shift quotes only the lines without one, as
Guided reuses a saved line by its file and source text however its prompt
changed (architecture, Result reuse).

Results keeps each request's receipt under the request's fingerprint, which
digests its whole context, the glossary and guidance included, and a receipt
names its lines by unit ID only. The index here keeps beside the receipts,
for each one, the request it answers: its ID, each line's source by unit ID
and its language pair, read once from a run plan that holds the request.
A fingerprint fixes all of that, so an entry never goes out of date; one
whose receipt is gone, as after Start over, is dropped.
"""

from dazedtl.storage import write_json

from . import organize
from .files import digest, project_path, read_json
from .jobs import now
from .project import WORK
from .requests import result_value, source_language, target_language
from .results import Results, indexed, line_problems, unsent_line, untranslated

INDEX = WORK + "/work/accepted-units.json"
# The requests of lines imported from translation files, by fingerprint, as
# run plans hold their runs' requests (save_import).
IMPORTS = WORK + "/work/imported"
# Raise when an entry would record something else of the same request.
VERSION = 1
# Organize under this policy leaves each unit with a current translation out
# of its requests (run_compiler); the operation's compile record freezes it,
# so an organize started before keeps every unit.
POLICY = "unit-results-v1"
# An organize given the option to send cold lines again, which its compile
# record freezes under this name, packs again each line whose current
# translation came from a request that started without the lines before it
# (cold), so it is translated with them; an organize frozen without it
# keeps every current translation.
COLD = "cold-lines-v1"
# The provenance of a receipt of lines imported from a translation file
# (save_import), which holds its own index entry, since no run plan holds
# its request.
IMPORTED = "translation-file"


def entry(request):
    """The index entry of a compiled request."""
    context = request["context"]
    return {
        "id": request["id"],
        "sources": request["sources"],
        "language": source_language(context),
        "target": target_language(context),
    }


def _saved(source):
    try:
        value = read_json(project_path(source, INDEX, exists=False))
    except OSError, ValueError:
        return {}
    if (
        not isinstance(value, dict)
        or value.get("version") != VERSION
        or not isinstance(value.get("requests"), dict)
    ):
        return {}
    # An entry that can't be read is looked up again.
    return {
        key: item
        for key, item in value["requests"].items()
        if isinstance(item, dict)
        and set(item) == {"id", "sources", "language", "target"}
        and isinstance(item["sources"], dict)
        and all(isinstance(text, str) for text in item["sources"].values())
    }


def entries(store, project_id, source, listing):
    """The index entry of each saved receipt in listing (Results.listing), by
    fingerprint. A receipt not indexed yet is looked up in the project's run
    plans, which are read only for the receipts they hold."""
    saved = _saved(source)
    receipts = {key for key, (path, _stamp) in listing.items() if path}
    found = {key: value for key, value in saved.items() if key in receipts}
    for fingerprint, request in held(
        store, project_id, receipts - set(found), source
    ).items():
        found[fingerprint] = entry(request)
    if found != saved:
        write_json(
            project_path(source, INDEX, exists=False),
            {"version": VERSION, "requests": found},
        )
    return found


def held(store, project_id, fingerprints, source=None):
    """The compiled requests of fingerprints, by fingerprint: each read from
    a run plan of the project that holds it or, in the game at *source*, as
    a request of lines imported from a translation file (save_import).
    Plans are read only for the requests they hold, and one that can't be
    read is passed over."""
    missing, found = set(fingerprints), {}
    for job in store.list(project_id) if missing else ():
        if job["kind"] != "translation" or missing.isdisjoint(
            job["fingerprints"].values()
        ):
            continue
        try:
            _job, plan = store.load(job["id"], project_id)
        except OSError, ValueError:
            continue
        for request in plan["requests"]:
            if request["fingerprint"] in missing:
                found[request["fingerprint"]] = request
                missing.discard(request["fingerprint"])
        if not missing:
            break
    if missing and source is not None:
        for fingerprint in sorted(missing):
            request = _imported(source, fingerprint)
            if request is not None:
                found[fingerprint] = request
    return found


def current(source, units, language, target, found, listing):
    """The request whose saved receipt answers each of units (organize's)
    with a current translation, by unit ID: of the receipts of found (entries)
    whose requests held the unit with the same source text in this language
    pair, the one that gave it its translation last, not its source text
    (results.untranslated), keeping the unit's protected tokens and layout
    bounds. Guided's newest compatible run wins the same way. A receipt gave
    its lines their translation when it was saved, but a correction only
    the lines it changed (Results.corrected): the others keep the time they
    were accepted, so a correction never brings back lines a newer request
    translated again."""
    wanted = {unit["id"]: unit for unit in units}
    holding = {}
    for fingerprint, value in found.items():
        if (value["language"], value["target"]) != (language, target):
            continue
        identities = [
            identity
            for identity, text in value["sources"].items()
            if identity in wanted and wanted[identity]["source"] == text
        ]
        if identities:
            holding[fingerprint] = identities
    results = Results(source)
    answered, newest = {}, {}
    for fingerprint in sorted(
        holding, key=lambda key: listing[key][1][3], reverse=True
    ):
        request = indexed(fingerprint, found[fingerprint])
        try:
            value = results.get(request, listing[fingerprint][0])
        except OSError, ValueError:
            value = None
        if not value:
            continue
        saved = listing[fingerprint][1][3]
        changed = results.corrected(request, value) if "accepted_ns" in value else None
        for identity in holding[fingerprint]:
            given = (
                saved
                if changed is None or identity in changed
                else value["accepted_ns"]
            )
            unit = wanted[identity]
            text = value["translations"][identity]
            if (identity in answered and given <= newest[identity]) or untranslated(
                unit["source"], text, language, target
            ):
                continue
            try:
                result_value(
                    {
                        "sources": {identity: unit["source"]},
                        "constraints": {identity: unit["constraints"]},
                    },
                    {identity: text},
                )
            except ValueError:
                continue
            answered[identity], newest[identity] = fingerprint, given
    return answered


def cold(store, project_id, source, units, answered, language, target, quotes):
    """The unit IDs of answered (current) whose translation came from a
    request that started cold: one a run compiled without source context
    although its first line in play order follows lines of its group
    (organize._before under organize.LEAD_IN), as every request but a split
    scene's later parts of an organize frozen before that policy did. Lines
    before count as organize's layout quotes them, without those DazedTL
    writes itself (organize.unsent), so each line sent again gets context.
    A line a correction changed keeps its translation (Results.corrected),
    as does one imported from a translation file, one without source
    letters, or one answered by a request no run plan holds any more."""
    unsent = organize.unsent(units, language, target, quotes)
    quoted = [unit for unit in units if unit["id"] not in unsent]
    position = {unit["id"]: index for index, unit in enumerate(quoted)}
    results = Results(source)
    found = set()
    for fingerprint, request in held(store, project_id, set(answered.values())).items():
        if request["context"].get("preceding_japanese_source_context"):
            continue
        first = min(
            (
                position[identity]
                for identity in request["sources"]
                if identity in position
            ),
            default=None,
        )
        if first is None or not organize._before(quoted, first, True):
            continue
        corrected = results.corrected(request)
        found.update(
            identity
            for identity in request["sources"]
            if answered.get(identity) == fingerprint
            and identity in position
            and identity not in corrected
        )
    return found


def record(units, answered, found):
    """A run's record of the units organize left out: each one's kind,
    speaker and the request whose receipt answers it, by unit ID in play
    order, and those requests' index entries, which the run's export and
    results read the translations by (Results.reused_units)."""
    return {
        "units": {
            unit["id"]: {
                "request": answered[unit["id"]],
                "kind": unit["kind"],
                "speaker": unit["speaker"],
            }
            for unit in units
            if unit["id"] in answered
        },
        "requests": {
            fingerprint: found[fingerprint]
            for fingerprint in dict.fromkeys(answered.values())
        },
    }


def _imported(source, fingerprint):
    """The request of lines imported from a translation file with
    *fingerprint*, in the game at *source*, or None for another request or
    one that can't be read."""
    if not all(char in "0123456789abcdef" for char in fingerprint):
        return None
    try:
        value = read_json(
            project_path(source, f"{IMPORTS}/{fingerprint}.json", exists=False)
        )
    except OSError, ValueError:
        return None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("id"), str)
        or not isinstance(value.get("sources"), dict)
        or not isinstance(value.get("constraints"), dict)
        or not isinstance(value.get("context"), dict)
    ):
        return None
    return value if value.get("fingerprint") == fingerprint else None


def translations(store, project_id, source, units, language, target, quotes=True):
    """Each of *units*' current translation as the game gets it, by unit ID:
    its newest saved receipt's (current), else, for a line without source
    letters, what DazedTL writes for it (organize.unsent). A unit with
    neither is left out."""
    results = Results(source)
    listing = results.listing()
    found = entries(store, project_id, source, listing)
    answered = current(source, units, language, target, found, listing)
    value = {}
    if answered:
        reused = record(units, answered, found)
        for row in results.reused_units(reused, list(reused["units"]), listing, quotes):
            if "translation" in row:
                value[row["source_id"]] = row["translation"]
    left = [unit for unit in units if unit["id"] not in value]
    for identity, unit in organize.unsent(left, language, target, quotes).items():
        value[identity] = unsent_line(unit["source"], target, quotes)
    return value


# What a spreadsheet program writes in place of a cell it read as a broken
# formula, such as a translation starting with "-" or "=" saved from Excel.
SPREADSHEET_ERRORS = frozenset(
    {
        "#BLOCKED!",
        "#BUSY!",
        "#CALC!",
        "#CONNECT!",
        "#DIV/0!",
        "#ERROR!",
        "#FIELD!",
        "#GETTING_DATA",
        "#N/A",
        "#NAME?",
        "#NULL!",
        "#NUM!",
        "#REF!",
        "#SPILL!",
        "#UNKNOWN!",
        "#VALUE!",
    }
)


def import_problems(units, translations, language, target):
    """Why each of *translations*, by unit ID, would not be kept as its
    unit's translation: the checks a saved translation passes
    (results.line_problems), that it is its source text, which reads as no
    translation (results.untranslated), or a spreadsheet's error value."""
    request = _request(units, translations, language, target)
    problems = line_problems(request, translations)
    for identity, text in translations.items():
        if identity in problems:
            continue
        if text.strip().upper() in SPREADSHEET_ERRORS:
            problems[identity] = (
                "It is a spreadsheet's error value, not a translation; "
                "a cell starting with - or = can read as a formula."
            )
        elif untranslated(units[identity]["source"], text, language, target):
            problems[identity] = "It is the line's source text, not a translation."
    return problems


def _request(units, translations, language, target, imported=""):
    """The request a receipt of *translations* answers: their units' source
    text and constraints, in the language pair. Each import is a request of
    its own, named by when it was *imported*, so the newest one's receipt
    wins (current) even when an earlier import gave the same lines."""
    sources = {identity: units[identity]["source"] for identity in translations}
    fingerprint = digest(
        {
            "kind": IMPORTED,
            "sources": sources,
            "translations": translations,
            "language": language,
            "target": target,
            "imported": imported,
        }
    )
    return {
        "id": "imported-" + fingerprint[:12],
        "fingerprint": fingerprint,
        "sources": sources,
        "constraints": {
            identity: units[identity]["constraints"] for identity in translations
        },
        "context": {"source_language": language, "target_language": target},
    }


def save_import(source, units, translations, language, target, file):
    """Saves *translations*, by unit ID, imported from the translation file
    named *file*, as the receipt of a request holding just those lines, so
    each unit keeps its imported translation as it would a run's: the newest
    receipt wins (current). Its index entry is saved beside the others and
    inside the receipt, since no run plan holds the request. Every line
    passed import_problems."""
    request = _request(units, translations, language, target, now())
    value = entry(request)
    # Saved first, so a receipt never answers a request nothing holds.
    write_json(
        project_path(source, f"{IMPORTS}/{request['fingerprint']}.json", exists=False),
        request,
    )
    Results(source).accept(
        request,
        translations,
        {"kind": IMPORTED, "file": file},
    )
    saved = _saved(source)
    saved[request["fingerprint"]] = value
    write_json(
        project_path(source, INDEX, exists=False),
        {"version": VERSION, "requests": saved},
    )
