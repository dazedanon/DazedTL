import { useState } from "react";
import { AlertTriangle, Check, CircleHelp, LoaderCircle } from "lucide-react";
import type { BatchCancellation, Job } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { Tabs } from "../../ui/Tabs";
import { VirtualList } from "../../ui/VirtualList";
import { useAction } from "../../state/useAction";
import { api } from "../../api/client";
import { useApplication } from "../../app/ApplicationProvider";
import { historyPhase } from "./historyView";
import type { RequestInspectionTarget } from "./ProcessPanel";
import { batchOutcome, batchRuns, canRetrySaving, canReapplyBatch, terminalBatch, totalBatchProgress } from "./batchView";

const keyOf = (job: Job) => job.id;

export function BatchMonitor({ projectId, runs, focusRun, close, inspect, reapply, applicationJob, disabled }: {
  projectId: string; runs: Job[]; focusRun?: string; close: () => void; inspect: (job: Job, target?: RequestInspectionTarget) => void;
  reapply: (job: Job) => Promise<void>; applicationJob: (job: Job) => Job | undefined; disabled: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [filter, setFilter] = useState(focusRun || !batchRuns(runs).length ? "all" : "active");
  const [cancellation, setCancellation] = useState<BatchCancellation | null>(null);
  const [focus, setFocus] = useState(focusRun || null);
  const blocking = action.busy && (action.key === "batch:confirm-cancel" || action.key.startsWith("batch:collect:") || action.key.startsWith("batch:reapply:"));
  const jobs = batchRuns(runs, filter === "all");
  return <>
    <Modal label="Batches" className="guided-sheet batch-monitor" dismissible={!blocking} onDismiss={close}>
      <header className="guided-sheet-heading batch-monitor-heading"><h2>Batches</h2><Button disabled={blocking} onClick={close}>Close</Button></header>
      <div className="batch-monitor-filter"><Tabs id="batch-filter" label="Batch filter" items={[{ id: "active", label: "In progress" }, { id: "all", label: "All batches" }]} value={filter} onChange={setFilter} /></div>
      <div className="batch-monitor-list" role="tabpanel" id={`batch-filter-panel-${filter}`} aria-labelledby={`batch-filter-tab-${filter}`}>
        <VirtualList items={jobs} itemKey={keyOf} focusKey={focus} onFocusReady={() => setFocus(null)} label="Saved Batch runs" empty={<p className="muted">{filter === "active" ? "No Batches are in progress. Completed runs are in All batches." : "No provider Batches have been submitted for this project."}</p>}>
          {job => {
            const batches = job.process?.batches || [], collectKey = "batch:collect:" + job.id, reapplyKey = "batch:reapply:" + job.id;
            const remaining = job.process?.remaining || 0;
            const total = batches.length && (batches.length > 1 || remaining > 0) ? totalBatchProgress(batches, remaining) : null;
            const monitoring = job.process?.monitoring, applied = applicationJob(job);
            const issue = monitoring && ["error", "blocked"].includes(monitoring.state) ? monitoring.message
              : canRetrySaving(job) ? "Collected responses could not be saved." : "";
            return <section className="batch-monitor-run" aria-label={`${historyPhase(job)} Batch ${job.id}`}>
              <ActionList compact><ActionRow label={<div className="batch-run-heading">
                <div><strong>{historyPhase(job)}</strong><span>{job.files?.length || 0} selected files</span></div>
                <small>{job.model || "Saved model"}{job.created && ` · ${new Date(job.created).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`}</small>
              </div>}><div className="actions">
                <Button variant="quiet" disabled={blocking} onClick={() => inspect(job)}>Requests</Button>
                {job.status === "complete" && <ActionControl label="Reapply" disabled={disabled || action.busy || !canReapplyBatch(job)}
                  pending={action.busy && action.key === reapplyKey} pendingText="Preparing saved output…"
                  title={!canReapplyBatch(job) ? "Saved output is unavailable for this Batch." : "Review and apply this Batch’s saved output to the game."}
                  error={action.key === reapplyKey ? action.error : ""} job={applied?.status === "complete" ? undefined : applied}
                  notice={applied?.status === "complete" ? "Batch output applied." : ""}
                  onClick={() => action.run(() => reapply(job), "", reapplyKey)} />}
              </div></ActionRow>
              {total && <ActionRow label={<div className="batch-provider-row">
                <div className="batch-provider-heading"><strong>Total progress</strong><span>{total.finished != null && total.total != null
                  ? `${total.finished.toLocaleString()}/${total.total.toLocaleString()} requests finished`
                  : `${total.total != null ? `${total.total.toLocaleString()} requests · ` : ""}Counts unavailable`}</span>
                  {remaining > 0 && <span>{remaining.toLocaleString()} queued</span>}</div>
                {(remaining > 0 || batches.some(batch => !terminalBatch(batch.status))) && (total.finished == null || total.finished !== total.total)
                  && <progress aria-label="Total finished requests" max={total.total || 1} value={total.finished} />}
              </div>}>{null}</ActionRow>}
              {batches.map(batch => {
                const outcome = batchOutcome(batch, job), cancelKey = "batch:cancel:" + batch.id;
                const state = outcome.active ? "active" : outcome.failed ? "warning" : outcome.successful ? "complete" : "unknown";
                const StatusIcon = outcome.active ? LoaderCircle : outcome.failed ? AlertTriangle : outcome.successful ? Check : CircleHelp;
                return <ActionRow key={batch.id} label={<div className="batch-provider-row">
                  <div className="batch-provider-heading"><strong className="batch-activity" data-state={state}>
                    <StatusIcon size={14} className={outcome.active ? "job-status-spinner" : undefined} aria-hidden="true" />{outcome.label}
                  </strong><span>{outcome.summary}</span></div>
                  {!total && outcome.pending && (outcome.progress.finished == null || outcome.progress.finished !== outcome.progress.total)
                    && <progress aria-label={`Finished requests in ${batch.id}`} max={outcome.progress.total || 1} value={outcome.progress.finished} />}
                </div>}>
                  {outcome.pending && !["cancelling", "canceling"].includes(batch.status) && <ActionControl label="Cancel Batch" variant="quiet" disabled={action.busy} pending={action.busy && action.key === cancelKey} pendingText="Reading cancellation scope…"
                    error={action.key === cancelKey ? action.error : ""}
                    onClick={() => action.run(async () => setCancellation(await api.guided.batchCancelPreview(projectId, job.id, batch.id)), "", cancelKey)} />}
                </ActionRow>;
              })}
              {!!job.process?.validationIssues?.length && <ActionRow label={<small className="translation-error">
                {job.process.rejected ? `${job.process.rejected} translations rejected.` : "Translation validation needs review."} Original text was kept for rejected requests.
              </small>}><Button variant="quiet" onClick={() => {
                const rejected = job.process?.requests?.find(request => request.state === "rejected");
                inspect(job, { file: rejected?.file || job.process!.validationIssues![0].file, index: rejected?.index ?? 0, validation: true });
              }}>Review issues</Button></ActionRow>}
              {issue && <ActionRow label={<small className="translation-error" role="alert">{issue}</small>}>
                {canRetrySaving(job) && <ActionControl label="Retry saving results" pending={action.busy && action.key === collectKey} disabled={action.busy} pendingText="Saving responses…"
                  error={action.key === collectKey ? action.error : ""} notice={action.key === collectKey ? action.notice : ""}
                  onClick={() => action.run(() => api.guided.batchCollect(projectId, job.id), "Saving collected responses.", collectKey)} />}
              </ActionRow>}
              {!batches.length && <p className="translation-error">Submission receipt unavailable. Inspect requests before retrying.</p>}
              </ActionList>
            </section>;
          }}
        </VirtualList>
      </div>
    </Modal>
    {cancellation && <Modal label="Cancel provider Batch" className="guided-sheet translation-review" dismissible={!action.busy} onDismiss={() => setCancellation(null)}>
      <header className="guided-sheet-heading"><h2>Cancel this Batch?</h2></header><div className="guided-sheet-body">
        <p>{cancellation.model} · {cancellation.requests} requests · {cancellation.provider}</p><p className="batch-run-files">{cancellation.batchId}</p>
        <p>The provider will stop unfinished requests where possible. Requests already running may finish and be billed. Cancellation can take several minutes.</p>
        <p>This affects the whole provider Batch. The run’s files are: {cancellation.files.join(", ")}.</p>
        <p>Saved requests and responses are retained. Available results are collected automatically after cancellation finishes. Cancellation does not submit replacement work.</p>
      </div><ActionBar feedback={<Message message={action.key === "batch:confirm-cancel" ? action.error : ""} />}>
        <Button disabled={action.busy} onClick={() => setCancellation(null)}>Back to Batches</Button>
        <Button variant="danger" pending={action.busy} disabled={action.key === "batch:confirm-cancel" && !!action.error} onClick={() => action.run(async () => { await api.guided.batchCancel(projectId, cancellation.token); setCancellation(null); }, "Cancellation requested. The provider may still be finishing requests.", "batch:confirm-cancel")}>Cancel Batch</Button>
      </ActionBar></Modal>}
  </>;
}
