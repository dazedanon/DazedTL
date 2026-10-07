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
    id: "prepare",
    title: "Prepare",
    short: "Prepare",
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
        title: "Investigation",
        description: "Find speaker names and prepare reusable guidance.",
      },
      {
        id: "guidance",
        title: "Guidance",
        description: "Edit terminology, translation style and game background.",
      },
      {
        id: "speakers",
        title: "Layout",
        description: "Set character limits for dialogue and interface text.",
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
        title: "Event / plugin codes",
        description:
          "Investigate specific text sources, review their coverage, then translate.",
      },
    ],
  },
  {
    id: "plugins",
    title: "Plugin text",
    short: "Plugin text",
    tasks: [
      {
        id: "plugins",
        title: "Plugin text",
        description:
          "Inspect player-visible text in plugin files and retain any excluded scope.",
      },
    ],
  },
  {
    id: "images",
    title: "Images",
    short: "Images",
    tasks: [
      {
        id: "images",
        title: "Images",
        description:
          "Find relevant images, edit selected copies, and apply reviewed results.",
      },
    ],
  },
  {
    id: "apply",
    title: "Apply & Fitting",
    short: "Apply & Fitting",
    tasks: [
      {
        id: "apply",
        title: "Apply & Fitting",
        description:
          "Apply a selected scope, then inspect its text fitting. QA and game tools are optional.",
      },
    ],
  },
  {
    id: "review",
    title: "Release",
    short: "Release",
    tasks: [
      {
        id: "package",
        title: "Build release ZIP",
        description:
          "Create a clean game or patch archive outside the working game folder.",
      },
    ],
  },
];

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
export function initialPosition(
  state: GuidedState,
  translation: TranslationState,
) {
  const stages = stagesFor(state.engine);
  if (["fitting", "playtest", "qa", "tools"].includes(state.task || ""))
    return { step: "apply" as const, task: "apply" };
  if (state.task === "plugins")
    return { step: "plugins" as const, task: "plugins" };
  if (["images", "image-text", "image-manager"].includes(state.task || ""))
    return { step: "images" as const, task: "images" };
  const step =
    state.step === "layout"
      ? "apply"
      : state.step === "advanced"
        ? "translate"
        : state.step;
  if (state.task === "run")
    return {
      step: runStage(state),
      task:
        state.run?.mode === "speakers" ? "run" : translationTask(state, true),
    };
  if (
    ["audit", "sources", "advanced-run", "variables"].includes(
      state.task || "",
    ) ||
    state.step === "advanced"
  )
    return { step: "translate" as const, task: "other-event-text" };
  if (
    state.step === "translate" &&
    ["scope", "main-text"].includes(state.task || "")
  )
    return { step: "translate" as const, task: mainTextTask(state) };
  const saved = stages.find((stage) => stage.id === step)!;
  if (step === "context" && state.task === "glossary")
    return { step, task: "guidance" };
  if (step === "context" && state.task === "setup")
    return { step, task: "names" };
  if (saved?.tasks.some((task) => task.id === state.task))
    return { step, task: state.task! };
  const preserved =
    translation.lifecycle.source_backup &&
    translation.lifecycle.source_backup.available !== false;
  if (!preserved) return { step: "prepare" as const, task: "setup" };
  if (unfinishedRun(state))
    return {
      step: runStage(state),
      task:
        state.run?.mode === "speakers" ? "run" : translationTask(state, true),
    };
  if (step === "prepare" && translation.git?.configured)
    return { step: "context" as const, task: "names" };
  return { step, task: saved?.tasks[0].id || "setup" };
}
