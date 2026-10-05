"""Engine-owned guided capabilities, kept behind the migration boundary."""

import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

from dazedtl.translation.files import digest, read_json, project_path
from dazedtl.storage import write_json


def file_titles(native):
    """Optional map names enrich selection without changing translation inputs."""
    path = Path(native["data"]) / "MapInfos.json"
    try:
        if path.is_symlink() or path.stat().st_size > 8_000_000:
            return {}
        value = read_json(path)
        values = value if isinstance(value, list) else value.values() if isinstance(value, dict) else []
        result = {}
        for row in values:
            if isinstance(row, dict) and type(row.get("id")) is int and isinstance(row.get("name"), str):
                result[row["id"]] = row["name"][:1000]
        return {row["name"]: result.get(int(match.group(1)), "") for row in native["files"]
                if (match := re.fullmatch(r"Map(\d+)\.json", row["name"], flags=re.IGNORECASE))}
    except (OSError, ValueError, UnicodeError):
        return {}


def tools_state(native):
    if native["engine"] != "MVMZ":
        return None
    from util.tl_inspector import installer as inspector
    from util.forge import installer as forge
    result = {}
    for key, module in (("inspector", inspector), ("forge", forge)):
        try:
            value = module.status(Path(native["source"]))
        except (OSError, UnicodeError):
            result[key] = {"installed": False, "present": False, "message": "Tool status unavailable"}
            continue
        # An orphaned plugin file or registration is not a working installation.
        result[key] = {"installed": bool(value.get("plugin_file") and value.get("declared")),
                       "present": bool(value.get("installed")), "message": str(value.get("message", ""))}
    return result


def release_scope(source):
    from util.release_package import _release_patch_sha, ReleasePackageError
    from dazedtl.translation.release import inventory
    try:
        public_version = _release_patch_sha(Path(source))
    except ReleasePackageError:
        public_version = None
    return inventory(source, public_version)


def run_release(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from dazedtl.translation.release import destination, publish, write_archive, packing_state
    validate_plan(plan)
    source = Path(plan["project"]["source"])
    workspace = Path(plan["folder"]).parents[1]
    from .runtime import ENGINE_ROOT
    output = destination(source, workspace, ENGINE_ROOT, plan["options"]["output"])
    expected = plan["release_scope"]
    if not packing_state(plan["project"], plan["folder"])["current"]:
        raise ValueError("Pack and verify current Ace data before packaging.")
    if release_scope(source) != expected:
        raise ValueError("The package contents or public version changed. Build a new release preview.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dazedtl-release-", dir=output.parent) as temporary:
        staged = Path(temporary) / output.name
        write_archive(source, staged, expected, log)
        validate_plan(plan)
        if not packing_state(plan["project"], plan["folder"])["current"]:
            raise ValueError("Ace packing evidence changed during packaging. Its partial archive was discarded.")
        if release_scope(source) != expected:
            raise ValueError("The game or public version changed during packaging. Its partial archive was discarded.")
        saved = publish(staged, output, plan["output_hash"], stopped=getattr(log, "stopped", lambda: False))
    return {**saved, "kind": "game", "files": len(expected["files"]) + bool(expected["updater_stamp"]),
            "excluded": len(expected["exclusions"]), "updater_stamp": bool(expected["updater_stamp"])}


def guard(project, folder):
    from desktop.backend.workflow_actions import action_guard
    return action_guard(project, folder)


def phased_workflows(workspace, lock, operations, manual):
    from desktop.backend.workflow import Workflows
    class ScopedWorkflows(Workflows):
        def execute(self, token):
            plan = self.previews.get(token)
            if plan and plan.get("overwrite_runtime") and plan.get("action") == "export_selected":
                from .text import validate_publication
                self.previews.pop(token)
                validate_publication(plan)
                return self.operations.start(plan)
            return super().execute(token)

        def apply_speaker_settings(self, identity, revision, options, receipt):
            from util.engine_options import validate_engine_options
            project = self.projects[identity]
            if project["revision"] != revision:
                raise ValueError("The guided project changed. Reload its findings before applying them.")
            validated = validate_engine_options({"rpgmakermvmz": options})["rpgmakermvmz"]
            updated = {**project, "engine_options": {**project["engine_options"], **validated},
                       "revision": revision + 1, "guided_speakers": receipt}
            # Preferences and the consumed report travel in one atomic write.
            self.save(updated)
            self.projects[identity] = updated
            return updated

        def apply_layout_settings(self, identity, revision, receipt):
            from util.game_settings import save_game_wrap_widths
            project = self.projects[identity]
            if project["revision"] != revision:
                raise ValueError("The guided settings changed before the measured layout was saved.")
            widths = receipt["widths"]
            if (set(widths) != {"width", "faceWidth", "listWidth", "noteWidth"}
                    or any(type(value) is not int or not 20 <= value <= 300 for value in widths.values())
                    or widths["faceWidth"] > widths["width"]):
                raise ValueError("The measured layout contains invalid character limits.")
            next_revision = revision + int(widths != project["widths"])
            receipt = {**receipt, "beforeRevision": revision, "revision": next_revision, "beforeWidths": dict(project["widths"])}
            updated = {**project, "widths": dict(widths), "revision": next_revision, "guided_layout": receipt}
            if receipt["applied"]:
                save_game_wrap_widths(project["source"], widths)
            self.save(updated)
            self.projects[identity] = updated
            return updated

        def _collect(self, project):
            from .preparations import temporary
            index = self.folder(project["id"]) / "source-inputs.json"
            if index.exists() and project.get("manual_job") in read_json(index).get("retired_runs", []):
                return  # Frozen work from an older source pass stays in its own run.
            versions = read_json(index).get("file_versions", {}) if index.exists() else {}
            current = self.manual.jobs.get(project.get("manual_job"))
            current_plan = self.manual.folder(current["id"]) / "plan.json" if current else None
            same_pass = True
            if current_plan and current_plan.is_file():
                saved = read_json(current_plan)
                same_pass = all(versions.get(name, "") == saved.get("dazedtl_source_versions", {}).get(name, "") for name in current.get("files", []))
            if same_pass and not (current and temporary(current)):
                super()._collect(project)
            # Native collection only follows one completed run. Preserve verified
            # completed files from older or partly failed runs as well, without
            # overwriting a newer working copy or merging changed guidance.
            collected = project.setdefault('dazedtl_collected_outputs', {})
            retired = read_json(index).get('retired_runs', []) if index.exists() else []
            changed = False
            for identity, job in self.manual.jobs.items():
                if identity in retired or job.get('mode') == 'estimate' or temporary(job):
                    continue
                from .checkpoints import can_collect_outputs
                if not can_collect_outputs(job):
                    continue
                source = self.manual.folder(identity)
                try:
                    plan_path = source / 'plan.json'
                    plan = read_json(plan_path)
                    if digest(plan_path.read_bytes()) != job['plan_hash'] or (plan.get('workflow') or {}).get('id') != project['id']:
                        continue
                    from .checkpoints import outputs as checkpoint_outputs
                    outputs = {**job.get('outputs', {}), **checkpoint_outputs(source, plan)}
                    before = {row['name']: row['sha256'] for row in plan['files']}
                    for name, expected in outputs.items():
                        if versions.get(name, '') != plan.get('dazedtl_source_versions', {}).get(name, ''):
                            continue
                        marker = identity + ':' + name
                        if collected.get(marker) == expected:
                            continue
                        output = project_path(source / 'translated', name)
                        working = project_path(self.folder(project['id']) / 'files', name)
                        destination = project_path(self.folder(project['id']), 'translated/' + name, exists=False)
                        if digest(output.read_bytes()) != expected or digest(working.read_bytes()) not in {before.get(name), expected}:
                            continue
                        if destination.exists() and digest(destination.read_bytes()) not in {before.get(name), expected, collected.get(marker)}:
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        from dazedtl.storage import write_bytes
                        write_bytes(destination, output.read_bytes())
                        collected[marker] = expected
                        changed = True
                except (OSError, ValueError, KeyError):
                    continue
            if changed:
                self.save(project)
    return ScopedWorkflows(workspace, lock, operations, manual)


def apply_selected(plan, log):
    from desktop.backend.workflow_actions import validate_plan, regular
    from util.project_scanner import export_to_game
    validate_plan(plan)
    names = plan["options"]["files"]
    if not names or set(names) - set(plan["guard"]["translated"] or {}) or set(names) - set(plan["guard"]["files"] or {}):
        raise ValueError("The selected saved outputs changed. Review the files again.")
    root, data, folder = Path(plan["project"]["source"]), Path(plan["project"]["data"]), Path(plan["folder"])
    for name in names:
        regular(root, data / name)
        regular(folder, folder / "translated" / name)
    log("Applying " + str(len(names)) + " reviewed files.")
    count, errors = export_to_game(folder / "translated", data, filenames=names)
    if errors:
        raise ValueError("; ".join(errors))
    receipt = folder / "applied-outputs.json"
    previous = read_json(receipt).get("files", {}) if receipt.exists() else {}
    write_json(receipt, {"version": 1, "files": {**previous, **{name: plan["guard"]["translated"][name] for name in names}}})
    return {"files": count, "destination": str(data), "ace_packing_required": plan["project"]["engine"] == "ACE"}


def rewrap_review(backend, native_id, token):
    current = backend.workflows.previews[token]
    jobs = sorted((job for job in backend.operations.jobs.values()
                   if job["project_id"] == native_id and job["action"] == "rewrap_preview" and job["status"] == "complete"),
                  key=lambda job: job["created"], reverse=True)
    if jobs:
        job = jobs[0]
        path = backend.operations.root / job["id"] / "plan.json"
        previous = read_json(path)
        if (digest(path.read_bytes()) == job["plan_hash"] and previous["options"] == current["options"]
                and previous["guard"] == current["guard"]):
            return job["result"]
    raise ValueError("Preview rewrap with these files and settings before applying it. Re-scan after any game changes.")


def runtime_files(source):
    """Propose the standard RPG Maker patch; the user reviews the complete list."""
    from util.project_preparation import rpgmaker_layout, RPG_GAMEUPDATE_COPY_SKIP_NAMES
    from dazedtl.translation.release import exclusion, applied_assets
    from util.paths import PROJECT_ROOT
    from util.len_patch_scope import patch_manifest
    from util.version_update.git_workflow import _run_git
    root = Path(source)
    layout = rpgmaker_layout(root)
    if not layout or layout["engine"] not in {"MVMZ", "ACE"}:
        raise ValueError("Guided translation supports RPG Maker MV/MZ and VX Ace.")
    paths = list((root / "Data").glob("*.rvdata2")) if layout["engine"] == "ACE" else list(layout["data_path"].glob("*.json"))
    if layout["plugins_js"]:
        paths.append(layout["plugins_js"])
        paths.extend((layout["plugins_js"].parent / "plugins").glob("*.js"))
    template = PROJECT_ROOT / "gameupdate"
    for path in template.rglob("*"):
        relative = path.relative_to(template)
        if path.is_file() and not any(part in RPG_GAMEUPDATE_COPY_SKIP_NAMES for part in relative.parts):
            target = root / relative
            if target.is_file() and relative.as_posix() not in {".gitignore", ".gitattributes", "README.md", "gameupdate/previous_patch_sha.txt"}:
                paths.append(target)
    # Keep an existing reviewed patch's images, fonts and other runtime assets
    # when the user changes workflow. Repository metadata is handled by Git.
    tracked = _run_git(root, "ls-files", "-z", check=False)
    if tracked.returncode == 0:
        for relative in tracked.stdout.split("\0"):
            if relative and relative not in {".gitignore", ".gitattributes", "README.md"}:
                path = root / relative
                if path.is_file():
                    paths.append(path)
    paths.extend(project_path(root, relative) for relative in applied_assets(root))
    names = sorted({path.relative_to(root).as_posix() for path in paths
                    if not exclusion(path.relative_to(root).as_posix())})
    patch_manifest(names)
    return names


def ace_available():
    return os.name == "nt"


def run_ace(plan, log):
    """Use bundled tools from a profile cache, never install into engine source."""
    from util.paths import PROJECT_ROOT
    from desktop.backend.workflow_actions import validate_plan
    validate_plan(plan)
    if not ace_available():
        raise ValueError("Native Ace conversion is available on Windows. Use an explicitly supported Windows environment to pack and verify this game.")
    action = plan["action"]
    root = Path(plan["project"]["source"])
    from dazedtl.translation.release import packing_inputs
    from dazedtl.translation.files import evidence
    inputs = packing_inputs(plan['project']) if action == 'ace_pack' else None
    outputs = [(Path('Data') / (Path(name).stem + '.rvdata2')).as_posix() for name in inputs] if inputs else []
    before = {name: (root / name).stat().st_mtime_ns for name in outputs if (root / name).is_file()}
    name = "RPGMakerDecrypter-cli.exe" if action == "ace_decrypt" else "RV2JSON.exe"
    source = PROJECT_ROOT / "util/ace/offline" / name
    if not source.is_file():
        source = PROJECT_ROOT / "util/ace" / name
    if not source.is_file():
        raise ValueError("The engine's bundled Ace tool is missing: " + name)
    destination = Path(plan["folder"]).parents[1] / "tools/ace" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    environment = dict(os.environ)
    arguments = [str(destination)]
    if action == "ace_decrypt":
        archives = sorted(root.glob("Game.rgss*"))
        if not archives:
            raise ValueError("No Game.rgss archive needs extraction.")
        archive = str(archives[0])
        arguments.append(archive)
    else:
        arguments.append("-c" if action == "ace_extract" else "-u")
    log("Running " + name)
    errors = []
    with subprocess.Popen(arguments, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", env=environment) as child:
        try:
            for line in child.stdout:
                message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
                # RV2JSON uses these prefixes even when returning exit code 0.
                if re.match(r"^(?:Error|ERROR):", message):
                    errors.append(message)
                if message:
                    log(message)
            if child.wait() or errors:
                raise ValueError(errors[0] if errors else "Ace conversion failed. Review the activity log before retrying.")
        except BaseException:
            child.terminate()
            raise
    if action == 'ace_pack':
        if inputs != packing_inputs(plan['project']):
            raise ValueError('Ace JSON changed during packing. No current packing receipt was saved.')
        for name in outputs:
            path = project_path(root, name)
            if path.read_bytes()[:2] != b'\x04\x08' or path.stat().st_mtime_ns == before.get(name):
                raise ValueError('Ace packing did not produce fresh native data: ' + name)
        receipt = {'source': str(root), 'inputs': inputs, 'outputs': evidence(root, outputs)}
        write_json(Path(plan['folder']) / 'ace-packing.json', receipt)
    return {"completed": action}
