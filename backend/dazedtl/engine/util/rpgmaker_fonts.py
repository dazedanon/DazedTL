"""The font an RPG Maker MV/MZ game draws its text in, and the characters of
its text that font lacks.

MZ names its main font in System.json (``advanced.mainFontFilename``) and MV
in ``fonts/gamefont.css``; both bundle it under ``fonts/``, so the main text
draws alike on every computer. A character the font lacks draws from the
fallback fonts (MZ's ``advanced.fallbackFonts``, or the browser's own), whose
widths vary by operating system; the layout check lists those characters.

Only the font's character map is read: TrueType and OpenType files,
collections and WOFF. WOFF2 needs Brotli, which DazedTL does not ship.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from bisect import bisect_left, bisect_right
from collections import Counter
from pathlib import Path
from typing import Any

from util import rpgmaker_rewrap
from util.source_text import letters

# The most characters a layout check lists, the most frequent first.
LISTED = 20
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""")


class FontUnreadable(ValueError):
    """The font file is not one whose character map DazedTL reads."""


def _tables(raw: bytes) -> dict[bytes, bytes]:
    """The font's tables by tag, decompressed."""
    tag = raw[:4]
    if tag == b"wOF2":
        raise FontUnreadable("it is WOFF2, which DazedTL cannot read")
    if tag == b"wOFF":
        (count,) = struct.unpack_from(">H", raw, 12)
        tables = {}
        for index in range(count):
            name, offset, packed, size, _check = struct.unpack_from(
                ">4sIIII", raw, 44 + 20 * index
            )
            body = raw[offset : offset + packed]
            tables[name] = zlib.decompress(body) if packed < size else body
        return tables
    # A collection: its first font, which a CSS url() draws.
    base = struct.unpack_from(">I", raw, 12)[0] if tag == b"ttcf" else 0
    if raw[base : base + 4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise FontUnreadable("it is not a TrueType, OpenType or WOFF font")
    (count,) = struct.unpack_from(">H", raw, base + 4)
    tables = {}
    for index in range(count):
        name, _check, offset, size = struct.unpack_from(
            ">4sIII", raw, base + 12 + 16 * index
        )
        tables[name] = raw[offset : offset + size]
    return tables


class Cmap:
    """A font's character map: which characters it draws a glyph for."""

    def __init__(self, raw: bytes):
        try:
            table = _tables(raw).get(b"cmap")
            if table is None:
                raise FontUnreadable("it has no character map")
            self.subtables = [
                subtable
                for subtable in self._read(table)
                if subtable is not None
            ]
        except FontUnreadable:
            raise
        except (struct.error, zlib.error, IndexError, ValueError) as error:
            raise FontUnreadable(f"it is damaged ({error})") from None
        if not self.subtables:
            raise FontUnreadable("it has no Unicode character map")

    @staticmethod
    def _read(table: bytes):
        _version, count = struct.unpack_from(">HH", table, 0)
        for index in range(count):
            platform, encoding, offset = struct.unpack_from(">HHI", table, 4 + 8 * index)
            # Unicode maps: platform 0, and Windows' BMP (1) and full (10) ones.
            if not (platform == 0 or (platform == 3 and encoding in (1, 10))):
                continue
            (form,) = struct.unpack_from(">H", table, offset)
            if form == 4:
                yield _Format4(table, offset)
            elif form == 12:
                yield _Format12(table, offset)

    def covers(self, character: str) -> bool:
        """Whether the font draws *character*; a damaged entry reads as
        drawn, so the layout check lists only what the font surely lacks."""
        code = ord(character)
        try:
            return any(subtable.glyph(code) for subtable in self.subtables)
        except (struct.error, IndexError):
            return True


class _Format4:
    """A segment map of the Basic Multilingual Plane."""

    def __init__(self, table: bytes, offset: int):
        (doubled,) = struct.unpack_from(">H", table, offset + 6)
        count = doubled // 2
        ends = offset + 14
        self.ends = struct.unpack_from(f">{count}H", table, ends)
        self.starts = struct.unpack_from(f">{count}H", table, ends + doubled + 2)
        self.deltas = struct.unpack_from(f">{count}h", table, ends + 2 * doubled + 2)
        self.ranges_at = ends + 3 * doubled + 2
        self.ranges = struct.unpack_from(f">{count}H", table, self.ranges_at)
        self.table = table

    def glyph(self, code: int) -> int:
        # Segments are sorted by their end; the last one ends at 0xFFFF.
        index = bisect_left(self.ends, code)
        if index == len(self.ends) or code < self.starts[index]:
            return 0
        if not self.ranges[index]:
            return (code + self.deltas[index]) & 0xFFFF
        at = self.ranges_at + 2 * index + self.ranges[index]
        (glyph,) = struct.unpack_from(">H", self.table, at + 2 * (code - self.starts[index]))
        return (glyph + self.deltas[index]) & 0xFFFF if glyph else 0


class _Format12:
    """Groups of consecutive characters, any plane."""

    def __init__(self, table: bytes, offset: int):
        (count,) = struct.unpack_from(">I", table, offset + 12)
        groups = sorted(
            struct.unpack_from(">III", table, offset + 16 + 12 * index)
            for index in range(count)
        )
        self.starts = [start for start, _end, _first in groups]
        self.groups = groups

    def glyph(self, code: int) -> int:
        index = bisect_right(self.starts, code) - 1
        if index < 0:
            return 0
        start, end, first = self.groups[index]
        return first + code - start if code <= end else 0


def main_font(data: Path) -> tuple[Path | None, str]:
    """The game's main font file, or None, and the fallback fonts that draw
    what it lacks. *data* is the game's data folder, beside its fonts."""
    fonts = data.parent / "fonts"
    try:
        system = json.loads((data / "System.json").read_text(encoding="utf-8-sig"))
        advanced = system.get("advanced") if isinstance(system, dict) else None
    except (OSError, ValueError):
        advanced = None
    if isinstance(advanced, dict) and isinstance(advanced.get("mainFontFilename"), str):
        fallback = advanced.get("fallbackFonts")
        name = advanced["mainFontFilename"].strip()
        return (fonts / name if name else None), fallback if isinstance(fallback, str) else ""
    try:
        css = (fonts / "gamefont.css").read_text(encoding="utf-8-sig")
    except OSError:
        return None, ""
    found = _CSS_URL.search(css)
    return (fonts / found.group(1) if found else None), ""


def fallback_glyphs(data: str | Path, source: str | None = None) -> dict[str, Any]:
    """The characters the game's text draws that its main font lacks, the
    most frequent first, with how often each appears and the cells the
    fitter counts it as (see :func:`util.rpgmaker_rewrap.visible_width`).
    Letters of the *source* language, the active source by default, are left
    out, as translation replaces them; a target's own, such as the kana and
    kanji of a Japanese translation of an English game, are listed."""
    data = Path(data)
    path, fallback = main_font(data)
    result: dict[str, Any] = {"fallbackFonts": fallback} if fallback else {}
    if path is None:
        return {**result, "unread": "The game names no font file."}
    try:
        result["font"] = path.resolve().relative_to(data.parent.resolve()).as_posix()
    except ValueError:
        return {**result, "unread": "The game names a font outside its folder."}
    try:
        cmap = Cmap(path.read_bytes())
    except OSError:
        return {**result, "unread": "The game's font file is missing."}
    except FontUnreadable as error:
        return {**result, "unread": f"The game's font could not be read: {error}."}
    source_letter = letters(source)
    counts: Counter[str] = Counter()
    for file in sorted(data.glob("*.json")):
        try:
            document = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        counts.update(rpgmaker_rewrap.drawn_characters(document, file.name))
    lacking = [
        (character, count)
        for character, count in counts.items()
        if character.isprintable()
        and not character.isspace()
        and not source_letter.match(character)
        and rpgmaker_rewrap.visible_width(character)
        and not cmap.covers(character)
    ]
    lacking.sort(key=lambda row: (-row[1], row[0]))
    result["glyphs"] = [
        {
            "character": character,
            "code": f"U+{ord(character):04X}",
            "count": count,
            "counted": rpgmaker_rewrap.visible_width(character),
        }
        for character, count in lacking[:LISTED]
    ]
    if len(lacking) > LISTED:
        result["more"] = len(lacking) - LISTED
    return result
