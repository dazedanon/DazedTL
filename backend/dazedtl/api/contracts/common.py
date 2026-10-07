"""Small shapes shared by several API areas."""

from typing import Literal, NotRequired, TypedDict


class Document(TypedDict):
    text: str
    revision: str
    path: NotRequired[str]


type Documents = dict[str, Document]


type Phase = Literal["database", "dialogue", "variables", "advanced", "speakers"]


type RunMode = Literal["estimate", "translate", "batch"]


type EngineValue = str | float | bool | list[str]


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
