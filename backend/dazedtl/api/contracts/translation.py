"""Len's method translation projects, runs and backups."""

from typing import Literal, NotRequired, TypedDict

import typing_extensions

from dazedtl.api.contracts.common import Documents
from dazedtl.api.contracts.runs import LegacyRun


class TranslationOptions(TypedDict):
    mode: Literal["agent", "live", "batch"]
    instructions: str
    include_images: bool
    include_glossary_base: bool
    install_forge: bool
    thorough_investigation: bool


class ProjectOptions(TypedDict):
    options: TranslationOptions
    revision: str
    initialized: bool


class QuoteRates(TypedDict):
    input: float
    output: float
    source: str
    batch_factor: float | None


class TranslationQuote(TypedDict):
    requests: int
    units: int
    input_tokens: int
    output_tokens: int
    cost: float
    live_cost: float
    batch_cost: float | None
    model: str
    provider: str
    basis: str
    rates: QuoteRates


class TranslationBatch(TypedDict):
    id: str
    state: str
    api_status: NotRequired[str]
    counts: NotRequired[dict[str, int]]


class TranslationIssue(TypedDict):
    id: str
    state: str
    message: str


class QaRequest(TypedDict):
    id: str
    index: int
    notes: int


class TranslationJob(TypedDict):
    id: str
    project_id: str
    kind: Literal["translation", "operation"]
    action: NotRequired[str | None]
    label: str
    status: str
    message: str
    created: str
    updated: str
    mode: NotRequired[Literal["agent", "live", "batch"] | None]
    quote: TranslationQuote | None
    approval_token: str
    approved: bool
    result: dict[str, object] | None
    usage: dict[str, float]
    counts: dict[str, int]
    units: int
    accepted_units: int
    requests: int
    stop_requested: bool
    cancel_requested: bool
    can_cancel_provider: NotRequired[bool]
    batches: list[TranslationBatch]
    issues: list[TranslationIssue]
    qa_requests: NotRequired[list[QaRequest]]


class ProgressMetric(TypedDict):
    total: int | None
    discovered: NotRequired[int]
    translated: int
    reviewed: int
    corpus_sha256: NotRequired[str]


class ProgressMetrics(TypedDict):
    text: ProgressMetric
    images: ProgressMetric


class ActiveTime(TypedDict):
    """Cumulative active seconds the helper reported."""

    translated: NotRequired[float]
    reviewed: NotRequired[float]


class ProgressSample(TypedDict):
    corpus: str
    timing: ActiveTime
    translated: int
    reviewed: int


class RemainingEstimate(TypedDict):
    low_minutes: float
    high_minutes: float
    basis: str


class ArtifactFingerprint(TypedDict):
    path: str
    sha256: str
    size: int
    mtime_ns: int


class TranslationProgress(TypedDict):
    schema: int
    updated_at: str | None
    scope_sha256: str
    phase: str | None
    phases: dict[str, str]
    metrics: ProgressMetrics
    warnings: NotRequired[list[str]]
    blocker: str
    next_action: str
    evidence: list[ArtifactFingerprint]
    timing: NotRequired[ActiveTime]
    history: NotRequired[list[ProgressSample]]
    estimates: NotRequired[dict[str, RemainingEstimate]]


class OptionsDraft(TypedDict):
    options: TranslationOptions
    revision: str


class TranslationDrafts(TypedDict):
    options: OptionsDraft | None
    documents: Documents


class GitStatus(TypedDict):
    configured: bool
    selected_root: str
    repo_root: str | None
    game_prefix: str
    original_exists: bool
    translation_exists: bool
    original_version: str | None
    translation_version: str | None
    original_commit: str | None
    translation_commit: str | None
    translation_branch: str | None
    current_branch: str | None
    worktree_clean: bool
    pending_cherry_pick: bool
    pending_operations: list[str]
    git_available: bool
    asset_sync_pending: bool
    asset_manifest_available: bool
    asset_baseline_repair_needed: bool
    applied_update_version: str | None
    preserve_game_files: bool
    available_original_refs: list[str]


class LifecycleCheckpoint(TypedDict):
    commit: str
    manifest: str


class GuidedReviewRecord(TypedDict):
    manifest: str
    evidence: dict[str, str]


class DeliveryRecord(TypedDict):
    path: str
    commit: str
    game_version: str
    updater_stamp: bool


class VersionUpdate(TypedDict):
    version: str
    complete: bool


class Lifecycle(typing_extensions.TypedDict, extra_items=object):
    """Saved lifecycle evidence; further keys are internal to the backend."""

    version: int
    # The original the project was set up from; later game backups never
    # replace it while it is available.
    source_backup: NotRequired[BackupRecord]
    # The latest game backup saved after the original.
    game_backup: NotRequired[BackupRecord]
    prepared_source: NotRequired[BackupRecord]
    workspace_backup: NotRequired[BackupRecord]
    checkpoint: NotRequired[LifecycleCheckpoint]
    guided_review: NotRequired[GuidedReviewRecord]
    delivery: NotRequired[DeliveryRecord]
    incoming_source: NotRequired[BackupRecord]
    incoming_version: NotRequired[str]
    version_update: NotRequired[VersionUpdate]
    discarded_release: NotRequired[str]


class ConnectionSummary(TypedDict):
    name: str
    model: str


class TranslationState(ProjectOptions):
    engine: str
    legacyRun: LegacyRun | None
    projectId: str
    drafts: TranslationDrafts
    documents: Documents
    progress: TranslationProgress | None
    # When the user's assistant last used the project helper, so Progress
    # shows its run started before the first report.
    assistantSeenAt: str | None
    git: GitStatus | None
    lifecycle: Lifecycle
    # The original backup the game folder already holds, offered to a project
    # without one, such as after the game was moved or copied.
    storedOriginal: NotRequired[BackupSnapshot]
    jobs: list[TranslationJob]
    active: bool
    warnings: list[str]
    statusText: str
    providerEnabled: bool
    connection: ConnectionSummary | None
    batchSupported: bool
    legacyAvailable: bool


class BackupRecord(TypedDict):
    id: str
    path: str
    files: int
    kind: NotRequired[Literal["source", "workspace"]]
    version: NotRequired[int]
    available: NotRequired[bool]
    issue: NotRequired[str]
    bytes_total: NotRequired[int]
    bytes_added: NotRequired[int]
    bytes_reused: NotRequired[int]
    reused_snapshot: NotRequired[bool]


class BackupSnapshot(TypedDict):
    id: str
    kind: Literal["source", "workspace"]
    created: str
    files: int
    version: int
    bytes_total: int | None


class BackupCatalog(TypedDict):
    snapshots: list[BackupSnapshot]
    warnings: list[str]


class RequestContext(typing_extensions.TypedDict, extra_items=object):
    """Compiled request context; Len's method requests may carry further keys."""

    line_kinds: NotRequired[
        dict[str, Literal["dialogue", "narration", "ui", "unknown"]]
    ]
    speakers: NotRequired[dict[str, str | None]]
    qa_notes: NotRequired[dict[str, str]]


class PreparedRequest(TypedDict):
    id: str
    sources: dict[str, str]
    fingerprint: str
    constraints: dict[str, object]
    context: RequestContext
    params: NotRequired[dict[str, object]]


class RequestResult(TypedDict):
    translations: dict[str, str]
    result_sha256: str
    reviewed: NotRequired[dict[str, str]]


class RequestPreview(TypedDict):
    run_id: str
    index: int
    total: int
    request: PreparedRequest
    result: RequestResult | None


class PreparedHandoff(TypedDict):
    handoff: str
    path: str
