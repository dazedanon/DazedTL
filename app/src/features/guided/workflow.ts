import type { GuidedState, GuidedStep, Phase, TranslationState } from "../../api/contracts.ts";

export interface WorkflowTask { id: string; title: string; description: string; engine?: "ACE" | "MVMZ" }
export interface WorkflowStage { id: GuidedStep; title: string; short: string; tasks: WorkflowTask[] }
export const workflow: WorkflowStage[] = [
  { id: "prepare", title: "Prepare", short: "Prepare", tasks: [
    { id: "backup", title: "Protect the original", description: "Save a recoverable original before any game files change." },
    { id: "extract", title: "Extract Ace data", description: "Extract encrypted data if needed, then convert the native files to JSON.", engine: "ACE" },
    { id: "format", title: "Prepare game files", description: "Format the runtime files and add GameUpdate support before establishing the original version." },
    { id: "baseline", title: "Save version baseline", description: "Choose which original game version translations and patches belong to." },
  ]},
  { id: "context", title: "Names & context", short: "Context", tasks: [
    { id: "names", title: "Collect character names", description: "Collect likely speaker names before preparing the glossary and game guidance." },
    { id: "setup", title: "Investigate the game", description: "Your coding assistant prepares terminology, voices, speaker recommendations, and measured line widths." },
    { id: "glossary", title: "Review the glossary", description: "Keep recurring names and terms consistent before translating dialogue." },
    { id: "guidance", title: "Review voice & context", description: "Preserve tone, recurring jokes, and facts the translator should know." },
    { id: "speakers", title: "Speakers & line widths", description: "Apply only the speaker rules and widths confirmed by the setup report." },
  ]},
  { id: "translate", title: "Translate", short: "Translate", tasks: [
    { id: "scope", title: "Choose a test scope", description: "Start with database text and an early scene. Apply and playtest it before expanding the translation." },
    { id: "database", title: "Database & interface", description: "Establish names and terms before translating dialogue." },
    { id: "dialogue", title: "Dialogue & choices", description: "Translate the selected event files using saved guidance, speaker settings, and widths." },
    { id: "variables", title: "Variable comparison cache", description: "Translate comparisons (111) so audited assignments (122) can reuse the same wording." },
  ]},
  { id: "advanced", title: "Extra text", short: "Extra text", tasks: [
    { id: "audit", title: "Audit extra text", description: "Inspect unusual text sources before enabling variables, scripts, or plugin commands." },
    { id: "sources", title: "Review safe sources", description: "Keep each source and its audited IDs, handlers, or patterns together. Leave SKIP and NONE sources off." },
    { id: "advanced-run", title: "Translate audited text", description: "Translate only the sources confirmed by the audit. Skip this phase if none are needed." },
  ]},
  { id: "apply", title: "Apply & test", short: "Apply & test", tasks: [
    { id: "plugins", title: "Plugin & image text", description: "Inspect player-visible text outside the main JSON phases and retain any excluded scope." },
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
  return state.run?.mode === "speakers" ? "context" : runPhase(state) === "advanced" ? "advanced" : "translate";
}
export function runPhase(state: GuidedState): Phase {
  // Native job.phase also carries progress states such as batch_approval/poll.
  return ["database", "dialogue", "variables", "advanced", "speakers"].includes(state.run?.phase || "")
    ? state.run!.phase as Phase : state.phase;
}
export function unfinishedRun(state: GuidedState) {
  return !!state.run && ["batch", "translate", "speakers"].includes(state.run.mode || "") && !["complete", "canceled"].includes(state.run.status);
}
export function initialPosition(state: GuidedState, translation: TranslationState) {
  const stages = stagesFor(state.engine);
  const step = state.step === "layout" ? "apply" : state.step === "translate" && state.phase === "advanced" ? "advanced" : state.step;
  const saved = stages.find((stage) => stage.id === step)!;
  if (state.task === "run") return { step: runStage(state), task: "run" };
  if (saved?.tasks.some((task) => task.id === state.task)) return { step, task: state.task! };
  const preserved = translation.lifecycle.source_backup && translation.lifecycle.source_backup.available !== false;
  if (!preserved) return { step: "prepare" as const, task: "backup" };
  if (unfinishedRun(state)) return { step: runStage(state), task: "run" };
  if (step === "prepare" && translation.git?.configured) return { step: "context" as const, task: "names" };
  return { step, task: saved?.tasks[0].id || "backup" };
}
