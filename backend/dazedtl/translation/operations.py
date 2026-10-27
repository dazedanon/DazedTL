"""Preparation and delivery compose preserved engine operations with the
game's recorded original files."""

import os
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any

from dazedtl import system
from dazedtl.actions import stopped_note
from dazedtl.compatibility import original_files
from dazedtl.compatibility.checkpoint_commits import for_action, in_phase, running
from dazedtl.freshness import Digests
from dazedtl.languages import game_source
from dazedtl.storage import staging_folder, write_json

from . import backups, originals, progress_report
from .files import digest, project_path, read_json, verify_evidence


def lifecycle_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "lifecycle.json"


def lifecycle(workspace, project_id) -> dict[str, Any]:
    path = lifecycle_path(workspace, project_id)
    return read_json(path) if path.exists() else {"version": 1}


def backup_path(workspace, project_id, source, identity):
    return backups.lookup(source, Path(workspace) / "backups" / project_id, identity)


def runtime_manifest(source, relative):
    """A saved runtime patch manifest with DazedTL's own files the game holds,
    GameUpdate's, the plugins Set up installs and the playtest's fixes, which
    every checkpoint and patch carries, whichever method wrote the manifest."""
    from dazedtl.compatibility.translation import with_dazedtl_files

    return with_dazedtl_files(source, read_json(project_path(source, relative)))


def release_plan_path(workspace, project_id, kind):
    """Where Release's review of a ZIP of `kind`, game or patch, saves the
    plan its build runs."""
    return (
        Path(workspace) / "translation/projects" / project_id / f"release-{kind}.json"
    )


def release_plan(workspace, project_id, arguments, kind):
    """The release plan a build was given, as its review saved it."""
    path = release_plan_path(workspace, project_id, kind)
    payload = read_json(path) if path.is_file() else None
    if (
        arguments.get("plan") != path.relative_to(workspace).as_posix()
        or not isinstance(payload, dict)
        or digest(payload) != arguments.get("sha256")
        or payload.get("version") != 1
        or payload.get("project_id") != project_id
        or payload.get("kind") != kind
    ):
        raise ValueError("The release plan changed. Review the ZIP again.")
    return payload


def translation_files(engine, source, options, manifest_path):
    """The game's files the translation changed or added, its patch's, which
    a clean game ZIP holds beside the game's own and its freshness compares;
    none before Git is set up."""
    if not engine.git_status(source, options)["configured"]:
        return []
    manifest = (
        runtime_manifest(source, manifest_path) if manifest_path else {"files": {}}
    )
    return [
        name
        for name in engine.patch_files(source, manifest, stamped=False)["files"]
        if (Path(source) / name).is_file()
    ]


def now():
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def outdate_patch(state):
    """The last patch no longer stands for the game, as after a write, an
    undo or a game update: Release and Progress keep showing it, Outdated,
    until the next package replaces it."""
    if isinstance(state.get("delivery"), dict):
        state["delivery"]["outdated"] = True


def census_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "census.json"


# The prepared record each census counted and the census version it counted
# by, by the census file's signature.
_COUNTED = Digests(limit=64)


def census_stale(workspace, project_id, source, state=None):
    """Whether the saved census no longer counts the game: it counted another
    game than its current version's prepared original, as after a game
    update, or an earlier DazedTL counted it by other rules (census.VERSION);
    None without a census. Polls read neither the census nor Git again while
    both stay."""
    from .census import VERSION

    path = census_path(workspace, project_id)
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None

    def counted_by():
        value = read_json(path)
        return value.get("snapshot") or "", value.get("version")

    counted, version = _COUNTED.remember(str(path), info, counted_by)
    current = originals.prepared_id(workspace, project_id, source, state)
    return not current or counted != current or version != VERSION


def take_census(
    engine, workspace, project_id, source, state, decoded, stopped, progress
):
    """The census of the untranslated game, read from its recorded prepared
    original rather than the working copy, which gains English as work goes
    on. The assistant's decoded dump, if named, adds engines the tool can't
    decode itself. DazedTL's own Set up files are no game text."""
    from util.len_patch_scope import setup_files

    from . import census

    snapshot = originals.prepared(workspace, project_id, source, state)
    if snapshot is None:
        raise ValueError(originals.MISSING)
    names = sorted(snapshot.files)
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
        snapshot.materialized(
            files=census.wanted(names, snapshot.peek), stopped=stopped
        ) as root,
        system.staging_folder(tempfile.gettempdir(), "dazedtl-census-") as work,
    ):
        result = census.scan(
            names,
            lambda name: (root / name).read_bytes(),
            engine.census_decoders(root, work),
            dump(folder) if folder else None,
            progress,
            snapshot.peek,
            game_source(source),
            setup_files(source),
        )
    result.update(snapshot=snapshot.id, decoded_folder=decoded or None)
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
    from . import run_compiler  # It builds on this module.

    if plan["action"] in run_compiler.ACTIONS:
        # Compiling a run changes no lifecycle record, so it never writes one.
        return run_compiler.prepare(engine, workspace, job, plan, progress)
    # The helper's own operations are an assistant's, in Assistant-led.
    change = for_action(plan["action"], plan.get("label"), "Assistant-led")
    # An assistant writes the game's text one file at a time; those writes
    # wait for their phase's checkpoint rather than each being one.
    phase = (
        progress_report.phase(plan["source"])
        if plan["action"] in {"write_rpgmaker", "rebase_rpgmaker"}
        else None
    )
    with ExitStack() as resources, running(change), in_phase(phase):
        return _execute(engine, workspace, job, plan, stopped, progress, resources)


def _execute(engine, workspace, job, plan, stopped, progress, resources):
    source, options = Path(plan["source"]), plan["options"]
    arguments = plan["arguments"]
    state = lifecycle(workspace, job["project_id"])

    def save(change, manifest_path=None):
        """A checkpoint of the changes waiting in the patch, whose scope takes
        a runtime manifest's files the patch lacks."""
        named = ()
        if manifest_path:
            named = engine.runtime_paths(runtime_manifest(source, manifest_path))
            state["runtime_manifest"] = manifest_path
        engine.checkpoint(source, change, named)
        return engine.git_status(source, options)["translation_commit"]

    def original_names():
        """The original game's files, which hold plugins with local-looking
        names Git's inventory leaves out."""
        try:
            snapshot = originals.prepared(workspace, job["project_id"], source, state)
        except OSError, ValueError:
            snapshot = None
        # Git's inventory alone still names every other original file.
        return list(snapshot.files) if snapshot else ()

    action = plan["action"]
    if action == "record_original":
        # DazedTL records the game in the background once it opens it; an
        # assistant about to change it with its own tools asks first, which
        # waits for that record. A game whose Git is set up holds
        # translation, never its original.
        if not engine.git_status(source, options)["configured"]:
            original_files.ensure_found(source, progress, stopped)
        result = {
            "recorded": originals.available(workspace, job["project_id"], source, state)
        }
    elif action == "rpgmaker_prepare":
        data = (
            project_path(source, arguments["data_path"] + "/System.json").parent
            if arguments.get("data_path")
            else None
        )
        result = engine.rpgmaker_prepare(source, options, data, log=progress)
        state["preparation"] = {"complete": True}
    elif action == "git_setup":
        current = engine.git_status(source, options)
        if not current["configured"]:
            if not arguments.get("manifest"):
                raise ValueError(
                    "Review a runtime patch manifest and ignore rules before creating a Git baseline."
                )
            original_files.ensure_found(source, progress, stopped)
            manifest = read_json(project_path(source, arguments["manifest"]))
            engine.audit_scope(source, manifest)
            original_files.record(
                source,
                original_files.PREPARED,
                arguments["version"],
                stopped=stopped,
                progress=progress,
            )
        # An untranslated game is its own original: the record above holds
        # exactly these files, so Git reads them in place.
        result = engine.git_setup(
            source,
            options,
            arguments["version"],
            arguments.get("original", ""),
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
    elif action == "line_widths":
        # RPG Maker text is fitted to them as write_rpgmaker writes it, and
        # the text it already wrote is fitted to them now.
        widths = read_json(project_path(source, arguments["widths"]))
        result = engine.line_widths(source, widths)
    elif action in {"write_rpgmaker", "rebase_rpgmaker"}:
        require_baseline(engine, source, options, state)
        output = project_path(source, arguments["output"], exists=False)
        staged = project_path(source, arguments["translated"])
        if arguments.get("backup_id"):
            saved = originals.by_id(
                workspace, job["project_id"], source, arguments["backup_id"], state
            )
            if arguments["source"] not in saved.files:
                raise ValueError("That saved original has no such file.")
            root = resources.enter_context(
                saved.materialized([arguments["source"]], stopped)
            )
            original = project_path(root, arguments["source"])
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
            result = engine.write_rpgmaker(source, original, staged, output)
        outdate_patch(state)
    elif action == "checkpoint":
        # Every write DazedTL makes is its own checkpoint; an assistant saves
        # its own edits with this, naming files its patch should take in a
        # runtime manifest.
        require_baseline(engine, source, options, state)
        change = for_action(action)
        if arguments.get("message"):
            change = replace(change, summary=arguments["message"])
        result = {"commit": save(change, arguments.get("manifest"))}
    elif action == "release_patch":
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
        ):
            raise ValueError("The release plan changed or belongs to another game.")
        if git_identity(initial_git) != payload["git"]:
            raise ValueError("Version tracking changed after the package preview.")
        inputs = read_json(project_path(workspace, payload["source_inputs"]))
        if digest(inputs) != payload["source_inputs_sha256"]:
            raise ValueError(
                "Working sources changed before packaging. Review the current scope."
            )
        # The preview's original commit fixes every original file the patch
        # is built against; working copies keep the bindings of the version
        # they came from, which a game update leaves behind.
        verify_evidence(source, payload["evidence"])
        output = release_destination(
            source, workspace, engine.source, payload["output"]
        )
        if output_hash(output) != payload["output_hash"]:
            raise ValueError(
                "The release destination changed. Review the output again."
            )
        progress("Saving the patch's checkpoint.")
        engine.outside_edits(source)
        save(for_action(action), payload["manifest"])
        package_git = git_identity(engine.git_status(source, options))
        verify_evidence(source, payload["evidence"])
        if stopped():
            raise InterruptedError(stopped_note(action))
        output.parent.mkdir(parents=True, exist_ok=True)
        with staging_folder(output.parent, ".dazedtl-patch-") as temporary:
            manifest = runtime_manifest(source, payload["manifest"])
            packaged = engine.package(
                source,
                options,
                manifest,
                temporary,
                original_names=original_names(),
            )
            packaged.pop("paths")
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
    elif action == "package":
        require_baseline(engine, source, options, state)
        from .delivery import require_patch
        from .release import (
            destination as release_destination,
        )
        from .release import (
            git_identity,
            input_stamps,
            output_hash,
            publish,
        )
        from .release import (
            stamp as file_stamp,
        )

        manifest_path = state.get("runtime_manifest")
        if not manifest_path:
            raise ValueError(
                "Register the patch's runtime manifest with Git setup first."
            )
        require_patch(source, manifest_path)
        # Release saves the patch where the user chose, as its review read it.
        planned = (
            release_plan(workspace, job["project_id"], arguments, "patch")
            if arguments.get("plan")
            else None
        )
        if planned and (
            git_identity(engine.git_status(source, options)) != planned["git"]
        ):
            raise ValueError(
                "Version tracking changed after the package preview. Review the patch again."
            )
        engine.outside_edits(source)
        save(for_action(action), manifest_path)
        manifest = runtime_manifest(source, manifest_path)
        if planned:
            output = release_destination(
                source, workspace, engine.source, planned["output"]
            )
            if output_hash(output) != planned["output_hash"]:
                raise ValueError(
                    "The release destination changed. Review the output again."
                )
            if stopped():
                raise InterruptedError(stopped_note("release_patch"))
            output.parent.mkdir(parents=True, exist_ok=True)
            with staging_folder(output.parent, ".dazedtl-patch-") as temporary:
                packaged = engine.package(
                    source,
                    options,
                    manifest,
                    temporary,
                    original_names=original_names(),
                )
                result = {
                    **packaged,
                    **publish(
                        packaged["path"],
                        output,
                        planned["output_hash"],
                        stopped=stopped,
                    ),
                }
        else:
            result = engine.package(
                source,
                options,
                manifest,
                Path(workspace) / "deliveries" / job["project_id"],
                original_names=original_names(),
            )
            identity = file_stamp(result["path"])
            result.update(stamp=identity, size=identity[2], saved=now())
        # Release and Progress compare the game's files with the patch's.
        result["inputs"] = input_stamps(source, result.pop("paths"))
        state["delivery"] = {**result, "kind": "patch"}
        # The job keeps what the ZIP holds; the file stamps stay in the record.
        result = {key: value for key, value in result.items() if key != "inputs"}
    elif action == "release":
        from .release import build_game
        from .release import destination as release_destination

        planned = release_plan(workspace, job["project_id"], arguments, "game")
        output = release_destination(
            source, workspace, engine.source, planned["output"]
        )
        manifest_path = state.get("runtime_manifest")
        result = build_game(
            source,
            output,
            planned["scope"],
            planned["output_hash"],
            progress,
            engine=engine.detect(source),
            inputs=lambda: translation_files(engine, source, options, manifest_path),
            stopped=stopped,
        )
        state["release"] = result
        result = {key: value for key, value in result.items() if key != "inputs"}
    elif action == "gameupdate":
        result = engine.install_gameupdate(source, log=progress)
    elif action == "stage_update":
        official = Path(arguments["official"]).expanduser().resolve(strict=True)
        if (
            not official.is_dir()
            or official == source
            or official.is_relative_to(source)
            or source.is_relative_to(official)
        ):
            raise ValueError("Choose a separate new official game folder.")
        pristine = original_files.record(
            source,
            original_files.UPDATE,
            arguments["version"],
            folder=official,
            stopped=stopped,
            progress=progress,
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
        copy = staged.with_name(job["id"] + ".release")
        recorded = originals.by_id(workspace, job["project_id"], source, pristine)
        copy.mkdir()
        try:
            recorded.extract(list(recorded.files), copy, stopped)
            # The copy is laid out as the game: a release inside an extra
            # folder, or a patch for the game's www folder, lines up with it.
            layout = engine.release_stage(
                source,
                copy,
                {True: "patch", False: "game"}.get(arguments.get("patch")),
                staged,
            )
        finally:
            system.remove_tree(copy, ignore_errors=True)
        patch = layout["kind"] == "patch"
        # A patch holds only some of the game's files, so the game says which engine it is.
        kind = engine.detect(source if patch else staged)
        prepared = False
        if patch and kind in {"MVMZ", "ACE"}:
            # An Ace patch needs an assistant unless it brings the archive.
            prepared = engine.rpgmaker_prepare_patch(staged, source, log=progress)
            prepared = prepared is not None
        elif not patch and kind in {"MVMZ", "ACE"}:
            baseline = originals.prepared(
                workspace, job["project_id"], source, state, or_found=False
            )
            engine.rpgmaker_prepare_release(
                staged, options, baseline.files if baseline else None, log=progress
            )
            prepared = True
        result = {
            "official": str(staged),
            "version": arguments["version"],
            "original": pristine,
            "engine": kind,
            "patch": patch,
            "layout": layout,
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
                f"Verified {count:,} restored file{'' if count == 1 else 's'} · {name}"
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
        if operation in {"preview", "apply"}:
            originals.hold_in_original(
                workspace, job["project_id"], source, state, stopped
            )
        if operation == "apply":
            # The release's record is made before the update changes the
            # game's files, and counts only once the update's commit names it
            # as it moves the `original` branch, so an update cancelled or
            # failed before then leaves the current one read, even under the
            # same version label. A
            # patch holds only some of the game's files, so it is laid over
            # the current version's record, or an older project's backup;
            # without either it records nothing, rather than a game missing
            # every file the patch leaves out.
            over = (
                originals.under_patch(
                    workspace,
                    job["project_id"],
                    source,
                    state,
                    stopped=stopped,
                    progress=progress,
                )
                if arguments.get("patch_overlay")
                else None
            )
            # Only the record made here is named.
            arguments = {**arguments, "prepared_record": None}
            if over or not arguments.get("patch_overlay"):
                prepared = original_files.record(
                    source,
                    original_files.PREPARED,
                    arguments["version"],
                    folder=Path(arguments["official"]),
                    over=over,
                    named=True,
                    stopped=stopped,
                    progress=progress,
                )
                arguments = {**arguments, "prepared_record": prepared}
            state["incoming_version"] = arguments["version"]
            # Finishing it, maybe after its conflicts, reads the release.
            state["incoming_release"] = arguments["official"]
            write_json(lifecycle_path(workspace, job["project_id"]), state)
        elif operation == "continue":
            # A damaged record of the assets left to copy is made again from
            # the release folder the update was applied from.
            arguments = {**arguments, "release": state.get("incoming_release")}
        result = engine.version(source, operation, arguments)
        if operation in {"apply", "continue"}:
            outdate_patch(state)
            if result.get("complete"):
                from dazedtl.compatibility.guided import finish_ace_update

                # An update applied before its record was kept in Git saved
                # a backup of its release instead.
                if "incoming_source" in state:
                    state["prepared_source"] = state.pop("incoming_source")
                state["version_update"] = {
                    "version": state.pop("incoming_version", ""),
                    "complete": True,
                }
                write_json(lifecycle_path(workspace, job["project_id"]), state)
                finish_ace_update(
                    source,
                    state.pop("incoming_release", None),
                    Path(plan["publications"]) if plan.get("publications") else None,
                    progress,
                )
                # The new version's text is extracted again, from a new census.
                progress_report.reopen(
                    workspace, job["project_id"], engine, source, options, "extraction"
                )
        elif operation == "abort":
            state.pop("incoming_source", None)
            state.pop("incoming_version", None)
            state.pop("incoming_release", None)
    elif action == "start_over":
        from .start_over import run as start_over

        state, result = start_over(
            workspace,
            job["project_id"],
            source,
            state,
            engine.documents(source),
            arguments["keep_context"],
            configured=bool(engine.git_status(source, options).get("configured")),
            stopped=stopped,
            progress=progress,
            publications=plan.get("publications"),
        )
        # The engine the assistant identified and when it last called belong
        # to the attempt set aside.
        records = Path(workspace) / "translation/projects" / job["project_id"]
        for name in ("engine.json", "assistant.json"):
            system.unlink(records / name, missing_ok=True)
    elif action in {"checkpoint_back", "checkpoint_undo"}:
        from . import checkpoint_records

        require_baseline(engine, source, options, state)
        restore = (
            checkpoint_records.go_back
            if action == "checkpoint_back"
            else checkpoint_records.undo
        )
        result = restore(
            checkpoint_records.Records(
                source,
                Path(workspace),
                job["project_id"],
                Path(plan["publications"]) if plan.get("publications") else None,
                engine,
            ),
            arguments["commit"],
            stopped=stopped,
            log=progress,
            original=originals.saved(workspace, job["project_id"], source, state),
        )
        # Plugin files' records name their runtime manifest there; the last
        # package no longer matches the game.
        state = lifecycle(workspace, job["project_id"])
        outdate_patch(state)
    elif action == "checkpoint_copy":
        from dazedtl.compatibility import checkpoint_history

        require_baseline(engine, source, options, state)
        result = checkpoint_history.save_copy(
            source, arguments["commit"], arguments["destination"], stopped, progress
        )
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
        # its record stays among the game's original files.
        state["discarded_release"] = arguments["stage"]
        result = {"stage": arguments["stage"]}
    else:
        raise ValueError("Unknown project operation.")
    write_json(lifecycle_path(workspace, job["project_id"]), state)
    return result


def require_baseline(engine, source, options, state, *, allow_pending=False):
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
        kind = PENDING_GIT.get(pending[0], "operation")
        # A game update applies its changes by cherry-pick, and Checkpoints
        # names what it left as the interrupted update.
        if kind == "cherry-pick":
            return (
                "A game update was interrupted. Finish the interrupted update, "
                "or cancel it, under Checkpoints to continue."
            )
        return f"The game folder has an unfinished Git {kind}. Finish or cancel it in Git to continue."
    if not allow_pending and status.get("asset_sync_pending"):
        return "The last game update has not finished restoring game assets. Finish it under Checkpoints to continue."
    current, branch = status.get("current_branch"), status.get("translation_branch")
    if current != branch:
        return (
            f"The game folder is on Git branch “{current}”"
            if current
            else "The game folder is not on a Git branch"
        ) + f". Switch it back to the translation branch “{branch}” to continue."
    return ""
