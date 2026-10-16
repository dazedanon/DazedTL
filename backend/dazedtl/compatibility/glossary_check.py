"""The glossary check through the engine: its scan in a tool worker, and the
fixes the user chose, fitted and written on disposable copies before the
Guided publication writes them into the game."""

import shutil
import tempfile
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, project_path, read_json
from dazedtl.translation.refusals import line_refusal

# The last scan's lines, in the game's workflow folder.
ARTIFACT = "glossary-check.json"


def run_check(plan, log):
    """Scans the game's text against its glossary and saves every flagged
    line; the operation's result holds only the counts."""
    from desktop.backend.workflow_actions import validate_plan
    from util.rpgmaker_glossary_check import scan
    from util.rpgmaker_qa import task_layout

    validate_plan(plan)
    root = Path(plan["project"]["source"])
    glossary = project_path(root, ".dazedtl/glossary.txt", exists=False)
    log("Checking the game's text against its glossary.")
    result = scan(
        plan["project"]["data"],
        glossary.read_text(encoding="utf-8") if glossary.is_file() else "",
        task_layout(root, plan["options"]["fit"]),
        # A refusal note saved as a translation is Translate's to send again.
        skip=line_refusal,
    )
    path = Path(plan["folder"]) / ARTIFACT
    write_json(path, result)
    return {
        "lines": result["lines"],
        "flagged": result["flagged"],
        "proposals": sum(1 for line in result["found"] if line["proposal"]),
        "artifact_sha256": digest(path.read_bytes()),
    }


def saved_scan(folder, expected=None):
    """The last scan's lines by key, from the file its operation saved; a
    scan the file no longer matches is refused."""
    path = Path(folder) / ARTIFACT
    raw = path.read_bytes()
    if expected is not None and digest(raw) != expected:
        raise ValueError("The glossary check changed. Check again before applying.")
    return read_json(path)


# What each mechanical flag a fix may introduce does to the line, in the
# words the user reads beside it.
FLAG_WORDS: dict[str, str] = {
    "empty-live": "leaves the line empty",
    "unchanged-source": "is the Japanese unchanged",
    "source-language-residue": "keeps Japanese text",
    "runtime-token-mismatch": "adds or drops a control code, such as \\C[2] or %1",
    "missing-center-alignment": "loses the line's centering code",
    "unsafe-bare-center-code": "puts a letter straight after a centering code",
    "visible-number-mismatch": "changes a number the Japanese shows",
}
# Text QA's own wording for the other problems, where it reads oddly after
# "This fix".
PROBLEM_WORDS: dict[str, str] = {
    "the correction matches the current text": "matches the current text",
    "a name or choice cannot contain a line break": "puts a line break in a name or choice",
}


def _plain(problem: str) -> str:
    if problem.startswith("introduces "):
        return "; ".join(
            FLAG_WORDS.get(flag, flag) for flag in problem[11:].split(", ")
        )
    return PROBLEM_WORDS.get(problem, problem)


def fitted(layout, record, text):
    """A fix as the game gets it, rewrapped to its box, and why it would
    fail to apply or break the line, in words that follow "This fix"."""
    from util.rpgmaker_glossary_check import fix_problems

    written, problems = fix_problems(record, text, layout)
    return written, [_plain(problem) for problem in problems]


def candidates(plan, root, prefix, folder):
    """The game files the chosen fixes change, written on copies of the
    game's files in the workflow folder."""
    from util.rpgmaker_glossary_check import apply_fixes

    options = plan["options"]
    scan = saved_scan(folder, options["scan"])
    lines = {line["key"]: line for line in scan["found"]}
    fixes = []
    for key, text in options["fixes"].items():
        line = lines.get(key)
        if line is None:
            raise ValueError("A fix no longer matches the glossary check; check again.")
        written, problems = fitted(scan["layout"], line["record"], text)
        if problems or written != text:
            raise ValueError(
                f"A fix in {line['file']} no longer fits its line; choose it again."
            )
        fixes.append({"record": line["record"], "text": text})
    if not fixes:
        raise ValueError("Choose the glossary fixes to apply.")
    with tempfile.TemporaryDirectory(dir=folder, prefix="glossary-") as temporary:
        staging = Path(temporary)
        for name in {fix["record"]["file"] for fix in fixes}:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project_path(root, (prefix / name).as_posix()), target)
        return {
            (prefix / name).as_posix(): (staging / name).read_bytes()
            for name in apply_fixes(staging, fixes)
        }
