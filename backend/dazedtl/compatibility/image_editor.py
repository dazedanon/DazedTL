"""The optional image editor's only boundary to preserved image tools.

No provider modules, hosted OCR, downloads or runtime asset replacement live here.
"""

import os
from copy import deepcopy
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

from dazedtl.storage import write_bytes, write_json

#: The background reconstructions this editor runs: deterministic, with
#: nothing to download. Installed models are never chosen here. Harmonic is
#: the default because it settles glyphs over line art into the shading
#: instead of dragging the lines across them as Telea and Navier-Stokes do.
REPAIRS = ("harmonic", "telea", "ns")


def repair_method(value):
    """*value* when this editor runs it, otherwise the harmonic fill."""
    return value if value in REPAIRS else "harmonic"


def harmonic_fill(values, hole):
    """The image tools' exact Laplace fill over *hole*, for the family
    background solver."""
    from util.imagetools import harmonic

    return harmonic.fill(values, hole)


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


#: Where games keep the faces their own text is drawn in: MV and MZ beside
#: their data folder (a deployed MV under www), VX Ace in Fonts.
GAME_FONT_FOLDERS = (("fonts",), ("www", "fonts"))
#: FreeType reads WOFF as well as the desktop formats, and MV and MZ ship
#: their default faces as WOFF.
GAME_FONT_SUFFIXES = {".ttf", ".ttc", ".otf", ".woff", ".woff2"}


def fonts(game=None):
    """The editor's font list: the game's own faces first, then installed ones.

    Each entry's ``id`` is all a saved style holds; ``path`` stays here and is
    looked up again from the id when the image is drawn.
    """
    return [*(game_fonts(game) if game is not None else []), *installed_fonts()]


@lru_cache(maxsize=1)
def installed_fonts():
    from util.imagetools.fonts import available_fonts, font_name

    from dazedtl.translation.files import digest

    return [
        {
            "id": digest(str(path).encode())[:24],
            "label": font_name(str(path)),
            "path": str(path),
            "origin": "installed",
        }
        for path in available_fonts()
    ]


def game_fonts(game):
    """The faces a game ships for its own text, named by their place in it.

    A recipe fitted to an accepted image draws with the game's font
    (``fonts/UtsukushiFONT.otf``), which no installed list has, so adjusting
    that recipe here needs the same face. Its id comes from the path inside the
    game rather than on this machine, so a moved or copied game keeps the font
    it chose. Folders are matched without regard to case, as Windows and a VX
    Ace ``Fonts`` folder need. Links, files outside the game and anything
    FreeType cannot open are left out.
    """
    from util.imagetools.fonts import font_name

    from dazedtl.translation.files import digest, project_path

    found, labels = {}, {}
    for parts in GAME_FONT_FOLDERS:
        folder = _folder(Path(game), parts)
        if folder is None:
            continue
        try:
            names = sorted(os.listdir(folder), key=str.casefold)
        except OSError:
            continue
        for name in names:
            if Path(name).suffix.lower() not in GAME_FONT_SUFFIXES:
                continue
            relative = Path(folder, name).relative_to(game).as_posix()
            identity = digest(("game:" + relative.casefold()).encode())[:24]
            try:
                path = project_path(game, relative)
                stat = path.stat()
            except OSError, ValueError:
                continue
            if identity in found or not _readable(
                str(path), stat.st_size, stat.st_mtime_ns
            ):
                continue
            label = font_name(str(path))
            labels.setdefault(label, []).append(identity)
            found[identity] = {
                "id": identity,
                "label": label,
                "path": str(path),
                "origin": "game",
                "file": name,
            }
    # Two files of one family (a full face and its subset) read alike, so the
    # file tells them apart.
    for identities in labels.values():
        if len(identities) > 1:
            for identity in identities:
                found[identity]["label"] += " · " + found[identity]["file"]
    return [
        {key: value for key, value in item.items() if key != "file"}
        for item in found.values()
    ]


def _folder(game, parts):
    """*parts* below *game* as the disk spells them, if every one is a real folder."""
    folder = game
    for part in parts:
        try:
            names = os.listdir(folder)
        except OSError:
            return None
        match = next((name for name in sorted(names) if name.casefold() == part), None)
        if match is None:
            return None
        folder = folder / match
        if folder.is_symlink() or not folder.is_dir():
            return None
    return folder


@lru_cache(maxsize=256)
def _readable(path, _size, _modified):
    """Whether FreeType opens the face; the size and time key out a changed file."""
    from PIL import ImageFont

    try:
        ImageFont.truetype(path, 10)
    except OSError, ValueError:
        return False
    return True


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
    import json

    from util.imagetools.job import ImageEntry

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
    import numpy as np
    from PIL import Image
    from util.imagetools.job import ImageEntry, apply_flags
    from util.imagetools.style import Style, measure

    entry = ImageEntry.from_dict(value)
    with Image.open(job.source_path(entry)) as original:
        pixels = np.array(original.convert("RGBA"))
    for block, raw in zip(entry.blocks, value["blocks"]):
        measured = measure(pixels, block, [item.box for item in entry.blocks]).to_dict()
        measured.update(raw.get("style") or {})
        measured["inpaint_method"] = repair_method(measured.get("inpaint_method"))
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
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import (  # pyright: ignore[reportMissingImports]
        RapidOCR,  # Optional local OCR runtime, checked by the status above.
    )
    from util.imagetools.geometry import Box
    from util.imagetools.ocr import Line, Reading, worth_keeping
    from util.imagetools.ocr.rapid import group_lines

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


def render(job, entry, *, game, expected_candidate=None, expected_original=None):
    from io import BytesIO

    import numpy as np
    from PIL import Image
    from util.imagetools import pngfile
    from util.imagetools.paint import load_cut, load_layer
    from util.imagetools.render import render_entry
    from util.imagetools.style import ensure

    source_path = job.source_path(entry)
    _verify_pixels(job, entry, expected_candidate, expected_original)
    # The output is the source file with new pixels, so its header, colour
    # profile, gamma and text chunks reach the game unchanged.
    template = source_path.read_bytes()
    with Image.open(BytesIO(template)) as original:
        source = np.array(original.convert("RGBA"))
        colour_key = original.info.get("transparency")
    problem = pngfile.header(template).problem()
    if problem:
        raise ValueError(
            f"This image needs the assistant image route, because {problem}."
        )
    if colour_key is not None:
        raise ValueError(
            "Colour-key PNGs need the assistant image route to preserve their transparency."
        )
    ensure(source, entry)
    catalog = {item["id"]: item["path"] for item in fonts(game)}
    names = {
        block.block_id: block.style.font
        for block in entry.blocks
        if block.style is not None and block.style.font
    }
    if any(name not in catalog for name in names.values()):
        raise ValueError(
            "The saved font is no longer available. Choose a font from the list before rendering."
        )
    for block in entry.blocks:
        if block.style is not None:
            # Background repair in this tool is deterministic only. Installed
            # generative models are not silently selected by `ensure`.
            block.style.inpaint_method = repair_method(block.style.inpaint_method)
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
    output = pngfile.encode_like(result.array, template)
    _verify_pixels(job, entry, expected_candidate, expected_original)
    original_path = job.original_path(entry)
    if not original_path.is_file():
        write_bytes(original_path, job.image_path(entry).read_bytes())
    write_bytes(job.image_path(entry), output)
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
