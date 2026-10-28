"""Shared helpers for ``<game>/.dazedtl/glossary.txt``.

``glossary.txt`` is loaded by the shared translation layer (:mod:`util.translation`)
and applied to every engine, so a good glossary keeps character names, honorifics,
and worldbuilding terms consistent across the whole translation.

The file has two parts:

* the game-specific entries (characters, worldbuilding terms) edited per project,
* a base glossary that is auto-appended from ``data/glossary_base.txt``.

``BASE_SEPARATOR`` marks where the auto-appended base section begins so the
workflow editors can show and save only the game-specific portion.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import NamedTuple

from util.paths import (
    GLOSSARY_BASE_SEPARATOR,
    active_glossary_path,
    ensure_game_glossary,
    glossary_base_path,
    read_active_glossary,
    read_game_glossary,
)
from util import system

BASE_SEPARATOR = GLOSSARY_BASE_SEPARATOR

_EMPTY_PLACEHOLDER = "# Add character glossary entries here\n"

# Guards each glossary write, and the read-modify-write of a merge, against
# concurrent translation file-threads clobbering each other's sections.
_VOCAB_LOCK = threading.Lock()

# Collect freezes the glossary for collect-time prompts and for rematching
# legacy (pre-v5) paid batch results after Pass 2 harvests names.
BATCH_GLOSSARY_FREEZE_FILE = Path("log/batch_glossary_freeze.txt")


def _path(game_root) -> "Path":
    if game_root is not None:
        return ensure_game_glossary(game_root)
    path = active_glossary_path()
    if path is None:
        raise RuntimeError("No active game folder is available for glossary access.")
    return path


def batch_glossary_phase() -> str:
    """Return the active batch phase, or ``\"\"`` when batch translation is off."""
    return (os.getenv("BATCH_PHASE") or "").strip().lower()


def freeze_batch_glossary(*, game_root=None) -> Path:
    """Snapshot the live glossary for the current batch collect/consume cycle."""
    text = read_active_glossary() if game_root is None else _path(game_root).read_text(
        encoding="utf-8"
    )
    return write_batch_glossary_freeze(text)


def write_batch_glossary_freeze(text: str) -> Path:
    """Write an explicit freeze snapshot (used when restoring from history)."""
    text = text if isinstance(text, str) else ""
    BATCH_GLOSSARY_FREEZE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BATCH_GLOSSARY_FREEZE_FILE.with_suffix(
        BATCH_GLOSSARY_FREEZE_FILE.suffix
        + f".{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(text, encoding="utf-8", newline="\n")
    system.replace(tmp, BATCH_GLOSSARY_FREEZE_FILE)
    return BATCH_GLOSSARY_FREEZE_FILE


def persist_batch_glossary_freeze_to_state() -> None:
    """Copy the freeze file into active batch_state for redownload/resume."""
    if not BATCH_GLOSSARY_FREEZE_FILE.is_file():
        return
    try:
        text = BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
        import util.translation as T

        with T.BATCH_LOCK:
            with T._batch_file_lock():
                state = T._read_batch_file(T.BATCH_STATE_FILE)
                state["glossary_freeze"] = text
                T._write_batch_file(T.BATCH_STATE_FILE, state)
    except Exception:
        pass


def restore_batch_glossary_freeze_from_state() -> bool:
    """Restore the freeze file from active batch_state when missing."""
    if BATCH_GLOSSARY_FREEZE_FILE.is_file():
        return True
    try:
        import util.translation as T

        with T._batch_file_lock():
            state = T._read_batch_file(T.BATCH_STATE_FILE)
        text = state.get("glossary_freeze")
        if not isinstance(text, str) or not text:
            return False
        write_batch_glossary_freeze(text)
        return True
    except Exception:
        return False


def clear_batch_glossary_freeze() -> None:
    """Drop the collect-time glossary freeze, if present."""
    system.unlink(BATCH_GLOSSARY_FREEZE_FILE, ignore_errors=True)


def read_translation_glossary() -> str:
    """Glossary text preferred during batch collect (freeze) or otherwise live.

    During collect, prefer the freeze taken at collect start. During consume,
    callers that need live harvests should read the live glossary; batch result
    keys use the freeze only for legacy (pre-v5) rematching.
    """
    if batch_glossary_phase() == "collect":
        if BATCH_GLOSSARY_FREEZE_FILE.is_file():
            try:
                return BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
            except OSError:
                pass
        restore_batch_glossary_freeze_from_state()
        if BATCH_GLOSSARY_FREEZE_FILE.is_file():
            try:
                return BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
            except OSError:
                pass
    return read_active_glossary()


def _split_base(text: str) -> tuple[str, str]:
    index = text.find(BASE_SEPARATOR)
    if index == -1:
        return text, ""
    return text[:index], text[index:]


def read_game_vocab(game_root=None, *, create: bool = True) -> str:
    """Return the game section, optionally previewing a missing glossary read-only."""
    if create:
        text = _path(game_root).read_text(encoding="utf-8")
    elif game_root is not None:
        text = read_game_glossary(game_root, create=False)
    else:
        path = active_glossary_path(create=False)
        if path is None:
            return _EMPTY_PLACEHOLDER
        text = read_game_glossary(path.parents[1], create=False)
    game_part, _base_part = _split_base(text)
    return game_part.rstrip("\n") or _EMPTY_PLACEHOLDER


def write_game_vocab(game_text: str, game_root=None) -> None:
    """Write the game-specific glossary and re-append the shipped base."""
    game_text = (game_text or "").rstrip("\n")
    base_path = glossary_base_path()
    base_text = (
        base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
    )
    with _VOCAB_LOCK:
        _replace_glossary(
            _path(game_root), game_text + "\n\n" + BASE_SEPARATOR + base_text
        )


def _replace_glossary(path: Path, text: str) -> None:
    """Replace the glossary in one step, so a reader never sees half of it.
    Callers hold :data:`_VOCAB_LOCK`."""
    tmp_path = path.with_suffix(
        path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    system.replace(tmp_path, path)


def _read_glossary(game_root=None) -> str:
    """The whole glossary as a merge starts from it: a named game's without
    creating it, else the active glossary, which may be the user's own file."""
    if game_root is None:
        return _path(None).read_text(encoding="utf-8")
    return read_game_glossary(game_root, create=False)


def _norm(s: str) -> str:
    """Normalise for no-op detection: collapse whitespace and case-fold."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def split_glossary_row(line: str) -> tuple[str, str, str] | None:
    """Split a ``source (translation)`` row into source, translation and rest.

    The translation is the first balanced parenthesized group, so a nameplate
    such as ``農夫の魂（夫） (Farmer's Soul (Husband))`` keeps its own
    parentheses, and rich rows continue after it (``サンク (Sank) - Male``).
    """
    start = line.find("(")
    while start != -1:
        depth = 0
        for end in range(start, len(line)):
            depth += {"(": 1, ")": -1}.get(line[end], 0)
            if depth == 0:
                source = line[:start].strip()
                if source:
                    return source, line[start + 1 : end].strip(), line[end + 1 :]
                break
        start = line.find("(", start + 1)
    return None


UNVERIFIED_NAMEPLATE = "Unverified nameplate"


def glossary_row(source: str, translation: str, notes: str = "") -> str:
    """One glossary row: ``source (translation)``, with ``- notes`` after it
    when there are any."""
    return f"{source} ({translation})" + (f" - {notes}" if notes else "")


def unverified_nameplate_row(source: str, translation: str, origin: str) -> str:
    """A glossary row for a nameplate translated apart from its story, marked
    for Project Setup to confirm or correct."""
    return glossary_row(source, translation, f"{UNVERIFIED_NAMEPLATE}, {origin}.")


_SOURCE_ALIAS_SPLIT_RE = re.compile(r"\s*[\/／]\s*")
_CATEGORY_NAME_SPLIT_RE = re.compile(r"\s*[·・|/]\s*")
# The character sections by authority: a curated Game Characters row outranks
# a generated Speakers row for the same name.
_CHARACTER_PRIORITY = {"game characters": 2, "speakers": 1}
# Sections whose ``A / B`` sources list variants of one name.
ALIAS_CATEGORIES = frozenset(_CHARACTER_PRIORITY)
# A section header: every line that starts with ``#``, as requests read them.
_HEADER_LINE_RE = re.compile(r"^[^\S\n]*#.*$", re.MULTILINE)


def split_vocab_source_aliases(source: str) -> list[str]:
    """Expand ``ニーナ / ネーナ・エヴァンス`` into individual source keys.

    Curated Game Characters rows often list orthographic or full-name variants
    separated by ASCII or fullwidth slashes. Speaker lookup and glossary matching
    must treat each variant as covered by the same English gloss.
    """
    text = str(source or "").strip()
    if not text:
        return []
    parts = [
        part.strip()
        for part in _SOURCE_ALIAS_SPLIT_RE.split(text)
        if part.strip()
    ]
    return parts or [text]


def glossary_category(header) -> str:
    """A section header's category name, ``"game characters"`` for
    ``# Game Characters · キャラクター``.

    This is what a section is: requests read rows by it, and every write,
    merge and removal of a category means all the sections it names.
    """
    return _category_parts(header)[0]


def _category_parts(header) -> tuple[str, str]:
    """A header's category name and the qualifier after it, ``("item",
    "アイテム")`` for ``# Item · アイテム``."""
    name = str(header or "").strip().lstrip("#").strip().casefold()
    parts = _CATEGORY_NAME_SPLIT_RE.split(name, maxsplit=1)
    return parts[0], " ".join(parts[1].split()) if len(parts) > 1 else ""


def _names_category(header, category) -> bool:
    """Whether section ``header`` is ``category``'s: the same
    :func:`glossary_category`, and the same qualifier when both name one, so
    WOLF's ``Item · アイテム`` and ``Item · 道具`` stay two sections."""
    name, qualifier = _category_parts(header)
    wanted, wanted_qualifier = _category_parts(category)
    return name == wanted and (
        not qualifier or not wanted_qualifier or qualifier == wanted_qualifier
    )


def character_priority(header) -> int:
    """How far a row in section ``header`` decides a character's name: 2 in
    Game Characters, 1 in Speakers, 0 in any other section."""
    return _CHARACTER_PRIORITY.get(glossary_category(header), 0)


class FoldedSections(NamedTuple):
    """A category's sections of a glossary text, read as one."""

    # The first section's header line as written.
    header: str
    # Every section's lines in order, each without blank lines at its ends.
    lines: list[str]
    # The text before the first section, and after it without the others.
    before: str
    after: str


def fold_glossary_sections(text: str, category) -> FoldedSections | None:
    """``category``'s sections of ``text`` folded into the first, or None
    when it has none.

    A section runs from its header to the next one, and it is
    ``category``'s when :func:`glossary_category` reads both alike, so
    ``# game characters`` and ``# Game Characters · キャラクター`` are
    ``Game Characters`` too, unless both name different qualifiers (see
    :func:`_names_category`). A later section's row with the source and
    translation of an earlier row is left out, as requests read it once.
    """
    headers = list(_HEADER_LINE_RE.finditer(text))
    sections = [
        (header, headers[index + 1].start() if index + 1 < len(headers) else len(text))
        for index, header in enumerate(headers)
        if _names_category(header.group(), category)
    ]
    if not sections:
        return None
    lines: list[str] = []
    rows: set[tuple[str, str]] = set()
    for number, (header, end) in enumerate(sections):
        for line in text[header.end() : end].strip().splitlines():
            row = split_glossary_row(line.strip())
            if row and number and row[:2] in rows:
                continue
            if row:
                rows.add(row[:2])
            lines.append(line)
    first, first_end = sections[0]
    after, position = [], first_end
    for header, end in sections[1:]:
        after.append(text[position : header.start()])
        position = end
    after.append(text[position:])
    return FoldedSections(
        first.group().rstrip(), lines, text[: first.start()], "".join(after)
    )


def glossary_row_sources(source: str, header) -> list[str]:
    """The sources a row in section ``header`` covers: each slash variant in a
    character or speaker section, as requests match them, else the whole
    source."""
    if glossary_category(header) in ALIAS_CATEGORIES:
        return split_vocab_source_aliases(source)
    return [source]


def is_unverified_nameplate(rest: str) -> bool:
    """Whether a row's text after its translation is the unverified marker."""
    return rest.strip().startswith(f"- {UNVERIFIED_NAMEPLATE}")


_SECTION_ROW_SOURCE_RE = re.compile(r"^(.+?)\s+\(")
# A row that is only "source (translation)", without a note after it.
_SECTION_PLAIN_ROW_RE = re.compile(r"^.+?\s+\(.+\)$")

_DECORATIVE_GLOSSARY_PUNCTUATION = frozenset({"•", "‣", "⁃", "※"})


def split_glossary_decorative_prefix(term: str) -> tuple[str, str]:
    """Return a leading label marker and the usable term behind it.

    Unicode ``So`` characters cover geometric markers such as ``▼``, ``■``,
    and ``★`` without classifying parentheses or percent signs as decoration.
    The explicit punctuation set covers common bullet and note markers used by
    game databases.
    """
    text = str(term or "").strip()
    marker_end = 0
    while marker_end < len(text):
        char = text[marker_end]
        if (
            unicodedata.category(char) == "So"
            or char in _DECORATIVE_GLOSSARY_PUNCTUATION
        ):
            marker_end += 1
            continue
        break
    if marker_end == 0:
        return "", text
    return text[:marker_end], text[marker_end:].lstrip()


def decorative_glossary_alias(source: str, target: str):
    """Return a clean alias when an existing row uses the same paired marker."""
    source_marker, source_alias = split_glossary_decorative_prefix(source)
    target_marker, target_alias = split_glossary_decorative_prefix(target)
    if (
        not source_marker
        or source_marker != target_marker
        or not source_alias
        or not target_alias
    ):
        return None
    return source_alias, target_alias


def normalize_generated_glossary_pair(source: str, target: str) -> tuple[str, str]:
    """Remove leading database-label decoration from a generated pair."""
    _source_marker, clean_source = split_glossary_decorative_prefix(source)
    _target_marker, clean_target = split_glossary_decorative_prefix(target)
    return clean_source, clean_target


def _merge_section_rows(
    category: str,
    lines: list[str],
    entries: dict[str, tuple[str, str]],
    *,
    overwrite: bool = False,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Return a section's rows with ``entries`` (source to translation and
    notes) merged in, and the rows an overwrite kept.

    Existing rows stay exactly as written, including a note after the
    translation (``サンク (Sank) - Male``), and sources the section lacks are
    appended after them. A source the section holds already, or covers
    through a slash variant of a character or speaker row (``ニーナ / ネーナ
    (Nina)``), is not added again, so the glossary never names one source
    two ways. With ``overwrite`` a source already present takes its new
    translation, unless its row carries a note. A row with a note, or one a
    slash variant covers, was written by hand: it stays, and a translation
    it overrules is kept as ``(row, source, translation)``.
    """
    rows = list(lines)
    present = set()
    covered: dict[str, tuple[str, str]] = {}
    kept = []
    for index, row in enumerate(rows):
        text = row.strip()
        found = _SECTION_ROW_SOURCE_RE.match(text)
        if not found:
            continue
        source = found.group(1)
        present.add(source)
        parsed = split_glossary_row(text)
        if parsed:
            for alias in glossary_row_sources(parsed[0], category):
                covered.setdefault(alias, (text, parsed[1]))
        if overwrite and source in entries:
            if _SECTION_PLAIN_ROW_RE.match(text):
                rows[index] = glossary_row(source, entries[source][0])
            elif parsed and entries[source][0] != parsed[1]:
                kept.append((text, source, entries[source][0]))
    for source, (target, notes) in entries.items():
        if source in present:
            continue
        if source not in covered:
            rows.append(glossary_row(source, target, notes))
        elif overwrite and covered[source][1] != target:
            kept.append((covered[source][0], source, target))
    return rows, kept


def _merge_section(
    game_part: str,
    category: str,
    entries: dict[str, tuple[str, str]],
    *,
    merge: bool,
    overwrite: bool = False,
) -> tuple[str, list[tuple[str, str, str]]]:
    """The game part with ``entries`` merged into, or replacing, the
    category's sections, and the rows an overwrite kept (see
    :func:`_merge_section_rows`).

    The sections are folded into the first, under its header as written (see
    :func:`fold_glossary_sections`); a category without one gets a ``#
    {category}`` section at the end.
    """
    found = fold_glossary_sections(game_part, category)
    kept = []
    if merge and found:
        rows, kept = _merge_section_rows(
            category, found.lines, entries, overwrite=overwrite
        )
    else:
        rows = [glossary_row(src, *entry) for src, entry in entries.items()]
    if found:
        block = found.header + "\n" + "\n".join(rows) + "\n\n"
        return found.before + block + found.after, kept
    new_game = game_part.rstrip("\n")
    if new_game:
        new_game += "\n\n"
    return new_game + f"# {category}\n" + "\n".join(rows) + "\n\n", kept


def _change_game_vocab(change, game_root=None) -> None:
    """Run one read-modify-write of the glossary's game part.

    ``change`` takes the game part and returns its new text; it may raise to
    leave the file as it was. The base section stays intact, the change holds
    :data:`_VOCAB_LOCK` from read to write, and the file is replaced in one
    step.
    """
    with _VOCAB_LOCK:
        existing = _read_glossary(game_root)
        game_part, base_part = _split_base(existing)
        new_game = change(game_part)
        if new_game == game_part:
            return
        if base_part:
            combined = new_game.rstrip("\n") + "\n\n" + base_part
        else:
            combined = new_game
        if combined == existing:
            return
        _replace_glossary(_path(game_root), combined)


def append_vocab_rows(sections, *, game_root=None) -> None:
    """Add rows to the game glossary's sections, never changing a row there.

    ``sections`` maps a category (``"Game Characters"``) to ``(source,
    translation, notes)`` rows, written ``source (translation) - notes`` after
    the section's own rows; a source the section has already is skipped (see
    :func:`_merge_section_rows`), and the category's sections are folded into
    one. A category without a section gets one at the end. ``sections`` may
    instead be a function that receives the game part as it is read under the
    lock and returns them, or raises to leave the file untouched.
    """

    def change(game_part: str) -> str:
        wanted = sections(game_part) if callable(sections) else sections
        for category, rows in wanted.items():
            entries = {source: (target, notes) for source, target, notes in rows}
            if entries:
                game_part, _kept = _merge_section(
                    game_part, category, entries, merge=True
                )
        return game_part

    _change_game_vocab(change, game_root)


def update_vocab_section(
    category: str,
    pairs,
    *,
    merge: bool = False,
    overwrite: bool = False,
    game_root=None,
) -> list[tuple[str, str, str]]:
    """Insert or replace a ``# {category}`` section in the game-specific vocab.

    Mirrors the RPGMaker auto-glossary behaviour (translated DB names feed
    ``glossary.txt`` so later phases stay consistent), but always writes *above*
    the auto-appended base section (:data:`BASE_SEPARATOR`) so the base glossary is
    preserved and not stripped on the next :func:`read_game_vocab`.

    - ``category``: section header text, e.g. ``"Weapon · 武器"``. Every
      section :func:`glossary_category` reads as it is folded into the first.
    - ``pairs``: iterable of ``(source, translated)``. Deduped by source (last
      wins); no-ops (empty translation or unchanged after normalisation) are
      dropped. Leading database-label decoration is removed from generated
      rows. When nothing survives filtering the file is left untouched.
    - ``merge``: when True, keep existing rows for this category as written,
      including notes after the translation, and only add sources that are not
      already present (names.json stays authoritative), as
      :func:`append_vocab_rows` does.
    - ``overwrite``: with ``merge``, a source already present takes its new
      translation instead of keeping the old one, except on a row with a note.
      A pass that translated only some of a category's names uses both, so the
      rest of the section survives and the glossary matches the written files.

    Returns the hand-written rows an overwrite kept against this pass's
    translation, as ``(row, source, translation)``, and prints each for the
    run log. Collect skips writes (source text is still untranslated).
    Consume writes immediately so sequential Pass 2 files can load harvested
    names.
    """
    dedup: dict[str, tuple[str, str]] = {}
    for src, dst in pairs:
        src, dst = normalize_generated_glossary_pair(src, dst)
        if not src:
            continue
        if dst is None or _norm(dst) == "" or _norm(dst) == _norm(src):
            continue
        dedup[str(src)] = (str(dst), "")
    if not dedup:
        return []

    if batch_glossary_phase() == "collect":
        # Collect leaves source text untranslated; nothing useful to harvest.
        return []

    kept: list[tuple[str, str, str]] = []

    def change(game_part: str) -> str:
        game_part, rows = _merge_section(
            game_part, category, dedup, merge=merge, overwrite=overwrite
        )
        kept[:] = rows
        return game_part

    _change_game_vocab(change, game_root)
    for row, source, translation in kept:
        print(
            f"Glossary keeps {row} for {source}; this pass translated it "
            f"{translation}.",
            flush=True,
        )
    return kept


def remove_vocab_section(category: str, *, game_root=None) -> None:
    """Remove a category's sections from the game-specific vocab, if present
    (see :func:`fold_glossary_sections`)."""
    with _VOCAB_LOCK:
        glossary_path = _path(game_root)
        existing = glossary_path.read_text(encoding="utf-8")

        game_part, base_part = _split_base(existing)

        found = fold_glossary_sections(game_part, category)
        if found is None:
            return
        new_game = found.before + found.after
        new_game = re.sub(r"\n{3,}", "\n\n", new_game).rstrip("\n")
        if base_part:
            combined = new_game + "\n\n" + base_part if new_game else base_part
        else:
            combined = new_game + "\n" if new_game else ""
        if combined == existing:
            return
        _replace_glossary(glossary_path, combined)
