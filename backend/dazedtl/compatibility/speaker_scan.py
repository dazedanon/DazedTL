"""Run the preserved speaker parser locally, stopping before name translation."""

import os
from pathlib import Path
import shutil
import tempfile

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path


def collect(engine, files, progress):
    engine.resetSpeakerState()
    engine.setSpeakerParseMode(True)
    # The native parser returns some file errors in its result tuple. Do not
    # let a partial scan look complete just because handleMVMZ logged them.
    original = engine.openFiles

    def checked(filename):
        result = original(filename)
        if result[2] is not None:
            raise ValueError(
                "Speaker scan could not parse " + filename + ". Review its scan log."
            )
        return result

    engine.openFiles = checked
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
        engine.openFiles = original
        engine.setSpeakerParseMode(False)


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
        from desktop.backend.rpgmaker_worker import configure_environment

        configure_environment(root, {**project["widths"], "batchsize": 50})
        from desktop.backend.manual_environment import prepare

        prepare(root)  # Local mode removes credentials and blocks network access.
        from modules import rpgmakermvmz as engine

        names = collect(engine, plan["options"]["files"], log)
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
        log(f"Found {len(names)} unique speaker names. No API requests were made.")
        result = {
            "names": names,
            "actor_names": actor_names,
            "variable_actor_ids": variable_actors,
            "files": len(plan["options"]["files"]),
            "source_inputs": sources,
            "configuration": plan["options"]["configuration"],
            "reportId": plan["options"]["reportId"],
        }
        artifact = project_path(source, ".dazedtl/guided/speakers.json", exists=False)
        write_json(artifact, result)
        return {**result, "artifact_sha256": digest(artifact.read_bytes())}
