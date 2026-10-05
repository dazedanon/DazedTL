export interface PluginOccurrence {
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
  finding?: {
    disposition: string;
    safe: boolean;
    evidence: string;
    reason: string;
  };
  selected: boolean;
  manual?: { selected: boolean; reason: string };
  before: string;
  after: string;
  target: string;
}
export interface PluginRow {
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
}
export interface PluginView {
  mode: "scope" | "working";
  query: string;
  filter: string;
  selectedOnly: boolean;
  currentFile: string;
  offset: number;
}
export interface PluginFileReview {
  path: string;
  destination: string;
  beforeHash: string;
  afterHash: string;
  originalHash: string;
  candidateHash: string;
  backup: string;
  changes: number;
  kind: string;
}
export interface PluginPreview {
  token: string;
  mode: "apply" | "restore";
  files: PluginFileReview[];
  blocked: { path: string; reason: string }[];
  manifest: string;
}
export interface PluginReceipt {
  id: string;
  mode: string;
  saved: string;
  status: string;
  files: PluginFileReview[];
  failure: string;
  conflicts: string[];
  manifest: string;
}
export interface PluginState {
  projectId: string;
  revision: string;
  observationRevision: string;
  supported: boolean;
  limitation: string;
  layout: string;
  source: string;
  view: PluginView;
  counts: {
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
  findings: {
    status: string;
    errors: string[];
    accepted?: number;
    reported?: number;
    expected?: number;
  };
  editing: {
    status: string;
    errors: string[];
    accepted?: number;
    reported?: number;
    expected?: number;
  };
  originalIssue: string;
  originalBackup: string;
  receipts: PluginReceipt[];
  requestPaths: Record<string, string>;
  activeRequest: string;
}
export interface PluginList {
  items: PluginRow[];
  total: number;
  selectedMatched: number;
  offset: number;
  limit: number;
}
export interface PluginDetail extends PluginRow {
  items: PluginOccurrence[];
  total: number;
  checks: Record<string, boolean>;
  resultEvidence: string;
  rendered: string;
  original: string;
  originalHash: string;
}
export interface PluginActionResult {
  state?: PluginState;
  text?: string;
  preview?: PluginPreview;
  receipt?: PluginReceipt;
  completed?: number;
  message?: string;
  request?: string;
  requestId?: string;
  stage?: string;
}
