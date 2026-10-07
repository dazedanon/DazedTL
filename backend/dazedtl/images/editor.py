"""Optional native image editing, scoped to prepared copies and retained per project."""

import json
import math
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

from dazedtl.compatibility import image_editor as native
from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path, read_json


def _number(value, low, high, label, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
        or integer
        and int(value) != value
    ):
        raise ValueError(f"{label} is outside the supported range.")
    return int(value) if integer else value


def _colour(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Colours require four RGBA channels.")
    return [_number(item, 0, 255, "Colour", True) for item in value]


def validate_blocks(blocks, width, height):
    """Reject malformed geometry/style before native deserialization or any write."""
    if not isinstance(blocks, list) or len(blocks) > 2000:
        raise ValueError("An image can retain at most 2,000 text boxes.")
    result, seen = [], set()
    for value in blocks:
        if not isinstance(value, dict) or set(value) - {
            "id",
            "box",
            "source",
            "target",
            "skip",
            "angle",
            "style",
            "lines",
            "flags",
        }:
            raise ValueError("Invalid text box fields.")
        identity = value.get("id")
        if (
            not isinstance(identity, str)
            or not identity
            or len(identity) > 80
            or identity in seen
        ):
            raise ValueError("Text boxes need unique IDs.")
        seen.add(identity)
        box = value.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("Use x, y, width and height for each text box.")
        x, y, w, h = [
            _number(item, 0, max(width, height), "Box coordinate", True) for item in box
        ]
        if w < 1 or h < 1 or x + w > width or y + h > height:
            raise ValueError("Text boxes must stay inside the original image.")
        item = {
            "id": identity,
            "box": [x, y, w, h],
            "angle": _number(value.get("angle", 0), -180, 180, "Rotation"),
            "skip": value.get("skip", False),
            "source": value.get("source", ""),
            "target": value.get("target", ""),
        }
        if type(item["skip"]) is not bool or any(
            not isinstance(item[key], str) or len(item[key]) > 20000
            for key in ("source", "target")
        ):
            raise ValueError("Text and skip choices are invalid.")
        style = value.get("style")
        if style is not None:
            if not isinstance(style, dict):
                raise ValueError("Invalid text style.")
            # Retain measured style data while validating every renderer input.
            allowed = {
                "background",
                "fill",
                "text_color",
                "outline_color",
                "outline_width",
                "cap_height",
                "align",
                "font",
                "scale_x",
                "scale_y",
                "tracking",
                "bold",
                "italic",
                "overflow",
                "locked",
                "confidence",
                "notes",
                "row_colors",
                "column_colors",
                "donor",
                "inpaint_method",
            }
            if set(style) - allowed or style.get("background", "keep") not in {
                "transparent",
                "solid",
                "vgradient",
                "hgradient",
                "patch",
                "inpaint",
                "keep",
            }:
                raise ValueError("Invalid background repair style.")
            normalized = deepcopy(style)
            for key in ("fill", "text_color", "outline_color"):
                if normalized.get(key) is not None:
                    normalized[key] = _colour(normalized[key])
            for key, low, high in (
                ("outline_width", 0, 64),
                ("cap_height", 1, 512),
                ("scale_x", 25, 400),
                ("scale_y", 25, 400),
                ("tracking", -1000, 1000),
            ):
                if key in normalized:
                    normalized[key] = _number(normalized[key], low, high, key, True)
            if normalized.get("align", "center") not in {"left", "center", "right"}:
                raise ValueError("Choose left, center or right alignment.")
            font = normalized.get("font", "")
            if (
                not isinstance(font, str)
                or len(font) > 120
                or "/" in font
                or "\\" in font
            ):
                raise ValueError("Choose a font family, rather than a file path.")
            for key in ("bold", "italic", "overflow", "locked"):
                if key in normalized and type(normalized[key]) is not bool:
                    raise ValueError("Invalid style choice.")
            if "confidence" in normalized:
                normalized["confidence"] = _number(
                    normalized["confidence"], 0, 1, "Style confidence"
                )
            if "notes" in normalized and (
                not isinstance(normalized["notes"], list)
                or len(normalized["notes"]) > 100
                or any(
                    not isinstance(note, str) or len(note) > 2000
                    for note in normalized["notes"]
                )
            ):
                raise ValueError("Invalid measured style notes.")
            for key in ("row_colors", "column_colors"):
                if key in normalized:
                    if not isinstance(normalized[key], list) or len(
                        normalized[key]
                    ) > max(width, height):
                        raise ValueError("Invalid measured gradient.")
                    normalized[key] = [_colour(colour) for colour in normalized[key]]
            if normalized.get("donor") is not None:
                donor = normalized["donor"]
                if (
                    not isinstance(donor, list)
                    or len(donor) != 4
                    or any(type(n) is not int for n in donor)
                ):
                    raise ValueError("Invalid background donor box.")
                dx, dy, dw, dh = donor
                if (
                    dx < 0
                    or dy < 0
                    or dw < 1
                    or dh < 1
                    or dx + dw > width
                    or dy + dh > height
                ):
                    raise ValueError("Background donor box must stay inside the image.")
            normalized["inpaint_method"] = "telea"
            item["style"] = normalized
        # Native OCR geometry stays in the saved job; renderer submissions cannot
        # inject word masks, arbitrary paint paths or resource commands.
        result.append(item)
    if sum(len(item["source"]) + len(item["target"]) for item in result) > 1_000_000:
        raise ValueError("Keep one image's retained text below one million characters.")
    return result


class ImageEditor:
    def __init__(self, core):
        self.core = core

    def _context(self):
        return (
            self.core.backend.context()
            if hasattr(self.core.backend, "context")
            else nullcontext()
        )

    def _open(self, project_id, asset_ids):
        _project, root = self.core.record(project_id)
        work = self.core.workspace(project_id) / "native-editor"
        work = project_path(root, work.relative_to(root).as_posix(), exists=False)
        path = work / "image_job.json"
        saved = read_json(path, limit=8_000_000) if path.exists() else {}
        if not isinstance(saved, dict):
            raise ValueError("The retained image editor record is invalid.")
        selected = saved.get("selected_ids", []) if asset_ids is None else asset_ids
        if (
            not isinstance(selected, list)
            or len(selected) > 1000
            or any(not isinstance(item, str) for item in selected)
            or len(selected) != len(set(selected))
        ):
            raise ValueError(
                "Open at most 1,000 explicitly selected images in the optional editor."
            )
        rows = self.core.resolve_assets(project_id, selected) if selected else []
        editable_root = root / ".dazedtl/images"
        prepared = []
        for row in rows:
            editable = Path(row["editablePath"])
            if not editable.is_file():
                raise ValueError(
                    f"Make this image editable in Image Manager first: {row['path']}"
                )
            project_path(root, editable.relative_to(root).as_posix())
            relative = editable.relative_to(editable_root).as_posix()
            original = Path(row["frozenPath"]) if row.get("frozenPath") else None
            if original:
                project_path(root, original.relative_to(root).as_posix())
            if row.get("originalIssue"):
                raise ValueError(row["originalIssue"])
            prepared.append({"relative": relative, "original": original})
        # Stored native entries can never introduce a path outside editable copies.
        for entry in saved.get("images", []):
            relative = entry.get("image") if isinstance(entry, dict) else None
            if not isinstance(relative, str):
                raise ValueError("A retained editor image is invalid.")
            project_path(root, ".dazedtl/images/" + relative, exists=False)
        with self._context():
            job = native.load(editable_root, work, prepared)
            for row, item in zip(rows, prepared):
                entry = job.find(item["relative"])
                entry.width, entry.height = native.image_size(job.source_path(entry))
        revision = digest(
            {
                "record": digest(path.read_bytes()) if path.exists() else "new",
                "selected": selected,
                "sources": [
                    (row["id"], row.get("sourceHash"), row.get("candidateHash"))
                    for row in rows
                ],
            }
        )
        return root, work, job, rows, selected, revision

    def _persist(self, job, rows, selected, notes=None):
        previous = read_json(job.path, limit=8_000_000) if job.path.exists() else {}
        payload = job.to_dict()
        payload["selected_ids"] = selected
        payload["bindings"] = {
            **previous.get("bindings", {}),
            **{
                row["id"]: {
                    "sourceHash": row.get("sourceHash"),
                    "candidateHash": row.get("candidateHash"),
                }
                for row in rows
            },
        }
        payload["notes"] = {**previous.get("notes", {}), **(notes or {})}
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 8_000_000:
            raise ValueError(
                "The native image editor record exceeds 8 MB. Use a smaller image task."
            )
        write_json(job.path, payload)

    def state(self, project_id, asset_ids=None):
        _root, work, job, rows, selected, revision = self._open(project_id, asset_ids)
        saved = read_json(job.path, limit=8_000_000) if job.path.exists() else {}
        images = []
        for row in rows:
            relative = Path(row["editablePath"]).relative_to(job.root).as_posix()
            entry = job.find(relative)
            images.append(
                {
                    "assetId": row["id"],
                    "path": row["path"],
                    "width": entry.width,
                    "height": entry.height,
                    "status": entry.status,
                    "blocks": [block.to_dict() for block in entry.blocks],
                    "sourceHash": row.get("sourceHash", ""),
                    "candidateHash": row.get("candidateHash", ""),
                    # Encrypted sources differ from their decrypted copy, so
                    # a render is judged against the original PNG pixels.
                    "changed": bool(
                        row.get("candidateHash")
                        and row.get("candidateHash")
                        != row.get("originalPngHash", row.get("sourcePngHash"))
                    ),
                    "originalUrl": "",
                    "candidateUrl": "",
                    "notes": saved.get("notes", {}).get(row["id"], []),
                    "error": entry.error,
                    "engine": entry.engine,
                }
            )
        status = native.local_ocr()
        with self._context():
            fonts = [
                {key: item[key] for key in ("id", "label")} for item in native.fonts()
            ]
        return {
            "revision": revision,
            "selectedIds": selected,
            "images": images,
            "localOcr": {key: status[key] for key in ("available", "detail")},
            "fonts": fonts,
            "exchangePath": str(work / "image_text.json")
            if (work / "image_text.json").is_file()
            else "",
        }

    def save(self, project_id, revision, images, asset_ids=None):
        if hasattr(self.core, "_idle"):
            self.core._idle(project_id)
        if asset_ids is None and isinstance(images, list):
            asset_ids = [
                item.get("assetId") for item in images if isinstance(item, dict)
            ]
        _root, _work, job, rows, selected, current = self._open(project_id, asset_ids)
        if revision != current:
            raise ValueError(
                "Image work changed elsewhere. Reload before saving this draft."
            )
        if not isinstance(images, list) or len(images) > len(rows):
            raise ValueError("Save only images in the opened editor scope.")
        by_id, seen = {row["id"]: row for row in rows}, set()
        with self._context():
            font_ids = {item["id"] for item in native.fonts()}
        pending = []
        for item in images:
            if not isinstance(item, dict) or set(item) - {
                "assetId",
                "sourceHash",
                "candidateHash",
                "blocks",
                "status",
            }:
                raise ValueError("Invalid image editor fields.")
            row = by_id.get(item.get("assetId"))
            if not row or row["id"] in seen:
                raise ValueError("Save each opened image once.")
            seen.add(row["id"])
            if item.get("sourceHash") != row.get("sourceHash") or item.get(
                "candidateHash"
            ) != row.get("candidateHash"):
                raise ValueError(
                    "This image changed since the editor opened. Reload its current pixels."
                )
            entry = job.find(Path(row["editablePath"]).relative_to(job.root).as_posix())
            status = item.get("status", "needs_review")
            if status not in {"needs_review", "confirmed"}:
                raise ValueError(
                    "Choose whether corrected boxes and source text are confirmed."
                )
            value = entry.to_dict()
            blocks = validate_blocks(item.get("blocks"), entry.width, entry.height)
            if any(
                block.get("style", {}).get("font")
                and block["style"]["font"] not in font_ids
                for block in blocks
            ):
                raise ValueError(
                    "Choose an installed font from the editor's font list."
                )
            previous = {block["id"]: block for block in value["blocks"]}
            for block in blocks:
                old = previous.get(block["id"])
                if (
                    old
                    and old["box"] == block["box"]
                    and old["source"] == block["source"]
                ):
                    block["lines"] = old.get("lines", [])
            value.update(blocks=blocks, status=status, error="")
            pending.append(value)
        with self._context():
            for value in pending:
                native.set_entry(job, value)
            self._persist(job, rows, selected)
        return self.state(project_id, selected)

    def action(self, project_id, revision, action, asset_ids, arguments=None):
        if hasattr(self.core, "_idle"):
            self.core._idle(project_id)
        arguments = arguments or {}
        _root, work, job, rows, selected, current = self._open(project_id, asset_ids)
        if revision != current:
            raise ValueError("Image work changed elsewhere. Reload before continuing.")
        if not rows:
            raise ValueError("Select at least one editable image.")
        entries = {
            row["id"]: job.find(
                Path(row["editablePath"]).relative_to(job.root).as_posix()
            )
            for row in rows
        }
        by_id = {row["id"]: row for row in rows}
        notes, result = {}, {}
        with self._context():
            if action == "export":
                if hasattr(self.core.settings, "describe"):
                    language = self.core.settings.describe()["values"]["language"]
                    if (
                        not isinstance(language, str)
                        or not language
                        or len(language) > 80
                    ):
                        raise ValueError(
                            "Choose a target language in Settings before exporting image text."
                        )
                    job.language = language
                relatives = [entry.relpath for entry in entries.values()]
                payload = native.exchange(job, relatives, work / "image_text.json")
                included = {item["image"] for item in payload["images"]}
                included_ids = [
                    identity
                    for identity, entry in entries.items()
                    if entry.relpath in included
                ]
                binding = {
                    "projectId": project_id,
                    "assetIds": included_ids,
                    "sources": {
                        row["id"]: row.get("sourceHash")
                        for row in rows
                        if row["id"] in included_ids
                    },
                    "payload": payload,
                }
                write_json(work / "exchange-request.json", binding)
                result = {
                    "path": str(work / "image_text.json"),
                    "assetIds": included_ids,
                    "count": sum(len(item["regions"]) for item in payload["images"]),
                    "requestHash": digest(binding),
                }
            elif action == "import":
                binding = read_json(work / "exchange-request.json", limit=8_000_000)
                payload = arguments.get("payload") or read_json(
                    work / "image_text.json", limit=8_000_000
                )
                result = self._import(
                    job, entries, project_id, rows, selected, binding, payload
                )
            elif action in {"ocr", "render", "undo"}:
                if (
                    action == "ocr"
                    and any(entry.blocks for entry in entries.values())
                    and arguments.get("replaceConfirmed") is not True
                ):
                    raise ValueError(
                        "OCR would replace retained boxes. Confirm replacement first."
                    )
                result = {"completed": [], "errors": {}}
                for identity, entry in entries.items():
                    try:
                        if action == "ocr":
                            native.ocr(job, entry)
                        elif action == "render":
                            if (
                                entry.status
                                not in {"confirmed", "translated", "rendered"}
                                or not entry.blocks
                            ):
                                raise ValueError(
                                    "Confirm corrected source text before rendering this image."
                                )
                            if any(
                                block.source_text
                                and not block.target_text
                                and not block.skip
                                for block in entry.blocks
                            ):
                                raise ValueError(
                                    "Fill every translation or mark its box skipped before rendering."
                                )
                            row = by_id[identity]
                            notes[identity] = native.render(
                                job,
                                entry,
                                expected_candidate=row.get("candidateHash"),
                                expected_original=row.get("originalPngHash"),
                            )
                        else:
                            row = by_id[identity]
                            native.undo(
                                job,
                                entry,
                                expected_candidate=row.get("candidateHash"),
                                expected_original=row.get("originalPngHash"),
                            )
                        entry.error = ""
                        result["completed"].append(identity)
                    except (ValueError, OSError) as exc:
                        entry.error = str(exc)
                        result["errors"][identity] = str(exc)
                    # Each finished image is durable even if a later one fails.
                    self._persist(job, rows, selected, notes)
                    if action in {"render", "undo"}:
                        self.core.refresh_assets(project_id, [identity])
            else:
                raise ValueError("Unknown image editor action.")
            self._persist(job, rows, selected, notes)
        return {"state": self.state(project_id, selected), "result": result}

    @staticmethod
    def _import(job, entries, project_id, rows, selected, binding, payload):
        if (
            binding.get("projectId") != project_id
            or binding.get("assetIds") != selected
            or binding.get("sources")
            != {row["id"]: row.get("sourceHash") for row in rows}
        ):
            raise ValueError(
                "The image translation exchange belongs to another scope or source revision."
            )
        original = binding.get("payload")
        if (
            not isinstance(payload, dict)
            or not isinstance(original, dict)
            or any(
                payload.get(key) != original.get(key)
                for key in ("format", "version", "root", "language")
            )
        ):
            raise ValueError("The translated image exchange has a different identity.")
        expected = {
            (item["image"], region["id"]): region
            for item in original["images"]
            for region in item["regions"]
        }
        by_path = {entry.relpath: entry for entry in entries.values()}
        pending, seen, seen_images = [], set(), set()
        images = payload.get("images")
        if not isinstance(images, list):
            raise ValueError("Invalid translated image entries.")
        for image in images:
            if (
                not isinstance(image, dict)
                or image.get("image") not in by_path
                or image.get("image") in seen_images
                or not isinstance(image.get("regions"), list)
            ):
                raise ValueError("The exchange contains an unknown or duplicate image.")
            seen_images.add(image["image"])
            entry = by_path[image["image"]]
            for region in image["regions"]:
                if not isinstance(region, dict):
                    raise ValueError("Invalid translated text box.")
                if not isinstance(region.get("id"), str):
                    raise ValueError(
                        "Translated text boxes require their original IDs."
                    )
                key = (entry.relpath, region.get("id"))
                reference = expected.get(key)
                if (
                    reference is None
                    or key in seen
                    or any(
                        region.get(field) != reference.get(field)
                        for field in reference
                        if field != "target"
                    )
                ):
                    raise ValueError(
                        "Source text or box identity changed in the translation exchange."
                    )
                seen.add(key)
                block = entry.block(region["id"])
                if (
                    block.source_text != reference["source"]
                    or block.box.as_xywh() != reference["box"]
                ):
                    raise ValueError(
                        "Editor boxes changed after export. Export a fresh translation exchange."
                    )
                target = region.get("target", "")
                if not isinstance(target, str) or len(target) > 20000:
                    raise ValueError("Invalid image translation text.")
                if target.strip():
                    pending.append((entry, block, target))
        for entry, block, target in pending:
            block.target_text = target
            entry.status = "translated"
        return {
            "applied": len(pending),
            "missing": len(expected.keys() - seen),
            "empty": len(seen) - len(pending),
        }
