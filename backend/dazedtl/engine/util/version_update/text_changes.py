"""What an official update does to a game's text, line by line.

A preview names the files an update changes; this reads the JSON and the
plugins among them as data, so their Japanese strings become lines: the old
release's, the new release's, the translation's and what the game will hold
once the update merges. Lines line up by text between the two releases,
since a release that inserts a command shifts every position after it, and
by position between a release and its translation, which only rewrites
strings in place. A plugin registry's settings read as data by plugin, and a
plugin script's lines that hold Japanese in quotes are its strings.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from util.rpgmaker_plugin_registry import PluginRegistryError, plugin_entries

from .git_workflow import GitWorkflowError, UpdatePreview, inspect_repository, merged_file, _tree_files
from .json_merge import expand
from .script_merge import is_plugin_registry, paired_lines, quoted_text
from util import system

JAPANESE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
# A file's lines a preview keeps for display, and all files' lines together;
# the counts always cover every line.
FILE_LINES = 200
ALL_LINES = 2000
# The files of one checkpoint whose lines are read.
CHECKPOINT_FILES = 40
# How alike an old and a new line must be to read as one line changed, and
# the largest replaced block paired that way.
PAIRING_RATIO = 0.5
PAIRING_LIMIT = 2500
# Engine metadata that keeps a translated line's source; it is not game text.
_SOURCE_KEYS = frozenset({"_original"})


@dataclass(frozen=True)
class LineChange:
    # "added", "changed", "removed", or "replaced" for an unchanged line whose
    # translation the update drops anyway; "edited" for a checkpoint's line,
    # its text before and after.
    kind: str
    # The old release's Japanese and the translation the game had for it.
    before: str | None
    translation: str | None
    # The new release's Japanese.
    after: str | None


@dataclass
class FileText:
    path: str
    # New or changed lines that will be Japanese in the game after the update.
    to_translate: int = 0
    # Translated lines the update replaces or removes.
    replaced: int = 0
    # Translated lines the update leaves as they are.
    kept: int = 0
    # Lines a checkpoint changed.
    edited: int = 0
    lines: list[LineChange] = field(default_factory=list)
    # Lines left out of `lines` past the display limits.
    more: int = 0


@dataclass(frozen=True)
class TextChanges:
    to_translate: int
    replaced: int
    kept: int
    files: tuple[FileText, ...]


def _strings(document, path=()):
    if isinstance(document, str):
        yield path, document
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from _strings(value, (*path, index))
    elif isinstance(document, dict):
        for key, value in document.items():
            if key not in _SOURCE_KEYS:
                yield from _strings(value, (*path, key))


def _parse(raw: bytes | None):
    if raw is None:
        return None
    try:
        return expand(json.loads(raw.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError):
        return None


def _plugins(raw: bytes | None):
    """A plugin registry's settings by plugin, so a plugin the translation or
    the release registered shifts no other plugin's strings."""
    if raw is None:
        return None
    try:
        entries = plugin_entries(raw.decode("utf-8"))
    except (UnicodeDecodeError, PluginRegistryError):
        return None
    document, seen = {}, Counter()
    for value in entries:
        name = str(value.get("name"))
        document[f"{name}#{seen[name]}"] = expand(value.get("parameters"))
        seen[name] += 1
    return document


def _script(raw: bytes | None) -> list[str] | None:
    if raw is None:
        return None
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def _text_line(line: str) -> str:
    """A script line that holds Japanese in quotes, or nothing for code and
    comments, such as a plugin's help."""
    text = line.strip()
    if text.startswith(("//", "/*", "*")) or not any(JAPANESE.search(value) for value in quoted_text(text)):
        return ""
    return text


def _documents(path, base, translated, official, merged):
    """The sides as documents whose strings share keys: a release's by its
    own, a translation by its source's and the merge by the new release's;
    None when the new release's file cannot be read."""
    if is_plugin_registry(path) or not path.casefold().endswith(".js"):
        read = _plugins if is_plugin_registry(path) else _parse
        new = read(official)
        if new is None:
            return None
        result = read(merged)
        return read(base), read(translated), new, new if result is None else result
    old, translation, new, result = (_script(raw) for raw in (base, translated, official, merged))
    if new is None:
        return None
    # A translation and a merge may add or remove lines, so each line takes
    # the key of the release line it stands for.
    return (
        None if old is None else [_text_line(line) for line in old],
        None
        if translation is None
        else {line: translation[other].strip() for line, other in paired_lines(old or [], translation).items()},
        [_text_line(line) for line in new],
        None if result is None else {line: result[other].strip() for line, other in paired_lines(new, result).items()},
    )


def _blobs(repo: Path, objects: list[str]) -> dict[str, bytes]:
    """Reads Git objects in one process, as raw bytes."""
    unique = list(dict.fromkeys(objects))
    if not unique:
        return {}
    try:
        output = system.run(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            input=("\n".join(unique) + "\n").encode(),
            capture_output=True,
            check=True,
            timeout=300,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitWorkflowError("Git could not read the update's files.") from exc
    blobs, offset = {}, 0
    for identity in unique:
        end = output.index(b"\n", offset)
        header = output[offset:end].split()
        if len(header) < 3 or header[1] != b"blob":
            offset = end + 1
            continue
        size = int(header[2])
        blobs[identity] = output[end + 1 : end + 1 + size]
        offset = end + 2 + size
    return blobs


def _pairs(old, new):
    """A replaced block's lines, the old and new versions of one line paired
    by similarity in order, and every other line on its own side."""
    if len(old) * len(new) > PAIRING_LIMIT:
        # A long rewrite pairs by position; the counts are the same.
        return [
            (old[index] if index < len(old) else (None, None), new[index] if index < len(new) else (None, None))
            for index in range(max(len(old), len(new)))
        ]
    matched, start = {}, 0
    for index, (_key, source) in enumerate(old):
        best, score = None, PAIRING_RATIO
        for other in range(start, len(new)):
            ratio = SequenceMatcher(None, source, new[other][1], autojunk=False).ratio()
            if ratio > score:
                best, score = other, ratio
        if best is not None:
            matched[best] = index
            start = best + 1
    pairs, index = [], 0
    for other, line in enumerate(new):
        if other in matched:
            while index < matched[other]:
                pairs.append((old[index], (None, None)))
                index += 1
            pairs.append((old[index], line))
            index += 1
        else:
            pairs.append(((None, None), line))
    pairs.extend((line, (None, None)) for line in old[index:])
    return pairs


def _compare(path, base, translated, official, merged, budget) -> FileText:
    text = FileText(path)
    before = [(key, value) for key, value in _strings(base) if JAPANESE.search(value)] if base is not None else []
    after = [(key, value) for key, value in _strings(official) if JAPANESE.search(value)]
    translation = dict(_strings(translated)) if translated is not None else {}
    result = dict(_strings(merged)) if merged is not None else dict(_strings(official))

    def translated_text(key, source):
        value = translation.get(key)
        return value if value is not None and value != source else None

    def note(change: LineChange):
        if len(text.lines) < FILE_LINES and budget[0] > 0:
            text.lines.append(change)
            budget[0] -= 1
        else:
            text.more += 1

    matcher = SequenceMatcher(None, [value for _, value in before], [value for _, value in after], autojunk=False)
    for operation, start, end, new_start, new_end in matcher.get_opcodes():
        old = before[start:end]
        new = after[new_start:new_end]
        if operation == "equal":
            for (key, source), (new_key, _value) in zip(old, new):
                english = translated_text(key, source)
                if english is None:
                    continue
                if result.get(new_key) == english:
                    text.kept += 1
                else:
                    text.replaced += 1
                    text.to_translate += 1
                    note(LineChange("replaced", source, english, result.get(new_key)))
            continue
        for (key, source), (new_key, value) in _pairs(old, new):
            english = translated_text(key, source) if key is not None else None
            if english is not None:
                text.replaced += 1
            if value is not None and JAPANESE.search(result.get(new_key, value)):
                text.to_translate += 1
            note(
                LineChange(
                    "changed" if source is not None and value is not None else "removed" if value is None else "added",
                    source,
                    english,
                    value,
                )
            )
    return text


def _replace_whole(path, current, official, budget) -> FileText:
    """A file the update copies over the game's, compared with the game's
    copy, the only earlier version there is, string by string in order."""
    text = FileText(path)
    now = [value for _, value in _strings(current)] if current is not None else []
    new = [value for _, value in _strings(official)]
    matcher = SequenceMatcher(None, now, new, autojunk=False)
    for operation, start, end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        old = now[start:end]
        for index, value in enumerate(new[new_start:new_end]):
            if not JAPANESE.search(value):
                continue
            was = old[index] if index < len(old) else None
            if was is not None and not JAPANESE.search(was):
                change = LineChange("replaced", None, was, value)
                text.replaced += 1
            else:
                change = LineChange("added" if was is None else "changed", was, None, value)
            text.to_translate += 1
            if len(text.lines) < FILE_LINES and budget[0] > 0:
                text.lines.append(change)
                budget[0] -= 1
            else:
                text.more += 1
    return text


def text_changes(game_root: str | Path, preview: UpdatePreview) -> TextChanges:
    """The lines a previewed update adds, changes and removes in the game's JSON files and plugins."""
    game = Path(game_root).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root:
        raise GitWorkflowError("The game is not in a Git repository")
    repo, prefix = status.repo_root, status.game_prefix
    full = (lambda path: f"{prefix}/{path}") if prefix else (lambda path: path)
    base_tree = preview.baseline_tree or f"{preview.original_commit}^{{tree}}"
    trees = {
        "base": _tree_files(repo, base_tree, prefix),
        "translated": _tree_files(repo, preview.translation_commit, prefix),
        "official": _tree_files(repo, preview.proposed_tree, prefix),
    }
    tracked = [
        change.path
        for change in preview.file_changes
        if change.path.casefold().endswith((".json", ".js"))
        and not change.already_present
        and change.change != "Removed"
    ]
    blobs = _blobs(
        repo,
        [trees[side][full(path)][1] for path in tracked for side in trees if full(path) in trees[side]],
    )

    def read(side, path):
        entry = trees[side].get(full(path))
        return blobs.get(entry[1]) if entry else None

    budget = [ALL_LINES]
    files = []
    for path in tracked:
        base, translated, official = (read(side, path) for side in ("base", "translated", "official"))
        if official is None:
            continue
        entries = [trees[side].get(full(path)) for side in ("translated", "base", "official")]
        merged = official
        if all(entries) and entries[0][1] not in (entries[1][1], entries[2][1]):
            # Both sides changed the file: what the merge keeps, or the new
            # release's file when Git cannot merge it, such as binary content.
            merged = merged_file(repo, full(path), *(entry[1] for entry in entries)) or official
        documents = _documents(path, base, translated, official, merged)
        if documents is not None:
            files.append(_compare(path, *documents, budget))
    # Files outside Git, such as maps no translation version saved, replace
    # the game's copy whole, and no old release is kept to compare with.
    for change in preview.external_changes:
        if not change.path.casefold().endswith(".json") or change.already_present or change.change == "Removed":
            continue
        official = _parse(_read_file(preview.source_root / change.path))
        if official is not None:
            current = _parse(_read_file(game / change.path))
            files.append(_replace_whole(change.path, current, official, budget))
    files = [entry for entry in files if entry.to_translate or entry.replaced or entry.lines]
    return TextChanges(
        sum(entry.to_translate for entry in files),
        sum(entry.replaced for entry in files),
        sum(entry.kept for entry in files),
        tuple(files),
    )


def _ordered(path: str, raw: bytes | None) -> list[str] | None:
    """A file's strings in the order they appear: a JSON file's and a plugin
    registry's values, a script's lines."""
    if is_plugin_registry(path) or not path.casefold().endswith(".js"):
        document = (_plugins if is_plugin_registry(path) else _parse)(raw)
        return None if document is None else [value for _key, value in _strings(document)]
    lines = _script(raw)
    return None if lines is None else [line.strip() for line in lines]


def _edits(path, old, new, budget) -> FileText:
    """A checkpoint's lines of one file, before and after. They line up by
    text, since a translated message may hold fewer rows than its source,
    and a changed run of lines pairs by position, as a translation's lines
    share no words with the text they replace."""
    text = FileText(path)
    for tag, start, end, new_start, new_end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        was, now = old[start:end], new[new_start:new_end]
        for index in range(max(len(was), len(now))):
            before = was[index] if index < len(was) else None
            after = now[index] if index < len(now) else None
            if not (before or after):
                continue
            text.edited += 1
            if len(text.lines) < FILE_LINES and budget[0] > 0:
                text.lines.append(LineChange("edited", before or None, None, after or None))
                budget[0] -= 1
            else:
                text.more += 1
    return text


def checkpoint_text(repo: Path, files: dict[str, tuple[str, str]]) -> dict:
    """The lines one checkpoint changed in a game's JSON files and plugins,
    from each file's blob before and after it ("0" * 40 for none)."""
    # A setup or update checkpoint changes every file; its first files show
    # their lines and the rest are listed, so one view never reads a game.
    readable = dict(
        sorted((path, blobs) for path, blobs in files.items() if path.casefold().endswith((".json", ".js")))[
            :CHECKPOINT_FILES
        ]
    )
    contents = _blobs(repo, [blob for pair in readable.values() for blob in pair if blob.strip("0")])
    budget = [ALL_LINES]
    found = []
    for path, (old, new) in sorted(readable.items()):
        before, after = (_ordered(path, contents.get(blob)) if blob.strip("0") else [] for blob in (old, new))
        if before is None or after is None:
            continue
        text = _edits(path, before, after, budget)
        if text.edited:
            found.append(asdict(text))
    return {
        "to_translate": 0,
        "replaced": 0,
        "kept": 0,
        "edited": sum(file["edited"] for file in found),
        "files": found,
    }


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None
