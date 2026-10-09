import type {
  GuidedState,
  Job,
  Phase,
  RunPayload,
  RunProcess,
} from "../../api/contracts.ts";
import { type DisplayState, displayLabels } from "../../ui/displayStatus.ts";

export const activeRun = (run?: Job | null) =>
  !!run && ["ready", "running", "waiting"].includes(run.status);
const activeWorker = (run?: Job | null) =>
  !!run &&
  ["ready", "running", "waiting"].includes(run.workerStatus ?? run.status);
export const terminalBatch = (status: string) =>
  ["completed", "ended", "failed", "expired", "cancelled", "canceled"].includes(
    status,
  );
export const providerBatchActive = (status: string) =>
  [
    "validating",
    "in_progress",
    "finalizing",
    "cancelling",
    "canceling",
  ].includes(status);
export const requestStateLabel = (state: string) =>
  (
    ({
      unused: "Unused duplicate",
      rejected: "Validation failed",
      validated: "Validation passed",
      saved: "Validation passed",
      received: "Not validated",
    }) as Record<string, string>
  )[state] || state;

/** Keep raw receipt indices stable while presenting one selection per source request. */
export function groupedRequests(rows: NonNullable<RunProcess["requests"]>) {
  const groups: ((typeof rows)[number] & {
    indices: number[];
    number: number;
  })[] = [];
  const owners = new Map<number, (typeof groups)[number]>();
  for (const row of rows) {
    // Clarifications and validation retries are attempts at the same lines.
    const first = row.clarificationOf ?? row.retryOf;
    const parent = first == null ? undefined : owners.get(first);
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
  return (
    attempt?.payload ||
    (attempt ? { ...payload, response: attempt.response } : payload)
  );
}

/** Keep the inspector current without replacing its retained full log. */
export function observedRun(detail: Job | null, observed?: Job) {
  const time = (run: Job) =>
    Math.max(
      Date.parse(run.updated || "") || 0,
      Date.parse(run.process?.monitoring?.checkedAt || "") || 0,
    );
  if (
    !detail ||
    !observed ||
    detail.id !== observed.id ||
    !time(observed) ||
    time(observed) < time(detail)
  )
    return detail;
  return { ...detail, ...observed, log: detail.log };
}

/** Preparation has a later approval exit; only running work needs a footer stop. */
export function translationStopLabel(run?: Job | null) {
  if (
    !run ||
    !activeRun(run) ||
    run.approval ||
    ["estimate", "batch"].includes(run.mode || "")
  )
    return null;
  return "Stop translation";
}

/** A missing request log is not evidence of an empty translation estimate. */
export function estimateRequestCount(job?: Job | null) {
  const count = job?.estimate?.requests ?? job?.estimate?.request_count;
  return typeof count === "number" && Number.isSafeInteger(count) && count >= 0
    ? count
    : undefined;
}
/** Live estimates report no request count; finding no source text also means no work. */
export const estimateEmpty = (job?: Job | null) =>
  estimateRequestCount(job) === 0 || !!job?.nothingToTranslate;

export function estimateFollowup(
  id: string,
  quote: { job?: Job | null; current: boolean } | undefined,
  runs: Job[],
  inputsChanged: boolean,
) {
  const job =
    quote?.job?.id === id ? quote.job : runs.find((run) => run.id === id);
  if (!job || activeRun(job)) return { kind: "waiting" as const, job };
  if (job.status !== "complete") return { kind: "failed" as const, job };
  if (quote?.job?.id !== id || !quote.current || inputsChanged)
    return { kind: "stale" as const, job };
  return {
    kind: estimateEmpty(job) ? ("empty" as const) : ("review" as const),
    job,
  };
}
/** A late observation of the answered name approval cannot reopen it. */
export function preparationFollowup(
  id: string,
  runs: Job[],
  answeredApproval?: string,
) {
  const job = runs.find((run) => run.id === id);
  if (!job || (answeredApproval && job.approval?.token === answeredApproval))
    return { kind: "waiting" as const };
  if (job.approval) return { kind: "review" as const, job };
  if (["failed", "interrupted", "stopped", "canceled"].includes(job.status))
    return { kind: "failed" as const, job };
  return {
    kind: job.status === "complete" ? ("empty" as const) : ("waiting" as const),
    job,
  };
}
export function phaseRun(
  runs: Job[],
  phase: Phase,
  selected?: readonly string[],
) {
  const own = runs
    .filter((run) => run.logicalPhase === phase)
    .sort((a, b) => (b.created || "").localeCompare(a.created || ""));
  const latest =
    own.find((run) => run.mode !== "estimate" && activeWorker(run)) || own[0];
  // Check scope after choosing the latest attempt. Falling back by overlap
  // revives old failures when selection changes or an estimate replaces them.
  return latest &&
    latest.mode !== "estimate" &&
    (!selected ||
      latest.files?.some(
        (name) =>
          selected.includes(name) && !latest.retiredFiles?.includes(name),
      ))
    ? latest
    : undefined;
}
export const needsSubmissionReview = (run: Job) =>
  run.mode !== "estimate" &&
  run.status !== "complete" &&
  !!run.process?.retryBlocked;
/** Paid work the provider never confirmed receiving, after its worker stopped.
 * Confirmed Batches still need review before resending, but are not in doubt;
 * a worker that is still sending has not finished confirming. */
export const unconfirmedSubmission = (run: Job) =>
  needsSubmissionReview(run) && !!run.process?.uncertain && !activeWorker(run);
export const canResumeRun = (run: Job) =>
  !run.temporary &&
  !["estimate", "batch"].includes(run.mode || "") &&
  ["failed", "stopped", "interrupted"].includes(run.status) &&
  !run.process?.retryBlocked;
export function completeForSelection(run: Job, selected: readonly string[]) {
  return (
    !!run.scopeComplete &&
    selected.length > 0 &&
    run.files?.length === selected.length &&
    selected.every(
      (name) =>
        run.files!.includes(name) &&
        !run.partialOutputs?.includes(name) &&
        !run.retiredFiles?.includes(name),
    )
  );
}
export function filePreviewRun(
  name: string,
  run?: Job,
  estimate?: Job | null,
  previous?: Job,
  estimateCurrent = true,
) {
  if (run?.files?.includes(name) && activeWorker(run)) return run;
  if (estimateCurrent && estimate?.files?.includes(name)) return estimate;
  if (run?.files?.includes(name) && run.scopeComplete) return run;
  const saved = previous?.files?.includes(name) ? previous : undefined;
  if (estimate?.files?.includes(name) && (estimateCurrent || !saved))
    return estimate;
  return saved;
}
/** The observer supplies newest-first runs; a resumed worker owns its files. */
export function fileRun(
  runs: Job[],
  phase: Phase,
  name: string,
  retired: readonly string[] = [],
) {
  const matches = runs.filter(
    (run) =>
      run.logicalPhase === phase &&
      run.mode !== "estimate" &&
      !retired.includes(run.id) &&
      !run.retiredFiles?.includes(name) &&
      run.files?.includes(name),
  );
  return matches.find(activeWorker) || matches[0];
}
/** An estimate without requests settles a file until newer work includes it. */
export function settledWithoutRequests(
  state: Pick<GuidedState, "sourceStatus">,
  phase: Phase,
  name: string,
  run?: Job,
) {
  const checked = state.sourceStatus.noRequests?.[phase]?.[name];
  return (
    !!checked && (!run || (!activeWorker(run) && (run.created || "") < checked))
  );
}
/**
 * A file's translated and total lines from the engine's own receipts: the
 * lines its latest run saved, out of the lines that run prepared. A saved
 * "nothing to translate" check closes the file at what is done. Estimates
 * carry no per-file lines, so without a run the amounts stay unknown. A Live
 * run prepares requests as it goes, so while it works only the saved lines
 * are known; `running` marks that partial count. A run that carried a
 * finished file over without sending it, such as a rerun after a stop,
 * keeps the lines of the run that translated it.
 */
export function fileLines(
  state: Pick<GuidedState, "runs" | "sourceStatus">,
  phase: Phase,
  name: string,
): { done: number; total: number | null; running?: boolean } {
  const latest = fileRun(state.runs, phase, name, state.sourceStatus.retired);
  // One row per source request, at its latest attempt; duplicates never count.
  const requests = (run?: Job) =>
    run && !run.temporary
      ? groupedRequests(run.process?.requests || []).filter(
          (row) => row.file === name && row.state !== "unused",
        )
      : [];
  // The run saved this file whole, whether or not the run itself finished.
  const finished = (run: Job) =>
    !!run.availableOutputs?.includes(name) &&
    !run.partialOutputs?.includes(name);
  const translated =
    latest && !requests(latest).length && finished(latest)
      ? fileMetricRun(state.runs, phase, name, state.sourceStatus.retired)
      : undefined;
  const run = translated && requests(translated).length ? translated : latest;
  const rows = requests(run);
  const sum = (items: typeof rows) =>
    items.reduce((total, row) => total + row.sourceItems, 0);
  const done = sum(
    rows.filter((row) => ["validated", "saved"].includes(row.state)),
  );
  if (settledWithoutRequests(state, phase, name, latest))
    return { done, total: done };
  if (run && run.mode !== "batch" && activeWorker(run))
    return { done, total: null, running: true };
  // Live prepares requests as it goes, so a file a run did not finish never
  // saw the rest of its lines and the prepared ones are not its total.
  if (
    run &&
    run.mode !== "batch" &&
    run.status !== "complete" &&
    !finished(run)
  )
    return { done, total: null };
  return { done, total: rows.length ? sum(rows) : null };
}
/**
 * The files an event-code task covers: the selected event files and every
 * file an earlier run of the task included, so clearing the selection keeps
 * finished work while a newly selected file still needs its run.
 */
export function eventTaskFiles(
  state: Pick<GuidedState, "files" | "runs">,
  phase: Phase,
  selected: readonly string[],
) {
  const attempted = new Set(
    state.runs
      .filter(
        (run) =>
          run.logicalPhase === phase &&
          run.mode !== "estimate" &&
          !run.temporary,
      )
      .flatMap((run) => run.files || []),
  );
  return state.files
    .filter(
      (file) =>
        file.group === "dialogue" &&
        (selected.includes(file.name) || attempted.has(file.name)),
    )
    .map((file) => file.name);
}
/**
 * Task progress combines each file's latest run, so re-running some files
 * keeps the rest. Database and map tasks cover their whole file group,
 * independently of the next action's selection; event-code tasks cover
 * eventTaskFiles.
 */
export function translationTaskComplete(
  state: Pick<GuidedState, "files" | "runs" | "sourceStatus">,
  phase: Phase,
  names: readonly string[] = state.files
    .filter((file) => file.group === phase)
    .map((file) => file.name),
) {
  return (
    names.length > 0 &&
    names.every((name) => {
      if (state.sourceStatus.changed.includes(name)) return false;
      const run = fileRun(state.runs, phase, name, state.sourceStatus.retired);
      if (settledWithoutRequests(state, phase, name, run)) return true;
      if (
        !run ||
        run.temporary ||
        activeWorker(run) ||
        run.partialOutputs?.includes(name)
      )
        return false;
      // Completion remains conservative even when a retained file can be shown
      // normally while an interrupted Batch still has unfinished run work.
      if (
        run.mode === "batch" &&
        ["stopped", "interrupted"].includes(run.workerStatus ?? run.status) &&
        (run.phase?.startsWith("poll") || run.process?.resultsCollected)
      )
        return false;
      return (
        ["ready", "applied"].includes(fileStatus(name, run).state) ||
        (run.mode === "batch" &&
          !run.outputs?.[name] &&
          !!run.process?.noRequestFiles?.includes(name))
      );
    })
  );
}
/** Status follows current work; metrics follow the last run that changed this file. */
export function fileMetricRun(
  runs: Job[],
  phase: Phase,
  name: string,
  retired: readonly string[] = [],
) {
  const matches = runs.filter(
    (run) =>
      run.logicalPhase === phase &&
      run.mode !== "estimate" &&
      !run.temporary &&
      !retired.includes(run.id) &&
      !run.retiredFiles?.includes(name) &&
      run.files?.includes(name),
  );
  const changed = (run: Job) =>
    run.changedOutputs !== undefined
      ? run.changedOutputs.includes(name)
      : !run.process?.noRequestFiles?.includes(name) &&
        !!run.process?.fileMetrics?.[name];
  return (
    matches.find((run) => activeWorker(run) && changed(run)) ||
    matches.find(changed)
  );
}
/** Unsettled Batches remain visible independently of Apply and working-file reloads. */
export function unsettledBatches(runs: Job[], selected: readonly string[]) {
  return runs.filter(
    (run) =>
      run.mode === "batch" &&
      !run.temporary &&
      run.files?.some(
        (name) => selected.includes(name) && !run.retiredFiles?.includes(name),
      ) &&
      (activeRun(run) ||
        run.process?.batches?.some((batch) => !terminalBatch(batch.status)) ||
        (needsSubmissionReview(run) && !run.process?.resultsCollected) ||
        ["monitoring", "collecting"].includes(
          run.process?.monitoring?.state || "",
        ) ||
        (["stopped", "interrupted"].includes(run.status) &&
          ((!!run.process?.batches?.length &&
            !!run.phase?.startsWith("poll")) ||
            run.process?.resultsCollected))),
  );
}
/** A file's state in the shared words, with the reason a word leaves out. */
const fileState = (state: DisplayState, detail = "") => ({
  state,
  label: displayLabels[state],
  detail,
  pending: state === "working",
});
/** File receipts and verified output own the row; run diagnostics stay in Inspect. */
export function fileStatus(name: string, run?: Job, settled = false) {
  const idle = fileState("not_started");
  // Saved output that is not in the game yet.
  const complete = fileState("ready");
  const progress = fileState("working");
  if (settled) return complete;
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name))
    return idle;
  const saved =
    run.availableOutputs?.includes(name) ??
    (run.outputsAvailable && !!run.outputs?.[name]);
  const noRequests =
    run.mode === "batch" && run.process?.noRequestFiles?.includes(name);
  if (noRequests && !saved && !run.outputs?.[name]) return complete;
  // A prepared run waiting for cost approval has not started work.
  const awaiting = fileState("needs_review", "Awaiting your cost approval.");
  if (run.temporary) {
    return activeWorker(run) ? (run.approval ? awaiting : progress) : idle;
  }
  const rows = groupedRequests(
    run.process?.requests?.filter((row) => row.file === name) || [],
  );
  const states = rows.map((row) => row.state);
  const working = activeWorker(run);
  // A submission without a provider receipt may still be at the provider, so
  // its reason is checking before sending again, not rejected lines. A Live
  // request still marked sent when its worker stopped is one of them.
  const incomplete = fileState(
    "needs_review",
    states.includes("uncertain") ||
      (!working && run.mode !== "batch" && states.includes("submitted"))
      ? "Its submission could not be confirmed. Check Run history before sending it again."
      : "Some lines were rejected or not saved; Inspect shows which.",
  );
  const invalid = run.process?.validationIssues?.some(
    (issue) => issue.file === name,
  );
  const partial = run.partialOutputs?.includes(name) || invalid;
  const rejected =
    invalid || states.some((state) => ["rejected", "failed"].includes(state));
  if (!noRequests && (run.workerStatus ?? run.status) !== "complete") {
    if (working && run.approval) return awaiting;
    const submitted = rows.filter((row) => row.state === "submitted");
    if (run.mode === "batch" && submitted.length) {
      // A retained submission protects against duplicate charges; it does not
      // establish current provider activity. Match the latest attempt to its
      // Batch receipts, including any clarification under the original index.
      const batches = run.process?.batches || [];
      const belongs = (
        batch: (typeof batches)[number],
        row: (typeof submitted)[number],
      ) => batch.requestIndices?.includes(row.indices.at(-1)!);
      if (
        batches.some(
          (batch) =>
            providerBatchActive(batch.status) &&
            submitted.some((row) => belongs(batch, row)),
        )
      )
        return progress;
      const finished = submitted.every(
        (row) =>
          row.providerFinished &&
          batches.some(
            (batch) =>
              belongs(batch, row) &&
              ["completed", "ended"].includes(batch.status),
          ),
      );
      if (finished) return progress;
    }
    if (working && run.mode !== "batch" && submitted.length) return progress;
    if (
      working &&
      states.some((state) => ["queued", "prepared"].includes(state))
    )
      return progress;
    if (!saved || (partial && working)) {
      if (
        working &&
        states.some((state) => ["received", "validated"].includes(state)) &&
        (run.mode !== "batch" || run.phase === "consume")
      )
        return progress;
      // Item progress identifies the file still being parsed between requests,
      // including after rejection; progress.file is the last finished file.
      if (working && run.mode !== "batch" && run.itemProgress?.file === name)
        return progress;
      // A file stays partial until the worker finishes writing it, so only
      // rejected or failed lines need review before then.
      if (working && run.mode !== "batch" && saved && !rejected)
        return progress;
    }
  }
  if (saved && partial) return incomplete;
  if (saved)
    return run.appliedOutputs?.includes(name) ? fileState("applied") : complete;
  if (run.outputs?.[name])
    return fileState("blocked", "The saved output is missing or changed.");
  // Requests still in the local queue were never sent, and a failed request
  // returned no lines, so either way the run left the file untouched.
  if (partial || states.some((state) => !["queued", "failed"].includes(state)))
    return incomplete;
  if (working && run.mode !== "batch") return progress;
  if (states.includes("failed"))
    return fileState(
      "not_started",
      "Its requests failed without returning any lines; Translate sends them again.",
    );
  return idle;
}

/** Pair only an exact line-key match or the validated Live result of equal length. */
export function translatedLines(
  payload: RunPayload,
): Record<string, string> | null {
  if (["rejected", "unused"].includes(payload.state)) return null;
  const keys = Object.keys(payload.source || {});
  if (!keys.length) return null;
  // New Live receipts retain both raw bodies and independently validated values.
  // A received or rejected raw body must not become a saved-text comparison.
  let value =
    "translations" in payload ? payload.translations : payload.response;
  const response = value;
  if (Array.isArray(response))
    return payload.state === "validated" &&
      response.length === keys.length &&
      response.every((item) => typeof item === "string")
      ? Object.fromEntries(keys.map((key, index) => [key, response[index]]))
      : null;
  // The engine's Batch cache stores the provider's extracted response text.
  if (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "text" in value
  )
    value = value.text;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value.replace(/^\s*```(?:json)?\s*|\s*```\s*$/g, ""));
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === keys.length &&
    keys.every((key) => typeof record[key] === "string")
    ? (record as Record<string, string>)
    : null;
}

/** Read only identifiable per-request blocks; never substitute today's glossary. */
export function requestContext(payload: RunPayload) {
  const text = (value: unknown): string =>
    typeof value === "string"
      ? value
      : Array.isArray(value)
        ? value
            .map((block) => (typeof block?.text === "string" ? block.text : ""))
            .filter(Boolean)
            .join("\n\n")
        : "";
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const dynamic = [
    payload.system,
    ...messages
      .filter((message) => message.role === "system")
      .map((message) => message.content),
  ]
    .map((value) =>
      Array.isArray(value)
        ? text(value.slice(1))
        : text(value).replace(
            /^```[\s\S]*?\n```\s*(?=Here are glossary entries|Japanese SFX reference|$)/,
            "",
          ),
    )
    .filter((value) =>
      /^(Here are glossary entries|Japanese SFX reference)/.test(value.trim()),
    );
  const context = payload.context as {
    source_items?: string[];
    instructions?: string[];
  } | null;
  const section = (prefix: string) =>
    messages
      .filter(
        (message) =>
          message.role === "user" && text(message.content).startsWith(prefix),
      )
      .map((message) => {
        const content = text(message.content);
        return content.match(/```\n([\s\S]*?)\n```/)?.[1] || content;
      });
  return [
    {
      title: "Matched glossary & sound effects",
      text: [...new Set(dynamic)].join("\n\n"),
      notes: false,
    },
    {
      title: "Preceding scene context",
      text: (
        context?.source_items || section("Preceding Japanese Source Context")
      ).join("\n"),
      notes: false,
    },
    {
      title: "Request-specific instructions",
      text: (context?.instructions || section("Request Instructions:")).join(
        "\n",
      ),
      notes: true,
    },
  ].filter((section) => section.text.trim());
}
