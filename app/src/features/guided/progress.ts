import type {
  GuidedState,
  GuidedStep,
  ImageForeignWork,
  ImageManagerState,
  PluginForeignWork,
  PluginState,
  TranslationState,
} from "../../api/contracts";
import { investigationResults } from "./contextView.ts";
import { nothingToTranslate } from "./eventTextSelection.ts";
import { guidanceAvailability } from "./guidanceReview.ts";
import { pluginsComplete } from "../plugins/pluginTask.ts";
import { imageFlow } from "../images/imageFlow.ts";
import {
  eventTaskFiles,
  fileLines,
  translationTaskComplete,
} from "./translationView.ts";
import {
  doneStages,
  initialPosition,
  openedStages,
  stagesFor,
} from "./workflow.ts";

type Values = GuidedState["preferences"]["values"];

/** The observed Plugin files and Images work, which Guided state leaves out. */
export type ObservedWork = {
  plugins?: PluginState | null;
  images?: ImageManagerState | null;
  /** Work another project saved in the game folder, waiting for a choice. */
  pluginsForeign?: PluginForeignWork;
  imagesForeign?: ImageForeignWork;
};

/** Tasks that need the user's choice before their work can continue. */
export function reviewTasks({ pluginsForeign, imagesForeign }: ObservedWork) {
  return new Set<string>([
    ...(pluginsForeign ? ["plugins"] : []),
    ...(imagesForeign ? ["images"] : []),
  ]);
}

/**
 * Tasks whose saved evidence shows them done. `values` lets the open
 * workspace pass its draft selection; unsaved width edits never count.
 */
export function completedTasks(
  state: GuidedState,
  translation: TranslationState,
  {
    values = state.preferences.values,
    widthsDirty = false,
    plugins,
    images,
  }: { values?: Values; widthsDirty?: boolean } & ObservedWork = {},
) {
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const phaseComplete = (
    target: "database" | "dialogue" | "advanced" | "variables",
  ) =>
    target === "database" || target === "dialogue"
      ? translationTaskComplete(state, target)
      : translationTaskComplete(
          state,
          target,
          eventTaskFiles(state, target, values.selected),
        );
  const discovery = state.contextSetup;
  // Plugin files is done once every plugin's player text is translated with
  // nothing waiting to go into the game, and Images once every image in its
  // list is in the game or a finished investigation found no image text.
  // Release is done while a saved ZIP still matches the game.
  const ownPlugins =
    plugins && plugins.projectId === state.projectId ? plugins : null;
  const ownImages =
    images && images.projectId === state.projectId ? images : null;
  return new Set<string>([
    ...(baseline ? ["setup"] : []),
    ...(phaseComplete("database") ? ["database"] : []),
    ...(phaseComplete("dialogue") ? ["dialogue"] : []),
    ...((nothingToTranslate(state.eventText, values.engine_options) ||
      phaseComplete("advanced")) &&
    (state.comparisons.status === "not_needed" ||
      (state.comparisons.status === "ready" && phaseComplete("variables")))
      ? ["other-event-text"]
      : []),
    ...(investigationResults(state).every((row) => row.saved) ? ["names"] : []),
    ...(guidanceAvailability(discovery.documents).complete ? ["guidance"] : []),
    ...(discovery.layoutStatus === "saved" && !widthsDirty ? ["speakers"] : []),
    ...(ownPlugins && pluginsComplete(ownPlugins) ? ["plugins"] : []),
    ...(ownImages && imageFlow(ownImages).step === "done" ? ["images"] : []),
    ...(state.artifacts.some((artifact) => artifact.current)
      ? ["package"]
      : []),
    ...(lineWidthsChecked(state) ? ["fitting"] : []),
  ]);
}

/** The current line width check found nothing left to rewrap. */
function lineWidthsChecked(state: GuidedState) {
  const scan = state.operations.find(
    (item) => item.id === state.readiness.layout_scan,
  )?.result as
    { changes_found?: number; overflow_skipped?: number } | undefined;
  return (
    !!scan && (scan.changes_found ?? 0) - (scan.overflow_skipped ?? 0) <= 0
  );
}

export type GuidedProgress = {
  stages: {
    id: GuidedStep;
    short: string;
    title: string;
    complete: boolean;
    /** Required tasks done, of the stage's required tasks. */
    done: number;
    total: number;
    tasks: {
      id: string;
      title: string;
      done: boolean;
      optional: boolean;
      /** Waiting for the user's choice, such as work another project saved. */
      review: boolean;
    }[];
  }[];
  /** The first unfinished required task, in workflow order. */
  next: {
    step: GuidedStep;
    stage: string;
    task: string;
    title: string;
    description: string;
  } | null;
  /**
   * The task last opened in Translation, when it differs from `next`. A
   * finished task before `next`, such as setup, has nothing to return to.
   */
  last: {
    step: GuidedStep;
    task: string;
    stage: string;
    title: string;
  } | null;
};

/** Where a Guided project stands, from saved state only. */
export function guidedProgress(
  state: GuidedState,
  translation: TranslationState,
  observed: ObservedWork = {},
): GuidedProgress {
  const stages = stagesFor(state.engine);
  const done = completedTasks(state, translation, observed);
  const review = reviewTasks(observed);
  const finished = doneStages(stages, done, openedStages(state));
  const order = stages.flatMap((stage) =>
    stage.tasks.map((task) => ({ stage, task })),
  );
  const next = order.find(({ task }) => !task.optional && !done.has(task.id));
  const position = initialPosition(state, translation);
  const index = (task: string) =>
    order.findIndex((item) => item.task.id === task);
  const opened = stages.find((item) => item.id === position.step);
  const last =
    next &&
    (position.task === next.task.id ||
      (done.has(position.task) && index(position.task) < index(next.task.id)))
      ? null
      : {
          ...position,
          stage: opened?.short || "",
          title:
            opened?.tasks.find((item) => item.id === position.task)?.title ||
            opened?.short ||
            "",
        };
  return {
    stages: stages.map((stage) => ({
      id: stage.id,
      short: stage.short,
      title: stage.title,
      complete: finished.has(stage.id),
      done: stage.tasks.filter((task) => !task.optional && done.has(task.id))
        .length,
      total: stage.tasks.filter((task) => !task.optional).length,
      tasks: stage.tasks.map((task) => ({
        id: task.id,
        title: task.title,
        done: done.has(task.id),
        optional: !!task.optional,
        review: review.has(task.id),
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
    last,
  };
}

/**
 * The project's amounts from saved engine receipts: lines translated (with a
 * total only when every file's total is known), files applied and the cost the
 * engine recorded. Batch charges without a receipt are not included.
 */
export function projectAmounts(state: GuidedState) {
  let done = 0,
    total: number | null = 0;
  for (const file of state.files) {
    const lines = fileLines(state, file.group, file.name);
    done += lines.done;
    total = total === null || lines.total === null ? null : total + lines.total;
  }
  const outputs = state.readiness.outputs;
  const cost = state.runs
    .filter((run) => run.mode !== "estimate")
    .reduce(
      (sum, run) =>
        sum +
        Object.values(run.process?.fileMetrics || {}).reduce(
          (files, metric) => files + metric.cost,
          0,
        ) +
        (run.process?.billing?.openrouter_cost || 0),
      0,
    );
  return {
    done,
    total,
    applied: outputs.filter((name) => state.readiness.applied.includes(name))
      .length,
    outputs: outputs.length,
    cost,
  };
}
