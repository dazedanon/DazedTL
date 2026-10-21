"""Rejects file calls that skip the platform layer's Windows waits.

Ruff's banned-api rule (TID251 in pyproject.toml) sees module calls such as
os.replace but not method calls, so this check extends it to the calls Ruff
cannot see. It reads the files ruff lints, spares those whose per-file
ignores list TID251, and accepts a call marked `# platform: <reason>`; Ruff
reports a `# noqa: TID251` it has no error for as unused.

Moves and deletes: the Path methods that move or delete a file without the
wait Windows needs while a reader holds it. A Path is not known without type
information, so a call counts when it is a .replace or .rename with one
positional argument or only target=, shapes no str, bytes or datetime call
has; an unbound Path.replace(a, b) counts too. .unlink and .rmdir count with
no positional argument, as only a Path's take none.

Run record reads: read_text, read_bytes and open of a run record (RECORDS),
which fail on Windows while a live run replaces the file. A path counts as a
run record when its last part is one, written in place or held in a name of
its function or module, a loop over such paths or a project_path, glob or
Path call naming one. A reader that takes the path as an argument, such as a
Live run's translated output, is out of its sight.

Live paths: project_path of a run record or of a file under a run's
translated/ folder, which resolves the file and fails on Windows while a
worker replaces it; translation.files.live_path checks the folder instead.

Usage: python scripts/platform_calls.py <ruff>
"""

import ast
import re
import sys
import tomllib
import warnings
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from dazedtl import system

METHODS = {"replace": "system.replace", "rename": "system.rename"}
DELETES = {"unlink": "system.unlink", "rmdir": "system.rmdir"}
# Module functions of the same shape that copy an object instead of moving a file.
COPIES = {"copy", "dataclasses"}
MARK = re.compile(r"#\s*platform:\s*\S")
# Files a live run replaces while another process reads them.
RECORDS = {
    # A run's own records.
    "attempt.json",
    "job.json",
    "plan.json",
    # Batch queue and recovery files.
    "batch_history.json",
    "batch_requests.json",
    "batch_results.json",
    "batch_state.json",
    "dazedtl-batch-evidence.json",
    "dazedtl-batch-submission.json",
    "dazedtl-clarified-results.json",
    "estimate_requests.json",
    # Per-file workers' shared progress.
    "dazedtl-checkpoints.json",
    "dazedtl-speaker-results.json",
    "var_translation_map.json",
    # Text QA's task state.
    "checkpoint.json",
}
READS = {"read_text", "read_bytes", "open"}
# Folders whose files a run's workers replace while it runs.
LIVE_FOLDERS = ("translated/",)
# Calls whose result names the same file as the path among their arguments.
PATH_CALLS = {
    "Path",
    "PurePath",
    "beneath",
    "glob",
    "joinpath",
    "list",
    "project_path",
    "rglob",
    "sorted",
    "with_name",
}
# Path methods whose result names the file they are called on.
SAME_FILE = {"absolute", "expanduser", "resolve"}


def exempt_patterns():
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = settings["tool"]["ruff"]["lint"]["per-file-ignores"]
    return [pattern for pattern, codes in ignores.items() if "TID251" in codes]


def linted_files(ruff):
    listing = system.run(
        [ruff, "check", "--show-files", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line) for line in listing.stdout.splitlines() if line.endswith(".py")]


def moved_by(call):
    """The Path method a call makes, or None for another call."""
    function = call.func
    if not isinstance(function, ast.Attribute):
        return None
    if function.attr in DELETES:
        return deleted_by(call)
    if function.attr not in METHODS:
        return None
    owner = function.value
    if isinstance(owner, ast.Name) and owner.id in COPIES:
        return None
    if isinstance(owner, ast.Name) and owner.id == "Path" and len(call.args) == 2:
        return function.attr
    if isinstance(owner, ast.Constant):
        return None
    if len(call.args) == 1 and not call.keywords:
        return None if isinstance(call.args[0], ast.Starred) else function.attr
    if not call.args and [keyword.arg for keyword in call.keywords] == ["target"]:
        return function.attr
    return None


class Records:
    """The local names of one function, or of a module's top level, that
    hold a run record's path, found without regard to order; outer names
    are the module's, which its functions see."""

    def __init__(self, scope, outer=()):
        self.names = set(outer)
        bindings = list(_bindings(scope))
        while True:
            found = {
                name
                for target, value in bindings
                if self.names_record(value)
                for name in _names(target)
            }
            if found <= self.names:
                return
            self.names |= found

    def names_record(self, node):
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str) and _record_name(node.value)
        if isinstance(node, ast.JoinedStr):
            tail = node.values[-1] if node.values else None
            return isinstance(tail, ast.Constant) and _record_name(tail.value)
        if isinstance(node, ast.Name):
            return node.id in self.names
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            return self.names_record(node.right)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(self.names_record(element) for element in node.elts)
        if isinstance(node, (ast.Subscript, ast.Starred)):
            return self.names_record(node.value)
        if isinstance(node, ast.IfExp):
            return self.names_record(node.body) or self.names_record(node.orelse)
        if not isinstance(node, ast.Call):
            return False
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else None
        if isinstance(function, ast.Name):
            name = function.id
        if name in SAME_FILE and isinstance(function, ast.Attribute):
            return self.names_record(function.value)
        return name in PATH_CALLS and any(
            self.names_record(argument) for argument in node.args
        )


def resolved_by(call, records):
    """project_path's name when a call resolves a live file with it."""
    function = call.func
    name = function.attr if isinstance(function, ast.Attribute) else None
    if isinstance(function, ast.Name):
        name = function.id
    if name != "project_path" or len(call.args) < 2:
        return None
    relative = call.args[1]
    if records.names_record(relative) or _live_folder(relative):
        return name
    return None


def _live_folder(node):
    """A path a run's workers write while it runs, by its literal start."""
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        node = node.left
    if isinstance(node, ast.JoinedStr) and node.values:
        node = node.values[0]
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(LIVE_FOLDERS)
    )


def _record_name(text):
    return text.rsplit("/", 1)[-1] in RECORDS


def _bindings(scope):
    """(target, value) for each name scope binds, nested functions included;
    loops bind their targets to what they iterate."""
    for node in _inside(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield from _paired(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value:
            yield node.target, node.value
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            yield node.target, node.iter


def _paired(target, value):
    same_shape = isinstance(target, (ast.Tuple, ast.List)) and isinstance(
        value, (ast.Tuple, ast.List)
    )
    if same_shape and len(target.elts) == len(value.elts):
        for element, part in zip(target.elts, value.elts, strict=True):
            yield from _paired(element, part)
    else:
        yield target, value


def _names(target):
    """The names a target binds; an attribute or item it sets binds none."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _names(element)}
    return set()


def read_by(call, records):
    """The raw read a call makes of a run record, or None for another call."""
    function = call.func
    if isinstance(function, ast.Attribute) and function.attr in READS:
        owner = function.value
        if isinstance(owner, ast.Name) and owner.id in {"io", "system"}:
            if function.attr != "open":
                return None
        elif records.names_record(owner):
            return f"Path.{function.attr}"
    builtin = isinstance(function, ast.Name) and function.id == "open"
    module = isinstance(function, ast.Attribute) and function.attr == "open"
    if (builtin or module) and call.args and records.names_record(call.args[0]):
        return "open"
    return None


def _scopes(tree):
    """The module's top level, then each function no other function holds,
    whose names its nested functions see too."""
    yield tree
    pending = list(ast.iter_child_nodes(tree))[::-1]
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        else:
            pending.extend(list(ast.iter_child_nodes(node))[::-1])


def _inside(scope):
    """The nodes of a scope in source order; the top level leaves its
    functions to them."""
    pending = list(ast.iter_child_nodes(scope))[::-1]
    while pending:
        node = pending.pop()
        if isinstance(scope, ast.Module) and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        yield node
        pending.extend(list(ast.iter_child_nodes(node))[::-1])


def deleted_by(call):
    """Path.unlink or Path.rmdir, called on a path or unbound on Path; no str,
    bytes or module function of those names takes no path argument."""
    function = call.func
    owner = function.value
    keywords = {keyword.arg for keyword in call.keywords}
    if isinstance(owner, ast.Name) and owner.id == "Path" and len(call.args) == 1:
        return function.attr
    if call.args or not keywords <= {"missing_ok"}:
        return None
    return function.attr


def problems(path, relative):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    with warnings.catch_warnings():
        # Old escapes in the engine's strings are ruff's to report.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(text, filename=str(path))

    def marked(node):
        end = node.end_lineno or node.lineno
        return any(MARK.search(line) for line in lines[node.lineno - 1 : end])

    def where(node):
        return f"{relative}:{node.lineno}:{node.col_offset + 1}: "

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = moved_by(node)
        if method is None or marked(node):
            continue
        yield (
            f"{where(node)}Path.{method} does not wait for readers on Windows; "
            f"use {(METHODS | DELETES)[method]} (engine: util.system)."
        )
    module = Records(tree)
    for scope in _scopes(tree):
        records = module if scope is tree else Records(scope, module.names)
        for node in _inside(scope):
            read = isinstance(node, ast.Call) and read_by(node, records)
            if not read or marked(node):
                continue
            yield (
                f"{where(node)}{read} of a run record fails on Windows while a "
                "run replaces it; use system.read_bytes or system.read_text "
                "(engine: util.system)."
            )
        for node in _inside(scope):
            if not isinstance(node, ast.Call) or marked(node):
                continue
            if resolved_by(node, records):
                yield (
                    f"{where(node)}project_path resolves a file a run replaces, "
                    "which fails on Windows mid-replace; use "
                    "translation.files.live_path."
                )


def main():
    exempt = exempt_patterns()
    found = []
    for path in linted_files(sys.argv[1]):
        relative = PurePosixPath(path.resolve().relative_to(ROOT).as_posix())
        if any(relative.full_match(pattern) for pattern in exempt):
            continue
        found.extend(problems(path, relative))
    for problem in found:
        print(problem)
    if found:
        print(
            f"{len(found)} file call(s) outside the platform layer. A call that"
            " must stay raw is marked `# platform: <reason>`."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
