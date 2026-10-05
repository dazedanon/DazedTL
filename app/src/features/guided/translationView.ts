import type { GuidedState, Job, Phase, RunPayload, RunProcess } from "../../api/contracts.ts";

export const activeRun = (run?: Job | null) => !!run && ["ready", "running", "waiting"].includes(run.status);
const activeWorker = (run?: Job | null) => !!run && ["ready", "running", "waiting"].includes(run.workerStatus ?? run.status);
export const terminalBatch = (status: string) => ["completed", "ended", "failed", "expired", "cancelled", "canceled"].includes(status);
export const providerBatchActive = (status: string) => ["validating", "in_progress", "finalizing", "cancelling", "canceling"].includes(status);
export const requestStateLabel = (state: string) => ({ unused: "Unused duplicate", rejected: "Validation failed",
  validated: "Validation passed", saved: "Validation passed", received: "Not validated" } as Record<string, string>)[state] || state;

/** Keep raw receipt indices stable while presenting one selection per source request. */
export function groupedRequests(rows: NonNullable<RunProcess["requests"]>) {
  const groups: (typeof rows[number] & { indices: number[]; number: number })[] = [];
  const owners = new Map<number, typeof groups[number]>();
  for (const row of rows) {
    const parent = row.clarificationOf == null ? undefined : owners.get(row.clarificationOf);
    if (parent && parent.file === row.file) {
      parent.indices.push(row.index);
      parent.state = row.state;
      parent.providerFinished = row.providerFinished;
      owners.set(row.index, parent);
    } else {
      const group = { ...row, indices: [row.index], number: groups.length + 1 };
      groups.push(group);
      owners.set(row.index, group);
    }
  }
  return groups;
}

/** Attempt changes use the already loaded receipt, without another backend read. */
export function requestAttempt(payload: RunPayload, index: number) {
  const attempt = payload.responseAttempts?.[index];
  return attempt?.payload || (attempt ? { ...payload, response: attempt.response } : payload);
}

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
/** A late observation of the answered name approval cannot reopen it. */
export function preparationFollowup(id: string, runs: Job[], answeredApproval?: string) {
  const job = runs.find(run => run.id === id);
  if (!job || answeredApproval && job.approval?.token === answeredApproval) return { kind: "waiting" as const };
  if (job.approval) return { kind: "review" as const, job };
  if (["failed", "interrupted", "stopped", "canceled"].includes(job.status)) return { kind: "failed" as const, job };
  return { kind: job.status === "complete" ? "empty" as const : "waiting" as const, job };
}
export function phaseRun(runs: Job[], phase: Phase, selected?: readonly string[]) {
  const own = runs.filter(run => run.logicalPhase === phase)
    .sort((a, b) => (b.created || "").localeCompare(a.created || ""));
  const latest = own.find(run => run.mode !== "estimate" && activeWorker(run)) || own[0];
  // Check scope after choosing the latest attempt. Falling back by overlap
  // revives old failures when selection changes or an estimate replaces them.
  return latest && latest.mode !== "estimate"
    && (!selected || latest.files?.some(name => selected.includes(name) && !latest.retiredFiles?.includes(name))) ? latest : undefined;
}
export const needsSubmissionReview = (run: Job) => run.mode !== "estimate" && run.status !== "complete" && !!run.process?.retryBlocked;
export const canResumeRun = (run: Job) => !run.temporary && !["estimate", "batch"].includes(run.mode || "")
  && ["failed", "stopped", "interrupted"].includes(run.status) && !run.process?.retryBlocked;
export function completeForSelection(run: Job, selected: readonly string[]) {
  return !!run.scopeComplete && selected.length > 0 && run.files?.length === selected.length && selected.every(name => run.files!.includes(name) && !run.partialOutputs?.includes(name) && !run.retiredFiles?.includes(name));
}
export function filePreviewRun(name: string, run?: Job, estimate?: Job | null, previous?: Job, estimateCurrent = true) {
  if (run?.files?.includes(name) && activeWorker(run)) return run;
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
  return matches.find(activeWorker) || matches[0];
}
/** Task progress covers the whole file group, independently of the next action's selection. */
export function translationTaskComplete(state: Pick<GuidedState, "files" | "runs" | "sourceStatus">, phase: "database" | "dialogue") {
  const files = state.files.filter(file => file.group === phase);
  return files.length > 0 && files.every(({ name }) => {
    if (state.sourceStatus.changed.includes(name)) return false;
    const run = fileRun(state.runs, phase, name, state.sourceStatus.retired);
    if (!run || run.temporary || activeWorker(run) || run.partialOutputs?.includes(name)) return false;
    // Completion remains conservative even when a retained file can be shown
    // normally while an interrupted Batch still has unfinished run work.
    if (run.mode === "batch" && ["stopped", "interrupted"].includes(run.workerStatus ?? run.status)
      && (run.phase?.startsWith("poll") || run.process?.resultsCollected)) return false;
    return fileStatus(name, run).tone === "success"
      || run.mode === "batch" && !run.outputs?.[name] && !!run.process?.noRequestFiles?.includes(name);
  });
}
/** Status follows current work; metrics follow the last run that changed this file. */
export function fileMetricRun(runs: Job[], phase: Phase, name: string, retired: readonly string[] = []) {
  const matches = runs.filter(run => run.logicalPhase === phase && run.mode !== "estimate" && !run.temporary
    && !retired.includes(run.id) && !run.retiredFiles?.includes(name) && run.files?.includes(name));
  const changed = (run: Job) => run.changedOutputs !== undefined ? run.changedOutputs.includes(name)
    : !run.process?.noRequestFiles?.includes(name) && !!run.process?.fileMetrics?.[name];
  return matches.find(run => activeWorker(run) && changed(run)) || matches.find(changed);
}
/** Unsettled Batches remain visible independently of Apply and working-file reloads. */
export function unsettledBatches(runs: Job[], selected: readonly string[]) {
  return runs.filter(run => run.mode === "batch" && !run.temporary
    && run.files?.some(name => selected.includes(name) && !run.retiredFiles?.includes(name))
    && (activeRun(run) || run.process?.batches?.some(batch => !terminalBatch(batch.status))
      || needsSubmissionReview(run) && !run.process?.resultsCollected
      || ["monitoring", "collecting"].includes(run.process?.monitoring?.state || "")
      || ["stopped", "interrupted"].includes(run.status) && (!!run.process?.batches?.length && !!run.phase?.startsWith("poll") || run.process?.resultsCollected)));
}
/** File receipts and verified output own the row; run diagnostics stay in Inspect. */
export function fileStatus(name: string, run?: Job) {
  const idle = { label: "Not started", tone: "idle", symbol: "·", pending: false };
  const complete = { label: "Complete", tone: "success", symbol: "✓", pending: false };
  const progress = { label: "In progress", tone: "active", symbol: "◷", pending: true };
  const incomplete = { label: "Incomplete", tone: "idle", symbol: "◐", pending: false };
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name)) return idle;
  const saved = run.availableOutputs?.includes(name) ?? (run.outputsAvailable && !!run.outputs?.[name]);
  const noRequests = run.mode === "batch" && run.process?.noRequestFiles?.includes(name);
  if (noRequests && !saved && !run.outputs?.[name]) return complete;
  if (run.temporary) {
    return activeWorker(run) ? { ...progress, pending: !run.approval } : idle;
  }
  const rows = groupedRequests(run.process?.requests?.filter(row => row.file === name) || []);
  const states = rows.map(row => row.state);
  const partial = run.partialOutputs?.includes(name) || run.process?.validationIssues?.some(issue => issue.file === name);
  const working = activeWorker(run);
  if (!noRequests && (run.workerStatus ?? run.status) !== "complete") {
    if (working && run.approval) return { ...progress, pending: false };
    const submitted = rows.filter(row => row.state === "submitted");
    if (run.mode === "batch" && submitted.length) {
      // A retained submission protects against duplicate charges; it does not
      // establish current provider activity. Match the latest attempt to its
      // Batch receipts, including any clarification under the original index.
      const batches = run.process?.batches || [];
      const belongs = (batch: typeof batches[number], row: typeof submitted[number]) => batch.requestIndices?.includes(row.indices.at(-1)!);
      if (batches.some(batch => providerBatchActive(batch.status) && submitted.some(row => belongs(batch, row)))) return progress;
      const finished = submitted.every(row => row.providerFinished && batches.some(batch => belongs(batch, row) && ["completed", "ended"].includes(batch.status)));
      if (finished) return progress;
    }
    if (working && run.mode !== "batch" && submitted.length) return progress;
    if (working && states.some(state => ["queued", "prepared"].includes(state))) return progress;
    if (!saved || partial && working) {
      if (working && states.some(state => ["received", "validated"].includes(state)) && (run.mode !== "batch" || run.phase === "consume")) return progress;
      // Item progress identifies the file still being parsed between requests,
      // including after rejection; progress.file is the last finished file.
      if (working && run.mode !== "batch" && run.itemProgress?.file === name) return progress;
    }
  }
  if (saved && partial) return incomplete;
  if (saved) return run.appliedOutputs?.includes(name)
    ? { ...complete, label: "Applied" }
    : complete;
  if (run.outputs?.[name]) return { ...incomplete, tone: "warning", symbol: "!" };
  if (partial || states.length) return incomplete;
  if (working && run.mode !== "batch") return progress;
  return idle;
}

/** Pair only an exact line-key match or the validated Live result of equal length. */
export function translatedLines(payload: RunPayload): Record<string, string> | null {
  if (["rejected", "unused"].includes(payload.state)) return null;
  const keys = Object.keys(payload.source || {});
  if (!keys.length) return null;
  // New Live receipts retain both raw bodies and independently validated values.
  // A received or rejected raw body must not become a saved-text comparison.
  let value = "translations" in payload ? payload.translations : payload.response;
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
