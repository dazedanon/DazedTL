/** What a task has reviewed and ready to go into the game, from observed state. */

import type { Preview } from "../../api/contracts.ts";

export type PendingPartId = "plugins" | "images" | "rewraps";

export interface PendingPart {
  id: PendingPartId;
  title: string;
  /** The amount in words, such as "12 line rewraps". */
  summary: string;
}

/** Each task's work that is ready to apply. */
export type PendingInput = {
  /** Plugin files checked and ready to apply. */
  plugins: number;
  /** Images reviewed and ready to apply. */
  images: number;
  /** Line rewraps a current line width check would write. */
  rewraps: number;
};

const parts: Record<
  PendingPartId,
  { title: string; one: string; many?: string }
> = {
  plugins: { title: "Plugin files", one: "plugin file" },
  images: { title: "Images", one: "image" },
  rewraps: { title: "Rewrapped lines", one: "rewrap" },
};

/** The part a task applies, or null while it has nothing ready. */
export function pendingPart(
  id: PendingPartId,
  input: PendingInput,
): PendingPart | null {
  const count = input[id];
  if (!count) return null;
  const { title, one, many = one + "s" } = parts[id];
  return {
    id,
    title,
    summary: `${count.toLocaleString()} ${count === 1 ? one : many}`,
  };
}

/**
 * What a rewrap review would write, so a fresh preview taken just
 * before Apply can be compared with the reviewed one. It binds the exact
 * bytes by hash: the visible diff is cut off on large files.
 */
export const reviewSignature = (preview: Preview) =>
  JSON.stringify([
    preview.action,
    [...preview.paths].sort(),
    preview.rewrap?.previews.map((row) => [row.file_name, row.after]),
    preview.publication?.map((row) => [row.path, row.before, row.after]),
  ]);
