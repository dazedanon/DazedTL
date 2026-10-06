"""Engine run records shown by the guided workflow and its inspectors."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import EngineValue, Phase


class Progress(TypedDict):
    current: int
    total: int
    file: str


class EventTextReview(TypedDict):
    manual: NotRequired[list[str]]
    reason: NotRequired[str]
    binding: NotRequired[str]
    reportId: NotRequired[str | None]
    fingerprint: NotRequired[str]
    literalBased: NotRequired[bool]
    settings: NotRequired[dict[str, EngineValue]]


class Approval(TypedDict):
    token: str
    kind: Literal["batch", "speakers"]
    detail: dict[str, object]


class RunEstimate(TypedDict):
    """Token counts and prices from an estimate; producers fill different parts."""

    model: NotRequired[str]
    provider: NotRequired[str | None]
    basis: NotRequired[str]
    files: NotRequired[int]
    requests: NotRequired[int]
    request_count: NotRequired[int]
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]
    dynamic_tokens: NotRequired[int]
    cache_write_tokens: NotRequired[int]
    cache_read_tokens: NotRequired[int]
    cache_kind: NotRequired[str | None]
    uses_prompt_cache: NotRequired[bool]
    live_cost: NotRequired[float]
    estimated_cost: NotRequired[float]
    batch_supported: NotRequired[bool]
    batch_cost: NotRequired[float | None]
    batch_cached_cost: NotRequired[float]
    batch_nocache_cost: NotRequired[float]
    unestimated_thinking_tokens: NotRequired[bool]
    elapsed_seconds: NotRequired[float]


class Job(TypedDict):
    id: str
    status: str
    workerStatus: NotRequired[str]
    message: str
    created: NotRequired[str]
    updated: NotRequired[str]
    label: NotRequired[str]
    mode: NotRequired[str | None]
    phase: NotRequired[str]
    model: NotRequired[str]
    files: NotRequired[list[str]]
    progress: NotRequired[Progress | None]
    itemProgress: NotRequired[Progress | None]
    log: list[str]
    estimate: NotRequired[RunEstimate | None]
    outputs: NotRequired[dict[str, str]]
    outputsAvailable: NotRequired[bool]
    availableOutputs: NotRequired[list[str]]
    changedOutputs: NotRequired[list[str]]
    partialOutputs: NotRequired[list[str]]
    retiredFiles: NotRequired[list[str]]
    logicalPhase: NotRequired[Phase | None]
    preparationMode: NotRequired[Literal["batch", "translate"] | None]
    nothingToTranslate: NotRequired[
        Annotated[bool, "A finished estimate found no source text in any of its files."]
    ]
    temporary: NotRequired[bool]
    repeatSubmission: NotRequired[bool]
    nameTranslation: NotRequired[NameTranslation | None]
    scopeComplete: NotRequired[bool]
    appliedOutputs: NotRequired[list[str]]
    process: NotRequired[RunProcess]
    eventTextReview: NotRequired[EventTextReview | None]
    action: NotRequired[str]
    result: NotRequired[dict[str, object] | None]
    approval: NotRequired[Approval | None]


class LegacyRun(TypedDict):
    """A run saved by the former workflow, for the project helper to recover."""

    id: str
    status: str
    message: str
    mode: NotRequired[str | None]
    phase: NotRequired[str]
    approval: NotRequired[Approval | None]
    outputs: NotRequired[dict[str, str]]


class NameTranslationRow(TypedDict):
    source: str
    translation: str


class NameTranslation(TypedDict):
    state: Literal["running", "saved", "failed", "unavailable"]
    reused: NotRequired[bool]
    count: int
    rows: list[NameTranslationRow]


class NameTranslationPage(TypedDict):
    rows: list[NameTranslationRow]
    total: int
    offset: int
    nextOffset: int | None


class Billing(TypedDict):
    openrouter_cost: NotRequired[float]
    upstream_inference_cost: NotRequired[float]


class BatchMonitoring(TypedDict):
    state: Literal["monitoring", "collecting", "error", "save_error", "blocked"]
    message: str
    checkedAt: NotRequired[str]


class FileMetric(TypedDict):
    cost: float
    seconds: float


class ValidationIssue(TypedDict):
    file: str
    rejected: int | None


class ProcessRequest(TypedDict):
    index: int
    state: str
    file: NotRequired[str | None]
    sourceItems: int
    clarificationOf: NotRequired[int]
    preview: NotRequired[str]
    providerFinished: NotRequired[bool]


class FreshStart(TypedDict):
    eligible: bool
    reason: str
    failed: NotRequired[int]
    remaining: NotRequired[int]


class ProviderBatch(TypedDict):
    id: str
    status: str
    provider: NotRequired[str]
    canCancel: NotRequired[bool]
    total: NotRequired[int | None]
    requestIndices: NotRequired[list[int]]
    clarification: NotRequired[bool]
    originalBatchId: NotRequired[str]
    counts: dict[str, int | None]
    errors: NotRequired[list[dict[str, str]]]


class RunProcess(TypedDict):
    resultsUnavailable: NotRequired[str | None]
    queueStopped: NotRequired[bool]
    queueCanContinue: NotRequired[bool]
    billing: NotRequired[Billing | None]
    noRequestFiles: NotRequired[list[str]]
    monitoring: NotRequired[BatchMonitoring]
    resultsCollected: NotRequired[bool]
    fileMetrics: NotRequired[dict[str, FileMetric]]
    mode: NotRequired[str]
    prepared: NotRequired[int]
    submitted: NotRequired[int | None]
    remaining: NotRequired[int | None]
    received: NotRequired[int | None]
    validated: NotRequired[int | None]
    validatedFiles: NotRequired[int]
    appliedFiles: NotRequired[int]
    failed: NotRequired[int]
    retryBlocked: NotRequired[bool]
    nextAction: NotRequired[str]
    rejected: NotRequired[int]
    unused: NotRequired[int]
    validationIssues: NotRequired[list[ValidationIssue]]
    uncertain: NotRequired[int]
    duplicateSubmissions: NotRequired[int]
    requests: NotRequired[list[ProcessRequest]]
    freshStart: NotRequired[FreshStart | None]
    sourceItems: NotRequired[int | None]
    submittedItems: NotRequired[int | None]
    batches: NotRequired[list[ProviderBatch]]
    runErrors: NotRequired[list[str]]
    errors: list[str]
    usage: NotRequired[dict[str, float] | None]


class BatchCancellation(TypedDict):
    token: str
    runId: str
    batchId: str
    provider: str
    model: str
    files: list[str]
    requests: int


class ResponseAttempt(TypedDict):
    kind: Literal["original", "clarification"]
    batchId: NotRequired[str]
    response: object
    payload: NotRequired[RunPayload]


class UnusedResponse(TypedDict):
    appliedRequests: list[int]


class RunPayload(TypedDict):
    responseOrigin: NotRequired[Literal["validated", "log"] | None]
    responseAttempts: NotRequired[list[ResponseAttempt]]
    translations: NotRequired[object]
    unused: NotRequired[UnusedResponse | None]
    index: int
    total: int
    state: str
    source: dict[str, str] | None
    context: object
    parameters: dict[str, object]
    messages: object
    system: object
    exact: object
    error: NotRequired[object]
    response: NotRequired[object]
    usage: NotRequired[dict[str, float] | None]


class PreparationDiscarded(TypedDict):
    discarded: bool


class SettledEstimate(TypedDict):
    files: list[str]


class ProviderDetails(TypedDict):
    batches: list[ProviderBatch]


class BatchCancelRequested(TypedDict):
    id: str
    status: str
    requested: bool
