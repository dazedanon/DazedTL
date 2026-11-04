"""Game image formats Images edits as PNG copies, on small generated pictures.

TLG has no reference files here, so its streams are made by encoders written
after KiriKiri Z's own (SaveTLG5.cpp, SaveTLG6.cpp): the decoder follows its
loader (LoadTLG.cpp, tvpgl.c), so a misread of either side's format shows."""

import struct
import tracemalloc
import unittest
from io import BytesIO

import numpy as np
from PIL import Image
from util import image_formats
from util.image_formats import from_png, to_png


def png(pixels):
    stream = BytesIO()
    Image.fromarray(pixels, "RGBA" if pixels.shape[2] == 4 else "RGB").save(
        stream, format="PNG"
    )
    return stream.getvalue()


def pixels_of(raw):
    with Image.open(BytesIO(to_png(raw))) as image:
        return np.asarray(image.convert("RGBA"))


def picture(height, width, seed, alpha=True):
    """Noise beside smooth and flat areas, so predictions both hit and miss
    by far: a long Golomb code past its four-byte limit comes from a jump
    after flat pixels."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:height, 0:width]
    pixels = np.dstack([3 * xs + ys, 200 - 2 * ys, xs * ys, 255 - xs + 2 * ys]).astype(
        np.uint8
    )
    pixels[height // 2 :, : width // 2] = rng.integers(
        0, 256, (height - height // 2, width // 2, 4), dtype=np.uint8
    )
    pixels[: height // 2, width // 2 :] = 9
    pixels[0, -1] = (250, 3, 128, 7)
    if not alpha:
        pixels[:, :, 3] = 255
    return pixels


class Bits:
    """TLG6BitStream: bits written lowest first."""

    def __init__(self):
        self.bits = []

    def put(self, value, length=1):
        for _ in range(length):
            self.bits.append(value & 1)
            value >>= 1

    def gamma(self, value):
        length = value.bit_length() - 1
        self.put(0, length)
        self.put(1)
        self.put(value, length)

    def golomb(self, values):
        """CompressValuesGolomb, run-length Golomb-Rice codes of the values
        and of their runs of zeros and nonzeros."""
        table = image_formats._GOLOMB_BITS
        self.put(1 if values[0] else 0)
        n, a, i, zeros = 3, 0, 0, 0
        while i < len(values):
            if not values[i]:
                zeros += 1
                i += 1
                continue
            if zeros:
                self.gamma(zeros)
            end = i
            while end < len(values) and values[end]:
                end += 1
            self.gamma(end - i)
            for value in values[i:end]:
                k = table[a * 4 + n]
                m = (2 * value if value >= 0 else -2 * value - 1) - 1
                limit = len(self.bits) // 8 + 4
                whole = True
                for _ in range(m >> k):
                    if len(self.bits) // 8 == limit:
                        self.put(m >> k, 8)
                        whole = False
                        break
                    self.put(0)
                if whole and len(self.bits) // 8 == limit:
                    self.put(m >> k, 8)
                    whole = False
                if whole:
                    self.put(1)
                self.put(m, k)
                a += m >> 1
                n -= 1
                if n < 0:
                    a >>= 1
                    n = 3
            i, zeros = end, 0
        if zeros:
            self.gamma(zeros)

    def bytes(self):
        padded = self.bits + [0] * (-len(self.bits) % 8)
        return np.packbits(np.array(padded, np.uint8), bitorder="little").tobytes()


def literal_lzss(data):
    """LZSS with every byte a literal: a zero flag byte before each eight."""
    return b"".join(b"\x00" + data[i : i + 8] for i in range(0, len(data), 8))


def lzss(data, text, r):
    """A greedy LZSS of TLG5's ring, matching only the last 40 positions:
    runs copy over their own output, longer distances copy apart."""
    out, flags, items = bytearray(), 0, []
    i = 0
    while i < len(data):
        best, where = 0, 0
        for distance in range(1, 41):
            ring, position = bytearray(text), (r - distance) & 0xFFF
            length = 0
            while length < 18 + 255 and i + length < len(data):
                value = ring[(position + length) & 0xFFF]
                if value != data[i + length]:
                    break
                ring[(r + length) & 0xFFF] = value
                length += 1
            if length > best:
                best, where = length, position
        if best >= 3:
            short = min(best, 18) - 3
            item = bytes([where & 0xFF, (where >> 8) | (short << 4)])
            items.append((item + bytes([best - 18]) if best >= 18 else item, True))
            for step in range(best):
                text[(r + step) & 0xFFF] = text[(where + step) & 0xFFF]
            r, i = (r + best) & 0xFFF, i + best
        else:
            items.append((bytes([data[i]]), False))
            text[r], r, i = data[i], (r + 1) & 0xFFF, i + 1
    for start in range(0, len(items), 8):
        group = items[start : start + 8]
        for bit, (_, match) in enumerate(group):
            flags |= match << bit
        out.append(flags)
        flags = 0
        for item, _ in group:
            out += item
    return bytes(out), r


def tlg5(pixels, colors, block=4):
    """SaveTLG5's stream of BGRA pixels, each block's planes LZSS-compressed."""
    height, width = pixels.shape[:2]
    upper = np.zeros_like(pixels)
    upper[1:] = pixels[:-1]
    vertical = pixels - upper
    left = np.zeros_like(vertical)
    left[:, 1:] = vertical[:, :-1]
    values = vertical - left
    values[:, :, 0] -= values[:, :, 1]
    values[:, :, 2] -= values[:, :, 1]
    text, r, blocks = bytearray(4096), 0, b""
    count = (height - 1) // block + 1
    for top in range(0, height, block):
        for color in range(colors):
            packed, r = lzss(values[top : top + block, :, color].tobytes(), text, r)
            blocks += b"\x00" + struct.pack("<I", len(packed)) + packed
    return (
        b"TLG5.0\x00raw\x1a"
        + bytes([colors])
        + struct.pack("<III", width, height, block)
        + bytes(4 * count)
        + blocks
    )


# ApplyColorFilter's 16 filters, each a series of `target -= source` steps on
# the blue, green and red residuals (0, 1, 2); filter 15 subtracts twice blue.
FILTERS = (
    (),
    ((2, 1), (0, 1)),
    ((2, 1), (1, 0)),
    ((0, 1), (1, 2)),
    ((2, 1), (1, 0), (0, 2)),
    ((1, 0), (0, 2)),
    ((0, 1),),
    ((1, 0),),
    ((2, 1),),
    ((0, 1), (1, 2), (2, 0)),
    ((1, 2), (0, 2)),
    ((2, 0), (1, 0)),
    ((1, 2), (2, 0)),
    ((1, 2), (2, 0), (0, 1)),
    ((2, 0), (0, 1), (1, 2)),
)


def tlg6(pixels, colors):
    """SaveTLG6's stream of BGRA pixels, cycling through all 32 filter types
    instead of choosing the smallest."""
    height, width = pixels.shape[:2]
    source = pixels.astype(np.int32)
    types, groups = [], b""
    longest = 0
    for top in range(0, height, 8):
        bottom = min(top + 8, height)
        lines = bottom - top
        group = [[] for _ in range(colors)]
        for column, left in enumerate(range(0, width, 8)):
            right = min(left + 8, width)
            span = right - left
            # A grayscale image has no colors to correlate.
            kind = len(types) % (32 if colors > 1 else 2)
            types.append(kind)
            errors = np.zeros((lines, span, 4), np.int32)
            for y in range(top, bottom):
                for x in range(left, right):
                    a = source[y, x - 1] if x else np.zeros(4, np.int32)
                    b = source[y - 1, x] if y else np.zeros(4, np.int32)
                    if kind & 1:
                        guess = (a + b + 1) >> 1
                    else:
                        c = source[y - 1, x - 1] if x and y else np.zeros(4, np.int32)
                        guess = np.where(
                            c >= np.maximum(a, b),
                            np.minimum(a, b),
                            np.where(c < np.minimum(a, b), np.maximum(a, b), a + b - c),
                        )
                    errors[y - top, x - left] = (source[y, x] - guess) & 255
            ordered = []
            for y in range(top, bottom):
                row = (y - top) if not column & 1 else (bottom - y - 1)
                if not lines & 1 or not column & 1:
                    backward = bool((y & 1) ^ (column & 1))
                else:
                    backward = bool(y & 1)
                xs = range(span - 1, -1, -1) if backward else range(span)
                ordered.extend(errors[row, x] for x in xs)
            ordered = np.array(ordered, np.int32)
            if kind >> 1 == 15:
                twice = (ordered[:, 0] << 1) & 255
                ordered[:, 2] -= twice
                ordered[:, 1] -= twice
            else:
                for target, by in FILTERS[kind >> 1]:
                    ordered[:, target] -= ordered[:, by]
            ordered &= 255
            for color in range(colors):
                group[color].extend(ordered[:, color].tolist())
        for color in range(colors):
            bits = Bits()
            bits.golomb(
                [value - 256 if value > 127 else value for value in group[color]]
            )
            longest = max(longest, len(bits.bits))
            groups += struct.pack("<I", len(bits.bits)) + bits.bytes()
    filters = literal_lzss(bytes(types))
    return (
        b"TLG6.0\x00raw\x1a"
        + bytes([colors, 0, 0, 0])
        + struct.pack("<III", width, height, longest)
        + struct.pack("<I", len(filters))
        + filters
        + groups
    )


def bgra(pixels):
    return pixels[:, :, [2, 1, 0, 3]].copy()


def bmp32(pixels):
    """A KiriKiri-style 32-bit BMP: BGRA rows bottom up, alpha in the fourth
    byte of an uncompressed bitmap."""
    height, width = pixels.shape[:2]
    data = bgra(pixels)[::-1].tobytes()
    return (
        struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54)
        + struct.pack(
            "<IiiHHIIiiII", 40, width, height, 1, 32, 0, len(data), 0, 0, 0, 0
        )
        + data
    )


class TlgTests(unittest.TestCase):
    def test_tlg6_reads_as_kirikiri_writes_it(self):
        # Sizes with a partial block column and a partial last group, whose
        # odd line count reverses the reading direction rules; one pixel; and
        # 33 blocks, for every filter type with three colors and four.
        for height, width, colors in (
            (13, 21, 4),
            (11, 9, 3),
            (1, 1, 4),
            (17, 88, 3),
            (24, 90, 4),
        ):
            with self.subTest(size=(height, width), colors=colors):
                pixels = picture(height, width, height * width, alpha=colors == 4)
                raw = tlg6(bgra(pixels), colors)
                np.testing.assert_array_equal(pixels_of(raw), pixels)

    def test_a_tall_tlg6_decodes_within_its_size(self):
        # Decoding in one pass took memory growing with height * (width +
        # height): a 1280x12000 staff roll needed about 2.7 GB.
        pixels = picture(1600, 9, 7, alpha=False)
        raw = tlg6(bgra(pixels), 3)
        tracemalloc.start()
        try:
            decoded = pixels_of(raw)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        np.testing.assert_array_equal(decoded, pixels)
        self.assertLess(peak, 8_000_000)

    def test_tlg5_reads_its_compressed_blocks(self):
        pixels = picture(10, 14, 3)
        np.testing.assert_array_equal(pixels_of(tlg5(bgra(pixels), 4)), pixels)

    def test_an_edited_tlg_is_written_back_with_its_tags(self):
        # The tags a TLG0.0 wrapper keeps, such as a layer's offset, stay
        # with the edited image, which KiriKiri reads back as its pixels.
        original = picture(9, 12, 5)
        stream = tlg6(bgra(original), 4)
        tags = b"tags" + struct.pack("<I", 13) + b"4:LEFT=2:20,"
        wrapped = b"TLG0.0\x00sds\x1a" + struct.pack("<I", len(stream)) + stream + tags
        edited = picture(9, 12, 6)
        written = from_png(png(edited), wrapped)
        self.assertTrue(written.startswith(b"TLG0.0\x00sds\x1a"))
        self.assertTrue(written.endswith(tags))
        np.testing.assert_array_equal(pixels_of(written), edited)
        # Writing it again changes nothing, so a repeated apply finds it done.
        self.assertEqual(from_png(png(edited), written), written)

    def test_an_opaque_tlg_refuses_an_edit_with_transparency(self):
        original = tlg6(bgra(picture(8, 8, 1, alpha=False)), 3)
        with self.assertRaisesRegex(ValueError, "transparent"):
            from_png(png(picture(8, 8, 2)), original)

    def test_a_grayscale_tlg6_reads_and_is_written_back(self):
        # KiriKiri reads a one-color TLG6, such as a mask; it was refused as
        # an unsupported color type, then its edit only at Apply.
        pixels = picture(19, 13, 4)
        raw = tlg6(bgra(pixels), 1)
        with Image.open(BytesIO(to_png(raw))) as image:
            self.assertEqual(image.mode, "L")
            np.testing.assert_array_equal(np.asarray(image), pixels[:, :, 2])
        edited = picture(19, 13, 5)[:, :, 0]
        stream = BytesIO()
        Image.fromarray(edited, "L").save(stream, format="PNG")
        written = from_png(stream.getvalue(), raw)
        self.assertTrue(written.startswith(b"TLG6.0\x00raw\x1a\x01"))
        with Image.open(BytesIO(to_png(written))) as image:
            np.testing.assert_array_equal(np.asarray(image), edited)


class BmpAndJpegTests(unittest.TestCase):
    def test_a_32_bit_bmp_keeps_the_alpha_kirikiri_reads(self):
        original = picture(6, 7, 1)
        raw = bmp32(original)
        np.testing.assert_array_equal(pixels_of(raw), original)
        edited = picture(6, 7, 2)
        written = from_png(png(edited), raw)
        self.assertEqual(written[28], 32)
        np.testing.assert_array_equal(pixels_of(written), edited)

    def test_a_bmp_with_an_alpha_mask_keeps_its_alpha(self):
        # A BMP whose header masks give alpha (BI_BITFIELDS) read with its
        # alpha but was written back opaque, so even its untouched copy
        # failed to apply.
        original = picture(4, 5, 1)
        data = bgra(original)[::-1].tobytes()
        header = (
            struct.pack("<IiiHHIIiiII", 108, 5, 4, 1, 32, 3, len(data), 0, 0, 0, 0)
            + struct.pack("<4I", 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
            + bytes(52)
        )
        raw = (
            struct.pack("<2sIHHI", b"BM", 14 + len(header) + len(data), 0, 0, 122)
            + header
            + data
        )
        np.testing.assert_array_equal(pixels_of(raw), original)
        written = from_png(to_png(raw), raw)
        np.testing.assert_array_equal(pixels_of(written), original)

    def test_a_32_bit_bmp_without_alpha_stays_so(self):
        # Every fourth byte zero: an opaque picture, whose edit keeps them so.
        original = picture(5, 4, 1)
        original[:, :, 3] = 0
        raw = bmp32(original)
        opaque = original.copy()
        opaque[:, :, 3] = 255
        np.testing.assert_array_equal(pixels_of(raw), opaque)
        written = from_png(png(opaque), raw)
        self.assertFalse(np.frombuffer(written, np.uint8, offset=54)[3::4].any())
        np.testing.assert_array_equal(pixels_of(written), opaque)

    def test_a_24_bit_bmp_and_a_jpeg_are_written_in_their_format(self):
        original = picture(8, 8, 1, alpha=False)
        edited = picture(8, 8, 2, alpha=False)
        for kind in ("BMP", "JPEG"):
            with self.subTest(kind=kind):
                stream = BytesIO()
                Image.fromarray(original[:, :, :3]).save(stream, format=kind)
                written = from_png(png(edited), stream.getvalue())
                with Image.open(BytesIO(written)) as image:
                    self.assertEqual((image.format, image.mode), (kind, "RGB"))
                difference = np.abs(
                    pixels_of(written).astype(int) - edited.astype(int)
                ).max()
                self.assertLessEqual(difference, 0 if kind == "BMP" else 60)
                with self.assertRaisesRegex(ValueError, "transparent"):
                    from_png(png(picture(8, 8, 3)), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
