"""Text recipes: how one family of images sets its lettering, written down.

The second image in a family should cost one command. On the HOLLOWWALD map
title cards it cost half a session instead, because the pass that translated
the first card saved its pixels and not how it drew them, so the font size,
the glow and the shadow had to be reverse-engineered from the result before the
next card could match it. A recipe is that knowledge kept: fitted once from an
accepted translation (``util.imagetools.fitter``), then rendered onto every
sibling's clean base by ``render``.

A recipe holds *slots* - "title", "subtitle", "name", "line1" - because an
image usually sets more than one piece of type, each with its own font, size,
place and effects. A slot says:

* the font file and its hash, so a later render cannot quietly pick up a
  different face of the same name;
* the size in points, drawn by Pillow exactly as the earlier passes drew it;
* where the type goes, as a rule rather than a position: "centred by advance
  width on x = 512, baseline at 287". A rule is what carries over to a string
  of another length; the fitted position only describes the one it was
  measured on.
* the effect stack, as the editor's own ``Style`` fields, so a slot's style is
  a block style the Image Editor can open.

Rendering is deterministic: the same recipe, base and text give the same
bytes, and pixels no layer reaches are returned untouched.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from util.imagetools import effects
from util.imagetools.effects import tidy
from util.imagetools.geometry import Box
from util.imagetools.style import Style

FORMAT = "dazedtl-text-recipe"
VERSION = 1

ALIGNS = ("left", "center", "right")
#: What the alignment measures: the pen's advance, which is what ``getlength``
#: and every "centre the string" snippet use, or the painted ink.
MEASURES = ("advance", "ink")

#: The style fields a recipe carries. The rest of ``Style`` describes how to
#: erase the source text, which a recipe does not do.
STYLE_KEYS = (
    "text_color",
    "outline_color",
    "outline_width",
    "shadow",
    "glow",
    "cap_height",
    "align",
)


class RecipeError(ValueError):
    """A recipe that cannot be used as written, in words the caller can act on."""


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=128)
def font_at(path: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# ------------------------------------------------------------------- place


@dataclass
class Placement:
    """Where a slot's type goes, as a rule that holds for any string.

    ``x`` is the left edge, the centre or the right edge of the text, measured
    by ``by``; ``baseline`` is the line the glyphs stand on. A baseline rather
    than a top edge, because a family set at one baseline keeps it when one
    long title has to be set smaller - which is what HOLLOWWALD's eighth map
    card needed and what a top-edge rule gets wrong by the difference in
    ascent.

    ``snap`` rounds the drawing origin to whole pixels, the way the earlier
    passes being matched computed theirs: ``round(512 - getlength(text) / 2)``.
    """

    align: str = "center"
    by: str = "advance"
    x: float = 0.0
    baseline: float = 0.0
    snap: bool = True

    def origin(self, font: ImageFont.FreeTypeFont, text: str) -> tuple[float, float]:
        """The ``"la"`` drawing origin of *text* in *font* under this rule."""
        start, width = _span(font, text, self.by)
        offset = {"left": 0.0, "center": width / 2.0, "right": width}[self.align]
        x = self.x - offset - start
        y = self.baseline - font.getmetrics()[0]
        if self.snap:
            return float(round(x)), float(round(y))
        return x, y

    def to_dict(self) -> dict:
        return {
            "align": self.align,
            "by": self.by,
            "x": tidy(self.x),
            "baseline": tidy(self.baseline),
            "snap": self.snap,
        }

    @staticmethod
    def from_dict(data) -> Placement:
        if not isinstance(data, dict):
            raise RecipeError("A slot needs a placement")
        align = str(data.get("align") or "center")
        by = str(data.get("by") or "advance")
        if align not in ALIGNS:
            raise RecipeError(f"Alignment must be one of {', '.join(ALIGNS)}, not {align!r}")
        if by not in MEASURES:
            raise RecipeError(f"Alignment measures {' or '.join(MEASURES)}, not {by!r}")
        return Placement(
            align=align,
            by=by,
            x=_finite(data.get("x"), "placement x"),
            baseline=_finite(data.get("baseline"), "placement baseline"),
            snap=bool(data.get("snap", True)),
        )


def _span(font: ImageFont.FreeTypeFont, text: str, by: str) -> tuple[float, float]:
    """``(start, width)`` of what alignment measures, relative to the origin."""
    if by == "ink":
        left, _, right, _ = font.getbbox(text)
        return float(left), float(right - left)
    return 0.0, float(font.getlength(text))


def anchor(
    font: ImageFont.FreeTypeFont, text: str, origin_x: float, align: str, by: str
) -> float:
    """The inverse of ``Placement.origin`` on x: the anchor a drawn origin implies."""
    start, width = _span(font, text, by)
    offset = {"left": 0.0, "center": width / 2.0, "right": width}[align]
    return origin_x + start + offset


def _finite(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RecipeError(f"The {label} is not a number") from None
    if not math.isfinite(number):
        raise RecipeError(f"The {label} is not a number")
    return number


# -------------------------------------------------------------------- slots


@dataclass
class Slot:
    name: str
    #: The text the recipe was fitted on, so ``check`` can draw it again.
    text: str
    font: str
    font_sha256: str
    size: float
    placement: Placement
    style: Style
    #: Draw at this many times the size and box-filter down, which is how a
    #: canvas-rendered game window antialiases. 1 is Pillow drawing directly.
    supersample: int = 1
    #: What the fit found: correlation, error. Informational only.
    fit: dict = field(default_factory=dict)

    def to_dict(self, folder: Path | None = None) -> dict:
        style = self.style.to_dict()
        data = {
            "name": self.name,
            "text": self.text,
            "font": {"path": portable_path(self.font, folder), "sha256": self.font_sha256},
            "size": tidy(self.size),
            "supersample": self.supersample,
            "placement": self.placement.to_dict(),
            "style": {key: style[key] for key in STYLE_KEYS if key in style},
        }
        if self.fit:
            data["fit"] = self.fit
        return data

    @staticmethod
    def from_dict(data, folder: Path | None = None) -> Slot:
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise RecipeError("Every slot needs a name")
        name = data["name"]
        font = data.get("font")
        if not isinstance(font, dict) or not isinstance(font.get("path"), str):
            raise RecipeError(f"Slot {name!r} names no font file")
        size = _finite(data.get("size"), f"size of slot {name!r}")
        if not 1 <= size <= 2000:
            raise RecipeError(f"Slot {name!r} has an impossible size: {size}")
        supersample = int(data.get("supersample") or 1)
        if not 1 <= supersample <= 8:
            raise RecipeError(f"Slot {name!r} supersamples between 1 and 8 times")
        style = data.get("style") if isinstance(data.get("style"), dict) else {}
        return Slot(
            name=name,
            text=str(data.get("text") or ""),
            font=_resolve(font["path"], folder),
            font_sha256=str(font.get("sha256") or ""),
            size=size,
            placement=Placement.from_dict(data.get("placement")),
            style=Style.from_dict({key: style[key] for key in STYLE_KEYS if key in style}),
            supersample=supersample,
            fit=data.get("fit") if isinstance(data.get("fit"), dict) else {},
        )


def portable_path(path: str, folder: Path | None) -> str:
    """The font's path relative to the recipe, when it lives in the same game.

    Relative, so a recipe kept in a game's resources folder still finds the
    game's own font after the game moves. Only as far up as a game folder
    plausibly goes; past that an absolute path says more about where the font
    really is.
    """
    absolute = Path(path).resolve()
    if folder is None:
        return str(absolute)
    try:
        relative = os.path.relpath(absolute, folder.resolve())
    except ValueError:  # another drive on Windows
        return str(absolute)
    if relative.count("..") > 4:
        return str(absolute)
    return Path(relative).as_posix()


def _resolve(path: str, folder: Path | None) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() and folder is not None:
        candidate = folder / candidate
    return str(candidate)


@dataclass
class Recipe:
    width: int
    height: int
    slots: list[Slot]
    #: The whole-image fit report and where the fit came from.
    fit: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)

    def slot(self, name: str) -> Slot:
        for slot in self.slots:
            if slot.name == name:
                return slot
        raise RecipeError(
            f"The recipe has no slot {name!r}; it has "
            + ", ".join(repr(slot.name) for slot in self.slots)
        )

    def to_dict(self, folder: Path | None = None) -> dict:
        return {
            "format": FORMAT,
            "version": VERSION,
            "image": {"width": self.width, "height": self.height},
            "slots": [slot.to_dict(folder) for slot in self.slots],
            "fit": self.fit,
            "sources": self.sources,
        }

    @staticmethod
    def from_dict(data, folder: Path | None = None) -> Recipe:
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise RecipeError("This is not a DazedTL text recipe")
        if data.get("version") != VERSION:
            raise RecipeError(
                f"This recipe is version {data.get('version')}; this build reads {VERSION}"
            )
        image = data.get("image") if isinstance(data.get("image"), dict) else {}
        slots = [Slot.from_dict(item, folder) for item in data.get("slots") or []]
        if not slots:
            raise RecipeError("The recipe has no slots")
        names = [slot.name for slot in slots]
        if len(set(names)) != len(names):
            raise RecipeError("Slot names must be unique")
        return Recipe(
            width=int(image.get("width") or 0),
            height=int(image.get("height") or 0),
            slots=slots,
            fit=data.get("fit") if isinstance(data.get("fit"), dict) else {},
            sources=data.get("sources") if isinstance(data.get("sources"), dict) else {},
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(target.parent), ensure_ascii=False, indent=2)
        target.write_text(text + "\n", encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> Recipe:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RecipeError(f"Could not read the recipe {source}: {exc}") from None
        return Recipe.from_dict(data, source.parent)


def verify_font(slot: Slot) -> None:
    """Refuse to draw with a face other than the one the recipe was fitted on."""
    if not Path(slot.font).is_file():
        raise RecipeError(f"Slot {slot.name!r}: font file not found: {slot.font}")
    if slot.font_sha256 and file_sha256(slot.font) != slot.font_sha256:
        raise RecipeError(
            f"Slot {slot.name!r}: {slot.font} is not the font the recipe was fitted "
            "on (its hash differs). Point the recipe at the original file."
        )


# -------------------------------------------------------------------- draw


def coverage(
    font_path: str,
    size: float,
    text: str,
    origin: tuple[float, float],
    canvas: Box,
    spread: float = 0.0,
    supersample: int = 1,
) -> np.ndarray:
    """The glyphs of *text*, grown by *spread* pixels, as float32 over *canvas*.

    Grown by the rasteriser's own stroke - every point within *spread* of the
    outline - rather than by dilating the drawn pixels, because that is what
    ``draw.text(..., stroke_width=...)`` gives and what the passes being fitted
    used. A fractional spread is a fractional stroke, not a rounded one.
    """
    scale = max(1, int(supersample))
    image = Image.new("L", (canvas.w * scale, canvas.h * scale), 0)
    font = font_at(font_path, size * scale)
    at = ((origin[0] - canvas.x) * scale, (origin[1] - canvas.y) * scale)
    ImageDraw.Draw(image).text(
        at,
        text,
        font=font,
        fill=255,
        stroke_width=max(0.0, spread) * scale,
        stroke_fill=255,
    )
    if scale > 1:
        image = image.resize((canvas.w, canvas.h), Image.BOX)
    return np.asarray(image, dtype=np.float32) / 255.0


@dataclass
class Placed:
    """One slot's text at one size, positioned and ready to draw."""

    slot: Slot
    text: str
    size: float
    origin: tuple[float, float]
    #: The ink box, before any effect grows it.
    ink: Box
    #: Room for every layer: the ink box plus the effects' reach.
    canvas: Box
    _grown: dict = field(default_factory=dict, repr=False)

    def grow(self, spread: float) -> np.ndarray:
        key = round(float(spread), 4)
        plane = self._grown.get(key)
        if plane is None:
            plane = coverage(
                self.slot.font,
                self.size,
                self.text,
                self.origin,
                self.canvas,
                spread,
                self.slot.supersample,
            )
            self._grown[key] = plane
        return plane

    def layers(self, style: Style | None = None) -> list[effects.Layer]:
        style = style or self.slot.style
        return effects.stack(
            self.grow,
            style.text_color,
            outline_color=style.outline_color,
            outline_width=float(style.outline_width or 0),
            shadow=style.shadow,
            glow=style.glow,
        )


def place(
    slot: Slot,
    text: str,
    size: float | None = None,
    *,
    margin: int | None = None,
) -> Placed:
    """Lay *text* out under *slot*'s rule, at its own size unless told otherwise.

    A changed size keeps the slot's baseline and alignment, so a title shrunk
    to fit still sits on the family's line.
    """
    size = float(size or slot.size)
    font = font_at(slot.font, size)
    origin = slot.placement.origin(font, text)
    left, top, right, bottom = font.getbbox(text)
    ink = Box(
        math.floor(origin[0] + left),
        math.floor(origin[1] + top),
        math.ceil(origin[0] + right),
        math.ceil(origin[1] + bottom),
    )
    style = slot.style
    if margin is None:
        margin = effects.reach(float(style.outline_width or 0), style.shadow, style.glow)
    margin += 2
    canvas = Box(ink.x - margin, ink.y - margin, ink.x2 + margin, ink.y2 + margin)
    return Placed(slot, text, size, origin, ink, canvas)


def render(
    recipe: Recipe,
    base: np.ndarray,
    texts: dict[str, str],
    sizes: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[Placed]]:
    """Draw *texts* (slot name -> string) onto a copy of *base*, in slot order."""
    if recipe.width and recipe.height and base.shape[:2] != (recipe.height, recipe.width):
        raise RecipeError(
            f"The base is {base.shape[1]}x{base.shape[0]}; the recipe was "
            f"fitted on {recipe.width}x{recipe.height} images"
        )
    unknown = set(texts) - {slot.name for slot in recipe.slots}
    if unknown:
        recipe.slot(min(unknown))  # raises, naming the slots there are
    painter = effects.Painter(base)
    placed: list[Placed] = []
    for slot in recipe.slots:
        if slot.name not in texts:
            continue
        verify_font(slot)
        item = place(slot, texts[slot.name], (sizes or {}).get(slot.name))
        for colour, plane in item.layers():
            painter.paint(colour, plane, (item.canvas.x, item.canvas.y))
        placed.append(item)
    return painter.result(), placed


# ------------------------------------------------------------------- error


def _premultiplied(array: np.ndarray) -> np.ndarray:
    """RGBA as premultiplied float levels: what the pixel looks like over black."""
    pixels = array.astype(np.float32)
    if pixels.shape[2] == 3:
        alpha = np.full(pixels.shape[:2] + (1,), 255.0, dtype=np.float32)
        pixels = np.concatenate([pixels, alpha], axis=2)
    pixels[:, :, :3] *= pixels[:, :, 3:4] / 255.0
    return pixels


def difference(
    candidate: np.ndarray,
    accepted: np.ndarray,
    base: np.ndarray | None = None,
    reach: list[Box] | None = None,
) -> dict:
    """How far *candidate* is from *accepted*, over the text area.

    Mean absolute error of the premultiplied pixels, per channel, in levels of
    255 - premultiplied, because a colour under alpha 0 cannot be seen and must
    not count. The text area is every pixel either image changed from *base*;
    without a base it is every pixel the two disagree on. Alpha counts as a
    channel only when some pixel is translucent.

    *reach* is where the recipe can paint at all. A change outside it is not
    the recipe's error - it is the accepted image disagreeing with the base,
    usually a repair made after the text was drawn - so it is counted apart, as
    ``outside``, where it says the base is not quite that image's base.
    """
    if candidate.shape[:2] != accepted.shape[:2]:
        raise RecipeError("The images to compare are different sizes")
    first, second = _premultiplied(candidate), _premultiplied(accepted)
    if base is not None:
        reference = _premultiplied(base)
        area = (first != reference).any(axis=2) | (second != reference).any(axis=2)
    else:
        area = (first != second).any(axis=2)
    opaque = all(
        image.shape[2] == 3 or bool((image[:, :, 3] == 255).all())
        for image in (candidate, accepted)
    )
    channels = 3 if opaque else 4
    error = np.abs(first - second)[:, :, :channels]
    outside = None
    if reach is not None:
        inside = np.zeros(area.shape, dtype=bool)
        bounds = Box.from_size(area.shape[1], area.shape[0])
        for box in reach:
            rows, cols = box.clamp(bounds).slices()
            inside[rows, cols] = True
        stray = area & ~inside & (error.max(axis=2) > 0)
        outside = {
            "pixels": int(stray.sum()),
            "mean": round(float(error[stray].mean()), 3) if stray.any() else 0.0,
        }
        area &= inside
    pixels = int(area.sum())
    report = {"mean": 0.0, "p99": 0.0, "max": 0.0, "pixels": pixels, "channels": channels}
    if pixels:
        worst = error.max(axis=2)[area]
        report.update(
            mean=round(float(error[area].mean()), 3),
            p99=round(float(np.percentile(worst, 99)), 3),
            max=round(float(worst.max()), 3),
        )
    if outside is not None:
        report["outside"] = outside
    return report
