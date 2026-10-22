"""Writes RGSS archives as RPG Maker does, for the Ace tests and the
testkit's encrypted Ace games (scripts/testkit/ace_game.py)."""

import struct

MASK = 0xFFFFFFFF


def stream(key, data):
    """RGSSAD file encryption, a byte at a time as RPGMakerDecrypter does."""
    out = bytearray()
    for index, byte in enumerate(data):
        if index and index % 4 == 0:
            key = (key * 7 + 3) & MASK
        out.append(byte ^ key.to_bytes(4, "little")[index % 4])
    return bytes(out)


def archive_v3(entries, seed):
    """A VX Ace Game.rgss3a holding `entries`, (archived name, bytes) pairs."""
    key = (seed * 9 + 3) & MASK
    key_bytes = key.to_bytes(4, "little")
    # A zero offset ends the table, as in shipped archives.
    offset = 12 + sum(16 + len(name.encode()) for name, _ in entries) + 4
    table, body = bytearray(), bytearray()
    for index, (name, data) in enumerate(entries):
        raw, file_key = name.encode(), 0x9E3779B9 + index
        values = (offset, len(data), file_key, len(raw))
        table += struct.pack("<4I", *(value ^ key for value in values))
        table += bytes(byte ^ key_bytes[i % 4] for i, byte in enumerate(raw))
        body += stream(file_key, data)
        offset += len(data)
    table += struct.pack("<I", key)
    return b"RGSSAD\0\x03" + struct.pack("<I", seed) + table + body


def archive_v1(entries):
    """An XP or VX Game.rgssad holding `entries`."""
    key, out = 0xDEADCAFE, bytearray(b"RGSSAD\0\x01")

    def step(value):
        return (value * 7 + 3) & MASK

    for name, data in entries:
        raw = name.encode()
        out += struct.pack("<I", len(raw) ^ key)
        key = step(key)
        for byte in raw:
            out.append(byte ^ (key & 0xFF))
            key = step(key)
        out += struct.pack("<I", len(data) ^ key)
        key = step(key)
        out += stream(key, data)
    return bytes(out)
