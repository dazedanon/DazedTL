"""Small shapes shared by several API areas."""

from typing import Literal, NotRequired, TypedDict


class DocumentDraft(TypedDict):
    """A guidance document's unsaved text, and the revision of its file when
    the draft began."""

    text: str
    revision: str


type DocumentDrafts = dict[str, DocumentDraft]


class Document(TypedDict):
    """A guidance document as its file holds it, with what its definition
    (util/guidance_documents) says the renderer needs: its title, its kind,
    whether translation requests carry it and the work its draft holds up.
    `state` is "saved", "missing", whose text is empty, or "unreadable",
    whose `reason` says why and how to fix it."""

    text: str
    revision: str
    path: str
    # Its path in the game folder, as the editors show it.
    file: str
    title: str
    kind: Literal["core", "optional", "custom"]
    requests: bool
    holdsUp: list[Literal["handoff", "work"]]
    state: Literal["saved", "missing", "unreadable"]
    reason: NotRequired[str]
    # Whether the file changed on disk since the document's draft began.
    changed: bool


type Documents = dict[str, Document]


class DocumentsSaved(TypedDict):
    """The documents after a save, and the names it wrote."""

    documents: Documents
    saved: list[str]


type Phase = Literal["database", "dialogue", "variables", "advanced", "speakers"]


type RunMode = Literal["estimate", "translate", "batch"]


class CustomPattern(TypedDict):
    """A game's own pattern for event text nothing installed captures; its
    regex's last capturing group is translated."""

    name: str
    regex: str
    # Exact text in the first line of the scripts a 355/655 pattern reads.
    script: NotRequired[str]
    # How a 356 or 108 pattern's translation joins its words.
    spacing: NotRequired[Literal["space", "nbsp", "underscore"]]


class CustomHandler(TypedDict):
    """A game's own handler for an MZ plugin command's plain-text arguments."""

    plugin: str
    command: str
    args: list[str]


type EngineValue = (
    str | float | bool | list[str] | list[CustomPattern] | list[CustomHandler]
)


class Evidence(TypedDict):
    file: str
    sha256: str
    location: str


class Saved(TypedDict):
    saved: bool


class ExportedFiles(TypedDict):
    path: str
    files: int


class ForeignWork(TypedDict):
    """Work the game folder holds for another project or app version, and the
    choice offered for it."""

    # What the user was shown; adopting or starting over repeats it.
    binding: str
    saved: str
    # Where starting over moves it, inside the game folder.
    archive: str
    # Why the work cannot be used here, or empty.
    blocked: str
    applied: int
    # Applications that stay restorable once the work is used here.
    restorable: int
