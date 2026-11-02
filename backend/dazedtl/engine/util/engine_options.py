"""Validated engine options without importing translation SDKs or Qt."""
from __future__ import annotations

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG

from util.config_integration import ConfigIntegration
from util.custom_patterns import KEYS as CUSTOM_LISTS, LABELS as CUSTOM_LABELS, normalize as normalize_custom
from util.id_ranges import normalize_id_ranges
from util.paths import PROJECT_ROOT

# Free-text lists an investigation sets for the RPG Maker engine, not choices.
WORD_LISTS = ("SPACES_356", "NBSP_356", "KEEP_356", "SPACES_108", "NBSP_108", "KEEP_108")
ENGINE_LABELS = {"rpgmakermvmz": "RPG Maker MV/MZ"}
# Engines whose modules were retired (RT1). Settings saved before keep their
# options; they read as no options rather than unknown ones.
RETIRED_ENGINES = frozenset({"csv", "wolf", "srpg"})
LABELS = {
    "FIRSTLINESPEAKERS": "First dialogue line contains the speaker", "INLINE401SPEAKERS": "Detect inline speaker names",
    "FACENAME101": "Detect names from face images", "AUTONAMEPOPUP101": "Use AutoNamePopup face mapping",
    "NAMES": "Collect character names", "BRFLAG": "Use <br> line breaks", "FIXTEXTWRAP": "Rewrap translated text",
    "IGNORETLTEXT": "Skip already translated text", "PRESERVEORIGINAL": "Preserve original source fields",
    "TLSYSTEMVARIABLES": "Translate variable names", "TLSYSTEMSWITCHES": "Translate switch names",
    "JOIN408": "Join comment continuation lines", "SPEAKERS408": "Collect comment speakers",
    "VXACE": "VX Ace game data (Ruby event scripts)",
    "CODE101": "Speaker names (101)", "CODE401": "Dialogue (401)", "CODE405": "Scrolling text (405)",
    "CODE102": "Choices (102)", "CODE408": "Supported comment continuations (408)",
    "CODE122": "Text variables (122)", "CODE122_VAR_RANGES": "Variable IDs and inclusive ranges",
    "CODE122_VAR_MIN": "Legacy variable range start", "CODE122_VAR_MAX": "Legacy variable range end",
    "CODE355655": "Script text (355 / 655)", "CODE357": "Plugin picture text (357)", "CODE657": "Extended picture text (657)",
    "CODE356": "Plugin commands (356)", "CODE320": "Character name changes (320)", "CODE324": "Nickname changes (324)",
    "CODE325": "Profile changes (325)", "CODE111": "Conditional branch text (111)", "CODE108": "Supported comments (108)",
    "ENABLED_PLUGINS_357": "Enabled plugin text handlers", "ENABLED_PATTERNS_355655": "Enabled script text handlers",
    "SPACES_356": "Plugin command handlers keeping spaces", "NBSP_356": "Plugin command handlers joining words with no-break spaces",
    "KEEP_356": "Plugin commands left untranslated", "SPACES_108": "Comment markers keeping spaces",
    "NBSP_108": "Comment markers joining words with no-break spaces", "KEEP_108": "Comments left untranslated",
    **CUSTOM_LABELS,
}


@lru_cache(maxsize=16)
def _literals(path_string, modified):
    values = {}
    for node in ast.parse(Path(path_string).read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "set" and not node.value.args:
                    values[target.id] = set()
    return values


def engine_options(code_root=PROJECT_ROOT):
    """Each engine's option schema, parsed again only after its module changes."""
    modules = []
    for engine in ENGINE_LABELS:
        path = Path(code_root) / "modules" / (engine + ".py")
        try:
            value = path.stat()
        except OSError:
            continue
        if S_ISREG(value.st_mode):
            modules.append((engine, str(path), value.st_mtime_ns, value.st_size))
    return deepcopy(_engine_options(tuple(modules)))


@lru_cache(maxsize=16)
def _engine_options(modules):
    result = {}
    for engine, path_string, modified, _size in modules:
        label, path = ENGINE_LABELS[engine], Path(path_string)
        literals = _literals(path_string, modified)
        integration = ConfigIntegration()
        values = integration.read_current_config(path)
        values.update({key: sorted(value) for key, value in integration.read_plugin_config(path).items()})
        values.update({key: literals[key] for key in (*WORD_LISTS, *CUSTOM_LISTS) if isinstance(literals.get(key), list)})
        fields = []
        for key, value in values.items():
            kind = ("boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "strings" if key in WORD_LISTS
                    else "custom" if key in CUSTOM_LISTS else "choices" if isinstance(value, list) else "string")
            field = {"key": key, "label": LABELS.get(key, key.replace("_", " ").capitalize()), "type": kind, "default": value}
            if kind == "integer":
                field.update(min=0, max=999999)
            if key == "ENABLED_PLUGINS_357":
                field["choices"] = sorted(literals.get("HEADER_MAPPINGS_357", {}))
            if key == "ENABLED_PATTERNS_355655":
                field["choices"] = sorted(literals.get("PATTERNS_355655", {}))
            fields.append(field)
        result[engine] = {"label": label, "fields": fields}
    return result


def validate_engine_options(overrides, code_root=PROJECT_ROOT):
    schema = engine_options(code_root)
    if not isinstance(overrides, dict) or set(overrides) - schema.keys() - RETIRED_ENGINES:
        raise ValueError("Unknown engine configuration.")
    result = {}
    for engine, values in overrides.items():
        if engine in RETIRED_ENGINES:
            continue
        fields = {field["key"]: field for field in schema[engine]["fields"]}
        if not isinstance(values, dict) or set(values) - fields.keys():
            raise ValueError("Unknown engine option.")
        result[engine] = {}
        for key, value in values.items():
            field = fields[key]
            kind = field["type"]
            if kind == "custom":
                # Each entry's own problem reaches the investigation that wrote it.
                result[engine][key] = normalize_custom(key, value)
                continue
            valid = (kind == "boolean" and isinstance(value, bool)
                     or kind == "integer" and type(value) is int and field["min"] <= value <= field["max"]
                     or kind in {"string", "select"} and isinstance(value, str) and len(value) <= 16000
                     or kind == "choices" and isinstance(value, list) and all(isinstance(item, str) and item in field["choices"] for item in value)
                     or kind == "strings" and isinstance(value, list) and len(value) <= 2000
                     and all(isinstance(item, str) and 0 < len(item) <= 4000 for item in value))
            if not valid or kind == "select" and value not in field["choices"]:
                raise ValueError(f"Invalid value for {field['label']}.")
            if key == "CODE122_VAR_RANGES" and value.strip():
                value = normalize_id_ranges(value)
            result[engine][key] = sorted(set(value)) if kind in {"choices", "strings"} else value
    return result


def apply_engine_options(module, overrides):
    """Apply an already validated immutable job snapshot to its engine."""
    engine = module.__name__.split(".")[-1]
    for key, value in overrides.get(engine, {}).items():
        if not hasattr(module, key):
            raise ValueError(f"The installed engine no longer supports {key}; create a new run.")
        setattr(module, key, set(value) if key.startswith("ENABLED_") else value)
