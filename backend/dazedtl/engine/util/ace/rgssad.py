"""Extracts RPG Maker's encrypted RGSS archives (Game.rgss3a and older).

Behaves like uuksu's RPGMakerDecrypter CLI (MIT,
https://github.com/uuksu/RPGMakerDecrypter) as DazedTL ran it: files are
written beside the archive under their archived paths, names drop the
characters Windows does not allow so they extract the same everywhere, and
files that already exist are left alone. Unlike it, ".." in a name never
leads outside the target folder.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable, Iterator
from pathlib import Path

HEADER = b"RGSSAD\0"
V1_KEY = 0xDEADCAFE
# Path.GetInvalidFileNameChars on Windows, which RPGMakerDecrypter removes.
_INVALID = re.compile(r'[\x00-\x1f"<>|:*?/\\]')

Log = Callable[[str], None]


class ArchiveError(ValueError):
    """The file is not an RGSS archive this module can read."""


def archives(root: Path) -> list[Path]:
    """The game's RGSS archives (Game.rgss3a and older), named in any case
    as Windows and the game itself accept."""
    return sorted(Path(root).glob("Game.rgss*", case_sensitive=False))


def _keystream(key: int, length: int) -> bytes:
    """The XOR stream for file data: the key's bytes, then key * 7 + 3 for
    every following 4 bytes, all modulo 2**32."""
    import numpy as np

    words = (length + 3) // 4
    if not words:
        return b""
    # k[i] = key * 7**i + 3 * (7**0 + ... + 7**(i-1)); uint32 arithmetic
    # wraps exactly as the archive's 32-bit key does.
    powers = np.empty(words, dtype=np.uint32)
    powers[0] = 1
    if words > 1:
        powers[1:] = np.cumprod(np.full(words - 1, 7, dtype=np.uint32), dtype=np.uint32)
    sums = np.zeros(words, dtype=np.uint32)
    if words > 1:
        sums[1:] = np.cumsum(powers[:-1], dtype=np.uint32)
    with np.errstate(over="ignore"):
        keys = powers * np.uint32(key) + sums * np.uint32(3)
    return keys.astype("<u4").tobytes()[:length]


def decrypt(data: bytes, key: int) -> bytes:
    import numpy as np

    stream = np.frombuffer(_keystream(key, len(data)), dtype=np.uint8)
    return np.bitwise_xor(np.frombuffer(data, dtype=np.uint8), stream).tobytes()


def _entries_v3(data: bytes) -> Iterator[tuple[str, int, int, int]]:
    key = (struct.unpack_from("<I", data, 8)[0] * 9 + 3) & 0xFFFFFFFF
    key_bytes = struct.pack("<I", key)
    position = 12
    while position + 16 <= len(data):
        offset, size, file_key, length = (
            value ^ key for value in struct.unpack_from("<4I", data, position)
        )
        position += 16
        if offset == 0:
            return
        raw = data[position : position + length]
        position += length
        name = bytes(byte ^ key_bytes[i % 4] for i, byte in enumerate(raw))
        yield name.decode("utf-8", "replace"), offset, size, file_key
    raise ArchiveError("The archive's file table is incomplete.")


def _entries_v1(data: bytes) -> Iterator[tuple[str, int, int, int]]:
    key = V1_KEY
    position = 8

    def advance(value: int) -> int:
        return (value * 7 + 3) & 0xFFFFFFFF

    while position < len(data):
        if position + 4 > len(data):
            raise ArchiveError("The archive's file table is incomplete.")
        length = struct.unpack_from("<I", data, position)[0] ^ key
        key = advance(key)
        position += 4
        name = bytearray()
        for byte in data[position : position + length]:
            name.append(byte ^ (key & 0xFF))
            key = advance(key)
        position += length
        size = struct.unpack_from("<I", data, position)[0] ^ key
        key = advance(key)
        position += 4
        yield name.decode("utf-8", "replace"), position, size, key
        position += size


def entries(data: bytes) -> list[tuple[str, int, int, int]]:
    """The archived files as (name, offset, size, key)."""
    if not data.startswith(HEADER) or len(data) < 8:
        raise ArchiveError("This is not an RGSS archive.")
    version = data[7]
    if version == 3:
        return list(_entries_v3(data))
    if version == 1:
        return list(_entries_v1(data))
    raise ArchiveError(f"RGSS archive version {version} is not supported.")


def safe_path(name: str) -> Path:
    """An archived name as a relative path, cleaned as RPGMakerDecrypter does."""
    parts = [_INVALID.sub("", part) for part in name.split("\\")]
    parts = [part for part in parts if part not in ("", ".", "..")]
    if not parts:
        raise ArchiveError("An archived file has no usable name: " + name)
    return Path(*parts)


def extract(
    archive: Path, out: Path | None = None, *, overwrite: bool = False, log: Log = print
) -> list[Path]:
    """Extracts every file; existing files are kept unless ``overwrite``."""
    data = Path(archive).read_bytes()
    target = Path(out) if out is not None else Path(archive).parent
    written = []
    skipped = 0
    for name, offset, size, key in entries(data):
        if offset + size > len(data):
            raise ArchiveError(
                "An archived file runs past the end of the archive: " + name
            )
        path = target / safe_path(name)
        if path.exists() and not overwrite:
            skipped += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(decrypt(data[offset : offset + size], key))
        written.append(path)
    log(
        f"Extracted {len(written)} files"
        + (f", kept {skipped} existing" if skipped else "")
    )
    return written
