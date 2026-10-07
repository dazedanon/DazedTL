import type {
  GuidedState,
  GuidedStep,
  Phase,
  TranslationState,
} from "../../api/contracts.ts";

export interface WorkflowTask {
  id: string;
  title: string;
  description: string;
  /** Optional work can be done but never holds up the next step. */
  optional?: boolean;
  engine?: "ACE" | "MVMZ";
}
export interface WorkflowStage {
  id: GuidedStep;
  title: string;
  short: string;
  tasks: WorkflowTask[];
}
export const workflow: WorkflowStage[] = [
  {
    id: "setup",
    title: "Set up",
    short: "Set up",
    tasks: [
      {
        id: "setup",
        title: "Set up this game",
        description:
          "Back up the original, prepare its files and save its version so later game updates can be merged.",
      },
    ],
  },
  {
    id: "context",
    title: "Context",
    short: "Context",
    tasks: [
      {
        id: "names",
        title: "Names & glossary",
        description:
          "Find speaker names and prepare the glossary and game context.",
      },
      {
        id: "guidance",
        title: "Guidance",
        description: "Edit terminology, translation style and game background.",
      },
      {
        id: "speakers",
        title: "Line widths",
        description:
          "Set how many characters fit on a line of dialogue and interface text.",
      },
    ],
  },
  {
    id: "translate",
    title: "Translate",
    short: "Translate",
    tasks: [
      {
        id: "database",
        title: "Database files",
        description: "Names, descriptions and interface text.",
      },
      {
        id: "dialogue",
        title: "Maps & events",
        description: "Maps, common events and troop events.",
      },
      {
        id: "other-event-text",
        title: "Other event text",
        description:
          "Investigate specific text sources, review their coverage, then translate.",
      },
      {
        id: "plugins",
        title: "Plugin files",
        description:
          "Inspect player-visible text in plugin files and retain any excluded scope.",
      },
      {
        id: "images",
        title: "Images",
        description:
          "Find relevant images, edit selected copies, and apply reviewed results.",
      },
    ],
  },
  {
    id: "check",
    title: "Check",
    short: "Check",
    tasks: [
      {
        id: "apply",
        title: "Pending changes",
        description: "Everything reviewed and waiting to go into the game.",
      },
      {
        id: "fitting",
        optional: true,
        title: "Line width check",
        description:
          "Rewrap applied text that is wider than the saved line widths.",
      },
      {
        id: "qa",
        optional: true,
        title: "Text QA",
        description:
          "Prepare a QA task, copy it to your assistant, then review its saved findings.",
      },
    ],
  },
  {
    id: "release",
    title: "Release",
    short: "Release",
    tasks: [
      {
        id: "package",
        optional: true,
        title: "Build release ZIP",
        description:
          "Create a clean game or patch archive outside the working game folder.",
      },
    ],
  },
];

/**
 * A stage is done once its required tasks are; a stage of optional tasks
 * only, such as Release, once all of them are.
 */
export function stageDone(
  stage: WorkflowStage,
  completed: ReadonlySet<string>,
) {
  const required = stage.tasks.filter((task) => !task.optional);
  return (required.length ? required : stage.tasks).every((task) =>
    completed.has(task.id),
  );
}

export function stagesFor(engine: GuidedState["engine"]) {
  return workflow.map((stage) => ({
    ...stage,
    tasks: stage.tasks.filter((task) => !task.engine || task.engine === engine),
  }));
}
export function runStage(state: GuidedState): GuidedStep {
  return state.run?.mode === "speakers" ? "context" : "translate";
}
export function runPhase(state: GuidedState): Phase {
  // Native job.phase also carries progress states such as batch_approval/poll.
  if (state.run?.logicalPhase) return state.run.logicalPhase;
  return ["database", "dialogue", "variables", "advanced", "speakers"].includes(
    state.run?.phase || "",
  )
    ? (state.run!.phase as Phase)
    : state.phase;
}
export function unfinishedRun(state: GuidedState) {
  return (
    !!state.run &&
    ["batch", "translate", "speakers"].includes(state.run.mode || "") &&
    ["running", "waiting"].includes(state.run.status)
  );
}
export function taskForStage(state: GuidedState, stage: WorkflowStage) {
  const task = state.positions?.[stage.id];
  if (
    stage.id === "translate" &&
    ["main-text", "scope", "run"].includes(task || "")
  )
    return task === "run" ? translationTask(state, true) : mainTextTask(state);
  if (task === "run" && state.run && runStage(state) === stage.id) return task;
  return stage.tasks.find((item) => item.id === task)?.id || stage.tasks[0].id;
}
function mainTextTask(state: GuidedState) {
  return (unfinishedRun(state) &&
  ["database", "dialogue"].includes(runPhase(state))
    ? runPhase(state)
    : state.phase) === "dialogue"
    ? "dialogue"
    : "database";
}
function translationTask(state: GuidedState, savedRun = false) {
  const phase =
    savedRun || unfinishedRun(state) ? runPhase(state) : state.phase;
  return phase === "dialogue"
    ? "dialogue"
    : phase === "advanced" || phase === "variables"
      ? "other-event-text"
      : "database";
}
/**
 * The task Translation opens on. Saved positions arrive in the current stage
 * ids (the backend and the navigation preferences migrate older layouts);
 * older task names inside a stage still open the task that holds their work.
 */
export function initialPosition(
  state: GuidedState,
  translation: TranslationState,
): { step: GuidedStep; task: string } {
  const stages = stagesFor(state.engine);
  const step = state.step;
  if (state.task === "run")
    return {
      step: runStage(state),
      task:
        state.run?.mode === "speakers" ? "run" : translationTask(state, true),
    };
  if (
    ["audit", "sources", "advanced-run", "variables"].includes(state.task || "")
  )
    return { step: "translate", task: "other-event-text" };
  if (step === "translate" && ["scope", "main-text"].includes(state.task || ""))
    return { step: "translate", task: mainTextTask(state) };
  const saved = stages.find((stage) => stage.id === step);
  if (step === "context" && state.task === "glossary")
    return { step, task: "guidance" };
  if (step === "context" && state.task === "setup")
    return { step, task: "names" };
  if (saved?.tasks.some((task) => task.id === state.task))
    return { step, task: state.task! };
  const preserved =
    translation.lifecycle.source_backup &&
    translation.lifecycle.source_backup.available !== false;
  if (!preserved) return { step: "setup", task: "setup" };
  if (unfinishedRun(state))
    return {
      step: runStage(state),
      task:
        state.run?.mode === "speakers" ? "run" : translationTask(state, true),
    };
  if (!saved || (step === "setup" && translation.git?.configured))
    return translation.git?.configured
      ? { step: "context", task: "names" }
      : { step: "setup", task: "setup" };
  return { step, task: saved.tasks[0].id };
}
