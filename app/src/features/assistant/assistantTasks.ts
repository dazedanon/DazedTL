import type {
  AssistantTaskKind,
  AssistantTaskRecord,
  GuidedState,
  GuidedStep,
  ImageManagerState,
  ImageReportState,
  PluginState,
  TranslationMethod,
  WorkspaceSnapshot,
} from "../../api/contracts.ts";
import type { DisplayState } from "../../ui/displayStatus.ts";
import { investigationResults } from "../guided/contextView.ts";
import { qaPhase, qaTaskDone } from "../guided/qaView.ts";
import {
  pluginFilesBlocked,
  pluginFilesLeft,
  pluginTaskState,
} from "../plugins/pluginTask.ts";

/** A copied assistant task that still needs the user or the assistant. */
export interface AssistantTaskView {
  kind: AssistantTaskKind;
  title: string;
  state: Extract<
    DisplayState,
    "waiting" | "needs_review" | "outdated" | "blocked"
  >;
  detail: string;
  /** When it was copied, while nothing it expects has come back. */
  since: string;
  /** The task's own page, where it is copied and reviewed. */
  place: { step: GuidedStep; task: string; label: string };
}

export const assistantTaskTitles: Record<AssistantTaskKind, string> = {
  names: "Names & glossary",
  line_widths: "Line widths",
  event_text: "Event text sources",
  plugins: "Plugin files",
  image_discovery: "Image investigation",
  image_editing: "Image translation",
  qa: "Text QA",
  walkthrough: "Player walkthrough",
};

const places: Record<AssistantTaskKind, AssistantTaskView["place"]> = {
  names: { step: "context", task: "names", label: "Context" },
  line_widths: { step: "context", task: "speakers", label: "Context" },
  event_text: { step: "context", task: "event-sources", label: "Context" },
  plugins: { step: "translate", task: "plugins", label: "Translate" },
  image_discovery: { step: "translate", task: "images", label: "Translate" },
  image_editing: { step: "translate", task: "images", label: "Translate" },
  qa: { step: "check", task: "qa", label: "Check" },
  walkthrough: { step: "release", task: "package", label: "Release" },
};

/** Where a task stands; "finished" and "idle" leave the list. */
interface Standing {
  state: AssistantTaskView["state"] | "finished" | "idle";
  detail?: string;
}

export interface AssistantSources {
  records: AssistantTaskRecord[];
  /** Assistant-led keeps images on its Translation page, not in stages. */
  method?: TranslationMethod | null;
  guided?: GuidedState | null;
  images?: ImageManagerState | null;
  plugins?: PluginState | null;
}

/** The open project's copied tasks and the feature states they read. */
export function assistantSources(
  snapshot: WorkspaceSnapshot,
): AssistantSources | null {
  const project = snapshot.application.project;
  if (!project) return null;
  const own = <T extends { projectId: string }>(value?: T | null) =>
    value && value.projectId === project.id ? value : null;
  return {
    records: snapshot.assistantTasks,
    method: project.method,
    guided: own(snapshot.guided),
    images: own(snapshot.images),
    plugins: own(snapshot.plugins),
  };
}

const waiting = (detail = ""): Standing => ({ state: "waiting", detail });

/** A file the latest copy expects is on disk, saved after that copy. */
const savedSinceCopy = (record?: AssistantTaskRecord) =>
  !!record?.resultAt &&
  Date.parse(record.resultAt) >= Date.parse(record.copiedAt);

/** The task's validation report, when it was saved after its last result. */
const lastValidation = (record: AssistantTaskRecord) =>
  record.validation &&
  record.resultAt &&
  Date.parse(record.validation.savedAt) >= Date.parse(record.resultAt)
    ? record.validation
    : null;

/**
 * A copied task its assistant is still working on: nothing came back since
 * the copy, the result it saves last has not, or, for a task whose assistant
 * validates its results, no passing validation followed the last one. A
 * dismissed task is not.
 */
export function unfinishedCopy(record?: AssistantTaskRecord) {
  if (!record || record.dismissed) return false;
  if (!savedSinceCopy(record)) return true;
  if (record.validation !== undefined && !lastValidation(record)?.passed)
    return true;
  return (
    record.finishedAt !== undefined &&
    !(
      record.finishedAt &&
      Date.parse(record.finishedAt) >= Date.parse(record.copiedAt)
    )
  );
}

/**
 * Each kind from its feature's own saved state. `back` says whether a result
 * the copied task expects was saved since the copy; a task without a record
 * (copied before records existed) counts only when its feature waits.
 */
function standing(
  kind: AssistantTaskKind,
  record: AssistantTaskRecord | undefined,
  { guided, images, plugins }: AssistantSources,
): Standing {
  const back = savedSinceCopy(record);
  const copied = !!record;
  if (kind === "names") {
    if (!guided) return { state: "idle" };
    const speakers = guided.speakerSetup;
    if (speakers.status === "invalid")
      return { state: "blocked", detail: speakers.message };
    if (speakers.status === "stale")
      return { state: "outdated", detail: speakers.message };
    const rows = investigationResults(guided);
    const saved = rows.filter((row) => row.saved).length;
    if (copied && !back) return waiting();
    if (saved < rows.length)
      return copied ||
        speakers.status === "waiting" ||
        guided.contextSetup.status === "waiting"
        ? waiting(saved ? `${saved} of ${rows.length} saved` : "")
        : { state: "idle" };
    // The assistant goes on to the speaker slips, glossary and line widths
    // after its first results; the widths come last.
    return unfinishedCopy(record) ? waiting() : { state: "finished" };
  }
  if (kind === "line_widths") {
    if (!guided) return { state: "idle" };
    const setup = guided.contextSetup;
    // A report the app cannot save or use is blocked whichever task saved
    // it, such as Names & glossary, which ends with the widths; a copy that
    // nothing came back to since waits for its own report.
    if (setup.layoutMessage)
      return { state: "blocked", detail: setup.layoutMessage };
    if (copied && !back) return waiting();
    if (setup.layoutRejected)
      return { state: "blocked", detail: setup.layoutRejected };
    if (!copied) return { state: "idle" };
    // A report that could not measure the windows finishes the task too.
    return setup.layout || setup.layoutUnmeasured
      ? { state: "finished" }
      : waiting();
  }
  if (kind === "event_text") {
    if (!guided) return { state: "idle" };
    const found = guided.eventText;
    if (found.status === "invalid")
      return { state: "blocked", detail: found.message };
    if (found.status === "stale")
      return { state: "outdated", detail: found.message };
    if (found.status === "waiting" || (copied && found.status === "missing"))
      return waiting();
    // Saved findings finish the task; Source choices holds their review.
    return found.status === "ready" ? { state: "finished" } : { state: "idle" };
  }
  if (kind === "plugins") {
    if (!plugins) return { state: "idle" };
    // The copied task waits while a request it handed out has no report;
    // it continues on its own until every plugin file is done.
    if (plugins.awaiting) {
      const left = pluginFilesLeft(plugins);
      return waiting(
        left
          ? `${left.toLocaleString()} ${left === 1 ? "file" : "files"} left`
          : "",
      );
    }
    if (!copied) return { state: "idle" };
    const files = (count: number) =>
      `${count.toLocaleString()} ${count === 1 ? "plugin file" : "plugin files"}`;
    const state = pluginTaskState(plugins, { waiting: false, copied });
    if (state === "outdated")
      return {
        state,
        detail: `${files(pluginFilesLeft(plugins))} changed since your assistant finished`,
      };
    if (state === "blocked")
      return {
        state,
        detail: `${files(pluginFilesBlocked(plugins).length)} could not be read`,
      };
    return { state: "finished" };
  }
  if (kind === "image_discovery" || kind === "image_editing") {
    if (!images) return { state: "idle" };
    const report: ImageReportState =
      kind === "image_discovery" ? images.discovery : images.editing;
    if (report.rejected) return { state: "blocked", detail: report.rejected };
    // A copy can hand out the same request again; it waits for a newer report.
    if (report.status === "awaiting_results" || (copied && !back))
      return waiting();
    if (report.status === "partial") return waiting("Some results saved");
    if (report.status === "complete") {
      const review = kind === "image_editing" ? images.counts.needsReview : 0;
      return review
        ? {
            state: "needs_review",
            detail: `${review.toLocaleString()} ${review === 1 ? "image" : "images"} to review`,
          }
        : { state: "finished" };
    }
    return { state: "idle" };
  }
  if (kind === "qa") {
    if (!guided || !copied) return { state: "idle" };
    const qa = guided.readiness.qa;
    const phase = qaPhase(qa);
    if (phase === "blocked") return { state: "blocked", detail: qa.message };
    if (phase === "not_started") return { state: "idle" };
    // The copy holds the task it handed out and any its assistant prepared
    // since, such as QA's next round after an apply; preparing from the page
    // copies again.
    const own =
      record.requestId === qa.task!.split(/[\\/]/).pop() ||
      Date.parse(qa.prepared_at || "") >= Date.parse(record.copiedAt);
    // Applied corrections change the text the task checked, and later edits
    // are expected. A copy for MV/MZ names the playtest's report, which it
    // saves last: its assistant then plays the game again and fixes what it
    // finds, crashes that stop the game included, until a report of the game
    // as it is settles it.
    if (phase === "applied" || phase === "clean")
      return !own || record.finishedAt === undefined || qaTaskDone(guided)
        ? { state: "finished" }
        : waiting();
    // Changes to the text QA reviewed, other than its own corrections,
    // outdate the findings; the game's plugins, which the assistant's own
    // fixes change, do not.
    if (phase === "outdated") return { state: "outdated", detail: qa.message };
    // Only the user's answers hold QA up; the assistant applies the rest.
    if (phase === "questions") {
      const questions = qa.questions.filter((row) => !row.choice).length;
      return {
        state: "needs_review",
        detail: `${questions.toLocaleString()} ${questions === 1 ? "question" : "questions"} for you`,
      };
    }
    return own ? waiting() : { state: "idle" };
  }
  // The walkthrough is finished once its page is saved. An MV/MZ page is
  // validated only after it is published and republished until its report
  // passes, so it finishes with a passing report after its last save.
  if (!copied) return { state: "idle" };
  if (!back) return waiting();
  if (!unfinishedCopy(record)) return { state: "finished" };
  const report = lastValidation(record);
  return waiting(
    !report
      ? "Saved as WALKTHROUGH.html, waiting for validation"
      : report.errors
        ? `Validation found ${report.errors.toLocaleString()} ${report.errors === 1 ? "error" : "errors"} in WALKTHROUGH.html`
        : "WALKTHROUGH.html did not pass validation",
  );
}

/** When a task was handed out, for a task with no record of its own. */
function legacySince(
  kind: AssistantTaskKind,
  images?: ImageManagerState | null,
) {
  if (kind === "image_discovery") return images?.discovery.copiedAt || "";
  if (kind === "image_editing") return images?.editing.copiedAt || "";
  return "";
}

/**
 * The open assistant tasks for one project, oldest first. A dismissed task
 * stays out until it is copied again; its feature keeps its saved results.
 */
export function assistantTasks(sources: AssistantSources): AssistantTaskView[] {
  const records = new Map(sources.records.map((row) => [row.kind, row]));
  const tasks: (AssistantTaskView & { copiedAt: string })[] = [];
  for (const kind of Object.keys(assistantTaskTitles) as AssistantTaskKind[]) {
    const record = records.get(kind);
    if (record?.dismissed) continue;
    const current = standing(kind, record, sources);
    if (current.state === "finished" || current.state === "idle") continue;
    const copiedAt = record?.copiedAt || legacySince(kind, sources.images);
    tasks.push({
      kind,
      title: assistantTaskTitles[kind],
      state: current.state,
      detail: current.detail || "",
      since: current.state === "waiting" ? copiedAt : "",
      place:
        sources.method === "len"
          ? { ...places[kind], label: "Translation" }
          : places[kind],
      copiedAt,
    });
  }
  return tasks
    .sort((a, b) => a.copiedAt.localeCompare(b.copiedAt))
    .map(({ copiedAt: _copiedAt, ...task }) => task);
}

/** Where each copied task stands, finished and idle ones included. */
export function copiedTaskStandings(sources: AssistantSources) {
  return sources.records
    .filter((record) => !record.dismissed)
    .map((record) => ({
      kind: record.kind,
      copiedAt: record.copiedAt,
      ...standing(record.kind, record, sources),
    }));
}

/**
 * How a feature's own assistant panel should read its waiting state: the
 * shared list's, so a dismissed task reads Not started everywhere and a
 * copied one reads Waiting even where the feature has no waiting state.
 */
export function assistantWaiting(
  kind: AssistantTaskKind,
  sources: AssistantSources,
): Handoff {
  const record = sources.records.find((row) => row.kind === kind);
  const task = assistantTasks(sources).find((row) => row.kind === kind);
  return {
    waiting: task?.state === "waiting",
    dismissed: !!record?.dismissed,
    copied: !!record && !record.dismissed,
    since: task?.since || "",
    detail: task?.detail || "",
    saved: savedSinceCopy(record),
  };
}

/** A copied task's standing for its feature's own panel. */
export interface Handoff {
  waiting: boolean;
  dismissed: boolean;
  /** Copied in this project, and not dismissed since. */
  copied: boolean;
  since: string;
  /** What it waits for, when the shared list says. */
  detail: string;
  saved: boolean;
}

/** Before the snapshot arrives, nothing is copied. */
export const noHandoff: Handoff = {
  waiting: false,
  dismissed: false,
  copied: false,
  since: "",
  detail: "",
  saved: false,
};

/** A feature panel's state with the shared list's waiting applied. */
export function withHandoff<T extends string>(
  state: T | "not_started" | "waiting",
  handoff: { waiting: boolean; dismissed: boolean },
): T | "not_started" | "waiting" {
  if (handoff.dismissed && state === "waiting") return "not_started";
  if (handoff.waiting && state === "not_started") return "waiting";
  return state;
}

/** "since 14:02" beside a waiting task. */
export const sinceLabel = (since: string) =>
  since
    ? `since ${new Date(since).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })}`
    : undefined;
