"""Accepted results are bound to source plus context, shared across all transports."""

import os
import re
import stat
from collections import Counter
from functools import partial
from pathlib import Path

from dazedtl import system
from dazedtl.freshness import Digests, signature, signature_settled
from dazedtl.storage import write_json

from .files import digest, encode, project_path, read_json, write_project_json
from .project import WORK
from .refusals import RULES_VERSION, line_refusal
from .requests import (
    protected_tokens,
    result_value,
    source_language,
    target_language,
)

ACCEPTED = WORK + "/work/accepted"
# The rules an export writes its lines by (exported_line): 1, recorded by
# none, Guided's automatic lint fixes; 2, also Guided's reply cleanup; 3,
# also its repair of small kana left in a line (util/target_text
# stranded_kana). An export written by older rules is written again, and
# only a line whose translation differs from its old one written by these
# rules is new.
EXPORT_VERSION = 3
# The progress export: an index of parts, each the units of PART_REQUESTS
# requests, then the units organize left out with an earlier translation, so
# saving one request's result rewrites one part instead of every line of the
# run.
EXPORT = WORK + "/work/translation-units.json"
EXPORT_PARTS = WORK + "/work/translation-units"
PART_REQUESTS = 32
# A part of units organize left out holds this many, about as many as a
# part of requests.
PART_UNITS = 1000
# What a listing gives for a result file it doesn't hold.
_NONE = (None, None)
# Each part this process wrote or checked, by path: the inputs it was built
# from, its requests or units with their result files' signatures, and its own
# file's signature then.
_PARTS = {}
# Each request's export rows before its result joins them, by fingerprint,
# which fixes everything they hold. A refresh after every accepted receipt
# rebuilds the rows of the whole run, and hashing their tens of thousands of
# IDs again took most of its time.
_ROWS = {}
ROWS_KEPT = 20_000
# Whether a receipt saved under other refusal rules than RULES_VERSION holds
# a refusal note, by its translations' and sources' hashes and the rules that
# read it, so each saved receipt is screened once per process.
_SCREENED = {}
SCREENED_KEPT = 50_000
# Whether each result file holds an accepted result (Results.accepted), by
# its path, reused while the file is unchanged.
_ACCEPTED_FILES = Digests()


def _rows(request):
    rows = _ROWS.get(request["fingerprint"])
    if rows is None:
        context = request["context"]
        rows = []
        for identity, source in request["sources"].items():
            row = {
                "id": digest([request["id"], identity]),
                "batch": request["id"],
                "source_id": identity,
                "source": source,
            }
            if "line_kinds" in context:
                row.update(
                    kind=context["line_kinds"][identity],
                    speaker=context["speakers"][identity],
                )
            if identity in context.get("qa_notes", {}):
                row["qa_note"] = context["qa_notes"][identity]
            rows.append((identity, row, digest(source.encode("utf-8"))))
        if len(_ROWS) >= ROWS_KEPT:
            _ROWS.clear()
        _ROWS[request["fingerprint"]] = rows
    return rows


def _answer(row, request, value, output, identity, source_sha256):
    """Gives an export row its line's saved translation, as the game gets it
    (output), and its review."""
    row.update(
        translation=output[identity],
        translated_from_sha256=source_sha256,
        request_sha256=request["fingerprint"],
    )
    reviewed = value.get("reviewed", {}).get(identity)
    if reviewed is not None:
        accepted = value["translations"][identity]
        # A review of the accepted text covers its lint fixes.
        if output[identity] != accepted and reviewed == review_digest(
            row["source"], accepted
        ):
            reviewed = review_digest(row["source"], output[identity])
        row["reviewed_sha256"] = reviewed


def _signature(path):
    try:
        return signature(path.stat())
    except FileNotFoundError:
        return None


def _content(units):
    """Units without their review hashes, which a review alone changes, so it
    reopens nothing, as canonical JSON text."""
    return [
        encode({key: item for key, item in row.items() if key != "reviewed_sha256"})
        for row in units
    ]


def _requests(plan):
    """The requests whose receipts a run's export reads, by fingerprint: its
    own and those answering the units its organize left out."""
    found = {request["fingerprint"]: request for request in plan["requests"]}
    reused = plan.get("reused") or {"requests": {}}
    for fingerprint, entry in reused.get("requests", {}).items():
        found.setdefault(fingerprint, indexed(fingerprint, entry))
    return found


def _rewritten(requests, quotes, units):
    """_content of export rows written by older rules (EXPORT_VERSION), each
    translation written again by these rules (exported_line), so a row
    changes only when its saved translation did."""
    rows = []
    for row in units:
        request = requests.get(row.get("request_sha256"))
        if "translation" in row and request and row["source_id"] in request["sources"]:
            row = {
                **row,
                "translation": exported_line(
                    request, row["source_id"], row["translation"], quotes
                ),
            }
        rows.append(row)
    return _content(rows)


def _refusal(request, translations):
    """The first line of translations that holds a refusal note in place of
    game text, or None."""
    for identity, text in translations.items():
        source = request["sources"][identity]
        if text != source and line_refusal(text, source):
            return identity
    return None


def _content_failures(request, translations):
    """Each line of translations that fails Guided's content check
    (util/translation `validate_translation_content`), such as one collapsed
    to a mark or repeating without end, or its control-code check
    (util/runtime_text `validate_unmasked_control_codes`), such as one that
    drops a colour code or breaks its scope, whether or not its constraints
    name the code, with why. A line given back as its source is left alone,
    as Guided keeps a line it could not translate in its original text. The
    content check reads each line with the kana Guided's reply cleanup
    writes otherwise (util/target_text `kana_written`), as Guided checks a
    reply once it is cleaned, so a small kana that cleanup repairs or leaves
    out fails no line."""
    from util.runtime_text import validate_unmasked_control_codes
    from util.target_text import kana_written
    from util.translation import validate_translation_content

    from dazedtl.languages import reading, source_pattern

    identities = [
        identity
        for identity, text in translations.items()
        if text != request["sources"][identity]
    ]
    if not identities:
        return {}
    context = request["context"]
    language, target = source_language(context), target_language(context)
    pattern = source_pattern(language=language)
    with reading(language, target):
        _valid, invalid, reasons = validate_translation_content(
            [request["sources"][identity] for identity in identities],
            [
                kana_written(
                    translations[identity],
                    target,
                    protected_tokens(request, identity),
                )
                for identity in identities
            ],
            pattern,
            target,
            protected=[protected_tokens(request, identity) for identity in identities],
        )
    content = {
        identities[index]: reason.split(": ", 1)[-1]
        for index, reason in zip(invalid, reasons, strict=True)
    }
    source_text = re.compile(pattern)
    failures = {}
    for identity in identities:
        if identity in content:
            failures[identity] = content[identity]
            continue
        valid, errors = validate_unmasked_control_codes(
            request["sources"][identity], translations[identity], source_text
        )
        if not valid:
            failures[identity] = (
                f"its control codes differ from the source's ({errors[0].split(': ', 1)[-1]})"
            )
    return failures


def _checked(request, translations, keep):
    """The result's translations and the lines kept in their source text,
    refusing any line that holds a refusal note in place of game text,
    whoever wrote it. A line that fails the content check refuses the
    result, unless keep: then, while another line of it passes, the line
    keeps its source text, as Guided keeps such a line of a response."""
    output = result_value(request, translations)
    identity = _refusal(request, output)
    if identity is not None:
        raise ValueError(
            f"{identity} holds a refusal note instead of its translation. "
            "Translate it, or decline the request so another model can finish it."
        )
    failures = _content_failures(request, output)
    sources = request["sources"]
    if not failures:
        if translates_nothing(request, {"translations": output}):
            raise ValueError(
                f"{next(iter(sources))} is no translation: every line is its source text. "
                "Translate it, or decline the request so another model can finish it."
            )
        return output, {}
    if keep and any(
        text != sources[identity] and identity not in failures
        for identity, text in output.items()
    ):
        return {**output, **{identity: sources[identity] for identity in failures}}, (
            failures
        )
    identity, reason = next(iter(failures.items()))
    raise ValueError(
        f"{identity} is no usable translation: {reason}. "
        "Translate it again, or decline the request so another model can finish it."
    )


def translated(request, translations):
    """The result's translations, refusing any line that holds a refusal note
    in place of game text, whoever wrote it, or that fails the content
    check, so the assistant who wrote it translates it again."""
    return _checked(request, translations, keep=False)[0]


def kept(request, translations):
    """A paid result's translations, as translated() gives them but with each
    line that fails the content check kept in its source text while another
    line passes, and those lines with why, so the lines that passed are never
    paid for again. Guided keeps such a line the same way: its Batch at once,
    its Live run once its validation retries are spent. An API run's
    approval covers one call per request, so none is retried here."""
    return _checked(request, translations, keep=True)


def untranslated(source, text, language, target):
    """Whether a saved line is no translation: given back as its source text
    while it still holds source text, as a line a run kept in its source
    after it failed the content check (kept) is, or one the model gave back
    unchanged. Guided reads such a line the same way, so its next run sends
    it again (compatibility/run_evidence `kept`); this reads it for the
    language pair, as Guided's line counts read a line (util/source_text
    `source_left`), so a Chinese translation writing a name in the same
    kanji as its source is one."""
    if text != source:
        return False
    from util.source_text import source_left

    return bool(source_left(text, source, language, target))


def left_lines(request, value):
    """The unit IDs of a saved receipt's lines that are no translation."""
    context = request["context"]
    language, target = source_language(context), target_language(context)
    return {
        identity
        for identity, text in value["translations"].items()
        if untranslated(request["sources"][identity], text, language, target)
    }


def translates_nothing(request, value):
    """Whether no line of a saved receipt is a translation, so the request
    has none to reuse and is sent again, as one holding a refusal note is."""
    sources = request["sources"]
    # Most receipts change their first line, which settles it.
    if any(
        text != sources[identity] for identity, text in value["translations"].items()
    ):
        return False
    return len(left_lines(request, value)) == len(sources)


def indexed(fingerprint, entry):
    """The request an index entry (translation/unit_results) describes, as
    far as reading its receipt needs: its fingerprint, lines and language
    pair."""
    return {
        "id": entry["id"],
        "fingerprint": fingerprint,
        "sources": entry["sources"],
        "constraints": {},
        "context": {
            "source_language": entry["language"],
            "target_language": entry["target"],
        },
    }


def review_digest(source, translation):
    """The hash a source-checked review records for a line's translation,
    which Len's progress (util/len_progress) checks against the export."""
    from util.len_progress import review_fingerprint

    return review_fingerprint(source.encode("utf-8"), translation.encode("utf-8"))


# Whether a run writes corner brackets as quotes, the convertQuotes setting
# it froze as a Guided run freezes it in its engine settings; a run compiled
# before it froze one writes them, as the setting does by default.
QUOTES = "convertQuotes"


def run_quotes(plan):
    """Whether the run *plan* writes corner brackets as quotes (QUOTES)."""
    return plan.get(QUOTES, True)


def exported_line(request, identity, text, quotes=True):
    """A line's saved translation as the game gets it: as Guided writes every
    line of a reply (util/target_text `translated_line`), corner brackets as
    quotes when *quotes*, the line's protected tokens kept as they are, then
    with the automatic lint fixes Guided gives a new translation
    (rpgmaker_qa_lint `normalize`). A line given back as its source stays
    as it is, as Guided keeps such a line."""
    from util.rpgmaker_qa_lint import normalize
    from util.target_text import translated_line

    source = request["sources"][identity]
    if text == source:
        return text
    target = target_language(request["context"])
    line = translated_line(text, target, quotes, protected_tokens(request, identity))
    return normalize(source, line, target)


def exported(request, value, quotes=True):
    """A saved result's translations as the game gets them (exported_line).
    The receipt keeps what was accepted."""
    return {
        identity: exported_line(request, identity, text, quotes)
        for identity, text in value["translations"].items()
    }


def holds_refusal(request, value):
    """Whether a saved receipt holds a refusal note under the current rules.
    accept() screened it under the rules it records, so only a receipt from
    other or unrecorded rules is read again: what counts as a refusal note
    has grown since, and one accepted before then is no translation."""
    if value.get("refusal_rules") == RULES_VERSION:
        return False
    key = (value["result_sha256"], value["sources_sha256"], RULES_VERSION)
    verdict = _SCREENED.get(key)
    if verdict is None:
        verdict = _refusal(request, value["translations"]) is not None
        if len(_SCREENED) >= SCREENED_KEPT:
            _SCREENED.clear()
        _SCREENED[key] = verdict
    return verdict


def exported_translations(source):
    """The rows of the game's progress export (EXPORT) that hold a
    translation, as the game gets it; none before the first export."""
    index_path = project_path(source, EXPORT, exists=False)
    if not index_path.is_file():
        return []
    index = read_json(index_path)
    # An export from before parts held every unit itself.
    rows = index.get("units")
    if not isinstance(rows, list):
        rows = [
            row
            for part in index["parts"]
            for row in read_json(project_path(source, part))["units"]
        ]
    return [row for row in rows if "translation" in row]


class Results:
    def __init__(self, source):
        self.source = Path(source)

    def relative(self, request):
        fingerprint = request["fingerprint"]
        if len(fingerprint) != 64 or any(
            letter not in "0123456789abcdef" for letter in fingerprint
        ):
            raise ValueError("Invalid request identity.")
        return ACCEPTED + "/" + fingerprint + ".json"

    def listing(self):
        """The accepted result files by fingerprint, each with its stat
        signature, from one listing of their checked folder instead of
        project_path per request, whose path resolution costs most on Windows.
        A name that is not a regular file maps to (None, None), which get()
        checks as usual. Names are casefolded, as Windows looks them up."""
        folder = project_path(self.source, ACCEPTED, exists=False)
        result = {}
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = entry.name.casefold().removesuffix(".json")
                    if entry.is_file(follow_symlinks=False):
                        result[name] = (
                            Path(entry.path),
                            signature(entry.stat(follow_symlinks=False)),
                        )
                    else:
                        result[name] = (None, None)
        except FileNotFoundError, NotADirectoryError:
            return {}
        return result

    def saved(self):
        """The accepted result files by fingerprint, for get()."""
        return {name: path for name, (path, _signature) in self.listing().items()}

    def _receipt(self, request, path=None):
        """The request's saved receipt, or None, whether or not it holds a
        refusal note; path is its file when saved() or the caller has
        already checked it."""
        path = path or project_path(self.source, self.relative(request), exists=False)
        if not path.exists():
            return None
        value = read_json(path)
        if value.get("request_sha256") != request["fingerprint"] or value.get(
            "sources_sha256"
        ) != digest(request["sources"]):
            raise ValueError("An accepted result no longer matches its saved request.")
        result_value(request, value["translations"])
        fingerprint = digest(value["translations"])
        if value.get("result_sha256", fingerprint) != fingerprint:
            raise ValueError(
                "An accepted result changed outside the result workflow. Restore its saved receipt before correcting it."
            )
        value["result_sha256"] = fingerprint
        return value

    def get(self, request, path=None):
        """The request's accepted result, or None, as for a receipt that
        holds a refusal note (`holds_refusal`) or translates no line
        (`translates_nothing`), which every caller then resends."""
        value = self._receipt(request, path)
        if value is None or holds_refusal(request, value):
            return None
        return None if translates_nothing(request, value) else value

    def accepted(self, fingerprint, request):
        """Whether the request with this fingerprint has an accepted result
        (get), for a reader that holds only the fingerprint, such as a state
        poll. request() gives the request; it is called only for a saved
        result file whose verdict this process does not know yet, and the
        verdict is reused while the file is unchanged. A result or request
        that cannot be read is no result, read again next time."""
        path = self.source / self.relative({"fingerprint": fingerprint})
        try:
            info = path.lstat()
        except FileNotFoundError, NotADirectoryError:
            return False
        if not stat.S_ISREG(info.st_mode):
            return False

        def read():
            try:
                return self.get(request(), path) is not None
            except OSError, ValueError, KeyError:
                # None is never kept, so it is read again.
                return None

        return bool(_ACCEPTED_FILES.remember(os.fspath(path), info, read))

    def accept(self, request, translations, provenance):
        output = translated(request, translations)
        path = project_path(self.source, self.relative(request), exists=False)
        old = self._receipt(request, path)
        if old and (holds_refusal(request, old) or translates_nothing(request, old)):
            # The refusal note or the source text it holds was never a
            # translation; it is archived as a correction would archive it.
            return self._replace(request, old, output, provenance)
        if old:
            if old["translations"] != output:
                raise ValueError(
                    "A different accepted result already exists. Use a new reviewed request for corrections."
                )
            return old
        value = {
            "version": 1,
            "request_sha256": request["fingerprint"],
            "sources_sha256": digest(request["sources"]),
            "translations": output,
            "result_sha256": digest(output),
            "refusal_rules": RULES_VERSION,
            "provenance": provenance,
        }
        write_json(path, value)
        return value

    def correct(self, request, translations, replaces_sha256, provenance):
        previous = self._receipt(request)
        if previous is None or replaces_sha256 != previous["result_sha256"]:
            raise ValueError(
                "The accepted translation changed. Review its current result hash before applying a correction."
            )
        output = translated(request, translations)
        if output == previous["translations"]:
            return previous
        return self._replace(request, previous, output, provenance)

    def _replace(self, request, previous, output, provenance):
        """Saves output in place of the previous receipt, which it archives."""
        history = (
            WORK
            + "/work/accepted-history/"
            + request["fingerprint"]
            + "/"
            + digest(previous)
            + ".json"
        )
        path = project_path(self.source, history, exists=False)
        if path.exists() and read_json(path) != previous:
            raise ValueError(
                "The previous result's recovery record is inconsistent. It was not overwritten."
            )
        if not path.exists():
            write_project_json(self.source, history, previous)
        value = {
            "version": 1,
            "request_sha256": request["fingerprint"],
            "sources_sha256": digest(request["sources"]),
            "translations": output,
            "result_sha256": digest(output),
            "previous_result_sha256": previous["result_sha256"],
            "refusal_rules": RULES_VERSION,
            "provenance": provenance,
        }
        write_project_json(self.source, self.relative(request), value)
        return value

    def _saved(self, request, listing, quotes):
        """The request's accepted result, read where listing found its file,
        with its lines as the game gets them, corner brackets as quotes when
        *quotes*, and those that are no translation (`untranslated`)."""
        key = request["fingerprint"]
        value = None
        if key in listing:
            path = listing[key][0]
            value = self.get(request, path) if path else self.get(request)
        if not value:
            return None, {}, set()
        return value, exported(request, value, quotes), left_lines(request, value)

    def units(self, requests, listing, quotes=True):
        """The export rows of requests, each with its saved result; a line
        saved as no translation reads left."""
        units = []
        for request in requests:
            value, output, left = self._saved(request, listing, quotes)
            for identity, base, source_sha256 in _rows(request):
                row = dict(base)
                if value and identity not in left:
                    _answer(row, request, value, output, identity, source_sha256)
                units.append(row)
        return units

    def reused_units(self, reused, identities, listing, quotes=True):
        """The export rows of a run's units its organize left out, which
        earlier requests' receipts answer (translation/unit_results), by
        unit ID; a unit whose receipt is gone reads left."""
        units, read = [], {}
        for identity in identities:
            unit = reused["units"][identity]
            key = unit["request"]
            if key not in read:
                request = indexed(key, reused["requests"][key])
                read[key] = (request, *self._saved(request, listing, quotes))
            request, value, output, left = read[key]
            source = request["sources"][identity]
            row = {
                "id": digest([request["id"], identity]),
                "batch": request["id"],
                "source_id": identity,
                "source": source,
                "kind": unit["kind"],
                "speaker": unit["speaker"],
            }
            if value and identity not in left:
                _answer(
                    row,
                    request,
                    value,
                    output,
                    identity,
                    digest(source.encode("utf-8")),
                )
            units.append(row)
        return units

    def export(self, plan):
        """Writes the plan's progress export and replies with its path and
        whether any translation in it changed. Only parts whose requests or
        saved results changed since this process last wrote them are built."""
        listing = self.listing()
        folder = project_path(self.source, EXPORT_PARTS, exists=False)
        folder.mkdir(parents=True, exist_ok=True)
        requests = plan["requests"]
        parts, changed = [], False
        index_path = project_path(self.source, EXPORT, exists=False)
        previous_index = read_json(index_path) if index_path.exists() else None
        # An export from before parts held every unit itself; it alone shows
        # what changed while the parts are first written.
        legacy = (
            previous_index
            if isinstance(previous_index, dict)
            and isinstance(previous_index.get("units"), list)
            else None
        )
        quotes = run_quotes(plan)
        # Rows written by older rules, read as these rules write them, so a
        # run already written into the game reads no new translation.
        older = (
            legacy is None
            and isinstance(previous_index, dict)
            and previous_index.get("version", 1) != EXPORT_VERSION
        )
        counted = partial(_rewritten, _requests(plan), quotes) if older else _content
        # Each part's inputs, which fix its rows, ending with the signature of
        # a result file they read, and how its rows are built.
        groups = [
            (
                tuple(
                    (row["fingerprint"], listing.get(row["fingerprint"], _NONE)[1])
                    for row in group
                ),
                partial(self.units, group, listing, quotes),
            )
            for group in (
                requests[start : start + PART_REQUESTS]
                for start in range(0, len(requests), PART_REQUESTS)
            )
        ]
        # The units organize left out follow, by the receipts that answer them.
        reused = plan.get("reused") or {"units": {}}
        identities = list(reused["units"])
        for start in range(0, len(identities), PART_UNITS):
            group = identities[start : start + PART_UNITS]
            inputs = tuple(
                (
                    identity,
                    *(
                        reused["units"][identity][key]
                        for key in ("request", "kind", "speaker")
                    ),
                    listing.get(reused["units"][identity]["request"], _NONE)[1],
                )
                for identity in group
            )
            groups.append(
                (inputs, partial(self.reused_units, reused, group, listing, quotes))
            )
        # The rows of each part written or removed, before and after: a run
        # holding the same rows in other parts, as one organize left every
        # line out of does, changes no translation.
        before, after = Counter(), Counter()
        for number, (inputs, build) in enumerate(groups, 1):
            name = f"part-{number:04d}.json"
            relative = EXPORT_PARTS + "/" + name
            parts.append(relative)
            path = folder / name
            if _PARTS.get(str(path)) == ((quotes, inputs), _signature(path)):
                continue
            document = {"units": build()}
            previous = read_json(path) if path.exists() else None
            if previous != document:
                if previous is not None:
                    before.update(counted(previous["units"]))
                after.update(_content(document["units"]))
                write_project_json(self.source, relative, document)
            stamp = _signature(path)
            # A file younger than one clock tick may change without a new stamp.
            if all(
                signature_settled(item)
                for item in (stamp, *(item[-1] for item in inputs))
            ):
                _PARTS[str(path)] = ((quotes, inputs), stamp)
        index = {
            "complete": plan["complete"],
            "parts": parts,
            "version": EXPORT_VERSION,
        }
        names = {part.rsplit("/", 1)[1] for part in parts}
        with os.scandir(folder) as entries:
            gone = [
                entry.path
                for entry in entries
                if entry.name.startswith("part-")
                and entry.name not in names
                and entry.is_file(follow_symlinks=False)
            ]
        for path in gone:
            try:
                before.update(counted(read_json(path)["units"]))
            except OSError, ValueError, KeyError, TypeError:
                changed = True
        if legacy is not None:
            units = [
                row
                for part in parts
                for row in read_json(folder / part.rsplit("/", 1)[1])["units"]
            ]
            changed = legacy.get("complete") != index["complete"] or _content(
                legacy["units"]
            ) != _content(units)
        else:
            changed = (
                changed
                or before != after
                or (previous_index or {}).get("complete") != index["complete"]
            )
        if previous_index != index:
            write_project_json(self.source, EXPORT, index)
        for path in gone:
            try:
                system.unlink(path)
            except OSError:
                # A reader holds it on Windows; the next export tries again.
                continue
            _PARTS.pop(path, None)
        return EXPORT, changed
