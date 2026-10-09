import type { TranslationJob, TranslationState } from "../../api/contracts";

/** The current attempt's jobs; Run history keeps those from before the last start over. */
export function attemptJobs(state: TranslationState) {
  const since = state.lifecycle.started_over?.at;
  return state.jobs.filter(
    (job) => !since || Date.parse(job.created) > Date.parse(since),
  );
}

/** The latest API run the app holds for the assistant. */
export const apiRun = (jobs: TranslationJob[]) =>
  jobs.find((job) => job.kind === "translation" && job.mode !== "agent");

/** The run's estimate while it waits for the user's spending decision. */
export const awaitingQuote = (run: TranslationJob | undefined) =>
  run && !run.approved && !["complete", "uncertain"].includes(run.status)
    ? run.quote
    : null;
