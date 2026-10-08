"""The commands a coding assistant runs to reach this app through its helper."""

import os
import shlex
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parents[3] / "scripts/project.py"


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
