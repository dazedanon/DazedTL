"""What a Maps & events run translates in an RPG Maker MV/MZ event file.

The engine (modules/rpgmakermvmz.py) translates, and Guided's line counts
(translation/file_lines.py) count, the same game text:

- the text blocks of every event command list (util/rpgmaker_blocks):
  messages, scrolling text, choices, and the comments a plugin shows while
  Comment text is on
- the actor name, nickname and profile an event changes (:func:`changes`),
  which players read as they read the database's own
- a map's display name
- the labels a map's events show from their notes (:func:`labels`), such as
  EventLabel's ``<LB:...>``

Each is translated while it holds Japanese (util/source_text).
"""

import re
from typing import Any, NamedTuple

# Note tags whose text a plugin shows over the event, in the order the
# engine translates them.
NOTE_TAGS = (
    re.compile(r"<namePop:\s?([\w一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ]+)", re.DOTALL),
    re.compile(r"<LB:(.*?)\s?>.*", re.DOTALL),
    re.compile(r"<dn:\s*(.*?)>.*", re.DOTALL),
)
# EventLabel shows the event's own name over an event whose note holds <LB>.
NAME_TAG = "<LB>"
# Change Name, Change Nickname and Change Profile: each sets an actor's text
# from its second parameter.
CHANGES = {320: "name change", 324: "nickname change", 325: "profile change"}
# A name change holding these sets a name some games read as a file name.
FILE_NAME = re.compile(r"[■_]")


class Change(NamedTuple):
    """An actor text an event command sets: its kind and its position in the
    command list."""

    kind: str
    index: int


def changes(commands: Any) -> list[Change]:
    """The actor names, nicknames and profiles a command list sets, in order;
    a name holding what :data:`FILE_NAME` matches stays as it is."""
    found = []
    for index, command in enumerate(commands if isinstance(commands, list) else ()):
        code = command.get("code") if isinstance(command, dict) else None
        parameters = command.get("parameters") if code in CHANGES else None
        if not isinstance(parameters, list) or len(parameters) < 2:
            continue
        text = parameters[1]
        if not isinstance(text, str):
            continue
        source = command.get("_original")
        if code == 320 and FILE_NAME.search(
            source if isinstance(source, str) else text
        ):
            continue
        found.append(Change(CHANGES[code], index))
    return found


class Label(NamedTuple):
    """A label an event shows: the field holding it ("name" or "note") and
    its text as the field holds it."""

    field: str
    text: str


def note(event: Any) -> str:
    """An event's note as text."""
    value = event.get("note") if isinstance(event, dict) else None
    return value if isinstance(value, str) else "" if value is None else str(value)


def labels(event: Any) -> list[Label]:
    """The labels a map event shows: its name under <LB>, then the first
    text of each note tag."""
    found = []
    text = note(event)
    name = event.get("name") if isinstance(event, dict) else None
    if NAME_TAG in text and isinstance(name, str) and name:
        found.append(Label("name", name))
    for tag in NOTE_TAGS:
        match = tag.search(text)
        if match:
            found.append(Label("note", match[1]))
    return found
