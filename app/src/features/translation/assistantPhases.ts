import type { TranslationProgress } from "../../api/contracts";
import type { StepState } from "../../ui/StepProgress";
import { displayLabels } from "../../ui/displayStatus.ts";

/** The assistant's phases, in the order the starting prompt works through. */
const phases = [
  { id: "preparation", label: "Preparation" },
  { id: "extraction", label: "Extraction" },
  { id: "translation", label: "Translation" },
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
 * such as translation while images remain, reads as started.
 */
export function phaseStates(
  progress: TranslationProgress | null,
  started: boolean,
  images: boolean,
): { id: string; label: string; state: StepState; detail?: string }[] {
  if (!progress?.updated_at)
    return phases.map((phase) => ({
      ...phase,
      state: started && phase.id === "preparation" ? "current" : "next",
    }));
  const active = phases.filter(
    (phase) => progress.phases[phase.id] === "active",
  );
  const current = progress.phase ?? active[active.length - 1]?.id;
  const { text, images: pictures } = progress.metrics;
  // Translation completes only once every scoped line and image is done.
  const imagesLeft =
    images &&
    text.total !== null &&
    text.translated === text.total &&
    (pictures.total === null || pictures.translated < pictures.total);
  return phases.map((phase) =>
    progress.phases[phase.id] === "active" && phase.id !== current
      ? {
          ...phase,
          state: "started",
          detail:
            phase.id === "translation" && imagesLeft
              ? "Images left"
              : "Unfinished",
        }
      : {
          ...phase,
          ...(phaseSteps[progress.phases[phase.id]] || { state: "next" }),
        },
  );
}
