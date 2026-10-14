import { useId, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type {
  RequestPreview,
  TranslationBatch,
  TranslationJob,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Feedback, Message } from "../../ui/Feedback";
import { FieldRow } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { TabPanel, Tabs } from "../../ui/Tabs";
import { batchLabel, runMode, unconfirmedBatch } from "./apiRun";
import { RequestLines } from "./RequestLines";

export type RunView = "requests" | "batches";

const views = [
  { id: "requests", label: "Requests" },
  { id: "batches", label: "Batches" },
] as const;

const requestCount = (count: number) =>
  `${count.toLocaleString()} ${count === 1 ? "request" : "requests"}`;

/** What a sent Batch's provider counts add: the requests it could not finish. */
function batchFailures(batch: TranslationBatch) {
  const counts = batch.counts || {};
  const failed = ["failed", "errored", "expired"].reduce(
    (sum, key) => sum + (counts[key] || 0),
    0,
  );
  return failed ? `${failed.toLocaleString()} failed` : "";
}

/**
 * An Assistant-led run's requests one at a time, with each saved result and
 * the reviews and receipts that change it, and its provider Batches. It opens
 * at once, wherever the run sits on the page, and reads the request while it
 * shows.
 */
export function LenRunInspector({
  projectId,
  job,
  initialIndex,
  initialView,
  active,
  onClose,
}: {
  projectId: string;
  job: TranslationJob;
  initialIndex: number;
  initialView: RunView;
  /** Translation work is running, so results stay as they are. */
  active: boolean;
  onClose: () => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const tabId = useId();
  const batches = job.batches.map((batch, index) => ({ batch, index }));
  const sent = batches.filter(({ batch }) => batch.state !== "pending");
  const unsent = batches.filter(({ batch }) => batch.state === "pending");
  const [view, setView] = useState<RunView>(
    batches.length ? initialView : "requests",
  );
  // The uncertain submission being attached to its provider job.
  const [attaching, setAttaching] = useState({ index: -1, id: "" });
  const closeAttach = () => {
    setAttaching({ index: -1, id: "" });
    if (action.key === "attach") action.clear();
  };
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
  const request = readError ? (
    <>
      <Message message={readError} />
      <Button onClick={read.retry}>Try again</Button>
    </>
  ) : !preview ? (
    <p className="muted" role="status">
      Reading request…
    </p>
  ) : (
    <>
      <p className="lens-request-id">{preview.request.id}</p>
      <RequestLines preview={preview} />
      {preview.result && (
        <ActionControl
          label={
            preview.result.reviewed
              ? "Source-checked review recorded"
              : Object.keys(preview.request.context.qa_notes || {}).length
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
            This request may already have been billed. Check the provider before
            allowing another attempt.
          </p>
          <label className="translation-check">
            <input
              type="checkbox"
              checked={reviewedRetry}
              onChange={(event) => setReviewedRetry(event.target.checked)}
            />
            I reviewed the outcome and want to prepare a new quote for this
            request.
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
              () => window.dazedtl.copyText(JSON.stringify(preview, null, 2)),
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
            {preview.result.result_sha256}. The previous result is retained and
            affected QA becomes pending.
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
  );
  const batchList = (
    <ActionList>
      {sent.map(({ batch, index }) => (
        <ActionRow
          key={index}
          title={batch.id || batchLabel(batch)}
          description={[
            batch.id ? batchLabel(batch) : "",
            requestCount(batch.requests),
            batchFailures(batch),
            batch.cancel_error
              ? `Cancellation failed: ${batch.cancel_error}`
              : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        >
          {unconfirmedBatch(batch) && (
            <Button
              disabled={active || action.busy}
              onClick={() => setAttaching({ index, id: "" })}
            >
              Attach provider job
            </Button>
          )}
        </ActionRow>
      ))}
      {!!unsent.length && (
        <ActionRow
          title="Not sent yet"
          description={`${unsent.length.toLocaleString()} ${unsent.length === 1 ? "Batch" : "Batches"} · ${requestCount(
            unsent.reduce((sum, { batch }) => sum + batch.requests, 0),
          )}`}
        />
      )}
    </ActionList>
  );
  return (
    <>
      <Modal
        label="Run inspector"
        size="lg"
        className="lens-run-inspector"
        dismissible={!action.busy}
        onDismiss={onClose}
      >
        <DialogHeader
          title="Inspect run"
          description={`${runMode(job)} · ${job.status.replaceAll("_", " ")}`}
          onClose={onClose}
          closeDisabled={action.busy}
        />
        <DialogBody className="payload-inspector lens-run-body">
          <div className="request-toolbar">
            {!!batches.length && (
              <Tabs
                id={tabId}
                label="Run content"
                items={views}
                value={view}
                onChange={setView}
              />
            )}
            {view === "requests" && (
              <div className="request-navigation">
                <span>
                  Request {(index + 1).toLocaleString()} of{" "}
                  {job.requests.toLocaleString()}
                </span>
                <div className="actions">
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
                </div>
              </div>
            )}
          </div>
          <div
            className="request-reader"
            key={view === "requests" ? index : view}
            aria-busy={view === "requests" && read.pending}
          >
            {batches.length ? (
              <TabPanel id={tabId} value={view}>
                {view === "requests" ? request : batchList}
              </TabPanel>
            ) : (
              request
            )}
          </div>
        </DialogBody>
      </Modal>
      {attaching.index >= 0 && (
        <Modal
          label="Attach a provider job"
          size="sm"
          dismissible={!action.busy}
          onDismiss={closeAttach}
        >
          <DialogHeader title="Attach the matching provider job?" />
          <DialogBody>
            <p>
              Use the job ID from the provider for this exact submission.
              Collection will check its request IDs. This does not submit
              another batch.
            </p>
            <FieldRow id="attach-provider-job" label="Provider job ID" wide>
              {(props) => (
                <input
                  {...props}
                  value={attaching.id}
                  onChange={(event) =>
                    setAttaching({ ...attaching, id: event.target.value })
                  }
                />
              )}
            </FieldRow>
          </DialogBody>
          <ActionBar
            feedback={
              action.key === "attach" &&
              action.error && <Feedback error={action.error} />
            }
          >
            <Button disabled={action.busy} onClick={closeAttach}>
              Back to inspection
            </Button>
            <Button
              variant="primary"
              disabled={!attaching.id.trim() || active}
              pending={action.busy && action.key === "attach"}
              onClick={() =>
                void action.run(
                  async () => {
                    await api.translation.attach(
                      projectId,
                      job.id,
                      attaching.index,
                      attaching.id,
                    );
                    closeAttach();
                  },
                  "",
                  "attach",
                )
              }
            >
              Attach job
            </Button>
          </ActionBar>
        </Modal>
      )}
    </>
  );
}
