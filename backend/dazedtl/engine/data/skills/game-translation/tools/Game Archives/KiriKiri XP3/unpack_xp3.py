#!/usr/bin/env python3
"""Unpack a standard KiriKiri XP3 archive.

A file it can't read, such as one a game-specific cipher encrypts, is named
at the end and left out; the rest are extracted, and the exit code is 2."""
import argparse
import shutil
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath


XP3_MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"


class XP3Error(Exception):
    pass


def read_u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def read_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def read_u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def read_index(fp):
    fp.seek(0)
    if fp.read(len(XP3_MAGIC)) != XP3_MAGIC:
        raise XP3Error("missing XP3 magic")

    index_offset = struct.unpack("<Q", fp.read(8))[0]
    fp.seek(index_offset)
    flag = fp.read(1)[0]

    # This archive uses an XP3 continuation marker at the header index pointer:
    # 0x80, zero, real_index_offset. Follow it before reading the zlib index.
    if flag & 0x80:
        first_offset = struct.unpack("<Q", fp.read(8))[0]
        next_offset = struct.unpack("<Q", fp.read(8))[0]
        if next_offset:
            index_offset = next_offset
        elif first_offset:
            index_offset = first_offset
        else:
            raise XP3Error("XP3 continuation marker has no target offset")
        fp.seek(index_offset)
        flag = fp.read(1)[0]

    method = flag & 0x7F
    if method == 0:
        size = struct.unpack("<Q", fp.read(8))[0]
        return fp.read(size)
    if method == 1:
        compressed_size = struct.unpack("<Q", fp.read(8))[0]
        original_size = struct.unpack("<Q", fp.read(8))[0]
        data = zlib.decompress(fp.read(compressed_size))
        if len(data) != original_size:
            raise XP3Error(
                f"index size mismatch: got {len(data)}, expected {original_size}"
            )
        return data
    raise XP3Error(f"unsupported XP3 index method {method}")


def parse_index(index):
    records = []
    pos = 0
    while pos < len(index):
        tag = index[pos : pos + 4]
        size = read_u64(index, pos + 4)
        body = index[pos + 12 : pos + 12 + size]
        if tag != b"File":
            # KiriKiri skips other chunks too, such as a name hash table.
            pos += 12 + size
            continue

        record = {"name": None, "flags": 0, "original_size": 0, "archive_size": 0, "segments": [], "adler32": None}
        sub_pos = 0
        while sub_pos < len(body):
            sub_tag = body[sub_pos : sub_pos + 4]
            sub_size = read_u64(body, sub_pos + 4)
            sub = body[sub_pos + 12 : sub_pos + 12 + sub_size]

            if sub_tag == b"info":
                record["flags"] = read_u32(sub, 0)
                record["original_size"] = read_u64(sub, 4)
                record["archive_size"] = read_u64(sub, 12)
                name_len = read_u16(sub, 20)
                record["name"] = sub[22 : 22 + name_len * 2].decode("utf-16le")
            elif sub_tag == b"segm":
                if len(sub) % 28:
                    raise XP3Error(f"bad segment table length for {record['name']}")
                for seg_pos in range(0, len(sub), 28):
                    record["segments"].append(
                        {
                            "flags": read_u32(sub, seg_pos),
                            "offset": read_u64(sub, seg_pos + 4),
                            "original_size": read_u64(sub, seg_pos + 12),
                            "archive_size": read_u64(sub, seg_pos + 20),
                        }
                    )
            elif sub_tag == b"adlr":
                record["adler32"] = read_u32(sub, 0)

            sub_pos += 12 + sub_size

        if not record["name"]:
            raise XP3Error(f"file record at 0x{pos:x} has no name")
        records.append(record)
        pos += 12 + size
    if index and not records:
        # A game's own index format, such as an encrypted or hashed one.
        raise XP3Error("the archive index lists no files this tool can read")
    return records


def output_path(root, xp3_name):
    normalized = xp3_name.replace("\\", "/")
    rel = PurePosixPath(normalized)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise XP3Error(f"unsafe archive path {xp3_name!r}")
    return root.joinpath(*rel.parts)


def member_chunks(src, record):
    """The bytes of one archive member, in chunks; raises XP3Error when the
    member can't be read, after the chunk that shows it."""
    checksum = 1
    total = 0
    for segment in record["segments"]:
        src.seek(segment["offset"])
        raw_size = segment["archive_size"]
        original_size = segment["original_size"]
        flags = segment["flags"]

        if flags == 0:
            remaining = raw_size
            while remaining:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise XP3Error("unexpected end of archive")
                checksum = zlib.adler32(chunk, checksum)
                total += len(chunk)
                remaining -= len(chunk)
                yield chunk
            if raw_size != original_size:
                raise XP3Error("raw segment size mismatch")
        elif flags == 1:
            try:
                data = zlib.decompress(src.read(raw_size))
            except zlib.error as exc:
                raise XP3Error("compressed segment does not decompress (encrypted?)") from exc
            if len(data) != original_size:
                raise XP3Error("compressed segment size mismatch")
            checksum = zlib.adler32(data, checksum)
            total += len(data)
            yield data
        else:
            raise XP3Error(f"unsupported segment flags {flags} (encrypted?)")

    if total != record["original_size"]:
        raise XP3Error("file size mismatch")
    if record["adler32"] is not None and (checksum & 0xFFFFFFFF) != record["adler32"]:
        raise XP3Error("checksum mismatch: encrypted by the game or damaged")


def extract_file(src, dst, record, overwrite):
    """Extract one member; a member it can't read leaves no file behind."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        raise XP3Error(f"output exists: {dst}")
    try:
        with dst.open("wb") as out:
            for chunk in member_chunks(src, record):
                out.write(chunk)
    except XP3Error:
        dst.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Unpack a standard Kirikiri XP3 archive.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    failed = []
    with args.archive.open("rb") as src:
        records = parse_index(read_index(src))
        print(f"records: {len(records)}")
        print(f"output: {args.output}")
        for index, record in enumerate(records, 1):
            try:
                extract_file(src, output_path(args.output, record["name"]), record, args.overwrite)
            except XP3Error as exc:
                failed.append((record["name"], str(exc)))
            if index % 100 == 0 or index == len(records):
                print(f"read {index}/{len(records)}", flush=True)
    print(f"extracted: {len(records) - len(failed)}")
    if failed:
        print(f"could not read {len(failed)} files:", file=sys.stderr)
        for name, reason in failed:
            print(f"  {name}: {reason}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except XP3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
