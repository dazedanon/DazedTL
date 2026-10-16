"""Plugin files: the assistant's task, its application and reviewed restores."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import ForeignWork
from dazedtl.api.contracts.guided import PlaytestOperation


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
    # Files ready to apply whose translation is in the game, where only
    # shortened labels wait.
    shortened: int
    applied: int
    # Labels from Text QA still waiting for the assistant to shorten.
    labels: int


class PluginUnreadable(TypedDict):
    path: str
    issue: str
    # The user chose to leave it unchanged while it fails this way.
    kept: bool


class PluginLabel(TypedDict):
    """A label Text QA's latest capture found too long for the screen that QA
    holds no line of, and where it stands here: waiting for the assistant,
    shortened and ready to apply or applied, kept as it is, or found in no
    plugin file."""

    text: str
    # The captured screen that shows it.
    title: str
    state: Literal["waiting", "ready", "applied", "kept", "elsewhere"]
    # Why the assistant kept it as it is.
    reason: NotRequired[str]


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
    labels: list[PluginLabel]


class PluginLabelFit(TypedDict):
    """How a label of the shortening request shows on its screen captured
    with the working copies served in place of the game's files."""

    text: str
    title: Annotated[str, "The screen QA's capture found it on."]
    shows: Annotated[list[str], "The text that screen should draw now."]
    fits: Annotated[bool, "Whether the game draws that text in full."]
    note: Annotated[str, "What the game draws there."]
    capture: NotRequired[Annotated[str, "The screen's capture file."]]
    squeezed: NotRequired[
        Annotated[float, "The share of the width it needs the game drew it in."]
    ]
    clipped: NotRequired[Annotated[bool, "Its end is cut off at its window's edge."]]


class PluginCapture(TypedDict):
    """The latest capture of the shortening request's labels on their
    screens, for the assistant's project helper."""

    requestId: str
    operation: NotRequired[PlaytestOperation]
    finishedAt: NotRequired[str]
    current: NotRequired[
        Annotated[bool, "It served the request's working copies as they are now."]
    ]
    labels: NotRequired[list[PluginLabelFit]]
    unavailable: NotRequired[Annotated[str, "Why DazedTL couldn't run the game."]]
    next: Annotated[str, "The step to take next."]


class PluginForeignWork(ForeignWork):
    investigated: int
    translated: int


class PluginActionResult(TypedDict):
    state: NotRequired[PluginState]
    text: NotRequired[str]
    preview: NotRequired[PluginPreview]
    receipt: NotRequired[PluginReceipt]
    completed: NotRequired[int]
    # Checked files an apply left unchanged, with why.
    blocked: NotRequired[list[PluginBlocked]]
    message: NotRequired[str]
    request: NotRequired[str]
    requestId: NotRequired[str]
    stage: NotRequired[str]
