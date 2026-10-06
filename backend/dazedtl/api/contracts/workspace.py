"""Application navigation and the combined workspace snapshot."""

from typing import Literal, NotRequired, TypedDict

from dazedtl.api.contracts.guided import GuidedState
from dazedtl.api.contracts.images import ImageManagerState
from dazedtl.api.contracts.plugins import PluginState
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


class WorkspaceSnapshot(TypedDict):
    application: AppState
    guided: GuidedState | None
    translation: TranslationState | None
    translationError: str
    images: NotRequired[ImageManagerState | None]
    imagesError: NotRequired[str]
    plugins: NotRequired[PluginState | None]
    pluginsError: NotRequired[str]
