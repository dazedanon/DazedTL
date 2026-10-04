import type { Job, Phase, RunPayload } from "../../api/contracts.ts";

export const activeRun = (run?: Job | null) => !!run && ["ready", "running", "waiting"].includes(run.status);

/** Preparation has a later approval exit; only running work needs a footer stop. */
export function translationStopLabel(run?: Job | null) {
  if (!run || !activeRun(run) || run.approval || run.mode === "estimate") return null;
  if (run.mode !== "batch" || run.phase === "consume") return "Stop translation";
  return run.process?.submitted || run.phase?.startsWith("poll") ? "Pause monitoring" : null;
}

/** A missing request log is not evidence of an empty translation estimate. */
export function estimateRequestCount(job?: Job | null) {
  const count = job?.estimate?.requests ?? job?.estimate?.request_count;
  return typeof count === "number" && Number.isSafeInteger(count) && count >= 0 ? count : undefined;
}

export function estimateFollowup(id: string, quote: { job?: Job | null; current: boolean } | undefined, runs: Job[], inputsChanged: boolean) {
  const job = quote?.job?.id === id ? quote.job : runs.find(run => run.id === id);
  if (!job || activeRun(job)) return { kind: "waiting" as const, job };
  if (job.status !== "complete") return { kind: "failed" as const, job };
  if (quote?.job?.id !== id || !quote.current || inputsChanged) return { kind: "stale" as const, job };
  return { kind: estimateRequestCount(job) === 0 ? "empty" as const : "review" as const, job };
}
export function phaseRun(runs: Job[], phase: Phase, selected?: readonly string[]) {
  const own = runs.filter(run => run.logicalPhase === phase)
    .sort((a, b) => (b.created || "").localeCompare(a.created || ""));
  const latest = own.find(run => run.mode !== "estimate" && activeRun(run)) || own[0];
  // Check scope after choosing the latest attempt. Falling back by overlap
  // revives old failures when selection changes or an estimate replaces them.
  return latest && latest.mode !== "estimate" && (activeRun(latest) || !latest.keptForHistory)
    && (!selected || latest.files?.some(name => selected.includes(name) && !latest.retiredFiles?.includes(name))) ? latest : undefined;
}
export const needsSubmissionReview = (run: Job) => run.mode !== "estimate" && run.status !== "complete" && !!run.process?.retryBlocked;
export const canResumeRun = (run: Job) => run.mode !== "estimate" && ["failed", "stopped", "interrupted"].includes(run.status)
  && (run.mode === "batch" && run.phase?.startsWith("poll") ? needsSubmissionReview(run)
    : !run.process?.retryBlocked && !(run.mode === "batch" && run.process?.failed));
export function completeForSelection(run: Job, selected: readonly string[]) {
  return !!run.scopeComplete && selected.length > 0 && run.files?.length === selected.length && selected.every(name => run.files!.includes(name) && !run.partialOutputs?.includes(name) && !run.retiredFiles?.includes(name));
}
export function filePreviewRun(name: string, run?: Job, estimate?: Job | null, previous?: Job, estimateCurrent = true) {
  if (run?.files?.includes(name) && activeRun(run)) return run;
  if (estimateCurrent && estimate?.files?.includes(name)) return estimate;
  if (run?.files?.includes(name) && run.scopeComplete) return run;
  const saved = previous?.files?.includes(name) ? previous : undefined;
  if (estimate?.files?.includes(name) && (estimateCurrent || !saved)) return estimate;
  return saved;
}
export function fileStatus(name: string, run?: Job, historical = false) {
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name)) return { label: "Ready", tone: "idle", symbol: "·" };
  const saved = run.availableOutputs?.includes(name) ?? (run.outputsAvailable && !!run.outputs?.[name]);
  if (saved && run.partialOutputs?.includes(name)) return { label: "Progress saved", tone: "active", symbol: "◐" };
  if (saved) return run.appliedOutputs?.includes(name)
    ? { label: "Applied", tone: "success", symbol: "✓" }
    : { label: "Saved", tone: "success", symbol: "✓" };
  if (run.outputs?.[name]) return { label: "Output unavailable", tone: "warning", symbol: "!" };
  if (historical && !needsSubmissionReview(run) && !activeRun(run)) return { label: "Ready", tone: "idle", symbol: "·" };
  const states = run.process?.requests?.filter(row => row.file === name).map(row => row.state) || [];
  if (states.includes("uncertain")) return { label: "Check submission", tone: "warning", symbol: "!" };
  if (states.includes("failed")) return { label: "Needs attention", tone: "warning", symbol: "!" };
  if (states.some(state => ["validated", "received"].includes(state))) return { label: "Partial results", tone: "active", symbol: "◐" };
  if (states.includes("submitted")) return { label: "Submitted", tone: "active", symbol: "◷" };
  if (activeRun(run)) return run.progress?.file === name
    ? { label: "Translating", tone: "active", symbol: "◷" } : { label: "Queued", tone: "idle", symbol: "·" };
  if (["failed", "interrupted", "stopped"].includes(run.status)) return { label: "Unfinished", tone: "warning", symbol: "!" };
  return { label: "No saved output", tone: "idle", symbol: "·" };
}

/** Pair only an exact line-key match or the validated Live result of equal length. */
export function translatedLines(payload: RunPayload): Record<string, string> | null {
  const keys = Object.keys(payload.source || {});
  if (!keys.length) return null;
  let value = payload.response;
  const response = value;
  if (Array.isArray(response)) return payload.state === "validated" && response.length === keys.length && response.every(item => typeof item === "string")
    ? Object.fromEntries(keys.map((key, index) => [key, response[index]])) : null;
  // The engine's Batch cache stores the provider's extracted response text.
  if (value && typeof value === "object" && !Array.isArray(value) && "text" in value) value = value.text;
  if (typeof value === "string") {
    try { value = JSON.parse(value.replace(/^\s*```(?:json)?\s*|\s*```\s*$/g, "")); } catch { return null; }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === keys.length && keys.every(key => typeof record[key] === "string") ? record as Record<string, string> : null;
}

/** Read only identifiable per-request blocks; never substitute today's glossary. */
export function requestContext(payload: RunPayload) {
  const text = (value: unknown): string => typeof value === "string" ? value : Array.isArray(value)
    ? value.map(block => typeof block?.text === "string" ? block.text : "").filter(Boolean).join("\n\n") : "";
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const dynamic = [payload.system, ...messages.filter(message => message.role === "system").map(message => message.content)]
    .map(value => Array.isArray(value) ? text(value.slice(1)) : text(value).replace(/^```[\s\S]*?\n```\s*(?=Here are glossary entries|Japanese SFX reference|$)/, ""))
    .filter(value => /^(Here are glossary entries|Japanese SFX reference)/.test(value.trim()));
  const context = payload.context as { source_items?: string[]; instructions?: string[] } | null;
  const section = (prefix: string) => messages.filter(message => message.role === "user" && text(message.content).startsWith(prefix))
    .map(message => { const content = text(message.content); return content.match(/```\n([\s\S]*?)\n```/)?.[1] || content; });
  return [
    { title: "Matched glossary & sound effects", text: [...new Set(dynamic)].join("\n\n"), notes: false },
    { title: "Preceding scene context", text: (context?.source_items || section("Preceding Japanese Source Context")).join("\n"), notes: false },
    { title: "Request-specific instructions", text: (context?.instructions || section("Request Instructions:")).join("\n"), notes: true },
  ].filter(section => section.text.trim());
}
