import { useState, type ReactNode } from "react";
import type { BatchCancellation, Job } from "../../api/contracts";
import { api } from "../../api/client";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Feedback, Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { ExpandableText } from "../../ui/ExpandableText";
import { JobStatus } from "../../ui/JobStatus";
import { ProcessPanel, type RequestInspectionTarget } from "./ProcessPanel";
import { InspectedFile } from "./InspectedFile";
import { RunLog } from "./RunTechnical";
import { batchOutcome, canRetrySaving, canReapplyBatch } from "./batchView";
import type { RequestBatch } from "./requestView";
import { observedRun } from "./translationView";
import { useRead } from "../../state/useRead";

export function RunInspector({
  projectId,
  job: summary,
  target,
  close,
  history,
  returnFocus,
  actions,
  reapply,
  applied,
  disabled,
}: {
  projectId: string;
  job: Job | null;
  target?: RequestInspectionTarget;
  close: () => void;
  history: () => void;
  returnFocus?: HTMLElement | null;
  actions?: ReactNode;
  reapply: (job: Job) => Promise<void>;
  applied?: Job;
  disabled: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [cancellation, setCancellation] = useState<BatchCancellation | null>(
    null,
  );
  const jobId = summary?.id;
  // The key is null without a job, so the read only runs with one.
  const inspection = useRead(jobId ? `${projectId}:${jobId}` : null, () =>
    api.guided.inspect(projectId, jobId!),
  );
  const detail = inspection.value ?? null;
  const reading = inspection.pending;
  const readError =
    inspection.error === undefined
      ? ""
      : inspection.error instanceof Error
        ? inspection.error.message
        : "Saved run unavailable.";
  const job = observedRun(detail, summary || undefined) || summary;
  const feedback = (key: string, pendingText: string) => ({
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  function batchActions(group?: RequestBatch) {
    if (!job) return null;
    const providers = group?.provider
      ? [group.provider, ...group.clarifications]
      : [];
    const cancellable = providers.filter(
      (batch) =>
        batch.canCancel !== false &&
        batchOutcome(batch, job).pending &&
        !["cancelling", "canceling"].includes(batch.status),
    );
    const queue =
      job.process?.batches?.some((batch) => batch.provider === "openrouter") &&
      (job.process?.remaining ?? 0) > 0;
    const collect = canRetrySaving(job) || !!job.process?.resultsUnavailable;
    const reapplyVisible = job.status === "complete";
    return (
      <div className="inspector-batch-actions">
        {providers.some(
          (batch) =>
            batch.canCancel === false && batchOutcome(batch, job).pending,
        ) && <p className="muted">Cannot cancel at provider.</p>}
        <ActionList compact>
          {cancellable.map((batch) => (
            <ActionRow
              key={batch.id}
              label={
                <small>
                  {batch.clarification ? "Clarification retry" : group?.label}
                </small>
              }
            >
              <ActionControl
                label="Cancel Batch"
                variant="quiet"
                disabled={action.busy}
                {...feedback(
                  "cancel:" + batch.id,
                  "Reading cancellation scope…",
                )}
                onClick={() =>
                  action.run(
                    async () =>
                      setCancellation(
                        await api.guided.batchCancelPreview(
                          projectId,
                          job.id,
                          batch.id,
                        ),
                      ),
                    "",
                    "cancel:" + batch.id,
                  )
                }
              />
            </ActionRow>
          ))}
          {(queue || action.key === "queue") && (
            <ActionRow
              label={
                <small>
                  {job.process?.remaining
                    ? `${job.process.remaining.toLocaleString()} requests not sent`
                    : "Approved queue"}
                </small>
              }
            >
              <ActionControl
                label={
                  job.process?.queueStopped
                    ? "Continue queued work"
                    : "Stop queued work"
                }
                variant="quiet"
                disabled={
                  action.busy ||
                  !queue ||
                  (!!job.process?.queueStopped &&
                    !job.process?.queueCanContinue)
                }
                {...feedback(
                  "queue",
                  job.process?.queueStopped
                    ? "Continuing queued work…"
                    : "Stopping queued work…",
                )}
                onClick={() =>
                  action.run(
                    () =>
                      job.process?.queueStopped
                        ? api.resume(projectId, job.id)
                        : api.stop(projectId, job.id),
                    job.process?.queueStopped
                      ? "Continuing the approved queue."
                      : "Queued work stopped. Submitted Batches continue at OpenRouter.",
                    "queue",
                  )
                }
              />
            </ActionRow>
          )}
          {(collect || action.key === "collect") && (
            <ActionRow label={<small>Saved provider results</small>}>
              <ActionControl
                label={
                  job.process?.resultsUnavailable
                    ? "Retry collection"
                    : "Retry saving results"
                }
                variant="quiet"
                disabled={action.busy || !collect}
                {...feedback("collect", "Collecting responses…")}
                onClick={() =>
                  action.run(
                    () => api.guided.batchCollect(projectId, job.id),
                    "Saving collected responses.",
                    "collect",
                  )
                }
              />
            </ActionRow>
          )}
          {reapplyVisible && (
            <ActionRow label={<small>Saved output for this run</small>}>
              <ActionControl
                label="Reapply"
                variant="quiet"
                disabled={disabled || action.busy || !canReapplyBatch(job)}
                {...feedback("reapply", "Preparing saved output…")}
                title={
                  !canReapplyBatch(job)
                    ? "Saved output is unavailable for this Batch."
                    : "Review and apply this Batch’s saved output to the game."
                }
                job={applied?.status === "complete" ? undefined : applied}
                notice={
                  applied?.status === "complete" ? "Batch output applied." : ""
                }
                onClick={() => action.run(() => reapply(job), "", "reapply")}
              />
            </ActionRow>
          )}
        </ActionList>
        {action.key === "batch:confirm-cancel" && action.notice && (
          <Feedback notice={action.notice} />
        )}
      </div>
    );
  }
  return (
    <>
      <Modal
        label="Request inspector"
        className={
          job?.process || target?.file ? "request-inspector-sheet" : ""
        }
        returnFocus={returnFocus}
        dismissible={!action.busy}
        onDismiss={close}
      >
        <header className="request-inspector-heading">
          <h2>
            {job?.process
              ? "Inspect run"
              : target?.file
                ? "Inspect file"
                : "Inspect activity"}
          </h2>
          <div className="request-heading-actions">
            <Button variant="quiet" disabled={action.busy} onClick={history}>
              Run history
            </Button>
            <Button disabled={action.busy} onClick={close}>
              Close
            </Button>
          </div>
        </header>
        {job?.process ? (
          <ProcessPanel
            job={job}
            projectId={projectId}
            initialRequest={target}
            readPayload={(index) =>
              api.guided.payload(projectId, job.id, index)
            }
            readNames={(offset) =>
              api.guided.nameResults(projectId, job.id, offset)
            }
            actions={actions}
            batchActions={job.mode === "batch" ? batchActions : undefined}
          />
        ) : target?.file ? (
          <>
            <ExpandableText
              text={target.file}
              label="Selected file"
              appearance="inline"
              limit={80}
            />
            <p className="muted">
              No saved request is linked to this file. Showing its current
              contents.
            </p>
            <InspectedFile projectId={projectId} file={target.file} />
          </>
        ) : (
          job && (
            <div className="run-technical">
              <section>
                <JobStatus
                  job={{
                    label: job.label || "Saved activity",
                    status: job.status,
                    message: job.message,
                  }}
                />
                <p className="muted">
                  {job.created &&
                    `${new Date(job.created).toLocaleString()} · `}
                  <code>{job.id}</code>
                </p>
                {!!job.files?.length && (
                  <dl className="run-detail-summary">
                    <div>
                      <dt>Files</dt>
                      <dd>
                        <ExpandableText
                          text={job.files.join(", ")}
                          label="Activity files"
                          appearance="inline"
                        />
                      </dd>
                    </div>
                  </dl>
                )}
              </section>
              {job.result && (
                <section>
                  <h3>Saved result</h3>
                  <ExpandableText
                    text={JSON.stringify(job.result, null, 2)}
                    label="Saved result"
                  />
                </section>
              )}
              <RunLog log={job.log} />
            </div>
          )
        )}
        <Message message={readError} />
        {readError && (
          <Button variant="quiet" pending={reading} onClick={inspection.retry}>
            Retry reading run
          </Button>
        )}
      </Modal>
      {cancellation && (
        <Modal
          label="Cancel provider Batch"
          className="guided-sheet translation-review"
          dismissible={!action.busy}
          onDismiss={() => setCancellation(null)}
        >
          <header className="guided-sheet-heading">
            <h2>Cancel this Batch?</h2>
          </header>
          <div className="guided-sheet-body">
            <p>
              {cancellation.model} · {cancellation.requests} requests ·{" "}
              {cancellation.provider}
            </p>
            <p className="batch-run-files">{cancellation.batchId}</p>
            <p>
              The provider will stop unfinished requests where possible.
              Requests already running may finish and be billed. Cancellation
              can take several minutes.
            </p>
            <p>
              This affects the whole provider Batch. The run’s files are:{" "}
              {cancellation.files.join(", ")}.
            </p>
            <p>
              Saved requests and responses are retained. Available results are
              collected automatically after cancellation finishes. Cancellation
              does not submit replacement work.
            </p>
          </div>
          <ActionBar
            feedback={
              <Message
                message={
                  action.key === "batch:confirm-cancel" ? action.error : ""
                }
              />
            }
          >
            <Button
              disabled={action.busy}
              onClick={() => setCancellation(null)}
            >
              Back to inspection
            </Button>
            <Button
              variant="danger"
              pending={action.busy}
              disabled={action.key === "batch:confirm-cancel" && !!action.error}
              onClick={() =>
                action.run(
                  async () => {
                    await api.guided.batchCancel(projectId, cancellation.token);
                    setCancellation(null);
                  },
                  "Cancellation requested. The provider may still be finishing requests.",
                  "batch:confirm-cancel",
                )
              }
            >
              Cancel Batch
            </Button>
          </ActionBar>
        </Modal>
      )}
    </>
  );
}
