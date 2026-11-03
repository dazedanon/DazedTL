"""File preparation shared by RPG Maker Workflow and Len's Method."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil

from util.ace import rgssad
from util.paths import PROJECT_ROOT

# The template README is every published repository's player page; WOLF games
# get this section appended instead of a copy of the file.
WOLF_README_SECTION = "README.wolf.md"
GAMEUPDATE_COPY_SKIP_NAMES = frozenset({"previous_patch_sha.txt", WOLF_README_SECTION})
WOLF_ONLY_GAMEUPDATE_NAMES = frozenset({"UberWolfCli.exe", "UberWolfCli.LICENSE.txt"})
RPG_GAMEUPDATE_COPY_SKIP_NAMES = GAMEUPDATE_COPY_SKIP_NAMES | WOLF_ONLY_GAMEUPDATE_NAMES
# Reinstalling the helper keeps a game's own README.
GAMEUPDATE_PRESERVE_EXISTING = frozenset({"README.md"})
GAMEUPDATE_LAUNCHER = "GameUpdate.bat"
GAMEUPDATE_CONFIG = "gameupdate/patch-config.txt"
GAMEUPDATE_STATE = "gameupdate/previous_patch_sha.txt"
# What GameUpdate keeps in gameupdate/ on a player's computer, never in a
# patch: patch.ps1's Git for Windows, the folder it unpacks it in first, and
# the lock one run holds.
GAMEUPDATE_LOCAL_NAMES = frozenset({"mingit", "mingit.partial", "gameupdate.lock"})


def format_plugins_js(path: str | Path) -> int:
    import jsbeautifier

    path = Path(path)
    original = path.read_bytes()
    text = original.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    options.eol = "\n"
    formatted = jsbeautifier.beautify(text, options)
    # Write LF bytes on every platform; text writes would reintroduce CRLF.
    output = formatted.encode("utf-8")
    if output != original:
        path.write_bytes(output)
    return len(formatted)


def copy_files(src: str | Path, dst: str | Path, *, skip_names=frozenset(),
               preserve_existing=frozenset(), log=None) -> tuple[int, list[str]]:
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        return 0, [f"Source folder not found: {src}"]
    if src.resolve().is_relative_to(dst.resolve()) or dst.resolve().is_relative_to(src.resolve()):
        raise ValueError("Source and destination copy folders must not overlap.")
    dst.mkdir(parents=True, exist_ok=True)
    copied, errors = 0, []
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(src)
        target = dst / relative
        if path.name in skip_names or relative.as_posix() in preserve_existing and target.exists():
            if log:
                log(f"  kept/skipped {relative}")
            continue
        try:
            _game_path(dst, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
            if log:
                log(f"  copied {relative}")
        except Exception as exc:
            errors.append(f"{relative}: {exc}")
    return copied, errors


def gameupdate_local(relative: str) -> bool:
    """Whether the game-relative *relative* is in what GameUpdate keeps on the
    player's computer (GAMEUPDATE_LOCAL_NAMES)."""
    parts = [part.casefold() for part in PurePosixPath(relative).parts[:2]]
    return len(parts) == 2 and parts[0] == "gameupdate" and parts[1] in GAMEUPDATE_LOCAL_NAMES


def install_gameupdate(game_root: str | Path, *, wolf: bool = False, source: str | Path | None = None,
                       log=None) -> tuple[int, list[str]]:
    """Copy the bundled GameUpdate files; only WOLF games get UberWolf and its README section.

    Installing the files does not mean delivery works: whether the game's
    patch-config.txt is ready is reported separately by write_gameupdate_config.
    """
    root = Path(game_root)
    source = Path(source) if source is not None else PROJECT_ROOT / "gameupdate"
    readme = root / "README.md"
    new_readme = not readme.exists()
    copied, errors = copy_files(source, root, skip_names=GAMEUPDATE_COPY_SKIP_NAMES if wolf else RPG_GAMEUPDATE_COPY_SKIP_NAMES,
                                preserve_existing=GAMEUPDATE_PRESERVE_EXISTING, log=log)
    if wolf and new_readme and readme.is_file():
        try:
            section = (source / WOLF_README_SECTION).read_bytes()
            readme.write_bytes(readme.read_bytes().rstrip(b"\n") + b"\n\n" + section)
        except OSError as exc:
            errors.append(f"README.md: {exc}")
    return copied, errors


def gameupdate_installed(game_root: str | Path) -> bool:
    """Whether the game holds GameUpdate, by the rule its config writer uses."""
    from util.gameupdate_config import installed

    return installed(game_root)


def remove_gameupdate(game_root: str | Path, *, source: str | Path | None = None,
                      log=None) -> tuple[list[str], list[str]]:
    """Delete the GameUpdate files install_gameupdate copies, the config and
    state written beside them, and on MV/MZ the update check; the README stays,
    since it is the published repository's page. Returns the removed paths and
    any errors."""
    from util import system
    from util.translation_update_check.installer import uninstall as uninstall_check

    root = Path(game_root)
    source = Path(source) if source is not None else PROJECT_ROOT / "gameupdate"
    names = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
    names -= GAMEUPDATE_PRESERVE_EXISTING | {WOLF_README_SECTION}
    names |= {GAMEUPDATE_CONFIG, GAMEUPDATE_STATE}
    removed, errors = [], []
    for name in sorted(names):
        target = root / name
        try:
            _game_path(root, target)
            if target.is_file():
                system.unlink(target)
                removed.append(name)
                if log:
                    log(f"  removed {name}")
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    # GameUpdate's local Git and lock go too, though no patch holds them, so
    # the folder can go with them.
    for name in sorted(GAMEUPDATE_LOCAL_NAMES):
        target = root / "gameupdate" / name
        try:
            _game_path(root, target)
            if target.is_symlink() or target.is_file():
                system.unlink(target)
            elif target.is_dir():
                system.remove_tree(target)
            else:
                continue
            if log:
                log(f"  removed gameupdate/{name}")
        except (OSError, ValueError) as exc:
            errors.append(f"gameupdate/{name}: {exc}")
    folder = root / "gameupdate"
    try:
        if folder.is_dir() and not folder.is_symlink() and not any(folder.iterdir()):
            system.rmdir(folder)
    except OSError as exc:
        errors.append(f"gameupdate: {exc}")
    plugins = rpgmaker_layout(root)
    if plugins and plugins["plugins_js"]:
        check = plugins["plugins_js"].parent / "plugins/TranslationUpdateCheck.js"
        held = check.is_file()
        ok, message = uninstall_check(root)
        if not ok:
            errors.append(message)
        elif held:
            removed += [path.relative_to(root).as_posix() for path in (plugins["plugins_js"], check)]
    return removed, errors


def _game_path(root: Path, path: Path) -> Path:
    """Validate a selected game path before an in-place preparation write."""
    if not path.is_relative_to(root) or ".." in path.relative_to(root).parts:
        raise ValueError(f"Preparation path is outside the selected game: {path}")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            raise ValueError(f"Preparation cannot write through a symlink or junction: {current}")
    return path


def rpgmaker_layout(game_root: str | Path) -> dict | None:
    """Recognize actual RPG Maker layouts without treating arbitrary data JSON as RPG Maker."""
    root = Path(game_root)
    for base in (root / "www", root):
        plugins = base / "js/plugins.js"
        for data in (base / "data", base / "Data"):
            if (data / "System.json").is_file() and plugins.is_file():
                return {"engine": "MVMZ", "data_path": data, "plugins_js": plugins}
    native = root / "Data"
    if (native.is_dir() and any(native.glob("*.rvdata2"))) or rgssad.archives(root):
        return {"engine": "ACE", "data_path": root / "ace_json", "plugins_js": None}
    return None


def write_gameupdate_config(game_root: str | Path, *, env_path=None) -> tuple[bool, str]:
    """Write a missing or placeholder patch-config.txt from the saved defaults
    and the game's repository; a real one is kept. Returns (ready, message)."""
    from util.gameupdate_config import CONFIG, load_gameupdate_defaults, reconcile

    try:
        state = reconcile(game_root, load_gameupdate_defaults(env_path or PROJECT_ROOT / ".env"))
    except Exception as exc:  # noqa: BLE001 - preparation reports it and continues
        return False, f"could not write {CONFIG}: {exc}"
    if state["state"] == "ready":
        values = state["values"]
        return True, f"{CONFIG}: {values['host']}/{values['username']}/{values['repo']} ({values['branch']})"
    if state["state"] == "edited":
        return False, f"kept the edited {CONFIG}; its values differ from the saved settings"
    return False, f"skipped {CONFIG}: {state['message']}"


def install_startup_check(game_root: str | Path, *, settings_root: str | Path | None = None) -> tuple[bool, str]:
    """Install the update check, its text in the target language of the game
    at *settings_root*, the game itself unless named."""
    from util.translation_update_check import install

    ok, message = install(game_root, settings_root=settings_root)
    if ok:
        # The registration is part of preparation too; finish in the same
        # canonical layout so a second setup does not introduce formatting churn.
        for path in (Path(game_root) / "www/js/plugins.js", Path(game_root) / "js/plugins.js"):
            if path.is_file():
                format_plugins_js(path)
                break
    return ok, message


def prepare_rpgmaker(game_root: str | Path, *, data_path: str | Path | None = None,
                     gameupdate_source: str | Path | None = None, env_path=None, log=None,
                     gameupdate: bool = True) -> dict:
    """Run Workflow's three file-preparation steps, before the shared Git setup.

    Ace extraction/conversion is Workflow Step 0: supply its existing JSON export.
    Native Marshal files are never run through a text formatter. Without
    `gameupdate`, the third step takes GameUpdate and its startup check out
    instead of installing them.
    """
    from util.dazedformat import format_json_files

    root = Path(game_root).expanduser().resolve()
    layout = rpgmaker_layout(root)
    if layout is None:
        raise ValueError("No RPG Maker MV/MZ or Ace game was detected; other engines use their own preparation.")
    data = Path(data_path).expanduser() if data_path is not None else layout["data_path"]
    if not data.is_absolute():
        data = root / data
    data = _game_path(root, data)
    if layout["engine"] == "MVMZ" and data != layout["data_path"]:
        raise ValueError("MV/MZ preparation must use this game's detected data folder.")
    if not data.is_dir() or not any(data.glob("*.json")):
        raise ValueError("Extract/convert the Ace data using Workflow's tools first, then supply its JSON folder with --data-path.")
    json_files = [p for p in data.rglob("*") if p.suffix.lower() == ".json"]
    for path in json_files:
        _game_path(root, path)
    plugins = layout["plugins_js"]
    if plugins:
        _game_path(root, plugins)
        _game_path(root, plugins.parent / "plugins/TranslationUpdateCheck.js")
    source = Path(gameupdate_source) if gameupdate_source is not None else PROJECT_ROOT / "gameupdate"
    if not (source / GAMEUPDATE_LAUNCHER).is_file():
        raise ValueError(f"The bundled GameUpdate helper is missing: {source}")
    _game_path(root, root / GAMEUPDATE_CONFIG)

    emit = log or (lambda _message: None)
    emit("1. Format game data")
    count, errors = format_json_files(data, log=emit)
    if errors:
        raise ValueError("Game-data formatting failed; later preparation steps were not run. " + "; ".join(errors))
    emit("2. Format plugin configuration" if plugins else "2. Plugin configuration: not applicable to Ace")
    if plugins:
        format_plugins_js(plugins)
    result = {"engine": layout["engine"], "data_path": str(data), "formatted_json": count,
              "plugins_formatted": bool(plugins),
              "next_step": "Review preparation, then run git-setup before translating."}
    if not gameupdate:
        emit("3. Remove GameUpdate")
        removed, errors = remove_gameupdate(root, source=source, log=emit)
        if errors:
            raise ValueError("GameUpdate removal failed. " + "; ".join(errors))
        return {**result, "gameupdate_removed": removed}
    emit("3. Install GameUpdate")
    copied, errors = install_gameupdate(root, source=source, log=emit)
    if errors:
        raise ValueError("GameUpdate copy failed; Git setup must wait. " + "; ".join(errors))
    configured, config_message = write_gameupdate_config(root, env_path=env_path)
    emit(config_message)
    checker_message = "Startup check: not applicable to Ace"
    if plugins:
        installed, checker_message = install_startup_check(root)
        if not installed:
            raise ValueError(checker_message)
    emit(checker_message)
    return {**result, "gameupdate_files": copied, "config_written": configured,
            "config_status": config_message, "startup_check": checker_message}


def prepare_rpgmaker_patch(patch_root: str | Path, game_root: str | Path, *, log=None) -> dict:
    """Give an MV/MZ patch's files the preparation the game's own files had.

    The patch must be laid out as the game. Its data and plugin configuration
    then compare line by line with the prepared game, and the files it leaves
    out keep their preparation in the game.
    """
    from util.dazedformat import format_json_files

    root = Path(patch_root).expanduser().resolve()
    game = Path(game_root).expanduser().resolve()
    layout = rpgmaker_layout(game)
    if layout is None or layout["engine"] != "MVMZ":
        raise ValueError("Only RPG Maker MV/MZ patches are prepared here; other engines use their own preparation.")
    emit = log or (lambda _message: None)
    data = root / layout["data_path"].relative_to(game)
    count = 0
    if data.is_dir():
        emit("1. Format the patch's game data")
        count, errors = format_json_files(data, log=emit)
        if errors:
            raise ValueError("Patch data formatting failed. " + "; ".join(errors))
    plugins = root / layout["plugins_js"].relative_to(game)
    if plugins.is_file():
        emit("2. Format the patch's plugin configuration")
        _game_path(root, plugins)
        format_plugins_js(plugins)
        # The patch replaces plugins.js, so it needs the startup check again.
        installed, message = install_startup_check(root, settings_root=game)
        if not installed:
            raise ValueError(message)
        emit(message)
    return {"engine": "MVMZ", "formatted_json": count, "plugins_formatted": plugins.is_file()}
