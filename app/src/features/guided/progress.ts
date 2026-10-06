import type {
  GuidedState,
  GuidedStep,
  TranslationState,
} from "../../api/contracts";
import { investigationResults } from "./contextView";
import { guidanceAvailability } from "./guidanceReview";
import {
  completeForSelection,
  selectionSettled,
  translationTaskComplete,
} from "./translationView";
import { initialPosition, stagesFor } from "./workflow";

type Values = GuidedState["preferences"]["values"];

/**
 * Tasks whose saved evidence shows them done. `values` lets the open
 * workspace pass its draft selection; unsaved width edits never count.
 */
export function completedTasks(
  state: GuidedState,
  translation: TranslationState,
  values: Values = state.preferences.values,
  widthsDirty = false,
) {
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const selected = new Set(values.selected);
  const eventFiles = state.files
    .filter((file) => file.group === "dialogue" && selected.has(file.name))
    .map((file) => file.name);
  const outputs = state.readiness.outputs.filter((name) => selected.has(name));
  const applied =
    outputs.length > 0 &&
    outputs.every((name) => state.readiness.applied.includes(name));
  const phaseComplete = (
    target: "database" | "dialogue" | "advanced" | "variables",
  ) => {
    if (target === "database" || target === "dialogue")
      return translationTaskComplete(state, target);
    const saved = state.phaseRuns[target];
    return (
      (!!saved && completeForSelection(saved, eventFiles)) ||
      selectionSettled(state, target, eventFiles)
    );
  };
  const discovery = state.contextSetup;
  return new Set<string>([
    ...(preserved ? ["backup"] : []),
    ...(baseline ? ["baseline"] : []),
    ...(applied ? ["apply"] : []),
    ...(phaseComplete("database") ? ["database"] : []),
    ...(phaseComplete("dialogue") ? ["dialogue"] : []),
    ...(phaseComplete("advanced") &&
    (state.comparisons.status === "not_needed" ||
      (state.comparisons.status === "ready" && phaseComplete("variables")))
      ? ["other-event-text"]
      : []),
    ...(investigationResults(state).every((row) => row.saved) ? ["names"] : []),
    ...(guidanceAvailability(discovery.documents).complete ? ["guidance"] : []),
    ...(discovery.layoutStatus === "saved" && !widthsDirty ? ["speakers"] : []),
    ...(state.preparation.complete || baseline ? ["format"] : []),
    ...(state.tools?.inspector.installed && state.tools.forge.installed
      ? ["tools"]
      : []),
  ]);
}

// Tasks with a completion signal; optional work such as Plugin text, Images
// and Release never blocks "next".
const tracked = new Set([
  "backup",
  "format",
  "baseline",
  "names",
  "guidance",
  "speakers",
  "database",
  "dialogue",
  "apply",
]);

export type GuidedProgress = {
  stages: {
    id: GuidedStep;
    short: string;
    title: string;
    done: number;
    total: number;
    tasks: { id: string; title: string; done: boolean }[];
  }[];
  /** The first unfinished required task, in workflow order. */
  next: {
    step: GuidedStep;
    stage: string;
    task: string;
    title: string;
    description: string;
  } | null;
  /** Where the workspace reopens. */
  current: { step: GuidedStep; task: string; stage: string; title: string };
};

/** Where a Guided project stands, from saved state only. */
export function guidedProgress(
  state: GuidedState,
  translation: TranslationState,
): GuidedProgress {
  const stages = stagesFor(state.engine);
  const done = completedTasks(state, translation);
  const next = stages
    .flatMap((stage) => stage.tasks.map((task) => ({ stage, task })))
    .find(({ task }) => tracked.has(task.id) && !done.has(task.id));
  return {
    stages: stages.map((stage) => ({
      id: stage.id,
      short: stage.short,
      title: stage.title,
      done: stage.tasks.filter((task) => done.has(task.id)).length,
      total: stage.tasks.length,
      tasks: stage.tasks.map((task) => ({
        id: task.id,
        title: task.title,
        done: done.has(task.id),
      })),
    })),
    next: next
      ? {
          step: next.stage.id,
          stage: next.stage.short,
          task: next.task.id,
          title: next.task.title,
          description: next.task.description,
        }
      : null,
    current: (() => {
      const position = initialPosition(state, translation);
      const stage = stages.find((item) => item.id === position.step);
      const task = stage?.tasks.find((item) => item.id === position.task);
      return {
        ...position,
        stage: stage?.short || "",
        title: task?.title || stage?.short || "",
      };
    })(),
  };
}
