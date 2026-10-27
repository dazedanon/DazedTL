"""Len's method translation projects and runs, and backups from before checkpoints."""

from typing import Literal, NotRequired, TypedDict

import typing_extensions

from dazedtl.api.contracts.common import Documents
from dazedtl.api.contracts.runs import LegacyRun
from dazedtl.api.contracts.settings import Forge


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
    # For Claude, the most a Batch costs, with every cached instruction
    # written again; batch_cost_reused when each one is reused.
    batch_cost: float | None
    batch_cost_reused: NotRequired[float]
    # OpenAI's automatic cache, counted for pricing the quote again.
    cache_read_tokens: NotRequired[int]
    cacheable_tokens: NotRequired[int]
    # The model thinks, billed as output the quote cannot predict.
    unestimated_thinking_tokens: NotRequired[bool]
    model: str
    provider: str
    basis: str
    rates: QuoteRates


class TranslationBatch(TypedDict):
    id: str
    state: str
    # The run's requests this Batch holds.
    requests: int
    api_status: NotRequired[str]
    counts: NotRequired[dict[str, int]]
    # The error class of a provider cancellation that failed.
    cancel_error: NotRequired[str]


class TranslationIssue(TypedDict):
    id: str
    # The request's position in the run, as translation_request reads it.
    index: int
    state: str
    message: str


class RunRequestState(TypedDict):
    """A run's request in plan order, for choosing one by its ID or state."""

    id: str
    state: str


class QaRequest(TypedDict):
    id: str
    index: int
    notes: int


class TranslationJob(TypedDict):
    id: str
    project_id: str
    kind: Literal["translation", "operation"]
    action: NotRequired[str | None]
    # The checkpoint a Checkpoints operation goes back to, undoes or copies.
    target: NotRequired[str | None]
    label: str
    status: str
    message: str
    created: str
    updated: str
    mode: NotRequired[Literal["agent", "live", "batch"] | None]
    quote: TranslationQuote | None
    approval_token: str
    approved: bool
    app_approved_at: str | None
    # Only on an estimate waiting for approval in a project's state.
    settings_changed: NotRequired[bool]
    result: dict[str, object] | None
    usage: dict[str, float]
    # The recorded usage priced at the run's rates in a project's state;
    # None when the provider reports its own charge or the rates are unknown.
    usage_cost: NotRequired[float | None]
    counts: dict[str, int]
    units: int
    accepted_units: int
    # Lines the assistant declined that no run has translated yet.
    declined_units: int
    # The Assistant only run whose declined requests this API run translates.
    finishes: str | None
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
    # With assets pending, whether the update reached the translation: Finish
    # copies the assets, otherwise Cancel restores the version before it.
    asset_update_applied: bool
    asset_manifest_available: bool
    asset_baseline_repair_needed: bool
    applied_update_version: str | None
    preserve_game_files: bool
    available_original_refs: list[str]


class StartedOver(TypedDict):
    at: str
    # The game-relative folder holding the attempt set aside.
    archive: str


class DeliveryRecord(TypedDict):
    path: str
    commit: str
    game_version: str
    updater_stamp: bool
    files: NotRequired[int]


class VersionUpdate(TypedDict):
    version: str
    complete: bool


class Lifecycle(typing_extensions.TypedDict, extra_items=object):
    """Saved lifecycle evidence; further keys are internal to the backend,
    such as the backup records projects set up before their original files
    were kept in Git still hold."""

    version: int
    delivery: NotRequired[DeliveryRecord]
    incoming_version: NotRequired[str]
    version_update: NotRequired[VersionUpdate]
    discarded_release: NotRequired[str]
    # When the user last started over; earlier runs belong to that attempt.
    started_over: NotRequired[StartedOver]


class ConnectionSummary(TypedDict):
    name: str
    model: str


class ScopeRuleCount(TypedDict):
    # Built into DazedTL, or written by the user's assistant.
    by: Literal["tool", "assistant"]
    kind: str
    field: str
    reason: str
    file: NotRequired[str]
    # How many exact runs the rule names, when it names them.
    values: NotRequired[int]
    runs: int


class UncoveredField(TypedDict):
    kind: str
    field: str
    runs: int


class Coverage(TypedDict):
    """How the tool's census of the game's Japanese text is covered, in
    Japanese runs: extracted, set aside by a rule, or not extracted."""

    runs: int
    extracted: int
    set_aside: int
    uncovered: int
    untraced: int
    unit_runs: int
    rules: list[ScopeRuleCount]
    stale: bool
    source: Literal["tool", "assistant_dump"]
    needs_dump: list[str]
    unreadable: int
    uncovered_fields: list[UncoveredField]
    checked_at: NotRequired[str]


class GameUpdateValues(TypedDict):
    forge: Forge
    host: str
    owner: str
    repo: str
    branch: str


class GameUpdateStatus(TypedDict):
    """Where a game's gameupdate/patch-config.txt stands.

    absent: the game has no GameUpdate; unconfigured: no owner in Settings;
    needs_repo: the game's repository is unknown; pending: DazedTL writes it
    next; edited: changed after DazedTL wrote it, with other values; ready;
    unavailable: its status could not be read (see message).
    """

    state: Literal[
        "absent",
        "unconfigured",
        "needs_repo",
        "pending",
        "edited",
        "ready",
        "unavailable",
    ]
    message: str
    # The repository the game's settings keep, and the one origin suggests.
    repo: str
    suggested: str
    # What DazedTL writes; its repository is empty while unknown.
    values: GameUpdateValues | None
    # The complete values in the file, which players get.
    file: GameUpdateValues | None
    placeholder: bool
    differences: list[Literal["forge", "host", "owner", "repo", "branch"]]
    # Values the game sets itself instead of following Settings.
    overrides: list[Literal["forge", "host", "owner", "branch"]]
    # Why no Git remote is where players download from, or "".
    remote: str


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
    # The census coverage organize last found; None before a census.
    coverage: Coverage | None
    git: GitStatus | None
    gameUpdate: GameUpdateStatus
    lifecycle: Lifecycle
    # Whether the game's original files are kept: in its Git repository, or
    # in a backup saved before that.
    originalsRecorded: bool
    jobs: list[TranslationJob]
    active: bool
    warnings: list[str]
    # Why the game's Git checkout refuses every change, also among warnings;
    # "" when it takes them.
    checkoutIssue: str
    statusText: str
    providerEnabled: bool
    connection: ConnectionSummary | None
    batchSupported: bool
    legacyAvailable: bool


class UpdateTask(TypedDict):
    version: str
    prompt: str


class CheckpointBlocker(TypedDict):
    """The later checkpoint to undo first, and the files both changed."""

    commit: str
    title: str
    files: list[str]


class Checkpoint(TypedDict):
    """One checkpoint on the translation branch; see
    compatibility/checkpoint_history.py."""

    commit: str
    title: str
    # The stage the view groups it under.
    group: str
    time: str
    files: int
    # The first few files it changed.
    names: list[str]
    # "setup" or "update" for the checkpoint that starts a game version.
    kind: Literal["change", "setup", "update"]
    release: str
    current: bool
    # The go back that took it out of the game, or "".
    taken_out_by: str
    # In the current game version, so it can be gone back to or undone.
    restorable: bool
    blocker: CheckpointBlocker | None


class CheckpointVersion(TypedDict):
    version: str
    current: bool
    checkpoints: list[Checkpoint]


class CheckpointTimeline(TypedDict):
    version: str
    # Files in the patch edited outside DazedTL, not yet in a checkpoint.
    outside: list[str]
    versions: list[CheckpointVersion]
    # The backup store from before checkpoints, when the game has one.
    backups: str | None


class CheckpointTextLine(TypedDict):
    kind: Literal["edited"]
    before: str | None
    translation: None
    after: str | None


class CheckpointFileText(TypedDict):
    path: str
    to_translate: int
    replaced: int
    kept: int
    edited: int
    lines: list[CheckpointTextLine]
    more: int


class CheckpointText(TypedDict):
    to_translate: int
    replaced: int
    kept: int
    edited: int
    files: list[CheckpointFileText]


class CheckpointFileChange(TypedDict):
    path: str
    change: Literal["Added", "Removed", "Changed"]
    result: str


class CheckpointChanges(TypedDict):
    title: str
    group: str
    time: str
    file_changes: list[CheckpointFileChange]
    text: CheckpointText


class ReleaseLayout(TypedDict):
    """How a release lines up with the game as one kind; see the engine's
    util/version_update/release_layout.py."""

    kind: Literal["game", "patch"]
    source: str
    target: str
    files: int
    replaced: int
    outside: int
    left_out: list[str]
    game_files: int
    covered: int


class ReleaseInspection(TypedDict):
    detected: Literal["game", "patch"]
    version: str
    game: ReleaseLayout
    patch: ReleaseLayout


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


class TranslationResults(TypedDict):
    """Where the run's translations were written by line ID; counts only."""

    path: str
    translated: int
    missing: dict[str, int]
