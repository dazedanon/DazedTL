import type { TranslationProgress } from "../../api/contracts";
import type { StepState } from "../../ui/StepProgress";
import { displayLabels } from "../../ui/displayStatus.ts";

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
 * The phase strip has one current phase: the one the assistant reports
 * working in, or else its furthest active one. A phase it left unfinished,
 * such as translation while it works on images during an API run, reads as
 * started. Images shows only when the project includes image text.
 */
export function phaseStates(
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
