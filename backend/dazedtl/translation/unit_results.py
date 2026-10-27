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

from .files import project_path, read_json
from .project import WORK
from .requests import result_value, source_language, target_language
from .results import Results, indexed, untranslated

INDEX = WORK + "/work/accepted-units.json"
# Raise when an entry would record something else of the same request.
VERSION = 1
# Organize under this policy leaves each unit with a current translation out
# of its requests (run_compiler); the operation's compile record freezes it,
# so an organize started before keeps every unit.
POLICY = "unit-results-v1"


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
    missing = receipts - set(found)
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
                found[request["fingerprint"]] = entry(request)
                missing.discard(request["fingerprint"])
        if not missing:
            break
    if found != saved:
        write_json(
            project_path(source, INDEX, exists=False),
            {"version": VERSION, "requests": found},
        )
    return found


def current(source, units, language, target, found, listing):
    """The request whose saved receipt answers each of units (organize's)
    with a current translation, by unit ID: of the receipts of found (entries)
    whose requests held the unit with the same source text in this language
    pair, the newest that gives it a translation, not its source text
    (results.untranslated), keeping the unit's protected tokens and layout
    bounds. Guided's newest compatible run wins the same way."""
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
    answered = {}
    for fingerprint in sorted(
        holding, key=lambda key: listing[key][1][3], reverse=True
    ):
        try:
            value = results.get(
                indexed(fingerprint, found[fingerprint]), listing[fingerprint][0]
            )
        except OSError, ValueError:
            value = None
        if not value:
            continue
        for identity in holding[fingerprint]:
            unit = wanted[identity]
            text = value["translations"][identity]
            if identity in answered or untranslated(
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
            answered[identity] = fingerprint
    return answered


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
