import { request } from "./transport";
import { imagesApi } from "./images";
import type {
  AssistantTaskKind,
  ImageEditorSave,
  Screen,
  TranslationMethod,
  Phase,
  GuidedOptions,
  GuidedPreferences,
  GuidedStep,
  GuidedForm,
  Documents,
  SettingsPayload,
  ConnectionInput,
  TranslationOptions,
} from "./contracts";

export const api = {
  images: {
    ...imagesApi,
    editorState: (project_id: string, asset_ids: string[] = []) =>
      request("images_editor_state", { project_id, asset_ids }),
    editorSave: (
      project_id: string,
      revision: string,
      images: ImageEditorSave[],
      asset_ids: string[] = [],
    ) =>
      request("images_editor_save", {
        project_id,
        revision,
        images,
        asset_ids,
      }),
    editorAction: (
      project_id: string,
      revision: string,
      action: string,
      asset_ids: string[],
      args: Record<string, unknown> = {},
    ) =>
      request("images_editor_action", {
        project_id,
        revision,
        action,
        asset_ids,
        arguments: args,
      }),
    editorTranslationState: (project_id: string) =>
      request("images_editor_translation_state", { project_id }),
    editorTranslationPreview: (
      project_id: string,
      mode: "estimate" | "translate" | "batch",
    ) => request("images_editor_translation_preview", { project_id, mode }),
    editorTranslationStart: (
      project_id: string,
      token: string,
      approved = false,
    ) =>
      request("images_editor_translation_start", {
        project_id,
        token,
        approved,
      }),
    editorTranslationAction: (
      project_id: string,
      run_id: string,
      action: string,
      args: Record<string, unknown> = {},
    ) =>
      request("images_editor_translation_action", {
        project_id,
        run_id,
        action,
        arguments: args,
      }),
  },
  translation: {
    speakers: (project_id: string, scan = false) =>
      request("translation_speakers", { project_id, scan }),
    resolve: (
      project_id: string,
      run_id: string,
      batch_id: string,
      request_sha256: string,
    ) =>
      request("translation_resolve_uncertain", {
        project_id,
        run_id,
        batch_id,
        request_sha256,
        retry_reviewed: true,
      }),
    save: (project_id: string, revision: string, values: TranslationOptions) =>
      request("translation_save", { project_id, revision, values }),
    draft: (
      project_id: string,
      section: "options" | "documents",
      value: unknown,
    ) => request("translation_draft", { project_id, section, value }),
    document: (
      project_id: string,
      name: string,
      revision: string,
      text: string,
    ) =>
      request("translation_save_document", {
        project_id,
        name,
        revision,
        text,
      }),
    prepare: (project_id: string) =>
      request("translation_prepare", { project_id }),

    backups: (project_id: string) =>
      request("translation_backups", { project_id }),
    compile: (project_id: string, input_path: string) =>
      request("translation_compile", { project_id, input_path }),
    request: (project_id: string, run_id: string, index: number) =>
      request("translation_request", { project_id, run_id, index }),
    start: (project_id: string, run_id: string, approval_token = "") =>
      request("translation_start", { project_id, run_id, approval_token }),
    stop: (project_id: string, run_id: string, cancel_provider = false) =>
      request("translation_stop", { project_id, run_id, cancel_provider }),
    accept: (
      project_id: string,
      run_id: string,
      batch_id: string,
      input_path: string,
    ) =>
      request("translation_accept", {
        project_id,
        run_id,
        batch_id,
        input_path,
      }),
    finish: (project_id: string, run_id: string) =>
      request("translation_finish", { project_id, run_id }),
    translatorPrompt: (project_id: string, run_id: string) =>
      request("translation_translator_prompt", { project_id, run_id }),
    review: (
      project_id: string,
      run_id: string,
      batch_id: string,
      request_sha256: string,
    ) =>
      request("translation_review", {
        project_id,
        run_id,
        batch_id,
        request_sha256,
      }),
    operation: (
      project_id: string,
      action: string,
      args: Record<string, unknown> = {},
    ) =>
      request("translation_operation", { project_id, action, arguments: args }),
    startOver: (project_id: string, keep_context: boolean) =>
      request("project_start_over", { project_id, keep_context }),
    attach: (
      project_id: string,
      run_id: string,
      index: number,
      provider_job_id: string,
    ) =>
      request("translation_attach_batch", {
        project_id,
        run_id,
        index,
        provider_job_id,
      }),
  },

  snapshot: () => request("workspace_snapshot", {}),
  recheck: (project_id: string) => request("workspace_recheck", { project_id }),
  dismissAssistantTask: (project_id: string, kind: AssistantTaskKind) =>
    request("assistant_task_dismiss", { project_id, kind }),
  open: (source: string) => request("open_project", { source }),
  select: (project_id: string) => request("select_project", { project_id }),
  navigate: (screen: Screen) => request("navigate", { screen }),
  method: (project_id: string, method: TranslationMethod) =>
    request("project_method", { project_id, method }),
  phase: (project_id: string, phase: Phase) =>
    request("guided_phase_select", { project_id, phase }),
  preview: (
    project_id: string,
    action: string,
    files?: string[],
    options?: Record<string, unknown>,
  ) => request("guided_preview", { project_id, action, files, options }),
  execute: (project_id: string, token: string) =>
    request("guided_execute", { project_id, token }),
  guided: {
    outputFolder: (project_id: string) =>
      request("guided_output_folder", { project_id }),
    releaseDestination: (project_id: string, output: string) =>
      request("guided_release_destination", { project_id, output }),
    eventTextApply: (project_id: string, revision: number, report_id: string) =>
      request("guided_event_text_apply", { project_id, revision, report_id }),
    eventTextView: (
      project_id: string,
      view: import("./contracts").EventTextState["view"],
    ) => request("guided_event_text_view", { project_id, view }),
    eventTextPicker: (
      project_id: string,
      value: import("./contracts").EventTextState["picker"],
    ) => request("guided_event_text_picker", { project_id, value }),
    comparisonsReview: (
      project_id: string,
      fingerprint: string | null,
      accepted: boolean,
    ) =>
      request("guided_comparisons_review", {
        project_id,
        fingerprint,
        accepted,
      }),
    applySpeakers: (
      project_id: string,
      revision: number,
      report_id: string,
      reset = false,
    ) =>
      request("guided_apply_speakers", {
        project_id,
        revision,
        report_id,
        reset,
      }),
    inspect: (project_id: string, run_id: string) =>
      request("guided_inspect", { project_id, run_id }),
    payload: (project_id: string, run_id: string, index: number) =>
      request("guided_payload", { project_id, run_id, index }),
    nameResults: (project_id: string, run_id: string, offset = 0) =>
      request("guided_name_results", { project_id, run_id, offset }),
    filePreview: (project_id: string, name: string, offset = 0, query = "") =>
      request("guided_file_preview", { project_id, name, offset, query }),
    discardPreparation: (project_id: string, run_id: string) =>
      request("guided_discard_preparation", { project_id, run_id }),
    settleEmptyEstimate: (project_id: string, run_id: string) =>
      request("guided_settle_empty_estimate", { project_id, run_id }),
    batchCancelPreview: (
      project_id: string,
      run_id: string,
      batch_id: string,
    ) =>
      request("guided_batch_cancel_preview", { project_id, run_id, batch_id }),
    batchCancel: (project_id: string, token: string) =>
      request("guided_batch_cancel", { project_id, token }),
    batchCollect: (project_id: string, run_id: string) =>
      request("guided_batch_collect", { project_id, run_id }),
    form: (project_id: string, value: GuidedForm) =>
      request("guided_form", { project_id, value }),
    position: (
      project_id: string,
      step: GuidedStep,
      task?: string,
      document?: string,
    ) => request("guided_position", { project_id, step, task, document }),
    draft: (project_id: string, value: GuidedPreferences | null) =>
      request("guided_options_draft", { project_id, value }),
    save: (project_id: string, revision: number, values: GuidedOptions) =>
      request("guided_save_options", { project_id, revision, values }),
    context: (project_id: string, retry_layout = false) =>
      request("guided_context_status", { project_id, retry_layout }),
    referenceAdd: (project_id: string, folder: string) =>
      request("guided_reference_add", { project_id, folder }),
    referenceRemove: (project_id: string, reference_id: string) =>
      request("guided_reference_remove", { project_id, reference_id }),
    reviewContext: (
      project_id: string,
      name: string,
      revision: string,
      choice: "empty" | "review" | "layout",
    ) =>
      request("guided_context_review", { project_id, name, revision, choice }),
    skill: (project_id: string, name: string) =>
      request("guided_skill", { project_id, name }),
  },
  answer: (project_id: string, token: string, approved: boolean) =>
    request("guided_answer", { project_id, token, approved }),
  stop: (project_id: string, run_id?: string) =>
    request("guided_stop", { project_id, ...(run_id ? { run_id } : {}) }),
  resume: (project_id: string, run_id?: string) =>
    request("guided_resume", { project_id, ...(run_id ? { run_id } : {}) }),
  draft: (project_id: string, documents: Documents) =>
    request("guided_draft", { project_id, documents }),
  saveDocument: (
    project_id: string,
    name: string,
    revision: string,
    text: string,
  ) => request("guided_save_document", { project_id, name, revision, text }),
  settings: () => request("settings_get", {}),
  modelDefaults: (connection_id: string, model: string) =>
    request("settings_model_defaults", { connection_id, model }),
  revertSettings: ({ revision, activeConnectionId }: SettingsPayload) =>
    request("settings_revert", { revision, connection_id: activeConnectionId }),
  saveSettings: ({
    revision,
    values,
    modelOptions,
    activeConnectionId,
  }: SettingsPayload) =>
    request("settings_save", {
      revision,
      values,
      model_options: modelOptions,
      connection_id: activeConnectionId,
    }),
  settingsDraft: ({
    revision,
    values,
    modelOptions,
    activeConnectionId,
  }: SettingsPayload) =>
    request("settings_draft", {
      revision,
      values,
      model_options: modelOptions,
      connection_id: activeConnectionId,
    }),
  saveConnection: (revision: number, input: ConnectionInput) =>
    request("connection_save", { revision, ...input }),
  selectConnection: (revision: number, connection_id: string) =>
    request("connection_select", { revision, connection_id }),
  checkConnection: (revision: number, connection_id: string) =>
    request("connection_check", { revision, connection_id }),
  connectionUsage: (connection_id: string) =>
    request("connection_usage", { connection_id }),
  removeConnection: (
    revision: number,
    connection_id: string,
    unfinished: number,
  ) => request("connection_remove", { revision, connection_id, unfinished }),
  openrouterHosts: (model: string) => request("openrouter_hosts", { model }),
};
