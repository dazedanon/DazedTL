"""Retained assistant investigation, exact text edits and reviewed runtime publication."""

import json
import os
import re
import shlex
import sys
import threading
import uuid
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dazedtl import foreign_work
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import backups, reference_folders
from dazedtl.translation.files import decode_json, digest, project_path, read_json
from dazedtl.translation.operations import (
    lifecycle,
    lifecycle_path,
    require_source_backup,
)

from .documents import Documents, decode, occurrences, reason, validate

WORK = ".dazedtl/plugin-work"
# Bump when scanning finds different files, text or problems, so saved scans
# are read again once.
SCAN_RULES = 2
# What the assistant can settle for one occurrence. Reports saved before every
# occurrence needed a decision may still say "unresolved"; that text stays
# with the assistant.
DECIDED = {"visible", "latent", "protected", "editor_only", "non_visible"}
DISPOSITIONS = DECIDED | {"unresolved"}
DATABASE_JSON = {
    "Actors.json",
    "Classes.json",
    "Skills.json",
    "Items.json",
    "Weapons.json",
    "Armors.json",
    "Enemies.json",
    "Troops.json",
    "States.json",
    "Animations.json",
    "Tilesets.json",
    "System.json",
    "CommonEvents.json",
    "MapInfos.json",
}


def now():
    return datetime.now(UTC).isoformat()


def bounded(value, label, limit=4000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(label + " must be bounded text.")
    return value


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def undecided(item):
    """Text only the assistant can settle; the app protects lookup keys itself."""
    return (
        not item["protected"]
        and item.get("finding", {}).get("disposition") not in DECIDED
    )


def no_context(_project_id):
    return {"translated": "", "references": []}


# Stored reviews and receipts also keep the working copies and frozen bytes that
# publication and recovery check; the renderer sees only what it shows.
REVIEW_KEYS = (
    "path",
    "destination",
    "beforeHash",
    "afterHash",
    "originalHash",
    "candidateHash",
    "backup",
    "changes",
    "kind",
)


def preview_view(preview):
    return {
        **pick(preview, ("token", "mode", "blocked", "manifest")),
        "files": [pick(row, REVIEW_KEYS) for row in preview["files"]],
    }


def carries(files, receipt):
    """Whether a file still carries this application; later restores and
    applications supersede older receipts."""
    return receipt["mode"] == "apply" and any(
        files.get(row["path"], {}).get("applied", {}).get("receipt") == receipt["id"]
        for row in receipt["files"]
    )


def receipt_view(receipt, files):
    return {
        **pick(
            receipt,
            (
                "id",
                "mode",
                "saved",
                "status",
                "failure",
                "conflicts",
                "manifest",
                "restoreIssue",
            ),
        ),
        "files": [pick(row, REVIEW_KEYS) for row in receipt["files"]],
        # Only the application a file still carries can restore it.
        "restorable": carries(files, receipt) and not receipt.get("restoreIssue"),
    }


def safe_name(name):
    # MZ loads plugins from subfolders of js/plugins, such as Author/Plugin;
    # each folder and file name must still be a plain name.
    if (
        not isinstance(name, str)
        or not name
        or any(c in name for c in "\\:\x00\r\n")
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Configured plugin names must be exact safe filenames.")
    return name


class PluginService:
    def __init__(
        self, projects, translation, backend, *, documents=None, context=no_context
    ):
        self.projects, self.translation, self.backend = projects, translation, backend
        self.documents = documents or Documents()
        # Where the game's established English lives beyond its guidance files:
        # the translated text folder and the reference games.
        self.context = context
        self.lock = threading.RLock()
        self.previews, self.cache, self.observed, self.foreign = {}, {}, {}, {}

    def record(self, project_id):
        project = self.projects.get(project_id)
        root = Path(project["source"]).resolve(strict=True)
        for protected in (self.translation.workspace, self.backend.source):
            path = Path(protected).resolve()
            if root.is_relative_to(path) or path.is_relative_to(root):
                raise ValueError(
                    "Plugin work needs a game separate from the app and profile."
                )
        return project, root

    def path(self, project_id, name):
        return project_path(self.record(project_id)[1], WORK + "/" + name, exists=False)

    def load(self, project_id):
        path = self.path(project_id, "state.json")
        if not path.exists():
            return {
                "version": 1,
                "projectId": project_id,
                "files": {},
                "selection": [],
                "requests": {},
                "findings": {"status": "idle", "errors": []},
                "editing": {"status": "idle", "errors": []},
                "receipts": [],
                "pending": [],
                "layout": "",
                "originals": {},
                "binding": "",
            }
        signature = (path.stat().st_mtime_ns, path.stat().st_size)
        saved = self.cache.get(project_id)
        if saved and saved[0] == signature:
            value = deepcopy(saved[1])
        else:
            try:
                value = read_json(path, limit=64_000_000)
            except ValueError:
                value = None
            if not foreign_work.owned(value, project_id):
                raise ForeignWorkError(
                    "Plugin work in this game folder was saved by another project or app version. Its files were kept; choose how to continue in Plugin files.",
                    self.foreign_summary(project_id, path, value, signature),
                )
        # The file table and manual text choices are gone; text is chosen from
        # the assistant's findings alone.
        value.pop("view", None)
        value.pop("manual", None)
        self.cache[project_id] = (signature, deepcopy(value))
        return value

    def save(self, project_id, value):
        path = self.path(project_id, "state.json")
        write_json(path, value)
        self.cache[project_id] = (
            (path.stat().st_mtime_ns, path.stat().st_size),
            deepcopy(value),
        )

    def foreign_summary(self, project_id, path, value, signature):
        """What another project's saved plugin work holds, and whether it can be
        used here. Snapshots ask often, so it is kept until the file changes."""
        saved = self.foreign.get(project_id)
        if saved and saved[0] == signature:
            return saved[1]
        counts = {"investigated": 0, "translated": 0, "applied": 0, "restorable": 0}
        blocked = ""
        try:
            if not foreign_work.readable(value):
                raise TypeError
            rows = value["files"].values()
            carried = self.carried_receipts(project_id, value)
            counts.update(
                investigated=sum(bool(row.get("examined")) for row in rows),
                translated=sum(bool(row.get("result")) for row in rows),
                applied=sum(bool(row.get("applied")) for row in rows),
                restorable=sum(
                    row.get("applied", {}).get("receipt") in carried for row in rows
                ),
            )
            if value["pending"]:
                blocked = foreign_work.INTERRUPTED
        except AttributeError, KeyError, TypeError:
            blocked = foreign_work.UNREADABLE
        summary = {**foreign_work.summary(path), **counts, "blocked": blocked}
        self.foreign[project_id] = (signature, summary)
        return summary

    def carried_receipts(self, project_id, value):
        """Earlier applications a new owner can restore: a file still carries
        each one, and its journal and backups match its receipt exactly."""
        _, root = self.record(project_id)
        verified = {}
        for receipt in value["receipts"]:
            if not carries(value["files"], receipt):
                continue
            try:
                publication = read_json(
                    self.path(
                        project_id, "publications/" + receipt["id"] + "/approval.json"
                    )
                )
                approved = {row["path"]: row for row in publication["files"]}
                if (
                    publication["id"] != receipt["id"]
                    or publication["mode"] != "apply"
                    or publication["manifest"] != receipt["manifest"]
                    or any(approved.get(row["path"]) != row for row in receipt["files"])
                    or any(
                        digest(self.source(root, row["backup"])) != row["beforeHash"]
                        for row in receipt["files"]
                    )
                ):
                    continue
            except OSError, ValueError, KeyError, TypeError:
                continue
            verified[receipt["id"]] = publication
        return verified

    def foreign_state(self, project_id, binding):
        """Another project's saved work and its summary, as the user was shown them."""
        try:
            self.load(project_id)
        except ForeignWorkError as exc:
            path = self.path(project_id, "state.json")
            return foreign_work.reviewed(path, exc.summary, binding), exc.summary
        raise ValueError("This project's plugin work is already in use.")

    def adopt(self, project_id, binding):
        """Takes over another project's saved work after the user chose it.

        Findings, choices, working copies and application records carry over.
        Copied tasks do not: their requests are bound to the other project, so
        their reports are never accepted here and the next copy starts afresh.
        Applications stay restorable only where journal and backups still match.
        """
        with self.lock:
            raw, summary = self.foreign_state(project_id, binding)
            if summary["blocked"]:
                raise ValueError(summary["blocked"])
            value = decode_json(raw)
            previous = value["projectId"]
            carried = self.carried_receipts(project_id, value)
            for receipt in value["receipts"]:
                if receipt["id"] in carried:
                    write_json(
                        Path(self.translation.workspace)
                        / "plugin-approvals"
                        / project_id
                        / (receipt["id"] + ".json"),
                        {
                            "journalHash": digest(carried[receipt["id"]]),
                            "projectId": project_id,
                            "id": receipt["id"],
                        },
                    )
                elif carries(value["files"], receipt):
                    receipt["restoreIssue"] = (
                        "Its saved record no longer matches the files it applied, so it can't be restored here. The Project page's Backups can recover the original game."
                    )
            rows = value["files"].values()
            results = [row["result"] for row in rows if row.get("result")]
            for result in results:
                result["carried"] = True
            # A report still awaited will never arrive here; the record
            # describes the work kept instead.
            for key, done in (
                ("findings", [bool(row.get("examined")) for row in rows]),
                ("editing", [result["status"] == "ready" for result in results]),
            ):
                if value[key]["status"] == "awaiting_report":
                    accepted = sum(done)
                    value[key] = {
                        "status": "idle"
                        if not accepted
                        else "current"
                        if accepted == len(done)
                        else "partial",
                        "errors": [],
                        **(
                            {"accepted": accepted, "expected": len(done)}
                            if done
                            else {}
                        ),
                    }
            value.update(
                projectId=project_id,
                requests={},
                activeRequest="",
                adopted={"projectId": previous, "saved": now()},
            )
            self.save(project_id, value)
            self.foreign.pop(project_id, None)
            return {
                "state": self.state(project_id),
                "message": "Saved plugin work is now used here.",
            }

    def start_over(self, project_id, binding):
        """Moves another project's saved work aside, keeping every file."""
        with self.lock:
            self.foreign_state(project_id, binding)
            _, root = self.record(project_id)
            archived = foreign_work.archive(root, WORK, "plugin-work")
            self.cache.pop(project_id, None)
            self.foreign.pop(project_id, None)
            return {
                "state": self.state(project_id),
                "message": "Earlier plugin work moved to " + archived + ".",
            }

    def source(self, root, path):
        target = project_path(root, path)
        if not target.is_file() or target.stat().st_size > 16_000_000:
            raise ValueError("Plugin files must be regular files below 16 MB.")
        before = target.stat()
        raw = target.read_bytes()
        after = target.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError(
                "A plugin file changed during reading. Refresh when its writer finishes."
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Plugin files must be UTF-8 text.") from exc
        return raw

    def inventory(self, project_id):
        project, root = self.record(project_id)
        if project["engine"] == "ACE":
            raise ValueError(
                "Ace scripts require a Ruby parser and native packing integration. Existing extracted scripts remain untouched; use the preserved Ruby assistant workflow separately."
            )
        if project["engine"] != "MVMZ":
            raise ValueError("Plugin files support RPG Maker MV/MZ.")
        matches = [
            prefix
            for prefix in ("www/", "")
            if (root / (prefix + "js/plugins.js")).is_file()
        ]
        if len(matches) != 1:
            raise ValueError(
                "Choose a game with one unambiguous js/plugins.js or www/js/plugins.js."
            )
        prefix = matches[0]
        config = prefix + "js/plugins.js"
        parsed = self.documents.parse(
            [
                {
                    "path": config,
                    "source": self.source(root, config).decode(),
                    "kind": "parameters",
                }
            ]
        )[config]
        if parsed["issues"]:
            raise ValueError(parsed["issues"][0])
        rows = {
            config: {
                "path": config,
                "kind": "parameters",
                "plugin": "Plugin parameters",
                "enabled": True,
            }
        }
        names = set()
        statuses = {}
        for index, entry in enumerate(parsed["plugins"]):
            if (
                not isinstance(entry, dict)
                or type(entry.get("status")) is not bool
                or not isinstance(entry.get("parameters"), dict)
            ):
                raise ValueError(
                    "Every plugin entry needs a static name, status and parameter object."
                )
            name = safe_name(entry.get("name"))
            if name in names:
                raise ValueError(
                    "Duplicate configured plugins need investigation before exact scope can be formed."
                )
            names.add(name)
            statuses[name] = entry["status"]
            path = prefix + "js/plugins/" + name + ".js"
            # A listed plugin whose file is gone has no text to translate.
            if not (root / path).exists():
                continue
            rows[path] = {
                "path": path,
                "kind": "source",
                "plugin": name,
                "enabled": entry["status"],
                "pluginIndex": index,
            }
        for path in sorted((root / (prefix + "js/plugins")).glob("*.js")):
            relative = path.relative_to(root).as_posix()
            owner = (
                path.stem.removesuffix("Config")
                if path.stem.endswith("Config")
                else path.stem
            )
            rows.setdefault(
                relative,
                {
                    "path": relative,
                    "kind": "config" if path.stem.endswith("Config") else "source",
                    "plugin": path.stem,
                    "enabled": statuses.get(owner),
                },
            )
        return prefix, rows, parsed

    def original_context(self, project_id, prefix):
        _, root = self.record(project_id)
        state = lifecycle(self.translation.workspace, project_id)
        require_source_backup(root, state)
        record = state["source_backup"]
        location = backups.lookup(root, Path(record["path"]).parent, record["id"])
        manifest = backups.manifest(location, root)
        names = [
            name
            for name in manifest["files"]
            if name.startswith(prefix + "data/") and name.endswith(".json")
        ]
        if not names or prefix + "js/plugins.js" not in manifest["files"]:
            raise ValueError(
                "The preserved original lacks the Japanese database or plugin configuration. Recover the matching original source before editing."
            )
        keys, hashes = set(), {name: manifest["files"][name] for name in names}
        with backups.materialized(
            location, files=[*names, prefix + "js/plugins.js"]
        ) as (original, _):

            def nested(value):
                if isinstance(value, str):
                    keys.add(value)
                    try:
                        inner = decode(value)
                    except ValueError:
                        return
                    if isinstance(inner, (dict, list, str)):
                        nested(inner)
                elif isinstance(value, dict):
                    keys.update(value)
                    for inner in value.values():
                        nested(inner)
                elif isinstance(value, list):
                    for inner in value:
                        nested(inner)

            def fields(value, database):
                if isinstance(value, dict):
                    note = value.get("note")
                    if isinstance(note, str):
                        keys.update(
                            match.group(1).strip()
                            for match in re.finditer(r"<([^<>:]+)(?::[^<>]*)?>", note)
                        )
                    if database and isinstance(value.get("name"), str):
                        keys.add(value["name"])
                    if value.get("code") in {356, 357} and isinstance(
                        value.get("parameters"), list
                    ):
                        for item in value["parameters"]:
                            if isinstance(item, str) and value["code"] == 356:
                                keys.update(item.split())
                            nested(item)
                    for item in value.values():
                        fields(item, database)
                elif isinstance(value, list):
                    for item in value:
                        fields(item, database)

            for name in names:
                fields(
                    read_json(original / name),
                    Path(name).name
                    in {
                        "Actors.json",
                        "Classes.json",
                        "Skills.json",
                        "Items.json",
                        "Weapons.json",
                        "Armors.json",
                        "Enemies.json",
                        "States.json",
                    },
                )
            raw = (original / (prefix + "js/plugins.js")).read_bytes()
            parsed = self.documents.parse(
                [
                    {
                        "path": prefix + "js/plugins.js",
                        "source": raw.decode(),
                        "kind": "parameters",
                    }
                ]
            )[prefix + "js/plugins.js"]
            if parsed["issues"]:
                raise ValueError(
                    "The preserved original plugin configuration cannot be parsed."
                )
            structural_keys = sorted(keys)
            for entry in parsed["plugins"]:
                nested(entry["parameters"])
        hashes[prefix + "js/plugins.js"] = manifest["files"][prefix + "js/plugins.js"]
        return {
            "backupId": record["id"],
            "hashes": hashes,
            "keys": sorted(keys),
            "structuralKeys": structural_keys,
            "binding": digest(hashes),
        }

    def scan(self, project_id, value):
        _, root = self.record(project_id)
        prefix, rows, config = self.inventory(project_id)
        # Explicit JSON dependencies discovered in a previous request remain addressable.
        for path, row in value["files"].items():
            if row["kind"] == "json":
                rows[path] = {
                    key: row[key]
                    for key in ("path", "kind", "plugin", "enabled", "dependency")
                }
        files, raw_files = [], {}
        for path, row in rows.items():
            try:
                raw = self.source(root, path)
                raw_files[path] = raw
                files.append(
                    {"path": path, "source": raw.decode(), "kind": row["kind"]}
                )
            except (OSError, ValueError, UnicodeError) as exc:
                row["issue"] = str(exc)
        parsed = self.documents.parse(files)
        try:
            originals = self.original_context(project_id, prefix)
            original_issue = ""
        except (OSError, ValueError, UnicodeError) as exc:
            originals = {}
            original_issue = str(exc)
        protected = set(originals.get("keys", []))
        for path, row in rows.items():
            prior = value["files"].get(path, {})
            row["sourceHash"] = digest(raw_files[path]) if path in raw_files else ""
            row["issue"] = row.get("issue") or " ".join(
                reason(issue) for issue in parsed.get(path, {}).get("issues", [])
            )
            try:
                row["occurrences"] = (
                    occurrences(path, raw_files[path], parsed[path])
                    if path in parsed and not row["issue"]
                    else []
                )
            except ValueError as exc:
                row["occurrences"], row["issue"] = [], str(exc)
            row["loaderLiterals"] = [
                {
                    "id": digest(
                        {
                            "file": path,
                            "span": [item["start"], item["end"]],
                            "value": item["value"],
                        }
                    )[:24],
                    "value": item["value"],
                    "line": item["line"],
                }
                for item in parsed.get(path, {}).get("literals", [])
                if isinstance(item["value"], str) and item["value"].endswith(".json")
            ]
            code_keys = {
                item["value"]
                for item in parsed.get(path, {}).get("literals", [])
                if item["protected"]
            }
            if row["kind"] == "parameters":
                for item in row["occurrences"]:
                    logical = parsed[path]["literals"][item["token"]]["path"]
                    if (
                        len(logical) >= 3
                        and type(logical[0]) is int
                        and logical[1] == "parameters"
                    ):
                        entry = config["plugins"][logical[0]]
                        item.update(
                            plugin=entry["name"],
                            enabled=entry["status"],
                            parameterPath=logical[2:],
                        )
                    else:
                        item["protected"] = True
            for item in row["occurrences"]:
                item.setdefault("plugin", row["plugin"])
                item.setdefault("enabled", row["enabled"])
                lookup_keys = (
                    set(originals.get("structuralKeys", []))
                    if row["kind"] == "parameters"
                    else protected
                )
                item["protected"] = (
                    item["protected"]
                    or item["value"] in lookup_keys
                    or item["value"] in code_keys
                )
                item["latent"] = not item["enabled"] or item["kind"] == "default"
                old = next(
                    (
                        old
                        for old in prior.get("occurrences", [])
                        if old["id"] == item["id"]
                    ),
                    {},
                )
                for key in ("finding", "target"):
                    if key in old and row["sourceHash"] == prior.get("sourceHash"):
                        item[key] = old[key]
            if row["sourceHash"] == prior.get("sourceHash"):
                for key in ("prepared", "result", "applied", "examined"):
                    if key in prior:
                        row[key] = prior[key]
            elif prior.get("applied") and row["sourceHash"] == prior["applied"].get(
                "afterHash"
            ):
                # Applied source is displayed separately; frozen investigation remains meaningful.
                row = {**prior, "observedHash": row["sourceHash"]}
            else:
                row["stale"] = bool(prior)
                if prior.get("prepared"):
                    row["archivedPrepared"] = prior["prepared"]
            # A file with no unprotected Japanese text and no JSON it loads
            # leaves the assistant nothing to decide.
            if (
                not row["issue"]
                and not row["loaderLiterals"]
                and all(item["protected"] for item in row["occurrences"])
            ):
                row.update(examined=True, stale=False)
            rows[path] = row
        value.update(
            files=rows,
            layout=prefix + "js/plugins.js",
            originals=originals,
            originalIssue=original_issue,
        )
        value["binding"] = digest(
            {path: row["sourceHash"] for path, row in rows.items()}
        )
        value["scanRules"] = SCAN_RULES
        return parsed

    def eligible(self, value):
        return {
            item["id"]: item
            for row in value["files"].values()
            if not row.get("issue") and not row.get("stale")
            for item in row["occurrences"]
            if not item["protected"]
            and item.get("finding", {}).get("disposition") in {"visible", "latent"}
            and item.get("finding", {}).get("safe") is True
        }

    def chosen_text(self, value):
        """Active display text the assistant found safe to change; inactive and
        default-only text never reaches players."""
        return sorted(
            identity
            for identity, item in self.eligible(value).items()
            if not item["latent"] and item["finding"]["disposition"] == "visible"
        )

    @staticmethod
    def row_status(value, row):
        """Where one file stands: unreadable, investigate, translate, ready,
        applied, translated (checked with nothing to change) or none (no
        player text)."""
        if row.get("issue"):
            return "unreadable"
        if (
            row.get("stale")
            or not row.get("examined")
            or any(undecided(item) for item in row["occurrences"])
        ):
            return "investigate"
        selected = set(value["selection"])
        ids = sorted(
            item["id"] for item in row["occurrences"] if item["id"] in selected
        )
        result = row.get("result", {})
        checked = result.get("selection") == ids and result.get("status") in {
            "ready",
            "unchanged",
        }
        if (
            checked
            and row.get("applied")
            and result.get("candidateHash") == row["applied"]["afterHash"]
        ):
            return "applied"
        if not ids:
            return "none"
        if not checked:
            return "translate"
        return "ready" if result["status"] == "ready" else "translated"

    def investigation_scope(self, value, *, recheck=False):
        """Each readable file with text the assistant has not settled, asking
        only about that text; a recheck asks about every decision again."""
        scope = []
        for path, row in value["files"].items():
            if row.get("issue"):
                continue
            asked = [
                item
                for item in row["occurrences"]
                if not item["protected"] and (recheck or undecided(item))
            ]
            if asked or self.row_status(value, row) == "investigate":
                scope.append((path, asked))
        return scope

    def translation_scope(self, value):
        """Files with chosen text whose checked translation is missing or out
        of date, with that text."""
        selected = set(value["selection"])
        return [
            (path, [item for item in row["occurrences"] if item["id"] in selected])
            for path, row in value["files"].items()
            if self.row_status(value, row) == "translate"
        ]

    def observe(self, project_id, value):
        """Bounded observations invalidate displayed checks without rewriting assistant work."""
        _, root = self.record(project_id)

        def fingerprint(path):
            target = project_path(root, path)
            stat = target.stat()
            signature = (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            )
            cached = self.observed.get(str(target))
            if not cached or cached[0] != signature:
                cached = (signature, digest(self.source(root, path)))
                self.observed[str(target)] = cached
            return cached[1]

        for row in value["files"].values():
            try:
                if not project_path(root, row["path"], exists=False).exists():
                    # A removed plugin has nothing to translate; the next scan
                    # drops it.
                    row.update(stale=True, issue="")
                    continue
                result = row.get("result", {})
                expected = row.get("applied", {}).get("afterHash") or row["sourceHash"]
                if fingerprint(row["path"]) != expected:
                    row["stale"] = True
                    # A file the last scan could not read reads now; the
                    # assistant has to look at it.
                    if not row["sourceHash"]:
                        row["issue"] = ""
                if not row.get("prepared"):
                    continue
                prepared = row["prepared"]
                if fingerprint(prepared["original"]) != prepared["originalHash"]:
                    row["issue"] = (
                        "Frozen original changed; recover it before continuing."
                    )
                if (
                    result
                    and fingerprint(prepared["candidate"]) != result["candidateHash"]
                ):
                    row["result"] = {
                        **result,
                        "status": "needs_revision",
                        "reason": "The working copy changed after its check; the plugin task checks it again.",
                        "checks": {},
                    }
                ids = sorted(
                    item["id"]
                    for item in row["occurrences"]
                    if item["id"] in value["selection"]
                )
                if result and ids and ids != result["selection"]:
                    row["result"] = {
                        **result,
                        "status": "needs_revision",
                        "reason": "The text to translate changed; the plugin task translates it again.",
                        "checks": {},
                    }
                # Work taken over from another project was checked there; what
                # the game already holds stays applied.
                if (
                    result.get("carried")
                    and result.get("status") == "ready"
                    and result.get("candidateHash")
                    != row.get("applied", {}).get("afterHash")
                ):
                    row["result"] = {
                        **result,
                        "status": "needs_revision",
                        "reason": "Checked by the project that saved this work. Copy the plugin task so your assistant checks it here; the working copy is kept.",
                        "checks": {},
                    }
            except (OSError, ValueError) as exc:
                row["issue"] = str(exc)

    def state(self, project_id):
        with self.lock:
            value = self.load(project_id)
            self.recover(project_id, value)
            if value["binding"] and value.get("scanRules") != SCAN_RULES:
                try:
                    self.scan(project_id, value)
                    self.save(project_id, value)
                except OSError, ValueError, UnicodeError:
                    # A copied task scans again and reports the problem.
                    value = self.load(project_id)
            self.observe(project_id, value)
            project, _ = self.record(project_id)
            # Files with nothing for the assistant to decide stay out of the
            # counts, so they read as the assistant's progress; a changed file
            # counts until a scan says what it holds now.
            statuses = Counter(
                self.row_status(value, row)
                for row in value["files"].values()
                if row.get("issue")
                or row.get("stale")
                or row.get("loaderLiterals")
                or not all(item["protected"] for item in row["occurrences"])
            )
            translated = (
                statuses["ready"] + statuses["applied"] + statuses["translated"]
            )
            active = next(
                (
                    request
                    for request in value["requests"].values()
                    if request["requestId"] == value.get("activeRequest")
                ),
                None,
            )
            report = (
                value["findings" if active["kind"] == "investigation" else "editing"]
                if active
                else {}
            )
            return {
                "projectId": project_id,
                "supported": project["engine"] == "MVMZ",
                "limitation": "Ace Ruby scripts need parser and native packing support; this workspace cannot publish them."
                if project["engine"] == "ACE"
                else "",
                # Whether the game's plugins were read; counts start then.
                "scanned": bool(value["binding"]),
                "counts": {
                    "files": statuses.total() - statuses["unreadable"],
                    "investigated": statuses.total()
                    - statuses["investigate"]
                    - statuses["unreadable"],
                    "textFiles": translated + statuses["translate"],
                    "selected": len(value["selection"]),
                    "translated": translated,
                    "ready": statuses["ready"],
                    "applied": statuses["applied"],
                },
                # A file kept unchanged stays kept while it fails the same way.
                "unreadable": [
                    {
                        "path": path,
                        "issue": row["issue"],
                        "kept": value.get("kept", {}).get(path) == row["issue"],
                    }
                    for path, row in value["files"].items()
                    if row.get("issue")
                ],
                "originalIssue": self.original_issue(project_id, value),
                "receipts": [
                    receipt_view(row, value["files"]) for row in value["receipts"][-12:]
                ],
                # The helper reads the active request's saved instructions here.
                "activeRequest": active["path"] if active else "",
                "awaiting": bool(active)
                and report.get("status") == "awaiting_report"
                and report.get("requestId") == active["requestId"],
            }

    def original_issue(self, project_id, value):
        """Why the last scan had no original evidence, while that still holds."""
        issue = value.get("originalIssue", "")
        if issue and not value["originals"]:
            try:
                require_source_backup(
                    self.record(project_id)[1],
                    lifecycle(self.translation.workspace, project_id),
                )
            except OSError, ValueError:
                return issue
            return "The original backup is available now. Copy the plugin task again so its investigation can check the original text."
        return issue

    def action(self, project_id, action, options=None):
        options = options or {}
        if not isinstance(options, dict):
            raise ValueError("Plugin action options must be an object.")
        with self.lock:
            value = self.load(project_id)
            if action == "plugin_task":
                result = self.copy_task(project_id, value)
            elif action in {"preview_apply", "preview_restore"}:
                return {
                    "preview": preview_view(
                        self.preview(
                            project_id,
                            value,
                            "apply" if action == "preview_apply" else "restore",
                            options,
                        )
                    )
                }
            elif action in {"apply", "restore"}:
                return self.publish(project_id, value, action, options)
            elif action == "keep_unreadable":
                result = self.keep_unreadable(value, options.get("paths"))
            else:
                raise ValueError("Choose a supported Plugin files action.")
            self.save(project_id, value)
            return {**result, "state": self.state(project_id)}

    @staticmethod
    def keep_unreadable(value, paths):
        """Leave files the app cannot read unchanged, so they stop holding up
        the task; the choice lapses when a file fails differently."""
        issues = {
            path: row["issue"]
            for path, row in value["files"].items()
            if row.get("issue")
        }
        if (
            not isinstance(paths, list)
            or not paths
            or any(path not in issues for path in paths)
        ):
            raise ValueError("Choose plugin files the app cannot read.")
        value.setdefault("kept", {}).update({path: issues[path] for path in paths})
        return {}

    def copy_task(self, project_id, value):
        """The request a copied task starts from: whatever is left, or a recheck
        of every decision once nothing is."""
        self.scan(project_id, value)
        self.observe(project_id, value)
        active = next(
            (
                request
                for request in value["requests"].values()
                if request["requestId"] == value.get("activeRequest")
            ),
            None,
        )
        result = self.advance(project_id, value, active)
        if not result:
            scope = self.investigation_scope(value, recheck=True)
            if not scope:
                # The scan is the whole answer: nothing is handed out.
                return {"message": "No plugin holds Japanese text to translate."}
            result = self.request(
                project_id, value, "investigation", scope, recheck=True
            )
        # What the copied task expects back, for the assistant task list.
        return {
            **result,
            "handoff": {
                "kind": "plugins",
                "requestId": result["requestId"],
                "expects": [value["requests"][result["stage"]]["report"]],
            },
        }

    def advance(self, project_id, value, current=None):
        """The next request: text still to investigate first, then files to
        translate. A request whose scope has not changed is handed out again,
        so its saved report is extended rather than orphaned."""
        kind, scope = "investigation", self.investigation_scope(value)
        if not scope:
            kind, scope = "translation", self.translation_scope(value)
            if not scope:
                return None
            self.prepare(project_id, value)
        if current and self.same_scope(project_id, value, current, kind, scope):
            key = "findings" if kind == "investigation" else "editing"
            value[key] = {**value[key], "status": "awaiting_report"}
            return {
                "text": current["instructions"],
                "request": current["path"],
                "requestId": current["requestId"],
                "stage": kind,
            }
        return self.request(
            project_id,
            value,
            kind,
            scope,
            previous=current["requestId"] if current else "",
        )

    def guidance(self, root):
        paths = [
            ".dazedtl/glossary.txt",
            *[
                path.relative_to(root).as_posix()
                for path in (root / ".dazedtl/skills").glob("*.md")
            ],
        ]
        return {
            path: {
                "sha256": digest(self.source(root, path)),
                "text": self.source(root, path).decode(),
            }
            for path in paths
            if (root / path).is_file()
        }

    def request(self, project_id, value, kind, scope, *, previous="", recheck=False):
        """A request-bound stage of the copied task for exactly `scope`: the
        files and occurrences it asks about, with the game's established
        English as context."""
        _, root = self.record(project_id)
        if not value["originals"]:
            raise ValueError(
                value.get("originalIssue")
                or "Plugin text needs the original game backup to protect lookup values."
            )
        identity = uuid.uuid4().hex
        request_path = self.path(project_id, "requests/" + identity + ".json")
        report_path = self.path(project_id, "reports/" + identity + ".json")
        files = []
        for path, items in scope:
            row = value["files"][path]
            if kind == "translation" and not row.get("prepared"):
                raise ValueError("A file to translate has no working copy: " + path)
            files.append(
                {
                    "path": path,
                    "plugin": row["plugin"],
                    "sourceHash": row["sourceHash"],
                    "kind": row["kind"],
                    "enabled": row["enabled"],
                    "occurrences": items,
                    "loaderLiterals": row.get("loaderLiterals", [])
                    if kind == "investigation"
                    else [],
                    # Why an earlier translation of this file was not accepted.
                    "failedCheck": row.get("result", {}).get("reason", "")
                    if kind == "translation"
                    else "",
                    **row.get("prepared", {}),
                }
            )
        # Translation follows prepare(), which checked the originals.
        self.current_sources(project_id, value, files)
        context = self.context(project_id)
        game_data = root / value["layout"].removesuffix("js/plugins.js") / "data"
        # Requests never alias mutable findings, choices or results.
        request = deepcopy(
            {
                "version": 1,
                "kind": kind,
                "projectId": project_id,
                "requestId": identity,
                "binding": value["binding"],
                "guidance": self.guidance(root),
                "translatedText": context["translated"],
                "gameData": str(game_data),
                "references": context["references"],
                # The app guards the original lookup keys itself; the request
                # binds only which original it checked against.
                "originals": pick(value["originals"], ("backupId", "binding")),
                "layout": value["layout"],
                "files": files,
                "report": str(report_path),
                "path": str(request_path),
                "automatic": True,
                "previousRequestId": previous,
            }
        )
        value["findings" if kind == "investigation" else "editing"] = {
            "status": "awaiting_report",
            "errors": [],
            "requestId": identity,
        }
        identity_fields = {
            "version": 1,
            "kind": kind,
            "projectId": project_id,
            "requestId": identity,
            "binding": value["binding"],
            "complete": False,
        }
        text = (
            "Translate the text this game's plugins show to players. This is one DazedTL Plugin files task; copying it did not start an assistant. Keep DazedTL open.\n"
            "Work through it in this conversation: after each report, the helper below checks it and returns the next request, until every plugin file is investigated and its player text translated. "
            "Do not ask the user to copy another prompt or approve routine steps; ask only about choices the evidence cannot settle, after finishing the independent work.\n\n"
            "Read the request JSON: " + str(request_path) + "\n"
            "Save a structured report at: " + str(report_path) + "\n"
            "Bind version, kind, projectId, requestId and binding exactly, and use only the requested files, occurrence IDs and SHA-256 hashes. "
            "Never run plugin or game code, providers or translation APIs. Event plugin commands belong to Other event text; do not edit event or database JSON or images.\n\n"
        )
        if kind == "investigation":
            schema = {
                **identity_fields,
                "files": [
                    {
                        "path": "exact requested path",
                        "sourceHash": "request hash",
                        "examined": True,
                        "evidence": "complete source and recursive-parameter coverage",
                        "occurrences": [
                            {
                                "id": "requested occurrence ID",
                                "disposition": "visible|latent|protected|editor_only|non_visible",
                                "safe": True,
                                "evidence": "where the plugin uses it, with readback checks",
                                "reason": "why players see it, or why they do not",
                            }
                        ],
                    }
                ],
                "dependencies": [
                    {
                        "path": "exact plugin-loaded JSON path",
                        "sourceFile": "requested loader file",
                        "literalId": "requested literal ID containing the exact path",
                        "evidence": "static loader use",
                    }
                ],
            }
            text += (
                "INVESTIGATE. Decide whether players see each listed occurrence. Do not edit runtime files, working copies, settings or source backups in this stage.\n"
                "Read each listed source and its configuration in js/plugins.js. Recursively decode every parameter layer and follow each string to where the plugin uses it: drawing, messages, menus and help text, but also comparisons, lookups, keys and file names. "
                "Check defaults and fallbacks; comments and editor metadata are not player text.\n"
                "Dispositions: visible (an enabled plugin shows it to players), latent (display text players never see because its plugin is disabled or it is only a default), protected (compared, looked up, or used as a key or file name), editor_only, non_visible. "
                "Set safe to true only when changing the text cannot change behavior. The app already protects original database names, notetag names and plugin command arguments, so those occurrences are not listed.\n"
                "Give every listed occurrence a disposition, evidence and a reason. A file is done once its entry has examined true, file-level evidence and every listed occurrence decided. "
                "You may report some files, run the helper and continue with the request it returns for the rest.\n"
                "A plugin that loads its own JSON through an exact path literal listed in loaderLiterals can add that file under dependencies; a later request lists its text.\n"
                + (
                    "This is a recheck: each occurrence lists its earlier finding. Keep or correct each one, starting with anything the user reports as untranslated or broken in the game. Files left out of the report keep their findings; a file you report must decide all of its listed occurrences again.\n"
                    if recheck
                    else "A finding listed with an occurrence was left undecided earlier; settle it now.\n"
                    if any("finding" in item for _, items in scope for item in items)
                    else ""
                )
            )
        else:
            schema = {
                **identity_fields,
                "files": [
                    {
                        "path": "exact requested path",
                        "sourceHash": "request hash",
                        "candidateHash": "working copy SHA-256",
                        "evidence": "Japanese/English meaning and layout review performed",
                        "targets": {
                            "requested occurrence ID": "exact decoded English target"
                        },
                    }
                ],
            }
            sources = [
                "the glossary and guidance files in the request",
                *(
                    [
                        "the Translate stage's English output in "
                        + context["translated"]
                        + " (its Japanese sources are in the files folder beside it)"
                    ]
                    if context["translated"]
                    else []
                ),
                "text already applied to the game in " + str(game_data),
                *(["the reference games below"] if context["references"] else []),
            ]
            text += (
                "TRANSLATE. Translate the listed occurrences in each file's working copy (candidate); runtime files and frozen originals (original) are read-only. "
                "Their paths are relative to the game folder " + str(root) + ".\n"
                "Keep names and terms consistent with the game's established English: "
                + ", ".join(sources[:-1])
                + " and "
                + sources[-1]
                + ". Fit the space where the plugin draws the text.\n"
                'Change only the listed literal spans or decoded parameter paths. Preserve quote style, parameter keys, ordering, types and serialization depth, identifiers, interpolation and control codes; keep a leading tag that the file\'s code matches with startsWith or indexOf, such as ア: in line.startsWith("ア:"), exactly as written. '
                "Report every translated occurrence with its exact decoded target.\n"
                "The app rejects bytes outside the listed spans, unlisted decoded leaves and stale hashes, and syntax alone does not verify meaning. "
                "When a check fails, the helper returns a request for the files still needing work, with each failedCheck: repair the same working copies and report them under that request. "
                "Applying to the game is a separate review in the app; do not claim rendered fit without testing it.\n"
            )
        text += reference_folders.instructions(context["references"])
        text += (
            "\nReport schema:\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
            + "\n"
        )
        helper = Path(__file__).resolve().parents[3] / "scripts/project.py"
        arguments = [
            sys.executable,
            "-B",
            str(helper),
            "--workspace",
            str(self.translation.workspace),
            "--project",
            project_id,
            "plugins",
        ]

        def command(arguments):
            return (
                "& "
                + " ".join("'" + item.replace("'", "''") + "'" for item in arguments)
                if os.name == "nt"
                else shlex.join(arguments)
            )

        text += (
            "\nAfter saving the report, run:\n"
            + command([*arguments, "--continue-request", identity])
            + "\nIt checks the report and returns the next request with its instructions, or the final state. "
            "Working copies are prepared automatically, and runtime Apply stays in the app: this helper cannot approve or publish game files.\n"
            "If loopback access is sandboxed, use your normal permission flow and retry this read-only status command first:\n"
            + command(arguments)
            + "\nA lost response may follow a completed action. Read the activeRequest path from that status and follow its saved instructions; "
            "do not restart the task or blindly retry a step. Never expose the local connection token. "
            "If permitted access still fails, save your work and report the connection blocker.\n"
        )
        request["instructions"] = text
        value["activeRequest"] = identity
        write_json(request_path, request)
        # The assistant saves its report there.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        value["requests"][kind] = request
        write_json(
            Path(self.translation.workspace)
            / "plugin-contracts"
            / project_id
            / (identity + ".json"),
            {
                "projectId": project_id,
                "requestId": identity,
                "requestHash": digest(request),
            },
        )
        return {
            "text": text,
            "request": str(request_path),
            "requestId": identity,
            "stage": kind,
        }

    def continue_task(self, project_id, request_id):
        """Advance a copied task through reports and editable copies, never publication."""
        with self.lock:
            value = self.load(project_id)
            request = next(
                (
                    row
                    for row in value["requests"].values()
                    if row["requestId"] == value.get("activeRequest")
                ),
                None,
            )
            if not request or not request.get("automatic"):
                raise ValueError(
                    "Copy a plugin task in the app before continuing through the helper."
                )
            self.verify_request(project_id, request)
            if request_id != request["requestId"]:
                if request_id == request.get("previousRequestId"):
                    # A lost reply must not restart the next stage or replace edited copies.
                    return {
                        "text": request["instructions"],
                        "request": request["path"],
                        "requestId": request["requestId"],
                        "stage": request["kind"],
                        "state": self.state(project_id),
                    }
                raise ValueError(
                    "This plugin task was replaced. Read plugin status and use its active request."
                )
            self.translation.idle(project_id)
            self.translation.clean_drafts(project_id)
            self.refresh(project_id, value, request["kind"])
            problems = (
                value["editing"]["errors"] if request["kind"] == "translation" else []
            )
            # Retain accepted findings even if later preparation cannot finish.
            self.save(project_id, value)
            # Changed sources and newly found JSON need their text listed first.
            if any(row.get("stale") for row in value["files"].values()):
                self.scan(project_id, value)
            self.observe(project_id, value)
            result = self.advance(project_id, value, request)
            self.save(project_id, value)
            if result:
                left = (
                    self.investigation_scope(value)
                    if result["stage"] == "investigation"
                    else self.translation_scope(value)
                )
                result["message"] = (
                    f"{len(left)} {'file' if len(left) == 1 else 'files'} left to "
                    + (
                        "investigate"
                        if result["stage"] == "investigation"
                        else "translate"
                    )
                    + "."
                    + (" Failed checks: " + "; ".join(problems) if problems else "")
                )
            else:
                unreadable = [
                    path for path, row in value["files"].items() if row.get("issue")
                ]
                result = {
                    "stage": "complete",
                    "message": "Every plugin file is investigated and its player text translated. Applying to the game is reviewed in the app."
                    + (
                        " These files could not be read and were left unchanged: "
                        + ", ".join(unreadable)
                        if unreadable
                        else ""
                    ),
                }
            return {**result, "state": self.state(project_id)}

    def current_sources(self, project_id, value, rows):
        _, root = self.record(project_id)
        for row in rows:
            if not row["sourceHash"] and row.get("issue"):
                continue
            expected = (
                value["files"][row["path"]].get("applied", {}).get("afterHash")
                or row["sourceHash"]
            )
            if digest(self.source(root, row["path"])) != expected:
                raise ValueError(
                    "Source changed: "
                    + row["path"]
                    + ". Refresh investigation before editing or publication."
                )

    def current_originals(self, project_id, value):
        prefix = value["layout"].removesuffix("js/plugins.js")
        current = self.original_context(project_id, prefix)
        if (
            not value["originals"]
            or current["binding"] != value["originals"]["binding"]
        ):
            raise ValueError(
                "Original Japanese lookup evidence changed or is missing. Investigate again."
            )
        return current

    def same_scope(self, project_id, value, request, kind, scope):
        """Whether a request still asks exactly about `scope`, against the
        scanned sources, guidance and originals."""
        try:
            self.verify_request(project_id, request)
        except OSError, ValueError:
            return False
        _, root = self.record(project_id)
        shape = lambda rows: [
            (
                row["path"],
                row["sourceHash"],
                [item["id"] for item in row["occurrences"]],
            )
            for row in rows
        ]
        return (
            request["kind"] == kind
            and request["binding"] == value["binding"]
            and request["guidance"] == self.guidance(root)
            and request["originals"]
            == pick(value["originals"], ("backupId", "binding"))
            and request["layout"] == value["layout"]
            and shape(request["files"])
            == shape(
                {
                    "path": path,
                    "sourceHash": value["files"][path]["sourceHash"],
                    "occurrences": items,
                }
                for path, items in scope
            )
        )

    def saved_request(self, project_id, request_id):
        """A translation request this project issued, as the profile recorded it."""
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", request_id
        ):
            raise ValueError(
                "Saved results need the translation task that asked for them."
            )
        request = read_json(self.path(project_id, "requests/" + request_id + ".json"))
        self.verify_request(project_id, request)
        if request.get("kind") != "translation":
            raise ValueError(
                "Saved results need the translation task that asked for them."
            )
        return request

    def verify_request(self, project_id, request):
        authority = read_json(
            Path(self.translation.workspace)
            / "plugin-contracts"
            / project_id
            / (request["requestId"] + ".json")
        )
        if (
            authority
            != {
                "projectId": project_id,
                "requestId": request["requestId"],
                "requestHash": digest(request),
            }
            or read_json(request["path"]) != request
        ):
            raise ValueError("The scoped request changed. Copy and review a new task.")

    def runtime_allowlist(self, project_id, value, row):
        prefix, catalog, _ = self.inventory(project_id)
        if row["path"] in catalog:
            if row["kind"] != catalog[row["path"]]["kind"]:
                raise ValueError("The exact runtime file kind changed.")
            return
        dependency = row.get("dependency", {})
        source = dependency.get("sourceFile")
        literal = dependency.get("literalId")
        name = dependency.get("path")
        if row["kind"] != "json" or source not in catalog or not isinstance(name, str):
            raise ValueError("Runtime file is outside the exact plugin allowlist.")
        _, root = self.record(project_id)
        parsed = self.documents.parse(
            [
                {
                    "path": source,
                    "source": self.source(root, source).decode(),
                    "kind": catalog[source]["kind"],
                }
            ]
        )[source]
        possible = {
            digest(
                {
                    "file": source,
                    "span": [item["start"], item["end"]],
                    "value": item["value"],
                }
            )[:24]: item["value"]
            for item in parsed["literals"]
        }
        expected = prefix + name if prefix and not name.startswith(prefix) else name
        if possible.get(literal) != name or expected != row["path"]:
            raise ValueError("The exact plugin-loaded JSON dependency changed.")

    def copy_boundary(self, root, prepared):
        copy_root = prepared.get("copyRoot")
        if not copy_root:
            raise ValueError(
                "Working-copy scope is missing. Prepare a fresh owned copy."
            )
        directory = project_path(root, copy_root, exists=False)
        if not directory.is_dir():
            raise ValueError("Working-copy directory is missing.")
        expected = {prepared["original"], prepared["candidate"]}
        actual = set()
        for target in directory.rglob("*"):
            if target.is_symlink():
                raise ValueError("Working copies cannot contain symbolic links.")
            if target.is_file():
                actual.add(target.relative_to(root).as_posix())
        if actual != expected:
            raise ValueError(
                "New or missing files in the working-copy scope are not authorized."
            )

    def refresh(self, project_id, value, kind):
        request = value["requests"].get(kind)
        if not request:
            raise ValueError("Copy the scoped task before refreshing its saved report.")
        _, root = self.record(project_id)
        self.verify_request(project_id, request)
        if not Path(request["report"]).is_file():
            raise ValueError(
                "No saved "
                + kind
                + " report yet. Have your agent finish the copied task, then check again."
            )
        report = read_json(request["report"], limit=32_000_000)
        if not isinstance(report, dict) or any(
            report.get(key) != request[key]
            for key in ("version", "kind", "projectId", "requestId", "binding")
        ):
            raise ValueError(
                "Saved report is foreign, stale or belongs to another task. No findings were accepted."
            )
        if self.guidance(root) != request["guidance"]:
            raise ValueError(
                "Saved guidance changed. Copy a new scoped task before accepting results."
            )
        rows = report.get("files")
        allowed = {row["path"]: row for row in request["files"]}
        if (
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            or len({row.get("path") for row in rows}) != len(rows)
        ):
            raise ValueError("Report files must be unique exact entries.")
        if any(row.get("path") not in allowed for row in rows):
            raise ValueError("Report contains an out-of-scope file.")
        self.current_sources(project_id, value, request["files"])
        if kind == "translation":
            self.current_originals(project_id, value)
        accepted = 0
        errors = []
        # Work on a copy so malformed reports never partially mutate trusted findings.
        updated = deepcopy(value)
        for answer in rows:
            path = answer["path"]
            asked = allowed[path]
            row = updated["files"][path]
            if answer.get("sourceHash") != asked["sourceHash"]:
                raise ValueError("Report source hash does not match: " + path)
            if kind == "investigation":
                answers = answer.get("occurrences", [])
                known = {item["id"]: item for item in row["occurrences"]}
                questions = {item["id"] for item in asked["occurrences"]} & set(known)
                if not isinstance(answers, list) or len(
                    {item.get("id") for item in answers if isinstance(item, dict)}
                ) != len(answers):
                    raise ValueError("Occurrence findings must be unique entries.")
                # A report covering a file settles exactly what it answers; the
                # rest of its asked text cannot keep an earlier finding.
                for identity in questions:
                    known[identity].pop("finding", None)
                for item in answers:
                    if (
                        item.get("id") not in questions
                        or item.get("disposition") not in DISPOSITIONS
                        or type(item.get("safe")) is not bool
                    ):
                        raise ValueError("Unknown occurrence or invalid disposition.")
                    evidence = bounded(item.get("evidence", ""), "Finding evidence")
                    reason = bounded(item.get("reason", ""), "Finding reason")
                    if not evidence.strip() or not reason.strip():
                        raise ValueError(
                            "Every disposition needs concrete usage evidence and a reason."
                        )
                    target = known[item["id"]]
                    finding = deepcopy(item)
                    if target["protected"]:
                        finding.update(
                            disposition="protected",
                            safe=False,
                            reason="Protected original lookup value or code key. "
                            + reason,
                        )
                    elif target["latent"] and finding["disposition"] == "visible":
                        finding["disposition"] = "latent"
                    if not updated["originals"]:
                        finding["safe"] = False
                    target["finding"] = finding
                row["examined"] = answer.get("examined") is True and bool(
                    bounded(answer.get("evidence", ""), "File evidence").strip()
                )
                row["stale"] = False
                if self.row_status(updated, row) != "investigate":
                    accepted += 1
            else:
                prepared = row.get("prepared")
                if not prepared:
                    raise ValueError("This file has no owned working copy.")
                self.copy_boundary(root, prepared)
                candidate = self.source(root, prepared["candidate"])
                original = self.source(root, prepared["original"])
                if digest(original) != prepared["originalHash"]:
                    raise ValueError("Frozen original changed: " + path)
                if answer.get("candidateHash") != digest(candidate):
                    raise ValueError("Candidate hash does not match: " + path)
                targets = answer.get("targets")
                approved = asked["occurrences"]
                ids = {item["id"] for item in approved}
                if not isinstance(targets, dict) or set(targets) - ids:
                    raise ValueError("Results contain unapproved occurrence IDs.")
                evidence = bounded(
                    answer.get("evidence", ""), "Translation review evidence"
                )
                if not evidence.strip():
                    raise ValueError("Results need saved meaning/review evidence.")
                try:
                    parsed = self.documents.parse(
                        [
                            {
                                "path": "original/" + path,
                                "source": original.decode(),
                                "kind": row["kind"],
                            },
                            {
                                "path": "candidate/" + path,
                                "source": candidate.decode(),
                                "kind": row["kind"],
                            },
                        ]
                    )
                    checks = validate(
                        original,
                        candidate,
                        parsed["original/" + path],
                        parsed["candidate/" + path],
                        approved,
                        targets,
                    )
                    complete = set(targets) == ids
                    status = (
                        "ready"
                        if complete and candidate != original
                        else "partial"
                        if not complete
                        else "unchanged"
                    )
                    reason = (
                        ""
                        if status == "ready"
                        else "Awaiting remaining approved occurrences"
                        if status == "partial"
                        else "No changed text to publish"
                    )
                except (ValueError, UnicodeError) as exc:
                    status, reason, checks = "needs_revision", str(exc), {}
                row["result"] = {
                    "status": status,
                    "reason": reason,
                    "checks": checks,
                    "candidateHash": digest(candidate),
                    "targets": targets,
                    "evidence": evidence,
                    "requestId": request["requestId"],
                    "selection": sorted(ids),
                    "saved": now(),
                }
                if status in {"ready", "unchanged"}:
                    accepted += 1
                else:
                    errors.append(path + ": " + reason)
        if kind == "investigation":
            for dependency in report.get("dependencies", []):
                path = dependency.get("path")
                source = dependency.get("sourceFile")
                literal = dependency.get("literalId")
                if source not in allowed:
                    raise ValueError(
                        "JSON dependency loader must belong to this investigation."
                    )
                # Path literals generally contain no Japanese and are supplied separately below.
                parsed = self.documents.parse(
                    [
                        {
                            "path": source,
                            "source": self.source(root, source).decode(),
                            "kind": allowed[source]["kind"],
                        }
                    ]
                )[source]
                possible = {
                    digest(
                        {
                            "file": source,
                            "span": [item["start"], item["end"]],
                            "value": item["value"],
                        }
                    )[:24]: item["value"]
                    for item in parsed["literals"]
                }
                if (
                    literal not in possible
                    or possible[literal] != path
                    or not isinstance(path, str)
                    or not path.endswith(".json")
                ):
                    raise ValueError(
                        "Loaded JSON needs an exact static loader-path literal from the request."
                    )
                prefix = value["layout"].removesuffix("js/plugins.js")
                actual = (
                    prefix + path if prefix and not path.startswith(prefix) else path
                )
                if (
                    not actual.startswith(
                        (prefix + "data/", prefix + "img/", prefix + "js/")
                    )
                    or Path(actual).name in DATABASE_JSON
                    or re.fullmatch(r"Map\d+\.json", Path(actual).name)
                ):
                    raise ValueError(
                        "This JSON is outside the plugin-loaded runtime scope or belongs to an existing text phase."
                    )
                self.source(root, actual)
                if not bounded(
                    dependency.get("evidence", ""), "Loader evidence"
                ).strip():
                    raise ValueError("Loaded JSON needs concrete loader-use evidence.")
                updated["files"].setdefault(
                    actual,
                    {
                        "path": actual,
                        "plugin": updated["files"][source]["plugin"] + " data",
                        "kind": "json",
                        "enabled": allowed[source]["enabled"],
                        "dependency": dependency,
                        "sourceHash": digest(self.source(root, actual)),
                        "occurrences": [],
                        "issue": "",
                        "stale": True,
                    },
                )
        key = "findings" if kind == "investigation" else "editing"
        completed = (
            len(rows) == len(allowed)
            and not errors
            and (
                kind != "investigation"
                or all(
                    self.row_status(updated, row) != "investigate"
                    for row in updated["files"].values()
                )
            )
        )
        updated[key] = {
            "status": "current" if completed else "partial",
            "errors": errors,
            "accepted": accepted,
            "reported": len(rows),
            "expected": len(allowed),
            "saved": now(),
            "requestId": request["requestId"],
        }
        if kind == "investigation":
            updated["selection"] = self.chosen_text(updated)
        value.clear()
        value.update(updated)
        return {
            "accepted": accepted,
            "message": "Saved " + kind + " report checked.",
            "errors": errors,
        }

    def prepare(self, project_id, value):
        """Editable copies of every file with chosen text; runtime files stay unchanged."""
        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        eligible = self.eligible(value)
        selected = set(value["selection"])
        if not selected or selected - set(eligible):
            raise ValueError(
                "Choose current, safe investigated text before making working copies."
            )
        self.current_originals(project_id, value)
        _, root = self.record(project_id)
        rows = [
            row
            for row in value["files"].values()
            if any(item["id"] in selected for item in row["occurrences"])
        ]
        self.current_sources(project_id, value, rows)
        for row in rows:
            self.runtime_allowlist(project_id, value, row)
            if row.get("prepared"):
                prepared = row["prepared"]
                self.copy_boundary(root, prepared)
                if (
                    digest(self.source(root, prepared["original"]))
                    != prepared["originalHash"]
                ):
                    raise ValueError("Frozen original changed: " + row["path"])
                self.source(root, prepared["candidate"])
                continue
            identity = uuid.uuid4().hex
            base = WORK + "/copies/" + identity + "/" + row["path"]
            raw = self.source(root, row["path"])
            original = base + ".original"
            candidate = base
            write_bytes(project_path(root, original, exists=False), raw)
            write_bytes(project_path(root, candidate, exists=False), raw)
            row["prepared"] = {
                "original": original,
                "originalHash": digest(raw),
                "candidate": candidate,
                "copyRoot": WORK + "/copies/" + identity,
                "prepared": now(),
            }

    def checked_rows(self, project_id, value, mode, options):
        _, root = self.record(project_id)
        selected = set(value["selection"])
        included = []
        blocked = []
        receipt = None
        if mode == "restore":
            receipt = next(
                (
                    row
                    for row in value["receipts"]
                    if row["id"] == options.get("receipt")
                ),
                None,
            )
            if not receipt:
                raise ValueError("Choose a saved application receipt to restore.")
            publication = self.approved_publication(project_id, receipt["id"])
            approved = {row["path"]: row for row in publication["files"]}
            if (
                publication["mode"] != "apply"
                or receipt["mode"] != "apply"
                or receipt["manifest"] != publication["manifest"]
                or any(approved.get(row["path"]) != row for row in receipt["files"])
            ):
                raise ValueError(
                    "Restore receipt differs from its exact approved publication."
                )
            rows = [
                value["files"][item["path"]]
                for item in receipt["files"]
                if item["path"] in value["files"]
            ]
        else:
            # Files the game already carries are done, not left unchanged.
            rows = [
                row
                for row in value["files"].values()
                if any(item["id"] in selected for item in row["occurrences"])
                and self.row_status(value, row) != "applied"
            ]
            originals = self.current_originals(project_id, value)
        for row in rows:
            path = row["path"]
            reason = ""
            try:
                current = digest(self.source(root, path))
                if mode == "restore":
                    assert receipt is not None  # Restores require a receipt above.
                    saved = next(
                        item for item in receipt["files"] if item["path"] == path
                    )
                    if current != saved["afterHash"]:
                        raise ValueError(
                            "Runtime changed since this receipt; recover/compare it before restore."
                        )
                    output = self.source(root, saved["backup"])
                    after = digest(output)
                    if after != saved["beforeHash"]:
                        raise ValueError("Receipt backup changed.")
                    candidate = saved["backup"]
                    original_hash = saved["originalHash"]
                else:
                    result = row.get("result", {})
                    prepared = row.get("prepared", {})
                    self.runtime_allowlist(project_id, value, row)
                    self.copy_boundary(root, prepared)
                    expected = (
                        row.get("applied", {}).get("afterHash") or row["sourceHash"]
                    )
                    if current != expected:
                        raise ValueError(
                            "Runtime source changed; refresh investigation."
                        )
                    if result.get("status") != "ready":
                        raise ValueError(
                            result.get("reason")
                            or "Saved validated translation results are needed."
                        )
                    ids = sorted(
                        item["id"]
                        for item in row["occurrences"]
                        if item["id"] in selected
                    )
                    if result["selection"] != ids:
                        raise ValueError(
                            "Approved occurrence scope changed; copy a new translation task."
                        )
                    if (
                        digest(self.source(root, prepared["original"]))
                        != prepared["originalHash"]
                    ):
                        raise ValueError("Frozen original changed.")
                    output = self.source(root, prepared["candidate"])
                    after = digest(output)
                    if after != result["candidateHash"]:
                        raise ValueError("Working copy changed; refresh its checks.")
                    candidate = prepared["candidate"]
                    original_hash = prepared["originalHash"]
                    # Each result answers the request that asked for it.
                    request = self.saved_request(project_id, result["requestId"])
                    asked = next(
                        (item for item in request["files"] if item["path"] == path),
                        None,
                    )
                    if (
                        not asked
                        or sorted(item["id"] for item in asked["occurrences"]) != ids
                    ):
                        raise ValueError("The exact approved occurrence scope changed.")
                    original = self.source(root, prepared["original"])
                    parsed = self.documents.parse(
                        [
                            {
                                "path": "original/" + path,
                                "source": original.decode(),
                                "kind": row["kind"],
                            },
                            {
                                "path": "candidate/" + path,
                                "source": output.decode(),
                                "kind": row["kind"],
                            },
                        ]
                    )
                    actual = {
                        item["id"]: item
                        for item in occurrences(
                            path, original, parsed["original/" + path]
                        )
                    }
                    lookup_keys = set(
                        originals["structuralKeys"]
                        if row["kind"] == "parameters"
                        else originals["keys"]
                    )
                    code_keys = {
                        item["value"]
                        for item in parsed["original/" + path]["literals"]
                        if item["protected"]
                    }
                    for occurrence in asked["occurrences"]:
                        checked = actual.get(occurrence["id"])
                        if not checked or any(
                            checked[key] != occurrence[key]
                            for key in ("value", "token", "logical", "start", "end")
                        ):
                            raise ValueError(
                                "Approved literal identity no longer matches its frozen bytes."
                            )
                        if (
                            checked["protected"]
                            or checked["value"] in lookup_keys
                            or checked["value"] in code_keys
                        ):
                            raise ValueError(
                                "Protected original lookup or code value cannot be published."
                            )
                    validate(
                        original,
                        output,
                        parsed["original/" + path],
                        parsed["candidate/" + path],
                        asked["occurrences"],
                        result["targets"],
                    )
                if current == after:
                    raise ValueError("Runtime already matches this output.")
                included.append(
                    {
                        "path": path,
                        "destination": path,
                        "beforeHash": current,
                        "afterHash": after,
                        "originalHash": original_hash,
                        "candidate": candidate,
                        "candidateHash": after,
                        "backup": WORK + "/backups/" + uuid.uuid4().hex + "/" + path,
                        "kind": row["kind"],
                        "changes": len(row.get("result", {}).get("targets", {})),
                    }
                )
            except (ValueError, OSError) as exc:
                reason = str(exc)
            if reason:
                blocked.append({"path": path, "reason": reason})
        return included, blocked

    def preview(self, project_id, value, mode, options):
        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        included, blocked = self.checked_rows(project_id, value, mode, options)
        token = uuid.uuid4().hex
        prior_manifest = lifecycle(self.translation.workspace, project_id).get(
            "runtime_manifest"
        )
        _, root = self.record(project_id)
        prior_hash = digest(self.source(root, prior_manifest)) if prior_manifest else ""
        preview = {
            "token": token,
            "mode": mode,
            "projectId": project_id,
            "files": included,
            "blocked": blocked,
            "created": now(),
            "priorManifest": prior_manifest,
            "priorManifestHash": prior_hash,
            "selection": value["selection"],
            "receipt": options.get("receipt", ""),
            "originalBinding": value["originals"].get("binding", ""),
            "manifest": WORK + "/publications/" + token + "/runtime-manifest.json",
        }
        self.previews[token] = deepcopy(preview)
        return preview

    def _publish_file(self, root, path, raw):
        target = project_path(root, path)
        mode = target.stat().st_mode & 0o777
        write_bytes(target, raw)
        target.chmod(mode)

    def publication_manifest(self, project_id, rows):
        _, root = self.record(project_id)
        state = lifecycle(self.translation.workspace, project_id)
        prior = state.get("runtime_manifest")
        document = (
            read_json(project_path(root, prior))
            if prior
            else {"version": 1, "files": {}}
        )
        files = document.get("files")
        if isinstance(files, list):
            files = {name: {} for name in files}
        if not isinstance(files, dict):
            raise ValueError("The reviewed runtime manifest is malformed.")
        files = deepcopy(files)
        for row in rows:
            files[row["path"]] = {
                **files.get(row["path"], {}),
                "sha256": row["afterHash"],
                "original_sha256": row["originalHash"],
            }
        return {**document, "files": files}

    def publish(self, project_id, value, mode, options):
        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        token = options.get("token")
        preview = self.previews.pop(token, None)
        if not preview or preview["projectId"] != project_id or preview["mode"] != mode:
            raise ValueError("This publication review expired or was already used.")
        if datetime.fromisoformat(preview["created"]) < datetime.now(UTC) - timedelta(
            minutes=20
        ):
            raise ValueError(
                "This publication review expired. Review the exact current batch again."
            )
        if not preview["files"]:
            raise ValueError("The reviewed batch is empty. Nothing was published.")
        if preview["selection"] != value["selection"]:
            raise ValueError("Selection changed after review.")
        included, _blocked = self.checked_rows(
            project_id, value, mode, {"receipt": preview["receipt"]}
        )
        keys = (
            "path",
            "destination",
            "beforeHash",
            "afterHash",
            "originalHash",
            "candidate",
            "candidateHash",
        )
        if [{key: row[key] for key in keys} for row in included] != [
            {key: row[key] for key in keys} for row in preview["files"]
        ]:
            raise ValueError(
                "Source, scope, candidate or original changed after review. Review the exact batch again."
            )
        _, root = self.record(project_id)
        publication = deepcopy(preview)
        publication["id"] = token
        prior_manifest = lifecycle(self.translation.workspace, project_id).get(
            "runtime_manifest"
        )
        prior_hash = digest(self.source(root, prior_manifest)) if prior_manifest else ""
        if (
            prior_manifest != preview["priorManifest"]
            or prior_hash != preview["priorManifestHash"]
        ):
            raise ValueError(
                "The reviewed runtime manifest changed. Review publication again."
            )
        frozen = []
        for row in publication["files"]:
            raw = self.source(root, row["path"])
            candidate = self.source(root, row["candidate"])
            if (
                digest(raw) != row["beforeHash"]
                or digest(candidate) != row["afterHash"]
            ):
                raise ValueError("Files changed during whole-batch preflight.")
            write_bytes(project_path(root, row["backup"], exists=False), raw)
            name = WORK + "/publications/" + token + "/output/" + row["path"]
            write_bytes(project_path(root, name, exists=False), candidate)
            row["frozen"] = name
            frozen.append((row, candidate, raw))
        manifest = self.publication_manifest(project_id, publication["files"])
        write_json(project_path(root, preview["manifest"], exists=False), manifest)
        journal = self.path(project_id, "publications/" + token + "/approval.json")
        write_json(journal, publication)
        authority = (
            Path(self.translation.workspace)
            / "plugin-approvals"
            / project_id
            / (token + ".json")
        )
        write_json(
            authority,
            {"journalHash": digest(publication), "projectId": project_id, "id": token},
        )
        value["pending"].append(token)
        self.save(project_id, value)
        written = []
        failure = ""
        conflicts = []
        try:
            for row, candidate, raw in frozen:
                if digest(self.source(root, row["path"])) != row["beforeHash"]:
                    raise ValueError(
                        "Runtime changed during publication: " + row["path"]
                    )
                written.append((row, raw))
                self._publish_file(root, row["path"], candidate)
        except Exception as exc:  # noqa: BLE001
            failure = str(exc)
            for row, raw in reversed(written):
                try:
                    current = digest(self.source(root, row["path"]))
                    if current == row["beforeHash"]:
                        continue
                    if current != row["afterHash"]:
                        raise ValueError(
                            "File changed after publication; rollback left it untouched."
                        )
                    self._publish_file(root, row["path"], raw)
                except Exception as rollback:  # noqa: BLE001
                    conflicts.append(row["path"] + ": " + str(rollback))
        completed = [
            row
            for row, _, _ in frozen
            if digest(self.source(root, row["path"])) == row["afterHash"]
        ]
        receipt = {
            "id": token,
            "mode": mode,
            "saved": now(),
            "status": "complete"
            if not failure
            else "partial"
            if completed
            else "rolled_back",
            "files": completed,
            "reviewedFiles": publication["files"],
            "manifest": preview["manifest"],
            "failure": failure,
            "conflicts": conflicts,
        }
        self.finish(project_id, value, receipt)
        if failure:
            raise ValueError(
                "Publication failed; rollback attempted. "
                + failure
                + (" Recovery conflicts: " + "; ".join(conflicts) if conflicts else "")
            )
        return {
            "receipt": receipt_view(receipt, value["files"]),
            "state": self.state(project_id),
            "completed": len(completed),
        }

    def finish(self, project_id, value, receipt):
        _, root = self.record(project_id)
        for row in receipt["files"]:
            item = value["files"][row["path"]]
            if receipt["mode"] == "apply":
                item["applied"] = {
                    "receipt": receipt["id"],
                    "afterHash": row["afterHash"],
                }
            else:
                item.pop("applied", None)
        if receipt["files"]:
            # The exact paths feed the existing runtime manifest owner, including plugin-loaded JSON.
            state = lifecycle(self.translation.workspace, project_id)
            state["runtime_manifest"] = receipt["manifest"]
            if receipt["status"] != "complete":
                write_json(
                    project_path(root, receipt["manifest"], exists=False),
                    self.publication_manifest(project_id, receipt["files"]),
                )
            write_json(lifecycle_path(self.translation.workspace, project_id), state)
        value["receipts"].append(receipt)
        value["pending"] = [
            identity for identity in value["pending"] if identity != receipt["id"]
        ]
        self.save(project_id, value)

    def approved_publication(self, project_id, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("Malformed publication journal identity.")
        publication = read_json(
            self.path(project_id, "publications/" + identity + "/approval.json")
        )
        authority = read_json(
            Path(self.translation.workspace)
            / "plugin-approvals"
            / project_id
            / (identity + ".json")
        )
        if authority != {
            "journalHash": digest(publication),
            "projectId": project_id,
            "id": identity,
        }:
            raise ValueError(
                "Publication approval journal changed. No recovery receipt was manufactured."
            )
        return publication

    def recover(self, project_id, value):
        if not value["pending"]:
            return
        _, root = self.record(project_id)
        for identity in list(value["pending"]):
            publication = self.approved_publication(project_id, identity)
            completed, conflicts = [], []
            for row in publication["files"]:
                try:
                    if (
                        digest(self.source(root, row["backup"])) != row["beforeHash"]
                        or digest(self.source(root, row["frozen"])) != row["afterHash"]
                    ):
                        raise ValueError("Frozen publication/backup bytes changed")
                    current = digest(self.source(root, row["path"]))
                    if current == row["afterHash"]:
                        completed.append(row)
                    elif current != row["beforeHash"]:
                        conflicts.append(
                            row["path"]
                            + ": runtime differs from approved before/after bytes"
                        )
                except (ValueError, OSError) as exc:
                    conflicts.append(row["path"] + ": " + str(exc))
            receipt = {
                "id": identity,
                "mode": publication["mode"],
                "saved": now(),
                "status": "recovered" if not conflicts else "conflict",
                "files": completed,
                "reviewedFiles": publication["files"],
                "manifest": publication["manifest"],
                "failure": "Interrupted publication reconciled from exact approved bytes; review recovery.",
                "conflicts": conflicts,
            }
            self.finish(project_id, value, receipt)
