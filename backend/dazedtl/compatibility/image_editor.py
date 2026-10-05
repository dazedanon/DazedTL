"""The optional image editor's only boundary to preserved image tools.

No provider modules, hosted OCR, downloads or runtime asset replacement live here.
"""

from copy import deepcopy
from importlib.util import find_spec
from functools import lru_cache
from pathlib import Path

from dazedtl.storage import write_json, write_bytes


def local_ocr():
    # This package generation bundles its ONNX weights. The newer `rapidocr`
    # package may download models at construction, so it is deliberately absent.
    spec = find_spec("rapidocr_onnxruntime")
    if spec is None or not spec.origin:
        return {"available": False, "detail": "Local RapidOCR is not installed."}
    models = sorted(Path(spec.origin).parent.glob("models/*.onnx"))
    weights = {
        kind: next((path for path in models if f"_{kind}" in path.name.lower()), None)
        for kind in ("det", "rec", "cls")
    }
    if not all(weights.values()):
        return {
            "available": False,
            "detail": "Local RapidOCR model files are missing. No models are downloaded.",
        }
    return {
        "available": True,
        "detail": "RapidOCR uses installed local model files.",
        "weights": {key: str(value) for key, value in weights.items()},
    }


@lru_cache(maxsize=1)
def fonts():
    from util.imagetools.fonts import available_fonts, font_name
    from dazedtl.translation.files import digest

    return [
        {
            "id": digest(str(path).encode())[:24],
            "label": font_name(str(path)),
            "path": str(path),
        }
        for path in available_fonts()
    ]


def _job(root, work, originals):
    from util.imagetools.job import Job

    class EditorJob(Job):
        @property
        def work(self):
            return work

        def original_path(self, entry):
            path = originals.get(entry.relpath)
            return path if path is not None else work / "original" / entry.relpath

    return EditorJob(root)


def load(root, work, images):
    """Keep the native record in this project's manager workspace, not a shared file."""
    from util.imagetools.job import ImageEntry
    import json

    originals = {
        item["relative"]: Path(item["original"])
        for item in images
        if item.get("original")
    }
    job = _job(Path(root), Path(work), originals)
    if job.path.is_file():
        data = json.loads(job.path.read_text(encoding="utf-8"))
        job.language = str(data.get("language") or "English")
        job.images = [ImageEntry.from_dict(item) for item in data.get("images", [])]
    # sync preserves work belonging to images outside the opened selection.
    job.sync([item["relative"] for item in images])
    return job


def set_entry(job, value):
    from util.imagetools.job import ImageEntry, apply_flags
    from util.imagetools.style import Style, measure
    from PIL import Image
    import numpy as np

    entry = ImageEntry.from_dict(value)
    with Image.open(job.source_path(entry)) as original:
        pixels = np.array(original.convert("RGBA"))
    for block, raw in zip(entry.blocks, value["blocks"]):
        measured = measure(pixels, block, [item.box for item in entry.blocks]).to_dict()
        measured.update(raw.get("style") or {})
        measured["inpaint_method"] = "telea"
        block.style = Style.from_dict(measured)
    apply_flags(entry)
    job.images = [entry if old.relpath == entry.relpath else old for old in job.images]
    return entry


def image_size(path):
    from PIL import Image

    with Image.open(path) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("The native editor requires a single-frame PNG.")
        if image.width * image.height > 80_000_000:
            raise ValueError("This image is too large for the optional native editor.")
        return image.width, image.height


def ocr(job, entry):
    status = local_ocr()
    if not status["available"]:
        raise ValueError(status["detail"])
    from rapidocr_onnxruntime import RapidOCR
    from util.imagetools.geometry import Box
    from util.imagetools.ocr import Line, Reading, worth_keeping
    from util.imagetools.ocr.rapid import group_lines
    from PIL import Image
    import numpy as np

    with Image.open(job.source_path(entry)) as original:
        source = np.array(original.convert("RGBA"))
    engine = RapidOCR(
        **{f"{kind}_model_path": path for kind, path in status["weights"].items()}
    )
    result, _elapsed = engine(source[:, :, :3].copy())
    lines = []
    for polygon, text, _confidence in result or []:
        xs, ys = [point[0] for point in polygon], [point[1] for point in polygon]
        box = Box(min(xs), min(ys), max(xs), max(ys))
        if worth_keeping(text, box):
            lines.append(Line(text, box))
    entry.adopt(Reading(blocks=group_lines(lines), engine="rapidocr"))
    from util.imagetools.job import apply_flags

    apply_flags(entry)


def exchange(job, relatives, path):
    from util.imagetools.exchange import build

    scoped = deepcopy(job)
    scoped.images = [
        entry for entry in scoped.images if entry.relpath in set(relatives)
    ]
    payload = build(scoped)
    if not payload["images"]:
        raise ValueError(
            "Confirm at least one image with source text before translation."
        )
    # Never mirror into the frozen engine's files directory or another project.
    write_json(path, payload)
    return payload


def _verify_pixels(job, entry, expected_candidate, expected_original):
    from dazedtl.translation.files import digest

    for path, expected in (
        (job.image_path(entry), expected_candidate),
        (job.source_path(entry), expected_original),
    ):
        if (
            path.is_symlink()
            or not path.is_file()
            or expected
            and digest(path.read_bytes()) != expected
        ):
            raise ValueError(
                "Image pixels changed during editing. Reload before rendering or restoring."
            )


def render(job, entry, *, expected_candidate=None, expected_original=None):
    from io import BytesIO
    from PIL import Image
    from util.imagetools.render import render_entry
    from util.imagetools.paint import load_cut, load_layer
    from util.imagetools.style import ensure
    import numpy as np

    source_path = job.source_path(entry)
    _verify_pixels(job, entry, expected_candidate, expected_original)
    with Image.open(source_path) as original:
        mode = original.mode
        source = np.array(original.convert("RGBA"))
        metadata = {
            key: original.info[key]
            for key in ("icc_profile", "dpi", "exif")
            if key in original.info
        }
        colour_key = original.info.get("transparency")
    if mode not in {"RGB", "RGBA", "L", "LA"}:
        raise ValueError(
            "Indexed PNGs need the assistant image route to preserve their palette."
        )
    if colour_key is not None:
        raise ValueError(
            "Colour-key PNGs need the assistant image route to preserve their transparency."
        )
    ensure(source, entry)
    catalog = {item["id"]: item["path"] for item in fonts()}
    names = {
        block.block_id: block.style.font
        for block in entry.blocks
        if block.style is not None and block.style.font
    }
    if any(name not in catalog for name in names.values()):
        raise ValueError(
            "The saved font is unavailable. Choose an installed font before rendering."
        )
    for block in entry.blocks:
        if block.style is not None:
            # Background repair in this tool is deterministic OpenCV only.
            # Installed generative models are not silently selected by `ensure`.
            block.style.inpaint_method = "telea"
            if block.style.font:
                block.style.font = catalog[block.style.font]
    try:
        result = render_entry(
            source,
            entry,
            paint=load_layer(job, entry, source.shape),
            cut=load_cut(job, entry, source.shape),
        )
    finally:
        for block in entry.blocks:
            if block.block_id in names:
                block.style.font = names[block.block_id]
    if result.failures:
        raise ValueError("; ".join(note.message for note in result.failures))
    output = BytesIO()
    Image.fromarray(result.array).convert(mode).save(output, format="PNG", **metadata)
    _verify_pixels(job, entry, expected_candidate, expected_original)
    original_path = job.original_path(entry)
    if not original_path.is_file():
        write_bytes(original_path, job.image_path(entry).read_bytes())
    write_bytes(job.image_path(entry), output.getvalue())
    entry.status = "rendered"
    return [
        {
            "blockId": note.block_id,
            "ok": note.ok,
            "message": note.message,
            "tight": note.tight,
        }
        for note in result.notes
    ]


def undo(job, entry, *, expected_candidate=None, expected_original=None):
    _verify_pixels(job, entry, expected_candidate, expected_original)
    original = job.original_path(entry)
    if not original.is_file():
        raise ValueError("There is no preserved original to restore.")
    write_bytes(job.image_path(entry), original.read_bytes())
    entry.status = (
        "translated"
        if all(block.target_text or block.skip for block in entry.blocks)
        else "confirmed"
    )
