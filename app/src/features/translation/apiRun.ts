import type { TranslationJob, TranslationState } from "../../api/contracts";

/** The current attempt's jobs; Run history keeps those from before the last start over. */
export function attemptJobs(state: TranslationState) {
  const since = state.lifecycle.started_over?.at;
  return state.jobs.filter(
    (job) => !since || Date.parse(job.created) > Date.parse(since),
  );
}

/** The latest API run the app holds for the assistant. */
export const latestApiRun = (jobs: TranslationJob[]) =>
  jobs.find((job) => job.kind === "translation" && job.mode !== "agent");

/** A prepared run's estimate while it waits for the user's spending decision. */
export const awaitingQuote = (run: TranslationJob | undefined) =>
  run?.status === "ready" && !run.approved ? run.quote : null;

/** An estimate priced with settings or a mode that have changed since. */
export const estimateOutdated = (run: TranslationJob | undefined) =>
  !!awaitingQuote(run) && !!run?.settings_changed;

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
      job.finishes === declined.id &&
      !estimateOutdated(job) &&
      ["ready", "running", "waiting", "interrupted", "stopped"].includes(
        job.status,
      ),
  );
