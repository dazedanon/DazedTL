"""Rebuild the text-free background that an image family shares.

A variant family is a set of same-size images that are identical except where
each carries its own lettering, such as name cards on one starry backdrop or
area banners on one shaded ellipse. Wherever a member's lettering does not
reach a pixel, that member holds the true background there, so the family
returns exact pixels that inpainting can only guess.

The solver works in premultiplied colour and transparency (t = 1 - alpha),
where a neutral dark glow of coverage g scales both by k = 1 - g. Every pixel
where members differ gets the best evidence available:

- consensus: the value of a member whose lettering does not reach it, taken
  from the one farthest from its own strokes; the reach ends where lettering
  changes pixels by no more than the tolerance. Over a translucent backdrop
  lettering only adds coverage, so a member more opaque than another is
  lettered there; shared white fill or black shadow can't outvote the backdrop.
  Untouched donors must agree, or the family is rejected as a conflict.
- inverted: the glow model g = o * blur(dilate(core, r), sigma), fitted on
  pixels whose truth the consensus gives, inverted from each lettered member
  and weighted smoothly toward the members with the highest k.
- blended: where even the best member is weak, that estimate keeps only its
  star and detail peaks over a smooth Laplace fill, blended with a ramp.
- filled: a Laplace fill, where no member gives evidence or where the family's
  backdrop is smooth enough that the fill beats inversion.

Inversion and the Laplace fill both rebuild consensus pixels from lettered
members alone first; the one with the lower leave-one-out error is used, and
inversion reaches down to the weakest members for which it still wins. Pixels
every member agrees on are never changed.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from dazedtl.compatibility import image_editor

KEPT, CONSENSUS, INVERTED, BLENDED, FILLED = range(5)
METHODS = ("kept", "consensus", "inverted", "blended", "filled")
# Distinct colours for viewing the method map as a palette PNG.
PALETTE = ((0, 0, 0), (40, 170, 90), (60, 130, 230), (240, 170, 40), (220, 50, 50))
SIGMAS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0)
RADII = (0, 1, 2, 3)
# Confidence is 255 * (1 - expected error / CONFIDENCE_SPAN levels).
CONFIDENCE_SPAN = 8.0


@dataclass(frozen=True)
class Options:
    # A member differing from the family by this many levels is lettering.
    core_delta: float = 48.0
    # So is a member this opaque where another shows a translucent backdrop.
    core_alpha: int = 235
    # Lettering components smaller than this are left out of the glow fit.
    min_area: int = 12
    # Untouched donors differing by more than tolerance levels disagree. A few
    # faint disagreements are lettering tails; many, or any beyond conflict
    # levels, mean the members do not share one background.
    tolerance: float = 2.0
    conflict: float = 24.0
    donor_min_distance: float = 4.0
    donor_min_k: float = 0.5
    # A donor this much weaker than the best one counts e times less.
    k_spread: float = 0.1
    weak_k: float = 0.97
    star_threshold: float = 0.08
    ramp: int = 8
    # Leave-one-out mean error, in levels, above which inversion is rejected.
    max_error: float = 1.5
    # A fitted glow model to reuse, or None to fit one.
    glow: dict | None = None


class FamilyError(ValueError):
    """The images can't give a background, with details for the report."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


@dataclass
class Family:
    """What a family's members show about their background, within the box
    around the pixels where they differ."""

    full: np.ndarray
    box: tuple[int, int, int, int]
    stack: np.ndarray
    differ: np.ndarray
    distance: np.ndarray
    donors: np.ndarray
    exact: np.ndarray
    winner: np.ndarray
    background: np.ndarray
    method: np.ndarray
    confidence: np.ndarray
    report: dict
    options: Options


@dataclass
class Solution:
    pixels: np.ndarray
    method: np.ndarray
    confidence: np.ndarray
    report: dict


def _box(mask):
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    return [
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    ]


def _bounds(mask):
    """The box of a mask known to be set somewhere."""
    ys, xs = np.nonzero(mask)
    return (
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )


def _ellipse(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)


def _components(mask, min_area):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def _distance(mask):
    """Distance of every pixel to the nearest pixel of mask."""
    if not mask.any():
        return np.full(mask.shape, np.inf, np.float32)
    return cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)


def _premultiplied(stack):
    """Premultiplied colour and transparency t = 1 - alpha, in 0..1."""
    values = stack.astype(np.float32) / 255
    alpha = values[..., 3:4]
    return np.concatenate([values[..., :3] * alpha, 1 - alpha], -1)


def _straight(values, fallback):
    """Rounded straight RGBA from premultiplied values; transparent pixels
    keep the fallback's hidden colour."""
    alpha = np.clip(1 - values[..., 3], 0, 1)
    colour = np.clip(values[..., :3], 0, alpha[..., None])
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(
            alpha[..., None] > 1e-6, colour / alpha[..., None], fallback[..., :3] / 255
        )
    return np.clip(np.round(np.dstack([rgb, alpha]) * 255), 0, 255).astype(np.uint8)


def _glow_mask(core, sigma, radius):
    mask = core.astype(np.float32)
    if radius > 0:
        mask = cv2.dilate(
            mask, _ellipse(radius), borderType=cv2.BORDER_CONSTANT, borderValue=0
        )
    size = int(sigma * 4) * 2 + 1
    return cv2.GaussianBlur(mask, (size, size), sigma, borderType=cv2.BORDER_CONSTANT)


def harmonic_fill(values, mask):
    """Solve Laplace's equation for the masked pixels of a float image, with
    the other pixels as fixed boundary: the image tools' exact fill, which the
    inpainting bridge and the image text editor run too."""
    result = values.astype(np.float64, copy=True)
    if not mask.any() or mask.all():
        return result
    return image_editor.harmonic_fill(result, mask)


def _consensus(flat, eligible):
    """Per pixel, the eligible member whose exact value most eligible members
    share, how many share it, and whether another value ties with it."""
    support = np.full(flat.shape, -1, np.int32)
    for index in range(len(flat)):
        same = (flat == flat[index]) & eligible
        support[index] = np.where(eligible[index], same.sum(0), -1)
    winner = support.argmax(0)
    best = np.take_along_axis(support, winner[None], 0)[0]
    chosen = np.take_along_axis(flat, winner[None], 0)[0]
    rival = np.where((flat != chosen) & eligible, support, -1).max(0)
    return winner, best, rival == best


def _reach(distances, gap=4):
    """How far lettering reaches beyond its strong strokes: its tails thin
    out continuously, so the first gap of empty distances ends them and a
    member's own difference further away stays a disagreement."""
    if not len(distances):
        return 1.0
    counts = np.bincount(np.floor(distances).astype(np.int64))
    empty = 0
    for distance, count in enumerate(counts):
        empty = empty + 1 if count == 0 else 0
        if empty == gap:
            return float(distance - gap + 1)
    return float(len(counts))


def _fit_glow(samples, cores):
    """Fit one neutral glow to lettered members over pixels whose background
    the consensus gives: truth - observed = g * truth - g * colour in colour
    channels and g * truth in transparency, with g = o * glow mask."""
    observed = np.concatenate([item[3] for item in samples])
    truth = np.concatenate([item[4] for item in samples])
    difference = (truth - observed).ravel()
    best = None
    for radius in RADII:
        for sigma in SIGMAS:
            weight = np.concatenate(
                [
                    _glow_mask(cores[index], sigma, radius)[ys, xs]
                    for index, ys, xs, _, _ in samples
                ]
            )[:, None]
            colour_term = np.concatenate(
                [-weight.repeat(3, 1), np.zeros_like(weight)], 1
            )
            design = np.stack([(weight * truth).ravel(), colour_term.ravel()], 1)
            solution = np.linalg.lstsq(design, difference, rcond=None)[0]
            strength = float(solution[0])
            if not 0 < strength <= 1:
                continue
            colour = min(max(float(solution[1]) / strength, 0.0), 1.0)
            residual = difference - design @ np.array([strength, strength * colour])
            error = float(np.sqrt(np.mean(residual**2)))
            if best is None or error < best["rms"]:
                best = {
                    "o": strength,
                    "sigma": sigma,
                    "r": radius,
                    "colour": colour,
                    "rms": error,
                }
    return best


def _invert(values, k, colour, clearest):
    """The background under a neutral glow of coverage 1 - k and grey colour.
    Lettering only adds coverage, so the backdrop is at least as transparent
    as the clearest member."""
    k = np.maximum(k, 1e-6)[..., None]
    background = values / k
    background[..., :3] = (values[..., :3] - (1 - k) * colour) / k
    background[..., 3] = np.clip(np.maximum(background[..., 3], clearest), 0, 1)
    background[..., :3] = np.clip(
        background[..., :3], 0, (1 - background[..., 3])[..., None]
    )
    return background


def _score(estimate, truth, mask):
    error = np.abs(estimate - truth)[mask] * 255
    return {
        "pixels": int(mask.sum()),
        "mean": round(float(error.mean()), 3),
        "meanColour": round(float(error[:, :3].mean()), 3),
        "meanAlpha": round(float(error[:, 3].mean()), 3),
        "p99Colour": round(float(np.quantile(error[:, :3], 0.99)), 2),
        "p99Alpha": round(float(np.quantile(error[:, 3], 0.99)), 2),
    }


def _confidence(expected):
    return np.clip(
        np.round(255 * (1 - np.asarray(expected) / CONFIDENCE_SPAN)), 0, 255
    ).astype(np.uint8)


def analyse(images, options=None):
    """Rebuild the shared background of same-size RGBA uint8 originals."""
    options = options or Options()
    if len(images) < 2:
        raise FamilyError("A family needs at least two images.")
    shape = images[0].shape
    if shape[-1:] != (4,) or any(
        image.shape != shape or image.dtype != np.uint8 for image in images
    ):
        raise FamilyError("Family images must be RGBA arrays of one size.")
    count = len(images)
    full = np.stack(images)
    normal = full.copy()
    normal[normal[..., 3] == 0] = 0
    differ_full = ~(normal == normal[:1]).all(axis=(0, 3))
    if not differ_full.any():
        raise FamilyError("The images are identical; there is no lettering to remove.")

    # Everything happens within a margin around the pixels where members differ.
    x, y, w, h = _bounds(differ_full)
    margin = options.ramp + 8
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(shape[1], x + w + margin), min(shape[0], y + h + margin)
    stack = normal[:, y0:y1, x0:x1]
    differ = differ_full[y0:y1, x0:x1]
    values = _premultiplied(stack)
    flat = np.ascontiguousarray(stack).view(np.uint32)[..., 0]

    def shifted(box):
        return [box[0] + x0, box[1] + y0, box[2], box[3]] if box else None

    # Over a translucent backdrop a member more opaque than the least opaque
    # one is lettered there.
    alpha = stack[..., 3]
    lightest = alpha.min(0)
    translucent = lightest < options.core_alpha
    heavier = (alpha > lightest) & (lightest < 255)
    # A provisional consensus where a clear plurality shares one exact value.
    winner, support, tie = _consensus(flat, ~heavier)
    quorum = np.where(translucent, 1, max(2, -(-count // 3)))
    provisional = differ & (support >= quorum) & ~tie
    reference = np.where(
        provisional[..., None],
        np.take_along_axis(values, winner[None, ..., None], 0)[0],
        np.median(values, axis=0),
    )
    deviation = np.abs(values - reference).max(-1) * 255
    # A member more transparent than the reference is less lettered, not more.
    covering = values[..., 3] < reference[..., 3] - 2 / 255
    opaque = (alpha >= options.core_alpha) & translucent
    strong = (
        ((deviation >= options.core_delta) & (covering | ~translucent)) | opaque
    ) & differ
    distance = np.stack([_distance(mask) for mask in strong])
    # Deviations within tolerance can't make untouched donors disagree, so
    # only larger ones show how far lettering reaches.
    deviant = provisional & (deviation > options.tolerance)
    reach = _reach(distance[deviant])
    touched = (distance <= reach) & differ

    # Exact consensus from the members whose lettering does not reach a pixel.
    donors = differ & ~touched & ~heavier
    # The donor farthest from its own lettering carries the least of its tails;
    # agreement is judged against the value most donors share.
    voted = np.take_along_axis(values, _consensus(flat, donors)[0][None, ..., None], 0)[
        0
    ]
    winner = np.where(donors, distance, -1).argmax(0)
    exact = differ & donors.any(0)
    chosen = np.take_along_axis(values, winner[None, ..., None], 0)[0]
    spread = np.where(donors, np.abs(values - voted).max(-1) * 255, 0)
    disagree = exact & (spread > options.tolerance).any(0)
    if disagree.sum() > max(8, exact.sum() // 2000) or spread.max() > options.conflict:
        culprits = {
            int(index): int((disagree & (spread[index] > options.tolerance)).sum())
            for index in range(count)
            if (disagree & (spread[index] > options.tolerance)).any()
        }
        raise FamilyError(
            "Members disagree where no lettering reaches them, so they do not share one background.",
            {
                "conflictPixels": int(disagree.sum()),
                "conflictBox": shifted(_box(disagree)),
                "membersOffConsensus": culprits,
                "maxDifference": round(float(spread.max()), 1),
            },
        )

    background = values[0].copy()
    background[exact] = chosen[exact]
    method = np.full(differ.shape, KEPT, np.uint8)
    method[exact] = CONSENSUS
    confidence = np.full(differ.shape, 255, np.uint8)
    confidence[exact & (donors.sum(0) == 1)] = _confidence(0.5)
    open_ = differ & ~exact
    lettered = touched | heavier

    # Fit the glow on lettered members over pixels the consensus gives.
    cores = [_components(mask, options.min_area) for mask in strong]
    glow = dict(options.glow) if options.glow else None
    if glow is None:
        rng = np.random.default_rng(0)
        samples = []
        for index in range(count):
            ys, xs = np.nonzero(
                exact
                & lettered[index]
                & (distance[index] >= options.donor_min_distance)
            )
            samples.append((index, ys, xs))
        total = sum(len(ys) for _, ys, _ in samples)
        if total >= 50:
            keep = min(1.0, 40_000 / total)
            thinned = []
            for index, ys, xs in samples:
                pick = rng.random(len(ys)) < keep
                ys, xs = ys[pick], xs[pick]
                thinned.append((index, ys, xs, values[index][ys, xs], chosen[ys, xs]))
            glow = _fit_glow(thinned, cores)

    # Leave one out: rebuild consensus pixels from their lettered members
    # alone, as open pixels must be rebuilt, where some member shows lettering.
    k = np.ones(distance.shape, np.float32)
    valid = np.zeros(distance.shape, bool)
    inverted = fused = None
    if glow:
        for index in range(count):
            k[index] = 1 - np.clip(
                glow["o"] * _glow_mask(cores[index], glow["sigma"], glow["r"]), 0, 1
            )
        valid = (
            differ
            & lettered
            & (distance >= options.donor_min_distance)
            & (k >= options.donor_min_k)
        )
        inverted = np.stack(
            [
                _invert(values[index], k[index], glow["colour"], 1 - lightest / 255)
                for index in range(count)
            ]
        )
        # Donors count less the weaker they are than the best one and fade in
        # away from their own strokes, so the estimate never switches abruptly
        # between donors whose small model errors differ.
        best_k = np.where(valid, k, 0).max(0)
        weight = np.where(valid, np.exp((k - best_k) / options.k_spread), 0)
        weight *= np.clip(distance / (2 * options.donor_min_distance), 0, 1)
        fused = (inverted * weight[..., None]).sum(0) / np.maximum(
            weight.sum(0), 1e-12
        )[..., None]
        pick = weight.argmax(0)
        shows = (
            np.take_along_axis(flat, pick[None], 0)[0]
            != np.take_along_axis(flat, winner[None], 0)[0]
        )
        scored = exact & valid.any(0) & shows
    else:
        scored = exact & lettered.any(0)
    validation = {}
    best_k = np.where(valid, k, 0).max(0)
    weak_k = options.weak_k
    if scored.any():
        filled = harmonic_fill(background, scored | open_)
        validation["filled"] = _score(filled, chosen, scored)
        if fused is not None:
            validation["inverted"] = _score(fused, chosen, scored)
            # Weaker donors stay inverted for as long as inversion still beats
            # the fill on consensus pixels with donors that weak.
            inverted_error = np.abs(fused - chosen).max(-1)
            filled_error = np.abs(filled - chosen).max(-1)
            for low in (0.9, 0.8, 0.7, 0.6, 0.5):
                band = scored & (best_k >= low) & (best_k < weak_k)
                if low < options.donor_min_k or band.sum() < 30:
                    break
                if inverted_error[band].mean() >= filled_error[band].mean():
                    break
                weak_k = low
            validation["weakK"] = weak_k
    inversion = (
        "inverted" in validation
        and validation["inverted"]["mean"] <= options.max_error
        and validation["inverted"]["mean"] <= validation["filled"]["mean"]
    )

    if inversion:
        assert inverted is not None and fused is not None
        expected = validation["inverted"]["mean"]
        good = open_ & valid.any(0) & (best_k >= weak_k)
        background[good] = fused[good]
        method[good] = INVERTED
        confidence[good] = _confidence(expected / np.maximum(best_k[good], 1e-6))
        weak = open_ & ~good
        donated = weak & valid.any(0)
        background[donated] = fused[donated]
        method[donated] = BLENDED
        confidence[donated] = _confidence(
            4 * expected / np.maximum(best_k[donated], 1e-6)
        )
        missing = weak & ~valid.any(0)
        method[missing] = FILLED
        confidence[missing] = 0
        if weak.any():
            background = harmonic_fill(background, missing)
            low = np.stack(
                [
                    cv2.GaussianBlur(
                        cv2.medianBlur(
                            np.clip(np.round(background[..., c] * 255), 0, 255).astype(
                                np.uint8
                            ),
                            5,
                        )
                        / 255,
                        (0, 0),
                        3,
                    )
                    for c in range(4)
                ],
                -1,
            )
            detail = background - low
            detail[missing] = 0
            # Bright detail in colour is a star; darkening is left-over lettering.
            peaks = cv2.dilate(
                (detail[..., :3].max(-1) > options.star_threshold).astype(np.uint8),
                np.ones((3, 3), np.uint8),
            )
            zone = (
                cv2.dilate(weak.astype(np.uint8), _ellipse(options.ramp)) > 0
            ) & open_
            smooth = harmonic_fill(low, zone)
            ramp = np.clip(1 - _distance(weak) / options.ramp, 0, 1)[..., None]
            blend = (
                low * (1 - ramp)
                + smooth * ramp
                + detail * (1 - ramp)
                + detail * (peaks[..., None] > 0) * ramp
            )
            background[zone] = blend[zone]
    elif open_.any():
        # A smooth backdrop, or no model that beats the fill.
        background = harmonic_fill(background, open_)
        method[open_] = FILLED
        confidence[open_] = (
            _confidence(validation["filled"]["mean"]) if "filled" in validation else 0
        )

    report = {
        "members": count,
        "differ": {"pixels": int(differ.sum()), "box": shifted(_box(differ))},
        "reach": reach,
        "consensus": {
            "pixels": int(exact.sum()),
            "singleDonor": int((exact & (donors.sum(0) == 1)).sum()),
            "disagreements": int(disagree.sum()),
        },
        "open": "inverted" if inversion else "filled",
        "glow": {
            key: round(value, 4) if isinstance(value, float) else value
            for key, value in glow.items()
        }
        if glow
        else None,
        "validation": validation,
        "confidenceScale": f"255 is exact; otherwise 255 * (1 - expected error / {CONFIDENCE_SPAN:g} levels)",
    }
    return Family(
        full=full,
        box=(x0, y0, x1, y1),
        stack=stack,
        differ=differ,
        distance=distance,
        donors=donors,
        exact=exact,
        winner=winner,
        background=background,
        method=method,
        confidence=confidence,
        report=report,
        options=options,
    )


def _full(family, crop, fill):
    """A crop-sized map placed into an image-sized one."""
    x0, y0, x1, y1 = family.box
    result = np.full(family.full.shape[1:3], fill, crop.dtype)
    result[y0:y1, x0:x1] = crop
    return result


def _cleanup(family, target, region):
    """Pixels to rebuild: where the target is no donor, or every differing
    pixel for the shared background, optionally within region."""
    cleanup = family.differ & (~family.donors[target] if target is not None else True)
    if region is not None:
        x0, y0, x1, y1 = family.box
        rx, ry, rw, rh = region
        limit = np.zeros(family.full.shape[1:3], bool)
        limit[max(0, ry) : max(0, ry + rh), max(0, rx) : max(0, rx + rw)] = True
        cleanup &= limit[y0:y1, x0:x1]
    return cleanup


def _render(family, base):
    """The family background as straight RGBA bytes; consensus pixels copy
    their donor's own bytes, hidden colour included."""
    crop = _straight(family.background, base)
    donor = np.take_along_axis(family.stack, family.winner[None, ..., None], 0)[0]
    crop[family.exact] = donor[family.exact]
    return crop


def solve(family, target=None, region=None):
    """Rebuild member target's background from an analysed family, or the
    family's shared background when target is None.

    region optionally limits cleanup to [x, y, width, height]; use it to
    protect a member's own artwork that is not lettering."""
    if target is not None and not 0 <= target < len(family.full):
        raise FamilyError("The target is not a member of the family.")
    member = target if target is not None else 0
    x0, y0, x1, y1 = family.box
    cleanup = _cleanup(family, target, region)
    pixels = family.full[member].copy()
    view = pixels[y0:y1, x0:x1]
    view[cleanup] = _render(family, family.stack[member])[cleanup]
    method = np.where(cleanup, family.method, KEPT)
    box = _box(cleanup)
    report = {
        **family.report,
        "target": target,
        "cleanup": {
            "pixels": int(cleanup.sum()),
            "box": [box[0] + x0, box[1] + y0, box[2], box[3]] if box else None,
        },
        "changed": int((pixels != family.full[member]).any(-1).sum()),
        "methods": {
            name: int((method == code).sum())
            for code, name in enumerate(METHODS)
            if code
        },
    }
    return Solution(
        pixels,
        _full(family, method.astype(np.uint8), KEPT),
        _full(family, np.where(cleanup, family.confidence, 255).astype(np.uint8), 255),
        report,
    )


def check(family, candidate, target=None):
    """Check a claimed text-free image against what an analysed family proves
    about its background: exact pixels must match, and darker or denser residue
    in the shape of a member's lettering is a ghost of that lettering."""
    if candidate.shape != family.full.shape[1:]:
        raise FamilyError("The candidate must be the family's size, as RGBA.")
    member = target if target is not None else 0
    x0, y0, x1, y1 = family.box
    normal = candidate.copy()
    normal[normal[..., 3] == 0] = 0
    agreed = np.ones(candidate.shape[:2], bool)
    agreed[y0:y1, x0:x1] = ~family.differ
    reference = family.full[member].copy()
    reference[reference[..., 3] == 0] = 0
    outside = int((normal != reference).any(-1)[agreed].sum())

    crop = _premultiplied(normal[y0:y1, x0:x1])
    residual = np.abs(crop - family.background).max(-1) * 255
    exact = family.exact
    open_ = family.differ & ~exact
    off = exact & (residual > family.options.tolerance)
    # Residue on a member's strokes beyond what surrounds them is a ghost of
    # that member's lettering; an area that is wrong all over shows in the
    # residuals instead.
    away = family.differ & (family.distance > 1).all(0)
    elsewhere = float(residual[away].mean()) if away.any() else 0.0
    ghosts = []
    for index, distance in enumerate(family.distance):
        strokes = family.differ & (distance <= 1)
        ring = away & (distance >= 3) & (distance <= 8)
        if strokes.sum() < 12 or ring.sum() < 12:
            continue
        level = float(residual[strokes].mean() - residual[ring].mean())
        if level > max(2.0, elsewhere):
            box = _box(strokes)
            ghosts.append(
                {
                    "member": index,
                    "strokeResidual": round(level, 2),
                    "box": [box[0] + x0, box[1] + y0, box[2], box[3]] if box else None,
                }
            )
    report = {
        **family.report,
        "target": target,
        "outsideMismatches": outside,
        "consensusMismatches": int(off.sum()),
        "consensusMaxDifference": round(float(residual[exact].max()), 1)
        if exact.any()
        else 0.0,
        "residualAwayFromLettering": round(elsewhere, 2),
        "openResidual": {
            "mean": round(float(residual[open_].mean()), 2) if open_.any() else 0.0,
            "p99": round(float(np.quantile(residual[open_], 0.99)), 2)
            if open_.any()
            else 0.0,
        },
        "ghosts": sorted(ghosts, key=lambda ghost: -ghost["strokeResidual"]),
    }
    report["ok"] = not outside and not off.any() and not ghosts
    return report, _full(
        family, np.clip(np.round(residual * 8), 0, 255).astype(np.uint8), 0
    )
