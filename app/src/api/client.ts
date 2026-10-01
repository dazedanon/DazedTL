import { request } from "./transport";
import type {
  Screen,
  Phase,
  RunMode,
  Documents,
  SettingsPayload,
  ConnectionInput,
  TranslationOptions,
} from "./contracts";

export const api = {
  translation: {
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
    action: "import" | "export_selected",
    files?: string[],
  ) => request("guided_preview", { project_id, action, files }),
  execute: (project_id: string, token: string) =>
    request("guided_execute", { project_id, token }),
  start: (project_id: string, mode: RunMode) =>
    request("guided_start", { project_id, mode }),
  answer: (project_id: string, token: string, approved: boolean) =>
    request("guided_answer", { project_id, token, approved }),
  stop: (project_id: string) => request("guided_stop", { project_id }),
  resume: (project_id: string) => request("guided_resume", { project_id }),
  export: (project_id: string) => request("guided_export", { project_id }),
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
