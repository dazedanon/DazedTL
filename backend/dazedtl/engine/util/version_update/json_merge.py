"""Carries a translation onto a new official release by its data, not its lines.

Git merges formatted JSON line by line, and game data repeats the same lines
in every command, so a command the release inserts can line up against a
translated one and conflict; resolving that by hunk then drops the
translation. Here the old and new releases line up by value instead: whatever
the new release left as it was keeps its translation, and whatever it changed
comes from the release untranslated, to be translated again.

Translations record their source beside the text they changed, under
``_original``. A record keeps those notes for the fields whose translation
carries over; a field whose translation the release changes comes back whole
from the release, so no note names text that is no longer there.

Plugin settings and plugin command arguments hold JSON inside strings, such
as a whole quest list in one value; those merge by the values inside too, so
a release that adds a quest keeps the translation of the quests it left.
"""

from __future__ import annotations

import copy
import json
from difflib import SequenceMatcher

ORIGINAL = "_original"
_MISSING = object()
# The key under which expand() holds a string's JSON.
_NESTED = "\0json"


class _Unsafe(Exception):
    """The translation changed the data's shape, so values cannot line up."""


def expand(value):
    """The value with each string that holds a JSON object or array opened up,
    when writing that JSON back gives the same text; collapse() writes it back."""
    if isinstance(value, str):
        if value[:1] in ("[", "{"):
            try:
                inner = json.loads(value)
            except ValueError:
                return value
            if isinstance(inner, (dict, list)) and _compact(inner) == value:
                return {_NESTED: expand(inner)}
        return value
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item) for item in value]
    return value


def collapse(value):
    if isinstance(value, dict):
        if _nested(value):
            return _compact(collapse(value[_NESTED]))
        return {key: collapse(item) for key, item in value.items()}
    if isinstance(value, list):
        return [collapse(item) for item in value]
    return value


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _nested(value) -> bool:
    return isinstance(value, dict) and _NESTED in value


def merge_value(base, translation, release):
    """The release's value with the translation of everything it left
    unchanged, or None when the translation changed the value's shape."""
    try:
        return collapse(_merge(expand(base), expand(translation), expand(release)))
    except _Unsafe:
        return None


def merge_json(base: bytes, translated: bytes, official: bytes) -> str | None:
    """The new release with the translation of everything it left unchanged,
    or None when the files cannot merge by value: not JSON, a translation
    that added or removed data, or a release file not in the prepared format.

    Prepared game data is formatted one value per line, and the merged file
    keeps that format; a file an engine keeps in its own layout is left to
    Git's line merge rather than reformatted.
    """
    try:
        release = official.decode("utf-8")
        old, translation, new = (
            json.loads(raw.decode("utf-8-sig")) for raw in (base, translated, official)
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if release.rstrip("\n") != _format(new):
        return None
    merged = merge_value(old, translation, new)
    if merged is None:
        return None
    return _format(merged) + release[len(release.rstrip("\n")) :]


def _format(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=4)


def _plain(value):
    """A value without translation notes, as the releases hold it."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if key != ORIGINAL}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _merge(old, translation, new):
    if _nested(translation) != _nested(old):
        # The translation wrote the JSON text another way, so the values
        # inside cannot line up; the text merges as one value.
        return copy.deepcopy(translation if _plain(old) == _plain(new) else new)
    plain_old, plain_translation = _plain(old), _plain(translation)
    if type(plain_translation) is not type(plain_old):
        raise _Unsafe
    if plain_old == _plain(new):
        # The release left it as it was: the translation's stays.
        return copy.deepcopy(translation)
    if plain_translation == plain_old:
        return copy.deepcopy(new)
    if isinstance(old, dict) and isinstance(new, dict):
        return _merge_record(old, translation, new)
    if isinstance(old, list) and isinstance(new, list):
        return _merge_list(old, translation, new)
    # A value the release changed is the release's, translated or not.
    return copy.deepcopy(new)


def _merge_record(old, translation, new):
    if translation.keys() - {ORIGINAL} != old.keys():
        raise _Unsafe
    merged = {
        key: _merge(old[key], translation[key], value) if key in old else copy.deepcopy(value)
        for key, value in new.items()
        if key != ORIGINAL
    }
    notes = translation.get(ORIGINAL, _MISSING)
    if notes is _MISSING:
        return merged
    translated = [key for key in old if _plain(translation[key]) != _plain(old[key])]
    dropped = {
        key
        for key in translated
        if key not in merged or _plain(merged[key]) != _plain(translation[key])
    }
    for key in dropped:
        if key in new:
            merged[key] = copy.deepcopy(new[key])
    if not dropped:
        merged[ORIGINAL] = copy.deepcopy(notes)
    elif isinstance(notes, dict):
        # Notes keyed by field keep the fields whose translation carried over.
        kept = {key: copy.deepcopy(value) for key, value in notes.items() if key not in dropped}
        if kept:
            merged[ORIGINAL] = kept
    return merged


def _key(item) -> str:
    return json.dumps(_plain(item), ensure_ascii=False, sort_keys=True)


def _merge_list(old, translation, new):
    if len(translation) != len(old):
        raise _Unsafe
    matcher = SequenceMatcher(None, [_key(item) for item in old], [_key(item) for item in new])
    merged = []
    for operation, start, end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            merged.extend(copy.deepcopy(translation[index]) for index in range(start, end))
        elif operation == "replace" and end - start == new_end - new_start:
            # Entries changed in place, such as a command whose text changed.
            merged.extend(
                _merge(old[start + offset], translation[start + offset], new[new_start + offset])
                for offset in range(end - start)
            )
        else:
            # Entries the release inserted, removed or regrouped are its own.
            merged.extend(copy.deepcopy(new[index]) for index in range(new_start, new_end))
    return merged
