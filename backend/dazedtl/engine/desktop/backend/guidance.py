"""Portable game guidance shared by guided projects and Len handoffs: the one
reader and the one save of the documents util.guidance_documents defines."""
from pathlib import Path
from util import system
from dazedtl.translation.git_status_cache import RepositoryStatusCache
from util.guidance_documents import CUSTOM_PREFIX, FIXED, GLOSSARY, defined, definition
from .project import digest
from .workflow_actions import regular

LIMIT = 1_000_000
# The revision each document had before a save `_replaced` finds in its
# history, or None.
_recoveries = RepositoryStatusCache(stable=True)


class Unreadable(Exception):
    """Why a document's file can't be read, and how to make it readable."""

    def __init__(self, why, fix):
        super().__init__(why)
        self.why, self.fix = why, fix


def definitions(root, drafted=()):
    """The game's documents in the editors' order: the fixed ones, then each
    custom skill its skills folders hold or `drafted` names, as a draft of a
    skill whose file was deleted does."""
    root = Path(root)
    stems = {key.removeprefix(CUSTOM_PREFIX) for key in drafted if key.startswith(CUSTOM_PREFIX)}
    for parent in (root / ".dazedtl/skills", root / "skills"):
        # Only names: a skill in a linked folder is listed and reads as
        # unreadable through the link, so requests never leave it out
        # unsaid, and the other documents stay readable.
        stems.update(path.stem for path in parent.glob("*.md"))
    return [*FIXED, *sorted(filter(None, (definition(CUSTOM_PREFIX + stem) for stem in stems)), key=lambda found: found.key)]


def read(root, drafts=()):
    """Every guidance document of the game, keyed by name in the editors'
    order, each with its definition's title, kind, whether requests carry it
    and the work its draft holds up, and its file's `state`: "saved" with
    its text and revision, "missing" as empty, or "unreadable" with the
    `reason` saying why and how to fix it. `drafts`, the drafts' names or
    the drafts, lists a custom skill whose file is gone, and a draft says
    whether its document's file `changed` on disk since it began."""
    root = Path(root)
    result = {}
    for found in definitions(root, drafts):
        document = result[found.key] = _document(root, found)
        draft = drafts.get(found.key) if isinstance(drafts, dict) else None
        if isinstance(draft, dict) and isinstance(draft.get("text"), str):
            document["changed"] = _changed(root, found.key, document, draft.get("revision"), draft.get("text"))
    return result


def documents(root):
    """The documents translation requests carry, read as `read` reads them;
    one whose file can't be read refuses the work that needs it, saying
    why."""
    root = Path(root)
    result = {}
    for found in definitions(root):
        if found.requests:
            document = result[found.key] = _document(root, found)
            if document["state"] == "unreadable":
                raise ValueError(document["reason"])
    return result


def _changed(root, name, document, revision, text):
    """Whether `document`'s file changed on disk since a draft holding
    `text` began from its `revision`, as an assistant changes it: the file
    moved past that revision and doesn't hold the text, and no save that
    wrote the file and then made no checkpoint replaced that revision, as
    the draft then still has it. A file that can't be read is its own
    state."""
    if document["state"] == "unreadable":
        return False
    if document["state"] == "missing" and revision == "":
        revision = digest(b"")
    return document["revision"] != revision and not holds(name, document, text) and not _replaced(root, name, document, revision)


def _files(root, found):
    """The files that hold `found`'s document: its own and its legacy ones,
    or every case of the notes' name."""
    if found.any_case:
        from util.paths import game_notes_files

        return game_notes_files(root)
    candidates = (root / relative for relative in (found.path, *found.legacy))
    return [path for path in candidates if path.exists() or path.is_symlink()]


def document_files(root, name):
    """Every file in the game holding the document `name`, by its name in the
    game: its own, its legacy ones, or every case of the notes' name."""
    root = Path(root)
    return [path.relative_to(root).as_posix() for path in _files(root, defined(name))]


def _document(root, found):
    files = _files(root, found)
    path = files[0] if files else root / found.path
    name = path.relative_to(root).as_posix()
    document = {
        "path": str(path),
        "file": name,
        "title": found.title,
        "kind": found.kind,
        "requests": found.requests,
        "holdsUp": sorted(found.holds_up),
        "description": found.description,
        "help": found.help.format(file=name),
        "changed": False,
    }
    try:
        if len(files) > 1:
            raise Unreadable(f"{files[1].relative_to(root).as_posix()} holds it too", "Keep one of them")
        if through_link(root, path):
            raise Unreadable("its folder is a link, and DazedTL reads only the game's own folders", "Put the folder in its place")
        if not files:
            return {**document, "text": "", "revision": digest(b""), "state": "missing"}
        text = stored(found.key, _read(root, path))
    except Unreadable as error:
        reason = f"DazedTL can't read {name}: {error.why}. {error.fix}, and DazedTL reads it again."
        return {**document, "text": "", "revision": "", "state": "unreadable", "reason": reason}
    return {**document, "text": text, "revision": digest(text.encode()), "state": "saved"}


def through_link(root, path):
    """Whether `path` in the game is reached through a linked folder, as a
    file in a linked skills folder is, which DazedTL neither reads nor
    moves, since the folder holding it is outside the game."""
    root = Path(root)
    return any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(root) and parent != root)


def _read(root, path):
    """A document's file as text: a regular file below 1 MB, in UTF-8 or in
    UTF-16 with its byte order mark, as Windows PowerShell 5's Out-File and
    `>` write it. Its Set-Content writes the ANSI code page, such as cp1252
    or cp932, which can't be told from other bytes, so such a file is
    unreadable until it is saved as UTF-8."""
    try:
        regular(root, path)
    except ValueError:
        if path.is_symlink():
            raise Unreadable("it is a link, and DazedTL reads only the file itself", "Put the file in its place") from None
        if path.is_dir():
            raise Unreadable("it is a folder, not a file", "Move it out of the way") from None
        raise Unreadable("it isn't a regular file", "Put a text file in its place") from None
    try:
        if path.stat().st_size > LIMIT:
            raise Unreadable("it is larger than 1 MB", "Shorten it")
        raw = path.read_bytes()
    except PermissionError:
        raise Unreadable("DazedTL isn't allowed to open it, as when another program holds it", "Close that program or let DazedTL read it") from None
    except OSError as error:
        raise Unreadable(f"it can't be opened ({error.strerror or error})", "Fix the file") from None
    try:
        return raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unreadable("it isn't saved as UTF-8 or UTF-16 text", "Save it as UTF-8, or delete it") from None


def whole(root, path):
    """A guidance file's whole text as `read` decodes it, a glossary's
    shipped base included, or "" for one missing or unreadable."""
    path = Path(path)
    try:
        return _read(Path(root), path) if path.is_file() else ""
    except Unreadable:
        return ""


def stored(name, text):
    """`text` as `read` reads it back from a file that holds it: a glossary
    file also keeps the shipped base, which is not part of it."""
    if name == GLOSSARY.key:
        from util.vocab import _split_base
        return _split_base(text)[0].rstrip("\n")
    return text


def holds(name, document, text):
    """Whether `document`, as `read` reads it, already holds `text`."""
    return document.get("text") == stored(name, text)


def written(root, names):
    """The game files saving the guidance documents `names` may change, which
    a game write names: their own files, in any case the notes' file has,
    the legacy files the save moves into .dazedtl, which are a document's
    own and, for any skill, the former root skills folder, and the
    .gitignore keeping DazedTL's rules once the game's Git is set up."""
    from util.paths import LEGACY_GAME_SKILLS_RELATIVE, game_git_set_up
    root = Path(root)
    chosen = [defined(name) for name in names]
    own, moved = [], []
    for found in chosen:
        own += [found.path, *(path.relative_to(root).as_posix() for path in _files(root, found))]
        moved += found.legacy
    if any(found.skill for found in chosen):
        moved += [path.relative_to(root).as_posix() for path in (root / LEGACY_GAME_SKILLS_RELATIVE).rglob("*") if not path.is_dir()]
    present = [path for path in moved if (root / path).exists() or (root / path).is_symlink()]
    return list(dict.fromkeys(own + present)) + ([".gitignore"] if game_git_set_up(root) else [])


def _replaced(root, name, held, revision):
    """Whether a save whose write ended without its checkpoint, committed
    since under its own name, replaced this document at `revision` with what
    its file holds, so a draft based on that revision overwrites no one
    else's change. Every read with a draft asks it, so the answer from Git
    is reused until the repository or the file moves."""
    from dazedtl.compatibility.checkpoint_commits import recovered_text
    try:
        relative = Path(held["path"]).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return False
    def before():
        found = recovered_text(root, relative)
        return None if found is None else digest(stored(name, found[0] or "").encode())

    return _recoveries.get((str(root), relative), root, before, (held["revision"],)) == revision


def _target(root, found, document):
    """The file a save writes `found`'s document to: its portable file, into
    which the skills' path functions move a legacy one, or the notes' file
    in the case the game folder has it."""
    from util.skills import custom_skill_path_for_game, game_skill_path_for_game, quirks_path_for_game
    paths = {"quirks": quirks_path_for_game, "game": game_skill_path_for_game}
    if found.kind == "custom":
        return custom_skill_path_for_game(root, found.key.removeprefix(CUSTOM_PREFIX))
    if found.key in paths:
        return paths[found.key](root)
    return Path(document["path"])


def documents_save(root, changes):
    """Saves a set of guidance documents, {name: {revision, text}}, checking
    every one before writing any, so a refused set changes no file, and
    returns the names it wrote. A change's revision is the file's when its
    draft began: a file changed on disk since (`_changed`) is replaced only
    by a draft the user chose to keep, which takes the file's current
    revision. A file that can't be read is never saved over, and a document
    created only with text whose file is missing is not created empty."""
    root = Path(root)
    if not isinstance(changes, dict):
        raise ValueError("Choose a guidance document below 1 MB.")
    current = read(root, [name for name in changes if isinstance(name, str)])
    for name, change in changes.items():
        text = change.get("text") if isinstance(change, dict) else None
        if definition(name) is None or not isinstance(text, str) or len(text.encode()) > LIMIT:
            raise ValueError("Choose a guidance document below 1 MB.")
        held = current[name]
        if held["state"] == "unreadable":
            raise ValueError(held["reason"])
        if _changed(root, name, held, change.get("revision"), text):
            raise ValueError(
                f"{Path(held['path']).relative_to(root).as_posix()} changed on disk after your {held['title']} draft began."
                " Save again to choose whether to keep the file or your draft."
            )
    saved = [
        name for name, change in changes.items()
        if change["text"] or current[name]["state"] != "missing" or defined(name).created == "always"
    ]
    # Every file's place, which moving a legacy file or refusing a folder
    # decides, before any is written, so a refused set writes nothing.
    if GLOSSARY.key in saved:
        from util.paths import validate_game_glossary_migration
        validate_game_glossary_migration(root)
    targets = {name: _target(root, defined(name), current[name]) for name in saved if name != GLOSSARY.key}
    for name in saved:
        text = changes[name]["text"]
        if name == GLOSSARY.key:
            from util.vocab import write_game_vocab
            write_game_vocab(text, game_root=root)
            continue
        path = targets[name]
        # A file outside DazedTL's folder, as the notes are, is written
        # beside DazedTL's own files, which no record of the original game
        # holds.
        inside = path.parent.resolve().is_relative_to((root / ".dazedtl").resolve())
        staging = path.parent if inside else root / ".dazedtl"
        staging.mkdir(parents=True, exist_ok=True)
        temporary = staging / (path.name + ".desktop-tmp")
        regular(root, temporary).write_text(text, encoding="utf-8", newline="\n")
        system.replace(temporary, path)
        if not inside:
            # A game whose patch rules ignore the rest of its root keeps
            # the file in Git all the same.
            from util.paths import ensure_game_tool_gitignore
            ensure_game_tool_gitignore(root)
    return saved


def valid_document_name(name):
    return definition(name) is not None
