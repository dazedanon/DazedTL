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
          "Prepare its files and save its version so later game updates can be merged. The first change keeps the original files in Git.",
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
        id: "event-sources",
        title: "Event text sources",
        description:
          "Find which event codes, plugin commands and scripts carry player text, and choose what Translate covers.",
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
          "Set how many characters fit on a line, and how many rows fit in a message window.",
      },
      {
        id: "estimate",
        title: "Cost estimate",
        description:
          "Estimate what translating the game's text with your API key costs.",
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
          "Translate the event codes, plugin commands and scripts chosen in Event text sources.",
      },
      {
        id: "plugins",
        engine: "MVMZ",
        title: "Plugin files",
        description: "Translate the text plugins show to players.",
      },
      {
        // VX Ace keeps this text in its Ruby scripts.
        id: "plugins",
        engine: "ACE",
        title: "Plugin files",
        description: "Translate the text the game's scripts show to players.",
      },
      {
        id: "images",
        title: "Images",
        description: "Translate the text in the game's images.",
      },
    ],
  },
  {
    id: "check",
    title: "Check",
    short: "Check",
    tasks: [
      {
        id: "qa",
        optional: true,
        title: "Text QA",
        description:
          "Your assistant reviews the game's text and, for MV and MZ, plays the game and fixes what it finds.",
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
 * The stages that are done: a stage once its required tasks are; a stage of
 * optional tasks only, such as Check and Release, once all of them are or once
 * it has been opened with every required task before it done.
 */
export function doneStages(
  stages: WorkflowStage[],
  completed: ReadonlySet<string>,
  opened: ReadonlySet<GuidedStep>,
) {
  const done = new Set<GuidedStep>();
  let earlierDone = true;
  for (const stage of stages) {
    const required = stage.tasks.filter((task) => !task.optional);
    const requiredDone = required.every((task) => completed.has(task.id));
    if (
      required.length
        ? requiredDone
        : stage.tasks.every((task) => completed.has(task.id)) ||
          (earlierDone && opened.has(stage.id))
    )
      done.add(stage.id);
    earlierDone &&= requiredDone;
  }
  return done;
}

/** Stages the user has opened: navigation saves a position for each one. */
export function openedStages(state: GuidedState) {
  return new Set([
    state.step,
    ...(Object.keys(state.positions ?? {}) as GuidedStep[]),
  ]);
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
  // Other event text's views saved as tasks; investigating and choosing its
  // sources moved to Context.
  if (["audit", "sources"].includes(state.task || ""))
    return { step: "context", task: "event-sources" };
  if (["advanced-run", "variables"].includes(state.task || ""))
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
  if (!translation.git?.configured) return { step: "setup", task: "setup" };
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
