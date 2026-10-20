"""Run the preserved speaker parser locally, stopping before name translation."""

import os
import shutil
import tempfile
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path
from dazedtl.translation.speaker_setup import SCAN_VERSION


def collect(engine, files, progress):
    engine.resetSpeakerState()
    engine.setSpeakerParseMode(True)

    # The native parser returns some file errors in its result tuple. Do not
    # let a partial scan look complete just because handleMVMZ logged them.
    def checked(native, filename):
        result = native(filename)
        if result[2] is not None:
            raise ValueError(
                "Speaker scan could not parse " + filename + ". Review its scan log."
            )
        return result

    engine.openFiles.layer("speaker-scan", checked)
    try:
        for index, name in enumerate(files):
            progress(f"Scanning speaker names · {index + 1}/{len(files)} · {name}")
            if engine.handleMVMZ(name, False) == "Fail" or engine.MISMATCH:
                raise ValueError("Speaker scan could not finish " + name + ".")
        return list(
            dict.fromkeys(
                name
                for name in engine.SPEAKER_COLLECTED
                if isinstance(name, str) and name
            )
        )
    finally:
        engine.openFiles.remove("speaker-scan")
        engine.setSpeakerParseMode(False)


def configure_environment(widths):
    """Engine settings for the scan; prepare() adds the run paths and blocks
    network access."""
    # This process never receives API credentials or inherits the user's .env.
    for key in list(os.environ):
        if any(token in key.lower() for token in ("api_key", "secret", "token")) or (
            key in {"key", "api", "organization", "org"}
        ):
            os.environ.pop(key, None)
    os.environ.update(
        {
            "model": "gpt-6-luna",
            "API_PROVIDER": "openai",
            "key": "desktop-broker-only",
            "api": "https://api.openai.com/v1",
            "language": "English",
            "timeout": "45",
            "width": str(widths["width"]),
            "faceWidth": str(widths["faceWidth"]),
            "listWidth": str(widths["listWidth"]),
            "noteWidth": str(widths["noteWidth"]),
            "batchsize": "50",
            "convertQuotes": "true",
            "useSfxReference": "true",
        }
    )
    for key in (
        "BATCH_PHASE",
        "BATCH_PROVIDER",
        "TRANSLATION_LOG_REQUESTS",
        "API_KEY_OPTIONAL",
    ):
        os.environ.pop(key, None)


def run_scan(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util import paths

    validate_plan(plan)
    project = plan["project"]
    source, data = Path(project["source"]), Path(project["data"])
    relative_data = data.relative_to(source)
    sources = {}
    # Copies, logs and any parser caches stay in the app profile. The scanner
    # receives no vault, has no provider transport, and never finalizes names.
    with tempfile.TemporaryDirectory(
        prefix="speaker-scan-", dir=plan["folder"]
    ) as temporary:
        root = Path(temporary)
        for directory in (
            root / "files",
            root / "game" / relative_data,
            root / "game/.dazedtl",
            root / "context",
            root / "log",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for name, expected in plan["guard"]["data"].items():
            if Path(name).parent != Path(".") or Path(name).suffix.lower() != ".json":
                continue
            relative = (relative_data / name).as_posix()
            original = project_path(source, relative)
            raw = original.read_bytes()
            if digest(raw) != expected:
                raise ValueError("Game files changed while preparing the speaker scan.")
            sources[relative] = expected
            for target in (root / "files" / name, root / "game" / relative):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        if project.get("plugins"):
            relative = Path(project["plugins"]).relative_to(source).as_posix()
            original = project_path(source, relative)
            sources[relative] = digest(original.read_bytes())
            target = root / "game" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        for name in (".dazedtl/glossary.txt", "glossary.txt"):
            original = project_path(source, name, exists=False)
            if original.is_file():
                shutil.copyfile(original, root / "game/.dazedtl/glossary.txt")
                break
        for filename, path in (
            ("system.md", paths.PROMPT_PATH),
            ("base-glossary.txt", paths.GLOSSARY_BASE_PATH),
            ("translation_contexts.json", paths.TRANSLATION_CONTEXTS_PATH),
            ("sfx.json", paths.SFX_REFERENCE_PATH),
        ):
            shutil.copyfile(paths.runtime_data_file(path), root / "context" / filename)
        write_json(
            root / "plan.json",
            {
                "mode": "estimate",
                "engine": "RPG Maker MV/MZ",
                "engines": {
                    "rpgmakermvmz": {
                        **project["engine_options"],
                        "CODE408": project["phase1_comments"],
                    }
                },
            },
        )
        configure_environment(project["widths"])
        from desktop.backend.manual_environment import prepare

        prepare(root)  # Local mode removes credentials and blocks network access.
        from modules import rpgmakermvmz as engine

        names = collect(engine, plan["options"]["files"], log)
        from util.rpgmaker_header_check import check as check_headers

        # The same copied files show where the game's headers likely slipped.
        headers = check_headers(root / "files")
        actor_names = {
            str(key): name
            for key, name in engine._get_actor_map().items()
            if isinstance(name, str) and name
        }
        variable_actors = {
            str(key): value for key, value in engine._get_var_actor_map().items()
        }
        os.chdir(plan["folder"])
        validate_plan(plan)
        log(
            f"Found {len(names)} unique speaker names and {headers['total']} likely "
            "speaker slips. No API requests were made."
        )
        result = {
            "version": SCAN_VERSION,
            "names": names,
            "actor_names": actor_names,
            "variable_actor_ids": variable_actors,
            "headers": headers,
            "files": len(plan["options"]["files"]),
            "source_inputs": sources,
            "configuration": plan["options"]["configuration"],
            "reportId": plan["options"]["reportId"],
        }
        artifact = project_path(source, ".dazedtl/guided/speakers.json", exists=False)
        write_json(artifact, result)
        return {**result, "artifact_sha256": digest(artifact.read_bytes())}
