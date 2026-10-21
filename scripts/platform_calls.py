"""Rejects Path.replace and Path.rename calls outside the platform layer.

Ruff's banned-api rule (TID251 in pyproject.toml) sees module calls such as
os.replace but not method calls, so this check extends it to the Path methods
that move a file without the wait Windows needs while a reader holds it. It
reads the files ruff lints, spares those whose per-file ignores list TID251,
and accepts a call marked `# noqa: TID251 - <reason>`.

A Path is not known without type information, so a call counts when it is a
.replace or .rename with one positional argument or only target=, shapes no
str, bytes or datetime call has; an unbound Path.replace(a, b) counts too.

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
# Module functions of the same shape that copy an object instead of moving a file.
COPIES = {"copy", "dataclasses"}
MARK = re.compile(r"#\s*noqa:[^#]*\bTID251\b\s*-\s*\S")


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
    if not isinstance(function, ast.Attribute) or function.attr not in METHODS:
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


def problems(path, relative):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    with warnings.catch_warnings():
        # Old escapes in the engine's strings are ruff's to report.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = moved_by(node)
        if method is None:
            continue
        end = node.end_lineno or node.lineno
        if any(MARK.search(line) for line in lines[node.lineno - 1 : end]):
            continue
        yield (
            f"{relative}:{node.lineno}:{node.col_offset + 1}: "
            f"Path.{method} does not wait for readers on Windows; "
            f"use {METHODS[method]} (engine: util.system)."
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
            f"{len(found)} Path.replace or Path.rename call(s) outside the platform"
            " layer. A call that must stay raw is marked"
            " `# noqa: TID251 - <reason>`."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
