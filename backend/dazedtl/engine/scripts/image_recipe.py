#!/usr/bin/env python3
"""Fit, render and check text recipes for families of translated images.

A recipe records how an accepted translated image drew its lettering - font
file and hash, size, placement rule and effect stack - so the next image in
the family is one command instead of a reverse-engineering session.

  fit     recover a recipe from an accepted image, its clean base and the exact text
  render  draw new text onto another image's clean base with a recipe
  check   re-render the accepted image from its recipe and report the error

Every command prints JSON. Errors go to stderr as JSON with exit code 2; a
check over its error limit exits 1.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

# The fit multiplies matrices a few columns wide and a hundred thousand rows
# long, thousands of times. A threaded BLAS spends more waking its pool for
# each than the product costs, on every core, so it runs on one unless the
# caller says otherwise. Set before anything imports NumPy.
for _variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Standalone helpers use the same bundled runtime and shared resources as the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazedtl.compatibility.runtime import activate

activate()

NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")
#: Mean error per channel, in levels of 255, above which ``check`` fails. The
#: HOLLOWWALD title cards fitted to 3.7 and were indistinguishable at 3x zoom.
CHECK_LIMIT = 6.0
#: Chunks that describe pixel data and so come from the new encoding, never
#: from the template.
PIXEL_CHUNKS = {b"IHDR", b"IDAT", b"IEND"}


def _print(payload: dict, *, stream=None) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )


def _runtime():
    try:
        import numpy as np
        from PIL import Image
        from util.imagetools import fitter, recipe
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "The image editor resources are unavailable in this Python "
            f"({sys.executable}): {exc}. Open Edit text in DazedTL and accept "
            "the resource download before using the recipe tool."
        ) from exc
    return np, Image, fitter, recipe


# --------------------------------------------------------------------- input


def _read(path: Path):
    """``(pixels, mode)``: RGB stays RGB and everything else becomes RGBA."""
    np, Image, _fitter, _recipe = _runtime()
    if not path.is_file():
        raise ValueError(f"Image does not exist: {path}")
    with Image.open(path) as image:
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError(f"{path} has more than one frame")
        mode = "RGB" if image.mode == "RGB" else "RGBA"
        return np.asarray(image.convert(mode), dtype=np.uint8).copy(), image.mode


def _base(args):
    """The clean base: given, or rebuilt from the original and its cleanup mask."""
    np, Image, fitter, _recipe = _runtime()
    if args.base and (args.original or args.mask):
        raise ValueError("Give either --base or --original with --mask, not both")
    if args.base:
        pixels, _mode = _read(args.base)
        return pixels, {"base": args.base}
    if not (args.original and args.mask):
        raise ValueError("Give the clean base (--base) or the original and its cleanup mask")
    original, _mode = _read(args.original)
    with Image.open(args.mask) as mask:
        hole = np.asarray(mask.convert("L"), dtype=np.uint8) > 0
    return (
        fitter.base_from_mask(original, hole, args.inpaint),
        {"original": args.original, "mask": args.mask},
    )


def _pairs(values: list[str] | None, flag: str) -> list[tuple[str, str]]:
    pairs = []
    for value in values or []:
        name, separator, rest = value.partition("=")
        if not separator or not NAME.fullmatch(name):
            raise ValueError(f"{flag} takes NAME=VALUE, with a name of letters, digits, - or _")
        pairs.append((name, rest))
    return pairs


def _per_slot(values: list[str] | None, flag: str, names: list[str]) -> tuple[str | None, dict]:
    """A default for every slot, and per-slot overrides written ``NAME=VALUE``."""
    default, specific = None, {}
    for value in values or []:
        name, separator, rest = value.partition("=")
        if separator and name in names:
            specific[name] = rest
        elif separator and NAME.fullmatch(name):
            raise ValueError(f"{flag} names {name!r}, which is not a --slot")
        else:
            default = value
    return default, specific


def _texts(args, names: list[str] | None = None) -> dict[str, str]:
    texts: dict[str, str] = {}
    for name, text in _pairs(args.slot, "--slot"):
        if name in texts:
            raise ValueError(f"Slot {name!r} is given twice")
        if names is not None and name not in names:
            raise ValueError(f"The recipe has no slot {name!r}; it has {', '.join(names)}")
        texts[name] = text
    if not texts:
        raise ValueError("Give at least one --slot NAME=TEXT")
    return texts


def _sizes(args, names: list[str]) -> dict[str, float]:
    _default, sizes = _per_slot(args.size, "--size", names)
    out = {}
    for name, value in sizes.items():
        try:
            out[name] = float(value)
        except ValueError:
            raise ValueError(f"--size {name}= takes a number of points") from None
    return out


# -------------------------------------------------------------------- output


def _chunks(data: bytes):
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        yield kind, data[offset : offset + 12 + length]
        offset += 12 + length


def _like(fresh: bytes, template: bytes) -> bytes:
    """*fresh*'s pixels inside *template*'s chunks: colour profile, gamma, text.

    An ICC profile or a gamma chunk changes how the same bytes look, so a
    candidate that drops the ones its original carried is a different picture
    in the game even where every pixel matches.
    """
    old = list(_chunks(template))
    new = dict(_chunks(fresh))
    if next((chunk for kind, chunk in old if kind == b"IHDR"), None) != new[b"IHDR"]:
        raise ValueError(
            "The template's PNG header differs from the output's (size, bit depth "
            "or colour type), so its chunks cannot be kept; drop --like or "
            "convert the base to the template's mode first"
        )
    pixels = b"".join(chunk for kind, chunk in _chunks(fresh) if kind == b"IDAT")
    out, wrote = [fresh[:8]], False
    for kind, chunk in old:
        if kind == b"IDAT":
            if not wrote:
                out.append(pixels)
                wrote = True
            continue
        out.append(chunk)
    return b"".join(out)


def _write_png(pixels, mode: str, output: Path, *, like: Path | None, replace: bool) -> None:
    _np, Image, _fitter, _recipe = _runtime()
    if output.exists() and not replace:
        raise ValueError(f"Output already exists (pass --replace to overwrite it): {output}")
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode=mode).save(buffer, format="PNG")
    data = buffer.getvalue()
    if like is not None:
        data = _like(data, like.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".png", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _diff_image(np, candidate, accepted):
    """The disagreement, four times as loud, as an opaque picture to look at."""
    def premultiplied(array):
        pixels = array.astype(np.float32)
        if pixels.shape[2] == 3:
            return pixels
        return pixels[:, :, :3] * pixels[:, :, 3:4] / 255.0

    loud = np.abs(premultiplied(candidate) - premultiplied(accepted)) * 4
    return np.clip(np.round(loud), 0, 255).astype(np.uint8)


def _guard(output: Path, *inputs) -> None:
    resolved = output.resolve()
    if any(path is not None and Path(path).resolve() == resolved for path in inputs):
        raise ValueError("The output must not overwrite one of the inputs")


# ------------------------------------------------------------------ commands


def _fit(args) -> dict:
    _np, _Image, fitter, recipe = _runtime()
    from util.imagetools.geometry import Box

    texts = _texts(args)
    names = list(texts)
    font, fonts = _per_slot(args.font, "--font", names)
    align, aligns = _per_slot(args.align, "--align", names)
    by, bys = _per_slot(args.by, "--by", names)
    _default, sizes = _per_slot(args.size, "--size", names)
    _default, regions = _per_slot(args.near, "--near", names)
    groups: dict[str, str] = {}
    for value in args.same_style or []:
        members = [name.strip() for name in value.split(",") if name.strip()]
        if len(members) < 2 or any(name not in names for name in members):
            raise ValueError("--same-style takes two or more --slot names, comma-separated")
        for name in members:
            groups[name] = members[0]
    requests = []
    for name in names:
        path = fonts.get(name, font)
        if not path:
            raise ValueError(f"Give the font for slot {name!r} with --font")
        near = None
        if name in regions:
            try:
                x, y, w, h = (int(part) for part in regions[name].split(","))
            except ValueError:
                raise ValueError("--near takes NAME=X,Y,WIDTH,HEIGHT") from None
            near = Box.from_xywh(x, y, w, h)
        requests.append(
            fitter.Request(
                name=name,
                text=texts[name],
                font=str(Path(path).resolve()),
                align=aligns.get(name, align or "center"),
                by=bys.get(name, by or "advance"),
                size=float(sizes[name]) if name in sizes else None,
                near=near,
                group=groups.get(name, ""),
            )
        )
    if args.recipe.exists() and not args.replace:
        raise ValueError(f"Recipe already exists (pass --replace to overwrite it): {args.recipe}")
    accepted, _mode = _read(args.accepted)
    base, sources = _base(args)
    effects = tuple(part.strip() for part in args.effects.split(",") if part.strip())
    result = fitter.fit(
        accepted, base, requests, supersample=args.supersample, allowed=effects
    )
    folder = args.recipe.resolve().parent
    result.sources = {
        "accepted": {
            "path": recipe.portable_path(str(args.accepted), folder),
            "sha256": recipe.file_sha256(args.accepted),
        },
        **{
            key: {
                "path": recipe.portable_path(str(path), folder),
                "sha256": recipe.file_sha256(path),
            }
            for key, path in sources.items()
        },
    }
    if "mask" in sources:
        result.sources["inpaint"] = args.inpaint
    result.save(args.recipe)
    return {
        "ok": True,
        "recipe": str(args.recipe.resolve()),
        "error": result.fit["error"],
        "slots": [_describe(slot) for slot in result.slots],
    }


def _describe(slot) -> dict:
    data = slot.to_dict()
    return {
        "name": slot.name,
        "size": data["size"],
        "placement": data["placement"],
        "style": data["style"],
        "correlation": slot.fit.get("correlation"),
    }


def _render(args) -> dict:
    _np, _Image, _fitter, recipe = _runtime()
    loaded = recipe.Recipe.load(args.recipe)
    names = [slot.name for slot in loaded.slots]
    texts = _texts(args, names)
    missing = [name for name in names if name not in texts]
    if missing and not args.partial:
        raise ValueError(
            f"No text for slot(s) {', '.join(missing)}; give each a --slot, or "
            "pass --partial to leave them undrawn"
        )
    _guard(args.output, args.base, args.like, args.recipe)
    base, _mode = _read(args.base)
    pixels, placed = recipe.render(loaded, base, texts, _sizes(args, names))
    mode = "RGB" if pixels.shape[2] == 3 else "RGBA"
    _write_png(pixels, mode, args.output, like=args.like, replace=args.replace)
    return {
        "ok": True,
        "output": str(args.output.resolve()),
        "skipped": missing,
        "slots": [
            {
                "name": item.slot.name,
                "text": item.text,
                "size": recipe.tidy(item.size),
                "origin": [recipe.tidy(value) for value in item.origin],
                "ink_xywh": item.ink.as_xywh(),
                "reach_xywh": item.canvas.as_xywh(),
            }
            for item in placed
        ],
    }


def _check(args) -> dict:
    np, _Image, _fitter, recipe = _runtime()
    loaded = recipe.Recipe.load(args.recipe)
    accepted, _mode = _read(args.accepted)
    base, _sources = _base(args)
    texts = {slot.name: slot.text for slot in loaded.slots}
    pixels, placed = recipe.render(loaded, base, texts)
    error = recipe.difference(pixels, accepted, base, [item.canvas for item in placed])
    limit = CHECK_LIMIT if args.max_error is None else args.max_error
    if args.diff is not None:
        _guard(args.diff, args.accepted, args.base, args.original, args.mask, args.recipe)
        _write_png(_diff_image(np, pixels, accepted), "RGB", args.diff, like=None, replace=True)
    return {
        "ok": error["mean"] <= limit,
        "error": error,
        "limit": limit,
        "recipe_fit_error": loaded.fit.get("error"),
        "diff": str(args.diff.resolve()) if args.diff is not None else "",
    }


# -------------------------------------------------------------------- parser


def _sources(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", type=Path, help="Clean text-free base PNG")
    parser.add_argument("--original", type=Path, help="Original PNG, when there is no clean base")
    parser.add_argument("--mask", type=Path, help="Cleanup mask PNG for --original (nonzero = erased)")
    parser.add_argument(
        "--inpaint", default="telea",
        help="Reconstruction for --original/--mask (default telea)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fit = commands.add_parser("fit", help="Recover a recipe from an accepted translated image")
    fit.add_argument("--accepted", required=True, type=Path, help="Accepted translated PNG")
    _sources(fit)
    fit.add_argument(
        "--slot", action="append", required=True, metavar="NAME=TEXT",
        help="A string exactly as drawn in the accepted image; repeat per string",
    )
    fit.add_argument(
        "--font", action="append", required=True, metavar="[NAME=]FONT",
        help="Font file for every slot, or for one slot as NAME=FONT",
    )
    fit.add_argument("--align", action="append", metavar="[NAME=]left|center|right",
                     help="Alignment rule to record (default center)")
    fit.add_argument("--by", action="append", metavar="[NAME=]advance|ink",
                     help="What alignment measures (default advance, Pillow's getlength)")
    fit.add_argument("--size", action="append", metavar="NAME=POINTS", help="Size hint, if the search needs one")
    fit.add_argument("--near", action="append", metavar="NAME=X,Y,W,H", help="Where to look, if the search needs it")
    fit.add_argument("--same-style", action="append", metavar="NAME,NAME",
                     help="Slots that share one effect stack, such as the lines of one message")
    fit.add_argument("--supersample", type=int, default=1,
                     help="Draw at N times the size and box-filter down, as canvas-drawn game text is (default 1)")
    fit.add_argument("--effects", default="outline,shadow,glow",
                     help="Effects the fit may use, comma-separated (default outline,shadow,glow)")
    fit.add_argument("--recipe", required=True, type=Path, help="Recipe JSON to write")
    fit.add_argument("--replace", action="store_true", help="Replace an existing recipe")

    render = commands.add_parser("render", help="Draw new text onto a clean base with a recipe")
    render.add_argument("--recipe", required=True, type=Path)
    render.add_argument("--base", required=True, type=Path, help="Clean text-free base PNG")
    render.add_argument("--slot", action="append", required=True, metavar="NAME=TEXT",
                        help="Text for a recipe slot; repeat per slot")
    render.add_argument("--size", action="append", metavar="NAME=POINTS",
                        help="Draw a slot at another size, keeping its baseline and alignment")
    render.add_argument("--partial", action="store_true", help="Allow slots without text, left undrawn")
    render.add_argument("--like", type=Path,
                        help="Keep this PNG's ancillary chunks (colour profile, gamma, text)")
    render.add_argument("--output", required=True, type=Path, help="Candidate PNG to write")
    render.add_argument("--replace", action="store_true", help="Replace an existing output")

    check = commands.add_parser("check", help="Re-render the accepted image from its recipe and report the error")
    check.add_argument("--recipe", required=True, type=Path)
    check.add_argument("--accepted", required=True, type=Path, help="The accepted translated PNG")
    _sources(check)
    check.add_argument("--max-error", type=float,
                       help=f"Fail above this mean error per channel, in levels of 255 (default {CHECK_LIMIT})")
    check.add_argument("--diff", type=Path, help="Also write the difference, four times as loud")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = {"fit": _fit, "render": _render, "check": _check}[args.command](args)
    except Exception as exc:
        _print(
            {"error": f"{type(exc).__name__}: {exc}", "ok": False},
            stream=sys.stderr,
        )
        return 2
    _print(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
