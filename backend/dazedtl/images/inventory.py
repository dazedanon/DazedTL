"""Incremental disk index. Responses never materialize the entire image library."""

from collections import OrderedDict
from contextlib import contextmanager
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sqlite3
import warnings

from dazedtl.translation.files import project_path


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def signature(path):
    value = path.stat()
    return [
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    ]


def png_metadata(value):
    from PIL import Image

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(value)) as checked:
            checked.verify()
        with Image.open(BytesIO(value)) as image:
            if image.format != "PNG":
                raise ValueError("Expected a PNG image.")
            alpha = (
                image.convert("RGBA").getchannel("A")
                if "A" in image.getbands() or "transparency" in image.info
                else None
            )
            alpha_range = list(alpha.getextrema()) if alpha is not None else [255, 255]
            result = {
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "transparency": alpha_range[0] < 255,
                "alphaRange": alpha_range,
                "alphaChannel": "A" in image.getbands() or "transparency" in image.info,
                "frames": getattr(image, "n_frames", 1),
            }
            if result["frames"] != 1:
                raise ValueError(
                    "Animated PNGs require a separate workflow and cannot be patched here."
                )
        return result


class Index:
    def __init__(self, path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, folder TEXT, name TEXT, "
                "classification TEXT, state TEXT, selected INTEGER DEFAULT 0, examined INTEGER DEFAULT 0, generation TEXT, data TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS image_folder ON assets(folder)")
            db.execute(
                "CREATE INDEX IF NOT EXISTS image_state ON assets(state,classification)"
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, identity, db=None):
        if db is not None:
            result = db.execute(
                "SELECT data FROM assets WHERE id=?", (identity,)
            ).fetchone()
            return json.loads(result[0]) if result else None
        with self.connection() as connection:
            return self.get(identity, connection)

    @staticmethod
    def put(db, row, generation=""):
        db.execute(
            "INSERT INTO assets(id,folder,name,classification,state,examined,generation,data) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET folder=excluded.folder,name=excluded.name,"
            "classification=excluded.classification,state=excluded.state,examined=excluded.examined,generation=excluded.generation,data=excluded.data",
            (
                row["id"],
                row["folder"],
                row["filename"],
                row["classification"],
                row["state"],
                int(bool((row.get("finding") or {}).get("examined"))),
                generation,
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    @staticmethod
    def where(query="", folder="", filter="all", selected_only=False):
        parts, parameters = [], []
        if query:
            parts.append("instr(lower(id),?)>0")
            parameters.append(query.casefold())
        if folder:
            parts.append("(folder=? OR instr(folder,?)=1)")
            parameters.extend((folder.rstrip("/"), folder.rstrip("/") + "/"))
        if filter and filter != "all":
            parts.append("(classification=? OR state=?)")
            parameters.extend((filter, filter))
        if selected_only:
            parts.append("selected=1")
        return (" WHERE " + " AND ".join(parts) if parts else ""), parameters

    def rows(self, **filters):
        where, parameters = self.where(**filters)
        with self.connection() as db:
            for record in db.execute(
                "SELECT data FROM assets" + where + " ORDER BY id COLLATE NOCASE",
                parameters,
            ):
                yield json.loads(record[0])

    def selected(self, identities):
        with self.connection() as db:
            db.execute("UPDATE assets SET selected=0 WHERE selected=1")
            db.executemany(
                "UPDATE assets SET selected=1 WHERE id=?",
                ((value,) for value in identities),
            )

    def list(self, offset=0, limit=100, **filters):
        where, parameters = self.where(**filters)
        with self.connection() as db:
            total = db.execute(
                "SELECT count(*) FROM assets" + where, parameters
            ).fetchone()[0]
            selected_where = where + (" AND " if where else " WHERE ") + "selected=1"
            selected = db.execute(
                "SELECT count(*) FROM assets" + selected_where, parameters
            ).fetchone()[0]
            rows = db.execute(
                "SELECT data FROM assets"
                + where
                + " ORDER BY id COLLATE NOCASE LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            return {
                "items": [json.loads(row[0]) for row in rows],
                "total": total,
                "selectedMatched": selected,
                "offset": offset,
                "limit": limit,
            }

    def counts(self):
        with self.connection() as db:
            classifications = dict(
                db.execute(
                    "SELECT classification,count(*) FROM assets GROUP BY classification"
                )
            )
            states = dict(
                db.execute("SELECT state,count(*) FROM assets GROUP BY state")
            )
            selected = dict(
                db.execute(
                    "SELECT state,count(*) FROM assets WHERE selected=1 GROUP BY state"
                )
            )
            indexed = sum(classifications.values())
            examined = db.execute(
                "SELECT count(*) FROM assets WHERE examined=1"
            ).fetchone()[0]
            return {
                "indexed": indexed,
                "examined": examined,
                "recommended": classifications.get("recommended", 0),
                "uncertain": classifications.get("uncertain", 0),
                "notExamined": indexed - examined,
                "ready": states.get("ready", 0),
                "blocked": states.get("blocked", 0),
                "applied": states.get("applied", 0),
                "selected": sum(selected.values()),
                "selectedReady": selected.get("ready", 0),
                "selectedBlocked": selected.get("blocked", 0),
                "selectedNotPrepared": selected.get("not_prepared", 0),
                "selectedApplied": selected.get("applied", 0),
                "selectedEditable": sum(selected.values())
                - selected.get("not_prepared", 0),
                "missing": db.execute(
                    "SELECT count(*) FROM assets WHERE instr(data,?)>0",
                    ('"runtime":""',),
                ).fetchone()[0],
            }

    def folders(self):
        with self.connection() as db:
            return [
                {"path": path, "count": count}
                for path, count in db.execute(
                    "SELECT folder,count(*) FROM assets GROUP BY folder ORDER BY folder COLLATE NOCASE"
                )
            ]


class PreviewCache:
    def __init__(self, budget=24_000_000):
        self.values = OrderedDict()
        self.bytes, self.budget = 0, budget

    def get(self, key):
        value = self.values.get(key)
        if value is not None:
            self.values.move_to_end(key)
        return value

    def put(self, key, value):
        if len(value) > self.budget:
            return
        old = self.values.pop(key, b"")
        self.bytes += len(value) - len(old)
        self.values[key] = value
        while self.bytes > self.budget:
            self.bytes -= len(self.values.popitem(last=False)[1])


def inspect_row(root, adapter, row, old, key):
    """Hash and inspect changed bytes only; cache is tied to file stat signatures."""
    row = {**(old or {}), **row}
    row.update(
        filename=Path(row["id"]).name,
        folder=Path(row["id"]).parent.as_posix(),
        classification=row.get("classification", "not_examined"),
        sourceIssue="",
    )
    runtime_changed = False
    try:
        if not row.get("runtime"):
            raise ValueError(
                "The runtime source is missing. Locate it before editing or applying this copy."
            )
        runtime = project_path(root, row["runtime"])
        current_signature = signature(runtime)
        if row.get("encrypted") and key is None:
            raise ValueError(
                "The encryption key is unavailable. Restore System.json before preparing this asset."
            )
        if current_signature != row.get("sourceSignature") or row.get("encrypted"):
            source_hash = sha_file(runtime)
            raw = adapter.source_bytes(root, row, key)
            row.update(png_metadata(raw))
            runtime_changed = bool(
                row.get("sourceHash") and row["sourceHash"] != source_hash
            )
            row.update(
                sourceHash=source_hash,
                sourcePngHash=hashlib.sha256(raw).hexdigest(),
                sourceSignature=current_signature,
            )
    except (OSError, ValueError, KeyError) as exc:
        row["sourceIssue"] = str(exc)
        row["sourceHash"] = ""
    path = project_path(root, row["editable"], exists=False)
    row["editablePath"] = row["editable"]
    row["editable"] = row["editablePath"]
    row["hasEditable"] = path.is_file()
    row["candidateIssue"] = ""
    previous_candidate = row.get("candidateHash", "")
    try:
        if path.exists():
            current_signature = signature(path)
            if current_signature != row.get("candidateSignature"):
                if current_signature[2] > 128_000_000:
                    raise ValueError(
                        "Editable image exceeds the supported 128 MB size limit."
                    )
                raw = path.read_bytes()
                row["candidateHash"] = hashlib.sha256(raw).hexdigest()
                row["candidateMetadata"] = png_metadata(raw)
                row["candidateSignature"] = current_signature
        else:
            row.update(
                candidateHash="", candidateSignature=None, candidateMetadata=None
            )
    except (OSError, ValueError) as exc:
        row["candidateHash"] = ""
        row["candidateIssue"] = str(exc)
    if runtime_changed:
        applied = row.get("applied") or {}
        finding = row.get("finding") or {}
        if row.get("sourcePngHash") != applied.get("candidateHash") and finding.get(
            "sourceHash"
        ) != row.get("sourceHash"):
            row.pop("finding", None)
            if not row.get("manualOverride"):
                row["classification"] = "not_examined"
            elif row["manualOverride"].get("sourceHash") != row.get("sourceHash"):
                row["manualOverrideStale"] = True
            row["staleReason"] = (
                "The source changed since discovery. Investigate this image again."
            )
    if runtime_changed or row.get("candidateHash") != previous_candidate:
        row.pop("aiReview", None)
        row.pop("userReview", None)
    return row
