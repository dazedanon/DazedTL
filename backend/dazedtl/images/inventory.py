"""Incremental disk index. Responses never materialize the entire image library."""

import hashlib
import json
import sqlite3
import threading
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import cast

from dazedtl.translation.files import project_path

from . import families


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


@contextmanager
def _verified(value):
    """The PNG image of bytes that passed verification."""
    from PIL import Image

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(value)) as checked:
            checked.verify()
        with Image.open(BytesIO(value)) as image:
            yield image


def png_metadata(value):
    with _verified(value) as image:
        return describe_png(image)


def png_signature(value):
    """Metadata and family tile signature of verified PNG bytes, from one
    decode; the signature is None for a mode it can't read."""
    with _verified(value) as image:
        metadata = describe_png(image)
        try:
            return metadata, families.signature(image)
        except OSError, ValueError:
            return metadata, None


def png_preview(value, size):
    """Metadata, bytes and media type of a preview, from one decode.

    Without a size the preview is the PNG itself. A scaled copy is WebP,
    about as small at the screen's pixel density as a PNG at half of it.
    A preview only shows the image; indexing and application verify it with
    png_metadata, so a preview skips that separate pass.
    """
    from PIL import Image

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(value)) as image:
            image.load()
            metadata = describe_png(image)
            if not size:
                return metadata, value, "image/png"
            image.thumbnail((size, size))
            stream = BytesIO()
            image.convert("RGBA").save(stream, format="WEBP", quality=90, method=2)
            return metadata, stream.getvalue(), "image/webp"


def describe_png(image):
    if image.format != "PNG":
        raise ValueError("Expected a PNG image.")
    alpha = (
        (image if image.mode == "RGBA" else image.convert("RGBA")).getchannel("A")
        if "A" in image.getbands() or "transparency" in image.info
        else None
    )
    # A single channel's extrema are its (minimum, maximum) values.
    alpha_range = (
        list(cast(tuple[int, int], alpha.getextrema()))
        if alpha is not None
        else [255, 255]
    )
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
        self._prepare()

    def _prepare(self):
        """Create the parent folder, the sqlite file and the assets schema.
        Idempotent, so the connection path can call it to recover when the
        inventory file or its folder is deleted while the app runs."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, folder TEXT, name TEXT, "
                    "classification TEXT, state TEXT, selected INTEGER DEFAULT 0, examined INTEGER DEFAULT 0, generation TEXT, data TEXT)"
                )
                db.execute("CREATE INDEX IF NOT EXISTS image_folder ON assets(folder)")
                db.execute(
                    "CREATE INDEX IF NOT EXISTS image_state ON assets(state,classification)"
                )
                # Tile signatures of the untranslated originals, by size, for
                # families; the first table held an older signature.
                db.execute("DROP TABLE IF EXISTS tiles")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS family_tiles (id TEXT PRIMARY KEY,"
                    " width INTEGER, height INTEGER, mode TEXT, data BLOB)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS family_size ON family_tiles(width,height,mode)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS family_groups (id TEXT PRIMARY KEY, data TEXT)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
                )
        finally:
            db.close()

    @contextmanager
    def connection(self):
        # The inventory can disappear under us when the user deletes the game's
        # work folder outside the app, or restores the whole game folder from a
        # backup. Rebuild an empty one so the Image Manager stays open and the
        # next scan refills it, instead of failing the whole workspace snapshot.
        if not self.path.exists():
            self._prepare()
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
        # inspect_row hands over a new tile signature with the row; it is kept
        # in its own table so rows stay small, and families group again only
        # after a signature changed.
        if "familyTiles" in row:
            row = dict(row)
            original = row["original"]
            db.execute(
                "INSERT INTO family_tiles(id,width,height,mode,data) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET width=excluded.width,height=excluded.height,"
                "mode=excluded.mode,data=excluded.data",
                (
                    row["id"],
                    original["width"],
                    original["height"],
                    original["mode"],
                    row.pop("familyTiles"),
                ),
            )
            Index._regroup(db)
        elif (
            not row.get("original")
            and db.execute("DELETE FROM family_tiles WHERE id=?", (row["id"],)).rowcount
        ):
            Index._regroup(db)
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
        # The list's own view and Unsure leave images already in the game to
        # Applied.
        if filter == "not_applied":
            parts.append("state!='applied'")
        elif filter and filter != "all":
            parts.append("(classification=? OR state=?)")
            parameters.extend((filter, filter))
            if filter == "uncertain":
                parts.append("state!='applied'")
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
            # Ticked images already in the game have left the list's view, so
            # no view counts them as images in the list it hides.
            selected_where = (
                where
                + (" AND " if where else " WHERE ")
                + "selected=1 AND state!='applied'"
            )
            selected = db.execute(
                "SELECT count(*) FROM assets" + selected_where, parameters
            ).fetchone()[0]
            rows = db.execute(
                "SELECT data FROM assets"
                + where
                + " ORDER BY id COLLATE NOCASE LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            result = {
                "items": [json.loads(row[0]) for row in rows],
                "total": total,
                "selectedMatched": selected,
                "offset": offset,
                "limit": limit,
            }
            # The first page counts each view within the same folder and
            # search, so the view switch shows what each view would list.
            if offset == 0:
                scope, values = self.where(
                    query=filters.get("query", ""), folder=filters.get("folder", "")
                )
                views = db.execute(
                    "SELECT count(*), total(selected=1 AND state!='applied'),"
                    " total(classification='uncertain' AND state!='applied'),"
                    " total(classification='ready' OR state='ready'),"
                    " total(classification='applied' OR state='applied')"
                    " FROM assets" + scope,
                    values,
                ).fetchone()
                result["views"] = dict(
                    zip(
                        ("all", "list", "uncertain", "ready", "applied"),
                        (int(count) for count in views),
                    )
                )
            return result

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
            # An image in the game is no longer unsure.
            uncertain = db.execute(
                "SELECT count(*) FROM assets WHERE classification='uncertain'"
                " AND state!='applied'"
            ).fetchone()[0]
            # Images in the game and excluded ones are settled, so they are
            # not left for an investigation of the remaining images.
            remaining = db.execute(
                "SELECT count(*) FROM assets WHERE examined=0 AND state!='applied'"
                " AND classification!='excluded'"
            ).fetchone()[0]
            return {
                "indexed": indexed,
                "examined": examined,
                "recommended": classifications.get("recommended", 0),
                "uncertain": uncertain,
                "notExamined": remaining,
                "ready": states.get("ready", 0),
                "needsReview": states.get("needs_review", 0),
                "blocked": states.get("blocked", 0),
                "applied": states.get("applied", 0),
                "selected": sum(selected.values()),
                "selectedReady": selected.get("ready", 0),
                "selectedBlocked": selected.get("blocked", 0),
                "selectedNotPrepared": selected.get("not_prepared", 0),
                "selectedApplied": selected.get("applied", 0),
                "selectedSkipped": selected.get("skipped", 0),
                "selectedNeedsReview": selected.get("needs_review", 0),
                "selectedEditable": sum(selected.values())
                - selected.get("not_prepared", 0),
                "missing": db.execute(
                    "SELECT count(*) FROM assets WHERE instr(data,?)>0",
                    ('"runtime":""',),
                ).fetchone()[0],
            }

    @staticmethod
    def _regroup(db):
        db.execute(
            "INSERT INTO meta(key,value) VALUES('familiesStale','1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    def families(self, db=None):
        """Variant families among the indexed originals, one size at a time."""
        if db is None:
            with self.connection() as connection:
                return self.families(connection)
        found = []
        for width, height, mode, count in db.execute(
            "SELECT width, height, mode, count(*) FROM family_tiles"
            " GROUP BY width, height, mode HAVING count(*) > 1"
        ).fetchall():
            found += families.group_size(
                width,
                height,
                db.execute(
                    "SELECT id, data FROM family_tiles WHERE width=? AND height=? AND mode IS ?",
                    (width, height, mode),
                ),
                count,
            )
        return found

    def refresh_families(self):
        """Record each family once and on each member the family it belongs
        to, after a scan. Nothing is grouped again until a signature changes."""
        with self.connection() as db:
            stale = db.execute(
                "SELECT value FROM meta WHERE key='familiesStale'"
            ).fetchone()
            if stale and stale[0] == "0":
                return [
                    json.loads(data)
                    for (data,) in db.execute("SELECT data FROM family_groups")
                ]
            found = self.families(db)
            db.execute("DELETE FROM family_groups")
            db.executemany(
                "INSERT INTO family_groups(id,data) VALUES(?,?)",
                (
                    (family["id"], json.dumps(family, ensure_ascii=False))
                    for family in found
                ),
            )
            # A member keeps only the family's ID, size and region, so rows stay
            # small however large the family.
            membership = {
                member: {
                    "id": family["id"],
                    "size": len(family["members"]),
                    "region": family["region"],
                }
                for family in found
                for member in family["members"]
            }
            # Rows are read in pages, so only a page of them is in memory.
            last = 0
            while page := db.execute(
                "SELECT rowid, id, data FROM assets WHERE rowid>? ORDER BY rowid LIMIT 512",
                (last,),
            ).fetchall():
                last = page[-1][0]
                changes = []
                for _rowid, identity, data in page:
                    row = json.loads(data)
                    if row.get("family") != membership.get(identity):
                        if identity in membership:
                            row["family"] = membership[identity]
                        else:
                            row.pop("family", None)
                        changes.append(
                            (
                                json.dumps(
                                    row, ensure_ascii=False, separators=(",", ":")
                                ),
                                identity,
                            )
                        )
                db.executemany("UPDATE assets SET data=? WHERE id=?", changes)
            db.execute(
                "INSERT INTO meta(key,value) VALUES('familiesStale','0') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            return found

    def family(self, identity, db=None):
        """The family of an image, with where each member's original is and
        how far it is translated, or None."""
        if db is None:
            with self.connection() as connection:
                return self.family(identity, connection)
        summary = (self.get(identity, db) or {}).get("family")
        stored = (
            summary
            and db.execute(
                "SELECT data FROM family_groups WHERE id=?", (summary["id"],)
            ).fetchone()
        )
        if not stored:
            return None
        family = json.loads(stored[0])
        members = []
        for member in family["members"]:
            row = self.get(member, db) or {}
            members.append(
                {
                    "id": member,
                    "original": (row.get("original") or {}).get("path", ""),
                    "translated": families.translated(row),
                }
            )
        return {**family, "members": members}

    def folders(self):
        with self.connection() as db:
            return [
                {"path": path, "count": count}
                for path, count in db.execute(
                    "SELECT folder,count(*) FROM assets GROUP BY folder ORDER BY folder COLLATE NOCASE"
                )
            ]


class PreviewCache:
    """Recent previews as (metadata, bytes, media type), shared by threads."""

    def __init__(self, budget=24_000_000):
        self.values = OrderedDict()
        self.bytes, self.budget = 0, budget
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.values.get(key)
            if value is not None:
                self.values.move_to_end(key)
            return value

    def put(self, key, value):
        size = len(value[1])
        if size > self.budget:
            return
        with self.lock:
            old = self.values.pop(key, None)
            self.bytes += size - (len(old[1]) if old else 0)
            self.values[key] = value
            while self.bytes > self.budget:
                self.bytes -= len(self.values.popitem(last=False)[1][1])


def _observe(row, original, png_hash, metadata, tiles):
    """Record where a row's untranslated original is, and hand its tile
    signature to Index.put."""
    relative, _encrypted, stamp = original
    if tiles is None:
        row.pop("original", None)
        return
    row["familyTiles"] = tiles
    row["original"] = {
        "path": relative,
        "signature": stamp,
        "tiles": families.VERSION,
        "pngHash": png_hash,
        **{key: metadata[key] for key in ("width", "height", "mode")},
    }


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
    # Families compare untranslated originals, so a member already translated
    # in the game still matches its siblings. An original is decoded for its
    # tile signature only when its file changed, and one that is the runtime
    # file shares that file's stat, hash and decode.
    try:
        original = families.original_file(root, row)
    except ValueError:
        original = None
    known = row.get("original") or {}

    def stale(relative, stamp):
        return (known.get("path"), known.get("signature"), known.get("tiles")) != (
            relative,
            stamp,
            families.VERSION,
        )

    pending = None
    if original and original[0] != row.get("runtime"):
        try:
            stamp = signature(project_path(root, original[0]))
            if stale(original[0], stamp):
                pending = (*original, stamp)
        except OSError, ValueError:
            original = None
    try:
        if not row.get("runtime"):
            raise ValueError(
                "The runtime source is missing. Locate it before editing or applying this copy."
            )
        runtime = project_path(root, row["runtime"])
        current_signature = signature(runtime)
        if (
            original
            and original[0] == row["runtime"]
            and stale(original[0], current_signature)
        ):
            pending = (*original, current_signature)
        if row.get("encrypted") and key is None:
            raise ValueError(
                "The encryption key is unavailable. Restore System.json before preparing this asset."
            )
        if current_signature != row.get("sourceSignature") or row.get("encrypted"):
            source_hash = sha_file(runtime)
            raw = adapter.source_bytes(root, row, key)
            png_hash = hashlib.sha256(raw).hexdigest()
            if pending and pending[0] == row["runtime"]:
                metadata, tiles = png_signature(raw)
                _observe(row, pending, png_hash, metadata, tiles)
                pending = None
            else:
                metadata = png_metadata(raw)
            row.update(metadata)
            runtime_changed = bool(
                row.get("sourceHash") and row["sourceHash"] != source_hash
            )
            row.update(
                sourceHash=source_hash,
                sourcePngHash=png_hash,
                sourceSignature=current_signature,
            )
    except (OSError, ValueError, KeyError) as exc:
        row["sourceIssue"] = str(exc)
        row["sourceHash"] = ""
        if original and original[0] == row.get("runtime"):
            original = pending = None
    if pending:
        try:
            raw = adapter.source_bytes(
                root, {"runtime": pending[0], "encrypted": pending[1]}, key
            )
            _observe(row, pending, hashlib.sha256(raw).hexdigest(), *png_signature(raw))
        except OSError, ValueError, KeyError:
            original = None
    if original is None:
        row.pop("original", None)
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
