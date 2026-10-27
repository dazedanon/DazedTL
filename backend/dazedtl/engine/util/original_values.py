"""The source of a game value that keeps none of its own, read from the
game's original files.

A translated value keeps the text it was translated from in `_original`
where the engine records it, and the source-text rule reads it against that
(util/source_text `source_left`). Some values keep none: plugin settings,
custom data files, the strings of structured commands a translation left
unchanged, note labels, and map names translated before they kept one. In a
translation that shares the source's kanji, Japanese into Chinese, such a
value's hanzi read as Japanese left without its source.

The app records each game's original files and stages those a reader needs
in a folder laid out as the game is (`data/<file>`, `js/plugins.js`), a run
in its own `originals` folder (:data:`FOLDER`). A file is staged only where
the game's current one differs from it, and a folder without a file reads as
no source, as for a game whose originals are not recorded.

A value's source is the value at the same place in the original file where
it differs (:func:`source`): a value the same as its original may be text
never translated, so it reads with no source, every letter left. A message's
rows keep their source themselves and translation may change how many there
are, so :class:`Mirror` pairs only whole commands, and the rows of a command
whose row count is unchanged.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from util.rpgmaker_markers import plugin_list

# A run's staged originals, beside its files folder.
FOLDER = "originals"

# Rows that follow a command and belong to it: messages, scrolling text,
# comments and script lines. Translation may change how many there are.
_ROWS = {101: 401, 105: 405, 108: 408, 355: 655}
_ROW_CODES = frozenset(_ROWS.values())
# Commands translation may add or remove, so the commands either side still
# pair: a message's window, its rows, and the rows an engine empties.
_LOOSE = frozenset({101, 105, 108, -1}) | _ROW_CODES


def source(value: Any, original: Any) -> str | None:
    """The source *value* was translated from, its *original*, where it is
    text and differs; None where it keeps the original, which may be text
    never translated."""
    if isinstance(value, str) and isinstance(original, str) and value != original:
        return original
    return None


class Originals:
    """A folder of staged original files, each parsed once while a few are
    in use."""

    _KEPT = 8

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._documents: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def data(self, name: str) -> Any:
        """The original of the data file *name*, such as Map001.json, or
        None."""
        return self._read("data/" + name)

    def plugins(self) -> tuple[dict, ...] | None:
        """The original plugin list (js/plugins.js), or None."""
        path = self.folder / "js" / "plugins.js"
        return plugin_list(path) if path.is_file() else None

    def mirror(self, name: str, document: Any) -> Mirror | None:
        """The data file *name* as *document* has it now, paired with its
        original, or None without one."""
        original = self.data(name)
        return None if original is None else Mirror(document, original)

    def _read(self, relative: str) -> Any:
        with self._lock:
            if relative in self._documents:
                self._documents.move_to_end(relative)
                return self._documents[relative]
        try:
            document = json.loads(
                (self.folder / relative).read_text(encoding="utf-8-sig")
            )
        except (OSError, UnicodeDecodeError, ValueError):
            document = None
        with self._lock:
            self._documents[relative] = document
            while len(self._documents) > self._KEPT:
                self._documents.popitem(last=False)
        return document


class Mirror:
    """Each list and dict of a document paired with its counterpart in the
    original document, at the same place: by key, by position, and for an
    event command list by command (:func:`commands`)."""

    def __init__(self, document: Any, original: Any):
        # id -> (node, counterpart); the node is held so its id stays its own.
        self._pairs: dict[int, tuple[Any, Any]] = {}
        self._pair(document, original)

    def of(self, node: Any) -> Any:
        """The original of a list or dict of the document, or None."""
        pair = self._pairs.get(id(node))
        return pair[1] if pair is not None and pair[0] is node else None

    def source(self, node: Any, *path: Any) -> str | None:
        """The source of the value at *path* below *node* (:func:`source`),
        or None."""
        original = self.of(node)
        if original is None:
            return None
        return source(at(node, path), at(original, path))

    def _pair(self, node: Any, original: Any) -> None:
        if isinstance(node, dict) and isinstance(original, dict):
            self._pairs[id(node)] = (node, original)
            for key, child in node.items():
                if key != "_original" and key in original:
                    self._pair(child, original[key])
        elif isinstance(node, list) and isinstance(original, list):
            self._pairs[id(node)] = (node, original)
            pairs = (
                commands(node, original)
                if _is_command_list(node)
                else zip(range(len(node)), range(len(original)))
            )
            for index, other in pairs:
                self._pair(node[index], original[other])


class Mirrors:
    """The mirrors of the documents a run has open, from any thread."""

    def __init__(self):
        self._open: list[Mirror] = []
        self._lock = threading.Lock()

    @contextmanager
    def opened(self, mirror: Mirror | None) -> Iterator[None]:
        if mirror is None:
            yield
            return
        with self._lock:
            self._open.append(mirror)
        try:
            yield
        finally:
            with self._lock:
                self._open.remove(mirror)

    def mirrors(self) -> tuple[Mirror, ...]:
        """The open documents' mirrors."""
        return tuple(self._open)

    def source(self, node: Any, *path: Any) -> str | None:
        """The source an open document's original gives the value at *path*
        below *node*, or None."""
        for mirror in self.mirrors():
            if mirror.of(node) is not None:
                return mirror.source(node, *path)
        return None


def at(node: Any, path: tuple) -> Any:
    """The value at *path* below *node*, keys and list positions, or None."""
    for part in path:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            return None
    return node


def _is_command_list(value: list) -> bool:
    return any(isinstance(item, dict) and "code" in item for item in value)


def _key(command: Any) -> tuple:
    """What translation leaves of a command: its code, indent and every
    parameter but text."""
    if not isinstance(command, dict):
        return (None,)
    parameters = command.get("parameters")
    parameters = parameters if isinstance(parameters, list) else []
    return (
        command.get("code"),
        command.get("indent"),
        len(parameters),
        tuple(
            value
            for value in parameters
            if not isinstance(value, (str, list, dict))
        ),
    )


def _units(commands: list) -> list[tuple[int, int]]:
    """Each command with the rows that follow it, as (first, end)."""
    units = []
    index = 0
    while index < len(commands):
        code = commands[index].get("code") if isinstance(commands[index], dict) else None
        end = index + 1
        row = _ROWS.get(code)
        while (
            row is not None
            and end < len(commands)
            and isinstance(commands[end], dict)
            and commands[end].get("code") == row
        ):
            end += 1
        units.append((index, end))
        index = end
    return units


def commands(current: list, original: list) -> list[tuple[int, int]]:
    """The commands of an event command list paired with those of its
    original, as (position, original position).

    Where translation changed no command, each pairs with the one at its
    position. Otherwise commands pair in order where they match, skipping a
    message window, comment or row either side holds alone, as fitting adds;
    rows pair only where their command keeps as many, and pairing stops at
    the first other command that does not match."""
    if len(current) == len(original) and all(
        _key(a) == _key(b) for a, b in zip(current, original)
    ):
        return list(zip(range(len(current)), range(len(original))))
    pairs = []
    mine, theirs = _units(current), _units(original)
    left = right = 0
    while left < len(mine) and right < len(theirs):
        (start, end), (other, other_end) = mine[left], theirs[right]
        code = _key(current[start])[0]
        if _key(current[start]) == _key(original[other]):
            if code in _ROW_CODES:
                # A row apart from its command, such as one a translation
                # added: its source is its command's.
                pass
            elif end - start == other_end - other:
                pairs.extend(zip(range(start, end), range(other, other_end)))
            else:
                pairs.append((start, other))
            left += 1
            right += 1
        elif code in _LOOSE:
            left += 1
        elif _key(original[other])[0] in _LOOSE:
            right += 1
        else:
            break
    return pairs
