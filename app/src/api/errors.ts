export type ErrorCode =
  | "validation"
  | "not_found"
  | "storage"
  | "unavailable"
  | "protocol"
  | "internal";
export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly details?: unknown;
  constructor(code: ErrorCode, message: string, details?: unknown) {
    super(message);
    this.code = code;
    this.details = details;
    this.name = "ApiError";
  }
}
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
