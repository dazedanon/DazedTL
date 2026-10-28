"""Len's project settings, shared context and local work rules for the game-translation skill."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from util import system
from util.paths import (
    DATA_DIR, GAME_TOOL_GITIGNORE_BEGIN, GLOSSARY_BASE_SEPARATOR, LEN_PATCH_GITIGNORE_BEGIN, LEN_WORK_GITIGNORE_BEGIN,
    LEN_WORK_GITIGNORE_END, SKILLS_DIR, game_git_set_up, game_glossary_path, glossary_base_text,
    runtime_data_files_pinned,
    prepare_game_translation_context, read_game_glossary, without_gitignore_section,
)
from util.languages import active_source
from util.prompt_pair import render as render_prompt, run_language
from util.skills import load_system_prompt
from util.reference_games import load_registry, reference_context
from util.project_preparation import rpgmaker_layout


BUNDLED_SKILL = SKILLS_DIR / "game-translation"
WORKSPACE_RELATIVE = Path(".dazedtl") / "len-method"
_WORK_IGNORE_BEGIN = LEN_WORK_GITIGNORE_BEGIN
_WORK_IGNORE_END = LEN_WORK_GITIGNORE_END
_WORK_IGNORE_BLOCK = f"""{_WORK_IGNORE_BEGIN}
# Len work, guidance, translation stores and QA artifacts stay local.
# Runtime patch files are selected separately with git-scope.
/.dazedtl/**
.env
.env.*
.api_key
api_keys.json
*_key.txt
*_keys.txt
.venv/
venv/
__pycache__/
node_modules/
saves/
save/
logs/
cache/
{_WORK_IGNORE_END}
"""
MODES = {
    "local": "Agent Translation",
    "api": "API Batch Translation",
}


@dataclass(frozen=True)
class LenProject:
    game_root: Path
    mode: str = "local"
    include_images: bool = True
    instructions: str = ""
    include_glossary_base: bool = True
    install_forge: bool = True

    @property
    def workspace(self) -> Path:
        return self.game_root / WORKSPACE_RELATIVE

    @property
    def legacy_skill_root(self) -> Path:
        """Preserve adaptations made by the initial ZIP-based integration."""
        return self.workspace / "game-translation"

    @property
    def work_root(self) -> Path:
        return self.workspace / "work"


def _validate_project(project: LenProject) -> None:
    if not project.game_root.is_absolute() or not project.game_root.is_dir():
        raise ValueError("Choose an existing game folder.")
    if project.mode not in MODES:
        raise ValueError("Choose a supported translation mode.")
    if any(type(value) is not bool for value in (project.include_images, project.include_glossary_base, project.install_forge)):
        raise ValueError("Image scope, base glossary and Forge installation must be enabled or disabled.")
    if not isinstance(project.instructions, str):
        raise ValueError("Project instructions must be text.")
    # Do not write through project metadata symlinks into unrelated locations.
    for path in (project.game_root / ".dazedtl", project.workspace, project.work_root):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"The Len workspace must use normal directories: {path}")


def load_project(game_root: Path) -> LenProject:
    game_root = game_root.expanduser().resolve()
    _validate_project(LenProject(game_root))
    path = game_root / WORKSPACE_RELATIVE / "project.json"
    if not path.exists():
        project = LenProject(game_root)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in {1, 2, 3}:
            raise ValueError("Unsupported Len project settings version.")
        # Resolve against the selected game so a moved folder remains portable.
        # Legacy task selection and quote approval do not constrain a new run.
        # The skill resumes from artifacts and reviews costs before paid work.
        project = LenProject(game_root, include_glossary_base=data.get("include_glossary_base", True),
                             install_forge=data.get("install_forge", True),
                             **{key: data[key] for key in (
            "mode", "include_images", "instructions"
        )})
    _validate_project(project)
    return project


def _validate_skill(root: Path) -> None:
    for relative in ("SKILL.md", "scripts/check_tools.py", "tools/THIRD-PARTY.md"):
        if not (root / relative).is_file() or (root / relative).is_symlink():
            raise ValueError(f"Incomplete game-translation skill: missing {relative}")
    if not (root / "references").is_dir():
        raise ValueError("Incomplete game-translation skill: missing references/")


def shared_context(project: LenProject, language: str | None = None) -> dict:
    """Read the same portable guidance used by Workflow, without changing process settings,
    for translating the active source language into *language*, the run's by default."""
    language = run_language(language)
    _validate_project(project)
    prepare_game_translation_context(project.game_root)
    glossary = read_game_glossary(project.game_root)
    custom = glossary.split(GLOSSARY_BASE_SEPARATOR, 1)[0].rstrip()
    # The shared editor owns the custom section; refreshed shipped defaults are derived.
    base = glossary_base_text() if project.include_glossary_base else ""
    glossary = custom + "\n"
    if base:
        glossary += "\n" + GLOSSARY_BASE_SEPARATOR + base
    context = {
        "schema": 1,
        "game_root": str(project.game_root),
        "system": render_prompt(load_system_prompt(project.game_root), active_source(), language),
        "glossary": glossary,
        "glossary_file": str(game_glossary_path(project.game_root, migrate=False)),
        "skills_folder": str(project.game_root / ".dazedtl" / "skills"),
        "include_glossary_base": project.include_glossary_base,
        "references": load_registry(project.game_root),
    }
    context["content_sha256"] = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return context


def _line_speakers(sources, speakers):
    """Validate a complete speaker map/list before context files can be prepared."""
    if speakers is None:
        return None
    if isinstance(sources, dict):
        if not isinstance(speakers, dict) or set(speakers) != set(sources):
            raise ValueError("Speakers must have exactly the same IDs as sources; use null for unidentified speakers.")
        values = [speakers[key] for key in sources]
    else:
        if not isinstance(speakers, list) or len(speakers) != len(sources):
            raise ValueError("Speakers must be a list aligned with every source line; use null for unidentified speakers.")
        values = speakers
    normalized = []
    for value in values:
        if value is None:
            normalized.append(None)
        elif not isinstance(value, str) or any(char in value for char in "\r\n\0"):
            raise ValueError("Each speaker must be a single-line name or null.")
        else:
            normalized.append(value.strip() or None)
    return dict(zip(sources, normalized)) if isinstance(sources, dict) else normalized


def request_context(project: LenProject, sources: list[str] | dict[str, str], *,
                    instruction_key: str | None = None, source_context: str = "",
                    speakers: list[str | None] | dict[str, str | None] | None = None,
                    glossary_names: list[str] | tuple[str, ...] = (),
                    language: str | None = None, _shared=None, _reference_pack=None) -> dict:
    """Compile one batch with DazedTL's actual glossary/SFX matching and current instructions.

    ``glossary_names`` are names a request's notes mention, such as who uses a
    skill, whose glossary entries join its matched glossary as speakers' do.
    No provider calls. Pipelines consume these fields directly instead of rebuilding prompts.
    """
    from util.skills import ctx
    from util.translation import createContextParts

    values = list(sources.values()) if isinstance(sources, dict) else sources
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise ValueError("Sources must be a nonempty JSON list of strings or an ID-to-string object.")
    if isinstance(sources, dict) and not all(isinstance(key, str) and key for key in sources):
        raise ValueError("Source IDs must be nonempty strings.")
    line_speakers = _line_speakers(sources, speakers)
    speaker_names = list(line_speakers.values()) if isinstance(line_speakers, dict) else line_speakers or []
    language = run_language(language)
    shared = _shared if _shared is not None else shared_context(project, language)
    payload = json.dumps(sources, ensure_ascii=False)
    config = SimpleNamespace(prompt=shared["system"], vocab=shared["glossary"], language=language, useSfxReference=True)
    system, glossary, sfx, user = createContextParts(
        config, payload, "json",
        speaker_names=tuple(dict.fromkeys(name for name in [*speaker_names, *glossary_names] if name)),
    )
    if line_speakers is not None:
        metadata = json.dumps(line_speakers, ensure_ascii=False)
        user = (
            "Speaker metadata for the source below, matched by the same IDs or list positions. "
            "Use it with the glossary for character voice and pronoun context. "
            "Null means no identified speaker; do not automatically carry a previous speaker forward. "
            "These labels are context only: do not translate this metadata, add it to dialogue, "
            "or include it as extra output fields. Preserve any speaker tags actually present in the source.\n"
            f"```json\n{metadata}\n```\n\n"
            "Translate only the following source text, keeping its IDs/order and the required output schema:\n"
            + user
        )
    result = {
        "schema": 1, "context_sha256": shared["content_sha256"],
        "system": system, "glossary": glossary, "sfx_reference": sfx,
        "request_instructions": ctx(instruction_key, language=language, context=source_context) if instruction_key else "",
        "preceding_japanese_source_context": source_context,
        "user": user,
        "reference_translations": (_reference_pack if _reference_pack is not None
                                   else reference_context(project.game_root, values)),
    }
    if line_speakers is not None:
        result["speakers"] = line_speakers
    result["request_sha256"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return result


def _reference_subset(references, sources):
    """Keep canonical reference evidence identical to a single-batch lookup."""
    wanted = set(sources.values() if isinstance(sources, dict) else sources)
    pack = dict(references)
    if pack["status"] == "ready":
        pack["matches"] = {key: value for key, value in pack["matches"].items() if key in wanted}
        pack["source_count"] = len(pack["matches"])
        pack.pop("content_sha256")
        pack["content_sha256"] = hashlib.sha256(json.dumps(
            pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
    return pack


def request_contexts(project: LenProject, batches: list[dict], language: str | None = None) -> list[dict]:
    """Compile a scene-ordered set with one guidance load and one reference census,
    translating into *language*, the run's by default.

    Returned requests are identical to independent request_context calls. A changed
    dependency aborts the whole operation; no persistent cache can bless stale work.
    """
    if not isinstance(batches, list) or not batches:
        raise ValueError("Supply a nonempty list of context batches.")
    language = run_language(language)
    identities = set()
    sources = []
    for batch in batches:
        if not isinstance(batch, dict) or batch.keys() - {"id", "sources", "speakers", "instruction_key", "source_context", "glossary_names"}:
            raise ValueError("Context batches accept id, sources, speakers, instruction_key, source_context and glossary_names.")
        identity = batch.get("id")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("Each context batch needs a unique nonempty id.")
        identities.add(identity)
        values = batch.get("sources")
        values = list(values.values()) if isinstance(values, dict) else values
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ValueError("Each batch needs a nonempty source list or source object.")
        sources.extend(values)
    # Every request reads the same runtime files; finding each once spares a
    # big compile thousands of path lookups, which Windows makes slow. The
    # check below looks again.
    with runtime_data_files_pinned():
        shared = shared_context(project, language)
        references = reference_context(project.game_root, sources)
        result = []
        for batch in batches:
            values = batch["sources"]
            pack = _reference_subset(references, values)
            request = request_context(project, **{key: value for key, value in batch.items() if key != "id"},
                                      language=language, _shared=shared, _reference_pack=pack)
            result.append({"id": batch["id"], "sources": batch["sources"], "context": request})
    if shared_context(project, language)["content_sha256"] != shared["content_sha256"] or reference_context(project.game_root, sources) != references:
        raise ValueError("Guidance or references changed during compilation; retry the entire operation.")
    return result


def import_glossary(project: LenProject, document: dict) -> dict:
    """Merge Len's names/en or legacy characters/name schema into the shared glossary.

    Existing decisions are preserved. Any conflicting source/alias aborts the entire import.
    Non-display identifiers remain extraction metadata in the original JSON, never prompt rows.
    """
    from util.translation import parseVocabWithCategories
    from util.vocab import append_vocab_rows, glossary_row_sources

    _validate_project(project)
    if not isinstance(document, dict):
        raise ValueError("The imported glossary must be a JSON object.")
    if "names" in document and "characters" in document:
        raise ValueError("Use one name schema: names or characters, not both.")
    names = document.get("names", document.get("characters", {}))
    terms = document.get("terms", {})
    if not isinstance(names, dict) or not isinstance(terms, dict) or not (names or terms):
        raise ValueError("Expected nonempty names/characters or terms objects.")

    def one_line(value, label):
        if not isinstance(value, str) or not value.strip() or any(char in value for char in "\r\n\0"):
            raise ValueError(f"{label} must be nonempty single-line text.")
        return value.strip()

    protected_pairs = set()
    pairs = document.get("do_not_merge", [])
    if not isinstance(pairs, list):
        raise ValueError("do_not_merge must be a list of Japanese name pairs.")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
            raise ValueError("do_not_merge must contain pairs of Japanese names.")
        protected_pairs.add(frozenset(one_line(item, "Protected identity") for item in pair))
    candidates: dict[str, tuple[str, str, str]] = {}

    def add(source, target, notes, category):
        source = one_line(source, "Japanese source")
        target = one_line(target, "English target")
        parsed = parseVocabWithCategories(f"{category}\n{source} ({target})")
        if not parsed or parsed[0][0] != (source, target):
            raise ValueError(f"Cannot represent {source} ({target}) in the shared glossary format.")
        aliases = glossary_row_sources(source, category)
        if any(pair.issubset(aliases) for pair in protected_pairs):
            raise ValueError(f"Give protected identities in {source} separate name entries.")
        for alias in aliases:
            if alias in candidates and candidates[alias][0] != target:
                raise ValueError(f"The imported glossary has conflicting translations for {alias}.")
            candidates.setdefault(alias, (target, notes, category))

    for source, info in names.items():
        one_line(source, "Japanese name")
        if not isinstance(info, dict):
            raise ValueError(f"Name {source} must have a structured entry.")
        target = info.get("en", info.get("name"))
        notes = []
        for key in ("gender", "role", "register", "speech", "personality", "note"):
            if info.get(key):
                notes.append(f"{key}: {one_line(info[key], key)}")
        if str(info.get("gender", "")).casefold() == "unknown":
            notes.append("Do not infer gender; preserve any deliberate uncertainty.")
        add(source, target, "; ".join(notes), "# Game Characters")
        aliases = info.get("aliases", [])
        if not isinstance(aliases, list):
            raise ValueError(f"Aliases for {source} must be a list.")
        for alias in aliases:
            alias = one_line(alias, "Alias")
            if alias in names:
                continue  # Public and revealed identities retain their own named rows.
            if frozenset((source, alias)) in protected_pairs:
                raise ValueError(f"Give protected identity {alias} its own name entry before importing.")
            add(alias, target, "; ".join(notes), "# Game Characters")
    for source, target in terms.items():
        add(source, target, "", "# Game Terms")

    additions: dict[str, tuple[str, str, str]] = {}

    def sections(current: str) -> dict[str, list[tuple[str, str, str]]]:
        """The rows to add to the glossary as it is under the write lock."""
        existing: dict[str, str] = {}
        for pair, _line, category in parseVocabWithCategories(current):
            if not isinstance(pair, tuple):
                continue
            source, target = pair
            for alias in glossary_row_sources(source, category):
                if alias in existing and existing[alias] != target:
                    raise ValueError(f"Resolve conflicting existing glossary entries for {alias} first.")
                existing[alias] = target
        conflicts = [source for source, (target, *_rest) in candidates.items() if source in existing and existing[source] != target]
        if conflicts:
            raise ValueError("Import conflicts with the shared glossary: " + ", ".join(conflicts))
        additions.update((source, entry) for source, entry in candidates.items() if source not in existing)
        return {owner.removeprefix("# "): [(source, target, notes) for source, (target, notes, category) in additions.items()
                                           if category == owner]
                for owner in ("# Game Characters", "# Game Terms")}

    append_vocab_rows(sections, game_root=project.game_root)
    return {"added": len(additions), "preserved": len(candidates) - len(additions),
            "glossary_file": str(game_glossary_path(project.game_root, migrate=False)),
            "extraction_metadata": document.get("do_not_translate", [])}


def _write_atomic(path: Path, text: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {path}")
    temporary = path.with_name(f".{path.name}.{os.urandom(8).hex()}.tmp")
    try:
        # Opened with the usual mode so the umask applies; a new file such as
        # the game's .gitignore is not left private like a mkstemp file.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(descriptor, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as handle:
            handle.write(text)
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        system.replace(temporary, path)
    finally:
        system.unlink(temporary, ignore_errors=True)


def _below_work(text: str) -> int:
    """Where the first block that goes below Len's work block starts: the
    patch rules, or the portable-settings allowlist, which a game recorded
    before its Git setup has alone; -1 without either."""
    found = [index for index in (text.find(LEN_PATCH_GITIGNORE_BEGIN), text.find(GAME_TOOL_GITIGNORE_BEGIN)) if index >= 0]
    return min(found, default=-1)


def _prepare_local_work(project: LenProject) -> None:
    """Keep all Len working state local, before the patch rules and the
    portable-settings allowlist after them, which Git setup and each
    checkpoint put in that order. Like those rules, the block waits for the
    game's Git setup, whose history it serves."""
    if not game_git_set_up(project.game_root):
        project.work_root.mkdir(parents=True, exist_ok=True)
        return
    ignore = project.game_root / ".gitignore"
    text = ignore.read_text(encoding="utf-8", errors="surrogateescape") if ignore.exists() else ""
    if text.count(_WORK_IGNORE_BEGIN) != text.count(_WORK_IGNORE_END) or text.count(_WORK_IGNORE_BEGIN) > 1:
        raise ValueError("The Len project .gitignore block is incomplete or duplicated.")
    if _WORK_IGNORE_BEGIN in text:
        start = text.index(_WORK_IGNORE_BEGIN)
        end = text.index(_WORK_IGNORE_END) + len(_WORK_IGNORE_END)
        if end < start:
            raise ValueError("The Len project .gitignore block is out of order.")
        # A current block anywhere above the patch rules already keeps the work
        # local. A checkpoint can leave the image patch rules after it, and
        # moving it again would change a committed .gitignore.
        below = _below_work(text)
        if text[start:end] + "\n" == _WORK_IGNORE_BLOCK and (below < 0 or end < below):
            project.work_root.mkdir(parents=True, exist_ok=True)
            return
        text = without_gitignore_section(text, start, end)
    below = _below_work(text)
    if below >= 0:
        updated = text[:below].rstrip() + "\n\n" + _WORK_IGNORE_BLOCK + "\n" + text[below:].lstrip("\r\n")
    else:
        updated = text.rstrip() + "\n\n" + _WORK_IGNORE_BLOCK
    if not ignore.exists() or ignore.read_text(encoding="utf-8", errors="surrogateescape") != updated:
        _write_atomic(ignore, updated)
    project.work_root.mkdir(parents=True, exist_ok=True)


def setup_forge(project: LenProject) -> dict:
    """Honor Len's saved opt-in using Workflow's existing offline Forge installer."""
    _validate_project(project)
    layout = rpgmaker_layout(project.game_root)
    if not layout or layout["engine"] != "MVMZ":
        return {"status": "unsupported", "message": "Forge supports RPG Maker MV/MZ only."}
    if not project.install_forge:
        return {"status": "skipped", "message": "Forge installation is disabled for this project."}
    from util.forge.installer import install
    from util.playtest.config import load_config
    from util.project_preparation import format_plugins_js

    try:
        cfg = load_config(DATA_DIR.parent / ".env")
        if os.environ.get("DAZEDTL_DESKTOP_WORKSPACE"):
            from desktop.backend.cli_environment import public_values
            values = public_values(os.environ["DAZEDTL_DESKTOP_WORKSPACE"])
            cfg = {"hotkey": values["tlHotkey"], "forgeHotkey": values["forgeHotkey"],
                   "uiScale": values["playtestUiScale"], "editorCmd": values["tlEditorCmd"], "workspaceFolder": "auto"}
        ok, message = install(project.game_root, cfg=cfg)
        if not ok:
            raise ValueError(message)
        format_plugins_js(layout["plugins_js"])
    finally:
        # The shared installer exposes Workflow's portable guidance. Len's
        # runtime-patch repositories keep all of that working material local.
        _prepare_local_work(project)
    return {"status": "installed", "message": message}
