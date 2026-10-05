"""Portable workflow options; the app registry owns only location and selection."""

from pathlib import Path

from dazedtl.storage import write_json
from .files import digest, read_json, project_path


WORK = ".dazedtl/len-method"
MODES = {"agent", "live", "batch"}
DEFAULTS = {
    "mode": "agent",
    "instructions": "",
    "include_images": True,
    "include_glossary_base": True,
    "install_forge": True,
}


def options(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("Invalid translation project options.")
    if not isinstance(value["mode"], str) or value["mode"] not in MODES:
        raise ValueError("Choose Agent, Live API, or API Batch Translation.")
    if (
        not isinstance(value["instructions"], str)
        or len(value["instructions"].encode("utf-8")) > 100_000
    ):
        raise ValueError("Keep project instructions below 100 KB.")
    if any(
        type(value[key]) is not bool
        for key in ("include_images", "include_glossary_base", "install_forge")
    ):
        raise ValueError("Project scope choices must be enabled or disabled.")
    return dict(value)


def scope(value):
    return digest({key: item for key, item in value.items() if key != "mode"})


class ProjectWorkspace:
    def __init__(self, source):
        self.root = Path(source).expanduser().resolve(strict=True)
        if not self.root.is_dir() or self.root == self.root.parent:
            raise ValueError("Choose a game folder.")
        self.path = project_path(self.root, WORK + "/workflow.json", exists=False)

    def read(self):
        if self.path.exists():
            raw = self.path.read_bytes()
            value = read_json(self.path, limit=200_000)
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError(
                    "This translation project requires a compatible app version."
                )
            selected = options(value.get("options"))
            return {"options": selected, "revision": digest(raw), "initialized": True}
        selected = dict(DEFAULTS)
        legacy = project_path(self.root, WORK + "/project.json", exists=False)
        if legacy.exists():
            old = read_json(legacy, limit=200_000)
            if (
                not isinstance(old, dict)
                or old.get("version") not in {1, 2, 3}
                or not isinstance(old.get("mode"), str)
                or old.get("mode") not in {"local", "api"}
            ):
                raise ValueError(
                    "The existing Len project needs review before it can be imported."
                )
            selected.update(
                {key: old[key] for key in selected if key != "mode" and key in old}
            )
            selected["mode"] = "agent" if old["mode"] == "local" else "batch"
        return {"options": options(selected), "revision": "new", "initialized": False}

    def save(self, revision, selected):
        before = self.read()
        if revision != before["revision"]:
            raise ValueError("Project options changed elsewhere. Reload before saving.")
        value = options(selected)
        write_json(self.path, {"version": 1, "options": value})
        return self.read()

    def artifact(self, relative):
        return project_path(self.root, relative)
