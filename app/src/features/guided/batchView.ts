import type { Job, RunProcess } from "../../api/contracts.ts";
import {
  activeRun,
  terminalBatch,
  providerBatchActive,
} from "./translationView.ts";
export { terminalBatch, providerBatchActive } from "./translationView.ts";

export type ProviderBatch = NonNullable<RunProcess["batches"]>[number];
export const batchCount = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined;
export function batchProgress(batch: ProviderBatch) {
  const total = batchCount(batch.total ?? batch.counts.total);
  const counts = ["succeeded", "errored", "canceled", "expired"].map((key) =>
    batchCount(batch.counts[key]),
  );
  const counted = counts.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  // Known outcomes can exhaust the total even when older receipts omit zero counts.
  const finished =
    counts.every((value) => value !== undefined) || counted === total
      ? counted
      : undefined;
  return {
    total,
    finished:
      total != null && finished != null && finished <= total
        ? finished
        : undefined,
  };
}
export function batchInProgress(job: Job) {
  const batches = job.process?.batches || [];
  // A stopped local worker does not stop provider work. Conversely, recovery
  // guards and stale polling phases do not make terminal failures active.
  if (batches.some((batch) => providerBatchActive(batch.status))) return true;
  const monitor = job.process?.monitoring?.state;
  if (monitor && ["error", "save_error", "blocked"].includes(monitor))
    return false;
  const collectable = batches.some(
    (batch) =>
      (batchCount(batch.counts.succeeded) || 0) > 0 ||
      (batch.counts.succeeded == null &&
        ["completed", "ended"].includes(batch.status)),
  );
  if (monitor === "collecting" && collectable) return true;
  if (activeRun(job) && !job.approval) {
    if (job.phase === "poll_capacity") return true;
    if (job.phase === "consume")
      return (job.process?.received || 0) > 0 || collectable;
    if (job.phase === "submit")
      return (
        !batches.length ||
        batches.every((batch) => batchOutcome(batch, job).successful)
      );
    if (
      job.phase?.startsWith("poll") &&
      batches.length &&
      batches.every((batch) => batchOutcome(batch, job).successful)
    )
      return true;
  }
  return (
    monitor === "monitoring" &&
    collectable &&
    batches.every((batch) => terminalBatch(batch.status))
  );
}
export function canRetrySaving(job: Job) {
  return (
    job.mode === "batch" &&
    !!job.process?.resultsCollected &&
    (job.process.received ?? 0) > 0 &&
    job.process?.monitoring?.state === "save_error" &&
    !job.process.remaining &&
    ["failed", "stopped", "interrupted", "canceled"].includes(job.status)
  );
}
export function canReapplyBatch(job: Job) {
  return (
    job.mode === "batch" &&
    job.status === "complete" &&
    !job.temporary &&
    job.outputsAvailable === true &&
    Object.keys(job.outputs || {}).length > 0
  );
}
const statuses: Record<string, string> = {
  validating: "Checking requests",
  in_progress: "Translating",
  finalizing: "Preparing results",
  cancelling: "Canceling",
  canceling: "Canceling",
  completed: "Completed",
  ended: "Completed",
  cancelled: "Canceled",
  canceled: "Canceled",
  failed: "Failed",
  expired: "Expired",
  unknown: "Status unavailable",
};
export const batchStatus = (status: string) =>
  statuses[status] || status.replaceAll("_", " ");

export function batchOutcome(batch: ProviderBatch, job: Job) {
  const progress = batchProgress(batch),
    succeeded = batchCount(batch.counts.succeeded);
  const failures = (
    [
      ["errored", "failed"],
      ["canceled", "canceled"],
      ["expired", "expired"],
    ] as const
  )
    .filter(([key]) => (batchCount(batch.counts[key]) || 0) > 0)
    .map(([key, label]) => `${batch.counts[key]!.toLocaleString()} ${label}`);
  const terminal = terminalBatch(batch.status);
  const hasResults =
    (succeeded || 0) > 0 ||
    (succeeded == null && ["completed", "ended"].includes(batch.status));
  const consuming =
    terminal && hasResults && activeRun(job) && job.phase === "consume";
  const collecting =
    terminal && hasResults && job.process?.monitoring?.state === "collecting";
  let label =
    terminal && failures.length
      ? succeeded
        ? "Partial"
        : batch.counts.errored
          ? "Failed"
          : batch.counts.canceled
            ? "Canceled"
            : "Expired"
      : batchStatus(batch.status);
  if (consuming || collecting)
    label = consuming ? "Saving results" : "Receiving results";
  const uniform =
    terminal &&
    progress.total != null &&
    (succeeded === progress.total ||
      (succeeded === 0 && failures.length === 1));
  const summary = uniform
    ? `${progress.total!.toLocaleString()} ${progress.total === 1 ? "request" : "requests"}`
    : [
        succeeded != null && (succeeded > 0 || !failures.length)
          ? `${succeeded.toLocaleString()}${progress.total != null ? `/${progress.total.toLocaleString()}` : ""} succeeded`
          : "",
        ...failures,
      ]
        .filter(Boolean)
        .join(" · ") ||
      (progress.total != null
        ? `${progress.total.toLocaleString()} requests`
        : "Counts unavailable");
  const providerActive = providerBatchActive(batch.status);
  const active = providerActive || consuming || collecting;
  const failed =
    terminal &&
    (failures.length > 0 || !["completed", "ended"].includes(batch.status));
  const successful =
    terminal &&
    !active &&
    !failed &&
    progress.total != null &&
    succeeded === progress.total;
  return {
    label,
    summary,
    progress,
    pending: providerActive,
    active,
    failed,
    successful,
  };
}
