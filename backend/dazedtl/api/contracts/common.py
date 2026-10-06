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
