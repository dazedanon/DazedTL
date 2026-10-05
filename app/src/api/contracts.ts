import type { ImageActionResult, ImageDraft, ImageList, ImageManagerState, ImagePixels } from "./imageContracts";
import type { PluginActionResult, PluginDetail, PluginList, PluginState, PluginView } from "./pluginContracts";
import type { ImageEditorActionResult, ImageEditorSave, ImageEditorState, ImageNativeTranslationActionResult, ImageNativeTranslationPreview, ImageNativeTranslationState } from "./imageEditorContracts";

export type Screen = "overview" | "translation" | "guided" | "manual" | "settings";
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
  operation?: Pick<TranslationJob, "label" | "status" | "message">;
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
  created?: string;
  updated?: string;
  label?: string;
  mode?: string;
  phase?: string;
  model?: string;
  files?: string[];
  progress?: { current: number; total: number; file: string };
  itemProgress?: { current: number; total: number; file: string } | null;
  log: string[];
  estimate?: Record<string, number>;
  outputs?: Record<string, string>;
  outputsAvailable?: boolean;
  availableOutputs?: string[];
  changedOutputs?: string[];
  partialOutputs?: string[];
  retiredFiles?: string[];
  logicalPhase?: Phase;
  preparationMode?: "batch" | "translate" | null;
  temporary?: boolean;
  repeatSubmission?: boolean;
  nameTranslation?: NameTranslation | null;
  scopeComplete?: boolean;
  appliedOutputs?: string[];
  process?: RunProcess;
  keptForHistory?: boolean;
  eventTextReview?: { manual?: string[]; reason?: string; binding?: string; reportId?: string | null; fingerprint?: string; literalBased?: boolean; settings?: Record<string, EngineValue> } | null;
  action?: string;
  result?: Record<string, unknown> | null;
  approval?: {
    token: string;
    kind: "batch" | "speakers";
    detail: Record<string, unknown>;
  };
}
export interface NameTranslation {
  state: "running" | "saved" | "failed" | "unavailable";
  reused?: boolean;
  count: number;
  rows: { source: string; translation: string }[];
}
export interface NameTranslationPage {
  rows: NameTranslation["rows"]; total: number; offset: number; nextOffset: number | null;
}
export interface RunProcess {
  noRequestFiles?: string[];
  monitoring?: { state: "monitoring" | "collecting" | "error" | "save_error" | "blocked"; message: string; checkedAt?: string };
  resultsCollected?: boolean;
  fileMetrics?: Record<string, { cost: number; seconds: number }>;
  mode?: string; prepared?: number; submitted?: number | null; remaining?: number | null;
  received?: number | null; validated?: number | null; validatedFiles?: number; appliedFiles?: number;
  failed?: number; retryBlocked?: boolean; nextAction?: string;
  rejected?: number;
  unused?: number;
  validationIssues?: { file: string; rejected: number | null }[];
  uncertain?: number; duplicateSubmissions?: number;
  requests?: { index: number; state: string; file?: string | null; sourceItems: number; clarificationOf?: number }[];
  freshStart?: { eligible: boolean; reason: string; failed?: number; remaining?: number } | null;
  sourceItems?: number | null; submittedItems?: number | null;
  batches?: { id: string; status: string; provider?: string; total?: number | null; counts: Record<string, number | null>; errors?: Record<string, string>[] }[];
  errors: string[]; usage?: Record<string, number> | null;
}
export interface BatchCancellation {
  token: string; runId: string; batchId: string; provider: string; model: string; files: string[]; requests: number;
}
export interface RunPayload {
  responseOrigin?: "validated" | "log" | null;
  responseAttempts?: { kind: "original" | "clarification"; response: unknown; payload?: RunPayload }[];
  translations?: unknown;
  unused?: { appliedRequests: number[] } | null;
  index: number; total: number; state: string; source: Record<string, string> | null;
  context: unknown; parameters: Record<string, unknown>; messages: unknown; system: unknown; exact: unknown; error?: unknown; response?: unknown;
  usage?: Record<string, number> | null;
}
export interface FileTextPreview {
  file: string; origin: "translated" | "working" | "game"; revision: string;
  rows: { location: string; text: string; source: string | null; truncated: boolean }[];
  offset: number; total: number; nextOffset: number | null;
}
export type Phase = "database" | "dialogue" | "variables" | "advanced" | "speakers";
export type RunMode = "estimate" | "translate" | "batch";
export type GuidedStep = "prepare" | "context" | "translate" | "plugins" | "images" | "advanced" | "apply" | "layout" | "review";
export type EngineValue = string | number | boolean | string[];
export interface GuidedOptions {
  selected: string[];
  mode: "batch" | "translate";
  engine_options: Record<string, EngineValue>;
  widths: Record<"width" | "faceWidth" | "listWidth" | "noteWidth", number>;
  phase1_comments: boolean;
}
export interface GuidedPreferences {
  revision: number;
  values: GuidedOptions;
}
export interface GuidedForm {
  version: string;
  original: string;
  untranslated: boolean | null;
  only_overflow: boolean;
  text: { view: "apply" | "fitting" | "qa" | "tools"; categories: string[]; codes: string; max_rows: number; protect_rows: boolean; focus: string; findings_task: string; findings: string[] };
  release: {
    kind: "game" | "patch";
    name: string;
    names: { game: string; patch: string };
    assets: string[];
    directory: string;
    tools: PlaytestOptions;
  };
}
export interface PlaytestOptions { hotkey: string; forgeHotkey: string; uiScale: string; editorCmd: string }
export interface ReleaseArtifact { id: string; kind: "game" | "patch"; path: string; folder: string; available: boolean; size: number | null; saved: string | null }
export interface GuidedFile { name: string; title?: string; default?: boolean; size?: number; group: "database" | "dialogue" }
export interface SpeakerSetup {
  status: "missing" | "waiting" | "invalid" | "stale" | "ready" | "applied";
  message: string;
  reportId: string | null;
  overrides: string[];
  rules: { key: string; label: string; decision: "enable" | "skip"; confidence: "high" | "medium" | "low"; reason: string;
    evidence: { file: string; sha256: string; location: string }[] }[];
}
export interface ContextSetup {
  status: "missing" | "waiting" | "ready" | "stale" | "invalid"; message: string; requestId: string | null;
  speakerReportId: string | null; referencesSha256: string; scanSha256: string | null; revisions: Record<string, string>;
  documents: Record<string, { exists: boolean; reviewed: boolean; needsReview: boolean; intentionalEmpty: boolean }>;
  layout: { widths: GuidedOptions["widths"]; reason: string; evidence: { file: string; sha256: string; location: string }[] } | null;
  layoutStatus: "defaults" | "saved"; layoutRevision: string;
  layoutReportId?: string | null; layoutApplication?: "none" | "pending" | "applied" | "manual"; layoutMessage?: string;
}
export interface ReferenceFolder { id: string; title: string; path: string; available: boolean }
export interface EventTextRow {
  key: string; label: string; coverage: string; selector: "ENABLED_PLUGINS_357" | "ENABLED_PATTERNS_355655" | null;
  choices: { id: string; group: string; details: string }[]; builtins: string[];
  decision: "enable" | "skip" | "review"; confidence: "high" | "medium" | "low"; coverageStatus: string;
  reason: string; targets: string | string[]; observations: string[]; exclusions: string[];
  evidence: { file: string; sha256: string; location: string }[];
}
export interface EventTextState {
  status: "missing" | "waiting" | "ready" | "stale" | "invalid"; message: string; reportId: string | null;
  fingerprint: string | null; requestId: string | null; binding: string | null;
  recommended: Record<string, EngineValue>; rows: EventTextRow[]; builtinHits: Record<string, string[]>;
  accepted: boolean; errors: string[]; enabled: string[]; manual: string[]; manualReason: string; previousManualReason: string;
  view: "audit" | "sources" | "advanced-run" | "variables";
  picker: { key: "ENABLED_PLUGINS_357" | "ENABLED_PATTERNS_355655"; selected: string[]; baseline: string[]; query: string; filter: "all" | "selected" | "recommended" } | null;
}
export interface GuidedState {
  eventText: EventTextState;
  contextDocument: string;
  contextSetup: ContextSetup;
  speakerSetup: SpeakerSetup;
  speakerScan: SpeakerScan;
  projectId: string;
  source: string;
  engine: "MVMZ" | "ACE";
  dataPath: string;
  encrypted: string[];
  hasPlugins: boolean;
  aceAvailable: boolean;
  step: GuidedStep;
  task: string | null;
  positions: Partial<Record<GuidedStep, string | null>>;
  form: GuidedForm;
  preparation: { complete: boolean; configuration: string; stages: { action: string; label: string; status: string; message: string }[] };
  preferences: GuidedPreferences;
  optionsDraft: GuidedPreferences | null;
  engineSchema: { key: string; label: string; type: string; choices?: string[]; min?: number; max?: number }[];
  files: GuidedFile[];
  selection: string[];
  importedFiles: string[];
  collectionError: string;
  operations: Job[];
  run: Job | null;
  runs: Job[];
  activeJobId: string | null;
  phase: Phase;
  phaseFiles: string[];
  estimates: Partial<Record<Phase, { job: Job | null; current: boolean }>>;
  phaseRuns: Partial<Record<Phase, Job>>;
  comparisons: { matches: number; unmatched: number; files: string[]; message: string; status: "not_needed" | "review_needed" | "ready" | "recovery_needed"; fingerprint: string | null;
    rows: { file: string; location: string; literal: string; translation: string; variables: string[] }[] };
  sourceStatus: { ready: string[]; changed: string[]; retired?: string[] };
  readiness: {
    publications: { id: string; kind: string; state: string; files: string[]; recovery_errors: string[] }[];
    qa: { current: boolean; task?: string; status: Record<string, unknown>; message: string;
      findings: { id: string; source?: string; live?: string; current?: string; correction?: string; reason?: string; evidence?: string; note?: string; category?: string; classification?: string; identity?: string }[];
      corrections: { finding_id: string; file: string; expected: string; replacement: string; identity: string }[] };
    outputs: string[];
    applied: string[];
    unapplied: string[];
    runtime_edited: string[];
    review_current: boolean;
    layout_scan: string | null;
    delivery_available: boolean;
  };
  documents: Documents;
  drafts: Documents;
  tools: { inspector: { installed: boolean; present: boolean; message: string }; forge: { installed: boolean; present: boolean; message: string } } | null;
  artifacts: ReleaseArtifact[];
  acePacking: { required: boolean; current: boolean; message: string };
  references: { id: string; title: string }[];
  referenceFolders: ReferenceFolder[];
  provider: {
    connection: string;
    model: string;
    defaultMode: RunMode;
    batchSupported: boolean;
    ready: boolean;
    enabled: boolean;
  };
}
export interface SpeakerScan { job: Job | null; available: boolean; current: boolean; names: string[]; actorNames: Record<string, string>; variableActorIds: Record<string, number>; files: number; path: string | null; savedAt: string | null; issue: string }
export interface WorkspaceSnapshot {
  application: AppState;
  guided: GuidedState | null;
  translation: TranslationState | null;
  translationError: string;
  images?: ImageManagerState | null;
  imagesError?: string;
  plugins?: PluginState | null;
  pluginsError?: string;
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
  action?: string | null;
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
    guided_review?: { manifest: string; evidence: Record<string, string> };
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
  available?: boolean;
  issue?: string;
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
  publication?: { path: string; destination: string; before: string; after: string; size: number; later_edits: boolean; diff: string; truncated: boolean; before_text: string; after_text: string }[];
  run?: { model: string; connection: string; mode: string } | null;
  estimate?: { jobId: string; fingerprint: string; value: Record<string, number>; repeatSubmission?: boolean } | null;
  package?: { included: number; excluded: number; exclusions?: { path: string; reason: string }[]; updater?: string; generated?: string[] };
  overwrite?: boolean;
  game_version?: string;
  additions?: string[];
  token: string;
  label: string;
  destination: string;
  files: number;
  action: string;
  paths: string[];
  confirmation: boolean;
  options: Record<string, unknown>;
  rewrap?: { changes_found: number; overflow_skipped: number; previews: { file_name: string; locator: string; before: string; after: string; rows?: number; overflow?: boolean }[] };
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
  images_state: { request: { project_id: string }; response: ImageManagerState };
  plugins_state: {request:{project_id:string};response:PluginState};
  plugins_list: {request:{project_id:string;query?:string;filter?:string;selected_only?:boolean;offset?:number;limit?:number};response:PluginList};
  plugins_detail: {request:{project_id:string;file:string};response:PluginDetail};
  plugins_update: {request:{project_id:string;revision:string;changes:{view:Partial<PluginView>}};response:PluginState};
  plugins_action: {request:{project_id:string;action:string;options?:Record<string,unknown>};response:PluginActionResult};
  plugins_continue: {request:{project_id:string;request_id:string};response:PluginActionResult};
  images_list: { request: { project_id: string; query?: string; folder?: string; filter?: string; offset?: number; limit?: number; selected_only?: boolean; asset_id?: string }; response: ImageList };
  images_update: { request: { project_id: string; revision: string; changes: Partial<ImageDraft> }; response: ImageManagerState };
  images_action: { request: { project_id: string; action: string; options?: Record<string, unknown> }; response: ImageActionResult };
  images_preview: { request: { project_id: string; asset_id: string; variant?: "source" | "original" | "candidate"; size?: number }; response: ImagePixels };
  images_editor_state: { request: { project_id: string; asset_ids?: string[] }; response: ImageEditorState };
  images_editor_save: { request: { project_id: string; revision: string; images: ImageEditorSave[]; asset_ids?: string[] }; response: ImageEditorState };
  images_editor_action: { request: { project_id: string; revision: string; action: string; asset_ids: string[]; arguments?: Record<string, unknown> }; response: ImageEditorActionResult };
  images_editor_translation_state: { request: { project_id: string }; response: ImageNativeTranslationState };
  images_editor_translation_preview: { request: { project_id: string; mode: "estimate" | "translate" | "batch" }; response: ImageNativeTranslationPreview };
  images_editor_translation_start: { request: { project_id: string; token: string; approved?: boolean }; response: ImageNativeTranslationState };
  images_editor_translation_action: { request: { project_id: string; run_id: string; action: string; arguments?: Record<string, unknown> }; response: ImageNativeTranslationActionResult };
  translation_speakers: { request: { project_id: string; scan: boolean }; response: SpeakerScan };
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
      action: string;
      files?: string[];
      options?: Record<string, unknown>;
    };
    response: Preview;
  };
  guided_execute: {
    request: { project_id: string; token: string };
    response: Job;
  };
  guided_position: {
    request: { project_id: string; step: GuidedStep; task?: string; document?: string };
    response: Saved;
  };
  guided_form: {
    request: { project_id: string; value: GuidedForm };
    response: Saved;
  };
  guided_save_options: {
    request: { project_id: string; revision: number; values: GuidedOptions };
    response: GuidedPreferences;
  };
  guided_apply_speakers: {
    request: { project_id: string; revision: number; report_id: string; reset: boolean };
    response: GuidedPreferences;
  };
  guided_options_draft: {
    request: { project_id: string; value: GuidedPreferences | null };
    response: Saved;
  };
  guided_event_text_request: { request: { project_id: string }; response: { request: Record<string, unknown> | null; findings: EventTextState } };
  guided_event_text_review: { request: { project_id: string; revision: number; binding: string | null; report_id: string | null; manual_reason: string; risk_accepted: boolean }; response: Saved };
  guided_event_text_view: { request: { project_id: string; view: EventTextState["view"] }; response: Saved };
  guided_event_text_picker: { request: { project_id: string; value: EventTextState["picker"] }; response: Saved };
  guided_comparisons_review: { request: { project_id: string; fingerprint: string | null; accepted: boolean }; response: Saved };
  guided_context_status: { request: { project_id: string; retry_layout?: boolean }; response: ContextSetup };
  guided_context_review: { request: { project_id: string; name: string; revision: string; choice: "empty" | "review" | "layout" }; response: Saved };
  guided_reference_add: { request: { project_id: string; folder: string }; response: ReferenceFolder[] };
  guided_reference_remove: { request: { project_id: string; reference_id: string }; response: ReferenceFolder[] };
  guided_skill: {
    request: { project_id: string; name: string };
    response: { text: string };
  };
  guided_answer: {
    request: { project_id: string; token: string; approved: boolean };
    response: Job;
  };
  guided_stop: { request: { project_id: string; run_id?: string }; response: Job };
  guided_resume: { request: { project_id: string; run_id?: string }; response: Job };
  guided_retain_run: { request: { project_id: string; run_id: string; dismissed: boolean }; response: Job };
  guided_output_folder: { request: { project_id: string }; response: { path: string } };
  guided_export: { request: { project_id: string; run_id?: string }; response: ExportedFiles };
  guided_inspect: { request: { project_id: string; run_id: string }; response: Job };
  guided_payload: { request: { project_id: string; run_id: string; index: number }; response: RunPayload };
  guided_name_results: { request: { project_id: string; run_id: string; offset?: number }; response: NameTranslationPage };
  guided_file_preview: { request: { project_id: string; name: string; offset?: number; query?: string }; response: FileTextPreview };
  guided_discard_preparation: { request: { project_id: string; run_id: string }; response: { discarded: boolean } };
  guided_provider_details: { request: { project_id: string; run_id: string }; response: { batches: NonNullable<RunProcess['batches']> } };
  guided_batch_cancel_preview: { request: { project_id: string; run_id: string; batch_id: string }; response: BatchCancellation };
  guided_batch_cancel: { request: { project_id: string; token: string }; response: { id: string; status: string; requested: boolean } };
  guided_batch_collect: { request: { project_id: string; run_id: string }; response: Job };
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
