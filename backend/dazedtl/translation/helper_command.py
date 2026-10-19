"""The commands a coding assistant runs to reach this app through its helper."""

import os
import shlex
import shutil
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parents[3] / "scripts/project.py"
# Every prompt that hands the helper to an assistant says this.
LOOPBACK_NOTE = (
    "The helper connects to the running app over authenticated loopback HTTP (127.0.0.1). "
    "A coding assistant's network sandbox can block that connection even while DazedTL is open. "
    "If loopback access is restricted, use the assistant's normal permission/escalation flow for this helper "
    'before your first helper command (in Codex, sandbox_permissions="require_escalated" when required). '
    "Reuse valid permission already granted. "
    "A failed sandboxed connection does not mean the app is closed: retry a read-only helper command with permitted access "
    "before asking the user to reopen DazedTL."
)


def shell_command(arguments):
    """Quotes a command for the assistant's shell: PowerShell on Windows, sh elsewhere.

    Windows pipes use the ANSI code page, which cannot hold Japanese game text,
    so the PowerShell form decodes the helper's UTF-8 output. The engine's
    rpgmaker_qa.runtime_command follows the same form.
    """
    if os.name != "nt":
        return shlex.join(arguments)
    return "[Console]::OutputEncoding = [Text.Encoding]::UTF8; & " + " ".join(
        "'" + argument.replace("'", "''") + "'" for argument in arguments
    )


def helper_command(workspace, project_id, *operation):
    """The project helper invocation for one project, ready for appended options."""
    return shell_command(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            str(HELPER),
            "--workspace",
            str(workspace),
            "--project",
            project_id,
            *operation,
        ]
    )


def windows_note():
    """How an assistant on Windows runs the Python and Git its task needs.

    A fresh Windows has only the Microsoft Store placeholder for Python and no
    Git but DazedTL's bundled copy, and Python prints to pipes and reads files
    in the ANSI code page, which cannot hold Japanese, so an assistant's own
    script over game text fails with UnicodeEncodeError unless UTF-8 mode is
    on. PowerShell decodes captured output in the console code page, so the
    example sets UTF-8 as shell_command's form does. Every copied task starts
    with this note.
    """
    if os.name != "nt":
        return ""
    python = str(Path(sys.executable)).replace("'", "''")
    note = (
        "On Windows, run Python you write with DazedTL's own Python in UTF-8 mode, in PowerShell"
        f" `[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '{python}' -X utf8 script.py`,"
        " and install nothing into it:"
        " `python` on PATH may be missing or the Microsoft Store placeholder, and without"
        " -X utf8 printing or reading Japanese text fails with UnicodeEncodeError."
    )
    git = shutil.which("git")
    if git and any(part.startswith("mingit-") for part in Path(git).parts):
        path = str(Path(git)).replace("'", "''")
        note += (
            " Git here is DazedTL's bundled copy and may not be on your PATH;"
            f" in PowerShell run it as `& '{path}'`."
        )
    return note + "\n\n"
