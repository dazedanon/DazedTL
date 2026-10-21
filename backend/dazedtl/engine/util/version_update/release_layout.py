"""Where a new official release's files belong in the game.

Developers ship either a complete game or a patch whose files are copied over
the previous version. Either can sit inside an extra folder, and a patch can
start below the game's root, such as an MV patch holding ``data/`` for the
game's ``www/data/``. Paths line up case-insensitively, as they do on
Windows, where these releases are made and applied.

A patch keeps the files it leaves out because the previous version stays under
it. An MV/MZ patch is previewed with the same data and plugin formatting as
the game's own files (git_workflow._source_files), so it merges line by line.
"""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .git_workflow import GitWorkflowError, _is_local_only_asset, _is_tool_owned_path

# A release holding at least this share of the game's files replaces the game;
# one holding less is a patch, since replacing would remove the rest.
COMPLETE_SHARE = 0.5
# Choosing a whole drive or library by mistake stops here instead of hashing it.
FILE_LIMIT = 200_000
# Left-out files a layout names; the rest are only counted.
LISTED = 20
_TAGGED_VERSION = re.compile(r"(?i)(?<![a-z])v(?:er(?:sion)?)?[\s._-]*(\d+(?:\.\d+)+)")
_BARE_VERSION = re.compile(r"(?<![\d.])(\d+(?:\.\d+)+)(?![\d.])")


@dataclass(frozen=True)
class ReleaseLayout:
    kind: str
    # The release folder whose contents line up with the game; "" is its root.
    source: str
    # The game folder a patch's files go into; "" is the game's root.
    target: str
    # Release files that go into the game, and how many of them it already has.
    files: int
    replaced: int
    # Release files outside `source`, which stay out of the game, and the
    # first few of them by name.
    outside: int
    left_out: tuple[str, ...]
    # The game's own files, and how many of them the release holds.
    game_files: int
    covered: int


@dataclass(frozen=True)
class ReleaseInspection:
    detected: str
    version: str
    game: ReleaseLayout
    patch: ReleaseLayout

    def layout(self, kind: str | None = None) -> ReleaseLayout:
        return self.patch if (kind or self.detected) == "patch" else self.game


def _walk(root: Path) -> list[str]:
    found: list[str] = []
    for folder, directories, names in os.walk(root):
        relative = Path(folder).relative_to(root)
        directories[:] = sorted(
            name
            for name in directories
            if name != ".git" and not (relative == Path(".") and name == ".dazedtl")
        )
        for name in sorted(names):
            found.append((relative / name).as_posix())
            if len(found) > FILE_LIMIT:
                raise GitWorkflowError(
                    f"{root} holds more than {FILE_LIMIT:,} files. "
                    "Choose the folder of the game's release."
                )
    return found


def _game_files(game: Path) -> list[str]:
    # The game's own files, without DazedTL's tools and the player's saves.
    return [
        path
        for path in _walk(game)
        if not _is_tool_owned_path(path) and not _is_local_only_asset(path)
    ]


def _folders(paths: list[str]) -> set[tuple[str, ...]]:
    entries = set()
    for path in paths:
        parts = tuple(path.split("/"))
        for end in range(1, len(parts) + 1):
            entries.add(parts[:end])
    return entries


def _fold(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(part.casefold() for part in parts)


def _alignments(release: list[str], game: list[str]) -> Counter:
    """Votes for each (release folder, game folder) pair that line up.

    Every release file and folder votes for the pair under which it matches a
    game entry over the longest shared path, so a patch adding only new maps
    still finds its place through the folders that hold them.
    """
    named = defaultdict(list)
    for entry in _folders(game):
        named[entry[-1].casefold()].append(entry)
    votes: Counter = Counter()
    for entry in _folders(release):
        folded = _fold(entry)
        pairs = set()
        for other in named.get(folded[-1], ()):
            shared = 0
            for left, right in zip(reversed(folded), reversed(_fold(other))):
                if left != right:
                    break
                shared += 1
            pairs.add(("/".join(entry[:-shared]), "/".join(other[:-shared])))
        for pair in pairs:
            votes[pair] += 1
    return votes


def _best(votes: Counter, pairs) -> tuple[str, str]:
    # Most votes; then the shallowest folders, so a full match wins its own parts.
    return max(
        pairs,
        key=lambda pair: (
            votes[pair],
            -len([part for part in pair[0].split("/") if part]),
            -len([part for part in pair[1].split("/") if part]),
        ),
        default=("", ""),
    )


def _under(path: str, folder: str) -> str | None:
    if not folder:
        return path
    return path[len(folder) + 1 :] if path.startswith(folder + "/") else None


def _layout(kind, release, game, source, target) -> ReleaseLayout:
    inside = [_under(path, source) for path in release]
    tails = [tail for tail in inside if tail is not None]
    game_folded = {path.casefold() for path in game}
    place = (lambda tail: f"{target}/{tail}") if target else (lambda tail: tail)
    supplied = {place(tail).casefold() for tail in tails}
    return ReleaseLayout(
        kind=kind,
        source=source,
        target=target,
        files=len(tails),
        replaced=sum(1 for path in supplied if path in game_folded),
        outside=len(release) - len(tails),
        left_out=tuple(path for path, tail in zip(release, inside) if tail is None)[:LISTED],
        game_files=len(game),
        covered=sum(1 for path in game_folded if path in supplied),
    )


def guess_version(name: str) -> str:
    """The version a release folder's name gives, such as 1.10 in "Game_v1.10"."""
    text = unicodedata.normalize("NFKC", name)
    found = _TAGGED_VERSION.search(text) or _BARE_VERSION.search(text)
    return found.group(1) if found else ""


def inspect_release(game_root: str | Path, release_root: str | Path) -> ReleaseInspection:
    """How a release folder lines up with the game, as a complete game and as a patch."""
    game = Path(game_root).expanduser().resolve()
    release = Path(release_root).expanduser().resolve()
    if not release.is_dir():
        raise GitWorkflowError(f"Release folder not found: {release}")
    files = _walk(release)
    if not files:
        raise GitWorkflowError("The release folder is empty.")
    own = _game_files(game)
    votes = _alignments(files, own)
    # A complete game replaces the game's root, so only its own folder varies.
    root = _best(votes, [pair for pair in votes if not pair[1]])
    complete = _layout("game", files, own, root[0], "")
    patch = _layout("patch", files, own, *_best(votes, votes))
    detected = (
        "game" if own and complete.covered >= COMPLETE_SHARE * len(own) else "patch"
    )
    names = [release.name, *(root[0].split("/") if root[0] else ())]
    version = next((found for found in map(guess_version, reversed(names)) if found), "")
    return ReleaseInspection(detected, version, complete, patch)


def stage_release(
    game_root: str | Path, copy: str | Path, destination: str | Path, layout: ReleaseLayout
) -> None:
    """Moves a private copy of the release into `destination`, laid out as the game.

    A patch's paths take the game's spelling where they name the same file or
    folder, so applying it replaces those files instead of adding a second
    copy that differs only in case.
    """
    copy = Path(copy)
    destination = Path(destination)
    if destination.exists():
        raise GitWorkflowError(f"The staging folder already exists: {destination}")
    if layout.kind == "game":
        shutil.move(copy / layout.source if layout.source else copy, destination)
        return
    spelled = {}
    for entry in _folders(_walk(Path(game_root))):
        spelled[_fold(entry)] = entry[-1]
    placed = {}
    for path in _walk(copy):
        tail = _under(path, layout.source)
        if tail is None:
            continue
        parts = tuple(f"{layout.target}/{tail}".split("/") if layout.target else tail.split("/"))
        named = tuple(
            spelled.get(_fold(parts[: index + 1]), part) for index, part in enumerate(parts)
        )
        key = _fold(named)
        if key in placed:
            raise GitWorkflowError(
                f"The patch has two files for {'/'.join(named)}: {placed[key]} and {path}."
            )
        placed[key] = path
        target = destination.joinpath(*named)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(copy / path, target)
