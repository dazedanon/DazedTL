import type { QaState, TranslationProgress } from "../../api/contracts";
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
 * hold it for the user. Whether QA is done stays the assistant's report:
 * new translation after an apply reopens it.
 */
function qaStep(
  qa: QaState | null,
  reported: StepState,
): { state: StepState; detail?: string } | null {
  if (!qa?.task) return null;
  const phase = qaPhase(qa);
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
  return null;
}

/**
 * The phase strip has one current phase: the one the assistant reports
 * working in, or else its furthest active one. A phase it left unfinished,
 * such as translation while it works on images during an API run, reads as
 * started. Images shows only when the project includes image text, and QA
 * follows its task once the assistant prepares one.
 */
export function phaseStates(
  progress: TranslationProgress | null,
  started: boolean,
  images: boolean,
  qa: QaState | null = null,
): { id: string; label: string; state: StepState; detail?: string }[] {
  return reportedStates(progress, started, images).map((step) =>
    step.id === "qa" && progress?.updated_at
      ? { ...step, ...qaStep(qa, step.state) }
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
