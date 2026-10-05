import type { Job } from "../../api/contracts.ts";
import { activeRun, needsSubmissionReview } from "./translationView.ts";

export type HistoryOutcome = {
  kind: "active" | "approval" | "review" | "failed" | "stopped" | "canceled" | "estimate" | "saved" | "partial" | "missing" | "empty" | "finished";
  label: string;
  detail: string;
};
const count = (value: number, noun: string) => `${value.toLocaleString()} ${noun}${value === 1 ? "" : "s"}`;
export const historyPhase = (job: Job) => (job.logicalPhase && ({ database: "Database", dialogue: "Maps & events", advanced: "Event / plugin codes", variables: "Comparisons", speakers: "Speakers" })[job.logicalPhase]) || "Translation";
export const historyMode = (job: Job) => job.mode === "estimate" ? "Estimate" : job.mode === "batch" ? "Batch" : job.mode === "speakers" ? "Names" : job.mode === "offline" ? "Offline" : "Live";

/** Describe retained evidence without treating a completed job as saved output. */
export function historyOutcome(job: Job): HistoryOutcome {
  const process = job.process;
  const saved = job.availableOutputs ?? (job.outputsAvailable === true ? Object.keys(job.outputs || {}) : undefined);
  const partialNames = new Set(job.partialOutputs || []);
  const partial = saved?.filter(name => partialNames.has(name)) || [];
  const whole = saved?.filter(name => !partialNames.has(name));
  const output = [whole?.length ? `${count(whole.length, "file")} saved` : "", partial.length ? `${count(partial.length, "partial file")} saved` : ""].filter(Boolean).join(" · ");
  const prepared = process?.prepared;
  const received = process?.received;
  const rejected = process?.failed;
  const requestDetail = [rejected ? `${rejected.toLocaleString()} rejected` : "", process?.remaining ? `${process.remaining.toLocaleString()} unsent` : "",
    received ? `${received.toLocaleString()} received` : ""].filter(Boolean).join(" · ");
  const evidence = [output, requestDetail].filter(Boolean).join(" · ") || (prepared != null ? `${count(prepared, "request")} prepared` : "Request counts not recorded");
  if (job.approval) return { kind: "approval", label: "Review cost", detail: prepared != null ? `${count(prepared, "request")} prepared` : "Approval required" };
  if (activeRun(job)) return { kind: "active", label: job.mode === "estimate" ? "Estimating" : job.mode === "batch" && job.phase?.startsWith("poll") ? "At provider" : "In progress", detail: evidence };
  if (needsSubmissionReview(job)) return { kind: "review", label: "Check submission", detail: process?.uncertain ? `${count(process.uncertain, "uncertain request")}` : evidence };
  if (job.status === "failed" || job.status === "needs_attention") return { kind: "failed", label: "Failed", detail: evidence };
  if (job.status === "interrupted" || job.status === "stopped") return { kind: "stopped", label: job.status === "stopped" ? "Stopped" : "Interrupted", detail: evidence };
  if (job.status === "canceled" || job.status === "cancelled") return { kind: "canceled", label: "Canceled", detail: evidence };
  if (job.mode === "estimate") return { kind: "estimate", label: "Estimate ready", detail: prepared != null ? `${count(prepared, "request")} planned` : "Request count not recorded" };
  const savedNames = new Set(saved);
  const missing = Object.keys(job.outputs || {}).filter(name => saved && !savedNames.has(name));
  if (missing.length || job.outputsAvailable === false && Object.keys(job.outputs || {}).length && !saved)
    return { kind: "missing", label: "Output unavailable", detail: output || "Saved output could not be verified" };
  if (process?.validationIssues?.length) return { kind: "partial", label: output ? "Saved with issues" : "Validation failed", detail: [output, process.rejected ? `${process.rejected} requests rejected` : "Translation validation needs review"].filter(Boolean).join(" · ") };
  if (partial.length) return { kind: "partial", label: "Progress saved", detail: output };
  if (whole?.length) return { kind: "saved", label: "Output saved", detail: output };
  if (saved === undefined && Object.keys(job.outputs || {}).length) return { kind: "finished", label: "Finished", detail: "Output availability not recorded" };
  if (prepared === 0) return { kind: "empty", label: "No new requests", detail: "" };
  return { kind: "finished", label: job.status === "complete" ? "Finished" : job.status.replaceAll("_", " "), detail: requestDetail || "Output not recorded" };
}

export function historyDay(created?: string): string {
  const value = new Date(created || "");
  return Number.isNaN(value.getTime()) ? "undated" : `${value.getFullYear()}-${value.getMonth()}-${value.getDate()}`;
}
export function historyDate(created?: string): string {
  const date = new Date(created || "");
  if (Number.isNaN(date.getTime())) return "Date not recorded";
  const now = new Date(), yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const prefix = historyDay(created) === historyDay(now.toISOString()) ? "Today" : historyDay(created) === historyDay(yesterday.toISOString()) ? "Yesterday" : date.toLocaleDateString([], { weekday: "short" });
  return `${prefix} · ${date.toLocaleDateString([], { month: "short", day: "numeric", ...(date.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) })}`;
}
