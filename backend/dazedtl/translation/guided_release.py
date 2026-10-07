"""The setup and release form, release readiness and patch manifests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from dazedtl.storage import write_json

from . import backups
from .files import read_json
from .operations import lifecycle

if TYPE_CHECKING:
    from .guided import Guided


class GuidedRelease:
    def __init__(self, guided: Guided):
        self.guided = guided

    def form(self, project_id, value):
        self.guided.record(project_id)
        value = self.form_value(project_id, value)
        write_json(self.guided.path(project_id, "form"), value)
        return {"saved": True}

    def form_value(self, project_id, value):
        if (
            not isinstance(value, dict)
            or set(value)
            - {
                "version",
                "original",
                "untranslated",
                "only_overflow",
                "release",
                "text",
            }
            or {"version", "original", "untranslated", "only_overflow"} - set(value)
            or any(
                not isinstance(value[key], str)
                or len(value[key]) > 10000
                or "\0" in value[key]
                for key in ("version", "original")
            )
            or value.get("untranslated") is not None
            and type(value["untranslated"]) is not bool
            or type(value.get("only_overflow")) is not bool
        ):
            raise ValueError("Invalid guided form values.")
        text = value.get(
            "text",
            {
                "view": "apply",
                "categories": ["dialogue", "face_dialogue", "list", "notes"],
                "codes": "401,405",
                "max_rows": 4,
                "protect_rows": True,
                "focus": "release",
                "findings": [],
            },
        )
        if isinstance(text, dict):
            text = {"findings_task": "", **text}
        if (
            not isinstance(text, dict)
            or set(text)
            != {
                "view",
                "categories",
                "codes",
                "max_rows",
                "protect_rows",
                "focus",
                "findings_task",
                "findings",
            }
            or text["view"] not in {"apply", "fitting", "qa", "tools"}
            or not isinstance(text["categories"], list)
            or any(
                item not in {"dialogue", "face_dialogue", "list", "notes"}
                for item in text["categories"]
            )
            or not isinstance(text["codes"], str)
            or len(text["codes"]) > 100
            or type(text["max_rows"]) is not int
            or not 1 <= text["max_rows"] <= 100
            or type(text["protect_rows"]) is not bool
            or text["focus"] not in {"release", "database", "dialogue", "risky-codes"}
            or not isinstance(text["findings_task"], str)
            or len(text["findings_task"]) > 10000
            or not isinstance(text["findings"], list)
            or any(
                not isinstance(item, str) or len(item) > 200
                for item in text["findings"]
            )
        ):
            raise ValueError("Invalid fitting or optional QA choices.")
        return {
            **value,
            "text": deepcopy(text),
            "release": self.validate_release_form(
                value.get("release", self.release_defaults(project_id))
            ),
        }

    def release_defaults(self, project_id):
        source = Path(self.guided.projects.get(project_id)["source"])
        return {
            "kind": "game",
            "name": source.name + "-game.zip",
            "names": {
                "game": source.name + "-game.zip",
                "patch": source.name + "-patch.zip",
            },
            "assets": [],
            "directory": str(source.parent),
            "tools": {
                "hotkey": "F9",
                "forgeHotkey": "F10",
                "uiScale": "auto",
                "editorCmd": "auto",
            },
        }

    def release_destination(self, project_id, output):
        """Reads whether a release ZIP may be written there, without writing."""
        from .release import destination

        project, _ = self.guided.record(project_id)
        try:
            destination(
                project["source"],
                self.guided.translation.workspace,
                self.guided.backend.source,
                output,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"error": ""}

    @staticmethod
    def validate_release_form(value):
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            value = deepcopy(value)
            stem = (
                Path(value.get("name", "game.zip"))
                .stem.removesuffix("-public")
                .removesuffix("-game")
                .removesuffix("-patch")
            )
            value.setdefault(
                "names", {"game": stem + "-game.zip", "patch": stem + "-patch.zip"}
            )
            value.setdefault("assets", [])
        if (
            not isinstance(value, dict)
            or set(value) != {"kind", "name", "names", "assets", "directory", "tools"}
            or not isinstance(value["kind"], str)
            or value["kind"] not in {"game", "patch"}
            or any(
                not isinstance(value[key], str)
                or len(value[key]) > 10000
                or "\0" in value[key]
                for key in ("name", "directory")
            )
        ):
            raise ValueError("Invalid release options.")
        if (
            not isinstance(value["names"], dict)
            or set(value["names"]) != {"game", "patch"}
            or any(
                not isinstance(name, str) or len(name) > 10000 or "\0" in name
                for name in value["names"].values()
            )
            or not isinstance(value["assets"], list)
            or len(value["assets"]) > 2000
            or any(
                not isinstance(name, str) or len(name) > 2000
                for name in value["assets"]
            )
            or len(set(value["assets"])) != len(value["assets"])
        ):
            raise ValueError("Invalid retained archive names or runtime assets.")
        value["names"][value["kind"]] = value["name"]
        tools = value["tools"]
        if (
            not isinstance(tools, dict)
            or set(tools) != {"hotkey", "forgeHotkey", "uiScale", "editorCmd"}
            or any(
                not isinstance(item, str)
                or len(item) > 4096
                or any(char in item for char in ("\0", "\r", "\n"))
                for item in tools.values()
            )
            or tools["uiScale"]
            not in {"auto", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5"}
        ):
            raise ValueError("Choose valid playtest tool settings.")
        return deepcopy(value)

    def saved_form(self, project_id):
        path = self.guided.path(project_id, "form")
        saved = read_json(path) if path.exists() else {}
        if not isinstance(saved, dict):
            raise ValueError(
                "The saved Guided form is invalid. Its original file was retained."
            )
        return self.form_value(
            project_id,
            {
                "version": "",
                "original": "",
                "untranslated": None,
                "only_overflow": True,
                **saved,
            },
        )

    def release_artifacts(self, project_id, jobs, source):
        from .release import available, current

        values = [
            (job["id"], job.get("result") or {})
            for job in jobs
            if job["action"] == "release" and job["status"] == "complete"
        ]
        state = lifecycle(self.guided.translation.workspace, project_id)
        if state.get("guided_release"):
            values.insert(0, ("patch", state["guided_release"]))
        if state.get("delivery") and not any(
            value.get("path") == state["delivery"].get("path") for _, value in values
        ):
            legacy = {**state["delivery"], "kind": "patch"}
            values.append(("previous-patch", legacy))
        values = [
            (identity, value)
            for identity, value in values
            if isinstance(value.get("path"), str)
        ][:10]
        return [
            {
                "id": identity,
                "kind": value.get("kind", "game"),
                "path": value["path"],
                "folder": str(Path(value["path"]).parent),
                "size": value.get("size"),
                "saved": value.get("saved"),
                "available": available(value),
                "current": current(value, source),
            }
            for identity, value in values
        ]

    def release_paths(self, project_id, source, action):
        from .release import runtime_asset

        paths = set(self.guided.backend.guided_runtime_files(source))
        paths.update(
            runtime_asset(source, name)
            for name in self.saved_form(project_id)["release"]["assets"]
        )
        if action == "release_patch":
            paths.discard("gameupdate/patch-config.txt")
        return sorted(paths)

    def release_ready(self, project_id, native, value):
        status = self.guided.translation.ready(project_id)
        self.guided.pending_run(value)
        source_status = self.guided.inputs(native).status(
            sorted(self.guided.supported_files(native))
        )
        if source_status["changed"]:
            raise ValueError("Review changed sources before packaging this pass.")
        readiness = self.guided.readiness(project_id, native, value, source_status)
        if readiness["unapplied"]:
            raise ValueError(
                "Apply the selected saved outputs to the game before packaging them."
            )
        if not self.ace_packing(native)["current"]:
            raise ValueError(self.ace_packing(native)["message"])
        return status

    def patch_manifest(self, project_id, paths, action):
        project, native = self.guided.record(project_id)
        entries = {name: {} for name in paths}
        if action != "git_setup":
            originals = self.guided.translation.engine.source_bindings(
                project["source"], paths
            )
            state = lifecycle(self.guided.translation.workspace, project_id)
            saved = state.get("prepared_source") or state.get("source_backup")
            source_files = {}
            if saved:
                location = backups.lookup(
                    project["source"], Path(saved["path"]).parent, saved["id"]
                )
                source_files = backups.manifest(location, source=project["source"])[
                    "files"
                ]
            for name in paths:
                if name not in originals and name not in source_files:
                    entries[name] = {"original_sha256": None}
        inputs = []
        if native["engine"] == "ACE":
            inputs = [
                path.relative_to(Path(project["source"])).as_posix()
                for path in Path(native["data"]).glob("*.json")
            ]
        return {"files": entries, "inputs": sorted(inputs)}

    def ace_packing(self, native):
        from .release import packing_state

        return packing_state(native, self.guided.backend.workflows.folder(native["id"]))
