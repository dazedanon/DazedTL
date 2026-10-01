"""Preparation and delivery compose preserved engine operations with backups."""

from pathlib import Path
from contextlib import contextmanager, ExitStack
import uuid

from dazedtl.storage import write_json
from . import backups
from .files import read_json, project_path, digest, evidence, verify_evidence


def verify_guided_review(source, state, workspace=None, engine=None):
    review = state.get("guided_review")
    if not review:
        raise ValueError("Record your review and playtest of the current guided patch before packaging.")
    verify_evidence(source, review["evidence"])
    if review.get("source_inputs"):
        if workspace is None:
            raise ValueError("Verify this playtest review through its app workspace.")
        from .guided_inputs import original_bindings
        inputs = read_json(project_path(workspace, review["source_inputs"]))
        if digest(inputs) != review["source_inputs_sha256"]:
            raise ValueError("Working sources changed after playtest review. Review the current pass again.")
        if engine is not None:
            engine.verify_bindings(source, original_bindings(inputs))
    return review


def lifecycle_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "lifecycle.json"


def lifecycle(workspace, project_id):
    path = lifecycle_path(workspace, project_id)
    return read_json(path) if path.exists() else {"version": 1}


def backup_path(workspace, project_id, source, identity):
    return backups.lookup(source, Path(workspace) / "backups" / project_id, identity)


def reconcile_source_backup(workspace, project_id, source, state):
    """Retire missing auxiliary records after a source backup has been saved."""
    retired = {}
    saved = state.get("workspace_backup")
    if saved:
        try:
            backups.lookup(source, Path(saved["path"]).parent, saved["id"])
        except backups.BackupMissing:
            retired["workspace_backup"] = saved
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Unreadable or damaged artifacts still need recovery, not cleanup.

    identification = Path(workspace) / "translation/projects" / project_id / "engine.json"
    try:
        identified = read_json(identification)
        paths = identified["evidence"]
        if isinstance(paths, dict) and paths:
            for name in paths:
                try:
                    project_path(source, name, exists=False).stat()
                except FileNotFoundError:
                    continue
                break
            else:
                retired["engine"] = identified
    except (OSError, ValueError, KeyError, TypeError):
        pass

    if not retired:
        return
    archive = Path(workspace) / "backups/stale-project-records" / project_id / uuid.uuid4().hex
    write_json(archive / "records.json", {"version": 1, "source_backup": state["source_backup"]["id"], **retired})
    if "workspace_backup" in retired:
        state.pop("workspace_backup")
        write_json(lifecycle_path(workspace, project_id), state)
    if "engine" in retired and read_json(identification) == retired["engine"]:
        identification.rename(archive / "engine.json")


@contextmanager
def backup_files(workspace, project_id, source, identity, *, files=None, stopped=lambda: False):
    path = backup_path(workspace, project_id, source, identity)
    with backups.materialized(path, files=files, stopped=stopped) as restored:
        yield restored


def execute(engine, workspace, job, plan, stopped, progress=lambda _message: None):
    with ExitStack() as resources:
        return _execute(engine, workspace, job, plan, stopped, progress, resources)


def _execute(engine, workspace, job, plan, stopped, progress, resources):
    source, options = Path(plan["source"]), plan["options"]
    arguments = plan["arguments"]
    state = lifecycle(workspace, job["project_id"])
    destination = backups.store_path(source)
    def restored(identity, files=None):
        return resources.enter_context(backup_files(workspace, job["project_id"], source, identity, files=files, stopped=stopped))
    action = plan["action"]
    if action in {"backup_source", "backup_workspace"}:
        root = source if action == "backup_source" else source / ".dazedtl"
        result = backups.snapshot(root, destination, source_game=action == "backup_source", stopped=stopped,
                                  progress=lambda count, path: progress("Backed up " + str(count) + " files · " + path))
        state["source_backup" if action == "backup_source" else "workspace_backup"] = result
    elif action == "rpgmaker_prepare":
        require_source_backup(source, state)
        data = project_path(source, arguments["data_path"] + "/System.json").parent if arguments.get("data_path") else None
        result = engine.rpgmaker_prepare(source, options, data, log=progress)
        state["preparation"] = {"complete": True}
    elif action == "git_setup":
        require_source_backup(source, state)
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
            original = str(restored(state["prepared_source"]["id"])[0])
        result = engine.git_setup(source, options, arguments["version"], original, arguments.get("untranslated") is True)
        state["git"] = {key: result.get(key) for key in ("original_commit", "translation_commit", "original_version", "translation_branch")}
        if arguments.get("manifest"):
            state["runtime_manifest"] = arguments["manifest"]
    elif action in {"write_rpgmaker", "rebase_rpgmaker"}:
        require_baseline(engine, source, options, state)
        output = project_path(source, arguments["output"], exists=False)
        staged = project_path(source, arguments["translated"])
        if arguments.get("backup_id"):
            root, manifest = restored(arguments["backup_id"], [arguments["source"]])
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
        original = str(restored(state["prepared_source"]["id"], engine.runtime_paths(manifest))[0]) if state.get("prepared_source") else None
        engine.git_scope(source, options, manifest, original, True)
        result = engine.git_scope(source, options, manifest, original, False)
        result["commit"] = engine.commit(source, arguments.get("message", "translation: save reviewed patch"))
        state["checkpoint"] = {"commit": result["commit"], "manifest": arguments["manifest"]}
        state["runtime_manifest"] = arguments["manifest"]
        state["workspace_backup"] = backups.snapshot(source / ".dazedtl", destination, stopped=stopped)
        result["backup"] = state["workspace_backup"]
    elif action == "guided_review":
        require_baseline(engine, source, options, state)
        manifest = read_json(project_path(source, arguments["manifest"]))
        state["guided_review"] = {"manifest": arguments["manifest"],
                                  "evidence": evidence(source, list(dict.fromkeys([arguments["manifest"], *engine.runtime_paths(manifest), *manifest.get("inputs", [])])))}
        if arguments.get("source_inputs"):
            from .guided_inputs import original_bindings
            inputs = read_json(project_path(workspace, arguments["source_inputs"]))
            if digest(inputs) != arguments["source_inputs_sha256"]:
                raise ValueError("Working sources changed. Review this pass again.")
            engine.verify_bindings(source, original_bindings(inputs))
            state["guided_review"].update(source_inputs=arguments["source_inputs"], source_inputs_sha256=arguments["source_inputs_sha256"])
        result = {"reviewed_files": len(manifest["files"]), "message": "User review and playtest recorded for these exact files."}
    elif action in {"package", "guided_package"}:
        require_baseline(engine, source, options, state)
        if not state.get("checkpoint"):
            raise ValueError("Checkpoint the reviewed runtime patch before packaging.")
        if engine.git_status(source, options)["translation_commit"] != state["checkpoint"]["commit"]:
            raise ValueError("The translation branch changed after its reviewed checkpoint. Checkpoint the current patch first.")
        if action == "guided_package":
            review = verify_guided_review(source, state, workspace, engine)
            if review["manifest"] != state["checkpoint"]["manifest"]:
                raise ValueError("Checkpoint the reviewed guided manifest before packaging.")
        else:
            from .delivery import verify
            verify(source, full=True)
        manifest = read_json(project_path(source, state["checkpoint"]["manifest"]))
        result = engine.package(source, options, manifest, Path(workspace) / "deliveries" / job["project_id"])
        state["delivery"] = result
        state["workspace_backup"] = backups.snapshot(source / ".dazedtl", destination, stopped=stopped)
        result["backup"] = state["workspace_backup"]
    elif action == "stage_update":
        official = Path(arguments["official"]).expanduser().resolve(strict=True)
        if not official.is_dir() or official == source or official.is_relative_to(source) or source.is_relative_to(official):
            raise ValueError("Choose a separate new official game folder.")
        pristine = backups.snapshot(official, destination, source_game=True, stopped=stopped,
                                     progress=lambda count, path: progress("Preserved " + str(count) + " new-original files · " + path))
        staged = Path(workspace) / "translation/projects" / job["project_id"] / "incoming" / job["id"]
        progress("Creating an isolated working copy of the new original.")
        staged.parent.mkdir(parents=True, exist_ok=True)
        backups.restore(pristine["path"], staged, stopped=stopped)
        kind = engine.detect(staged)
        prepared = False
        if kind == "MVMZ" or kind == "ACE" and (staged / "ace_json").is_dir():
            engine.rpgmaker_prepare(staged, options, log=progress)
            prepared = True
        result = {"official": str(staged), "version": arguments["version"], "source_backup": pristine,
                  "engine": kind, "preparation_required": not prepared}
    elif action == "restore_backup":
        target = Path(arguments["destination"]).expanduser().absolute()
        if target.resolve().is_relative_to(source) or source.is_relative_to(target.resolve()):
            raise ValueError("Choose a new restore folder outside the selected game.")
        path = backup_path(workspace, job["project_id"], source, arguments["backup_id"])
        result = backups.restore(path, target, stopped=stopped,
                                 progress=lambda count, name: progress("Verified " + str(count) + " restored files · " + name))
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
    if action == "backup_source":
        reconcile_source_backup(workspace, job["project_id"], source, state)
    return result


def require_source_backup(source, state):
    if not state.get("source_backup"):
        raise ValueError("Preserve a recoverable source backup before translation.")
    record = state["source_backup"]
    path = backups.lookup(source, Path(record["path"]).parent, record["id"])
    saved = backups.verify(path, source=source, full=False)
    if saved["kind"] != "source":
        raise ValueError("The source backup is unavailable. Restore it before continuing.")
    return saved


def require_baseline(engine, source, options, state, *, allow_pending=False):
    require_source_backup(source, state)
    status = engine.git_status(source, options)
    if status.get("repo_root") != str(Path(source).resolve()):
        raise ValueError("The selected game must own its version-tracking repository.")
    if not status.get("configured") or not status.get("original_version") or not status.get("translation_version"):
        raise ValueError("Establish the original and translation branches with a source version first.")
    if status.get("current_branch") != status.get("translation_branch") or not allow_pending and (status.get("pending_operations") or status.get("asset_sync_pending")):
        raise ValueError("Finish pending Git work and select the translation branch before continuing.")
    return status
