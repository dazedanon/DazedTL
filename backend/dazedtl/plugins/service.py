"""Retained assistant investigation, exact text edits and checked runtime publication."""

import json
import re
import threading
import uuid
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from dazedtl import foreign_work, freshness
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.languages import active_source, game_source, pair_note
from dazedtl.settings import language_pair
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import originals as game_originals
from dazedtl.translation import reference_folders
from dazedtl.translation.checkpoint_records import undoes
from dazedtl.translation.files import decode_json, digest, project_path, read_json
from dazedtl.translation.helper_command import helper_command, windows_note
from dazedtl.translation.operations import lifecycle, lifecycle_path

from . import ruby
from .documents import (
    Documents,
    decode,
    draws,
    leaves,
    occurrence_id,
    occurrences,
    read_leaf,
    reason,
    redrawn,
    validate,
)

WORK = ".dazedtl/plugin-work"
# Bump when scanning finds different files, text or problems, so saved scans
# are read again once.
SCAN_RULES = 2
# What the assistant can settle for one occurrence. Reports saved before every
# occurrence needed a decision may still say "unresolved"; that text stays
# with the assistant.
DECIDED = {"visible", "latent", "protected", "editor_only", "non_visible"}
DISPOSITIONS = DECIDED | {"unresolved"}
# Decisions that keep an occurrence's Japanese: a key or name the plugin
# compares, and text players never read.
KEPT = DECIDED - {"visible"}
# File states with nothing left to apply: the game holds the translation, or
# the file has nothing to translate.
SETTLED = {"applied", "translated", "none"}
# Where a VX Ace game's Ruby scripts are, one file per script: Set up
# extracts them from Data/Scripts.rvdata2 and applying packs them back.
ACE_SCRIPTS = "ace_json/scripts"
# Database files whose names the game looks up.
DATABASE = {
    "Actors",
    "Classes",
    "Skills",
    "Items",
    "Weapons",
    "Armors",
    "Enemies",
    "States",
}
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


def nested_keys(value, keys):
    """Every string and object key of a value, through each JSON layer."""
    if isinstance(value, str):
        keys.add(value)
        try:
            inner = decode(value)
        except ValueError:
            return
        if isinstance(inner, (dict, list, str)):
            nested_keys(inner, keys)
    elif isinstance(value, dict):
        keys.update(value)
        for inner in value.values():
            nested_keys(inner, keys)
    elif isinstance(value, list):
        for inner in value:
            nested_keys(inner, keys)


def data_keys(value, database, keys):
    """Text the game's data looks up: note tag names, the names of a
    `database` file's entries and MV/MZ plugin command words."""
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
                nested_keys(item, keys)
        for item in value.values():
            data_keys(item, database, keys)
    elif isinstance(value, list):
        for item in value:
            data_keys(item, database, keys)


def event_script_keys(value, keys):
    """Strings VX Ace event scripts compare or use as keys: a script that
    shows the same text has to keep it for the event to match it. Script
    calls are code 355 with 655 lines; a conditional branch (111) of type 12
    holds one line."""
    if isinstance(value, dict):
        for item in value.values():
            event_script_keys(item, keys)
        return
    if not isinstance(value, list):
        return
    scripts, lines = [], None
    for item in value:
        code = item.get("code") if isinstance(item, dict) else None
        parameters = item.get("parameters") if isinstance(item, dict) else None
        text = parameters[0] if isinstance(parameters, list) and parameters else None
        if code == 655 and lines is not None and isinstance(text, str):
            lines.append(text)
            continue
        lines = [text] if code == 355 and isinstance(text, str) else None
        if lines is not None:
            scripts.append(lines)
        if (
            code == 111
            and isinstance(parameters, list)
            and len(parameters) > 1
            and parameters[0] == 12
            and isinstance(parameters[1], str)
        ):
            scripts.append([parameters[1]])
        event_script_keys(item, keys)
    for lines in scripts:
        keys.update(
            literal["value"]
            for literal in ruby.parse("", "\n".join(lines))["literals"]
            if literal["protected"]
        )


def prefix_of(layout):
    """The game's web folder for MV/MZ, or the root for VX Ace."""
    return (
        layout.removesuffix("js/plugins.js") if layout.endswith("js/plugins.js") else ""
    )


def bounded(value, label, limit=4000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(label + " must be bounded text.")
    return value


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def undecided(item):
    """Text only the assistant can settle; the app protects lookup keys itself.
    Text kept in Japanese that the playtest saw drawn is decided again, once,
    with that evidence."""
    finding = item.get("finding", {})
    return not item["protected"] and (
        finding.get("disposition") not in DECIDED
        or bool(
            item.get("seen")
            and finding.get("disposition") in KEPT
            and not finding.get("seen")
        )
    )


# Each game's kept settings while its plugin state and the file that state
# describes are unchanged: Text QA asks on every poll.
_KEPT = {}


def _signature(path):
    return freshness.signature(path.stat())


def kept_settings(root):
    """Plugin settings whose Japanese Plugin files keeps on purpose, each as
    its plugin, parameter path and value: lookup keys the app protects and
    text the assistant decided players never read.

    Its findings count while js/plugins.js is the file it scanned or applied,
    or once the file is settled, since Plugin files keeps a settled file's
    findings through later edits; the value says which text each finding was
    about. Work another project saved counts too, as it describes the same
    text. A setting another entry of the same plugin leaves open stays out.
    """
    try:
        path = project_path(root, WORK + "/state.json")
        signature = _signature(path)
        cached = _KEPT.get(path)
        if (
            cached
            and cached[0] == signature
            and (cached[1] is None or _signature(cached[1]) == cached[2])
        ):
            return list(cached[3])
        value = read_json(path, limit=64_000_000)
    except OSError, ValueError:
        return []
    if not str(value.get("layout", "")).endswith("js/plugins.js"):
        # VX Ace scripts have no settings.
        return []
    layout, saved, kept = None, None, []
    try:
        layout = project_path(root, value["layout"])
        saved = _signature(layout)
        kept = _kept(value, digest(layout.read_bytes()))
    except OSError:
        return []
    except ValueError, KeyError, TypeError, AttributeError:
        # Plugin files has not found the plugin list yet, or another app
        # version saved state it can't read.
        layout = None
    _KEPT[path] = (signature, layout, saved, kept)
    return list(kept)


def _kept(value, current):
    row = value["files"][value["layout"]]
    if row.get("issue") or (
        current not in {row["sourceHash"], row.get("applied", {}).get("afterHash")}
        and PluginService.row_status(value, row) not in SETTLED
    ):
        return []
    kept, open_ = set(), set()
    for item in row["occurrences"]:
        if "parameterPath" not in item:
            continue
        setting = (
            item["plugin"],
            (
                *item["parameterPath"],
                *(part for part in item["logical"] if part != "$decode"),
            ),
            item["value"],
        )
        if _keeps(item):
            kept.add(setting)
        else:
            open_.add(setting)
    return [
        {"plugin": plugin, "path": list(path), "value": text}
        for plugin, path, text in sorted(kept - open_, key=repr)
    ]


def kept_literals(root):
    """Strings in plugin code whose Japanese Plugin files keeps on purpose,
    each as its file, line, kind and value: lookup keys and text the
    assistant decided players never read, which the playtest need not report
    again unless it sees them drawn.

    A file's findings count while it is the file Plugin files scanned or
    applied, or once it is settled, as for kept_settings; a string another
    finding of the same text on its line leaves open stays out."""
    try:
        value = read_json(project_path(root, WORK + "/state.json"), limit=64_000_000)
        files = value["files"]
    except OSError, ValueError, KeyError, TypeError:
        return []
    found = []
    for name, row in sorted(files.items()):
        if name == value.get("layout") or row.get("issue"):
            continue
        try:
            current = digest(project_path(root, name).read_bytes())
            if (
                current
                not in {row["sourceHash"], row.get("applied", {}).get("afterHash")}
                and PluginService.row_status(value, row) not in SETTLED
            ):
                continue
            kept, open_ = set(), set()
            for item in row["occurrences"]:
                literal = (item["line"], item["kind"], item["value"])
                (open_ if undecided(item) or not _keeps(item) else kept).add(literal)
        except OSError, ValueError, KeyError, TypeError, AttributeError:
            # The file is gone, or another app version saved state it can't
            # read.
            continue
        found += [
            {"file": name, "line": line, "kind": kind, "value": text}
            for line, kind, text in sorted(kept - open_, key=repr)
        ]
    return found


def _keeps(item):
    return item["protected"] or item.get("finding", {}).get("disposition") in KEPT


def no_context(_project_id):
    return {"translated": "", "references": []}


def no_labels(_project_id):
    return {"task": "", "labels": []}


def no_capture(_project_id, _plan):
    raise ValueError("DazedTL can't capture this game's screens.")


def no_captured(_project_id):
    return None


def no_seen(_project_id):
    return {"report": "", "texts": []}


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


# The checkpoint an application makes, as the project's activity names it.
APPLY_SUMMARY = "Apply plugin file changes"


def receipt_label(receipt):
    """An application or restore as the project's activity names it."""
    return APPLY_SUMMARY if receipt.get("mode") == "apply" else "Restore plugin files"


def receipt_view(receipt, files, issue=""):
    restorable = (
        carries(files, receipt)
        and not receipt.get("restoreIssue")
        and (undoes(receipt) or all("backup" in row for row in receipt["files"]))
    )
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
                "restores",
                "applies",
            ),
        ),
        **({"restoreIssue": issue} if issue and restorable else {}),
        "files": [pick(row, REVIEW_KEYS) for row in receipt["files"]],
        # Only the application a file still carries can restore it.
        "restorable": restorable and not issue,
        "undo": undoes(receipt),
    }


def publication_manifest(workspace, project_id, root, rows):
    """The runtime manifest with `rows`' files as an application or restore
    leaves them."""
    state = lifecycle(workspace, project_id)
    prior = state.get("runtime_manifest")
    document = (
        read_json(project_path(root, prior)) if prior else {"version": 1, "files": {}}
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


def finish(workspace, project_id, root, value, receipt):
    """Records a finished application or restore in `value`: what each file
    carries and the runtime manifest."""
    for row in receipt["files"]:
        item = value["files"][row["path"]]
        if receipt["mode"] == "apply":
            item["applied"] = {"receipt": receipt["id"], "afterHash": row["afterHash"]}
        else:
            item.pop("applied", None)
    if receipt["files"]:
        # The exact paths feed the existing runtime manifest owner, including plugin-loaded JSON.
        state = lifecycle(workspace, project_id)
        state["runtime_manifest"] = receipt["manifest"]
        if receipt["status"] != "complete":
            write_json(
                project_path(root, receipt["manifest"], exists=False),
                publication_manifest(workspace, project_id, root, receipt["files"]),
            )
        write_json(lifecycle_path(workspace, project_id), state)
    value["receipts"].append(receipt)
    value["pending"] = [
        identity for identity in value["pending"] if identity != receipt["id"]
    ]


def _followed(workspace, project_id, root, value, rows, commit, **names):
    """A receipt for the files of `rows` that checkpoint `commit` changed,
    each row naming its hash before, recorded in `value`: `restores` names
    the application it took out, or `applies` the one it brought back."""
    token = uuid.uuid4().hex
    rows = [
        {
            **row,
            "afterHash": digest(target.read_bytes())
            if (target := project_path(root, row["path"], exists=False)).is_file()
            else "",
        }
        for row in rows
    ]
    receipt = {
        "id": token,
        "mode": "apply" if "applies" in names else "restore",
        "saved": now(),
        "status": "complete",
        "files": rows,
        "reviewedFiles": rows,
        "manifest": WORK + "/publications/" + token + "/runtime-manifest.json",
        "failure": "",
        "conflicts": [],
        "commit": commit,
        **names,
    }
    write_json(
        project_path(root, receipt["manifest"], exists=False),
        publication_manifest(workspace, project_id, root, rows),
    )
    finish(workspace, project_id, root, value, receipt)
    return receipt


def take_out(workspace, project_id, root, value, application, commit):
    """Records an application taken out of the game by checkpoint `commit`."""
    return _followed(
        workspace,
        project_id,
        root,
        value,
        [{**row, "beforeHash": row["afterHash"]} for row in application["files"]],
        commit,
        restores=application["id"],
    )


def _origin(receipt):
    """The application a receipt carries: its own, or the one it brought
    back."""
    return receipt.get("applies", receipt["id"])


def follow(workspace, project_id, root, undone, commit):
    """Takes out each application still in the game whose checkpoint is among
    `undone`, newest first, and brings back each one a restore among them
    took out, as made by checkpoint `commit`. Only the outcome is recorded,
    one receipt for each application it changed, however many of its
    checkpoints were undone; one brought back carries a receipt of its own,
    which Recovery undoes."""
    path = project_path(root, WORK + "/state.json", exists=False)
    if not path.is_file():
        return
    value = read_json(path, limit=64_000_000)
    if not foreign_work.owned(value, project_id):
        return
    receipts = {row["id"]: row for row in value["receipts"]}
    files = value["files"]
    held = {
        name: (item.get("applied") or {}).get("receipt") for name, item in files.items()
    }

    def carriers():
        """Each application in the game and the receipt carrying it."""
        found = {}
        for identity in held.values():
            if identity in receipts:
                found[_origin(receipts[identity])] = identity
        return found

    before = carriers()
    for taken in undone:
        for receipt in reversed(value["receipts"]):
            if receipt.get("commit") != taken:
                continue
            if receipt["mode"] == "apply":
                origin = _origin(receipt)
                for name, identity in held.items():
                    if identity in receipts and _origin(receipts[identity]) == origin:
                        held[name] = None
                continue
            restored = receipts.get(receipt.get("restores", ""))
            # Files the task no longer lists keep no record to follow.
            if (
                restored
                and restored["mode"] == "apply"
                and all(row["path"] in files for row in restored["files"])
                and not any(held[row["path"]] for row in restored["files"])
            ):
                for row in restored["files"]:
                    held[row["path"]] = restored["id"]
    after = carriers()
    for origin in before.keys() - after.keys():
        take_out(workspace, project_id, root, value, receipts[before[origin]], commit)
    for origin in after.keys() - before.keys():
        _followed(
            workspace,
            project_id,
            root,
            value,
            receipts[after[origin]]["files"],
            commit,
            applies=origin,
        )
    if before.keys() != after.keys():
        write_json(path, value)


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


def web_prefix(root):
    """Where the game's web folder, which holds js/plugins.js, is in it."""
    matches = [
        prefix
        for prefix in ("www/", "")
        if (Path(root) / (prefix + "js/plugins.js")).is_file()
    ]
    if len(matches) != 1:
        raise ValueError(
            "Choose a game with one unambiguous js/plugins.js or www/js/plugins.js."
        )
    return matches[0]


class PluginService:
    def __init__(
        self,
        projects,
        translation,
        backend,
        *,
        documents=None,
        context=no_context,
        labels=no_labels,
        capture=no_capture,
        captured=no_captured,
        seen=no_seen,
    ):
        self.projects, self.translation, self.backend = projects, translation, backend
        self.documents = documents or Documents()
        # Where the game's established English lives beyond its guidance files:
        # the translated text folder and the reference games.
        self.context = context
        # Labels Text QA's latest capture found too long for the screen that
        # it holds no line of, which this task shortens.
        self.labels = labels
        # Starts a capture of those labels' screens with the shortening
        # copies served in place of the game's files, and reads the latest.
        self.capture_labels, self.captured = capture, captured
        # Japanese the latest release playtest saw a plugin draw.
        self.seen = seen
        self.lock = threading.RLock()
        self.previews, self.cache, self.foreign = {}, {}, {}
        self.digests = freshness.Digests()
        self.located = {}
        # A VX Ace original's lookup keys by the files they come from;
        # reading them decodes the game's whole database.
        self.ace_keys = {}
        # Each VX Ace game's script order, while its Scripts data is unchanged.
        self.script_order = {}
        # The app's own folders, which a game must stay apart from; resolving
        # a path costs a file open on Windows, and every plugin call checks.
        self.protected = [
            Path(path).resolve()
            for path in (self.translation.workspace, self.backend.source)
        ]

    def record(self, project_id):
        project = self.projects.get(project_id)
        root = Path(project["source"]).resolve(strict=True)
        for path in self.protected:
            if root.is_relative_to(path) or path.is_relative_to(root):
                raise ValueError(
                    "Plugin work needs a game separate from the app and profile."
                )
        return project, root

    def path(self, project_id, name):
        return project_path(self.record(project_id)[1], WORK + "/" + name, exists=False)

    def report_path(self, project_id, request_id):
        """Where a request's report is saved, in the game where it is now; a
        request names the folder the game was in when it was copied."""
        return self.path(project_id, "reports/" + request_id + ".json")

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
            if not carries(value["files"], receipt) or not (
                undoes(receipt) or all("backup" in row for row in receipt["files"])
            ):
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
                        "backup" in row
                        and digest(self.source(root, row["backup"]))
                        != row["beforeHash"]
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
                        "Its saved record no longer matches the files it applied, so it can't be restored here. The Project page's Checkpoints can undo it."
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
            return "", self.ace_scripts(root), {"plugins": []}
        if project["engine"] != "MVMZ":
            raise ValueError(
                "Plugin files works with RPG Maker MV, MZ and VX Ace games."
            )
        prefix = web_prefix(root)
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
        # The game loads the first enabled entry of a plugin and skips later
        # ones, such as an empty divider plugin listed many times. MZ compares
        # file names, so Author/Plugin and Other/Plugin are one plugin there.
        mz = (root / (prefix + "js/rmmz_core.js")).is_file()
        loaded, statuses = set(), {}
        for entry in parsed["plugins"]:
            if (
                not isinstance(entry, dict)
                or type(entry.get("status")) is not bool
                or not isinstance(entry.get("parameters"), dict)
            ):
                raise ValueError(
                    "Every plugin entry needs a static name, status and parameter object."
                )
            name = safe_name(entry.get("name"))
            key = name.rsplit("/", 1)[-1] if mz else name
            entry["loads"] = entry["status"] and key not in loaded
            if entry["loads"]:
                loaded.add(key)
            statuses[name] = statuses.get(name, False) or entry["loads"]
        for name, enabled in statuses.items():
            path = prefix + "js/plugins/" + name + ".js"
            # A listed plugin whose file is gone has no text to translate.
            if (root / path).exists():
                rows[path] = {
                    "path": path,
                    "kind": "source",
                    "plugin": name,
                    "enabled": enabled,
                }
        from util.playtest.fixes import NAME as FIXES

        for path in sorted((root / (prefix + "js/plugins")).glob("*.js")):
            # The playtest's fixes are DazedTL's own code, never game text.
            if path.stem == FIXES:
                continue
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

    def ace_scripts(self, root):
        """A VX Ace game's scripts in the order RGSS3 runs them, each named as
        in the script editor and with its place in that order, since a later
        script can redefine an earlier one's methods. RGSS3 runs every one,
        so all are enabled."""
        folder = Path(root) / ACE_SCRIPTS
        if not folder.is_dir():
            # Without it the task would find no text and read done.
            raise ValueError(
                "The game's scripts are not extracted yet. Run Convert Ace data in Set up first."
            )
        data = Path(root) / "Data"
        try:
            signature = (data / "Scripts.rvdata2").stat()
            signature = signature.st_mtime_ns, signature.st_size
        except OSError:
            signature = None
        saved = self.script_order.get(str(root))
        if not saved or saved[0] != signature:
            saved = (signature, self.translation.engine.ace_script_order(root))
            self.script_order[str(root)] = saved
        order = {name: index for index, name in enumerate(saved[1], 1)}
        rows = {}
        for path in sorted(
            folder.glob("*.rb"), key=lambda path: (order.get(path.name, 1e9), path.name)
        ):
            relative = path.relative_to(root).as_posix()
            rows[relative] = {
                "path": relative,
                "kind": "ruby",
                "plugin": path.stem.partition("_")[2] or path.stem,
                "enabled": True,
                **({"order": order[path.name]} if path.name in order else {}),
            }
        return rows

    def original_context(self, project_id, prefix):
        project, root = self.record(project_id)
        if project["engine"] == "ACE":
            return self.ace_original_context(project_id)
        original = game_originals.require(self.translation.workspace, project_id, root)
        names = [
            name
            for name in original.files
            if name.startswith(prefix + "data/") and name.endswith(".json")
        ]
        if not names or prefix + "js/plugins.js" not in original.files:
            raise ValueError(
                "The preserved original lacks the game's database or plugin configuration. Recover the matching original source before editing."
            )
        keys, hashes = set(), {name: original.files[name] for name in names}
        with original.materialized([*names, prefix + "js/plugins.js"]) as folder:
            for name in names:
                data_keys(
                    read_json(folder / name),
                    Path(name).name.removesuffix(".json") in DATABASE,
                    keys,
                )
            raw = (folder / (prefix + "js/plugins.js")).read_bytes()
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
                nested_keys(entry["parameters"], keys)
        hashes[prefix + "js/plugins.js"] = original.files[prefix + "js/plugins.js"]
        return {
            # Saved scans and requests name the original by this key.
            "backupId": original.id,
            "hashes": hashes,
            "keys": sorted(keys),
            "structuralKeys": structural_keys,
            "binding": digest(hashes),
        }

    def ace_original_context(self, project_id):
        """A VX Ace game's original lookup keys: its database names, note tag
        names and the strings its event scripts compare, from the preserved
        original's RGSS archive or, for a game that came unencrypted, its
        Data files. RGSS3 reads only the archive while one exists."""
        _, root = self.record(project_id)
        original = game_originals.require(self.translation.workspace, project_id, root)
        files = original.files
        archives = [
            name
            for name in files
            if "/" not in name
            and name.casefold().endswith((".rgss3a", ".rgss2a", ".rgssad"))
        ]
        names = archives[:1] or [
            name
            for name in files
            if name.casefold().startswith("data/")
            and name.casefold().endswith(".rvdata2")
            and name.casefold() != "data/scripts.rvdata2"
        ]
        missing = ValueError(
            "The preserved original lacks the game's database. Recover the matching original source before editing."
        )
        if not names:
            raise missing
        hashes = {name: files[name] for name in names}
        binding = digest(hashes)
        keys = self.ace_keys.get(binding)
        if keys is None:
            with original.materialized(names) as folder:
                data = self.translation.engine.ace_data(folder, names)
            if not data:
                raise missing
            found = set()
            for name, value in data.items():
                data_keys(value, PurePosixPath(name).stem in DATABASE, found)
                event_script_keys(value, found)
            keys = self.ace_keys[binding] = sorted(found)
        return {
            "backupId": original.id,
            "hashes": hashes,
            "keys": keys,
            "structuralKeys": [],
            "binding": binding,
        }

    def scan(self, project_id, value):
        project, root = self.record(project_id)
        prefix, rows, config = self.inventory(project_id)
        language = game_source(root)
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
                    occurrences(path, raw_files[path], parsed[path], language=language)
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
                if isinstance(item["value"], str)
                and item["value"].endswith(".json")
                # RGSS3 loads no JSON.
                and row["kind"] != "ruby"
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
                            enabled=entry["loads"],
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
                for key in (
                    "prepared",
                    "result",
                    "applied",
                    "examined",
                    "fit",
                    "fitting",
                ):
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
            layout=ACE_SCRIPTS
            if project["engine"] == "ACE"
            else prefix + "js/plugins.js",
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
        # Text shortened for the screen counts as the file's text too.
        if not ids and not row.get("fit"):
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

    @staticmethod
    def current_copy(row):
        """The file whose bytes the game gets: a file's checked working copy
        once it has one, else the game's own file."""
        return row["prepared"]["candidate"] if row.get("prepared") else row["path"]

    def drawn_copy(self, value, row):
        """The file whose bytes the game draws: an applied file's own, which
        edits after the apply, such as a game update's, may have changed, else
        the bytes Apply gives it."""
        if self.row_status(value, row) == "applied":
            return row["path"]
        return self.current_copy(row)

    def mark_seen(self, project_id, value):
        """Marks each occurrence the latest playtest saw drawn with where; one
        kept in Japanese then goes back to the assistant."""
        texts = {row["text"]: row for row in self.seen(project_id)["texts"]}
        for row in value["files"].values():
            for item in row["occurrences"]:
                item.pop("seen", None)
                if item["protected"] or not texts:
                    continue
                text = str(item["value"]).strip()
                # A plugin may draw a long string over several lines.
                found = texts.get(text) or next(
                    (
                        row
                        for key, row in texts.items()
                        if len(key) >= 4 and key in text
                    ),
                    None,
                )
                if found:
                    item["seen"] = pick(found, ("where", "capture"))

    def find_labels(self, project_id, value, texts):
        """Where the game draws each label from: text in the bytes each plugin
        file gets that a loaded plugin can draw and the app lets the
        assistant change, so no lookup value, code key or default. Found
        again only when a file, the labels or the originals change."""
        _, root = self.record(project_id)
        rows = []
        for row in value["files"].values():
            if row.get("issue"):
                continue
            try:
                drawn = self.drawn_copy(value, row)
                rows.append((row, drawn, self.fingerprint(root, drawn)))
            except OSError, ValueError:
                continue
        key = (
            tuple(texts),
            tuple((row["path"], hashed) for row, _drawn, hashed in rows),
            value["originals"].get("binding", ""),
        )
        saved = self.located.get(project_id)
        if saved and saved[0] == key:
            return saved[1]
        _prefix, _catalog, config = self.inventory(project_id)
        originals = value["originals"]
        # A label's longest word, to skip files that cannot hold it.
        words = {
            text: max(re.findall(r"[^\W_]{3,}", text), key=len, default=text).encode()
            for text in texts
        }
        found = {text: [] for text in texts}
        for row, drawn, hashed in rows:
            raw = self.source(root, drawn)
            wanted = [text for text in texts if words[text] in raw]
            if not wanted:
                continue
            parsed = self.documents.parse(
                [{"path": row["path"], "source": raw.decode(), "kind": row["kind"]}]
            )[row["path"]]
            if parsed["issues"]:
                continue
            code_keys = {
                item["value"] for item in parsed["literals"] if item["protected"]
            }
            lookup = set(
                originals.get(
                    "structuralKeys" if row["kind"] == "parameters" else "keys", []
                )
            )
            japanese = {
                (item["token"], tuple(item["logical"])): item["value"]
                for item in row["occurrences"]
            }
            for index, literal in enumerate(parsed["literals"]):
                if literal["protected"] or literal["kind"] == "default":
                    continue
                plugin, enabled, parameter = row["plugin"], row["enabled"], None
                if row["kind"] == "parameters":
                    path = literal.get("path") or []
                    if not (
                        len(path) >= 3
                        and type(path[0]) is int
                        and path[1] == "parameters"
                        and path[0] < len(config["plugins"])
                    ):
                        continue
                    entry = config["plugins"][path[0]]
                    plugin, enabled, parameter = entry["name"], entry["loads"], path[2:]
                if not enabled:
                    continue
                for logical, text, opaque in leaves(literal["value"]):
                    if opaque or text in lookup or text in code_keys:
                        continue
                    for label in wanted:
                        if not draws(text, label):
                            continue
                        source = japanese.get((index, tuple(logical)))
                        found[label].append(
                            {
                                "id": occurrence_id(
                                    row["path"], hashed, literal, logical
                                ),
                                "path": row["path"],
                                "plugin": plugin,
                                "token": index,
                                "logical": logical,
                                "value": text,
                                "line": literal["line"],
                                "start": literal["start"],
                                "end": literal["end"],
                                "kind": literal["kind"],
                                **({"parameterPath": parameter} if parameter else {}),
                                **({"source": source} if source else {}),
                            }
                        )
        self.located[project_id] = (key, found)
        return found

    def label_rows(self, project_id, value):
        """Each label from Text QA's latest capture with where it stands here:
        waiting for the assistant, shortened for that capture and ready to
        apply or applied, kept for a reason the assistant gave, or found in
        no plugin file; and the waiting ones with the text they could come
        from."""
        handed = self.labels(project_id)
        # DazedTL captures MV/MZ screens only.
        if not handed["labels"] or value.get("layout") == ACE_SCRIPTS:
            return {"task": handed["task"], "rows": [], "waiting": []}
        texts = sorted({label["text"] for label in handed["labels"]})
        # Before the task first reads the plugins, or while it can't, every
        # label waits for it; a copied task reports why.
        try:
            found = (
                self.find_labels(project_id, value, texts) if value["binding"] else None
            )
        except OSError, ValueError, UnicodeError:
            found = None
        decided = value.get("labels", {})
        rows, waiting = [], []
        for label in handed["labels"]:
            decision = decided.get(label["text"], {})
            # A label shortened for an earlier capture that still shows it
            # did not change what the game draws.
            settled = decision.get("decision") == "kept" or (
                decision.get("decision") == "shortened"
                and decision.get("task") == handed["task"]
            )
            state = (
                "kept"
                if decision.get("decision") == "kept"
                else (
                    "ready"
                    if any(
                        path in value["files"]
                        and self.row_status(value, value["files"][path]) == "ready"
                        for path in decision.get("files", [])
                    )
                    else "applied"
                )
                if settled
                else "waiting"
                if found is None or found[label["text"]]
                else "elsewhere"
            )
            rows.append(
                {
                    "text": label["text"],
                    "title": label["title"],
                    "state": state,
                    **({"reason": decision["reason"]} if state == "kept" else {}),
                }
            )
            if state == "waiting" and found:
                waiting.append(
                    {
                        **pick(
                            label, ("text", "title", "capture", "squeezed", "clipped")
                        ),
                        "candidates": found[label["text"]],
                    }
                )
        return {"task": handed["task"], "rows": rows, "waiting": waiting}

    def prepare_fit(self, project_id, value, waiting):
        """An editable copy of the bytes each file with a waiting label's text
        gets, apart from its translation's working copy, so that copy keeps
        its checks while the assistant shortens labels."""
        _, root = self.record(project_id)
        for path in sorted(
            {item["path"] for label in waiting for item in label["candidates"]}
        ):
            row = value["files"][path]
            self.runtime_allowlist(project_id, value, row)
            raw = self.source(root, self.current_copy(row))
            fitting = row.get("fitting")
            if fitting and fitting["originalHash"] == digest(raw):
                self.copy_boundary(root, fitting)
                if (
                    digest(self.source(root, fitting["original"]))
                    == fitting["originalHash"]
                ):
                    self.source(root, fitting["candidate"])
                    continue
            identity = uuid.uuid4().hex
            base = WORK + "/copies/" + identity + "/" + path
            write_bytes(project_path(root, base + ".original", exists=False), raw)
            write_bytes(project_path(root, base, exists=False), raw)
            row["fitting"] = {
                "original": base + ".original",
                "originalHash": digest(raw),
                "candidate": base,
                "copyRoot": WORK + "/copies/" + identity,
                "prepared": now(),
            }

    @staticmethod
    def fit_files(value, waiting):
        """Each file a waiting label's text is in, with that text and the
        copy the assistant shortens it in."""
        found = {}
        for label in waiting:
            for item in label["candidates"]:
                found.setdefault(item["path"], {})[item["id"]] = item
        return [
            {
                "path": path,
                "plugin": value["files"][path]["plugin"],
                "sourceHash": value["files"][path]["sourceHash"],
                "kind": value["files"][path]["kind"],
                "enabled": value["files"][path]["enabled"],
                "candidates": list(items.values()),
                # Why the last shortened copy of this file was not accepted.
                "failedCheck": value["files"][path]["fitting"].get("failed", ""),
                **pick(
                    value["files"][path]["fitting"],
                    ("original", "originalHash", "candidate", "copyRoot"),
                ),
            }
            for path, items in sorted(found.items())
        ]

    def capture(self, project_id, start=False):
        """The latest capture of the shortening request's labels on their
        screens, with its working copies served in place of the game's
        files, for the assistant's helper; *start* captures the copies as
        they are now first."""
        with self.lock:
            value = self.load(project_id)
            request = self.fit_request(value)
            _, root = self.record(project_id)
            served = self.served(root, request)
            plan = {
                "files": served,
                "labels": self.label_plan(request, served, root),
                "request": request["requestId"],
            }
        if start:
            self.capture_labels(project_id, plan)
        return self.capture_view(project_id, request, served)

    @staticmethod
    def fit_request(value):
        request = next(
            (
                row
                for row in value["requests"].values()
                if row["requestId"] == value.get("activeRequest")
            ),
            None,
        )
        if not request or request["kind"] != "fit":
            raise ValueError(
                "Only a request to shorten labels has screens to capture. Read plugin "
                "status and follow its active request."
            )
        return request

    def served(self, root, request):
        """Each shortening copy of a request as the capture serves it: in
        place of its file, by that file's path under the game's web folder,
        with the hash of its bytes now."""
        prefix = web_prefix(root)
        rows = []
        for item in request["files"]:
            if not item["path"].startswith(prefix):
                raise ValueError("A plugin file is outside the game's web folder.")
            rows.append(
                {
                    "path": item["path"],
                    "serve": item["path"][len(prefix) :],
                    "candidate": item["candidate"],
                    "hash": digest(self.source(root, item["candidate"])),
                }
            )
        return rows

    def label_plan(self, request, served, root):
        """Each requested label with the text its screen should draw now: what
        its changed candidates draw in its place, or the label itself while
        none changed."""
        found, parsed = {}, {}
        for item in request["files"]:
            for candidate in item["candidates"]:
                found[candidate["id"]] = (item, candidate)
        labels = []
        for label in request["labels"]:
            shows = []
            for identity in label["candidates"]:
                item, candidate = found[identity]
                if item["path"] not in parsed:
                    raw = self.source(root, item["candidate"])
                    parsed[item["path"]] = self.documents.parse(
                        [
                            {
                                "path": item["path"],
                                "source": raw.decode(),
                                "kind": item["kind"],
                            }
                        ]
                    )[item["path"]]
                literals = parsed[item["path"]]["literals"]
                if candidate["token"] >= len(literals):
                    continue
                now = read_leaf(
                    literals[candidate["token"]]["value"], candidate["logical"]
                )
                text = (
                    redrawn(candidate["value"], label["text"], now)
                    if isinstance(now, str) and now != candidate["value"]
                    else None
                )
                if text and text not in shows:
                    shows.append(text)
            labels.append(
                {
                    **pick(label, ("text", "title", "capture")),
                    "shows": shows or [label["text"]],
                }
            )
        return labels

    def languages(self, root):
        """The source and target of the game at *root*."""
        pair = language_pair.pair(self.translation.settings, root)
        return pair["source"], pair["target"]

    def capture_view(self, project_id, request, served):
        """Where the label capture stands for the request's copies as they are."""
        _, root = self.record(project_id)
        _source, target = self.languages(root)
        saved = self.captured(project_id) or {}
        operation = saved.get("operation")
        view = {"requestId": request["requestId"]}
        if operation:
            view["operation"] = operation
        helper = helper_command(
            self.translation.workspace,
            project_id,
            "plugins",
            "--capture",
            "--wait",
            "10",
        )
        if "report" in saved:
            current = saved["files"] == {row["path"]: row["hash"] for row in served}
            asked = {label["text"] for label in request["labels"]}
            view.update(
                finishedAt=saved["finished_at"],
                current=current,
                labels=[
                    {
                        key: row[key]
                        for key in (
                            "text",
                            "title",
                            "shows",
                            "fits",
                            "note",
                            "capture",
                            "squeezed",
                            "clipped",
                        )
                        if key in row
                    }
                    for row in saved["labels"]
                    if row["text"] in asked
                ],
                **(
                    {"unavailable": saved["unavailable"]}
                    if "unavailable" in saved
                    else {}
                ),
            )
        if operation and operation["status"] == "running":
            following = (
                "DazedTL is capturing the labels' screens; wait for it with " + helper
            )
        elif "report" not in saved:
            following = "Capture your working copies with " + helper
        elif not view["current"]:
            following = (
                "Your working copies changed after the last capture; capture them again with "
                + helper
            )
        elif "unavailable" in saved:
            following = (
                f"DazedTL couldn't run the game, so size the {target} from how short of "
                "room each label is; the app records that the labels weren't seen."
            )
        elif all(row["fits"] for row in view["labels"]) and len(view["labels"]) == len(
            request["labels"]
        ):
            following = "Every label fits on its screen; report them."
        else:
            following = (
                "Look at each capture, shorten the labels that don't fit and capture "
                f"again; keep a label only when no shorter {target} keeps its meaning."
            )
        view["next"] = following
        return view

    def unseen(self, project_id, request, root, texts):
        """Why the latest capture doesn't show these shortened labels fitting
        on their screens with the request's copies as they are, or ""; and
        what it saw of each, which the decision keeps."""
        saved = self.captured(project_id) or {}
        served = {row["path"]: row["hash"] for row in self.served(root, request)}
        if "report" not in saved or saved["files"] != served:
            problem = (
                "Capture your working copies with plugins --capture and look at each "
                "label on its screen before reporting it shortened."
            )
            return problem, {}
        if "unavailable" in saved:
            return "", {text: {"unseen": saved["unavailable"]} for text in texts}
        rows = {row["text"]: row for row in saved["labels"]}
        problems, seen = [], {}
        for text in texts:
            row = rows.get(text)
            if not row:
                problems.append(
                    f"The latest capture didn't measure {text}; capture again."
                )
            elif not row["fits"]:
                problems.append(f"{text}: {row['note']} See {row['capture']}.")
            else:
                seen[text] = {"capture": row["capture"]}
        return " ".join(problems), seen

    def fingerprint(self, root, path):
        """A file's hash, read again only when the file changed."""
        target = project_path(root, path)
        return self.digests.remember(
            str(target), target.stat(), lambda: digest(self.source(root, path))
        )

    def observe(self, project_id, value):
        """Bounded observations invalidate displayed checks without rewriting assistant work."""
        _, root = self.record(project_id)

        def fingerprint(path):
            return self.fingerprint(root, path)

        for row in value["files"].values():
            try:
                # Edits after a file is settled are expected, so it keeps its
                # state; copying the task again rescans every file.
                settled = self.row_status(value, row) in SETTLED
                if not project_path(root, row["path"], exists=False).exists():
                    # A removed plugin has nothing to translate; the next scan
                    # drops it.
                    if not settled:
                        row.update(stale=True, issue="")
                    continue
                result = row.get("result", {})
                expected = row.get("applied", {}).get("afterHash") or row["sourceHash"]
                # state() scans again under new SCAN_RULES before this.
                if not settled and freshness.compare(
                    freshness.Basis(None, {"source": expected}),
                    freshness.Basis(None, {"source": fingerprint(row["path"])}),
                ):
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
            self.mark_seen(project_id, value)
            project, _ = self.record(project_id)
            selected = set(value["selection"])
            stands = {
                path: self.row_status(value, row)
                for path, row in value["files"].items()
            }
            # Files with nothing for the assistant to decide stay out of the
            # counts, so they read as the assistant's progress; a changed file
            # counts until a scan says what it holds now. A file whose only
            # change shortens labels has no text to translate.
            statuses = Counter(
                stands[path]
                if any(item["id"] in selected for item in row["occurrences"])
                or stands[path] not in SETTLED | {"ready"}
                else "none"
                for path, row in value["files"].items()
                if row.get("issue")
                or row.get("stale")
                or row.get("loaderLiterals")
                or not all(item["protected"] for item in row["occurrences"])
            )
            translated = (
                statuses["ready"] + statuses["applied"] + statuses["translated"]
            )
            ready = [
                row for path, row in value["files"].items() if stands[path] == "ready"
            ]
            labels = self.label_rows(project_id, value)["rows"]
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
                "supported": project["engine"] in {"MVMZ", "ACE"},
                "limitation": ""
                if project["engine"] in {"MVMZ", "ACE"}
                else "Plugin files works with RPG Maker MV, MZ and VX Ace games.",
                # VX Ace keeps its player text in Ruby scripts, not plugins.
                "scripts": project["engine"] == "ACE",
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
                    "ready": len(ready),
                    # Of those, files whose translation is in the game and
                    # only shortened labels wait.
                    "shortened": sum(
                        bool(row["result"].get("onlyLabels")) for row in ready
                    ),
                    "applied": sum(stand == "applied" for stand in stands.values()),
                    "labels": sum(row["state"] == "waiting" for row in labels),
                },
                # Text QA's labels too long for the screen, from its latest
                # capture, and where each stands here.
                "labels": labels,
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
                "receipts": self.receipt_views(project_id, value),
                # The helper reads the active request's saved instructions here.
                "activeRequest": str(
                    self.path(project_id, "requests/" + active["requestId"] + ".json")
                )
                if active
                else "",
                "awaiting": bool(active)
                and report.get("status") == "awaiting_report"
                and report.get("requestId") == active["requestId"],
            }

    def receipt_views(self, project_id, value):
        """The latest applications and restores, each application undone
        through Git naming the later checkpoint to undo first."""
        from dazedtl.compatibility.checkpoint_history import blockers, refusal

        shown = value["receipts"][-12:]
        commits = [
            row["commit"]
            for row in shown
            if row.get("commit") and carries(value["files"], row)
        ]
        issues = {}
        if commits:
            try:
                issues = {
                    commit: refusal(found)
                    for commit, found in blockers(
                        self.record(project_id)[1], commits
                    ).items()
                }
            except (OSError, ValueError, RuntimeError) as exc:
                issues = dict.fromkeys(commits, str(exc))
        return [
            receipt_view(row, value["files"], issues.get(row.get("commit"), ""))
            for row in shown
        ]

    def original_issue(self, project_id, value):
        """Why the last scan had no original evidence, while that still holds."""
        issue = value.get("originalIssue", "")
        if issue and not value["originals"]:
            try:
                game_originals.require(
                    self.translation.workspace, project_id, self.record(project_id)[1]
                )
            except OSError, ValueError:
                return issue
            return "The original game files are available now. Copy the plugin task again so its investigation can check the original text."
        return issue

    def action(self, project_id, action, options=None):
        options = options or {}
        if not isinstance(options, dict):
            raise ValueError("Plugin action options must be an object.")
        with self.lock:
            value = self.load(project_id)
            if action == "plugin_task":
                result = self.copy_task(
                    project_id, value, recheck=options.get("recheck", True)
                )
            elif action == "apply":
                return self.apply(project_id, value)
            elif action == "preview_restore":
                preview = self.preview(project_id, value, "restore", options)
                self.previews[preview["token"]] = deepcopy(preview)
                return {"preview": preview_view(preview)}
            elif action == "restore":
                return self.restore(project_id, value, options)
            elif action == "undo":
                return self.undo(project_id, value, options)
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

    def copy_task(self, project_id, value, recheck=True):
        """The request a copied task starts from: whatever is left, or a recheck
        of every decision once nothing is, unless `recheck` is false, as for
        the final check's assistant, which only finishes what is left."""
        self.scan(project_id, value)
        self.observe(project_id, value)
        self.mark_seen(project_id, value)
        active = next(
            (
                request
                for request in value["requests"].values()
                if request["requestId"] == value.get("activeRequest")
            ),
            None,
        )
        result = self.advance(project_id, value, active)
        if not result and not recheck:
            return {
                "stage": "complete",
                "message": "Plugin files has nothing left: every "
                + ("script" if value["layout"] == ACE_SCRIPTS else "plugin file")
                + " is investigated and its player text translated.",
            }
        if not result:
            scope = self.investigation_scope(value, recheck=True)
            if not scope:
                # The scan is the whole answer: nothing is handed out.
                return {
                    "message": "No "
                    + ("script" if value["layout"] == ACE_SCRIPTS else "plugin")
                    + f" holds {active_source()} text to translate."
                }
            result = self.request(
                project_id, value, "investigation", scope, recheck=True
            )
        # What the copied task expects back, for the assistant task list.
        return {
            **result,
            "handoff": {
                "kind": "plugins",
                "requestId": result["requestId"],
                "expects": [self.report_path(project_id, result["requestId"])],
            },
        }

    def advance(self, project_id, value, current=None):
        """The next request: text still to investigate first, then files to
        translate, then labels Text QA found too long for the screen. A
        request whose scope has not changed is handed out again, so its saved
        report is extended rather than orphaned."""
        kind, scope = "investigation", self.investigation_scope(value)
        if not scope:
            kind, scope = "translation", self.translation_scope(value)
            if scope:
                self.prepare(project_id, value)
        if not scope:
            kind, scope = "fit", self.label_rows(project_id, value)
            if not scope["waiting"]:
                return None
            self.prepare_fit(project_id, value, scope["waiting"])
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
        for path, items in [] if kind == "fit" else scope:
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
                    **({"order": row["order"]} if "order" in row else {}),
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
        if kind == "fit":
            files = self.fit_files(value, scope["waiting"])
        # Translation follows prepare(), which checked the originals.
        self.current_sources(project_id, value, files)
        context = self.context(project_id)
        ace = value["layout"] == ACE_SCRIPTS
        game_data = root / ("ace_json" if ace else prefix_of(value["layout"]) + "data")
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
                **(
                    {
                        "qaTask": scope["task"],
                        "labels": [
                            {
                                **pick(
                                    label,
                                    ("text", "title", "capture", "squeezed", "clipped"),
                                ),
                                "candidates": [
                                    item["id"] for item in label["candidates"]
                                ],
                            }
                            for label in scope["waiting"]
                        ],
                    }
                    if kind == "fit"
                    else {}
                ),
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
        source, target = self.languages(root)
        text = (
            windows_note()
            + pair_note(source, target)
            + (
                (
                    "Translate the text this VX Ace game's Ruby scripts show to players. This is one DazedTL Plugin files task, which covers the scripts of VX Ace games; copying it did not start an assistant. Keep DazedTL open.\n"
                    "Work through it in this conversation: after each report, the helper below checks it and returns the next request, until every script is investigated and its player text translated. "
                    if ace
                    else "Translate the text this game's plugins show to players. This is one DazedTL Plugin files task; copying it did not start an assistant. Keep DazedTL open.\n"
                    "Work through it in this conversation: after each report, the helper below checks it and returns the next request, until every plugin file is investigated and its player text translated, and every plugin label Text QA found too long for the screen is shortened. "
                )
                + "Do not ask the user to copy another prompt or approve routine steps; ask only about choices the evidence cannot settle, after finishing the independent work.\n\n"
                "Read the request JSON: " + str(request_path) + "\n"
                "Save a structured report at: " + str(report_path) + "\n"
                "Bind version, kind, projectId, requestId and binding exactly, and use only the requested files, occurrence IDs and SHA-256 hashes. "
                + (
                    "Never run scripts or the game, providers or translation APIs. Event script calls belong to Other event text; do not edit event or database JSON, Data files or images.\n\n"
                    if ace
                    else "Never run plugin or game code, providers or translation APIs. Event plugin commands belong to Other event text; do not edit event or database JSON or images.\n\n"
                )
            )
        )
        if kind == "investigation":
            schema = {
                **identity_fields,
                "files": [
                    {
                        "path": "exact requested path",
                        "sourceHash": "request hash",
                        "examined": True,
                        "evidence": "complete script coverage"
                        if ace
                        else "complete source and recursive-parameter coverage",
                        "occurrences": [
                            {
                                "id": "requested occurrence ID",
                                "disposition": "visible|latent|protected|editor_only|non_visible",
                                "safe": True,
                                "evidence": "where the "
                                + ("scripts use" if ace else "plugin uses")
                                + " it, with readback checks",
                                "reason": "why players see it, or why they do not",
                            }
                        ],
                    }
                ],
                # RGSS3 scripts load no JSON of their own.
                **(
                    {}
                    if ace
                    else {
                        "dependencies": [
                            {
                                "path": "exact plugin-loaded JSON path",
                                "sourceFile": "requested loader file",
                                "literalId": "requested literal ID containing the exact path",
                                "evidence": "static loader use",
                            }
                        ]
                    }
                ),
            }
            text += (
                (
                    "INVESTIGATE. Decide whether players see each listed occurrence. Do not edit scripts, working copies or source backups in this stage.\n"
                    "Each file is one script of "
                    + ACE_SCRIPTS
                    + ", the paths relative to the game folder "
                    + str(root)
                    + "; its order is its place in the order RGSS3 runs the scripts, and a later script can redefine an earlier one's methods. "
                    "Follow each string to where the scripts use it: drawing (draw_text, add_command, set_text, $game_message), Vocab constants, menus and help text, but also comparisons, hash keys, case/when, lookups, note tag patterns and file names (Cache, Audio, Bitmap, Font). "
                    "Check the event scripts in ace_json/*.json too (codes 355, 655 and conditional branches 111): text an event compares, or stores in a variable a script or event compares later, "
                    f"keeps its {source}. "
                    "Comments and =begin blocks are not player text.\n"
                    "Dispositions: visible (players see it), latent (display text players never see because nothing uses it), protected (compared, looked up, or used as a key or file name), editor_only, non_visible. Only visible text that is safe to change is translated; "
                    f"the rest keeps its {source}. "
                    "Set safe to true only when changing the text cannot change behavior. The app already protects original database and note tag names, and strings the code compares, uses as hash or index keys or lists in a when clause, so those occurrences are not listed.\n"
                    "Give every listed occurrence a disposition, evidence and a reason. A file is done once its entry has examined true, file-level evidence and every listed occurrence decided. "
                    "You may report some files, run the helper and continue with the request it returns for the rest.\n"
                    if ace
                    else "INVESTIGATE. Decide whether players see each listed occurrence. Do not edit runtime files, working copies, settings or source backups in this stage.\n"
                    "Read each listed source and its configuration in js/plugins.js. Recursively decode every parameter layer and follow each string to where the plugin uses it: drawing, messages, menus and help text, but also comparisons, lookups, keys and file names. "
                    "Check defaults and fallbacks; comments and editor metadata are not player text.\n"
                    "Dispositions: visible (an enabled plugin shows it to players), latent (display text players never see because its plugin is disabled or it is only a default), protected (compared, looked up, or used as a key or file name), editor_only, non_visible. Only visible text that is safe to change is translated; "
                    f"the rest keeps its {source}. "
                    "Set safe to true only when changing the text cannot change behavior. The app already protects original database names, notetag names and plugin command arguments, so those occurrences are not listed.\n"
                    "Give every listed occurrence a disposition, evidence and a reason. A file is done once its entry has examined true, file-level evidence and every listed occurrence decided. "
                    "You may report some files, run the helper and continue with the request it returns for the rest.\n"
                    "A plugin that loads its own JSON through an exact path literal listed in loaderLiterals can add that file under dependencies; a later request lists its text.\n"
                )
                + (
                    "An occurrence with seen was drawn on screen when DazedTL played the game: seen says where, with a capture to look at. Text a screen of the game draws is player text, so decide it visible unless the plugin also uses it as a key; a screen the playtest opened on its own may be one players never reach, so check what opens it first. Say why in the reason.\n"
                    if any(item.get("seen") for _, items in scope for item in items)
                    else ""
                )
                + (
                    "This is a recheck: each occurrence lists its earlier finding. Keep or correct each one, starting with anything the user reports as untranslated or broken in the game. Files left out of the report keep their findings; a file you report must decide all of its listed occurrences again.\n"
                    if recheck
                    else "A finding listed with an occurrence was left undecided earlier; settle it now.\n"
                    if any("finding" in item for _, items in scope for item in items)
                    else ""
                )
            )
        elif kind == "translation":
            schema = {
                **identity_fields,
                "files": [
                    {
                        "path": "exact requested path",
                        "sourceHash": "request hash",
                        "candidateHash": "working copy SHA-256",
                        "evidence": f"{source}/{target} meaning and layout review performed",
                        "targets": {
                            "requested occurrence ID": f"exact decoded {target} target"
                        },
                    }
                ],
            }
            sources = [
                "the glossary and guidance files in the request",
                *(
                    [
                        f"the Translate stage's {target} output in "
                        + context["translated"]
                        + f" (its {source} sources are in the files folder beside it)"
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
                f"Keep names and terms consistent with the game's established {target}: "
                + ", ".join(sources[:-1])
                + " and "
                + sources[-1]
                + (
                    ". Fit the space where the script draws the text: RGSS3 draws with Font.default_name and Font.default_size, VL Gothic at 24 px unless a script sets them.\n"
                    "Each occurrence gives its line and the UTF-8 byte span of its literal in the original, quotes included; a heredoc's span is its body and a %w word's is the word. "
                    "Change only the listed string literals, writing Ruby that reads back as your exact target: keep each literal's quotes or delimiters. "
                    "In double-quoted strings, %Q() and heredocs escape \" as \\\" and \\ as \\\\, and write #{ only where it was; in single-quoted strings escape ' as \\' and \\ as \\\\; in a %w list write each space inside a word as \\ followed by the space. "
                    "Keep #{...} interpolation, format sequences such as %s and %d (a literal percent sign in a format string is %%), and control codes such as \\C[2], \\V[1] and \\G exactly, and keep a leading tag that the script matches with start_with? or index exactly as written. "
                    'Report every translated occurrence with its exact decoded target: the text Ruby makes of the literal, so "Gold\\\\G" in the source is Gold\\G in the target.\n'
                    "The app rejects bytes outside the listed spans, any change to the script's other strings and stale hashes, and syntax alone does not verify meaning. "
                    "When a check fails, the helper returns a request for the files still needing work, with each failedCheck: repair the same working copies and report them under that request. "
                    "Applying to the game is a separate step in the app, which also packs the applied scripts into Data/Scripts.rvdata2; do not claim rendered fit without testing it.\n"
                    if ace
                    else ". Fit the space where the plugin draws the text.\n"
                    'Change only the listed literal spans or decoded parameter paths. Preserve quote style, parameter keys, ordering, types and serialization depth, identifiers, interpolation and control codes; keep a leading tag that the file\'s code matches with startsWith or indexOf, such as ア: in line.startsWith("ア:"), exactly as written. '
                    "Report every translated occurrence with its exact decoded target.\n"
                    "The app rejects bytes outside the listed spans, unlisted decoded leaves and stale hashes, and syntax alone does not verify meaning. "
                    "When a check fails, the helper returns a request for the files still needing work, with each failedCheck: repair the same working copies and report them under that request. "
                    "Applying to the game is a separate step in the app; do not claim rendered fit without testing it.\n"
                )
            )
        else:
            schema = {
                **identity_fields,
                "labels": [
                    {
                        "text": "exact requested label",
                        "decision": "shortened|kept",
                        "evidence": "what the captures before and after your change show, and which listed text the plugin draws there",
                        "reason": "why it stays as it is (kept only)",
                    }
                ],
                "files": [
                    {
                        "path": "exact requested path",
                        "sourceHash": "request hash",
                        "candidateHash": "working copy SHA-256",
                        "evidence": f"how the shorter {target} keeps the meaning and fits",
                        "targets": {
                            "requested candidate ID": f"exact decoded shorter {target}"
                        },
                    }
                ],
            }
            text += (
                "SHORTEN. Text QA ran the game, captured its screens and found these plugin labels too long for the screen: the game squeezes or cuts them off. "
                "Each label lists its screen, its capture (an image to look at) and how short of room it is: squeezed 0.75 means the game drew it at 75% of the width it needs, "
                f"so the {target} needs about a quarter less width; clipped means its end is cut off. "
                f"Its candidates are the plugin text it can come from, with the {source} source where the app has it.\n"
                "Look at each capture, read the plugin's code to find which candidates it draws there, and shorten those in each file's working copy (candidate) until the label fits; runtime files and frozen copies (original) are read-only. "
                "Their paths are relative to the game folder " + str(root) + ".\n"
                f"Keep the meaning, the glossary's terms and the same {target} wherever the game shows the same term; a setting that lists several labels keeps its separators and item count. "
                "Change only listed candidates, keeping quote style, structure, interpolation and control codes.\n"
                f"Size the shorter {target} from how short of room each label is, with the font and window width the plugin's code sets, then check it on screen: run\n"
                + helper_command(
                    self.translation.workspace,
                    project_id,
                    "plugins",
                    "--capture",
                    "--wait",
                    "10",
                )
                + "\nDazedTL plays the game in a hidden window with your working copies served in place of the game's files, writing nothing into the game, and captures each label's screen again. "
                "For each label it lists the text the screen should draw now, whether it draws it in full, a note on what it draws instead, and the capture; look at each capture, and shorten again and capture again until the labels fit.\n"
                "Report a decision for every label: shortened, with each changed candidate in its file's targets, or kept with the reason, "
                f"only when no shorter {target} keeps its meaning or the plugin draws none of its candidates there. "
                "The app accepts a shortened label only when the latest capture of exactly these working copies shows it fitting; when DazedTL can't run the game, the capture says so, and the app records the label as not seen. "
                "The app also checks each working copy as it checks translations; when a check fails, the helper returns a request with each failedCheck. Applying to the game stays in the app.\n"
            )
        text += reference_folders.instructions(context["references"])
        text += (
            "\nReport schema:\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
            + "\n"
        )
        workspace = self.translation.workspace
        text += (
            "\nAfter saving the report, run:\n"
            + helper_command(
                workspace, project_id, "plugins", "--continue-request", identity
            )
            + "\nIt checks the report and returns the next request with its instructions, or the final state. "
            "Working copies are prepared automatically; applying them to the game is a separate step, never part of this task.\n"
            "If loopback access is sandboxed, use your normal permission flow and retry this read-only status command first:\n"
            + helper_command(workspace, project_id, "plugins")
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
            self.mark_seen(project_id, value)
            if request_id != request["requestId"]:
                if request_id == request.get("previousRequestId"):
                    # A lost reply must not restart the next stage or replace edited copies.
                    return {
                        "text": request["instructions"],
                        "request": str(
                            self.path(
                                project_id, "requests/" + request["requestId"] + ".json"
                            )
                        ),
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
                value["editing"]["errors"]
                if request["kind"] in {"translation", "fit"}
                else []
            )
            # Retain accepted findings even if later preparation cannot finish.
            self.save(project_id, value)
            # Changed sources and newly found JSON need their text listed first.
            if any(row.get("stale") for row in value["files"].values()):
                self.scan(project_id, value)
            self.observe(project_id, value)
            self.mark_seen(project_id, value)
            result = self.advance(project_id, value, request)
            self.save(project_id, value)
            if result:
                count, noun, verb = (
                    (len(self.investigation_scope(value)), "file", "investigate")
                    if result["stage"] == "investigation"
                    else (len(self.translation_scope(value)), "file", "translate")
                    if result["stage"] == "translation"
                    else (
                        len(self.label_rows(project_id, value)["waiting"]),
                        "label",
                        "shorten",
                    )
                )
                result["message"] = (
                    f"{count} {noun if count == 1 else noun + 's'} left to {verb}."
                    + (" Failed checks: " + "; ".join(problems) if problems else "")
                )
            else:
                unreadable = [
                    path for path, row in value["files"].items() if row.get("issue")
                ]
                labels = self.label_rows(project_id, value)["rows"]
                result = {
                    "stage": "complete",
                    "message": "Every "
                    + ("script" if value["layout"] == ACE_SCRIPTS else "plugin file")
                    + " is investigated and its player text translated"
                    + (
                        ", and every plugin label Text QA found too long for the screen is shortened or kept"
                        if any(row["state"] != "elsewhere" for row in labels)
                        else ""
                    )
                    + ". Applying it to the game is a separate step."
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
        current = self.original_context(project_id, prefix_of(value["layout"]))
        if (
            not value["originals"]
            or current["binding"] != value["originals"]["binding"]
        ):
            raise ValueError(
                "Original lookup evidence changed or is missing. Investigate again."
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
        same = (
            request["kind"] == kind
            and request["binding"] == value["binding"]
            and request["guidance"] == self.guidance(root)
            and request["originals"]
            == pick(value["originals"], ("backupId", "binding"))
            and request["layout"] == value["layout"]
        )
        if kind == "fit":
            # The same labels in the same copies, which the assistant may
            # have started shortening.
            labels = lambda rows: [
                (row["text"], row["capture"], row["candidates"]) for row in rows
            ]
            files = lambda rows: [
                (row["path"], row["originalHash"], row["candidate"]) for row in rows
            ]
            return (
                same
                and request["qaTask"] == scope["task"]
                and labels(request["labels"])
                == labels(
                    {
                        **label,
                        "candidates": [item["id"] for item in label["candidates"]],
                    }
                    for label in scope["waiting"]
                )
                and files(request["files"])
                == files(self.fit_files(value, scope["waiting"]))
            )
        return same and shape(request["files"]) == shape(
            {
                "path": path,
                "sourceHash": value["files"][path]["sourceHash"],
                "occurrences": items,
            }
            for path, items in scope
        )

    def saved_request(self, project_id, request_id):
        """A translation or shortening request this project issued, as the
        profile recorded it."""
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", request_id
        ):
            raise ValueError(
                "Saved results need the translation task that asked for them."
            )
        request = read_json(self.path(project_id, "requests/" + request_id + ".json"))
        self.verify_request(project_id, request)
        if request.get("kind") not in {"translation", "fit"}:
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
            or read_json(
                self.path(project_id, "requests/" + request["requestId"] + ".json")
            )
            != request
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
        path = self.report_path(project_id, request["requestId"])
        if not path.is_file():
            raise ValueError(
                "No saved "
                + kind
                + " report yet. Have your agent finish the copied task, then check again."
            )
        report = read_json(path, limit=32_000_000)
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
        if kind == "fit":
            return self.accept_fit(project_id, value, request, report, rows)
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
                    if target.get("seen"):
                        finding["seen"] = True
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
                # Text shortened for the screen stays as it was checked.
                fitted = [item for item in row.get("fit", []) if item["id"] not in ids]
                kept = {item["id"]: item["target"] for item in fitted}
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
                        [*approved, *fitted],
                        {**kept, **targets},
                        language=game_source(root),
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
                    "targets": {**kept, **targets},
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
                if source not in allowed or allowed[source]["kind"] == "ruby":
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
                prefix = prefix_of(value["layout"])
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

    def accept_fit(self, project_id, value, request, report, rows):
        """Checks a report on labels too long for the screen. A label counts
        as shortened once a checked working copy holds text that no longer
        draws it, and as kept with the assistant's reason; a copy that fails
        its checks stays with the assistant with its failedCheck."""
        _, root = self.record(project_id)
        originals = self.current_originals(project_id, value)
        asked = {label["text"]: label for label in request["labels"]}
        answers = report.get("labels", [])
        if (
            not isinstance(answers, list)
            or any(not isinstance(item, dict) for item in answers)
            or len({item.get("text") for item in answers}) != len(answers)
        ):
            raise ValueError("Label decisions must be unique entries.")
        decisions = {}
        for item in answers:
            if item.get("text") not in asked or item.get("decision") not in {
                "shortened",
                "kept",
            }:
                raise ValueError("Unknown label or invalid decision.")
            evidence = bounded(item.get("evidence", ""), "Label evidence")
            reason = bounded(item.get("reason", ""), "Label reason")
            if not evidence.strip() or (
                item["decision"] == "kept" and not reason.strip()
            ):
                raise ValueError(
                    "Every label decision needs evidence, and a kept label its reason."
                )
            decisions[item["text"]] = {
                "decision": item["decision"],
                "evidence": evidence,
                "reason": reason,
            }
        labels_of = {}
        for text, label in asked.items():
            for identity in label["candidates"]:
                labels_of.setdefault(identity, set()).add(text)
        allowed = {row["path"]: row for row in request["files"]}
        updated = deepcopy(value)
        errors, shortened, failed, passed = [], {}, set(), 0
        # What the latest capture of these copies shows of each label.
        sightings = {}
        for answer in rows:
            path = answer["path"]
            wanted = allowed[path]
            row = updated["files"][path]
            if answer.get("sourceHash") != wanted["sourceHash"]:
                raise ValueError("Report source hash does not match: " + path)
            keys = ("original", "originalHash", "candidate", "copyRoot")
            fitting = row.get("fitting") or {}
            if pick(fitting, keys) != pick(wanted, keys):
                raise ValueError(
                    "This file's copy for shortening changed. Read plugin status and use its active request."
                )
            self.copy_boundary(root, fitting)
            base = self.source(root, fitting["original"])
            edited = self.source(root, fitting["candidate"])
            if digest(base) != fitting["originalHash"]:
                raise ValueError("Frozen copy changed: " + path)
            if answer.get("candidateHash") != digest(edited):
                raise ValueError("Candidate hash does not match: " + path)
            targets = answer.get("targets")
            candidates = {item["id"]: item for item in wanted["candidates"]}
            if (
                not isinstance(targets, dict)
                or not targets
                or set(targets) - set(candidates)
            ):
                raise ValueError("Results contain unrequested candidate IDs.")
            if any(
                not any(
                    decisions.get(text, {}).get("decision") == "shortened"
                    for text in labels_of[identity]
                )
                for identity in targets
            ):
                raise ValueError(
                    "Change only candidates of labels you report as shortened."
                )
            evidence = bounded(answer.get("evidence", ""), "Shortening evidence")
            if not evidence.strip():
                raise ValueError("Results need saved meaning and fit evidence.")
            touched = {text for identity in targets for text in labels_of[identity]}
            # A shorter label counts once the game shows it fitting.
            problem, seen = self.unseen(project_id, request, root, sorted(touched))
            if problem:
                fitting["failed"] = problem
                errors.append(path + ": " + problem)
                failed |= touched
                continue
            sightings.update(seen)
            try:
                self.promote_fit(
                    root,
                    updated,
                    row,
                    base,
                    edited,
                    {identity: candidates[identity] for identity in targets},
                    targets,
                    originals,
                )
            except (ValueError, UnicodeError) as exc:
                fitting["failed"] = str(exc)
                errors.append(path + ": " + str(exc))
                failed |= touched
                continue
            row["result"].update(evidence=evidence, requestId=request["requestId"])
            passed += 1
            for identity, target in targets.items():
                for text in labels_of[identity]:
                    if not draws(target, text):
                        shortened.setdefault(text, set()).add(path)
        saved = updated.setdefault("labels", {})
        for text, decision in decisions.items():
            if decision["decision"] == "shortened" and (
                text in failed or text not in shortened
            ):
                if text not in failed:
                    errors.append(
                        text + ": no checked copy holds shorter text for this label"
                    )
                continue
            saved[text] = {
                **decision,
                # The capture that showed it fitting, or why none could.
                **sightings.get(text, {}),
                # The files that hold its shorter text.
                "files": sorted(shortened.get(text, ())),
                "task": request["qaTask"],
                "requestId": request["requestId"],
                "saved": now(),
            }
        updated["editing"] = {
            "status": "current"
            if not errors and set(decisions) == set(asked)
            else "partial",
            "errors": errors,
            "accepted": passed,
            "reported": len(rows),
            "expected": len(allowed),
            "saved": now(),
            "requestId": request["requestId"],
        }
        value.clear()
        value.update(updated)
        return {
            "accepted": len(decisions),
            "message": "Saved shortening report checked.",
            "errors": errors,
        }

    def promote_fit(self, root, value, row, base, edited, approved, targets, originals):
        """Makes a checked shortening copy the file's working copy. The copy
        is checked against the bytes it started from, then as the whole
        working copy against the frozen original, with the shortened text as
        approved text of its own."""
        path = row["path"]
        parsed = self.documents.parse(
            [
                {"path": "base/" + path, "source": base.decode(), "kind": row["kind"]},
                {
                    "path": "edited/" + path,
                    "source": edited.decode(),
                    "kind": row["kind"],
                },
            ]
        )
        validate(
            base,
            edited,
            parsed["base/" + path],
            parsed["edited/" + path],
            list(approved.values()),
            targets,
            language=game_source(root),
        )
        if edited == base:
            raise ValueError("No label text changed in the working copy.")
        prepared = row.get("prepared")
        if prepared:
            self.copy_boundary(root, prepared)
            original = self.source(root, prepared["original"])
            if digest(original) != prepared["originalHash"]:
                raise ValueError("Frozen original changed.")
        else:
            original = base
        first = self.documents.parse(
            [
                {
                    "path": "original/" + path,
                    "source": original.decode(),
                    "kind": row["kind"],
                }
            ]
        )["original/" + path]
        if len(first["literals"]) != len(parsed["base/" + path]["literals"]):
            raise ValueError(
                "Literal inventory changed; unrelated code or new literals are not allowed."
            )
        selected = set(value["selection"])
        own = {
            item["id"]: item for item in row["occurrences"] if item["id"] in selected
        }
        fitted = {item["id"]: item for item in row.get("fit", [])}
        merged = {
            **{identity: item["target"] for identity, item in fitted.items()},
            **{
                identity: target
                for identity, target in row.get("result", {}).get("targets", {}).items()
                if identity in own
            },
        }
        hashed = digest(original)
        for identity, candidate in approved.items():
            literal = first["literals"][candidate["token"]]
            text = next(
                (
                    text
                    for logical, text, _opaque in leaves(literal["value"])
                    if logical == candidate["logical"]
                ),
                None,
            )
            if text is None:
                raise ValueError("The decoded parameter path changed.")
            located = occurrence_id(path, hashed, literal, candidate["logical"])
            merged[located] = targets[identity]
            if located not in own:
                fitted[located] = {
                    "id": located,
                    "file": path,
                    "token": candidate["token"],
                    "logical": candidate["logical"],
                    "value": text,
                    "line": literal["line"],
                    "start": literal["start"],
                    "end": literal["end"],
                    "protected": False,
                    "kind": literal["kind"],
                    "target": targets[identity],
                }
        lookup = set(
            originals["structuralKeys" if row["kind"] == "parameters" else "keys"]
        )
        code_keys = {item["value"] for item in first["literals"] if item["protected"]}
        if any(
            item["value"] in lookup or item["value"] in code_keys
            for item in fitted.values()
        ):
            raise ValueError(
                "Protected original lookup or code value cannot be published."
            )
        checks = validate(
            original,
            edited,
            first,
            parsed["edited/" + path],
            [*own.values(), *fitted.values()],
            merged,
            language=game_source(root),
        )
        # Whether the file's translation is in the game, or waits with it.
        settled = self.row_status(value, row) != "ready" or bool(
            row.get("result", {}).get("onlyLabels")
        )
        if prepared:
            write_bytes(project_path(root, prepared["candidate"]), edited)
        else:
            identity = uuid.uuid4().hex
            copy = WORK + "/copies/" + identity + "/" + path
            write_bytes(project_path(root, copy + ".original", exists=False), base)
            write_bytes(project_path(root, copy, exists=False), edited)
            row["prepared"] = {
                "original": copy + ".original",
                "originalHash": digest(base),
                "candidate": copy,
                "copyRoot": WORK + "/copies/" + identity,
                "prepared": now(),
            }
        row["fit"] = list(fitted.values())
        row["result"] = {
            "status": "ready",
            "reason": "",
            "checks": checks,
            "candidateHash": digest(edited),
            "targets": merged,
            "selection": sorted(own),
            "onlyLabels": settled,
            "saved": now(),
        }
        row.pop("fitting", None)

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
            # Only checked translations go in; files the game already
            # carries, and those the assistant still works on, are not
            # left unchanged.
            rows = [
                row
                for row in value["files"].values()
                if self.row_status(value, row) == "ready"
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
                    if not asked or (
                        request["kind"] == "translation"
                        and sorted(item["id"] for item in asked["occurrences"]) != ids
                    ):
                        raise ValueError("The exact approved occurrence scope changed.")
                    # The chosen text, and any text shortened for the screen.
                    approved = [
                        *(
                            item
                            for item in row["occurrences"]
                            if item["id"] in selected
                        ),
                        *row.get("fit", []),
                    ]
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
                            path, original, parsed["original/" + path], every=True
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
                    for occurrence in approved:
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
                        approved,
                        result["targets"],
                        language=game_source(root),
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
        self.translation.writable(project_id)
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
        return preview

    @staticmethod
    def _mode(root, path):
        return project_path(root, path).stat().st_mode & 0o777

    def publication_manifest(self, project_id, rows):
        return publication_manifest(
            self.translation.workspace, project_id, self.record(project_id)[1], rows
        )

    def apply(self, project_id, value):
        """Writes every checked translation into the game in one step. A list
        of files could not show the user what changed, so the app's checks
        are the review: each file is checked again here and backed up for
        Recovery."""
        preview = self.preview(project_id, value, "apply", {})
        if not preview["files"]:
            if not preview["blocked"]:
                raise ValueError("No plugin file is ready to apply.")
            reasons = {}
            for row in preview["blocked"]:
                reasons.setdefault(row["reason"], []).append(
                    PurePosixPath(row["path"]).name
                )
            raise ValueError(
                " ".join(
                    ["Nothing was applied."]
                    + [
                        ", ".join(names) + ": " + reason
                        for reason, names in reasons.items()
                    ]
                )
            )
        return {
            **self.publish(project_id, value, preview),
            "blocked": preview["blocked"],
        }

    def restore(self, project_id, value, options):
        """Restores an application's backups once they still match the
        restore the user reviewed."""
        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        self.translation.writable(project_id)
        preview = self.previews.pop(options.get("token"), None)
        if (
            not preview
            or preview["projectId"] != project_id
            or preview["mode"] != "restore"
        ):
            raise ValueError("This restore review expired or was already used.")
        if datetime.fromisoformat(preview["created"]) < datetime.now(UTC) - timedelta(
            minutes=20
        ):
            raise ValueError("This restore review expired. Review the restore again.")
        if not preview["files"]:
            raise ValueError("The reviewed restore is empty. Nothing was restored.")
        if preview["selection"] != value["selection"]:
            raise ValueError("Selection changed after review.")
        included, _blocked = self.checked_rows(
            project_id, value, "restore", {"receipt": preview["receipt"]}
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
            raise ValueError("A file changed after review. Review the restore again.")
        return self.publish(project_id, value, preview)

    def undo(self, project_id, value, options):
        """Takes an application out of the game through its checkpoint, in
        one click, while every file it wrote still holds what it wrote."""
        from dazedtl.compatibility import checkpoint_history
        from dazedtl.translation import checkpoint_records

        self.translation.idle(project_id)
        self.translation.clean_drafts(project_id)
        self.translation.writable(project_id)
        project, root = self.record(project_id)
        receipt = next(
            (row for row in value["receipts"] if row["id"] == options.get("receipt")),
            None,
        )
        if not receipt or not undoes(receipt):
            raise ValueError("Choose an application to undo.")
        if not carries(value["files"], receipt) or receipt.get("restoreIssue"):
            raise ValueError(
                receipt.get("restoreIssue")
                or "A later application or restore replaced these files."
            )

        def unchanged():
            for row in receipt["files"]:
                if digest(self.source(root, row["path"])) != row["afterHash"]:
                    raise ValueError(
                        PurePosixPath(row["path"]).name
                        + " changed since it was applied, so it can't be undone here."
                    )

        workspace = self.translation.workspace
        original = game_originals.saved(workspace, project_id, root)
        if receipt.get("commit"):
            # The application's record follows as every undo's does.
            checkpoint_records.undo(
                checkpoint_records.Records(
                    root,
                    workspace,
                    project_id,
                    checkpoint_records.publications(self.backend, project),
                ),
                receipt["commit"],
                original=original,
                check=unchanged,
            )
            value = self.load(project_id)
            restored = next(
                (
                    row
                    for row in reversed(value["receipts"])
                    if row.get("restores") == receipt["id"]
                ),
                None,
            )
            if restored is None:
                raise ValueError(
                    "The application was undone, but Plugin files no longer lists "
                    "all of its files, so its record stays as it was."
                )
        else:
            result = checkpoint_history.put_back(
                root,
                receipt["parent"],
                [row["path"] for row in receipt["files"]],
                "Restored an interrupted plugin application",
                check=unchanged,
                original=original,
                folder=checkpoint_records.publications(self.backend, project),
            )
            restored = take_out(
                workspace, project_id, root, value, receipt, result["commit"]
            )
            self.save(project_id, value)
        return {
            "receipt": receipt_view(restored, value["files"]),
            "state": self.state(project_id),
            "completed": len(restored["files"]),
        }

    def publish(self, project_id, value, preview):
        """Backs up and writes a checked batch, rolling back what it wrote if
        any file fails. A VX Ace game's scripts are then packed into the
        Data/Scripts.rvdata2 the game reads."""
        project, root = self.record(project_id)
        with self.backend.game_write(
            root,
            project.get("backend_id"),
            paths=[row["path"] for row in preview["files"]],
            subject="The scripts",
            summary=APPLY_SUMMARY,
            stage="Translate",
        ) as game:
            receipt, completed = self._publish(project_id, value, preview, root, game)
        if game.checkpoint:
            # Undoing the application is undoing this checkpoint.
            receipt["commit"] = game.checkpoint
            self.save(project_id, value)
        # Read once the gateway packed a VX Ace game's scripts.
        return {
            "receipt": receipt_view(receipt, value["files"]),
            "state": self.state(project_id),
            "completed": len(completed),
        }

    def _publish(self, project_id, value, preview, root, game):
        token = preview["token"]
        mode = preview["mode"]
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
            name = WORK + "/publications/" + token + "/output/" + row["path"]
            write_bytes(project_path(root, name, exists=False), candidate)
            row["frozen"] = name
            frozen.append((row, candidate, raw))
        manifest = self.publication_manifest(project_id, publication["files"])
        write_json(project_path(root, preview["manifest"], exists=False), manifest)
        # What an interrupted publication's files go back to.
        publication["parent"] = game.parent
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
                game.put(row["path"], candidate, self._mode(root, row["path"]))
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
                    game.put(row["path"], raw, self._mode(root, row["path"]))
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
            "parent": publication["parent"],
        }
        self.finish(project_id, value, receipt)
        if failure:
            raise ValueError(
                "Publication failed; rollback attempted. "
                + failure
                + (" Recovery conflicts: " + "; ".join(conflicts) if conflicts else "")
            )
        return receipt, completed

    def finish(self, project_id, value, receipt):
        finish(
            self.translation.workspace,
            project_id,
            self.record(project_id)[1],
            value,
            receipt,
        )
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
                        "backup" in row
                        and digest(self.source(root, row["backup"]))
                        != row["beforeHash"]
                    ) or digest(self.source(root, row["frozen"])) != row["afterHash"]:
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
                **(
                    {"parent": publication["parent"]}
                    if publication.get("parent")
                    else {}
                ),
            }
            self.finish(project_id, value, receipt)
