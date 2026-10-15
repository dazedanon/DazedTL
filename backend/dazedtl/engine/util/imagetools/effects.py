"""Text effects: one model for the Image Editor and for fitted recipes.

Game lettering is a face with up to three effects under it, painted in this
order: an outer glow, an offset drop shadow, an outline, then the face. Each
one is a flat colour behind a coverage plane, and each coverage plane is the
glyphs grown by some distance and then, for the glow and the shadow, blurred
and moved. That is the whole model, and it is the one the HOLLOWWALD title
cards were fitted with: eight numbers and four colours reproduced them to
within 4/255 per channel.

How the glyphs are *grown* is the one thing callers do differently, so it is
passed in. The editor stretches its type after drawing it and grows the
finished coverage by dilation (``dilate``); a recipe draws unstretched type and
asks the rasteriser for a true stroke, which is what the earlier passes it is
fitted to drew. Everything after that - blur, offset, opacity, order and the
composite - lives here, so a recipe opened in the editor means the same thing
there.

Opacity is the alpha of each colour, as it already is for the face and the
outline, so the four layers read the same way on the panel and in a recipe.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

#: Below this coverage a layer leaves a pixel exactly as it was. Half a level
#: of eight-bit alpha is the most a layer can add without changing the stored
#: byte, so anything fainter is not a touch.
UNTOUCHED = 0.5 / 255


def _number(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def tidy(value: float) -> float | int:
    """A width as a person would write it: ``2`` rather than ``2.0``."""
    value = round(float(value), 3)
    return int(value) if value.is_integer() else value


def _colour(value, default: list[int]) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return list(default)
    channels = [int(max(0, min(255, round(_number(v, 0))))) for v in value[:4]]
    return channels + [255] * (4 - len(channels))


@dataclass
class Shadow:
    """A copy of the glyphs under the type, moved, grown and softened."""

    color: list[int] = field(default_factory=lambda: [0, 0, 0, 180])
    dx: float = 2.0
    dy: float = 2.0
    spread: float = 0.0
    blur: float = 1.0

    def to_dict(self) -> dict:
        return {
            "color": list(self.color),
            "dx": tidy(self.dx),
            "dy": tidy(self.dy),
            "spread": tidy(self.spread),
            "blur": tidy(self.blur),
        }

    @staticmethod
    def from_dict(data) -> Shadow | None:
        if not isinstance(data, dict):
            return None
        return Shadow(
            color=_colour(data.get("color"), [0, 0, 0, 180]),
            dx=_number(data.get("dx"), 2.0),
            dy=_number(data.get("dy"), 2.0),
            spread=max(0.0, _number(data.get("spread"), 0.0)),
            blur=max(0.0, _number(data.get("blur"), 1.0)),
        )


@dataclass
class Glow:
    """A soft halo all round the glyphs: grown, then blurred, never moved."""

    color: list[int] = field(default_factory=lambda: [255, 255, 255, 150])
    spread: float = 1.0
    blur: float = 3.0

    def to_dict(self) -> dict:
        return {
            "color": list(self.color),
            "spread": tidy(self.spread),
            "blur": tidy(self.blur),
        }

    @staticmethod
    def from_dict(data) -> Glow | None:
        if not isinstance(data, dict):
            return None
        return Glow(
            color=_colour(data.get("color"), [255, 255, 255, 150]),
            spread=max(0.0, _number(data.get("spread"), 1.0)),
            blur=max(0.0, _number(data.get("blur"), 3.0)),
        )


# --------------------------------------------------------------- coverage


def disc(radius: float) -> np.ndarray:
    """A round brush reaching *radius* pixels from the centre, corners included.

    Built from the distance to the centre rather than taken from
    ``getStructuringElement``, whose ``MORPH_ELLIPSE`` at 3x3 is a plus sign
    rather than a disc. The four diagonal neighbours it leaves out are exactly
    the corners of a stem, so a one-pixel stroke - the commonest width there is
    - came out with four bare specks on every upright in the line. A fractional
    radius lands between its neighbours rather than being rounded to one.
    """
    reach = max(0, math.ceil(radius))
    span = np.arange(-reach, reach + 1, dtype=np.float32)
    grid = np.hypot(*np.meshgrid(span, span))
    return (grid <= radius + 0.5).astype(np.uint8)


def dilate(coverage: np.ndarray, radius: float) -> np.ndarray:
    """*coverage* grown by *radius* pixels, by taking the most ink under a disc."""
    if radius <= 0:
        return coverage
    return cv2.dilate(coverage, disc(radius))


def blur(plane: np.ndarray, sigma: float) -> np.ndarray:
    """A Gaussian of *sigma* pixels, reaching three sigma either side.

    The kernel size is the one the HOLLOWWALD renderer used, so a recipe fitted
    to its output reproduces it rather than landing a fraction of a level off
    across the whole halo. The border is empty: callers draw on a canvas with
    room around the type, and what lies past its edge is no ink at all.
    """
    size = int(sigma * 3) * 2 + 1
    if sigma <= 0 or size < 3:
        return plane
    return cv2.GaussianBlur(
        plane, (size, size), sigma, borderType=cv2.BORDER_CONSTANT
    )


def shift(plane: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """*plane* moved by a possibly fractional offset, empty where it came from."""
    if not dx and not dy:
        return plane
    height, width = plane.shape[:2]
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(
        plane,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def visible(colour) -> bool:
    return colour is not None and len(colour) > 3 and int(colour[3]) > 0


def reach(
    outline_width: float = 0.0,
    shadow: Shadow | None = None,
    glow: Glow | None = None,
) -> int:
    """How far past the glyph ink any layer can paint, in whole pixels."""
    far = max(0.0, outline_width)
    if shadow is not None and visible(shadow.color):
        moved = max(abs(shadow.dx), abs(shadow.dy))
        far = max(far, shadow.spread + 3 * shadow.blur + moved)
    if glow is not None and visible(glow.color):
        far = max(far, glow.spread + 3 * glow.blur)
    return math.ceil(far) + 1 if far > 0 else 0


Layer = tuple[list[int], np.ndarray]


def stack(
    grow: Callable[[float], np.ndarray],
    text_color,
    *,
    outline_color=None,
    outline_width: float = 0.0,
    shadow: Shadow | None = None,
    glow: Glow | None = None,
) -> list[Layer]:
    """Every layer of one piece of type, in paint order: glow, shadow, outline, face.

    *grow* returns the glyph coverage grown by a distance, as float32 in 0..1;
    ``grow(0)`` is the face itself. Each layer is ``(rgba, coverage)``: the
    colour's alpha is its opacity and is not folded into the coverage, so the
    caller multiplies it in whichever way its compositor counts.
    """
    layers: list[Layer] = []
    if glow is not None and visible(glow.color):
        halo = blur(grow(glow.spread), glow.blur)
        layers.append((list(glow.color), np.clip(halo, 0.0, 1.0)))
    if shadow is not None and visible(shadow.color):
        moved = shift(grow(shadow.spread), shadow.dx, shadow.dy)
        layers.append(
            (list(shadow.color), np.clip(blur(moved, shadow.blur), 0.0, 1.0))
        )
    if outline_color is not None and outline_width > 0 and visible(outline_color):
        layers.append((list(outline_color), grow(outline_width)))
    layers.append((list(text_color), grow(0.0)))
    return layers


# --------------------------------------------------------------- composite


class Painter:
    """Source-over in floating point onto a copy of an image, rounded once.

    Every pixel no layer reaches comes back bit-exact - including the colour
    stored under alpha 0, which a naive composite rewrites. That colour is
    invisible in the game and visible to everything that compares files: an
    erase that recolours fully transparent pixels shows up as a change across
    the whole canvas in every diff and every protected-pixel check.
    """

    def __init__(self, base: np.ndarray):
        if base.ndim != 3 or base.shape[2] not in (3, 4) or base.dtype != np.uint8:
            raise ValueError("Paint onto an HxWx3 or HxWx4 uint8 image")
        self.base = base
        self.rgb = base[:, :, :3].astype(np.float32) / 255.0
        if base.shape[2] == 4:
            self.alpha = base[:, :, 3].astype(np.float32) / 255.0
        else:
            self.alpha = np.ones(base.shape[:2], dtype=np.float32)
        self.touched = np.zeros(base.shape[:2], dtype=bool)

    def paint(self, colour, coverage: np.ndarray, at: tuple[int, int]) -> None:
        """One flat colour behind *coverage*, whose top-left sits at *at*.

        The canvas may hang off the image on any side; only the overlap is
        painted.
        """
        x, y = at
        height, width = self.alpha.shape
        left, top = max(0, x), max(0, y)
        right = min(width, x + coverage.shape[1])
        bottom = min(height, y + coverage.shape[0])
        if right <= left or bottom <= top:
            return
        opacity = (int(colour[3]) if len(colour) > 3 else 255) / 255.0
        a = coverage[top - y : bottom - y, left - x : right - x] * opacity
        hit = a >= UNTOUCHED
        if not hit.any():
            return
        a = np.where(hit, a, 0.0).astype(np.float32)
        rgb = self.rgb[top:bottom, left:right]
        below = self.alpha[top:bottom, left:right]
        out = a + below * (1.0 - a)
        paint = np.array(colour[:3], dtype=np.float32) / 255.0
        mixed = (
            paint[None, None, :] * a[:, :, None]
            + rgb * (below * (1.0 - a))[:, :, None]
        ) / np.maximum(out, 1e-8)[:, :, None]
        rgb[hit] = mixed[hit]
        below[hit] = out[hit]
        self.touched[top:bottom, left:right] |= hit

    def result(self) -> np.ndarray:
        out = self.base.copy()
        if not self.touched.any():
            return out
        rgb = np.clip(np.round(self.rgb * 255.0), 0, 255).astype(np.uint8)
        out[self.touched, :3] = rgb[self.touched]
        if self.base.shape[2] == 4:
            alpha = np.clip(np.round(self.alpha * 255.0), 0, 255).astype(np.uint8)
            out[self.touched, 3] = alpha[self.touched]
            # Touched by a whisper that rounded back to nothing: still fully
            # transparent, so it keeps the colour it was stored with.
            empty = self.touched & (alpha == 0) & (self.base[:, :, 3] == 0)
            out[empty] = self.base[empty]
        return out
