"""Portable workflow options; the app registry owns only location and selection."""

from pathlib import Path

from dazedtl.storage import write_json

from .files import digest, project_path, read_json

WORK = ".dazedtl/len-method"
# The method of a Manual project's runs, which its plans name: the user's own
# tools extract and write the game's text, so DazedTL writes the game only to
# add or take out GameUpdate on the user's word, needs no Git baseline and
# keeps no assistant's progress report for them.
MANUAL = "manual"
# A Manual project's loaded file as the units its estimates organize.
MANUAL_UNITS = ".dazedtl/manual/units.json"
MODES = {"agent", "live", "batch"}
DEFAULTS = {
    "mode": "batch",
    "instructions": "",
    "include_images": True,
    "include_glossary_base": True,
    "install_forge": True,
    "install_gameupdate": True,
    "install_tl_inspector": False,
    "thorough_investigation": False,
    "text_qa": "release",
}
# Options added after workflow.json shipped, which older files and drafts lack.
ADDED = {
    "install_gameupdate": True,
    "install_tl_inspector": False,
    "thorough_investigation": False,
    "text_qa": "release",
}
# What Text QA reviews after injection: a focus of Guided's Check task, or
# only the mechanical checks (CHECKS). Only engines Text QA reads offer it.
TEXT_QA = ("release", "database", "dialogue", "risky-codes")
CHECKS = "checks"
# How the assistant works or what it installs rather than what it translates,
# so changing one keeps saved runs and their quotes current.
METHOD = {
    "mode",
    "install_gameupdate",
    "install_tl_inspector",
    "thorough_investigation",
    "text_qa",
}


def review_focus(selected):
    """The focus Text QA's review takes under the project's *selected*
    options, or None when it runs only the mechanical checks."""
    return None if selected["text_qa"] == CHECKS else selected["text_qa"]


def options(value):
    if isinstance(value, dict):
        value = {**ADDED, **value}
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("Invalid translation project options.")
    if not isinstance(value["mode"], str) or value["mode"] not in MODES:
        raise ValueError("Choose API Batch, Live API or Assistant only.")
    if (
        not isinstance(value["instructions"], str)
        or len(value["instructions"].encode("utf-8")) > 100_000
    ):
        raise ValueError("Keep project instructions below 100 KB.")
    if any(
        type(value[key]) is not bool
        for key in (
            "include_images",
            "include_glossary_base",
            "install_forge",
            "install_gameupdate",
            "install_tl_inspector",
            "thorough_investigation",
        )
    ):
        raise ValueError("Project scope choices must be enabled or disabled.")
    if value["text_qa"] not in (*TEXT_QA, CHECKS):
        raise ValueError("Choose a Text QA focus or the checks only.")
    return dict(value)


def scope(value):
    return digest({key: item for key, item in value.items() if key not in METHOD})


class ProjectWorkspace:
    def __init__(self, source):
        self.root = Path(source).expanduser().resolve(strict=True)
        if not self.root.is_dir() or self.root == self.root.parent:
            raise ValueError("Choose a game folder.")
        self.path = project_path(self.root, WORK + "/workflow.json", exists=False)

    def read(self, mode="batch"):
        """The saved options; a new project starts in `mode`, the API mode the
        active connection can run, and its revision names that default so a
        clean view follows when the default changes."""
        if self.path.exists():
            raw = self.path.read_bytes()
            value = read_json(self.path, limit=200_000)
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError(
                    "This translation project requires a compatible app version."
                )
            selected = options(value.get("options"))
            return {"options": selected, "revision": digest(raw), "initialized": True}
        selected = {**DEFAULTS, "mode": mode}
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
            selected["mode"] = "agent" if old["mode"] == "local" else mode
        return {
            "options": options(selected),
            "revision": "new:" + selected["mode"],
            "initialized": False,
        }

    def save(self, revision, selected, mode="batch"):
        before = self.read(mode)
        if revision != before["revision"]:
            raise ValueError("Project options changed elsewhere. Reload before saving.")
        value = options(selected)
        write_json(self.path, {"version": 1, "options": value})
        return self.read()

    def artifact(self, relative):
        return project_path(self.root, relative)
