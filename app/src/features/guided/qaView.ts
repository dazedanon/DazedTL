/** Text QA as the page shows it, from the observed QA state. */

import type { QaFinding, QaState } from "../../api/contracts";
import type { StepState } from "../../ui/StepProgress";
import { sentence } from "../../ui/displayText.ts";

/** Where text QA stands on the page. */
export type QaPhase =
  | "not_started"
  | "running"
  | "questions"
  | "ready"
  | "applied"
  | "clean"
  | "outdated";

export function qaPhase(qa: QaState): QaPhase {
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

/** The one activity line, such as "Deep review 412 of 621 · about 25 min left". */
export function qaActivity(qa: QaState) {
  const activity = qa.activity;
  if (!activity) return "";
  return [
    `${stageNames[activity.stage]} ${activity.done.toLocaleString()} of ${activity.total.toLocaleString()}`,
    activity.eta_seconds !== undefined && timeLeft(activity.eta_seconds),
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
  const screen = (status.screen || {}) as Counts & { lint?: Counts };
  const deep = (status.deep || {}) as Counts;
  const lint = screen.lint || {};
  const order = ["screen", "deep", "sweep", "editorial", "complete"];
  const reached = (name: string) =>
    !!qa.task &&
    (order.indexOf(stage) > order.indexOf(name) ||
      (stage === "ready-finalize" && order.indexOf(name) < 2));
  const lintDone = (lint.accepted || 0) >= (lint.total || 0);
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

/** The summary line once QA is done: corrections and what it covered. */
export function qaSummary(qa: QaState) {
  // A proposal the user chose counts as a correction.
  const chosen = qa.questions.filter((row) => row.choice === "use");
  const applied = [...qa.findings, ...chosen].filter(
    (row) => row.state === "applied",
  ).length;
  const lines = qa.coverage?.lines || 0;
  const missing = qa.coverage?.not_reviewed || 0;
  const corrections = (count: number) =>
    `${count.toLocaleString()} ${count === 1 ? "correction" : "corrections"}`;
  return [
    qa.applied
      ? `${corrections(applied)} applied`
      : qa.findings.length + chosen.length
        ? `${corrections(qa.findings.length + chosen.length)} to apply`
        : "No corrections needed",
    lines && `${(lines - missing).toLocaleString()} lines checked`,
  ]
    .filter(Boolean)
    .join(" · ");
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

/** Where a finding came from, in the reader's words. */
export function qaOrigin(row: QaFinding) {
  return {
    review: "",
    lint: "Mechanical fix",
    sweep: "Same problem as an accepted correction",
    source: "Fix for a slip in the Japanese source",
  }[row.kind];
}

/**
 * An apply or undo whose checkpoint failed has no control left to report
 * it; saving the version again takes its place and reports its own result,
 * under the "qa-save" key.
 */
export function qaUnsaved(qa: QaState, action: { key: string; error: string }) {
  return (
    action.key === "qa-save" ||
    (!!action.error &&
      ((action.key === "qa-apply" && qaPhase(qa) === "applied") ||
        [...qa.findings, ...qa.questions].some(
          (row) => action.key === "qa-undo:" + row.id && row.state === "undone",
        )))
  );
}
