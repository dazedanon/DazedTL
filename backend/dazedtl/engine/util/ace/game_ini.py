"""Game.ini's Title, the window caption RGSS3's Game.exe shows.

The editor writes the database's game title there on every save; packing
does the same, so a translated game's window shows its translated title.
Game.exe reads the file with GetPrivateProfileStringW: a file without a
byte order mark is decoded with the player's ANSI code page, so the
Shift-JIS title of a Japanese game turns to mojibake on English Windows,
while a UTF-16 file reads the same on every Windows. A title of plain ASCII
reads the same either way, so only the Title line changes and every other
byte is kept; any other title turns the file into UTF-16.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

# The encoding the Japanese editor writes Game.ini in.
EDITOR_ENCODING = "cp932"
BOMS = {b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be"}


def find(root: Path) -> Path | None:
    """The game's Game.ini, in whatever case the folder spells it."""
    for path in Path(root).iterdir():
        if path.name.casefold() == "game.ini" and path.is_file():
            return path
    return None


def _title_line(lines: list[str]) -> tuple[int | None, int | None]:
    """The [Game] section header's index and its Title line's index."""
    header = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            if header is not None:
                break
            if stripped.casefold() == "[game]":
                header = index
        elif (
            header is not None
            and stripped.partition("=")[0].rstrip().casefold() == "title"
        ):
            return header, index
    return header, None


def _with_title(text: str, value: str) -> tuple[str, str | None]:
    """The file's text with Title set to ``value``, and the previous value."""
    # Only line feeds end ini lines; splitlines would also split at 0x85,
    # which ends many Shift-JIS characters.
    lines = re.split(r"(?<=\n)", text)
    if not lines[-1]:
        lines.pop()
    ending = "\r\n" if "\r\n" in text else "\n"
    header, index = _title_line(lines)
    if index is not None:
        line = lines[index]
        key, _, rest = line.partition("=")
        newline = rest[len(rest.rstrip("\r\n")) :]
        lines[index] = key + "=" + value + newline
        return "".join(lines), rest.rstrip("\r\n").strip()
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += ending
    if header is None:
        lines += ["[Game]" + ending, "Title=" + value + ending]
    else:
        lines.insert(header + 1, "Title=" + value + ending)
    return "".join(lines), None


def write_title(path: Path, title: object, log: Callable[[str], None] = print) -> bool:
    """Sets the ini's Title to the game title; False when it already shows
    that title or there is none to write."""
    if not isinstance(title, str):
        return False
    # An ini value is one line, and Windows trims the spaces around it.
    value = re.sub(r"[\x00-\x1f]+", " ", title).strip()
    if not value:
        return False
    data = path.read_bytes()
    codec = next((name for bom, name in BOMS.items() if data.startswith(bom)), None)
    if codec:
        text = data[2:].decode(codec)
        updated, previous = _with_title(text, value)
        if previous == value:
            return False
        output = data[:2] + updated.encode(codec)
    else:
        # Latin-1 maps every byte to one character, so lines split and join
        # without changing bytes Shift-JIS or any code page gave them.
        updated, previous = _with_title(data.decode("latin-1"), value)
        if previous is not None:
            raw = previous.encode("latin-1")
            try:
                if raw.decode(EDITOR_ENCODING) == value:
                    return False
            except UnicodeDecodeError:
                pass
        if value.isascii():
            output = updated.encode("latin-1")
        else:
            try:
                text = data.decode(EDITOR_ENCODING)
            except UnicodeDecodeError:
                log(
                    f"{path.name} keeps its title: its text is not in the editor's encoding"
                )
                return False
            output = b"\xff\xfe" + _with_title(text, value)[0].encode("utf-16-le")
    path.write_bytes(output)
    log(f"Set the window title in {path.name}")
    return True
