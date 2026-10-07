import { Check, X } from "lucide-react";
import { Button } from "./Button";
import { ExpandableText } from "./ExpandableText";
export function Feedback({
  error = "",
  loading = false,
  pending = false,
  dirty = false,
  notice = "",
  loadingText = "Loading…",
}: {
  error?: string;
  loading?: boolean;
  pending?: boolean;
  dirty?: boolean;
  notice?: string;
  loadingText?: string;
}) {
  return (
    <div
      className={`feedback ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {error ? (
        // Results sit beside their control, so a long failure stays a short
        // excerpt until the user asks for all of it.
        <ExpandableText
          text={error}
          label="Error details"
          appearance="inline"
          limit={120}
        />
      ) : loading ? (
        loadingText
      ) : pending ? (
        "Saving…"
      ) : dirty ? (
        <>
          <span className="unsaved-dot" />
          Unsaved changes
        </>
      ) : (
        <>
          <Check size={15} />
          {notice || "All changes saved"}
        </>
      )}
    </div>
  );
}
export function Message({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss?: () => void;
}) {
  if (!message) return null;
  return (
    <div className="banner" role="alert">
      {/* A long failure, such as a contract report, stays an excerpt that
          expands in its own scrolling space instead of covering the page. */}
      <ExpandableText
        text={message}
        label="Error details"
        appearance="inline"
        limit={320}
      />
      {onDismiss && (
        <Button variant="quiet" aria-label="Dismiss error" onClick={onDismiss}>
          <X size={16} />
        </Button>
      )}
    </div>
  );
}
