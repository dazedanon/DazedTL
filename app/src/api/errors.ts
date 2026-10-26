export type ErrorCode =
  | "validation"
  | "not_found"
  | "storage"
  | "unavailable"
  | "protocol"
  | "internal"
  // A write that waits for the record of the game's original files.
  | "recording";
// The refusals that wait for that record, by their text, which is all a
// control keeps of its failure; it shows the record's progress instead.
const recordWaits = new Set<string>();
export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly details?: unknown;
  constructor(code: ErrorCode, message: string, details?: unknown) {
    super(message);
    this.code = code;
    this.details = details;
    this.name = "ApiError";
    if (code === "recording") recordWaits.add(message);
  }
}
/** Whether a failure's text is a write waiting for the original record. */
export const waitsForRecord = (message: string) => recordWaits.has(message);
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
export type RendererFailure = {
  reason: "render" | "error" | "unhandledrejection";
  causes: {
    type: string;
    frames: { file: string; line: number; column: number; function: string }[];
  }[];
};
