"""Image Manager, image text editor and native image translation."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import ForeignWork
from dazedtl.api.contracts.runs import Job

type ImageDiscoveryScope = Literal["remaining", "all", "folders", "selected"]


type ImageEntryMode = Literal["discovery", "manual", "findings", "review"]


type ImageClassification = Literal[
    "recommended", "uncertain", "no_text", "already_english", "not_examined", "excluded"
]


class ImageView(TypedDict):
    query: str
    status: str
    folder: str
    showSelected: bool
    tileSize: int
    scroll: float
    currentImage: NotRequired[str]
    viewedImage: NotRequired[str]
    workflowMode: NotRequired[ImageEntryMode]


class ImageFinding(TypedDict):
    requestId: NotRequired[str]
    sourceHash: NotRequired[str]
    classification: NotRequired[ImageClassification]
    method: NotRequired[str]
    reason: NotRequired[str]
    evidence: NotRequired[str]
    examined: NotRequired[bool]
    variants: NotRequired[list[str]]
    saved: NotRequired[str]
    reusedFrom: NotRequired[str]


class ImageMetadata(TypedDict):
    width: int
    height: int
    mode: str
    transparency: bool
    alphaRange: list[int]
    alphaChannel: bool
    frames: int


class ImageApplication(TypedDict):
    """The runtime image a publication wrote, kept to detect later edits."""

    candidateHash: str
    runtimeHash: str
    sourceHash: str
    saved: str
    review: str
    recovered: NotRequired[bool]


class ImageAsset(TypedDict):
    id: str
    path: str
    filename: str
    folder: str
    sourceHash: str
    sourcePngHash: str
    editable: bool
    # Blocked only because the game's image changed after the copy was made.
    outdated: bool
    candidateHash: str | None
    state: str
    classification: ImageClassification
    reason: str
    blockedReason: str
    sourceIssue: NotRequired[str]
    encrypted: bool
    changed: bool
    aiReviewed: bool
    userReviewed: bool
    destination: str
    width: NotRequired[int | None]
    height: NotRequired[int | None]
    mode: NotRequired[str | None]
    method: NotRequired[str]
    evidence: NotRequired[list[object]]
    variants: NotRequired[list[str]]
    checks: NotRequired[dict[str, bool]]
    reviewEvidence: NotRequired[str]
    finding: NotRequired[ImageFinding | None]
    candidateIssue: str
    staleReason: str
    candidateMetadata: ImageMetadata | None
    applied: ImageApplication | None


class ImageCounts(TypedDict):
    indexed: int
    examined: int
    recommended: int
    uncertain: int
    notExamined: int
    ready: int
    needsReview: int
    blocked: int
    applied: int
    selected: int
    selectedReady: int
    selectedBlocked: int
    selectedNotPrepared: int
    selectedApplied: int
    selectedSkipped: int
    selectedNeedsReview: int
    selectedEditable: int
    missing: int


class ImageReportState(TypedDict):
    status: str
    lastReport: NotRequired[str | None]
    reportId: NotRequired[str | None]
    requestId: NotRequired[str | None]
    message: NotRequired[str]
    errors: NotRequired[list[str]]
    scope: NotRequired[ImageDiscoveryScope]
    folders: NotRequired[list[str]]
    copiedAt: NotRequired[str]
    # Why the last report found on returning to the window was not accepted.
    rejected: NotRequired[str]


class ImageReceiptAsset(TypedDict):
    id: str
    path: NotRequired[str]
    destination: NotRequired[str]


class ImageReceipt(TypedDict):
    id: str
    action: NotRequired[str]
    created: NotRequired[str]
    count: NotRequired[int]
    assets: NotRequired[list[ImageReceiptAsset]]
    available: NotRequired[bool]
    message: NotRequired[str]


class ImageProfile(TypedDict):
    id: str
    label: str
    imageRoot: NotRequired[str]
    supported: bool
    reason: NotRequired[str]
    context: str


class ImageFolder(TypedDict):
    path: str
    count: int


class ImageJobProgress(TypedDict):
    current: int
    total: int
    file: NotRequired[str]


class ImageJob(TypedDict):
    id: NotRequired[str]
    action: NotRequired[str]
    status: str
    message: NotRequired[str]
    indexed: NotRequired[int]
    current: NotRequired[int]
    total: NotRequired[int]
    progress: NotRequired[ImageJobProgress]


class ImageManagerState(TypedDict):
    projectId: str
    name: str
    engine: str
    profile: ImageProfile
    source: str
    revision: str
    observationRevision: NotRequired[str]
    inventoryRevision: str
    counts: ImageCounts
    folders: list[ImageFolder]
    selection: list[str]
    view: ImageView
    discovery: ImageReportState
    editing: ImageReportState
    receipts: list[ImageReceipt]
    warnings: list[str]
    lastAction: NotRequired[
        Annotated[dict[str, object], "The latest prepare or publication receipt."]
    ]
    editableRoot: NotRequired[str]
    supported: NotRequired[bool]
    job: NotRequired[ImageJob | None]


class ImageForeignWork(ForeignWork):
    examined: int
    edited: int


class ImageDraft(TypedDict):
    selection: list[str]
    view: ImageView
    discoveryScope: ImageDiscoveryScope
    folders: list[str]
    imageRoot: NotRequired[str]


class ImageList(TypedDict):
    items: list[ImageAsset]
    total: int
    selectedMatched: int
    offset: NotRequired[int]
    limit: int


class ImagePreviewAsset(TypedDict):
    id: str
    path: str
    destination: str
    sourceHash: str
    candidateHash: str


class ImageBlocked(TypedDict):
    id: str
    path: str
    reason: str


class ImagePreview(TypedDict):
    token: str
    action: str
    assets: list[ImagePreviewAsset]
    blocked: list[ImageBlocked]
    included: int
    count: int
    unchanged: int
    backups: NotRequired[list[str] | bool]
    expires: NotRequired[str | float]


class ImageActionResult(TypedDict):
    state: ImageManagerState
    result: NotRequired[
        Annotated[dict[str, object], "Counts and paths the action reported."]
    ]
    text: NotRequired[str]
    requestId: NotRequired[str]
    preview: NotRequired[ImagePreview]
    message: NotRequired[str]


class ImagePixels(ImageMetadata):
    url: str
    sha256: str


type Colour = list[int]


class ImageTextStyle(TypedDict):
    background: NotRequired[
        Literal[
            "transparent", "solid", "vgradient", "hgradient", "patch", "inpaint", "keep"
        ]
    ]
    fill: NotRequired[Colour | None]
    text_color: NotRequired[Colour]
    outline_color: NotRequired[Colour | None]
    outline_width: NotRequired[int]
    cap_height: NotRequired[int]
    align: NotRequired[Literal["left", "center", "right"]]
    font: NotRequired[str]
    scale_x: NotRequired[int]
    scale_y: NotRequired[int]
    tracking: NotRequired[int]
    bold: NotRequired[bool]
    italic: NotRequired[bool]
    overflow: NotRequired[bool]
    locked: NotRequired[bool]
    confidence: NotRequired[float]
    notes: NotRequired[list[str]]
    row_colors: NotRequired[list[Colour]]
    column_colors: NotRequired[list[Colour]]
    donor: NotRequired[tuple[int, int, int, int] | None]
    inpaint_method: NotRequired[str]


class ImageTextBlock(TypedDict):
    id: str
    box: tuple[int, int, int, int]
    source: str
    target: str
    angle: float
    skip: bool
    flags: NotRequired[list[str]]
    lines: NotRequired[list[object]]
    style: NotRequired[ImageTextStyle]


class ImageTextNote(TypedDict):
    blockId: str
    ok: bool
    message: str
    tight: bool


class ImageEditorImage(TypedDict):
    assetId: str
    path: str
    width: int
    height: int
    status: str
    blocks: list[ImageTextBlock]
    sourceHash: str
    candidateHash: str
    changed: bool
    originalUrl: str
    candidateUrl: str
    error: str
    engine: str
    notes: list[ImageTextNote]


class ImageFont(TypedDict):
    id: str
    label: str


class LocalOcr(TypedDict):
    available: bool
    detail: str


class ImageEditorState(TypedDict):
    revision: str
    selectedIds: list[str]
    images: list[ImageEditorImage]
    fonts: list[ImageFont]
    localOcr: LocalOcr
    exchangePath: str


class ImageEditorSave(TypedDict):
    assetId: str
    sourceHash: str
    candidateHash: str
    blocks: list[ImageTextBlock]
    status: Literal["needs_review", "confirmed"]


class ImageEditorExport(TypedDict):
    path: str
    assetIds: list[str]
    count: int
    requestHash: str


class ImageEditorOutcome(TypedDict):
    path: NotRequired[str]
    assetIds: NotRequired[list[str]]
    count: NotRequired[int]
    requestHash: NotRequired[str]
    applied: NotRequired[int]
    missing: NotRequired[int]
    empty: NotRequired[int]
    completed: NotRequired[list[str]]
    errors: NotRequired[dict[str, str]]


class ImageEditorActionResult(TypedDict):
    state: ImageEditorState
    result: ImageEditorOutcome


class ImageNativeJob(Job):
    imported: NotRequired[bool]
    imageConfiguration: NotRequired[ImageNativeConfiguration]


class ImageNativeSelection(TypedDict):
    fingerprint: str
    count: int
    configuration: ImageNativeConfiguration


class ImageNativeTranslationState(TypedDict):
    jobs: list[ImageNativeJob]
    job: ImageNativeJob | None
    activeId: str | None
    quote: ImageNativeJob | None
    quoteCurrent: bool
    current: ImageNativeSelection | None
    error: str
    providerEnabled: bool
    batchSupported: bool


class ImageNativeConfiguration(TypedDict):
    model: str
    language: str
    endpoint: str
    entries_per_request: int


class ImageNativeTranslationPreview(TypedDict):
    token: str
    mode: Literal["estimate", "translate", "batch"]
    count: int
    assetIds: list[str]
    configuration: ImageNativeConfiguration
    estimate: dict[str, object] | None
    confirmation: bool


class ImageNativeOutcome(TypedDict):
    path: NotRequired[str]
    files: NotRequired[int]
    state: NotRequired[ImageEditorState]
    result: NotRequired[ImageEditorOutcome]


class ImageNativeTranslationActionResult(TypedDict):
    state: ImageNativeTranslationState
    result: ImageNativeOutcome
