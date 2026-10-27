/** Text QA as the page shows it, from the observed QA state. */

import type {
  GuidedState,
  QaFinding,
  QaState,
  QaUntranslatedSource,
} from "../../api/contracts";
import type { StepState } from "../../ui/StepProgress";
import { plural, sentence } from "../../ui/displayText.ts";

/** Where text QA stands on the page. */
export type QaPhase =
  | "not_started"
  | "running"
  | "questions"
  | "ready"
  | "applied"
  | "clean"
  | "outdated"
  | "blocked";

export function qaPhase(qa: QaState): QaPhase {
  // A prepared task the app can't read still holds QA's place.
  if (qa.unreadable) return "blocked";
  if (!qa.task) return "not_started";
  // Applying changes the text QA checked; later edits are expected.
  if (qa.applied) return "applied";
  if (!qa.current) return "outdated";
  if (qa.status.stage !== "complete") return "running";
  if (qa.questions.some((row) => !row.choice)) return "questions";
  return qa.findings.length || qa.questions.some((row) => row.choice === "use")
    ? "ready"
    : "clean";
}

/**
 * For MV/MZ, whose QA task is also the final check, the assistant's
 * playtest has yet to settle after QA, whichever method runs it.
 */
export const finalCheckOpen = (state: GuidedState) =>
  state.engine === "MVMZ" && !state.readiness.playtest.settled;

/**
 * Guided's Text QA task is done: QA's corrections are in the game or it
 * found none, and the final check settled after them.
 */
export function qaTaskDone(state: GuidedState) {
  return (
    ["applied", "clean"].includes(qaPhase(state.readiness.qa)) &&
    !finalCheckOpen(state)
  );
}

const stageNames = {
  lint: "Lint review",
  screen: "Screening",
  deep: "Deep review",
  sweep: "Consistency sweep",
  editorial: "Editorial review",
} as const;

/** Minutes and hours a reader can act on, from the engine's estimate. */
export function timeLeft(seconds: number) {
  if (seconds < 60) return "under a minute left";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `about ${minutes} min left`;
  return `about ${Math.round(minutes / 60)} h left`;
}

/**
 * The one activity line, such as "Deep review 412 of 621 · about 25 min
 * left", which says when reviewers take one bundle at a time while others wait.
 */
export function qaActivity(qa: QaState) {
  const activity = qa.activity;
  if (!activity) return "";
  return [
    `${stageNames[activity.stage]} ${activity.done.toLocaleString()} of ${activity.total.toLocaleString()}`,
    activity.eta_seconds !== undefined && timeLeft(activity.eta_seconds),
    activity.one_at_a_time && "one reviewer at a time",
  ]
    .filter(Boolean)
    .join(" · ");
}

type Counts = { accepted?: number; total?: number };

/**
 * The stage strip: Preflight, Lint, Screen, Deep, Consistency, Editorial
 * and Apply, with the one current stage. Deep review that started while
 * screening continues reads as started.
 */
export function qaStages(qa: QaState): {
  id: string;
  label: string;
  state: StepState;
}[] {
  const status = qa.status;
  const stage = typeof status.stage === "string" ? status.stage : "";
  const screen = (status.screen || {}) as Counts & {
    lint?: Counts & { declined?: number };
  };
  const deep = (status.deep || {}) as Counts;
  const lint = screen.lint || {};
  const order = ["screen", "deep", "sweep", "editorial", "complete"];
  const reached = (name: string) =>
    !!qa.task &&
    (order.indexOf(stage) > order.indexOf(name) ||
      (stage === "ready-finalize" && order.indexOf(name) < 2));
  // Declined proposals wait for another helper, not for lint review.
  const lintDone =
    (lint.accepted || 0) + (lint.declined || 0) >= (lint.total || 0);
  const states: [string, string, StepState][] = [
    ["preflight", "Preflight", qa.task ? "done" : "current"],
    [
      "lint",
      "Lint",
      !qa.task ? "next" : lintDone || reached("screen") ? "done" : "current",
    ],
    [
      "screen",
      "Screen",
      reached("screen")
        ? "done"
        : stage === "screen" && lintDone
          ? "current"
          : "next",
    ],
    [
      "deep",
      "Deep",
      reached("deep")
        ? "done"
        : stage === "deep"
          ? "current"
          : stage === "screen" && (deep.accepted || 0) > 0
            ? "started"
            : "next",
    ],
    [
      "consistency",
      "Consistency",
      reached("sweep") ? "done" : stage === "sweep" ? "current" : "next",
    ],
    [
      "editorial",
      "Editorial",
      reached("editorial")
        ? "done"
        : stage === "editorial"
          ? "current"
          : "next",
    ],
    [
      "apply",
      "Apply",
      qa.applied ? "done" : stage === "complete" ? "current" : "next",
    ],
  ];
  return states.map(([id, label, state]) => ({ id, label, state }));
}

/**
 * The corrections QA proposes, and how many are in the game or were undone
 * since. A proposal the user chose counts as a correction.
 */
export function qaCorrections(qa: QaState) {
  const rows = [
    ...qa.findings,
    ...qa.questions.filter((row) => row.choice === "use"),
  ];
  const count = (state: string) =>
    rows.filter((row) => row.state === state).length;
  return {
    total: rows.length,
    applied: count("applied"),
    undone: count("undone"),
  };
}

/**
 * Lines an earlier QA reviewed, or the user said were checked before,
 * unchanged since: this task reads them only as context.
 */
export function qaReviewedBefore(qa: QaState) {
  const earlier = qa.status.reviewed_before as { lines?: number } | undefined;
  return earlier?.lines || 0;
}

/** The summary line once QA is done: corrections and what it covered. */
export function qaSummary(qa: QaState) {
  const { total, applied, undone } = qaCorrections(qa);
  const lines = qa.coverage?.lines || 0;
  const missing = qa.coverage?.not_reviewed || 0;
  const earlier = qaReviewedBefore(qa);
  const corrections = (count: number) => plural(count, "correction");
  const checked = lines - missing - earlier;
  return [
    qa.applied
      ? applied
        ? `${corrections(applied)} applied`
        : undone
          ? `${corrections(undone)} undone`
          : "No corrections applied"
      : total
        ? `${corrections(total)} to apply`
        : "No corrections needed",
    qa.applied && applied && undone && `${undone.toLocaleString()} undone`,
    lines && `${plural(checked, "line")} checked`,
    earlier && `${earlier.toLocaleString()} unchanged since earlier QA`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Whether players may see a source's text: no evidence rules it out. The
 * evidence is about a whole plugin or file, so of several texts players may
 * see only some.
 */
export function qaReach(source: QaUntranslatedSource) {
  if (source.reach === "uncalled" || source.reach === "unread")
    return "Players don't see this now.";
  return source.count > 1
    ? "Players may see some of this."
    : "Players may see this.";
}

/** A source's name and what kind of text it holds. */
export function qaSource(source: QaUntranslatedSource) {
  return source.kind === "plugin"
    ? { title: source.plugin || source.file, kind: "Plugin settings" }
    : {
        title: source.file,
        kind:
          source.kind === "custom"
            ? "Custom data file"
            : "Game data without a saved original",
      };
}

const categoryOrder = [
  "meaning",
  "speaker",
  "terminology",
  "voice",
  "fluency",
  "wordplay",
  "ui",
  "gameplay",
  "runtime",
  "formatting",
  "other",
];

/** The audit log's groups: by category, findings of one family together. */
export function qaGroups(findings: QaFinding[]) {
  const groups = new Map<string, QaFinding[]>();
  for (const row of findings) {
    const key = categoryOrder.includes(row.category) ? row.category : "other";
    groups.set(key, [...(groups.get(key) || []), row]);
  }
  return [...groups.entries()]
    .sort(
      ([left], [right]) =>
        categoryOrder.indexOf(left) - categoryOrder.indexOf(right),
    )
    .map(([category, rows]) => ({
      category,
      title: category === "ui" ? "Interface" : sentence(category),
      findings: [...rows].sort(
        (left, right) =>
          left.family.localeCompare(right.family) ||
          left.id.localeCompare(right.id),
      ),
    }));
}

/** Where a finding came from, in the reader's words, for a game whose text
 * is in *source*. */
export function qaOrigin(row: QaFinding, source: string) {
  return {
    review: "",
    lint: "Mechanical fix",
    glossary: "Glossary term",
    sweep: "Same problem as an accepted correction",
    source: `Fix for a slip in the ${source} source`,
    scene: "One correction across a scene",
  }[row.kind];
}
