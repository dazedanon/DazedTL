import type {
  AssistantTaskKind,
  AssistantTaskRecord,
  GuidedState,
  GuidedStep,
  ImageManagerState,
  ImageReportState,
  PluginState,
} from "../../api/contracts.ts";
import type { DisplayState } from "../../ui/displayStatus.ts";
import { investigationResults } from "../guided/contextView.ts";

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
  event_text: "Other event text",
  plugins: "Plugin files",
  image_discovery: "Image discovery",
  image_editing: "Image editing",
  qa: "Text QA",
  walkthrough: "Player walkthrough",
};

const places: Record<AssistantTaskKind, AssistantTaskView["place"]> = {
  names: { step: "context", task: "names", label: "Context" },
  line_widths: { step: "context", task: "speakers", label: "Context" },
  event_text: {
    step: "translate",
    task: "other-event-text",
    label: "Translate",
  },
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
  guided?: GuidedState | null;
  images?: ImageManagerState | null;
  plugins?: PluginState | null;
}

const waiting = (detail = ""): Standing => ({ state: "waiting", detail });

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
  const back =
    !!record?.resultAt &&
    Date.parse(record.resultAt) >= Date.parse(record.copiedAt);
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
    return { state: "finished" };
  }
  if (kind === "line_widths") {
    if (!guided || !copied) return { state: "idle" };
    if (guided.contextSetup.layoutMessage)
      return { state: "blocked", detail: guided.contextSetup.layoutMessage };
    return back && guided.contextSetup.layout
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
    if (found.status === "ready")
      return found.accepted
        ? { state: "finished" }
        : { state: "needs_review", detail: "Findings are ready to review." };
    return { state: "idle" };
  }
  if (kind === "plugins") {
    if (!plugins) return { state: "idle" };
    const awaiting =
      (plugins.activeRequest === plugins.requestPaths.investigation &&
        plugins.findings.status === "awaiting_report") ||
      (plugins.activeRequest === plugins.requestPaths.translation &&
        plugins.editing.status === "awaiting_report");
    if (awaiting) return waiting();
    const problem =
      plugins.findings.errors[0] || plugins.editing.errors[0] || "";
    if (plugins.findings.status === "partial" || problem)
      return {
        state: "needs_review",
        detail: problem || "Some investigation remains unresolved.",
      };
    if (copied && !back) return waiting();
    return copied ? { state: "finished" } : { state: "idle" };
  }
  if (kind === "image_discovery" || kind === "image_editing") {
    if (!images) return { state: "idle" };
    const report: ImageReportState =
      kind === "image_discovery" ? images.discovery : images.editing;
    if (report.rejected) return { state: "blocked", detail: report.rejected };
    if (report.status === "awaiting_results") return waiting();
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
    return copied && !back ? waiting() : { state: "idle" };
  }
  if (kind === "qa") {
    if (!guided || !copied) return { state: "idle" };
    const qa = guided.readiness.qa;
    if (!qa.task) return { state: "idle" };
    if (!qa.current) {
      const latest = guided.readiness.publications[0];
      return latest?.kind === "qa_apply" && latest.state === "complete"
        ? { state: "finished" }
        : { state: "outdated", detail: qa.message };
    }
    if (qa.findings.length)
      return {
        state: "needs_review",
        detail: `${qa.findings.length.toLocaleString()} ${qa.findings.length === 1 ? "finding" : "findings"} to review`,
      };
    if (qa.status.stage === "complete") return { state: "finished" };
    return waiting();
  }
  // The walkthrough is finished once its page is saved.
  return copied && !back ? waiting() : { state: copied ? "finished" : "idle" };
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
      place: places[kind],
      copiedAt,
    });
  }
  return tasks
    .sort((a, b) => a.copiedAt.localeCompare(b.copiedAt))
    .map(({ copiedAt: _copiedAt, ...task }) => task);
}

/**
 * How a feature's own assistant panel should read its waiting state: the
 * shared list's, so a dismissed task reads Not started everywhere and a
 * copied one reads Waiting even where the feature has no waiting state.
 */
export function assistantWaiting(
  kind: AssistantTaskKind,
  sources: AssistantSources,
): { waiting: boolean; dismissed: boolean; since: string } {
  const record = sources.records.find((row) => row.kind === kind);
  const task = assistantTasks(sources).find((row) => row.kind === kind);
  return {
    waiting: task?.state === "waiting",
    dismissed: !!record?.dismissed,
    since: task?.since || "",
  };
}

/** A feature panel's state with the shared list's waiting applied. */
export function withHandoff<T extends string>(
  state: T | "idle" | "waiting",
  handoff: { waiting: boolean; dismissed: boolean },
): T | "idle" | "waiting" {
  if (handoff.dismissed && state === "waiting") return "idle";
  if (handoff.waiting && state === "idle") return "waiting";
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
