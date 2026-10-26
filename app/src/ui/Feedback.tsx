import { useState } from "react";
import { Check, LoaderCircle, X } from "lucide-react";
import { Button } from "./Button";
import { ExpandableText } from "./ExpandableText";
import { messageOf, waitsForRecord } from "../api/errors";
import { useOriginalRecord } from "./OriginalRecord";
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
  if (error && waitsForRecord(error)) return <RecordWait />;
  return (
    <div
      className={`feedback ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {error ? (
        // Results sit beside their control, so a long failure stays a short
        // excerpt until the user asks for all of it.
        <ExpandableText
          key={error}
          text={error}
          label="Error details"
          appearance="inline"
          lines={2}
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
      ) : notice ? (
        // A long result stays an excerpt beside its control, as errors do,
        // and its mark reads in its first line, so a wrapped result keeps it.
        <ExpandableText
          key={notice}
          text={notice}
          label="Result details"
          appearance="inline"
          lines={2}
          lead={<Check size={15} className="feedback-mark" />}
        />
      ) : (
        <>
          <Check size={15} />
          All changes saved
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
  if (waitsForRecord(message)) return <RecordWait />;
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

/** In place of a write's refusal: the original record's progress with Stop
 * while it runs, then how it ended, so the user knows when trying again
 * works. */
function RecordWait() {
  const { record, stop } = useOriginalRecord();
  const [stopping, setStopping] = useState(false);
  const [failure, setFailure] = useState("");
  if (record?.running)
    // Read like other pending results, with Stop at the end of the line.
    return (
      <div className="feedback" role="status">
        <LoaderCircle size={15} className="job-status-spinner" aria-hidden />
        <span>
          {record.message}{" "}
          <Button
            variant="link"
            pending={stopping}
            disabled={record.message === "Stopping…"}
            onClick={() => {
              setStopping(true);
              setFailure("");
              stop()
                .catch((error: unknown) => setFailure(messageOf(error)))
                .finally(() => setStopping(false));
            }}
          >
            Stop
          </Button>
          {failure && <span className="record-wait-failure"> {failure}</span>}
        </span>
      </div>
    );
  if (record?.stopped)
    return (
      <div className="feedback" role="status">
        Recording the original game files stopped. Try again to record them
        first.
      </div>
    );
  if (record?.error)
    return (
      <Feedback
        error={`The game's original files weren't recorded: ${record.error} Try again to record them again.`}
      />
    );
  return <Feedback notice="The original game files are recorded. Try again." />;
}
