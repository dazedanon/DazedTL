#!/usr/bin/env python3
"""Find image variant families and rebuild their exact text-free backgrounds.

Members of a family are identical except where each carries its own lettering,
such as name cards on one backdrop or area banners on one shaded ellipse.
Wherever a member's lettering does not reach a pixel, that member holds the
true background, so rebuild a member's background here before inpainting it.

  python image_family.py families --project GAME [--asset img/pictures/Namecut12.png]
  python image_family.py solve --project GAME --asset img/pictures/Namecut12.png --output WORK/Namecut12_clean.png
  python image_family.py solve --image a.png --image b.png --image c.png --target a.png --output WORK/a_clean.png
  python image_family.py check --project GAME --asset img/pictures/Namecut12.png --candidate WORK/Namecut12_clean.png

Project commands read DazedTL's image inventory and every member's untranslated
original (its frozen copy, the Qt backup or the runtime file). Every command
prints JSON; errors print {"ok": false, ...} to stderr and exit 2, and a check
that finds problems exits 1.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


# Standalone helpers use the same bundled runtime as the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazedtl.compatibility.runtime import activate  # noqa: E402

activate()

INVENTORY = ".dazedtl/image_manager/guided/inventory.sqlite3"
EDITABLE = ".dazedtl/images"


def _print(payload: dict, *, stream=None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def _modules():
    import numpy as np
    from PIL import Image

    from dazedtl.compatibility.images import ImageCompatibility
    from dazedtl.images import background, families, inventory
    from dazedtl.translation.files import project_path

    return np, Image, ImageCompatibility(None), background, families, inventory, project_path


def _inventory(root: Path):
    path = root / INVENTORY
    if not path.is_file():
        raise ValueError(
            "This game has no image inventory yet. Scan its images in DazedTL first, or pass --image files."
        )
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        rows = {row["id"]: row for row in (json.loads(data) for (data,) in db.execute("SELECT data FROM assets"))}
        try:
            stored = {
                identity: (width, height, mode, data)
                for identity, width, height, mode, data in db.execute(
                    "SELECT id, width, height, mode, data FROM family_tiles"
                )
            }
        except sqlite3.OperationalError:
            stored = {}
    return rows, stored


def _key(root: Path, rows: dict):
    if not any(row.get("encrypted") for row in rows.values()):
        return None
    from util.rpgmaker_images import read_encryption_key

    try:
        return read_encryption_key(root)
    except (OSError, ValueError, KeyError):
        return None


def _original(root: Path, row: dict, key):
    """The relative path and PNG bytes of a row's untranslated original."""
    _np, _image, adapter, _background, families, _inventory_module, _path = _modules()
    relative, encrypted = families.original_file(root, row)
    return relative, adapter.source_bytes(root, {"runtime": relative, "encrypted": encrypted}, key)


def _families(root: Path, rows: dict, stored: dict, key):
    """Families among the inventory's originals, reusing stored signatures
    that still match their files."""
    _np, _image, _adapter, _background, families, inventory, project_path = _modules()
    sizes: dict = {}
    for row in rows.values():
        sizes[(row.get("width"), row.get("height"), row.get("mode"))] = sizes.get(
            (row.get("width"), row.get("height"), row.get("mode")), 0
        ) + 1
    entries = []
    for identity, row in rows.items():
        size = (row.get("width"), row.get("height"), row.get("mode"))
        if not row.get("width") or sizes[size] < 2:
            continue
        try:
            relative, _encrypted = families.original_file(root, row)
            known = row.get("original") or {}
            fresh = (known.get("path"), known.get("signature"), known.get("tiles")) == (
                relative,
                inventory.signature(project_path(root, relative)),
                families.VERSION,
            )
            entry = stored.get(identity) if fresh else None
            if entry is None:
                metadata, blob = inventory.png_signature(_original(root, row, key)[1])
                entry = (metadata["width"], metadata["height"], metadata["mode"], blob)
        except (OSError, ValueError, KeyError):
            continue
        if entry[3] is not None:
            entries.append((identity, *entry))
    return families.group(entries)


def _describe(root: Path, family: dict, rows: dict) -> dict:
    _np, _image, _adapter, _background, families, _inventory_module, _path = _modules()
    members = []
    for identity in family["members"]:
        row = rows[identity]
        try:
            original = families.original_file(root, row)[0]
        except ValueError:
            original = ""
        members.append({"id": identity, "original": original, "translated": families.translated(row)})
    return {**family, "members": members}


def _family_of(root: Path, asset: str):
    rows, stored = _inventory(root)
    if asset not in rows:
        raise ValueError(f"{asset} is not in this game's image inventory.")
    key = _key(root, rows)
    for family in _families(root, rows, stored, key):
        if asset in family["members"]:
            return family, rows, key
    raise ValueError(
        f"{asset} has no variant family: no same-size image shares its pixels outside a local region."
    )


def _decode(raw: bytes):
    np, Image, *_rest = _modules()
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != "PNG":
            raise ValueError("Family members must be PNG images.")
        return np.asarray(image.convert("RGBA")).copy(), image.mode


def _members(args):
    """Member labels, decoded RGBA originals, their modes and sources, and the
    target's index (None for the shared background)."""
    if args.project:
        root = args.project.resolve()
        family, rows, key = _family_of(root, args.asset)
        excluded = set(args.exclude or [])
        unknown = excluded - set(family["members"])
        if unknown:
            raise ValueError("Excluded images are not family members: " + ", ".join(sorted(unknown)))
        if args.asset in excluded:
            raise ValueError("The asset itself can't be excluded.")
        labels, images, modes, sources = [], [], [], []
        for identity in family["members"]:
            if identity in excluded:
                continue
            relative, raw = _original(root, rows[identity], key)
            pixels, mode = _decode(raw)
            labels.append(identity)
            images.append(pixels)
            modes.append(mode)
            sources.append(
                {
                    "id": identity,
                    "original": relative,
                    # The file's own hash, as recipes list their inputs, and
                    # the hash of the PNG inside an encrypted file.
                    "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
                    "pngSha256": hashlib.sha256(raw).hexdigest(),
                    "translated": _modules()[4].translated(rows[identity]),
                }
            )
        target = None if args.shared else labels.index(args.asset)
        return labels, images, modes, sources, target, family
    paths = [path.resolve() for path in args.image or []]
    if len(paths) < 2:
        raise ValueError("Pass a family as --project/--asset or as two or more --image files.")
    labels, images, modes, sources = [], [], [], []
    for path in paths:
        raw = path.read_bytes()
        pixels, mode = _decode(raw)
        labels.append(str(path))
        images.append(pixels)
        modes.append(mode)
        sources.append({"id": str(path), "original": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    if args.shared:
        target = None
    else:
        if not args.target:
            raise ValueError("Name the --target image, or pass --shared for the family's background.")
        if str(args.target.resolve()) not in labels:
            raise ValueError("The --target must be one of the --image files.")
        target = labels.index(str(args.target.resolve()))
    return labels, images, modes, sources, target, None


def _region(value: str | None):
    if not value:
        return None
    parts = [int(part) for part in value.split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError("--region is x,y,width,height in pixels.")
    return parts


def _guard(args, output: Path, inputs: list[str]) -> None:
    if args.project:
        editable = (args.project.resolve() / EDITABLE).resolve()
        if editable == output or editable in output.parents:
            raise ValueError(
                "Write rebuilt backgrounds outside the editable image folder; only finished translations belong there."
            )
    if str(output) in inputs:
        raise ValueError("The output must not overwrite a family member.")
    if output.exists() and not args.replace:
        raise ValueError(f"Output already exists (pass --replace to overwrite it): {output}")


def _save(Image, pixels, mode: str, output: Path) -> str:
    """Write RGBA pixels as an RGB or RGBA PNG atomically and return its hash."""
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").convert(mode).save(stream, format="PNG")
    data = stream.getvalue()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".png", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _options(args):
    background = _modules()[3]
    values = {}
    if args.tolerance is not None:
        values["tolerance"] = args.tolerance
    return background.Options(**values)


def _analyse(args, images, labels):
    """Analyse the family, naming members by ID or path in a conflict."""
    background = _modules()[3]
    try:
        return background.analyse(images, _options(args))
    except background.FamilyError as exc:
        culprits = exc.details.get("membersOffConsensus")
        if culprits:
            exc.details["membersOffConsensus"] = {labels[int(index)]: count for index, count in culprits.items()}
        raise


def _list(args) -> dict:
    root = args.project.resolve()
    rows, stored = _inventory(root)
    found = _families(root, rows, stored, _key(root, rows))
    if args.asset:
        found = [family for family in found if args.asset in family["members"]]
    return {"ok": True, "families": [_describe(root, family, rows) for family in found]}


def _solve(args) -> int:
    np, Image, _adapter, background, *_rest = _modules()
    labels, images, modes, sources, target, family = _members(args)
    mode = modes[target if target is not None else 0]
    if mode not in ("RGB", "RGBA"):
        raise ValueError(f"Rebuilt backgrounds are written as RGB or RGBA, not mode {mode}.")
    output = args.output.resolve()
    method_path = output.with_name(output.stem + ".method.png")
    confidence_path = output.with_name(output.stem + ".confidence.png")
    for path in (output, method_path, confidence_path):
        _guard(args, path, labels)
    solution = background.solve(_analyse(args, images, labels), target, _region(args.region))
    digest = _save(Image, solution.pixels, mode, output)
    palette = Image.fromarray(solution.method, mode="P")
    palette.putpalette([channel for colour in background.PALETTE for channel in colour])
    method_path.parent.mkdir(parents=True, exist_ok=True)
    palette.save(method_path, format="PNG")
    Image.fromarray(solution.confidence, mode="L").save(confidence_path, format="PNG")
    _print(
        {
            "ok": True,
            "output": str(output),
            "sha256": digest,
            "mode": mode,
            "family": family["id"] if family else None,
            "target": labels[target] if target is not None else None,
            "members": sources,
            "methodMap": {
                "path": str(method_path),
                "codes": dict(enumerate(background.METHODS)),
            },
            "confidenceMap": str(confidence_path),
            "report": solution.report,
        }
    )
    return 0


def _check(args) -> int:
    np, Image, _adapter, background, *_rest = _modules()
    labels, images, _modes, sources, target, family = _members(args)
    with Image.open(args.candidate) as candidate:
        pixels = np.asarray(candidate.convert("RGBA")).copy()
    report, residual = background.check(_analyse(args, images, labels), pixels, target)
    for ghost in report["ghosts"]:
        ghost["member"] = labels[ghost["member"]]
    if args.residual:
        path = args.residual.resolve()
        _guard(args, path, labels)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(residual, mode="L").save(path, format="PNG")
        report["residualMap"] = {"path": str(path), "scale": "8 x the largest premultiplied channel difference"}
    ok = report.pop("ok")
    _print(
        {
            "ok": ok,
            "candidate": str(args.candidate.resolve()),
            "family": family["id"] if family else None,
            "target": labels[target] if target is not None else None,
            "members": sources,
            "report": report,
        }
    )
    return 0 if ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("families", help="List the inventory's variant families as JSON")
    listing.add_argument("--project", required=True, type=Path, help="Game folder with a DazedTL image inventory")
    listing.add_argument("--asset", help="Only the family of this inventory image ID")

    for name, text in (
        ("solve", "Rebuild a member's text-free background from its family"),
        ("check", "Check a claimed text-free image against what the family proves"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--project", type=Path, help="Game folder with a DazedTL image inventory")
        command.add_argument("--asset", help="Inventory image ID of the family member")
        command.add_argument("--exclude", action="append", help="Leave this member out (repeatable)")
        command.add_argument("--image", action="append", type=Path, help="A family member PNG (repeatable)")
        command.add_argument("--target", type=Path, help="With --image: the member to rebuild")
        command.add_argument(
            "--shared", action="store_true", help="The family's shared background, without any member's lettering"
        )
        command.add_argument(
            "--tolerance", type=float, help="Levels untouched members may differ (default 2)"
        )
        if name == "solve":
            command.add_argument("--output", required=True, type=Path, help="Rebuilt background PNG")
            command.add_argument(
                "--region", help="Only rebuild within x,y,width,height, protecting a member's own artwork"
            )
            command.add_argument("--replace", action="store_true", help="Replace existing outputs")
        else:
            command.add_argument("--candidate", required=True, type=Path, help="The text-free PNG to check")
            command.add_argument("--residual", type=Path, help="Also write the residual map PNG here")
            command.add_argument("--replace", action="store_true", help="Replace an existing residual map")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "families":
            _print(_list(args))
            return 0
        if args.project and not args.asset:
            raise ValueError("Name the family member with --asset.")
        return _solve(args) if args.command == "solve" else _check(args)
    except Exception as exc:
        details = getattr(exc, "details", None)
        _print(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}", **({"details": details} if details else {})},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
