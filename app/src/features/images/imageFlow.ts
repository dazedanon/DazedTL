import type { ImageManagerState } from "../../api/contracts";

/**
 * The Images flow: the assistant investigates the images, the user chooses
 * which to translate, the assistant translates them and the user applies
 * them to the game. The list of images to translate is the saved selection.
 */
export type ImageStep =
  "investigate" | "choose" | "translate" | "apply" | "done";

export const imageSteps: { id: Exclude<ImageStep, "done">; label: string }[] = [
  { id: "investigate", label: "Investigate" },
  { id: "choose", label: "Choose" },
  { id: "translate", label: "Translate" },
  { id: "apply", label: "Apply" },
];

/** Whether each copied task is still with the assistant. */
export interface ImageWaiting {
  investigation: boolean;
  translation: boolean;
}

/** A partly saved report means the assistant may still be at work. */
const withAssistant = (status: string) =>
  status === "awaiting_results" || status === "partial";

export function imageFlow(
  state: Pick<ImageManagerState, "counts" | "discovery" | "editing">,
  waiting: ImageWaiting = {
    investigation: withAssistant(state.discovery.status),
    translation: withAssistant(state.editing.status),
  },
) {
  const counts = state.counts;
  const listed = counts.selected || 0;
  const applied = counts.selectedApplied || 0;
  const ready = counts.selectedReady || 0;
  const review = counts.selectedNeedsReview || 0;
  // The list's images not yet in the game, which a translation task covers.
  const toTranslate = listed - applied - (counts.selectedSkipped || 0);
  const investigated =
    counts.examined > 0 || state.discovery.status === "complete";
  // A finished investigation that found no text closes Images, as does
  // applied work the list no longer holds.
  const settled =
    counts.applied > 0 ||
    (state.discovery.status === "complete" &&
      !counts.recommended &&
      !counts.uncertain);
  const step: ImageStep = waiting.investigation
    ? "investigate"
    : waiting.translation
      ? "translate"
      : !listed
        ? !investigated
          ? "investigate"
          : settled
            ? "done"
            : "choose"
        : ready || review
          ? "apply"
          : !toTranslate
            ? "done"
            : state.editing.status === "idle"
              ? "choose"
              : "translate";
  return {
    step,
    listed,
    toTranslate,
    /** Images in the list the assistant has not translated yet. */
    untranslated: toTranslate - ready - review,
    ready,
    review,
    applied,
    waiting,
  };
}

export type ImageFlow = ReturnType<typeof imageFlow>;
