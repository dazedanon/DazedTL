import type { RunPayload } from "../../api/contracts";

/** Failure evidence belongs to the selected attempt, beside its reply or payload. */
export function RequestFailure({ payload }: { payload: RunPayload }) {
  const failed = payload.state === "failed" || payload.state === "rejected";
  if (payload.unused || payload.error == null && !failed) return null;
  const error = payload.error;
  const record = error && typeof error === "object" ? error as Record<string, unknown> : null;
  const message = typeof error === "string" ? error : typeof record?.message === "string" ? record.message
    : error != null ? JSON.stringify(error, null, 2)
    : payload.state === "rejected" ? "This response failed validation. No detailed reason was retained."
    : "This request failed. No detailed reason was retained.";
  const metadata = [record?.code, record?.param].filter(value => typeof value === "string" && value);
  return <div className="request-failure">
    <p className="translation-error">{message}</p>
    {!!metadata.length && <small className="muted">{metadata.join(" · ")}</small>}
  </div>;
}
