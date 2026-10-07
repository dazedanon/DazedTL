import type { RunPayload } from "../../api/contracts";

/** Failure evidence belongs to the selected attempt, beside its reply or payload. */
export function RequestFailure({
  payload,
  details = false,
}: {
  payload: RunPayload;
  details?: boolean;
}) {
  const failed = payload.state === "failed" || payload.state === "rejected";
  if (payload.unused || (payload.error == null && !failed)) return null;
  const error = payload.error;
  const record =
    error && typeof error === "object"
      ? (error as Record<string, unknown>)
      : null;
  // The lines of a failed request are not lost; say what happens to them.
  // A replaced attempt's lines came from the later response instead.
  const kept = failed && record?.code !== "replaced_response" && (
    <p className="muted">
      Its lines keep their original text until the next Translate.
    </p>
  );
  if (details && error != null) {
    const body = record?.body ?? error;
    return (
      <div className="request-failure">
        {record?.body == null && typeof record?.message === "string" ? (
          <p className="translation-error">{record.message}</p>
        ) : (
          <>
            {record?.body != null && typeof record.status === "number" && (
              <small className="muted">HTTP {record.status}</small>
            )}
            <pre className="translation-error">
              {typeof body === "string" ? body : JSON.stringify(body, null, 2)}
            </pre>
          </>
        )}
        {kept}
      </div>
    );
  }
  const message =
    typeof error === "string"
      ? error
      : typeof record?.message === "string"
        ? record.message
        : error != null
          ? JSON.stringify(error, null, 2)
          : payload.state === "rejected"
            ? "This response failed validation. No detailed reason was retained."
            : "This request failed. No detailed reason was retained.";
  const metadata = [record?.code, record?.param].filter(
    (value) => typeof value === "string" && value,
  );
  return (
    <div className="request-failure">
      <p className="translation-error">{message}</p>
      {!!metadata.length && (
        <small className="muted">{metadata.join(" · ")}</small>
      )}
      {details && kept}
    </div>
  );
}
