"""Preparation and delivery compose preserved engine operations with backups."""

import tempfile
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from dazedtl.storage import write_json

from . import backups
from .files import digest, evidence, project_path, read_json, verify_evidence


def verify_guided_review(source, state, workspace=None, engine=None):
    review = state.get("guided_review")
    if not review:
        raise ValueError(
            "Record your review and playtest of the current guided patch before packaging."
        )
    verify_evidence(source, review["evidence"])
    if review.get("source_inputs"):
        if workspace is None:
            raise ValueError("Verify this playtest review through its app workspace.")
        from .guided_inputs import original_bindings

        inputs = read_json(project_path(workspace, review["source_inputs"]))
        if digest(inputs) != review["source_inputs_sha256"]:
            raise ValueError(
                "Working sources changed after playtest review. Review the current pass again."
            )
        if engine is not None:
            engine.verify_bindings(source, original_bindings(inputs))
    return review


def lifecycle_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "lifecycle.json"


def lifecycle(workspace, project_id) -> dict[str, Any]:
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
        except OSError, ValueError, KeyError, TypeError:
            pass  # Unreadable or damaged artifacts still need recovery, not cleanup.

    identification = (
        Path(workspace) / "translation/projects" / project_id / "engine.json"
    )
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
    except OSError, ValueError, KeyError, TypeError:
        pass

    if not retired:
        return
    archive = (
        Path(workspace)
        / "backups/stale-project-records"
        / project_id
        / uuid.uuid4().hex
    )
    write_json(
        archive / "records.json",
        {"version": 1, "source_backup": state["source_backup"]["id"], **retired},
    )
    if "workspace_backup" in retired:
        state.pop("workspace_backup")
        write_json(lifecycle_path(workspace, project_id), state)
    if "engine" in retired and read_json(identification) == retired["engine"]:
        identification.rename(archive / "engine.json")


BACKUP_RECORDS = ("source_backup", "game_backup", "prepared_source", "workspace_backup")


def reconcile_missing_backups(workspace, project_id, source, state):
    """Retire backup records whose store is gone so their "unavailable"
    warnings clear on their own, for example after the user deletes .dazedtl.
    Each record must already carry record_status's `available`. A store that
    still holds snapshots but misses a recorded one is left alone: that is
    possible corruption to recover from, not a deliberate reset. Retired
    records are archived beside reconcile_source_backup's for an audit trail.
    """
    try:
        if (backups.store_path(source) / "snapshots").exists():
            return ()
    except OSError:
        return ()
    retired = {
        key: state[key]
        for key in BACKUP_RECORDS
        if isinstance(state.get(key), dict) and state[key].get("available") is False
    }
    if not retired:
        return ()
    archive = (
        Path(workspace)
        / "backups/stale-project-records"
        / project_id
        / uuid.uuid4().hex
    )
    write_json(archive / "records.json", {"version": 1, "records": retired})
    for key in retired:
        state.pop(key, None)
    write_json(lifecycle_path(workspace, project_id), state)
    return tuple(retired)


@contextmanager
def backup_files(
    workspace, project_id, source, identity, *, files=None, stopped=lambda: False
):
    path = backup_path(workspace, project_id, source, identity)
    with backups.materialized(path, files=files, stopped=stopped) as restored:
        yield restored


def census_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "census.json"


def take_census(
    engine, workspace, project_id, source, state, decoded, stopped, progress
):
    """The census of the untranslated game, read from its prepared source
    backup rather than the working copy, which gains English as work goes
    on. The assistant's decoded dump, if named, adds engines the tool can't
    decode itself."""
    from . import census

    snapshot = state.get("prepared_source") or state.get("source_backup")
    if not snapshot:
        raise ValueError("Back up the original game before taking its census.")
    path = backup_path(workspace, project_id, source, snapshot["id"])
    names = sorted(backups.manifest(path)["files"])
    folder = None
    if decoded:
        folder = project_path(source, decoded.rstrip("/"), exists=False)
        if not folder.is_dir():
            raise ValueError(
                "Name the folder your decoder wrote, relative to the game."
            )

    def dump(folder):
        for item in sorted(folder.rglob("*")):
            if item.is_file() and not item.is_symlink():
                yield item.relative_to(folder).as_posix(), item.read_bytes()

    with (
        backups.materialized(path, files=census.wanted(names), stopped=stopped) as (
            root,
            _manifest,
        ),
        tempfile.TemporaryDirectory(prefix="dazedtl-census-") as work,
    ):
        result = census.scan(
            names,
            lambda name: (root / name).read_bytes(),
            engine.census_decoders(root, work),
            dump(folder) if folder else None,
            progress,
            lambda name, size: backups.peek(path, name, size),
        )
    result.update(snapshot=snapshot["id"], decoded_folder=decoded or None)
    write_json(census_path(workspace, project_id), result)
    kinds = {}
    for entry in result["entries"]:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + len(entry["runs"])
    return {
        "runs": sum(kinds.values()),
        "kinds": dict(sorted(kinds.items())),
        "unreadable": len(result["unreadable"]),
        "opened": result["opened"],
        "needs_dump": result["needs_dump"],
        "decoded": result["decoded"],
    }


def execute(engine, workspace, job, plan, stopped, progress=lambda _message: None):
    with ExitStack() as resources:
        return _execute(engine, workspace, job, plan, stopped, progress, resources)


def _execute(engine, workspace, job, plan, stopped, progress, resources):
    source, options = Path(plan["source"]), plan["options"]
    arguments = plan["arguments"]
    state = lifecycle(workspace, job["project_id"])
    destination = backups.store_path(source)

    def restored(identity, files=None):
        return resources.enter_context(
            backup_files(
                workspace,
                job["project_id"],
                source,
                identity,
                files=files,
                stopped=stopped,
            )
        )

    def checkpoint(manifest_path, message):
        manifest = read_json(project_path(source, manifest_path))
        original = (
            str(
                restored(
                    state["prepared_source"]["id"], engine.runtime_paths(manifest)
                )[0]
            )
            if state.get("prepared_source")
            else None
        )
        engine.git_scope(source, options, manifest, original, True)
        result = engine.git_scope(source, options, manifest, original, False)
        result["commit"] = engine.commit(source, message)
        state["checkpoint"] = {"commit": result["commit"], "manifest": manifest_path}
        state["runtime_manifest"] = manifest_path
        state["workspace_backup"] = backups.snapshot(
            source / ".dazedtl", destination, stopped=stopped
        )
        result["backup"] = state["workspace_backup"]
        return result

    action = plan["action"]
    if action in {"backup_source", "backup_workspace"}:
        root = source if action == "backup_source" else source / ".dazedtl"
        # Checked first: an identical snapshot would make a missing original
        # look available again.
        preserved = action == "backup_source" and original_available(source, state)
        result = backups.snapshot(
            root,
            destination,
            source_game=action == "backup_source",
            stopped=stopped,
            progress=lambda count, path: progress(
                f"Backed up {count:,} files · {path}"
            ),
        )
        if action == "backup_workspace":
            state["workspace_backup"] = result
        elif preserved:
            # A later game backup never replaces the original it was set up
            # from; it is recorded as the latest one.
            state["game_backup"] = result
        else:
            state["source_backup"] = result
    elif action == "use_source_backup":
        # A moved, copied or reinstalled game keeps its original in its own
        # store; a project without one takes over the snapshot it showed.
        if state.get("source_backup"):
            raise ValueError("This project already has an original backup.")
        saved = backups.original(source)
        if not saved or saved["id"] != arguments["backup_id"]:
            raise ValueError(
                "The game's saved backups changed. Review setup again before using one."
            )
        backups.verify(saved["path"], source=source, full=False)
        result = {key: value for key, value in saved.items() if key != "created"}
        state["source_backup"] = result
    elif action == "rpgmaker_prepare":
        require_source_backup(source, state)
        data = (
            project_path(source, arguments["data_path"] + "/System.json").parent
            if arguments.get("data_path")
            else None
        )
        result = engine.rpgmaker_prepare(source, options, data, log=progress)
        state["preparation"] = {"complete": True}
    elif action == "git_setup":
        require_source_backup(source, state)
        current = engine.git_status(source, options)
        if not current["configured"]:
            if not arguments.get("manifest"):
                raise ValueError(
                    "Review a runtime patch manifest and ignore rules before creating a Git baseline."
                )
            manifest = read_json(project_path(source, arguments["manifest"]))
            engine.audit_scope(source, manifest)
            snapshot = backups.snapshot(
                source, destination, source_game=True, stopped=stopped
            )
            state["prepared_source"] = snapshot
            write_json(lifecycle_path(workspace, job["project_id"]), state)
        original = arguments.get("original", "")
        if (
            not original
            and arguments.get("untranslated")
            and state.get("prepared_source")
        ):
            original = str(restored(state["prepared_source"]["id"])[0])
        result = engine.git_setup(
            source,
            options,
            arguments["version"],
            original,
            arguments.get("untranslated") is True,
        )
        state["git"] = {
            key: result.get(key)
            for key in (
                "original_commit",
                "translation_commit",
                "original_version",
                "translation_branch",
            )
        }
        if arguments.get("manifest"):
            state["runtime_manifest"] = arguments["manifest"]
    elif action in {"write_rpgmaker", "rebase_rpgmaker"}:
        require_baseline(engine, source, options, state)
        output = project_path(source, arguments["output"], exists=False)
        staged = project_path(source, arguments["translated"])
        if arguments.get("backup_id"):
            root, manifest = restored(arguments["backup_id"], [arguments["source"]])
            original = project_path(root, arguments["source"])
            if manifest["files"].get(arguments["source"]) != digest(
                original.read_bytes()
            ):
                raise ValueError(
                    "The backup source bytes changed. Restore the matching original before injection."
                )
        else:
            original = project_path(source, arguments["source"])
        if action == "rebase_rpgmaker":
            result = engine.rebase_rpgmaker(
                source,
                original,
                staged,
                output,
                arguments.get("expected_original_commit"),
            )
        else:
            result = {"path": engine.write_rpgmaker(original, staged, output)}
        state.pop("delivery", None)
    elif action == "checkpoint":
        require_baseline(engine, source, options, state)
        result = checkpoint(
            arguments["manifest"],
            arguments.get("message", "translation: save reviewed patch"),
        )
    elif action == "release_patch":
        from .guided_inputs import original_bindings
        from .release import (
            destination as release_destination,
        )
        from .release import (
            git_identity,
            input_stamps,
            output_hash,
            publish,
        )

        initial_git = require_baseline(engine, source, options, state)
        payload = read_json(project_path(workspace, arguments["plan"]))
        if (
            digest(payload) != arguments["sha256"]
            or payload["version"] != 1
            or payload["project_id"] != job["project_id"]
            or Path(payload["source"]) != source
        ):
            raise ValueError("The release plan changed or belongs to another game.")
        if git_identity(initial_git) != payload["git"]:
            raise ValueError("Version tracking changed after the package preview.")
        inputs = read_json(project_path(workspace, payload["source_inputs"]))
        if digest(inputs) != payload["source_inputs_sha256"]:
            raise ValueError(
                "Working sources changed before packaging. Review the current scope."
            )
        engine.verify_bindings(source, original_bindings(inputs))
        verify_evidence(source, payload["evidence"])
        output = release_destination(
            source, workspace, engine.source, payload["output"]
        )
        if output_hash(output) != payload["output_hash"]:
            raise ValueError(
                "The release destination changed. Review the output again."
            )
        progress("Saving the translation version and a project backup.")
        checkpoint(payload["manifest"], "translation: prepare release patch")
        package_git = git_identity(engine.git_status(source, options))
        if package_git["translation_commit"] != state["checkpoint"]["commit"]:
            raise ValueError(
                "The translation branch changed while checkpointing the release."
            )
        write_json(lifecycle_path(workspace, job["project_id"]), state)
        verify_evidence(source, payload["evidence"])
        if stopped():
            raise InterruptedError(
                "Release stopped. Its translation version and backup were kept."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".dazedtl-patch-", dir=output.parent
        ) as temporary:
            manifest = read_json(project_path(source, payload["manifest"]))
            # The translation version keeps GameUpdate's config for publishing;
            # a local patch leaves it out.
            packaged = engine.package(
                source, options, manifest, Path(temporary), updater=False
            )
            verify_evidence(source, payload["evidence"])
            inputs = input_stamps(source, payload["evidence"])
            if (
                git_identity(engine.git_status(source, options)) != package_git
                or digest(read_json(project_path(workspace, payload["source_inputs"])))
                != payload["source_inputs_sha256"]
            ):
                raise ValueError(
                    "Version tracking or the source pass changed during packaging."
                )
            result = {
                **packaged,
                **publish(
                    packaged["path"], output, payload["output_hash"], stopped=stopped
                ),
                "kind": "patch",
                "inputs": inputs,
            }
        state["guided_release"] = result
    elif action == "guided_review":
        require_baseline(engine, source, options, state)
        manifest = read_json(project_path(source, arguments["manifest"]))
        state["guided_review"] = {
            "manifest": arguments["manifest"],
            "evidence": evidence(
                source,
                list(
                    dict.fromkeys(
                        [
                            arguments["manifest"],
                            *engine.runtime_paths(manifest),
                            *manifest.get("inputs", []),
                        ]
                    )
                ),
            ),
        }
        if arguments.get("source_inputs"):
            from .guided_inputs import original_bindings

            inputs = read_json(project_path(workspace, arguments["source_inputs"]))
            if digest(inputs) != arguments["source_inputs_sha256"]:
                raise ValueError("Working sources changed. Review this pass again.")
            engine.verify_bindings(source, original_bindings(inputs))
            state["guided_review"].update(
                source_inputs=arguments["source_inputs"],
                source_inputs_sha256=arguments["source_inputs_sha256"],
            )
        result = {
            "reviewed_files": len(manifest["files"]),
            "message": "User review and playtest recorded for these exact files.",
        }
    elif action in {"package", "guided_package"}:
        require_baseline(engine, source, options, state)
        if not state.get("checkpoint"):
            raise ValueError("Checkpoint the reviewed runtime patch before packaging.")
        if (
            engine.git_status(source, options)["translation_commit"]
            != state["checkpoint"]["commit"]
        ):
            raise ValueError(
                "The translation branch changed after its reviewed checkpoint. Checkpoint the current patch first."
            )
        if action == "guided_package":
            review = verify_guided_review(source, state, workspace, engine)
            if review["manifest"] != state["checkpoint"]["manifest"]:
                raise ValueError(
                    "Checkpoint the reviewed guided manifest before packaging."
                )
        else:
            from .delivery import verify

            proof = verify(source, full=True)
            if state["checkpoint"]["manifest"] not in proof["files"]:
                raise ValueError(
                    "Record QA for the current checkpoint scope before packaging with Assistant-led."
                )
        manifest = read_json(project_path(source, state["checkpoint"]["manifest"]))
        result = engine.package(
            source,
            options,
            manifest,
            Path(workspace) / "deliveries" / job["project_id"],
        )
        state["delivery"] = result
        state["workspace_backup"] = backups.snapshot(
            source / ".dazedtl", destination, stopped=stopped
        )
        result["backup"] = state["workspace_backup"]
    elif action == "stage_update":
        official = Path(arguments["official"]).expanduser().resolve(strict=True)
        if (
            not official.is_dir()
            or official == source
            or official.is_relative_to(source)
            or source.is_relative_to(official)
        ):
            raise ValueError("Choose a separate new official game folder.")
        pristine = backups.snapshot(
            official,
            destination,
            source_game=True,
            stopped=stopped,
            progress=lambda count, path: progress(
                f"Backed up {count:,} new-original files · {path}"
            ),
        )
        staged = (
            Path(workspace)
            / "translation/projects"
            / job["project_id"]
            / "incoming"
            / job["id"]
        )
        progress("Creating an isolated working copy of the new original.")
        staged.parent.mkdir(parents=True, exist_ok=True)
        backups.restore(pristine["path"], staged, stopped=stopped)
        kind = engine.detect(staged)
        prepared = False
        if kind == "MVMZ" or kind == "ACE" and (staged / "ace_json").is_dir():
            engine.rpgmaker_prepare(staged, options, log=progress)
            prepared = True
        result = {
            "official": str(staged),
            "version": arguments["version"],
            "source_backup": pristine,
            "engine": kind,
            "preparation_required": not prepared,
        }
    elif action == "restore_backup":
        target = Path(arguments["destination"]).expanduser().absolute()
        if target.resolve().is_relative_to(source) or source.is_relative_to(
            target.resolve()
        ):
            raise ValueError("Choose a new restore folder outside the selected game.")
        path = backup_path(workspace, job["project_id"], source, arguments["backup_id"])
        result = backups.restore(
            path,
            target,
            stopped=stopped,
            progress=lambda count, name: progress(
                f"Verified {count:,} restored files · {name}"
            ),
        )
    elif action.startswith("version_"):
        operation = action.removeprefix("version_")
        require_baseline(
            engine,
            source,
            options,
            state,
            allow_pending=operation in {"continue", "abort"},
        )
        if operation == "apply":
            state["incoming_source"] = backups.snapshot(
                Path(arguments["official"]),
                destination,
                source_game=True,
                stopped=stopped,
            )
            state["incoming_version"] = arguments["version"]
            write_json(lifecycle_path(workspace, job["project_id"]), state)
        result = engine.version(source, operation, arguments)
        if operation in {"apply", "continue"}:
            state.pop("delivery", None)
            if result.get("complete"):
                state["prepared_source"] = state.pop(
                    "incoming_source", state.get("prepared_source")
                )
                state["version_update"] = {
                    "version": state.pop("incoming_version", ""),
                    "complete": True,
                }
        elif operation == "abort":
            state.pop("incoming_source", None)
            state.pop("incoming_version", None)
    elif action == "start_over":
        from .start_over import run as start_over

        state, result = start_over(
            source,
            state,
            engine.documents(source),
            arguments["keep_context"],
            stopped=stopped,
            progress=progress,
        )
        # The engine the assistant identified and when it last called belong
        # to the attempt set aside.
        records = Path(workspace) / "translation/projects" / job["project_id"]
        for name in ("engine.json", "assistant.json"):
            (records / name).unlink(missing_ok=True)
    elif action == "census":
        result = take_census(
            engine,
            workspace,
            job["project_id"],
            source,
            state,
            arguments.get("decoded"),
            stopped,
            progress,
        )
    elif action == "discard_release":
        # A staged release the user decided against stops offering its review;
        # its preserved backup stays in Backups.
        state["discarded_release"] = arguments["stage"]
        result = {"stage": arguments["stage"]}
    else:
        raise ValueError("Unknown project operation.")
    write_json(lifecycle_path(workspace, job["project_id"]), state)
    if action in {"backup_source", "use_source_backup"}:
        reconcile_source_backup(workspace, job["project_id"], source, state)
    return result


def original_available(source, state):
    try:
        require_source_backup(source, state)
    except OSError, ValueError:
        return False
    return True


def require_source_backup(source, state):
    if not state.get("source_backup"):
        raise ValueError("Back up the original game before translation.")
    record = state["source_backup"]
    path = backups.lookup(source, Path(record["path"]).parent, record["id"])
    saved = backups.verify(path, source=source, full=False)
    if saved["kind"] != "source":
        raise ValueError(
            "The source backup is unavailable. Restore it before continuing."
        )
    return saved


def require_baseline(engine, source, options, state, *, allow_pending=False):
    require_source_backup(source, state)
    status = engine.git_status(source, options)
    if status.get("repo_root") != str(Path(source).resolve()):
        raise ValueError("The selected game must own its version-tracking repository.")
    if (
        not status.get("configured")
        or not status.get("original_version")
        or not status.get("translation_version")
    ):
        raise ValueError(
            "Establish the original and translation branches with a source version first."
        )
    issue = checkout_issue(status, allow_pending=allow_pending)
    if issue:
        raise ValueError(issue)
    return status


# Git's marker for each unfinished operation, as the user knows it.
PENDING_GIT = {
    "MERGE_HEAD": "merge",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
    "rebase-merge": "rebase",
    "rebase-apply": "rebase",
    "sequencer": "cherry-pick",
    "BISECT_LOG": "bisect",
}


def checkout_issue(status, *, allow_pending=False):
    """Why the game's Git checkout cannot take translation work, or ""."""
    pending = status.get("pending_operations") or []
    if not allow_pending and pending:
        return (
            f"The game folder has an unfinished Git {PENDING_GIT.get(pending[0], 'operation')}. "
            "Finish or cancel it under Game updates, or in Git, to continue."
        )
    if not allow_pending and status.get("asset_sync_pending"):
        return "The last game update has not finished restoring game assets. Finish it under Game updates to continue."
    current, branch = status.get("current_branch"), status.get("translation_branch")
    if current != branch:
        return (
            f"The game folder is on Git branch “{current}”"
            if current
            else "The game folder is not on a Git branch"
        ) + f". Switch it back to the translation branch “{branch}” to continue."
    return ""
