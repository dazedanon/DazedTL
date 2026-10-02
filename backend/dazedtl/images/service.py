"""One retained image workflow shared by Guided and the standalone manager."""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import uuid

from dazedtl.compatibility.images import ImageCompatibility
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest, project_path, read_json
from dazedtl.translation.operations import lifecycle, require_source_backup
from .inventory import Index, PreviewCache, inspect_row, png_metadata, sha_file


WORK = ".dazedtl/image_manager/guided"
CLASSIFICATIONS = {"recommended", "uncertain", "no_text", "already_english", "not_examined", "excluded"}
EXAMINATION_METHODS = {"visual", "ocr", "local_ocr", "visual+ocr", "visual+local_ocr"}
SCOPES = {"all", "folders", "selected"}
REVIEW_VERSION = 1
VIEW = {"query": "", "status": "all", "folder": "", "showSelected": False,
        "tileSize": 112, "scroll": 0, "currentImage": "", "workflowMode": "discovery"}


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, label, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(label + " must be text within the supported length.")
    return value


class ImageService:
    def __init__(self, projects, translation, settings, backend, *, adapter=None):
        self.projects, self.translation, self.settings, self.backend = projects, translation, settings, backend
        self.adapter = adapter or ImageCompatibility(backend)
        self.lock = threading.RLock()
        self.indexes, self.jobs, self.cancellations = {}, {}, {}
        self.cache = PreviewCache()
        self.previews = {}
        self.mutating = set()
        self.threads = {}

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
        for protected in (getattr(self.backend, "source", None), getattr(self.translation, "workspace", None)):
            if protected:
                path = Path(protected).resolve()
                if root.is_relative_to(path) or path.is_relative_to(root):
                    raise ValueError("Choose a game separate from the application and its profile.")
        return project, root

    def workspace(self, project_id):
        _project, root = self.record(project_id)
        return project_path(root, WORK + "/state.json", exists=False).parent

    def _load(self, project_id):
        project, root = self.record(project_id)
        path = project_path(root, WORK + "/state.json", exists=False)
        if path.exists():
            value = read_json(path, limit=16_000_000)
            if not isinstance(value, dict) or value.get("version") != 1 or value.get("projectId") != project_id:
                raise ValueError("Image progress belongs to another project or app version. Its files were retained.")
            return value
        return {"version": 1, "projectId": project_id, "selection": [], "view": dict(VIEW),
                "inventoryRevision": "", "profile": None,
                "discovery": {"scope": "all", "folders": [], "status": "idle", "lastReport": "", "errors": []},
                "editing": {"status": "idle", "lastReport": "", "errors": []},
                "requests": {}, "receipts": [], "warnings": []}

    def _save(self, project_id, value):
        write_json(self.workspace(project_id) / "state.json", value)

    @staticmethod
    def _preferences_revision(value):
        return digest({"selection": value["selection"], "view": {**VIEW, **value["view"]},
                       "discoveryScope": value["discovery"]["scope"], "folders": value["discovery"].get("folders", []),
                       "imageRoot": (value.get("profile") or {}).get("imageRoot", "")})

    def _index(self, project_id):
        if project_id not in self.indexes:
            self.indexes[project_id] = Index(project_path(self.record(project_id)[1], WORK + "/inventory.sqlite3", exists=False))
            self.indexes[project_id].selected(self._load(project_id)["selection"])
        return self.indexes[project_id]

    def _profile(self, project_id, value=None):
        project, root = self.record(project_id)
        value = value or self._load(project_id)
        return self.adapter.profile(root, project["engine"], (value.get("profile") or {}).get("imageRoot", ""))

    def state(self, project_id):
        with self.lock:
            project, root = self.record(project_id)
            self._recover_publications(project_id)
            value = self._load(project_id)
            index = self._index(project_id)
            profile = self._profile(project_id, value)
            counts = index.counts()
            public = {key: deepcopy(item) for key, item in value.items() if key not in {"requests", "pendingPublications"}}
            job = deepcopy(self.jobs.get(project_id) or value.get("lastScan"))
            if job and job["status"] == "running" and project_id not in self.jobs:
                job.update(status="interrupted", message="The previous scan was interrupted. Refresh inventory to resume indexing.")
            return {**public, "revision": self._preferences_revision(value), "observationRevision": digest(value),
                    "source": str(root), "name": project["name"],
                    "engine": project["engine"], "profile": profile, "counts": counts, **counts,
                    "folders": index.folders(), "job": job,
                    "discoveryScope": value["discovery"]["scope"], "supported": profile["supported"],
                    "editableRoot": str(root / ".dazedtl/images")}

    def list(self, project_id, query="", folder="", filter="all", offset=0, limit=100, selected_only=False, asset_id=""):
        text(query, "Search", 500); text(folder, "Folder", 2000); text(filter, "Filter", 40)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Choose a valid image range, up to 500 images per request.")
        with self.lock:
            if asset_id:
                row = self._index(project_id).get(asset_id)
                return {"items": [self._public(row)] if row else [], "total": int(bool(row)), "selectedMatched": 0, "offset": 0, "limit": 1}
            result = self._index(project_id).list(query=query, folder=folder, filter=filter, offset=offset,
                                                 limit=limit, selected_only=selected_only)
            result["items"] = [self._public(row) for row in result["items"]]
            return result

    @staticmethod
    def _public(row):
        keys = ("id", "path", "filename", "folder", "sourceHash", "candidateHash", "sourcePngHash",
                "state", "classification", "reason", "blockedReason", "aiReviewed", "userReviewed", "destination",
                "width", "height", "mode", "encrypted", "sourceIssue", "candidateIssue", "changed", "staleReason")
        return {**{key: row.get(key, "") for key in keys}, "editable": bool(row.get("hasEditable")),
                "finding": deepcopy(row.get("finding")), "checks": deepcopy(row.get("checks", {})),
                "reviewEvidence": (row.get("aiReview") or {}).get("evidence", ""),
                "candidateMetadata": row.get("candidateMetadata"), "applied": deepcopy(row.get("applied"))}

    def update(self, project_id, revision, changes):
        if not isinstance(changes, dict) or set(changes) - {"selection", "view", "discoveryScope", "folders", "discovery", "imageRoot"}:
            raise ValueError("Unknown image preference.")
        with self.lock:
            value = self._load(project_id)
            if self._preferences_revision(value) != revision:
                raise ValueError("Image progress changed. Reload before saving these choices.")
            if "selection" in changes:
                value["selection"] = self._ids(project_id, changes["selection"], allow_empty=True)
            if "view" in changes:
                view = changes["view"]
                if not isinstance(view, dict) or set(view) - set(VIEW):
                    raise ValueError("Unknown image view setting.")
                for key, item in view.items():
                    if key == "workflowMode" and item not in {"discovery", "manual", "findings", "review"}:
                        raise ValueError("Choose a valid image workflow view.")
                    if key in {"query", "status", "folder", "currentImage", "workflowMode"}:
                        text(item, "Image view", 2000)
                    elif key == "showSelected" and type(item) is not bool:
                        raise ValueError("Image selection filter must be enabled or disabled.")
                    elif key == "tileSize" and (type(item) is not int or not 72 <= item <= 240):
                        raise ValueError("Choose a thumbnail size between 72 and 240 pixels.")
                    elif key == "scroll" and (not isinstance(item, (int, float)) or isinstance(item, bool) or not 0 <= item < 100_000_000):
                        raise ValueError("Invalid image scroll position.")
                value["view"].update(view)
            discovery = changes.get("discovery", {})
            if not isinstance(discovery, dict) or set(discovery) - {"scope", "folders"}:
                raise ValueError("Unknown discovery preference.")
            scope = changes.get("discoveryScope", discovery.get("scope", value["discovery"]["scope"]))
            if scope not in SCOPES:
                raise ValueError("Choose All images, Current folders, or Selected images.")
            value["discovery"]["scope"] = scope
            if "folders" in changes or "folders" in discovery:
                folders = changes.get("folders", discovery.get("folders"))
                if not isinstance(folders, list) or len(folders) > 1000:
                    raise ValueError("Choose a supported folder scope.")
                for folder in folders:
                    text(folder, "Discovery folder", 2000)
                value["discovery"]["folders"] = sorted(set(folders))
            if "imageRoot" in changes:
                if self.jobs.get(project_id, {}).get("status") == "running":
                    raise ValueError("Stop the current image scan before changing its folder.")
                value["profile"] = {"imageRoot": text(changes["imageRoot"], "Loose image folder", 2000)}
                self._profile(project_id, value)
            self._save(project_id, value)
            self._index(project_id).selected(value["selection"])
            return self.state(project_id)

    def _ids(self, project_id, identities, *, allow_empty=False):
        if not isinstance(identities, list) or len(identities) > 100_000 or any(not isinstance(item, str) for item in identities):
            raise ValueError("Choose image asset IDs from this project's inventory.")
        identities = list(dict.fromkeys(identities))
        if not identities and not allow_empty:
            raise ValueError("Select at least one image. An empty selection never applies all images.")
        index = self._index(project_id)
        with index.connection() as db:
            if any(index.get(identity, db) is None for identity in identities):
                raise ValueError("An image is no longer in this project's inventory. Refresh the asset list.")
        return identities

    def _chosen(self, project_id, options):
        return self._ids(project_id, options.get("asset_ids", self._load(project_id)["selection"]))

    def resolve_assets(self, project_id, asset_ids):
        with self.lock:
            _project, root = self.record(project_id)
            ids = self._ids(project_id, asset_ids)
            self.refresh_assets(project_id, ids)
            index = self._index(project_id)
            rows = [index.get(identity) for identity in ids]
            return [{**row, "editablePath": str(project_path(root, row["editable"], exists=False)),
                     "frozenPath": str(project_path(root, row["frozen"], exists=False)) if row.get("frozen") else ""}
                    for row in rows]

    editor_assets = resolve_assets

    def _status(self, row):
        candidate = row.get("candidateMetadata") or {}
        original = row.get("originalMetadata") or {key: row.get(key) for key in ("width", "height", "mode", "transparency", "frames")}
        issues = [row.get(key, "") for key in ("sourceIssue", "candidateIssue", "collisionIssue", "originalIssue") if row.get(key)]
        checks = {"png": bool(row.get("candidateHash")), "dimensions": candidate.get("width") == original.get("width")
                  and candidate.get("height") == original.get("height"),
                  "mode": candidate.get("mode") == original.get("mode"),
                  "transparency": candidate.get("transparency") == original.get("transparency"),
                  "frames": candidate.get("frames") == original.get("frames")}
        if row.get("hasEditable"):
            issues += ["The edited image's " + key + " differs from the original." for key in ("dimensions", "mode", "transparency", "frames") if not checks[key]]
        if row.get("originalRuntimeHash") and row.get("sourceHash") != row["originalRuntimeHash"]:
            if row.get("sourceHash") != (row.get("applied") or {}).get("runtimeHash"):
                issues.append("The runtime source changed after this working copy was prepared. Resolve the source conflict first.")
        binding = {"sourceHash": row.get("sourceHash"), "candidateHash": row.get("candidateHash")}
        ai = row.get("aiReview") or {}
        user = row.get("userReview") or {}
        row["aiReviewed"] = ai.get("version") == REVIEW_VERSION and all(ai.get(key) == item for key, item in binding.items()) and bool(ai.get("evidence"))
        row["userReviewed"] = user.get("version") == REVIEW_VERSION and all(user.get(key) == item for key, item in binding.items()) and bool(user.get("reviewed"))
        row["changed"] = bool(row.get("candidateHash") and row.get("candidateHash") != row.get("originalPngHash", row.get("sourcePngHash")))
        row["checks"] = checks
        row["reason"] = (row.get("manualOverride") or row.get("finding") or {}).get("reason", row.get("staleReason", ""))
        if row.get("manualOverrideStale"):
            row["reason"] += " Source changed; the manual exclusion is retained, but its investigation is stale."
        if issues:
            row["state"], row["blockedReason"] = "blocked", "; ".join(dict.fromkeys(issues))
        elif row["classification"] == "excluded" or (row.get("editResult") or {}).get("status") == "skipped":
            row["state"], row["blockedReason"] = "skipped", ""
        elif row.get("candidateHash") == (row.get("applied") or {}).get("candidateHash") and row.get("sourceHash") == (row.get("applied") or {}).get("runtimeHash"):
            row["state"], row["blockedReason"] = "applied", ""
        elif not row.get("hasEditable"):
            row["state"], row["blockedReason"] = "not_prepared", "Make this image editable before starting image work."
        elif not row.get("changed"):
            row["state"], row["blockedReason"] = "editable", "No edited output is saved yet."
        elif row["aiReviewed"] or row["userReviewed"]:
            row["state"], row["blockedReason"] = "ready", ""
        else:
            row["state"], row["blockedReason"] = "needs_review", "Refresh saved AI review results or review this candidate."
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
                    raise ValueError("The preserved original image changed. Recover it before reviewing or applying this candidate.")
                if sha_file(project_path(root, result["runtimeBackup"])) != result.get("runtimeBackupHash"):
                    raise ValueError("The preserved original runtime backup changed. Recover it before applying this candidate.")
                result["originalIssue"] = ""
            except (OSError, ValueError) as exc:
                result["originalIssue"] = str(exc)
        return self._status(result)

    def refresh_assets(self, project_id, asset_ids):
        with self.lock:
            index = self._index(project_id)
            key = self.adapter.key(self.record(project_id)[1], self._profile(project_id))
            changed = False
            with index.connection() as db:
                for identity in self._ids(project_id, asset_ids):
                    old = index.get(identity, db)
                    row = self._inspect(project_id, old, old, key)
                    if row != old:
                        index.put(db, row, old.get("generation", "")); changed = True
            if changed:
                self._touch(project_id)

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
                raise ValueError("A pending image approval lacks valid integrity evidence. Its journal was retained.")
            relative = binding["path"]
            journal = read_json(project_path(root, relative), limit=48_000_000)
            if journal.get("version") != 1 or journal.get("projectId") != project_id or journal.get("id") != identity or journal.get("action") not in {"apply", "restore"}:
                raise ValueError("A pending image publication journal is invalid. Preserve it before recovery.")
            if self._journal_binding(journal) != binding["hash"]:
                raise ValueError("A pending image approval journal changed. No recovery receipt was manufactured; preserve and inspect its original record.")
            changed, original, conflicts = [], [], []
            with index.connection() as db:
                for frozen in journal["assets"]:
                    row = index.get(frozen["id"], db)
                    if not row or row.get("runtime") != frozen["runtime"]:
                        conflicts.append(frozen["id"]); continue
                    try:
                        actual = sha_file(project_path(root, frozen["runtime"]))
                    except (ValueError, OSError):
                        conflicts.append(frozen["id"]); continue
                    if actual == frozen["expectedRuntimeHash"]:
                        changed.append(frozen["id"])
                        if journal["action"] == "apply":
                            row["applied"] = {"candidateHash": frozen["candidateHash"], "runtimeHash": actual,
                                              "sourceHash": frozen["sourceHash"], "saved": journal["saved"],
                                              "review": frozen["review"], "recovered": True}
                        else:
                            row.pop("applied", None); row.pop("aiReview", None); row.pop("userReview", None)
                            row["originalRuntimeHash"] = actual
                        row = self._inspect(project_id, row, row)
                        index.put(db, row, row.get("generation", ""))
                    elif actual == frozen["sourceHash"]:
                        original.append(frozen["id"])
                    else:
                        conflicts.append(frozen["id"])
                        row["sourceIssue"] = "Runtime bytes differ from both sides of the interrupted publication. Resolve this conflict before applying."
                        index.put(db, self._status(row), row.get("generation", ""))
            status = "recovered" if len(changed) == len(journal["assets"]) else "interrupted"
            receipt = {"id": identity, "action": journal["action"], "assets": [row["id"] for row in journal["assets"]],
                       "saved": now(), "status": status, "completed": len(changed), "unchanged": len(original),
                       "conflicts": conflicts, "errors": journal.get("errors", []),
                       "message": "Recovered exact reviewed publication bytes." if status == "recovered" else
                                  "Publication was interrupted. Published images retain original backups; review recovery before continuing."}
            journal.update(status=status, recoveredAt=now(), receipt=receipt)
            write_json(project_path(root, relative), journal)
            value["receipts"] = [row for row in value["receipts"] if row["id"] != identity] + [receipt]
            value["receipts"] = value["receipts"][-200:]
            value["lastAction"] = receipt
            pending.pop(identity)
            if status == "interrupted":
                warning = "An image " + journal["action"] + " was interrupted: " + str(len(changed)) + " published, " + str(len(conflicts)) + " conflicts. Review its saved recovery receipt."
                if warning not in value["warnings"]:
                    value["warnings"].append(warning)
        value["pendingPublications"] = pending
        self._save(project_id, value)

    @staticmethod
    def _journal_binding(journal):
        return digest({key: journal[key] for key in ("version", "id", "projectId", "action", "saved", "assets")})

    def _scan(self, project_id):
        with self.lock:
            if project_id in self.mutating:
                raise ValueError("Finish the current image operation before scanning again.")
            for identity, event in self.cancellations.items():
                event.set()
            event = threading.Event()
            self.cancellations[project_id] = event
            generation = uuid.uuid4().hex
            value = self._load(project_id)
            profile = self._profile(project_id, value)
            if not profile["supported"]:
                raise ValueError(profile["reason"])
            value["profile"] = profile
            self._save(project_id, value)
            self.jobs[project_id] = {"id": generation, "action": "scan", "status": "running", "indexed": 0,
                                     "message": "Indexing image metadata. AI discovery has not started."}
            value["lastScan"] = deepcopy(self.jobs[project_id])
            self._save(project_id, value)
            worker = threading.Thread(target=self._scan_worker, args=(project_id, generation, event, profile), daemon=True)
            self.threads[generation] = worker
            worker.start()

    def _scan_worker(self, project_id, generation, event, profile):
        try:
            _project, root = self.record(project_id)
            index, seen, case_paths, collision_ids = self._index(project_id), set(), {}, set()
            key = self.adapter.key(root, profile)
            batch = {}
            for entry in self.adapter.inventory(root, profile, event.is_set):
                if event.is_set():
                    break
                identity = entry["id"]
                old = batch.get(identity) or index.get(identity)
                if not entry["runtime"] and old and old.get("runtime"):
                    entry = {**entry, "runtime": old["runtime"], "destination": old["destination"], "encrypted": old["encrypted"]}
                if identity in seen and entry.get("runtime") and old and old.get("encrypted") and not entry["encrypted"]:
                    entry = {**entry, "runtime": old["runtime"], "destination": old["destination"], "encrypted": True}
                folded = identity.casefold()
                if folded in case_paths and case_paths[folded] != identity:
                    collision_ids.update((identity, case_paths[folded]))
                case_paths[folded] = identity
                entry["collisionIssue"] = ""
                row = self._inspect(project_id, entry, old, key)
                row["generation"] = generation
                batch[identity] = row; seen.add(identity)
                if len(batch) >= 64:
                    self._scan_batch(project_id, generation, list(batch.values()), len(seen)); batch = {}
            if batch:
                self._scan_batch(project_id, generation, list(batch.values()), len(seen))
            with self.lock:
                if self.jobs.get(project_id, {}).get("id") != generation:
                    return
                if not event.is_set():
                    with index.connection() as db:
                        for record in db.execute("SELECT data FROM assets WHERE generation!=?", (generation,)).fetchall():
                            row = json.loads(record[0]); row.update(runtime="", sourceHash="", sourceIssue="Runtime source not found during the latest scan.")
                            index.put(db, self._status(row), generation)
                        for identity in collision_ids:
                            row = index.get(identity, db)
                            row["collisionIssue"] = "These filenames differ only by letter case and cannot be patched safely on Windows."
                            index.put(db, self._status(row), generation)
                    value = self._load(project_id)
                    fingerprint = hashlib.sha256()
                    for row in index.rows():
                        fingerprint.update((row["id"] + "\0" + row.get("sourceHash", "") + "\n").encode())
                    value["inventoryRevision"] = fingerprint.hexdigest()
                    self._save(project_id, value)
                index.selected(self._load(project_id)["selection"])
                self.jobs[project_id].update(status="stopped" if event.is_set() else "complete", indexed=len(seen),
                    message="Scan stopped. Indexed images remain available; unscanned coverage is incomplete." if event.is_set() else "Image inventory saved. Copy a discovery task to investigate text.")
                value = self._load(project_id)
                value["lastScan"] = deepcopy(self.jobs[project_id])
                self._save(project_id, value)
        except Exception as exc:
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
            raise ValueError("Finish or stop the image scan before changing this image batch.")
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
                filters = {key: options.get(key, default) for key, default in
                           (("query", ""), ("folder", ""), ("filter", "all"), ("selected_only", False))}
                ids = [row["id"] for row in self._index(project_id).rows(**filters)]
                value = self._load(project_id)
                selected = list(dict.fromkeys(value["selection"] + ids)) if options.get("mode") == "add" else ids
                value["selection"] = selected
                self._save(project_id, value); self._index(project_id).selected(selected)
                return {"state": self.state(project_id)}
            self._idle(project_id)
            if action == "use_recommendations":
                value = self._load(project_id)
                recommendations = [row["id"] for row in self._index(project_id).rows(filter="recommended")
                                   if not row.get("sourceIssue") and not row.get("manualOverride", {}).get("excluded")]
                value["selection"] = list(dict.fromkeys(value["selection"] + recommendations))
                self._save(project_id, value); self._index(project_id).selected(value["selection"])
            elif action in {"discovery_task", "edit_task", "revision_task"}:
                return self._task(project_id, action, options)
            elif action in {"refresh_findings", "refresh_results"}:
                return self._refresh_report(project_id, "discovery" if action == "refresh_findings" else "editing")
            elif action == "prepare":
                return self._prepare(project_id, options)
            elif action in {"user_review", "exclude", "include"}:
                self._review(project_id, action, options)
            elif action == "remove_copies":
                self._remove(project_id, options)
            elif action in {"preview_apply", "preview_restore"}:
                return self._preview_mutation(project_id, action.removeprefix("preview_"), options)
            elif action in {"apply", "restore"}:
                return self._execute(project_id, action, options)
            else:
                raise ValueError("Unknown image action.")
            return {"state": self.state(project_id)}

    def _scope(self, project_id, options, value):
        scope = options.get("scope", value["discovery"]["scope"])
        if scope not in SCOPES:
            raise ValueError("Choose All images, Current folders, or Selected images.")
        if scope == "selected":
            return scope, self._chosen(project_id, options)
        folders = options.get("folders", value["discovery"].get("folders", []))
        if scope == "folders" and not folders:
            raise ValueError("Choose at least one discovery folder.")
        identities = []
        for row in self._index(project_id).rows():
            if scope == "all" or any(row["folder"] == folder.rstrip("/") or row["folder"].startswith(folder.rstrip("/") + "/") for folder in folders):
                identities.append(row["id"])
        return scope, self._ids(project_id, identities)

    def _guidance(self, project_id):
        if hasattr(self.translation, "clean_drafts"):
            self.translation.clean_drafts(project_id)
        _project, root = self.record(project_id)
        names = [".dazedtl/glossary.txt", ".dazedtl/skills/game.md", ".dazedtl/skills/quirks.md"]
        if hasattr(self.translation, "documents"):
            names = [str(Path(row["path"]).relative_to(root)) for row in self.translation.documents(project_id).values()]
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
        scope, identities = self._scope(project_id, options, value) if kind == "discovery" else ("selected", self._chosen(project_id, options))
        self.refresh_assets(project_id, identities)
        value = self._load(project_id)
        rows = [self._index(project_id).get(identity) for identity in identities]
        if kind == "editing":
            blocked = [row["id"] for row in rows if not row.get("hasEditable") or row.get("sourceIssue") or row.get("originalIssue")]
            if blocked:
                raise ValueError("Prepare or resolve these selected images before copying an editing task: " + ", ".join(blocked[:6]))
        _project, root = self.record(project_id)
        comments = text(options.get("comments", options.get("comment", "")), "Revision comments", 40_000)
        guidance = self._guidance(project_id)
        previous_id = value[kind].get("requestId", "")
        if previous_id and previous_id in value["requests"]:
            previous_entry = value["requests"][previous_id]
            previous_path = project_path(root, previous_entry["path"])
            previous = read_json(previous_path, limit=48_000_000)
            current_bindings = [(row["id"], row["sourceHash"]) for row in rows]
            previous_bindings = [(row["id"], row["sourceHash"]) for row in previous.get("assets", [])]
            if (digest(previous) == previous_entry["hash"] and previous.get("kind") == kind
                    and previous.get("scope") == scope and previous.get("inventoryRevision") == value["inventoryRevision"]
                    and previous.get("guidance") == guidance and previous.get("revisionComments", "") == comments
                    and previous_bindings == current_bindings and previous.get("reviewVersion") == REVIEW_VERSION):
                value[kind]["copiedAt"] = now()
                self._save(project_id, value)
                return {"state": self.state(project_id), "text": self._task_text(project_id, previous, previous_path),
                        "requestId": previous_id, "request": str(previous_path), "report": previous["report"]}
        identity = uuid.uuid4().hex
        report = project_path(root, WORK + "/reports/" + identity + ".json", exists=False)
        assets = [{key: row.get(key) for key in ("id", "path", "sourceHash", "candidateHash", "runtime", "editable", "frozen",
                                                "width", "height", "mode", "encrypted", "sourceIssue")}
                  for row in rows]
        request = {"version": 1, "kind": kind, "id": identity, "projectId": project_id, "source": str(root),
                   "inventoryRevision": value["inventoryRevision"], "created": now(), "scope": scope,
                   "assets": assets, "guidance": guidance, "report": str(report),
                   "reviewVersion": REVIEW_VERSION,
                   "revisionComments": comments, "resumeFrom": previous_id,
                   "resumeRequest": value["requests"].get(previous_id, {}).get("path", ""),
                   "resumeReport": WORK + "/reports/" + previous_id + ".json" if previous_id else ""}
        request_path = project_path(root, WORK + "/requests/" + identity + ".json", exists=False)
        write_json(request_path, request)
        value["requests"][identity] = {"kind": kind, "path": str(request_path.relative_to(root)), "hash": digest(request)}
        value[kind].update(status="awaiting_results", requestId=identity, lastReport="", errors=[], copiedAt=now(), scope=scope)
        self._save(project_id, value)
        return {"state": self.state(project_id), "text": self._task_text(project_id, request, request_path), "requestId": identity,
                "request": str(request_path), "report": str(report)}

    def _task_text(self, project_id, request, request_path):
        root = self.record(project_id)[1]
        contract = self._contract(request, request_path)
        if request["kind"] == "editing":
            skill = self.adapter.skill(root, self._profile(project_id))
            # The Qt template assumes every PNG is scoped. Replace that statement before delegation.
            skill = skill.replace("every PNG", "each requested PNG").replace("Every PNG", "Each requested PNG")
            contract += "\n\nApply the following image-only methodology within the exact request scope above. "
            contract += "The request's asset list overrides any broader editable-folder instruction in this reference.\n\n" + skill
        return contract

    def _contract(self, request, path):
        kind = request["kind"]
        example = {"version": 1, "kind": kind, "requestId": request["id"], "projectId": request["projectId"],
                   "inventoryRevision": request["inventoryRevision"], "complete": False, "assets": []}
        if kind == "discovery":
            example["assets"] = [{"id": "copy an exact request asset ID", "sourceHash": "copy its source hash",
                                  "classification": "recommended", "method": "visual", "examined": True,
                                  "reason": "Explain the candidate", "evidence": "contact sheet/crop reference and observation",
                                  "variants": []}]
            instructions = (
                "Investigate which requested images need translation. This is discovery only; do not edit images or game files. "
                "Use metadata, byte-identical duplicate groups, numbered contact sheets and enlarged crops/originals where needed. "
                "Process bounded batches, cache results by source hash, resume unchanged work and record coverage honestly. "
                "Use Len's image census methodology as a reference, not its whole-game authorization. "
                "Local installed OCR is optional; do not install/download tools, invoke hosted OCR or paid services without separate authorization. "
                "A detector miss does not certify no text. Record uncertain/not_examined for unreadable, locked, failed or insufficiently examined assets. "
                "Allowed classifications: recommended, uncertain, no_text, already_english, not_examined, excluded. "
                "Positive examination methods are exactly visual, ocr, local_ocr, visual+ocr or visual+local_ocr. "
                "no_text and already_english require actual visual/OCR examination and evidence; detector-only findings cannot certify them. "
                "Related variants are suggestions, not reviewed equivalents. Only byte-identical source images may reuse evidence, identified explicitly. "
                "Never mark an unexamined image examined. Retain partial findings and write reports atomically; do not claim complete until every requested asset is accounted for.")
        else:
            example["assets"] = [{"id": "copy an exact request asset ID", "sourceHash": "copy its source hash",
                                  "candidateHash": "SHA-256 of the final editable PNG", "status": "edited", "reason": "",
                                  "review": {"version": REVIEW_VERSION, "visual": True, "alpha": True, "protectedPixels": True, "layout": True,
                                             "evidence": "original/candidate visual check and saved evidence reference"}}]
            instructions = (
                "Edit only the requested working PNG copies. Handle transcription, translation, rendering, validation and routine visual review. "
                "Keep game runtime originals read-only, preserve exact filenames, PNG format, dimensions, mode and transparency. "
                "Read frozen originals for redo and do not render repeatedly over translated pixels. Reuse glossary/context already saved in the request. "
                "No mandatory user sign-off for every image. Report genuine uncertainties/exclusions or material generative choices for user decision; "
                "do not call image-generation/paid services without separate authorization. "
                "Record edited/unchanged/skipped/needs_review/error for each asset and bind review to exact source and candidate hashes. "
                "Review original/candidate appearance, alpha, protected artwork and runtime layout. Do not assert checks you have not performed. "
                "Retain image_translation_log.md and reusable layout/resource records outside the editable tree. "
                "Write the structured report below atomically, with partial updates for resume. The app, not the assistant, applies reviewed runtime images.")
        return ("Perform this single user-authorized Guided image task using request " + str(path) + ".\n"
                "Request scope: " + str(len(request["assets"])) + " exact assets; project " + request["projectId"] + ".\n"
                + instructions + "\nRead-only image methodology reference: " + self.adapter.census_reference() + "\n"
                "The exact asset/source/guidance hashes and permitted editable paths are in the request. "
                "Unlisted assets are outside scope; do not broaden the task to the whole editable folder or whole game.\n"
                "Resume matching saved results from this report and request.resumeRequest/resumeReport. "
                "Reuse only source/candidate-bound evidence; changed bytes must be re-examined. "
                "Keep valid completed work and partial coverage, and save accepted reused findings under this request ID.\n"
                "Save findings to " + request["report"] + ". Required JSON schema example:\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
                + "\nCopying this task did not start an agent. Report what was completed, unresolved and skipped, then stop.")

    def _request(self, project_id, kind):
        value = self._load(project_id)
        identity = value[kind].get("requestId")
        entry = value["requests"].get(identity)
        if not entry:
            raise ValueError("Copy a scoped " + kind + " task before refreshing its report.")
        root = self.record(project_id)[1]
        request = read_json(project_path(root, entry["path"]), limit=48_000_000)
        if digest(request) != entry["hash"] or request.get("projectId") != project_id or request.get("kind") != kind:
            raise ValueError("The image task request changed or belongs to another project.")
        return value, request

    def _refresh_report(self, project_id, kind):
        value, request = self._request(project_id, kind)
        root = self.record(project_id)[1]
        path = project_path(root, WORK + "/reports/" + request["id"] + ".json", exists=False)
        if not path.exists():
            value[kind].update(status="awaiting_results", errors=["No saved report is available yet. Paste the copied task into your coding assistant, then refresh."])
            self._save(project_id, value)
            return {"state": self.state(project_id)}
        report = read_json(path, limit=48_000_000)
        if (not isinstance(report, dict) or report.get("version") != 1 or report.get("kind") != kind
                or report.get("projectId") != project_id or report.get("requestId") != request["id"]
                or report.get("inventoryRevision") != request["inventoryRevision"] or type(report.get("complete")) is not bool
                or not isinstance(report.get("assets"), list)):
            raise ValueError("The saved image report is invalid or belongs to another task/project/inventory.")
        for name, expected in request["guidance"].items():
            if sha_file(project_path(root, name)) != expected:
                raise ValueError("Saved guidance changed after this task. Copy a new task before accepting these results.")
        expected = {row["id"]: row for row in request["assets"]}
        identities, updates, errors = set(), [], []
        index = self._index(project_id)
        key = self.adapter.key(root, self._profile(project_id))
        for result in report["assets"]:
            if not isinstance(result, dict) or result.get("id") not in expected or result["id"] in identities:
                raise ValueError("The report contains duplicate or out-of-scope image findings.")
            identity = result["id"]; identities.add(identity)
            old = index.get(identity)
            row = self._inspect(project_id, old, old, key)
            if result.get("sourceHash") != expected[identity]["sourceHash"] or row.get("sourceHash") != result.get("sourceHash"):
                errors.append(identity + ": source evidence changed or is unavailable; findings remain unresolved.")
                updates.append(row); continue
            if kind == "discovery":
                classification = result.get("classification")
                if classification not in CLASSIFICATIONS or type(result.get("examined")) is not bool:
                    raise ValueError("Invalid discovery classification or examination state.")
                method = text(result.get("method", ""), "Discovery method", 100)
                evidence = text(result.get("evidence", ""), "Discovery evidence", 8000)
                reason = text(result.get("reason", ""), "Discovery reason", 4000)
                real_examination = method in EXAMINATION_METHODS and bool(evidence.strip())
                if classification in {"no_text", "already_english"} and (not result["examined"] or not real_examination):
                    classification = "not_examined"
                    errors.append(identity + ": a detector miss cannot certify text-free/English-only content.")
                examined = bool(result["examined"] and real_examination)
                variants = result.get("variants", [])
                if not isinstance(variants, list) or len(variants) > 10_000 or any(not isinstance(item, str) for item in variants):
                    raise ValueError("Invalid related image variants.")
                finding = {"requestId": request["id"], "sourceHash": row["sourceHash"], "classification": classification,
                           "method": method, "reason": reason, "evidence": evidence, "examined": examined,
                           "variants": variants, "saved": now()}
                if result.get("reusedFrom"):
                    other = index.get(result["reusedFrom"])
                    if not other or other.get("sourceHash") != row["sourceHash"]:
                        raise ValueError("Discovery evidence may be reused only for byte-identical source images.")
                    finding["reusedFrom"] = result["reusedFrom"]
                row["finding"] = finding
                row["classification"] = (row.get("manualOverride") or {}).get("classification", classification)
                row.pop("staleReason", None)
            else:
                if result.get("status") not in {"edited", "unchanged", "skipped", "needs_review", "error"}:
                    raise ValueError("Invalid image editing result status.")
                reason = text(result.get("reason", ""), "Editing reason", 4000)
                row["editResult"] = {"requestId": request["id"], "status": result["status"], "reason": reason, "saved": now()}
                review = result.get("review") or {}
                if result.get("candidateHash") != row.get("candidateHash") or not row.get("candidateHash"):
                    row.pop("aiReview", None)
                    errors.append(identity + ": candidate changed or is missing; saved review was not accepted.")
                elif (result["status"] in {"edited", "unchanged"} and isinstance(review, dict)
                      and review.get("version") == REVIEW_VERSION and request.get("reviewVersion") == REVIEW_VERSION
                      and all(review.get(check) is True for check in ("visual", "alpha", "protectedPixels", "layout"))
                      and isinstance(review.get("evidence"), str) and review["evidence"].strip()):
                    row["aiReview"] = {"version": REVIEW_VERSION, "requestId": request["id"], "sourceHash": row["sourceHash"],
                                       "candidateHash": row["candidateHash"], "evidence": text(review["evidence"], "Review evidence", 8000),
                                       "checks": {check: True for check in ("visual", "alpha", "protectedPixels", "layout")}, "saved": now()}
                else:
                    row.pop("aiReview", None)
            updates.append(self._status(row))
        with index.connection() as db:
            for row in updates:
                index.put(db, row, row.get("generation", ""))
        # Completion is accumulated across partial saves of this exact request, never inferred from its flag alone.
        accounted = 0
        for identity in expected:
            row = index.get(identity)
            accepted = row.get("finding" if kind == "discovery" else "editResult") or {}
            if accepted.get("requestId") == request["id"]:
                accounted += 1
        value[kind].update(status="complete" if report["complete"] and accounted == len(expected) and not errors else "partial",
                           lastReport=now(), reportPath=str(path.relative_to(root)), errors=errors,
                           accounted=accounted, requested=len(expected), reportHash=sha_file(path))
        self._save(project_id, value)
        return {"state": self.state(project_id)}

    def _prepare(self, project_id, options):
        identities = self._chosen(project_id, options)
        self.refresh_assets(project_id, identities)
        root, index, profile = self.record(project_id)[1], self._index(project_id), self._profile(project_id)
        rows = [index.get(identity) for identity in identities]
        errors, allowed = [], []
        for row in rows:
            if row.get("sourceIssue") or row.get("collisionIssue") or row.get("originalIssue"):
                errors.append(row["id"] + ": " + (row.get("sourceIssue") or row.get("collisionIssue") or row.get("originalIssue")))
                continue
            if not row.get("frozen"):
                raw = self.adapter.source_bytes(root, row, self.adapter.key(root, profile))
                runtime_bytes = project_path(root, row["runtime"]).read_bytes()
                if digest(runtime_bytes) != row["sourceHash"] or digest(raw) != row["sourcePngHash"]:
                    raise ValueError("A source image changed during preparation. Existing images were retained; refresh before continuing.")
                origin = "Runtime source before image preparation"
                if hasattr(self.adapter, "original_bytes"):
                    raw, runtime_original, origin = self.adapter.original_bytes(root, row, self.adapter.key(root, profile))
                else:
                    runtime_original = runtime_bytes
                original_metadata = png_metadata(raw)
                frozen = WORK + "/originals/" + row["id"]
                backup = WORK + "/runtime-originals/" + row["runtime"]
                frozen_path = project_path(root, frozen, exists=False)
                backup_path = project_path(root, backup, exists=False)
                if frozen_path.exists() or backup_path.exists():
                    raise ValueError("Unrecognized preserved image files exist. Inspect them before preparing new originals.")
                write_bytes(frozen_path, raw)
                write_bytes(backup_path, runtime_original)
                row.update(frozen=frozen, originalPngHash=digest(raw), originalRuntimeHash=row["sourceHash"],
                           originalMetadata=original_metadata, originalOrigin=origin,
                           runtimeBackup=backup, runtimeBackupHash=digest(runtime_original))
            allowed.append(row)
        with index.connection() as db:
            for row in allowed:
                index.put(db, row, row.get("generation", ""))
        result = self.adapter.prepare(root, profile, allowed, self.adapter.key(root, profile)) if allowed else {"completed": 0, "skipped": 0, "errors": []}
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
                        row["classification"] = finding.get("classification", "not_examined") if finding.get("sourceHash") == row.get("sourceHash") else "not_examined"
                    else:
                        if not reason.strip():
                            raise ValueError("Record a reason for excluding an image.")
                        row["manualOverride"] = {"classification": "excluded", "excluded": True, "reason": reason,
                                                 "sourceHash": row.get("sourceHash", ""), "saved": now()}
                        row["classification"] = "excluded"
                else:
                    if options.get("reviewed") is False:
                        row.pop("userReview", None)
                    else:
                        if not row.get("candidateHash") or not all(row.get("checks", {}).values()) or row.get("sourceIssue") or row.get("originalIssue"):
                            raise ValueError("Resolve structural/source issues before marking this image reviewed.")
                        row["userReview"] = {"version": REVIEW_VERSION, "sourceHash": row["sourceHash"], "candidateHash": row["candidateHash"],
                                             "reviewed": True, "reason": reason, "saved": now()}
                index.put(db, self._status(row), row.get("generation", ""))
        self._touch(project_id)

    def _remove(self, project_id, options):
        identities = self._chosen(project_id, options)
        root, index = self.record(project_id)[1], self._index(project_id)
        for identity in identities:
            row = index.get(identity)
            project_path(root, row["editable"], exists=False).unlink(missing_ok=True)
        self.refresh_assets(project_id, identities)

    def _preview_mutation(self, project_id, action, options):
        identities = self._chosen(project_id, options)
        self.refresh_assets(project_id, identities)
        root, index = self.record(project_id)[1], self._index(project_id)
        require_source_backup(root, lifecycle(self.translation.workspace, project_id))
        included, blocked, unchanged = [], [], 0
        for identity in identities:
            row = index.get(identity)
            if action == "apply":
                if row["state"] == "applied" or not row.get("changed") and row.get("hasEditable") and not row.get("sourceIssue"):
                    unchanged += 1; continue
                reason = row["blockedReason"] if row["state"] != "ready" else ""
            else:
                reason = "" if row.get("runtimeBackup") and (row.get("applied") or {}).get("runtimeHash") == row.get("sourceHash") else "This image has no current application receipt/original backup to restore."
                if not reason:
                    try:
                        if sha_file(project_path(root, row["runtimeBackup"])) != row["runtimeBackupHash"]:
                            reason = "The preserved original runtime bytes changed."
                    except (OSError, ValueError):
                        reason = "The preserved original runtime backup is missing."
            if reason:
                blocked.append({"id": identity, "path": row["path"], "reason": reason})
            else:
                included.append(row)
        token = uuid.uuid4().hex
        plan = {"projectId": project_id, "action": action, "assets": deepcopy(included), "created": time.monotonic(),
                "inventoryRevision": self._load(project_id)["inventoryRevision"], "selection": identities}
        self.previews[token] = plan
        # Bound memory and review lifetime without ever persisting execution authorization.
        for old_token, old in list(self.previews.items()):
            if time.monotonic() - old["created"] > 900:
                self.previews.pop(old_token, None)
        preview = {"token": token, "action": action, "assets": [self._public(row) for row in included],
                   "blocked": blocked, "included": len(included), "count": len(included), "selected": len(identities),
                   "unchanged": unchanged, "backups": [row.get("runtimeBackup", "") for row in included],
                   "expires": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                   "message": "If any included image fails validation, this batch is not applied."}
        return {"state": self.state(project_id), "preview": preview}

    def _execute(self, project_id, action, options):
        token = options.get("token")
        plan = self.previews.pop(token, None) if isinstance(token, str) else None
        if not plan or plan["projectId"] != project_id or plan["action"] != action or time.monotonic() - plan["created"] > 900:
            raise ValueError("This image review expired or was already used. Review the batch again.")
        if not plan["assets"]:
            raise ValueError("No images were included. Nothing was applied.")
        root, profile = self.record(project_id)[1], self._profile(project_id)
        require_source_backup(root, lifecycle(self.translation.workspace, project_id))
        identities = [row["id"] for row in plan["assets"]]
        self.refresh_assets(project_id, identities)
        index = self._index(project_id)
        current = [index.get(identity) for identity in identities]
        for before, after in zip(plan["assets"], current):
            if any(before.get(key) != after.get(key) for key in ("sourceHash", "candidateHash", "runtime", "editable", "runtimeBackupHash", "originalPngHash")):
                raise ValueError("An included image changed after review. Nothing was applied; review the batch again.")
            if action == "apply" and after["state"] != "ready":
                raise ValueError("An included image is no longer ready. Nothing was applied.")
            if action == "restore" and (after.get("applied") or {}).get("runtimeHash") != after.get("sourceHash"):
                raise ValueError("A runtime image changed after its application. Nothing was restored.")
        journal_id = uuid.uuid4().hex
        journal_path = WORK + "/publications/" + journal_id + ".json"
        key = self.adapter.key(root, profile)
        journal = {"version": 1, "id": journal_id, "projectId": project_id, "action": action,
                   "status": "publishing", "saved": now(), "assets": []}
        for row in current:
            expected_hash = self.adapter.output_hash(root, row, key) if action == "apply" else row["runtimeBackupHash"]
            journal["assets"].append({"id": row["id"], "runtime": row["runtime"], "sourceHash": row["sourceHash"],
                                      "candidateHash": row["candidateHash"], "expectedRuntimeHash": expected_hash,
                                      "runtimeBackup": row["runtimeBackup"], "runtimeBackupHash": row["runtimeBackupHash"],
                                      "review": "ai" if row.get("aiReviewed") else "user", "reviewVersion": REVIEW_VERSION})
        write_json(project_path(root, journal_path, exists=False), journal)
        value = self._load(project_id)
        value.setdefault("pendingPublications", {})[journal_id] = {"path": journal_path, "hash": self._journal_binding(journal)}
        self._save(project_id, value)
        self.mutating.add(project_id)
        try:
            result = self.adapter.apply(root, profile, current, key) if action == "apply" else self.adapter.restore(root, current)
            if not result.get("errors"):
                with index.connection() as db:
                    for row in current:
                        runtime_hash = sha_file(project_path(root, row["runtime"]))
                        if action == "apply":
                            row["applied"] = {"candidateHash": row["candidateHash"], "runtimeHash": runtime_hash,
                                              "sourceHash": row["sourceHash"], "saved": now(), "review": "ai" if row.get("aiReviewed") else "user"}
                        else:
                            row.pop("applied", None); row.pop("aiReview", None); row.pop("userReview", None)
                            row["originalRuntimeHash"] = runtime_hash
                        index.put(db, row, row.get("generation", ""))
            self.refresh_assets(project_id, identities)
            value = self._load(project_id)
            receipt = {"id": journal_id, "action": action, "assets": identities, "saved": now(),
                       "status": "error" if result.get("errors") else "complete", **result}
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
        if variant not in {"source", "original", "candidate"} or type(size) is not int or size < 0 or size > 2048:
            raise ValueError("Choose an original/candidate preview and valid thumbnail size.")
        with self.lock:
            self._ids(project_id, [asset_id])
            root, index = self.record(project_id)[1], self._index(project_id)
            row = index.get(asset_id)
            if variant == "candidate":
                path = project_path(root, row["editable"])
                if path.stat().st_size > 128_000_000:
                    raise ValueError("Editable image exceeds the supported 128 MB size limit.")
                raw = path.read_bytes()
            elif variant == "original" and row.get("frozen"):
                path = project_path(root, row["frozen"])
                if path.stat().st_size > 128_000_000:
                    raise ValueError("Original image exceeds the supported 128 MB size limit.")
                raw = path.read_bytes()
                if digest(raw) != row.get("originalPngHash"):
                    raise ValueError("The preserved original changed. Recover it before comparison.")
            else:
                raw = self.adapter.source_bytes(root, row, self.adapter.key(root, self._profile(project_id)))
            metadata = png_metadata(raw)
            fingerprint = digest(raw)
            cache_key = (project_id, asset_id, variant, fingerprint, size)
            cached = self.cache.get(cache_key)
            if cached is None:
                if size:
                    from PIL import Image
                    with Image.open(BytesIO(raw)) as image:
                        image.thumbnail((size, size))
                        image = image.convert("RGBA")
                        stream = BytesIO(); image.save(stream, format="PNG"); raw = stream.getvalue()
                cached = raw
                self.cache.put(cache_key, cached)
            return {"url": "data:image/png;base64," + base64.b64encode(cached).decode("ascii"),
                    "sha256": fingerprint, **metadata}
