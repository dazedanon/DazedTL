"""Plugin text review and application."""

from typing import Literal, NotRequired, TypedDict


class PluginFinding(TypedDict):
    disposition: str
    safe: bool
    evidence: str
    reason: str


class PluginManualChoice(TypedDict):
    selected: bool
    reason: str


class PluginOccurrence(TypedDict):
    id: str
    file: str
    value: str
    line: int
    logical: list[str | int]
    kind: str
    protected: bool
    latent: bool
    enabled: bool
    plugin: str
    finding: NotRequired[PluginFinding]
    selected: bool
    manual: NotRequired[PluginManualChoice]
    before: str
    after: str
    target: str


class PluginRow(TypedDict):
    path: str
    plugin: str
    enabled: bool | None
    kind: str
    sourceHash: str
    issue: str
    selected: int
    visible: int
    latent: int
    occurrences: int
    recommended: int
    manual: int
    uncertain: int
    status: str
    changed: int
    reason: str
    candidateHash: str
    working: str
    ready: bool


class PluginView(TypedDict):
    mode: Literal["scope", "working"]
    query: str
    filter: str
    selectedOnly: bool
    currentFile: str
    offset: int


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


class PluginCounts(TypedDict):
    files: int
    selectedFiles: int
    selectedNotPrepared: int
    selected: int
    recommended: int
    ready: int
    blocked: int
    applied: int
    latent: int


class PluginReport(TypedDict):
    status: str
    errors: list[str]
    accepted: NotRequired[int]
    reported: NotRequired[int]
    expected: NotRequired[int]


class PluginState(TypedDict):
    projectId: str
    revision: str
    observationRevision: str
    supported: bool
    limitation: str
    layout: str
    source: str
    view: PluginView
    counts: PluginCounts
    findings: PluginReport
    editing: PluginReport
    originalIssue: str
    originalBackup: str
    receipts: list[PluginReceipt]
    requestPaths: dict[str, str]
    activeRequest: str


class PluginList(TypedDict):
    items: list[PluginRow]
    total: int
    selectedMatched: int
    offset: int
    limit: int


class PluginDetail(PluginRow):
    items: list[PluginOccurrence]
    total: int
    checks: dict[str, bool]
    resultEvidence: str
    rendered: str
    original: str
    originalHash: str


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
