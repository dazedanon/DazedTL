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
"""

from __future__ import annotations

import copy
import json
from difflib import SequenceMatcher

ORIGINAL = "_original"
_MISSING = object()


class _Unsafe(Exception):
    """The translation changed the data's shape, so values cannot line up."""


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
    try:
        merged = _merge(old, translation, new)
    except _Unsafe:
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
