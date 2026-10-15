import type {
  TranslationBatch,
  TranslationJob,
  TranslationState,
} from "../../api/contracts";
import { batchStatus } from "../guided/batchView.ts";

/** The current attempt's jobs; Run history keeps those from before the last start over. */
export function attemptJobs(state: TranslationState) {
  const since = state.lifecycle.started_over?.at;
  return state.jobs.filter(
    (job) => !since || Date.parse(job.created) > Date.parse(since),
  );
}

/**
 * Whether pages show a run: an estimate nobody approved only while it can
 * still be approved, not once it was discarded or a newer one replaced it.
 */
export const listedRun = (job: TranslationJob) =>
  !job.quote || job.approved || job.status === "ready";

/** The latest API run the app holds for the assistant. */
export const latestApiRun = (jobs: TranslationJob[]) =>
  jobs.find(
    (job) =>
      job.kind === "translation" && job.mode !== "agent" && listedRun(job),
  );

/** A prepared run's estimate while it waits for the user's spending decision. */
export const awaitingQuote = (run: TranslationJob | undefined) =>
  run?.status === "ready" && !run.approved ? run.quote : null;

/**
 * A price that may be a range, such as a Claude Batch that may reuse its
 * cached instructions or none of them.
 */
export const priceRange = (
  money: (value: number) => string,
  high: number,
  low?: number,
) =>
  low !== undefined && low < high
    ? `${money(low)}–${money(high)}`
    : money(high);

/** An estimate priced with settings or a mode that have changed since. */
export const estimateOutdated = (run: TranslationJob | undefined) =>
  !!awaitingQuote(run) && !!run?.settings_changed;

/**
 * The preparation estimating an outdated run again with the current
 * settings, started after it, while it works or once it failed; a finished
 * one has made a newer run.
 */
export const redoneEstimate = (jobs: TranslationJob[], run: TranslationJob) =>
  jobs.find(
    (job) =>
      job.kind === "operation" &&
      ["organize", "compile"].includes(job.action ?? "") &&
      !job.finishes &&
      Date.parse(job.created) > Date.parse(run.created),
  );

/**
 * Whether the user approved the run in the app after the assistant last used
 * DazedTL, so the assistant may still be waiting for an answer.
 */
export const approvalUntold = (
  run: TranslationJob | undefined,
  assistantSeenAt: string | null,
) =>
  !!run?.app_approved_at &&
  !(
    assistantSeenAt &&
    Date.parse(assistantSeenAt) >= Date.parse(run.app_approved_at)
  );

/** The latest Assistant only run while it has lines the assistant declined. */
export const declinedRun = (jobs: TranslationJob[]) => {
  const run = jobs.find(
    (job) => job.kind === "translation" && job.mode === "agent",
  );
  return run?.declined_units ? run : undefined;
};

/**
 * The API run translating a run's declined lines while its estimate waits
 * for approval or it still works; an outdated or ended one can be redone.
 */
export const finishingRun = (
  jobs: TranslationJob[],
  declined: TranslationJob,
) =>
  jobs.find(
    (job) =>
      job.kind === "translation" &&
      job.finishes === declined.id &&
      !estimateOutdated(job) &&
      ["ready", "running", "waiting", "interrupted", "stopped"].includes(
        job.status,
      ),
  );

/** The latest operation estimating a run's declined lines, which compiles
    and prices their requests before the API run exists. */
export const declinedEstimate = (
  jobs: TranslationJob[],
  declined: TranslationJob,
) =>
  jobs.find((job) => job.kind === "operation" && job.finishes === declined.id);

/** A run's request state as the run inspector names it; a tone marks the
    states that need the user. */
export function requestState(state: string) {
  if (state === "failed") return { label: "Failed", tone: "error" } as const;
  if (state === "uncertain")
    return { label: "Submission unconfirmed", tone: "warning" } as const;
  return {
    label:
      (
        {
          pending: "Pending",
          sending: "Sending",
          queued: "At provider",
          accepted: "Saved",
          declined: "Declined",
        } as Record<string, string>
      )[state] || "Status unavailable",
    tone: undefined,
  };
}

/** How a run sends its requests, as History names it. */
export const runMode = (job: TranslationJob) =>
  job.mode === "agent"
    ? "Agent"
    : job.mode === "batch"
      ? "API Batch"
      : "Live API";

// The run's own Batch states that say more than the provider's status.
const batchStates: Record<string, string> = {
  pending: "Not sent",
  submitting: "Not confirmed",
  unmatched: "Not matched",
  rejected: "Rejected",
};

/** Where one of a run's Batches stands. */
export const batchLabel = (batch: TranslationBatch) =>
  batchStates[batch.state] ??
  (batch.api_status
    ? batchStatus(batch.api_status)
    : batch.state === "complete"
      ? "Completed"
      : batch.state === "canceled"
        ? "Canceled"
        : "Submitted");

/** A submission that may have reached the provider; its job can be attached. */
export const unconfirmedBatch = (batch: TranslationBatch) =>
  batch.state === "submitting" || batch.state === "unmatched";

/** A run's Batches counted by where they stand: "11 completed · 6 not sent". */
export function batchSummary(batches: TranslationBatch[]) {
  const counts = new Map<string, number>();
  for (const batch of batches) {
    const label = batchLabel(batch);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts]
    .map(([label, count]) => `${count.toLocaleString()} ${label.toLowerCase()}`)
    .join(" · ");
}
