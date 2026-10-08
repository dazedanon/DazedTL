import type { StatusKind } from "./StatusIcon";

/**
 * Where a piece of work stands, in the words every screen shares. Each
 * feature keeps its own states; the helpers below say how they read here.
 */
export type DisplayState =
  | "not_started"
  | "working"
  | "waiting"
  | "needs_review"
  | "ready"
  | "applied"
  | "done"
  | "outdated"
  | "blocked"
  | "skipped";

export const displayLabels: Record<DisplayState, string> = {
  not_started: "Not started",
  working: "Working",
  // Handed to an assistant: the app never claims it is running.
  waiting: "Waiting",
  needs_review: "Needs review",
  ready: "Ready to apply",
  applied: "Applied",
  // Finished work that never writes into the game.
  done: "Done",
  outdated: "Outdated",
  blocked: "Blocked",
  skipped: "Skipped",
};

export const displayMarks: Record<DisplayState, StatusKind> = {
  not_started: "idle",
  working: "active",
  waiting: "waiting",
  needs_review: "review",
  ready: "ready",
  applied: "done",
  done: "done",
  outdated: "outdated",
  blocked: "failed",
  skipped: "skipped",
};

/**
 * An Image Manager asset. Discovery findings stay a filter, except that an
 * image found to have nothing to translate is skipped and an uncertain one
 * needs a decision, until the user lists the image to translate.
 */
export function imageDisplay(
  asset: {
    state: string;
    classification: string;
    outdated?: boolean;
  },
  listed = false,
): DisplayState {
  if (asset.outdated) return "outdated";
  switch (asset.state) {
    case "editing":
      return "waiting";
    case "needs_review":
      return "needs_review";
    case "approved":
    case "ready":
      return "ready";
    case "applied":
      return "applied";
    case "skipped":
      return "skipped";
    case "blocked":
    case "conflict":
    case "missing_source":
    case "error":
      return "blocked";
  }
  if (listed && asset.classification !== "excluded") return "not_started";
  if (["no_text", "already_english", "excluded"].includes(asset.classification))
    return "skipped";
  return asset.classification === "uncertain" ? "needs_review" : "not_started";
}
