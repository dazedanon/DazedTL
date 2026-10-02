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
    from util.release_package import _iter_release_files
    files, excluded = _iter_release_files(Path(source))
    return {relative.as_posix(): [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
            for path, relative in files for stat in [project_path(source, relative.as_posix()).stat()]}, excluded


def run_release(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util.release_package import create_release_zip
    from dazedtl.translation.release import destination, publish
    validate_plan(plan)
    source = Path(plan["project"]["source"])
    workspace = Path(plan["folder"]).parents[1]
    output = destination(source, workspace, os.environ["DAZEDTL_ENGINE_SOURCE"], plan["options"]["output"])
    expected = plan["release_scope"]
    if release_scope(source)[0] != expected:
        raise ValueError("The package contents changed. Build a new release preview.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dazedtl-release-", dir=output.parent) as temporary:
        staged = Path(temporary) / output.name
        result = create_release_zip(source, staged, progress=lambda current, total, name: log(f"{current}/{total} · {name}"))
        if release_scope(source)[0] != expected:
            raise ValueError("The game changed during packaging. Its partial archive was discarded.")
        saved = publish(staged, output, plan["output_hash"], stopped=getattr(log, "stopped", lambda: False))
    return {**saved, "kind": "game", "files": result.files_added, "excluded": result.excluded_entries}


def guard(project, folder):
    from desktop.backend.workflow_actions import action_guard
    return action_guard(project, folder)


def phased_workflows(workspace, lock, operations, manual):
    from desktop.backend.workflow import Workflows
    class ScopedWorkflows(Workflows):
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

        def _collect(self, project):
            index = self.folder(project["id"]) / "source-inputs.json"
            if index.exists() and project.get("manual_job") in read_json(index).get("retired_runs", []):
                return  # Frozen work from an older source pass stays in its own run.
            return super()._collect(project)
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
    names = sorted({path.relative_to(root).as_posix() for path in paths})
    patch_manifest(names)
    return names


def ace_available():
    return os.name == "nt" or bool(shutil.which("wine") and shutil.which("winepath"))


def run_ace(plan, log):
    """Use bundled tools from a profile cache, never install into engine source."""
    from util.paths import PROJECT_ROOT
    from desktop.backend.workflow_actions import validate_plan
    validate_plan(plan)
    if not ace_available():
        raise ValueError("Ace conversion requires Windows or Wine. Convert the game on Windows, then reopen the game root with its ace_json export here.")
    action = plan["action"]
    root = Path(plan["project"]["source"])
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
    if os.name != "nt":
        environment.update(WINEPREFIX=str(destination.parent / "wine"), WINEDEBUG="-all")
    arguments = [str(destination)]
    if action == "ace_decrypt":
        archives = sorted(root.glob("Game.rgss*"))
        if not archives:
            raise ValueError("No Game.rgss archive needs extraction.")
        archive = str(archives[0])
        if os.name != "nt":
            archive = subprocess.run([shutil.which("winepath"), "-w", archive], check=True, capture_output=True, text=True,
                                     env=environment).stdout.strip()
        arguments.append(archive)
    else:
        arguments.append("-c" if action == "ace_extract" else "-u")
    if os.name != "nt":
        arguments.insert(0, shutil.which("wine"))
    log("Running " + name)
    errors = []
    with subprocess.Popen(arguments, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", env=environment) as child:
        try:
            for line in child.stdout:
                message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
                # RV2JSON uses these prefixes even when returning exit code 0.
                # Wine/Mesa may emit lowercase environment diagnostics without
                # preventing the console converter from completing.
                if re.match(r"^(?:Error|ERROR):", message):
                    errors.append(message)
                if message:
                    log(message)
            if child.wait() or errors:
                raise ValueError(errors[0] if errors else "Ace conversion failed. Review the activity log before retrying.")
        except BaseException:
            child.terminate()
            raise
    return {"completed": action}
