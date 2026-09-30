export type ErrorCode =
  | "validation"
  | "not_found"
  | "storage"
  | "unavailable"
  | "protocol"
  | "internal";
export class ApiError extends Error {
  constructor(
    public readonly code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
