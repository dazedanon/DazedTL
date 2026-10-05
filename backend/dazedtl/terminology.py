"""Project-owned terminology review. Source text is evidence, never a rewrite target."""

import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.file_preview import text_fields
from dazedtl.translation.files import decode_json, digest, project_path, read_json

WORK = ".dazedtl/terminology"
PAGE_SIZE = 40
MAX_MATCHES = 20_000
MAX_BYTES = 128_000_000


def bounded(value, label, limit):
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise ValueError(f"{label} must be text of at most {limit:,} characters.")
    return value


def terms_from(text):
    bounded(text, "Custom terms", 40_000)
    terms = list(
        dict.fromkeys(line.strip() for line in text.splitlines() if line.strip())
    )
    if len(terms) > 128 or any(len(term) > 256 for term in terms):
        raise ValueError("Use at most 128 exact terms, each at most 256 characters.")
    return terms


def review_value(value):
    if not isinstance(value, dict) or set(value) != {"revision", "character", "note"}:
        raise ValueError("Choose a saved terminology review before editing context.")
    return {
        "revision": bounded(value["revision"], "Review revision", 64),
        "character": bounded(value["character"], "Character / referent", 256),
        "note": bounded(value["note"], "Context note", 4000),
    }


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Choose a saved terminology occurrence or scan.")
    return value


def context_group(location):
    # Neighboring fields remain within one event page or database record.
    # They are shown as evidence; adjacency never assigns a speaker.
    return (
        location.split("/list/", 1)[0]
        if "/list/" in location
        else location.rsplit("/", 1)[0]
    )


def occurrences(project_id, name, document, terms):
    fields = list(text_fields(document))
    for index, field in enumerate(fields):
        source = field["text"]
        matches = []
        for term in terms:
            start = source.find(term)
            while start >= 0:
                matches.append((start, term))
                start = source.find(term, start + 1)
        if not matches:
            continue
        if len(source) > 64_000:
            raise ValueError(
                f"A matching field in {name} is longer than 64,000 characters. Narrow the terms before scanning."
            )
        group = context_group(field["location"])
        nearby = lambda rows: [
            {"text": row["text"][:4000], "shortened": len(row["text"]) > 4000}
            for row in rows
            if context_group(row["location"]) == group
        ]
        before, after = (
            nearby(fields[max(0, index - 2) : index]),
            nearby(fields[index + 1 : index + 3]),
        )
        source_hash = digest(source.encode("utf-8"))
        for start, term in sorted(matches):
            occurrence_id = digest(
                [project_id, name, field["location"], source_hash, start, term]
            )
            yield {
                "id": occurrence_id,
                "file": name,
                "location": field["location"],
                "term": term,
                "source": source,
                "start": start,
                "end": start + len(term),
                "before": before,
                "after": after,
            }


class Terminology:
    def __init__(self, projects, translation):
        self.projects, self.translation = projects, translation
        self.engine = translation.engine
        self.lock = threading.RLock()
        self.scans = {}

    def root(self, project_id):
        record = self.projects.get(project_id)
        root = Path(record["source"]).resolve(strict=True)
        for protected in (
            self.translation.workspace,
            Path(__file__).resolve().parents[2],
        ):
            protected = Path(protected).resolve()
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise ValueError(
                    "Terminology review requires a game outside the application and profile folders."
                )
        return root

    def path(self, project_id, name):
        return project_path(self.root(project_id), WORK + "/" + name, exists=False)

    def draft_path(self, project_id, name):
        self.projects.get(project_id)
        return project_path(
            self.translation.workspace,
            "translation/projects/" + project_id + "/terminology/" + name,
            exists=False,
        )

    def settings(self, project_id):
        path = self.path(project_id, "terms.json")
        if not path.exists():
            terms = []
        else:
            value = read_json(path, limit=200_000)
            if (
                not isinstance(value, dict)
                or value.get("version") != 1
                or not isinstance(value.get("terms"), list)
                or any(not isinstance(term, str) for term in value["terms"])
            ):
                raise ValueError(
                    "Saved terminology terms need recovery. The file was retained."
                )
            terms = terms_from("\n".join(value["terms"]))
        return {"revision": digest(terms), "text": "\n".join(terms)}

    def summary(self, project_id):
        path = self.path(project_id, "current.json")
        if not path.exists():
            return None
        value = read_json(path, limit=20_000)
        if value.get("version") != 1 or value.get("projectId") != project_id:
            raise ValueError(
                "Saved terminology findings belong to a different project or version."
            )
        return value

    def state(self, project_id):
        with self.lock:
            settings = self.settings(project_id)
            draft_path = self.draft_path(project_id, "terms.json")
            draft = (
                read_json(draft_path, limit=200_000) if draft_path.exists() else None
            )
            scan = self.summary(project_id)
            supported = self.projects.get(project_id)["engine"] in {"MVMZ", "ACE"}
            return {
                "projectId": project_id,
                "settings": settings,
                "draft": draft,
                "scan": scan,
                "supported": supported,
                "outdated": bool(
                    scan and scan["termsRevision"] != settings["revision"]
                ),
            }

    def terms_draft(self, project_id, value):
        with self.lock:
            path = self.draft_path(project_id, "terms.json")
            if value is None:
                path.unlink(missing_ok=True)
            else:
                if not isinstance(value, dict) or set(value) != {"revision", "text"}:
                    raise ValueError("Invalid terminology draft.")
                bounded(value["revision"], "Terms revision", 64)
                bounded(value["text"], "Custom terms", 40_000)
                write_json(path, value)
            return {"saved": True}

    def save_terms(self, project_id, revision, text):
        with self.lock:
            if revision != self.settings(project_id)["revision"]:
                raise ValueError(
                    "Custom terms changed elsewhere. Reload the saved terms before saving your edits."
                )
            write_json(
                self.path(project_id, "terms.json"),
                {"version": 1, "terms": terms_from(text)},
            )
            self.terms_draft(project_id, None)
            return self.settings(project_id)

    def sources(self, project_id):
        root = self.root(project_id)
        names = self.engine.terminology_files(root)
        if not names:
            raise ValueError(
                "No game JSON is available. Prepare the RPG Maker files first; Ace needs its JSON exports."
            )
        if len(names) > 2000:
            raise ValueError("Terminology scans support at most 2,000 game JSON files.")
        for name in names:
            project_path(root, name)
        return root, names, self.engine.source_bindings(root, names)

    def read_source(self, root, name, original=None):
        path = project_path(root, name)
        if original:
            raw = self.engine.original_bytes(root, original)
        else:
            before = path.stat()
            if before.st_size > 32_000_000:
                raise ValueError(f"{name} exceeds the 32 MB per-file scan limit.")
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (
                after.st_mtime_ns,
                after.st_size,
            ):
                raise ValueError(
                    "A source file changed while scanning. Scan again after its writer finishes."
                )
        if len(raw) > 32_000_000:
            raise ValueError(f"{name} exceeds the 32 MB per-file scan limit.")
        return raw

    def verify_sources(self, project_id, files):
        root = self.root(project_id)
        originals = self.engine.source_bindings(root, list(files))
        for name, expected in files.items():
            if (
                originals.get(name) != expected.get("original")
                or digest(self.read_source(root, name, originals.get(name)))
                != expected["sha256"]
            ):
                raise ValueError(
                    "Source changed since this scan. Scan again before saving or copying reviewed context."
                )

    def scan(self, project_id, revision):
        with self.lock:
            settings = self.settings(project_id)
            if revision != settings["revision"]:
                raise ValueError(
                    "Custom terms changed. Save and scan the current terms."
                )
            terms = terms_from(settings["text"])
            if not terms:
                raise ValueError("Add at least one custom term before scanning.")
            root, names, originals = self.sources(project_id)
            rows, files, size = [], {}, 0
            for name in names:
                raw = self.read_source(root, name, originals.get(name))
                size += len(raw)
                if size > MAX_BYTES:
                    raise ValueError(
                        "The game JSON exceeds the 128 MB terminology scan limit."
                    )
                files[name] = {
                    "sha256": digest(raw),
                    **({"original": originals[name]} if name in originals else {}),
                }
                for row in occurrences(project_id, name, decode_json(raw), terms):
                    rows.append(row)
                    if len(rows) > MAX_MATCHES:
                        raise ValueError(
                            "More than 20,000 occurrences match. Narrow the custom terms and scan again."
                        )
            self.verify_sources(project_id, files)
            document = {
                "version": 1,
                "projectId": project_id,
                "terms": terms,
                "files": files,
                "occurrences": rows,
            }
            scan_id = digest(document)
            path = self.path(project_id, "scans/" + scan_id + ".json")
            if not path.exists():
                write_json(path, document)
            elif digest(read_json(path)) != scan_id:
                raise ValueError(
                    "A preserved terminology scan changed outside the app. Its file was retained."
                )
            summary = {
                "version": 1,
                "projectId": project_id,
                "id": scan_id,
                "termsRevision": revision,
                "created": datetime.now(UTC).isoformat(),
                "files": len(files),
                "matches": len(rows),
                "origin": "original"
                if len(originals) == len(names)
                else "mixed"
                if originals
                else "game",
            }
            write_json(self.path(project_id, "current.json"), summary)
            return summary

    def load_scan(self, project_id, scan_id):
        path = self.path(project_id, "scans/" + identity(scan_id) + ".json")
        if not path.is_file():
            raise ValueError(
                "The saved terminology scan is unavailable. Scan the source text again."
            )
        stat = path.stat()
        signature = (scan_id, stat.st_mtime_ns, stat.st_size)
        cached = self.scans.get(project_id)
        if cached and cached[0] == signature:
            return cached[1]
        value = read_json(path)
        if (
            value.get("projectId") != project_id
            or value.get("version") != 1
            or digest(value) != scan_id
        ):
            raise ValueError(
                "The saved terminology scan changed or belongs to another project."
            )
        self.scans[project_id] = (signature, value)
        return value

    def review(self, project_id, occurrence_id):
        path = self.path(project_id, "reviews/" + identity(occurrence_id) + ".json")
        if not path.exists():
            return {"revision": "new", "character": "", "note": "", "reviewed": False}
        value = read_json(path, limit=40_000)
        if (
            value.get("version") != 1
            or value.get("projectId") != project_id
            or value.get("id") != occurrence_id
        ):
            raise ValueError(
                "The saved context belongs to another terminology occurrence."
            )
        return {
            "revision": digest(value),
            "character": value["character"],
            "note": value["note"],
            "reviewed": True,
        }

    def list(self, project_id, scan_id, query="", term="", offset=0):
        with self.lock:
            bounded(query, "Search", 256)
            bounded(term, "Term filter", 256)
            if type(offset) is not int or offset < 0:
                raise ValueError("Choose a valid occurrence page.")
            scan = self.load_scan(project_id, scan_id)
            needle = query.casefold().strip()
            rows = [
                row
                for row in scan["occurrences"]
                if (not term or row["term"] == term)
                and (
                    not needle
                    or needle in (row["file"] + "\n" + row["source"]).casefold()
                )
            ]
            page = [
                {**row, "review": self.review(project_id, row["id"])}
                for row in rows[offset : offset + PAGE_SIZE]
            ]
            return {
                "scanId": scan_id,
                "rows": page,
                "total": len(rows),
                "offset": offset,
                "nextOffset": offset + len(page)
                if offset + len(page) < len(rows)
                else None,
                "terms": scan["terms"],
            }

    def occurrence(self, project_id, scan_id, occurrence_id):
        scan = self.load_scan(project_id, scan_id)
        row = next(
            (
                row
                for row in scan["occurrences"]
                if row["id"] == identity(occurrence_id)
            ),
            None,
        )
        if row is None:
            raise ValueError("Choose an occurrence belonging to this scan and project.")
        return scan, row

    def detail(self, project_id, scan_id, occurrence_id):
        with self.lock:
            scan, row = self.occurrence(project_id, scan_id, occurrence_id)
            stale = ""
            try:
                self.verify_sources(
                    project_id, {row["file"]: scan["files"][row["file"]]}
                )
            except (ValueError, OSError) as exc:
                stale = str(exc)
            path = self.draft_path(project_id, occurrence_id + ".json")
            return {
                "scanId": scan_id,
                "occurrence": deepcopy(row),
                "saved": self.review(project_id, occurrence_id),
                "draft": read_json(path, limit=40_000) if path.exists() else None,
                "stale": stale,
            }

    def review_draft(self, project_id, scan_id, occurrence_id, value):
        with self.lock:
            self.occurrence(project_id, scan_id, occurrence_id)
            path = self.draft_path(project_id, occurrence_id + ".json")
            if value is None:
                path.unlink(missing_ok=True)
            else:
                write_json(path, review_value(value))
            return {"saved": True}

    def save_review(self, project_id, scan_id, occurrence_id, value):
        with self.lock:
            scan, row = self.occurrence(project_id, scan_id, occurrence_id)
            value = review_value(value)
            current = self.summary(project_id)
            if (
                not current
                or current["id"] != scan_id
                or current["termsRevision"] != self.settings(project_id)["revision"]
            ):
                raise ValueError(
                    "The saved terms or scan changed. Open the current occurrence before saving context."
                )
            self.verify_sources(project_id, {row["file"]: scan["files"][row["file"]]})
            if value["revision"] != self.review(project_id, occurrence_id)["revision"]:
                raise ValueError(
                    "This occurrence's context changed elsewhere. Reload before saving your edits."
                )
            write_json(
                self.path(project_id, "reviews/" + occurrence_id + ".json"),
                {
                    "version": 1,
                    "projectId": project_id,
                    "id": occurrence_id,
                    "character": value["character"],
                    "note": value["note"],
                },
            )
            self.review_draft(project_id, scan_id, occurrence_id, None)
            return self.review(project_id, occurrence_id)

    def export(self, project_id, scan_id):
        with self.lock:
            current = self.state(project_id)
            if (
                not current["scan"]
                or current["scan"]["id"] != scan_id
                or current["outdated"]
            ):
                raise ValueError("Scan the saved custom terms before copying context.")
            if current["draft"] and current["draft"] != current["settings"]:
                raise ValueError(
                    "Save or discard your custom term edits before copying context."
                )
            scan = self.load_scan(project_id, scan_id)
            rows = []
            for row in scan["occurrences"]:
                review = self.review(project_id, row["id"])
                if not review["reviewed"]:
                    continue
                draft = self.draft_path(project_id, row["id"] + ".json")
                if draft.exists():
                    raise ValueError(
                        "Save or discard the open context drafts before copying reviewed context."
                    )
                rows.append(
                    {**row, "character": review["character"], "note": review["note"]}
                )
            if not rows:
                raise ValueError(
                    "Save context for at least one occurrence before copying reviewed context."
                )
            self.verify_sources(
                project_id, {row["file"]: scan["files"][row["file"]] for row in rows}
            )
            return {
                "version": 1,
                "projectId": project_id,
                "scanId": scan_id,
                "description": "Original source with user-reviewed terminology notes. Notes describe context; they do not replace source wording or establish unsupported facts.",
                "occurrences": rows,
            }
