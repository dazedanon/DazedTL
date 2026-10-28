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

/** A game's own pattern for event text nothing installed captures; its
regex's last capturing group is translated. */
export type CustomPattern = {
  name: string;
  regex: string;
  script?: string;
  spacing?: "space" | "nbsp" | "underscore";
};

/** A game's own handler for an MZ plugin command's plain-text arguments. */
export type CustomHandler = {
  plugin: string;
  command: string;
  args: string[];
};

export type EngineValue =
  string | number | boolean | string[] | CustomPattern[] | CustomHandler[];

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

/** Work the game folder holds for another project or app version, and the
choice offered for it. */
export type ForeignWork = {
  binding: string;
  saved: string;
  archive: string;
  blocked: string;
  applied: number;
  restorable: number;
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
  cache_max_write_tokens?: number;
  cacheable_tokens?: number;
  cache_kind?: string | null;
  uses_prompt_cache?: boolean;
  live_cost?: number;
  estimated_cost?: number;
  batch_supported?: boolean;
  batch_cost?: number | null;
  batch_cached_cost?: number;
  batch_nocache_cost?: number;
  batch_max_cost?: number;
  unestimated_thinking_tokens?: boolean;
  thinking_effort?: string;
  approximate_input?: boolean;
  elapsed_seconds?: number;
  price_rules?: number;
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
  unsaved?: string[];
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

/** A source request at its latest attempt; `indices` lists every attempt.
A request holding lines of several files, such as map display names,
lists each file's lines in `files`; `file` is the first of them. */
export type ProcessRequest = {
  index: number;
  indices: number[];
  state: string;
  file: string | null;
  sourceItems: number;
  files?: Record<string, number>;
  providerFinished?: boolean;
  keptLines?: number;
};

export type SubmittedRequests = {
  batches: string[];
  finished: boolean;
};

export type FileRequests = {
  first: number;
  requests: number;
  lines: number;
  done: number;
  states: string[];
  submitted?: SubmittedRequests[];
};

export type RequestGroup = {
  id: string;
  label: string;
  batches: string[];
  total: number;
  files: number;
  first: number | null;
};

export type RequestPage = {
  group: string | null;
  rows: ProcessRequest[];
  offset: number;
  total: number;
  previous: number | null;
  next: number | null;
};

export type ProviderBatch = {
  id: string;
  status: string;
  provider?: string;
  canCancel?: boolean;
  total?: number | null;
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
  files?: Record<string, FileRequests>;
  groups?: RequestGroup[];
  attention?: ProcessRequest[];
  requestRevision?: string;
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
  kind: "original" | "clarification" | "retry";
  batchId?: string;
  response: unknown;
  payload?: RunPayload;
};

export type UnusedResponse = {
  appliedRequests: number[];
};

/** A line a validated response left in its original text, as `source`
names it, and why it failed validation. */
export type KeptLine = {
  line: string;
  reason: string;
};

export type RunPayload = {
  responseOrigin?: "validated" | "log" | null;
  responseAttempts?: ResponseAttempt[];
  translations?: unknown;
  unused?: UnusedResponse | null;
  keptLines?: KeptLine[] | null;
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
  /** Why a line left is: still in Japanese, choice help still in Japanese, or a refusal note. */
  reason?: "untranslated" | "help" | "note";
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
  "setup" | "context" | "translate" | "check" | "release";

export type LayoutWidths = {
  width: number;
  faceWidth: number;
  listWidth: number;
  noteWidth: number;
  messageRows: number;
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
  thorough_investigation: boolean;
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
  current: boolean | null;
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
  layoutUnmeasured?: boolean;
  layoutRejected?: string;
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
  recommended: Record<string, EngineValue>;
  rows: EventTextRow[];
  builtinHits: Record<string, string[]>;
  /** DazedTL is still reading the selected event files' built-in matches; builtinHits holds none yet and errors wait for them. */
  reading: boolean;
  applied: boolean;
  errors: string[];
  enabled: string[];
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
  current: boolean | null;
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

/** How much of a file is translated, from the file itself (see
translation/file_lines.py). */
export type FileLines = {
  /** Lines whose source holds Japanese. */
  lines: number;
  /** Lines holding no Japanese and no refusal note. */
  translated: number;
  /** Lines holding a refusal note an earlier run saved instead of a translation; the next run sends them again. */
  notes?: number;
  /** Choice help blocks still in Japanese, which Comment text translates. */
  help?: number;
  /** Refusal notes in values outside these lines, such as Other event text. */
  otherNotes?: number;
};

export type SourceStatus = {
  ready: string[];
  changed: string[];
  retired?: string[];
  /** Estimate start time per phase and file found without text to translate. */
  noRequests?: Partial<Record<Phase, Record<string, string>>>;
  /** Each Database files and Maps & events file's lines, read from its newest copy; a file that cannot be read has none. */
  lines?: Record<string, FileLines>;
  /** Files whose lines DazedTL is still counting, which have none in lines yet. */
  counting?: string[];
};

/** What a batch's restore waits for: for one undone through its
checkpoint, the later checkpoint to undo first (kind "checkpoint"), else
the newest later batch still in the game that changed some of its
files. */
export type RestoreBlocker = {
  /** The later batch, or the later checkpoint's commit. */
  id: string;
  kind: string;
  /** The files both changed. */
  files: string[];
  /** Why its checkpoint can't be undone yet, as the Checkpoints tab says it. */
  reason?: string;
};

export type PublicationStatus = {
  id: string;
  kind: string;
  state: string;
  files: string[];
  recovery_errors: string[];
  /** Restores in one click by undoing its checkpoint, or, interrupted, by putting its files back from the checkpoint before it; else by a reviewed restore of the copies it saved. */
  undo: boolean;
  blocker?: RestoreBlocker;
};

/** One line of a scene correction. */
export type QaLineChange = {
  source: string;
  current: string;
  correction: string;
};

export type QaFinding = {
  id: string;
  source: string;
  current: string;
  correction: string;
  category: string;
  severity: string;
  /** The family a reviewer or lint named, or empty. */
  family: string;
  /** How the finding came to be: a reviewer, lint, the glossary's term for another rendering, the family sweep, a source fix, or a reviewer's correction of several lines of one scene. */
  kind: "review" | "lint" | "glossary" | "sweep" | "source" | "scene";
  /** Lines the correction changes. */
  places: number;
  files: string[];
  /** What is wrong in one plain sentence; a task made before reviewers wrote one gives their full evidence. */
  reason: string;
  /** A scene correction's lines, which apply and undo together; source, current and correction join them. */
  lines?: QaLineChange[];
  state?: "applied" | "undone";
};

/** A playtest or context question no evidence settled; the user keeps the
current text or uses the reviewer's proposal. */
export type QaQuestion = {
  id: string;
  source: string;
  current: string;
  /** As a finding's reason. */
  reason: string;
  places: number;
  proposal: string;
  choice?: "keep" | "use";
  state?: "applied" | "undone";
};

export type QaCoverage = {
  /** Translated lines in QA's inventory. */
  lines: number;
  /** Lines reviewers declined, which QA set aside. */
  not_reviewed: number;
};

export type QaActivity = {
  stage: "lint" | "screen" | "deep" | "sweep" | "editorial";
  done: number;
  total: number;
  eta_seconds?: number;
  /** Bundles waited while reviewers took one at a time. */
  one_at_a_time?: boolean;
};

/** A prepared task the app can't read or trust, for the helper's next step. */
export type QaUnreadable = {
  /** The task folder, or the file naming it when that fails. */
  path: string;
  /** The error as raised. */
  error: string;
};

export type QaReportLine = {
  identity: string;
  file: string;
  source: string;
  current: string;
};

/** A defect a reviewer found but no correction could fix within apply's
checks; QA reports it without asking the user. */
export type QaNotCorrected = {
  id: string;
  file: string;
  source: string;
  current: string;
  /** As a finding's reason. */
  reason: string;
  /** The reviewer's full reasoning, when it says more. */
  evidence?: string;
  places: number;
};

/** A finding's or question's full review, for the History inspector. */
export type QaReviewNote = {
  id: string;
  /** The line as reviewers read it, to find it by. */
  current: string;
  /** The reviewer's full reasoning. */
  evidence: string;
  /** The editorial reviewer's note. */
  editorial?: string;
};

export type QaUntranslatedText = {
  pointer: string;
  kind: string;
  text: string;
};

/** One file's or plugin's Japanese that was never translated. */
export type QaUntranslatedSource = {
  /** Game data without a saved original, a custom data file, or plugin settings. */
  kind: "data" | "custom" | "plugin";
  file: string;
  plugin?: string;
  count: number;
  reach?: "called" | "runs" | "unknown" | "uncalled" | "unread";
  /** What the reach rests on. */
  evidence?: string;
  /** Its first texts. */
  texts: QaUntranslatedText[];
};

/** Text the game squeezes or cuts off that QA holds no line of, such as a
plugin's menu command. */
export type QaInterfaceText = {
  text: string;
  /** The captured screen that shows it. */
  title: string;
};

/** What QA could not cover, for the History inspector. */
export type QaReport = {
  not_reviewed: QaReportLine[];
  not_corrected: QaNotCorrected[];
  /** Each correction's and question's full review. */
  notes: QaReviewNote[];
  not_translated: QaUntranslatedSource[];
  interface_outside: QaInterfaceText[];
  interface_error?: string;
};

export type TextQaOperation = {
  kind: "prepare" | "apply" | "undo" | "reapply" | "checkpoint";
  id: string;
  status: string;
  message: string;
};

/** Text the game squeezes or cuts off on a screen QA captured that QA
holds no line of, for an Assistant-led assistant to shorten. */
export type QaLabel = {
  text: string;
  /** The captured screen that shows it. */
  title: string;
  /** The screen's capture file. */
  capture: string;
  /** The share of the width it needs the game drew it in. */
  squeezed?: number;
  /** Its end is cut off at its window's edge. */
  clipped?: boolean;
};

/** Where the game's text QA stands, for the assistant's project helper. */
export type TextQaStatus = {
  focus: string;
  task: string;
  stage: string;
  current: boolean;
  applied: boolean;
  /** Findings with a correction. */
  findings: number;
  /** Open playtest or context questions. */
  questions: number;
  message: string;
  /** The step to run next. */
  next: string;
  /** The engine's checkpoint status. */
  progress: Record<string, unknown>;
  /** Assistant-led only: squeezed labels the assistant shortens before apply. */
  labels?: QaLabel[];
  /** Assistant-led only: never-translated text players can reach in the census's scope, which the assistant translates before apply. */
  untranslated?: number;
  operation?: TextQaOperation;
  /** The saved findings file. */
  report?: string;
};

/** Text QA's text-only rules over an Assistant-led game's exported
translations, for an engine Text QA can't read. */
export type TextQaCheck = {
  /** The project-relative file listing each hit. */
  report: string;
  /** Exported units with a translation. */
  lines: number;
  /** Hits: one per rule and distinct line. */
  hits: number;
  /** Hits neither corrected nor answered. */
  open: number;
  answered: number;
  /** Open hits by rule. */
  rules: Record<string, number>;
  /** The step to run next. */
  next: string;
};

export type QaState = {
  current: boolean;
  applied: boolean;
  task?: string;
  status: Record<string, unknown>;
  message: string;
  findings: QaFinding[];
  questions: QaQuestion[];
  coverage?: QaCoverage;
  activity?: QaActivity;
  rules_changed?: boolean;
  prepared_at?: string;
  unreadable?: QaUnreadable;
};

/** Where the playtest's tour saw a problem on screen. */
export type PlaytestSeen = {
  stop: string;
  scene?: string;
  /** Its capture, for guided_playtest_capture. */
  capture?: string;
};

/** One string of a grouped problem, such as a plugin's Japanese. */
export type PlaytestText = {
  pointer?: string;
  line?: number;
  text: string;
  reach?: string;
  evidence?: string;
  seen?: PlaytestSeen;
};

export type PlaytestFix = "text-qa" | "translate" | "plugin-files" | "game";

export type PlaytestProblem = {
  /** The game stops, Japanese shows, text doesn't fit, or a name or code is lost. */
  kind: "crash" | "japanese" | "fit" | "codes";
  /** Which check found it. */
  check: string;
  /** Game-relative path, or empty when the tour saw it with no file. */
  file: string;
  note: string;
  /** The task that fixes it; game means the game's own code or data. */
  fix: PlaytestFix;
  pointer?: string;
  line?: number;
  plugin?: string;
  text?: string;
  original?: string;
  /** Strings a grouped problem covers. */
  count?: number;
  reach?: string;
  evidence?: string;
  window?: string;
  rows?: number;
  codes?: string[];
  reaches?: Record<string, number>;
  /** Its first strings. */
  texts?: PlaytestText[];
  seen?: PlaytestSeen;
  /** The previous playtest did not find it. */
  new?: boolean;
  /** Where text QA stands on a problem it corrects: in its review now, reviewed, waiting for QA to run again, or outside the lines its focus holds. */
  review?: "reviewing" | "reviewed" | "waiting" | "outside";
};

export type PlaytestStop = {
  id: string;
  title?: string;
  status: "done" | "failed" | "skipped" | "not-reached" | "running";
  note?: string;
};

export type PlaytestCoverage = {
  stops: PlaytestStop[];
  reached: number;
  messages: number;
  choices: number;
  battle_lines: number;
  /** Screens the tour opened. */
  scenes: number;
};

/** Against the playtest before it: problems fixed, and problems new. */
export type PlaytestSince = {
  fixed: number;
  new: number;
};

/** The latest release playtest of the game. */
export type PlaytestState = {
  /** The game's data and plugins are as it played them. */
  current: boolean;
  problems: PlaytestProblem[];
  /** What the playtest could not reach or read. */
  gaps: string[];
  report?: string;
  finished_at?: string;
  seconds?: number;
  /** The tour ran; false when only the files were checked. */
  played?: boolean;
  complete?: boolean;
  coverage?: PlaytestCoverage;
  since?: PlaytestSince;
  unreadable?: string;
  /** Nothing plays the game, the latest report is of the game as it is, and no text problem waits for QA; a report that could not play settles it once no crash stops it. MV/MZ's QA task finishes then. */
  settled: boolean;
  /** Crashes that stop the game before the playtest can play it, which the assistant fixes; none once it played. */
  stopping: number;
  /** Text problems in a current report that wait for QA's next round. */
  waiting: number;
};

export type PlaytestOperation = {
  id: string;
  status: string;
  message: string;
};

export type LayoutProbe = {
  title: string;
  /** Every row shows, with the check's headroom spare after the widest line. */
  fits: boolean;
  /** Pixels the widest line takes. */
  widest: number;
  /** Pixels the window gives a line. */
  room: number;
  /** Pixels left after the widest line. */
  spare?: number;
  /** Whole characters left after the widest line. */
  spareCharacters?: number;
  /** The most characters that keep the headroom spare. */
  suggested?: number;
  lines: number;
  /** Rows the window shows. */
  rows: number;
  /** The capture's file. */
  capture?: string;
};

export type FallbackGlyph = {
  character: string;
  code: string;
  /** How often the game's text holds it. */
  count: number;
  /** Characters the fitter counts it as. */
  counted: number;
  /** Pixels the game's message window draws it. */
  pixels?: number;
  /** Characters the game's message window draws it as. */
  drawn?: number;
};

/** The game's main font and the characters of its text it lacks. */
export type LayoutFallback = {
  font?: string;
  fallbackFonts?: string;
  /** Why the font's characters were not read. */
  unread?: string;
  glyphs?: FallbackGlyph[];
  /** Lacking characters past the listed ones. */
  more?: number;
};

/** English shown at given widths in the game's own windows. */
export type LayoutCheck = {
  operation?: PlaytestOperation;
  finished_at?: string;
  widths?: Record<string, number>;
  probes?: LayoutProbe[];
  /** Characters each width keeps spare. */
  headroom?: number;
  fallback?: LayoutFallback;
  missing?: Record<string, string>[];
  unavailable?: string;
};

export type PlaytestFixCheck = {
  finished_at: string;
  /** Problems of the last playtest the play with the fixes no longer found. */
  fixed: number;
  new: number;
  /** Why the fixes stayed out of the game. */
  reason?: string;
  /** The batch that wrote them, which History restores. */
  publication?: string;
};

/** The plugin that carries the assistant's fixes for the game's own code. */
export type PlaytestFixes = {
  /** The working copy the assistant edits. */
  file: string;
  /** The game has the working copy as it is, and its main.js loads it. */
  in_game: boolean;
  /** The game's main.js loads fixes other than the working copy, such as an older copy. */
  other_in_game?: boolean;
  check?: PlaytestFixCheck;
};

/** Where the release playtest stands, for the assistant's project helper. */
export type PlaytestStatus = {
  current: boolean;
  finished_at: string;
  /** Problems by the task that fixes them. */
  problems: Record<string, number>;
  /** Problems in translated text a complete QA task does not hold, for QA's next round. */
  waiting: number;
  /** The final check's playtest is done; QA's task finishes then. */
  settled: boolean;
  /** Problems the tour saw on screen. */
  seen: number;
  gaps: number;
  /** Stops reached, as 'done of total'. */
  reached: string;
  /** The step to run next. */
  next: string;
  /** Saved stops every run visits after the standard tour. */
  stops: number;
  fixes: PlaytestFixes;
  operation?: PlaytestOperation;
  /** The saved report file. */
  report?: string;
  layout?: LayoutCheck;
};

export type PlaytestCapture = {
  /** A data URL of the JPEG. */
  url: string;
};

export type TextMisfit = {
  file: string;
  /** The text's JSON pointer in the file. */
  pointer: string;
  /** Why it does not fit, such as needs 5 rows; its window shows 4. */
  reason: string;
};

export type TextFitState = {
  pending: boolean;
  /** Why a pending fit waits on the game's Git checkout, such as a game update's unfinished merge, or empty. */
  waiting: string;
  job: string | null;
  /** The first texts the newest fit could not fit even wrapped again, while the game holds its text: until new widths or another write. */
  misfits: TextMisfit[];
  misfit_count: number;
};

export type Readiness = {
  publications: PublicationStatus[];
  /** Every text batch restored since it was applied, by id, so History marks its row undone. */
  restored: string[];
  qa: QaState;
  playtest: PlaytestState;
  outputs: string[];
  applied: string[];
  unapplied: string[];
  runtime_edited: string[];
  text_fit: TextFitState;
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
  batchUnavailable: string;
  ready: boolean;
  enabled: boolean;
};

/** One Translate task's share of the whole game's estimate. */
export type FullEstimateTask = {
  phase: "database" | "dialogue" | "advanced";
  files: number;
  noSources: boolean;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  liveCost: number;
  batchCost: number;
  batchMaxCost?: number;
  promptCache: boolean;
  approximateInput: boolean;
  unestimatedThinking: boolean;
};

export type FullEstimateResult = {
  model: string;
  batchSupported: boolean;
  tasks: FullEstimateTask[];
};

/** Where one task of a working whole-game estimate stands. */
export type FullEstimateTaskProgress = {
  phase: "database" | "dialogue" | "advanced";
  state: "waiting" | "starting" | "estimating" | "counting" | "done";
  current: number;
  total: number;
  took: number | null;
};

/** Where a working whole-game estimate stands: copying the game's text
before any task, then each task with files to estimate, in order. */
export type FullEstimateProgress = {
  copying: boolean;
  tasks: FullEstimateTaskProgress[];
};

/** Context's whole-game cost estimate: the newest attempt's state and the
newest saved result, current while every task's inputs are unchanged. */
export type FullEstimate = {
  status: "none" | "working" | "complete" | "failed" | "stopped";
  message: string;
  started: string | null;
  progress: FullEstimateProgress | null;
  stopping: boolean;
  result: FullEstimateResult | null;
  finished: string | null;
  took: number | null;
  current: boolean | null;
};

export type GuidedState = {
  eventText: EventTextState;
  fullEstimate: FullEstimate;
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

export type ShowTextHeader = {
  faceName: string;
  faceIndex: number;
  name: string;
};

export type HeaderFlag = {
  kind: "face" | "self-address" | "pronoun" | "sound-effect" | "unnamed-line";
  file: string;
  pointer: string;
  faceName: string;
  faceIndex: number;
  name: string;
  text: string;
  evidence: string;
  decision: "fixed" | "kept" | null;
  reason: string;
  fixedTo: ShowTextHeader | null;
};

export type HeaderCheck = {
  total: number;
  fixed: number;
  kept: number;
  flags: HeaderFlag[];
};

export type SpeakerScan = {
  job: Job | null;
  available: boolean;
  current: boolean;
  names: string[];
  actorNames: Record<string, string>;
  variableActorIds: Record<string, number>;
  headers: HeaderCheck | null;
  files: number;
  path: string | null;
  savedAt: string | null;
  issue: string;
};

export type PublicationChange = {
  path: string;
  destination: string;
  /** None for a file the batch adds. */
  before: string | null;
  /** None for a file the batch takes out. */
  after: string | null;
  size: number;
  later_edits: boolean;
  task?: Phase;
  diff?: string;
  truncated?: boolean;
  before_text?: string;
  after_text?: string;
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
  model: string;
  connection: string;
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

export type GuidedAction =
  | "start"
  | "git_setup"
  | "release_patch"
  | "refresh_sources"
  | "export_selected"
  | "runtime_restore"
  | "runtime_undo"
  | "qa_apply"
  | "qa_undo"
  | "prepare_game"
  | "format_data"
  | "format_plugins"
  | "gameupdate"
  | "import"
  | "ace_decrypt"
  | "ace_extract"
  | "ace_pack"
  | "qa_prepare"
  | "qa_status"
  | "release_playtest"
  | "playtest_fix"
  | "layout_capture"
  | "label_capture"
  | "playtest_install"
  | "playtest_status"
  | "playtest_apply"
  | "inspector_install"
  | "inspector_remove"
  | "forge_install"
  | "forge_remove"
  | "editors"
  | "release"
  | "reference_add"
  | "reference_pair"
  | "reference_remove"
  | "reference_build"
  | "images_status";

export type ActionFamily =
  | "run"
  | "lifecycle"
  | "native"
  | "apply"
  | "text"
  | "preparation"
  | "background"
  | "helper"
  | "engine"
  | "retired";

/** An action's row in the registry, as the renderer reads it. */
export type ActionView = {
  label: string;
  family: ActionFamily;
  restorable: boolean;
  reports_outcome: boolean;
  step?: string;
  counterpart?: GuidedAction;
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
  action: GuidedAction;
  paths: string[];
  confirmation: boolean;
  options: Record<string, unknown>;
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

/** Why a release ZIP cannot be written to the chosen path, or empty, and
whether the archive name alone or the whole path is at fault. */
export type ReleaseDestination = {
  error: string;
  field: "" | "name" | "path";
};

export type TranslationOptions = {
  mode: "agent" | "live" | "batch";
  instructions: string;
  include_images: boolean;
  include_glossary_base: boolean;
  install_forge: boolean;
  thorough_investigation: boolean;
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
  batch_input?: number;
  batch_output?: number;
  batch_factor?: number | null;
};

export type TranslationQuote = {
  requests: number;
  units: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  live_cost: number;
  batch_cost: number | null;
  batch_cost_reused?: number;
  cache_read_tokens?: number;
  cacheable_tokens?: number;
  unestimated_thinking_tokens?: boolean;
  thinking_effort?: string;
  price_rules?: number;
  model: string;
  provider: string;
  basis: string;
  rates: QuoteRates;
};

export type TranslationBatch = {
  id: string;
  state: string;
  requests: number;
  api_status?: string;
  counts?: Record<string, number>;
  cancel_error?: string;
};

export type TranslationIssue = {
  id: string;
  index: number;
  state: string;
  message: string;
};

/** A run's request in plan order, for choosing one by its ID or state. */
export type RunRequestState = {
  id: string;
  state: string;
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
  target?: string | null;
  label: string;
  status: string;
  message: string;
  created: string;
  updated: string;
  mode?: "agent" | "live" | "batch" | null;
  quote: TranslationQuote | null;
  approval_token: string;
  approved: boolean;
  app_approved_at: string | null;
  settings_changed?: boolean;
  pricing_changed?: boolean;
  result: Record<string, unknown> | null;
  usage: Record<string, number>;
  usage_cost?: number | null;
  counts: Record<string, number>;
  units: number;
  accepted_units: number;
  declined_units: number;
  finishes: string | null;
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
  asset_update_applied: boolean;
  asset_manifest_available: boolean;
  asset_baseline_repair_needed: boolean;
  applied_update_version: string | null;
  preserve_game_files: boolean;
  available_original_refs: string[];
};

export type StartedOver = {
  at: string;
  archive: string;
};

export type DeliveryRecord = {
  path: string;
  commit: string;
  game_version: string;
  updater_stamp: boolean;
  files?: number;
};

export type VersionUpdate = {
  version: string;
  complete: boolean;
};

/** Saved lifecycle evidence; further keys are internal to the backend,
such as the backup records projects set up before their original files
were kept in Git still hold. */
export type Lifecycle = {
  version: number;
  delivery?: DeliveryRecord;
  incoming_version?: string;
  version_update?: VersionUpdate;
  discarded_release?: string;
  started_over?: StartedOver;
  [key: string]: unknown;
};

export type ConnectionSummary = {
  name: string;
  model: string;
};

export type ScopeRuleCount = {
  by: "tool" | "assistant";
  kind: string;
  field: string;
  reason: string;
  file?: string;
  values?: number;
  runs: number;
};

export type UncoveredField = {
  kind: string;
  field: string;
  runs: number;
};

/** The census's lines of Japanese punctuation without letters that no
rule sets aside, in runs, and how many units hold, which DazedTL writes
without a request; outside coverage. */
export type UnsentCoverage = {
  runs: number;
  extracted: number;
};

/** How the tool's census of the game's Japanese text is covered, in
Japanese runs: extracted, set aside by a rule, or not extracted. */
export type Coverage = {
  runs: number;
  extracted: number;
  set_aside: number;
  uncovered: number;
  untraced: number;
  unit_runs: number;
  rules: ScopeRuleCount[];
  stale: boolean;
  source: "tool" | "assistant_dump";
  needs_dump: string[];
  unreadable: number;
  uncovered_fields: UncoveredField[];
  unsent?: UnsentCoverage;
  checked_at?: string;
};

export type GameUpdateValues = {
  forge: Forge;
  host: string;
  owner: string;
  repo: string;
  branch: string;
};

/** Where a game's gameupdate/patch-config.txt stands.

absent: the game has no GameUpdate; unconfigured: no owner in Settings;
needs_repo: the game's repository is unknown; pending: DazedTL writes it
next; edited: changed after DazedTL wrote it, with other values; ready;
unavailable: its status could not be read (see message).
 */
export type GameUpdateStatus = {
  state:
    | "absent"
    | "unconfigured"
    | "needs_repo"
    | "pending"
    | "edited"
    | "ready"
    | "unavailable";
  message: string;
  repo: string;
  suggested: string;
  values: GameUpdateValues | null;
  file: GameUpdateValues | null;
  placeholder: boolean;
  differences: ("forge" | "host" | "owner" | "repo" | "branch")[];
  overrides: ("forge" | "host" | "owner" | "branch")[];
  remote: string;
};

/** The Assistant-led Release options the user last chose. */
export type AssistantReleaseForm = {
  kind: "game" | "patch";
  name: string;
  names: ReleaseNames;
  directory: string;
};

export type AssistantRelease = {
  form: AssistantReleaseForm;
  artifacts: ReleaseArtifact[];
};

/** The review of an Assistant-led release ZIP, and the plan its build
runs. */
export type ReleasePreview = {
  action: "release" | "release_patch";
  label: string;
  destination: string;
  files: number;
  paths: string[];
  package: PackageSummary;
  overwrite: boolean;
  game_version: string | null;
  plan: string;
  sha256: string;
};

export type TranslationState = ProjectOptions & {
  engine: string;
  legacyRun: LegacyRun | null;
  projectId: string;
  drafts: TranslationDrafts;
  documents: Documents;
  progress: TranslationProgress | null;
  assistantSeenAt: string | null;
  coverage: Coverage | null;
  git: GitStatus | null;
  gameUpdate: GameUpdateStatus;
  lifecycle: Lifecycle;
  release: AssistantRelease | null;
  originalsRecorded: boolean;
  jobs: TranslationJob[];
  active: boolean;
  warnings: string[];
  checkoutIssue: string;
  statusText: string;
  providerEnabled: boolean;
  connection: ConnectionSummary | null;
  batchUnavailable: string;
  legacyAvailable: boolean;
};

export type UpdateTask = {
  version: string;
  prompt: string;
};

/** The later checkpoint to undo first, and the files both changed. */
export type CheckpointBlocker = {
  commit: string;
  title: string;
  files: string[];
};

/** One checkpoint on the translation branch; see
compatibility/checkpoint_history.py. */
export type Checkpoint = {
  commit: string;
  title: string;
  group: string;
  time: string;
  files: number;
  names: string[];
  kind: "change" | "setup" | "update";
  release: string;
  current: boolean;
  taken_out_by: string;
  restorable: boolean;
  blocker: CheckpointBlocker | null;
};

export type CheckpointVersion = {
  version: string;
  current: boolean;
  checkpoints: Checkpoint[];
};

export type CheckpointTimeline = {
  version: string;
  outside: string[];
  versions: CheckpointVersion[];
  backups: string | null;
};

export type CheckpointTextLine = {
  kind: "edited";
  before: string | null;
  translation: null;
  after: string | null;
};

export type CheckpointFileText = {
  path: string;
  to_translate: number;
  replaced: number;
  kept: number;
  edited: number;
  lines: CheckpointTextLine[];
  more: number;
};

export type CheckpointText = {
  to_translate: number;
  replaced: number;
  kept: number;
  edited: number;
  files: CheckpointFileText[];
};

export type CheckpointFileChange = {
  path: string;
  change: "Added" | "Removed" | "Changed";
  result: string;
};

export type CheckpointChanges = {
  title: string;
  group: string;
  time: string;
  file_changes: CheckpointFileChange[];
  text: CheckpointText;
};

/** How a release lines up with the game as one kind; see the engine's
util/version_update/release_layout.py. */
export type ReleaseLayout = {
  kind: "game" | "patch";
  source: string;
  target: string;
  files: number;
  replaced: number;
  outside: number;
  left_out: string[];
  game_files: number;
  covered: number;
};

export type ReleaseInspection = {
  detected: "game" | "patch";
  version: string;
  game: ReleaseLayout;
  patch: ReleaseLayout;
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

/** Whether the game's main font draws U+00A0, and its file; when that is
unknown, why the font was not read. See engine/util/word_spacing.py. */
export type NbspCoverage = {
  drawn: boolean | null;
  font?: string;
  fallbackFonts?: string;
  unread?: string;
};

export type WordSpacing = {
  rule: string;
  nbsp: NbspCoverage;
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
  index?: number;
  kept?: string[];
  total: number;
  request: PreparedRequest;
  result: RequestResult | null;
};

export type PreparedHandoff = {
  handoff: string;
  path: string;
};

/** Where the run's translations were written by line ID; counts only. */
export type TranslationResults = {
  path: string;
  translated: number;
  missing: Record<string, number>;
};

export type SourceLanguage = "Japanese" | "English";

export type PreferenceValues = {
  language: string;
  model: string;
  sourceLanguage: SourceLanguage;
};

export type EffortLevel =
  "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

export type ModelOptions = {
  entriesPerRequest: "" | number | null;
  batchInputTokens?: number | null;
  maxOutputTokens?: number | null;
  thinkingEffort?: EffortLevel | null;
  pricing: "automatic" | "custom";
  inputRate: "" | number | null;
  outputRate: "" | number | null;
  batchPricing?: "automatic" | "custom";
  batchInputRate?: "" | number | null;
  batchOutputRate?: "" | number | null;
};

export type EffortOption = {
  value: EffortLevel | null;
  label: string;
};

export type EffortCheckLevel = {
  value: EffortLevel;
  label: string;
  sends: string;
};

export type EffortCheckResult = {
  value: EffortLevel;
  label: string;
  passed: boolean;
  message: string;
  checkedAt: string;
};

/** A model whose efforts nothing describes, on a connection whose server
may take `reasoning_effort` (settings/effort checkable): a level is
offered once a check on this connection passed it. */
export type EffortCheck = {
  levels: EffortCheckLevel[];
  results: EffortCheckResult[];
  replyTokens: number;
  local: boolean;
};

/** The efforts Settings offers for a model (settings/effort describe):
the provider default first, then each level the model takes. */
export type ThinkingEffort = {
  options: EffortOption[];
  source?: string;
  check?: EffortCheck;
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
  thinkingEffort?: ThinkingEffort;
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

export type Forge = "gitlab" | "forgejo" | "github";

/** Where players' GameUpdate downloads patches; each game adds its repository. */
export type GameUpdateDefaults = {
  forge: Forge;
  host: string;
  owner: string;
  branch: string;
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
  gameUpdate: GameUpdateDefaults;
  draft?: SettingsDraft;
};

export type Provider =
  | "openai"
  | "openrouter"
  | "anthropic"
  | "gemini"
  | "mistral"
  | "kimi"
  | "deepseek"
  | "custom";

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

/** Unfinished saved runs that need a connection to resume or collect. */
export type ConnectionUsage = {
  unfinished: number;
};

export type ImageDiscoveryScope = "remaining" | "all" | "folders" | "selected";

export type ImageEntryMode = "discovery" | "manual" | "findings" | "review";

export type ImageClassification =
  | "recommended"
  | "uncertain"
  | "no_text"
  | "already_english"
  | "sound_effects"
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
  viewedImage?: string;
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
  outdated: boolean;
  candidateHash: string | null;
  state: string;
  classification: ImageClassification;
  reason: string;
  blockedReason: string;
  heldReason: string;
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
  needsReview: number;
  blocked: number;
  applied: number;
  selected: number;
  selectedReady: number;
  selectedBlocked: number;
  selectedNotPrepared: number;
  selectedApplied: number;
  selectedSkipped: number;
  selectedNeedsReview: number;
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
  rejected?: string;
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
  decoded?: boolean;
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
  /** Whether every image in the folder has a finding, is in the game or is excluded. */
  investigated: boolean;
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

export type ImageForeignWork = ForeignWork & {
  examined: number;
  edited: number;
};

export type ImageDraft = {
  selection: string[];
  view: ImageView;
  discoveryScope: ImageDiscoveryScope;
  folders: string[];
  imageRoot?: string;
};

/** How many images each view lists within the same folder and search. */
export type ImageViewCounts = {
  all: number;
  list: number;
  uncertain: number;
  ready: number;
  applied: number;
};

export type ImageList = {
  items: ImageAsset[];
  total: number;
  selectedMatched: number;
  offset?: number;
  limit: number;
  views?: ImageViewCounts;
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

export type ImageTextShadow = {
  color: Colour;
  dx?: number;
  dy?: number;
  spread?: number;
  blur?: number;
};

export type ImageTextGlow = {
  color: Colour;
  spread?: number;
  blur?: number;
};

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
  shadow?: ImageTextShadow | null;
  glow?: ImageTextGlow | null;
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
  changed: boolean;
  originalUrl: string;
  candidateUrl: string;
  error: string;
  engine: string;
  notes: ImageTextNote[];
};

export type ImageFont = {
  id: string;
  label: string;
  origin: "game" | "installed";
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
  quote: ImageNativeJob | null;
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

export type ImageAssistantCounts = {
  indexed: number;
  notExamined: number;
  recommended: number;
  uncertain: number;
  listed: number;
  ready: number;
  needsReview: number;
  skipped: number;
  applied: number;
};

/** Where an Assistant-led project's Images flow stands after a step. */
export type ImageAssistantStepResult = {
  next: "scan" | "investigate" | "translate" | "apply" | "done";
  scan: string;
  investigation: string;
  translation: string;
  problems: string[];
  counts: ImageAssistantCounts;
  task: string;
  report: string;
  applied: string[];
};

export type PluginFileReview = {
  path: string;
  destination: string;
  beforeHash: string;
  afterHash: string;
  originalHash: string;
  candidateHash: string;
  backup?: string;
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
  restorable: boolean;
  /** Restores in one click by undoing its checkpoint, or, interrupted, by putting its files back from the checkpoint before it; else by a reviewed restore of the backups it saved. */
  undo: boolean;
  restoreIssue?: string;
  restores?: string;
  applies?: string;
};

export type PluginCounts = {
  files: number;
  investigated: number;
  textFiles: number;
  translated: number;
  selected: number;
  ready: number;
  shortened: number;
  applied: number;
  labels: number;
};

export type PluginUnreadable = {
  path: string;
  issue: string;
  kept: boolean;
};

/** A label Text QA's latest capture found too long for the screen that QA
holds no line of, and where it stands here: waiting for the assistant,
shortened and ready to apply or applied, kept as it is, or found in no
plugin file. */
export type PluginLabel = {
  text: string;
  title: string;
  state: "waiting" | "ready" | "applied" | "kept" | "elsewhere";
  reason?: string;
};

export type PluginState = {
  projectId: string;
  supported: boolean;
  limitation: string;
  scripts: boolean;
  scanned: boolean;
  counts: PluginCounts;
  unreadable: PluginUnreadable[];
  originalIssue: string;
  receipts: PluginReceipt[];
  activeRequest: string;
  awaiting: boolean;
  labels: PluginLabel[];
};

/** How a label of the shortening request shows on its screen captured
with the working copies served in place of the game's files. */
export type PluginLabelFit = {
  text: string;
  /** The screen QA's capture found it on. */
  title: string;
  /** The text that screen should draw now. */
  shows: string[];
  /** Whether the game draws that text in full. */
  fits: boolean;
  /** What the game draws there. */
  note: string;
  /** The screen's capture file. */
  capture?: string;
  /** The share of the width it needs the game drew it in. */
  squeezed?: number;
  /** Its end is cut off at its window's edge. */
  clipped?: boolean;
};

/** The latest capture of the shortening request's labels on their
screens, for the assistant's project helper. */
export type PluginCapture = {
  requestId: string;
  operation?: PlaytestOperation;
  finishedAt?: string;
  /** It served the request's working copies as they are now. */
  current?: boolean;
  labels?: PluginLabelFit[];
  /** Why DazedTL couldn't run the game. */
  unavailable?: string;
  /** The step to take next. */
  next: string;
};

export type PluginForeignWork = ForeignWork & {
  investigated: number;
  translated: number;
};

export type PluginActionResult = {
  state?: PluginState;
  text?: string;
  preview?: PluginPreview;
  receipt?: PluginReceipt;
  completed?: number;
  blocked?: PluginBlocked[];
  message?: string;
  request?: string;
  requestId?: string;
  stage?: string;
};

export type Screen =
  "project" | "translation" | "guided" | "manual" | "settings";

export type TranslationMethod = "guided" | "len";

export type ProjectOperation = {
  label: string;
  status: string;
  message: string;
};

/** The background record of the open game's original files, while it
runs or after it ended without one. */
export type OriginalRecord = {
  running: boolean;
  message: string;
  error: string;
  stopped: boolean;
};

/** The languages a project's game translates between. */
export type GameLanguages = {
  source: SourceLanguage;
  target: string;
  characters: boolean;
  sourceTag: string | null;
  targetTag: string | null;
};

export type Project = {
  id: string;
  name: string;
  source: string;
  engine: string;
  engine_label?: string;
  method: TranslationMethod | null;
  phase: string;
  available?: boolean;
  status?: string;
  detail?: string;
  operation?: ProjectOperation;
  originals?: OriginalRecord;
  next_label?: string;
  languages?: GameLanguages;
};

export type AppState = {
  project: Project | null;
  recent: Project[];
  screen: Screen;
  running: boolean;
  provider_ready: boolean;
  observing: boolean;
};

export type AssistantTaskKind =
  | "names"
  | "line_widths"
  | "event_text"
  | "plugins"
  | "image_discovery"
  | "image_editing"
  | "qa"
  | "walkthrough";

/** The newest report from a validator the assistant runs on its results. */
export type AssistantTaskValidation = {
  savedAt: string;
  passed: boolean;
  errors: number;
};

/** A task copied to a coding assistant; each feature keeps its results. */
export type AssistantTaskRecord = {
  kind: AssistantTaskKind;
  requestId: string;
  copiedAt: string;
  resultAt: string | null;
  dismissed: boolean;
  finishedAt?: string | null;
  validation?: AssistantTaskValidation | null;
};

export type WorkspaceSnapshot = {
  application: AppState;
  assistantTasks: AssistantTaskRecord[];
  guided: GuidedState | null;
  translation: TranslationState | null;
  translationError: string;
  images?: ImageManagerState | null;
  imagesError?: string;
  imagesForeign?: ImageForeignWork;
  plugins?: PluginState | null;
  pluginsError?: string;
  pluginsForeign?: PluginForeignWork;
};

export type ProjectRequest = {
  project_id: string;
};

export type LocateProjectRequest = {
  project_id: string;
  source: string;
};

export type AssistantTaskRequest = {
  project_id: string;
  kind: AssistantTaskKind;
};

export type AssistantTaskDismissed = {
  kind: AssistantTaskKind;
};

export type ActionRequest = {
  project_id: string;
  action: string;
  options?: Record<string, unknown>;
};

export type ForeignWorkRequest = {
  project_id: string;
  binding: string;
};

export type PluginsContinueRequest = {
  project_id: string;
  request_id: string;
};

export type PluginsCaptureRequest = {
  project_id: string;
  /** Capture the shortening request's working copies as they are now first. */
  start?: boolean;
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
  fix_headers?: boolean;
};

export type TranslationIdentifyRequest = {
  project_id: string;
  engine: string;
  evidence_file: string;
};

export type TranslationImagesRequest = {
  project_id: string;
  step: "status" | "scan" | "investigate" | "translate" | "apply";
  root?: string;
};

export type TranslationQaRequest = {
  project_id: string;
  step:
    | "status"
    | "report"
    | "prepare"
    | "apply"
    | "checkpoint"
    | "undo"
    | "reapply"
    | "choose";
  findings?: string[];
  question?: string;
  choice?: "keep" | "use";
  since?: string;
  everything?: boolean;
};

export type TranslationQaCheckRequest = {
  project_id: string;
  /** Hit ID to a one-line reason the line is right, kept while the hit stays the same. */
  answers?: Record<string, string>;
};

export type TranslationPlaytestRequest = {
  project_id: string;
  step: "status" | "report" | "run" | "fix" | "checkpoint" | "layout";
  /** Places only the game's events reach, played after the standard tour; they replace the saved stops every later run visits. */
  stops?: Record<string, unknown>[];
  /** With layout: characters per line as width, faceWidth and listWidth, and messageRows. */
  widths?: Record<string, number>;
};

export type PlaytestCaptureRequest = {
  project_id: string;
  name: string;
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

export type SaveDocumentsRequest = {
  project_id: string;
  documents: Documents;
};

export type TranslationReleaseRequest = {
  project_id: string;
  folder: string;
};

export type InputPathRequest = {
  project_id: string;
  input_path: string;
};

export type TranslationOrganizeRequest = {
  project_id: string;
  input_path: string;
  complete?: boolean;
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

/** A run's request by its index, or by its request_sha256, which also
reaches an earlier request whose lines organize kept for the run. */
export type RunRequestChoice = {
  project_id: string;
  run_id: string;
  index?: number;
  request_sha256?: string;
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

export type TranslationDeclineRequest = {
  project_id: string;
  run_id: string;
  batch_id: string;
  reason: string;
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

export type CheckpointRequest = {
  project_id: string;
  action: "checkpoint_back" | "checkpoint_undo" | "checkpoint_copy";
  commit: string;
  destination?: string;
};

export type CheckpointChangesRequest = {
  project_id: string;
  commit: string;
};

export type ReleaseFormRequest = {
  project_id: string;
  value: AssistantReleaseForm;
};

export type ReleaseDestinationRequest = {
  project_id: string;
  output: string;
  kind: "game" | "patch";
};

export type ReleasePreviewRequest = {
  project_id: string;
  kind: "game" | "patch";
  output: string;
};

export type ReleaseBuildRequest = {
  project_id: string;
  kind: "game" | "patch";
  plan: string;
  sha256: string;
};

export type StartOverRequest = {
  project_id: string;
  keep_context: boolean;
};

export type TranslationAttachBatchRequest = {
  project_id: string;
  run_id: string;
  index: number;
  provider_job_id: string;
};

export type NoParams = Record<string, never>;

/** How many working files were checked again for outside edits. */
export type Rechecked = {
  checked: number;
};

export type OpenProjectRequest = {
  source: string;
};

export type NavigateRequest = {
  screen: Screen;
};

export type ProjectMethodRequest = {
  project_id: string;
  method: TranslationMethod;
};

export type ProjectLanguagesRequest = {
  project_id: string;
  source: SourceLanguage;
  target: string;
};

/** Why a game's languages can't change any more; empty while they can. */
export type LanguagesLock = {
  reason: string;
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

export type EffortCheckRequest = {
  connection_id: string;
  model: string;
  level: EffortLevel;
};

export type ConnectionSaveRequest = ConnectionInput & {
  revision: number;
};

export type ConnectionUsageRequest = {
  connection_id: string;
};

export type ConnectionRemoveRequest = {
  revision: number;
  connection_id: string;
  unfinished: number;
};

export type GuidedPhaseSelectRequest = {
  project_id: string;
  phase: Phase;
};

export type GuidedPreviewRequest = {
  project_id: string;
  action: GuidedAction;
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

export type GuidedReleaseDestinationRequest = {
  project_id: string;
  output: string;
  kind: "game" | "patch";
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

export type GuidedEventTextRequestRequest = {
  project_id: string;
  apply?: boolean;
};

export type GuidedEventTextApplyRequest = {
  project_id: string;
  revision: number;
  report_id: string;
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

export type GuidedRequestsRequest = {
  project_id: string;
  run_id: string;
  group?: string | null;
  index?: number | null;
};

export type GuidedPayloadRequest = RunIndexRequest & {
  prepared?: boolean;
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
  /** Only the Database files or Maps & events lines still left in the file. */
  left?: boolean;
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

export type GameUpdateDefaultsRequest = {
  revision: number;
  forge: Forge;
  host: string;
  owner: string;
  branch: string;
};

export type ProjectGameUpdateRequest = {
  project_id: string;
  action: "save" | "keep" | "replace" | "defaults";
  repo?: string;
};

export type RpcContract = {
  workspace_snapshot: { request: NoParams; response: WorkspaceSnapshot };
  workspace_recheck: { request: ProjectRequest; response: Rechecked };
  assistant_task_dismiss: {
    request: AssistantTaskRequest;
    response: AssistantTaskDismissed;
  };
  open_project: { request: OpenProjectRequest; response: AppState };
  select_project: { request: ProjectRequest; response: AppState };
  locate_project: { request: LocateProjectRequest; response: AppState };
  remove_project: { request: ProjectRequest; response: AppState };
  navigate: { request: NavigateRequest; response: AppState };
  project_method: { request: ProjectMethodRequest; response: AppState };
  project_languages: { request: ProjectLanguagesRequest; response: AppState };
  project_languages_lock: { request: ProjectRequest; response: LanguagesLock };
  originals_stop: { request: ProjectRequest; response: AppState };
  settings_get: { request: NoParams; response: Settings };
  settings_save: { request: PreferencesRequest; response: Settings };
  settings_draft: { request: PreferencesRequest; response: Saved };
  settings_revert: { request: ConnectionRequest; response: Settings };
  settings_game_update: {
    request: GameUpdateDefaultsRequest;
    response: Settings;
  };
  connection_save: { request: ConnectionSaveRequest; response: Settings };
  connection_select: { request: ConnectionRequest; response: Settings };
  connection_check: { request: ConnectionRequest; response: Settings };
  connection_effort_check: {
    request: EffortCheckRequest;
    response: ThinkingEffort;
  };
  connection_usage: {
    request: ConnectionUsageRequest;
    response: ConnectionUsage;
  };
  connection_remove: { request: ConnectionRemoveRequest; response: Settings };
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
  guided_save_documents: { request: SaveDocumentsRequest; response: Documents };
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
  guided_payload: { request: GuidedPayloadRequest; response: RunPayload };
  guided_requests: { request: GuidedRequestsRequest; response: RequestPage };
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
  guided_full_estimate: { request: ProjectRequest; response: Job };
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
    request: GuidedEventTextRequestRequest;
    response: EventTextRequest;
  };
  guided_event_text_apply: {
    request: GuidedEventTextApplyRequest;
    response: GuidedPreferences;
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
  guided_release_destination: {
    request: GuidedReleaseDestinationRequest;
    response: ReleaseDestination;
  };
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
  translation_organize: {
    request: TranslationOrganizeRequest;
    response: TranslationJob;
  };
  translation_run: { request: RunRequest; response: TranslationJob };
  translation_request: { request: RunRequestChoice; response: RequestPreview };
  translation_requests: { request: RunRequest; response: RunRequestState[] };
  translation_results: { request: RunRequest; response: TranslationResults };
  translation_backups: { request: ProjectRequest; response: BackupCatalog };
  translation_word_spacing: { request: ProjectRequest; response: WordSpacing };
  translation_update_task: { request: ProjectRequest; response: UpdateTask };
  translation_release: {
    request: TranslationReleaseRequest;
    response: ReleaseInspection;
  };
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
  translation_decline: {
    request: TranslationDeclineRequest;
    response: TranslationJob;
  };
  translation_finish: { request: RunRequest; response: TranslationJob };
  translation_reestimate: { request: RunRequest; response: TranslationJob };
  translation_translator_prompt: {
    request: RunRequest;
    response: PreparedHandoff;
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
  project_start_over: { request: StartOverRequest; response: TranslationJob };
  project_checkpoints: {
    request: ProjectRequest;
    response: CheckpointTimeline;
  };
  project_checkpoint_changes: {
    request: CheckpointChangesRequest;
    response: CheckpointChanges;
  };
  project_checkpoint: { request: CheckpointRequest; response: TranslationJob };
  project_release_form: { request: ReleaseFormRequest; response: Saved };
  project_release_destination: {
    request: ReleaseDestinationRequest;
    response: ReleaseDestination;
  };
  project_release_preview: {
    request: ReleasePreviewRequest;
    response: ReleasePreview;
  };
  project_release_build: {
    request: ReleaseBuildRequest;
    response: TranslationJob;
  };
  project_game_update: {
    request: ProjectGameUpdateRequest;
    response: GameUpdateStatus;
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
  translation_images: {
    request: TranslationImagesRequest;
    response: ImageAssistantStepResult;
  };
  translation_qa: { request: TranslationQaRequest; response: TextQaStatus };
  translation_qa_check: {
    request: TranslationQaCheckRequest;
    response: TextQaCheck;
  };
  guided_qa_report: { request: ProjectRequest; response: QaReport };
  translation_playtest: {
    request: TranslationPlaytestRequest;
    response: PlaytestStatus;
  };
  guided_playtest_capture: {
    request: PlaytestCaptureRequest;
    response: PlaytestCapture;
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
  images_adopt: { request: ForeignWorkRequest; response: ImageActionResult };
  images_start_over: {
    request: ForeignWorkRequest;
    response: ImageActionResult;
  };
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
  plugins_capture: { request: PluginsCaptureRequest; response: PluginCapture };
  plugins_action: { request: ActionRequest; response: PluginActionResult };
  plugins_continue: {
    request: PluginsContinueRequest;
    response: PluginActionResult;
  };
  plugins_task: { request: ProjectRequest; response: PluginActionResult };
  plugins_apply: { request: ProjectRequest; response: PluginActionResult };
  plugins_adopt: { request: ForeignWorkRequest; response: PluginActionResult };
  plugins_start_over: {
    request: ForeignWorkRequest;
    response: PluginActionResult;
  };
};

/** The workflow actions, from backend/dazedtl/actions.py. */
export const ACTIONS = {
  start: {
    label: "Translate",
    family: "run",
    restorable: false,
    reports_outcome: false,
  },
  git_setup: {
    label: "Record game version",
    family: "lifecycle",
    restorable: false,
    reports_outcome: false,
  },
  checkpoint: {
    label: "Save a checkpoint",
    family: "helper",
    restorable: false,
    reports_outcome: false,
  },
  release_patch: {
    label: "Build local patch ZIP",
    family: "lifecycle",
    restorable: false,
    reports_outcome: true,
  },
  refresh_sources: {
    label: "Reload selected files from game",
    family: "lifecycle",
    restorable: false,
    reports_outcome: false,
  },
  export_selected: {
    label: "Apply selected saved outputs",
    family: "apply",
    restorable: false,
    reports_outcome: true,
  },
  runtime_restore: {
    label: "Restore reviewed text batch",
    family: "text",
    restorable: false,
    reports_outcome: false,
  },
  runtime_undo: {
    label: "Undo text batch",
    family: "text",
    restorable: false,
    reports_outcome: false,
  },
  qa_apply: {
    label: "Apply QA corrections",
    family: "text",
    restorable: true,
    reports_outcome: true,
  },
  qa_undo: {
    label: "Undo QA corrections",
    family: "text",
    restorable: true,
    reports_outcome: false,
  },
  prepare_game: {
    label: "Prepare game files",
    family: "preparation",
    restorable: false,
    reports_outcome: false,
  },
  format_data: {
    label: "Format game data",
    family: "native",
    restorable: false,
    reports_outcome: true,
    step: "Format game data",
  },
  format_plugins: {
    label: "Format plugins.js",
    family: "native",
    restorable: false,
    reports_outcome: true,
    step: "Format plugins.js",
  },
  gameupdate: {
    label: "Install GameUpdate",
    family: "native",
    restorable: false,
    reports_outcome: true,
    step: "Create GameUpdate files",
  },
  import: {
    label: "Import selected files",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  ace_decrypt: {
    label: "Decrypt Ace archive",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  ace_extract: {
    label: "Convert Ace data to JSON",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  ace_pack: {
    label: "Pack translated Ace data",
    family: "native",
    restorable: false,
    reports_outcome: true,
  },
  qa_prepare: {
    label: "Prepare or resume translation QA",
    family: "native",
    restorable: false,
    reports_outcome: true,
  },
  qa_status: {
    label: "Refresh translation QA",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  release_playtest: {
    label: "Play the game for the release playtest",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  playtest_fix: {
    label: "Apply playtest fixes",
    family: "native",
    restorable: true,
    reports_outcome: false,
  },
  layout_capture: {
    label: "Show test text in the game's windows",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  label_capture: {
    label: "Show shortened plugin labels in the game",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  playtest_install: {
    label: "Install both playtest plugins",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  playtest_status: {
    label: "Refresh playtest plugins",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  playtest_apply: {
    label: "Apply playtest settings",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  inspector_install: {
    label: "Install TL Inspector",
    family: "native",
    restorable: false,
    reports_outcome: true,
    counterpart: "inspector_remove",
  },
  inspector_remove: {
    label: "Remove TL Inspector",
    family: "native",
    restorable: false,
    reports_outcome: true,
    counterpart: "inspector_install",
  },
  forge_install: {
    label: "Install Forge",
    family: "native",
    restorable: false,
    reports_outcome: true,
    counterpart: "forge_remove",
  },
  forge_remove: {
    label: "Remove Forge",
    family: "native",
    restorable: false,
    reports_outcome: true,
    counterpart: "forge_install",
  },
  editors: {
    label: "Find code editors",
    family: "native",
    restorable: false,
    reports_outcome: true,
  },
  release: {
    label: "Build clean game ZIP",
    family: "native",
    restorable: false,
    reports_outcome: true,
  },
  reference_add: {
    label: "Add DazedTL reference translation",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  reference_pair: {
    label: "Add original / translation reference pair",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  reference_remove: {
    label: "Remove reference registration",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  reference_build: {
    label: "Build exact reference matches",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  images_status: {
    label: "Refresh image readiness",
    family: "native",
    restorable: false,
    reports_outcome: false,
  },
  fit_text: {
    label: "Fit text to the new Line widths",
    family: "background",
    restorable: true,
    reports_outcome: false,
  },
  full_estimate: {
    label: "Estimate the translation cost",
    family: "background",
    restorable: false,
    reports_outcome: false,
  },
  speaker_scan: {
    label: "Scan speaker names",
    family: "background",
    restorable: false,
    reports_outcome: false,
  },
  backup_source: {
    label: "Back up original game",
    family: "retired",
    restorable: false,
    reports_outcome: false,
  },
  use_source_backup: {
    label: "Use the game's saved original",
    family: "retired",
    restorable: false,
    reports_outcome: false,
  },
  glossary_apply: {
    label: "Apply glossary fixes",
    family: "retired",
    restorable: true,
    reports_outcome: false,
  },
} as const satisfies Record<string, ActionView>;

export type ActionName = keyof typeof ACTIONS;

/** A saved request's headings, from backend/dazedtl/engine/util/prompt_pair.py. */
export const REQUEST_HEADINGS = {
  glossary: "Here are glossary entries",
  sfx: "Japanese SFX reference",
  sourceContext: [
    "Preceding Japanese Source Context",
    "Preceding English Source Context",
  ],
  instructions: "Request Instructions:",
} as const;

/** The source languages, from backend/dazedtl/engine/util/languages.py. */
export const SOURCE_LANGUAGES = ["Japanese", "English"] as const;
