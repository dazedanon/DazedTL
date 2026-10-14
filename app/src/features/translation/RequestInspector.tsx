import { useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { RequestPreview, TranslationJob } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Message } from "../../ui/Feedback";
import { FieldRow } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { RequestLines } from "./RequestLines";

/**
 * An Assistant-led run's requests one at a time, with each saved result and
 * the reviews and receipts that change it. It opens at once, wherever the
 * run sits on the page, and reads the request while it shows.
 */
export function RequestInspector({
  projectId,
  job,
  initialIndex,
  active,
  onClose,
}: {
  projectId: string;
  job: TranslationJob;
  initialIndex: number;
  /** Translation work is running, so results stay as they are. */
  active: boolean;
  onClose: () => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [index, setIndex] = useState(initialIndex);
  // A review or receipt changes the saved result, so the request is read
  // again. Paging waits for each read: a large run's plan takes a while to
  // read, and the backend answers its requests in turn.
  const [revision, setRevision] = useState(0);
  const read = useRead(`${projectId}:${job.id}:${index}:${revision}`, () =>
    api.translation.request(projectId, job.id, index),
  );
  // Reading the shown request again keeps it on screen, and its scroll.
  const [shown, setShown] = useState<RequestPreview | null>(null);
  useOnChange(read.value, (value) => {
    if (value) setShown(value);
  });
  const preview = shown?.index === index ? shown : null;
  const readError = read.error === undefined ? "" : messageOf(read.error);
  const [reviewedRetry, setReviewedRetry] = useState(false);
  const [receipt, setReceipt] = useState("");
  const feedback = (key: string, pendingText: string) => ({
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const write = (key: string, message: string, task: () => Promise<unknown>) =>
    void action.run(
      async () => {
        await task();
        setRevision((value) => value + 1);
      },
      message,
      key,
    );
  const uncertain =
    !!preview &&
    job.mode === "live" &&
    job.issues.some(
      (issue) => issue.id === preview.request.id && issue.state === "uncertain",
    );
  return (
    <Modal
      label="Request inspector"
      size="lg"
      className="lens-request-inspector"
      dismissible={!action.busy}
      onDismiss={onClose}
    >
      <DialogHeader
        title={`Request ${(index + 1).toLocaleString()} of ${job.requests.toLocaleString()}`}
        description={
          preview ? (
            preview.request.id
          ) : (
            <span role="status">
              {readError
                ? "This request could not be read."
                : "Reading request…"}
            </span>
          )
        }
        actions={
          <>
            <Button
              variant="quiet"
              disabled={index === 0 || read.pending || action.busy}
              onClick={() => setIndex(index - 1)}
            >
              Previous
            </Button>
            <Button
              variant="quiet"
              disabled={
                index + 1 >= job.requests || read.pending || action.busy
              }
              onClick={() => setIndex(index + 1)}
            >
              Next
            </Button>
          </>
        }
        onClose={onClose}
        closeDisabled={action.busy}
      />
      <DialogBody
        className="lens-request-body"
        key={index}
        aria-busy={read.pending}
      >
        {readError ? (
          <>
            <Message message={readError} />
            <Button onClick={read.retry}>Try again</Button>
          </>
        ) : (
          preview && (
            <>
              <RequestLines preview={preview} />
              {preview.result && (
                <ActionControl
                  label={
                    preview.result.reviewed
                      ? "Source-checked review recorded"
                      : Object.keys(preview.request.context.qa_notes || {})
                            .length
                        ? "Mark request and flagged lines source-checked"
                        : "Mark this request source-checked"
                  }
                  disabled={active || action.busy}
                  {...feedback("review", "Recording…")}
                  onClick={() =>
                    write("review", "", () =>
                      api.translation.review(
                        projectId,
                        job.id,
                        preview.request.id,
                        preview.request.fingerprint,
                      ),
                    )
                  }
                />
              )}
              {uncertain && (
                <div className="translation-quote">
                  <p>
                    This request may already have been billed. Check the
                    provider before allowing another attempt.
                  </p>
                  <label className="translation-check">
                    <input
                      type="checkbox"
                      checked={reviewedRetry}
                      onChange={(event) =>
                        setReviewedRetry(event.target.checked)
                      }
                    />
                    I reviewed the outcome and want to prepare a new quote for
                    this request.
                  </label>
                  <ActionControl
                    label="Record review; allow a new quote"
                    disabled={!reviewedRetry || active || action.busy}
                    {...feedback("resolve", "Recording…")}
                    onClick={() =>
                      write("resolve", "", async () => {
                        await api.translation.resolve(
                          projectId,
                          job.id,
                          preview.request.id,
                          preview.request.fingerprint,
                        );
                        setReviewedRetry(false);
                      })
                    }
                  />
                </div>
              )}
              <details>
                <summary>Exact compiled context and provider payload</summary>
                <ActionControl
                  label="Copy request"
                  {...feedback("copy", "Copying…")}
                  onClick={() =>
                    void action.run(
                      () =>
                        window.dazedtl.copyText(
                          JSON.stringify(preview, null, 2),
                        ),
                      "Copied.",
                      "copy",
                    )
                  }
                />
                <pre className="translation-json">
                  {JSON.stringify(preview.request, null, 2)}
                </pre>
              </details>
              <details>
                <summary>
                  {preview.result
                    ? "Import a reviewed correction"
                    : "Import a saved result receipt"}
                </summary>
                {preview.result && (
                  <p className="footnote">
                    Include this result hash as replaces_sha256 in the receipt:{" "}
                    {preview.result.result_sha256}. The previous result is
                    retained and affected QA becomes pending.
                  </p>
                )}
                <FieldRow
                  id="request-receipt-path"
                  label="Receipt file, relative to the game"
                  wide
                >
                  {(props) => (
                    <input
                      {...props}
                      value={receipt}
                      onChange={(event) => setReceipt(event.target.value)}
                    />
                  )}
                </FieldRow>
                <div className="actions">
                  <ActionControl
                    label="Validate and save result"
                    disabled={!receipt || active || action.busy}
                    {...feedback("accept", "Validating…")}
                    onClick={() =>
                      write("accept", "Result saved.", () =>
                        api.translation.accept(
                          projectId,
                          job.id,
                          preview.request.id,
                          receipt,
                        ),
                      )
                    }
                  />
                </div>
              </details>
            </>
          )
        )}
      </DialogBody>
    </Modal>
  );
}
