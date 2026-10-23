"""Where each project's game is, and which project a game folder belongs to.

The registry (store.py) is the only record of where a project's game is:
every other profile record names its project and finds the game through it
(`registered`), so a move changes one record. A game folder names its project
in `.git/dazedtl/project.json`, which Git never commits, so no checkpoint,
patch, package or archive carries it; a game from before then names its
project only in the progress Plugin files or Images saved in it. A project
this profile doesn't know, such as another profile's, names nothing here.

Opening a folder that names a project registered elsewhere continues that
project there when its old location no longer holds the game (`holds`): the
game was moved or renamed, also into a folder inside its old one. When the
old location still holds it, the folder is a copy and opens as a project of
its own, as a folder no project names does. A project made for the new
location before the move is replaced, hidden and never deleted, unless it has
saved work of its own; then both stay, and the folder keeps that project.
"""

import json
from pathlib import Path

from dazedtl import system
from dazedtl.projects import store
from dazedtl.projects.store import UNRECOGNIZED
from dazedtl.translation.files import read_json

MARKER = "dazedtl/project.json"
# Saved progress that names the project that saved it, read for a game from
# before the marker: Plugin files' and Images' state.
CLAIMS = (".dazedtl/plugin-work/state.json", ".dazedtl/image_manager/guided/state.json")
BUSY = "Finish or stop the running work before opening this game in its new location."


def _marker(root):
    """The marker's path, in the game's own repository; a game without one,
    or whose `.git` points elsewhere, has none, since a parent folder's
    repository is never the game's."""
    git = Path(root) / ".git"
    return git / MARKER if git.is_dir() and not git.is_symlink() else None


def _project_id(path, limit, known):
    try:
        value = read_json(path, limit=limit)
    except OSError, ValueError, UnicodeError:
        return None
    identity = value.get("projectId") if isinstance(value, dict) else None
    return identity if isinstance(identity, str) and identity in known else None


def marked(root, known):
    """The project of `known` the game's marker names, or None."""
    path = _marker(root)
    return _project_id(path, 64_000, known) if path and path.is_file() else None


def claimed(root, known, worked=lambda identity: True):
    """The project of `known` the game folder belongs to by its marker, or
    for a game from before it, by the progress it saved, which must agree.
    A marker naming a project without saved work (`worked`) yields to
    progress naming another, as when the moved game was opened as a new
    project before its own was found."""
    identity = marked(root, known)
    if identity and worked(identity):
        return identity
    claims = {
        _project_id(path, None, known)
        for path in (Path(root) / name for name in CLAIMS)
        if path.is_file()
    } - {None}
    return claims.pop() if len(claims) == 1 else identity


def mark(root, project_id):
    """Names project_id in the game's marker once its repository exists. A
    marker that can't be written, such as in a read-only repository, leaves
    the game to its saved progress or its folder to name its project."""
    path = _marker(root)
    if path is None or marked(root, {project_id}):
        return
    try:
        system.write_text(
            path, json.dumps({"version": 1, "projectId": project_id}) + "\n"
        )
    except OSError:
        pass


def keep(root, project_id, known):
    """mark, unless the game names another project, which only opening the
    folder decides about (Locations.open)."""
    if claimed(root, known) in {None, project_id}:
        mark(root, project_id)


def holds(project, detect, known):
    """Whether the project's registered location still holds its game: the
    folder there names this project, or, naming none of `known`, has a game's
    files at its root. A game found only inside it, as after a move into a
    subfolder, is not there. A project whose engine was never recognized
    counts any folder there that names no other project. Guided steps link
    (`backend_id`) only a recognized RPG Maker game, so a linked project's
    unrecognized engine is one earlier versions saved over it when its old
    folder was opened after the move."""
    root = Path(project["source"])
    if not root.is_dir():
        return False
    identity = marked(root, known)
    if identity:
        return identity == project["id"]
    never_recognized = project["engine"] == UNRECOGNIZED and not project.get(
        "backend_id"
    )
    return never_recognized or detect(root) != UNRECOGNIZED


# The workspace whose registry this process's game writes consult (`adopt`):
# each app and worker process serves one profile.
_workspace = []


def use(workspace):
    """Names the workspace whose projects this process writes games for."""
    _workspace[:] = [Path(workspace)]


def adopt(root):
    """Names the project registered at root in the marker of the repository
    DazedTL just made for it, so a game set up and then moved before it is
    opened again still finds its project."""
    if not _workspace:
        return
    projects = store.saved(_workspace[0])
    project = store.registered_at(projects, Path(root).resolve())
    if project:
        keep(root, project["id"], {p["id"] for p in projects})


def registered(workspace, project_id):
    """The game folder the registry in workspace gives project_id, for a
    store without the app's registry, such as a run's in its worker."""
    found = next((p for p in store.saved(workspace) if p["id"] == project_id), None)
    if found is None:
        raise ValueError("This run's project is not in the project list.")
    return found["source"]


def owners(workspace):
    """The game folder of each Guided workspace the registry links, by the
    workspace's ID."""
    return {
        p["backend_id"]: p["source"]
        for p in store.saved(workspace)
        if isinstance(p.get("backend_id"), str) and p["backend_id"]
    }


def workflow_game(folder):
    """The game folder of the project whose Guided workspace holds folder,
    a path inside `<workspace>/engine/workflows/<id>/`, or None."""
    folder = Path(folder).resolve()
    for parent in folder.parents:
        if parent.parent.name == "workflows" and parent.parent.parent.name == "engine":
            return owners(parent.parent.parent.parent).get(parent.name)
    return None


class Locations:
    """Opens game folders as projects and moves projects to where their game
    went. `detect` names a folder's engine, `has_work` tells whether a
    project holds saved work, `busy` whether a run's worker is executing, and
    `relocate` publishes a move, given the moved project and its folder
    before, to the stores that keep its game in memory."""

    def __init__(self, projects, *, detect, has_work, busy, relocate):
        self.projects = projects
        self.detect = detect
        self.has_work = has_work
        self.busy = busy
        self.relocate = relocate

    @property
    def known(self):
        return {p["id"] for p in self.projects.data["projects"]}

    def holds(self, project):
        return holds(project, self.detect, self.known)

    def claimed(self, root):
        return claimed(
            root,
            self.known,
            lambda identity: self.has_work(self.projects.get(identity)),
        )

    def keep(self, project):
        """Names the open project in its game, unless it names another."""
        keep(project["source"], project["id"], self.known)

    def open(self, root, chosen=None):
        """Opens the game at root as the project it belongs to; chosen is the
        recent project picked, whose folder root is. A pick waits for the
        work running now before it moves another project there."""
        root = Path(root)
        detected = {"source": str(root), "engine": self.detect(root)}
        identity = self.claimed(root)
        owner = next(
            (p for p in self.projects.data["projects"] if p["id"] == identity), None
        )
        here = chosen or self.projects.at(detected["source"])
        moved = (
            owner is not None
            and owner["source"] != detected["source"]
            and not self.holds(owner)
            and not (here is not None and self.has_work(here))
        )
        if owner is not None and owner["source"] == detected["source"]:
            project = self.projects.open(detected, identity=owner["id"])
        elif moved and chosen is not None and self.busy():
            # The game stays its owner's to move once nothing runs.
            return self.projects.open(detected, identity=chosen["id"])
        elif moved:
            project = self._move(owner, detected, here)
        else:
            # The folder's own project, a copy or a game no project names.
            project = self.projects.open(
                detected, identity=here["id"] if here else None
            )
        mark(root, project["id"])
        return project

    def find(self, project_id, root):
        """Find game folder: moves the project to root once root is its game."""
        project = self.projects.get(project_id)
        root = Path(root)
        detected = {"source": str(root), "engine": self.detect(root)}
        identity = self.claimed(root)
        if identity and identity != project_id:
            raise ValueError("That folder holds another project's game.")
        if not identity and project["engine"] not in {UNRECOGNIZED, detected["engine"]}:
            raise ValueError("That folder doesn't hold this project's game.")
        if detected["source"] != project["source"] and self.holds(project):
            raise ValueError(
                "This project's game is still in its folder; open the other one as a project of its own."
            )
        here = self.projects.at(detected["source"])
        if here is not None and here["id"] != project_id and self.has_work(here):
            raise ValueError(
                "Another project with saved work uses that folder; open it from the recent list."
            )
        moved = self._move(project, detected, here)
        mark(root, project_id)
        return moved

    def _move(self, project, detected, here):
        if project["source"] == detected["source"]:
            return self.projects.open(detected, identity=project["id"])
        if self.busy():
            raise ValueError(BUSY)
        before = project["source"]
        replaced = (
            here["id"] if here is not None and here["id"] != project["id"] else None
        )
        moved = self.projects.move(project["id"], detected, replaced)
        self.relocate(moved, before)
        return moved
