"""One retained image workflow shared by Guided and the standalone manager."""

import base64
import hashlib
import json
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dazedtl import foreign_work, system
from dazedtl.compatibility.images import ImageCompatibility
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.freshness import Basis, Digests, compare, signature, signature_settled
from dazedtl.languages import ENGLISH, JAPANESE
from dazedtl.settings import language_pair
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import originals as game_originals
from dazedtl.translation.files import decode_json, digest, project_path, read_json
from dazedtl.translation.git_status_cache import repository_signature
from dazedtl.translation.helper_command import windows_note

from . import families, recipes
from .inventory import (
    Index,
    PreviewCache,
    image_folder,
    inspect_row,
    png_metadata,
    png_preview,
    sha_file,
)

WORK = ".dazedtl/image_manager/guided"
CLASSIFICATIONS = {
    "recommended",
    "uncertain",
    "no_text",
    "already_english",
    "sound_effects",
    "not_examined",
    "excluded",
}
EXAMINATION_METHODS = {"visual", "ocr", "local_ocr", "visual+ocr", "visual+local_ocr"}
SCOPES = {"remaining", "all", "folders", "selected"}
ASSISTANT_STEPS = ("status", "scan", "investigate", "translate", "apply")
REVIEW_VERSION = 1
# Editing requests from this version on accept the assistant's review of an
# edited image only with a current recipe and passing validation.
RECIPE_VERSION = 1
VIEW = {
    "query": "",
    "status": "all",
    "folder": "",
    "showSelected": False,
    "tileSize": 112,
    "scroll": 0,
    "currentImage": "",
    "viewedImage": "",
    "workflowMode": "discovery",
}
# What an assistant hears when it saves or continues an investigation the
# user stopped to choose the images themselves.
USER_CHOSE = (
    "The user stopped this image investigation to choose the images to translate "
    "themselves, so DazedTL no longer reads its report. Don't investigate the images "
    "again; images --status names the next step."
)
# The view of the list to translate, without the images already in the game.
LIST_VIEW = {"showSelected": True, "status": "not_applied"}
# The view settings a user browses by. Once they change one, the grid stays
# where they put it.
BROWSING = ("status", "showSelected", "folder", "query", "scroll")


def now():
    return datetime.now(UTC).isoformat()


def text(value, label, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(label + " must be text within the supported length.")
    return value


# Stored report records also bind their report file, hash and counts, which
# only result checks read.
REPORT_KEYS = (
    "status",
    "lastReport",
    "reportId",
    "requestId",
    "message",
    "errors",
    "scope",
    "folders",
    "copiedAt",
    "rejected",
)


def report_view(value):
    return {key: deepcopy(value[key]) for key in REPORT_KEYS if key in value}


def receipt_view(receipt):
    """A publication receipt in the contract's terms; restores read the stored one."""
    view = {"id": receipt["id"]}
    if receipt.get("action"):
        view["action"] = receipt["action"]
    if receipt.get("saved") or receipt.get("created"):
        view["created"] = receipt.get("saved") or receipt["created"]
    if isinstance(receipt.get("completed"), int):
        view["count"] = receipt["completed"]
    view["assets"] = [
        {"id": item} if isinstance(item, str) else {"id": str(item.get("id", ""))}
        for item in receipt.get("assets", [])
    ]
    if receipt.get("message"):
        view["message"] = receipt["message"]
    return view


def _investigated(value, counts):
    """Whether the images are investigated: the folder Images reads is
    scanned and every image in it has a finding or is settled, in the game
    or excluded, so an investigation of the remaining images has nothing
    left to ask. The Images task and images --status both read this."""
    return bool(value["inventoryRevision"]) and not counts["notExamined"]


def _stopped(value):
    """Whether the user stopped the investigation to choose the images."""
    return value["discovery"].get("status") == "stopped"


def _set_aside(row):
    """Restore originals takes an image's application out of the game; it
    comes back once the game holds that image again (`_inspect`)."""
    applied = row.pop("applied", None)
    if applied:
        row["restored"] = applied


class ImageService:
    def __init__(self, projects, translation, settings, backend, *, adapter=None):
        self.projects, self.translation, self.settings, self.backend = (
            projects,
            translation,
            settings,
            backend,
        )
        self.adapter = adapter or ImageCompatibility(backend)
        self.lock = threading.RLock()
        self.indexes, self.jobs, self.cancellations = {}, {}, {}
        self.cache = PreviewCache()
        self.previews = {}
        self.mutating = set()
        self.threads = {}
        self.foreign = {}
        # The game's checkpoints as the images were last inspected against.
        self.checkpoints = {}
        # Recipe inputs by path and stat signature, hashed once per change.
        self.digests = Digests()

    def close(self):
        for event in self.cancellations.values():
            event.set()
        for worker in self.threads.values():
            worker.join(timeout=1)

    def record(self, project_id):
        project = self.projects.get(project_id)
        root = Path(project["source"]).resolve(strict=True)
        if not root.is_dir() or root == root.parent:
            raise ValueError("The selected game folder is unavailable.")
        for protected in (
            getattr(self.backend, "source", None),
            getattr(self.translation, "workspace", None),
        ):
            if protected:
                path = Path(protected).resolve()
                if root.is_relative_to(path) or path.is_relative_to(root):
                    raise ValueError(
                        "Choose a game separate from the application and its profile."
                    )
        return project, root

    def workspace(self, project_id):
        _project, root = self.record(project_id)
        return project_path(root, WORK + "/state.json", exists=False).parent

    def _load(self, project_id):
        _project, root = self.record(project_id)
        path = project_path(root, WORK + "/state.json", exists=False)
        if path.exists():
            try:
                value = read_json(path, limit=16_000_000)
            except ValueError:
                value = None
            if not foreign_work.owned(value, project_id):
                raise ForeignWorkError(
                    "Image work in this game folder was saved by another project or app version. Its files were kept; choose how to continue in Images.",
                    self._foreign_summary(project_id, root, path, value),
                )
            # Earlier versions saved a refresh before any report as an error.
            for kind in ("discovery", "editing"):
                task = value.get(kind) or {}
                if isinstance(task.get("errors"), list):
                    task["errors"] = [
                        error
                        for error in task["errors"]
                        if not str(error).startswith(
                            "No saved report is available yet."
                        )
                    ]
            # Earlier versions let a click replace the list after a translation
            # task was copied; that task's images join the list again, once,
            # and the grid opens on the list instead of a retired filter.
            if value.get("listVersion") != 2:
                value["selection"] = list(
                    dict.fromkeys(value["selection"] + self._requested(root, value))
                )
                if value["selection"]:
                    value["view"].update(LIST_VIEW, folder="", query="")
                value["listVersion"] = 2
                self._save(project_id, value)
            # Earlier versions' view of the list also showed images in the game.
            view = value["view"]
            if view.get("showSelected") and view.get("status") == "all":
                view.update(LIST_VIEW)
            return value
        return {
            "version": 1,
            "projectId": project_id,
            "listVersion": 2,
            "selection": [],
            "view": dict(VIEW),
            "inventoryRevision": "",
            "profile": None,
            "discovery": {
                "scope": "all",
                "folders": [],
                "status": "idle",
                "lastReport": "",
                "errors": [],
            },
            "editing": {"status": "idle", "lastReport": "", "errors": []},
            "requests": {},
            "receipts": [],
            "warnings": [],
        }

    @staticmethod
    def _requested(root, value):
        """The images the latest copied translation task covers."""
        entry = value["requests"].get(value["editing"].get("requestId") or "")
        if not entry:
            return []
        try:
            request = read_json(project_path(root, entry["path"]), limit=48_000_000)
            return [row["id"] for row in request["assets"]]
        except KeyError, OSError, TypeError, ValueError:
            return []

    def _save(self, project_id, value):
        write_json(self.workspace(project_id) / "state.json", value)

    def _foreign_summary(self, project_id, root, path, value):
        """What another project's saved image work holds, and whether it can be
        used here. Snapshots ask often, so it is kept until its files change."""
        inventory = project_path(root, WORK + "/inventory.sqlite3", exists=False)
        signature = [
            (item.stat().st_mtime_ns, item.stat().st_size) if item.exists() else None
            for item in (path, inventory)
        ]
        saved = self.foreign.get(project_id)
        if saved and saved[0] == signature:
            return saved[1]
        counts = {"examined": 0, "edited": 0, "applied": 0, "restorable": 0}
        blocked = ""
        try:
            if not foreign_work.readable(value):
                raise TypeError
            if inventory.is_file():
                with closing(
                    sqlite3.connect(inventory.as_uri() + "?mode=ro", uri=True)
                ) as db:
                    for (raw,) in db.execute("SELECT data FROM assets"):
                        row = json.loads(raw)
                        applied = (row.get("applied") or {}).get("runtimeHash")
                        counts["examined"] += bool(
                            (row.get("finding") or {}).get("examined")
                        )
                        counts["edited"] += bool(row.get("changed"))
                        counts["applied"] += bool(applied)
                        # Restores need only the original Prepare kept, which
                        # the game folder's Git record or copy holds.
                        counts["restorable"] += bool(
                            applied
                            and row.get("frozen")
                            and applied == row.get("sourceHash")
                        )
            if value["pendingPublications"]:
                blocked = foreign_work.INTERRUPTED
        except AttributeError, KeyError, TypeError, ValueError, sqlite3.Error:
            blocked = foreign_work.UNREADABLE
        summary = {**foreign_work.summary(path), **counts, "blocked": blocked}
        self.foreign[project_id] = (signature, summary)
        return summary

    def _foreign_state(self, project_id, binding):
        """Another project's saved work and its summary, as the user was shown them."""
        try:
            self._load(project_id)
        except ForeignWorkError as exc:
            path = self.workspace(project_id) / "state.json"
            return foreign_work.reviewed(path, exc.summary, binding), exc.summary
        raise ValueError("This project's image work is already in use.")

    def adopt(self, project_id, binding):
        """Takes over another project's saved work after the user chose it.

        Selection, findings, edited copies, reviews and application records
        carry over, and restores keep the originals saved in the game folder.
        Copied tasks do not: their requests are bound to the other project, so
        they are never handed out again or their reports accepted, and the next
        copy resumes from them.
        """
        with self.lock:
            raw, summary = self._foreign_state(project_id, binding)
            if summary["blocked"]:
                raise ValueError(summary["blocked"])
            value = decode_json(raw)
            previous = value["projectId"]
            for entry in value["requests"].values():
                entry["carried"] = True
            for kind in ("discovery", "editing"):
                if value[kind]["status"] == "awaiting_results":
                    value[kind]["status"] = "idle"
                value[kind].pop("rejected", None)
                value[kind].pop("rejectedHash", None)
            value.update(
                projectId=project_id, adopted={"projectId": previous, "saved": now()}
            )
            self._save(project_id, value)
            self.indexes.pop(project_id, None)
            self.foreign.pop(project_id, None)
            return {
                "state": self.state(project_id),
                "message": "Saved image work is now used here.",
            }

    def start_over(self, project_id, binding):
        """Moves another project's saved work aside, keeping every file."""
        with self.lock:
            self._foreign_state(project_id, binding)
            archived = foreign_work.archive(
                self.record(project_id)[1], WORK, "image-work"
            )
            for cache in (self.indexes, self.jobs, self.foreign):
                cache.pop(project_id, None)
            return {
                "state": self.state(project_id),
                "message": "Earlier image work moved to " + archived + ".",
            }

    @staticmethod
    def _preferences_revision(value):
        return digest(
            {
                "selection": value["selection"],
                "view": {**VIEW, **value["view"]},
                "discoveryScope": value["discovery"]["scope"],
                "folders": value["discovery"].get("folders", []),
                "imageRoot": (value.get("profile") or {}).get("imageRoot", ""),
            }
        )

    @staticmethod
    def _observation_revision(value):
        """What scans, reports and actions changed. The user's own choices are
        left to the preferences revision, so saving a selection or a scroll
        position does not make the manager reload its images."""
        discovery = {
            key: item
            for key, item in value["discovery"].items()
            if key not in {"scope", "folders"}
        }
        return digest(
            {
                **{
                    key: item
                    for key, item in value.items()
                    if key not in {"selection", "view", "profile", "browsed"}
                },
                "discovery": discovery,
            }
        )

    def _index(self, project_id):
        if project_id not in self.indexes:
            value = self._load(project_id)
            self.indexes[project_id] = Index(
                project_path(
                    self.record(project_id)[1],
                    WORK + "/inventory.sqlite3",
                    exists=False,
                ),
                image_folder(value),
            )
            self.indexes[project_id].selected(value["selection"])
        return self.indexes[project_id]

    def _profile(self, project_id, value=None):
        project, root = self.record(project_id)
        value = value or self._load(project_id)
        saved = value.get("profile") or {}
        return self.adapter.profile(
            root,
            project["engine"],
            saved.get("imageRoot", ""),
            saved.get("decoded", False),
        )

    def state(self, project_id):
        with self.lock:
            project, root = self.record(project_id)
            self._recover_publications(project_id)
            self._follow_checkpoints(project_id, root)
            value = self._load(project_id)
            index = self._index(project_id)
            profile = self._profile(project_id, value)
            job = deepcopy(self.jobs.get(project_id) or value.get("lastScan"))
            if job and job["status"] == "running" and project_id not in self.jobs:
                job.update(
                    status="interrupted",
                    message="The previous scan was interrupted. Refresh inventory to resume indexing.",
                )
            counts = index.counts()
            return {
                "projectId": project_id,
                "name": project["name"],
                "engine": project["engine"],
                "profile": profile,
                "source": str(root),
                "revision": self._preferences_revision(value),
                "observationRevision": self._observation_revision(value),
                "inventoryRevision": value["inventoryRevision"],
                "counts": counts,
                "investigated": _investigated(value, counts),
                "folders": index.folders(),
                "selection": deepcopy(value["selection"]),
                "view": deepcopy(value["view"]),
                "discovery": report_view(value["discovery"]),
                "editing": report_view(value["editing"]),
                "receipts": [receipt_view(row) for row in value["receipts"]],
                "warnings": deepcopy(value["warnings"]),
                **(
                    {"lastAction": deepcopy(value["lastAction"])}
                    if "lastAction" in value
                    else {}
                ),
                "editableRoot": str(root / ".dazedtl/images"),
                "supported": profile["supported"],
                "job": job,
            }

    def list(
        self,
        project_id,
        query="",
        folder="",
        filter="all",
        offset=0,
        limit=100,
        selected_only=False,
        asset_id="",
    ):
        text(query, "Search", 500)
        text(folder, "Folder", 2000)
        text(filter, "Filter", 40)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError(
                "Choose a valid image range, up to 500 images per request."
            )
        with self.lock:
            if asset_id:
                row = self._index(project_id).get(asset_id)
                return {
                    "items": [self._public(row)] if row else [],
                    "total": int(bool(row)),
                    "selectedMatched": 0,
                    "offset": 0,
                    "limit": 1,
                }
            result = self._index(project_id).list(
                query=query,
                folder=folder,
                filter=filter,
                offset=offset,
                limit=limit,
                selected_only=selected_only,
            )
            result["items"] = [self._public(row) for row in result["items"]]
            return result

    @staticmethod
    def _public(row):
        keys = (
            "id",
            "path",
            "filename",
            "folder",
            "sourceHash",
            "candidateHash",
            "sourcePngHash",
            "state",
            "classification",
            "reason",
            "blockedReason",
            "heldReason",
            "aiReviewed",
            "userReviewed",
            "destination",
            "width",
            "height",
            "mode",
            "encrypted",
            "sourceIssue",
            "candidateIssue",
            "changed",
            "staleReason",
        )
        return {
            **{key: row.get(key, "") for key in keys},
            "editable": bool(row.get("hasEditable")),
            "outdated": bool(row.get("outdated")),
            "finding": deepcopy(row.get("finding")),
            "checks": deepcopy(row.get("checks", {})),
            "reviewEvidence": (row.get("aiReview") or {}).get("evidence", ""),
            "candidateMetadata": row.get("candidateMetadata"),
            "applied": deepcopy(row.get("applied")),
        }

    def update(self, project_id, revision, changes):
        if not isinstance(changes, dict) or set(changes) - {
            "selection",
            "view",
            "discoveryScope",
            "folders",
            "discovery",
            "imageRoot",
        }:
            raise ValueError("Unknown image preference.")
        with self.lock:
            value = self._load(project_id)
            if self._preferences_revision(value) != revision:
                raise ValueError(
                    "Image progress changed. Reload before saving these choices."
                )
            if "selection" in changes:
                value["selection"] = self._ids(
                    project_id, changes["selection"], allow_empty=True
                )
            if "view" in changes:
                view = changes["view"]
                if not isinstance(view, dict) or set(view) - set(VIEW):
                    raise ValueError("Unknown image view setting.")
                for key, item in view.items():
                    if key == "workflowMode" and item not in {
                        "discovery",
                        "manual",
                        "findings",
                        "review",
                    }:
                        raise ValueError("Choose a valid image workflow view.")
                    if key in {
                        "query",
                        "status",
                        "folder",
                        "currentImage",
                        "viewedImage",
                        "workflowMode",
                    }:
                        text(item, "Image view", 2000)
                    elif key == "showSelected" and type(item) is not bool:
                        raise ValueError(
                            "Image selection filter must be enabled or disabled."
                        )
                    elif key == "tileSize" and (
                        type(item) is not int or not 72 <= item <= 240
                    ):
                        raise ValueError(
                            "Choose a thumbnail size between 72 and 240 pixels."
                        )
                    elif key == "scroll" and (
                        not isinstance(item, (int, float))
                        or isinstance(item, bool)
                        or not 0 <= item < 100_000_000
                    ):
                        raise ValueError("Invalid image scroll position.")
                if any(
                    key in BROWSING and item != value["view"].get(key)
                    for key, item in view.items()
                ):
                    value["browsed"] = True
                value["view"].update(view)
            discovery = changes.get("discovery", {})
            if not isinstance(discovery, dict) or set(discovery) - {"scope", "folders"}:
                raise ValueError("Unknown discovery preference.")
            scope = changes.get(
                "discoveryScope", discovery.get("scope", value["discovery"]["scope"])
            )
            if scope not in SCOPES:
                raise ValueError(
                    "Choose All images, Current folders, or Selected images."
                )
            value["discovery"]["scope"] = scope
            if "folders" in changes or "folders" in discovery:
                folders = changes.get("folders", discovery.get("folders"))
                if not isinstance(folders, list) or len(folders) > 1000:
                    raise ValueError("Choose a supported folder scope.")
                for folder in folders:
                    text(folder, "Discovery folder", 2000)
                value["discovery"]["folders"] = sorted(set(folders))
            if "imageRoot" in changes:
                self._image_root(project_id, value, changes["imageRoot"])
            self._save(project_id, value)
            if "selection" in changes:
                self._index(project_id).selected(value["selection"])
            return self.state(project_id)

    def _image_root(self, project_id, value, root, decoded=False):
        """Points a game without RPG Maker MV/MZ's img folder at the folder of
        loose images to index, the user's choice or, `decoded`, the folder an
        assistant decoded the game's image archives into, whose applied
        images then ship only inside the archive it packs again; the next
        scan reads it."""
        root = text(root, "Loose image folder", 2000)
        profile = self._profile(project_id, {**value, "profile": {"imageRoot": root}})
        if not profile["supported"]:
            raise ValueError(profile["reason"])
        chosen = {"imageRoot": profile["imageRoot"]}
        # Naming the folder it reads already changes nothing, even mid-scan,
        # but for the mark of a folder an assistant decoded.
        if self._profile(project_id, value)["imageRoot"] == profile["imageRoot"]:
            if decoded:
                value["profile"] = {**(value.get("profile") or {}), **chosen}
                value["profile"]["decoded"] = True
            return
        if self.jobs.get(project_id, {}).get("status") == "running":
            raise ValueError("Stop the current image scan before changing its folder.")
        self._read_from(
            project_id, value, {**chosen, **({"decoded": True} if decoded else {})}
        )

    def _read_from(self, project_id, value, profile):
        """Saves the profile whose folder Images reads. The list, its view
        and its scopes keep only the images in that folder; the others'
        rows, applied files and receipts stay, and their rows return with
        the folder. Another folder is not scanned yet: its scan records its
        inventory and groups its families."""
        value["profile"] = profile
        index = self._index(project_id)
        if index.folder != image_folder(value):
            index.folder = image_folder(value)
            value["inventoryRevision"] = ""
        value["selection"] = [
            identity for identity in value["selection"] if index.holds(identity)
        ]
        index.selected(value["selection"])
        if value["view"].get("folder") and not index.holds(value["view"]["folder"]):
            value["view"]["folder"] = ""
        value["discovery"]["folders"] = [
            folder for folder in value["discovery"]["folders"] if index.holds(folder)
        ]

    def _ids(self, project_id, identities, *, allow_empty=False):
        if (
            not isinstance(identities, list)
            or len(identities) > 100_000
            or any(not isinstance(item, str) for item in identities)
        ):
            raise ValueError("Choose image asset IDs from this project's inventory.")
        identities = list(dict.fromkeys(identities))
        if not identities and not allow_empty:
            raise ValueError(
                "Tick at least one image first. An empty list never applies all images."
            )
        index = self._index(project_id)
        with index.connection() as db:
            if any(
                not index.holds(identity) or index.get(identity, db) is None
                for identity in identities
            ):
                raise ValueError(
                    "An image is no longer in this project's inventory. Refresh the asset list."
                )
        return identities

    def _chosen(self, project_id, options):
        return self._ids(
            project_id, options.get("asset_ids", self._load(project_id)["selection"])
        )

    def resolve_assets(self, project_id, asset_ids):
        with self.lock:
            _project, root = self.record(project_id)
            ids = self._ids(project_id, asset_ids)
            self.refresh_assets(project_id, ids)
            index = self._index(project_id)
            rows = [index.get(identity) for identity in ids]
            return [
                {
                    **row,
                    "editablePath": str(
                        project_path(root, row["editable"], exists=False)
                    ),
                    "frozenPath": str(project_path(root, row["frozen"], exists=False))
                    if row.get("frozen")
                    else "",
                }
                for row in rows
            ]

    editor_assets = resolve_assets

    def _status(self, row):
        candidate = row.get("candidateMetadata") or {}
        original = row.get("originalMetadata") or {
            key: row.get(key)
            for key in ("width", "height", "mode", "transparency", "frames")
        }
        issues = [
            row.get(key, "")
            for key in (
                "sourceIssue",
                "candidateIssue",
                "collisionIssue",
                "originalIssue",
            )
            if row.get(key)
        ]
        checks = {
            "png": bool(row.get("candidateHash")),
            "dimensions": candidate.get("width") == original.get("width")
            and candidate.get("height") == original.get("height"),
            "mode": candidate.get("mode") == original.get("mode"),
            "transparency": candidate.get("transparency")
            == original.get("transparency"),
            "frames": candidate.get("frames") == original.get("frames"),
        }
        if row.get("hasEditable"):
            issues += [
                "The edited image's " + key + " differs from the original."
                for key in ("dimensions", "mode", "transparency", "frames")
                if not checks[key]
            ]
        source_changed = bool(
            row.get("originalRuntimeHash")
            and row.get("sourceHash") != row["originalRuntimeHash"]
            and row.get("sourceHash") != (row.get("applied") or {}).get("runtimeHash")
        )
        if source_changed:
            issues.append(
                "The runtime source changed after this working copy was prepared. Resolve the source conflict first."
            )
        # A copy made from an older source is outdated rather than broken when
        # nothing else blocks it.
        row["outdated"] = source_changed and len(issues) == 1
        binding = {
            "sourceHash": row.get("sourceHash"),
            "candidateHash": row.get("candidateHash"),
        }
        ai = row.get("aiReview") or {}
        user = row.get("userReview") or {}
        proof = row.get("proof") or {}
        # An assistant review that needs a recipe counts once the recipe and
        # validation of this exact edit pass; until then their reason shows.
        held = (
            ai.get("proof")
            and all(ai.get(key) == item for key, item in binding.items())
            and not (
                all(proof.get(key) == item for key, item in binding.items())
                and proof.get("ok")
            )
        )
        row["aiReviewed"] = (
            ai.get("version") == REVIEW_VERSION
            and all(ai.get(key) == item for key, item in binding.items())
            and bool(ai.get("evidence"))
            and not held
        )
        row["heldReason"] = (
            proof.get("reason") or "Its recipe and validation are not saved."
            if held
            else ""
        )
        row["userReviewed"] = (
            user.get("version") == REVIEW_VERSION
            and all(user.get(key) == item for key, item in binding.items())
            and bool(user.get("reviewed"))
        )
        row["changed"] = bool(
            row.get("candidateHash")
            and row.get("candidateHash")
            != row.get("originalPngHash", row.get("sourcePngHash"))
        )
        row["checks"] = checks
        row["reason"] = (row.get("manualOverride") or row.get("finding") or {}).get(
            "reason", row.get("staleReason", "")
        )
        if row.get("manualOverrideStale"):
            row["reason"] += (
                " Source changed; the manual exclusion is retained, but its investigation is stale."
            )
        if issues:
            row["state"], row["blockedReason"] = (
                "blocked",
                "; ".join(dict.fromkeys(issues)),
            )
        elif (
            row["classification"] == "excluded"
            or (row.get("editResult") or {}).get("status") == "skipped"
        ):
            row["state"], row["blockedReason"] = "skipped", ""
        elif row.get("candidateHash") == (row.get("applied") or {}).get(
            "candidateHash"
        ) and row.get("sourceHash") == (row.get("applied") or {}).get("runtimeHash"):
            row["state"], row["blockedReason"] = "applied", ""
        elif not row.get("hasEditable"):
            row["state"], row["blockedReason"] = (
                "not_prepared",
                "Make this image editable before starting image work.",
            )
        elif not row.get("frozen"):
            # An edited copy placed without Prepare has no preserved original,
            # so Apply could not keep the game's image to restore.
            row["state"], row["blockedReason"] = (
                "not_prepared",
                "Prepare this image first so its original is kept.",
            )
        elif not row.get("changed"):
            row["state"], row["blockedReason"] = (
                "editable",
                "No edited output is saved yet.",
            )
        elif row["aiReviewed"] or row["userReviewed"]:
            row["state"], row["blockedReason"] = "ready", ""
        else:
            row["state"], row["blockedReason"] = (
                "needs_review",
                row["heldReason"] or "Compare the edited copy, then mark it reviewed.",
            )
        # A held review explains only an image still waiting for review, not
        # one the user reviewed, applied or that is blocked for another reason.
        if row["state"] != "needs_review":
            row["heldReason"] = ""
        return row

    def _inspect(self, project_id, row, old=None, key=None):
        _project, root = self.record(project_id)
        if row.get("encrypted") and key is None:
            key = self.adapter.key(root, self._profile(project_id))
        result = inspect_row(root, self.adapter, row, old, key)
        if result.get("frozen"):
            try:
                original = project_path(root, result["frozen"])
                if sha_file(original) != result.get("originalPngHash"):
                    raise ValueError(
                        "The preserved original image changed. Recover it before reviewing or applying this candidate."
                    )
                # Images prepared before restores read Git kept a copy.
                if result.get("runtimeBackup") and sha_file(
                    project_path(root, result["runtimeBackup"])
                ) != result.get("runtimeBackupHash"):
                    raise ValueError(
                        "The preserved original runtime backup changed. Recover it before applying this candidate."
                    )
                result["originalIssue"] = ""
            except (OSError, ValueError) as exc:
                result["originalIssue"] = str(exc)
        restored = result.get("restored")
        if (
            restored
            and not result.get("applied")
            and result.get("sourceHash") == restored.get("runtimeHash")
        ):
            # The game holds the applied image again, as when Restore
            # originals' checkpoint is undone.
            result["applied"] = result.pop("restored")
        return self._status(result)

    def refresh_assets(self, project_id, asset_ids):
        with self.lock:
            index = self._index(project_id)
            key = self.adapter.key(
                self.record(project_id)[1], self._profile(project_id)
            )
            changed = False
            with index.connection() as db:
                for identity in self._ids(project_id, asset_ids):
                    old = index.get(identity, db)
                    row = self._inspect(project_id, old, old, key)
                    if row != old:
                        index.put(db, row, old.get("generation", ""))
                        changed = True
            if changed:
                self._touch(project_id)

    def recheck(self, project_id):
        """Reinspects the images being worked on, which an outside editor can
        change: working copies, the selection and applied images.

        Runs when the window regains focus. Unchanged files keep their cached
        hashes, and other images wait for the next scan. A running scan or
        image operation sees its own files, so it is left alone.
        """
        with self.lock:
            self.record(project_id)
            checked = self._reinspect(project_id)
            if checked is None:
                return 0
            self._pickup(project_id)
            return checked

    def _reinspect(self, project_id):
        """Reinspects working copies, the selection and the images applied
        or restored, and counts them; None while nothing is worked on here
        yet or a running scan or image operation owns its files."""
        try:
            value = self._load(project_id)
        except ForeignWorkError:
            return None  # Nothing is worked on here until the user chooses.
        if (
            project_id in self.mutating
            or self.jobs.get(project_id, {}).get("status") == "running"
            or not value["inventoryRevision"]
        ):
            return None
        selected = set(value["selection"])
        identities = [
            row["id"]
            for row in self._index(project_id).rows()
            if row.get("hasEditable")
            or row.get("applied")
            or row.get("restored")
            or row["id"] in selected
        ]
        if identities:
            self.refresh_assets(project_id, identities)
        return len(identities)

    def _follow_checkpoints(self, project_id, root):
        """Whether an image is applied reads from its file, which undoing or
        going back past a checkpoint changes; so the images are inspected
        again once the game's checkpoints move."""
        mark = repository_signature(root)
        if mark is None or self.checkpoints.get(project_id) == mark:
            return
        try:
            checked = self._reinspect(project_id)
        except OSError, ValueError, sqlite3.Error:
            # An image it can't read now is checked again on the next read.
            return
        if checked is not None:
            self.checkpoints[project_id] = mark

    def _pickup(self, project_id):
        """Imports reports an assistant saved for a copied task, validated as
        Check for results does. A finished task's report is read again when
        the assistant saves it again, as it does for the user's redo requests.
        A rejected report is remembered by its hash, so it is reported once and
        not retried until the file changes."""
        for kind in ("discovery", "editing"):
            value = self._load(project_id)
            task = value[kind]
            if task.get("status") not in {"awaiting_results", "partial", "complete"}:
                continue
            entry = value["requests"].get(task.get("requestId"))
            # Another project's task reports only after it is copied again here.
            if not entry or entry.get("carried"):
                continue
            path = self._report_path(project_id, task["requestId"])
            if not path.is_file():
                continue
            saved = sha_file(path)
            if saved in {task.get("reportHash"), task.get("rejectedHash")}:
                continue
            try:
                self._refresh_report(project_id, kind)
            except (ValueError, OSError) as exc:
                value = self._load(project_id)
                value[kind].update(rejected=str(exc), rejectedHash=saved)
                self._save(project_id, value)

    def _touch(self, project_id):
        value = self._load(project_id)
        value["indexRevision"] = value.get("indexRevision", 0) + 1
        self._save(project_id, value)

    def _recover_publications(self, project_id):
        """Reconcile only exact bytes authorized by a pre-publication journal."""
        if project_id in self.mutating:
            return
        value = self._load(project_id)
        pending = value.get("pendingPublications", {})
        if not pending:
            return
        root, index = self.record(project_id)[1], self._index(project_id)
        for identity, binding in list(pending.items()):
            if not isinstance(binding, dict) or set(binding) != {"path", "hash"}:
                raise ValueError(
                    "A pending image approval lacks valid integrity evidence. Its journal was retained."
                )
            relative = binding["path"]
            journal = read_json(project_path(root, relative), limit=48_000_000)
            if (
                journal.get("version") != 1
                or journal.get("projectId") != project_id
                or journal.get("id") != identity
                or journal.get("action") not in {"apply", "restore"}
            ):
                raise ValueError(
                    "A pending image publication journal is invalid. Preserve it before recovery."
                )
            if self._journal_binding(journal) != binding["hash"]:
                raise ValueError(
                    "A pending image approval journal changed. No recovery receipt was manufactured; preserve and inspect its original record."
                )
            changed, original, conflicts = [], [], []
            with index.connection() as db:
                for frozen in journal["assets"]:
                    row = index.get(frozen["id"], db)
                    if not row or row.get("runtime") != frozen["runtime"]:
                        conflicts.append(frozen["id"])
                        continue
                    try:
                        actual = sha_file(project_path(root, frozen["runtime"]))
                    except ValueError, OSError:
                        conflicts.append(frozen["id"])
                        continue
                    if actual == frozen["expectedRuntimeHash"]:
                        changed.append(frozen["id"])
                        if journal["action"] == "apply":
                            row.pop("restored", None)
                            row["applied"] = {
                                "candidateHash": frozen["candidateHash"],
                                "runtimeHash": actual,
                                "sourceHash": frozen["sourceHash"],
                                "saved": journal["saved"],
                                "review": frozen["review"],
                                "recovered": True,
                            }
                        else:
                            _set_aside(row)
                            row.pop("aiReview", None)
                            row.pop("userReview", None)
                            row["originalRuntimeHash"] = actual
                        row = self._inspect(project_id, row, row)
                        index.put(db, row, row.get("generation", ""))
                    elif actual == frozen["sourceHash"]:
                        original.append(frozen["id"])
                    else:
                        conflicts.append(frozen["id"])
                        row["sourceIssue"] = (
                            "Runtime bytes differ from both sides of the interrupted publication. Resolve this conflict before applying."
                        )
                        index.put(db, self._status(row), row.get("generation", ""))
            status = (
                "recovered" if len(changed) == len(journal["assets"]) else "interrupted"
            )
            receipt = {
                "id": identity,
                "action": journal["action"],
                "assets": [row["id"] for row in journal["assets"]],
                "saved": now(),
                "status": status,
                "completed": len(changed),
                "unchanged": len(original),
                "conflicts": conflicts,
                "errors": journal.get("errors", []),
                "message": "Recovered exact reviewed publication bytes."
                if status == "recovered"
                else "Publication was interrupted. Restore originals puts back the images it published; review recovery before continuing.",
            }
            journal.update(status=status, recoveredAt=now(), receipt=receipt)
            write_json(project_path(root, relative), journal)
            value["receipts"] = [
                row for row in value["receipts"] if row["id"] != identity
            ] + [receipt]
            value["receipts"] = value["receipts"][-200:]
            value["lastAction"] = receipt
            pending.pop(identity)
            if status == "interrupted":
                warning = (
                    "An image "
                    + journal["action"]
                    + " was interrupted: "
                    + str(len(changed))
                    + " published, "
                    + str(len(conflicts))
                    + " conflicts. Review its saved recovery receipt."
                )
                if warning not in value["warnings"]:
                    value["warnings"].append(warning)
        value["pendingPublications"] = pending
        self._save(project_id, value)

    @staticmethod
    def _journal_binding(journal):
        return digest(
            {
                key: journal[key]
                for key in ("version", "id", "projectId", "action", "saved", "assets")
            }
        )

    def _scan(self, project_id):
        with self.lock:
            if project_id in self.mutating:
                raise ValueError(
                    "Finish the current image operation before scanning again."
                )
            for event in self.cancellations.values():
                event.set()
            event = threading.Event()
            self.cancellations[project_id] = event
            generation = uuid.uuid4().hex
            value = self._load(project_id)
            profile = self._profile(project_id, value)
            if not profile["supported"]:
                raise ValueError(profile["reason"])
            self._read_from(project_id, value, profile)
            self._save(project_id, value)
            self.jobs[project_id] = {
                "id": generation,
                "action": "scan",
                "status": "running",
                "indexed": 0,
                "message": "Indexing image metadata. AI discovery has not started.",
            }
            value["lastScan"] = deepcopy(self.jobs[project_id])
            self._save(project_id, value)
            worker = threading.Thread(
                target=self._scan_worker,
                args=(project_id, generation, event, profile),
                daemon=True,
            )
            self.threads[generation] = worker
            worker.start()

    def _scan_worker(self, project_id, generation, event, profile):
        try:
            _project, root = self.record(project_id)
            index, seen, case_paths, collision_ids = (
                self._index(project_id),
                set(),
                {},
                set(),
            )
            key = self.adapter.key(root, profile)
            batch = {}
            for entry in self.adapter.inventory(root, profile, event.is_set):
                if event.is_set():
                    break
                identity = entry["id"]
                old = batch.get(identity) or index.get(identity)
                if not entry["runtime"] and old and old.get("runtime"):
                    entry = {
                        **entry,
                        "runtime": old["runtime"],
                        "destination": old["destination"],
                        "encrypted": old["encrypted"],
                    }
                if (
                    identity in seen
                    and entry.get("runtime")
                    and old
                    and old.get("encrypted")
                    and not entry["encrypted"]
                ):
                    entry = {
                        **entry,
                        "runtime": old["runtime"],
                        "destination": old["destination"],
                        "encrypted": True,
                    }
                folded = identity.casefold()
                if folded in case_paths and case_paths[folded] != identity:
                    collision_ids.update((identity, case_paths[folded]))
                case_paths[folded] = identity
                entry["collisionIssue"] = ""
                row = self._inspect(project_id, entry, old, key)
                row["generation"] = generation
                batch[identity] = row
                seen.add(identity)
                if len(batch) >= 64:
                    self._scan_batch(
                        project_id, generation, list(batch.values()), len(seen)
                    )
                    batch = {}
            if batch:
                self._scan_batch(
                    project_id, generation, list(batch.values()), len(seen)
                )
            with self.lock:
                if self.jobs.get(project_id, {}).get("id") != generation:
                    return
                if not event.is_set():
                    with index.connection() as db:
                        within, values = index.within()
                        for record in db.execute(
                            "SELECT data FROM assets WHERE generation!=? AND " + within,
                            (generation, *values),
                        ).fetchall():
                            row = json.loads(record[0])
                            row.update(
                                runtime="",
                                sourceHash="",
                                sourceIssue="Runtime source not found during the latest scan.",
                            )
                            index.put(db, self._status(row), generation)
                        for identity in collision_ids:
                            row = index.get(identity, db)
                            row["collisionIssue"] = (
                                "These filenames differ only by letter case and cannot be patched safely on Windows."
                            )
                            index.put(db, self._status(row), generation)
                    # Variant families are grouped over the folder's whole
                    # inventory, so only a complete scan regroups them.
                    index.refresh_families()
                    value = self._load(project_id)
                    fingerprint = hashlib.sha256()
                    for row in index.rows():
                        fingerprint.update(
                            (
                                row["id"] + "\0" + row.get("sourceHash", "") + "\n"
                            ).encode()
                        )
                    value["inventoryRevision"] = fingerprint.hexdigest()
                    self._save(project_id, value)
                index.selected(self._load(project_id)["selection"])
                self.jobs[project_id].update(
                    status="stopped" if event.is_set() else "complete",
                    indexed=len(seen),
                    message="Scan stopped. Indexed images remain available; unscanned coverage is incomplete."
                    if event.is_set()
                    else "Image inventory saved. Copy a discovery task to investigate text.",
                )
                value = self._load(project_id)
                value["lastScan"] = deepcopy(self.jobs[project_id])
                self._save(project_id, value)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                if self.jobs.get(project_id, {}).get("id") == generation:
                    self.jobs[project_id].update(status="error", message=str(exc))

    def _scan_batch(self, project_id, generation, rows, count):
        with self.lock:
            if self.jobs.get(project_id, {}).get("id") != generation:
                return
            with self._index(project_id).connection() as db:
                for row in rows:
                    Index.put(db, row, generation)
            self.jobs[project_id]["indexed"] = count
            self.jobs[project_id]["current"] = count
            self._touch(project_id)

    def _idle(self, project_id):
        if self.jobs.get(project_id, {}).get("status") == "running":
            raise ValueError(
                "Finish or stop the image scan before changing this image batch."
            )
        if hasattr(self.translation, "idle"):
            self.translation.idle(project_id)
        if project_id in self.mutating:
            raise ValueError("An image operation is already in progress.")

    def action(self, project_id, action, options=None):
        options = options or {}
        if not isinstance(options, dict):
            raise ValueError("Image action options must be an object.")
        with self.lock:
            self.record(project_id)
            if action == "scan":
                self._scan(project_id)
                return {"state": self.state(project_id)}
            if action == "stop_scan":
                event = self.cancellations.get(project_id)
                if event:
                    event.set()
                return {"state": self.state(project_id)}
            if action == "select_matching":
                filters = {
                    key: options.get(key, default)
                    for key, default in (
                        ("query", ""),
                        ("folder", ""),
                        ("filter", "all"),
                        ("selected_only", False),
                    )
                }
                ids = [row["id"] for row in self._index(project_id).rows(**filters)]
                value = self._load(project_id)
                mode = options.get("mode")
                if mode == "remove":
                    removed = set(ids)
                    selected = [
                        identity
                        for identity in value["selection"]
                        if identity not in removed
                    ]
                else:
                    selected = (
                        list(dict.fromkeys(value["selection"] + ids))
                        if mode == "add"
                        else ids
                    )
                value["selection"] = selected
                self._save(project_id, value)
                self._index(project_id).selected(selected)
                return {"state": self.state(project_id)}
            # While a copied task waits, the manager looks for its report.
            if action == "pickup":
                self._pickup(project_id)
                return {"state": self.state(project_id)}
            self._idle(project_id)
            if action in {"discovery_task", "edit_task", "revision_task"}:
                return self._task(project_id, action, options)
            elif action == "stop_investigation":
                return self._stop_investigation(project_id)
            elif action in {"refresh_findings", "refresh_results"}:
                return self._refresh_report(
                    project_id,
                    "discovery" if action == "refresh_findings" else "editing",
                )
            elif action == "prepare":
                return self._prepare(project_id, options)
            elif action in {"user_review", "exclude", "include"}:
                self._review(project_id, action, options)
            elif action == "remove_copies":
                self._remove(project_id, options)
            elif action in {"preview_apply", "preview_restore"}:
                return self._preview_mutation(
                    project_id, action.removeprefix("preview_"), options
                )
            elif action in {"apply", "restore"}:
                return self._execute(project_id, action, options)
            else:
                raise ValueError("Unknown image action.")
            return {"state": self.state(project_id)}

    def assistant(self, project_id, step, root=None):
        """Runs one Images step for an Assistant-led project's own assistant,
        which also does the user's part: its recommendations stay the list,
        and it applies the images it translated and reviewed. `root`, with
        the scan, names the game-relative folder it decoded the game's image
        archives into, which the steps then read and write instead."""
        if step not in ASSISTANT_STEPS:
            raise ValueError(
                "Choose an image step: " + ", ".join(ASSISTANT_STEPS) + "."
            )
        if root is not None:
            if step != "scan":
                raise ValueError("Name an image folder with images --scan only.")
            if self.record(project_id)[0]["engine"] == "MVMZ":
                raise ValueError(
                    "RPG Maker MV/MZ images are read from the game's img folder; "
                    "run images --scan without --root."
                )
            with self.lock:
                value = self._load(project_id)
                self._image_root(project_id, value, root, decoded=True)
                self._save(project_id, value)
        profile = self.state(project_id)["profile"]
        if not profile["supported"]:
            raise ValueError(
                profile["reason"]
                + " Decode the game's images into it again, or name another folder with images --scan --root <folder>."
                if profile["imageRoot"]
                else "DazedTL found no folder of loose images in this game. If its "
                "images sit in archives, decode them with Len's tools into a "
                "folder in the game and run images --scan --root <folder>."
            )
        task, result = None, None
        # An investigation the user stopped to choose the images stays stopped.
        stopped = _stopped(self._load(project_id))
        if step == "scan":
            if (self.state(project_id)["job"] or {}).get("status") != "running":
                self.action(project_id, "scan")
        else:
            self.action(project_id, "pickup")
            if step == "investigate" and not stopped:
                task = self.action(
                    project_id,
                    "discovery_task",
                    {"scope": "remaining", "assistant": True},
                )
            elif step == "translate":
                task = self.action(project_id, "edit_task", {"assistant": True})
            elif step == "apply":
                review = self.action(project_id, "preview_apply", {"ready_only": True})[
                    "preview"
                ]
                result = self.action(project_id, "apply", {"token": review["token"]})[
                    "result"
                ]
        state = self.state(project_id)
        value = self._load(project_id)
        counts = state["counts"]
        listed = counts["selected"]
        waiting = {
            kind: state[kind].get("status") in {"awaiting_results", "partial"}
            for kind in ("discovery", "editing")
        }
        untranslated = listed - counts["selectedApplied"] - counts["selectedSkipped"]
        next_step = (
            "scan"
            if (state["job"] or {}).get("status") == "running"
            or not state["inventoryRevision"]
            else "investigate"
            if waiting["discovery"] or not self._settled(project_id, value)
            else "apply"
            if counts["selectedReady"]
            else "translate"
            if waiting["editing"] or untranslated
            else "done"
        )
        view = {
            "next": next_step,
            "scan": (state["job"] or {}).get("status", ""),
            "investigation": state["discovery"].get("status", "idle"),
            "translation": state["editing"].get("status", "idle"),
            "problems": [
                *(
                    [USER_CHOSE]
                    if (stopped and step == "investigate")
                    or self._stopped_save(project_id, value)
                    else []
                ),
                *state["discovery"].get("errors", []),
                *state["editing"].get("errors", []),
                *[
                    state[kind]["rejected"]
                    for kind in ("discovery", "editing")
                    if state[kind].get("rejected")
                ],
            ],
            "counts": {
                "indexed": counts["indexed"],
                "notExamined": counts["notExamined"],
                "recommended": counts["recommended"],
                "uncertain": counts["uncertain"],
                "listed": listed,
                "ready": counts["selectedReady"],
                "needsReview": counts["selectedNeedsReview"],
                "skipped": counts["selectedSkipped"],
                "applied": counts["selectedApplied"],
            },
            "task": "",
            "report": "",
            "applied": [],
        }
        ticked = set(state["selection"])
        view["problems"].extend(
            row["id"] + ": " + row["heldReason"]
            for row in self._index(project_id).rows()
            if row["id"] in ticked
            and row.get("heldReason")
            and row["state"] == "needs_review"
        )
        if task:
            # The task's text embeds the image skill; a file keeps it out of
            # the helper's printed reply.
            path = Path(str(task["request"])).with_suffix(".md")
            write_bytes(path, str(task["text"]).encode("utf-8"))
            view.update(task=str(path), report=str(task["report"]))
            if task.get("message"):
                view["problems"].append(str(task["message"]))
        if result:
            view["applied"] = list(result.get("patch_files", []))
            view["problems"].extend(result.get("errors", []))
        return view

    def _stop_investigation(self, project_id):
        """The user chooses the images to translate instead of waiting for the
        investigation. What its report saved so far is read once more and
        kept; then the request is closed, as an adopted project's are: a later
        save is not read, refreshing it is refused, and copying the
        investigation again starts a new one instead of resuming it."""
        value = self._load(project_id)
        if value["discovery"].get("status") not in {"awaiting_results", "partial"}:
            raise ValueError("No image investigation is waiting.")
        self._pickup(project_id)
        value = self._load(project_id)
        task = value["discovery"]
        # A report that answered everything finished the investigation.
        if task["status"] == "complete":
            return {
                "state": self.state(project_id),
                "message": "Your assistant had finished; its recommendations are ticked.",
            }
        # The report as it was last read, accepted or not; a save after it is
        # one the assistant made after the stop.
        task.update(
            status="stopped",
            stoppedAt=now(),
            stoppedHash=task.get("rejectedHash") or task.get("reportHash") or "",
            errors=[],
        )
        task.pop("rejected", None)
        task.pop("rejectedHash", None)
        self._save(project_id, value)
        return {
            "state": self.state(project_id),
            "message": "Investigation stopped. What it found is kept.",
        }

    def _report_path(self, project_id, request_id):
        return project_path(
            self.record(project_id)[1],
            WORK + "/reports/" + request_id + ".json",
            exists=False,
        )

    def _stopped_save(self, project_id, value):
        """Whether the assistant saved its report again after the user stopped
        its investigation, which is then not read."""
        task = value["discovery"]
        if not _stopped(value):
            return False
        report = self._report_path(project_id, task["requestId"])
        return report.is_file() and sha_file(report) != task.get("stoppedHash")

    def _settled(self, project_id, value):
        """Whether the list to translate is settled: every image is
        investigated, or the user stopped the investigation to choose the
        images themselves."""
        return _stopped(value) or _investigated(value, self._index(project_id).counts())

    def progress_units(self, project_id):
        """The Images flow as Len image progress records: each image in the
        list, or already applied, counts until it is applied, except one its
        translation skipped. None when this engine has no image profile."""
        with self.lock:
            value = self._load(project_id)
            if not self._profile(project_id, value)["supported"]:
                return None
            root = self.record(project_id)[1]
            listed = set(value["selection"])
            units = []
            for row in self._index(project_id).rows():
                applied = row["state"] == "applied"
                if not applied and (
                    row["id"] not in listed or row["state"] == "skipped"
                ):
                    continue
                # An applied image counts from its preserved original; any
                # other from the untouched game file.
                source = next(
                    (
                        relative
                        for relative in (
                            (row.get("frozen"), row.get("runtimeBackup"))
                            if applied
                            else (row.get("runtime"),)
                        )
                        if relative
                        and project_path(root, relative, exists=False).is_file()
                    ),
                    None,
                )
                if not source:
                    continue
                unit = {"id": row["id"], "source": source, "translation": None}
                if applied:
                    unit.update(
                        translation=row["editable"],
                        translated_from_sha256=sha_file(project_path(root, source)),
                    )
                units.append(unit)
            return {
                "complete": bool(value["inventoryRevision"])
                and self._settled(project_id, value),
                "units": units,
            }

    def _scope(self, project_id, options, value):
        scope = options.get("scope", value["discovery"]["scope"])
        if scope not in SCOPES:
            raise ValueError("Choose All images, Current folders, or Selected images.")
        if scope == "selected":
            return scope, self._chosen(project_id, options)
        # Images not yet examined; applied and excluded ones are settled.
        if scope == "remaining":
            identities = [
                row["id"] for row in self._index(project_id).rows(filter="remaining")
            ]
            if not identities:
                raise ValueError("Every image has been investigated.")
            return scope, self._ids(project_id, identities)
        # Investigating all images again leaves out the settled ones: images
        # in the game and the user's own exclusions.
        if scope == "all":
            identities = [
                row["id"]
                for row in self._index(project_id).rows()
                if row["state"] != "applied" and not row.get("manualOverride")
            ]
            if not identities:
                raise ValueError("Every image is already in the game.")
            return scope, self._ids(project_id, identities)
        folders = options.get("folders", value["discovery"].get("folders", []))
        if scope == "folders" and not folders:
            raise ValueError("Choose at least one discovery folder.")
        identities = [
            row["id"]
            for row in self._index(project_id).rows()
            if any(
                row["folder"] == folder.rstrip("/")
                or row["folder"].startswith(folder.rstrip("/") + "/")
                for folder in folders
            )
        ]
        return scope, self._ids(project_id, identities)

    def _guidance(self, project_id):
        if hasattr(self.translation, "clean_drafts"):
            self.translation.clean_drafts(project_id)
        _project, root = self.record(project_id)
        names = [
            ".dazedtl/glossary.txt",
            ".dazedtl/skills/game.md",
            ".dazedtl/skills/quirks.md",
        ]
        if hasattr(self.translation, "documents"):
            names = [
                Path(row["path"]).relative_to(root).as_posix()
                for row in self.translation.documents(project_id).values()
            ]
        result = {}
        for name in names:
            path = project_path(root, name, exists=False)
            if path.exists():
                result[name] = sha_file(path)
        return result

    def _task(self, project_id, action, options):
        value = self._load(project_id)
        if not value["inventoryRevision"]:
            raise ValueError("Finish an image scan before preparing an assistant task.")
        kind = "discovery" if action == "discovery_task" else "editing"
        own = options.get("assistant") is True
        scope, identities = (
            self._scope(project_id, options, value)
            if kind == "discovery"
            else ("selected", self._chosen(project_id, options))
        )
        self.refresh_assets(project_id, identities)
        value = self._load(project_id)
        rows = [self._index(project_id).get(identity) for identity in identities]
        message = ""
        if kind == "editing":
            # The list's images not yet in the game. Their editable copies are
            # made here, so copying the task is the user's only step.
            rows = [row for row in rows if row["state"] not in {"applied", "skipped"}]
            if not rows:
                raise ValueError("Every image in your list is already in the game.")
            unprepared = [
                row["id"]
                for row in rows
                if not row.get("frozen")
                and not row.get("sourceIssue")
                and not row.get("originalIssue")
            ]
            if unprepared:
                self._prepare(project_id, {"asset_ids": unprepared})
                value = self._load(project_id)
                rows = [self._index(project_id).get(row["id"]) for row in rows]
            blocked = [
                row
                for row in rows
                if not row.get("hasEditable")
                or row.get("sourceIssue")
                or row.get("originalIssue")
            ]
            rows = [row for row in rows if row not in blocked]
            if not rows:
                raise ValueError(
                    "These images can't be edited: "
                    + (blocked[0].get("blockedReason") or blocked[0]["id"])
                )
            if blocked:
                message = (
                    f"Left out {len(blocked)} image{'' if len(blocked) == 1 else 's'}"
                    " that can't be edited; Blocked lists why."
                )
        _project, root = self.record(project_id)
        comments = text(
            options.get("comments", options.get("comment", "")),
            "Revision comments",
            40_000,
        )
        guidance = self._guidance(project_id)
        previous_id = value[kind].get("requestId", "")
        # An investigation asked for again starts over: a finished one, or one
        # the user stopped, is neither handed out again nor resumed.
        if kind == "discovery" and value[kind].get("status") in {"complete", "stopped"}:
            previous_id = ""
        previous_entry = value["requests"].get(previous_id)
        # A task taken over from another project is resumed, never handed out again.
        if previous_entry and not previous_entry.get("carried"):
            previous_path = project_path(root, previous_entry["path"])
            previous = read_json(previous_path, limit=48_000_000)

            def basis(request, assets, versions):
                return Basis(
                    versions,
                    {
                        "inventory": request.get("inventoryRevision"),
                        **{row["id"]: row["sourceHash"] for row in assets},
                    },
                    digest(
                        [
                            request.get(key, "")
                            for key in ("kind", "scope", "guidance", "revisionComments")
                        ]
                    ),
                )

            # A request names the game's folder for the assistant's tools, so
            # one copied before the game moved is copied again.
            if (
                digest(previous) == previous_entry["hash"]
                and previous.get("source") == str(root)
                and not compare(
                    basis(
                        previous,
                        previous.get("assets", []),
                        (previous.get("reviewVersion"), previous.get("recipeVersion")),
                    ),
                    basis(
                        {
                            "inventoryRevision": value["inventoryRevision"],
                            "kind": kind,
                            "scope": scope,
                            "guidance": guidance,
                            "revisionComments": comments,
                        },
                        rows,
                        (REVIEW_VERSION, RECIPE_VERSION if kind == "editing" else None),
                    ),
                )
            ):
                value[kind]["copiedAt"] = now()
                value[kind].pop("rejected", None)
                self._save(project_id, value)
                return {
                    "state": self.state(project_id),
                    **({"message": message} if message else {}),
                    "text": self._task_text(project_id, previous, previous_path, own),
                    "requestId": previous_id,
                    "request": str(previous_path),
                    "report": previous["report"],
                    "handoff": self._handoff(kind, previous_id, previous["report"]),
                }
        identity = uuid.uuid4().hex
        report = project_path(
            root, WORK + "/reports/" + identity + ".json", exists=False
        )
        # The assistant saves its report there.
        report.parent.mkdir(parents=True, exist_ok=True)
        # Each file's hash sits beside its path: sourceHash is the runtime
        # file's, encrypted where the game encrypts, and frozenHash the PNG
        # the app preserved from it. editableHash is the working copy's when
        # the task was made; a report gives its final hash as candidateHash.
        names = {"frozenHash": "originalPngHash", "editableHash": "candidateHash"}
        index = self._index(project_id)
        assets = [
            {
                key: row.get(names.get(key, key))
                for key in (
                    "id",
                    "path",
                    "runtime",
                    "sourceHash",
                    "encrypted",
                    "frozen",
                    "frozenHash",
                    "editable",
                    "editableHash",
                    "width",
                    "height",
                    "mode",
                    "sourceIssue",
                )
            }
            # Siblings that share this image's backdrop, with their originals
            # and how far each is translated.
            | {"family": index.family(row["id"])}
            for row in rows
        ]
        request = {
            "version": 1,
            "kind": kind,
            "id": identity,
            "projectId": project_id,
            "source": str(root),
            "inventoryRevision": value["inventoryRevision"],
            "created": now(),
            "scope": scope,
            "assets": assets,
            "guidance": guidance,
            "report": str(report),
            "reviewVersion": REVIEW_VERSION,
            **({"recipeVersion": RECIPE_VERSION} if kind == "editing" else {}),
            "revisionComments": comments,
            "resumeFrom": previous_id,
            "resumeRequest": value["requests"].get(previous_id, {}).get("path", ""),
            "resumeReport": WORK + "/reports/" + previous_id + ".json"
            if previous_id
            else "",
        }
        request_path = project_path(
            root, WORK + "/requests/" + identity + ".json", exists=False
        )
        write_json(request_path, request)
        value["requests"][identity] = {
            "kind": kind,
            "path": request_path.relative_to(root).as_posix(),
            "hash": digest(request),
        }
        value[kind].update(
            status="awaiting_results",
            requestId=identity,
            lastReport="",
            errors=[],
            copiedAt=now(),
            scope=scope,
        )
        value[kind].pop("rejected", None)
        value[kind].pop("rejectedHash", None)
        self._save(project_id, value)
        return {
            "state": self.state(project_id),
            **({"message": message} if message else {}),
            "text": self._task_text(project_id, request, request_path, own),
            "requestId": identity,
            "request": str(request_path),
            "report": str(report),
            "handoff": self._handoff(kind, identity, report),
        }

    @staticmethod
    def _handoff(kind, request_id, report):
        """What a copied task hands to the assistant and expects back."""
        return {
            "kind": "image_" + kind,
            "requestId": request_id,
            "expects": [str(report)],
        }

    def _task_text(self, project_id, request, request_path, own=False):
        root = self.record(project_id)[1]
        # Assistant-led's own assistant read the note in its starting prompt.
        contract = ("" if own else windows_note()) + self._contract(
            request, request_path, own, language_pair.pair(self.settings, root)
        )
        if request["kind"] == "editing":
            skill = self.adapter.skill(root, self._profile(project_id))
            # The Qt template assumes every PNG is scoped. Replace that statement before delegation.
            skill = skill.replace("every PNG", "each requested PNG").replace(
                "Every PNG", "Each requested PNG"
            )
            # What kept the last results from being accepted, so a task copied
            # again says what to fix rather than looking finished.
            held = [
                row["id"] + ": " + row["heldReason"]
                for row in (
                    self._index(project_id).get(asset["id"])
                    for asset in request["assets"]
                )
                if row and row.get("heldReason") and row.get("state") == "needs_review"
            ]
            if held:
                contract += (
                    "\nThe app has not accepted these results yet; fix them, check again and save the report again:\n- "
                    + "\n- ".join(held)
                )
            contract += "\n\nApply the following image-only methodology within the exact request scope above. "
            contract += (
                "The request's asset list overrides any broader editable-folder instruction in this reference.\n\n"
                + skill
            )
        return contract

    def _contract(self, request, path, own=False, pair=None):
        """The task an assistant follows. A copied task hands one step to
        the user's assistant; own is the Assistant-led assistant, which runs
        every step itself and continues to the next. *pair* is the game's
        language pair (settings/language_pair)."""
        pair = pair or {"source": JAPANESE, "target": ENGLISH}
        kind = request["kind"]
        example = {
            "version": 1,
            "kind": kind,
            "requestId": request["id"],
            "projectId": request["projectId"],
            "inventoryRevision": request["inventoryRevision"],
            "complete": False,
            "assets": [],
        }
        if kind == "discovery":
            example["assets"] = [
                {
                    "id": "copy an exact request asset ID",
                    "sourceHash": "copy its source hash",
                    "classification": "recommended",
                    "method": "visual",
                    "examined": True,
                    "reason": "Explain the candidate",
                    "evidence": "contact sheet/crop reference and observation",
                    "variants": [],
                }
            ]
            instructions = (
                "Investigate which requested images need translation. This is discovery only; do not edit images or game files. "
                "Recommend the images with text players read: "
                + (
                    "your recommendations become the list you translate next. "
                    if own
                    else "the app ticks your recommendations for the user to review before a separate translation task. "
                )
                + "Sound effects lettered into scene art, such as moans, slurps, impacts and hearts in event CGs, are flavor and stay untranslated: "
                f"classify an image whose only {pair['source']} is such lettering as sound_effects, also when its marks may be sound effects or decoration, "
                "and recommend an image that also has other text for that text. "
                "Use metadata, byte-identical duplicate groups, numbered contact sheets and enlarged crops/originals where needed. "
                "An asset's family lists same-size images that share its backdrop; review a family by what changes (methodology: Review a family by what changes): "
                "view one member in full, then every other member as a crop of the pixels that differ from the closest member examined at its current source hash, many crops to a sheet. "
                "Each crop examines its member, whose other pixels are that examined member's, lettering included: give the member compared with and the crop box as evidence, "
                "and view a member with no differing pixels whole. "
                "Enlarge only cells that show marks or that shrank a large image below about a third, and review the sheets yourself "
                "rather than splitting them across parallel agents that each rebuild tools and view the images again. "
                "Process bounded batches, cache results by source hash, resume unchanged work and record coverage honestly. "
                "Use Len's image census methodology as a reference, not its whole-game authorization. "
                "Local installed OCR is optional: try it on a few images with known text first and drop it when it misses them; "
                "do not install/download tools, invoke hosted OCR or paid services without separate authorization. "
                "A detector miss does not certify no text. Record uncertain/not_examined for unreadable, locked, failed or insufficiently examined assets. "
                "Allowed classifications: recommended, uncertain, no_text, already_english, sound_effects, not_examined, excluded. "
                + (
                    ""
                    if pair["target"] == ENGLISH
                    else f"already_english marks an image whose text is already in {pair['target']}. "
                )
                + "Positive examination methods are exactly visual, ocr, local_ocr, visual+ocr or visual+local_ocr. "
                "no_text, already_english and sound_effects require actual visual/OCR examination and evidence; detector-only findings cannot certify them. "
                "Related variants are suggestions, not reviewed equivalents. Only byte-identical source images may reuse a finding outright, identified explicitly; "
                "a family member's identical pixels count only through its own diff crop. "
                "Never mark an unexamined image examined. Retain partial findings and write reports atomically; do not claim complete until every requested asset is accounted for."
            )
            if request.get("scope") == "all":
                instructions += (
                    " This investigation starts over: examine and classify each image again under these instructions "
                    "instead of reusing findings or caches from earlier investigations, other than request.resumeReport."
                )
        else:
            example["assets"] = [
                {
                    "id": "copy an exact request asset ID",
                    "sourceHash": "copy its source hash",
                    "candidateHash": "SHA-256 of the final editable PNG, not the request's editableHash",
                    "status": "edited",
                    "reason": "",
                    "review": {
                        "version": REVIEW_VERSION,
                        "visual": True,
                        "alpha": True,
                        "protectedPixels": True,
                        "layout": True,
                        "evidence": "original/candidate visual check and saved evidence reference",
                    },
                }
            ]
            instructions = (
                "Edit only the requested working PNG copies. Handle transcription, translation, rendering, validation and routine visual review. "
                "Keep game runtime originals read-only, preserve exact filenames, PNG format, dimensions, mode and transparency. "
                "Each request asset names three files with their SHA-256 hashes: runtime and sourceHash are the game's file, encrypted where the game encrypts its images; "
                "frozen and frozenHash are the original PNG the app preserved from it, which every render and redo starts from, never translated pixels; "
                "editable and editableHash are the working copy as it was when this task was made. "
                "An asset's family lists the images that share its backdrop: rebuild its background with the family solver before any inpainting (methodology section 4a), "
                "and fit an accepted sibling's text recipe instead of measuring its lettering by hand (section 10). "
                "Reuse glossary/context already saved in the request. "
                "No mandatory user sign-off for every image. "
                + (
                    "Settle uncertainties yourself; report an image you can't or won't edit as skipped with the reason; "
                    if own
                    else "Report genuine uncertainties/exclusions or material generative choices for user decision; "
                )
                + "do not call image-generation/paid services without separate authorization. "
                "Record edited/unchanged/skipped/needs_review/error for each asset; copy its sourceHash and give the final PNG's hash as candidateHash, which binds your review to those exact files. "
                "Review original/candidate appearance, alpha, protected artwork and runtime layout. Do not assert checks you have not performed. "
                "Save each changed image's recipe in the resource manifest (methodology section 15a) and check the request with the validator before saving your report: "
                + self._validator(path)
                + " The app runs the same checks when it reads your report and accepts your review of a changed image only with a current recipe and passing validation. "
                "Write the structured report below atomically, with partial updates for resume. "
                + (
                    "images --apply then puts the reviewed images into the game. "
                    if own
                    else "The app, not the assistant, applies reviewed runtime images. "
                )
                + "When the user later asks for changes, edit the same working copies and save this report again with their new candidate hashes and review; the app reads it again."
            )
        return (
            (
                "Perform this image task of your Assistant-led run using request "
                if own
                else "Perform this single user-authorized Guided image task using request "
            )
            + str(path)
            + ".\n"
            "Request scope: "
            + str(len(request["assets"]))
            + " exact assets; project "
            + request["projectId"]
            + ".\n"
            + instructions
            + "\nRead-only image methodology reference: "
            + self.adapter.census_reference()
            + "\n"
            "The exact asset/source/guidance hashes and permitted editable paths are in the request. "
            "Unlisted assets are outside scope; do not broaden the task to the whole editable folder or whole game.\n"
            "Resume matching saved results from this report and request.resumeRequest/resumeReport. "
            "Reuse only source/candidate-bound evidence; changed bytes must be re-examined. "
            "Keep valid completed work and partial coverage, and save accepted reused findings under this request ID.\n"
            "Save findings to "
            + request["report"]
            + ". Required JSON schema example:\n"
            + json.dumps(example, ensure_ascii=False, indent=2)
            + (
                "\nRecord what was completed, unresolved and skipped in status.md, then run images --status for the next step."
                if own
                else "\nCopying this task did not start an agent. Report what was completed, unresolved and skipped, then stop."
            )
        )

    def _validator(self, request_path):
        """The validator command for a request, with the app's own Python."""
        script = Path(self.backend.source) / "scripts/image_validate.py"
        return (
            f'"{Path(sys.executable).absolute()}" "{script}" request "{request_path}" --reproduce'
            " (adapt the quoting to your shell)."
        )

    def _request(self, project_id, kind):
        value = self._load(project_id)
        identity = value[kind].get("requestId")
        entry = value["requests"].get(identity)
        # A task taken over from another project reports only once copied here.
        if not entry or entry.get("carried"):
            raise ValueError(
                "Copy a scoped " + kind + " task before refreshing its report."
            )
        if value[kind].get("status") == "stopped":
            raise ValueError(
                "This investigation was stopped to choose the images yourself, so its report is no longer read. Copy the investigation again to start a new one."
            )
        root = self.record(project_id)[1]
        request = read_json(project_path(root, entry["path"]), limit=48_000_000)
        if (
            digest(request) != entry["hash"]
            or request.get("projectId") != project_id
            or request.get("kind") != kind
        ):
            raise ValueError(
                "The image task request changed or belongs to another project."
            )
        return value, request

    def _refresh_report(self, project_id, kind):
        value, request = self._request(project_id, kind)
        root = self.record(project_id)[1]
        path = project_path(
            root, WORK + "/reports/" + request["id"] + ".json", exists=False
        )
        # Nothing saved yet is the assistant still working, not a task problem.
        if not path.exists():
            return {
                "state": self.state(project_id),
                "message": "No results saved yet.",
            }
        report = read_json(path, limit=48_000_000)
        if (
            not isinstance(report, dict)
            or report.get("version") != 1
            or report.get("kind") != kind
            or report.get("projectId") != project_id
            or report.get("requestId") != request["id"]
            or report.get("inventoryRevision") != request["inventoryRevision"]
            or type(report.get("complete")) is not bool
            or not isinstance(report.get("assets"), list)
        ):
            raise ValueError(
                "The saved image report is invalid or belongs to another task/project/inventory."
            )
        for name, expected in request["guidance"].items():
            if sha_file(project_path(root, name)) != expected:
                raise ValueError(
                    "Saved guidance changed after this task. Copy a new task before accepting these results."
                )
        expected = {row["id"]: row for row in request["assets"]}
        identities, updates, errors = set(), [], []
        recommended, dropped = set(), set()
        index = self._index(project_id)
        key = self.adapter.key(root, self._profile(project_id))
        recipe_book = (
            recipes.manifest(root)
            if request.get("recipeVersion") == RECIPE_VERSION
            else None
        )
        for result in report["assets"]:
            if (
                not isinstance(result, dict)
                or result.get("id") not in expected
                or result["id"] in identities
            ):
                raise ValueError(
                    "The report contains duplicate or out-of-scope image findings."
                )
            identity = result["id"]
            identities.add(identity)
            old = index.get(identity)
            row = self._inspect(project_id, old, old, key)
            if result.get("sourceHash") != expected[identity]["sourceHash"] or row.get(
                "sourceHash"
            ) != result.get("sourceHash"):
                errors.append(
                    identity
                    + ": source evidence changed or is unavailable; findings remain unresolved."
                )
                updates.append(row)
                continue
            if kind == "discovery":
                classification = result.get("classification")
                if (
                    classification not in CLASSIFICATIONS
                    or type(result.get("examined")) is not bool
                ):
                    raise ValueError(
                        "Invalid discovery classification or examination state."
                    )
                method = text(result.get("method", ""), "Discovery method", 100)
                evidence = text(result.get("evidence", ""), "Discovery evidence", 8000)
                reason = text(result.get("reason", ""), "Discovery reason", 4000)
                real_examination = method in EXAMINATION_METHODS and bool(
                    evidence.strip()
                )
                if classification in {
                    "no_text",
                    "already_english",
                    "sound_effects",
                } and (not result["examined"] or not real_examination):
                    classification = "not_examined"
                    errors.append(
                        identity
                        + ": a detector miss cannot certify text-free, already-translated or sound-effect-only content."
                    )
                examined = bool(result["examined"] and real_examination)
                variants = result.get("variants", [])
                if (
                    not isinstance(variants, list)
                    or len(variants) > 10_000
                    or any(not isinstance(item, str) for item in variants)
                ):
                    raise ValueError("Invalid related image variants.")
                finding = {
                    "requestId": request["id"],
                    "sourceHash": row["sourceHash"],
                    "classification": classification,
                    "method": method,
                    "reason": reason,
                    "evidence": evidence,
                    "examined": examined,
                    "variants": variants,
                    "saved": now(),
                }
                if result.get("reusedFrom"):
                    other = index.get(result["reusedFrom"])
                    if not other or other.get("sourceHash") != row["sourceHash"]:
                        raise ValueError(
                            "Discovery evidence may be reused only for byte-identical source images."
                        )
                    finding["reusedFrom"] = result["reusedFrom"]
                row["finding"] = finding
                row["classification"] = (row.get("manualOverride") or {}).get(
                    "classification", classification
                )
                row.pop("staleReason", None)
                # A finding sets its image's tick once, so an image the user
                # took out stays out when the same request saves again. A
                # recommendation joins the list; an investigation of all
                # images also takes out the ones it no longer recommends.
                earlier = old.get("finding") or {}
                if not (
                    earlier.get("requestId") == request["id"]
                    and earlier.get("classification") == classification
                ):
                    if row["classification"] == "recommended":
                        recommended.add(identity)
                    elif request.get("scope") == "all":
                        dropped.add(identity)
            else:
                if result.get("status") not in {
                    "edited",
                    "unchanged",
                    "skipped",
                    "needs_review",
                    "error",
                }:
                    raise ValueError("Invalid image editing result status.")
                reason = text(result.get("reason", ""), "Editing reason", 4000)
                row["editResult"] = {
                    "requestId": request["id"],
                    "status": result["status"],
                    "reason": reason,
                    "saved": now(),
                }
                review = result.get("review") or {}
                if result.get("candidateHash") != row.get(
                    "candidateHash"
                ) or not row.get("candidateHash"):
                    row.pop("aiReview", None)
                    errors.append(
                        identity
                        + ": candidate changed or is missing; saved review was not accepted."
                    )
                elif (
                    result["status"] in {"edited", "unchanged"}
                    and isinstance(review, dict)
                    and review.get("version") == REVIEW_VERSION
                    and request.get("reviewVersion") == REVIEW_VERSION
                    and all(
                        review.get(check) is True
                        for check in ("visual", "alpha", "protectedPixels", "layout")
                    )
                    and isinstance(review.get("evidence"), str)
                    and review["evidence"].strip()
                ):
                    row["aiReview"] = {
                        "version": REVIEW_VERSION,
                        "requestId": request["id"],
                        "sourceHash": row["sourceHash"],
                        "candidateHash": row["candidateHash"],
                        "evidence": text(review["evidence"], "Review evidence", 8000),
                        "checks": {
                            check: True
                            for check in (
                                "visual",
                                "alpha",
                                "protectedPixels",
                                "layout",
                            )
                        },
                        "saved": now(),
                    }
                    # An edit that changes the image proves it can be rendered
                    # again and stayed inside its declared regions.
                    if recipe_book and row.get("changed"):
                        row["aiReview"]["proof"] = RECIPE_VERSION
                        row["proof"] = self._proof(
                            root, request["id"], row, *recipe_book
                        )
                else:
                    row.pop("aiReview", None)
            updates.append(self._status(row))
        with index.connection() as db:
            for row in updates:
                index.put(db, row, row.get("generation", ""))
        # New recommendations are ticked to translate, and the grid opens on
        # the list so the user reviews it next, unless they have browsed the
        # images, which a report arriving mid-browse must not undo. An image
        # already translated stays in the list whatever a later finding says.
        listed = [
            row["id"]
            for row in updates
            if row["id"] in recommended
            and row["state"] not in {"applied", "skipped", "blocked"}
        ]
        unlisted = {
            row["id"]
            for row in updates
            if row["id"] in dropped
            and not row.get("editResult")
            and row["state"] not in {"ready", "needs_review", "applied"}
        }
        if listed or unlisted & set(value["selection"]):
            value["selection"] = list(
                dict.fromkeys(
                    [item for item in value["selection"] if item not in unlisted]
                    + listed
                )
            )
            if not value.get("browsed"):
                value["view"].update(LIST_VIEW, folder="", query="", scroll=0)
            index.selected(value["selection"])
        # Completion is accumulated across partial saves of this exact request:
        # a request whose every image has a result is answered, flag or not, so
        # a forgotten flag never leaves the task waiting. Until a report says
        # it is complete, an image it holds as not examined is still to come:
        # the assistant saves those placeholders as it goes.
        accounted = 0
        for identity in expected:
            row = index.get(identity)
            accepted = row.get("finding" if kind == "discovery" else "editResult") or {}
            if accepted.get("requestId") == request["id"] and (
                report["complete"] or accepted.get("classification") != "not_examined"
            ):
                accounted += 1
        value[kind].update(
            status="complete"
            if accounted == len(expected) and not errors
            else "partial",
            lastReport=now(),
            reportPath=path.relative_to(root).as_posix(),
            errors=errors,
            accounted=accounted,
            requested=len(expected),
            reportHash=sha_file(path),
        )
        value[kind].pop("rejected", None)
        value[kind].pop("rejectedHash", None)
        self._save(project_id, value)
        return {"state": self.state(project_id)}

    def _proof(self, root, request_id, row, found, unreadable):
        """The recipe and validation of a reported edit, bound to its hashes.
        A validation whose inputs are unchanged is kept from the last read."""
        binding = {
            "version": RECIPE_VERSION,
            "requestId": request_id,
            "sourceHash": row["sourceHash"],
            "candidateHash": row["candidateHash"],
            "saved": now(),
        }
        if found is None or not row.get("frozen"):
            reason = unreadable or "The image has no preserved original to check."
            return {**binding, "ok": False, "reason": reason, "recipe": "invalid"}
        try:
            candidate = project_path(root, row["editable"]).read_bytes()
        except OSError, ValueError:
            candidate = b""
        if digest(candidate) != row["candidateHash"]:
            return {
                **binding,
                "ok": False,
                "reason": "The edited copy changed while it was checked.",
                "recipe": "",
            }
        image = {
            "id": row["id"],
            "frozen": row["frozen"],
            "frozenHash": row.get("originalPngHash"),
            "candidateHash": row["candidateHash"],
            "candidate": candidate,
            "originals": {
                row.get(name)
                for name in (
                    "originalPngHash",
                    "originalRuntimeHash",
                    "runtimeBackupHash",
                    "sourceHash",
                )
            }
            - {None, ""},
        }
        result = recipes.proof(
            root,
            image,
            found.get(row["id"]),
            file_hash=lambda path: self._file_hash(root, path),
            cached=row.get("proof"),
        )
        return {
            **binding,
            "ok": result["ok"],
            "reason": result["reason"],
            "recipe": result["recipe"]["state"],
            "key": result["key"],
            "validation": result["validation"],
        }

    def _file_hash(self, root, relative):
        """A recipe input's hash, kept until the file changes."""
        try:
            path = project_path(root, relative, exists=False)
            if not path.is_file():
                return None
            return self.digests.file(path, path.stat())
        except OSError, ValueError:
            return None

    def _prepare(self, project_id, options):
        identities = self._chosen(project_id, options)
        self.refresh_assets(project_id, identities)
        root, index, profile = (
            self.record(project_id)[1],
            self._index(project_id),
            self._profile(project_id),
        )
        rows = [index.get(identity) for identity in identities]
        errors, allowed = [], []
        for row in rows:
            if (
                row.get("sourceIssue")
                or row.get("collisionIssue")
                or row.get("originalIssue")
            ):
                errors.append(
                    row["id"]
                    + ": "
                    + (
                        row.get("sourceIssue")
                        or row.get("collisionIssue")
                        or row.get("originalIssue")
                    )
                )
                continue
            if not row.get("frozen"):
                raw = self.adapter.source_bytes(
                    root, row, self.adapter.key(root, profile)
                )
                runtime_bytes = project_path(root, row["runtime"]).read_bytes()
                if (
                    digest(runtime_bytes) != row["sourceHash"]
                    or digest(raw) != row["sourcePngHash"]
                ):
                    raise ValueError(
                        "A source image changed during preparation. Existing images were retained; refresh before continuing."
                    )
                origin = "Runtime source before image preparation"
                if hasattr(self.adapter, "original_bytes"):
                    raw, runtime_original, origin = self.adapter.original_bytes(
                        root, row, self.adapter.key(root, profile)
                    )
                else:
                    runtime_original = runtime_bytes
                original_metadata = png_metadata(raw)
                frozen = WORK + "/originals/" + row["id"]
                frozen_path = project_path(root, frozen, exists=False)
                if frozen_path.exists():
                    raise ValueError(
                        "Unrecognized preserved image files exist. Inspect them before preparing new originals."
                    )
                write_bytes(frozen_path, raw)
                # Restore puts back the game's bytes these hash to, which the
                # game's record of its original files holds.
                row.update(
                    frozen=frozen,
                    originalPngHash=digest(raw),
                    originalRuntimeHash=row["sourceHash"],
                    originalMetadata=original_metadata,
                    originalOrigin=origin,
                    runtimeBackupHash=digest(runtime_original),
                )
            allowed.append(row)
        with index.connection() as db:
            for row in allowed:
                index.put(db, row, row.get("generation", ""))
        if allowed:
            # The editable copies are DazedTL's own records, but making them
            # may add DazedTL's rules to the game's .gitignore.
            with self.backend.game_write(
                root,
                self.projects.get(project_id).get("backend_id"),
                pack=False,
                summary="Prepare images for editing",
                stage="Translate",
            ):
                result = self.adapter.prepare(
                    root, profile, allowed, self.adapter.key(root, profile)
                )
        else:
            result = {"completed": 0, "skipped": 0, "errors": []}
        result["errors"] = errors + result.get("errors", [])
        self.refresh_assets(project_id, identities)
        value = self._load(project_id)
        value["lastAction"] = {"action": "prepare", "saved": now(), **result}
        self._save(project_id, value)
        return {"state": self.state(project_id), "result": result}

    def _review(self, project_id, action, options):
        identities = self._chosen(project_id, options)
        self.refresh_assets(project_id, identities)
        index = self._index(project_id)
        reason = text(options.get("reason", ""), "Review reason", 4000)
        with index.connection() as db:
            for identity in identities:
                row = index.get(identity, db)
                if action in {"exclude", "include"}:
                    if action == "include" or options.get("excluded") is False:
                        row.pop("manualOverride", None)
                        row.pop("manualOverrideStale", None)
                        finding = row.get("finding") or {}
                        row["classification"] = (
                            finding.get("classification", "not_examined")
                            if finding.get("sourceHash") == row.get("sourceHash")
                            else "not_examined"
                        )
                    else:
                        if not reason.strip():
                            raise ValueError("Record a reason for excluding an image.")
                        row["manualOverride"] = {
                            "classification": "excluded",
                            "excluded": True,
                            "reason": reason,
                            "sourceHash": row.get("sourceHash", ""),
                            "saved": now(),
                        }
                        row["classification"] = "excluded"
                else:
                    if options.get("reviewed") is False:
                        row.pop("userReview", None)
                    else:
                        if (
                            not row.get("candidateHash")
                            or not all(row.get("checks", {}).values())
                            or row.get("sourceIssue")
                            or row.get("originalIssue")
                        ):
                            raise ValueError(
                                "Resolve structural/source issues before marking this image reviewed."
                            )
                        row["userReview"] = {
                            "version": REVIEW_VERSION,
                            "sourceHash": row["sourceHash"],
                            "candidateHash": row["candidateHash"],
                            "reviewed": True,
                            "reason": reason,
                            "saved": now(),
                        }
                index.put(db, self._status(row), row.get("generation", ""))
        self._touch(project_id)

    def _remove(self, project_id, options):
        identities = self._chosen(project_id, options)
        root, index = self.record(project_id)[1], self._index(project_id)
        for identity in identities:
            row = index.get(identity)
            system.unlink(
                project_path(root, row["editable"], exists=False), missing_ok=True
            )
        self.refresh_assets(project_id, identities)

    def _preview_mutation(self, project_id, action, options):
        self.translation.writable(project_id)
        identities = self._chosen(project_id, options)
        self.refresh_assets(project_id, identities)
        root, index = self.record(project_id)[1], self._index(project_id)
        game_originals.require(self.translation.workspace, project_id, root)
        # Apply to game takes the list's translated images and leaves the rest
        # of the list, still being translated, out of the review.
        if action == "apply" and options.get("ready_only"):
            identities = [
                identity
                for identity in identities
                if index.get(identity)["state"] == "ready"
            ]
            if not identities:
                raise ValueError("No image in your list is translated yet.")
        included, blocked, unchanged = [], [], 0
        for identity in identities:
            row = index.get(identity)
            if action == "apply":
                if (
                    row["state"] == "applied"
                    or not row.get("changed")
                    and row.get("hasEditable")
                    and not row.get("sourceIssue")
                ):
                    unchanged += 1
                    continue
                reason = row["blockedReason"] if row["state"] != "ready" else ""
            else:
                reason = (
                    ""
                    if row.get("frozen")
                    and (row.get("applied") or {}).get("runtimeHash")
                    == row.get("sourceHash")
                    else "This image has no current application to restore."
                )
            if reason:
                blocked.append({"id": identity, "path": row["path"], "reason": reason})
            else:
                included.append(row)
        if action == "restore" and included:
            # Each image's original, read from the game's records at once.
            issues = {}
            try:
                self._original_runtime(project_id, root, included, issues, keep=False)
            except (OSError, ValueError) as exc:
                issues = dict.fromkeys((row["id"] for row in included), str(exc))
            blocked += [
                {"id": row["id"], "path": row["path"], "reason": issues[row["id"]]}
                for row in included
                if row["id"] in issues
            ]
            included = [row for row in included if row["id"] not in issues]
        token = uuid.uuid4().hex
        plan = {
            "projectId": project_id,
            "action": action,
            "assets": deepcopy(included),
            "created": time.monotonic(),
            "inventoryRevision": self._load(project_id)["inventoryRevision"],
            "selection": identities,
        }
        self.previews[token] = plan
        # Bound memory and review lifetime without ever persisting execution authorization.
        for old_token, old in list(self.previews.items()):
            if time.monotonic() - old["created"] > 900:
                self.previews.pop(old_token, None)
        # The review lists destinations; the full rows stay in the plan.
        review = ("id", "path", "destination", "sourceHash", "candidateHash")
        preview = {
            "token": token,
            "action": action,
            "assets": [
                {key: public.get(key, "") for key in review}
                for public in (self._public(row) for row in included)
            ],
            "blocked": blocked,
            "included": len(included),
            "count": len(included),
            "unchanged": unchanged,
            "expires": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        }
        return {"state": self.state(project_id), "preview": preview}

    def _original_runtime(self, project_id, root, rows, issues=None, keep=True):
        """The game's bytes each image had when Prepare kept its original,
        for Restore: a copy Prepare saved before restores read Git, else the
        game's record of its original files, else an older publisher's
        backup. An image none of them holds is refused, or, given `issues`,
        named there with why, so a preview reads every image in one pass;
        without `keep` it holds their hashes, not their bytes."""
        found = {}
        for row in rows:
            if row.get("runtimeBackup"):
                try:
                    raw = project_path(root, row["runtimeBackup"]).read_bytes()
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        "The preserved original runtime backup is missing."
                    ) from exc
                if digest(raw) != row["runtimeBackupHash"]:
                    issue = "The preserved original runtime bytes changed."
                    if issues is None:
                        raise ValueError(issue)
                    issues[row["id"]] = issue
        wanted = [row for row in rows if not row.get("runtimeBackup")]
        if not wanted:
            return found
        original = game_originals.prepared(self.translation.workspace, project_id, root)
        names = [row["runtime"] for row in wanted]
        if original is not None:
            with original.materialized(names) as folder:
                for name in names:
                    path = folder / name
                    if path.is_file():
                        raw = path.read_bytes()
                        found[name] = raw if keep else digest(raw)

        def hashed(value):
            return value if not keep or value is None else digest(value)

        for row in wanted:
            raw = found.get(row["runtime"])
            if raw is None or hashed(raw) != row["runtimeBackupHash"]:
                backup = project_path(
                    root, families.BACKUPS + row["runtime"], exists=False
                )
                raw = backup.read_bytes() if backup.is_file() else None
                if raw is not None and not keep:
                    raw = digest(raw)
            if raw is None or hashed(raw) != row["runtimeBackupHash"]:
                found.pop(row["runtime"], None)
                issue = (
                    "DazedTL has no copy of this image as it was before it was "
                    "translated. The Project page's Checkpoints can undo its apply."
                )
                if issues is None:
                    raise ValueError(issue)
                issues[row["id"]] = issue
                continue
            found[row["runtime"]] = raw
        return found

    def _execute(self, project_id, action, options):
        # Refused before the review is used, so it still applies once the
        # game's Git operation is finished.
        self.translation.writable(project_id)
        token = options.get("token")
        plan = self.previews.pop(token, None) if isinstance(token, str) else None
        if (
            not plan
            or plan["projectId"] != project_id
            or plan["action"] != action
            or time.monotonic() - plan["created"] > 900
        ):
            raise ValueError(
                "This image review expired or was already used. Review the batch again."
            )
        if not plan["assets"]:
            raise ValueError("No images were included. Nothing was applied.")
        root, profile = self.record(project_id)[1], self._profile(project_id)
        game_originals.require(self.translation.workspace, project_id, root)
        identities = [row["id"] for row in plan["assets"]]
        self.refresh_assets(project_id, identities)
        index = self._index(project_id)
        current = [index.get(identity) for identity in identities]
        for before, after in zip(plan["assets"], current):
            if any(
                before.get(key) != after.get(key)
                for key in (
                    "sourceHash",
                    "candidateHash",
                    "runtime",
                    "editable",
                    "runtimeBackupHash",
                    "originalPngHash",
                )
            ):
                raise ValueError(
                    "An included image changed after review. Nothing was applied; review the batch again."
                )
            if action == "apply" and after["state"] != "ready":
                raise ValueError(
                    "An included image is no longer ready. Nothing was applied."
                )
            if action == "restore" and (after.get("applied") or {}).get(
                "runtimeHash"
            ) != after.get("sourceHash"):
                raise ValueError(
                    "A runtime image changed after its application. Nothing was restored."
                )
        # Read before the journal is saved, so a missing original leaves no
        # publication to recover.
        originals = (
            self._original_runtime(project_id, root, current)
            if action == "restore"
            else {}
        )
        journal_id = uuid.uuid4().hex
        journal_path = WORK + "/publications/" + journal_id + ".json"
        key = self.adapter.key(root, profile)
        journal = {
            "version": 1,
            "id": journal_id,
            "projectId": project_id,
            "action": action,
            "status": "publishing",
            "saved": now(),
            "assets": [],
        }
        for row in current:
            expected_hash = (
                self.adapter.output_hash(root, row, key)
                if action == "apply"
                else row["runtimeBackupHash"]
            )
            journal["assets"].append(
                {
                    "id": row["id"],
                    "runtime": row["runtime"],
                    "sourceHash": row["sourceHash"],
                    "candidateHash": row["candidateHash"],
                    "expectedRuntimeHash": expected_hash,
                    **{
                        key: row[key]
                        for key in ("runtimeBackup", "runtimeBackupHash")
                        if key in row
                    },
                    "review": "ai" if row.get("aiReviewed") else "user",
                    "reviewVersion": REVIEW_VERSION,
                }
            )
        write_json(project_path(root, journal_path, exists=False), journal)
        value = self._load(project_id)
        value.setdefault("pendingPublications", {})[journal_id] = {
            "path": journal_path,
            "hash": self._journal_binding(journal),
        }
        self._save(project_id, value)
        self.mutating.add(project_id)
        try:
            with self.backend.game_write(
                root,
                self.projects.get(project_id).get("backend_id"),
                paths=[row["runtime"] for row in current],
                summary="Apply translated images"
                if action == "apply"
                else "Restore original images",
                stage="Translate",
            ):
                result = (
                    self.adapter.apply(root, profile, current, key)
                    if action == "apply"
                    else self.adapter.restore(root, current, originals)
                )
            if not result.get("errors"):
                with index.connection() as db:
                    for row in current:
                        runtime_hash = sha_file(project_path(root, row["runtime"]))
                        if action == "apply":
                            row.pop("restored", None)
                            row["applied"] = {
                                "candidateHash": row["candidateHash"],
                                "runtimeHash": runtime_hash,
                                "sourceHash": row["sourceHash"],
                                "saved": now(),
                                "review": "ai" if row.get("aiReviewed") else "user",
                            }
                        else:
                            _set_aside(row)
                            row.pop("aiReview", None)
                            row.pop("userReview", None)
                            row["originalRuntimeHash"] = runtime_hash
                        index.put(db, row, row.get("generation", ""))
            self.refresh_assets(project_id, identities)
            value = self._load(project_id)
            receipt = {
                "id": journal_id,
                "action": action,
                "assets": identities,
                "saved": now(),
                "status": "error" if result.get("errors") else "complete",
                **result,
            }
            value["receipts"] = (value["receipts"] + [receipt])[-200:]
            value["lastAction"] = receipt
            if not result.get("errors"):
                value.get("pendingPublications", {}).pop(journal_id, None)
                journal.update(status="complete", receipt=receipt)
                write_json(project_path(root, journal_path), journal)
            else:
                journal["errors"] = result["errors"]
                write_json(project_path(root, journal_path), journal)
            self._save(project_id, value)
            self.mutating.discard(project_id)
            return {"state": self.state(project_id), "result": result}
        finally:
            self.mutating.discard(project_id)

    def preview(self, project_id, asset_id, variant="source", size=0):
        if (
            variant not in {"source", "original", "candidate"}
            or type(size) is not int
            or size < 0
            or size > 2048
        ):
            raise ValueError(
                "Choose an original/candidate preview and valid thumbnail size."
            )
        # Only the inventory lookup holds the lock, so previews run beside each
        # other and beside other requests.
        with self.lock:
            self._ids(project_id, [asset_id])
            root, index = self.record(project_id)[1], self._index(project_id)
            row = index.get(asset_id)
            frozen = variant == "original" and row.get("frozen")
            key = (
                None
                if variant == "candidate" or frozen
                else self.adapter.key(root, self._profile(project_id))
            )
        # A preview is kept by the file it shows and that file's stat
        # signature, so showing it again reads nothing; a file that changed,
        # changed while it was read or is too new to trust its signature is
        # read and decoded again. An original is also kept by the hash its
        # record expects, which reading it checks.
        path = project_path(
            root,
            row["editable"]
            if variant == "candidate"
            else row["frozen"]
            if frozen
            else row["runtime"],
        )
        stamp = signature(path.stat())
        cache_key = (
            project_id,
            asset_id,
            variant,
            stamp,
            key if row.get("encrypted") and not frozen else None,
            row.get("originalPngHash") if frozen else None,
            size,
        )
        cached = self.cache.get(cache_key)
        if cached is None:
            cached = self._preview(root, row, variant, frozen, key, path, size)
            if signature_settled(stamp) and signature(path.stat()) == stamp:
                self.cache.put(cache_key, cached)
        metadata, pixels, media, fingerprint = cached
        return {
            "url": f"data:{media};base64," + base64.b64encode(pixels).decode("ascii"),
            "sha256": fingerprint,
            **metadata,
        }

    def _preview(self, root, row, variant, frozen, key, path, size):
        """Reads and decodes one preview: its metadata, pixels, media type and
        the hash of the bytes it shows."""
        if variant == "candidate":
            if path.stat().st_size > 128_000_000:
                raise ValueError(
                    "Editable image exceeds the supported 128 MB size limit."
                )
            raw = path.read_bytes()
        elif frozen:
            if path.stat().st_size > 128_000_000:
                raise ValueError(
                    "Original image exceeds the supported 128 MB size limit."
                )
            raw = path.read_bytes()
            if digest(raw) != row.get("originalPngHash"):
                raise ValueError(
                    "The preserved original changed. Recover it before comparison."
                )
        else:
            raw = self.adapter.source_bytes(root, row, key)
        metadata, pixels, media = png_preview(raw, size)
        return metadata, pixels, media, digest(raw)
