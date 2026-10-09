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


def git_note():
    """Names DazedTL's bundled Git, which a fresh Windows has on no other PATH.

    The engine's version_update.handoff adds the same note to its prompt.
    """
    git = shutil.which("git")
    if os.name != "nt" or not git:
        return ""
    if not any(part.startswith("mingit-") for part in Path(git).parts):
        return ""
    path = str(Path(git)).replace("'", "''")
    return (
        "Git here is DazedTL's bundled copy and may not be on your PATH;"
        f" in PowerShell run it as `& '{path}'`.\n"
    )
