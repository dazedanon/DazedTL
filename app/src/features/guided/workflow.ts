import type { GuidedState, GuidedStep, Phase, TranslationState } from "../../api/contracts.ts";

export interface WorkflowTask { id: string; title: string; description: string; engine?: "ACE" | "MVMZ" }
export interface WorkflowStage { id: GuidedStep; title: string; short: string; tasks: WorkflowTask[] }
export const workflow: WorkflowStage[] = [
  { id: "prepare", title: "Prepare", short: "Prepare", tasks: [
    { id: "backup", title: "Protect the original", description: "Save a recoverable original before any game files change." },
    { id: "extract", title: "Extract Ace data", description: "Extract encrypted data if needed, then convert the native files to JSON.", engine: "ACE" },
    { id: "format", title: "Prepare game files", description: "Run the required preparation stages in order." },
    { id: "baseline", title: "Save version baseline", description: "Record this prepared version so future game updates can be compared and merged." },
  ]},
  { id: "context", title: "Names & context", short: "Context", tasks: [
    { id: "names", title: "Speakers & game context", description: "Discover how speakers are named, then save reusable guidance." },
    { id: "guidance", title: "Review translation guidance", description: "Review names, terminology, translation style and game background." },
    { id: "speakers", title: "Review layout settings", description: "Set character limits for the game’s text areas." },
  ]},
  { id: "translate", title: "Translate", short: "Translate", tasks: [
    { id: "main-text", title: "Translate main text", description: "Choose any subset in either row. Estimate and review each run before it starts." },
    { id: "other-event-text", title: "Other event text", description: "Variables, plugin commands, scripts, and labels." },
  ]},
  { id: "plugins", title: "Plugin text", short: "Plugin text", tasks: [
    { id: "plugins", title: "Plugin text", description: "Inspect player-visible text in plugin files and retain any excluded scope." },
  ]},
  { id: "images", title: "Images", short: "Images", tasks: [
    { id: "images", title: "Images", description: "Find relevant images, edit selected copies, and apply reviewed results." },
  ]},
  { id: "apply", title: "Apply & test", short: "Apply & test", tasks: [
    { id: "apply", title: "Apply selected outputs", description: "Review which runtime files will receive saved translations." },
    { id: "fitting", title: "Fit text to windows", description: "Scan using the saved widths, then review proposed fitting changes." },
    { id: "playtest", title: "Playtest this scope", description: "Check an early scene in the game before expanding the scope." },
    { id: "qa", title: "Text QA findings", description: "Prepare or resume the assistant’s QA task, then inspect its saved findings." },
  ]},
  { id: "review", title: "Release", short: "Release", tasks: [
    { id: "tools", title: "Playtest tools", description: "Install and configure TL Inspector and Forge for in-game inspection and editing.", engine: "MVMZ" },
    { id: "package", title: "Build release ZIP", description: "Create a clean game or patch archive outside the working game folder." },
  ]},
];

export function stagesFor(engine: GuidedState["engine"]) {
  return workflow.map((stage) => ({ ...stage, tasks: stage.tasks.filter((task) => !task.engine || task.engine === engine) }));
}
export function runStage(state: GuidedState): GuidedStep {
  return state.run?.mode === "speakers" ? "context" : "translate";
}
export function runPhase(state: GuidedState): Phase {
  // Native job.phase also carries progress states such as batch_approval/poll.
  if (state.run?.logicalPhase) return state.run.logicalPhase;
  return ["database", "dialogue", "variables", "advanced", "speakers"].includes(state.run?.phase || "")
    ? state.run!.phase as Phase : state.phase;
}
export function unfinishedRun(state: GuidedState) {
  return !!state.run && ["batch", "translate", "speakers"].includes(state.run.mode || "") && !["complete", "canceled"].includes(state.run.status);
}
export function initialPosition(state: GuidedState, translation: TranslationState) {
  const stages = stagesFor(state.engine);
  if (state.task === "plugins") return { step: "plugins" as const, task: "plugins" };
  if (["images", "image-text", "image-manager"].includes(state.task || "")) return { step: "images" as const, task: "images" };
  const step = state.step === "layout" ? "apply" : state.step === "advanced" ? "translate" : state.step;
  if (state.task === "run") return { step: runStage(state), task: "run" };
  if (["audit", "sources", "advanced-run", "variables"].includes(state.task || "") || state.step === "advanced") return { step: "translate" as const, task: "other-event-text" };
  if (state.step === "translate" && ["scope", "database", "dialogue"].includes(state.task || "")) return { step: "translate" as const, task: "main-text" };
  const saved = stages.find((stage) => stage.id === step)!;
  if (step === "context" && state.task === "glossary") return { step, task: "guidance" };
  if (step === "context" && state.task === "setup") return { step, task: "names" };
  if (state.task === "run") return { step: runStage(state), task: "run" };
  if (saved?.tasks.some((task) => task.id === state.task)) return { step, task: state.task! };
  const preserved = translation.lifecycle.source_backup && translation.lifecycle.source_backup.available !== false;
  if (!preserved) return { step: "prepare" as const, task: "backup" };
  if (unfinishedRun(state)) return { step: runStage(state), task: "run" };
  if (step === "prepare" && translation.git?.configured) return { step: "context" as const, task: "names" };
  return { step, task: saved?.tasks[0].id || "backup" };
}
