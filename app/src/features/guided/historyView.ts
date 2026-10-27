import type { Job } from "../../api/contracts.ts";
import { plural } from "../../ui/displayText.ts";
import { activeRun, needsSubmissionReview } from "./translationView.ts";

export type HistoryOutcome = {
  kind:
    | "active"
    | "approval"
    | "review"
    | "failed"
    | "stopped"
    | "canceled"
    | "estimate"
    | "saved"
    | "partial"
    | "missing"
    | "empty"
    | "finished"
    | "undone";
  label: string;
  detail: string;
};
/** History's lists: translation runs, estimates and other activity. */
export type HistoryTab = "runs" | "estimates" | "operations";
/** How History names each phase, so links can search for one stage's runs. */
export const historyPhaseLabels: Record<string, string> = {
  database: "Database",
  dialogue: "Maps & events",
  advanced: "Other event text",
  variables: "Comparisons",
  speakers: "Speakers",
};
export const historyPhase = (job: Job) =>
  (job.logicalPhase && historyPhaseLabels[job.logicalPhase]) || "Translation";
export const historyMode = (job: Job) =>
  job.mode === "estimate"
    ? "Estimate"
    : job.mode === "batch"
      ? "Batch"
      : job.mode === "speakers"
        ? "Names"
        : job.mode === "offline"
          ? "Offline"
          : "Live";

/** Describe retained evidence without treating a completed job as saved output. */
export function historyOutcome(job: Job): HistoryOutcome {
  const process = job.process;
  const saved =
    job.availableOutputs ??
    (job.outputsAvailable === true
      ? Object.keys(job.outputs || {})
      : undefined);
  const partialNames = new Set(job.partialOutputs || []);
  const partial = saved?.filter((name) => partialNames.has(name)) || [];
  const whole = saved?.filter((name) => !partialNames.has(name));
  const output = [
    whole?.length ? `${plural(whole.length, "file")} saved` : "",
    partial.length ? `${plural(partial.length, "partial file")} saved` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const prepared = process?.prepared;
  const received = process?.received;
  // Requests the provider errored, refused or never received.
  const failed = process?.failed;
  const requestDetail = [
    failed ? `${failed.toLocaleString()} failed` : "",
    process?.remaining ? `${process.remaining.toLocaleString()} unsent` : "",
    received ? `${received.toLocaleString()} received` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const evidence =
    [output, requestDetail].filter(Boolean).join(" · ") ||
    (prepared != null
      ? `${plural(prepared, "request")} prepared`
      : "Request counts not recorded");
  if (job.approval)
    return {
      kind: "approval",
      label: "Review cost",
      detail:
        prepared != null
          ? `${plural(prepared, "request")} prepared`
          : "Approval required",
    };
  const atProvider = job.mode === "batch" && !!job.phase?.startsWith("poll");
  if (activeRun(job))
    return {
      kind: "active",
      label:
        job.mode === "estimate"
          ? "Estimating"
          : job.phase === "poll_capacity"
            ? "Waiting for capacity"
            : // The provider has finished; the app downloads its results.
              job.process?.monitoring?.state === "collecting"
              ? "Receiving results"
              : atProvider
                ? "At provider"
                : "In progress",
      // Requests at the provider are submitted, not merely prepared.
      detail:
        atProvider && !output && !requestDetail && prepared != null
          ? `${plural(prepared, "request")} submitted`
          : evidence,
    };
  if (needsSubmissionReview(job))
    return {
      kind: "review",
      label: "Check submission",
      detail: process?.uncertain
        ? `${plural(process.uncertain, "uncertain request")}`
        : evidence,
    };
  if (job.status === "failed")
    return { kind: "failed", label: "Failed", detail: evidence };
  if (job.status === "interrupted" || job.status === "stopped")
    return {
      kind: "stopped",
      label: job.status === "stopped" ? "Stopped" : "Interrupted",
      detail: evidence,
    };
  if (job.status === "canceled" || job.status === "cancelled")
    return { kind: "canceled", label: "Canceled", detail: evidence };
  if (job.mode === "estimate")
    return {
      kind: "estimate",
      label: "Estimate ready",
      detail:
        prepared != null
          ? `${plural(prepared, "request")} planned`
          : "Request count not recorded",
    };
  const savedNames = new Set(saved);
  const missing = Object.keys(job.outputs || {}).filter(
    (name) => saved && !savedNames.has(name),
  );
  if (
    missing.length ||
    (job.outputsAvailable === false &&
      Object.keys(job.outputs || {}).length &&
      !saved)
  )
    return {
      kind: "missing",
      label: "Output unavailable",
      detail: output || "Saved output could not be verified",
    };
  if (process?.validationIssues?.length)
    return {
      kind: "partial",
      label: output ? "Saved with issues" : "Validation failed",
      detail: [
        output,
        process.rejected
          ? `${process.rejected} ${process.rejected === 1 ? "request" : "requests"} rejected`
          : "Translation validation needs review",
      ]
        .filter(Boolean)
        .join(" · "),
    };
  if (partial.length)
    return { kind: "partial", label: "Progress saved", detail: output };
  if (whole?.length)
    return { kind: "saved", label: "Output saved", detail: output };
  if (saved === undefined && Object.keys(job.outputs || {}).length)
    return {
      kind: "finished",
      label: "Finished",
      detail: "Output availability not recorded",
    };
  if (prepared === 0)
    return { kind: "empty", label: "No new requests", detail: "" };
  return {
    kind: "finished",
    label:
      job.status === "complete" ? "Finished" : job.status.replaceAll("_", " "),
    detail: requestDetail || "Output not recorded",
  };
}

export function historyDay(created?: string): string {
  const value = new Date(created || "");
  return Number.isNaN(value.getTime())
    ? "undated"
    : `${value.getFullYear()}-${value.getMonth()}-${value.getDate()}`;
}
/** "Today" or "Yesterday" for a recent day, otherwise undefined. */
function recentDay(date: Date) {
  const now = new Date(),
    yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const day = historyDay(date.toISOString());
  return day === historyDay(now.toISOString())
    ? "Today"
    : day === historyDay(yesterday.toISOString())
      ? "Yesterday"
      : undefined;
}
const shortDate = (date: Date) =>
  date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== new Date().getFullYear()
      ? { year: "numeric" }
      : {}),
  });
export function historyDate(created?: string): string {
  const date = new Date(created || "");
  if (Number.isNaN(date.getTime())) return "Date not recorded";
  return `${recentDay(date) || date.toLocaleDateString([], { weekday: "short" })} · ${shortDate(date)}`;
}
/** A run's start time as its Run history row shows it. */
export const historyTime = (created: string) =>
  new Date(created).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
/** When a run started, in words that find its Run history row. */
export function historyWhen(created?: string): string {
  const date = new Date(created || "");
  if (!created || Number.isNaN(date.getTime())) return "";
  const day = recentDay(date);
  return `${day ? day.toLowerCase() : "on " + shortDate(date)} at ${historyTime(created)}`;
}

/** A finished operation's result in a sentence, such as "3 files saved.". */
export function operationSummary(job: Job): string {
  const result = job.result;
  if (!result) return "";
  // An operation's own sentence, such as a fit's rewrapped lines, says more
  // than its count of files.
  if (typeof result.message === "string" && result.message)
    return result.message;
  // Start over reports the files it put back; a reload, the files it read.
  if (typeof result.restored === "number")
    return `${result.restored ? `${result.restored} ${result.restored === 1 ? "file" : "files"} put back to the original game.` : "The game already matched the original."}${result.archive ? " The assistant's work is set aside." : ""}`;
  if (typeof result.archive === "string")
    return `${Number(result.files || 0)} ${result.files === 1 ? "file" : "files"} reloaded from the game. Previous copies and outputs archived.`;
  if (typeof result.files === "number")
    return `${result.files} ${result.files === 1 ? "file" : "files"} saved.`;
  if (typeof result.changes_found === "number")
    return `${result.changes_found} text-fitting changes found · ${Number(result.overflow_skipped || 0)} protected overflows skipped.`;
  if (typeof result.reviewed_files === "number")
    return `${result.reviewed_files} current runtime files reviewed.`;
  if (typeof result.path === "string") return result.path;
  if (Array.isArray(result.messages))
    return result.messages
      .filter((value) => typeof value === "string")
      .join(" ");
  return "";
}
