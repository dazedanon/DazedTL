#!/usr/bin/env python3
"""Pack files into an unencrypted KiriKiri XP3 archive, such as a patch.xp3.

Each file is stored under its path relative to --root, or under its bare name
with --flat: KAG's Initialize.tjs adds `patch.xp3>` to the storages KiriKiri
finds files in by name alone, so a patch archive lists its files flat. Check
the game's Initialize.tjs or startup.tjs for the patch names it loads.

The archive is written beside the output and read back before it replaces it,
so a failed pack leaves no archive behind.
"""
import argparse
import os
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unpack_xp3 import XP3_MAGIC, XP3Error, member_chunks, parse_index, read_index  # noqa: E402


def chunk(tag, body):
    return tag + struct.pack("<Q", len(body)) + body


def members(root, files, flat, output):
    """(archive name, path) of each file, refusing names that collide; the
    output archive is never one of them, so packing again leaves its old
    self out."""
    root, output = root.resolve(), output.resolve()
    paths = [root / name for name in files] if files else sorted(
        path for path in root.rglob("*") if path.is_file() and path.resolve() != output
    )
    found, seen = [], {}
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise XP3Error(f"not a file: {path}")
        if path == output:
            raise XP3Error(f"the output archive can't pack itself: {path}")
        try:
            relative = PurePosixPath(path.relative_to(root).as_posix())
        except ValueError:
            raise XP3Error(f"outside --root: {path}") from None
        name = relative.name if flat else relative.as_posix()
        # KiriKiri matches names without regard to case.
        if name.casefold() in seen:
            raise XP3Error(f"{seen[name.casefold()]} and {relative} share the name {name}")
        seen[name.casefold()] = relative
        found.append((name, path))
    if not found:
        raise XP3Error("no files to pack")
    return found


def write(out, entries):
    index = bytearray()
    out.write(XP3_MAGIC + struct.pack("<Q", 0))
    for name, path in entries:
        data = path.read_bytes()
        packed = zlib.compress(data, 9)
        compressed = len(packed) < len(data)
        stored = packed if compressed else data
        offset = out.tell()
        out.write(stored)
        encoded = name.encode("utf-16le")
        info = struct.pack("<IQQH", 0, len(data), len(stored), len(encoded) // 2) + encoded
        segment = struct.pack("<IQQQ", int(compressed), offset, len(data), len(stored))
        adler = struct.pack("<I", zlib.adler32(data))
        index += chunk(
            b"File", chunk(b"info", info) + chunk(b"segm", segment) + chunk(b"adlr", adler)
        )
    position = out.tell()
    packed = zlib.compress(bytes(index), 9)
    out.write(b"\x01" + struct.pack("<QQ", len(packed), len(index)) + packed)
    out.seek(len(XP3_MAGIC))
    out.write(struct.pack("<Q", position))


def verify(path, entries):
    with path.open("rb") as src:
        records = parse_index(read_index(src))
        if [record["name"] for record in records] != [name for name, _ in entries]:
            raise XP3Error("the packed index does not list the files packed")
        for record, (_name, source) in zip(records, entries):
            if b"".join(member_chunks(src, record)) != source.read_bytes():
                raise XP3Error(f"{record['name']} does not read back as packed")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="the archive to write, such as patch.xp3")
    parser.add_argument("--root", type=Path, required=True, help="the folder the files are in")
    parser.add_argument(
        "files", nargs="*", help="files to pack, relative to --root (default: every file in it)"
    )
    parser.add_argument("--flat", action="store_true", help="store each file under its bare name")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing archive")
    args = parser.parse_args()

    if args.output.exists() and not args.overwrite:
        raise XP3Error(f"output exists: {args.output}")
    entries = members(args.root, args.files, args.flat, args.output)
    temporary = args.output.with_name(args.output.name + ".packing")
    try:
        with temporary.open("wb") as out:
            write(out, entries)
        verify(temporary, entries)
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"packed {len(entries)} files into {args.output}")


if __name__ == "__main__":
    try:
        main()
    except XP3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
