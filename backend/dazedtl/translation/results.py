"""Accepted results are bound to source plus context, shared across all transports."""

from pathlib import Path

from .files import digest, read_json, project_path, write_project_json
from .project import WORK
from .requests import result_value


class Results:
    def __init__(self, source):
        self.source = Path(source)

    def relative(self, request):
        fingerprint = request["fingerprint"]
        if len(fingerprint) != 64 or any(letter not in "0123456789abcdef" for letter in fingerprint):
            raise ValueError("Invalid request identity.")
        return WORK + "/work/accepted/" + fingerprint + ".json"

    def get(self, request):
        path = project_path(self.source, self.relative(request), exists=False)
        if not path.exists():
            return None
        value = read_json(path)
        if value.get("request_sha256") != request["fingerprint"] or value.get("sources_sha256") != digest(request["sources"]):
            raise ValueError("An accepted result no longer matches its saved request.")
        result_value(request, value["translations"])
        fingerprint = digest(value["translations"])
        if value.get("result_sha256", fingerprint) != fingerprint:
            raise ValueError("An accepted result changed outside the result workflow. Restore its saved receipt before correcting it.")
        value["result_sha256"] = fingerprint
        return value

    def accept(self, request, translations, provenance):
        output = result_value(request, translations)
        old = self.get(request)
        if old:
            if old["translations"] != output:
                raise ValueError("A different accepted result already exists. Use a new reviewed request for corrections.")
            return old
        value = {"version": 1, "request_sha256": request["fingerprint"], "sources_sha256": digest(request["sources"]),
                 "translations": output, "result_sha256": digest(output), "provenance": provenance}
        write_project_json(self.source, self.relative(request), value)
        return value

    def correct(self, request, translations, replaces_sha256, provenance):
        previous = self.get(request)
        if previous is None or replaces_sha256 != previous["result_sha256"]:
            raise ValueError("The accepted translation changed. Review its current result hash before applying a correction.")
        output = result_value(request, translations)
        if output == previous["translations"]:
            return previous
        history = WORK + "/work/accepted-history/" + request["fingerprint"] + "/" + digest(previous) + ".json"
        path = project_path(self.source, history, exists=False)
        if path.exists() and read_json(path) != previous:
            raise ValueError("The previous result's recovery record is inconsistent. It was not overwritten.")
        if not path.exists():
            write_project_json(self.source, history, previous)
        value = {"version": 1, "request_sha256": request["fingerprint"], "sources_sha256": digest(request["sources"]),
                 "translations": output, "result_sha256": digest(output), "previous_result_sha256": replaces_sha256, "provenance": provenance}
        write_project_json(self.source, self.relative(request), value)
        return value

    def export(self, plan):
        units = []
        for request in plan["requests"]:
            value = self.get(request)
            for identity, source in request["sources"].items():
                row = {"id": digest([request["id"], identity]), "batch": request["id"], "source_id": identity, "source": source}
                if value:
                    row.update(translation=value["translations"][identity], translated_from_sha256=digest(source.encode("utf-8")),
                               request_sha256=request["fingerprint"])
                    if identity in value.get("reviewed", {}):
                        row["reviewed_sha256"] = value["reviewed"][identity]
                units.append(row)
        relative = WORK + "/work/translation-units.json"
        value = {"complete": plan["complete"], "units": units}
        path = project_path(self.source, relative, exists=False)
        previous = read_json(path) if path.exists() else None
        def content(document):
            return None if document is None else {**document, "units": [{key: item for key, item in row.items() if key != "reviewed_sha256"} for row in document["units"]]}
        changed = content(previous) != content(value)
        if previous != value:
            write_project_json(self.source, relative, value)
        return relative, changed
