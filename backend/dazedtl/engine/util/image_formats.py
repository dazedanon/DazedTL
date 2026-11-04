"""Image file formats Images edits besides PNG.

Images edits every image as a PNG copy. A game image in another format, such
as a KiriKiri game's BMP, JPEG or TLG file, is read into that copy here, and
Apply writes the edited copy back in the format the game's file holds, under
its own name: KiriKiri picks an image's decoder by its file's extension.
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import PurePosixPath

# The loose image files Images lists, by extension in any letter case.
LOOSE_IMAGE_EXTENSIONS = (".png", ".bmp", ".jpg", ".jpeg", ".tlg")
_CONVERTED = LOOSE_IMAGE_EXTENSIONS[1:]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TLG_SDS = b"TLG0.0\x00sds\x1a"
_TLG5 = b"TLG5.0\x00raw\x1a"
_TLG6 = b"TLG6.0\x00raw\x1a"
_MAX_PIXELS = 178_956_970  # Pillow's decompression-bomb limit


# Raised when this module turns a game image into other PNG bytes.
_DECODER_VERSION = 1


def decoder() -> str:
    """What makes a game image's PNG copy: this module and Pillow, which
    encodes the PNG. Saved hashes of copies hold while it stays the same."""
    import PIL

    return f"{_DECODER_VERSION}/Pillow {PIL.__version__}"


def png_name(relative: str) -> str:
    """The name of an image's PNG copy: its own for a PNG, else its name with
    `.png` added, so `title.bmp` and `title.png` keep separate copies."""
    return relative if relative.casefold().endswith(".png") else relative + ".png"


def runtime_name(copy: str) -> str:
    """The name of the image whose PNG copy is named `copy`; png_name's
    inverse."""
    image = copy[: -len(".png")]
    return image if PurePosixPath(image).suffix.casefold() in _CONVERTED else copy


def image_format(raw: bytes) -> str:
    """The format of an image file's bytes, whatever its name says."""
    if raw.startswith(_PNG_SIGNATURE):
        return "png"
    if raw.startswith(b"BM"):
        return "bmp"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw.startswith((_TLG_SDS, _TLG5, _TLG6)):
        return "tlg"
    return "unknown"


def to_png(raw: bytes) -> bytes:
    """An image file's pixels as PNG bytes; PNG bytes come back unchanged."""
    kind = image_format(raw)
    if kind in {"png", "unknown"}:
        # Left to the PNG checks, which name what is wrong with the file.
        return raw
    from PIL import Image

    if kind == "tlg":
        image = _tlg_image(raw)
    elif kind == "bmp":
        image = _bmp_image(raw)
    else:
        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def from_png(png: bytes, original: bytes) -> bytes:
    """Edited PNG bytes in the format of the game file `original`, which
    they replace; PNG bytes come back unchanged for a PNG original."""
    kind = image_format(original)
    if kind in {"png", "unknown"}:
        return png
    from PIL import Image

    with Image.open(BytesIO(png)) as opened:
        image = opened.convert("RGBA")
    if kind == "tlg":
        return _tlg_file(image, original)
    if kind == "bmp":
        return _bmp_file(image, original)
    stream = BytesIO()
    _opaque(image, "JPEG").save(stream, format="JPEG", quality=95, subsampling=0)
    return stream.getvalue()


def _opaque(image, label: str):
    """The RGB image of an edited RGBA copy whose game file keeps no
    transparency; a copy with transparent pixels can't be written so."""
    low, _high = image.getchannel("A").getextrema()
    if low < 255:
        raise ValueError(
            f"The game's {label} image has no transparency, but the edited copy has transparent pixels."
        )
    return image.convert("RGB")


def _bgra(image):
    """An image's pixels as KiriKiri keeps them, BGRA."""
    import numpy as np

    return np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, [2, 1, 0, 3]].copy()


def _bmp_header(raw: bytes) -> tuple[int, int, int, int, int]:
    """(pixel offset, width, height, bit count, compression) of a BMP file
    with a Windows info header."""
    if len(raw) < 34:
        raise ValueError("The BMP image is damaged.")
    offset = struct.unpack_from("<I", raw, 10)[0]
    width, height = struct.unpack_from("<ii", raw, 18)
    bits, compression = struct.unpack_from("<HI", raw, 28)
    return offset, width, height, bits, compression


def _bmp_alpha(raw: bytes):
    """The alpha channel KiriKiri reads from a 32-bit BMP's fourth bytes, or
    None for a BMP without one or with every fourth byte zero."""
    import numpy as np

    offset, width, height, bits, compression = _bmp_header(raw)
    if bits != 32 or compression != 0 or width <= 0 or not height:
        return None
    rows = abs(height)
    size = width * rows * 4
    if offset + size > len(raw):
        raise ValueError("The BMP image is damaged.")
    alpha = np.frombuffer(raw, np.uint8, size, offset).reshape(rows, width, 4)[
        :, :, 3
    ]
    if not alpha.any():
        return None
    # Rows run bottom to top unless the height is negative.
    return alpha[::-1] if height > 0 else alpha


def _bmp_image(raw: bytes):
    from PIL import Image

    with Image.open(BytesIO(raw)) as opened:
        image = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
    alpha = _bmp_alpha(raw)
    if alpha is not None:
        image = image.convert("RGBA")
        image.putalpha(Image.fromarray(alpha.copy(), "L"))
    return image


def _bmp_file(image, original: bytes) -> bytes:
    """A BMP KiriKiri reads as the original: 32-bit with the edited alpha in
    each pixel's fourth byte for an original with alpha, 32-bit with those
    bytes zero for an original that leaves them so, else 24-bit."""
    from PIL import Image

    _offset, _width, _height, bits, compression = _bmp_header(original)
    with Image.open(BytesIO(original)) as opened:
        # Pillow reads the alpha of a BMP whose masks give one.
        alpha = _bmp_alpha(original) is not None or "A" in opened.getbands()
    if alpha:
        pixels = _bgra(image)
    elif bits == 32 and compression == 0:
        pixels = _bgra(_opaque(image, "BMP"))
        pixels[:, :, 3] = 0
    else:
        stream = BytesIO()
        _opaque(image, "BMP").save(stream, format="BMP")
        return stream.getvalue()
    height, width = pixels.shape[:2]
    data = pixels[::-1].tobytes()
    header = struct.pack(
        "<2sIHHI", b"BM", 54 + len(data), 0, 0, 54
    ) + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, len(data), 2835, 2835, 0, 0)
    return header + data


# TLG, KiriKiri's own lossless format. TLG5 and TLG6 are read as KiriKiri Z's
# LoadTLG.cpp and tvpgl.c read them; edits are written as TLG5 with every
# block stored uncompressed, which KiriKiri reads as its own encoder writes a
# block that doesn't compress. An XP3 archive compresses it again.


def _tlg_parts(raw: bytes) -> tuple[bytes, bytes]:
    """The raw TLG5/TLG6 stream of a TLG file and the tag chunks a TLG0.0
    wrapper keeps after it."""
    if raw.startswith(_TLG_SDS):
        if len(raw) < 15:
            raise ValueError("The TLG image is damaged.")
        size = struct.unpack_from("<I", raw, 11)[0]
        return raw[15 : 15 + size], raw[15 + size :]
    return raw, b""


def _tlg_image(raw: bytes):
    from PIL import Image

    stream, _tags = _tlg_parts(raw)
    try:
        if stream.startswith(_TLG5):
            pixels, colors = _tlg5_pixels(stream)
        elif stream.startswith(_TLG6):
            pixels, colors = _tlg6_pixels(stream)
        else:
            raise ValueError("The TLG image has an unknown version.")
    except (IndexError, struct.error) as exc:
        raise ValueError("The TLG image is damaged.") from exc
    if colors == 1:
        # A grayscale TLG6 holds its values in the first channel.
        return Image.fromarray(pixels[:, :, 0].copy(), "L")
    # KiriKiri keeps pixels as BGRA.
    rgba = pixels[:, :, [2, 1, 0, 3]].copy()
    image = Image.fromarray(rgba, "RGBA")
    return image if colors == 4 else image.convert("RGB")


def _tlg_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
        raise ValueError("The TLG image is damaged or too large.")


def _lzss(data, size: int, text: bytearray, r: int) -> tuple[bytearray, int]:
    """TLG's LZSS: `data` decompressed with the 4096-byte ring `text` from
    position `r`, and the position after it."""
    out = bytearray()
    flags, i, end = 0, 0, len(data)
    while i < end:
        flags >>= 1
        if not flags & 256:
            flags = data[i] | 0xFF00
            i += 1
        if flags & 1:
            position = data[i] | ((data[i + 1] & 0x0F) << 8)
            length = (data[i + 1] >> 4) + 3
            i += 2
            if length == 18:
                length += data[i]
                i += 1
            if (
                position + length <= 4096
                and r + length <= 4096
                and (position + length <= r or r + length <= position)
            ):
                chunk = text[position : position + length]
                text[r : r + length] = chunk
                out += chunk
                r = (r + length) & 0xFFF
            else:
                for _ in range(length):
                    value = text[position]
                    out.append(value)
                    text[r] = value
                    position = (position + 1) & 0xFFF
                    r = (r + 1) & 0xFFF
        else:
            value = data[i]
            i += 1
            out.append(value)
            text[r] = value
            r = (r + 1) & 0xFFF
    if len(out) < size:
        raise ValueError("The TLG image is damaged.")
    return out, r


def _tlg5_pixels(stream: bytes):
    import numpy as np

    colors = stream[11]
    width, height, block = struct.unpack_from("<III", stream, 12)
    if colors not in (3, 4) or not block:
        raise ValueError("The TLG image has an unsupported color type.")
    _tlg_size(width, height)
    position = 24 + ((height - 1) // block + 1) * 4
    text, r = bytearray(4096), 0
    planes = np.zeros((height, width, 4), np.uint8)
    for top in range(0, height, block):
        rows = min(block, height - top)
        for color in range(colors):
            mark = stream[position]
            size = struct.unpack_from("<I", stream, position + 1)[0]
            data = stream[position + 5 : position + 5 + size]
            position += 5 + size
            if mark == 0:
                data, r = _lzss(data, rows * width, text, r)
            if len(data) < rows * width:
                raise ValueError("The TLG image is damaged.")
            planes[top : top + rows, :, color] = np.frombuffer(
                bytes(data[: rows * width]), np.uint8
            ).reshape(rows, width)
    planes[:, :, 0] += planes[:, :, 1]
    planes[:, :, 2] += planes[:, :, 1]
    pixels = planes.cumsum(axis=1, dtype=np.uint8).cumsum(axis=0, dtype=np.uint8)
    if colors == 3:
        pixels[:, :, 3] = 255
    return pixels, colors


def _tlg5_file(pixels, colors: int) -> bytes:
    """BGRA `pixels` as a TLG5 stream of `colors` channels."""
    import numpy as np

    height, width = pixels.shape[:2]
    block = 4
    upper = np.zeros_like(pixels)
    upper[1:] = pixels[:-1]
    vertical = pixels - upper
    left = np.zeros_like(vertical)
    left[:, 1:] = vertical[:, :-1]
    values = vertical - left
    values[:, :, 0] -= values[:, :, 1]
    values[:, :, 2] -= values[:, :, 1]
    blocks, sizes = [], []
    for top in range(0, height, block):
        rows = min(block, height - top)
        parts = [
            b"\x01"
            + struct.pack("<I", rows * width)
            + values[top : top + rows, :, color].tobytes()
            for color in range(colors)
        ]
        sizes.append(sum(len(part) for part in parts))
        blocks.extend(parts)
    return (
        _TLG5
        + bytes([colors])
        + struct.pack("<III", width, height, block)
        + struct.pack(f"<{len(sizes)}I", *sizes)
        + b"".join(blocks)
    )


def _tlg_file(image, original: bytes) -> bytes:
    stream, tags = _tlg_parts(original)
    colors = stream[11]
    if colors == 1:
        # KiriKiri reads TLG5 in color only, so a grayscale image stays TLG6.
        import numpy as np

        written = _tlg6_gray_file(np.asarray(_opaque(image, "TLG").convert("L")))
    else:
        written = _tlg5_file(
            _bgra(image if colors == 4 else _opaque(image, "TLG")), colors
        )
    if not original.startswith(_TLG_SDS):
        return written
    return _TLG_SDS + struct.pack("<I", len(written)) + written + tags


# TLG6's Golomb tables: each row of _GOLOMB_COMPRESSED says how many of the
# 1024 running sums give each bit length, for one of the four counters.
_GOLOMB_COMPRESSED = (
    (3, 7, 15, 27, 63, 108, 223, 448, 130),
    (3, 5, 13, 24, 51, 95, 192, 384, 257),
    (2, 5, 12, 21, 39, 86, 155, 320, 384),
    (2, 3, 9, 18, 33, 61, 129, 258, 511),
)
_GOLOMB_BITS = [0] * (1024 * 4)
for _n, _row in enumerate(_GOLOMB_COMPRESSED):
    _a = 0
    for _bits, _count in enumerate(_row):
        for _ in range(_count):
            _GOLOMB_BITS[_a * 4 + _n] = _bits
            _a += 1


def _golomb(pool: bytes, count: int) -> bytearray:
    """`count` residuals of one TLG6 channel, as unsigned bytes, from the
    run-length Golomb codes in `pool`; bits are read lowest first."""
    import numpy as np

    padded = np.frombuffer(bytes(pool) + bytes(8), np.uint8).astype(np.uint32)
    words = (
        padded[:-3] | (padded[1:-2] << 8) | (padded[2:-1] << 16) | (padded[3:] << 24)
    ).tolist()
    table = _GOLOMB_BITS
    out = bytearray(count)
    position = 1
    zero = not pool[0] & 1
    n, a, i = 3, 0, 0
    while i < count:
        # A run's length, as a gamma code.
        start = position
        word = words[position >> 3] >> (position & 7)
        while not word:
            position += 24
            word = words[position >> 3] >> (position & 7)
        position += (word & -word).bit_length()
        bits = position - start - 1
        run = (1 << bits) + (
            (words[position >> 3] >> (position & 7)) & ((1 << bits) - 1)
        )
        position += bits
        if i + run > count:
            raise ValueError("The TLG image is damaged.")
        if zero:
            i += run
        else:
            for i in range(i, i + run):
                k = table[a * 4 + n]
                byte = position >> 3
                word = words[byte] >> (position & 7)
                if word:
                    first = (word & -word).bit_length()
                    quotient = first - 1
                    position += first
                else:
                    quotient = pool[byte + 4]
                    position = (byte + 5) << 3
                value = (quotient << k) + (
                    (words[position >> 3] >> (position & 7)) & ((1 << k) - 1)
                )
                position += k
                half = value >> 1
                out[i] = (half + 1 if value & 1 else -half - 1) & 0xFF
                a += half
                n -= 1
                if n < 0:
                    a >>= 1
                    n = 3
            i += 1
        zero = not zero
    return out


# TLG6's color correlation filters: for each of the 16 codes, how B, G and R
# follow from the B, G and R residuals, as multiples of each.
_CHROMA = (
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((1, 1, 0), (0, 1, 0), (0, 1, 1)),
    ((1, 0, 0), (1, 1, 0), (1, 1, 1)),
    ((1, 1, 1), (0, 1, 1), (0, 0, 1)),
    ((1, 0, 1), (1, 1, 1), (1, 1, 2)),
    ((1, 0, 1), (1, 1, 1), (0, 0, 1)),
    ((1, 1, 0), (0, 1, 0), (0, 0, 1)),
    ((1, 0, 0), (1, 1, 0), (0, 0, 1)),
    ((1, 0, 0), (0, 1, 0), (0, 1, 1)),
    ((2, 1, 1), (1, 1, 1), (1, 0, 1)),
    ((1, 0, 1), (0, 1, 1), (0, 0, 1)),
    ((1, 0, 0), (1, 1, 0), (1, 0, 1)),
    ((1, 0, 0), (1, 1, 1), (1, 0, 1)),
    ((1, 1, 0), (1, 2, 1), (1, 1, 1)),
    ((1, 1, 1), (0, 1, 1), (1, 1, 2)),
    ((1, 0, 0), (2, 1, 0), (2, 0, 1)),
)


def _tlg6_order(width: int, lines: int):
    """Where each pixel of a TLG6 group of `lines` lines sits among the
    group's values: each 8-pixel-wide block's values run along its lines in
    turn, a block of an odd column from its bottom line up, and each odd
    line right to left."""
    import numpy as np

    x = np.arange(width)
    column = x // 8
    start = column * 8
    span = np.minimum(8, width - start)
    local = x - start
    line = np.arange(lines)[:, None]
    stored = np.where(column % 2 == 1, lines - 1 - line, line)
    across = np.where(line % 2 == 1, span - 1 - local, local)
    return column * lines * 8 + stored * span + across


class _Bits:
    """TLG6's bit stream, written lowest bit first."""

    def __init__(self):
        self.out, self.pending, self.count = bytearray(), 0, 0

    def put(self, value: int, length: int) -> None:
        self.pending |= value << self.count
        self.count += length
        while self.count >= 8:
            self.out.append(self.pending & 0xFF)
            self.pending >>= 8
            self.count -= 8

    def position(self) -> int:
        return len(self.out) * 8 + self.count

    def gamma(self, value: int) -> None:
        length = value.bit_length() - 1
        self.put((1 << length) | ((value & ((1 << length) - 1)) << (length + 1)), 2 * length + 1)


def _golomb_codes(values) -> tuple[bytes, int]:
    """KiriKiri's run-length Golomb codes of signed residuals, as its encoder
    writes them, and their length in bits; the decoder is _golomb."""
    table = _GOLOMB_BITS
    bits = _Bits()
    bits.put(1 if values[0] else 0, 1)
    n, a, i, zeros = 3, 0, 0, 0
    while i < len(values):
        if not values[i]:
            zeros += 1
            i += 1
            continue
        if zeros:
            bits.gamma(zeros)
        end = i
        while end < len(values) and values[end]:
            end += 1
        bits.gamma(end - i)
        for value in values[i:end]:
            k = table[a * 4 + n]
            m = (2 * value if value >= 0 else -2 * value - 1) - 1
            quotient = m >> k
            position = bits.position()
            # A quotient reaching four bytes on is written as a byte there.
            limit = ((position >> 3) + 4) * 8 - position
            if quotient >= limit:
                bits.put(0, limit)
                bits.put(quotient, 8)
            else:
                bits.put(1 << quotient, quotient + 1)
            bits.put(m & ((1 << k) - 1), k)
            a += m >> 1
            n -= 1
            if n < 0:
                a >>= 1
                n = 3
        i, zeros = end, 0
    if zeros:
        bits.gamma(zeros)
    length = bits.position()
    bits.put(0, -length % 8)
    return bytes(bits.out), length


def _tlg6_gray_file(gray) -> bytes:
    """A one-color TLG6 stream of 8-bit `gray`, each block predicted by MED
    as KiriKiri's own encoder may write it."""
    import numpy as np

    height, width = gray.shape
    pixels = gray.astype(np.int16)
    left, up, corner = (np.zeros_like(pixels) for _ in range(3))
    left[:, 1:] = pixels[:, :-1]
    up[1:] = pixels[:-1]
    corner[1:, 1:] = pixels[:-1, :-1]
    low, high = np.minimum(left, up), np.maximum(left, up)
    guess = np.where(
        corner >= high, low, np.where(corner < low, high, left + up - corner)
    )
    errors = ((pixels - guess) & 0xFF).astype(np.int8)
    groups, longest = [], 0
    for top in range(0, height, 8):
        lines = min(8, height - top)
        values = np.empty(lines * width, np.int8)
        values[_tlg6_order(width, lines)] = errors[top : top + lines]
        codes, length = _golomb_codes(values.tolist())
        longest = max(longest, length)
        groups.append(struct.pack("<I", length) + codes)
    blocks = ((width - 1) // 8 + 1) * ((height - 1) // 8 + 1)
    # Every block's filter type is 0, MED without color correlation, stored
    # as LZSS literals: a zero flag byte before each eight.
    filters = b"".join(
        b"\x00" + bytes(min(8, blocks - at)) for at in range(0, blocks, 8)
    )
    return (
        _TLG6
        + bytes([1, 0, 0, 0])
        + struct.pack("<IIII", width, height, longest, len(filters))
        + filters
        + b"".join(groups)
    )


def _tlg6_pixels(stream: bytes):
    import numpy as np

    colors, flag, color_type, external = stream[11:15]
    if colors not in (1, 3, 4) or flag or color_type or external:
        raise ValueError("The TLG image has an unsupported color type.")
    width, height, _longest = struct.unpack_from("<III", stream, 15)
    _tlg_size(width, height)
    columns = (width - 1) // 8 + 1
    rows = (height - 1) // 8 + 1
    size = struct.unpack_from("<I", stream, 27)[0]
    # The filter types' LZSS ring starts with every pair of 4-byte runs.
    text = bytearray(
        b"".join(bytes([i]) * 4 + bytes([j]) * 4 for i in range(32) for j in range(16))
    )
    filters, _r = _lzss(stream[31 : 31 + size], columns * rows, text, 0)
    filters = np.frombuffer(bytes(filters[: columns * rows]), np.uint8).reshape(
        rows, columns
    )
    position = 31 + size
    residuals = np.zeros((height, width, 4), np.uint8)
    for top in range(0, height, 8):
        lines = min(8, height - top)
        count = lines * width
        order = _tlg6_order(width, lines)
        for color in range(colors):
            bits = struct.unpack_from("<I", stream, position)[0]
            if bits >> 30:
                raise ValueError("The TLG image uses an unsupported coding method.")
            length = ((bits & 0x3FFFFFFF) + 7) // 8
            values = _golomb(stream[position + 4 : position + 4 + length], count)
            position += 4 + length
            residuals[top : top + lines, :, color] = np.frombuffer(
                bytes(values), np.uint8
            )[order]
    kind = np.repeat(np.repeat(filters, 8, axis=0), 8, axis=1)[:height, :width]
    chroma = np.array(_CHROMA, np.uint8)[kind >> 1]
    deltas = residuals.copy()
    deltas[:, :, :3] = np.einsum("yxij,yxj->yxi", chroma, residuals[:, :, :3]).astype(
        np.uint8
    )
    return _tlg6_predict(deltas, (kind & 1).astype(bool), colors), colors


def _tlg6_predict(deltas, average, colors: int):
    """TLG6's pixels from their prediction errors: each pixel is its MED or
    average prediction from the pixels left of, above and above-left of it,
    plus its error. Pixels on one anti-diagonal don't depend on each other,
    so each diagonal is computed at once."""
    import numpy as np

    height, width = deltas.shape[:2]
    edge = np.array([0, 0, 0, 255 if colors == 3 else 0], np.int16)
    # Row y + 1 and column x + y + 2 hold pixel (x, y); row 0 and the cells
    # left of each row's first pixel are the edge KiriKiri predicts from.
    skewed = np.empty((height + 1, width + height + 1, 4), np.int16)
    skewed[:] = edge
    error = np.zeros_like(skewed)
    mean = np.zeros(skewed.shape[:2], bool)
    y = np.arange(height)[:, None] + 1
    cells = np.arange(width)[None, :] + y + 1
    error[y, cells] = deltas
    mean[y, cells] = average
    for diagonal in range(2, width + height + 1):
        first, last = max(1, diagonal - width), min(height, diagonal - 1)
        if first > last:
            continue
        left = skewed[first : last + 1, diagonal - 1]
        up = skewed[first - 1 : last, diagonal - 1]
        corner = skewed[first - 1 : last, diagonal - 2]
        low, high = np.minimum(left, up), np.maximum(left, up)
        median = np.where(
            corner > high, low, np.where(corner < low, high, left + up - corner)
        )
        predicted = np.where(
            mean[first : last + 1, diagonal, None], (left + up + 1) >> 1, median
        )
        skewed[first : last + 1, diagonal] = (
            predicted + error[first : last + 1, diagonal]
        ) & 255
    return skewed[y, cells].astype(np.uint8)
