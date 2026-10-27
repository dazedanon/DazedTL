"""Accepted results are bound to source plus context, shared across all transports."""

import os
import stat
from pathlib import Path

from dazedtl import system
from dazedtl.freshness import Digests, signature, signature_settled
from dazedtl.storage import write_json

from .files import digest, project_path, read_json, write_project_json
from .project import WORK
from .refusals import RULES_VERSION, line_refusal
from .requests import (
    protected_tokens,
    result_value,
    source_language,
    target_language,
)

ACCEPTED = WORK + "/work/accepted"
# The progress export: an index of parts, each the units of PART_REQUESTS
# requests, so saving one request's result rewrites one part instead of every
# line of the run.
EXPORT = WORK + "/work/translation-units.json"
EXPORT_PARTS = WORK + "/work/translation-units"
PART_REQUESTS = 32
# Each part this process wrote or checked, by path: the requests and result
# file signatures it was built from, and its own file's signature then.
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


def _signature(path):
    try:
        return signature(path.stat())
    except FileNotFoundError:
        return None


def _content(units):
    """Units without their review hashes: a review alone reopens nothing."""
    return [
        {key: item for key, item in row.items() if key != "reviewed_sha256"}
        for row in units
    ]


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
    to a mark or repeating without end, with why. A line given back as its
    source is left alone, as Guided keeps a line it could not translate in
    its original text."""
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
    with reading(language, target):
        _valid, invalid, reasons = validate_translation_content(
            [request["sources"][identity] for identity in identities],
            [translations[identity] for identity in identities],
            source_pattern(language=language),
            target,
            protected=[protected_tokens(request, identity) for identity in identities],
        )
    return {
        identities[index]: reason.split(": ", 1)[-1]
        for index, reason in zip(invalid, reasons, strict=True)
    }


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
    if not failures:
        return output, {}
    sources = request["sources"]
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


def review_digest(source, translation):
    """The hash a source-checked review records for a line's translation,
    which Len's progress (util/len_progress) checks against the export."""
    from util.len_progress import review_fingerprint

    return review_fingerprint(source.encode("utf-8"), translation.encode("utf-8"))


def exported(request, value):
    """A saved result's translations as the game gets them: each with the
    automatic lint fixes Guided gives a new translation
    (rpgmaker_qa_lint `normalize`). The receipt keeps what was accepted."""
    from util.rpgmaker_qa_lint import normalize

    target = target_language(request["context"])
    return {
        identity: normalize(request["sources"][identity], text, target)
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
        holds a refusal note (`holds_refusal`), which every caller then resends."""
        value = self._receipt(request, path)
        return None if value is None or holds_refusal(request, value) else value

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
        if old and holds_refusal(request, old):
            # The refusal note it holds was never a translation; it is
            # archived as a correction would archive it.
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

    def units(self, requests, listing):
        """The export rows of requests, each with its saved result."""
        units = []
        for request in requests:
            key = request["fingerprint"]
            value = None
            if key in listing:
                path = listing[key][0]
                value = self.get(request, path) if path else self.get(request)
            output = exported(request, value) if value else {}
            for identity, base, source_sha256 in _rows(request):
                row = dict(base)
                if value:
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
                            base["source"], accepted
                        ):
                            reviewed = review_digest(base["source"], output[identity])
                        row["reviewed_sha256"] = reviewed
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
        for start in range(0, len(requests), PART_REQUESTS):
            group = requests[start : start + PART_REQUESTS]
            name = f"part-{start // PART_REQUESTS + 1:04d}.json"
            relative = EXPORT_PARTS + "/" + name
            parts.append(relative)
            path = folder / name
            inputs = tuple(
                (row["fingerprint"], listing.get(row["fingerprint"], (None, None))[1])
                for row in group
            )
            if _PARTS.get(str(path)) == (inputs, _signature(path)):
                continue
            document = {"units": self.units(group, listing)}
            previous = read_json(path) if path.exists() else None
            if previous != document:
                changed = (
                    changed
                    or previous is None
                    or (_content(previous["units"]) != _content(document["units"]))
                )
                write_project_json(self.source, relative, document)
            stamp = _signature(path)
            # A file younger than one clock tick may change without a new stamp.
            if all(
                signature_settled(item)
                for item in (stamp, *(item for _, item in inputs))
            ):
                _PARTS[str(path)] = (inputs, stamp)
        index = {"complete": plan["complete"], "parts": parts}
        if legacy is not None:
            units = [
                row
                for part in parts
                for row in read_json(folder / part.rsplit("/", 1)[1])["units"]
            ]
            changed = legacy.get("complete") != index["complete"] or _content(
                legacy["units"]
            ) != _content(units)
        elif previous_index != index:
            changed = True
        if previous_index != index:
            write_project_json(self.source, EXPORT, index)
        names = {part.rsplit("/", 1)[1] for part in parts}
        with os.scandir(folder) as entries:
            for entry in entries:
                if (
                    entry.name.startswith("part-")
                    and entry.name not in names
                    and entry.is_file(follow_symlinks=False)
                ):
                    try:
                        system.unlink(entry.path)
                    except OSError:
                        # A reader holds it on Windows; the next export tries again.
                        continue
                    _PARTS.pop(entry.path, None)
        return EXPORT, changed
