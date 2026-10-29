"""The commands a coding assistant runs to reach this app through its helper."""

import os
import shutil
from pathlib import Path

from dazedtl import system

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


def helper_command(workspace, project_id, *operation):
    """The project helper invocation for one project, ready for appended options."""
    return system.shell_command(
        system.python_command(
            HELPER,
            "--workspace",
            workspace,
            "--project",
            project_id,
            *operation,
        )
    )


def windows_note():
    """How an assistant on Windows runs the Python and Git its task needs.

    A fresh Windows has only the Microsoft Store placeholder for Python and no
    Git but DazedTL's bundled copy, and Python prints to pipes and reads files
    in the ANSI code page, which cannot hold Japanese, so an assistant's own
    script over game text fails with UnicodeEncodeError unless UTF-8 mode is
    on. The example takes system.shell_command's form, which has PowerShell
    decode UTF-8 too. Every copied task starts with this note.
    """
    if os.name != "nt":
        return ""
    python = system.shell_command(system.python_command("script.py"))
    note = (
        "On Windows, run Python you write with DazedTL's own Python in UTF-8 mode, in PowerShell"
        f" `{python}`,"
        " and install nothing into it:"
        " `python` on PATH may be missing or the Microsoft Store placeholder, and without"
        " -X utf8 printing or reading Japanese text fails with UnicodeEncodeError."
    )
    git = shutil.which("git")
    if git and any(part.startswith("mingit-") for part in Path(git).parts):
        note += (
            " Git here is DazedTL's bundled copy and may not be on your PATH;"
            f" in PowerShell run it as `& {system.shell_argument(git)}`."
        )
    return note + "\n\n"
