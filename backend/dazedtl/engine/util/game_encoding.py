"""Writing translated text in a game's own encoding, such as the Shift-JIS
(cp932) scripts of NScripter, KiriKiri and WOLF RPG games.

A letter the encoding has no code for loses only its accent where the
encoding has the letter without it, as ñ does in Shift-JIS. A letter or
digit it can't write at all, such as the Korean or simplified Chinese of a
translation into those languages, would be lost, so the file is not saved
with it and the message names its line. Other characters, such as the ♥ an
English translation may add, are left out as they always were.
"""

import unicodedata


class UnwritableText(ValueError):
    """Translated text the game's encoding can't write."""


def _writable(char: str, encoding: str) -> bool:
    try:
        char.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


def writable(lines, encoding: str, filename: str, first: int = 1) -> list[str]:
    """*lines* as *encoding* can write them: a letter it lacks without its
    accent where it has the bare letter. Raises UnwritableText naming the
    first line that holds a letter or digit it can't write either way,
    numbering *lines* from *first*."""
    written = []
    for number, line in enumerate(lines, start=first):
        if _writable(line, encoding):
            written.append(line)
            continue
        characters = []
        for char in line:
            if unicodedata.category(char)[0] in "LN" and not _writable(char, encoding):
                bare = "".join(
                    part
                    for part in unicodedata.normalize("NFKD", char)
                    if not unicodedata.combining(part)
                )
                if not bare or not _writable(bare, encoding):
                    raise UnwritableText(
                        f"{filename}: line {number} holds {char}, which the "
                        f"game's {encoding} text can't hold, so the file is not "
                        f"saved with it. Translate that line again or edit it: "
                        f"{line.strip()[:120]}"
                    )
                char = bare
            characters.append(char)
        written.append("".join(characters))
    return written


def check_line(lines, index: int, encoding: str, filename: str) -> None:
    """Raises UnwritableText when lines[index] holds a letter or digit
    *encoding* can't write. A writer checks each line as it sets it, so a
    file its game can't hold fails before its later requests are paid for,
    and checks the whole file with writable before it writes it."""
    writable(lines[index : index + 1], encoding, filename, index + 1)
