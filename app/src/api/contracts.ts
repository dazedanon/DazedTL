// Generated from backend/dazedtl/api/contracts by scripts/contracts.mjs.
// Edit the Python contracts and run that script instead of this file.

export type Document = {
  text: string;
  revision: string;
  path?: string;
};

export type Documents = Record<string, Document>;

export type Phase =
  "database" | "dialogue" | "variables" | "advanced" | "speakers";

export type RunMode = "estimate" | "translate" | "batch";

export type EngineValue = string | number | boolean | string[];

export type Evidence = {
  file: string;
  sha256: string;
  location: string;
};

export type Saved = {
  saved: boolean;
};

export type ExportedFiles = {
  path: string;
  files: number;
};

export type Progress = {
  current: number;
  total: number;
  file: string;
};

export type EventTextReview = {
  manual?: string[];
  reason?: string;
  binding?: string;
  reportId?: string | null;
  fingerprint?: string;
  literalBased?: boolean;
  settings?: Record<string, EngineValue>;
};

export type Approval = {
  token: string;
  kind: "batch" | "speakers";
  detail: Record<string, unknown>;
};

/** Token counts and prices from an estimate; producers fill different parts. */
export type RunEstimate = {
  model?: string;
  provider?: string | null;
  basis?: string;
  files?: number;
  requests?: number;
  request_count?: number;
  input_tokens?: number;
  output_tokens?: number;
  dynamic_tokens?: number;
  cache_write_tokens?: number;
  cache_read_tokens?: number;
  cache_kind?: string | null;
  uses_prompt_cache?: boolean;
  live_cost?: number;
  estimated_cost?: number;
  batch_supported?: boolean;
  batch_cost?: number | null;
  batch_cached_cost?: number;
  batch_nocache_cost?: number;
  unestimated_thinking_tokens?: boolean;
  elapsed_seconds?: number;
};

export type Job = {
  id: string;
  status: string;
  workerStatus?: string;
  message: string;
  created?: string;
  updated?: string;
  label?: string;
  mode?: string | null;
  phase?: string;
  model?: string;
  files?: string[];
  progress?: Progress | null;
  itemProgress?: Progress | null;
  log: string[];
  estimate?: RunEstimate | null;
  outputs?: Record<string, string>;
  outputsAvailable?: boolean;
  availableOutputs?: string[];
  changedOutputs?: string[];
  partialOutputs?: string[];
  retiredFiles?: string[];
  logicalPhase?: Phase | null;
  preparationMode?: "batch" | "translate" | null;
  /** A finished estimate found no source text in any of its files. */
  nothingToTranslate?: boolean;
  temporary?: boolean;
  repeatSubmission?: boolean;
  nameTranslation?: NameTranslation | null;
  scopeComplete?: boolean;
  appliedOutputs?: string[];
  process?: RunProcess;
  eventTextReview?: EventTextReview | null;
  action?: string;
  result?: Record<string, unknown> | null;
  approval?: Approval | null;
};

/** A run saved by the former workflow, for the project helper to recover. */
export type LegacyRun = {
  id: string;
  status: string;
  message: string;
  mode?: string | null;
  phase?: string;
  approval?: Approval | null;
  outputs?: Record<string, string>;
};

export type NameTranslationRow = {
  source: string;
  translation: string;
};

export type NameTranslation = {
  state: "running" | "saved" | "failed" | "unavailable";
  reused?: boolean;
  count: number;
  rows: NameTranslationRow[];
};

export type NameTranslationPage = {
  rows: NameTranslationRow[];
  total: number;
  offset: number;
  nextOffset: number | null;
};

export type Billing = {
  openrouter_cost?: number;
  upstream_inference_cost?: number;
};

export type BatchMonitoring = {
  state: "monitoring" | "collecting" | "error" | "save_error" | "blocked";
  message: string;
  checkedAt?: string;
};

export type FileMetric = {
  cost: number;
  seconds: number;
};

export type ValidationIssue = {
  file: string;
  rejected: number | null;
};

export type ProcessRequest = {
  index: number;
  state: string;
  file?: string | null;
  sourceItems: number;
  clarificationOf?: number;
  preview?: string;
  providerFinished?: boolean;
};

export type FreshStart = {
  eligible: boolean;
  reason: string;
  failed?: number;
  remaining?: number;
};

export type ProviderBatch = {
  id: string;
  status: string;
  provider?: string;
  canCancel?: boolean;
  total?: number | null;
  requestIndices?: number[];
  clarification?: boolean;
  originalBatchId?: string;
  counts: Record<string, number | null>;
  errors?: Record<string, string>[];
};

export type RunProcess = {
  resultsUnavailable?: string | null;
  queueStopped?: boolean;
  queueCanContinue?: boolean;
  billing?: Billing | null;
  noRequestFiles?: string[];
  monitoring?: BatchMonitoring;
  resultsCollected?: boolean;
  fileMetrics?: Record<string, FileMetric>;
  mode?: string;
  prepared?: number;
  submitted?: number | null;
  remaining?: number | null;
  received?: number | null;
  validated?: number | null;
  validatedFiles?: number;
  appliedFiles?: number;
  failed?: number;
  retryBlocked?: boolean;
  nextAction?: string;
  rejected?: number;
  unused?: number;
  validationIssues?: ValidationIssue[];
  uncertain?: number;
  duplicateSubmissions?: number;
  requests?: ProcessRequest[];
  freshStart?: FreshStart | null;
  sourceItems?: number | null;
  submittedItems?: number | null;
  batches?: ProviderBatch[];
  runErrors?: string[];
  errors: string[];
  usage?: Record<string, number> | null;
};

export type BatchCancellation = {
  token: string;
  runId: string;
  batchId: string;
  provider: string;
  model: string;
  files: string[];
  requests: number;
};

export type ResponseAttempt = {
  kind: "original" | "clarification";
  batchId?: string;
  response: unknown;
  payload?: RunPayload;
};

export type UnusedResponse = {
  appliedRequests: number[];
};

export type RunPayload = {
  responseOrigin?: "validated" | "log" | null;
  responseAttempts?: ResponseAttempt[];
  translations?: unknown;
  unused?: UnusedResponse | null;
  index: number;
  total: number;
  state: string;
  source: Record<string, string> | null;
  context: unknown;
  parameters: Record<string, unknown>;
  messages: unknown;
  system: unknown;
  exact: unknown;
  error?: unknown;
  response?: unknown;
  usage?: Record<string, number> | null;
};

export type PreparationDiscarded = {
  discarded: boolean;
};

export type SettledEstimate = {
  files: string[];
};

export type ProviderDetails = {
  batches: ProviderBatch[];
};

export type BatchCancelRequested = {
  id: string;
  status: string;
  requested: boolean;
};

export type FileTextRow = {
  location: string;
  text: string;
  source: string | null;
  truncated: boolean;
};

export type FileTextPreview = {
  file: string;
  origin: "translated" | "working" | "game";
  revision: string;
  rows: FileTextRow[];
  offset: number;
  total: number;
  nextOffset: number | null;
};

export type GuidedStep =
  | "prepare"
  | "context"
  | "translate"
  | "plugins"
  | "images"
  | "advanced"
  | "apply"
  | "layout"
  | "review";

export type LayoutWidths = {
  width: number;
  faceWidth: number;
  listWidth: number;
  noteWidth: number;
};

export type GuidedOptions = {
  selected: string[];
  mode: "batch" | "translate";
  engine_options: Record<string, EngineValue>;
  widths: LayoutWidths;
  phase1_comments: boolean;
};

export type GuidedPreferences = {
  revision: number;
  values: GuidedOptions;
};

export type TextToolsForm = {
  view: "apply" | "fitting" | "qa" | "tools";
  categories: string[];
  codes: string;
  max_rows: number;
  protect_rows: boolean;
  focus: string;
  findings_task: string;
  findings: string[];
};

export type ReleaseNames = {
  game: string;
  patch: string;
};

export type ReleaseForm = {
  kind: "game" | "patch";
  name: string;
  names: ReleaseNames;
  assets: string[];
  directory: string;
  tools: PlaytestOptions;
};

export type GuidedForm = {
  version: string;
  original: string;
  untranslated: boolean | null;
  only_overflow: boolean;
  text: TextToolsForm;
  release: ReleaseForm;
};

export type PlaytestOptions = {
  hotkey: string;
  forgeHotkey: string;
  uiScale: string;
  editorCmd: string;
};

export type ReleaseArtifact = {
  id: string;
  kind: "game" | "patch";
  path: string;
  folder: string;
  available: boolean;
  size: number | null;
  saved: string | null;
};

export type GuidedFile = {
  name: string;
  title?: string;
  default?: boolean;
  size?: number;
  group: "database" | "dialogue";
};

export type SpeakerRule = {
  key: string;
  label: string;
  decision: "enable" | "skip";
  confidence: "high" | "medium" | "low";
  reason: string;
  evidence: Evidence[];
};

export type SpeakerSetup = {
  status: "missing" | "waiting" | "invalid" | "stale" | "ready" | "applied";
  message: string;
  reportId: string | null;
  overrides: string[];
  rules: SpeakerRule[];
};

export type ContextDocumentStatus = {
  exists: boolean;
  reviewed: boolean;
  needsReview: boolean;
  intentionalEmpty: boolean;
};

export type LayoutRecommendation = {
  widths: LayoutWidths;
  reason: string;
  evidence: Evidence[];
};

export type ContextSetup = {
  status: "missing" | "waiting" | "ready" | "stale" | "invalid";
  message: string;
  requestId: string | null;
  speakerReportId: string | null;
  referencesSha256: string;
  scanSha256: string | null;
  revisions: Record<string, string>;
  documents: Record<string, ContextDocumentStatus>;
  layout: LayoutRecommendation | null;
  layoutStatus: "defaults" | "saved";
  layoutRevision: string;
  layoutReportId?: string | null;
  layoutApplication?: "none" | "pending" | "applied" | "manual";
  layoutMessage?: string;
};

export type ReferenceFolder = {
  id: string;
  title: string;
  path: string;
  available: boolean;
};

export type EventTextChoice = {
  id: string;
  group: string;
  details: string;
};

export type EventTextRow = {
  key: string;
  label: string;
  coverage: string;
  selector: "ENABLED_PLUGINS_357" | "ENABLED_PATTERNS_355655" | null;
  choices: EventTextChoice[];
  builtins: string[];
  decision: "enable" | "skip" | "review";
  confidence: "high" | "medium" | "low";
  coverageStatus: string;
  reason: string;
  targets: string | string[];
  observations: string[];
  exclusions: string[];
  evidence: Evidence[];
};

export type EventTextPicker = {
  key: "ENABLED_PLUGINS_357" | "ENABLED_PATTERNS_355655";
  selected: string[];
  baseline: string[];
  query: string;
  filter: "all" | "selected" | "recommended";
};

export type EventTextState = {
  status: "missing" | "waiting" | "ready" | "stale" | "invalid";
  message: string;
  reportId: string | null;
  fingerprint: string | null;
  requestId: string | null;
  binding: string | null;
  recommended: Record<string, EngineValue>;
  rows: EventTextRow[];
  builtinHits: Record<string, string[]>;
  accepted: boolean;
  errors: string[];
  enabled: string[];
  manual: string[];
  manualReason: string;
  previousManualReason: string;
  view: "audit" | "sources" | "advanced-run" | "variables";
  picker: EventTextPicker | null;
};

export type PreparationStage = {
  action: string;
  label: string;
  status: string;
  message: string;
  result?: Record<string, unknown>;
};

export type Preparation = {
  complete: boolean;
  configuration: string;
  stages: PreparationStage[];
};

export type EngineSetting = {
  key: string;
  label: string;
  type: string;
  default: EngineValue;
  choices?: string[];
  min?: number;
  max?: number;
};

export type PhaseEstimate = {
  job: Job | null;
  current: boolean;
};

export type ComparisonRow = {
  file: string;
  location: string;
  literal: string;
  translation: string;
  variables: string[];
};

export type Comparisons = {
  matches: number;
  unmatched: number;
  files: string[];
  message: string;
  status: "not_needed" | "review_needed" | "ready" | "recovery_needed";
  fingerprint: string | null;
  rows: ComparisonRow[];
};

export type SourceStatus = {
  ready: string[];
  changed: string[];
  retired?: string[];
  /** Estimate start time per phase and file found without text to translate. */
  noRequests?: Partial<Record<Phase, Record<string, string>>>;
};

export type PublicationStatus = {
  id: string;
  kind: string;
  state: string;
  files: string[];
  recovery_errors: string[];
};

export type QaFinding = {
  id: string;
  source?: string;
  live?: string;
  current?: string;
  correction?: string;
  reason?: string;
  evidence?: string;
  note?: string;
  category?: string;
  classification?: string;
  identity?: string;
};

export type QaCorrection = {
  finding_id: string;
  file: string;
  expected: string;
  replacement: string;
  identity: string;
};

export type QaState = {
  current: boolean;
  task?: string;
  status: Record<string, unknown>;
  message: string;
  findings: QaFinding[];
  corrections: QaCorrection[];
};

export type Readiness = {
  publications: PublicationStatus[];
  qa: QaState;
  outputs: string[];
  applied: string[];
  unapplied: string[];
  runtime_edited: string[];
  review_current: boolean;
  layout_scan: string | null;
  delivery_available: boolean;
};

export type ToolStatus = {
  installed: boolean;
  present: boolean;
  message: string;
};

export type PlaytestTools = {
  inspector: ToolStatus;
  forge: ToolStatus;
};

export type AcePacking = {
  required: boolean;
  current: boolean;
  message: string;
};

export type ReferenceSummary = {
  id: string;
  title: string;
};

export type GuidedProvider = {
  connection: string;
  model: string;
  defaultMode: RunMode;
  batchSupported: boolean;
  batchReason?: string;
  ready: boolean;
  enabled: boolean;
};

export type GuidedState = {
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
  preparation: Preparation;
  preferences: GuidedPreferences;
  optionsDraft: GuidedPreferences | null;
  engineSchema: EngineSetting[];
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
  estimates: Partial<Record<Phase, PhaseEstimate>>;
  phaseRuns: Partial<Record<Phase, Job>>;
  comparisons: Comparisons;
  sourceStatus: SourceStatus;
  readiness: Readiness;
  documents: Documents;
  drafts: Documents;
  tools: PlaytestTools | null;
  artifacts: ReleaseArtifact[];
  acePacking: AcePacking;
  references: ReferenceSummary[];
  referenceFolders: ReferenceFolder[];
  provider: GuidedProvider;
};

export type SpeakerScan = {
  job: Job | null;
  available: boolean;
  current: boolean;
  names: string[];
  actorNames: Record<string, string>;
  variableActorIds: Record<string, number>;
  files: number;
  path: string | null;
  savedAt: string | null;
  issue: string;
};

export type PublicationChange = {
  path: string;
  destination: string;
  before: string;
  after: string;
  size: number;
  later_edits: boolean;
  diff: string;
  truncated: boolean;
  before_text: string;
  after_text: string;
};

export type PreviewRun = {
  model: string;
  connection: string;
  mode: string;
};

export type PreviewEstimate = {
  jobId: string;
  fingerprint: string;
  value: RunEstimate;
  repeatSubmission?: boolean;
};

export type PackageExclusion = {
  path: string;
  reason: string;
};

export type PackageSummary = {
  included: number;
  excluded: number;
  exclusions?: PackageExclusion[];
  updater?: string;
  generated?: string[];
};

export type RewrapChange = {
  file_name: string;
  locator: string;
  before: string;
  after: string;
  rows?: number;
  overflow?: boolean;
};

export type RewrapSummary = {
  changes_found: number;
  overflow_skipped: number;
  previews: RewrapChange[];
};

export type Preview = {
  publication?: PublicationChange[];
  run?: PreviewRun | null;
  estimate?: PreviewEstimate | null;
  package?: PackageSummary | null;
  overwrite?: boolean;
  game_version?: string | null;
  additions?: string[];
  token: string;
  label: string;
  destination: string;
  files: number;
  action: string;
  paths: string[];
  confirmation: boolean;
  options: Record<string, unknown>;
  rewrap?: RewrapSummary;
};

export type EventTextRequest = {
  request: Record<string, unknown> | null;
  findings: EventTextState;
};

export type SkillText = {
  text: string;
};

export type OutputFolder = {
  path: string;
};

export type TranslationOptions = {
  mode: "agent" | "live" | "batch";
  instructions: string;
  include_images: boolean;
  include_glossary_base: boolean;
  install_forge: boolean;
};

export type ProjectOptions = {
  options: TranslationOptions;
  revision: string;
  initialized: boolean;
};

export type QuoteRates = {
  input: number;
  output: number;
  source: string;
  batch_factor: number | null;
};

export type TranslationQuote = {
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
  rates: QuoteRates;
};

export type TranslationBatch = {
  id: string;
  state: string;
  api_status?: string;
  counts?: Record<string, number>;
};

export type TranslationIssue = {
  id: string;
  state: string;
  message: string;
};

export type QaRequest = {
  id: string;
  index: number;
  notes: number;
};

export type TranslationJob = {
  id: string;
  project_id: string;
  kind: "translation" | "operation";
  action?: string | null;
  label: string;
  status: string;
  message: string;
  created: string;
  updated: string;
  mode?: "agent" | "live" | "batch" | null;
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
  can_cancel_provider?: boolean;
  batches: TranslationBatch[];
  issues: TranslationIssue[];
  qa_requests?: QaRequest[];
};

export type ProgressMetric = {
  total: number | null;
  discovered?: number;
  translated: number;
  reviewed: number;
  corpus_sha256?: string;
};

export type ProgressMetrics = {
  text: ProgressMetric;
  images: ProgressMetric;
};

/** Cumulative active seconds the helper reported. */
export type ActiveTime = {
  translated?: number;
  reviewed?: number;
};

export type ProgressSample = {
  corpus: string;
  timing: ActiveTime;
  translated: number;
  reviewed: number;
};

export type RemainingEstimate = {
  low_minutes: number;
  high_minutes: number;
  basis: string;
};

export type ArtifactFingerprint = {
  path: string;
  sha256: string;
  size: number;
  mtime_ns: number;
};

export type TranslationProgress = {
  schema: number;
  updated_at: string | null;
  scope_sha256: string;
  phase: string | null;
  phases: Record<string, string>;
  metrics: ProgressMetrics;
  warnings?: string[];
  blocker: string;
  next_action: string;
  evidence: ArtifactFingerprint[];
  timing?: ActiveTime;
  history?: ProgressSample[];
  estimates?: Record<string, RemainingEstimate>;
};

export type OptionsDraft = {
  options: TranslationOptions;
  revision: string;
};

export type TranslationDrafts = {
  options: OptionsDraft | null;
  documents: Documents;
};

export type GitStatus = {
  configured: boolean;
  selected_root: string;
  repo_root: string | null;
  game_prefix: string;
  original_exists: boolean;
  translation_exists: boolean;
  original_version: string | null;
  translation_version: string | null;
  original_commit: string | null;
  translation_commit: string | null;
  translation_branch: string | null;
  current_branch: string | null;
  worktree_clean: boolean;
  pending_cherry_pick: boolean;
  pending_operations: string[];
  git_available: boolean;
  asset_sync_pending: boolean;
  asset_manifest_available: boolean;
  asset_baseline_repair_needed: boolean;
  applied_update_version: string | null;
  preserve_game_files: boolean;
  available_original_refs: string[];
};

export type LifecycleCheckpoint = {
  commit: string;
  manifest: string;
};

export type GuidedReviewRecord = {
  manifest: string;
  evidence: Record<string, string>;
};

export type DeliveryRecord = {
  path: string;
  commit: string;
  game_version: string;
  updater_stamp: boolean;
};

export type VersionUpdate = {
  version: string;
  complete: boolean;
};

/** Saved lifecycle evidence; further keys are internal to the backend. */
export type Lifecycle = {
  version: number;
  source_backup?: BackupRecord;
  prepared_source?: BackupRecord;
  workspace_backup?: BackupRecord;
  checkpoint?: LifecycleCheckpoint;
  guided_review?: GuidedReviewRecord;
  delivery?: DeliveryRecord;
  incoming_source?: BackupRecord;
  incoming_version?: string;
  version_update?: VersionUpdate;
  [key: string]: unknown;
};

export type ConnectionSummary = {
  name: string;
  model: string;
};

export type TranslationState = ProjectOptions & {
  engine: string;
  legacyRun: LegacyRun | null;
  projectId: string;
  drafts: TranslationDrafts;
  documents: Documents;
  progress: TranslationProgress | null;
  git: GitStatus | null;
  lifecycle: Lifecycle;
  jobs: TranslationJob[];
  active: boolean;
  warnings: string[];
  statusText: string;
  handoff: string;
  providerEnabled: boolean;
  connection: ConnectionSummary | null;
  legacyAvailable: boolean;
};

export type BackupRecord = {
  id: string;
  path: string;
  files: number;
  kind?: "source" | "workspace";
  version?: number;
  available?: boolean;
  issue?: string;
  bytes_total?: number;
  bytes_added?: number;
  bytes_reused?: number;
  reused_snapshot?: boolean;
};

export type BackupSnapshot = {
  id: string;
  kind: "source" | "workspace";
  created: string;
  files: number;
  version: number;
  bytes_total: number | null;
};

export type BackupCatalog = {
  snapshots: BackupSnapshot[];
  warnings: string[];
};

/** Compiled request context; Len's method requests may carry further keys. */
export type RequestContext = {
  line_kinds?: Record<string, "dialogue" | "narration" | "ui" | "unknown">;
  speakers?: Record<string, string | null>;
  qa_notes?: Record<string, string>;
  [key: string]: unknown;
};

export type PreparedRequest = {
  id: string;
  sources: Record<string, string>;
  fingerprint: string;
  constraints: Record<string, unknown>;
  context: RequestContext;
  params?: Record<string, unknown>;
};

export type RequestResult = {
  translations: Record<string, string>;
  result_sha256: string;
  reviewed?: Record<string, string>;
};

export type RequestPreview = {
  run_id: string;
  index: number;
  total: number;
  request: PreparedRequest;
  result: RequestResult | null;
};

export type PreparedHandoff = {
  handoff: string;
  path: string;
};

export type PreferenceValues = {
  language: string;
  model: string;
};

export type ModelOptions = {
  entriesPerRequest: "" | number | null;
  batchInputTokens?: number | null;
  maxOutputTokens?: number | null;
  pricing: "automatic" | "custom";
  inputRate: "" | number | null;
  outputRate: "" | number | null;
  batchPricing?: "automatic" | "custom";
  batchInputRate?: "" | number | null;
  batchOutputRate?: "" | number | null;
};

export type ModelDefaults = {
  model: string;
  inputRate: number | null;
  outputRate: number | null;
  source: "catalog" | "engine_default" | "unavailable";
  updatedAt: string | null;
  stale: boolean;
  maxOutputTokens?: number | null;
  batchSupported?: boolean;
  batchReason?: string;
  batchInputRate?: number | null;
  batchOutputRate?: number | null;
};

export type SettingsProvider = {
  id: Provider;
  label: string;
  protocol: ProviderProtocol;
  defaultEndpoint: string;
};

export type SettingsDraft = {
  values: PreferenceValues;
  modelOptions: Record<string, ModelOptions>;
};

export type Settings = {
  revision: number;
  values: PreferenceValues;
  modelOptions: Record<string, ModelOptions>;
  defaultEntriesPerRequest: number;
  defaultOutputTokens?: number;
  defaultBatchInputTokens?: number;
  activeConnectionId: string;
  connections: Connection[];
  providers: SettingsProvider[];
  checksEnabled: boolean;
  draft?: SettingsDraft;
};

export type Provider =
  "openai" | "openrouter" | "anthropic" | "gemini" | "mistral" | "custom";

export type ProviderProtocol = "openai" | "anthropic" | "gemini" | "mistral";

export type ConnectionCheck = {
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

export type Connection = {
  id: string;
  name: string;
  provider: Provider | null;
  protocol: ProviderProtocol;
  endpoint: string;
  organization: string;
  openrouter_host?: string;
  keyless: boolean;
  has_secret: boolean;
  needsSetup: boolean;
  model: string;
  models: string[];
  check: ConnectionCheck;
};

export type ConnectionInput = {
  connection_id?: string;
  provider: Provider;
  protocol: ProviderProtocol;
  name: string;
  secret: string;
  endpoint: string;
  organization: string;
  openrouter_host?: string;
  keyless: boolean;
  reuse_secret: boolean;
};

export type SettingsPayload = {
  revision: number;
  values: PreferenceValues;
  modelOptions: Record<string, ModelOptions>;
  activeConnectionId: string;
};

export type OpenRouterHost = {
  slug: string;
  name: string;
};

export type ImageDiscoveryScope = "all" | "folders" | "selected";

export type ImageEntryMode = "discovery" | "manual" | "findings" | "review";

export type ImageClassification =
  | "recommended"
  | "uncertain"
  | "no_text"
  | "already_english"
  | "not_examined"
  | "excluded";

export type ImageView = {
  query: string;
  status: string;
  folder: string;
  showSelected: boolean;
  tileSize: number;
  scroll: number;
  currentImage?: string;
  workflowMode?: ImageEntryMode;
};

export type ImageFinding = {
  requestId?: string;
  sourceHash?: string;
  classification?: ImageClassification;
  method?: string;
  reason?: string;
  evidence?: string;
  examined?: boolean;
  variants?: string[];
  saved?: string;
  reusedFrom?: string;
};

export type ImageMetadata = {
  width: number;
  height: number;
  mode: string;
  transparency: boolean;
  alphaRange: number[];
  alphaChannel: boolean;
  frames: number;
};

/** The runtime image a publication wrote, kept to detect later edits. */
export type ImageApplication = {
  candidateHash: string;
  runtimeHash: string;
  sourceHash: string;
  saved: string;
  review: string;
  recovered?: boolean;
};

export type ImageAsset = {
  id: string;
  path: string;
  filename: string;
  folder: string;
  sourceHash: string;
  sourcePngHash: string;
  editable: boolean;
  candidateHash: string | null;
  state: string;
  classification: ImageClassification;
  reason: string;
  blockedReason: string;
  sourceIssue?: string;
  encrypted: boolean;
  changed: boolean;
  aiReviewed: boolean;
  userReviewed: boolean;
  destination: string;
  width?: number | null;
  height?: number | null;
  mode?: string | null;
  method?: string;
  evidence?: unknown[];
  variants?: string[];
  checks?: Record<string, boolean>;
  reviewEvidence?: string;
  finding?: ImageFinding | null;
  candidateIssue: string;
  staleReason: string;
  candidateMetadata: ImageMetadata | null;
  applied: ImageApplication | null;
};

export type ImageCounts = {
  indexed: number;
  examined: number;
  recommended: number;
  uncertain: number;
  notExamined: number;
  ready: number;
  blocked: number;
  applied: number;
  selected: number;
  selectedReady: number;
  selectedBlocked: number;
  selectedNotPrepared: number;
  selectedApplied: number;
  selectedEditable: number;
  missing: number;
};

export type ImageReportState = {
  status: string;
  lastReport?: string | null;
  reportId?: string | null;
  requestId?: string | null;
  message?: string;
  errors?: string[];
  scope?: ImageDiscoveryScope;
  folders?: string[];
  copiedAt?: string;
};

export type ImageReceiptAsset = {
  id: string;
  path?: string;
  destination?: string;
};

export type ImageReceipt = {
  id: string;
  action?: string;
  created?: string;
  count?: number;
  assets?: ImageReceiptAsset[];
  available?: boolean;
  message?: string;
};

export type ImageProfile = {
  id: string;
  label: string;
  imageRoot?: string;
  supported: boolean;
  reason?: string;
  context: string;
};

export type ImageFolder = {
  path: string;
  count: number;
};

export type ImageJobProgress = {
  current: number;
  total: number;
  file?: string;
};

export type ImageJob = {
  id?: string;
  action?: string;
  status: string;
  message?: string;
  indexed?: number;
  current?: number;
  total?: number;
  progress?: ImageJobProgress;
};

export type ImageManagerState = {
  projectId: string;
  name: string;
  engine: string;
  profile: ImageProfile;
  source: string;
  revision: string;
  observationRevision?: string;
  inventoryRevision: string;
  counts: ImageCounts;
  folders: ImageFolder[];
  selection: string[];
  view: ImageView;
  discovery: ImageReportState;
  editing: ImageReportState;
  receipts: ImageReceipt[];
  warnings: string[];
  /** The latest prepare or publication receipt. */
  lastAction?: Record<string, unknown>;
  editableRoot?: string;
  supported?: boolean;
  job?: ImageJob | null;
};

export type ImageDraft = {
  selection: string[];
  view: ImageView;
  discoveryScope: ImageDiscoveryScope;
  folders: string[];
  imageRoot?: string;
};

export type ImageList = {
  items: ImageAsset[];
  total: number;
  selectedMatched: number;
  offset?: number;
  limit: number;
};

export type ImagePreviewAsset = {
  id: string;
  path: string;
  destination: string;
  sourceHash: string;
  candidateHash: string;
};

export type ImageBlocked = {
  id: string;
  path: string;
  reason: string;
};

export type ImagePreview = {
  token: string;
  action: string;
  assets: ImagePreviewAsset[];
  blocked: ImageBlocked[];
  included: number;
  count: number;
  unchanged: number;
  backups?: string[] | boolean;
  expires?: string | number;
};

export type ImageActionResult = {
  state: ImageManagerState;
  /** Counts and paths the action reported. */
  result?: Record<string, unknown>;
  text?: string;
  requestId?: string;
  preview?: ImagePreview;
  message?: string;
};

export type ImagePixels = ImageMetadata & {
  url: string;
  sha256: string;
};

export type Colour = number[];

export type ImageTextStyle = {
  background?:
    | "transparent"
    | "solid"
    | "vgradient"
    | "hgradient"
    | "patch"
    | "inpaint"
    | "keep";
  fill?: Colour | null;
  text_color?: Colour;
  outline_color?: Colour | null;
  outline_width?: number;
  cap_height?: number;
  align?: "left" | "center" | "right";
  font?: string;
  scale_x?: number;
  scale_y?: number;
  tracking?: number;
  bold?: boolean;
  italic?: boolean;
  overflow?: boolean;
  locked?: boolean;
  confidence?: number;
  notes?: string[];
  row_colors?: Colour[];
  column_colors?: Colour[];
  donor?: [number, number, number, number] | null;
  inpaint_method?: string;
};

export type ImageTextBlock = {
  id: string;
  box: [number, number, number, number];
  source: string;
  target: string;
  angle: number;
  skip: boolean;
  flags?: string[];
  lines?: unknown[];
  style?: ImageTextStyle;
};

export type ImageTextNote = {
  blockId: string;
  ok: boolean;
  message: string;
  tight: boolean;
};

export type ImageEditorImage = {
  assetId: string;
  path: string;
  width: number;
  height: number;
  status: string;
  blocks: ImageTextBlock[];
  sourceHash: string;
  candidateHash: string;
  originalUrl: string;
  candidateUrl: string;
  error: string;
  engine: string;
  notes: ImageTextNote[];
};

export type ImageFont = {
  id: string;
  label: string;
};

export type LocalOcr = {
  available: boolean;
  detail: string;
};

export type ImageEditorState = {
  revision: string;
  selectedIds: string[];
  images: ImageEditorImage[];
  fonts: ImageFont[];
  localOcr: LocalOcr;
  exchangePath: string;
};

export type ImageEditorSave = {
  assetId: string;
  sourceHash: string;
  candidateHash: string;
  blocks: ImageTextBlock[];
  status: "needs_review" | "confirmed";
};

export type ImageEditorExport = {
  path: string;
  assetIds: string[];
  count: number;
  requestHash: string;
};

export type ImageEditorOutcome = {
  path?: string;
  assetIds?: string[];
  count?: number;
  requestHash?: string;
  applied?: number;
  missing?: number;
  empty?: number;
  completed?: string[];
  errors?: Record<string, string>;
};

export type ImageEditorActionResult = {
  state: ImageEditorState;
  result: ImageEditorOutcome;
};

export type ImageNativeJob = Job & {
  imported?: boolean;
  imageConfiguration?: ImageNativeConfiguration;
};

export type ImageNativeSelection = {
  fingerprint: string;
  count: number;
  configuration: ImageNativeConfiguration;
};

export type ImageNativeTranslationState = {
  jobs: ImageNativeJob[];
  job: ImageNativeJob | null;
  activeId: string | null;
  quote: Job | null;
  quoteCurrent: boolean;
  current: ImageNativeSelection | null;
  error: string;
  providerEnabled: boolean;
  batchSupported: boolean;
};

export type ImageNativeConfiguration = {
  model: string;
  language: string;
  endpoint: string;
  entries_per_request: number;
};

export type ImageNativeTranslationPreview = {
  token: string;
  mode: "estimate" | "translate" | "batch";
  count: number;
  assetIds: string[];
  configuration: ImageNativeConfiguration;
  estimate: Record<string, unknown> | null;
  confirmation: boolean;
};

export type ImageNativeOutcome = {
  path?: string;
  files?: number;
  state?: ImageEditorState;
  result?: ImageEditorOutcome;
};

export type ImageNativeTranslationActionResult = {
  state: ImageNativeTranslationState;
  result: ImageNativeOutcome;
};

export type PluginFinding = {
  disposition: string;
  safe: boolean;
  evidence: string;
  reason: string;
};

export type PluginManualChoice = {
  selected: boolean;
  reason: string;
};

export type PluginOccurrence = {
  id: string;
  file: string;
  value: string;
  line: number;
  logical: (string | number)[];
  kind: string;
  protected: boolean;
  latent: boolean;
  enabled: boolean;
  plugin: string;
  finding?: PluginFinding;
  selected: boolean;
  manual?: PluginManualChoice;
  before: string;
  after: string;
  target: string;
};

export type PluginRow = {
  path: string;
  plugin: string;
  enabled: boolean | null;
  kind: string;
  sourceHash: string;
  issue: string;
  selected: number;
  visible: number;
  latent: number;
  occurrences: number;
  recommended: number;
  manual: number;
  uncertain: number;
  status: string;
  changed: number;
  reason: string;
  candidateHash: string;
  working: string;
  ready: boolean;
};

export type PluginView = {
  mode: "scope" | "working";
  query: string;
  filter: string;
  selectedOnly: boolean;
  currentFile: string;
  offset: number;
};

export type PluginFileReview = {
  path: string;
  destination: string;
  beforeHash: string;
  afterHash: string;
  originalHash: string;
  candidateHash: string;
  backup: string;
  changes: number;
  kind: string;
};

export type PluginBlocked = {
  path: string;
  reason: string;
};

export type PluginPreview = {
  token: string;
  mode: "apply" | "restore";
  files: PluginFileReview[];
  blocked: PluginBlocked[];
  manifest: string;
};

export type PluginReceipt = {
  id: string;
  mode: string;
  saved: string;
  status: string;
  files: PluginFileReview[];
  failure: string;
  conflicts: string[];
  manifest: string;
};

export type PluginCounts = {
  files: number;
  selectedFiles: number;
  selectedNotPrepared: number;
  selected: number;
  recommended: number;
  ready: number;
  blocked: number;
  applied: number;
  latent: number;
};

export type PluginReport = {
  status: string;
  errors: string[];
  accepted?: number;
  reported?: number;
  expected?: number;
};

export type PluginState = {
  projectId: string;
  revision: string;
  observationRevision: string;
  supported: boolean;
  limitation: string;
  layout: string;
  source: string;
  view: PluginView;
  counts: PluginCounts;
  findings: PluginReport;
  editing: PluginReport;
  originalIssue: string;
  originalBackup: string;
  receipts: PluginReceipt[];
  requestPaths: Record<string, string>;
  activeRequest: string;
};

export type PluginList = {
  items: PluginRow[];
  total: number;
  selectedMatched: number;
  offset: number;
  limit: number;
};

export type PluginDetail = PluginRow & {
  items: PluginOccurrence[];
  total: number;
  checks: Record<string, boolean>;
  resultEvidence: string;
  rendered: string;
  original: string;
  originalHash: string;
};

export type PluginActionResult = {
  state?: PluginState;
  text?: string;
  preview?: PluginPreview;
  receipt?: PluginReceipt;
  completed?: number;
  message?: string;
  request?: string;
  requestId?: string;
  stage?: string;
};

export type Screen =
  "overview" | "translation" | "guided" | "manual" | "settings";

export type ProjectOperation = {
  label: string;
  status: string;
  message: string;
};

export type Project = {
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
  operation?: ProjectOperation;
  next_label?: string;
};

export type AppState = {
  project: Project | null;
  recent: Project[];
  screen: Screen;
  running: boolean;
  provider_ready: boolean;
  observing: boolean;
};

export type WorkspaceSnapshot = {
  application: AppState;
  guided: GuidedState | null;
  translation: TranslationState | null;
  translationError: string;
  images?: ImageManagerState | null;
  imagesError?: string;
  plugins?: PluginState | null;
  pluginsError?: string;
};

export type ProjectRequest = {
  project_id: string;
};

export type PluginsListRequest = {
  project_id: string;
  query?: string;
  filter?: string;
  selected_only?: boolean;
  offset?: number;
  limit?: number;
};

export type PluginsDetailRequest = {
  project_id: string;
  file: string;
};

export type PluginViewChanges = {
  mode?: "scope" | "working";
  query?: string;
  filter?: string;
  selectedOnly?: boolean;
  currentFile?: string;
  offset?: number;
};

export type PluginChanges = {
  view: PluginViewChanges;
};

export type PluginsUpdateRequest = {
  project_id: string;
  revision: string;
  changes: PluginChanges;
};

export type ActionRequest = {
  project_id: string;
  action: string;
  options?: Record<string, unknown>;
};

export type PluginsContinueRequest = {
  project_id: string;
  request_id: string;
};

export type ImagesListRequest = {
  project_id: string;
  query?: string;
  folder?: string;
  filter?: string;
  offset?: number;
  limit?: number;
  selected_only?: boolean;
  asset_id?: string;
};

export type ImageDraftChanges = {
  selection?: string[];
  view?: ImageView;
  discoveryScope?: ImageDiscoveryScope;
  folders?: string[];
  imageRoot?: string;
};

export type ImagesUpdateRequest = {
  project_id: string;
  revision: string;
  changes: ImageDraftChanges;
};

export type ImagesPreviewRequest = {
  project_id: string;
  asset_id: string;
  variant?: "source" | "original" | "candidate";
  size?: number;
};

export type ImagesEditorStateRequest = {
  project_id: string;
  asset_ids?: string[];
};

export type ImagesEditorSaveRequest = {
  project_id: string;
  revision: string;
  images: ImageEditorSave[];
  asset_ids?: string[];
};

export type ImagesEditorActionRequest = {
  project_id: string;
  revision: string;
  action: string;
  asset_ids: string[];
  arguments?: Record<string, unknown>;
};

export type ImagesEditorTranslationPreviewRequest = {
  project_id: string;
  mode: "estimate" | "translate" | "batch";
};

export type ImagesEditorTranslationStartRequest = {
  project_id: string;
  token: string;
  approved?: boolean;
};

export type ImagesEditorTranslationActionRequest = {
  project_id: string;
  run_id: string;
  action: string;
  arguments?: Record<string, unknown>;
};

export type TranslationSpeakersRequest = {
  project_id: string;
  scan: boolean;
};

export type TranslationIdentifyRequest = {
  project_id: string;
  engine: string;
  evidence_file: string;
};

export type TranslationLegacyRequest = {
  project_id: string;
  action: "resume" | "stop" | "answer" | "export";
  token?: string;
  approved?: boolean;
};

export type TranslationResolveUncertainRequest = {
  project_id: string;
  run_id: string;
  batch_id: string;
  request_sha256: string;
  retry_reviewed: boolean;
};

export type TranslationSaveRequest = {
  project_id: string;
  revision: string;
  values: TranslationOptions;
};

export type TranslationDraftRequest = {
  project_id: string;
  section: "options" | "documents";
  value: unknown;
};

export type SaveDocumentRequest = {
  project_id: string;
  name: string;
  revision: string;
  text: string;
};

export type InputPathRequest = {
  project_id: string;
  input_path: string;
};

export type RunRequest = {
  project_id: string;
  run_id: string;
};

export type RunIndexRequest = {
  project_id: string;
  run_id: string;
  index: number;
};

export type TranslationStartRequest = {
  project_id: string;
  run_id: string;
  approval_token?: string;
};

export type TranslationStopRequest = {
  project_id: string;
  run_id: string;
  cancel_provider?: boolean;
};

export type TranslationAcceptRequest = {
  project_id: string;
  run_id: string;
  batch_id: string;
  input_path: string;
};

export type TranslationReviewRequest = {
  project_id: string;
  run_id: string;
  batch_id: string;
  request_sha256: string;
};

export type TranslationOperationRequest = {
  project_id: string;
  action: string;
  arguments: Record<string, unknown>;
};

export type TranslationAttachBatchRequest = {
  project_id: string;
  run_id: string;
  index: number;
  provider_job_id: string;
};

export type NoParams = Record<string, never>;

export type OpenProjectRequest = {
  source: string;
};

export type NavigateRequest = {
  screen: Screen;
};

export type SettingsModelDefaultsRequest = {
  connection_id: string;
  model: string;
};

export type OpenrouterHostsRequest = {
  model?: string;
};

export type ConnectionRequest = {
  revision: number;
  connection_id: string;
};

export type ConnectionSaveRequest = ConnectionInput & {
  revision: number;
};

export type GuidedPhaseSelectRequest = {
  project_id: string;
  phase: Phase;
};

export type GuidedPreviewRequest = {
  project_id: string;
  action: string;
  files?: string[];
  options?: Record<string, unknown>;
};

export type TokenRequest = {
  project_id: string;
  token: string;
};

export type GuidedPositionRequest = {
  project_id: string;
  step: GuidedStep;
  task?: string;
  document?: string;
};

export type GuidedFormRequest = {
  project_id: string;
  value: GuidedForm;
};

export type GuidedSaveOptionsRequest = {
  project_id: string;
  revision: number;
  values: GuidedOptions;
};

export type GuidedApplySpeakersRequest = {
  project_id: string;
  revision: number;
  report_id: string;
  reset: boolean;
};

export type GuidedOptionsDraftRequest = {
  project_id: string;
  value: GuidedPreferences | null;
};

export type GuidedEventTextReviewRequest = {
  project_id: string;
  revision: number;
  binding: string | null;
  report_id: string | null;
  manual_reason: string;
  risk_accepted: boolean;
};

export type GuidedEventTextViewRequest = {
  project_id: string;
  view: "audit" | "sources" | "advanced-run" | "variables";
};

export type GuidedEventTextPickerRequest = {
  project_id: string;
  value: EventTextPicker | null;
};

export type GuidedComparisonsReviewRequest = {
  project_id: string;
  fingerprint: string | null;
  accepted: boolean;
};

export type GuidedContextStatusRequest = {
  project_id: string;
  retry_layout?: boolean;
};

export type GuidedContextReviewRequest = {
  project_id: string;
  name: string;
  revision: string;
  choice: "empty" | "review" | "layout";
};

export type GuidedReferenceAddRequest = {
  project_id: string;
  folder: string;
};

export type GuidedReferenceRemoveRequest = {
  project_id: string;
  reference_id: string;
};

export type GuidedSkillRequest = {
  project_id: string;
  name: string;
};

export type GuidedAnswerRequest = {
  project_id: string;
  token: string;
  approved: boolean;
};

export type RunControlRequest = {
  project_id: string;
  run_id?: string;
};

export type GuidedNameResultsRequest = {
  project_id: string;
  run_id: string;
  offset?: number;
};

export type GuidedFilePreviewRequest = {
  project_id: string;
  name: string;
  offset?: number;
  query?: string;
};

export type GuidedBatchCancelPreviewRequest = {
  project_id: string;
  run_id: string;
  batch_id: string;
};

export type GuidedDraftRequest = {
  project_id: string;
  documents: Documents;
};

export type PreferencesRequest = {
  revision: number;
  connection_id: string;
  values: PreferenceValues;
  model_options: Record<string, ModelOptions>;
};

export type RpcContract = {
  workspace_snapshot: { request: NoParams; response: WorkspaceSnapshot };
  open_project: { request: OpenProjectRequest; response: AppState };
  select_project: { request: ProjectRequest; response: AppState };
  navigate: { request: NavigateRequest; response: AppState };
  settings_get: { request: NoParams; response: Settings };
  settings_save: { request: PreferencesRequest; response: Settings };
  settings_draft: { request: PreferencesRequest; response: Saved };
  settings_revert: { request: ConnectionRequest; response: Settings };
  connection_save: { request: ConnectionSaveRequest; response: Settings };
  connection_select: { request: ConnectionRequest; response: Settings };
  connection_check: { request: ConnectionRequest; response: Settings };
  settings_model_defaults: {
    request: SettingsModelDefaultsRequest;
    response: ModelDefaults;
  };
  openrouter_hosts: {
    request: OpenrouterHostsRequest;
    response: OpenRouterHost[];
  };
  guided_phase_select: {
    request: GuidedPhaseSelectRequest;
    response: GuidedState;
  };
  guided_preview: { request: GuidedPreviewRequest; response: Preview };
  guided_execute: { request: TokenRequest; response: Job };
  guided_answer: { request: GuidedAnswerRequest; response: Job };
  guided_stop: { request: RunControlRequest; response: Job };
  guided_resume: { request: RunControlRequest; response: Job };
  guided_draft: { request: GuidedDraftRequest; response: Saved };
  guided_save_document: { request: SaveDocumentRequest; response: Documents };
  guided_position: { request: GuidedPositionRequest; response: Saved };
  guided_options_draft: { request: GuidedOptionsDraftRequest; response: Saved };
  guided_save_options: {
    request: GuidedSaveOptionsRequest;
    response: GuidedPreferences;
  };
  guided_skill: { request: GuidedSkillRequest; response: SkillText };
  guided_apply_speakers: {
    request: GuidedApplySpeakersRequest;
    response: GuidedPreferences;
  };
  translation_speakers: {
    request: TranslationSpeakersRequest;
    response: SpeakerScan;
  };
  guided_inspect: { request: RunRequest; response: Job };
  guided_payload: { request: RunIndexRequest; response: RunPayload };
  guided_name_results: {
    request: GuidedNameResultsRequest;
    response: NameTranslationPage;
  };
  guided_file_preview: {
    request: GuidedFilePreviewRequest;
    response: FileTextPreview;
  };
  guided_discard_preparation: {
    request: RunRequest;
    response: PreparationDiscarded;
  };
  guided_settle_empty_estimate: {
    request: RunRequest;
    response: SettledEstimate;
  };
  guided_provider_details: { request: RunRequest; response: ProviderDetails };
  guided_batch_cancel_preview: {
    request: GuidedBatchCancelPreviewRequest;
    response: BatchCancellation;
  };
  guided_batch_cancel: {
    request: TokenRequest;
    response: BatchCancelRequested;
  };
  guided_batch_collect: { request: RunRequest; response: Job };
  guided_form: { request: GuidedFormRequest; response: Saved };
  guided_context_status: {
    request: GuidedContextStatusRequest;
    response: ContextSetup;
  };
  guided_context_review: {
    request: GuidedContextReviewRequest;
    response: Saved;
  };
  guided_reference_add: {
    request: GuidedReferenceAddRequest;
    response: ReferenceFolder[];
  };
  guided_reference_remove: {
    request: GuidedReferenceRemoveRequest;
    response: ReferenceFolder[];
  };
  guided_event_text_request: {
    request: ProjectRequest;
    response: EventTextRequest;
  };
  guided_event_text_review: {
    request: GuidedEventTextReviewRequest;
    response: Saved;
  };
  guided_event_text_view: {
    request: GuidedEventTextViewRequest;
    response: Saved;
  };
  guided_event_text_picker: {
    request: GuidedEventTextPickerRequest;
    response: Saved;
  };
  guided_comparisons_review: {
    request: GuidedComparisonsReviewRequest;
    response: Saved;
  };
  guided_output_folder: { request: ProjectRequest; response: OutputFolder };
  translation_state: { request: ProjectRequest; response: TranslationState };
  translation_save: {
    request: TranslationSaveRequest;
    response: ProjectOptions;
  };
  translation_draft: { request: TranslationDraftRequest; response: Saved };
  translation_documents: { request: ProjectRequest; response: Documents };
  translation_save_document: {
    request: SaveDocumentRequest;
    response: Documents;
  };
  translation_prepare: { request: ProjectRequest; response: PreparedHandoff };
  translation_compile: { request: InputPathRequest; response: TranslationJob };
  translation_run: { request: RunRequest; response: TranslationJob };
  translation_request: { request: RunIndexRequest; response: RequestPreview };
  translation_backups: { request: ProjectRequest; response: BackupCatalog };
  translation_start: {
    request: TranslationStartRequest;
    response: TranslationJob;
  };
  translation_stop: {
    request: TranslationStopRequest;
    response: TranslationJob;
  };
  translation_accept: {
    request: TranslationAcceptRequest;
    response: TranslationJob;
  };
  translation_review: { request: TranslationReviewRequest; response: Saved };
  translation_progress: {
    request: InputPathRequest;
    response: TranslationProgress;
  };
  translation_operation: {
    request: TranslationOperationRequest;
    response: TranslationJob;
  };
  translation_attach_batch: {
    request: TranslationAttachBatchRequest;
    response: TranslationJob;
  };
  translation_resolve_uncertain: {
    request: TranslationResolveUncertainRequest;
    response: TranslationJob;
  };
  translation_identify: {
    request: TranslationIdentifyRequest;
    response: Saved;
  };
  translation_legacy: {
    request: TranslationLegacyRequest;
    response: Job | ExportedFiles;
  };
  images_state: { request: ProjectRequest; response: ImageManagerState };
  images_list: { request: ImagesListRequest; response: ImageList };
  images_preview: { request: ImagesPreviewRequest; response: ImagePixels };
  images_update: { request: ImagesUpdateRequest; response: ImageManagerState };
  images_action: { request: ActionRequest; response: ImageActionResult };
  images_editor_state: {
    request: ImagesEditorStateRequest;
    response: ImageEditorState;
  };
  images_editor_save: {
    request: ImagesEditorSaveRequest;
    response: ImageEditorState;
  };
  images_editor_action: {
    request: ImagesEditorActionRequest;
    response: ImageEditorActionResult;
  };
  images_editor_translation_state: {
    request: ProjectRequest;
    response: ImageNativeTranslationState;
  };
  images_editor_translation_preview: {
    request: ImagesEditorTranslationPreviewRequest;
    response: ImageNativeTranslationPreview;
  };
  images_editor_translation_start: {
    request: ImagesEditorTranslationStartRequest;
    response: ImageNativeTranslationState;
  };
  images_editor_translation_action: {
    request: ImagesEditorTranslationActionRequest;
    response: ImageNativeTranslationActionResult;
  };
  plugins_state: { request: ProjectRequest; response: PluginState };
  plugins_list: { request: PluginsListRequest; response: PluginList };
  plugins_detail: { request: PluginsDetailRequest; response: PluginDetail };
  plugins_update: { request: PluginsUpdateRequest; response: PluginState };
  plugins_action: { request: ActionRequest; response: PluginActionResult };
  plugins_continue: {
    request: PluginsContinueRequest;
    response: PluginActionResult;
  };
};
