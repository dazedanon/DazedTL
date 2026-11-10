"""Tool feedback: the short note on what DazedTL itself could do better that
a method's assistant writes as a translation's last step, which the user
copies or saves to post in DazedTL's Discord.

This module owns it whole. `closing` ends each method's last assistant task
with the helper's `feedback` command, which prints `show`: the one
instruction, engine/data/skills/tool_feedback.md, rendered with the limit
and commands, and any feedback saved before. `save` checks what a program
can tell is private or malformed and saves the rest as PATH, which `read`
gives the app. PATH sits in `.dazedtl/`, which the game's Git ignores but
for a few shared files (util/paths GAME_TOOL_GITIGNORE_BLOCK), and which no
patch or release ZIP carries, so the feedback stays on this computer until
the user shares it.
"""

import getpass
import os
import re
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from util.skills.setup import load_clipboard_skill

from dazedtl import system
from dazedtl.storage import write_bytes

from .files import project_path

PATH = ".dazedtl/tool-feedback.md"
DRAFT = ".dazedtl/tool-feedback-draft.md"
# One Discord message holds 2,000 characters; DazedTL's facts take the rest.
LIMIT = 1600
PARTS = (
    "**How it went:**",
    "**Problems:**",
    "**Missing engine support:**",
    "**Ideas:**",
)
# Japanese, Chinese and Korean letters: more than a few words of them is
# game text, whichever side of the translation it is on.
CJK = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff66-\uff9f]")
CJK_ALLOWED = 30
# A run of letters and digits, its dot-joined parts together, such as a JWT's.
RUN = re.compile(r"(?<![\w.-])[\w-]+(?:\.[\w-]+)*", re.ASCII)
# A file's extension, which a file's name, such as a plugin's, ends with.
EXTENSION = re.compile(r"\.[A-Za-z]{1,5}$")
# The openings of common providers' keys and tokens.
KEY_PREFIX = re.compile(r"(sk|pk|rk)[-_]|AIza|gh[pousr]_|github_pat_|xox[abpr]-|eyJ")
# Saved secrets shorter than this, which ordinary words could match, are not
# looked for.
SECRET_FLOOR = 6
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")


def closing(command):
    """What ends a method's last assistant task, given the helper's
    `feedback` command."""
    return (
        "\n## Tool feedback\n\n"
        "This is the last assistant task of this translation. When everything"
        f" above is finished, run `{command}` and follow what it prints.\n"
    )


def show(root, command):
    """The instruction for the helper's `feedback` command, given that
    command, and the feedback saved before, if any."""
    text = load_clipboard_skill("tool_feedback.md")
    for name, value in (
        ("LIMIT", f"{LIMIT:,}"),
        ("DRAFT", DRAFT),
        ("SAVE", f"{command} --input {DRAFT}"),
        ("SHOW", command),
    ):
        text = text.replace("{{" + name + "}}", value)
    saved = read(root)
    return {"instructions": text, "saved": saved["text"] if saved else None}


def save(root, relative, secrets=()):
    """Saves the feedback the assistant wrote at *relative* in the game
    folder at *root* as PATH, once it passes `problems` with the *secrets*
    DazedTL holds, and removes the draft; refused feedback changes nothing."""
    source = project_path(root, relative)
    saved = project_path(root, PATH, exists=False)
    if saved.exists() and source.samefile(saved):
        raise ValueError(f"Write the feedback to {DRAFT}, not to {PATH} itself.")
    try:
        text = source.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    except UnicodeDecodeError:
        raise ValueError("Write the tool feedback in UTF-8.") from None
    found = problems(text, secrets)
    if found:
        raise ValueError("Tool feedback not saved: " + " ".join(found))
    write_bytes(saved, (text + "\n").encode())
    # The feedback is saved, so a draft that can't go yet stays.
    system.unlink(source, ignore_errors=True)
    return {"path": PATH, "characters": len(text)}


def read(root):
    """The saved feedback, as the app shows it: its text and when it was
    saved, or None when there is none or it can't be read."""
    try:
        path = project_path(root, PATH, exists=False)
        if not path.is_file() or path.stat().st_size > 64_000:
            return None
        text = path.read_text(encoding="utf-8").strip()
        saved = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except ValueError, OSError:
        return None
    return {"text": text, "savedAt": saved} if text else None


def problems(text, secrets=()):
    """What keeps *text* from being saved as tool feedback, each with its
    fix: its structure and length, the *secrets* DazedTL holds, such as
    saved API keys, and what a program can tell is private. The instruction
    rules out the rest, such as game text in Latin letters."""
    found = []
    lines = [line.strip() for line in text.splitlines()]
    # A missing part reads as after the end.
    starts = [
        next((n for n, line in enumerate(lines) if line.startswith(part)), len(lines))
        for part in PARTS
    ]
    if len(lines) in starts or starts != sorted(starts) or starts[0] != 0:
        found.append(
            "Write its parts in this order, each at the start of a line, with"
            " nothing before the first: " + ", ".join(PARTS) + "."
        )
    if len(text) > LIMIT:
        found.append(
            f"Shorten it to at most {LIMIT:,} characters; it has {len(text):,}."
        )

    def line(index):
        return text.count("\n", 0, index) + 1

    held = [text.find(secret) for secret in secrets if len(secret) >= SECRET_FLOOR]
    if any(index >= 0 for index in held):
        found.append(
            "Leave out the saved API key or connection token on line"
            f" {line(min(index for index in held if index >= 0))}."
        )
    folded = text.casefold().replace("\\", "/")
    if any(home in folded for home in _homes()):
        found.append(
            "Leave out the home folder: write paths inside the game folder relative to it."
        )
    user = _user()
    named = user and re.search(
        rf"[/\\]{re.escape(user)}(?:[/\\]|$)", text, re.IGNORECASE | re.MULTILINE
    )
    if named:
        found.append(
            f"Leave out the path with the user name on line {line(named.start())}:"
            " write paths inside the game folder relative to it."
        )
    token = next(
        (run for run in RUN.finditer(text) if _random(EXTENSION.sub("", run.group()))),
        None,
    )
    if token:
        found.append(
            f"Leave out keys, tokens, IDs and hashes, such as the one on line"
            f" {line(token.start())}; they are secret or mean nothing outside this"
            " computer."
        )
    if EMAIL.search(text):
        found.append("Leave out e-mail addresses.")
    if len(CJK.findall(text)) > CJK_ALLOWED:
        found.append(
            "Quote at most a few words of game text; name the file, map, event"
            " or plugin instead."
        )
    return found


def _random(run):
    """Whether a run of at least 24 letters and digits reads as a key, token,
    ID or hash rather than a name: one opening as common keys do, hex digits
    or digits alone, letters with digits scattered through them, or letters
    whose case changes as often as random ones do. A name such as a plugin's,
    VisuMZ_1_ElementStatusCore, holds a short digit group or two and a few
    capitals."""
    if len(run) < 24:
        return False
    if KEY_PREFIX.match(run):
        return True
    digits = re.findall(r"\d+", run)
    if digits and re.fullmatch(r"[0-9A-Fa-f.-]+", run):
        return True
    if len(digits) >= 3 and re.search(r"[A-Za-z]", run):
        return True
    letters = re.sub(r"[^A-Za-z]", "", run)
    changes = sum(a.isupper() != b.isupper() for a, b in pairwise(letters))
    return len(letters) >= 24 and changes >= len(letters) * 0.4


def _homes():
    """The home folder as paths in the feedback could write it."""
    found = set()
    for value in (str(Path.home()), os.environ.get("USERPROFILE", "")):
        value = value.casefold().replace("\\", "/").rstrip("/")
        # A bare root or drive, as a home folder in a container can be, is
        # in every path.
        if value.count("/") >= 2:
            found.add(value)
    return found


def _user():
    """The user's account name, which paths outside the home folder can
    hold too, such as on another drive."""
    try:
        name = getpass.getuser()
    except OSError, KeyError, ImportError:
        return ""
    return name
