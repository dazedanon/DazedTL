"""Game identity and translation method, independent of the visible screen."""

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import WorkspaceError, read_versioned_json, write_json

METHODS = {"guided", "len", "translation"}
SCREENS = {"overview", "translation", "guided", "manual", "settings"}
SCHEMA_VERSION = 4


def upgrade_v1(value):
    if (
        not isinstance(value.get("projects"), list)
        or any(
            not isinstance(project, dict)
            or project.get("method") not in {"guided", "len"}
            for project in value["projects"]
        )
        or value.get("screen") not in {"overview", "guided", "settings"}
    ):
        raise ValueError("Invalid version-one project registry.")
    upgraded = deepcopy(value)
    if upgraded["screen"] == "guided":
        upgraded["screen"] = "translation"
    return upgraded


def upgrade_v2(value):
    if value.get("screen") not in {"overview", "translation", "settings"}:
        raise ValueError("Invalid version-two project registry.")
    return deepcopy(value)


def upgrade_v3(value):
    # Older clients cannot validate the expanded per-game Guided forms. Keep
    # registry identity/run links intact; form readers supply missing defaults.
    return deepcopy(value)


UPGRADES = {1: upgrade_v1, 2: upgrade_v2, 3: upgrade_v3}


def validate(value):
    invalid = WorkspaceError(
        "workspace_invalid",
        "Saved project data is invalid. The file was left unchanged.",
    )
    if (
        not isinstance(value.get("projects"), list)
        or not isinstance(value.get("screen"), str)
        or value.get("screen") not in SCREENS
    ):
        raise invalid
    identities = set()
    for project in value["projects"]:
        if not isinstance(project, dict) or any(
            not isinstance(project.get(field), str) or not project[field]
            for field in ("id", "name", "source", "engine", "method", "phase")
        ):
            raise invalid
        if project["id"] in identities or project["method"] not in METHODS:
            raise invalid
        if not isinstance(project.get("last_opened", ""), str) or not isinstance(
            project.get("backend_id", ""), str
        ):
            raise invalid
        identities.add(project["id"])
    current = value.get("current_id")
    if not isinstance(current, str) or (current and current not in identities):
        raise invalid


class Projects:
    def __init__(self, workspace):
        self.path = Path(workspace) / "projects.json"
        self.data = read_versioned_json(
            self.path,
            {
                "version": SCHEMA_VERSION,
                "current_id": "",
                "screen": "overview",
                "projects": [],
            },
            UPGRADES,
            validate,
        )

    def save(self):
        self._commit(self.data)

    def _commit(self, data):
        validate(data)
        write_json(self.path, data)
        self.data = data

    @staticmethod
    def _get(data, project_id):
        project = next((p for p in data["projects"] if p["id"] == project_id), None)
        if not project:
            raise ValueError("Choose an available project.")
        return project

    def get(self, project_id):
        return self._get(self.data, project_id)

    @property
    def current(self):
        return self.get(self.data["current_id"]) if self.data["current_id"] else None

    def open(self, detected, method="translation"):
        if method not in METHODS:
            raise ValueError("Choose a supported translation project.")
        source = str(Path(detected["source"]).resolve())
        data = deepcopy(self.data)
        project = next((p for p in data["projects"] if p["source"] == source), None)
        if not project:
            project = {
                "id": uuid.uuid4().hex,
                "name": Path(source).name,
                "source": source,
                "engine": detected["engine"],
                "method": method,
                "backend_id": "",
                "phase": "database",
            }
            data["projects"].append(project)
        # Reopening a game does not infer a different method from the screen.
        project["engine"] = detected["engine"]
        return self._select(data, project)

    def select(self, project_id):
        data = deepcopy(self.data)
        return self._select(data, self._get(data, project_id))

    def _select(self, data, project):
        project["last_opened"] = datetime.now(UTC).isoformat()
        data["current_id"] = project["id"]
        data["screen"] = "overview"
        self._commit(data)
        return project

    def navigate(self, screen):
        if screen not in SCREENS:
            raise ValueError("That page is not available.")
        if screen in {"translation", "guided", "manual"} and not self.current:
            raise ValueError("Open a game project first.")
        data = deepcopy(self.data)
        data["screen"] = screen
        self._commit(data)

    def state(self):
        return {
            "project": self.current,
            "screen": self.data["screen"],
            "recent": sorted(
                self.data["projects"],
                key=lambda p: p.get("last_opened", ""),
                reverse=True,
            )[:8],
        }
