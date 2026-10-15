"""Recover a text recipe from the pixels of an accepted translation.

Given an image someone already accepted, the clean base it was drawn on, the
exact strings and the font, this finds how the strings were drawn: the size,
where they sit and by what rule, and the effect stack - face, outline, offset
shadow, outer glow - so the next image in the family is one ``render`` away
(see ``util.imagetools.recipe``).

It is the method that recovered the HOLLOWWALD title cards, made general:

1. **Find each string by shape.** The text's own face is one flat colour, so
   the changed pixels are split into a few colour groups and every group is
   correlated against the string drawn at a range of sizes. The face group at
   the right size correlates near 0.95; everything else is well below. This
   gives the size and a whole-pixel position.
2. **Fit the effects by error.** Every other number is found by coordinate
   descent on the mean absolute error of the premultiplied composite, starting
   from the face alone and adding an outline, a shadow or a glow only while
   each earns its place. Colours are never searched: for a given set of
   coverages the composite is linear in them, so least squares gives them
   exactly at every step.

The reported error is always measured by drawing the finished recipe with the
renderer that will draw the next image, never by the fitter's own model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from util.imagetools import effects
from util.imagetools.effects import Glow, Shadow
from util.imagetools.geometry import Box
from util.imagetools.recipe import (
    ALIGNS,
    MEASURES,
    Placement,
    Recipe,
    RecipeError,
    Slot,
    anchor,
    coverage,
    difference,
    file_sha256,
    font_at,
    render,
)
from util.imagetools.style import Style

#: A pixel the text changed by more than this many levels is part of it.
FOOTPRINT = 4
#: Room kept around the changed pixels, for effects fainter than the footprint.
CONTEXT = 32
#: Room kept around each string when it is fitted. Wider than any effect the
#: search may produce (``_effect_params`` bounds their reach), so every pixel a
#: group's numbers can change is inside the window its error is judged on.
WINDOW = 48
#: How much of the error an effect has to remove before it is kept. Without a
#: bar, a faint glow is always found: it soaks up the last level of
#: antialiasing mismatch and turns a plain outline into a three-layer recipe.
GAIN = 0.03
#: How much of a group's error a fractional position has to remove before its
#: strings leave the whole-pixel grid; see ``_subpixel``.
SUBPIXEL_GAIN = 0.10
#: Colour groups the changed pixels are split into before matching shapes.
CLUSTERS = 4
#: A string found with less agreement than this was not found.
MIN_CORRELATION = 0.4
EFFECTS = ("outline", "shadow", "glow")


@dataclass
class Request:
    """One string to find, and what is known about it up front."""

    name: str
    text: str
    font: str
    align: str = "center"
    by: str = "advance"
    #: Hints, when the search needs them: a size in points and a region.
    size: float | None = None
    near: Box | None = None
    #: Strings in one group share an effect stack - the lines of one message
    #: window. Each string is its own group by default.
    group: str = ""

    @property
    def style_group(self) -> str:
        return self.group or self.name


@dataclass
class Location:
    size: float
    x: float
    y: float
    score: float


def _rgba(array: np.ndarray) -> np.ndarray:
    if array.ndim != 3 or array.shape[2] not in (3, 4) or array.dtype != np.uint8:
        raise RecipeError("Images must be 8-bit RGB or RGBA")
    if array.shape[2] == 4:
        return array
    alpha = np.full(array.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.concatenate([array, alpha], axis=2)


def _premultiplied(array: np.ndarray) -> np.ndarray:
    pixels = array.astype(np.float32) / 255.0
    pixels[:, :, :3] *= pixels[:, :, 3:4]
    return pixels


def base_from_mask(original: np.ndarray, mask: np.ndarray, method: str = "telea") -> np.ndarray:
    """A clean base rebuilt from the original and the mask its text was erased under.

    For when the earlier pass kept its cleanup mask but not the clean image.
    The rebuild is the local reconstruction, so it is not the earlier pass's
    exact background; the fit error says how much that matters.
    """
    from util.imagetools import inpaint

    rgba = np.ascontiguousarray(_rgba(original))
    if mask.shape != rgba.shape[:2]:
        raise RecipeError("The cleanup mask must be the same size as the original")
    repaired, complaint, _changed = inpaint.reconstruct_rgba(
        rgba, mask.astype(bool), method, allow_fallback=False
    )
    if complaint:
        raise RecipeError(f"Could not rebuild the base: {complaint}")
    if original.shape[2] == 3:
        return np.ascontiguousarray(repaired[:, :, :3])
    return repaired


# ----------------------------------------------------------------- problem


@dataclass
class _View:
    """The accepted image and its base over one window, premultiplied and flat."""

    crop: Box
    target_rgb: np.ndarray
    target_alpha: np.ndarray
    base_rgb: np.ndarray
    base_alpha: np.ndarray
    alpha_counts: bool


class _Problem:
    """The accepted image and its base, and the areas worth looking at.

    The search covers everything the accepted image changed, so a string can be
    found wherever it is. Fitting then looks only near the strings it found: an
    accepted image routinely differs from its base somewhere else too - a seam
    repaired after the text was drawn - and no text recipe can explain that, so
    it would only slow the fit down and blur its error.
    """

    def __init__(self, accepted: np.ndarray, base: np.ndarray, requests: list[Request]):
        height, width = accepted.shape[:2]
        self.bounds = Box.from_size(width, height)
        self.accepted, self.base = accepted, base
        changed = np.abs(
            _premultiplied(accepted) - _premultiplied(base)
        ).max(axis=2) * 255.0 > FOOTPRINT
        if not changed.any():
            raise RecipeError(
                "The accepted image and the base are identical: there is no text to fit"
            )
        ys, xs = np.nonzero(changed)
        area = Box(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        for request in requests:
            if request.near is not None:
                area = area.union(request.near)
        self.search = area.expand(CONTEXT, self.bounds)
        rows, cols = self.search.slices()
        self.changed = changed[rows, cols]
        self.target = _premultiplied(accepted[rows, cols])
        self.alpha_counts = not (
            (accepted[:, :, 3] == 255).all() and (base[:, :, 3] == 255).all()
        )

    def view(self, box: Box) -> _View:
        crop = box.clamp(self.bounds)
        rows, cols = crop.slices()
        target = _premultiplied(self.accepted[rows, cols])
        reference = _premultiplied(self.base[rows, cols])
        return _View(
            crop,
            target[:, :, :3].reshape(-1, 3),
            target[:, :, 3].reshape(-1),
            reference[:, :, :3].reshape(-1, 3),
            reference[:, :, 3].reshape(-1),
            self.alpha_counts,
        )


# ------------------------------------------------------------------ locate


def _clusters(problem: _Problem) -> list[np.ndarray]:
    """The changed pixels split into colour groups, one of which is the face.

    A small k-means seeded at luminance quantiles, so the same pixels always
    give the same groups - a fit that changes between runs cannot be checked.
    """
    pixels = problem.target[problem.changed]
    masks = [problem.changed]
    count = pixels.shape[0]
    if count < CLUSTERS * 4:
        return masks
    luma = pixels[:, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    order = np.argsort(luma + pixels[:, 3] * 1e-3, kind="stable")
    centres = pixels[order[[int((i + 0.5) * count / CLUSTERS) for i in range(CLUSTERS)]]]
    labels = np.zeros(count, dtype=np.int64)
    for _ in range(12):
        distance = ((pixels[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        labels = np.argmin(distance, axis=1)
        for index in range(CLUSTERS):
            members = pixels[labels == index]
            if members.shape[0]:
                centres[index] = members.mean(axis=0)
    for index in range(CLUSTERS):
        mask = np.zeros_like(problem.changed)
        mask[problem.changed] = labels == index
        if mask.sum() >= 8:
            masks.append(mask)
    return masks


def _bands(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """``(top, bottom, left, right)`` of each horizontal run of ink."""
    # Any row with ink, rather than rows with a share of the busiest row's: a
    # title's busiest row is ten times a subtitle's, and a relative threshold
    # cut the subtitle down to its x-height and sized it a fifth too small.
    filled = mask.sum(axis=1) >= 2
    runs: list[list[int]] = []
    for row, on in enumerate(filled):
        if not on:
            continue
        if runs and row - runs[-1][1] <= 2:
            runs[-1][1] = row + 1
        else:
            runs.append([row, row + 1])
    bands = []
    for top, bottom in runs:
        if bottom - top < 4:
            continue
        columns = np.nonzero(mask[top:bottom].any(axis=0))[0]
        bands.append((top, bottom, int(columns[0]), int(columns[-1]) + 1))
    return bands


def _template(font: str, size: float, text: str) -> tuple[np.ndarray, int, int]:
    """The face drawn at the origin, cropped to its ink, and where that crop starts."""
    left, top, right, bottom = font_at(font, size).getbbox(text)
    canvas = Box(left - 1, top - 1, right + 1, bottom + 1)
    return coverage(font, size, text, (0.0, 0.0), canvas), canvas.x, canvas.y


def _sizes(request: Request, band: tuple[int, int, int, int]) -> list[int]:
    if request.size:
        middle = round(request.size)
        return [s for s in range(middle - 1, middle + 2) if s >= 4]
    reference = 100.0
    left, top, right, bottom = font_at(request.font, reference).getbbox(request.text)
    if right <= left or bottom <= top:
        return []
    by_height = reference * (band[1] - band[0]) / (bottom - top)
    by_width = reference * (band[3] - band[2]) / (right - left)
    sizes: set[int] = set()
    for centre in (by_width, by_height):
        low, high = math.floor(centre * 0.9), math.ceil(centre * 1.1)
        sizes.update(range(max(4, low - 1), min(1000, high + 1) + 1))
    return sorted(sizes)


def _locate(problem: _Problem, request: Request, masks: list[np.ndarray]) -> Location:
    """Size and whole-pixel origin by template correlation of a face mask."""
    best = Location(0, 0, 0, -1.0)
    crop = problem.search
    templates: dict[int, tuple[np.ndarray, int, int]] = {}
    for mask in masks:
        if request.near is not None:
            limit = np.zeros_like(mask)
            near = request.near
            limit[
                max(0, near.y - crop.y) : max(0, near.y2 - crop.y),
                max(0, near.x - crop.x) : max(0, near.x2 - crop.x),
            ] = True
            mask = mask & limit
        plane = mask.astype(np.float32)
        for band in _bands(mask):
            for size in _sizes(request, band):
                if size not in templates:
                    templates[size] = _template(request.font, size, request.text)
                template, start_x, start_y = templates[size]
                th, tw = template.shape
                pad = max(4, th // 4)
                top = max(0, min(band[0] - pad, band[1] + pad - th))
                bottom = min(plane.shape[0], max(band[1] + pad, top + th))
                region = plane[top:bottom]
                if region.shape[0] < th or region.shape[1] < tw or template.std() == 0:
                    continue
                scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
                scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)
                _, score, _, (mx, my) = cv2.minMaxLoc(scores)
                if score > best.score:
                    best = Location(
                        float(size),
                        float(crop.x + mx - start_x),
                        float(crop.y + top + my - start_y),
                        float(score),
                    )
    if best.score < MIN_CORRELATION:
        raise RecipeError(
            f"Could not find {request.text!r} in the accepted image (best match "
            f"{max(best.score, 0):.2f}). Check the text and the font, or give a "
            "size or a region to search."
        )
    return best


def _ink(request: Request, found: Location) -> Box:
    left, top, right, bottom = font_at(request.font, found.size).getbbox(request.text)
    return Box(
        math.floor(found.x + left),
        math.floor(found.y + top),
        math.ceil(found.x + right),
        math.ceil(found.y + bottom),
    )


def _union(boxes: list[Box]) -> Box:
    area = boxes[0]
    for box in boxes[1:]:
        area = area.union(box)
    return area


# ------------------------------------------------------------------- model


@dataclass(frozen=True)
class _Param:
    key: str
    step: float
    least: float
    low: float
    high: float


def _effect_params(group: str, kind: str) -> list[_Param]:
    """The numbers of one effect, bounded so none reaches past ``WINDOW``."""
    alpha = _Param(f"{group}:{kind}.alpha", 0.1, 0.0125, 0.05, 1.0)
    if kind == "face":
        return [alpha]
    if kind == "outline":
        return [_Param(f"{group}:outline.width", 0.5, 0.25, 0.25, 8), alpha]
    if kind == "shadow":
        return [
            _Param(f"{group}:shadow.dx", 1, 0.25, -12, 12),
            _Param(f"{group}:shadow.dy", 1, 0.25, -12, 12),
            _Param(f"{group}:shadow.spread", 0.5, 0.25, 0, 6),
            _Param(f"{group}:shadow.blur", 0.5, 0.25, 0, 8),
            alpha,
        ]
    return [
        _Param(f"{group}:glow.spread", 0.5, 0.25, 0, 6),
        _Param(f"{group}:glow.blur", 0.5, 0.25, 0.25, 12),
        alpha,
    ]


def _starts(group: str, kind: str) -> list[dict]:
    """Where an effect's search starts: a handful of shapes, the best of which
    coordinate descent then refines."""
    if kind == "face":
        return [{f"{group}:face.alpha": alpha} for alpha in (0.5, 0.75)]
    if kind == "outline":
        return [
            {f"{group}:outline.width": width, f"{group}:outline.alpha": 1.0}
            for width in (0.5, 1, 2, 3)
        ]
    if kind == "shadow":
        steps = (-3, -1.5, 0, 1.5, 3)
        return [
            {
                f"{group}:shadow.dx": dx,
                f"{group}:shadow.dy": dy,
                f"{group}:shadow.spread": 0.0,
                f"{group}:shadow.blur": 1.0,
                f"{group}:shadow.alpha": 0.6,
            }
            for dx in steps
            for dy in steps
            if dx or dy
        ]
    return [
        {
            f"{group}:glow.spread": spread,
            f"{group}:glow.blur": blur_,
            f"{group}:glow.alpha": 0.6,
        }
        for spread in (0.0, 2.0)
        for blur_ in (1.5, 4.0, 8.0)
    ]


#: The numbers each layer's coverage depends on, besides where its string is.
_SHAPE = {
    "glow": ("glow", "glow.spread", "glow.blur", "glow.alpha"),
    "shadow": (
        "shadow", "shadow.dx", "shadow.dy", "shadow.spread", "shadow.blur", "shadow.alpha",
    ),
    "outline": ("outline", "outline.width", "outline.alpha"),
    "face": ("face.alpha",),
}
_KINDS = ("glow", "shadow", "outline", "face")


class _Model:
    """The composite over one window as a function of the numbers being fitted.

    Premultiplied throughout, which is what makes colours a linear problem:
    painting colour ``C`` at coverage ``a`` over a pixel ``P`` gives
    ``C*a + P*(1-a)``, so the finished pixel is the base times everything's
    transmission plus each colour times its own visible coverage.

    Every string is drawn, whichever group is being fitted, so where a title's
    glow reaches under its subtitle the subtitle's fit sees it.
    """

    def __init__(self, view: _View, requests: list[Request], supersample: int):
        self.view = view
        self.requests = requests
        self.supersample = supersample
        groups = dict.fromkeys(request.style_group for request in requests)
        self.tags = [(group, kind) for group in groups for kind in _KINDS]
        self._planes: dict = {}
        self._layers: dict = {}
        self._errors: dict = {}

    def _grow(self, request: Request, state: dict, spread: float) -> np.ndarray:
        x, y, size = (state[f"{request.name}:{axis}"] for axis in ("x", "y", "size"))
        key = (request.name, x, y, size, round(spread, 4))
        plane = self._planes.get(key)
        if plane is None:
            if len(self._planes) > 96:
                self._planes.pop(next(iter(self._planes)))
            plane = coverage(
                request.font, size, request.text, (x, y), self.view.crop,
                spread, self.supersample,
            )
            self._planes[key] = plane
        return plane

    def _layer(self, request: Request, state: dict, kind: str) -> np.ndarray | None:
        """One layer's alpha, remembered: most moves change one number of one layer."""
        group = request.style_group
        key = (request.name, kind) + tuple(
            state[f"{request.name}:{axis}"] for axis in ("x", "y", "size")
        ) + tuple(state[f"{group}:{name}"] for name in _SHAPE[kind])
        if key in self._layers:
            return self._layers[key]

        def value(name: str) -> float:
            return state[f"{group}:{name}"]

        def grow(spread: float) -> np.ndarray:
            return self._grow(request, state, spread)

        plane = None
        if kind == "face":
            plane = grow(0.0) * value("face.alpha")
        elif state.get(f"{group}:{kind}"):
            if kind == "glow":
                halo = effects.blur(grow(value("glow.spread")), value("glow.blur"))
                plane = np.clip(halo, 0, 1) * value("glow.alpha")
            elif kind == "shadow":
                moved = effects.shift(
                    grow(value("shadow.spread")), value("shadow.dx"), value("shadow.dy")
                )
                plane = np.clip(effects.blur(moved, value("shadow.blur")), 0, 1) * value(
                    "shadow.alpha"
                )
            else:
                plane = grow(value("outline.width")) * value("outline.alpha")
        if len(self._layers) > 256:
            self._layers.pop(next(iter(self._layers)))
        self._layers[key] = plane
        return plane

    def _system(self, state: dict):
        """Each colour's visible coverage, and how much of the base still shows."""
        layers = [
            (self.tags.index((request.style_group, kind)), plane)
            for request in self.requests
            for kind in _KINDS
            if (plane := self._layer(request, state, kind)) is not None
        ]
        used = sorted({tag for tag, _ in layers})
        transmission = np.ones(self.view.crop.h * self.view.crop.w, dtype=np.float32)
        columns = np.zeros((transmission.size, len(used)), dtype=np.float32)
        for tag, alpha in reversed(layers):
            flat = alpha.reshape(-1)
            columns[:, used.index(tag)] += flat * transmission
            transmission *= 1.0 - flat
        return used, columns, transmission

    @staticmethod
    def _solve(columns: np.ndarray, rest: np.ndarray, weights: np.ndarray | None = None):
        weighted = columns if weights is None else columns * weights[:, None]
        gram = (weighted.T @ columns).astype(np.float64)
        moment = (weighted.T @ rest).astype(np.float64)
        gram += np.eye(gram.shape[0]) * (1e-9 + 1e-7 * np.trace(gram) / gram.shape[0])
        return np.clip(np.linalg.solve(gram, moment), 0.0, 1.0).astype(np.float32)

    def evaluate(self, state: dict, robust: bool = False):
        """``(mean absolute error in levels of 255 per channel, colours per tag)``."""
        view = self.view
        used, columns, transmission = self._system(state)
        rest = view.target_rgb - view.base_rgb * transmission[:, None]
        solved = self._solve(columns, rest)
        if robust:
            # A few rounds of reweighting turn least squares into least
            # absolute error, the measure the fit is judged by.
            for _ in range(4):
                residual = np.abs(columns @ solved - rest).sum(axis=1)
                solved = self._solve(columns, rest, 1.0 / np.maximum(residual, 1.0 / 255))
        error = float(np.abs(columns @ solved - rest).sum())
        channels = 3
        if view.alpha_counts:
            alpha = 1.0 - (1.0 - view.base_alpha) * transmission
            error += float(np.abs(alpha - view.target_alpha).sum())
            channels = 4
        colours = np.zeros((len(self.tags), 3), dtype=np.float32)
        colours[used] = solved
        return error * 255.0 / (transmission.size * channels), colours

    def error(self, state: dict) -> float:
        key = tuple(sorted(state.items()))
        found = self._errors.get(key)
        if found is None:
            found = self.evaluate(state)[0]
            self._errors[key] = found
        return found


def _clamp(value: float, param: _Param) -> float:
    return float(min(param.high, max(param.low, round(value / param.least) * param.least)))


def _diagonals(model: _Model, state: dict, best: float, params: list[_Param]):
    """Move an effect's opacity together with its shape, where one at a time cannot.

    A wider glow at lower opacity looks much like a narrower, stronger one, so
    the error runs along a diagonal valley that single-number steps can only
    leave by getting worse first.
    """
    pairs = []
    for param in params:
        if param.key.endswith(".alpha"):
            prefix = param.key[: -len("alpha")]
            pairs += [
                (param, other)
                for other in params
                if other.key.startswith(prefix) and other is not param
            ]
    improved = True
    while improved:
        improved = False
        for first, second in pairs:
            for a, b in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                trial = dict(state)
                trial[first.key] = _clamp(state[first.key] + a * first.least * 2, first)
                trial[second.key] = _clamp(state[second.key] + b * second.least, second)
                error = model.error(trial)
                if error < best - 1e-6:
                    state, best, improved = trial, error, True
    return state, best


def _descend(model: _Model, state: dict, params: list[_Param], sweeps: int = 4):
    """Pattern search, one number at a time, halving each step until it stops paying."""
    best = model.error(state)
    for _ in range(sweeps):
        start = best
        for param in params:
            step = param.step
            while step >= param.least - 1e-9:
                moved = False
                for sign in (1, -1):
                    value = _clamp(state[param.key] + sign * step, param)
                    if value == state[param.key]:
                        continue
                    trial = dict(state)
                    trial[param.key] = value
                    error = model.error(trial)
                    if error < best - 1e-6:
                        state, best, moved = trial, error, True
                        break
                if not moved:
                    step /= 2
        state, best = _diagonals(model, state, best, params)
        if best >= start - 1e-6:
            break
    return state, best


# ------------------------------------------------------------------ search


def _switch(state: dict, group: str, kind: str, on: bool) -> dict:
    trial = dict(state)
    if kind == "face":
        if not on:
            trial[f"{group}:face.alpha"] = 1.0
    else:
        trial[f"{group}:{kind}"] = int(on)
    return trial


def _active_params(group: str, active: list[str]) -> list[_Param]:
    return [param for kind in active for param in _effect_params(group, kind)]


def _choose(
    model: _Model, state: dict, group: str, geometry: list[_Param], kinds: tuple[str, ...]
):
    """Add effects one at a time while each earns its place, then drop the idle.

    Each round tries every missing effect from a few starting shapes and keeps
    the one that removes the most error, provided it removes at least ``GAIN``
    of it; coordinate descent then settles everything active. Afterwards any
    effect the later ones made redundant is taken out again. Returns
    ``(state, active effects)``.
    """
    error = model.error(state)
    active: list[str] = []
    while True:
        best = None
        for kind in kinds:
            if kind in active:
                continue
            for start in _starts(group, kind):
                trial = _switch(state, group, kind, True)
                trial.update(start)
                offered = model.error(trial)
                if best is None or offered < best[0]:
                    best = (offered, kind, trial)
        if best is None or best[0] > error * (1 - GAIN):
            break
        active.append(best[1])
        state, error = _descend(model, best[2], geometry + _active_params(group, active))
    for kind in list(active):
        trial = _switch(state, group, kind, False)
        if model.error(trial) <= error * (1 + GAIN / 3):
            active.remove(kind)
            state, error = trial, model.error(trial)
    return state, active


def _subpixel(
    model: _Model, state: dict, group: str, members: list[Request], active: list[str]
) -> dict:
    """Let strings off the whole-pixel grid only where that clearly pays.

    Pillow callers draw at whole pixels, so a fit that lands a quarter pixel
    over has usually traded position for an effect's shape rather than found
    a fractional origin, and a recipe with a whole-pixel rule ("centred on
    512") is the one a person can check and reuse. A group keeps a fractional
    position only when it removes ``SUBPIXEL_GAIN`` of its error.
    """
    params = [
        _Param(
            f"{request.name}:{axis}", 0.5, 0.25,
            state[f"{request.name}:{axis}"] - 1, state[f"{request.name}:{axis}"] + 1,
        )
        for request in members
        for axis in ("x", "y")
    ] + _active_params(group, active)
    moved, error = _descend(model, state, params, sweeps=2)
    if error <= model.error(state) * (1 - SUBPIXEL_GAIN):
        return moved
    return state


# --------------------------------------------------------------------- fit


def _check(requests: list[Request]) -> None:
    if not requests:
        raise RecipeError("Name at least one string to fit")
    names = [request.name for request in requests]
    if len(set(names)) != len(names):
        raise RecipeError("Each string needs its own slot name")
    for request in requests:
        if not request.text.strip():
            raise RecipeError(f"Slot {request.name!r} has no text")
        if request.align not in ALIGNS or request.by not in MEASURES:
            raise RecipeError(f"Slot {request.name!r} has an unknown alignment rule")
        try:
            font_at(request.font, 12)
        except OSError as exc:
            raise RecipeError(
                f"Slot {request.name!r}: cannot open font {request.font}: {exc}"
            ) from None


def _placement(request: Request, size: float, x: float, y: float, width: int) -> Placement:
    """The rule that puts the fitted string where it was found.

    One image cannot tell a centring rule from a coincidence, so the caller
    names the rule and this finds its number. A whole-pixel origin means the
    earlier pass rounded, which leaves half a pixel of slack in the anchor; the
    slack is spent on the roundest number that still reproduces the origin -
    the image's centre first, which is where centred titles almost always are.
    """
    font = font_at(request.font, size)
    baseline = y + font.getmetrics()[0]
    raw = anchor(font, request.text, x, request.align, request.by)
    snapped = abs(x - round(x)) < 1e-6 and abs(y - round(y)) < 1e-6
    if not snapped:
        return Placement(request.align, request.by, raw, baseline, False)
    candidates = []
    if request.align == "center":
        candidates.append(width / 2.0)
    candidates += [float(round(raw)), math.floor(raw) + 0.5, math.ceil(raw) - 0.5]
    for value in candidates:
        rule = Placement(request.align, request.by, value, baseline, True)
        if abs(value - raw) <= 0.5 and rule.origin(font, request.text) == (x, y):
            return rule
    return Placement(request.align, request.by, raw, baseline, True)


def _style(state: dict, colours: dict, group: str, size: float, font: str) -> Style:
    def colour(kind: str, alpha: float) -> list[int]:
        return [round(c * 255) for c in colours[(group, kind)]] + [round(alpha * 255)]

    def value(name: str) -> float:
        return state[f"{group}:{name}"]

    style = Style(text_color=colour("face", value("face.alpha")))
    if state.get(f"{group}:outline"):
        style.outline_color = colour("outline", value("outline.alpha"))
        style.outline_width = effects.tidy(value("outline.width"))
    if state.get(f"{group}:shadow"):
        style.shadow = Shadow(
            color=colour("shadow", value("shadow.alpha")),
            dx=value("shadow.dx"),
            dy=value("shadow.dy"),
            spread=value("shadow.spread"),
            blur=value("shadow.blur"),
        )
    if state.get(f"{group}:glow"):
        style.glow = Glow(
            color=colour("glow", value("glow.alpha")),
            spread=value("glow.spread"),
            blur=value("glow.blur"),
        )
    _, top, _, bottom = font_at(font, size).getbbox("H")
    style.cap_height = max(1, bottom - top)
    return style


def fit(
    accepted: np.ndarray,
    base: np.ndarray,
    requests: list[Request],
    *,
    supersample: int = 1,
    allowed: tuple[str, ...] = EFFECTS,
) -> Recipe:
    """Fit a recipe for *requests* to *accepted*, drawn over *base*."""
    # Thousands of small blurs and shifts: OpenCV's thread pool costs more to
    # wake for each than the work itself, several cores' worth of it.
    threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        return _fit(accepted, base, requests, supersample, allowed)
    finally:
        cv2.setNumThreads(threads)


def _fit(
    accepted: np.ndarray,
    base: np.ndarray,
    requests: list[Request],
    supersample: int,
    allowed: tuple[str, ...],
) -> Recipe:
    _check(requests)
    if accepted.shape[:2] != base.shape[:2]:
        raise RecipeError(
            f"The accepted image is {accepted.shape[1]}x{accepted.shape[0]} and the "
            f"base {base.shape[1]}x{base.shape[0]}; they must match"
        )
    if not 1 <= supersample <= 8:
        raise RecipeError("Supersample between 1 and 8 times")
    unknown = set(allowed) - set(EFFECTS)
    if unknown:
        raise RecipeError(f"Unknown effect {min(unknown)!r}; choose from {', '.join(EFFECTS)}")
    problem = _Problem(_rgba(accepted), _rgba(base), requests)
    masks = _clusters(problem)
    locations = {request.name: _locate(problem, request, masks) for request in requests}
    groups: dict[str, list[Request]] = {}
    for request in requests:
        groups.setdefault(request.style_group, []).append(request)
    models = {
        group: _Model(
            problem.view(
                _union([_ink(r, locations[r.name]) for r in members]).expand(WINDOW)
            ),
            requests,
            supersample,
        )
        for group, members in groups.items()
    }

    state: dict = {}
    geometry: dict[str, list[_Param]] = {group: [] for group in groups}
    for request in requests:
        found = locations[request.name]
        state.update({
            f"{request.name}:x": found.x,
            f"{request.name}:y": found.y,
            f"{request.name}:size": found.size,
        })
        # Whole pixels first: see ``_subpixel``.
        geometry[request.style_group] += [
            _Param(f"{request.name}:x", 1, 1, found.x - 8, found.x + 8),
            _Param(f"{request.name}:y", 1, 1, found.y - 8, found.y + 8),
            _Param(f"{request.name}:size", 1, 1, max(4.0, found.size - 6), found.size + 6),
        ]
    for group in groups:
        state[f"{group}:face.alpha"] = 1.0
        for kind in EFFECTS:
            state[f"{group}:{kind}"] = 0
            for param in _effect_params(group, kind):
                state.setdefault(param.key, 0.0)

    # One group at a time, each judged on the pixels around its own strings: a
    # subtitle's effects weighed against the whole card's error never make the
    # cut. A translucent face is offered like an effect, so an opaque one stays
    # exactly opaque instead of trading opacity for colour under its outline.
    chosen: dict[str, list[str]] = {}
    for group, model in models.items():
        state, _ = _descend(model, state, geometry[group], sweeps=2)
        state, chosen[group] = _choose(
            model, state, group, geometry[group], ("face", *allowed)
        )
    # Again with every group's effects in place, since a title's glow can
    # reach under its subtitle; then off the whole-pixel grid where it pays.
    for group, model in models.items():
        params = geometry[group] + _active_params(group, chosen[group])
        state, _ = _descend(model, state, params, sweeps=3)
        state = _subpixel(model, state, group, groups[group], chosen[group])

    colours: dict = {}
    for group, model in models.items():
        _, solved = model.evaluate(state, robust=True)
        for kind in _KINDS:
            colours[(group, kind)] = solved[model.tags.index((group, kind))]

    height, width = accepted.shape[:2]
    slots = []
    for request in requests:
        group = request.style_group
        size = state[f"{request.name}:size"]
        x, y = state[f"{request.name}:x"], state[f"{request.name}:y"]
        style = _style(state, colours, group, size, request.font)
        style.align = request.align
        slots.append(
            Slot(
                name=request.name,
                text=request.text,
                font=request.font,
                font_sha256=file_sha256(request.font),
                size=size,
                placement=_placement(request, size, x, y, width),
                style=style,
                supersample=supersample,
                fit={"correlation": round(locations[request.name].score, 3), "group": group},
            )
        )
    recipe = Recipe(width, height, slots)
    rendered, placed = render(recipe, base, {request.name: request.text for request in requests})
    recipe.fit = {
        "error": difference(rendered, accepted, base, [item.canvas for item in placed])
    }
    return recipe
