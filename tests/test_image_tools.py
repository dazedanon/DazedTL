"""Local image reconstruction and PNG rewriting, on small generated pictures."""

import io
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin
from util.imagetools import harmonic, inpaint, pngfile, resources


class HarmonicFillTests(unittest.TestCase):
    def test_fill_is_the_exact_membrane_and_touches_nothing_outside_the_hole(self):
        # A linear ramp is already harmonic, so it is the one answer the fill
        # may give; the iterated fills it replaces only approach it.
        ys, xs = np.mgrid[0:48, 0:64]
        ramp = np.dstack([3 * xs + 2 * ys + 7, 255 - 4 * xs, 2 * ys + 11])
        hole = np.zeros((48, 64), bool)
        hole[6:44, 5:59] = True
        hole[20:28, 0:3] = True  # apart from it, against the picture's edge
        filled = harmonic.fill(ramp, hole)
        np.testing.assert_array_equal(filled[~hole], ramp[~hole])
        np.testing.assert_allclose(filled[6:44, 5:59], ramp[6:44, 5:59], atol=0.05)

        pixels = np.dstack([2 * xs + ys, 200 - xs, 3 * ys]).astype(np.uint8)
        stroke = np.zeros_like(hole)
        stroke[10:13, 8:56] = stroke[8:40, 30:33] = True
        np.testing.assert_array_equal(harmonic.fill_pixels(pixels, stroke), pixels)

    def test_translucent_and_transparent_surroundings_lend_by_opacity(self):
        rgba = np.zeros((40, 80, 4), np.uint8)
        rgba[:, :, :3] = (13, 200, 77)  # stored under alpha 0 by the exporter
        rgba[10:30, 30:80] = (0, 0, 0, 178)  # a 70% black bar
        rgba[15:25, 40:70] = (255, 255, 255, 255)  # a glyph cut into it
        rgba[2:6, 2:6] = (255, 255, 255, 255)  # a mark on the transparent part
        hole = np.zeros((40, 80), bool)
        hole[15:25, 40:70] = hole[2:6, 2:6] = True
        hole[16:20, 24:34] = True  # straddles the bar's left edge

        result, complaint, changed = inpaint.reconstruct_rgba(
            rgba, hole, inpaint.HARMONIC, allow_fallback=False
        )
        self.assertEqual(complaint, "")
        self.assertEqual(changed, int(hole.sum()))
        np.testing.assert_array_equal(result[~hole], rgba[~hole])
        self.assertTrue((result[15:25, 40:70] == (0, 0, 0, 178)).all())
        self.assertTrue((result[2:6, 2:6] == (13, 200, 77, 0)).all())
        # Fading out of the bar, the colour stays the bar's black instead of
        # picking up the green nobody can see.
        edge = result[17, 24:34]
        self.assertTrue((np.diff(edge[:, 3].astype(int)) >= 0).all())
        self.assertTrue((edge[edge[:, 3] > 0, :3] == 0).all())


class PngRewriteTests(unittest.TestCase):
    def test_rewrite_keeps_header_and_ancillary_chunks_in_order(self):
        info = PngImagePlugin.PngInfo()
        info.add(b"gAMA", struct.pack(">I", 45455))
        info.add(
            b"cHRM",
            struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000),
        )
        info.add_text("Software", "fixture")
        info.add_itxt("Comment", "テスト", lang="ja")
        rgba = np.zeros((12, 16, 4), np.uint8)
        rgba[:, :, :3] = (9, 8, 7)  # colour under alpha 0
        rgba[4:8, 4:12] = (200, 100, 50, 255)
        stream = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(
            stream, format="PNG", pnginfo=info, dpi=(144, 144), icc_profile=b"profile"
        )
        template = stream.getvalue()
        edited = rgba.copy()
        edited[5:7, 5:11] = (1, 2, 3, 255)

        written = pngfile.encode_like(edited, template)
        old, new = pngfile.chunks(template), pngfile.chunks(written)
        self.assertEqual(
            [chunk for kind, chunk in new if kind != b"IDAT"],
            [chunk for kind, chunk in old if kind != b"IDAT"],
        )
        kinds = [kind for kind, _chunk in old]
        for kind in (b"gAMA", b"cHRM", b"iCCP", b"pHYs", b"tEXt", b"iTXt"):
            self.assertIn(kind, kinds)
        with Image.open(io.BytesIO(written)) as decoded:
            np.testing.assert_array_equal(np.asarray(decoded), edited)

        sixteen = io.BytesIO()
        Image.fromarray(np.zeros((4, 4), np.uint16)).save(sixteen, "PNG")
        with self.assertRaisesRegex(ValueError, "16-bit"):
            pngfile.encode_like(np.zeros((4, 4, 4), np.uint8), sixteen.getvalue())


def _dll(linker=(14, 44), version=None) -> bytes:
    """A Windows DLL's header, with a version resource when *version* is given."""
    data = bytearray(0x100)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    data[0x80 + 26 : 0x80 + 28] = bytes(linker)
    if version:
        major, minor, build, revision = version
        data += struct.pack(
            "<4I", 0xFEEF04BD, 0x10000, major << 16 | minor, build << 16 | revision
        )
    return bytes(data)


class VisualCppRuntimeTests(unittest.TestCase):
    def test_the_first_copy_windows_loads_must_be_as_new_as_the_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            early, system = root / "python", root / "System32"
            early.mkdir()
            system.mkdir()
            library = root / "onnxruntime.dll"
            library.write_bytes(_dll(linker=(14, 44)))
            needed = resources.linker_version(library)
            self.assertEqual(needed, (14, 44))

            def place(where, version):
                for name in resources.VC_LIBRARIES:
                    (where / name).write_bytes(_dll(version=version))

            folders = [early, system]
            self.assertIn("lacks", resources.runtime_problem(needed, folders))
            place(system, (14, 29, 30133, 0))
            self.assertIn(
                "14.44 or newer, and this Windows has 14.29.30133.0",
                resources.runtime_problem(needed, folders),
            )
            # Before onnxruntime is installed its toolset is unknown.
            self.assertEqual(resources.runtime_problem(None, folders), "")
            place(early, (14, 50, 35717, 0))
            self.assertEqual(resources.runtime_problem(needed, folders), "")
            # An older copy ahead of a newer one is the copy that loads.
            self.assertIn(
                "this Windows has 14.29",
                resources.runtime_problem(needed, [system, early]),
            )


if __name__ == "__main__":
    unittest.main()
