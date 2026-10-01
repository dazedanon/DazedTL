export type ErrorCode =
  | "validation"
  | "not_found"
  | "storage"
  | "unavailable"
  | "protocol"
  | "internal";
export class ApiError extends Error {
  readonly code: ErrorCode;
  constructor(code: ErrorCode, message: string) {
    super(message);
    this.code = code;
    this.name = "ApiError";
  }
}
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
