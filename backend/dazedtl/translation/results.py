"""Accepted results are bound to source plus context, shared across all transports."""

import os
from pathlib import Path

from dazedtl.freshness import signature, signature_settled
from dazedtl.storage import write_json

from .files import digest, project_path, read_json, write_project_json
from .project import WORK
from .refusals import line_refusal
from .requests import result_value

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


def translated(request, translations):
    """The result's translations, refusing any line that holds a refusal note
    in place of game text, whoever wrote it."""
    output = result_value(request, translations)
    for identity, text in output.items():
        source = request["sources"][identity]
        if text != source and line_refusal(text, source):
            raise ValueError(
                f"{identity} holds a refusal note instead of its translation. "
                "Translate it, or decline the request so another model can finish it."
            )
    return output


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

    def get(self, request, path=None):
        """The request's accepted result, or None; path is its file when
        saved() or the caller has already checked it."""
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

    def accept(self, request, translations, provenance):
        output = translated(request, translations)
        path = project_path(self.source, self.relative(request), exists=False)
        old = self.get(request, path)
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
            "provenance": provenance,
        }
        write_json(path, value)
        return value

    def correct(self, request, translations, replaces_sha256, provenance):
        previous = self.get(request)
        if previous is None or replaces_sha256 != previous["result_sha256"]:
            raise ValueError(
                "The accepted translation changed. Review its current result hash before applying a correction."
            )
        output = translated(request, translations)
        if output == previous["translations"]:
            return previous
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
            "previous_result_sha256": replaces_sha256,
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
            for identity, base, source_sha256 in _rows(request):
                row = dict(base)
                if value:
                    row.update(
                        translation=value["translations"][identity],
                        translated_from_sha256=source_sha256,
                        request_sha256=request["fingerprint"],
                    )
                    if identity in value.get("reviewed", {}):
                        row["reviewed_sha256"] = value["reviewed"][identity]
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
                        os.unlink(entry.path)
                    except OSError:
                        # A reader holds it on Windows; the next export tries again.
                        continue
                    _PARTS.pop(entry.path, None)
        return EXPORT, changed
