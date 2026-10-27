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
  state: Pick<
    ImageManagerState,
    "counts" | "investigated" | "discovery" | "editing"
  >,
  waits: ImageWaiting = {
    investigation: withAssistant(state.discovery.status),
    translation: withAssistant(state.editing.status),
  },
) {
  const counts = state.counts;
  // The user stopped the investigation to choose the images themselves,
  // which the copied task's record may not show yet.
  const stopped = state.discovery.status === "stopped";
  const waiting = {
    ...waits,
    investigation: waits.investigation && !stopped,
  };
  const listed = counts.selected || 0;
  const applied = counts.selectedApplied || 0;
  const ready = counts.selectedReady || 0;
  const review = counts.selectedNeedsReview || 0;
  // The list's images not yet in the game, which a translation task covers.
  const toTranslate = listed - applied - (counts.selectedSkipped || 0);
  // The backend decides whether every image is investigated, as images
  // --status reads it.
  const investigated = state.investigated;
  // Applying what was translated finishes Images; an image the list still
  // holds untranslated, or one ticked later, can start another round without
  // reopening it. An investigation that leaves nothing ticked finishes too.
  const step: ImageStep = waiting.investigation
    ? "investigate"
    : waiting.translation
      ? "translate"
      : !listed
        ? stopped && !counts.applied
          ? "choose"
          : investigated || counts.applied
            ? "done"
            : "investigate"
        : ready || review
          ? "apply"
          : !toTranslate || applied
            ? "done"
            : state.editing.status === "idle"
              ? "choose"
              : "translate";
  return {
    step,
    investigated,
    /** Images still wait to be examined before the list to translate fills. */
    unexamined: step === "investigate" && !investigated,
    stopped,
    /** A waiting investigation the user can stop to choose the images. */
    stoppable: waiting.investigation && withAssistant(state.discovery.status),
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
