"""Local image reconstruction, on small generated pictures."""

import unittest

import numpy as np
from util.imagetools import harmonic, inpaint


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


if __name__ == "__main__":
    unittest.main()
