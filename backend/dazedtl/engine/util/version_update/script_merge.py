"""Carries a translation onto a new release's plugins.

RPG Maker's `plugins.js` registers every plugin with its settings, and one
setting often holds a whole list as JSON in a string, such as every quest.
Git merges the file by line, so a release that adds a quest conflicts with
the translated list and replaces it whole, and plugins the translation
registered lose their registrations where the release registers its own.
`merge_plugins` merges the registry by plugin and by value instead (see
json_merge), in the release's layout.

Plugin scripts merge by Git's lines. `restore_lines` then gives back each
translated line the release left as it was, where the translation only
rewrote text in quotes; code the translation rewrote stays with Git's merge.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from util.rpgmaker_plugin_registry import PluginRegistryError, entry_texts, with_entries

from .json_merge import merge_value

# Text in quotes on one line, as JavaScript writes strings.
_QUOTED = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')


def is_plugin_registry(path: str) -> bool:
    return PurePosixPath(path).name.casefold() == "plugins.js"


def merge_plugins(base: bytes, translated: bytes, official: bytes) -> str | None:
    """The release's registry with the translation of every setting it left
    unchanged and the plugins only the translation registered, or None when
    a file is not a registry or the release's is in neither of RPG Maker's
    layouts, so Git's line merge decides."""
    try:
        release = official.decode("utf-8")
        old, translation, new = (
            entry_texts(raw.decode("utf-8")) for raw in (base, translated, official)
        )
    except (UnicodeDecodeError, PluginRegistryError):
        return None
    old_names, translation_names, new_names = (
        [json.dumps(value.get("name")) for value, _ in entries] for entries in (old, translation, new)
    )
    new_to_old = {new: old for old, new in _same(old_names, new_names).items()}
    old_to_translation = _same(old_names, translation_names)

    # The merged entries, whether each is the release's text, and where each
    # translation entry went.
    entries, own, placed, released = [], [], {}, {}
    for index, (value, raw) in enumerate(new):
        source = new_to_old.get(index)
        counterpart = old_to_translation.get(source) if source is not None else None
        if source is None:
            # A plugin the release added is its own, even where the
            # translation registered one of the same name.
            released.setdefault(new_names[index], []).append(len(entries))
            entries.append(raw)
            own.append(True)
        elif counterpart is None:
            # The translation removed the plugin; it stays removed unless the
            # release changed it.
            if old[source][0] != value:
                entries.append(raw)
                own.append(True)
        else:
            placed[counterpart] = len(entries)
            entry = _merged_entry(old[source], translation[counterpart], new[index])
            entries.append(entry)
            own.append(entry == raw)
    added = sorted(set(range(len(translation))) - set(old_to_translation.values()))
    for index in added:
        # A plugin both registered stays where the release put it.
        if released.get(translation_names[index]):
            placed[index] = released[translation_names[index]].pop(0)
    for index in added:
        if index in placed:
            continue
        # A plugin only the translation registered goes back after the one it
        # followed, so it still loads in the same order.
        position = max((at for counterpart, at in placed.items() if counterpart < index), default=-1) + 1
        placed = {counterpart: at + (at >= position) for counterpart, at in placed.items()}
        placed[index] = position
        entries.insert(position, translation[index][1])
        own.insert(position, False)
    merged = with_entries(release, entries)
    if merged is None:
        # RPG Maker's own layout holds each entry on one line.
        merged = with_entries(release, [raw if mine else _one_line(raw) for raw, mine in zip(entries, own)])
    try:
        return merged if merged is not None and len(entry_texts(merged)) == len(entries) else None
    except PluginRegistryError:
        return None


def _merged_entry(old, translation, new) -> str:
    if old[0] == new[0]:
        # The release left the plugin as it was: the translation's stays.
        return translation[1]
    if old[0] == translation[0]:
        return new[1]
    try:
        # Escapes only JavaScript accepts, such as \V, cannot be written back
        # from parsed values; the release's entry wins there.
        values = [json.loads(raw) for _, raw in (old, translation, new)]
    except ValueError:
        return new[1]
    merged = merge_value(*values)
    return new[1] if merged is None else _compact(merged)


def _compact(value) -> str:
    """An entry as RPG Maker writes it; the canonical layout reformats it."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _one_line(raw: str) -> str:
    try:
        return _compact(json.loads(raw))
    except ValueError:
        return raw


def _same(old: list, new: list) -> dict[int, int]:
    """Each item of `old` that `new` holds unchanged, by position."""
    pairs = {}
    for operation, start, end, new_start, _new_end in SequenceMatcher(None, old, new).get_opcodes():
        if operation == "equal":
            pairs.update(zip(range(start, end), range(new_start, new_start + end - start)))
    return pairs


def paired_lines(old: list[str], new: list[str]) -> dict[int, int]:
    """Each line of `old` with its counterpart in `new`: lines kept, and
    lines replaced one for one."""
    pairs = {}
    for operation, start, end, new_start, new_end in SequenceMatcher(None, old, new).get_opcodes():
        if operation == "equal" or operation == "replace" and end - start == new_end - new_start:
            pairs.update(zip(range(start, end), range(new_start, new_end)))
    return pairs


def quoted_text(line: str) -> list[str]:
    """The strings in quotes on one line of a script."""
    return _QUOTED.findall(line)


def text_only(source: str, translation: str) -> bool:
    """Whether a translated line differs from its source only in quoted text."""
    return source != translation and _QUOTED.sub('""', source) == _QUOTED.sub('""', translation)


def restore_lines(base: bytes, translated: bytes, official: bytes, merged: bytes) -> bytes:
    """`merged` with each translated line back where the release left the
    line as it was, for a file Git merged by line with the release winning."""
    if base == translated:
        return merged
    try:
        old, translation, new, result = (
            raw.decode("utf-8").splitlines(keepends=True) for raw in (base, translated, official, merged)
        )
    except UnicodeDecodeError:
        return merged
    translated_lines = {
        line: translation[counterpart]
        for line, counterpart in paired_lines(old, translation).items()
        if text_only(old[line], translation[counterpart])
    }
    if not translated_lines:
        return merged
    sources = {new_line: line for line, new_line in _same(old, new).items()}
    restored = False
    for line, new_line in _same(result, new).items():
        source = sources.get(new_line)
        if source in translated_lines:
            result[line] = translated_lines[source]
            restored = True
    return "".join(result).encode("utf-8") if restored else merged
