import type { Job, RunProcess } from "../../api/contracts.ts";
import { activeRun, needsSubmissionReview, terminalBatch } from "./translationView.ts";
export { terminalBatch } from "./translationView.ts";

export type ProviderBatch = NonNullable<RunProcess["batches"]>[number];
export const batchCount = (value: unknown): number | undefined => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
export function batchProgress(batch: ProviderBatch) {
  const total = batchCount(batch.total ?? batch.counts.total);
  const counts = ["succeeded", "errored", "canceled", "expired"].map(key => batchCount(batch.counts[key]));
  const finished = counts.every(value => value !== undefined) ? counts.reduce((sum, value) => sum + value!, 0) : undefined;
  return { total, finished: total != null && finished != null && finished <= total ? finished : undefined };
}
export function batchRuns(runs: Job[], all = false) {
  return runs.filter(job => job.mode === "batch" && !job.temporary && (!!job.process?.batches?.length || needsSubmissionReview(job)) && (all || activeRun(job) || needsSubmissionReview(job)
    || !!job.process?.monitoring || job.process?.batches?.some(batch => !terminalBatch(batch.status))))
    .sort((a, b) => Number(activeRun(b)) - Number(activeRun(a)) || (b.created || "").localeCompare(a.created || ""));
}
export function canRetrySaving(job: Job) {
  return job.mode === "batch" && !!job.process?.resultsCollected && (job.process.received ?? 0) > 0 && job.process?.monitoring?.state === "save_error"
    && ["failed", "stopped", "interrupted", "canceled"].includes(job.status);
}
const statuses: Record<string, string> = { validating: "Validating", in_progress: "Processing", finalizing: "Finalizing", cancelling: "Canceling", canceling: "Canceling",
  completed: "Completed", ended: "Completed", cancelled: "Canceled", canceled: "Canceled", failed: "Failed", expired: "Expired" };
export const batchStatus = (status: string) => statuses[status] || status.replaceAll("_", " ");

export function batchOutcome(batch: ProviderBatch, job: Job) {
  const progress = batchProgress(batch), succeeded = batchCount(batch.counts.succeeded);
  const failures = ([['errored', 'failed'], ['canceled', 'canceled'], ['expired', 'expired']] as const)
    .filter(([key]) => (batchCount(batch.counts[key]) || 0) > 0).map(([key, label]) => `${batch.counts[key]!.toLocaleString()} ${label}`);
  const terminal = terminalBatch(batch.status);
  let label = terminal && failures.length ? succeeded ? "Partial" : batch.counts.errored ? "Failed" : batch.counts.canceled ? "Canceled" : "Expired" : batchStatus(batch.status);
  if (terminal && !failures.length && activeRun(job)) label = job.phase === "consume" ? "Saving results" : job.process?.monitoring?.state === "collecting" ? "Receiving results" : label;
  const uniform = terminal && progress.total != null && (succeeded === progress.total || succeeded === 0 && failures.length === 1);
  const summary = uniform ? `${progress.total!.toLocaleString()} ${progress.total === 1 ? "request" : "requests"}` : [succeeded != null && (succeeded > 0 || !failures.length) ? `${succeeded.toLocaleString()}${progress.total != null ? `/${progress.total.toLocaleString()}` : ""} succeeded` : "", ...failures].filter(Boolean).join(" · ")
    || (progress.total != null ? `${progress.total.toLocaleString()} requests` : "Counts unavailable");
  return { label, summary, progress, pending: !terminal, failed: terminal && failures.length > 0 };
}
