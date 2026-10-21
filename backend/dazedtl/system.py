"""How DazedTL and its engine touch files and start processes.

Each rule here came from a bug only Windows users saw, so code goes through
these functions instead of the os, shutil, tempfile and subprocess calls they
replace; the build rejects those calls anywhere else (pyproject.toml lists
them). The engine imports this module as util.system.

Files
- Another process reading a file, such as the app's poll or a virus scanner,
  makes Windows refuse to replace or delete it ("Access is denied", WinError 5
  or 32), so replace, unlink, remove_tree and the writers wait up to about two
  seconds for it to let go.
- Saved files are written whole through a file beside them, as UTF-8 with
  "\\n" line ends, so a crash never leaves half a file and Windows never adds
  "\\r".
- tempfile.mkdtemp's mode 0o700 becomes an owner-only ACL on Windows with
  Python 3.13+, which locks the app out of files an elevated assistant writes
  there; new_folder and staging_folder keep the parent's permissions. An old
  folder is repaired with `icacls <folder> /reset /T`.
- A path handed to translation.files.project_path is project_relative's
  forward-slash string, never str(Path), whose backslashes it rejects.

Processes
- Children never inherit standard input: on Windows a child's startup blocks
  while another process waits to read that pipe, which froze workers and Git.
  The backend and its workers also call private_stdin on themselves.
- Python children run in UTF-8 mode (-X utf8): -I ignores PYTHONUTF8, and
  without it Windows decodes pipes and JSON as cp1252, turning Japanese folder
  names into mojibake. Text pipes are read as UTF-8.
- Console children open no window on Windows.
- Stopping a worker stops everything it started (stop_tree), or a Git command
  it waits on outlives it.
- A worker started from a filtered environment still gets the system
  variables (system_environment): without USERPROFILE and APPDATA the Anthropic
  SDK cannot find a home folder on Windows.
"""

import os
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path, PurePath

__all__ = [
    "SYSTEM_VARIABLES",
    "Process",
    "Reader",
    "held_open",
    "new_folder",
    "popen",
    "private_stdin",
    "project_relative",
    "remove_tree",
    "replace",
    "run",
    "staging_folder",
    "stop_tree",
    "system_environment",
    "unlink",
    "write_bytes",
    "write_json",
    "write_text",
]

# Files


# Windows errors that clear once another process closes the file.
_HELD_ERRORS = {
    5,  # ERROR_ACCESS_DENIED
    32,  # ERROR_SHARING_VIOLATION
    33,  # ERROR_LOCK_VIOLATION
}
_held = {}


class _HeldOpen(PermissionError):
    """The failure held_open simulates."""


class Reader:
    """A simulated reader of one file; attempts counts the failures left."""

    def __init__(self, attempts):
        self.attempts = attempts


@contextmanager
def held_open(path, attempts=2):
    """Test seam: the next ``attempts`` replaces or deletes of ``path``, or
    removals of a folder holding it, fail as Windows fails them while another
    process has the file open. Retries after a simulated failure do not wait.
    Yields the Reader, whose attempts reach 0 once the writer met them all.
    """
    key = _key(path)
    reader = _held[key] = Reader(attempts)
    try:
        yield reader
    finally:
        _held.pop(key, None)


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _simulate_reader(path, tree=False):
    if not _held:
        return
    key = _key(path)
    for held, reader in _held.items():
        inside = held == key or (tree and held.startswith(key.rstrip(os.sep) + os.sep))
        if inside and reader.attempts:
            reader.attempts -= 1
            raise _HeldOpen(13, "Simulated reader holds the file", held)


def _retryable(error):
    if isinstance(error, _HeldOpen):
        return True
    return os.name == "nt" and (
        isinstance(error, PermissionError)
        or getattr(error, "winerror", None) in _HELD_ERRORS
    )


def _retried(operation, path, tree=False):
    delay = 0.05
    for attempt in range(8):
        try:
            _simulate_reader(path, tree)
            return operation()
        except OSError as error:
            if not _retryable(error) or attempt == 7:
                raise
            if not isinstance(error, _HeldOpen):
                time.sleep(delay)
            delay = min(delay * 2, 0.5)
    return None


def replace(source, target):
    """os.replace, waiting for a reader of target to let go."""
    _retried(lambda: os.replace(source, target), target)


def unlink(path, missing_ok=False):
    """Path.unlink, waiting for a reader to let go."""
    _retried(lambda: Path(path).unlink(missing_ok=missing_ok), path)


def remove_tree(path, missing_ok=False, ignore_errors=False):
    """shutil.rmtree that also removes read-only files and waits for readers
    of the files inside to let go. Never follows a link out of the folder.
    ignore_errors leaves what still cannot go, for a cleanup that must not
    hide the error it cleans up after."""
    if not os.path.lexists(path):
        if missing_ok or ignore_errors:
            return
        raise FileNotFoundError(2, "No such folder", os.fspath(path))
    try:
        _retried(lambda: shutil.rmtree(path, onexc=_writable), path, tree=True)
    except OSError:
        if not ignore_errors:
            raise


def _writable(function, path, error):
    if isinstance(error, FileNotFoundError):
        return  # Already gone.
    if not isinstance(error, PermissionError) or function is os.path.islink:
        raise error
    # Windows refuses to delete read-only files, such as restored ones; a file
    # another process holds fails again, and remove_tree retries.
    os.chmod(path, stat.S_IWRITE)
    function(path)


def write_bytes(path, content, mode=0o600):
    """Replaces path's content whole: the bytes go into a file beside it,
    which then takes its place with the file's permissions. A new file gets
    mode, owner-only unless given, since workspace files such as the approval
    key and settings must stay private."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        except FileNotFoundError:
            pass
        replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Keep the write's own error when a scanner holds the leftover.
            pass


def write_text(path, text):
    """write_bytes of text as UTF-8, keeping its "\\n" line ends."""
    write_bytes(path, text.encode("utf-8"))


def write_json(path, value):
    """write_text of value as indented JSON that keeps Japanese readable."""
    import json

    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def new_folder(parent, prefix):
    """Creates a uniquely named folder in parent that keeps its permissions,
    in place of tempfile.mkdtemp."""
    parent = Path(parent)
    for _attempt in range(100):
        folder = parent / (prefix + secrets.token_hex(8))
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise FileExistsError(f"No unused folder name in {parent}")


@contextmanager
def staging_folder(parent, prefix):
    """A new_folder that is removed on exit unless it was renamed away, in
    place of tempfile.TemporaryDirectory."""
    folder = new_folder(parent, prefix)
    try:
        yield folder
    finally:
        if folder.is_dir() and not folder.is_symlink():
            remove_tree(folder, missing_ok=True)


def project_relative(path, root):
    """path inside root as the forward-slash string project paths use."""
    return PurePath(path).relative_to(root).as_posix()


# Processes

# The type popen returns, for annotations.
Process = subprocess.Popen


def run(arguments, *, check=False, console=False, **options):
    """subprocess.run with the rules above; see popen."""
    return subprocess.run(
        _utf8_python(arguments), check=check, **_options(options, console)
    )


def popen(arguments, *, console=False, group=False, **options):
    """subprocess.Popen with the rules above.

    Standard input is the null device unless given; text pipes read UTF-8,
    replacing bytes that are not, unless an encoding is given; a command that
    starts sys.executable gets -X utf8; on Windows a console child opens
    no window unless console is set. group starts the child as the head of its
    own process group, so stop_tree can stop what it starts too.
    """
    options = _options(options, console)
    if group and os.name != "nt":
        options["start_new_session"] = True
    return subprocess.Popen(_utf8_python(arguments), **options)


def _options(options, console):
    options = dict(options)
    if "stdin" not in options and "input" not in options:
        options["stdin"] = subprocess.DEVNULL
    if (options.get("text") or options.get("universal_newlines")) and not options.get(
        "encoding"
    ):
        options["encoding"] = "utf-8"
        options.setdefault("errors", "replace")
    if os.name == "nt" and not console:
        options["creationflags"] = options.get("creationflags", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    return options


def _utf8_python(arguments):
    """Adds -X utf8 to a command that starts this Python without it."""
    if isinstance(arguments, (str, bytes)) or not arguments:
        return arguments
    arguments = list(arguments)
    if os.fspath(arguments[0]) != sys.executable:
        return arguments
    flags = arguments[1:]
    if any(flag == "utf8" and previous == "-X" for previous, flag in pairwise(flags)):
        return arguments
    return [arguments[0], "-X", "utf8", *flags]


def stop_tree(process, force=False):
    """Stops process and everything it started. On Linux and macOS the
    process must have been started with popen(group=True)."""
    if os.name == "nt":
        # taskkill finds the tree through a running process.
        if process.poll() is not None:
            return
        run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    # The group outlives its first process, which may have exited already.
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError, PermissionError:
        pass


# What workers start from in place of the whole environment, which may hold
# provider keys. Claude's SDK looks for its settings under APPDATA or the home
# folder whenever a client is created, and Windows has no home folder without
# USERPROFILE.
SYSTEM_VARIABLES = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
)


def system_environment(*names):
    """This process's system variables and names, for a worker to start from."""
    # Windows lists every variable name in capitals.
    wanted = {
        name.upper() if os.name == "nt" else name
        for name in (*SYSTEM_VARIABLES, *names)
    }
    return {key: value for key, value in os.environ.items() if key in wanted}


def private_stdin():
    """Moves standard input to a descriptor that children cannot inherit.

    A child receives the standard input handle unless told otherwise, and on
    Windows its startup blocks while another process waits to read that pipe,
    which froze every per-file translation worker until the next command
    arrived. Standard input becomes the null device; the returned stream keeps
    reading the original pipe.
    """
    channel = os.fdopen(os.dup(0), "r", encoding="utf-8")
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    return channel
