"""Game identity and translation method, independent of the visible screen."""

from datetime import datetime, timezone
from pathlib import Path
import uuid

from dazedtl.storage import WorkspaceError, read_versioned_json, write_json

METHODS = {"guided", "len"}
SCREENS = {"overview", "guided", "settings"}
SCHEMA_VERSION = 1
# Register N -> N+1 transformations here when the persisted format changes.
UPGRADES = {}


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
        validate(self.data)
        write_json(self.path, self.data)

    def get(self, project_id):
        project = next((p for p in self.data["projects"] if p["id"] == project_id), None)
        if not project:
            raise ValueError("Choose an available project.")
        return project

    @property
    def current(self):
        return self.get(self.data["current_id"]) if self.data["current_id"] else None

    def open(self, detected, method):
        if method not in METHODS:
            raise ValueError("Choose Guided Workflow or Len’s Method.")
        source = str(Path(detected["source"]).resolve())
        project = next((p for p in self.data["projects"] if p["source"] == source), None)
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
            self.data["projects"].append(project)
        # Reopening a game does not infer a different method from the screen.
        project["engine"] = detected["engine"]
        self.select(project["id"])
        return project

    def select(self, project_id):
        project = self.get(project_id)
        project["last_opened"] = datetime.now(timezone.utc).isoformat()
        self.data["current_id"] = project_id
        self.data["screen"] = "overview"
        self.save()
        return project

    def navigate(self, screen):
        if screen not in SCREENS:
            raise ValueError("That page is not available.")
        if screen == "guided" and (not self.current or self.current["method"] != "guided"):
            raise ValueError("Open a Guided Workflow project first.")
        self.data["screen"] = screen
        self.save()

    def state(self):
        return {
            "project": self.current,
            "screen": self.data["screen"],
            "recent": sorted(self.data["projects"], key=lambda p: p.get("last_opened", ""), reverse=True)[:8],
        }
