"""The Ace preparation actions a workflow runs on a game folder."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from util import rpgmaker_script_strings as script_strings

from . import game_ini, rgssad, rv2json

ACTIONS = ("ace_decrypt", "ace_extract", "ace_pack")
# A text variable's (code 122) operand as earlier versions translated it in
# VX Ace data: MV/MZ's template literal, maybe ending in ";". Ruby runs a
# string between backticks as a shell command, so the game froze there.
_TEMPLATE_OPERAND = re.compile(r"`((?:\\.|[^`\\])*)`(;?)", re.S)
# Where Set up keeps an encrypted game's original archive. The game reads
# its extracted files only while no archive sits beside Game.exe.
ORIGINALS = Path(".dazedtl/ace")


def original_archive(root: Path) -> Path | None:
    """The archive an encrypted game came with, once Set up set it aside."""
    folder = Path(root) / ORIGINALS
    found = rgssad.archives(folder) if folder.is_dir() else []
    return found[0] if found else None


def run(root: Path, action: str, log: Callable[[str], None] = print) -> list[Path]:
    """Extracts the encrypted archive (ace_decrypt), converts Data to ace_json
    (ace_extract, extracting an encrypted game first and setting its archive
    aside) or packs ace_json back into Data (ace_pack), and returns the native
    files packing wrote.

    Packing updates Data in place without RV2JSON's Data/backups copies: the
    workflow already keeps the original, and a copy inside Data would ship
    with the game. Like the editor, it also writes the game title into
    Game.ini, which the window caption shows, and returns Game.ini whether or
    not its title changed. Text variables translated as template literals go
    into Data as Ruby strings (see :func:`ruby_text_variables`).
    """
    root = Path(root)
    if action == "ace_decrypt":
        archives = rgssad.archives(root)
        if not archives:
            raise ValueError("No Game.rgss archive needs extraction.")
        log("Extracting " + archives[0].name)
        rgssad.extract(archives[0], root, log=log)
    elif action == "ace_extract":
        archives = rgssad.archives(root)
        if archives:
            # Files already extracted are kept; missing ones are added.
            log("Extracting " + archives[0].name)
            rgssad.extract(archives[0], root, log=log)
        log("Converting Data to ace_json")
        rv2json.create(root, log=log)
        if archives:
            target = root / ORIGINALS / archives[0].name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(archives[0], target)
            log(
                f"Moved {archives[0].name} to {ORIGINALS.as_posix()}, so the game reads its extracted files"
            )
    elif action == "ace_pack":
        log("Packing ace_json into Data")
        written = rv2json.update(
            root, skip_backup=True, edit=ruby_text_variables(log), log=log
        )
        ini = game_ini.find(root)
        system = root / "ace_json/System.json"
        if ini is None:
            return written
        if system.is_file():
            title = json.loads(system.read_text(encoding="utf-8-sig")).get("gameTitle")
            game_ini.write_title(ini, title, log)
        return [*written, ini]
    else:
        raise ValueError("Unknown Ace action: " + action)
    return []


def ruby_text_variables(log: Callable[[str], None]) -> Callable[[str, Any], None]:
    """Packing's edit of a data file's JSON (see rv2json.update): each text
    variable translated as a template literal, which VX Ace runs as a shell
    command, becomes the Ruby string that holds the same text. Only
    translated commands, which keep their _original, change, never one the
    game wrote; one whose literal runs code or holds a character code stays
    as it is and is reported. The JSON itself stays as translation wrote it."""

    def edit(name: str, document: Any) -> None:
        changed = kept = 0
        for command in _translated_variables(document):
            parameters = command.get("parameters")
            if not (
                isinstance(parameters, list)
                and len(parameters) > 4
                and isinstance(parameters[4], str)
            ):
                continue
            match = _TEMPLATE_OPERAND.fullmatch(parameters[4])
            if not match:
                continue
            inside = script_strings.ruby_from_template(match[1])
            if inside is None:
                kept += 1
                continue
            parameters[4] = f'"{inside}"{match[2]}'
            changed += 1
        if changed:
            log(f"{name}: packed {changed} text variable(s) as Ruby strings")
        if kept:
            log(
                f"{name}: {kept} text variable(s) run JavaScript, which VX Ace "
                "cannot, and stay as they are; translate them again"
            )

    return edit


def _translated_variables(value: Any) -> Iterator[dict]:
    """Every translated code 122 command in a data file's JSON."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("code") == 122 and "_original" in item:
                yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def patch_archive(root: Path, target: Path, tracked: Iterable[str]) -> str | None:
    """Rebuilds an encrypted game's archive with its current files at
    ``target`` and returns the archive's name, or None for a game that came
    unencrypted. Tracked files in the archive's folders are added to it, since
    the game reads those folders only from the archive."""
    original = original_archive(root)
    if original is None:
        return None
    _header, rows = rgssad.table(original)
    folders = {
        raw.decode("utf-8", "replace").split("\\")[0].casefold() for raw, _ in rows
    }
    extra = [
        name.replace("/", "\\")
        for name in sorted(tracked)
        if "/" in name and name.split("/")[0].casefold() in folders
    ]
    rgssad.rebuild(original, target, Path(root), extra=extra)
    return original.name
