"""Machine checks of an edited PNG against its original.

The image report reader and the validator command an assistant runs share
these checks, so an edit the app accepts is the edit the assistant checked.
They catch what a look at the image misses: PNG colour metadata Pillow drops
when it saves, colour rewritten under fully transparent pixels, and pixels
changed outside the regions the edit declared.
"""

import struct
from io import BytesIO
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Every other chunk is kept byte for byte: colour (gAMA, cHRM, sRGB, iCCP),
# density (pHYs), text (tEXt, zTXt, iTXt) and a palette's PLTE and tRNS.
PIXEL_CHUNKS = {b"IHDR", b"IDAT", b"IEND"}
# Diagnostic backdrops: dark, light and mid ground, a strong colour that
# shows matte halos, and the transparency checkerboard.
BACKDROPS = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "gray": (128, 128, 128),
    "magenta": (255, 0, 255),
}
# What each failed check says in an image's review reason.
LABELS = {
    "decode": "the edited PNG does not decode",
    "dimensions": "its size differs from the original",
    "mode": "its colour mode differs from the original",
    "ihdr": "its PNG header differs from the original",
    "chunks": "PNG metadata chunks were lost or changed",
    "intermediate": "the text-free copy is missing or does not match the image",
    "unreadable": "the images could not be checked",
    "regions": "its cleanup or text region is missing or unreadable",
    "confined": "pixels changed outside the declared regions",
    "cleanup_confined": "the text-free copy changed pixels outside the cleanup region",
    "text_confined": "the lettering changed pixels outside the text region",
    "alpha_confined": "transparency changed outside the declared regions",
    "hidden_rgb": "colour under fully transparent pixels was rewritten",
    "protected": "protected pixels changed",
    "clearance": "the text comes too close to a protected shape",
}


def chunks(data):
    """Each chunk's type and complete bytes, in file order."""
    if not data.startswith(SIGNATURE):
        raise ValueError("The file is not a PNG.")
    found, offset = [], len(SIGNATURE)
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("The PNG is truncated.")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind, end = data[offset + 4 : offset + 8], offset + 12 + length
        if end > len(data):
            raise ValueError("The PNG is truncated.")
        found.append((kind, data[offset:end]))
        offset = end
        if kind == b"IEND":
            break
    return found


def kept(found):
    return [(kind, chunk) for kind, chunk in found if kind not in PIXEL_CHUNKS]


def encode_like(candidate, original):
    """The candidate's pixels in a PNG that keeps the original's header and
    every other chunk in place, for an edit saved by a tool that drops them.

    Refuses when the pixels need a different header (size, bit depth, colour
    type, interlacing) or a palette edit, since splicing could not keep both.
    """
    from PIL import Image

    with Image.open(BytesIO(candidate)) as image:
        image.load()
        pixels = image.copy()
    stream = BytesIO()
    pixels.save(stream, format="PNG", compress_level=9)
    fresh, template = chunks(stream.getvalue()), chunks(original)
    header = {kind: chunk for kind, chunk in fresh if kind == b"IHDR"}
    if header.get(b"IHDR") != dict(template).get(b"IHDR"):
        raise ValueError(
            "The edited pixels need a different PNG header (size, bit depth, colour type or interlacing) than the original."
        )
    for kind in (b"PLTE", b"tRNS"):
        if kind in dict(fresh) and dict(fresh)[kind] != dict(template).get(kind):
            raise ValueError("The edited pixels use a different palette.")
    pixel_data = b"".join(chunk for kind, chunk in fresh if kind == b"IDAT")
    output, written = [SIGNATURE], False
    for kind, chunk in template:
        if kind == b"IDAT":
            if not written:
                output.append(pixel_data)
                written = True
            continue
        output.append(chunk)
    result = b"".join(output)
    with Image.open(BytesIO(result)) as check:
        check.load()
        if check.mode != pixels.mode or check.tobytes() != pixels.tobytes():
            raise ValueError("The re-encoded PNG does not keep the edited pixels.")
    return result


def region(spec, size, read):
    """A declared region as a boolean mask: a mask PNG whose nonzero pixels
    are in it (read(path) returns its bytes), or [x, y, width, height] boxes."""
    import numpy as np

    width, height = size
    if isinstance(spec, str):
        from PIL import Image

        # Nonzero gray, as the inpainting bridge reads masks; a transparent
        # pixel is outside whatever colour it hides.
        with Image.open(BytesIO(read(spec))) as image:
            if image.size != size:
                raise ValueError(f"the mask {spec} is not the image's size")
            mask = np.asarray(image.convert("L")) > 0
            if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
                mask &= np.asarray(image.convert("RGBA").getchannel("A")) > 0
            return mask
    if not isinstance(spec, list) or not spec:
        raise ValueError(
            "Declare a region as a mask path or [x, y, width, height] boxes."
        )
    mask = np.zeros((height, width), bool)
    for box in spec:
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(type(value) is not int or value < 0 for value in box)
        ):
            raise ValueError("Each box is [x, y, width, height] in whole pixels.")
        x, y, w, h = box
        mask[y : y + h, x : x + w] = True
    return mask


def _decode(data):
    from PIL import Image

    image = Image.open(BytesIO(data))
    image.load()
    return image


def _rgba(image):
    import numpy as np

    return np.asarray(image.convert("RGBA")).astype(np.int16)


def _box(mask):
    """The [x, y, width, height] bounds of a mask's pixels."""
    import numpy as np

    rows, columns = np.nonzero(mask)
    if not len(rows):
        return None
    x, y = int(columns.min()), int(rows.min())
    return [x, y, int(columns.max()) - x + 1, int(rows.max()) - y + 1]


def _spread(mask, within):
    """How many of a mask's pixels fall outside `within`, and where."""
    outside = mask & ~within
    return {
        "changed": int(mask.sum()),
        "outside": int(outside.sum()),
        "box": _box(outside if outside.any() else mask),
    }


def check(
    original,
    candidate,
    *,
    intermediate=None,
    cleanup=None,
    text=None,
    protected=None,
    clearance=0,
):
    """Checks a candidate PNG's bytes against the original's.

    cleanup, text and protected are masks, or None when not declared; the
    intermediate is the text-free PNG between cleanup and lettering. Returns
    {"ok", "checks": {name: {"ok", "detail"?}}, "failures": [names]}.
    """
    import numpy as np

    checks = {}

    def record(name, ok, detail=None):
        checks[name] = {
            "ok": bool(ok),
            **({} if detail is None else {"detail": detail}),
        }

    source = _decode(original)
    try:
        edited = _decode(candidate)
    except Exception as exc:  # noqa: BLE001 - any decoder failure is the finding
        record("decode", False, str(exc))
        return _finish(checks)
    record("decode", True)
    record("dimensions", edited.size == source.size, list(edited.size))
    record("mode", edited.mode == source.mode, edited.mode)
    try:
        before, after = chunks(original), chunks(candidate)
    except ValueError as exc:
        record("ihdr", False, str(exc))
        return _finish(checks)
    record("ihdr", dict(before).get(b"IHDR") == dict(after).get(b"IHDR"))
    old, new = kept(before), kept(after)
    record("chunks", old == new, _chunk_change(old, new) if old != new else None)
    if edited.size != source.size:
        return _finish(checks)
    o, c = _rgba(source), _rgba(edited)
    k = None
    if intermediate is not None:
        try:
            between = _decode(intermediate)
            usable = between.size == source.size and between.mode == source.mode
        except Exception:  # noqa: BLE001 - an unreadable copy fails the check
            usable = False
        record("intermediate", usable)
        if usable:
            k = _rgba(between)
    changed = (c != o).any(-1)
    alpha = source.mode in {"RGBA", "LA", "PA"} or "transparency" in source.info
    if cleanup is None and text is None:
        record("regions", False)
    else:
        empty = np.zeros(changed.shape, bool)
        cleaned = empty if cleanup is None else cleanup
        lettered = empty if text is None else text
        allowed = cleaned | lettered
        spread = _spread(changed, allowed)
        record("confined", not spread["outside"], spread)
        if k is not None:
            spread = _spread((k != o).any(-1), cleaned)
            record("cleanup_confined", not spread["outside"], spread)
            spread = _spread((c != k).any(-1), allowed if text is None else lettered)
            record("text_confined", not spread["outside"], spread)
        if alpha:
            spread = _spread(c[..., 3] != o[..., 3], allowed)
            record("alpha_confined", not spread["outside"], spread)
        if alpha and (o[..., 3] == 0).any():
            # Lettering never has a reason to touch colour that stays fully
            # transparent; reconstruction may edge-pad it inside the cleanup.
            def hidden(a, b):
                return (
                    (a[..., 3] == 0)
                    & (b[..., 3] == 0)
                    & (a[..., :3] != b[..., :3]).any(-1)
                )

            rewritten = (
                hidden(o, c) & ~cleaned
                if k is None
                else (hidden(o, k) & ~cleaned) | hidden(k, c)
            )
            record(
                "hidden_rgb",
                not rewritten.any(),
                {"rewritten": int(rewritten.sum()), "box": _box(rewritten)},
            )
    if protected is not None:
        touched = changed & protected
        record(
            "protected",
            not touched.any(),
            {"changed": int(touched.sum()), "box": _box(touched)},
        )
        footprint = changed if k is None else (c != k).any(-1)
        if clearance and footprint.any() and protected.any():
            import cv2

            distance = cv2.distanceTransform(
                (~protected).astype(np.uint8), cv2.DIST_L2, 5
            )
            nearest = float(distance[footprint].min())
            record(
                "clearance",
                nearest >= clearance,
                {"nearest": round(nearest, 1), "required": clearance},
            )
    return _finish(checks)


def _chunk_change(old, new):
    def names(found):
        return [kind.decode("latin-1") for kind, _chunk in found]

    before, after = names(old), names(new)
    return {
        "missing": [kind for kind in before if kind not in after],
        "added": [kind for kind in after if kind not in before],
        "changed": sorted(
            {
                kind.decode("latin-1")
                for kind, chunk in old
                if kind in dict(new) and dict(new)[kind] != chunk
            }
        ),
    }


def _finish(checks):
    failures = [name for name, result in checks.items() if not result["ok"]]
    return {"ok": not failures, "checks": checks, "failures": failures}


def summary(result):
    """A failed result in one clause for the image's review reason."""
    labels = []
    for name in result["failures"]:
        label = LABELS.get(name) or str(name)
        detail = result["checks"].get(name, {}).get("detail")
        if name == "chunks" and isinstance(detail, dict):
            lost = detail["missing"] + detail["changed"]
            if lost:
                label += " (" + ", ".join(lost) + ")"
        labels.append(label)
    shown = labels[:3]
    if len(labels) > 3:
        shown.append(f"and {len(labels) - 3} more")
    return ", ".join(shown)


def diagnostics(original, candidate, folder, name, *, intermediate=None, regions=None):
    """Writes review composites and returns their paths: the original beside
    the edited image, over dark, light, mid gray, magenta and a checkerboard
    when it has transparency; the changed pixels, red where they leave the
    declared regions; the alpha planes and their difference; and the
    text-free copy brightened, where faint glyph remains show."""
    import numpy as np
    from PIL import Image

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source, edited = _decode(original), _decode(candidate)
    if edited.size != source.size:
        return []
    o, c = _rgba(source).astype(np.float64), _rgba(edited).astype(np.float64)
    changed = (c != o).any(-1)
    allowed = regions if regions is not None else np.zeros(changed.shape, bool)
    # The edit's own pixels set the crop; a broad declared region would
    # otherwise shrink the text to a corner of the whole canvas.
    focus = _box(changed) or _box(allowed) or [0, 0, source.width, source.height]
    pad = 24
    x0, y0 = max(0, focus[0] - pad), max(0, focus[1] - pad)
    x1 = min(source.width, focus[0] + focus[2] + pad)
    y1 = min(source.height, focus[1] + focus[3] + pad)

    def crop(pixels):
        return pixels[y0:y1, x0:x1]

    def over(pixels, ground):
        weight = pixels[..., 3:4] / 255
        return np.round(pixels[..., :3] * weight + ground * (1 - weight))

    rows, columns = np.mgrid[0 : source.height, 0 : source.width]
    checker = np.where(((rows // 8) + (columns // 8)) % 2, 200, 140)[
        ..., None
    ] * np.ones(3)
    grounds = [np.array(color, np.float64) for color in BACKDROPS.values()] + [checker]
    written = []

    def save(suffix, pixels):
        path = folder / f"{name}-{suffix}.png"
        Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(path)
        written.append(str(path))

    # An opaque image looks the same on every backdrop, so it gets one row.
    transparent = bool((o[..., 3] < 255).any() or (c[..., 3] < 255).any())
    save(
        "compare",
        np.vstack(
            [
                np.hstack([crop(over(o, ground)), crop(over(c, ground))])
                for ground in (grounds if transparent else grounds[:1])
            ]
        ),
    )
    marked = over(c, np.array(BACKDROPS["gray"], np.float64))
    marked[changed & allowed] = (
        marked[changed & allowed] * 0.5 + np.array([0, 160, 200]) * 0.5
    )
    marked[changed & ~allowed] = [255, 0, 0]
    save("changes", crop(marked))
    if transparent:
        difference = np.abs(c[..., 3] - o[..., 3]) * 4
        save("alpha", np.hstack([crop(o[..., 3]), crop(c[..., 3]), crop(difference)]))
    if intermediate is not None:
        between = _decode(intermediate)
        if between.size == source.size:
            save(
                "textfree",
                crop(over(_rgba(between).astype(np.float64), np.zeros(3)) * 2),
            )
    return written
