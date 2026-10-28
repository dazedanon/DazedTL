import {
  type FileLines,
  type GuidedState,
  type Job,
  type Phase,
  REQUEST_HEADINGS,
  type RunPayload,
} from "../../api/contracts.ts";
import { type DisplayState, displayLabels } from "../../ui/displayStatus.ts";
import { DEFAULT_LANGUAGES } from "../../app/languages.ts";

export const activeRun = (run?: Job | null) =>
  !!run && ["ready", "running", "waiting"].includes(run.status);
/** The run's own worker is still going, whatever the app monitors after it. */
export const activeWorker = (run?: Job | null) =>
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
  quote: { job?: Job | null; current: boolean | null } | undefined,
  runs: Job[],
  inputsChanged: boolean,
) {
  const job =
    quote?.job?.id === id ? quote.job : runs.find((run) => run.id === id);
  if (!job || activeRun(job)) return { kind: "waiting" as const, job };
  if (job.status !== "complete") return { kind: "failed" as const, job };
  // Whether it is current waits for the selected event files to be read.
  if (!inputsChanged && quote?.job?.id === id && quote.current === null)
    return { kind: "waiting" as const, job };
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
  // Saved offline test runs stay in history but no longer run.
  !["estimate", "batch", "offline"].includes(run.mode || "") &&
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
/** The newest current run that includes a file, which Inspect opens; a
 * resumed worker owns its files (fileWork). */
export const fileRun = (
  runs: Job[],
  phase: Phase,
  name: string,
  retired: readonly string[] = [],
) => fileWork(runs, phase, name, retired).owner;
/** Whether a current run of a task, not an estimate, includes a file. */
const includesFile = (
  run: Job,
  phase: Phase,
  name: string,
  retired: readonly string[],
) =>
  run.logicalPhase === phase &&
  run.mode !== "estimate" &&
  !retired.includes(run.id) &&
  !run.retiredFiles?.includes(name) &&
  !!run.files?.includes(name);
const translatedCache = new WeakMap<
  Job[],
  Map<string, { retired: readonly string[]; names: Set<string> }>
>();
const noneRetired: readonly string[] = [];
/**
 * Files a current run changed or sent requests for, in any phase or, with
 * `phase`, in that task's runs only. A rerun reads the earlier run's output
 * and reuses the results of earlier requests, so only a file outside this set
 * still holds the game's own text, and a run that sent nothing for it found
 * nothing to translate. An event-code task asks for its own runs: text
 * another task translated in the file is not this task's to apply.
 */
export function translatedFiles(
  runs: Job[],
  retired: readonly string[] = noneRetired,
  phase?: Phase,
) {
  let phases = translatedCache.get(runs);
  if (!phases) translatedCache.set(runs, (phases = new Map()));
  const cached = phases.get(phase ?? "");
  if (cached?.retired === retired) return cached.names;
  const names = new Set<string>();
  for (const run of runs) {
    if (
      run.mode === "estimate" ||
      run.temporary ||
      retired.includes(run.id) ||
      (phase && run.logicalPhase !== phase)
    )
      continue;
    const add = (name: string) => {
      if (!run.retiredFiles?.includes(name)) names.add(name);
    };
    // Without request receipts any of its files may hold its results.
    if (!run.process?.files) (run.files || []).forEach(add);
    for (const [name, lines] of Object.entries(run.process?.files || {}))
      if (lines.requests) add(name);
    for (const name of Object.keys(run.outputs || {}))
      if (!run.changedOutputs || run.changedOutputs.includes(name)) add(name);
  }
  phases.set(phase ?? "", { retired, names });
  return names;
}
/**
 * Saved working outputs holding translation, and those in the game: a file
 * whose own lines are translated, or one a run changed, such as with Other
 * event text. With an event-code `phase`, only the files that task's own runs
 * translated, so its Apply counts its own work, not another task's.
 * `counting` holds the other outputs whose lines the backend is still
 * counting, which may yet hold translation.
 */
export function savedTranslations(
  state: Pick<GuidedState, "runs" | "sourceStatus" | "readiness">,
  phase?: Phase,
) {
  const own = phase && !countedPhase(phase) ? phase : undefined;
  const changed = translatedFiles(state.runs, state.sourceStatus.retired, own);
  const counts = (name: string) =>
    own || changed.has(name) ? undefined : fileCounts(state, name);
  const translated = (name: string) => {
    const counted = counts(name);
    return (
      changed.has(name) || (counted !== "counting" && !!counted?.translated)
    );
  };
  return {
    outputs: state.readiness.outputs.filter(translated),
    applied: state.readiness.applied.filter(translated),
    counting: state.readiness.outputs.filter(
      (name) => counts(name) === "counting",
    ),
  };
}
/**
 * A run found nothing to translate in a file no run translated when its
 * Batch prepared no request for it, or when it saved the file whole as it
 * was. A recorded output that is missing stays the run's problem.
 */
function nothingFound(name: string, run: Job, untranslated: boolean) {
  if (!untranslated) return false;
  const saved =
    run.availableOutputs?.includes(name) ??
    (run.outputsAvailable && !!run.outputs?.[name]);
  if (run.outputs?.[name] && !saved) return false;
  return (
    madeNoRequest(run, name) ||
    (!!saved &&
      !run.partialOutputs?.includes(name) &&
      !run.process?.validationIssues?.some((issue) => issue.file === name))
  );
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
 * Why Apply is unavailable for `files`: the game changed one since its
 * working copy, as a game update does, so its translated copy still holds the
 * old text and the backend refuses it until Reload from game.
 */
export const reloadFirst = "Reload changed files from the game first.";
export const reloadBeforeApply = (
  files: readonly string[],
  changed: readonly string[],
) => files.some((name) => changed.includes(name)) && reloadFirst;
/** Why applying a run's own saved output is unavailable: the files it
 * reapplies, its outputs among its files, include one the game changed. */
export const reloadBeforeRunApply = (job: Job, changed: readonly string[]) =>
  reloadBeforeApply(
    Object.keys(job.outputs || {}).filter((name) => job.files?.includes(name)),
    changed,
  );
/** Database files and Maps & events read each file's lines from the file. */
export const countedPhase = (phase: Phase) =>
  phase === "database" || phase === "dialogue";
/**
 * A file's translated and total lines. Database files and Maps & events read
 * them from the file's newest copy (sourceStatus.lines), except that a Live
 * run still working on the file knows only the lines it saved so far
 * (`running`); the count takes over once it is done with the file. A file the
 * backend could not read has no total, nor one it is still counting
 * (`counting`). Other event text reads its runs' receipts.
 */
export function fileLines(
  state: Pick<GuidedState, "runs" | "sourceStatus">,
  phase: Phase,
  name: string,
  work = fileWork(state.runs, phase, name, state.sourceStatus.retired),
): {
  done: number;
  total: number | null;
  running?: boolean;
  counting?: boolean;
} {
  if (!countedPhase(phase)) {
    const amounts = runLines(state, phase, name, work);
    // Refusal notes the file may hold leave a closed amount unknown until it
    // is counted, as its row reads (fileStatus).
    return amounts.total !== null && fileCounts(state, name) === "counting"
      ? { done: 0, total: null, counting: true }
      : amounts;
  }
  const { run } = work;
  if (
    run &&
    !run.temporary &&
    run.mode !== "batch" &&
    runActivity(name, run)?.state === "working"
  )
    return {
      done: run.process?.files?.[name]?.done ?? 0,
      total: null,
      running: true,
    };
  const counted = fileCounts(state, name);
  if (counted === "counting") return { done: 0, total: null, counting: true };
  if (counted) return { done: counted.translated, total: counted.lines };
  return { done: 0, total: null };
}
/**
 * A file's line counts from its newest copy (sourceStatus.lines), or
 * "counting" while the backend still counts them, when everything they say,
 * such as its lines translated or its refusal notes (otherNotes), is
 * unknown; undefined when the backend could not read the file. Every reader
 * of a file's counts asks this.
 */
export function fileCounts(
  state: Pick<GuidedState, "sourceStatus">,
  name: string,
): FileLines | "counting" | undefined {
  const counted = state.sourceStatus.lines?.[name];
  if (counted) return counted;
  const list = state.sourceStatus.counting;
  if (!list?.length) return undefined;
  let names = countingNames.get(list);
  if (!names) countingNames.set(list, (names = new Set(list)));
  return names.has(name) ? "counting" : undefined;
}
/** Each snapshot's counting list as a set, since every file asks it. */
const countingNames = new WeakMap<readonly string[], Set<string>>();
/** A file whose lines are still counted reads Working although no run works
 * on it, so a change in the game still reads Outdated. */
const countingState = () => ({
  ...fileState("working", "Counting this file's lines."),
  pending: false,
});
/**
 * Other event text's translated and total lines from the engine's own
 * receipts: the lines its latest run saved, out of the lines that run
 * prepared. A saved "nothing to translate" check closes the file at what is
 * done, and a run that found nothing to translate gives it a total of none.
 * Estimates carry no per-file lines, so without a run the amounts stay
 * unknown. A Live run prepares requests as it goes, so while it works only
 * the saved lines are known; `running` marks that partial count. A Batch
 * writes a file only while it saves its results, so until then, or when
 * saving it failed, the received lines are not saved. A run that carried a
 * finished file over without sending it, such as a rerun after a stop, found
 * every line of the run that translated it translated, since it sends any
 * line still in the game's own words. Refusal notes an earlier run kept
 * (otherNotes) stay untranslated until a run sends them again, even when a
 * check found nothing to send.
 */
function runLines(
  state: Pick<GuidedState, "runs" | "sourceStatus">,
  phase: Phase,
  name: string,
  work: ReturnType<typeof fileWork>,
): { done: number; total: number | null; running?: boolean } {
  const latest = work.run;
  const counted = fileCounts(state, name);
  // One count per source request, at its latest attempt; duplicates never count.
  const requests = (run?: Job) =>
    run && !run.temporary ? run.process?.files?.[name] : undefined;
  // The run saved this file whole, whether or not the run itself finished.
  const finished = (run: Job) =>
    !!run.availableOutputs?.includes(name) &&
    !run.partialOutputs?.includes(name);
  const translated =
    latest && !requests(latest)?.requests && finished(latest)
      ? work.changed
      : undefined;
  const run =
    translated && requests(translated)?.requests ? translated : latest;
  const lines = requests(run);
  const notes = (counted !== "counting" && counted?.otherNotes) || 0;
  const done =
    run !== latest && lines
      ? Math.max(0, lines.lines - notes)
      : run?.mode === "batch" && !run.outputs?.[name]
        ? 0
        : (lines?.done ?? 0);
  // A check that found nothing to send read refusal notes as translations.
  if (!notes && settledWithoutRequests(state, phase, name, latest))
    return { done, total: done };
  if (
    latest &&
    nothingFound(
      name,
      latest,
      !translatedFiles(state.runs, state.sourceStatus.retired, phase).has(name),
    )
  )
    return { done: 0, total: 0 };
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
  return { done, total: lines?.requests ? lines.lines : null };
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
 * A translation task is done when every file it covers is in the game or has
 * nothing to translate (its row reads Applied or Done) and no run still works
 * on one; saved work waiting for Apply keeps it open. Database and map tasks
 * cover their group's files, independently of the next action's selection.
 * Event-code tasks cover eventTaskFiles and combine each file's latest run,
 * so re-running some files keeps the rest. Every place that shows a task's
 * done state asks this.
 */
export function translationTaskComplete(
  state: Pick<GuidedState, "files" | "runs" | "sourceStatus" | "readiness">,
  phase: Phase,
  names: readonly string[] = state.files
    .filter((file) => file.group === phase)
    .map((file) => file.name),
) {
  if (!names.length) return false;
  const finished = (status: { state: DisplayState }) =>
    status.state === "applied" || status.state === "done";
  const work = (name: string) =>
    fileWork(state.runs, phase, name, state.sourceStatus.retired).run;
  if (countedPhase(phase))
    return names.every((name) => {
      const run = work(name);
      // A worker may still write a file it already saved.
      return (
        !state.sourceStatus.changed.includes(name) &&
        !(run && activeWorker(run)) &&
        finished(countedFileStatus(state, phase, name, run))
      );
    });
  return names.every((name) => {
    // A file still counted reads Counting by its row's rule below.
    const notes = notesOf(fileCounts(state, name));
    if (
      state.sourceStatus.changed.includes(name) ||
      (notes !== "counting" && !!notes)
    )
      return false;
    const run = work(name);
    if (settledWithoutRequests(state, phase, name, run))
      return finished(translationFileStatus(state, phase, name, run));
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
    return finished(translationFileStatus(state, phase, name, run));
  });
}
/**
 * Whether a run made no request for a file: a Batch whose finished
 * collection prepared none for it (every request reused, or nothing to send
 * at all). The backend records it for Batches only (noRequestFiles).
 */
export const madeNoRequest = (run: Job, name: string) =>
  run.mode === "batch" && !!run.process?.noRequestFiles?.includes(name);
/** A run that made no request for a file and saved no output of its own
 * changed nothing in it. */
const leftAlone = (run: Job, name: string) =>
  madeNoRequest(run, name) && !run.outputs?.[name];
/** Whether a run's saved output of a file differs from the file it read; a
 * run from before that record changed it when it made a request for it and
 * recorded its metrics. */
const changedFile = (run: Job, name: string) =>
  run.changedOutputs !== undefined
    ? run.changedOutputs.includes(name)
    : !madeNoRequest(run, name) && !!run.process?.fileMetrics?.[name];
/** The files whose translation from this run is in the game. An output the
 * same as the file it read, such as one with nothing to translate, is in the
 * game without an Apply, so it counts as no applied translation. */
export const appliedFiles = (run: Job) =>
  (run.appliedOutputs || []).filter((name) => changedFile(run, name));
/**
 * The runs a file in a translation task reads, from the observer's
 * newest-first runs: `owner`, the newest current run that includes the file,
 * a resumed worker first, which Inspect opens; `run`, whose work the row's
 * status, Lines, activity and the task's done mark show; and `changed`, the
 * last run that changed the file, whose cost and time the row shows. `run` is
 * the owner, except that a run that left the file alone leaves it as the run
 * before it did, applied or not; with no earlier run the file has nothing to
 * translate. A Batch never leaves alone a file it still has requests for, so
 * its other files keep the task open while it works. This is the one rule
 * for which run a file shows.
 */
export function fileWork(
  runs: Job[],
  phase: Phase,
  name: string,
  retired: readonly string[] = [],
): { owner?: Job; run?: Job; changed?: Job } {
  let newest: Job | undefined, active: Job | undefined;
  let own: Job | undefined, ownActive: Job | undefined;
  let changed: Job | undefined, changedActive: Job | undefined;
  for (const run of runs) {
    if (!includesFile(run, phase, name, retired)) continue;
    const working = activeWorker(run);
    newest ??= run;
    if (working) active ??= run;
    if (!leftAlone(run, name)) {
      own ??= run;
      if (working) ownActive ??= run;
    }
    if (!run.temporary && changedFile(run, name)) {
      changed ??= run;
      if (working) changedActive ??= run;
    }
  }
  const owner = active || newest;
  return {
    owner,
    run: owner && leftAlone(owner, name) ? ownActive || own || owner : owner,
    changed: changedActive || changed,
  };
}
/**
 * A file's state in a translation task's file list, from the run whose work
 * it shows (fileWork). This is the one rule for the row and for
 * translationTaskComplete.
 */
export function translationFileStatus(
  state: Pick<GuidedState, "runs" | "sourceStatus" | "readiness">,
  phase: Phase,
  name: string,
  run = fileWork(state.runs, phase, name, state.sourceStatus.retired).run,
  source = DEFAULT_LANGUAGES.source,
) {
  if (countedPhase(phase))
    return countedFileStatus(state, phase, name, run, source);
  return fileStatus(
    name,
    run,
    settledWithoutRequests(state, phase, name, run),
    !translatedFiles(state.runs, state.sourceStatus.retired, phase).has(name),
    notesOf(fileCounts(state, name)),
  );
}
/** A file's refusal notes outside its counted lines, as fileStatus reads them. */
const notesOf = (counted: ReturnType<typeof fileCounts>) =>
  counted === "counting" ? counted : counted?.otherNotes;
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
const count = (amount: number, one: string, many = one + "s") =>
  `${amount.toLocaleString()} ${amount === 1 ? one : many}`;
/** Why a file's lines are left, for its status tooltip, in the game's
 * *source* language. */
export function linesLeft(counted: FileLines, source: string) {
  const notes = counted.notes ?? 0,
    help = counted.help ?? 0,
    // Sent or not: a line the model gave back unchanged reads the same.
    left = counted.lines - counted.translated - notes - help;
  return [
    left > 0 && `${count(left, "line")} still in ${source}.`,
    help > 0 &&
      `${count(help, "line")} of choice help ${help === 1 ? "is" : "are"} still in ${source}; Comment text now translates ${help === 1 ? "it" : "them"}.`,
    notes > 0 &&
      `${count(notes, "line holds", "lines hold")} a refusal note an earlier run saved instead of a translation.`,
    counted.lines - counted.translated === 1
      ? "Translate sends it; Inspect lists it."
      : "Translate sends them; Inspect lists them.",
  ]
    .filter(Boolean)
    .join(" ");
}
/**
 * A Database files or Maps & events file's state: a run's work while it is
 * still in progress for the file, else what the file's newest copy holds.
 * Lines left read Not started until any is translated or holds a refusal
 * note; a file with none left is in the game when its translated copy is,
 * or when it has no translated copy of its own; one the backend is still
 * counting is Working. Its detail names the game's *source* language.
 */
export function countedFileStatus(
  state: Pick<GuidedState, "runs" | "sourceStatus" | "readiness">,
  phase: Phase,
  name: string,
  run = fileWork(state.runs, phase, name, state.sourceStatus.retired).run,
  source = DEFAULT_LANGUAGES.source,
) {
  const active = runActivity(name, run);
  if (active) return active;
  const counted = fileCounts(state, name);
  if (counted === "counting") return countingState();
  if (!counted)
    return fileState("blocked", "This file could not be read as game data.");
  if (!counted.lines)
    return fileState("done", "Nothing to translate in this file.");
  if (counted.translated < counted.lines) {
    if (counted.translated || counted.notes)
      return fileState(
        "needs_review",
        run && uncertainSubmission(name, run)
          ? unconfirmed
          : linesLeft(counted, source),
      );
    // Untouched, the file reads Not started, with why when the run did send
    // its requests or its help lines are left.
    return fileState(
      "not_started",
      run && uncertainSubmission(name, run)
        ? unconfirmed
        : run && requestsFailed(name, run)
          ? failedRequests
          : counted.help
            ? linesLeft(counted, source)
            : "",
    );
  }
  return !state.readiness.outputs.includes(name) ||
    state.readiness.applied.includes(name)
    ? fileState("applied")
    : fileState("ready");
}
/**
 * Other event text's file state from its run's receipts and verified output;
 * run diagnostics stay in Inspect. `untranslated` says no run translated the
 * file (translatedFiles), so a run that sent nothing for it leaves nothing to
 * apply. `notes` counts the file's refusal notes outside its Database files
 * or Maps & events lines (otherNotes), which leave a finished file needing
 * review until a run sends them; "counting" while they are unknown.
 */
export function fileStatus(
  name: string,
  run?: Job,
  settled = false,
  untranslated = false,
  notes: number | "counting" = 0,
) {
  const status = runFileStatus(name, run, settled, untranslated);
  if (!notes || !["ready", "applied", "done"].includes(status.state))
    return status;
  if (notes === "counting") return countingState();
  return fileState(
    "needs_review",
    `${count(notes, "line holds", "lines hold")} a refusal note an earlier run saved instead of a translation. Translate sends ${notes === 1 ? "it" : "them"} again.`,
  );
}
/** Why a file reads as it does when a run's request for it may still be at
 * the provider (uncertainSubmission). */
const unconfirmed =
  "Its submission could not be confirmed. Check Run history before sending it again.";
/** Why an untouched file reads Not started when its requests failed
 * (requestsFailed). */
const failedRequests =
  "Its requests failed without returning any lines; Translate sends them again.";
/** Whether a run's requests for a file that left its queue all failed,
 * returning no lines, so the run left the file as it was. */
function requestsFailed(name: string, run: Job) {
  const states = run.process?.files?.[name]?.states || [];
  return (
    states.includes("failed") &&
    states.every((state) => ["queued", "failed"].includes(state))
  );
}
/** A Live request still marked sent when its worker stopped, or any without
 * a provider receipt, may still be at the provider. */
function uncertainSubmission(name: string, run: Job) {
  const states = run.process?.files?.[name]?.states || [];
  return (
    states.includes("uncertain") ||
    (!activeWorker(run) && run.mode !== "batch" && states.includes("submitted"))
  );
}
/**
 * A run's work on a file while it is still in progress: Working, or awaiting
 * cost approval; undefined once the run no longer works on the file.
 */
function runActivity(name: string, run?: Job) {
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name))
    return undefined;
  const progress = fileState("working");
  // A prepared run waiting for cost approval has not started work.
  const awaiting = fileState("needs_review", "Awaiting your cost approval.");
  if (run.temporary)
    return activeWorker(run) ? (run.approval ? awaiting : progress) : undefined;
  if (
    madeNoRequest(run, name) ||
    (run.workerStatus ?? run.status) === "complete"
  )
    return undefined;
  const requests = run.process?.files?.[name];
  const states = requests?.states || [];
  const working = activeWorker(run);
  const saved =
    run.availableOutputs?.includes(name) ??
    (run.outputsAvailable && !!run.outputs?.[name]);
  // After a restart the app's monitor finishes a stopped worker's Batch and
  // then saves its results.
  const monitored = ["monitoring", "collecting"].includes(
    run.process?.monitoring?.state || "",
  );
  const invalid = run.process?.validationIssues?.some(
    (issue) => issue.file === name,
  );
  const partial = run.partialOutputs?.includes(name) || invalid;
  const rejected =
    invalid || states.some((state) => ["rejected", "failed"].includes(state));
  if (working && run.approval) return awaiting;
  // Submitted requests, grouped by the Batch receipts holding their latest
  // attempt (a clarification sits under the original request).
  const submitted = requests?.submitted || [];
  if (run.mode === "batch" && submitted.length) {
    // A retained submission protects against duplicate charges; it does not
    // establish current provider activity.
    const batches = run.process?.batches || [];
    if (
      batches.some(
        (batch) =>
          providerBatchActive(batch.status) &&
          submitted.some((group) => group.batches.includes(batch.id)),
      )
    )
      return progress;
    // An ended Batch, canceled or expired ones included, finished every
    // request it held; collection downloads what it returned.
    const finished = submitted.every(
      (group) =>
        group.finished &&
        batches.some(
          (batch) =>
            group.batches.includes(batch.id) && terminalBatch(batch.status),
        ),
    );
    if (finished) return progress;
  }
  if (working && run.mode !== "batch" && submitted.length) return progress;
  if (working && states.some((state) => ["queued", "prepared"].includes(state)))
    return progress;
  if (!saved || (partial && (working || monitored))) {
    // Received results are written by this run, including while a Batch
    // waits at the provider for a clarification of refused requests.
    if (
      (working || monitored) &&
      states.some((state) => ["received", "validated"].includes(state))
    )
      return progress;
    // Item progress identifies the file still being parsed between requests,
    // including after rejection; progress.file is the last finished file.
    if (working && run.mode !== "batch" && run.itemProgress?.file === name)
      return progress;
    // A file stays partial until the worker finishes writing it, so only
    // rejected or failed lines need review before then.
    if (working && run.mode !== "batch" && saved && !rejected) return progress;
  }
  // A Live run reaches the file's queued or failed requests in turn.
  if (
    working &&
    run.mode !== "batch" &&
    !saved &&
    !run.outputs?.[name] &&
    !partial &&
    states.every((state) => ["queued", "failed"].includes(state))
  )
    return progress;
  return undefined;
}
function runFileStatus(
  name: string,
  run: Job | undefined,
  settled: boolean,
  untranslated: boolean,
) {
  const idle = fileState("not_started");
  // Saved output that is not in the game yet.
  const complete = fileState("ready");
  const nothing = fileState("done", "Nothing to translate in this file.");
  // A check that needs no requests keeps the output the file already has,
  // in the game or not.
  if (settled)
    return untranslated
      ? nothing
      : run?.appliedOutputs?.includes(name)
        ? fileState("applied")
        : complete;
  if (!run || !run.files?.includes(name) || run.retiredFiles?.includes(name))
    return idle;
  if (nothingFound(name, run, untranslated)) return nothing;
  const saved =
    run.availableOutputs?.includes(name) ??
    (run.outputsAvailable && !!run.outputs?.[name]);
  const activity = runActivity(name, run);
  if (activity || run.temporary) return activity || idle;
  const states = run.process?.files?.[name]?.states || [];
  // A submission without a provider receipt may still be at the provider, so
  // its reason is checking before sending again, not rejected lines.
  const incomplete = fileState(
    "needs_review",
    uncertainSubmission(name, run)
      ? unconfirmed
      : "Some lines were rejected or not saved; Inspect shows which.",
  );
  const partial =
    run.partialOutputs?.includes(name) ||
    run.process?.validationIssues?.some((issue) => issue.file === name);
  if (saved && partial) return incomplete;
  if (saved)
    return run.appliedOutputs?.includes(name) ? fileState("applied") : complete;
  if (run.outputs?.[name])
    return fileState("blocked", "The saved output is missing or changed.");
  // Requests still in the local queue were never sent, and a failed request
  // returned no lines, so either way the run left the file untouched.
  if (partial || states.some((state) => !["queued", "failed"].includes(state)))
    return incomplete;
  if (requestsFailed(name, run))
    return fileState("not_started", failedRequests);
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
  const lines = (response: unknown) =>
    payload.state === "validated" &&
    Array.isArray(response) &&
    response.length === keys.length &&
    response.every((item) => typeof item === "string")
      ? Object.fromEntries(keys.map((key, index) => [key, response[index]]))
      : null;
  if (Array.isArray(value)) return lines(value);
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
  // A Batch reply wraps its lines in the same list a Live receipt keeps.
  if (value && typeof value === "object" && "translations" in value)
    return lines(value.translations);
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === keys.length &&
    keys.every((key) => typeof record[key] === "string")
    ? (record as Record<string, string>)
    : null;
}

const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// The matched glossary and SFX reference that follow a request's static prompt.
const MATCHED = `(?:${escaped(REQUEST_HEADINGS.glossary)}|${escaped(REQUEST_HEADINGS.sfx)})`;
const AFTER_PROMPT = new RegExp(
  `^\`\`\`[\\s\\S]*?\\n\`\`\`\\s*(?=${MATCHED}|$)`,
);
const MATCHED_START = new RegExp(`^${MATCHED}`);

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
        : text(value).replace(AFTER_PROMPT, ""),
    )
    .filter((value) => MATCHED_START.test(value.trim()));
  const context = payload.context as {
    source_items?: string[];
    instructions?: string[];
  } | null;
  const section = (prefixes: readonly string[]) =>
    messages
      .filter(
        (message) =>
          message.role === "user" &&
          prefixes.some((prefix) => text(message.content).startsWith(prefix)),
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
        context?.source_items || section(REQUEST_HEADINGS.sourceContext)
      ).join("\n"),
      notes: false,
    },
    {
      title: "Request-specific instructions",
      text: (
        context?.instructions || section([REQUEST_HEADINGS.instructions])
      ).join("\n"),
      notes: true,
    },
  ].filter((section) => section.text.trim());
}
