import type { Job, Phase, RunPayload } from "../../api/contracts.ts";

export const activeRun = (run?: Job | null) => !!run && ["ready", "running", "waiting"].includes(run.status);
export const terminalBatch = (status: string) => ["completed", "ended", "failed", "expired", "cancelled", "canceled"].includes(status);

/** Keep the inspector current without replacing its retained full log. */
export function observedRun(detail: Job | null, observed?: Job) {
  const time = (run: Job) => Math.max(Date.parse(run.updated || "") || 0, Date.parse(run.process?.monitoring?.checkedAt || "") || 0);
  if (!detail || !observed || detail.id !== observed.id || !time(observed) || time(observed) < time(detail)) return detail;
  return { ...detail, ...observed, log: detail.log };
}

/** Preparation has a later approval exit; only running work needs a footer stop. */
export function translationStopLabel(run?: Job | null) {
  if (!run || !activeRun(run) || run.approval || ["estimate", "batch"].includes(run.mode || "")) return null;
  return "Stop translation";
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
export const canResumeRun = (run: Job) => !run.temporary && !["estimate", "batch"].includes(run.mode || "")
  && ["failed", "stopped", "interrupted"].includes(run.status) && !run.process?.retryBlocked;
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
/** The observer supplies newest-first runs; a resumed worker owns its files. */
export function fileRun(runs: Job[], phase: Phase, name: string, retired: readonly string[] = []) {
  const matches = runs.filter(run => run.logicalPhase === phase && run.mode !== "estimate" && !retired.includes(run.id)
    && !run.retiredFiles?.includes(name) && run.files?.includes(name));
  return matches.find(activeRun) || matches[0];
}
export function blockingBatches(runs: Job[], selected: readonly string[]) {
  return runs.filter(run => run.mode === "batch" && !run.temporary
    && run.files?.some(name => selected.includes(name) && !run.retiredFiles?.includes(name))
    && (activeRun(run) || run.process?.batches?.some(batch => !terminalBatch(batch.status)) || needsSubmissionReview(run) && !run.process?.resultsCollected
      || ["monitoring", "collecting"].includes(run.process?.monitoring?.state || "")
      || ["stopped", "interrupted"].includes(run.status) && (!!run.process?.batches?.length && !!run.phase?.startsWith("poll") || run.process?.resultsCollected)));
}
export function fileStatus(name: string, run?: Job, historical = false) {
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name)) return { label: "Ready", tone: "idle", symbol: "·" };
  if (run.temporary) {
    if (["failed", "interrupted"].includes(run.status)) return { label: "Needs attention", tone: "warning", symbol: "!" };
    return { label: run.approval ? "Review cost" : activeRun(run) ? "Preparing" : "Ready", tone: activeRun(run) ? "active" : "idle", symbol: activeRun(run) ? "◷" : "·" };
  }
  const saved = run.availableOutputs?.includes(name) ?? (run.outputsAvailable && !!run.outputs?.[name]);
  const states = run.process?.requests?.filter(row => row.file === name).map(row => row.state) || [];
  const progress = run.itemProgress;
  const translating = run.mode === "translate" && progress?.file === name && Number.isSafeInteger(progress.current) && Number.isSafeInteger(progress.total)
    && progress.total > 0 && progress.current >= 0 && progress.current <= progress.total ? `Translating ${progress.current}/${progress.total}` : "Translating";
  if (run.mode === "batch" && run.process?.monitoring) {
    if (["error", "save_error", "blocked"].includes(run.process.monitoring.state)) return { label: "Needs attention", tone: "warning", symbol: "!" };
    return { label: run.process.monitoring.state === "collecting" ? "Receiving results" : "Awaiting Batch", tone: "active", symbol: "◷" };
  }
  // Retained checkpoints describe available output, not the active operation.
  if (activeRun(run)) {
    if (run.approval) return { label: "Review cost", tone: "active", symbol: "◷" };
    if (states.includes("uncertain")) return { label: "Check submission", tone: "warning", symbol: "!" };
    if (states.includes("failed")) return { label: "Needs attention", tone: "warning", symbol: "!" };
    if (states.includes("submitted")) return { label: run.mode === "batch" ? "Submitted" : translating, tone: "active", symbol: "◷" };
    if (states.some(state => ["queued", "prepared"].includes(state))) return { label: run.mode !== "batch" && run.progress?.file === name ? translating : "Queued", tone: "active", symbol: "◷" };
    if (!saved || run.partialOutputs?.includes(name)) {
      if (run.mode === "batch" && run.phase === "consume") return { label: "Saving results", tone: "active", symbol: "◷" };
      if (states.some(state => ["received", "validated"].includes(state))) return { label: run.mode === "translate" && run.progress?.file === name ? translating : "Received", tone: "active", symbol: "◐" };
      if (run.mode === "batch" && run.phase?.startsWith("poll")) return { label: "Awaiting Batch", tone: "active", symbol: "◷" };
      if (run.phase === "submit") return { label: "Submitting", tone: "active", symbol: "◷" };
      return { label: run.progress?.file === name ? translating : "Queued", tone: "active", symbol: "◷" };
    }
  }
  if (run.mode === "batch" && (run.phase?.startsWith("poll") || run.process?.resultsCollected) && ["stopped", "interrupted"].includes(run.status))
    return { label: run.process?.resultsCollected ? "Waiting to save" : "Awaiting Batch", tone: "active", symbol: "◷" };
  if (run.mode === "translate" && !historical && (!saved || run.partialOutputs?.includes(name))) {
    if (["stopped", "interrupted"].includes(run.status)) return { label: run.status === "stopped" ? "Stopped" : "Interrupted", tone: "warning", symbol: "Ⅱ" };
    if (run.status === "failed") return { label: "Needs attention", tone: "warning", symbol: "!" };
  }
  if (saved && run.partialOutputs?.includes(name)) return { label: "Progress saved", tone: "active", symbol: "◐" };
  if (saved) return run.appliedOutputs?.includes(name)
    ? { label: "Applied", tone: "success", symbol: "✓" }
    : { label: "Saved", tone: "success", symbol: "✓" };
  if (run.outputs?.[name]) return { label: "Output unavailable", tone: "warning", symbol: "!" };
  if (historical && !needsSubmissionReview(run) && !activeRun(run)) return { label: "Ready", tone: "idle", symbol: "·" };
  if (states.includes("uncertain")) return { label: "Check submission", tone: "warning", symbol: "!" };
  if (states.includes("failed")) return { label: "Needs attention", tone: "warning", symbol: "!" };
  if (states.some(state => ["validated", "received"].includes(state))) return { label: "Partial results", tone: "active", symbol: "◐" };
  if (states.includes("submitted")) return { label: "Submitted", tone: "active", symbol: "◷" };
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
