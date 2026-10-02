export type ImageDiscoveryScope = "all" | "folders" | "selected";
export type ImageEntryMode = "discovery" | "manual" | "findings" | "review";
export type ImageClassification = "recommended" | "uncertain" | "no_text" | "already_english" | "not_examined" | "excluded";
export interface ImageView {
  query: string;
  status: string;
  folder: string;
  showSelected: boolean;
  tileSize: number;
  scroll: number;
  currentImage?: string;
  workflowMode?: ImageEntryMode;
}
export interface ImageAsset {
  id: string;
  path: string;
  filename: string;
  folder: string;
  sourceHash: string;
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
  finding?: { method?: string; evidence?: string; variants?: string[] } | null;
}
export interface ImageCounts {
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
  [key: string]: number;
}
export interface ImageReportState {
  status: string;
  lastReport?: string | null;
  reportId?: string | null;
  requestId?: string | null;
  message?: string;
  errors?: string[];
  scope?: ImageDiscoveryScope;
  folders?: string[];
  copiedAt?: string;
}
export interface ImageReceipt {
  id: string;
  action?: string;
  created?: string;
  count?: number;
  assets?: { id: string; path?: string; destination?: string }[];
  available?: boolean;
  message?: string;
}
export interface ImageManagerState {
  projectId: string;
  name: string;
  engine: string;
  profile: { id: string; label: string; imageRoot?: string; supported: boolean; reason?: string };
  source: string;
  revision: string;
  observationRevision?: string;
  inventoryRevision: string;
  counts: ImageCounts;
  folders: { path: string; count: number }[];
  selection: string[];
  view: ImageView;
  discovery: ImageReportState;
  editing: ImageReportState;
  receipts: ImageReceipt[];
  warnings: string[];
  editableRoot?: string;
  supported?: boolean;
  job?: { id?: string; status: string; message?: string; current?: number; total?: number; progress?: { current: number; total: number; file?: string } } | null;
}
export interface ImageDraft {
  selection: string[];
  view: ImageView;
  discoveryScope: ImageDiscoveryScope;
  folders: string[];
  imageRoot?: string;
}
export interface ImageList {
  items: ImageAsset[];
  total: number;
  selectedMatched: number;
  offset?: number;
}
export interface ImagePreview {
  token: string;
  action: string;
  assets: { id: string; path: string; destination: string; sourceHash: string; candidateHash: string }[];
  blocked: { id: string; path: string; reason: string }[];
  included: number;
  count: number;
  unchanged: number;
  backups?: string[] | boolean;
  expires?: string | number;
}
export interface ImageActionResult {
  state: ImageManagerState;
  text?: string;
  requestId?: string;
  preview?: ImagePreview;
  message?: string;
}
export interface ImagePixels {
  url: string;
  sha256: string;
  width: number;
  height: number;
  mode: string;
}
