import type { QaState, TranslationProgress } from "../../api/contracts";
import type { AssistantTaskState } from "../../ui/AssistantTask";
import type { StepState } from "../../ui/StepProgress";
import { displayLabels } from "../../ui/displayStatus.ts";
import { qaActivity, qaPhase } from "../guided/qaView.ts";

/** The assistant's phases, in the order the starting prompt works through. */
const phases = [
  { id: "preparation", label: "Preparation" },
  { id: "extraction", label: "Extraction" },
  { id: "translation", label: "Translation" },
  { id: "images", label: "Images" },
  { id: "injection", label: "Injection" },
  { id: "qa", label: "QA" },
  { id: "patch", label: "Patch" },
];
const phaseSteps: Record<string, { state: StepState; detail?: string }> = {
  complete: { state: "done" },
  active: { state: "current" },
  blocked: { state: "blocked", detail: displayLabels.blocked },
  out_of_scope: { state: "next", detail: displayLabels.skipped },
};

/**
 * QA's stage and counts come from its task while it runs, and its questions
 * or a task the app can't read hold it. Whether QA is done stays the
 * assistant's report, since new translation after an apply reopens it, but
 * for MV/MZ QA stays open until the final check's playtest settles, as in
 * Guided.
 */
function qaStep(
  qa: QaState | null,
  reported: StepState,
  finalCheck: boolean,
  current: boolean,
): { state: StepState; detail?: string } | null {
  if (!qa) return null;
  const phase = qaPhase(qa);
  if (phase === "blocked")
    return reported === "done"
      ? null
      : { state: "blocked", detail: displayLabels.blocked };
  if (phase === "questions") {
    const open = qa.questions.filter((row) => !row.choice).length;
    return {
      state: "blocked",
      detail: `${open.toLocaleString()} ${open === 1 ? "question" : "questions"} for you`,
    };
  }
  if (phase === "running")
    return {
      state: reported === "current" ? "current" : "started",
      detail: qaActivity(qa) || undefined,
    };
  if (reported === "done" && finalCheck)
    return { state: current ? "current" : "started", detail: "Final check" };
  return null;
}

/**
 * Where the assistant's whole run stands, from its saved reports; for MV/MZ
 * a final check still open keeps the run going (finalCheckOpen).
 */
export function assistantRunState(
  progress: TranslationProgress | null,
  started: boolean,
  finalCheck = false,
): AssistantTaskState {
  if (!progress?.updated_at) return started ? "waiting" : "not_started";
  if (progress.blocker) return "blocked";
  return Object.values(progress.phases).every((phase) =>
    ["complete", "out_of_scope"].includes(phase),
  ) && !(finalCheck && progress.phases.qa === "complete")
    ? "done"
    : "waiting";
}

/**
 * The phase strip has one current phase: the one the assistant reports
 * working in, or else its furthest active one. A phase it left unfinished,
 * such as translation while it works on images during an API run, reads as
 * started. Images shows only when the project includes image text, and QA
 * follows its task once the assistant prepares one, and for MV/MZ its final
 * check (finalCheckOpen). QA reported done but still checking is current
 * unless the assistant reports working in another phase.
 */
export function phaseStates(
  progress: TranslationProgress | null,
  started: boolean,
  images: boolean,
  qa: QaState | null = null,
  finalCheck = false,
): { id: string; label: string; state: StepState; detail?: string }[] {
  const steps = reportedStates(progress, started, images);
  const current = !steps.some((step) => step.state === "current");
  return steps.map((step) =>
    step.id === "qa" && progress?.updated_at
      ? { ...step, ...qaStep(qa, step.state, finalCheck, current) }
      : step,
  );
}

function reportedStates(
  progress: TranslationProgress | null,
  started: boolean,
  images: boolean,
): { id: string; label: string; state: StepState; detail?: string }[] {
  const shown = phases.filter((phase) => images || phase.id !== "images");
  if (!progress?.updated_at)
    return shown.map((phase) => ({
      ...phase,
      state: started && phase.id === "preparation" ? "current" : "next",
    }));
  const active = shown.filter(
    (phase) => progress.phases[phase.id] === "active",
  );
  const current = progress.phase ?? active[active.length - 1]?.id;
  return shown.map((phase) =>
    progress.phases[phase.id] === "active" && phase.id !== current
      ? { ...phase, state: "started", detail: "Unfinished" }
      : {
          ...phase,
          ...(phaseSteps[progress.phases[phase.id]] || { state: "next" }),
        },
  );
}
