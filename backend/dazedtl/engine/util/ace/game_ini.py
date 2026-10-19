"""Game.ini's Title, the window caption RGSS3's Game.exe shows.

The editor writes the database's game title there on every save; packing
does the same, so a translated game's window shows its translated title.
Game.exe reads the file with GetPrivateProfileStringW: a file without a
byte order mark is decoded with the player's ANSI code page, so the
Shift-JIS title of a Japanese game turns to mojibake on English Windows.
mkxp-z, which plays Ace games on Linux, the Steam Deck and Android
(JoiPlay), reads the file as bytes: in UTF-16 it finds no [Game] section,
loses Scripts= and starts the game as RPG Maker XP. Only plain ASCII reads
the same everywhere, so packing writes the title in ASCII (é as e, ～ as
~, ♥ left out) and changes only the Title line, keeping every other byte;
a file that is already UTF-16 keeps its encoding and the whole title.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

# The encoding the Japanese editor writes Game.ini in.
EDITOR_ENCODING = "cp932"
BOMS = {b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be"}


# Punctuation with a plain ASCII form that compatibility decomposition, which
# turns ～ into ~ and … into ..., leaves alone.
_ASCII_PUNCTUATION = str.maketrans(
    {
        "\u00b7": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u301c": "~",
        "\u30fb": " ",
    }
)


def ascii_title(title: str) -> str:
    """*title* in plain ASCII, which every reader of Game.ini decodes alike:
    accented letters lose their accents, full-width forms and typographic
    punctuation take their ASCII ones, and other characters, such as ♥,
    become spaces."""
    text = unicodedata.normalize("NFKD", title).translate(_ASCII_PUNCTUATION)
    text = "".join(
        character if character.isascii() else " "
        for character in text
        if not unicodedata.combining(character)
    )
    return " ".join(text.split())


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
        text = data.decode("latin-1")
        previous = _with_title(text, value)[1]
        if previous is not None:
            try:
                # The title the editor wrote: the game is untranslated.
                if previous.encode("latin-1").decode(EDITOR_ENCODING) == value:
                    return False
            except UnicodeDecodeError:
                pass
        value = ascii_title(value)
        if not value:
            log(f"{path.name} keeps its title: it has no letters in ASCII")
            return False
        updated, previous = _with_title(text, value)
        if previous == value:
            return False
        output = updated.encode("latin-1")
    path.write_bytes(output)
    log(f"Set the window title in {path.name}")
    return True
