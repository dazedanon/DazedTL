"""Read installed event-text controls without importing the translation engine."""

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from dazedtl.translation.files import digest

CODES = (
    "CODE122",
    "CODE357",
    "CODE355655",
    "CODE356",
    "CODE657",
    "CODE320",
    "CODE324",
    "CODE325",
    "CODE108",
)
SELECTORS = {"CODE357": "ENABLED_PLUGINS_357", "CODE355655": "ENABLED_PATTERNS_355655"}
FIELDS = (*CODES, "CODE122_VAR_RANGES", *SELECTORS.values())
LABELS = (
    "Variable assignments (122)",
    "MZ plugin commands (357)",
    "Script text (355/655)",
    "MV plugin commands (356)",
    "Picture labels (657)",
    "Actor name changes (320)",
    "Nickname changes (324)",
    "Profile changes (325)",
    "Comment labels (108)",
)
COVERAGE = {
    "CODE122": "IDs select the assignment's starting variable only. Check its entire start/end range, operation, expression, and every internal use. The parser replaces the expression with a quoted translation.",
    "CODE357": "Registered plugin names match headers by substring and use fixed argument keys across commands. Built-in handlers also apply. Individual commands or argument keys cannot be excluded here.",
    "CODE355655": "Registered patterns translate their captured text. Built-in script handlers also apply. Variable-writing patterns are not restricted by the Code 122 variable IDs.",
    "CODE356": "One switch enables all built-in MV command handlers. There is no per-command or per-event filter.",
    "CODE657": "Processes the value of メッセージ = ... entries. Other keys are internal and skipped. There is no per-occurrence filter.",
    "CODE320": "Processes actor-name changes throughout selected files. There is no per-actor filter. AutoNamePopup can also process supported actor names independently.",
    "CODE324": "Processes nickname changes throughout selected files. There is no per-actor filter.",
    "CODE325": "Processes profile changes throughout selected files. There is no per-actor filter.",
    "CODE108": "Processes the installed comment/notetag patterns throughout selected files. There is no per-pattern checkbox.",
}


def _literals(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(value)
                except ValueError, TypeError:
                    pass
    return result


def _builtins(tree, key, subject):
    branches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and key
        in {item.id for item in ast.walk(node.test) if isinstance(item, ast.Name)}
        and "codeList" in ast.unparse(node.test)
    ]
    branch = max(branches, key=lambda node: len(node.body), default=None)
    if not branch:
        return []
    found = []
    # Only direct dispatch conditions and their elif chain, not regex literals
    # inside handler bodies or conditions inside the selectable-registry loop.
    for statement in branch.body:
        node = statement
        while isinstance(node, ast.If):
            names = {
                item.id for item in ast.walk(node.test) if isinstance(item, ast.Name)
            }
            if subject in names and not any(
                name.startswith("ENABLED_") for name in names
            ):
                for comparison in (
                    item
                    for item in ast.walk(node.test)
                    if isinstance(item, ast.Compare)
                ):
                    operands = [comparison.left, *comparison.comparators]
                    if any(
                        isinstance(item, ast.Name) and item.id == subject
                        for item in operands
                    ):
                        found.extend(
                            item.value
                            for item in operands
                            if isinstance(item, ast.Constant)
                            and isinstance(item.value, str)
                        )
            # The preserved MV choice handler has an unconditional string test.
            # Its actual regex guard is inside the body; it still belongs to
            # the coarse source switch and has no independent control.
            elif (
                key == "CODE356"
                and isinstance(node.test, ast.Constant)
                and isinstance(node.test.value, str)
            ):
                found.append(node.test.value)
            node = node.orelse[0] if len(node.orelse) == 1 else None
    return sorted(set(found))


@lru_cache(maxsize=4)
def _catalog(path, modified, changed, size):
    raw = Path(path).read_bytes()
    tree = ast.parse(raw)
    values = _literals(tree)
    handlers = values.get("HEADER_MAPPINGS_357")
    patterns = values.get("PATTERNS_355655")
    if not isinstance(handlers, dict) or not isinstance(patterns, dict):
        raise ValueError("The installed engine has no supported event-text registry.")
    controls = []
    for key, label in zip(CODES, LABELS):
        choices, builtins = [], []
        if key == "CODE357":
            choices = [
                {
                    "id": name,
                    "group": "Message and picture text"
                    if any(
                        arg.lower() in {"text", "message", "messagetext"}
                        for arg in args
                    )
                    else "Other plugin text",
                    "details": "Header substring: "
                    + name
                    + "; fixed argument keys: "
                    + ", ".join(args),
                }
                for name, (args, _font) in sorted(handlers.items())
            ]
            builtins = _builtins(tree, key, "headerString")
        elif key == "CODE355655":
            choices = [
                {
                    "id": name,
                    "group": "Variable assignments"
                    if "gameVariables" in name
                    else "Multiline scripts"
                    if multiline
                    else "Single-line scripts",
                    "details": ("Multiline" if multiline else "Single-line")
                    + "; last regex capture is translated: "
                    + regex,
                }
                for name, (regex, multiline) in sorted(patterns.items())
            ]
            builtins = _builtins(tree, key, "jaString")
        elif key == "CODE356":
            builtins = _builtins(tree, key, "jaString")
        elif key == "CODE108":
            function = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_code108_match"
                ),
                None,
            )
            for statement in function.body if function else []:
                if isinstance(statement, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "patterns"
                    for target in statement.targets
                ):
                    builtins = [
                        marker for marker, _regex in ast.literal_eval(statement.value)
                    ]
        controls.append(
            {
                "key": key,
                "label": label,
                "coverage": COVERAGE[key],
                "selector": SELECTORS.get(key),
                "choices": choices,
                "builtins": builtins,
            }
        )
    return {"fingerprint": digest(raw), "source": str(path), "controls": controls}


def catalog(source):
    path = Path(source) / "modules/rpgmakermvmz.py"
    if path.is_symlink():
        raise ValueError("The installed event-text registry must be a regular file.")
    stat = path.stat()
    return deepcopy(
        _catalog(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    )


def validate_options(options, source):
    from util.engine_options import validate_engine_options

    if not isinstance(options, dict) or set(options) - set(FIELDS):
        raise ValueError("Unknown event-text setting.")
    return validate_engine_options({"rpgmakermvmz": options}, source)["rpgmakermvmz"]
