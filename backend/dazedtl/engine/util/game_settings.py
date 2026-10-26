"""Per-game DazedTL workflow settings stored with the selected game."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

from util import languages
from util.paths import (
    GLOSSARY_BASE_ENABLED_ENV,
    GLOSSARY_OVERRIDE_ENV,
    ensure_game_tool_gitignore,
    game_metadata_dir,
)
from util import system

GAME_SETTINGS_RELATIVE = Path(".dazedtl") / "settings.json"
WRAP_WIDTH_KEYS = ("width", "faceWidth", "listWidth", "noteWidth")
# The rows a message window shows, measured and saved with the widths.
MESSAGE_ROWS_KEY = "messageRows"
LINE_WIDTH_KEYS = (*WRAP_WIDTH_KEYS, MESSAGE_ROWS_KEY)
DEFAULT_WRAP_WIDTHS = {
    "width": 60,
    "faceWidth": 50,
    "listWidth": 100,
    "noteWidth": 75,
    MESSAGE_ROWS_KEY: 4,
}
# VX Ace's stock windows, measured in the engine: 520 pixels inside a
# 544-pixel window, where RGSS3 draws its 24-point VL Gothic 10 pixels to a
# half-width character. A face takes 112 pixels of a message's line, and the
# help window starts its text 4 pixels in. No stock window draws notes.
ACE_WRAP_WIDTHS = {
    "width": 52,
    "faceWidth": 40,
    "listWidth": 51,
    "noteWidth": 52,
    MESSAGE_ROWS_KEY: 4,
}
# The game's GameUpdate repository, the values it sets itself instead of
# following Settings, and the digest of the config DazedTL last wrote.
GAME_UPDATE_KEYS = ("repo", "forge", "host", "username", "branch", "written")
MIN_WRAP_WIDTH = 20
MAX_WRAP_WIDTH = 300
MIN_MESSAGE_ROWS = 1
MAX_MESSAGE_ROWS = 20


class GameSettingsError(ValueError):
    """Raised when an existing per-game settings file cannot be used safely."""


def game_settings_path(game_root: str | Path) -> Path:
    """Return ``<game>/.dazedtl/settings.json`` for a selected game root."""
    return Path(game_root).expanduser().resolve() / GAME_SETTINGS_RELATIVE


def _in_range(key: str, value: int) -> bool:
    if key == MESSAGE_ROWS_KEY:
        return MIN_MESSAGE_ROWS <= value <= MAX_MESSAGE_ROWS
    return MIN_WRAP_WIDTH <= value <= MAX_WRAP_WIDTH


def _coerce_width(value, fallback: int, key: str = "width") -> int:
    if isinstance(value, bool):
        return fallback
    try:
        width = int(value)
    except (TypeError, ValueError):
        return fallback
    if not _in_range(key, width):
        return fallback
    return width


def default_wrap_widths(engine: str | None = None) -> dict[str, int]:
    """The Line widths of an engine's stock windows, which a game keeps until
    any are measured or set: VX Ace's for "ACE", otherwise MV/MZ's."""
    return dict(ACE_WRAP_WIDTHS if engine == "ACE" else DEFAULT_WRAP_WIDTHS)


def game_wrap_widths(game_root: str | Path) -> dict[str, int]:
    """A game's saved Line widths, or its engine's stock ones."""
    saved = load_game_wrap_widths(game_root)
    if saved is not None:
        return saved
    from util.project_preparation import rpgmaker_layout

    layout = rpgmaker_layout(Path(game_root))
    return default_wrap_widths(layout["engine"] if layout else None)


def valid_line_widths(value) -> bool:
    """Whether *value* holds Line widths as a person or a measurement gives
    them: the four widths, and the message rows when given, each a whole
    number in its range."""
    return (
        isinstance(value, Mapping)
        and set(WRAP_WIDTH_KEYS) <= set(value) <= set(LINE_WIDTH_KEYS)
        and all(
            type(item) is int and _in_range(key, item) for key, item in value.items()
        )
    )


def normalize_wrap_widths(
    values: Mapping | None,
    *,
    defaults: Mapping | None = None,
) -> dict[str, int]:
    """Return complete bounded Line widths, clamping face width to dialogue."""
    fallback = dict(DEFAULT_WRAP_WIDTHS)
    if defaults:
        for key in LINE_WIDTH_KEYS:
            fallback[key] = _coerce_width(defaults.get(key), fallback[key], key)

    source = values if isinstance(values, Mapping) else {}
    normalized = {
        key: _coerce_width(source.get(key), fallback[key], key)
        for key in LINE_WIDTH_KEYS
    }
    normalized["faceWidth"] = min(normalized["width"], normalized["faceWidth"])
    return normalized


def _read_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GameSettingsError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GameSettingsError(f"Expected a JSON object in {path}")
    return data


def load_game_wrap_widths(game_root: str | Path) -> dict[str, int] | None:
    """Load saved wrap widths, or return ``None`` when the game has none yet."""
    game_metadata_dir(game_root)
    path = game_settings_path(game_root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameSettingsError(f"Game settings path is not a regular file: {path}")
    if not path.is_file():
        return None
    data = _read_settings(path)
    if "rpgmaker" not in data:
        # The file holds only other per-game settings, such as GameUpdate's.
        return None
    rpgmaker = data.get("rpgmaker")
    if not isinstance(rpgmaker, dict):
        raise GameSettingsError(f"Missing rpgmaker settings object in {path}")
    widths = rpgmaker.get("wrapWidths")
    if not isinstance(widths, dict):
        raise GameSettingsError(f"Missing rpgmaker.wrapWidths object in {path}")
    return normalize_wrap_widths(widths)


def load_translation_runtime_environment(
    dotenv_path: str | Path | None = None,
) -> dict[str, int] | None:
    """Load current global config, then restore the active game's widths.

    Translation subprocesses intentionally refresh ``.env`` before importing an
    engine. Per-game values must be applied afterwards or the refresh silently
    replaces them with the last global widths.
    """
    # These paths are selected by the GUI for this run. They are runtime state,
    # not global dotenv configuration, so preserve them across override loading
    # and ignore accidental/stale copies in .env.
    root = (os.getenv("DAZED_GAME_ROOT") or "").strip()
    glossary = (os.getenv(GLOSSARY_OVERRIDE_ENV) or "").strip()
    include_glossary_base = (
        os.getenv(GLOSSARY_BASE_ENABLED_ENV) or ""
    ).strip()
    load_dotenv(dotenv_path=dotenv_path, override=True)
    if root:
        os.environ["DAZED_GAME_ROOT"] = root
    else:
        os.environ.pop("DAZED_GAME_ROOT", None)
    if glossary:
        os.environ[GLOSSARY_OVERRIDE_ENV] = glossary
    else:
        os.environ.pop(GLOSSARY_OVERRIDE_ENV, None)
    if glossary and include_glossary_base:
        os.environ[GLOSSARY_BASE_ENABLED_ENV] = include_glossary_base
    else:
        os.environ.pop(GLOSSARY_BASE_ENABLED_ENV, None)
    if not root:
        return None
    saved = load_game_wrap_widths(root)
    if saved is None:
        return None
    for key, value in saved.items():
        os.environ[key] = str(value)
    return saved


def wrap_widths_saved(game_root: str | Path, values: Mapping) -> bool:
    """Whether the game already uses these wrap widths: the ones its settings
    hold, or its engine's stock ones while it holds none, which stay implicit
    until the user changes them."""
    try:
        return game_wrap_widths(game_root) == normalize_wrap_widths(values)
    except GameSettingsError:
        return False


def save_game_wrap_widths(
    game_root: str | Path,
    values: Mapping,
) -> Path:
    """Atomically save wrap widths while preserving unrelated game settings."""
    root = Path(game_root).expanduser().resolve()

    def update(data: dict) -> None:
        rpgmaker = data.get("rpgmaker")
        if rpgmaker is None:
            rpgmaker = {}
            data["rpgmaker"] = rpgmaker
        elif not isinstance(rpgmaker, dict):
            raise GameSettingsError(
                f"Expected rpgmaker to be an object in {game_settings_path(root)}"
            )
        rpgmaker["wrapWidths"] = normalize_wrap_widths(values)
        ensure_game_tool_gitignore(root)

    return _update_settings(root, update)


def load_game_update(game_root: str | Path) -> dict[str, str]:
    """The game's GameUpdate repository, the forge, host, owner and branch it
    sets itself, and the digest of the config DazedTL last wrote; empty
    before DazedTL has any."""
    game_metadata_dir(game_root)
    path = game_settings_path(game_root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameSettingsError(f"Game settings path is not a regular file: {path}")
    if not path.is_file():
        return {}
    value = _read_settings(path).get("gameUpdate", {})
    if not isinstance(value, dict):
        raise GameSettingsError(f"Expected gameUpdate to be an object in {path}")
    return {
        key: item
        for key, item in value.items()
        if key in GAME_UPDATE_KEYS and isinstance(item, str) and item
    }


def save_game_update(game_root: str | Path, values: Mapping[str, str]) -> Path:
    """Atomically replace the game's GameUpdate record, keeping other settings."""
    record = {key: values[key] for key in GAME_UPDATE_KEYS if values.get(key)}

    def update(data: dict) -> None:
        data["gameUpdate"] = record

    return _update_settings(Path(game_root).expanduser().resolve(), update)


def load_language_pair(game_root: str | Path) -> dict[str, str] | None:
    """The game's language pair, {"source", "target"}, which Set up records
    from Settings and every run on the game reads; None for a game set up
    before the pair was recorded, which translates Japanese into the target
    Settings name."""
    game_metadata_dir(game_root)
    path = game_settings_path(game_root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameSettingsError(f"Game settings path is not a regular file: {path}")
    if not path.is_file():
        return None
    value = _read_settings(path).get("languages")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"source", "target"}
        or not isinstance(value["target"], str)
        or not value["target"].strip()
    ):
        raise GameSettingsError(
            f"Expected languages to name a source and a target in {path}"
        )
    try:
        source = languages.source_language(value["source"])
    except ValueError as error:
        raise GameSettingsError(f"{error} ({path})") from error
    # A target DazedTL doesn't know, recorded before Set up refused one,
    # reads as Latin script until Set up changes it.
    known = languages.language(value["target"]) is not None
    problem = known and languages.pair_problem(source, value["target"])
    if problem:
        raise GameSettingsError(f"{problem} ({path})")
    return {"source": source, "target": value["target"].strip()}


def game_source_language(game_root: str | Path) -> str:
    """The language the game's text is written in: its pair's source, or
    Japanese for a game without a pair."""
    pair = load_language_pair(game_root)
    return pair["source"] if pair else languages.DEFAULT_SOURCE


def game_target_language(game_root: str | Path) -> str:
    """The language the game records it is translated into, read where only
    the game is known, such as in Text QA and when packing; English for a
    game without a pair or whose settings can't be read. Settings' target
    for a game without a pair is known only to the app."""
    try:
        pair = load_language_pair(game_root)
    except (OSError, ValueError):
        return "English"
    return pair["target"] if pair else "English"


def save_language_pair(game_root: str | Path, source: str, target: str) -> Path:
    """Atomically record the game's language pair, keeping other settings."""
    source = languages.source_language(source)
    problem = languages.pair_problem(source, target)
    if problem:
        raise GameSettingsError(problem)

    def update(data: dict) -> None:
        data["languages"] = {"source": source, "target": target.strip()}

    return _update_settings(Path(game_root).expanduser().resolve(), update)


def binding_bytes(raw: bytes) -> bytes | None:
    """The settings file's bytes as saved translation work binds them: without
    the GameUpdate record, which DazedTL rewrites on its own and no
    translation work reads, and without a pair whose source is Japanese, which
    names what a game without one reads (Japanese into the target its runs
    freeze), so recording it never makes saved work read Outdated. These are
    the bytes the file held before those records were added, or None when
    nothing else is left. A pair with another source binds the work."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return raw
    if not isinstance(data, dict):
        return raw
    pair = data.get("languages")
    japanese = isinstance(pair, dict) and pair.get("source") == languages.JAPANESE
    if "gameUpdate" not in data and not japanese:
        return raw
    data.pop("gameUpdate", None)
    if japanese:
        data.pop("languages")
    # Writing a record stamps a version on a file that did not exist yet.
    if set(data) <= {"version"}:
        return None
    return _serialize(data).encode("utf-8")


def _serialize(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _update_settings(root: Path, update) -> Path:
    if not root.is_dir():
        raise GameSettingsError(f"Game folder does not exist: {root}")
    try:
        game_metadata_dir(root)
    except Exception as exc:
        raise GameSettingsError(str(exc)) from exc
    path = game_settings_path(root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameSettingsError(f"Game settings path is not a regular file: {path}")
    data = _read_settings(path) if path.is_file() else {}
    data["version"] = 1
    update(data)
    try:
        game_metadata_dir(root, create=True)
    except Exception as exc:
        raise GameSettingsError(str(exc)) from exc

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_serialize(data))
            handle.flush()
            os.fsync(handle.fileno())
        system.replace(temporary, path)
    finally:
        system.unlink(temporary, ignore_errors=True)
    return path
