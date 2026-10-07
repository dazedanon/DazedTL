"""Application navigation and the combined workspace snapshot."""

from typing import Literal, NotRequired, TypedDict

from dazedtl.api.contracts.guided import GuidedState
from dazedtl.api.contracts.images import ImageForeignWork, ImageManagerState
from dazedtl.api.contracts.plugins import PluginForeignWork, PluginState
from dazedtl.api.contracts.translation import TranslationState

type Screen = Literal["project", "translation", "guided", "manual", "settings"]
type TranslationMethod = Literal["guided", "len"]


class ProjectOperation(TypedDict):
    label: str
    status: str
    message: str


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
    next_label: NotRequired[str]


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


class AssistantTaskRecord(TypedDict):
    """A task copied to a coding assistant; each feature keeps its results."""

    kind: AssistantTaskKind
    requestId: str
    copiedAt: str
    # When a result the task expects was last saved, from file times.
    resultAt: str | None
    dismissed: bool


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
