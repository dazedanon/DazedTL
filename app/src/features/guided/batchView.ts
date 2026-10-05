import type { Job, RunProcess } from "../../api/contracts.ts";
import { activeRun, needsSubmissionReview, terminalBatch, providerBatchActive } from "./translationView.ts";
import { historyOutcome } from "./historyView.ts";
export { terminalBatch, providerBatchActive } from "./translationView.ts";

export type ProviderBatch = NonNullable<RunProcess["batches"]>[number];
export const batchCount = (value: unknown): number | undefined => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
export function batchProgress(batch: ProviderBatch) {
  const total = batchCount(batch.total ?? batch.counts.total);
  const counts = ["succeeded", "errored", "canceled", "expired"].map(key => batchCount(batch.counts[key]));
  const counted = counts.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  // Known outcomes can exhaust the total even when older receipts omit zero counts.
  const finished = counts.every(value => value !== undefined) || counted === total ? counted : undefined;
  return { total, finished: total != null && finished != null && finished <= total ? finished : undefined };
}
export function totalBatchProgress(batches: ProviderBatch[], remaining = 0) {
  // Clarifications retry existing source requests; they do not expand the run.
  const progress = batches.filter(batch => !batch.clarification).map(batchProgress);
  const sum = (key: "total" | "finished") => progress.length && progress.every(row => row[key] != null)
    ? batchCount(progress.reduce((total, row) => total + row[key]!, 0)) : undefined;
  const submitted = sum("total"), queued = batchCount(remaining);
  const total = submitted != null && queued != null ? batchCount(submitted + queued) : undefined;
  return { total, finished: total != null ? sum("finished") : undefined };
}
export function batchInProgress(job: Job) {
  const batches = job.process?.batches || [];
  // A stopped local worker does not stop provider work. Conversely, recovery
  // guards and stale polling phases do not make terminal failures active.
  if (batches.some(batch => providerBatchActive(batch.status))) return true;
  const monitor = job.process?.monitoring?.state;
  if (monitor && ["error", "save_error", "blocked"].includes(monitor)) return false;
  const collectable = batches.some(batch => (batchCount(batch.counts.succeeded) || 0) > 0
    || batch.counts.succeeded == null && ["completed", "ended"].includes(batch.status));
  if (monitor === "collecting" && collectable) return true;
  if (activeRun(job) && !job.approval) {
    if (job.phase === "poll_capacity") return true;
    if (job.phase === "consume") return (job.process?.received || 0) > 0 || collectable;
    if (job.phase === "submit") return !batches.length || batches.every(batch => batchOutcome(batch, job).successful);
    if (job.phase?.startsWith("poll") && batches.length && batches.every(batch => batchOutcome(batch, job).successful)) return true;
  }
  return monitor === "monitoring" && collectable && batches.every(batch => terminalBatch(batch.status));
}
export function batchRuns(runs: Job[], all = false) {
  return runs.filter(job => job.mode === "batch" && !job.temporary && (!!job.process?.batches?.length || needsSubmissionReview(job) || activeRun(job) && job.phase === "poll_capacity") && (all || batchInProgress(job)))
    .sort((a, b) => (b.created || "").localeCompare(a.created || ""));
}
export function canRetrySaving(job: Job) {
  return job.mode === "batch" && !!job.process?.resultsCollected && (job.process.received ?? 0) > 0 && job.process?.monitoring?.state === "save_error"
    && !job.process.remaining
    && ["failed", "stopped", "interrupted", "canceled"].includes(job.status);
}
export function canReapplyBatch(job: Job) {
  return job.mode === "batch" && job.status === "complete" && !job.temporary
    && job.outputsAvailable === true && Object.keys(job.outputs || {}).length > 0;
}
const statuses: Record<string, string> = { validating: "Checking requests", in_progress: "Translating", finalizing: "Preparing results", cancelling: "Canceling", canceling: "Canceling",
  completed: "Completed", ended: "Completed", cancelled: "Canceled", canceled: "Canceled", failed: "Failed", expired: "Expired", unknown: "Status unavailable" };
export const batchStatus = (status: string) => statuses[status] || status.replaceAll("_", " ");

export function batchOutcome(batch: ProviderBatch, job: Job) {
  const progress = batchProgress(batch), succeeded = batchCount(batch.counts.succeeded);
  const failures = ([['errored', 'failed'], ['canceled', 'canceled'], ['expired', 'expired']] as const)
    .filter(([key]) => (batchCount(batch.counts[key]) || 0) > 0).map(([key, label]) => `${batch.counts[key]!.toLocaleString()} ${label}`);
  const terminal = terminalBatch(batch.status);
  const hasResults = (succeeded || 0) > 0 || succeeded == null && ["completed", "ended"].includes(batch.status);
  const consuming = terminal && hasResults && activeRun(job) && job.phase === "consume";
  const collecting = terminal && hasResults && job.process?.monitoring?.state === "collecting";
  let label = terminal && failures.length ? succeeded ? "Partial" : batch.counts.errored ? "Failed" : batch.counts.canceled ? "Canceled" : "Expired" : batchStatus(batch.status);
  if (consuming || collecting) label = consuming ? "Saving results" : "Receiving results";
  const uniform = terminal && progress.total != null && (succeeded === progress.total || succeeded === 0 && failures.length === 1);
  const summary = uniform ? `${progress.total!.toLocaleString()} ${progress.total === 1 ? "request" : "requests"}` : [succeeded != null && (succeeded > 0 || !failures.length) ? `${succeeded.toLocaleString()}${progress.total != null ? `/${progress.total.toLocaleString()}` : ""} succeeded` : "", ...failures].filter(Boolean).join(" · ")
    || (progress.total != null ? `${progress.total.toLocaleString()} requests` : "Counts unavailable");
  const providerActive = providerBatchActive(batch.status);
  const active = providerActive || consuming || collecting;
  const failed = terminal && (failures.length > 0 || !["completed", "ended"].includes(batch.status));
  const successful = terminal && !active && !failed && progress.total != null && succeeded === progress.total;
  return { label, summary, progress, pending: providerActive, active, failed, successful };
}

/** Keep every active provider job actionable; completed chunks belong in Inspect. */
export function batchMonitorRows(job: Job) {
  const batches = job.process?.batches || [];
  const current = batches.filter(batch => providerBatchActive(batch.status));
  const remaining = job.process?.remaining;
  const unsent = remaining ? `${remaining.toLocaleString()} ${batchInProgress(job) ? "queued" : "not sent"}` : "";
  const monitor = job.process?.monitoring?.state;
  const problem = monitor && ["error", "blocked", "save_error"].includes(monitor);
  if (current.length) return current.map(batch => ({
    batch,
    name: batch.clarification ? "Clarification retry" : `Batch ${batches.filter(row => !row.clarification).indexOf(batch) + 1}`,
    ...batchOutcome(batch, job),
    detail: unsent,
  }));

  const active = batchInProgress(job), outcome = historyOutcome(job);
  const issues = job.process?.validationIssues?.length || job.process?.rejected;
  const total = totalBatchProgress(batches, remaining || 0);
  const label = active
    ? job.phase === "poll_capacity" ? "Waiting for capacity" : job.phase === "consume" ? "Saving results"
      : activeRun(job) && remaining && monitor !== "collecting" ? "Sending next batch" : "Receiving results"
    : remaining ? "Incomplete" : problem ? "Failed" : issues ? "Needs review"
      : !batches.length ? "Receipt unavailable" : outcome.kind === "active" ? "Needs review" : outcome.label;
  return [{
    batch: undefined, name: "", label, active,
    failed: !active && (!!remaining || !!problem || !!issues || ["review", "failed", "stopped", "canceled", "partial", "missing", "active"].includes(outcome.kind)),
    successful: !active && !remaining && !problem && !issues && outcome.kind === "saved",
    summary: job.phase === "poll_capacity" && !batches.length ? "" : total.finished != null && total.total != null
      ? total.finished === total.total ? `${total.total.toLocaleString()} requests` : `${total.finished.toLocaleString()}/${total.total.toLocaleString()} finished`
      : "Counts unavailable",
    detail: [unsent, job.process?.rejected ? `${job.process.rejected.toLocaleString()} rejected` : ""].filter(Boolean).join(" · "),
  }];
}
