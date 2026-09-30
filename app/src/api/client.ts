import { request } from "./transport";
import type {
  Screen,
  Phase,
  RunMode,
  Documents,
  SettingsPayload,
  ConnectionInput,
} from "./contracts";

export const api = {
  snapshot: () => request("workspace_snapshot", {}),
  open: (source: string) =>
    request("open_project", { source, method: "guided" }),
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
  revertSettings: ({ revision, activeConnectionId }: SettingsPayload) =>
    request("settings_revert", { revision, connection_id: activeConnectionId }),
  saveSettings: ({
    revision,
    values,
    engines,
    activeConnectionId,
  }: SettingsPayload) =>
    request("settings_save", {
      revision,
      values,
      engines,
      connection_id: activeConnectionId,
    }),
  settingsDraft: ({
    revision,
    values,
    engines,
    activeConnectionId,
  }: SettingsPayload) =>
    request("settings_draft", {
      revision,
      values,
      engines,
      connection_id: activeConnectionId,
    }),
  saveConnection: (revision: number, input: ConnectionInput) =>
    request("connection_save", { revision, ...input }),
  selectConnection: (revision: number, connection_id: string) =>
    request("connection_select", { revision, connection_id }),
  checkConnection: (revision: number, connection_id: string) =>
    request("connection_check", { revision, connection_id }),
};
