"""Request parameters and the registry of every application method.

Each method's handler takes the request fields as keyword arguments and returns
the response shape. scripts/contracts.mjs renders this registry and the shapes it
reaches as the renderer's TypeScript contracts and the shared protocol manifest.
"""

from dataclasses import dataclass
from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.common import Documents, ExportedFiles, Phase, Saved
from dazedtl.api.contracts.guided import (
    ContextSetup,
    EventTextPicker,
    EventTextRequest,
    FileTextPreview,
    GuidedAction,
    GuidedForm,
    GuidedOptions,
    GuidedPreferences,
    GuidedState,
    GuidedStep,
    OutputFolder,
    PlaytestCapture,
    PlaytestStatus,
    Preview,
    QaReport,
    ReferenceFolder,
    ReleaseDestination,
    SkillText,
    SpeakerScan,
    TextQaStatus,
)
from dazedtl.api.contracts.images import (
    ImageActionResult,
    ImageAssistantStep,
    ImageAssistantStepResult,
    ImageDiscoveryScope,
    ImageEditorActionResult,
    ImageEditorSave,
    ImageEditorState,
    ImageList,
    ImageManagerState,
    ImageNativeTranslationActionResult,
    ImageNativeTranslationPreview,
    ImageNativeTranslationState,
    ImagePixels,
    ImageView,
)
from dazedtl.api.contracts.plugins import (
    PluginActionResult,
    PluginCapture,
    PluginState,
)
from dazedtl.api.contracts.runs import (
    BatchCancellation,
    BatchCancelRequested,
    Job,
    NameTranslationPage,
    PreparationDiscarded,
    ProviderDetails,
    RequestPage,
    RunPayload,
    SettledEstimate,
)
from dazedtl.api.contracts.settings import (
    ConnectionInput,
    ConnectionUsage,
    Forge,
    ModelDefaults,
    ModelOptions,
    OpenRouterHost,
    PreferenceValues,
    Settings,
)
from dazedtl.api.contracts.translation import (
    BackupCatalog,
    CheckpointChanges,
    CheckpointTimeline,
    GameUpdateStatus,
    PreparedHandoff,
    ProjectOptions,
    ReleaseInspection,
    RequestPreview,
    RunRequestState,
    TranslationJob,
    TranslationOptions,
    TranslationProgress,
    TranslationResults,
    TranslationState,
    UpdateTask,
)
from dazedtl.api.contracts.workspace import (
    AppState,
    AssistantTaskKind,
    Screen,
    TranslationMethod,
    WorkspaceSnapshot,
)


@dataclass(frozen=True)
class Method:
    request: type
    response: object
    # Mutations refresh the workspace snapshot after they finish. One that
    # changes snapshot-backed state, a recovery draft included, must keep this:
    # a remounted editor would otherwise recover an older draft from the
    # cached snapshot. Reads and state outside the snapshot turn it off.
    refresh: bool = True
    # Allowed while the window closes, to save drafts and read final state.
    during_close: bool = False


class ProjectRequest(TypedDict):
    project_id: str


class LocateProjectRequest(TypedDict):
    project_id: str
    source: str


class AssistantTaskRequest(TypedDict):
    project_id: str
    kind: AssistantTaskKind


class AssistantTaskDismissed(TypedDict):
    kind: AssistantTaskKind


class ActionRequest(TypedDict):
    project_id: str
    action: str
    options: NotRequired[dict[str, object]]


class ForeignWorkRequest(TypedDict):
    project_id: str
    binding: str


class PluginsContinueRequest(TypedDict):
    project_id: str
    request_id: str


class PluginsCaptureRequest(TypedDict):
    project_id: str
    start: NotRequired[
        Annotated[
            bool,
            "Capture the shortening request's working copies as they are now first.",
        ]
    ]


class ImagesListRequest(TypedDict):
    project_id: str
    query: NotRequired[str]
    folder: NotRequired[str]
    filter: NotRequired[str]
    offset: NotRequired[int]
    limit: NotRequired[int]
    selected_only: NotRequired[bool]
    asset_id: NotRequired[str]


class ImageDraftChanges(TypedDict):
    selection: NotRequired[list[str]]
    view: NotRequired[ImageView]
    discoveryScope: NotRequired[ImageDiscoveryScope]
    folders: NotRequired[list[str]]
    imageRoot: NotRequired[str]


class ImagesUpdateRequest(TypedDict):
    project_id: str
    revision: str
    changes: ImageDraftChanges


class ImagesPreviewRequest(TypedDict):
    project_id: str
    asset_id: str
    variant: NotRequired[Literal["source", "original", "candidate"]]
    size: NotRequired[int]


class ImagesEditorStateRequest(TypedDict):
    project_id: str
    asset_ids: NotRequired[list[str]]


class ImagesEditorSaveRequest(TypedDict):
    project_id: str
    revision: str
    images: list[ImageEditorSave]
    asset_ids: NotRequired[list[str]]


class ImagesEditorActionRequest(TypedDict):
    project_id: str
    revision: str
    action: str
    asset_ids: list[str]
    arguments: NotRequired[dict[str, object]]


class ImagesEditorTranslationPreviewRequest(TypedDict):
    project_id: str
    mode: Literal["estimate", "translate", "batch"]


class ImagesEditorTranslationStartRequest(TypedDict):
    project_id: str
    token: str
    approved: NotRequired[bool]


class ImagesEditorTranslationActionRequest(TypedDict):
    project_id: str
    run_id: str
    action: str
    arguments: NotRequired[dict[str, object]]


class TranslationSpeakersRequest(TypedDict):
    project_id: str
    scan: bool
    # Apply the setup assistant's review of the scan's likely header slips.
    fix_headers: NotRequired[bool]


class TranslationIdentifyRequest(TypedDict):
    project_id: str
    engine: str
    evidence_file: str


class TranslationImagesRequest(TypedDict):
    project_id: str
    step: ImageAssistantStep


class TranslationQaRequest(TypedDict):
    project_id: str
    step: Literal[
        "status",
        "report",
        "prepare",
        "apply",
        "checkpoint",
        "undo",
        "reapply",
        "choose",
    ]
    findings: NotRequired[list[str]]
    question: NotRequired[str]
    choice: NotRequired[Literal["keep", "use"]]
    since: NotRequired[str]
    everything: NotRequired[bool]


class TranslationPlaytestRequest(TypedDict):
    project_id: str
    step: Literal["status", "report", "run", "fix", "checkpoint", "layout"]
    stops: NotRequired[
        Annotated[
            list[dict[str, object]],
            "Places only the game's events reach, played after the standard tour; they replace the saved stops every later run visits.",
        ]
    ]
    widths: NotRequired[
        Annotated[
            dict[str, int],
            "With layout: characters per line as width, faceWidth and listWidth, and messageRows.",
        ]
    ]


class PlaytestCaptureRequest(TypedDict):
    project_id: str
    name: str


class TranslationLegacyRequest(TypedDict):
    project_id: str
    action: Literal["resume", "stop", "answer", "export"]
    token: NotRequired[str]
    approved: NotRequired[bool]


class TranslationResolveUncertainRequest(TypedDict):
    project_id: str
    run_id: str
    batch_id: str
    request_sha256: str
    retry_reviewed: bool


class TranslationSaveRequest(TypedDict):
    project_id: str
    revision: str
    values: TranslationOptions


class TranslationDraftRequest(TypedDict):
    project_id: str
    section: Literal["options", "documents"]
    value: object


class SaveDocumentRequest(TypedDict):
    project_id: str
    name: str
    revision: str
    text: str


class SaveDocumentsRequest(TypedDict):
    project_id: str
    documents: Documents


class TranslationReleaseRequest(TypedDict):
    project_id: str
    folder: str


class InputPathRequest(TypedDict):
    project_id: str
    input_path: str


class TranslationOrganizeRequest(TypedDict):
    project_id: str
    input_path: str
    complete: NotRequired[bool]


class RunRequest(TypedDict):
    project_id: str
    run_id: str


class RunIndexRequest(TypedDict):
    project_id: str
    run_id: str
    index: int


class TranslationStartRequest(TypedDict):
    project_id: str
    run_id: str
    approval_token: NotRequired[str]


class TranslationStopRequest(TypedDict):
    project_id: str
    run_id: str
    cancel_provider: NotRequired[bool]


class TranslationAcceptRequest(TypedDict):
    project_id: str
    run_id: str
    batch_id: str
    input_path: str


class TranslationDeclineRequest(TypedDict):
    project_id: str
    run_id: str
    batch_id: str
    reason: str


class TranslationReviewRequest(TypedDict):
    project_id: str
    run_id: str
    batch_id: str
    request_sha256: str


class TranslationOperationRequest(TypedDict):
    project_id: str
    action: str
    arguments: dict[str, object]


class CheckpointRequest(TypedDict):
    project_id: str
    action: Literal["checkpoint_back", "checkpoint_undo", "checkpoint_copy"]
    commit: str
    # Save a copy's folder, which a new folder for the copy goes in.
    destination: NotRequired[str]


class CheckpointChangesRequest(TypedDict):
    project_id: str
    commit: str


class StartOverRequest(TypedDict):
    project_id: str
    keep_context: bool


class TranslationAttachBatchRequest(TypedDict):
    project_id: str
    run_id: str
    index: int
    provider_job_id: str


class NoParams(TypedDict):
    pass


class Rechecked(TypedDict):
    """How many working files were checked again for outside edits."""

    checked: int


class OpenProjectRequest(TypedDict):
    source: str


class NavigateRequest(TypedDict):
    screen: Screen


class ProjectMethodRequest(TypedDict):
    project_id: str
    method: TranslationMethod


class SettingsModelDefaultsRequest(TypedDict):
    connection_id: str
    model: str


class OpenrouterHostsRequest(TypedDict):
    model: NotRequired[str]


class ConnectionRequest(TypedDict):
    revision: int
    connection_id: str


class ConnectionSaveRequest(ConnectionInput):
    revision: int


class ConnectionUsageRequest(TypedDict):
    connection_id: str


class ConnectionRemoveRequest(TypedDict):
    revision: int
    connection_id: str
    # The unfinished runs the user was shown; a different count is refused.
    unfinished: int


class GuidedPhaseSelectRequest(TypedDict):
    project_id: str
    phase: Phase


class GuidedPreviewRequest(TypedDict):
    project_id: str
    action: GuidedAction
    files: NotRequired[list[str]]
    options: NotRequired[dict[str, object]]


class TokenRequest(TypedDict):
    project_id: str
    token: str


class GuidedPositionRequest(TypedDict):
    project_id: str
    step: GuidedStep
    task: NotRequired[str]
    document: NotRequired[str]


class GuidedFormRequest(TypedDict):
    project_id: str
    value: GuidedForm


class GuidedReleaseDestinationRequest(TypedDict):
    project_id: str
    output: str
    kind: Literal["game", "patch"]


class GuidedSaveOptionsRequest(TypedDict):
    project_id: str
    revision: int
    values: GuidedOptions


class GuidedApplySpeakersRequest(TypedDict):
    project_id: str
    revision: int
    report_id: str
    reset: bool


class GuidedOptionsDraftRequest(TypedDict):
    project_id: str
    value: GuidedPreferences | None


class GuidedEventTextRequestRequest(TypedDict):
    project_id: str
    # The assistant saves its findings' recommendations as source choices.
    apply: NotRequired[bool]


class GuidedEventTextApplyRequest(TypedDict):
    project_id: str
    revision: int
    report_id: str


class GuidedEventTextViewRequest(TypedDict):
    project_id: str
    view: Literal["audit", "sources", "advanced-run", "variables"]


class GuidedEventTextPickerRequest(TypedDict):
    project_id: str
    value: EventTextPicker | None


class GuidedComparisonsReviewRequest(TypedDict):
    project_id: str
    fingerprint: str | None
    accepted: bool


class GuidedContextStatusRequest(TypedDict):
    project_id: str
    retry_layout: NotRequired[bool]


class GuidedContextReviewRequest(TypedDict):
    project_id: str
    name: str
    revision: str
    choice: Literal["empty", "review", "layout"]


class GuidedReferenceAddRequest(TypedDict):
    project_id: str
    folder: str


class GuidedReferenceRemoveRequest(TypedDict):
    project_id: str
    reference_id: str


class GuidedSkillRequest(TypedDict):
    project_id: str
    name: str


class GuidedAnswerRequest(TypedDict):
    project_id: str
    token: str
    approved: bool


class RunControlRequest(TypedDict):
    project_id: str
    run_id: NotRequired[str]


class GuidedRequestsRequest(TypedDict):
    project_id: str
    run_id: str
    group: NotRequired[str | None]
    index: NotRequired[int | None]


class GuidedPayloadRequest(RunIndexRequest):
    # Number only the queued requests, as their submission review counts them.
    prepared: NotRequired[bool]


class GuidedNameResultsRequest(TypedDict):
    project_id: str
    run_id: str
    offset: NotRequired[int]


class GuidedFilePreviewRequest(TypedDict):
    project_id: str
    name: str
    offset: NotRequired[int]
    query: NotRequired[str]
    left: NotRequired[
        Annotated[
            bool,
            "Only the Database files or Maps & events lines still left in the file.",
        ]
    ]


class GuidedBatchCancelPreviewRequest(TypedDict):
    project_id: str
    run_id: str
    batch_id: str


class GuidedDraftRequest(TypedDict):
    project_id: str
    documents: Documents


class PreferencesRequest(TypedDict):
    revision: int
    connection_id: str
    values: PreferenceValues
    model_options: dict[str, ModelOptions]


class GameUpdateDefaultsRequest(TypedDict):
    revision: int
    forge: Forge
    host: str
    owner: str
    branch: str


class ProjectGameUpdateRequest(TypedDict):
    project_id: str
    # save a repository, keep an edited file's values, replace them with
    # DazedTL's, or follow Settings again.
    action: Literal["save", "keep", "replace", "defaults"]
    repo: NotRequired[str]


METHODS: dict[str, Method] = {
    # Workspace
    "workspace_snapshot": Method(
        NoParams, WorkspaceSnapshot, refresh=False, during_close=True
    ),
    # Rechecks outside edits when the window regains focus.
    "workspace_recheck": Method(ProjectRequest, Rechecked),
    # Abandons a copied assistant task; its saved results stay.
    "assistant_task_dismiss": Method(AssistantTaskRequest, AssistantTaskDismissed),
    "open_project": Method(OpenProjectRequest, AppState),
    "select_project": Method(ProjectRequest, AppState),
    # Find game folder: the project continues with its game where it is now.
    "locate_project": Method(LocateProjectRequest, AppState),
    # Takes a game off the recent list; its saved work stays.
    "remove_project": Method(ProjectRequest, AppState),
    "navigate": Method(NavigateRequest, AppState),
    "project_method": Method(ProjectMethodRequest, AppState),
    # Settings
    "settings_get": Method(NoParams, Settings, refresh=False),
    "settings_save": Method(PreferencesRequest, Settings),
    "settings_draft": Method(
        PreferencesRequest, Saved, refresh=False, during_close=True
    ),
    "settings_revert": Method(ConnectionRequest, Settings, refresh=False),
    # GameUpdate's defaults; the open game's config follows them.
    "settings_game_update": Method(GameUpdateDefaultsRequest, Settings),
    "connection_save": Method(ConnectionSaveRequest, Settings, during_close=True),
    "connection_select": Method(ConnectionRequest, Settings),
    "connection_check": Method(ConnectionRequest, Settings),
    "connection_usage": Method(ConnectionUsageRequest, ConnectionUsage, refresh=False),
    "connection_remove": Method(ConnectionRemoveRequest, Settings),
    "settings_model_defaults": Method(
        SettingsModelDefaultsRequest, ModelDefaults, refresh=False
    ),
    "openrouter_hosts": Method(
        OpenrouterHostsRequest, list[OpenRouterHost], refresh=False
    ),
    # Guided workflow
    "guided_phase_select": Method(GuidedPhaseSelectRequest, GuidedState),
    "guided_preview": Method(GuidedPreviewRequest, Preview, refresh=False),
    "guided_execute": Method(TokenRequest, Job),
    "guided_answer": Method(GuidedAnswerRequest, Job),
    "guided_stop": Method(RunControlRequest, Job),
    "guided_resume": Method(RunControlRequest, Job),
    "guided_draft": Method(GuidedDraftRequest, Saved, during_close=True),
    "guided_save_documents": Method(SaveDocumentsRequest, Documents),
    "guided_position": Method(GuidedPositionRequest, Saved),
    "guided_options_draft": Method(GuidedOptionsDraftRequest, Saved, during_close=True),
    "guided_save_options": Method(GuidedSaveOptionsRequest, GuidedPreferences),
    "guided_skill": Method(GuidedSkillRequest, SkillText),
    "guided_apply_speakers": Method(GuidedApplySpeakersRequest, GuidedPreferences),
    "translation_speakers": Method(TranslationSpeakersRequest, SpeakerScan),
    "guided_inspect": Method(RunRequest, Job, refresh=False),
    "guided_payload": Method(GuidedPayloadRequest, RunPayload, refresh=False),
    "guided_requests": Method(GuidedRequestsRequest, RequestPage, refresh=False),
    "guided_name_results": Method(
        GuidedNameResultsRequest, NameTranslationPage, refresh=False
    ),
    "guided_file_preview": Method(
        GuidedFilePreviewRequest, FileTextPreview, refresh=False
    ),
    "guided_discard_preparation": Method(RunRequest, PreparationDiscarded),
    "guided_settle_empty_estimate": Method(RunRequest, SettledEstimate),
    # Context's Cost estimate: every Translate task over all its files.
    "guided_full_estimate": Method(ProjectRequest, Job),
    "guided_provider_details": Method(RunRequest, ProviderDetails, refresh=False),
    "guided_batch_cancel_preview": Method(
        GuidedBatchCancelPreviewRequest, BatchCancellation, refresh=False
    ),
    "guided_batch_cancel": Method(TokenRequest, BatchCancelRequested),
    "guided_batch_collect": Method(RunRequest, Job),
    "guided_form": Method(GuidedFormRequest, Saved, during_close=True),
    "guided_context_status": Method(GuidedContextStatusRequest, ContextSetup),
    "guided_context_review": Method(GuidedContextReviewRequest, Saved),
    "guided_reference_add": Method(GuidedReferenceAddRequest, list[ReferenceFolder]),
    "guided_reference_remove": Method(
        GuidedReferenceRemoveRequest, list[ReferenceFolder]
    ),
    "guided_event_text_request": Method(
        GuidedEventTextRequestRequest, EventTextRequest, refresh=False
    ),
    "guided_event_text_apply": Method(GuidedEventTextApplyRequest, GuidedPreferences),
    "guided_event_text_view": Method(GuidedEventTextViewRequest, Saved),
    "guided_event_text_picker": Method(
        GuidedEventTextPickerRequest, Saved, during_close=True
    ),
    "guided_comparisons_review": Method(GuidedComparisonsReviewRequest, Saved),
    "guided_output_folder": Method(ProjectRequest, OutputFolder, refresh=False),
    "guided_release_destination": Method(
        GuidedReleaseDestinationRequest, ReleaseDestination, refresh=False
    ),
    # Len's method
    "translation_state": Method(ProjectRequest, TranslationState, refresh=False),
    "translation_save": Method(TranslationSaveRequest, ProjectOptions),
    "translation_draft": Method(TranslationDraftRequest, Saved, during_close=True),
    "translation_documents": Method(ProjectRequest, Documents, refresh=False),
    "translation_save_document": Method(SaveDocumentRequest, Documents),
    "translation_prepare": Method(ProjectRequest, PreparedHandoff),
    "translation_compile": Method(InputPathRequest, TranslationJob),
    "translation_organize": Method(TranslationOrganizeRequest, TranslationJob),
    "translation_run": Method(RunRequest, TranslationJob, refresh=False),
    "translation_request": Method(RunIndexRequest, RequestPreview, refresh=False),
    "translation_requests": Method(RunRequest, list[RunRequestState], refresh=False),
    "translation_results": Method(RunRequest, TranslationResults, refresh=False),
    "translation_backups": Method(ProjectRequest, BackupCatalog, refresh=False),
    # The assistant's task for the text an applied update brought in.
    "translation_update_task": Method(ProjectRequest, UpdateTask, refresh=False),
    # How a new official release's folder lines up with the game, before staging.
    "translation_release": Method(
        TranslationReleaseRequest, ReleaseInspection, refresh=False
    ),
    "translation_start": Method(TranslationStartRequest, TranslationJob),
    "translation_stop": Method(TranslationStopRequest, TranslationJob),
    "translation_accept": Method(TranslationAcceptRequest, TranslationJob),
    "translation_decline": Method(TranslationDeclineRequest, TranslationJob),
    "translation_finish": Method(RunRequest, TranslationJob),
    # A waiting estimate priced again or prepared again with current settings.
    "translation_reestimate": Method(RunRequest, TranslationJob),
    "translation_translator_prompt": Method(RunRequest, PreparedHandoff, refresh=False),
    "translation_review": Method(TranslationReviewRequest, Saved),
    "translation_progress": Method(InputPathRequest, TranslationProgress),
    "translation_operation": Method(TranslationOperationRequest, TranslationJob),
    "project_start_over": Method(StartOverRequest, TranslationJob),
    # The Checkpoints tab: its timeline, one checkpoint's changes, and go
    # back, undo and save a copy, which only the user starts.
    "project_checkpoints": Method(ProjectRequest, CheckpointTimeline, refresh=False),
    "project_checkpoint_changes": Method(
        CheckpointChangesRequest, CheckpointChanges, refresh=False
    ),
    "project_checkpoint": Method(CheckpointRequest, TranslationJob),
    # The game's GameUpdate repository and config; the user's choice only.
    "project_game_update": Method(ProjectGameUpdateRequest, GameUpdateStatus),
    "translation_attach_batch": Method(TranslationAttachBatchRequest, TranslationJob),
    "translation_resolve_uncertain": Method(
        TranslationResolveUncertainRequest, TranslationJob
    ),
    "translation_identify": Method(TranslationIdentifyRequest, Saved),
    "translation_images": Method(TranslationImagesRequest, ImageAssistantStepResult),
    "translation_qa": Method(TranslationQaRequest, TextQaStatus),
    "guided_qa_report": Method(ProjectRequest, QaReport, refresh=False),
    "translation_playtest": Method(TranslationPlaytestRequest, PlaytestStatus),
    "guided_playtest_capture": Method(
        PlaytestCaptureRequest, PlaytestCapture, refresh=False
    ),
    "translation_legacy": Method(TranslationLegacyRequest, Job | ExportedFiles),
    # Images
    "images_state": Method(ProjectRequest, ImageManagerState, refresh=False),
    "images_list": Method(ImagesListRequest, ImageList, refresh=False),
    "images_preview": Method(ImagesPreviewRequest, ImagePixels, refresh=False),
    "images_update": Method(ImagesUpdateRequest, ImageManagerState, during_close=True),
    "images_action": Method(ActionRequest, ImageActionResult),
    "images_adopt": Method(ForeignWorkRequest, ImageActionResult),
    "images_start_over": Method(ForeignWorkRequest, ImageActionResult),
    "images_editor_state": Method(
        ImagesEditorStateRequest, ImageEditorState, refresh=False
    ),
    "images_editor_save": Method(
        ImagesEditorSaveRequest, ImageEditorState, during_close=True
    ),
    "images_editor_action": Method(ImagesEditorActionRequest, ImageEditorActionResult),
    "images_editor_translation_state": Method(
        ProjectRequest, ImageNativeTranslationState, refresh=False
    ),
    "images_editor_translation_preview": Method(
        ImagesEditorTranslationPreviewRequest,
        ImageNativeTranslationPreview,
        refresh=False,
    ),
    "images_editor_translation_start": Method(
        ImagesEditorTranslationStartRequest, ImageNativeTranslationState
    ),
    "images_editor_translation_action": Method(
        ImagesEditorTranslationActionRequest, ImageNativeTranslationActionResult
    ),
    # Plugins
    "plugins_state": Method(ProjectRequest, PluginState, refresh=False),
    "plugins_capture": Method(PluginsCaptureRequest, PluginCapture, refresh=False),
    "plugins_action": Method(ActionRequest, PluginActionResult),
    "plugins_continue": Method(PluginsContinueRequest, PluginActionResult),
    "plugins_task": Method(ProjectRequest, PluginActionResult),
    "plugins_apply": Method(ProjectRequest, PluginActionResult),
    "plugins_adopt": Method(ForeignWorkRequest, PluginActionResult),
    "plugins_start_over": Method(ForeignWorkRequest, PluginActionResult),
}
