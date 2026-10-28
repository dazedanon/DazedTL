"""Tiny TrueType fonts for tests that read a game font's character map."""

import struct


def segments(*ranges):
    """A format 4 character map subtable drawing each inclusive (start, end)
    range of the Basic Multilingual Plane."""
    ends = [end for _start, end in ranges] + [0xFFFF]
    starts = [start for start, _end in ranges] + [0xFFFF]
    deltas = [(1 - start) & 0xFFFF for start, _end in ranges] + [1]
    count = len(ends)
    body = struct.pack(
        f">{count}HH{count}H{count}H{count}H", *ends, 0, *starts, *deltas, *[0] * count
    )
    return struct.pack(">HHHHHHH", 4, 14 + len(body), 0, 2 * count, 0, 0, 0) + body


def truetype(*ranges):
    """A TrueType font holding only a character map that draws each
    inclusive (start, end) range of the Basic Multilingual Plane."""
    # One Windows Unicode BMP map.
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + segments(*ranges)
    return (
        struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
        + struct.pack(">4sIII", b"cmap", 0, 28, len(cmap))
        + cmap
    )
