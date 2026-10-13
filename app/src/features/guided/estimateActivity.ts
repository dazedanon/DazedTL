import type { Job, Progress } from "../../api/contracts";
import type { TranslationFlowState } from "./useTranslationFlow";

export type EstimateStepId = "check" | "estimate" | "batch";

const labels: Record<EstimateStepId, string> = {
  check: "Check files",
  estimate: "Estimate cost",
  batch: "Prepare Batch",
};

/** What a Translate estimate is doing, as steps toward its cost review. */
export type EstimateActivity = {
  steps: { id: EstimateStepId; label: string }[];
  /** The step working now; none while stopping. */
  current?: EstimateStepId;
  title: string;
  /** The share of the current step done. */
  fraction: number;
  /** The files the current step has worked through, while it counts them;
  `key` names that count, so its pace is never taken for another's. */
  count?: Progress & { key: string };
};

/** A file count a worker reported, once it has started. */
function counted(job: Job | undefined) {
  const progress = job?.progress;
  return progress &&
    Number.isSafeInteger(progress.current) &&
    Number.isSafeInteger(progress.total) &&
    progress.total > 0 &&
    progress.current > 0 &&
    progress.current <= progress.total
    ? progress
    : undefined;
}

/**
 * The steps from Translate to the cost review and where the flow stands.
 * A Live estimate opens its review once it is priced. A Batch one then
 * prepares the requests it would submit, after any names the glossary lacks
 * are reviewed and translated: usually the estimate's own requests, otherwise
 * built again file by file.
 */
export function estimateActivity(
  value: TranslationFlowState,
): EstimateActivity {
  const ids: EstimateStepId[] =
    value.mode === "batch"
      ? ["check", "estimate", "batch"]
      : ["check", "estimate"];
  const steps = ids.map((id) => ({ id, label: labels[id] }));
  const at = (
    current: EstimateStepId,
    title: string,
    {
      job,
      key = current,
      fraction,
    }: { job?: Job; key?: string; fraction?: number } = {},
  ): EstimateActivity => {
    const progress = counted(job);
    return {
      steps,
      current,
      title,
      fraction: fraction ?? (progress ? progress.current / progress.total : 0),
      count: progress && job && { ...progress, key: `${key}:${job.id}` },
    };
  };
  if (value.stage === "canceling")
    return { steps, title: "Stopping preparation…", fraction: 0 };
  if (value.stage === "preparing")
    return at("check", "Checking the selected files…");
  if (value.stage === "estimating") {
    const job = value.job?.id === value.estimateId ? value.job : undefined;
    const progress = counted(job);
    return at(
      "estimate",
      !progress
        ? "Starting the cost estimate…"
        : progress.current < progress.total
          ? "Estimating translation cost…"
          : "Finishing the cost estimate…",
      { job },
    );
  }
  if (value.mode !== "batch")
    return at("estimate", "Preparing the Live cost review…", { fraction: 1 });
  if (
    value.namesApproved &&
    (!value.job?.nameTranslation ||
      value.job.nameTranslation.state === "running")
  )
    return at("batch", "Translating names and labels…");
  const job = value.runId ? value.job : undefined;
  if (!job) return at("batch", "Checking the selected files…");
  const progress = counted(job);
  if (job.phase === "preparing")
    // Each Batch phase counts its files afresh. The Batch reuses the
    // estimate's speaker scan; a count before collecting is a scan it had to
    // repeat, which leaves the bar for the requests themselves.
    return progress && !value.namesApproved
      ? at("batch", "Finding speaker names…", {
          job,
          key: "speakers",
          fraction: 0,
        })
      : at("batch", "Starting the Batch preparation…");
  // Reusing the estimate's requests passes through collecting at once;
  // building them again counts files.
  if (job.phase === "collect")
    return at(
      "batch",
      !progress
        ? "Preparing the Batch requests…"
        : progress.current < progress.total
          ? "Building Batch requests…"
          : "Finishing the Batch requests…",
      { job },
    );
  return at("batch", "Pricing the Batch requests…", { fraction: 1 });
}
