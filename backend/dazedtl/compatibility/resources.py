"""Route preserved engine readers to DazedTL-owned translation resources."""

from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
SHARED_FILES = frozenset(
    {
        "skills/system.md",
        "translation_contexts.json",
        "glossary_base.txt",
        "sfx_reference/j_ono.json",
        "skills/ace_script_translation.md",
        "skills/character_identity.md",
        "skills/evaluation_csv_review.md",
        "skills/evaluation_pairwise_review.md",
        "skills/image_translation.md",
        "skills/localization_investigation.md",
        "skills/plugin_translation.md",
        "skills/post_update_translation.md",
        "skills/project_setup.md",
        "skills/risky_codes.md",
        "skills/rpgmaker_translation_qa.md",
        "skills/wolf_precheck_repair.md",
        "skills/wolf_speakers.md",
        "skills/wrap_config.md",
        "skills/build-game-walkthrough/SKILL.md",
        "skills/setup-generic-game/SKILL.md",
    }
)


def install():
    """Install before importing engine consumers, including in child workers.

    Keep the native resolver's scoped overrides and path validation. Frozen run
    context lives outside the engine data directory and must never be redirected.
    No defaults are copied into profiles: uncustomized projects follow this
    package's resources on the next preparation, while saved runs keep theirs.
    """
    from util import paths

    if getattr(paths.runtime_data_file, "_dazedtl_resources", False) is True:
        return
    native = paths.runtime_data_file
    engine_data = paths.DATA_DIR

    def resolve(default, profile=None):
        default = Path(default)
        try:
            relative = default.relative_to(engine_data).as_posix()
        except ValueError:
            try:
                relative = default.relative_to(DATA_ROOT).as_posix()
            except ValueError:
                return native(default, profile)
        if relative not in SHARED_FILES:
            return native(default, profile)
        # The engine's override convention is relative to its own DATA_DIR.
        # Reuse it for both old template paths and our canonical resource paths.
        original = engine_data / relative
        selected = native(original, profile)
        if selected != original:
            return selected
        bundled = DATA_ROOT / relative
        if bundled.is_symlink() or not bundled.is_file():
            raise FileNotFoundError(
                "DazedTL translation resource missing or invalid: " + relative
            )
        return bundled

    resolve._dazedtl_resources = True
    paths.runtime_data_file = resolve
    for constant, relative in {
        "PROMPT_PATH": "skills/system.md",
        "GLOSSARY_BASE_PATH": "glossary_base.txt",
        "TRANSLATION_CONTEXTS_PATH": "translation_contexts.json",
        "SFX_REFERENCE_PATH": "sfx_reference/j_ono.json",
    }.items():
        setattr(paths, constant, DATA_ROOT / relative)
