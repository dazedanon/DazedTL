export type Screen = "overview" | "guided" | "settings";
export interface Project {
  id: string;
  name: string;
  source: string;
  engine: string;
  method: "guided" | "len";
  phase: string;
  available?: boolean;
  status?: string;
  detail?: string;
  next_label?: string;
  attention?: string[];
}
export interface AppState {
  project: Project | null;
  recent: Project[];
  screen: Screen;
  running: boolean;
  provider_ready: boolean;
}
export type Documents = Record<
  string,
  { text: string; revision: string; path?: string }
>;
export interface Job {
  id: string;
  status: string;
  message: string;
  label?: string;
  mode?: string;
  phase?: string;
  model?: string;
  files?: string[];
  progress?: { current: number; total: number; file: string };
  log: string[];
  estimate?: Record<string, number>;
  outputs?: Record<string, string>;
  approval?: {
    token: string;
    kind: "batch" | "speakers";
    detail: Record<string, unknown>;
  };
}
export type Phase = "database" | "dialogue";
export type RunMode = "estimate" | "translate" | "batch";
export interface GuidedState {
  projectId: string;
  source: string;
  files: { name: string; default?: boolean; size?: number }[];
  selection: string[];
  importedFiles: string[];
  collectionError: string;
  operations: Job[];
  run: Job | null;
  activeJobId: string | null;
  phase: Phase;
  phaseFiles: string[];
  documents: Documents;
  drafts: Documents;
  provider: {
    model: string;
    defaultMode: RunMode;
    batchSupported: boolean;
    ready: boolean;
    enabled: boolean;
  };
}
export interface WorkspaceSnapshot {
  application: AppState;
  guided: GuidedState | null;
}
export interface Preview {
  token: string;
  label: string;
  destination: string;
  files: number;
  options: { files: string[] };
}
export type Value = string | number | boolean | string[];
export interface SettingField {
  key: string;
  type: string;
  label: string;
  min?: number;
  max?: number;
  choices?: string[];
  help?: string;
}
export interface Settings {
  fields: SettingField[];
  revision: number;
  values: Record<string, Value>;
  engines: Record<string, Record<string, Value>>;
  activeConnectionId: string;
  connections: Connection[];
  providers: { id: Provider; label: string; defaultEndpoint: string }[];
  checksEnabled: boolean;
  draft?: {
    revision: number;
    values: Record<string, Value>;
    engines: Record<string, Record<string, Value>>;
  };
}

export type Provider = "openai" | "anthropic" | "gemini" | "mistral" | "custom";
export type ProviderProtocol = Exclude<Provider, "custom">;
export interface Connection {
  id: string;
  name: string;
  provider: Provider | null;
  protocol: ProviderProtocol;
  endpoint: string;
  organization: string;
  keyless: boolean;
  has_secret: boolean;
  needsSetup: boolean;
  model: string;
  models: string[];
  check: {
    status:
      | "not_checked"
      | "verified"
      | "reachable"
      | "failed"
      | "unavailable"
      | "unsupported";
    message: string;
    checkedAt: string | null;
  };
}
export interface ConnectionInput {
  connection_id?: string;
  provider: Provider;
  protocol: ProviderProtocol;
  name: string;
  secret: string;
  endpoint: string;
  organization: string;
  keyless: boolean;
  reuse_secret: boolean;
}
export type SettingsPayload = Pick<
  Settings,
  "revision" | "values" | "engines" | "activeConnectionId"
>;
interface PreferencesRequest {
  revision: number;
  connection_id: string;
  values: Settings["values"];
  engines: Settings["engines"];
}
export interface Saved {
  saved: boolean;
}
export interface ExportedFiles {
  path: string;
  files: number;
}
export interface RpcContract {
  workspace_snapshot: {
    request: Record<string, never>;
    response: WorkspaceSnapshot;
  };
  open_project: {
    request: { source: string; method: "guided" };
    response: AppState;
  };
  select_project: { request: { project_id: string }; response: AppState };
  navigate: { request: { screen: Screen }; response: AppState };
  settings_get: { request: Record<string, never>; response: Settings };
  settings_save: { request: PreferencesRequest; response: Settings };
  settings_draft: { request: PreferencesRequest; response: Saved };
  settings_revert: {
    request: { revision: number; connection_id: string };
    response: Settings;
  };
  connection_save: {
    request: ConnectionInput & { revision: number };
    response: Settings;
  };
  connection_select: {
    request: { revision: number; connection_id: string };
    response: Settings;
  };
  connection_check: {
    request: { revision: number; connection_id: string };
    response: Settings;
  };
  guided_phase_select: {
    request: { project_id: string; phase: Phase };
    response: GuidedState;
  };
  guided_preview: {
    request: {
      project_id: string;
      action: "import" | "export_selected";
      files?: string[];
    };
    response: Preview;
  };
  guided_execute: {
    request: { project_id: string; token: string };
    response: Job;
  };
  guided_start: {
    request: { project_id: string; mode: RunMode };
    response: Job;
  };
  guided_answer: {
    request: { project_id: string; token: string; approved: boolean };
    response: Job;
  };
  guided_stop: { request: { project_id: string }; response: Job };
  guided_resume: { request: { project_id: string }; response: Job };
  guided_export: { request: { project_id: string }; response: ExportedFiles };
  guided_draft: {
    request: { project_id: string; documents: Documents };
    response: Saved;
  };
  guided_save_document: {
    request: {
      project_id: string;
      name: string;
      revision: string;
      text: string;
    };
    response: Documents;
  };
}
