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
    messageRows: int


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
    thorough_investigation: bool
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
    # The current request's report says the windows could not be measured.
    layoutUnmeasured: NotRequired[bool]
    # Why the current request's report could not be used.
    layoutRejected: NotRequired[str]


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
    recommended: dict[str, EngineValue]
    rows: list[EventTextRow]
    builtinHits: dict[str, list[str]]
    # The current findings' recommendations were saved as source choices.
    applied: bool
    errors: list[str]
    enabled: list[str]
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
    refusalNotes: NotRequired[
        Annotated[
            dict[str, int],
            "Lines per working copy that hold a refusal note an earlier run saved; the next run sends them again.",
        ]
    ]


class PublicationStatus(TypedDict):
    id: str
    kind: str
    state: str
    files: list[str]
    recovery_errors: list[str]


class QaLineChange(TypedDict):
    """One line of a scene correction."""

    source: str
    current: str
    correction: str


class QaFinding(TypedDict):
    id: str
    source: str
    current: str
    correction: str
    category: str
    severity: str
    family: Annotated[str, "The family a reviewer or lint named, or empty."]
    kind: Annotated[
        Literal["review", "lint", "glossary", "sweep", "source", "scene"],
        "How the finding came to be: a reviewer, lint, the glossary's term for another rendering, the family sweep, a source fix, or a reviewer's correction of several lines of one scene.",
    ]
    places: Annotated[int, "Lines the correction changes."]
    files: list[str]
    reason: str
    lines: NotRequired[
        Annotated[
            list[QaLineChange],
            "A scene correction's lines, which apply and undo together; source, current and correction join them.",
        ]
    ]
    editorial: NotRequired[Annotated[str, "The editorial reviewer's note."]]
    state: NotRequired[Literal["applied", "undone"]]


class QaQuestion(TypedDict):
    """A playtest or context question no evidence settled; the user answers."""

    id: str
    source: str
    current: str
    reason: str
    places: int
    proposal: NotRequired[str]
    choice: NotRequired[Literal["keep", "use"]]
    state: NotRequired[Literal["applied", "undone"]]


class QaCoverage(TypedDict):
    lines: Annotated[int, "Translated lines in QA's inventory."]
    not_reviewed: Annotated[int, "Lines reviewers declined, which QA set aside."]


class QaActivity(TypedDict):
    stage: Literal["lint", "screen", "deep", "sweep", "editorial"]
    done: int
    total: int
    eta_seconds: NotRequired[int]
    one_at_a_time: NotRequired[
        Annotated[bool, "Bundles waited while reviewers took one at a time."]
    ]


class QaUnreadable(TypedDict):
    """A prepared task the app can't read or trust, for the helper's next step."""

    path: Annotated[str, "The task folder, or the file naming it when that fails."]
    error: Annotated[str, "The error as raised."]


class QaReportLine(TypedDict):
    identity: str
    file: str
    source: str
    current: str


class QaUntranslatedText(TypedDict):
    pointer: str
    kind: str
    text: str


class QaUntranslatedSource(TypedDict):
    """One file's or plugin's Japanese that was never translated."""

    kind: Annotated[
        Literal["data", "custom", "plugin"],
        "Game data without a saved original, a custom data file, or plugin settings.",
    ]
    file: str
    plugin: NotRequired[str]
    count: int
    # Whether players can reach a custom file's or plugin's text: something
    # calls the plugin, it changes the game's screens itself, its file could
    # not be read, nothing calls it, or no turned-on plugin reads the file.
    reach: NotRequired[Literal["called", "runs", "unknown", "uncalled", "unread"]]
    evidence: NotRequired[Annotated[str, "What the reach rests on."]]
    texts: Annotated[list[QaUntranslatedText], "Its first texts."]


class QaInterfaceText(TypedDict):
    """Text the game squeezes or cuts off that QA holds no line of, such as a
    plugin's menu command."""

    text: str
    title: Annotated[str, "The captured screen that shows it."]


class QaReport(TypedDict):
    """What QA could not cover, for the History inspector."""

    not_reviewed: list[QaReportLine]
    not_translated: list[QaUntranslatedSource]
    interface_outside: list[QaInterfaceText]
    interface_error: NotRequired[str]


class TextQaOperation(TypedDict):
    kind: Literal["prepare", "apply", "undo", "reapply", "checkpoint"]
    id: str
    status: str
    message: str


class QaLabel(TypedDict):
    """Text the game squeezes or cuts off on a screen QA captured that QA
    holds no line of, for an Assistant-led assistant to shorten."""

    text: str
    title: Annotated[str, "The captured screen that shows it."]
    capture: Annotated[str, "The screen's capture file."]
    squeezed: NotRequired[
        Annotated[float, "The share of the width it needs the game drew it in."]
    ]
    clipped: NotRequired[Annotated[bool, "Its end is cut off at its window's edge."]]


class TextQaStatus(TypedDict):
    """Where the game's text QA stands, for the assistant's project helper."""

    focus: str
    task: str
    stage: str
    current: bool
    applied: bool
    findings: Annotated[int, "Findings with a correction."]
    questions: Annotated[int, "Open playtest or context questions."]
    message: str
    next: Annotated[str, "The step to run next."]
    progress: Annotated[dict[str, object], "The engine's checkpoint status."]
    labels: NotRequired[
        Annotated[
            list[QaLabel],
            "Assistant-led only: squeezed labels the assistant shortens before apply.",
        ]
    ]
    operation: NotRequired[TextQaOperation]
    report: NotRequired[Annotated[str, "The saved findings file."]]


class QaState(TypedDict):
    current: bool
    # This task's findings were applied, that batch was not restored and
    # nothing QA made since, such as a follow-up round's finding, waits.
    applied: bool
    task: NotRequired[str]
    status: dict[str, object]
    message: str
    findings: list[QaFinding]
    questions: list[QaQuestion]
    coverage: NotRequired[QaCoverage]
    activity: NotRequired[QaActivity]
    # An update changed QA's rules after this task was prepared: it is
    # outdated, and its applied corrections can no longer be undone here.
    rules_changed: NotRequired[bool]
    # The prepared task can't be read or trusted, so QA is blocked; message
    # says why, and preparing again sets it aside.
    unreadable: NotRequired[QaUnreadable]


class PlaytestSeen(TypedDict):
    """Where the playtest's tour saw a problem on screen."""

    stop: str
    scene: NotRequired[str]
    capture: NotRequired[Annotated[str, "Its capture, for guided_playtest_capture."]]


class PlaytestText(TypedDict):
    """One string of a grouped problem, such as a plugin's Japanese."""

    pointer: NotRequired[str]
    line: NotRequired[int]
    text: str
    reach: NotRequired[str]
    evidence: NotRequired[str]
    seen: NotRequired[PlaytestSeen]


type PlaytestFix = Literal["text-qa", "translate", "plugin-files", "game"]


class PlaytestProblem(TypedDict):
    kind: Annotated[
        Literal["crash", "japanese", "fit", "codes"],
        "The game stops, Japanese shows, text doesn't fit, or a name or code is lost.",
    ]
    check: Annotated[str, "Which check found it."]
    file: Annotated[
        str, "Game-relative path, or empty when the tour saw it with no file."
    ]
    note: str
    fix: Annotated[
        PlaytestFix, "The task that fixes it; game means the game's own code or data."
    ]
    pointer: NotRequired[str]
    line: NotRequired[int]
    plugin: NotRequired[str]
    text: NotRequired[str]
    original: NotRequired[str]
    count: NotRequired[Annotated[int, "Strings a grouped problem covers."]]
    reach: NotRequired[str]
    evidence: NotRequired[str]
    window: NotRequired[str]
    rows: NotRequired[int]
    codes: NotRequired[list[str]]
    reaches: NotRequired[dict[str, int]]
    texts: NotRequired[Annotated[list[PlaytestText], "Its first strings."]]
    seen: NotRequired[PlaytestSeen]
    new: NotRequired[Annotated[bool, "The previous playtest did not find it."]]
    review: NotRequired[
        Annotated[
            Literal["reviewing", "reviewed", "waiting"],
            "Where text QA stands on a problem it corrects: in its review now, reviewed, or waiting for QA to run again.",
        ]
    ]


class PlaytestStop(TypedDict):
    id: str
    title: NotRequired[str]
    status: Literal["done", "failed", "skipped", "not-reached", "running"]
    note: NotRequired[str]


class PlaytestCoverage(TypedDict):
    stops: list[PlaytestStop]
    reached: int
    messages: int
    choices: int
    battle_lines: int
    scenes: Annotated[int, "Screens the tour opened."]


class PlaytestSince(TypedDict):
    """Against the playtest before it: problems fixed, and problems new."""

    fixed: int
    new: int


class PlaytestState(TypedDict):
    """The latest release playtest of the game."""

    current: Annotated[bool, "The game's data and plugins are as it played them."]
    problems: list[PlaytestProblem]
    gaps: Annotated[list[str], "What the playtest could not reach or read."]
    report: NotRequired[str]
    finished_at: NotRequired[str]
    seconds: NotRequired[float]
    played: NotRequired[
        Annotated[bool, "The tour ran; false when only the files were checked."]
    ]
    complete: NotRequired[bool]
    coverage: NotRequired[PlaytestCoverage]
    since: NotRequired[PlaytestSince]
    unreadable: NotRequired[str]


class PlaytestOperation(TypedDict):
    id: str
    status: str
    message: str


class LayoutProbe(TypedDict):
    title: str
    fits: bool
    widest: Annotated[int, "Pixels the widest line takes."]
    room: Annotated[int, "Pixels the window gives a line."]
    lines: int
    rows: Annotated[int, "Rows the window shows."]
    capture: NotRequired[Annotated[str, "The capture's file."]]


class LayoutCheck(TypedDict):
    """English shown at given widths in the game's own windows."""

    operation: NotRequired[PlaytestOperation]
    finished_at: NotRequired[str]
    widths: NotRequired[dict[str, int]]
    probes: NotRequired[list[LayoutProbe]]
    missing: NotRequired[list[dict[str, str]]]
    unavailable: NotRequired[str]


class PlaytestFixCheck(TypedDict):
    finished_at: str
    fixed: Annotated[
        int, "Problems of the last playtest the play with the fixes no longer found."
    ]
    new: int
    reason: NotRequired[Annotated[str, "Why the fixes stayed out of the game."]]
    publication: NotRequired[
        Annotated[str, "The batch that wrote them, which History restores."]
    ]


class PlaytestFixes(TypedDict):
    """The plugin that carries the assistant's fixes for the game's own code."""

    file: Annotated[str, "The working copy the assistant edits."]
    in_game: Annotated[bool, "The game has the working copy as it is."]
    check: NotRequired[PlaytestFixCheck]
    saved: NotRequired[
        Annotated[
            bool,
            "Assistant-led, once the game has fixes: the latest checkpoint holds them as they are.",
        ]
    ]


class PlaytestStatus(TypedDict):
    """Where the release playtest stands, for the assistant's project helper."""

    current: bool
    finished_at: str
    problems: Annotated[dict[str, int], "Problems by the task that fixes them."]
    seen: Annotated[int, "Problems the tour saw on screen."]
    gaps: int
    reached: Annotated[str, "Stops reached, as 'done of total'."]
    next: Annotated[str, "The step to run next."]
    stops: Annotated[int, "Saved stops every run visits after the standard tour."]
    fixes: PlaytestFixes
    operation: NotRequired[PlaytestOperation]
    checkpoint: NotRequired[
        Annotated[
            PlaytestOperation,
            "Assistant-led: the last checkpoint saving the fixes the helper started.",
        ]
    ]
    report: NotRequired[Annotated[str, "The saved report file."]]
    layout: NotRequired[LayoutCheck]


class PlaytestCapture(TypedDict):
    url: Annotated[str, "A data URL of the JPEG."]


class TextFitState(TypedDict):
    # New Line widths wait to fit the applied text until nothing else runs;
    # the job is the newest fit of it.
    pending: bool
    job: str | None


class Readiness(TypedDict):
    publications: list[PublicationStatus]
    qa: QaState
    playtest: PlaytestState
    outputs: list[str]
    applied: list[str]
    unapplied: list[str]
    runtime_edited: list[str]
    review_current: bool
    text_fit: TextFitState
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


class FullEstimateTask(TypedDict):
    """One Translate task's share of the whole game's estimate."""

    phase: Literal["database", "dialogue", "advanced"]
    files: int
    # Other event text with no source chosen has nothing to translate.
    noSources: bool
    requests: int
    inputTokens: int
    outputTokens: int
    liveCost: float
    # With prompt caching where the provider offers it.
    batchCost: float
    # The most a Batch costs, with no cached instruction reused; estimates
    # saved before it was added hold batchNocacheCost instead.
    batchMaxCost: NotRequired[float]
    promptCache: bool
    # Claude's own token count could not run, so its input is approximate.
    approximateInput: bool
    # Thinking tokens are billed as output and cannot be predicted.
    unestimatedThinking: bool


class FullEstimateResult(TypedDict):
    model: str
    batchSupported: bool
    tasks: list[FullEstimateTask]


class FullEstimateTaskProgress(TypedDict):
    """Where one task of a working whole-game estimate stands."""

    phase: Literal["database", "dialogue", "advanced"]
    # Waiting for its turn, starting its worker, estimating its files, priced
    # by Claude's own count, or done.
    state: Literal["waiting", "starting", "estimating", "counting", "done"]
    # Its files estimated so far and its file count.
    current: int
    total: int
    # Seconds it took, once done.
    took: float | None


class FullEstimateProgress(TypedDict):
    """Where a working whole-game estimate stands: copying the game's text
    before any task, then each task with files to estimate, in order."""

    copying: bool
    tasks: list[FullEstimateTaskProgress]


class FullEstimate(TypedDict):
    """Context's whole-game cost estimate: the newest attempt's state and the
    newest saved result, current while every task's inputs are unchanged."""

    status: Literal["none", "working", "complete", "failed", "stopped"]
    message: str
    # When the newest attempt started, where it stands while working, and
    # whether Stop was clicked.
    started: str | None
    progress: FullEstimateProgress | None
    stopping: bool
    result: FullEstimateResult | None
    finished: str | None
    # Seconds the saved estimate took, as a guide to the next one.
    took: float | None
    current: bool


class GuidedState(TypedDict):
    eventText: EventTextState
    fullEstimate: FullEstimate
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


class ShowTextHeader(TypedDict):
    faceName: str
    faceIndex: int
    name: str


class HeaderFlag(TypedDict):
    kind: Literal["face", "self-address", "pronoun", "sound-effect", "unnamed-line"]
    file: str
    pointer: str
    faceName: str
    faceIndex: int
    name: str
    text: str
    evidence: str
    # The setup assistant's decision after checking the scene, and its reason.
    decision: Literal["fixed", "kept"] | None
    reason: str
    fixedTo: ShowTextHeader | None


class HeaderCheck(TypedDict):
    total: int
    fixed: int
    kept: int
    flags: list[HeaderFlag]


class SpeakerScan(TypedDict):
    job: Job | None
    available: bool
    current: bool
    names: list[str]
    actorNames: dict[str, str]
    variableActorIds: dict[str, int]
    # Likely Show Text header slips; null for a scan saved before the check.
    headers: HeaderCheck | None
    files: int
    path: str | None
    savedAt: str | None
    issue: str


class PublicationChange(TypedDict):
    path: str
    destination: str
    before: Annotated[str | None, "None for a file the batch adds."]
    after: Annotated[str | None, "None for a file the batch takes out."]
    size: int
    later_edits: bool
    # A restore's review compares the text; other publications list files.
    diff: NotRequired[str]
    truncated: NotRequired[bool]
    before_text: NotRequired[str]
    after_text: NotRequired[str]


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


class EventTextRequest(TypedDict):
    request: dict[str, object] | None
    findings: EventTextState


class SkillText(TypedDict):
    text: str


class OutputFolder(TypedDict):
    path: str


class ReleaseDestination(TypedDict):
    """Why a release ZIP cannot be written to the chosen path, or empty, and
    whether the archive name alone or the whole path is at fault."""

    error: str
    field: Literal["", "name", "path"]
