"""The guided workflow state and its previews."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import (
    Documents,
    EngineValue,
    Evidence,
    Phase,
    RunMode,
)
from dazedtl.api.contracts.runs import Job, RunEstimate


class FileTextRow(TypedDict):
    location: str
    text: str
    source: str | None
    truncated: bool


class FileTextPreview(TypedDict):
    file: str
    origin: Literal["translated", "working", "game"]
    revision: str
    rows: list[FileTextRow]
    offset: int
    total: int
    nextOffset: int | None


type GuidedStep = Literal["setup", "context", "translate", "check", "release"]


class LayoutWidths(TypedDict):
    width: int
    faceWidth: int
    listWidth: int
    noteWidth: int


class GuidedOptions(TypedDict):
    selected: list[str]
    mode: Literal["batch", "translate"]
    engine_options: dict[str, EngineValue]
    widths: LayoutWidths
    phase1_comments: bool


class GuidedPreferences(TypedDict):
    revision: int
    values: GuidedOptions


class TextToolsForm(TypedDict):
    view: Literal["apply", "fitting", "qa", "tools"]
    categories: list[str]
    codes: str
    max_rows: int
    protect_rows: bool
    focus: str
    findings_task: str
    findings: list[str]


class ReleaseNames(TypedDict):
    game: str
    patch: str


class ReleaseForm(TypedDict):
    kind: Literal["game", "patch"]
    name: str
    names: ReleaseNames
    assets: list[str]
    directory: str
    tools: PlaytestOptions


class GuidedForm(TypedDict):
    version: str
    original: str
    untranslated: bool | None
    only_overflow: bool
    text: TextToolsForm
    release: ReleaseForm


class PlaytestOptions(TypedDict):
    hotkey: str
    forgeHotkey: str
    uiScale: str
    editorCmd: str


class ReleaseArtifact(TypedDict):
    id: str
    kind: Literal["game", "patch"]
    path: str
    folder: str
    available: bool
    # Built from the game's current runtime files; None for an archive saved
    # before DazedTL recorded them.
    current: bool | None
    size: int | None
    saved: str | None


class GuidedFile(TypedDict):
    name: str
    title: NotRequired[str]
    default: NotRequired[bool]
    size: NotRequired[int]
    group: Literal["database", "dialogue"]


class SpeakerRule(TypedDict):
    key: str
    label: str
    decision: Literal["enable", "skip"]
    confidence: Literal["high", "medium", "low"]
    reason: str
    evidence: list[Evidence]


class SpeakerSetup(TypedDict):
    status: Literal["missing", "waiting", "invalid", "stale", "ready", "applied"]
    message: str
    reportId: str | None
    overrides: list[str]
    rules: list[SpeakerRule]


class ContextDocumentStatus(TypedDict):
    exists: bool
    reviewed: bool
    needsReview: bool
    intentionalEmpty: bool


class LayoutRecommendation(TypedDict):
    widths: LayoutWidths
    reason: str
    evidence: list[Evidence]


class ContextSetup(TypedDict):
    status: Literal["missing", "waiting", "ready", "stale", "invalid"]
    message: str
    requestId: str | None
    speakerReportId: str | None
    referencesSha256: str
    scanSha256: str | None
    revisions: dict[str, str]
    documents: dict[str, ContextDocumentStatus]
    layout: LayoutRecommendation | None
    layoutStatus: Literal["defaults", "saved"]
    layoutRevision: str
    layoutReportId: NotRequired[str | None]
    layoutApplication: NotRequired[Literal["none", "pending", "applied", "manual"]]
    layoutMessage: NotRequired[str]


class ReferenceFolder(TypedDict):
    id: str
    title: str
    path: str
    available: bool


class EventTextChoice(TypedDict):
    id: str
    group: str
    details: str


class EventTextRow(TypedDict):
    key: str
    label: str
    coverage: str
    selector: Literal["ENABLED_PLUGINS_357", "ENABLED_PATTERNS_355655"] | None
    choices: list[EventTextChoice]
    builtins: list[str]
    decision: Literal["enable", "skip", "review"]
    confidence: Literal["high", "medium", "low"]
    coverageStatus: str
    reason: str
    targets: str | list[str]
    observations: list[str]
    exclusions: list[str]
    evidence: list[Evidence]


class EventTextPicker(TypedDict):
    key: Literal["ENABLED_PLUGINS_357", "ENABLED_PATTERNS_355655"]
    selected: list[str]
    baseline: list[str]
    query: str
    filter: Literal["all", "selected", "recommended"]


class EventTextState(TypedDict):
    status: Literal["missing", "waiting", "ready", "stale", "invalid"]
    message: str
    reportId: str | None
    fingerprint: str | None
    requestId: str | None
    binding: str | None
    recommended: dict[str, EngineValue]
    rows: list[EventTextRow]
    builtinHits: dict[str, list[str]]
    accepted: bool
    errors: list[str]
    enabled: list[str]
    manual: list[str]
    manualReason: str
    previousManualReason: str
    view: Literal["audit", "sources", "advanced-run", "variables"]
    picker: EventTextPicker | None


class PreparationStage(TypedDict):
    action: str
    label: str
    status: str
    message: str
    result: NotRequired[dict[str, object]]


class Preparation(TypedDict):
    complete: bool
    configuration: str
    configurationReady: bool
    stages: list[PreparationStage]


class EngineSetting(TypedDict):
    key: str
    label: str
    type: str
    default: EngineValue
    choices: NotRequired[list[str]]
    min: NotRequired[int]
    max: NotRequired[int]


class PhaseEstimate(TypedDict):
    job: Job | None
    current: bool


class ComparisonRow(TypedDict):
    file: str
    location: str
    literal: str
    translation: str
    variables: list[str]


class Comparisons(TypedDict):
    matches: int
    unmatched: int
    files: list[str]
    message: str
    status: Literal["not_needed", "review_needed", "ready", "recovery_needed"]
    fingerprint: str | None
    rows: list[ComparisonRow]


class SourceStatus(TypedDict):
    ready: list[str]
    changed: list[str]
    retired: NotRequired[list[str]]
    noRequests: NotRequired[
        Annotated[
            dict[Phase, dict[str, str]],
            "Estimate start time per phase and file found without text to translate.",
        ]
    ]


class PublicationStatus(TypedDict):
    id: str
    kind: str
    state: str
    files: list[str]
    recovery_errors: list[str]


class QaFinding(TypedDict):
    id: str
    source: NotRequired[str]
    live: NotRequired[str]
    current: NotRequired[str]
    correction: NotRequired[str]
    reason: NotRequired[str]
    evidence: NotRequired[str]
    note: NotRequired[str]
    category: NotRequired[str]
    classification: NotRequired[str]
    identity: NotRequired[str]


class QaCorrection(TypedDict):
    finding_id: str
    file: str
    expected: str
    replacement: str
    identity: str


class QaState(TypedDict):
    current: bool
    task: NotRequired[str]
    status: dict[str, object]
    message: str
    findings: list[QaFinding]
    corrections: list[QaCorrection]


class Readiness(TypedDict):
    publications: list[PublicationStatus]
    qa: QaState
    outputs: list[str]
    applied: list[str]
    unapplied: list[str]
    runtime_edited: list[str]
    review_current: bool
    layout_scan: str | None
    delivery_available: bool


class ToolStatus(TypedDict):
    installed: bool
    present: bool
    message: str


class PlaytestTools(TypedDict):
    inspector: ToolStatus
    forge: ToolStatus


class AcePacking(TypedDict):
    required: bool
    current: bool
    message: str


class ReferenceSummary(TypedDict):
    id: str
    title: str


class GuidedProvider(TypedDict):
    connection: str
    model: str
    defaultMode: RunMode
    batchSupported: bool
    batchReason: NotRequired[str]
    ready: bool
    enabled: bool


class GuidedState(TypedDict):
    eventText: EventTextState
    contextDocument: str
    contextSetup: ContextSetup
    speakerSetup: SpeakerSetup
    speakerScan: SpeakerScan
    projectId: str
    source: str
    engine: Literal["MVMZ", "ACE"]
    dataPath: str
    encrypted: list[str]
    hasPlugins: bool
    step: GuidedStep
    task: str | None
    positions: dict[GuidedStep, str | None]
    form: GuidedForm
    preparation: Preparation
    preferences: GuidedPreferences
    optionsDraft: GuidedPreferences | None
    engineSchema: list[EngineSetting]
    files: list[GuidedFile]
    selection: list[str]
    importedFiles: list[str]
    collectionError: str
    operations: list[Job]
    run: Job | None
    runs: list[Job]
    activeJobId: str | None
    phase: Phase
    phaseFiles: list[str]
    estimates: dict[Phase, PhaseEstimate]
    phaseRuns: dict[Phase, Job]
    comparisons: Comparisons
    sourceStatus: SourceStatus
    readiness: Readiness
    documents: Documents
    drafts: Documents
    tools: PlaytestTools | None
    artifacts: list[ReleaseArtifact]
    acePacking: AcePacking
    references: list[ReferenceSummary]
    referenceFolders: list[ReferenceFolder]
    provider: GuidedProvider


class SpeakerScan(TypedDict):
    job: Job | None
    available: bool
    current: bool
    names: list[str]
    actorNames: dict[str, str]
    variableActorIds: dict[str, int]
    files: int
    path: str | None
    savedAt: str | None
    issue: str


class PublicationChange(TypedDict):
    path: str
    destination: str
    before: str
    after: str
    size: int
    later_edits: bool
    diff: str
    truncated: bool
    before_text: str
    after_text: str


class PreviewRun(TypedDict):
    model: str
    connection: str
    mode: str


class PreviewEstimate(TypedDict):
    jobId: str
    fingerprint: str
    value: RunEstimate
    model: str
    connection: str
    repeatSubmission: NotRequired[bool]


class PackageExclusion(TypedDict):
    path: str
    reason: str


class PackageSummary(TypedDict):
    included: int
    excluded: int
    exclusions: NotRequired[list[PackageExclusion]]
    updater: NotRequired[str]
    generated: NotRequired[list[str]]


class RewrapChange(TypedDict):
    file_name: str
    locator: str
    before: str
    after: str
    rows: NotRequired[int]
    overflow: NotRequired[bool]


class RewrapSummary(TypedDict):
    changes_found: int
    overflow_skipped: int
    previews: list[RewrapChange]


class Preview(TypedDict):
    publication: NotRequired[list[PublicationChange]]
    run: NotRequired[PreviewRun | None]
    estimate: NotRequired[PreviewEstimate | None]
    package: NotRequired[PackageSummary | None]
    overwrite: NotRequired[bool]
    game_version: NotRequired[str | None]
    additions: NotRequired[list[str]]
    token: str
    label: str
    destination: str
    files: int
    action: str
    paths: list[str]
    confirmation: bool
    options: dict[str, object]
    rewrap: NotRequired[RewrapSummary]


class EventTextRequest(TypedDict):
    request: dict[str, object] | None
    findings: EventTextState


class SkillText(TypedDict):
    text: str


class OutputFolder(TypedDict):
    path: str


class ReleaseDestination(TypedDict):
    """Why a release ZIP cannot be written to the chosen path, or empty."""

    error: str
