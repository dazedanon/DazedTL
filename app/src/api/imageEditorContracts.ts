import type { Job } from "./contracts";

export interface ImageTextStyle {
  background?: string;
  fill?: number[] | null;
  text_color?: number[];
  outline_color?: number[] | null;
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
  [key: string]: unknown;
}
export interface ImageTextBlock {
  id: string;
  box: [number, number, number, number];
  source: string;
  target: string;
  angle: number;
  skip: boolean;
  flags?: string[];
  lines?: unknown[];
  style?: ImageTextStyle;
}
export interface ImageEditorImage {
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
  notes: { blockId: string; ok: boolean; message: string; tight: boolean }[];
}
export interface ImageEditorState {
  revision: string;
  selectedIds: string[];
  images: ImageEditorImage[];
  fonts: { id: string; label: string }[];
  localOcr: { available: boolean; detail: string };
  exchangePath: string;
}
export interface ImageEditorSave {
  assetId: string;
  sourceHash: string;
  candidateHash: string;
  blocks: ImageTextBlock[];
  status: "needs_review" | "confirmed";
}
export interface ImageEditorExport {
  path: string;
  assetIds: string[];
  count: number;
  requestHash: string;
}
export interface ImageEditorActionResult {
  state: ImageEditorState;
  result: Partial<ImageEditorExport> & {
    applied?: number;
    missing?: number;
    empty?: number;
    completed?: string[];
    errors?: Record<string, string>;
  };
}
export interface ImageNativeTranslationState {
  jobs: (Job & {
    imported?: boolean;
    imageConfiguration?: ImageNativeConfiguration;
  })[];
  job:
    | (Job & {
        imported?: boolean;
        imageConfiguration?: ImageNativeConfiguration;
      })
    | null;
  activeId: string | null;
  quote: Job | null;
  quoteCurrent: boolean;
  current: {
    fingerprint: string;
    count: number;
    configuration: ImageNativeConfiguration;
  } | null;
  error: string;
  providerEnabled: boolean;
  batchSupported: boolean;
}
export interface ImageNativeConfiguration {
  model: string;
  language: string;
  endpoint: string;
  entries_per_request: number;
}
export interface ImageNativeTranslationPreview {
  token: string;
  mode: "estimate" | "translate" | "batch";
  count: number;
  assetIds: string[];
  configuration: ImageNativeConfiguration;
  estimate: Record<string, unknown> | null;
  confirmation: boolean;
}
export interface ImageNativeTranslationActionResult {
  state: ImageNativeTranslationState;
  result: {
    path?: string;
    files?: number;
    state?: ImageEditorState;
    result?: ImageEditorActionResult["result"];
  };
}
