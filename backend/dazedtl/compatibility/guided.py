"""Engine-owned guided capabilities, kept behind the migration boundary."""

import re
from pathlib import Path

from dazedtl.storage import staging_folder, write_json
from dazedtl.translation.files import digest, project_path, read_json


def file_titles(native):
    """Optional map names enrich selection without changing translation inputs."""
    path = Path(native["data"]) / "MapInfos.json"
    try:
        if path.is_symlink() or path.stat().st_size > 8_000_000:
            return {}
        value = read_json(path)
        values = (
            value
            if isinstance(value, list)
            else value.values()
            if isinstance(value, dict)
            else []
        )
        result = {}
        for row in values:
            if (
                isinstance(row, dict)
                and type(row.get("id")) is int
                and isinstance(row.get("name"), str)
            ):
                result[row["id"]] = row["name"][:1000]
        return {
            row["name"]: result.get(int(match.group(1)), "")
            for row in native["files"]
            if (
                match := re.fullmatch(
                    r"Map(\d+)\.json", row["name"], flags=re.IGNORECASE
                )
            )
        }
    except OSError, ValueError, UnicodeError:
        return {}


def tools_state(native):
    if native["engine"] != "MVMZ":
        return None
    from util.forge import installer as forge
    from util.tl_inspector import installer as inspector

    result = {}
    for key, module in (("inspector", inspector), ("forge", forge)):
        try:
            value = module.status(Path(native["source"]))
        except OSError, UnicodeError:
            result[key] = {
                "installed": False,
                "present": False,
                "message": "Tool status unavailable",
            }
            continue
        # An orphaned plugin file or registration is not a working installation.
        result[key] = {
            "installed": bool(value.get("plugin_file") and value.get("declared")),
            "present": bool(value.get("installed")),
            "message": str(value.get("message", "")),
        }
    return result


def release_scope(source, known):
    from util.release_package import ReleasePackageError, _release_patch_sha

    from dazedtl.translation.release import inventory

    try:
        public_version = _release_patch_sha(Path(source))
    except ReleasePackageError:
        public_version = None
    return inventory(source, public_version, known)


def run_release(plan, log):
    from desktop.backend.workflow_actions import validate_plan

    from dazedtl.translation.release import (
        destination,
        game_folder,
        input_stamps,
        publish,
        write_archive,
    )

    validate_plan(plan)
    source = Path(plan["project"]["source"])
    workspace = Path(plan["folder"]).parents[1]
    from .runtime import ENGINE_ROOT

    output = destination(source, workspace, ENGINE_ROOT, plan["options"]["output"])
    folder = game_folder(output, plan["project"]["engine"])
    expected = plan["release_scope"]
    packing = ace_packing_state(plan["project"], plan["folder"])
    if not packing["current"]:
        raise ValueError(packing["message"])
    if release_scope(source, expected["known"]) != expected:
        raise ValueError(
            "The package contents or public version changed. Build a new release preview."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with staging_folder(output.parent, ".dazedtl-release-") as temporary:
        staged = temporary / output.name
        write_archive(source, staged, expected, log, folder=folder)
        validate_plan(plan)
        if not ace_packing_state(plan["project"], plan["folder"])["current"]:
            raise ValueError(
                "Ace packing evidence changed during packaging. Its partial archive was discarded."
            )
        if release_scope(source, expected["known"]) != expected:
            raise ValueError(
                "The game or public version changed during packaging. Its partial archive was discarded."
            )
        # Later checks compare only the runtime files translation work
        # changes, not the whole game. An applied image edited outside Images
        # still packages; that archive just cannot be compared later.
        try:
            inputs = input_stamps(source, runtime_files(source))
        except ValueError:
            inputs = None
        saved = publish(
            staged,
            output,
            plan["output_hash"],
            stopped=getattr(log, "stopped", lambda: False),
        )
    return {
        **saved,
        "kind": "game",
        "inputs": inputs,
        "files": len(expected["files"]) + bool(expected["updater_stamp"]),
        "excluded": len(expected["exclusions"]),
        "updater_stamp": bool(expected["updater_stamp"]),
    }


def guard(project, folder):
    from desktop.backend.workflow_actions import action_guard

    return action_guard(project, folder)


def guard_context(project, observed):
    """The guard's parts every phase shares, for a poll: the same values as
    action_guard's, hashing only files whose listed signature changed. A
    folder holding anything but plain files and folders, or a file the
    listing cannot place, gets the engine's own reading and errors."""
    from desktop.backend import workflow_actions as engine

    root = Path(project["source"])

    def file_hash(root, path):
        try:
            relative = Path(path).relative_to(root).as_posix()
        except ValueError:
            relative = None
        if relative:
            parent, _, name = relative.rpartition("/")
            folder = observed.folder(root, parent)
            if folder is not None and observed.entry(folder / name):
                return observed.digest(folder / name)
        return engine.file_hash(root, path)

    def tree_hashes(root, folder):
        hashes = plain_tree(root, folder)
        return engine.tree_hashes(root, folder) if hashes is None else hashes

    def plain_tree(root, folder):
        try:
            start = observed.folder(root, Path(folder).relative_to(root).as_posix())
        except ValueError:
            return None
        if start is None:
            return None
        result, pending = {}, [start]
        while pending:
            entries = observed.listing(pending.pop())
            if entries is None:
                return None
            for entry in entries.values():
                path = Path(entry.path)
                if entry.is_symlink() or entry.is_junction():
                    return None
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    result[path.relative_to(start).as_posix()] = observed.digest(path)
                else:
                    return None
        return result

    return engine.guard_context(
        root, engine.describe_game(root, files=False), file_hash, tree_hashes
    )


def phased_workflows(workspace, lock, operations, manual):
    from desktop.backend.workflow import Workflows

    class ScopedWorkflows(Workflows):
        def execute(self, token):
            plan = self.previews.get(token)
            if (
                plan
                and plan.get("overwrite_runtime")
                and plan.get("action") == "export_selected"
            ):
                from .text import validate_publication

                self.previews.pop(token)
                validate_publication(plan)
                return self.operations.start(plan)
            return super().execute(token)

        def apply_investigation_settings(
            self, identity, revision, options, receipt_key, receipt
        ):
            from util.engine_options import validate_engine_options

            project = self.projects[identity]
            if project["revision"] != revision:
                raise ValueError(
                    "The guided project changed. Reload its findings before applying them."
                )
            validated = validate_engine_options({"rpgmakermvmz": options})[
                "rpgmakermvmz"
            ]
            updated = {
                **project,
                "engine_options": {**project["engine_options"], **validated},
                "revision": revision + 1,
                receipt_key: receipt,
            }
            # Preferences and the consumed report travel in one atomic write.
            self.save(updated)
            self.projects[identity] = updated
            return updated

        def apply_layout_settings(self, identity, revision, receipt):
            from util.game_settings import save_game_wrap_widths, valid_line_widths

            project = self.projects[identity]
            if project["revision"] != revision:
                raise ValueError(
                    "The guided settings changed before the measured layout was saved."
                )
            widths = receipt["widths"]
            if not valid_line_widths(widths) or widths["faceWidth"] > widths["width"]:
                raise ValueError(
                    "The measured layout contains invalid character limits."
                )
            next_revision = revision + int(widths != project["widths"])
            receipt = {
                **receipt,
                "beforeRevision": revision,
                "revision": next_revision,
                "beforeWidths": dict(project["widths"]),
            }
            updated = {
                **project,
                "widths": dict(widths),
                "revision": next_revision,
                "guided_layout": receipt,
            }
            if receipt["applied"]:
                save_game_wrap_widths(project["source"], widths)
            self.save(updated)
            self.projects[identity] = updated
            return updated

        def _collect(self, project):
            from .preparations import temporary
            from .process_view import _read_cached, _verified_digest, file_stamp

            # Reload runs in a separate tool process. Do not collect between
            # its archive, version update and file replacements.
            if any(
                job.get("project_id") == project["id"]
                and job.get("action") == "refresh_sources"
                and job.get("status") in {"ready", "running", "waiting"}
                for job in self.operations.jobs.values()
            ):
                return
            index = self.folder(project["id"]) / "source-inputs.json"
            if index.exists() and project.get("manual_job") in read_json(index).get(
                "retired_runs", []
            ):
                return  # Frozen work from an older source pass stays in its own run.
            versions = (
                read_json(index).get("file_versions", {}) if index.exists() else {}
            )
            current = self.manual.jobs.get(project.get("manual_job"))
            current_plan = (
                self.manual.folder(current["id"]) / "plan.json" if current else None
            )
            same_pass = True
            if current_plan and current_plan.is_file():
                # Polls collect several times per observation, and a Batch
                # plan for a large game holds megabytes of reserved sources.
                saved = _read_cached(str(current_plan), file_stamp(current_plan))
                same_pass = all(
                    versions.get(name, "")
                    == saved.get("dazedtl_source_versions", {}).get(name, "")
                    for name in current.get("files", [])
                )
            if same_pass and not (current and temporary(current)):
                super()._collect(project)
            # Native collection only follows one completed run. Preserve verified
            # completed files from older or partly failed runs as well, without
            # overwriting a newer working copy or merging changed guidance.
            collected = project.setdefault("dazedtl_collected_outputs", {})
            retired = read_json(index).get("retired_runs", []) if index.exists() else []
            changed = False
            for identity, job in self.manual.jobs.items():
                if (
                    identity in retired
                    or job.get("mode") == "estimate"
                    or temporary(job)
                ):
                    continue
                from .checkpoints import can_collect_outputs

                if not can_collect_outputs(job):
                    continue
                source = self.manual.folder(identity)
                try:
                    plan_path = source / "plan.json"
                    plan = _read_cached(str(plan_path), file_stamp(plan_path))
                    if (
                        _verified_digest(str(plan_path), file_stamp(plan_path))
                        != job["plan_hash"]
                        or (plan.get("workflow") or {}).get("id") != project["id"]
                    ):
                        continue
                    from .checkpoints import outputs as checkpoint_outputs

                    outputs = {
                        **job.get("outputs", {}),
                        **checkpoint_outputs(source, plan),
                    }
                    before = {row["name"]: row["sha256"] for row in plan["files"]}
                    for name, expected in outputs.items():
                        if versions.get(name, "") != plan.get(
                            "dazedtl_source_versions", {}
                        ).get(name, ""):
                            continue
                        marker = identity + ":" + name
                        if collected.get(marker) == expected:
                            continue
                        output = project_path(source / "translated", name)
                        working = project_path(
                            self.folder(project["id"]) / "files", name
                        )
                        destination = project_path(
                            self.folder(project["id"]),
                            "translated/" + name,
                            exists=False,
                        )
                        if digest(output.read_bytes()) != expected or digest(
                            working.read_bytes()
                        ) not in {before.get(name), expected}:
                            continue
                        if destination.exists() and digest(
                            destination.read_bytes()
                        ) not in {before.get(name), expected, collected.get(marker)}:
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        from dazedtl.storage import write_bytes

                        write_bytes(destination, output.read_bytes())
                        collected[marker] = expected
                        changed = True
                except OSError, ValueError, KeyError:
                    continue
            if changed:
                self.save(project)

    return ScopedWorkflows(workspace, lock, operations, manual)


def apply_selected(plan, log):
    from desktop.backend.workflow_actions import regular, validate_plan
    from util.project_scanner import export_to_game

    validate_plan(plan)
    names = plan["options"]["files"]
    if (
        not names
        or set(names) - set(plan["guard"]["translated"] or {})
        or set(names) - set(plan["guard"]["files"] or {})
    ):
        raise ValueError("The selected saved outputs changed. Review the files again.")
    root, data, folder = (
        Path(plan["project"]["source"]),
        Path(plan["project"]["data"]),
        Path(plan["folder"]),
    )
    for name in names:
        regular(root, data / name)
        regular(folder, folder / "translated" / name)
    log("Applying " + str(len(names)) + " reviewed files.")
    count, errors = export_to_game(folder / "translated", data, filenames=names)
    if errors:
        raise ValueError("; ".join(errors))
    receipt = folder / "applied-outputs.json"
    previous = read_json(receipt).get("files", {}) if receipt.exists() else {}
    write_json(
        receipt,
        {
            "version": 1,
            "files": {
                **previous,
                **{name: plan["guard"]["translated"][name] for name in names},
            },
        },
    )
    return {"files": count, "destination": str(data)}


def runtime_files(source):
    """Propose the standard RPG Maker patch; the user reviews the complete list."""
    from util.len_patch_scope import (
        CONFIG,
        dazedtl_files,
        patch_manifest,
        updater_config,
    )
    from util.project_preparation import rpgmaker_layout
    from util.version_update.git_workflow import _run_git

    from dazedtl.translation.release import applied_assets, exclusion

    root = Path(source)
    layout = rpgmaker_layout(root)
    if not layout or layout["engine"] not in {"MVMZ", "ACE"}:
        raise ValueError("Guided translation supports RPG Maker MV/MZ and VX Ace.")
    if layout["engine"] == "ACE":
        from util.ace import game_ini

        # Packing writes the translated window title into Game.ini.
        paths = [
            *(root / "Data").glob("*.rvdata2"),
            *filter(None, [game_ini.find(root)]),
        ]
    else:
        paths = list(layout["data_path"].glob("*.json"))
    if layout["plugins_js"]:
        paths.append(layout["plugins_js"])
        paths.extend((layout["plugins_js"].parent / "plugins").glob("*.js"))
    # The published patch tells players' GameUpdate where to download it from.
    if updater_config(root):
        paths.append(root / CONFIG)
    # GameUpdate's files, the plugins Set up installs and the playtest's fixes
    # with the main.js line loading them.
    paths.extend(root / name for name in dazedtl_files(root))
    # Keep an existing reviewed patch's images, fonts and other runtime assets
    # when the user changes workflow. Repository metadata is handled by Git.
    tracked = _run_git(root, "ls-files", "-z", check=False)
    if tracked.returncode == 0:
        for relative in tracked.stdout.split("\0"):
            if relative and relative not in {
                ".gitignore",
                ".gitattributes",
                "README.md",
            }:
                path = root / relative
                if path.is_file():
                    paths.append(path)
    paths.extend(project_path(root, relative) for relative in applied_assets(root))
    names = sorted(
        {
            path.relative_to(root).as_posix()
            for path in paths
            if not exclusion(path.relative_to(root).as_posix())
        }
    )
    patch_manifest(names)
    return names


def ace_archive(source):
    """The name of the archive an encrypted Ace game came with, once Set up
    set it aside; patches carry it rebuilt."""
    from util.ace.actions import original_archive

    found = original_archive(Path(source))
    return found.name if found else None


def run_ace(plan, log):
    """Ace preparation with the built-in converter; packing checks its outputs."""
    from desktop.backend.workflow_actions import validate_plan
    from util.ace import actions

    validate_plan(plan)
    action = plan["action"]
    root = Path(plan["project"]["source"])
    if action == "ace_pack":
        pack_ace(plan["project"], plan["folder"], log)
        return {"completed": action}
    exports = root / "ace_json"
    fresh = not (exports.is_dir() and any(exports.glob("*.json", case_sensitive=False)))
    actions.run(root, action, log)
    if action == "ace_extract" and fresh:
        # JSON just converted from Data holds what Data does, so the game's
        # data starts out current without packing it.
        native = {**plan["project"], "data": str(exports)}
        _save_receipt(native, plan["folder"], actions.packed_files(root))
    return {"completed": action}


def ace_blocked(source):
    """Why packing can't reach an Ace game, or None: an RGSS archive left
    beside Game.exe, which the game reads instead of its data."""
    from util.ace import actions

    return actions.archive_in_root(Path(source))


def ace_packing_state(native, folder):
    """Whether the game's native data holds its current ace_json, and why
    not; an archive left in the game root comes first, since the game reads
    nothing else while it is there."""
    from dazedtl.translation.release import packing_state

    blocked = native["engine"] == "ACE" and ace_blocked(native["source"])
    if blocked:
        return {"required": True, "current": False, "message": blocked}
    return packing_state(native, folder)


def pack_ace(native, folder, log, touched=None):
    """Brings an Ace game's native data up to date with its ace_json and
    saves the packing receipt Release checks; every in-app write to ace_json
    runs it in the same step with the exports it `touched`, since the game
    reads only Data. From a current receipt it packs the data files whose
    exports changed since. Without one, such as for JSON converted by an
    earlier tool or Data an assistant wrote itself, a write packs only what
    it touched, so whatever else Data holds stays, and only a pack of
    everything, Pack outside edits, saves a receipt."""
    from util.ace import actions

    from dazedtl.translation.files import evidence
    from dazedtl.translation.release import (
        PACKING_VERSION,
        packing_inputs,
        packing_target,
        unpacked,
    )

    root = Path(native["source"])
    blocked = ace_blocked(root)
    if blocked:
        raise ValueError(blocked)
    inputs = packing_inputs(native)
    path = Path(folder) / "ace-packing.json"
    receipt = None
    try:
        saved = read_json(path) if path.exists() else {}
        if (
            saved.get("version") == PACKING_VERSION
            and saved.get("source") == native["source"]
            and saved["outputs"] == evidence(root, list(saved["outputs"]))
            and isinstance(saved["inputs"], dict)
        ):
            receipt = saved
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        receipt = None
    if receipt is not None:
        outputs = list(receipt["outputs"])
        only = {
            packing_target(name)
            for name, value in inputs.items()
            if receipt["inputs"].get(name) != value
        } | {packing_target(name) for name in unpacked(inputs, outputs)}
        if not only and receipt["inputs"] == inputs:
            return []
    elif touched is not None:
        only, outputs = {packing_target(name) for name in touched}, None
    else:
        only, outputs = None, []
    written = actions.run(root, "ace_pack", log, only=only)
    if outputs is None:
        return written
    if inputs != packing_inputs(native):
        raise ValueError(
            "Ace JSON changed during packing. No current packing receipt was saved."
        )
    _save_receipt(native, folder, [*map(root.joinpath, outputs), *written], inputs)
    return written


def _save_receipt(native, folder, outputs, inputs=None):
    """Records that the game's native files hold its current exports."""
    from dazedtl.translation.files import evidence
    from dazedtl.translation.release import PACKING_VERSION, packing_inputs, unpacked

    root = Path(native["source"])
    inputs = packing_inputs(native) if inputs is None else inputs
    outputs = sorted({Path(path).relative_to(root).as_posix() for path in outputs})
    missing = unpacked(inputs, outputs)
    if missing:
        raise ValueError("Ace packing found no native data for: " + ", ".join(missing))
    write_json(
        Path(folder) / "ace-packing.json",
        {
            "version": PACKING_VERSION,
            "source": str(root),
            "inputs": inputs,
            "outputs": evidence(root, outputs),
        },
    )


def publish_ace(plan, log, write):
    """Runs a write to the game's text, and for an Ace game packs what it
    wrote to ace_json into the native data the game reads, in the same
    operation. A game still reading its archive refuses before anything is
    written."""
    if plan["project"]["engine"] != "ACE":
        return write(plan, log)
    blocked = ace_blocked(plan["project"]["source"])
    if blocked:
        raise ValueError(blocked)
    result = write(plan, log)
    if not result.get("files"):
        return result
    root = Path(plan["project"]["source"])
    rows = (plan.get("publication") or {}).get("files")
    touched = (
        [row["path"] for row in rows]
        if rows
        else [
            (Path(plan["project"]["data"]) / name).relative_to(root).as_posix()
            for name in plan["options"]["files"]
        ]
    )
    try:
        pack_ace(plan["project"], plan["folder"], log, touched)
    except (OSError, ValueError) as error:
        raise ValueError(
            "The text is in ace_json, but the game's data could not be updated: "
            + str(error)
            + " Pack outside edits, in Release, tries again."
        ) from error
    return result
