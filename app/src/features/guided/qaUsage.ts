/**
 * The usage note both methods show before Text QA's review starts: about
 * how much of the game the chosen focus reads, and that the assistant's
 * plan pays for it in usage rather than money.
 */

import { useEffect, useState } from "react";
import type { QaSize } from "../../api/contracts";
import { api } from "../../api/client";

/** Text QA's review choices: Guided's QA focus, and Assistant-led's too. */
export const qaFocuses = [
  ["release", "Full game text"],
  ["database", "Database"],
  ["dialogue", "Dialogue"],
  ["risky-codes", "Risky event codes"],
] as const;

/** Whether Text QA's review reads games of `engine`: RPG Maker MV/MZ and
 * VX Ace, the engines Assistant-led's Options offer the choice for. */
export const qaReviews = (engine: string) =>
  engine === "MVMZ" || engine === "ACE";

/** Assistant-led's choice that skips the review, keeping its checks. */
export const qaChecksOnly = ["checks", "Checks only"] as const;

// How often the note reads the count again: soon while a big game is still
// being counted, and slowly otherwise, as when a census is saved meanwhile.
const COUNTING_MS = 2000;
const IDLE_MS = 15000;

/** The note's sentence for `focus`, from the game's count when there is one. */
export function qaUsageText(focus: string, size: QaSize | null) {
  if (focus === qaChecksOnly[0])
    return "Skips the review. Only the quick mechanical checks run, such as glossary terms, numbers and codes kept and text left untranslated, which use little of your assistant's plan.";
  if (size?.counting) return "Counting the lines this review reads…";
  const counted = size?.focuses?.[focus];
  if (!counted)
    return "Your assistant reads every line this review takes, which on a large game uses a lot of its plan's usage. The estimate shows here once DazedTL has counted the game's text.";
  if (!counted.lines) return "This game holds no lines this focus reviews.";
  const scenes = counted.scenes
    ? ` in ${counted.scenes.toLocaleString()} ${counted.scenes === 1 ? "scene" : "scenes"}`
    : "";
  return `Your assistant reads about ${counted.lines.toLocaleString()} ${counted.lines === 1 ? "line" : "lines"}${scenes} of this game to review them, which uses a lot of its plan's usage. An estimate from the game's text.`;
}

/** The usage note for the project's review of `focus`, read while `shown`. */
export function useQaUsageNote(
  projectId: string,
  focus: string,
  shown: boolean,
): string {
  const [read, setRead] = useState<{ projectId: string; size: QaSize } | null>(
    null,
  );
  useEffect(() => {
    if (!shown) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const look = async () => {
      let wait = IDLE_MS;
      try {
        const size = await api.guided.qaSize(projectId);
        if (stopped) return;
        setRead({ projectId, size });
        if (size.counting) wait = COUNTING_MS;
      } catch {
        // The note reads without a count until a later look succeeds.
      }
      if (!stopped) timer = setTimeout(() => void look(), wait);
    };
    void look();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [projectId, shown]);
  return qaUsageText(focus, read?.projectId === projectId ? read.size : null);
}
