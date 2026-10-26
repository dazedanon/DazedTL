"""Application navigation and the combined workspace snapshot."""

from typing import Literal, NotRequired, TypedDict

from dazedtl.api.contracts.guided import GuidedState
from dazedtl.api.contracts.images import ImageForeignWork, ImageManagerState
from dazedtl.api.contracts.plugins import PluginForeignWork, PluginState
from dazedtl.api.contracts.settings import SourceLanguage
from dazedtl.api.contracts.translation import TranslationState

type Screen = Literal["project", "translation", "guided", "manual", "settings"]
type TranslationMethod = Literal["guided", "len"]


class ProjectOperation(TypedDict):
    label: str
    status: str
    message: str


class OriginalRecord(TypedDict):
    """The background record of the open game's original files, while it
    runs or after it ended without one."""

    running: bool
    message: str
    error: str
    stopped: bool


class GameLanguages(TypedDict):
    """The languages a project's game translates between."""

    source: SourceLanguage
    target: str
    # The target is written in Chinese or Japanese characters, which stock
    # Line widths, measured on Latin letters, fit too wide.
    characters: bool
    # The BCP 47 tags of the source and target (util/languages), the `lang`
    # of text in them so the system draws that language's forms, such as
    # Japanese kanji over Chinese ones; None for a name DazedTL doesn't know.
    sourceTag: str | None
    targetTag: str | None


class Project(TypedDict):
    id: str
    name: str
    source: str
    engine: str
    engine_label: NotRequired[str]
    # None until the method is chosen; existing work implies it.
    method: TranslationMethod | None
    phase: str
    available: NotRequired[bool]
    status: NotRequired[str]
    detail: NotRequired[str]
    operation: NotRequired[ProjectOperation]
    originals: NotRequired[OriginalRecord]
    next_label: NotRequired[str]
    # The open project's, while its game can be read.
    languages: NotRequired[GameLanguages]


class AppState(TypedDict):
    project: Project | None
    recent: list[Project]
    screen: Screen
    running: bool
    provider_ready: bool
    observing: bool


type AssistantTaskKind = Literal[
    "names",
    "line_widths",
    "event_text",
    "plugins",
    "image_discovery",
    "image_editing",
    "qa",
    "walkthrough",
]


class AssistantTaskValidation(TypedDict):
    """The newest report from a validator the assistant runs on its results."""

    savedAt: str
    passed: bool
    # The errors it counted; zero when it does not say.
    errors: int


class AssistantTaskRecord(TypedDict):
    """A task copied to a coding assistant; each feature keeps its results."""

    kind: AssistantTaskKind
    requestId: str
    copiedAt: str
    # When a result the task expects was last saved, from file times.
    resultAt: str | None
    dismissed: bool
    # When the result the task saves last was saved, for a task that keeps
    # working after its first results; null until it is.
    finishedAt: NotRequired[str | None]
    # For a task whose assistant validates its results after saving them;
    # null while no readable report is saved.
    validation: NotRequired[AssistantTaskValidation | None]


class WorkspaceSnapshot(TypedDict):
    application: AppState
    assistantTasks: list[AssistantTaskRecord]
    guided: GuidedState | None
    translation: TranslationState | None
    translationError: str
    images: NotRequired[ImageManagerState | None]
    imagesError: NotRequired[str]
    # Image work saved by another project, waiting for the user's choice.
    imagesForeign: NotRequired[ImageForeignWork]
    plugins: NotRequired[PluginState | None]
    pluginsError: NotRequired[str]
    pluginsForeign: NotRequired[PluginForeignWork]
