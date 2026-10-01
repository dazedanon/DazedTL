export type Screen = "overview" | "translation" | "settings";
export interface Project {
  id: string;
  name: string;
  source: string;
  engine: string;
  engine_label?: string;
  method: "guided" | "len" | "translation";
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
  observing: boolean;
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
  translation: TranslationState | null;
  translationError: string;
}

export interface TranslationOptions {
  mode: "agent" | "live" | "batch";
  instructions: string;
  include_images: boolean;
  include_glossary_base: boolean;
  install_forge: boolean;
}
export interface ProjectOptions {
  options: TranslationOptions;
  revision: string;
  initialized: boolean;
}
export interface TranslationQuote {
  requests: number;
  units: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  live_cost: number;
  batch_cost: number | null;
  model: string;
  provider: string;
  basis: string;
  rates: {
    input: number;
    output: number;
    source: string;
    batch_factor: number | null;
  };
}
export interface TranslationJob {
  id: string;
  project_id: string;
  kind: "translation" | "operation";
  label: string;
  status: string;
  message: string;
  created: string;
  updated: string;
  mode?: "agent" | "live" | "batch";
  quote: TranslationQuote | null;
  approval_token: string;
  approved: boolean;
  result: Record<string, unknown> | null;
  usage: Record<string, number>;
  counts: Record<string, number>;
  units: number;
  accepted_units: number;
  requests: number;
  stop_requested: boolean;
  cancel_requested: boolean;
  batches: {
    id: string;
    state: string;
    api_status?: string;
    counts?: Record<string, number>;
  }[];
  issues: { id: string; state: string; message: string }[];
  qa_requests?: { id: string; index: number; notes: number }[];
}
export interface TranslationProgress {
  updated_at: string | null;
  phase: string | null;
  phases: Record<string, string>;
  metrics: Record<
    "text" | "images",
    {
      total: number | null;
      discovered?: number;
      translated: number;
      reviewed: number;
    }
  >;
  warnings?: string[];
  blocker: string;
  next_action: string;
}
export interface TranslationState extends ProjectOptions {
  engine: string;
  legacyRun: Job | null;
  projectId: string;
  drafts: {
    options: Pick<ProjectOptions, "options" | "revision"> | null;
    documents: Documents;
  };
  documents: Documents;
  progress: TranslationProgress | null;
  git: {
    configured: boolean;
    original_exists: boolean;
    translation_exists: boolean;
    original_version: string | null;
    translation_version: string | null;
    original_commit: string | null;
    translation_commit: string | null;
    translation_branch: string | null;
    current_branch: string | null;
    worktree_clean: boolean;
    pending_operations: string[];
    asset_sync_pending: boolean;
  } | null;
  lifecycle: {
    source_backup?: BackupRecord;
    prepared_source?: BackupRecord;
    workspace_backup?: BackupRecord;
    checkpoint?: { commit: string; manifest: string };
    delivery?: {
      path: string;
      commit: string;
      game_version: string;
      updater_stamp: boolean;
    };
  };
  jobs: TranslationJob[];
  active: boolean;
  warnings: string[];
  statusText: string;
  handoff: string;
  providerEnabled: boolean;
  connection: { name: string; model: string } | null;
  legacyAvailable: boolean;
}
export interface BackupRecord {
  id: string;
  path: string;
  files: number;
  bytes_total?: number;
  bytes_added?: number;
  bytes_reused?: number;
  reused_snapshot?: boolean;
}
export interface BackupCatalog {
  snapshots: {
    id: string;
    kind: "source" | "workspace";
    created: string;
    files: number;
    version: number;
    bytes_total: number | null;
  }[];
  warnings: string[];
}
export interface RequestPreview {
  run_id: string;
  index: number;
  total: number;
  request: {
    id: string;
    sources: Record<string, string>;
    fingerprint: string;
    constraints: Record<string, unknown>;
    context: Record<string, unknown> & {
      line_kinds?: Record<string, "dialogue" | "narration" | "ui" | "unknown">;
      speakers?: Record<string, string | null>;
      qa_notes?: Record<string, string>;
    };
    params?: Record<string, unknown>;
  };
  result: {
    translations: Record<string, string>;
    result_sha256: string;
    reviewed?: Record<string, string>;
  } | null;
}

export interface Preview {
  token: string;
  label: string;
  destination: string;
  files: number;
  options: { files: string[] };
}
export interface PreferenceValues {
  language: string;
  model: string;
}
export interface ModelOptions {
  entriesPerRequest: number | "" | null;
  pricing: "automatic" | "custom";
  inputRate: number | "" | null;
  outputRate: number | "" | null;
}
export interface ModelDefaults {
  model: string;
  inputRate: number | null;
  outputRate: number | null;
  source: "catalog" | "engine_default" | "unavailable";
  updatedAt: string | null;
  stale: boolean;
}
export interface Settings {
  revision: number;
  values: PreferenceValues;
  modelOptions: Record<string, ModelOptions>;
  defaultEntriesPerRequest: number;
  activeConnectionId: string;
  connections: Connection[];
  providers: { id: Provider; label: string; defaultEndpoint: string }[];
  checksEnabled: boolean;
  draft?: {
    values: PreferenceValues;
    modelOptions: Record<string, ModelOptions>;
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
  "revision" | "values" | "modelOptions" | "activeConnectionId"
>;
interface PreferencesRequest {
  revision: number;
  connection_id: string;
  values: Settings["values"];
  model_options: Settings["modelOptions"];
}
export interface Saved {
  saved: boolean;
}
export interface ExportedFiles {
  path: string;
  files: number;
}
export interface RpcContract {
  translation_identify: {
    request: { project_id: string; engine: string; evidence_file: string };
    response: Saved;
  };
  translation_legacy: {
    request: {
      project_id: string;
      action: "resume" | "stop" | "answer" | "export";
      token?: string;
      approved?: boolean;
    };
    response: Job | ExportedFiles;
  };

  translation_resolve_uncertain: {
    request: {
      project_id: string;
      run_id: string;
      batch_id: string;
      request_sha256: string;
      retry_reviewed: boolean;
    };
    response: TranslationJob;
  };

  translation_state: {
    request: { project_id: string };
    response: TranslationState;
  };
  translation_save: {
    request: {
      project_id: string;
      revision: string;
      values: TranslationOptions;
    };
    response: ProjectOptions;
  };
  translation_draft: {
    request: {
      project_id: string;
      section: "options" | "documents";
      value: unknown;
    };
    response: Saved;
  };
  translation_documents: {
    request: { project_id: string };
    response: Documents;
  };
  translation_save_document: {
    request: {
      project_id: string;
      name: string;
      revision: string;
      text: string;
    };
    response: Documents;
  };
  translation_prepare: {
    request: { project_id: string };
    response: { handoff: string; path: string };
  };
  translation_compile: {
    request: { project_id: string; input_path: string };
    response: TranslationJob;
  };
  translation_run: {
    request: { project_id: string; run_id: string };
    response: TranslationJob;
  };
  translation_request: {
    request: { project_id: string; run_id: string; index: number };
    response: RequestPreview;
  };
  translation_backups: {
    request: { project_id: string };
    response: BackupCatalog;
  };
  translation_start: {
    request: { project_id: string; run_id: string; approval_token?: string };
    response: TranslationJob;
  };
  translation_stop: {
    request: { project_id: string; run_id: string; cancel_provider?: boolean };
    response: TranslationJob;
  };
  translation_accept: {
    request: {
      project_id: string;
      run_id: string;
      batch_id: string;
      input_path: string;
    };
    response: TranslationJob;
  };
  translation_review: {
    request: {
      project_id: string;
      run_id: string;
      batch_id: string;
      request_sha256: string;
    };
    response: Saved;
  };
  translation_progress: {
    request: { project_id: string; input_path: string };
    response: TranslationProgress;
  };
  translation_operation: {
    request: {
      project_id: string;
      action: string;
      arguments: Record<string, unknown>;
    };
    response: TranslationJob;
  };
  translation_attach_batch: {
    request: {
      project_id: string;
      run_id: string;
      index: number;
      provider_job_id: string;
    };
    response: TranslationJob;
  };

  workspace_snapshot: {
    request: Record<string, never>;
    response: WorkspaceSnapshot;
  };
  open_project: {
    request: { source: string };
    response: AppState;
  };
  select_project: { request: { project_id: string }; response: AppState };
  navigate: { request: { screen: Screen }; response: AppState };
  settings_get: { request: Record<string, never>; response: Settings };
  settings_save: { request: PreferencesRequest; response: Settings };
  settings_model_defaults: {
    request: { connection_id: string; model: string };
    response: ModelDefaults;
  };
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
