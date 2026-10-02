import { request } from "./transport";
import type {
  Screen,
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
  translation: {
    speakers: (project_id: string, scan = false) => request("translation_speakers", { project_id, scan }),
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
  open: (source: string) => request("open_project", { source }),
  select: (project_id: string) => request("select_project", { project_id }),
  navigate: (screen: Screen) => request("navigate", { screen }),
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
    applySpeakers: (project_id: string, revision: number, report_id: string, reset = false) => request("guided_apply_speakers", { project_id, revision, report_id, reset }),
    inspect: (project_id: string, run_id: string) => request("guided_inspect", { project_id, run_id }),
    form: (project_id: string, value: GuidedForm) => request("guided_form", { project_id, value }),
    position: (project_id: string, step: GuidedStep, task?: string) => request("guided_position", { project_id, step, task }),
    draft: (project_id: string, value: GuidedPreferences | null) => request("guided_options_draft", { project_id, value }),
    save: (project_id: string, revision: number, values: GuidedOptions) => request("guided_save_options", { project_id, revision, values }),
    context: (project_id: string) => request("guided_context_status", { project_id }),
    reviewContext: (project_id: string, name: string, revision: string, choice: "empty" | "review" | "layout") => request("guided_context_review", { project_id, name, revision, choice }),
    skill: (project_id: string, name: string) => request("guided_skill", { project_id, name }),
  },
  answer: (project_id: string, token: string, approved: boolean) =>
    request("guided_answer", { project_id, token, approved }),
  stop: (project_id: string) => request("guided_stop", { project_id }),
  resume: (project_id: string) => request("guided_resume", { project_id }),
  export: (project_id: string, run_id?: string) => request("guided_export", { project_id, run_id }),
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
};
