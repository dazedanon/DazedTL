"""Writing a PNG back the way it came, with only its pixels replaced.

Pillow decodes a PNG into pixels and a few ``info`` keys and, on save, writes a
new file from those alone. Gamma (gAMA), chromaticities (cHRM), the sRGB
intent, text chunks and anything else it does not model are dropped. A game
that honours gAMA or iCCP then shows the edited picture in different colours
from the original - everywhere, not only where the text was.

``encode_like`` keeps the source file instead: its IHDR (size, bit depth,
colour type) and every ancillary chunk stay, in their original order, and only
the image data is new. Only 8-bit greyscale, RGB and their alpha forms can be
rewritten this way; a palette or another bit depth would need an encoder that
reproduces it, so those are refused rather than silently converted.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Pillow's mode for each 8-bit colour type it can write back unchanged.
MODES = {0: "L", 2: "RGB", 4: "LA", 6: "RGBA"}


@dataclass(frozen=True)
class Header:
    width: int
    height: int
    bit_depth: int
    colour_type: int
    interlace: int

    @property
    def mode(self) -> str | None:
        """Pillow's mode for these pixels, or None if they cannot be rewritten."""
        return MODES.get(self.colour_type) if self.bit_depth == 8 else None

    def problem(self) -> str:
        """Why pixels in this format cannot be written back, or ""."""
        if self.colour_type == 3:
            return "it stores colours as a palette, which rewriting would replace"
        if self.mode is None:
            return (
                f"it stores {self.bit_depth}-bit samples, and only 8-bit PNGs can "
                "be rewritten without changing every pixel's format"
            )
        return ""


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """``(type, whole chunk)`` pairs in file order, length and CRC included."""
    if not data.startswith(SIGNATURE):
        raise ValueError("Not a PNG file.")
    found = []
    offset = len(SIGNATURE)
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("The PNG file is truncated.")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("The PNG file is truncated.")
        kind = data[offset + 4 : offset + 8]
        found.append((kind, data[offset:end]))
        offset = end
        if kind == b"IEND":
            break
    if not found or found[0][0] != b"IHDR" or found[-1][0] != b"IEND":
        raise ValueError("The PNG file has no IHDR or IEND chunk.")
    return found


def header(data: bytes) -> Header:
    """The IHDR of PNG *data*."""
    chunk = chunks(data)[0][1]
    width, height, depth, colour, _compression, _filter, interlace = struct.unpack(
        ">IIBBBBB", chunk[8:21]
    )
    return Header(width, height, depth, colour, interlace)


def encode_like(pixels: np.ndarray, template: bytes) -> bytes:
    """*pixels* as a PNG that keeps every chunk of *template* but its pixels.

    *pixels* is any 8-bit array Pillow understands, normally HxWx4 RGBA; it is
    converted to the template's own colour type first. The one IHDR field that
    can change is interlacing: Pillow cannot write Adam7, so an interlaced
    source comes back non-interlaced, which decodes to the same pixels. The
    result is decoded again before it is returned, so a file that would not
    reproduce *pixels* is never handed back.
    """
    from PIL import Image

    source = header(template)
    problem = source.problem()
    if problem:
        raise ValueError(f"This PNG cannot be rewritten: {problem}.")
    picture = Image.fromarray(np.ascontiguousarray(pixels)).convert(source.mode)
    if picture.size != (source.width, source.height):
        raise ValueError(
            f"The pixels are {picture.size[0]}x{picture.size[1]}, but the PNG "
            f"is {source.width}x{source.height}."
        )
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    fresh = chunks(buffer.getvalue())
    fresh_header = fresh[0][1]
    if header(buffer.getvalue()) != Header(
        source.width, source.height, 8, source.colour_type, 0
    ):
        raise ValueError("Pillow wrote a PNG header that does not match the source.")
    data = [chunk for kind, chunk in fresh if kind == b"IDAT"]

    out = [SIGNATURE]
    for kind, chunk in chunks(template):
        if kind == b"IHDR":
            out.append(chunk if not source.interlace else fresh_header)
        elif kind == b"IDAT":
            out.extend(data)
            data = []
        else:
            out.append(chunk)
    written = b"".join(out)

    with Image.open(io.BytesIO(written)) as check:
        check.load()
        same = check.mode == source.mode and np.array_equal(
            np.asarray(check), np.asarray(picture)
        )
    if not same:
        raise ValueError("The rewritten PNG does not decode to the edited pixels.")
    return written
