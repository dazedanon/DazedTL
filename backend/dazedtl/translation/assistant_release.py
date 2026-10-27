"""Release for Assistant-led projects: Guided's release form, a clean game
ZIP or a patch ZIP saved where the user chooses, on the rules Guided's
Release builds by ([release](release.py)).

The patch ZIP is the one the assistant's `operation package` builds, with
its checks, saved at the chosen path instead of the workspace's deliveries
folder; the clean game ZIP holds the game's own files and its translation's,
whatever the engine. A review saves the plan its build runs, which binds the
archive's contents and the destination as the review read them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dazedtl.actions import history_label
from dazedtl.storage import write_json

from . import originals
from .files import digest, read_json
from .operations import (
    lifecycle,
    release_plan_path,
    runtime_manifest,
    translation_files,
)

if TYPE_CHECKING:
    from .service import Translation

KINDS = ("game", "patch")
# The operation that builds each kind, from the service's USER_OPERATIONS,
# and the review each is, as Guided names it.
ACTIONS = {"game": "release", "patch": "package"}
REVIEWS = {"game": "release", "patch": "release_patch"}


class AssistantRelease:
    def __init__(self, translation: Translation):
        self.translation = translation

    def _project(self, project_id):
        record, project = self.translation.project(project_id)
        if record.get("method") != "len":
            raise ValueError("This Release is for Assistant-led projects.")
        return project

    def _form_path(self, project_id):
        return (
            self.translation.workspace
            / "translation/projects"
            / project_id
            / "release-form.json"
        )

    def defaults(self, root):
        from .release import archive_stem

        stem = archive_stem(root.name, self.translation.engine.detect(root))
        names = {"game": stem + "-game.zip", "patch": stem + "-patch.zip"}
        return {
            "kind": "game",
            "name": names["game"],
            "names": names,
            "directory": str(root.parent),
        }

    @staticmethod
    def validate(value):
        if (
            not isinstance(value, dict)
            or set(value) != {"kind", "name", "names", "directory"}
            or value["kind"] not in KINDS
            or not isinstance(value["names"], dict)
            or set(value["names"]) != set(KINDS)
            or any(
                not isinstance(text, str) or len(text) > 10000 or "\0" in text
                for text in (
                    value["name"],
                    value["directory"],
                    *value["names"].values(),
                )
            )
        ):
            raise ValueError("Invalid release options.")
        return {
            **value,
            "names": {**value["names"], value["kind"]: value["name"]},
        }

    def form(self, project_id):
        """The release options the user last chose, or the defaults."""
        project = self._project(project_id)
        path = self._form_path(project_id)
        try:
            saved = read_json(path) if path.is_file() else None
            if isinstance(saved, dict) and saved.get("version") == 1:
                return self.validate(saved["form"])
        except ValueError, OSError, KeyError, TypeError:
            pass
        return self.defaults(project.root)

    def save_form(self, project_id, value):
        self._project(project_id)
        write_json(
            self._form_path(project_id), {"version": 1, "form": self.validate(value)}
        )
        return {"saved": True}

    def destination(self, project_id, output, kind):
        """Whether a ZIP of `kind` may be written there, without writing."""
        from .release import destination_check

        project = self._project(project_id)
        if kind not in KINDS:
            raise ValueError("Choose a clean game ZIP or a patch ZIP.")
        return destination_check(
            project.root,
            self.translation.workspace,
            self.translation.engine.source,
            output,
            kind,
            self.translation.engine.detect(project.root),
        )

    def view(self, project_id, root, state):
        """The release options and the last ZIP of each kind: the clean game
        ZIP Release built, and the patch, wherever it was saved."""
        from .release import available, current

        artifacts = []
        for kind, value in (
            ("game", state.get("release")),
            ("patch", state.get("delivery")),
        ):
            if not isinstance(value, dict) or not isinstance(value.get("path"), str):
                continue
            # A patch packaged before its ZIP's identity was recorded can be
            # found, not compared.
            stamped = "stamp" in value
            artifacts.append(
                {
                    "id": kind,
                    "kind": kind,
                    "path": value["path"],
                    "folder": str(Path(value["path"]).parent),
                    "size": value.get("size"),
                    "saved": value.get("saved"),
                    "available": available(value)
                    if stamped
                    else Path(value["path"]).is_file(),
                    "current": current(value, root) if stamped else None,
                }
            )
        return {"form": self.form(project_id), "artifacts": artifacts}

    def preview(self, project_id, kind, output):
        """The review of a ZIP of `kind` at `output`: what it holds, what it
        leaves out and whether it replaces a file, and the plan a build runs."""
        from .release import (
            destination,
            game_folder,
            game_scope,
            git_identity,
            output_hash,
            patch_summary,
            summary,
        )

        project = self._project(project_id)
        root = project.root
        engine = self.translation.engine
        if kind not in KINDS:
            raise ValueError("Choose a clean game ZIP or a patch ZIP.")
        # A review reads the game while no operation changes it.
        self.translation.idle(project_id)
        path = destination(root, self.translation.workspace, engine.source, output)
        state = lifecycle(self.translation.workspace, project_id)
        options = project.read()["options"]
        game_version = None
        # Writing GameUpdate's config is a checkpoint, so it goes first.
        self.translation.game_update.require_ready(project_id)
        if kind == "game":
            game_folder(path, engine.detect(root))
            names = originals.game_names(
                self.translation.workspace, project_id, root, state
            )
            known = (
                sorted(
                    names
                    | set(
                        translation_files(
                            engine, root, options, state.get("runtime_manifest")
                        )
                    )
                )
                if names
                else None
            )
            scope = game_scope(root, known)
            files = sorted(scope["files"])
            package = summary(files, scope["exclusions"], scope["updater_stamp"])
            extra = {"scope": scope}
        else:
            self.translation.package_ready(project_id)
            status = engine.git_status(root, options)
            manifest = runtime_manifest(root, state["runtime_manifest"])
            contents = engine.patch_files(root, manifest)
            from dazedtl.compatibility.guided import ace_archive

            files = contents["files"]
            package = patch_summary(
                files,
                contents["omitted"],
                contents["updater_stamp"],
                ace_archive(root),
            )
            game_version = status.get("original_version")
            extra = {"git": git_identity(status)}
        payload = {
            "version": 1,
            "project_id": project_id,
            "kind": kind,
            "output": str(path),
            "output_hash": output_hash(path),
            **extra,
        }
        plan = release_plan_path(self.translation.workspace, project_id, kind)
        write_json(plan, payload)
        return {
            "action": REVIEWS[kind],
            "label": history_label(REVIEWS[kind]),
            "destination": str(path),
            "files": len(files),
            "paths": files,
            "package": package,
            "overwrite": payload["output_hash"] is not None,
            "game_version": game_version,
            "plan": plan.relative_to(self.translation.workspace).as_posix(),
            "sha256": digest(payload),
        }

    def build(self, project_id, kind, plan, sha256):
        """Builds the ZIP a review planned, as an operation."""
        self._project(project_id)
        if kind not in KINDS:
            raise ValueError("Choose a clean game ZIP or a patch ZIP.")
        return self.translation.user_operation(
            project_id, ACTIONS[kind], {"plan": plan, "sha256": sha256}
        )
