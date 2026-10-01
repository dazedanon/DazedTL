"""Preparation and delivery compose preserved engine operations with backups."""

from pathlib import Path
import shutil

from dazedtl.storage import write_json
from . import backups
from .files import read_json, project_path, digest


def lifecycle_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "lifecycle.json"


def lifecycle(workspace, project_id):
    path = lifecycle_path(workspace, project_id)
    return read_json(path) if path.exists() else {"version": 1}


def backup_files(workspace, project_id, identity):
    if not isinstance(identity, str) or len(identity) != 32 or any(char not in "0123456789abcdef" for char in identity):
        raise ValueError("Choose a registered backup.")
    path = Path(workspace) / "backups" / project_id / identity
    value = backups.manifest(path)
    return path / "files", value


def execute(engine, workspace, job, plan, stopped, progress=lambda _message: None):
    source, options = Path(plan["source"]), plan["options"]
    arguments = plan["arguments"]
    state = lifecycle(workspace, job["project_id"])
    destination = Path(workspace) / "backups" / job["project_id"]
    action = plan["action"]
    if action in {"backup_source", "backup_workspace"}:
        root = source if action == "backup_source" else source / ".dazedtl"
        result = backups.snapshot(root, destination, source_game=action == "backup_source", stopped=stopped,
                                  progress=lambda count, path: progress("Backed up " + str(count) + " files · " + path))
        state["source_backup" if action == "backup_source" else "workspace_backup"] = result
    elif action == "rpgmaker_prepare":
        if not state.get("source_backup"):
            raise ValueError("Preserve the selected source before preparing game files.")
        data = project_path(source, arguments["data_path"] + "/System.json").parent if arguments.get("data_path") else None
        result = engine.rpgmaker_prepare(source, options, data, log=progress)
        state["preparation"] = {"complete": True}
    elif action == "git_setup":
        if not state.get("source_backup"):
            raise ValueError("Create a source backup before establishing Git baselines.")
        current = engine.git_status(source, options)
        if not current["configured"]:
            if not arguments.get("manifest"):
                raise ValueError("Review a runtime patch manifest and ignore rules before creating a Git baseline.")
            manifest = read_json(project_path(source, arguments["manifest"]))
            engine.audit_scope(source, manifest)
            snapshot = backups.snapshot(source, destination, source_game=True, stopped=stopped)
            state["prepared_source"] = snapshot
            write_json(lifecycle_path(workspace, job["project_id"]), state)
        original = arguments.get("original", "")
        if not original and arguments.get("untranslated") and state.get("prepared_source"):
            original = str(backup_files(workspace, job["project_id"], state["prepared_source"]["id"])[0])
        result = engine.git_setup(source, options, arguments["version"], original, arguments.get("untranslated") is True)
        state["git"] = {key: result.get(key) for key in ("original_commit", "translation_commit", "original_version", "translation_branch")}
        if arguments.get("manifest"):
            state["runtime_manifest"] = arguments["manifest"]
    elif action in {"write_rpgmaker", "rebase_rpgmaker"}:
        require_baseline(engine, source, options, state)
        output = project_path(source, arguments["output"], exists=False)
        staged = project_path(source, arguments["translated"])
        if arguments.get("backup_id"):
            root, manifest = backup_files(workspace, job["project_id"], arguments["backup_id"])
            original = project_path(root, arguments["source"])
            if manifest["files"].get(arguments["source"]) != digest(original.read_bytes()):
                raise ValueError("The backup source bytes changed. Restore the matching original before injection.")
        else:
            original = project_path(source, arguments["source"])
        if action == "rebase_rpgmaker":
            result = engine.rebase_rpgmaker(source, original, staged, output, arguments.get("expected_original_commit"))
        else:
            result = {"path": engine.write_rpgmaker(original, staged, output)}
        state.pop("delivery", None)
    elif action == "checkpoint":
        require_baseline(engine, source, options, state)
        manifest = read_json(project_path(source, arguments["manifest"]))
        original = str(backup_files(workspace, job["project_id"], state["prepared_source"]["id"])[0]) if state.get("prepared_source") else None
        engine.git_scope(source, options, manifest, original, True)
        result = engine.git_scope(source, options, manifest, original, False)
        result["commit"] = engine.commit(source, arguments.get("message", "translation: save reviewed patch"))
        state["checkpoint"] = {"commit": result["commit"], "manifest": arguments["manifest"]}
        state["runtime_manifest"] = arguments["manifest"]
        state["workspace_backup"] = backups.snapshot(source / ".dazedtl", destination, stopped=stopped)
    elif action == "package":
        require_baseline(engine, source, options, state)
        if not state.get("checkpoint"):
            raise ValueError("Checkpoint the reviewed runtime patch before packaging.")
        if engine.git_status(source, options)["translation_commit"] != state["checkpoint"]["commit"]:
            raise ValueError("The translation branch changed after its reviewed checkpoint. Checkpoint the current patch first.")
        from .delivery import verify
        verify(source, full=True)
        manifest = read_json(project_path(source, state["checkpoint"]["manifest"]))
        result = engine.package(source, options, manifest, Path(workspace) / "deliveries" / job["project_id"])
        state["delivery"] = result
        state["workspace_backup"] = backups.snapshot(source / ".dazedtl", destination, stopped=stopped)
    elif action == "stage_update":
        official = Path(arguments["official"]).expanduser().resolve(strict=True)
        if not official.is_dir() or official == source or official.is_relative_to(source) or source.is_relative_to(official):
            raise ValueError("Choose a separate new official game folder.")
        pristine = backups.snapshot(official, destination, source_game=True, stopped=stopped,
                                     progress=lambda count, path: progress("Preserved " + str(count) + " new-original files · " + path))
        staged = Path(workspace) / "translation/projects" / job["project_id"] / "incoming" / job["id"]
        progress("Creating an isolated working copy of the new original.")
        shutil.copytree(Path(pristine["path"]) / "files", staged)
        kind = engine.detect(staged)
        prepared = False
        if kind == "MVMZ" or kind == "ACE" and (staged / "ace_json").is_dir():
            engine.rpgmaker_prepare(staged, options, log=progress)
            prepared = True
        result = {"official": str(staged), "version": arguments["version"], "source_backup": pristine,
                  "engine": kind, "preparation_required": not prepared}
    elif action.startswith("version_"):
        operation = action.removeprefix("version_")
        require_baseline(engine, source, options, state, allow_pending=operation in {"continue", "abort"})
        if operation == "apply":
            state["incoming_source"] = backups.snapshot(Path(arguments["official"]), destination, source_game=True, stopped=stopped)
            state["incoming_version"] = arguments["version"]
            write_json(lifecycle_path(workspace, job["project_id"]), state)
        result = engine.version(source, operation, arguments)
        if operation in {"apply", "continue"}:
            state.pop("delivery", None)
            if result.get("complete"):
                state["prepared_source"] = state.pop("incoming_source", state.get("prepared_source"))
                state["version_update"] = {"version": state.pop("incoming_version", ""), "complete": True}
        elif operation == "abort":
            state.pop("incoming_source", None)
            state.pop("incoming_version", None)
    else:
        raise ValueError("Unknown project operation.")
    write_json(lifecycle_path(workspace, job["project_id"]), state)
    return result


def require_baseline(engine, source, options, state, *, allow_pending=False):
    if not state.get("source_backup"):
        raise ValueError("Preserve a recoverable source backup before translation.")
    saved = backups.manifest(state["source_backup"]["path"], source)
    if not saved.get("files") or not (Path(state["source_backup"]["path"]) / "files").is_dir():
        raise ValueError("The source backup is unavailable. Restore it before continuing.")
    status = engine.git_status(source, options)
    if status.get("repo_root") != str(Path(source).resolve()):
        raise ValueError("The selected game must own its version-tracking repository.")
    if not status.get("configured") or not status.get("original_version") or not status.get("translation_version"):
        raise ValueError("Establish the original and translation branches with a source version first.")
    if status.get("current_branch") != status.get("translation_branch") or not allow_pending and (status.get("pending_operations") or status.get("asset_sync_pending")):
        raise ValueError("Finish pending Git work and select the translation branch before continuing.")
    return status
