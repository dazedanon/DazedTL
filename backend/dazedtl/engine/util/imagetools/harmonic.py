"""The membrane fill: the smoothest surface that meets the hole's edge.

Every pixel under the mask becomes the average of its four neighbours, which is
Laplace's equation with the pixels around the hole held fixed. There is exactly
one such surface, so the answer does not depend on how the hole was traced or
how long anything ran - unlike Telea and Navier-Stokes, which march inwards
from the edge and carry whatever they met first. That difference is the point:
on thin glyphs over line art, the marching fills drag a dark line across the
gap as a smudge, where the membrane settles it into the surrounding shading.

What it cannot do is invent texture. A wide hole comes back as a smooth blend,
so this is for strokes and outlines, not for whole panels of hatching.

The solve is exact rather than iterated to taste: conjugate gradients with a
multigrid preconditioner, run until the error is far below one level of 8-bit
colour. A hole's thickness, not its area, is what makes a plain iteration slow
- a few thousand sweeps for a 50 px blob - and the multigrid levels are what
keep a 200x500 hole under a second.

NumPy only, on purpose: nothing to download, so it is always available.
"""

from __future__ import annotations

import numpy as np

#: Residual, relative to the right-hand side, at which a channel is solved.
#: Measured on glyph and block holes up to 220x550: the largest error left is
#: about 0.0001 of a level, so 8-bit rounding can differ from the exact answer
#: only where that sits within 0.0001 of a half.
TOLERANCE = 1e-7
#: A safety net only. The preconditioned solve needs 15-40 iterations.
ITERATIONS = 200
#: Damping of the Jacobi smoother inside each multigrid level.
SMOOTHING = 0.8
#: The coarse levels merge pixels into 2x2 cells, which understates how far a
#: correction should reach; scaling it up halves the iterations. Anything
#: below 2 keeps the preconditioner positive definite.
OVERCORRECTION = 1.5
#: Alpha (0..255 scale) below which a filled pixel's colour is taken from the
#: unpremultiplied solve instead: dividing by an alpha this close to zero only
#: amplifies the solver's rounding, and the pixel is invisible either way.
FAINT = 0.01


def fill(values: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Solve Laplace's equation over *hole*, with every other pixel fixed.

    *values* is HxW or HxWxC in any numeric type; the result is a float64
    copy whose pixels outside the hole are exactly the input's. The picture's
    own border acts as a mirror, so a hole touching it is filled from the
    pixels it does have.
    """
    values = np.asarray(values)
    hole = np.asarray(hole, dtype=bool)
    if hole.shape != values.shape[:2]:
        raise ValueError("The mask must have the picture's height and width.")
    out = np.array(values, dtype=np.float64)
    if not hole.any():
        return out
    if hole.all():
        raise ValueError("The mask covers the whole picture; there is no edge to fill from.")
    flat = out.reshape(hole.shape[0], hole.shape[1], -1)
    ys, xs = np.nonzero(hole)
    # One pixel wider than the hole holds every neighbour it has; past the
    # picture's edge there is nothing, which is the mirror.
    rows = slice(max(int(ys.min()) - 1, 0), min(int(ys.max()) + 2, hole.shape[0]))
    cols = slice(max(int(xs.min()) - 1, 0), min(int(xs.max()) + 2, hole.shape[1]))
    grid = flat[rows, cols]
    unknown = hole[rows, cols]
    level = _Level.fine(unknown)
    known = np.where(unknown[:, :, None], 0.0, grid)
    solved = _solve(level, level.neighbours(known))
    grid[unknown] = solved[unknown]
    return out


def fill_pixels(pixels: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """``fill`` for 8-bit RGB or RGBA, rounded back to 8 bits.

    RGBA is filled premultiplied: colour weighted by opacity, and opacity
    itself, so a translucent window lends its tint in proportion to how much
    of it there is, and the colour stored under fully transparent pixels -
    whatever the exporter left there - lends nothing. Where the surroundings
    are fully transparent, the stored colour is continued instead, so even
    the invisible pixels stay consistent with their neighbours.
    """
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4) or pixels.dtype != np.uint8:
        raise ValueError("pixels must be an HxWx3 or HxWx4 uint8 array")
    hole = np.asarray(hole, dtype=bool)
    result = pixels.copy()
    if not hole.any():
        return result
    colour = pixels[:, :, :3].astype(np.float64)
    if pixels.shape[2] == 3 or (pixels[:, :, 3][_ring(hole)] == 255).all():
        # Opaque all round: the opacity solves to 255 everywhere, so the
        # premultiplied and plain fills are the same fill.
        result[hole, :3] = _bytes(fill(colour, hole)[hole])
        if pixels.shape[2] == 4:
            result[hole, 3] = 255
        return result
    alpha = pixels[:, :, 3].astype(np.float64)
    stack = np.dstack([colour * (alpha / 255.0)[:, :, None], alpha, colour])
    solved = fill(stack, hole)[hole]
    opacity = np.clip(solved[:, 3], 0.0, 255.0)
    visible = opacity > FAINT
    straight = solved[:, :3] * 255.0 / np.where(visible, opacity, 1.0)[:, None]
    result[hole, :3] = _bytes(np.where(visible[:, None], straight, solved[:, 4:]))
    result[hole, 3] = _bytes(opacity)
    return result


def _bytes(values: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(values), 0, 255).astype(np.uint8)


def _ring(hole: np.ndarray) -> np.ndarray:
    """The pixels outside the hole that touch it - all the fill ever reads."""
    grown = hole.copy()
    grown[1:] |= hole[:-1]
    grown[:-1] |= hole[1:]
    grown[:, 1:] |= hole[:, :-1]
    grown[:, :-1] |= hole[:, 1:]
    return grown & ~hole


# ---------------------------------------------------------------- the solver


class _Level:
    """One grid of the hierarchy: a five-point operator on its unknown cells.

    ``east[y, x]`` couples ``(y, x)`` with ``(y, x + 1)`` and ``south[y, x]``
    with ``(y + 1, x)``. ``diagonal`` holds each unknown's total coupling,
    including to fixed pixels, which is what makes the system solvable.
    """

    def __init__(self, unknown, diagonal, east, south):
        self.unknown = unknown
        self.diagonal = np.where(unknown, diagonal, 0.0)
        self.east = east
        self.south = south
        self.inverse = np.where(unknown, 1.0 / np.where(unknown, diagonal, 1.0), 0.0)

    @classmethod
    def fine(cls, unknown):
        height, width = unknown.shape
        east = np.ones((height, width))
        east[:, -1] = 0.0
        south = np.ones((height, width))
        south[-1] = 0.0
        diagonal = np.zeros((height, width))
        diagonal[:, :-1] += 1.0
        diagonal[:, 1:] += 1.0
        diagonal[:-1] += 1.0
        diagonal[1:] += 1.0
        return cls(unknown, diagonal, east, south)

    def neighbours(self, x):
        """Each unknown's weighted sum of its neighbours' values."""
        out = np.zeros_like(x)
        east = self.east[:, :-1, None]
        south = self.south[:-1, :, None]
        out[:, :-1] += east * x[:, 1:]
        out[:, 1:] += east * x[:, :-1]
        out[:-1] += south * x[1:]
        out[1:] += south * x[:-1]
        out *= self.unknown[:, :, None]
        return out

    def apply(self, x):
        return self.diagonal[:, :, None] * x - self.neighbours(x)

    def coarsen(self):
        """The next level: 2x2 cells, with the Galerkin operator.

        A coarse cell is unknown when any of its pixels is, and a correction
        found there is copied to all of them. The coarse operator is exactly
        what the fine one does to such a correction, so the coarse problem
        never claims more than the fine one can deliver.
        """
        height, width = self.unknown.shape
        tall, wide = (height + 1) // 2, (width + 1) // 2

        def padded(array):
            out = np.zeros((tall * 2, wide * 2), array.dtype)
            out[:height, :width] = array
            return out

        unknown = padded(self.unknown)
        live = unknown.astype(np.float64)
        east = padded(self.east)
        east[:, :-1] *= live[:, :-1] * live[:, 1:]
        east[:, -1] = 0.0
        south = padded(self.south)
        south[:-1] *= live[:-1] * live[1:]
        south[-1] = 0.0

        def cells(array):
            return array.reshape(tall, 2, wide, 2)

        inside = cells(east)[:, :, :, 0].sum(1) + cells(south)[:, 0].sum(-1)
        diagonal = cells(padded(self.diagonal)).sum((1, 3)) - 2.0 * inside
        return _Level(
            cells(unknown).any((1, 3)),
            diagonal,
            cells(east)[:, :, :, 1].sum(1),
            cells(south)[:, 1].sum(-1),
        )

    def restrict(self, x, shape):
        tall, wide = shape
        out = np.zeros((tall * 2, wide * 2, x.shape[2]))
        out[: x.shape[0], : x.shape[1]] = x
        return out.reshape(tall, 2, wide, 2, x.shape[2]).sum((1, 3))

    def prolong(self, x):
        height, width = self.unknown.shape
        spread = np.repeat(np.repeat(x, 2, 0), 2, 1)[:height, :width]
        return spread * self.unknown[:, :, None]


class _Hierarchy:
    """Levels down to a single cell, whose one unknown is solved by division."""

    def __init__(self, level):
        self.levels = [level]
        while level.unknown.size > 1:
            level = level.coarsen()
            self.levels.append(level)

    def cycle(self, r, depth=0):
        """One V-cycle: an approximate inverse of the level's operator."""
        level = self.levels[depth]
        if depth == len(self.levels) - 1:
            return level.inverse[:, :, None] * r
        x = SMOOTHING * level.inverse[:, :, None] * r
        coarse = self.levels[depth + 1]
        below = level.restrict(r - level.apply(x), coarse.unknown.shape)
        x += OVERCORRECTION * level.prolong(self.cycle(below, depth + 1))
        x += SMOOTHING * level.inverse[:, :, None] * (r - level.apply(x))
        return x


def _solve(level, rhs):
    """Preconditioned conjugate gradients, every channel at once."""
    hierarchy = _Hierarchy(level)
    x = np.zeros_like(rhs)
    r = rhs.copy()
    z = hierarchy.cycle(r)
    p = z.copy()
    rz = (r * z).sum((0, 1))
    goal = TOLERANCE * np.sqrt((rhs * rhs).sum((0, 1)))
    for _ in range(ITERATIONS):
        if (np.sqrt((r * r).sum((0, 1))) <= goal).all():
            break
        ap = level.apply(p)
        pap = (p * ap).sum((0, 1))
        step = np.divide(rz, pap, out=np.zeros_like(rz), where=pap > 0)
        x += step * p
        r -= step * ap
        z = hierarchy.cycle(r)
        following = (r * z).sum((0, 1))
        p = z + np.divide(following, rz, out=np.zeros_like(rz), where=rz > 0) * p
        rz = following
    return x
