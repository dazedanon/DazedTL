"""Plugin files: the assistant's task and reviewed application."""

from typing import Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import ForeignWork


class PluginFileReview(TypedDict):
    path: str
    destination: str
    beforeHash: str
    afterHash: str
    originalHash: str
    candidateHash: str
    backup: str
    changes: int
    kind: str


class PluginBlocked(TypedDict):
    path: str
    reason: str


class PluginPreview(TypedDict):
    token: str
    mode: Literal["apply", "restore"]
    files: list[PluginFileReview]
    blocked: list[PluginBlocked]
    manifest: str


class PluginReceipt(TypedDict):
    id: str
    mode: str
    saved: str
    status: str
    files: list[PluginFileReview]
    failure: str
    conflicts: list[str]
    manifest: str
    restorable: bool
    # Why an application taken over from another project cannot be restored.
    restoreIssue: NotRequired[str]


class PluginCounts(TypedDict):
    # Readable files with text for the assistant to check, and those it has
    # settled.
    files: int
    investigated: int
    # Files with text players see, and those whose translation is checked.
    textFiles: int
    translated: int
    # Text locations chosen for translation.
    selected: int
    ready: int
    applied: int


class PluginUnreadable(TypedDict):
    path: str
    issue: str
    # The user chose to leave it unchanged while it fails this way.
    kept: bool


class PluginState(TypedDict):
    projectId: str
    supported: bool
    limitation: str
    # Whether the game's plugins were read; counts start then.
    scanned: bool
    counts: PluginCounts
    unreadable: list[PluginUnreadable]
    originalIssue: str
    receipts: list[PluginReceipt]
    # The copied task's current request, for the assistant's helper.
    activeRequest: str
    # Whether that request still waits for the assistant's report.
    awaiting: bool


class PluginForeignWork(ForeignWork):
    investigated: int
    translated: int


class PluginActionResult(TypedDict):
    state: NotRequired[PluginState]
    text: NotRequired[str]
    preview: NotRequired[PluginPreview]
    receipt: NotRequired[PluginReceipt]
    completed: NotRequired[int]
    message: NotRequired[str]
    request: NotRequired[str]
    requestId: NotRequired[str]
    stage: NotRequired[str]
