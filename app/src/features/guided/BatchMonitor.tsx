import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CircleHelp, LoaderCircle } from "lucide-react";
import type { BatchCancellation, Job } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { Tabs } from "../../ui/Tabs";
import { useAction } from "../../state/useAction";
import { api } from "../../api/client";
import { useApplication } from "../../app/ApplicationProvider";
import { historyDate, historyDay, historyPhase } from "./historyView";
import type { RequestInspectionTarget } from "./ProcessPanel";
import { batchMonitorRows, batchOutcome, batchRuns, canRetrySaving, canReapplyBatch, type ProviderBatch } from "./batchView";

export function BatchMonitor({ projectId, runs, focusRun, close, inspect, reapply, applicationJob, disabled }: {
  projectId: string; runs: Job[]; focusRun?: string; close: () => void; inspect: (job: Job, target?: RequestInspectionTarget) => void;
  reapply: (job: Job) => Promise<void>; applicationJob: (job: Job) => Job | undefined; disabled: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [filter, setFilter] = useState(focusRun || !batchRuns(runs).length ? "all" : "active");
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(30);
  const [cancellation, setCancellation] = useState<BatchCancellation | null>(null);
  const focused = useRef<HTMLElement | null>(null);
  const focusShown = useRef(false);
  const blocking = action.busy && (action.key === "batch:confirm-cancel" || action.key.startsWith("batch:collect:") || action.key.startsWith("batch:reapply:"));
  const all = batchRuns(runs, true);
  const jobs = batchRuns(runs, filter === "all").filter(job => [historyPhase(job), job.model, ...(job.files || [])]
    .join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const limit = Math.max(visible, focusRun && !focusShown.current ? jobs.findIndex(job => job.id === focusRun) + 1 : 0);
  const groups: { day: string; date: string; jobs: Job[] }[] = [];
  for (const job of jobs.slice(0, limit)) {
    const day = historyDay(job.created), last = groups.at(-1);
    if (last?.day === day) last.jobs.push(job);
    else groups.push({ day, date: historyDate(job.created), jobs: [job] });
  }
  useEffect(() => {
    if (focused.current && !focusShown.current) {
      focused.current.scrollIntoView({ block: "nearest" });
      focusShown.current = true;
      setVisible(value => Math.max(value, limit));
    }
  }, [focusRun, jobs.length, limit]);
  function status(outcome: ReturnType<typeof batchMonitorRows>[number]) {
    const state = outcome.active ? "active" : outcome.failed ? "warning" : outcome.successful ? "complete" : "unknown";
    const Icon = outcome.active ? LoaderCircle : outcome.failed ? AlertTriangle : outcome.successful ? Check : CircleHelp;
    return <><strong className="batch-activity" data-state={state}><Icon size={14} className={outcome.active ? "job-status-spinner" : undefined} aria-hidden="true" />{outcome.label}</strong><small>{outcome.summary}</small></>;
  }
  function cancel(batch: ProviderBatch, job: Job) {
    const key = "batch:cancel:" + batch.id;
    return batchOutcome(batch, job).pending && !["cancelling", "canceling"].includes(batch.status) && <ActionControl label="Cancel Batch" variant="quiet" disabled={action.busy}
      pending={action.busy && action.key === key} pendingText="Reading cancellation scope…" error={action.key === key ? action.error : ""}
      onClick={() => action.run(async () => setCancellation(await api.guided.batchCancelPreview(projectId, job.id, batch.id)), "", key)} />;
  }
  return <>
    <Modal label="Batches" className="history-sheet batch-monitor" dismissible={!blocking} onDismiss={close}>
      <header className="request-inspector-heading"><h2>Batches</h2><Button disabled={blocking} onClick={close}>Close</Button></header>
      <div className="guided-history">
        <Tabs id="batch-filter" label="Batch filter" items={[{ id: "active", label: "In progress" }, { id: "all", label: "All batches" }]}
          value={filter} onChange={value => { setFilter(value); setVisible(30); }} />
        <div className="history-filters"><input type="search" aria-label="Search batches" placeholder="Search files, model or task…" value={query}
          onChange={event => { setQuery(event.target.value); setVisible(30); }} /></div>
        <div className="history-list" role="tabpanel" id={`batch-filter-panel-${filter}`} aria-labelledby={`batch-filter-tab-${filter}`}>
          {!jobs.length && <div className="history-empty"><p className="muted">{query ? "No batches match this search." : filter === "active" ? "No Batches are in progress. Previous runs are in All batches." : "No provider Batches have been submitted for this project."}</p>
            {query && <Button variant="quiet" onClick={() => setQuery("")}>Clear search</Button>}</div>}
          {groups.map(group => <section className="history-day" key={group.day} aria-label={group.date}><h3>{group.date}</h3>
            {group.jobs.map(job => {
              const rows = batchMonitorRows(job), applied = applicationJob(job);
              const collectKey = "batch:collect:" + job.id, reapplyKey = "batch:reapply:" + job.id;
              return <section key={job.id} className="batch-history-run" aria-label={`${historyPhase(job)} Batch ${job.id}`}
                ref={element => { if (job.id === focusRun) focused.current = element; }}>
                <ActionList compact>{rows.map((row, index) => <ActionRow key={row.batch?.id || job.id} label={<div className="batch-current">
                  <strong>{historyPhase(job)}</strong>
                  {job.created && <time dateTime={job.created} title={new Date(job.created).toLocaleString()}>{new Date(job.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>}
                  {row.name && <span>{row.name}</span>}
                  {status(row)}
                  {row.detail && <small>{row.detail}</small>}
                </div>}><div className="actions">
                  {row.batch && cancel(row.batch, job)}
                  {index === 0 && <>
                    <Button variant="quiet" disabled={blocking} onClick={() => inspect(job)}>Inspect</Button>
                    {!!job.process?.validationIssues?.length && <Button variant="quiet" disabled={blocking} onClick={() => {
                      const rejected = job.process?.requests?.find(request => request.state === "rejected");
                      inspect(job, { file: rejected?.file || job.process!.validationIssues![0].file, index: rejected?.index ?? 0, validation: true });
                    }}>Review issues</Button>}
                    {canRetrySaving(job) && <ActionControl label="Retry saving results" pending={action.busy && action.key === collectKey} disabled={action.busy} pendingText="Saving responses…"
                      error={action.key === collectKey ? action.error : ""} notice={action.key === collectKey ? action.notice : ""}
                      onClick={() => action.run(() => api.guided.batchCollect(projectId, job.id), "Saving collected responses.", collectKey)} />}
                    {job.status === "complete" && <ActionControl label="Reapply" disabled={disabled || action.busy || !canReapplyBatch(job)}
                      pending={action.busy && action.key === reapplyKey} pendingText="Preparing saved output…"
                      title={!canReapplyBatch(job) ? "Saved output is unavailable for this Batch." : "Review and apply this Batch’s saved output to the game."}
                      error={action.key === reapplyKey ? action.error : ""} job={applied?.status === "complete" ? undefined : applied}
                      notice={applied?.status === "complete" ? "Batch output applied." : ""}
                      onClick={() => action.run(() => reapply(job), "", reapplyKey)} />}</>}
                </div></ActionRow>)}
                </ActionList>
              </section>;
            })}
          </section>)}
          {jobs.length > limit && <Button onClick={() => setVisible(limit + 30)}>Show older records ({jobs.length - limit})</Button>}
        </div>
        <div className="history-footer"><span>{jobs.length === all.length ? `${all.length} ${all.length === 1 ? "run" : "runs"}` : `${jobs.length} of ${all.length} runs`}</span><span>Newest first</span></div>
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
